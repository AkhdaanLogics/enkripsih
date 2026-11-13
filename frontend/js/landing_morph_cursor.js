(function () {
  'use strict';

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const ELEM = document.getElementById('morph-cursor');
  const PATH = document.getElementById('morph-path');
  if (!ELEM || !PATH) return;

  /* ── helpers ───────────────────────────────────────────────────── */
  var CX = 22, CY = 22;
  var lerp   = function(a, b, t) { return a + (b - a) * t; };
  var easeIO = function(t) { return t < 0.5 ? 2*t*t : 1 - Math.pow(-2*t+2, 2)/2; };
  var easeS  = function(t) { return t*t*(3-2*t); };
  var interpPts = function(a, b, t) {
    var o = [];
    for (var i = 0; i < a.length; i++)
      o.push([lerp(a[i][0], b[i][0], t), lerp(a[i][1], b[i][1], t)]);
    return o;
  };
  var interpColor = function(c1, c2, t) {
    var h = function(h){return parseInt(h.slice(1),16);};
    var r=Math.round(lerp(h(c1)>>16,  h(c2)>>16,  t)),
        g=Math.round(lerp((h(c1)>>8)&255,(h(c2)>>8)&255,t)),
        b=Math.round(lerp(h(c1)&255,    h(c2)&255,    t));
    return '#'+[r,g,b].map(function(v){return v.toString(16).padStart(2,'0');}).join('');
  };
  var ptsToPath = function(pts) {
    var d = 'M ' + pts[0][0].toFixed(2) + ' ' + pts[0][1].toFixed(2);
    for (var i = 1; i < pts.length; i++) d += ' L ' + pts[i][0].toFixed(2) + ' ' + pts[i][1].toFixed(2);
    return d + ' Z';
  };
  var draw = function(fi, ti, t) {
    var p = interpPts(SHAPES[fi].pts, SHAPES[ti].pts, t);
    PATH.setAttribute('d', ptsToPath(p));
    var col = interpColor(SHAPES[fi].color, SHAPES[ti].color, t);
    PATH.style.stroke = col;
    PATH.style.setProperty('--stroke-color', col);
  };
  var resetIdle = function() {
    // Snap back to solid triangle whenever user becomes active again
    IDLE_ACTIVE = false;
    segIdx = 0; nxtIdx = 0; tRatio = 0;
  };

  /* ── shape builders (N points each) ─────────────────────────────── */
  var N = 80;

  // △ triangle — 3 vertices
  function buildTri() {
    var s=9, angs=[Math.PI*1.5, Math.PI*1.5+Math.PI*2/3, Math.PI*1.5+Math.PI*4/3], out=[];
    for (var i=0; i<N; i++) {
      var f=i/N*3, seg=Math.floor(f), t=easeS(f-seg);
      out.push([lerp(CX+s*Math.cos(angs[seg%3]),CX+s*Math.cos(angs[(seg+1)%3]),t),
                lerp(CY+s*Math.sin(angs[seg%3]),CY+s*Math.sin(angs[(seg+1)%3]),t)]);
    }
    return out;
  }
  // ○ circle
  function buildCir() {
    var r=8.5, out=[];
    for (var i=0; i<N; i++) { var a=i/N*Math.PI*2-Math.PI/2; out.push([CX+r*Math.cos(a),CY+r*Math.sin(a)]); }
    return out;
  }
  // □ square — 4 vertices
  function buildSq() {
    var s=7.5, sides=[[-1,-1],[1,-1],[1,1],[-1,1]], out=[];
    for (var i=0; i<N; i++) {
      var f=i/N*4, seg=Math.floor(f)%4, t=easeS(f-Math.floor(f));
      out.push([lerp(CX+s*sides[seg][0],CX+s*sides[(seg+1)%4][0],t),
                lerp(CY+s*sides[seg][1],CY+s*sides[(seg+1)%4][1],t)]);
    }
    return out;
  }
  // ✕ proper cross — 8-point silhouette (top → top-right inner → right → bottom-right inner → bottom → left → left inner → top)
  function buildCross() {
    var L = 9, w = L * 0.42;
    // 8 outer vertices of the X silhouette, ordered clockwise
    var V = [
      [CX,       CY-L],   // 0 top tip
      [CX+w,     CY-w],   // 1 top-right inner corner
      [CX+L,     CY  ],   // 2 right tip
      [CX+w,     CY+w],   // 3 bottom-right inner corner
      [CX,       CY+L],   // 4 bottom tip
      [CX-w,     CY+w],   // 5 bottom-left inner corner
      [CX-L,     CY  ],   // 6 left tip
      [CX-w,     CY-w],   // 7 top-left inner corner
    ];
    var out = [];
    for (var i=0; i<N; i++) {
      var f=i/N*8, seg=Math.floor(f)%8, t=easeS(f-Math.floor(f));
      out.push([lerp(V[seg][0],V[(seg+1)%8][0],t), lerp(V[seg][1],V[(seg+1)%8][1],t)]);
    }
    return out;
  }
  // ◇ diamond — 4 vertices rotated square
  function buildDia() {
    var s=9.5, corners=[[0,-1],[1,0],[0,1],[-1,0]], out=[];
    for (var i=0; i<N; i++) {
      var f=i/N*4, seg=Math.floor(f)%4, t=easeS(f-Math.floor(f));
      out.push([lerp(CX+s*corners[seg][0],CX+s*corners[(seg+1)%4][0],t),
                lerp(CY+s*corners[seg][1],CY+s*corners[(seg+1)%4][1],t)]);
    }
    return out;
  }

  var SHAPES = [
    { pts: buildTri(),   color: '#0066FF' },
    { pts: buildCir(),   color: '#FFD700' },
    { pts: buildSq(),    color: '#9dff8e' },
    { pts: buildCross(), color: '#FF4D4D' },
    { pts: buildDia(),   color: '#c084fc' },
  ];

  /* ── config ─────────────────────────────────────────────────────── */
  var IDLE_MS   = 5000;
  var MORPH_SEC = 3.5;
  var FOLLOW    = 0.20;

  /* ── state ──────────────────────────────────────────────────────── */
  var mx = window.innerWidth/2, my = window.innerHeight/2;
  var cx = mx, cy = my;
  var visible = false;
  var idleSince = Infinity;
  var lastTick = performance.now();

  var segIdx = 0, nxtIdx = 1, tRatio = 0;
  var IDLE_ACTIVE = false;

  function tick(now) {
    var dt = (now - lastTick) / 1000;
    lastTick = now;

    cx = lerp(cx, mx, FOLLOW);
    cy = lerp(cy, my, FOLLOW);
    ELEM.style.transform = 'translate(' + cx.toFixed(1) + 'px,' + cy.toFixed(1) + 'px)';

    var dur = Date.now() - idleSince;

    if (dur >= IDLE_MS && !IDLE_ACTIVE) {
      // Enter idle mode — start morphing
      IDLE_ACTIVE = true;
    } else if (dur < IDLE_MS && IDLE_ACTIVE) {
      // User became active again — snap back to triangle
      resetIdle();
    }

    if (IDLE_ACTIVE) {
      tRatio += dt / MORPH_SEC;
      if (tRatio >= 1) {
        tRatio -= 1;
        segIdx = nxtIdx;
        nxtIdx = (nxtIdx + 1) % SHAPES.length;
      }
      draw(segIdx, nxtIdx, easeIO(tRatio));
    } else {
      draw(0, 0, 0); // solid triangle
    }

    requestAnimationFrame(tick);
  }

  /* ── event wiring ────────────────────────────────────────────────── */
  function onActivity() { idleSince = Date.now(); }
  document.addEventListener('mousemove', function(e) { mx = e.clientX; my = e.clientY; onActivity(); });
  ['mousedown','mouseup','scroll'].forEach(function(evt) {
    document.addEventListener(evt, onActivity, {passive:true});
  });

  var firstMove = false;
  document.addEventListener('mousemove', function onFirst() {
    if (!firstMove) {
      firstMove = true;
      ELEM.classList.add('visible');
      draw(0, 0, 0);
      requestAnimationFrame(tick);
    }
  });

})();
