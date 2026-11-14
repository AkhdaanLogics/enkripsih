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

    // Hero-only entrance motion — purpose: guide attention to headline first
    if (hasGsap && !reduce) {
      gsapL.registerPlugin(ScrollTrigger);
      gsapL.to('.hero .hero-eyebrow', { opacity: 1, y: 0, duration: 0.35, ease: 'power2.out', delay: 0.05 });
      gsapL.to('.hero h1 .line > span', { opacity: 1, yPercent: 0, duration: 0.6, ease: 'power3.out', delay: 0.1, stagger: 0.07 });
      gsapL.to('.hero-lede', { opacity: 1, y: 0, duration: 0.45, ease: 'power2.out', delay: 0.28 });
      gsapL.to('.hero-cta', { opacity: 1, y: 0, duration: 0.45, ease: 'power2.out', delay: 0.36 });
      gsapL.to('.hero-meta', { opacity: 1, duration: 0.4, delay: 0.44 });

      // Feature cards — purpose: reveal hierarchy as user scrolls; stagger keeps rhythm
      var featureCards = document.querySelectorAll('.features-grid .feature[data-reveal]');
      featureCards.forEach(function (card, i) {
        var d = 0.08 + i * 0.07;
        if (i >= 2) d += 0.06; // extra delay for bottom-row cards
        gsapL.from(card, {
          y: 22,
          opacity: 0,
          duration: 0.5,
          ease: 'power2.out',
          delay: d,
          scrollTrigger: { trigger: card, start: 'top 88%', once: true }
        });
      });
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
