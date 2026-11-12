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
    const chips = container.querySelectorAll('.chip');
    const symbols = ['△', '▢', '○', '✕'];
    chips.forEach(c => c.style.opacity = '0');
    for (let i = 0; i < chips.length; i++) {
      chips[i].textContent = symbols[Math.floor(Math.random() * symbols.length)];
      chips[i].style.opacity = '1';
      chips[i].style.transition = 'opacity 0.2s ease';
      await new Promise(r => setTimeout(r, 80));
    }
  };

  const observer = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) {
      const demoChips = document.querySelectorAll('.demo-chips');
      demoChips.forEach((c, idx) => setTimeout(() => animateChips(c), idx * 1000));
      observer.disconnect();
    }
  }, { threshold: 0.5 });

  const demoSection = document.querySelector('.demo');
  if (demoSection) observer.observe(demoSection);
});
