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

  // ✕ real X — thick diagonal strokes, built from 4 circular arcs at inner corners
  // Each inner corner is smoothed with a quarter-circle arc of radius rArc
  // Outer corners remain sharp. Path closes without self-intersection.
  function buildCross() {
    var R  = 9.2;   // arm tip distance from center
    var hw = 2.8;   // half-width of each diagonal stroke (controls thickness)
    var rArc = 2.5; // radius of rounded inner corners

    // Build N points along 4 symmetric arcs (one per quadrant), each spanning PI/2 radians
    // Arc 1 (top-left quadrant): sweeps from left-tip direction (π) to top-tip direction (3π/2)
    //   Centered at the rounded inner corner near (-hw, -hw) offset by (CX, CY)
    var pts = [];
    var segPts = N / 4;
    for (var q = 0; q < 4; q++) {
      var cx0 = CX + (q < 2 ? -hw : hw);
      var cy0 = CY + (q % 2 === 0 ? -hw : hw);
      // Arc starts perpendicular to arm direction, sweeps PI/2 CW
      var startA = Math.PI       + q * Math.PI / 2;  // arc start tangent angle
      for (var j = 0; j < segPts; j++) {
        var t = j / segPts;
        var a  = startA + t * Math.PI / 2;            // sweep PI/2 CW per quadrant
        pts.push([cx0 + rArc * Math.cos(a), cy0 + rArc * Math.sin(a)]);
      }
    }
    return pts;
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
