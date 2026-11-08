(function () {
  'use strict';

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var gsapL = window.gsap;
  var hasGsap = !!(gsapL && window.ScrollTrigger);

  var lenis = null;
  if (!reduce && window.Lenis) {
    lenis = new Lenis({ lerp: 0.09, wheelMultiplier: 1 });
    if (hasGsap && gsapL.ticker) {
      gsapL.ticker.add(function (time) {
        lenis.raf(time * 1000);
      });
      gsapL.ticker.lagSmoothing(0);
    }
    if (hasGsap && window.ScrollTrigger) {
      lenis.on('scroll', ScrollTrigger.update);
    }
  }

  // Decorative-only entrance motion. All [data-reveal] elements are already
  // visible in CSS; GSAP merely slides them up from a small offset. It never
  // hides content — the first frame is the final resting position.
  if (hasGsap && !reduce) {
    gsapL.registerPlugin(ScrollTrigger);

    gsapL.from('.hero .hero-eyebrow', { y: 12, autoAlpha: 0, duration: 0.45, ease: 'power3.out', delay: 0.05 });
    gsapL.from('.hero h1 .line > span', { yPercent: 60, autoAlpha: 0, duration: 0.7, ease: 'power3.out', delay: 0.12, stagger: 0.06 });
    gsapL.from('.hero-lede', { y: 14, autoAlpha: 0, duration: 0.5, ease: 'power2.out', delay: 0.3 });
    gsapL.from('.hero-cta', { y: 14, autoAlpha: 0, duration: 0.5, ease: 'power2.out', delay: 0.38 });
    gsapL.from('.hero-meta', { autoAlpha: 0, duration: 0.5, delay: 0.46 });
    gsapL.from('.hero-visual', { y: 20, autoAlpha: 0, duration: 0.6, ease: 'power2.out', delay: 0.5 });

    gsapL.utils.toArray('[data-reveal]').forEach(function (el) {
      if (el.closest('.hero') || el.closest('.ld-nav')) return;
      gsapL.from(el, {
        y: 20,
        autoAlpha: 0,
        duration: 0.55,
        ease: 'power2.out',
        scrollTrigger: { trigger: el, start: 'top 90%', once: true }
      });
    });
  }

  window.addEventListener('beforeunload', function () {
    if (lenis && lenis.destroy) lenis.destroy();
    if (hasGsap && window.ScrollTrigger) {
      window.ScrollTrigger.getAll().forEach(function (st) { st.kill(); });
    }
  });
})();
