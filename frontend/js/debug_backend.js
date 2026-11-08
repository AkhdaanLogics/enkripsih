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
const py = "E:\\enkripsih\\.venv\\Scripts\\python.exe";
const backend = spawn(py, ["-m", "uvicorn", "backend.main:app", "--port", "8099", "--host", "127.0.0.1"], {
  cwd: "E:\\enkripsih",
  env: { ...process.env, ...fileEnv },
  stdio: ["ignore", "pipe", "pipe"],
});

let out = "";
backend.stdout.on("data", d => { out += d.toString(); });
backend.stderr.on("data", d => { out += d.toString(); });

setTimeout(async () => {
  try {
    const r = await fetch("http://127.0.0.1:8099/api/health");
    console.log("status:", r.status);
  } catch (e) {
    console.log("err", e.message);
  }
  console.log("=== OUTPUT ===");
  console.log(out.slice(-3000));
  backend.kill();
}, 8000);
