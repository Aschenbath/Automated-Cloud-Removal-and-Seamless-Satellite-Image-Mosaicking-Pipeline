// Record a ~30 s scripted tour of the site as video frames, using headless Chrome.
//
//   node tools/record_demo.mjs <site-url> <out-dir>
//
// Chrome must already be running with --remote-debugging-port=9333 (see
// tools/record_demo.sh). Frames are captured with the DevTools screencast and
// resampled to a constant 30 fps; tools/encode_mp4.swift turns them into an MP4.
// Captions are added to the page only while recording.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [url = "http://127.0.0.1:8790/", outDir = "demo_frames"] = process.argv.slice(2);
const FPS = 30, WIDTH = 1280, HEIGHT = 720, SCALE = 1.5; // 1920 x 1080 frames
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const targets = await (await fetch("http://127.0.0.1:9333/json/list")).json();
const page = targets.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));

let nextId = 1;
const pending = new Map(), listeners = [];
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
  } else if (msg.method) listeners.forEach((fn) => fn(msg));
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = nextId++;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});
const js = async (code) => {
  // Run statements in the page; return nothing (some calls return objects too deep to send back).
  const expression = `(async () => { ${code}; })()`;
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || expr);
  return r.result.value;
};

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride",
  { width: WIDTH, height: HEIGHT, deviceScaleFactor: SCALE, mobile: false });
await send("Page.navigate", { url });
await sleep(6000); // page, images, street-map tiles and the page's own intro sweep

// Caption box over the map (recording only).
await js(`(() => {
  const c = document.createElement("div");
  c.id = "rec-caption";
  c.style.cssText = "position:absolute;left:50%;bottom:34px;transform:translateX(-50%);z-index:900;" +
    "background:rgba(10,20,30,.82);color:#fff;padding:9px 18px;border-radius:999px;" +
    "font:600 17px system-ui,sans-serif;white-space:nowrap;transition:opacity .3s;opacity:0";
  document.getElementById("map-wrap").appendChild(c);
  window.caption = (t) => { c.style.opacity = t ? 1 : 0; if (t) c.textContent = t; };
  window.region = (name) => [...document.querySelectorAll("#regions button")]
    .find((b) => b.textContent.startsWith(name)).click();
  // Glide the before/after divider to fraction f over ms milliseconds.
  window.divTo = (f, ms = 900) => new Promise((done) => {
    const f0 = dividerFrac, t0 = performance.now();
    const step = (now) => {
      const x = Math.min(1, (now - t0) / ms);
      dividerFrac = f0 + (f - f0) * (0.5 - Math.cos(Math.PI * x) / 2);
      placeDivider();
      x < 1 ? requestAnimationFrame(step) : done();
    };
    requestAnimationFrame(step);
  });
  window.panelTo = (sel) => {
    const p = document.getElementById("panel");
    p.scrollTo({ top: sel ? document.querySelector(sel).offsetTop - 12 : 0, behavior: "smooth" });
  };
})()`);

// Start capturing.
mkdirSync(outDir, { recursive: true });
const frames = [];
listeners.push((msg) => {
  if (msg.method !== "Page.screencastFrame") return;
  const { data, metadata, sessionId } = msg.params;
  const file = `raw_${String(frames.length).padStart(5, "0")}.jpg`;
  writeFileSync(join(outDir, file), Buffer.from(data, "base64"));
  frames.push({ file, t: metadata.timestamp });
  send("Page.screencastFrameAck", { sessionId });
});
await send("Page.startScreencast",
  { format: "jpeg", quality: 92, maxWidth: WIDTH * SCALE, maxHeight: HEIGHT * SCALE, everyNthFrame: 1 });
const t0 = Date.now() / 1000;
const at = async (s) => { const wait = t0 + s - Date.now() / 1000; if (wait > 0) await sleep(wait * 1000); };

// ---- The tour (times in seconds) ----
await at(0.2); await js(`caption("Utrecht: before | after. Clouds peel away"); peelIntro()`);
await at(4.4); await js(`caption("Cloud mask: red = cloudy before, cyan = filled after"); document.getElementById("show-mask").click(); divTo(0.3)`);
await at(8.2); await js(`document.getElementById("show-mask").click(); panelTo("#tol"); divTo(0.12)`);
await at(8.6); await js(`caption("Similarity threshold: strict fills nothing, relaxed fills more"); select(tolIdx, manifest.ssims.length - 1)`);
for (let i = 1; i < 5; i++) { await at(9.6 + i * 1.2); await js(`select(tolIdx, Math.max(0, manifest.ssims.length - 1 - ${i}))`); }
await at(15.6); await js(`caption("Columbus, Ohio: OSU campus"); panelTo(null); region("Columbus"); divTo(0.5, 600)`);
await at(17.0); await js(`peelIntro()`);
await at(21.2); await js(`caption("Taipei 101, Taiwan"); region("Taipei")`);
await at(22.6); await js(`peelIntro()`);
await at(26.6); await js(`caption("Red lines: seamlines where the strips were joined"); map.setView(map.getCenter(), map.getZoom() + 1, { animate: true })`);
await at(29.4); await js(`caption("CloudPeel · BuckAI Observatory")`);
await at(31.0);

await send("Page.stopScreencast");
await sleep(300);
ws.close();

// Resample to constant FPS: each output frame shows the latest captured frame.
const first = frames[0].t, list = [];
let k = 0;
for (let n = 0; n < Math.round(30.5 * FPS); n++) {
  const t = first + n / FPS;
  while (k + 1 < frames.length && frames[k + 1].t <= t) k++;
  list.push(frames[k].file);
}
writeFileSync(join(outDir, "frames.txt"), list.join("\n") + "\n");
console.log(`${frames.length} captured frames -> ${list.length} frames at ${FPS} fps in ${outDir}`);
