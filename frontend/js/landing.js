(function () {
  'use strict';

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var hasGsap = !!(window.gsap && window.ScrollTrigger);
  var hasLenis = !!window.Lenis;

  // Add class so CSS intro states apply only when we intend to animate.
  if (hasGsap && !reduce) {
    document.body.classList.add('hero-anim');
  }

  // --- Lenis smooth scroll (single engine), skipped on reduced motion ---
  var lenis = null;
  if (hasLenis && !reduce) {
    lenis = new Lenis({ lerp: 0.09, wheelMultiplier: 1 });
    if (hasGsap && gsap.ticker) {
      gsap.ticker.add(function (time) {
        lenis.raf(time * 1000);
      });
      gsap.ticker.lagSmoothing(0);
    }
    if (window.ScrollTrigger) {
      lenis.on('scroll', ScrollTrigger.update);
      gsap.ticker.add(function () {
        lenis.raf(performance.now());
      });
    }
  }

  // --- Hero intro: line-mask + reveal ---
  if (hasGsap && !reduce) {
    gsap.registerPlugin(ScrollTrigger);

    var heroTl = gsap.timeline({ defaults: { ease: 'power3.out' } });
    heroTl
      .from('.hero .hero-eyebrow', { y: 14, autoAlpha: 0, duration: 0.5 }, 0)
      .from('.hero h1 .line > span', { yPercent: 110, duration: 0.9, stagger: 0.08 }, 0.1)
      .to('.hero h1 .line > span', { yPercent: 0, duration: 0.9, stagger: 0.08 }, 0.1)
      .from('.hero-lede', { y: 16, autoAlpha: 0, duration: 0.6 }, '>-0.3')
      .from('.hero-cta', { y: 16, autoAlpha: 0, duration: 0.6 }, '>-0.3')
      .from('.hero-meta', { autoAlpha: 0, duration: 0.6 }, '>-0.2')
      .from('.hero-visual', { y: 24, autoAlpha: 0, duration: 0.8 }, '>-0.4');

    // Stagger reveal for marked elements
    gsap.utils.toArray('[data-reveal].js-init').forEach(function (el) {
      // already handled above for hero; skip those in hero
      if (el.closest('.hero') || el.closest('.ld-nav')) return;
      el.classList.remove('js-init');
      gsap.from(el, {
        y: 24,
        autoAlpha: 0,
        duration: 0.7,
        ease: 'power2.out',
        scrollTrigger: { trigger: el, start: 'top 85%', once: true }
      });
    });
  } else {
    // No motion: ensure everything is visible (progressive enhancement).
    document.querySelectorAll('[data-reveal]').forEach(function (el) {
      el.classList.remove('js-init');
    });
  }

  // Seed reveal states on DOM ready, before CSS transition kicks in.
  document.querySelectorAll('[data-reveal]').forEach(function (el) {
    el.classList.add('js-init');
  });
  if (hasGsap && !reduce) {
    document.querySelectorAll('[data-reveal]').forEach(function (el) {
      if (el.closest('.hero') || el.closest('.ld-nav')) return;
      el.classList.remove('js-init');
    });
    requestAnimationFrame(function () {
      document.querySelectorAll('.hero [data-reveal], .ld-nav[data-reveal]').forEach(function (el) {
        el.classList.add('js-in');
      });
    });
  } else {
    requestAnimationFrame(function () {
      document.querySelectorAll('[data-reveal]').forEach(function (el) {
        el.classList.add('js-in');
      });
    });
  }

  // --- Nav scroll shadow ---
  var nav = document.querySelector('.ld-nav');
  var onScroll = function () {
    if (!nav) return;
    if (lenis) {
      nav.style.transform = 'translateY(0)';
    }
  };
  window.addEventListener('scroll', onScroll, { passive: true });

  // Cleanup on unload
  window.addEventListener('beforeunload', function () {
    if (lenis && lenis.destroy) lenis.destroy();
    if (hasGsap && ScrollTrigger) ScrollTrigger.getAll().forEach(function (st) { st.kill(); });
  });
})();
