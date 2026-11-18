// CloudPeel: shows precomputed Step 4 results and a before/after swipe.
const PRESETS = [
  { name: "Cautious", cloud_tolerance: 0.05, ssim_threshold: 0.85 },
  { name: "Default", cloud_tolerance: 0.25, ssim_threshold: 0.75 },
  { name: "Bold", cloud_tolerance: 0.60, ssim_threshold: 0.55 },
];

// Where "Suggest a place" sends people: a pre-filled issue on the project's repository.
// Issues can only be filed once the repository is public.
const SUGGEST_ISSUE_URL = "https://github.com/buckai-observatory/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/issues/new";
const BOX_KM = 22;
const HIRES_ZOOM = 13;         // switch to the 10 m views from this zoom level
const SOURCE_COLOURS = ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02"];

const $ = (id) => document.getElementById(id);
const fmt = (v) => v.toFixed(2);
const runKey = (t, s) => `t${fmt(t)}_s${fmt(s)}`;
const EMBED = new URLSearchParams(location.search).get("embed") === "1";
// On phones the map sits above the panel; bring it into view after panel actions.
const NARROW = matchMedia("(max-width: 760px)");
const showMap = () => { if (NARROW.matches) $("map-wrap").scrollIntoView({ behavior: "smooth", block: "start" }); };
const fmtDate = (d) => d ? new Date(d + "T00:00:00Z").toLocaleDateString(LOCALES[LANG],
  { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : tr("date.unknown");

let datasets, dataset, manifest, map;
let beforeImg, beforeMask, afterImg, afterMask, seamsImg, sourcesImg;
let tolIdx = 0, ssimIdx = 0;
let dividerFrac = 0.5;
let userMoved = false;
let sourcesCanvas = null;      // decoded img/sources.png for click lookups

async function init() {
  setLang(initialLang(), false);
  for (const b of document.querySelectorAll("[data-lang]")) b.addEventListener("click", () => setLang(b.dataset.lang));
  $("embed-lang").addEventListener("change", (e) => setLang(e.target.value));
  if (EMBED) document.body.classList.add("embed");
  $("embed-bar").hidden = !EMBED;
  map = L.map("map", { zoomSnap: 0.25 });
  const streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  // Without internet the street map can't load; say so instead of showing a blank background.
  streets.on("tileerror", () => { $("offline-tag").hidden = false; });
  streets.on("tileload", () => { $("offline-tag").hidden = true; });
  map.createPane("before").style.zIndex = 410;
  map.createPane("after").style.zIndex = 420;
  map.createPane("seams").style.zIndex = 430; // above both sides, not clipped
  map.createPane("tour").style.zIndex = 440;
  for (const ev of ["pointerdown", "wheel", "keydown"]) {
    $("map").addEventListener(ev, () => { userMoved = true; }, { passive: true });
  }
  // Refit on resize until the user moves the map (the container can still
  // have zero size when the page first loads).
  new ResizeObserver(() => fit()).observe($("map-wrap"));

  buildStaticControls();
  $("embed-region").addEventListener("change", (e) =>
    loadDataset(datasets.find((d) => d.id === e.target.value)));
  setupDivider();
  setupSuggest();
  setupTour();
  setupNaiveExample();
  map.on("zoomend", () => updateImages());
  map.on("moveend", () => writeHash());
  map.on("click", onMapClick);

  datasets = await (await fetch("data/datasets.json", { cache: "no-cache" })).json();
  buildRegions();
  const state = readHash();
  await loadDataset(datasets.find((d) => d.id === state.r) || datasets[0], state);
  if (state.view) {
    userMoved = true;
    map.setView(state.view.center, state.view.zoom, { animate: false });
  }
  if (!state.any) peelIntro();
  hashReady = true;
  writeHash();
}

function fit(force = false) {
  map.invalidateSize();
  if ((force || !userMoved) && manifest && map.getSize().x > 0) {
    map.fitBounds(manifest.bounds, { padding: [10, 10] });
  }
}

async function loadDataset(ds, state = {}) {
  const prev = manifest;
  dataset = ds;
  manifest = await (await fetch(ds.path + "manifest.json", { cache: "no-cache" })).json();
  buildPools();
  showDates();
  document.querySelectorAll("#pools button").forEach((el) =>
    el.setAttribute("aria-pressed", el.dataset.id === ds.id));
  document.querySelectorAll("#regions button").forEach((el) =>
    el.setAttribute("aria-pressed", el.dataset.region === ds.region));
  $("embed-region").value = ds.id;

  for (const layer of [beforeImg, beforeMask, afterImg, afterMask, seamsImg, sourcesImg]) layer?.remove();
  const b = manifest.bounds, p = ds.path;
  beforeImg = L.imageOverlay(p + "img/before.png", b, { pane: "before" }).addTo(map);
  beforeMask = L.imageOverlay(p + "img/clouds_before.png", b, { pane: "before", opacity: 0.9 });
  afterImg = L.imageOverlay(p + "img/before.png", b, { pane: "after" }).addTo(map);
  afterMask = L.imageOverlay(p + "img/clouds_before.png", b, { pane: "after", opacity: 0.9 });
  if (state.mask !== undefined) $("show-mask").checked = state.mask;
  if (state.seams !== undefined) $("show-seams").checked = state.seams;
  $("legend").hidden = !$("show-mask").checked;
  if ($("show-mask").checked) { beforeMask.addTo(map); afterMask.addTo(map); }
  seamsImg = manifest.seams ? L.imageOverlay(p + "img/seams.png", b, { pane: "seams" }) : null;
  $("seams-row").hidden = !seamsImg;
  $("seams-note").hidden = !seamsImg || !$("show-seams").checked;
  if (seamsImg && $("show-seams").checked) seamsImg.addTo(map);
  setupSources();
  $("naive-row").hidden = !manifest.fill_sources;
  if (state.view) {
    // A link's own view; fitting first starts a zoom animation that would end after this and win.
    userMoved = true;
    map.setView(state.view.center, state.view.zoom, { animate: false });
  } else if (!prev || prev.name !== manifest.name) { userMoved = false; map.setView(centre(b), 11); fit(true); }

  buildPresets();
  buildGrid();
  $("tol").max = manifest.tolerances.length - 1;
  $("ssim").max = manifest.ssims.length - 1;
  // Settings: from the link if given; else keep the current one when this
  // result set has it; else the result set's own starting setting.
  const d = manifest.defaults;
  let t = manifest.tolerances.indexOf(d.cloud_tolerance), s = manifest.ssims.indexOf(d.ssim_threshold);
  if (prev) {
    const keepT = manifest.tolerances.indexOf(prev.tolerances[tolIdx]);
    const keepS = manifest.ssims.indexOf(prev.ssims[ssimIdx]);
    if (keepT >= 0) t = keepT;
    if (keepS >= 0) s = keepS;
  }
  if (state.t !== undefined && manifest.tolerances.indexOf(state.t) >= 0) t = manifest.tolerances.indexOf(state.t);
  if (state.s !== undefined && manifest.ssims.indexOf(state.s) >= 0) s = manifest.ssims.indexOf(state.s);
  if (state.d !== undefined) { dividerFrac = state.d; placeDivider(); }
  if (state.naive !== undefined) $("show-naive").checked = state.naive;
  if (state.src !== undefined) $("show-sources").checked = state.src;
  await select(t, s);
}

const centre = (b) => [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2];

// ---- Language (#8) ----
function setLang(lang, rerender = true) {
  if (!(lang in LANGS)) return;
  LANG = lang;
  try { localStorage.setItem("cloudpeel-lang", lang); } catch { /* storage may be blocked */ }
  applyStatic();
  $("embed-lang").value = lang;
  if (!rerender || !manifest) return;
  map.closePopup(); // an open popup would keep the old language
  buildRegions();
  buildPools();
  showDates();
  buildPresets();
  buildGrid();
  setupSourcesLegend();
  select(tolIdx, ssimIdx);
  if (!picking) $("sg-pick").textContent = tr("suggest.pick");
  if (tourStep >= 0) tourGo(tourStep);
  writeHash();
}

// ---- Dates (#3) ----
function showDates() {
  const box = $("dates"), d = manifest.dates;
  if (!d) { box.textContent = ""; $("pool-note").textContent = ""; return; }
  const cols = manifest.strip_colours || [];
  const sep = LANG === "zh" ? "、" : ", ";
  box.innerHTML = tr("dates.before") + "<br>" +
    d.mosaic.map((m, i) => `<span class="swatch" style="background:${cols[i] || "#999"}"></span>${fmtDate(m.date)}`).join("") +
    "<br>" + tr("dates.filled") + d.candidates.map((c) => fmtDate(c.date)).join(sep);
  $("pool-note").textContent = tr("dates.pool", { list: d.candidates.map((c) => fmtDate(c.date)).join(sep) });
}

function buildRegions() {
  const seen = new Set();
  $("embed-region").replaceChildren();
  $("regions").replaceChildren();
  for (const ds of datasets) {
    const opt = document.createElement("option");
    opt.value = ds.id;
    opt.textContent = datasets.filter((d) => d.region === ds.region).length > 1
      ? `${trRegion(ds.region)}: ${trPool(ds.label)}` : trRegion(ds.region);
    $("embed-region").appendChild(opt);
    if (seen.has(ds.region)) continue;
    seen.add(ds.region);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = trRegion(ds.region);
    btn.dataset.region = ds.region;
    btn.addEventListener("click", () => {
      if (ds.region !== dataset.region) loadDataset(datasets.find((d) => d.region === ds.region));
      showMap();
    });
    $("regions").appendChild(btn);
  }
  if (dataset) {
    $("embed-region").value = dataset.id;
    document.querySelectorAll("#regions button").forEach((el) =>
      el.setAttribute("aria-pressed", el.dataset.region === dataset.region));
  }
}

// Candidate pools available for the current region.
function buildPools() {
  const pools = datasets.filter((d) => d.region === dataset.region);
  $("pool-section").hidden = pools.length < 2;
  $("pools").replaceChildren();
  for (const ds of pools) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = trPool(ds.label);
    btn.dataset.id = ds.id;
    btn.addEventListener("click", () => loadDataset(ds));
    btn.setAttribute("aria-pressed", ds.id === dataset.id);
    $("pools").appendChild(btn);
  }
}

function buildStaticControls() {
  $("tol").addEventListener("input", (e) => select(+e.target.value, ssimIdx));
  $("ssim").addEventListener("input", (e) => select(tolIdx, +e.target.value));
  $("show-seams").addEventListener("change", (e) => {
    $("seams-note").hidden = !e.target.checked;
    if (seamsImg) e.target.checked ? seamsImg.addTo(map) : seamsImg.remove();
    writeHash();
  });
  $("show-mask").addEventListener("change", (e) => {
    const on = e.target.checked;
    $("legend").hidden = !on;
    for (const layer of [afterMask, beforeMask]) on ? layer.addTo(map) : layer.remove();
    clip();
    writeHash();
  });
  $("show-naive").addEventListener("change", () => { updateImages(); writeHash(); });
  $("show-sources").addEventListener("change", () => { updateSources(); writeHash(); });
  $("copy-link").addEventListener("click", async (e) => {
    writeHash();
    try { await navigator.clipboard.writeText(location.href); e.target.textContent = tr("btn.linkCopied"); }
    catch { e.target.textContent = tr("btn.copyAddress"); }
    setTimeout(() => { e.target.textContent = tr("btn.copyLink"); }, 2000);
  });
}

function buildPresets() {
  const box = $("presets");
  box.replaceChildren();
  for (const p of PRESETS) {
    const t = manifest.tolerances.indexOf(p.cloud_tolerance);
    const s = manifest.ssims.indexOf(p.ssim_threshold);
    if (t < 0 || s < 0) continue;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = tr("preset." + p.name);
    btn.dataset.t = t;
    btn.dataset.s = s;
    btn.title = tr("setting.label", { t: fmt(p.cloud_tolerance), s: fmt(p.ssim_threshold) });
    btn.addEventListener("click", () => select(t, s));
    box.appendChild(btn);
  }
}

// Heat grid: rows = SSIM (high at top), columns = tolerance.
function buildGrid() {
  const grid = $("grid");
  grid.replaceChildren();
  grid.style.gridTemplateColumns = `34px repeat(${manifest.tolerances.length}, 1fr)`;
  const vals = Object.values(manifest.runs).map((r) => r.cloudy_area_filled_pct);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const ssimsDesc = manifest.ssims.map((v, i) => [v, i]).reverse();
  for (const [sv, si] of ssimsDesc) {
    grid.appendChild(cell("div", "hdr", fmt(sv)));
    manifest.tolerances.forEach((tv, ti) => {
      const r = manifest.runs[runKey(tv, sv)];
      const btn = cell("button", "", `${Math.round(r.cloudy_area_filled_pct)}%`);
      const f = hi > lo ? (r.cloudy_area_filled_pct - lo) / (hi - lo) : 1;
      btn.style.background = ramp(f);
      btn.style.color = f > 0.55 ? "#fff" : "#0b1b2b";
      btn.dataset.t = ti;
      btn.dataset.s = si;
      btn.title = tr("grid.cell", { t: fmt(tv), s: fmt(sv), a: r.patches_filled, b: r.patches_total,
        c: r.flagged_km2.toFixed(1) });
      if (r.flagged_km2 > 0) {
        const dot = cell("span", "dot", "");
        dot.setAttribute("aria-label", "cloud copied in");
        btn.appendChild(dot);
      }
      btn.addEventListener("click", () => select(ti, si));
      grid.appendChild(btn);
    });
  }
  grid.appendChild(cell("div", "hdr", ""));
  manifest.tolerances.forEach((tv) => grid.appendChild(cell("div", "hdr", fmt(tv))));

  // Say so when tolerance makes no difference for any SSIM value.
  const same = (a, b) => a.cloudy_area_filled_pct === b.cloudy_area_filled_pct &&
    a.flagged_km2 === b.flagged_km2;
  const tolInert = manifest.ssims.every((sv) => {
    const first = manifest.runs[runKey(manifest.tolerances[0], sv)];
    return manifest.tolerances.every((tv) => same(manifest.runs[runKey(tv, sv)], first));
  });
  $("tol-note").hidden = !tolInert;
}

function cell(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  el.textContent = text;
  return el;
}

// Single-hue sequential ramp, light (few filled) to deep blue (most filled).
function ramp(f) {
  const a = [227, 241, 250], b = [8, 69, 128];
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * f)).join(",")})`;
}

const preloaded = new Map();
function preload(url) {
  if (!preloaded.has(url)) {
    preloaded.set(url, new Promise((res) => {
      const im = new Image();
      im.onload = im.onerror = () => res(url);
      im.src = url;
    }));
  }
  return preloaded.get(url);
}

const currentKey = () => runKey(manifest.tolerances[tolIdx], manifest.ssims[ssimIdx]);

async function select(t, s) {
  tolIdx = t;
  ssimIdx = s;
  const tv = manifest.tolerances[t], sv = manifest.ssims[s];
  const k = runKey(tv, sv);
  const r = manifest.runs[k];

  $("tol").value = t;
  $("ssim").value = s;
  $("tol-out").textContent = fmt(tv);
  $("ssim-out").textContent = fmt(sv);
  $("st-patches").textContent = `${r.patches_filled} / ${r.patches_total}`;
  $("st-area").textContent = `${r.cloudy_area_filled_pct.toFixed(0)}%`;
  $("st-left").textContent = `${r.cloud_left_km2.toFixed(1)} km²`;
  $("st-flag").textContent = `${r.flagged_km2.toFixed(1)} km²`;
  $("st-hint").textContent = tr("stat.hint", { time: `${r.step4_seconds.toFixed(1)} s` });

  document.querySelectorAll("#presets button, #grid button").forEach((el) => {
    const on = +el.dataset.t === t && +el.dataset.s === s;
    el.setAttribute(el.closest("#grid") ? "aria-selected" : "aria-pressed", on);
  });
  await updateImages();
  updateSources();
  writeHash();
}

// ---- Which image each side shows: normal, naive paste (#6) or 10 m (#9) ----
async function updateImages() {
  if (!manifest || !afterImg) return;
  const ds = dataset, k = currentKey(), p = ds.path;
  const atExtras = manifest.fill_sources && manifest.fill_sources.setting === k;
  const naiveOn = $("show-naive").checked && atExtras;
  const hiresOn = manifest.hires && manifest.hires.setting === k && map.getZoom() >= HIRES_ZOOM;
  const setting = manifest.fill_sources?.setting;
  $("show-naive").disabled = !atExtras;
  $("naive-note").hidden = !manifest.fill_sources;
  $("naive-example").hidden = !manifest.fill_sources;
  $("naive-note").textContent = atExtras ? tr("note.naiveOn") : tr("note.onlyAt", { setting: settingLabel(setting) });

  const beforeUrl = p + (hiresOn ? "img/before_10m.png" : "img/before.png");
  const afterUrl = p + (naiveOn ? "img/naive.png" : hiresOn ? `img/after10m_${k}.png` : `img/after_${k}.png`);
  const maskUrl = `${p}img/clouds_${k}.png`;
  await Promise.all([preload(beforeUrl), preload(afterUrl), preload(maskUrl)]);
  if (dataset !== ds || currentKey() !== k) return; // a newer selection won
  if (beforeImg._url !== beforeUrl) beforeImg.setUrl(beforeUrl);
  if (afterImg._url !== afterUrl) afterImg.setUrl(afterUrl);
  if (afterMask._url !== maskUrl) afterMask.setUrl(maskUrl);
  const res = hiresOn ? " · 10 m" : "";
  $("tag-before").textContent = tr("tag.before") + res;
  $("tag-after").textContent = naiveOn ? tr("tag.naive") : tr("tag.after") + res;
  clip();
}

const settingLabel = (k) => {
  const m = /^tr?([\d.]+)_s([\d.]+)$/.exec(k || "");
  return m ? tr("setting.label", { t: m[1], s: m[2] }) : tr("setting.na");
};

// ---- Which date filled each patch (#10) ----
function setupSources() {
  sourcesImg = null;
  sourcesCanvas = null;
  const fs = manifest.fill_sources;
  $("sources-row").hidden = !fs;
  $("sources-legend").replaceChildren();
  if (!fs) { $("sources-note").hidden = true; return; }
  const img = new Image();
  img.onload = () => {
    const c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    const g = c.getContext("2d");
    g.drawImage(img, 0, 0);
    sourcesCanvas = { w: c.width, h: c.height, data: g.getImageData(0, 0, c.width, c.height).data };
    // Colour the patches by candidate for display.
    const out = g.createImageData(c.width, c.height);
    const rgb = SOURCE_COLOURS.map((h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)));
    for (let i = 0; i < out.data.length; i += 4) {
      const idx = sourcesCanvas.data[i];
      if (idx > 0) {
        const [r, gg, b] = rgb[(idx - 1) % rgb.length];
        out.data[i] = r; out.data[i + 1] = gg; out.data[i + 2] = b; out.data[i + 3] = 170;
      }
    }
    g.putImageData(out, 0, 0);
    if (dataset && manifest.fill_sources === fs) {
      sourcesImg = L.imageOverlay(c.toDataURL(), manifest.bounds, { pane: "after", interactive: false });
      updateSources();
    }
  };
  img.src = dataset.path + "img/sources.png";
  setupSourcesLegend();
}

// Legend: one row per candidate that filled something.
function setupSourcesLegend() {
  const fs = manifest?.fill_sources;
  $("sources-legend").replaceChildren();
  if (!fs) return;
  const used = new Map();
  for (const p of fs.patches) {
    const u = used.get(p.candidate) || { km2: 0, n: 0, date: p.date };
    u.km2 += p.km2; u.n += 1;
    used.set(p.candidate, u);
  }
  for (const [cand, u] of used) {
    const i = fs.candidates.indexOf(cand);
    const li = document.createElement("li");
    li.innerHTML = `<i style="background:${SOURCE_COLOURS[i % SOURCE_COLOURS.length]}"></i>` +
      tr(u.n > 1 ? "src.rowN" : "src.row1", { date: fmtDate(u.date), n: u.n, km2: u.km2.toFixed(1) });
    $("sources-legend").appendChild(li);
  }
}

function updateSources() {
  if (!manifest) return;
  const fs = manifest.fill_sources;
  const at = fs && fs.setting === currentKey();
  $("show-sources").disabled = !at;
  const on = $("show-sources").checked && at;
  $("sources-legend").hidden = !on;
  $("sources-note").hidden = !fs;
  if (fs) {
    const logged = fs.patches.some((p) => p.how === "log");
    $("sources-note").textContent = at ? tr(logged ? "note.sourcesLog" : "note.sourcesOn")
      : tr("note.onlyAt", { setting: settingLabel(fs.setting) });
  }
  if (sourcesImg) on ? sourcesImg.addTo(map) : sourcesImg.remove();
}

function matchText(scores) {
  const lo = Math.min(...scores).toFixed(2), hi = Math.max(...scores).toFixed(2);
  return lo === hi ? lo : `${lo}–${hi}`;
}

function onMapClick(e) {
  if (picking || !sourcesCanvas || !$("show-sources").checked || $("show-sources").disabled) return;
  const b = manifest.bounds;
  const nw = map.project(L.latLng(b[1][0], b[0][1]), 0), se = map.project(L.latLng(b[0][0], b[1][1]), 0);
  const pt = map.project(e.latlng, 0);
  const x = Math.floor((pt.x - nw.x) / (se.x - nw.x) * sourcesCanvas.w);
  const y = Math.floor((pt.y - nw.y) / (se.y - nw.y) * sourcesCanvas.h);
  if (x < 0 || y < 0 || x >= sourcesCanvas.w || y >= sourcesCanvas.h) return;
  const idx = sourcesCanvas.data[(y * sourcesCanvas.w + x) * 4];
  if (!idx) return;
  const fs = manifest.fill_sources, cand = fs.candidates[idx - 1];
  // Patches without "how" come from manifests made before the fill log.
  const ps = fs.patches.filter((p) => p.candidate === cand);
  const logged = ps.filter((p) => p.how === "log");
  const detail = logged.length
    ? tr("popup.log", { x: matchText(logged.map((p) => p.ssim)) })
    : tr("popup.match", { x: matchText(ps.map((p) => p.score)) });
  const date = manifest.dates?.candidates.find((c) => c.scene === cand)?.date;
  L.popup().setLatLng(e.latlng).setContent(
    `<b>${tr("popup.filled", { date: fmtDate(date) })}</b><br><small>${detail}</small>`).openOn(map);
}

// ---- Shareable links (#1) ----
let hashReady = false, hashTimer = null, lastHash = "";

// A link pasted into a tab that already shows CloudPeel only changes the hash.
addEventListener("hashchange", async () => {
  if (!hashReady || location.hash === lastHash) return;
  const state = readHash();
  hashReady = false;
  await loadDataset(datasets.find((d) => d.id === state.r) || dataset, state);
  if (state.view) { userMoved = true; map.setView(state.view.center, state.view.zoom, { animate: false }); }
  hashReady = true;
  writeHash();
});
function readHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  const num = (k) => (q.has(k) && Number.isFinite(+q.get(k)) ? +q.get(k) : undefined);
  const flag = (k) => (q.has(k) ? q.get(k) === "1" : undefined);
  const state = { any: [...q.keys()].length > 0, r: q.get("r") || undefined,
    t: num("t"), s: num("s"), d: num("d"), mask: flag("mask"), seams: flag("seams"),
    naive: flag("naive"), src: flag("src") };
  if (state.d !== undefined) state.d = Math.min(1, Math.max(0, state.d));
  const lat = num("lat"), lon = num("lon"), z = num("z");
  if (lat !== undefined && lon !== undefined && z !== undefined) state.view = { center: [lat, lon], zoom: z };
  return state;
}

function writeHash() {
  if (!hashReady || !manifest) return;
  clearTimeout(hashTimer);
  hashTimer = setTimeout(() => {
    const c = map.getCenter();
    const q = new URLSearchParams({
      r: dataset.id, t: fmt(manifest.tolerances[tolIdx]), s: fmt(manifest.ssims[ssimIdx]),
      d: dividerFrac.toFixed(2), lat: c.lat.toFixed(4), lon: c.lng.toFixed(4), z: map.getZoom().toFixed(2),
      mask: $("show-mask").checked ? 1 : 0, seams: $("show-seams").checked ? 1 : 0,
      naive: $("show-naive").checked ? 1 : 0, src: $("show-sources").checked ? 1 : 0,
      lang: LANG,
    });
    lastHash = "#" + q.toString();
    history.replaceState(null, "", lastHash);
    $("embed-open").href = location.pathname + location.hash;
  }, 150);
}

// A one-off sweep of the divider when the page opens, so the clouds visibly
// peel away. Skipped for reduced-motion users; any interaction stops it.
function peelIntro() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const keys = [[0, 0.5], [900, 0.95], [2300, 0.05], [3200, 0.5]];
  let stop = false, t0 = null;
  const cancel = () => { stop = true; };
  for (const ev of ["pointerdown", "wheel", "keydown"]) addEventListener(ev, cancel, { once: true });
  const ease = (x) => 0.5 - Math.cos(Math.PI * x) / 2;
  const step = (now) => {
    if (stop) return;
    t0 ??= now;
    const t = now - t0;
    const i = keys.findIndex(([k]) => k > t);
    if (i < 0) { dividerFrac = 0.5; placeDivider(); return; }
    const [ta, fa] = keys[i - 1], [tb, fb] = keys[i];
    dividerFrac = fa + (fb - fa) * ease((t - ta) / (tb - ta));
    placeDivider();
    requestAnimationFrame(step);
  };
  setTimeout(() => requestAnimationFrame(step), 600);
}

let placeDivider = () => {};

// Before/after swipe: clip the two panes at the divider position.
// Drag it, or focus it and use the arrow keys (#4).
function setupDivider() {
  const wrap = $("map-wrap"), div = $("divider");
  const place = () => {
    div.style.left = `${dividerFrac * 100}%`;
    div.setAttribute("aria-valuenow", Math.round(dividerFrac * 100));
    clip();
  };
  placeDivider = place;
  let dragging = false;
  div.addEventListener("pointerdown", (e) => {
    dragging = true;
    div.setPointerCapture(e.pointerId);
    map.dragging.disable();
  });
  div.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const r = wrap.getBoundingClientRect();
    dividerFrac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    place();
  });
  const stop = () => { if (dragging) writeHash(); dragging = false; map.dragging.enable(); };
  div.addEventListener("pointerup", stop);
  div.addEventListener("pointercancel", stop);
  div.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 0.1 : 0.02;
    const moves = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step };
    if (e.key in moves) dividerFrac = Math.min(1, Math.max(0, dividerFrac + moves[e.key]));
    else if (e.key === "Home") dividerFrac = 0;
    else if (e.key === "End") dividerFrac = 1;
    else return;
    e.preventDefault();
    e.stopPropagation();
    place();
    writeHash();
  });
  map.on("move zoom resize zoomend", clip);
  place();
}

function clip() {
  if (!map) return;
  const size = map.getSize();
  const nw = map.containerPointToLayerPoint([0, 0]);
  const se = map.containerPointToLayerPoint(size);
  const touring = $("map-wrap").classList.contains("touring");
  const x = map.containerPointToLayerPoint([size.x * (touring ? 1 : dividerFrac), 0]).x;
  map.getPane("before").style.clip = `rect(${nw.y}px, ${x}px, ${se.y}px, ${nw.x}px)`;
  map.getPane("after").style.clip = `rect(${nw.y}px, ${se.x}px, ${se.y}px, ${x}px)`;
}

// ---- How it works (#5): a four-step tour on the map ----
let tourStep = -1, tourLayer = null, tourSaved = null;
const TOUR = [
  {
    title: () => tr("tour1.title"),
    text: () => tr("tour1.text"),
    legend: (m) => (m.dates?.mosaic || []).map((d, i) => [m.strip_colours?.[i] || "#999", fmtDate(d.date)]),
    show: () => ({ overlay: "strips.png" }),
  },
  {
    title: () => tr("tour2.title"),
    text: () => tr("tour2.text"),
    legend: () => [["#e61414", tr("tour2.legend")]],
    show: () => ({ before: true, seams: true }),
  },
  {
    title: () => tr("tour3.title"),
    text: () => tr("tour3.text"),
    legend: () => [["rgba(255,40,40,.8)", tr("tour3.legend")]],
    show: () => ({ before: true, mask: true }),
  },
  {
    title: () => tr("tour4.title"),
    text: () => tr("tour4.text"),
    legend: (m) => sourceLegend(m),
    show: () => ({ swipe: true, sources: true }),
  },
];

function sourceLegend(m) {
  const fs = m.fill_sources;
  if (!fs) return [];
  const seen = new Set(), rows = [];
  for (const p of fs.patches) {
    if (seen.has(p.candidate)) continue;
    seen.add(p.candidate);
    rows.push([SOURCE_COLOURS[fs.candidates.indexOf(p.candidate) % SOURCE_COLOURS.length], fmtDate(p.date)]);
  }
  return rows;
}

// The spot where blending makes the clearest visible difference (found by
// comparing edge steps in the naive and blended images, away from the mosaic edge).
// Zoom stays below HIRES_ZOOM so both versions are shown at the same 20 m.
const NAIVE_EXAMPLE = "r=taichung_auto&t=0.25&s=0.75&d=0.12&lat=24.1838&lon=120.6094&z=12.75&mask=0&seams=0&naive=1&src=0";
function setupNaiveExample() {
  $("naive-example").addEventListener("click", () => { location.hash = NAIVE_EXAMPLE + "&lang=" + LANG; });
}

function setupTour() {
  $("tour-start").addEventListener("click", () => startTour());
  $("tour-next").addEventListener("click", () => tourGo(tourStep + 1));
  $("tour-prev").addEventListener("click", () => tourGo(tourStep - 1));
  $("tour-close").addEventListener("click", () => endTour());
  addEventListener("keydown", (e) => { if (e.key === "Escape" && tourStep >= 0) endTour(); });
}

async function startTour() {
  if (!manifest.dates) return;
  const fs = manifest.fill_sources;
  tourSaved = { mask: $("show-mask").checked, seams: $("show-seams").checked,
    src: $("show-sources").checked, naive: $("show-naive").checked, t: tolIdx, s: ssimIdx };
  $("show-naive").checked = false;
  // The fill colours exist for the starting setting, so the tour uses it.
  if (fs) {
    const m = /^tr?([\d.]+)_s([\d.]+)$/.exec(fs.setting);
    if (m) await select(manifest.tolerances.indexOf(+m[1]), manifest.ssims.indexOf(+m[2]));
  }
  userMoved = false;
  fit(true);
  $("tour").hidden = false;
  showMap();
  tourGo(0);
}

function tourGo(i) {
  if (i >= TOUR.length) return endTour();
  tourStep = Math.max(0, i);
  const step = TOUR[tourStep], v = step.show();
  $("tour-step").textContent = tr("tour.step", { i: tourStep + 1, n: TOUR.length });
  $("tour-title").textContent = step.title();
  $("tour-text").textContent = step.text(manifest);
  $("tour-legend").innerHTML = step.legend(manifest)
    .map(([c, t]) => `<li><i style="background:${c}"></i>${t}</li>`).join("");
  $("tour-prev").disabled = tourStep === 0;
  $("tour-next").textContent = tr(tourStep === TOUR.length - 1 ? "tour.done" : "tour.next");

  tourLayer?.remove();
  tourLayer = v.overlay ? L.imageOverlay(dataset.path + "img/" + v.overlay, manifest.bounds, { pane: "tour" }).addTo(map) : null;
  $("map-wrap").classList.toggle("touring", !v.swipe);
  map.getPane("before").style.display = v.overlay ? "none" : "";
  map.getPane("after").style.display = v.swipe ? "" : "none";
  setLayer(seamsImg, v.seams || (v.swipe && tourSaved.seams));
  setLayer(beforeMask, !!v.mask);
  setLayer(afterMask, false);
  $("show-sources").checked = !!v.sources;
  updateSources();
  if (v.swipe) { dividerFrac = 0.35; placeDivider(); }
  clip();
}

const setLayer = (layer, on) => { if (layer) on ? layer.addTo(map) : layer.remove(); };

function endTour() {
  if (tourStep < 0) return;
  tourStep = -1;
  tourLayer?.remove();
  tourLayer = null;
  $("tour").hidden = true;
  $("map-wrap").classList.remove("touring");
  map.getPane("before").style.display = "";
  map.getPane("after").style.display = "";
  const s = tourSaved;
  $("show-mask").checked = s.mask;
  $("show-seams").checked = s.seams;
  $("show-sources").checked = s.src;
  $("show-naive").checked = s.naive;
  setLayer(seamsImg, s.seams);
  setLayer(beforeMask, s.mask);
  setLayer(afterMask, s.mask);
  $("legend").hidden = !s.mask;
  dividerFrac = 0.5;
  placeDivider();
  select(s.t, s.s);
}

// QR code for Amy's website, drawn in the browser (no external QR service).
if (window.QRCode) {
  new QRCode($("qr"), { text: "https://amy-hsu.github.io/#guestbook", width: 184, height: 184,
    colorDark: "#000000", colorLight: "#ffffff", correctLevel: QRCode.CorrectLevel.M });
}

// ---- Suggest a place ----
let picking = false, pickBox = null;

function utmEpsg(lat, lon) {
  const zone = Math.min(60, Math.floor((lon + 180) / 6) + 1);
  return (lat >= 0 ? 32600 : 32700) + zone;
}

function showBox(lat, lon) {
  const dLat = BOX_KM / 2 / 111.32, dLon = dLat / Math.cos(lat * Math.PI / 180);
  const b = [[lat - dLat, lon - dLon], [lat + dLat, lon + dLon]];
  if (pickBox) pickBox.setBounds(b);
  else pickBox = L.rectangle(b, { color: "#0a7bbb", weight: 2, dashArray: "6 4", fill: false }).addTo(map);
}

function setPicking(on) {
  picking = on;
  $("sg-pick").setAttribute("aria-pressed", on);
  $("sg-pick").textContent = tr(on ? "suggest.picking" : "suggest.pick");
  $("map").classList.toggle("picking", on);
}

function seasonWindow(season, lat) {
  // A recent year's window for the season (northern/southern hemisphere aware).
  const north = lat >= 0;
  const w = { Spring: ["03-01", "05-31"], Summer: ["06-01", "08-31"],
              Autumn: ["09-01", "11-30"], Winter: ["12-01", "02-28"] };
  const flip = { Spring: "Autumn", Autumn: "Spring", Summer: "Winter", Winter: "Summer" };
  const s = season ? (north ? season : flip[season]) : null;
  if (!s) return ["2024-04-01", "2024-10-31"];
  const [a, b] = w[s];
  return s === "Winter" ? [`2023-${a}`, `2024-${b}`] : [`2024-${a}`, `2024-${b}`];
}

function setupSuggest() {
  $("sg-pick").addEventListener("click", () => setPicking(!picking));
  map.on("click", (e) => {
    if (!picking) return;
    $("sg-lat").value = e.latlng.lat.toFixed(4);
    $("sg-lon").value = (((e.latlng.lng + 540) % 360) - 180).toFixed(4);
    showBox(+$("sg-lat").value, +$("sg-lon").value);
    setPicking(false);
  });
  for (const id of ["sg-lat", "sg-lon"]) {
    $(id).addEventListener("change", () => {
      const lat = parseFloat($("sg-lat").value), lon = parseFloat($("sg-lon").value);
      if (Number.isFinite(lat) && Number.isFinite(lon)) showBox(lat, lon);
    });
  }
  $("suggest-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = $("sg-name").value.trim();
    const lat = parseFloat($("sg-lat").value), lon = parseFloat($("sg-lon").value);
    const err = !name ? tr("suggest.errName")
      : !(lat >= -80 && lat <= 84) || !(lon >= -180 && lon <= 180) ? tr("suggest.errLoc") : "";
    $("sg-error").textContent = err;
    $("sg-error").hidden = !err;
    if (err) return;
    const season = $("sg-season").value, note = $("sg-note").value.trim();
    const [start, end] = seasonWindow(season, lat);
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 30) || "place";
    const body = [
      `**Place:** ${name}`,
      `**Location:** ${lat.toFixed(4)}, ${lon.toFixed(4)} ` +
        `([map](https://www.openstreetmap.org/?mlat=${lat.toFixed(4)}&mlon=${lon.toFixed(4)}#map=12/${lat.toFixed(4)}/${lon.toFixed(4)}))`,
      `**Season:** ${season || "any"}`,
      note ? `**Why:** ${note}` : "",
      "",
      "<details><summary>For the maintainers</summary>",
      "",
      "```bash",
      `python make_region.py --lat ${lat.toFixed(4)} --lon ${lon.toFixed(4)} --crs EPSG:${utmEpsg(lat, lon)} \\`,
      `    --start ${start} --end ${end} --primary-cloud 0.01 0.30 --target-cloud 0.10 \\`,
      `    --workdir work/${slug}`,
      "```",
      "</details>",
    ].filter((l, i, arr) => l !== "" || arr[i - 1] !== "").join("\n");
    const url = `${SUGGEST_ISSUE_URL}?title=${encodeURIComponent("CloudPeel place suggestion: " + name)}` +
      `&body=${encodeURIComponent(body)}`;
    window.open(url, "_blank", "noopener");
  });
}

$("copy-cite").addEventListener("click", async (e) => {
  const text = document.querySelector(".cite p").textContent.replace(/\s+/g, " ").trim();
  try { await navigator.clipboard.writeText(text); e.target.textContent = tr("cite.copied"); }
  catch { e.target.textContent = tr("cite.select"); }
});

init().catch((err) => {
  document.body.insertAdjacentHTML("afterbegin",
    `<p style="padding:12px;background:#fee;color:#900">${tr("error.load", { err })}</p>`);
});
