(function () {
  'use strict';

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var hasGsap = !!(window.gsap && window.ScrollTrigger);

  // Progressive enhancement: only mark [data-reveal] as hidden when we will
  // actually animate it. Otherwise the content stays fully visible (no-JS /
  // reduced-motion safe).
  if (hasGsap && !reduce) {
    gsap.registerPlugin(ScrollTrigger);
    document.querySelectorAll('[data-reveal]').forEach(function (el) {
      el.classList.add('js-init');
    });
  }

  // --- Lenis smooth scroll (single engine), skipped on reduced motion ---
  var lenis = null;
  var hasLenis = !!window.Lenis;
  if (hasLenis && !reduce) {
    lenis = new Lenis({ lerp: 0.09, wheelMultiplier: 1 });
    if (hasGsap && window.gsap && window.gsap.ticker) {
      window.gsap.ticker.add(function (time) {
        lenis.raf(time * 1000);
      });
      window.gsap.ticker.lagSmoothing(0);
    }
    if (hasGsap && window.ScrollTrigger) {
      lenis.on('scroll', ScrollTrigger.update);
    }
  }

  if (hasGsap && !reduce) {
    var gsapL = window.gsap;

    // Hero intro: line-mask reveal + fade-up. gsap.from auto-reverts to the
    // element's natural (visible) state, so nothing is left hidden.
    var heroTl = gsapL.timeline({ defaults: { ease: 'power3.out' } });
    heroTl
      .from('.hero .hero-eyebrow', { y: 14, autoAlpha: 0, duration: 0.5 }, 0)
      .from('.hero h1 .line > span', { yPercent: 110, duration: 0.9, stagger: 0.08 }, 0.1)
      .from('.hero-lede', { y: 16, autoAlpha: 0, duration: 0.6 }, '>-0.3')
      .from('.hero-cta', { y: 16, autoAlpha: 0, duration: 0.6 }, '>-0.3')
      .from('.hero-meta', { autoAlpha: 0, duration: 0.6 }, '>-0.2')
      .from('.hero-visual', { y: 24, autoAlpha: 0, duration: 0.8 }, '>-0.4');

    // Reveals outside the hero: scroll-triggered fade-up.
    gsapL.utils.toArray('[data-reveal]').forEach(function (el) {
      if (el.closest('.hero') || el.closest('.ld-nav')) return;
      gsapL.from(el, {
        y: 24,
        autoAlpha: 0,
        duration: 0.7,
        ease: 'power2.out',
        scrollTrigger: { trigger: el, start: 'top 85%', once: true }
      });
    });
  }

  // Cleanup on unload
  window.addEventListener('beforeunload', function () {
    if (lenis && lenis.destroy) lenis.destroy();
    if (hasGsap && window.ScrollTrigger) {
      window.ScrollTrigger.getAll().forEach(function (st) { st.kill(); });
    }
  });
})();
