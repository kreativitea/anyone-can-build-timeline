// Take one screenshot with headless Google Chrome, for a QA run.
// It needs only Node (18 or newer for fetch, 22 or newer for WebSocket) and Chrome.
// No packages. It is a QA tool: the app itself never uses it.
//
//   node shoot.mjs page <url> <out.png|out.jpg> [session-token|-] [width]
//       The page as one person: the session cookie is set first ("-" = signed out).
//   node shoot.mjs file <file.html> <out.png> [width]
//       A local HTML file (the evidence cards qa.sh makes).

import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const CHROME = process.env.QA_CHROME
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

const [mode, target, out, ...rest] = process.argv.slice(2);
if (!["page", "file"].includes(mode) || !target || !out) {
  console.error("Use: node shoot.mjs page <url> <out.png> [token|-] [width]");
  console.error("     node shoot.mjs file <file.html> <out.png> [width]");
  process.exit(2);
}
const token = mode === "page" ? (rest[0] || "-") : "-";
const width = Number(mode === "page" ? rest[1] : rest[0]) || 1280;
const url = mode === "page" ? target : pathToFileURL(resolve(target)).href;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "qa-chrome-"));
const chrome = spawn(CHROME, [
  "--headless=new", "--remote-debugging-port=0", "--user-data-dir=" + profile,
  "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "about:blank",
], { stdio: "ignore" });

try {
  // Chrome writes the port it chose into this file.
  const portFile = join(profile, "DevToolsActivePort");
  for (let i = 0; i < 100 && !existsSync(portFile); i++) await sleep(100);
  const port = readFileSync(portFile, "utf8").split("\n")[0];
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const ws = new WebSocket(pages.find((p) => p.type === "page").webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });

  let next = 0;
  const waiting = new Map();
  const events = [];
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && waiting.has(msg.id)) {
      const { r, j } = waiting.get(msg.id);
      waiting.delete(msg.id);
      msg.error ? j(new Error(JSON.stringify(msg.error))) : r(msg.result);
    } else if (msg.method) {
      events.push(msg.method);
    }
  };
  const send = (method, params = {}) => new Promise((r, j) => {
    const id = ++next;
    waiting.set(id, { r, j });
    ws.send(JSON.stringify({ id, method, params }));
  });

  await send("Page.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride",
    { width, height: mode === "page" ? 900 : 100, deviceScaleFactor: 1, mobile: false });
  if (token !== "-") {
    await send("Network.setCookie", { name: "session", value: token, url, httpOnly: true,
      sameSite: "Strict" });
  }
  await send("Page.navigate", { url });
  for (let i = 0; i < 100 && !events.includes("Page.loadEventFired"); i++) await sleep(100);
  // The page asks the server for posts, likes and trends after it loads.
  await sleep(mode === "page" ? 2500 : 200);

  const { cssContentSize } = await send("Page.getLayoutMetrics");
  const height = Math.min(Math.ceil(cssContentSize.height), 4000);
  await send("Emulation.setDeviceMetricsOverride",
    { width, height, deviceScaleFactor: 1, mobile: false });
  await sleep(300);
  // .jpg is much smaller for the page (its background is a colour gradient).
  const jpeg = /\.jpe?g$/i.test(out);
  const { data } = await send("Page.captureScreenshot",
    jpeg ? { format: "jpeg", quality: 80 } : { format: "png" });
  writeFileSync(out, Buffer.from(data, "base64"));
  console.log("saved " + out);
  ws.close();
} finally {
  chrome.kill();
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
}
