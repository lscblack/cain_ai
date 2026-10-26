// KAI desktop shell: makes sure the kai-* systemd user services are running,
// waits for the backend/frontend to be healthy, then shows KAI in a native window.
const { app, BrowserWindow, Tray, Menu, shell, nativeImage, ipcMain } = require("electron");
const { execFile } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");

// Ubuntu's AppArmor blocks Chromium's user-namespace sandbox for unpacked Electron.
// The window only ever loads http://127.0.0.1, so this is acceptable here.
app.commandLine.appendSwitch("no-sandbox");
app.commandLine.appendSwitch("disable-dev-shm-usage");

const URL_APP = "http://127.0.0.1:5174";
const HEALTH = `${URL_APP}/api/health`;
const DATA_MOUNT = "/run/media/lscblack/linux-data";
const DATA_UUID = "b70f155d-0dbe-4c48-806f-7c35c741302a";
const SERVICES = ["kai-postgres", "kai-redis", "kai-ollama", "kai-llama", "kai-backend", "kai-worker", "kai-frontend"]
  .map((s) => `${s}.service`);
const ICON = path.join(__dirname, "assets", "icon.png");

// ── password-less sign-in ───────────────────────────────────────────────
// The backend's /auth/desktop issues an operator token to whoever presents the
// local KAI_DESKTOP_TOKEN secret (from the project's .env). Tunnel/web visitors
// don't have it, so they still see the normal login.
let operatorToken = null;

function desktopSecret() {
  try {
    const env = fs.readFileSync(path.join(__dirname, "..", ".env"), "utf8");
    const m = env.match(/^KAI_DESKTOP_TOKEN=(.+)$/m);
    return m ? m[1].trim() : null;
  } catch { return null; }
}

function fetchOperatorToken() {
  return new Promise((resolve) => {
    const secret = desktopSecret();
    if (!secret) return resolve(null);
    const req = http.request(`${URL_APP}/api/auth/desktop`, {
      method: "POST", timeout: 8000, headers: { "X-KAI-Desktop": secret, "Content-Length": 0 },
    }, (res) => {
      let body = "";
      res.on("data", (d) => (body += d));
      res.on("end", () => {
        try { resolve(res.statusCode === 200 ? JSON.parse(body).access_token : null); }
        catch { resolve(null); }
      });
    });
    req.on("error", () => resolve(null));
    req.on("timeout", () => { req.destroy(); resolve(null); });
    req.end();
  });
}

async function refreshToken() {
  const t = await fetchOperatorToken();
  if (t) {
    operatorToken = t;
    if (win && !win.isDestroyed() && win.webContents.getURL().startsWith(URL_APP))
      win.webContents.executeJavaScript(`localStorage.setItem("kai.token", ${JSON.stringify(t)})`).catch(() => {});
  }
  return t;
}

ipcMain.on("kai-token", (e) => { e.returnValue = operatorToken; });

let win = null;
let tray = null;
let quitting = false;

const run = (cmd, args) =>
  new Promise((resolve) => execFile(cmd, args, { timeout: 60000 }, (err, out, errout) =>
    resolve({ ok: !err, out: String(out || ""), err: String(errout || (err && err.message) || "") })));

const healthy = () =>
  new Promise((resolve) => {
    const req = http.get(HEALTH, { timeout: 2000 }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => { req.destroy(); resolve(false); });
  });

const status = (t, err = false) => {
  console.log("[kai]", t);
  if (win && !win.isDestroyed())
    win.webContents.executeJavaScript(`window.setStatus&&window.setStatus(${JSON.stringify(t)},${err})`).catch(() => {});
};

async function ensureDataMount() {
  if (fs.existsSync(path.join(DATA_MOUNT, "conda"))) return true;
  status("Mounting data partition…");
  await run("udisksctl", ["mount", "-b", `/dev/disk/by-uuid/${DATA_UUID}`]);
  return fs.existsSync(path.join(DATA_MOUNT, "conda"));
}

async function startServices() {
  if (!(await ensureDataMount())) {
    status("The linux-data partition is not mounted (conda/Postgres live there).", true);
    return false;
  }
  status("Starting KAI services…");
  await run("systemctl", ["--user", "start", ...SERVICES]);
  for (let i = 0; i < 120; i++) {
    if (await healthy()) return true;
    status(`Waiting for KAI to come up… (${i * 2}s)`);
    await new Promise((r) => setTimeout(r, 2000));
  }
  status("KAI did not become healthy. Check: journalctl --user -u kai-backend", true);
  return false;
}

// The preload script puts the operator token into storage before the app starts,
// so a single load lands on the dashboard (no login screen).
async function openApp() {
  await win.loadURL(URL_APP).catch((e) => console.log("[kai] load:", e.message));
}

async function boot() {
  await win.loadFile(path.join(__dirname, "splash.html")).catch(() => {});
  const ok = await startServices();
  console.log("[kai] services ok:", ok);
  if (!ok) return;
  // No login: the desktop app signs in by itself with the local KAI_DESKTOP_TOKEN secret.
  let token = await refreshToken();
  console.log("[kai] auto sign-in:", token ? "ok" : "unavailable");
  await openApp();
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 900, minHeight: 600,
    backgroundColor: "#0b0f17", title: "KAI", icon: ICON, autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true },
  });
  win.removeMenu();
  // refresh shortcuts (menu is removed, so wire them by hand)
  win.webContents.on("before-input-event", (e, i) => {
    if (i.type !== "keyDown") return;
    const k = i.key.toLowerCase();
    if (k === "f5" || (i.control && k === "r")) { e.preventDefault(); i.shift ? win.webContents.reloadIgnoringCache() : win.webContents.reload(); }
  });
  // external links open in the default browser, not inside KAI
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(URL_APP)) { shell.openExternal(url); return { action: "deny" }; }
    return { action: "allow" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    if (url === "kai://retry") { e.preventDefault(); boot(); }
  });
  // close button hides to tray; Quit in the tray really exits
  win.on("close", (e) => { if (!quitting) { e.preventDefault(); win.hide(); } });
  boot();
}

function showWin() {
  if (!win || win.isDestroyed()) return createWindow();
  win.show(); win.focus();
}

function createTray() {
  tray = new Tray(nativeImage.createFromPath(ICON).resize({ width: 24, height: 24 }));
  tray.setToolTip("KAI");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Open KAI", click: showWin },
    { label: "Refresh", click: () => { showWin(); win.webContents.reloadIgnoringCache(); } },
    { label: "Restart KAI (reload app + sign-in)", click: () => { quitting = true; app.relaunch(); app.exit(0); } },
    { label: "Start services", click: () => run("systemctl", ["--user", "start", ...SERVICES]) },
    { label: "Stop services", click: () => run("systemctl", ["--user", "stop", ...SERVICES]) },
    { type: "separator" },
    { label: "Quit (leave services running)", click: () => { quitting = true; app.quit(); } },
    { label: "Quit and stop services", click: async () => {
        quitting = true;
        await run("systemctl", ["--user", "stop", ...SERVICES]);
        app.quit();
      } },
  ]));
  tray.on("click", showWin);
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", showWin);
  app.whenReady().then(() => {
    createTray(); createWindow();
    setInterval(refreshToken, 6 * 60 * 60 * 1000);   // tokens last 30 days; renew well before expiry
  });
  app.on("window-all-closed", () => {});
}

// Verification aid: KAI_SHOT=/path.png captures the app once loaded, then exits.
if (process.env.KAI_SHOT) {
  app.whenReady().then(() => setTimeout(async () => {
    const img = await win.webContents.capturePage();
    fs.writeFileSync(process.env.KAI_SHOT, img.toPNG());
    console.log("shot url:", win.webContents.getURL());
    console.log("page text:", JSON.stringify(await win.webContents.executeJavaScript("document.body.innerText.slice(0,160)")));
    quitting = true; app.quit();
  }, 25000));
}
