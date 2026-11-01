const { chromium } = require("playwright-core");
const exe = process.argv[2];
(async () => {
  const browser = await chromium.launch({ executablePath: exe, args: ["--no-sandbox"] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("http://127.0.0.1:8331/index.html", { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: ".taste-skill/tour_step1.png" });
  await page.click("#tourNext").catch(() => {});
  await page.waitForTimeout(500);
  await page.screenshot({ path: ".taste-skill/tour_step2.png" });
  await browser.close();
  console.log("done");
})().catch(e => { console.error(e.message); process.exit(1); });
