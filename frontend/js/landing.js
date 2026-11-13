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

  // Hero-only entrance motion, plus feature-card stagger on scroll.
  // [data-reveal] stays fully visible without JS; GSAP only adds timing.
  if (hasGsap && !reduce) {
    gsapL.registerPlugin(ScrollTrigger);
    gsapL.to('.hero .hero-eyebrow', { opacity: 1, y: 0, duration: 0.4, ease: 'power3.out', delay: 0.05 });
    gsapL.to('.hero h1 .line > span', { opacity: 1, yPercent: 0, duration: 0.7, ease: 'power3.out', delay: 0.12, stagger: 0.06 });
    gsapL.to('.hero-lede', { opacity: 1, y: 0, duration: 0.5, ease: 'power2.out', delay: 0.3 });
    gsapL.to('.hero-cta', { opacity: 1, y: 0, duration: 0.5, ease: 'power2.out', delay: 0.38 });
    gsapL.to('.hero-meta', { opacity: 1, duration: 0.5, delay: 0.46 });

    // Feature cards stagger — each card rises slightly into place
    var featureCards = document.querySelectorAll('.features-grid .feature[data-reveal]');
    featureCards.forEach(function (card, i) {
      gsapL.from(card, {
        y: 28,
        opacity: 0,
        duration: 0.55,
        ease: 'power2.out',
        delay: 0.1 + i * 0.09,
        scrollTrigger: {
          trigger: card,
          start: 'top 88%',
          once: true,
        }
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
