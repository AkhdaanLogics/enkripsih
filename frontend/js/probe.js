const { chromium } = require("playwright");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

function parseEnv(filePath) {
  const env = {};
  if (!fs.existsSync(filePath)) return env;
  const lines = fs.readFileSync(filePath, "utf8").split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const idx = trimmed.indexOf("=");
    if (idx > 0) {
      const k = trimmed.slice(0, idx).trim();
      const v = trimmed.slice(idx + 1).trim();
      env[k] = v;
    }
  }
  return env;
}

const fileEnv = parseEnv(path.join(__dirname, "../../.env"));

const PORT = 8099;
const OUT = "C:\\Users\\LENOVO\\AppData\\Local\\Temp\\opencode\\cdp_out";
fs.mkdirSync(OUT, { recursive: true });
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

(async () => {
  console.log("Starting backend...");
  const py = "E:\\enkripsih\\.venv\\Scripts\\python.exe";
  const backend = spawn(py, ["-m", "uvicorn", "backend.main:app", "--port", String(PORT), "--host", "127.0.0.1"], {
    cwd: "E:\\enkripsih",
    env: { ...process.env, ...fileEnv },
    stdio: ["ignore", "pipe", "pipe"],
  });

  backend.stderr.on("data", d => {
    // uncomment to debug backend: console.log("BE:", d.toString());
  });

  let health = false;
  console.log("Waiting for backend startup (Neon DB connection takes ~12s)...");
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/api/health`);
      if (r.status === 200) { health = true; break; }
    } catch {}
    await sleep(500);
  }
  console.log("backend health:", health);

  // login via API to obtain session cookie
  let sessionCookie = null;
  try {
    const login = await fetch(`http://127.0.0.1:${PORT}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: process.env.ENKRIPSIH_PASSWORD || "npg_z25gJGferdMK" }),
    });
    const setCookie = login.headers.get("set-cookie") || "";
    console.log("login status:", login.status);
    const m = setCookie.match(/enkripsih_session=([^;]+)/);
    if (m) sessionCookie = m[1];
  } catch (e) {
    console.log("login err", e.message);
  }

  const browser = await chromium.launchPersistentContext(
    "C:\\Users\\LENOVO\\AppData\\Local\\Temp\\opencode\\pw_profile",
    {
      headless: true,
      executablePath: CHROME,
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 1,
    }
  );

  const context = browser;
  const page = context.pages()[0] || await context.newPage();

  if (sessionCookie) {
    await context.addCookies([{
      name: "enkripsih_session",
      value: sessionCookie,
      domain: "127.0.0.1",
      path: "/",
      url: `http://127.0.0.1:${PORT}`,
    }]);
  }

  await page.goto(`http://127.0.0.1:${PORT}/?a=1`, { waitUntil: "domcontentloaded", timeout: 20000 });
  await sleep(1500);

  const report = {};
  report.viewport = await page.evaluate(() => ({ w: innerWidth, h: innerHeight }));

  report.sidebar = await page.evaluate(() => {
    const el = document.querySelector(".app-sidebar");
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {
      top: r.top, bottom: r.bottom, height: r.height,
      position: cs.position, paddingTop: cs.paddingTop,
      topCss: cs.top, alignSelf: cs.alignSelf,
    };
  });

  report.sentList = await page.evaluate(() => {
    const el = document.getElementById("commanderSentList");
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {
      top: r.top, bottom: r.bottom, height: r.height,
      maxHeight: cs.maxHeight, overflowY: cs.overflowY,
      clientHeight: el.clientHeight, scrollHeight: el.scrollHeight,
      children: el.children.length,
      clipped: el.scrollHeight > el.clientHeight,
    };
  });

  await page.screenshot({ path: path.join(OUT, "1_initial_100.jpg"), type: "jpeg", quality: 85 });

  // open tour
  await page.evaluate(() => { const b = document.getElementById("btnGuide"); if (b) b.hidden = false; });
  await page.click("#btnGuide");
  await sleep(800);

  // walk to step 3 (Enkripsi dan Kirim button)
  for (let i = 0; i < 2; i++) {
    await page.evaluate(() => {
      const b = document.getElementById("tourNext");
      if (b && !b.hidden && !b.disabled) b.click();
    });
    await sleep(600);
  }

  report.tour_step_3 = await page.evaluate(() => {
    const c = document.getElementById("tourCard");
    const b = document.getElementById("btnTransmitIntel");
    if (!c) return null;
    const r = c.getBoundingClientRect();
    const br = b ? b.getBoundingClientRect() : null;
    return {
      step: document.getElementById("tourStepIndicator")?.textContent || "",
      card: { top: r.top, bottom: r.bottom, left: r.left, right: r.right },
      btn: br && { top: br.top, bottom: br.bottom, left: br.left, right: br.right },
      overlapsBtn: br && (r.top < br.bottom && r.bottom > br.top && r.left < br.right && r.right > br.left),
      cardPosition: getComputedStyle(c).position,
      cardTopStyle: getComputedStyle(c).top,
    };
  });
  await page.screenshot({ path: path.join(OUT, "2_tour_step3.jpg"), type: "jpeg", quality: 85 });

  fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));

  await browser.close();
  backend.kill();
})().catch((e) => {
  console.error("FATAL", e);
  process.exit(1);
});
