// Auto-play video on hover for landing page demo
document.addEventListener('DOMContentLoaded', () => {
  const demoCard = document.querySelector('.demo-card');
  if (!demoCard) return;

  const video = demoCard.querySelector('#demoVideo');
  
  demoCard.addEventListener('mouseenter', () => {
    video.play().catch(e => console.error("Autoplay prevented:", e));
  });

  demoCard.addEventListener('mouseleave', () => {
    video.pause();
    video.currentTime = 0;
  });

  // Animate Chips
  const animateChips = async (container) => {
    const chips = Array.from(container.querySelectorAll('.chip'));
    const symbols = ['△', '▢', '○', '✕'];
    
    // Reset
    chips.forEach(c => {
      c.style.opacity = '0';
      c.style.transition = 'opacity 0.2s ease';
    });

    // Animate in
    for (let i = 0; i < chips.length; i++) {
      chips[i].textContent = symbols[Math.floor(Math.random() * symbols.length)];
      chips[i].style.opacity = '1';
      await new Promise(r => setTimeout(r, 80));
    }

    // Hold for 2s then fade out
    await new Promise(r => setTimeout(r, 2000));
    chips.forEach(c => c.style.opacity = '0');
  };

  const startLoop = async () => {
    const demoChips = document.querySelectorAll('.demo-chips');
    while (true) {
      for (const container of demoChips) {
        await animateChips(container);
      }
      await new Promise(r => setTimeout(r, 500));
    }
  };

  const observer = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) {
      startLoop();
      observer.disconnect();
    }
  }, { threshold: 0.5 });

  const demoSection = document.querySelector('.demo');
  if (demoSection) observer.observe(demoSection);
});
