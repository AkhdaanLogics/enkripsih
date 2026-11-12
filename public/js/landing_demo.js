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
});
