// Auto-play video on hover + animate chips (△○✕▢) for passkey demo card
document.addEventListener('DOMContentLoaded', () => {
  // Video card (first .demo-card in features grid)
  const demoCard = document.querySelector('.feature.demo-card');
  if (demoCard) {
    const video = demoCard.querySelector('#demoVideo');
    let loaded = false;
    demoCard.addEventListener('mouseenter', () => {
      if (!loaded) { video.load(); loaded = true; }
      video.play().catch(e => { if (e.name !== 'AbortError') console.error("Autoplay error:", e); });
    });
    demoCard.addEventListener('mouseleave', () => {
      video.pause();
      video.currentTime = 0;
    });
  }

  // Chip animation — challenge then response, looping forever
  const symbols = ['△', '▢', '○', '✕'];
  const colors = ['c1', 'c2', 'c3', 'c4'];
  const containers = [
    document.querySelector('#challenge-chips'),
    document.querySelector('#response-chips')
  ];
  if (containers[0] && containers[1]) {

    const animateSequence = async () => {
      while (true) {
        // Clear all
        containers.forEach(cont => {
          cont.querySelectorAll('.chip').forEach(c => {
            c.textContent = '';
            c.style.opacity = '0';
            c.className = 'chip';
          });
        });

        // Animate challenge chips one by one
        for (const box of containers[0].querySelectorAll('.chip-box')) {
          const chip = box.querySelector('.chip');
          const randIdx = Math.floor(Math.random() * symbols.length);
          chip.textContent = symbols[randIdx];
          chip.className = `chip ${colors[randIdx]}`;
          chip.style.opacity = '1';
          await new Promise(r => setTimeout(r, 150));
        }

        // Animate response chips one by one
        for (const box of containers[1].querySelectorAll('.chip-box')) {
          const chip = box.querySelector('.chip');
          const randIdx = Math.floor(Math.random() * symbols.length);
          chip.textContent = symbols[randIdx];
          chip.className = `chip ${colors[randIdx]}`;
          chip.style.opacity = '1';
          await new Promise(r => setTimeout(r, 100));
        }

        await new Promise(r => setTimeout(r, 3000));
      }
    };

    animateSequence();
  }
});
