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
  var interpPts = function(a, b, t) {
    var o = [];
    for (var i = 0; i < a.length; i++)
      o.push([lerp(a[i][0], b[i][0], t), lerp(a[i][1], b[i][1], t)]);
    return o;
  };
  var interpColor = function(c1, c2, t) {
    var h = function(h){return parseInt(h.slice(1),16);};
    var r=Math.round(lerp(h(c1)>>16,        h(c2)>>16,        t)),
        g=Math.round(lerp((h(c1)>>8)&255,   (h(c2)>>8)&255,   t)),
        b=Math.round(lerp(h(c1)&255,        h(c2)&255,        t));
    return '#'+[r,g,b].map(function(v){return v.toString(16).padStart(2,'0');}).join('');
  };
  var ptsToPath = function(pts) {
    var d = 'M '+pts[0][0].toFixed(2)+' '+pts[0][1].toFixed(2);
    for (var i = 1; i < pts.length; i++) d += ' L '+pts[i][0].toFixed(2)+' '+pts[i][1].toFixed(2);
    return d+' Z';
  };
  var draw = function(fi, ti, t) {
    var p = interpPts(SHAPES[fi].pts, SHAPES[ti].pts, t);
    PATH.setAttribute('d', ptsToPath(p));
    var col = interpColor(SHAPES[fi].color, SHAPES[ti].color, t);
    PATH.style.stroke = col;
    PATH.style.setProperty('--stroke-color', col);
  };
  var resetIdle = function() { IDLE_ACTIVE = false; segIdx = 0; nxtIdx = 0; tRatio = 0; };

  /* ── shape builders (N pts each, closed loop) ──────────────────── */
  var N = 80;

  // △ equilateral triangle pointing up
  function buildTri() {
    var s = 9, angs = [Math.PI*1.5, Math.PI*1.5+Math.PI*2/3, Math.PI*1.5+Math.PI*4/3];
    var out = [], step = N / 3;
    for (var i = 0; i < N; i++) {
      var fi = i / step, seg = Math.floor(fi), t = fi - seg;
      var a0 = angs[seg % 3], a1 = angs[(seg + 1) % 3];
      out.push([CX+s*Math.cos(a0)+t*(s*Math.cos(a1)-s*Math.cos(a0)),
                CY+s*Math.sin(a0)+t*(s*Math.sin(a1)-s*Math.sin(a0))]);
    }
    return out;
  }

  // ○ circle
  function buildCir() {
    var r = 8.5, out = [];
    for (var i = 0; i < N; i++) { var a = i/N*Math.PI*2-Math.PI/2;
      out.push([CX+r*Math.cos(a), CY+r*Math.sin(a)]); }
    return out;
  }

  // □ axis-aligned square
  function buildSq() {
    var s = 7.5, sides = [[-1,-1],[1,-1],[1,1],[-1,1]];
    var out = [], step = N / 4;
    for (var i = 0; i < N; i++) {
      var fi = i / step, seg = Math.floor(fi) % 4, t = fi - Math.floor(fi);
      out.push([lerp(CX+s*sides[seg][0], CX+s*sides[(seg+1)%4][0], t),
                lerp(CY+s*sides[seg][1], CY+s*sides[(seg+1)%4][1], t)]);
    }
    return out;
  }

  // ✕ real X — two diagonal thick strokes, traced as closed perimeter CW
  // 8 perimeter vertices → 10 pts per vertex × 8 = N segments
  // Order CW from top-left outer tip:
  //   tl-out → tl-in → tr-in → tr-out → br-out → br-in → bl-in → bl-out → close
  function buildCross() {
    var R = 9.2;   // tip distance from center
    var W = 3.0;   // half-width of stroke (controls thickness)
    // Perimeter points (CW): outer corner → inner corner → …
    // tl-out: top-left corner of upper-left arm   (upper-leftmost)
    // tl-in:  inner junction of upper-left arm    (where it meets horizontal midline)
    // tr-in:  inner junction of upper-right arm
    // tr-out: top-right corner of upper-right arm
    // br-out: bottom-right corner of lower-right arm
    // br-in:  inner junction of lower-right arm
    // bl-in:  inner junction of lower-left arm
    // bl-out: bottom-left corner of lower-left arm
    var P = [
      [CX - R*0.7, CY - R       ],   // 0 tl-out  (upper-left tip)
      [CX - W,     CY - W       ],   // 1 tl-in   (left of center, above midline)
      [CX + W,     CY - W       ],   // 2 tr-in   (right of center, above midline)
      [CX + R*0.7, CY - R       ],   // 3 tr-out  (upper-right tip)
      [CX + R*0.7, CY + R       ],   // 4 br-out  (lower-right tip)
      [CX + W,     CY + W       ],   // 5 br-in   (right of center, below midline)
      [CX - W,     CY + W       ],   // 6 bl-in   (left of center, below midline)
      [CX - R*0.7, CY + R       ],   // 7 bl-out  (lower-left tip)
    ];
    var out = [], segLen = N / P.length;
    for (var i = 0; i < N; i++) {
      var fi = i / segLen, seg = Math.floor(fi) % P.length, t = fi - Math.floor(fi);
      out.push([lerp(P[seg][0],  P[(seg+1)%P.length][0],  t),
                lerp(P[seg][1],  P[(seg+1)%P.length][1],  t)]);
    }
    return out;
  }

  var SHAPES = [
    { pts: buildTri(),   color: '#0066FF' },
    { pts: buildCir(),   color: '#FFD700' },
    { pts: buildCross(), color: '#FF4D4D' },
    { pts: buildSq(),    color: '#9dff8e' },
  ];

  /* ── config ─────────────────────────────────────────────────────── */
  var IDLE_MS   = 3000;
  var MORPH_SEC = 3.5;
  var FOLLOW    = 0.20;

  /* ── state ──────────────────────────────────────────────────────── */
  var mx = window.innerWidth/2, my = window.innerHeight/2;
  var cx = mx, cy = my;
  var idleSince = Infinity;
  var lastTick = performance.now();
  var segIdx = 0, nxtIdx = 1, tRatio = 0;
  var IDLE_ACTIVE = false;

  function tick(now) {
    var dt = (now - lastTick) / 1000;
    lastTick = now;
    cx = lerp(cx, mx, FOLLOW);
    cy = lerp(cy, my, FOLLOW);
    ELEM.style.transform = 'translate('+cx.toFixed(1)+'px,'+cy.toFixed(1)+'px)';

    var dur = Date.now() - idleSince;
    if (dur >= IDLE_MS && !IDLE_ACTIVE) { IDLE_ACTIVE = true; }
    else if (dur < IDLE_MS && IDLE_ACTIVE) { resetIdle(); }

    if (IDLE_ACTIVE) {
      tRatio += dt / MORPH_SEC;
      if (tRatio >= 1) {
        tRatio -= 1;
        segIdx = nxtIdx;
        nxtIdx = (nxtIdx + 1) % SHAPES.length;
      }
      draw(segIdx, nxtIdx, easeIO(tRatio));
    } else {
      draw(0, 0, 0);
    }
    requestAnimationFrame(tick);
  }

  /* ── events ─────────────────────────────────────────────────────── */
  function onActivity() { idleSince = Date.now(); }
  document.addEventListener('mousemove', function(e) { mx=e.clientX; my=e.clientY; onActivity(); });
  ['mousedown','mouseup','scroll'].forEach(function(ev){
    document.addEventListener(ev, onActivity, {passive:true});
  });
  var firstMove = false;
  document.addEventListener('mousemove', function onFirst() {
    if (!firstMove) {
      firstMove = true;
      ELEM.classList.add('visible');
      draw(0,0,0);
      requestAnimationFrame(tick);
    }
  });

})();
