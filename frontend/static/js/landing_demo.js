// Auto-play video on hover for landing page demo
document.addEventListener('DOMContentLoaded', () => {
  const demoCard = document.querySelector('.demo-card');
  if (!demoCard) return;

  const video = demoCard.querySelector('#demoVideo');
  
  demoCard.addEventListener('mouseenter', () => {
    // Gunakan promise untuk menghindari interrupt error
    video.play().catch(e => {
        if (e.name !== 'AbortError') console.error("Autoplay error:", e);
    });
  });

  demoCard.addEventListener('mouseleave', () => {
    // Reset video dengan aman
    video.pause();
    video.currentTime = 0;
  });
});
