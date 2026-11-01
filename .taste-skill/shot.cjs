const { chromium } = require('playwright-core');
const exe = process.argv[2];
(async () => {
  const browser = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto('http://127.0.0.1:8331/index.html', { waitUntil: 'networkidle' });
  await page.screenshot({ path: '.taste-skill/poles_login_1440.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('http://127.0.0.1:8331/index.html', { waitUntil: 'networkidle' });
  await page.screenshot({ path: '.taste-skill/poles_login_390.png' });
  await browser.close();
  console.log('done');
})().catch(e => { console.error(e.message); process.exit(1); });
