(function () {
  'use strict';

  var motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  var hasFinePointer = window.matchMedia('(pointer: fine)').matches;
  if (!hasFinePointer) return;

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

  // ✕ real X — build "+" then rotate 45°, resampled to N even points
  function buildCross() {
    var L = 8.5;   // arm length from center
    var h = 2.2;   // half-width of each stroke

    // 12 perimeter vertices of "+" in CW order
    var plus = [
      [-h, -L], [ h, -L], [ h, -h], [ L, -h],
      [ L,  h], [ h,  h], [ h,  L], [-h,  L],
      [-h,  h], [-L,  h], [-L, -h], [-h, -h]
    ];

    // Rotate 45° → becomes ✕
    var c = Math.cos(Math.PI / 4), s = Math.sin(Math.PI / 4);
    var poly = plus.map(function(p) {
      return [CX + p[0] * c - p[1] * s, CY + p[0] * s + p[1] * c];
    });

    // Arc-length resample to N even points
    var lens = [], total = 0;
    for (var i = 0; i < poly.length; i++) {
      var a = poly[i], b = poly[(i + 1) % poly.length];
      var d = Math.hypot(b[0] - a[0], b[1] - a[1]);
      lens.push(d); total += d;
    }
    var out = [], seg = 0, acc = 0;
    for (var k = 0; k < N; k++) {
      var target = k / N * total;
      while (acc + lens[seg] < target) { acc += lens[seg]; seg++; }
      var t = (target - acc) / lens[seg];
      var p0 = poly[seg], p1 = poly[(seg + 1) % poly.length];
      out.push([lerp(p0[0], p1[0], t), lerp(p0[1], p1[1], t)]);
    }
    return out;
  }

  var SHAPES = [
    { pts: buildTri(),   color: '#0066FF' },
    { pts: buildCir(),   color: '#FFD700' },
    { pts: buildCross(), color: '#FF4D4D' },
    { pts: buildSq(),    color: '#9dff8e' },
  ];

  var FOLLOW = 0.20;
  var IDLE_MS = 3000;
  var MORPH_MS = 160;
  var IDLE_MORPH_MS = 3500;
  var SCROLL_HOLD_MS = 220;
  var CLICK_HOLD_MS = 180;
  var mx = window.innerWidth/2, my = window.innerHeight/2;
  var cx = mx, cy = my;
  var lastActivity = performance.now();
  var transitionStart = lastActivity;
  var transitionDuration = MORPH_MS;
  var fromPts = SHAPES[0].pts;
  var fromColor = SHAPES[0].color;
  var targetShape = SHAPES[0];
  var scrollUntil = 0;
  var clickUntil = 0;
  var pointerDown = false;
  var running = false;
  var motionAllowed = !motionPreference.matches;
  var idleSegment = -1;

  function draw(now) {
    var t = Math.min((now - transitionStart) / transitionDuration, 1);
    var eased = easeIO(t);
    var points = interpPts(fromPts, targetShape.pts, eased);
    var color = interpColor(fromColor, targetShape.color, eased);
    PATH.setAttribute('d', ptsToPath(points));
    PATH.style.stroke = color;
    PATH.style.setProperty('--stroke-color', color);

    if (t >= 1) {
      fromPts = targetShape.pts;
      fromColor = targetShape.color;
    }
  }

  function setShape(index, now) {
    if (targetShape === SHAPES[index] && transitionDuration === MORPH_MS) return;
    var t = Math.min((now - transitionStart) / transitionDuration, 1);
    var eased = easeIO(t);
    fromPts = interpPts(fromPts, targetShape.pts, eased);
    fromColor = interpColor(fromColor, targetShape.color, eased);
    targetShape = SHAPES[index];
    transitionStart = now;
    transitionDuration = MORPH_MS;
  }

  function markActivity() {
    lastActivity = performance.now();
    idleSegment = -1;
  }

  function syncShape(now) {
    if (pointerDown || now < clickUntil) {
      setShape(2, now);
      return;
    }
    if (now < scrollUntil) {
      setShape(1, now);
      return;
    }

    var idleDuration = now - lastActivity;
    if (idleDuration < IDLE_MS) {
      idleSegment = -1;
      setShape(0, now);
      return;
    }

    var elapsed = idleDuration - IDLE_MS;
    var segment = Math.floor(elapsed / IDLE_MORPH_MS);
    if (segment !== idleSegment) {
      var fromIndex = segment % SHAPES.length;
      fromPts = SHAPES[fromIndex].pts;
      fromColor = SHAPES[fromIndex].color;
      targetShape = SHAPES[(fromIndex + 1) % SHAPES.length];
      transitionStart = lastActivity + IDLE_MS + segment * IDLE_MORPH_MS;
      transitionDuration = IDLE_MORPH_MS;
      idleSegment = segment;
    }
  }

  function tick(now) {
    cx = lerp(cx, mx, FOLLOW);
    cy = lerp(cy, my, FOLLOW);
    ELEM.style.transform = 'translate('+cx.toFixed(1)+'px,'+cy.toFixed(1)+'px)';
    syncShape(now);
    draw(now);
    if (running) requestAnimationFrame(tick);
  }

  function start() {
    if (running || !motionAllowed) return;
    running = true;
    document.body.classList.add('has-morph-cursor');
    ELEM.classList.add('visible');
    requestAnimationFrame(tick);
  }

  document.addEventListener('pointermove', function(e) {
    if (!motionAllowed || e.pointerType !== 'mouse') return;
    mx = e.clientX;
    my = e.clientY;
    markActivity();
    start();
  }, {passive:true});

  document.addEventListener('pointerdown', function(e) {
    if (!motionAllowed || e.pointerType !== 'mouse' || e.button !== 0) return;
    mx = e.clientX;
    my = e.clientY;
    pointerDown = true;
    markActivity();
    start();
  }, {passive:true});

  window.addEventListener('pointerup', function(e) {
    if (e.pointerType !== 'mouse' || !pointerDown) return;
    mx = e.clientX;
    my = e.clientY;
    pointerDown = false;
    clickUntil = performance.now() + CLICK_HOLD_MS;
    markActivity();
  }, {passive:true});

  window.addEventListener('pointercancel', function() {
    pointerDown = false;
    clickUntil = 0;
    markActivity();
  }, {passive:true});

  window.addEventListener('blur', function() {
    pointerDown = false;
    clickUntil = 0;
    markActivity();
  });

  window.addEventListener('scroll', function() {
    scrollUntil = performance.now() + SCROLL_HOLD_MS;
    markActivity();
  }, {passive:true});

  document.addEventListener('mouseleave', function() {
    pointerDown = false;
    clickUntil = 0;
    ELEM.classList.remove('visible');
    document.body.classList.remove('has-morph-cursor');
    running = false;
  });

  motionPreference.addEventListener('change', function(e) {
    motionAllowed = !e.matches;
    if (!motionAllowed) {
      pointerDown = false;
      clickUntil = 0;
      ELEM.classList.remove('visible');
      document.body.classList.remove('has-morph-cursor');
      running = false;
    }
  });

})();
