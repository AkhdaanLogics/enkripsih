(function () {
  'use strict';

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const ELEM = document.getElementById('morph-cursor');
  const PATH = document.getElementById('morph-path');
  if (!ELEM || !PATH) return;

  const CX = 22, CY = 22;

  function lerp(a, b, t) { return a + (b - a) * t; }
  function easeInOut(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }
  function easeSmooth(t) { return t * t * (3 - 2 * t); }

  function buildTriangle(pts) {
    var s = 9, r = 3;
    var angles = [Math.PI * 1.5, Math.PI * 1.5 + Math.PI * 2 / 3, Math.PI * 1.5 + Math.PI * 4 / 3];
    var out = [];
    for (var i = 0; i < pts; i++) {
      var frac = i / pts * 3;
      var seg = Math.floor(frac);
      var t = frac - seg;
      t = easeSmooth(t);
      var a0 = angles[seg % 3], a1 = angles[(seg + 1) % 3];
      var x = lerp(CX + s * Math.cos(a0), CX + s * Math.cos(a1), t);
      var y = lerp(CY + s * Math.sin(a0), CY + s * Math.sin(a1), t);
      out.push([x, y]);
    }
    return out;
  }

  function buildCircle(pts) {
    var r = 8.5;
    var out = [];
    for (var i = 0; i < pts; i++) {
      var a = (i / pts) * Math.PI * 2 - Math.PI / 2;
      out.push([CX + r * Math.cos(a), CY + r * Math.sin(a)]);
    }
    return out;
  }

  function buildSquare(pts) {
    var s = 7.5;
    var sides = [[-1,-1],[1,-1],[1,1],[-1,1]];
    var out = [];
    for (var i = 0; i < pts; i++) {
      var frac = i / pts * 4;
      var seg = Math.floor(frac) % 4;
      var t = frac - Math.floor(frac);
      t = easeSmooth(t);
      var p0 = sides[seg], p1 = sides[(seg + 1) % 4];
      out.push([lerp(CX + s * p0[0], CX + s * p1[0], t), lerp(CY + s * p0[1], CY + s * p1[1], t)]);
    }
    return out;
  }

  function buildDiamond(pts) {
    var s = 9.5;
    var corners = [[0,-1],[1,0],[0,1],[-1,0]];
    var out = [];
    for (var i = 0; i < pts; i++) {
      var frac = i / pts * 4;
      var seg = Math.floor(frac) % 4;
      var t = frac - Math.floor(frac);
      t = easeSmooth(t);
      var p0 = corners[seg], p1 = corners[(seg + 1) % 4];
      out.push([lerp(CX + s * p0[0], CX + s * p1[0], t), lerp(CY + s * p0[1], CY + s * p1[1], t)]);
    }
    return out;
  }

  var PTS = 40;
  var SHAPES = [
    { pts: buildTriangle(PTS),  color: '#0066FF' },
    { pts: buildCircle(PTS),   color: '#FFD700' },
    { pts: buildSquare(PTS),   color: '#9dff8e' },
    { pts: buildDiamond(PTS),  color: '#FF4D4D' },
  ];

  // Build initial path string from first shape
  function ptsToPath(pts) {
    var d = 'M ' + pts[0][0].toFixed(2) + ' ' + pts[0][1].toFixed(2);
    for (var i = 1; i < pts.length; i++) {
      d += ' L ' + pts[i][0].toFixed(2) + ' ' + pts[i][1].toFixed(2);
    }
    return d + ' Z';
  }

  function interpPts(a, b, t) {
    var out = [];
    for (var i = 0; i < a.length; i++) {
      out.push([lerp(a[i][0], b[i][0], t), lerp(a[i][1], b[i][1], t)]);
    }
    return out;
  }

  function interpColor(c1, c2, t) {
    var r1 = parseInt(c1.slice(1, 3), 16), g1 = parseInt(c1.slice(3, 5), 16), b1 = parseInt(c1.slice(5, 7), 16);
    var r2 = parseInt(c2.slice(1, 3), 16), g2 = parseInt(c2.slice(3, 5), 16), b2 = parseInt(c2.slice(5, 7), 16);
    var r = Math.round(lerp(r1, r2, t)), g = Math.round(lerp(g1, g2, t)), b = Math.round(lerp(b1, b2, t));
    return '#' + [r, g, b].map(function (v) { return v.toString(16).padStart(2, '0'); }).join('');
  }

  // Cycle timing (seconds per full transition)
  var CYCLE = 3.0;

  var mouseX = window.innerWidth / 2, mouseY = window.innerHeight / 2;
  var curX = mouseX, curY = mouseY;
  var stateT = 0;       // 0..1 within current segment
  var segIdx = 0;        // which shape we're coming FROM
  var nextIdx = 1;       // which shape we're going TO
  var startTime = performance.now();
  var lastTime = startTime;

  function morph(now) {
    var dt = (now - lastTime) / 1000;
    lastTime = now;
    stateT += dt / CYCLE;

    if (stateT >= 1) {
      stateT -= 1;
      segIdx = nextIdx;
      nextIdx = (nextIdx + 1) % SHAPES.length;
    }

    var t = easeInOut(stateT);
    var from = SHAPES[segIdx], to = SHAPES[nextIdx];
    var interp = interpPts(from.pts, to.pts, t);
    var col = interpColor(from.color, to.color, t);

    PATH.setAttribute('d', ptsToPath(interp));
    PATH.style.stroke = col;
    PATH.style.setProperty('--stroke-color', col);

    // Smooth follow
    curX = lerp(curX, mouseX, 0.18);
    curY = lerp(curY, mouseY, 0.18);
    ELEM.style.transform = 'translate(' + curX.toFixed(1) + 'px,' + curY.toFixed(1) + 'px)';

    requestAnimationFrame(morph);
  }

  document.addEventListener('mousemove', function (e) {
    mouseX = e.clientX;
    mouseY = e.clientY;
  });

  // Hide until first interaction, then fade in
  var firstMove = false;
  document.addEventListener('mousemove', function onFirst() {
    if (!firstMove) {
      firstMove = true;
      document.removeEventListener('mousemove', onFirst);
      ELEM.classList.add('visible');
      requestAnimationFrame(morph);
    }
  });

})();
