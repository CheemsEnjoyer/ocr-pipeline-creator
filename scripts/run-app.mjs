import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
process.chdir(root);
if (existsSync(".env")) process.loadEnvFile(".env");
const mode = process.argv[2] || "dev";
if (!["setup", "test", "dev", "start"].includes(mode)) throw new Error("Unknown launch mode");
const windows = process.platform === "win32";
const python = path.join(root, ".venv", windows ? "Scripts/python.exe" : "bin/python");
const children = new Set();
let stopping = false;

function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (windows && child.pid) spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
    else child.kill("SIGTERM");
  }
  process.exit(code);
}
process.on("SIGINT", () => stop());
process.on("SIGTERM", () => stop());

function launch(command, args, options = {}) {
  const child = spawn(command, args, { cwd: root, stdio: "inherit", windowsHide: true, ...options });
  children.add(child);
  child.once("exit", () => children.delete(child));
  return child;
}

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = launch(command, args);
    child.once("error", reject);
    child.once("exit", (code) => code === 0 ? resolve() : reject(new Error(`Command failed (exit ${code})`)));
  });
}

async function setup() {
  if (!existsSync(python)) {
    const candidates = process.env.PYTHON ? [process.env.PYTHON] : windows ? ["py", "python"] : ["python3", "python"];
    const selected = candidates.find((command) => spawnSync(command, ["-c", "import sys; sys.exit(sys.version_info < (3, 10))"], { windowsHide: true, stdio: "ignore" }).status === 0);
    if (!selected) throw new Error("Установите Python 3.10+ с python.org (Add Python to PATH), затем повторите npm run dev.");
    console.log("Создаём Python-окружение…");
    await run(selected, ["-m", "venv", ".venv"]);
  }
  const fingerprint = createHash("sha256").update(readFileSync("backend/requirements.txt")).digest("hex");
  const stamp = path.join(root, ".venv", ".ocr-requirements");
  if (!existsSync(stamp) || readFileSync(stamp, "utf8") !== fingerprint) {
    console.log("Устанавливаем зависимости Python…");
    // Normalize bare corporate proxy addresses for pip as well as the application.
    for (const name of ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]) {
      if (process.env[name] && !process.env[name].includes("://")) process.env[name] = `http://${process.env[name]}`;
    }
    await run(python, ["-m", "pip", "install", "-r", "backend/requirements.txt"]);
    writeFileSync(stamp, fingerprint);
  }
}

async function requireFreePort(port) {
  await new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", () => reject(new Error(`Порт ${port} занят. Остановите предыдущий запуск приложения.`)));
    server.listen(port, "127.0.0.1", () => server.close(resolve));
  });
}

try {
  await setup();
  if (mode === "setup") process.exit(0);
  if (mode === "test") {
    await run(python, ["-m", "unittest", "discover", "-s", "backend/tests", "-v"]);
    process.exit(0);
  }
  const backendPort = Number(process.env.BACKEND_PORT || 8000);
  const frontendPort = Number(process.env.PORT || 5173);
  for (const port of [backendPort, frontendPort]) {
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Некорректный порт сервера");
    await requireFreePort(port);
  }
  const backend = launch(python, ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", String(backendPort)]);
  backend.once("error", (error) => { console.error(error.message); stop(1); });
  backend.once("exit", (code) => { if (!stopping) stop(code || 1); });
  let ready = false;
  for (let attempt = 0; attempt < 120; attempt++) {
    try {
      const response = await fetch(`http://127.0.0.1:${backendPort}/api/health`, { signal: AbortSignal.timeout(1000) });
      if (response.ok) { ready = true; break; }
    } catch { /* Wait for FastAPI startup and automatic table creation. */ }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  if (!ready) throw new Error("Python-сервер не запустился. Проверьте сообщение выше.");
  console.log("База готова. Запускаем интерфейс…");
  const frontend = launch(process.execPath, ["node_modules/vinext/dist/cli.js", mode, "--port", String(frontendPort), "--hostname", "127.0.0.1"], { env: { ...process.env, BACKEND_URL: process.env.BACKEND_URL || `http://127.0.0.1:${backendPort}` } });
  frontend.once("error", (error) => { console.error(error.message); stop(1); });
  frontend.once("exit", (code) => { if (!stopping) stop(code || 0); });
} catch (error) {
  console.error(error.message);
  stop(1);
}
