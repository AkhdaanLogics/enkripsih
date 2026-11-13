// Auto-play video on hover for landing page demo
document.addEventListener('DOMContentLoaded', () => {
  const demoCard = document.querySelector('.demo-card');
  if (!demoCard) return;

  const video = demoCard.querySelector('#demoVideo');
  let loaded = false;

  demoCard.addEventListener('mouseenter', () => {
    if (!loaded) {
      video.load();
      loaded = true;
    }
    video.play().catch(e => {
        if (e.name !== 'AbortError') console.error("Autoplay error:", e);
    });
  });

  demoCard.addEventListener('mouseleave', () => {
    video.pause();
    video.currentTime = 0;
  });
});
