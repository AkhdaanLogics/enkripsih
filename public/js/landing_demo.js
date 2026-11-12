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
  const animateSequence = async () => {
    const symbols = ['△', '▢', '○', '✕'];
    const containers = [
      document.querySelector('#challenge-chips'),
      document.querySelector('#response-chips')
    ];

    while (true) {
      // Clear all
      containers.forEach(cont => {
        cont.querySelectorAll('.chip').forEach(c => {
          c.textContent = '';
          c.style.opacity = '0';
        });
      });

      // Animate Challenge
      for (const box of containers[0].querySelectorAll('.chip-box')) {
        const chip = box.querySelector('.chip');
        chip.textContent = symbols[Math.floor(Math.random() * symbols.length)];
        chip.style.opacity = '1';
        await new Promise(r => setTimeout(r, 150));
      }

      // Animate Response
      for (const box of containers[1].querySelectorAll('.chip-box')) {
        const chip = box.querySelector('.chip');
        chip.textContent = symbols[Math.floor(Math.random() * symbols.length)];
        chip.style.opacity = '1';
        await new Promise(r => setTimeout(r, 100));
      }

      await new Promise(r => setTimeout(r, 3000));
    }
  };

  const observer = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) {
      animateSequence();
      observer.disconnect();
    }
  }, { threshold: 0.5 });

  const demoSection = document.querySelector('.demo');
  if (demoSection) observer.observe(demoSection);
});
