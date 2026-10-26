const { ipcRenderer, contextBridge } = require("electron");

// Password-less desktop sign-in: runs before any app script on the KAI origin and puts the
// operator token (fetched by main.js via /auth/desktop) into the web app's storage, so the
// login screen never appears. Also tells the UI it is the desktop build.
if (location.origin.startsWith("http://127.0.0.1")) {
  try {
    const token = ipcRenderer.sendSync("kai-token");
    if (token) localStorage.setItem("kai.token", token);
  } catch { /* fall back to the normal login page */ }
  contextBridge.exposeInMainWorld("kaiDesktop", true);
}
