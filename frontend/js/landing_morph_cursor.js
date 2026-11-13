(function () {
  'use strict';

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const ELEM = document.getElementById('morph-cursor');
  const PATH = document.getElementById('morph-path');
  if (!ELEM || !PATH) return;

  /* ── helpers ───────────────────────────────────────────────────── */
  var CX = 22, CY = 22;
  var lerp = function(a, b, t) { return a + (b - a) * t; };
  var easeIO = function(t) { return t < 0.5 ? 2*t*t : 1 - Math.pow(-2*t+2, 2)/2; };
  var easeS  = function(t) { return t*t*(3-2*t); };
  var ptsToPath = function(pts) {
    var d = 'M ' + pts[0][0].toFixed(2) + ' ' + pts[0][1].toFixed(2);
    for (var i = 1; i < pts.length; i++) d += ' L ' + pts[i][0].toFixed(2) + ' ' + pts[i][1].toFixed(2);
    return d + ' Z';
  };
  var interpPts = function(a, b, t) {
    var o = [];
    for (var i = 0; i < a.length; i++) o.push([lerp(a[i][0],b[i][0],t), lerp(a[i][1],b[i][1],t)]);
    return o;
  };
  var interpColor = function(c1, c2, t) {
    var hex = function(h){return parseInt(h.slice(1),16);};
    var r=Math.round(lerp(hex(c1)>>16,(hex(c2)>>16),t)), g=Math.round(lerp((hex(c1)>>8)&255,(hex(c2)>>8)&255,t)), b=Math.round(lerp(hex(c1)&255,hex(c2)&255,t));
    return '#'+[r,g,b].map(function(v){return v.toString(16).padStart(2,'0');}).join('');
  };
  var draw = function(fi, ti, t) {
    var p = interpPts(SHAPES[fi].pts, SHAPES[ti].pts, t);
    PATH.setAttribute('d', ptsToPath(p));
    var col = interpColor(SHAPES[fi].color, SHAPES[ti].color, t);
    PATH.style.stroke = col;
    PATH.style.setProperty('--stroke-color', col);
  };

  /* ── shape builders (64 points each) ──────────────────────────── */
  var PTS = 64;

  // △ triangle — 3 vertices evenly spaced around circle
  function buildTri() {
    var s=9, angs=[Math.PI*1.5, Math.PI*1.5+Math.PI*2/3, Math.PI*1.5+Math.PI*4/3], out=[];
    for (var i=0; i<PTS; i++) {
      var f=i/PTS*3, seg=Math.floor(f), t=easeS(f-seg);
      out.push([lerp(CX+s*Math.cos(angs[seg%3]),CX+s*Math.cos(angs[(seg+1)%3]),t), lerp(CY+s*Math.sin(angs[seg%3]),CY+s*Math.sin(angs[(seg+1)%3]),t)]);
    }
    return out;
  }
  // ○ circle
  function buildCir() {
    var r=8.5, out=[];
    for (var i=0; i<PTS; i++) { var a=i/PTS*Math.PI*2-Math.PI/2; out.push([CX+r*Math.cos(a),CY+r*Math.sin(a)]); }
    return out;
  }
  // □ square (axis-aligned)
  function buildSq() {
    var s=7.5, sides=[[-1,-1],[1,-1],[1,1],[-1,1]], out=[];
    for (var i=0; i<PTS; i++) {
      var f=i/PTS*4, seg=Math.floor(f)%4, t=easeS(f-Math.floor(f));
      out.push([lerp(CX+s*sides[seg][0],CX+s*sides[(seg+1)%4][0],t), lerp(CY+s*sides[seg][1],CY+s*sides[(seg+1)%4][1],t)]);
    }
    return out;
  }
  // ✕ cross — thick diagonal strokes as closed polygon
  function buildCross() {
    var sz=7.5, hw=2.2;
    var pts=[
      [CX-sz,CY-sz],[CX-hw,CY-sz*0.5],[CX+hw,CY-sz*0.5],[CX+sz,CY-sz],   // top arm
      [CX+sz*0.5,CY-hw],[CX+sz*0.5,CY+hw],[CX+sz,CY+sz],                   // right arm
      [CX+hw,CY+sz*0.5],[CX-hw,CY+sz*0.5],[CX-sz,CY+sz],                   // bottom arm
      [CX-sz*0.5,CY+hw],[CX-sz*0.5,CY-hw]                                  // left arm
    ];
    var out=[], n=pts.length;
    for (var i=0; i<PTS; i++) {
      var f=i/PTS*n, seg=Math.floor(f)%n, t=f-Math.floor(f);
      out.push([lerp(pts[seg][0],pts[(seg+1)%n][0],t), lerp(pts[seg][1],pts[(seg+1)%n][1],t)]);
    }
    return out;
  }
  // ◇ diamond — rotated square
  function buildDia() {
    var s=9.5, corners=[[0,-1],[1,0],[0,1],[-1,0]], out=[];
    for (var i=0; i<PTS; i++) {
      var f=i/PTS*4, seg=Math.floor(f)%4, t=easeS(f-Math.floor(f));
      out.push([lerp(CX+s*corners[seg][0],CX+s*corners[(seg+1)%4][0],t), lerp(CY+s*corners[seg][1],CY+s*corners[(seg+1)%4][1],t)]);
    }
    return out;
  }

  var SHAPES = [
    { pts: buildTri(),  color: '#0066FF' },
    { pts: buildCir(),  color: '#FFD700' },
    { pts: buildSq(),   color: '#9dff8e' },
    { pts: buildCross(),color: '#FF4D4D' },
    { pts: buildDia(),  color: '#c084fc' },
  ];

  /* ── config ─────────────────────────────────────────────────────── */
  var IDLE_MS    = 5000;   // morph starts after this long of no movement
  var MORPH_SEC  = 3.5;    // seconds per shape→shape transition
  var FOLLOW     = 0.20;   // mouse-follow lag

  /* ── state ──────────────────────────────────────────────────────── */
  var mx = window.innerWidth/2, my = window.innerHeight/2;
  var cx = mx, cy = my;
  var visible = false;
  var idleSince = Infinity;
  var lastTick = performance.now();

  // Morph cycling vars
  var segIdx = 0, nxtIdx = 1, tRatio = 0;

  // When we exit idle mode, freeze here and re-enter idle later
  var holdSeg = 0, holdNxt = 1, holdT = 0;

  function enterIdle() {
    // Snapshot current state as holding point; full morph starts fresh
    segIdx = holdSeg;
    nxtIdx = holdNxt;
    tRatio = holdT;
  }

  function tick(now) {
    var dt = (now - lastTick) / 1000;
    lastTick = now;

    // Mouse follow
    cx = lerp(cx, mx, FOLLOW);
    cy = lerp(cy, my, FOLLOW);
    ELEM.style.transform = 'translate(' + cx.toFixed(1) + 'px,' + cy.toFixed(1) + 'px)';

    var idleDuration = Date.now() - idleSince;
    var isIdleMode = idleDuration >= IDLE_MS;

    if (isIdleMode) {
      // Smoothly ramp opacity/fade-in effect handled by CSS class
      tRatio += dt / MORPH_SEC;
      if (tRatio >= 1) {
        tRatio -= 1;
        holdSeg = segIdx; holdNxt = nxtIdx; holdT = 1;
        segIdx = nxtIdx;
        nxtIdx = (nxtIdx + 1) % SHAPES.length;
      }
      draw(segIdx, nxtIdx, easeIO(tRatio));
    } else {
      // Active: hold the frozen interpolation
      draw(holdSeg, holdNxt, holdT);
    }

    requestAnimationFrame(tick);
  }

  /* ── event wiring ────────────────────────────────────────────────── */
  document.addEventListener('mousemove', function(e) {
    mx = e.clientX; my = e.clientY;
    idleSince = Date.now();
  });
  ['mousedown','mouseup','scroll'].forEach(function(evt) {
    document.addEventListener(evt, function(){ idleSince = Date.now(); }, {passive:true});
  });

  // Reveal on first move
  var firstMove = false;
  document.addEventListener('mousemove', function onFirst() {
    if (!firstMove) {
      firstMove = true;
      ELEM.classList.add('visible');
      draw(0, 1, 0);
      requestAnimationFrame(tick);
    }
  });

})();
