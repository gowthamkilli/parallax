// Judge console: click-to-place enemy, category select, run+animate, event log.
// Map extent is fixed ENU meters; SVG viewBox is 800x800 with a 40px margin.

const EXTENT_M = 700;      // map covers [-EXTENT_M, +EXTENT_M] in both E and N
const MARGIN_PX = 40;
const VIEW_PX = 800;
const PLOT_PX = VIEW_PX - 2 * MARGIN_PX;

const CATEGORIES = [
  { key: "inside_cone", label: "Inside cone" },
  { key: "edge", label: "Edge" },
  { key: "outside_cone", label: "Outside cone" },
];

const svg = document.getElementById("map");
const catbtns = document.getElementById("catbtns");
const runBtn = document.getElementById("runBtn");
const statusEl = document.getElementById("status");
const logBody = document.getElementById("logBody");

let squad = [];
let centroid = { e: 0, n: 0 };
let enemyEnu = null;      // {e, n} once placed
let selectedCategory = null;
let running = false;
let lastLogTimestamp = null;

function enuToPx(e, n) {
  const x = MARGIN_PX + (e + EXTENT_M) / (2 * EXTENT_M) * PLOT_PX;
  const y = MARGIN_PX + (EXTENT_M - n) / (2 * EXTENT_M) * PLOT_PX;
  return [x, y];
}

function pxToEnu(x, y) {
  const e = (x - MARGIN_PX) / PLOT_PX * (2 * EXTENT_M) - EXTENT_M;
  const n = EXTENT_M - (y - MARGIN_PX) / PLOT_PX * (2 * EXTENT_M);
  return { e: Math.max(-EXTENT_M, Math.min(EXTENT_M, e)),
           n: Math.max(-EXTENT_M, Math.min(EXTENT_M, n)) };
}

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

function drawGrid() {
  const g = svgEl("g", {});
  // range rings every 100m
  for (let r = 100; r <= EXTENT_M; r += 100) {
    const [cx, cy] = enuToPx(0, 0);
    const [ex] = enuToPx(r, 0);
    g.appendChild(svgEl("circle", {
      cx, cy, r: ex - cx, fill: "none", stroke: "#1f2d37", "stroke-width": 1,
    }));
  }
  // N/E axes through the squad centroid
  const [ccx, ccy] = enuToPx(0, 0);
  g.appendChild(svgEl("line", { x1: MARGIN_PX, y1: ccy, x2: VIEW_PX - MARGIN_PX, y2: ccy,
                                stroke: "#1f2d37", "stroke-width": 1 }));
  g.appendChild(svgEl("line", { x1: ccx, y1: MARGIN_PX, x2: ccx, y2: VIEW_PX - MARGIN_PX,
                                stroke: "#1f2d37", "stroke-width": 1 }));
  svg.appendChild(g);
}

function drawSquad() {
  const g = svgEl("g", { id: "squadLayer" });
  for (const node of squad) {
    const [x, y] = enuToPx(node.e, node.n);
    g.appendChild(svgEl("polygon", {
      points: `${x},${y - 9} ${x - 8},${y + 6} ${x + 8},${y + 6}`,
      fill: "#4aa3ff", stroke: "white", "stroke-width": 0.8,
    }));
    const label = svgEl("text", { x: x + 11, y: y + 4, fill: "#4aa3ff", "font-size": 13,
                                  "font-family": "monospace" });
    label.textContent = `N${node.node_id}`;
    g.appendChild(label);
  }
  svg.appendChild(g);
}

let enemyLayer = null;
let animLayer = null;

function drawEnemyMarker(e, n) {
  if (enemyLayer) enemyLayer.remove();
  enemyLayer = svgEl("g", { id: "enemyLayer" });
  const [x, y] = enuToPx(e, n);
  enemyLayer.appendChild(svgEl("circle", { cx: x, cy: y, r: 7, fill: "#ff4d5e",
                                           stroke: "white", "stroke-width": 1 }));
  const label = svgEl("text", { x: x + 11, y: y - 8, fill: "#ff4d5e", "font-size": 13,
                                "font-family": "monospace" });
  label.textContent = `ENEMY (${e.toFixed(0)}, ${n.toFixed(0)})`;
  enemyLayer.appendChild(label);
  svg.appendChild(enemyLayer);
}

function clientToSvgPoint(evt) {
  const pt = svg.createSVGPoint();
  pt.x = evt.clientX;
  pt.y = evt.clientY;
  const ctm = svg.getScreenCTM().inverse();
  return pt.matrixTransform(ctm);
}

function updateRunEnabled() {
  runBtn.disabled = running || enemyEnu === null || selectedCategory === null;
}

function renderCategoryButtons() {
  catbtns.innerHTML = "";
  for (const cat of CATEGORIES) {
    const btn = document.createElement("button");
    btn.textContent = cat.label;
    btn.onclick = () => {
      selectedCategory = cat.key;
      for (const c of catbtns.children) c.classList.remove("active");
      btn.classList.add("active");
      updateRunEnabled();
    };
    catbtns.appendChild(btn);
  }
}

function animateShot(fromE, fromN, toE, toN, durationMs) {
  return new Promise((resolve) => {
    if (animLayer) animLayer.remove();
    animLayer = svgEl("g", { id: "animLayer" });
    const line = svgEl("line", { stroke: "#ff4d5e", "stroke-width": 2.5, "stroke-linecap": "round" });
    animLayer.appendChild(line);
    svg.appendChild(animLayer);

    const [x1, y1] = enuToPx(fromE, fromN);
    const [x2, y2] = enuToPx(toE, toN);
    const t0 = performance.now();

    function step(now) {
      const frac = Math.min(1, (now - t0) / durationMs);
      const cx = x1 + (x2 - x1) * frac;
      const cy = y1 + (y2 - y1) * frac;
      line.setAttribute("x1", x1); line.setAttribute("y1", y1);
      line.setAttribute("x2", cx); line.setAttribute("y2", cy);
      if (frac < 1) {
        requestAnimationFrame(step);
      } else {
        setTimeout(() => { if (animLayer) { animLayer.remove(); animLayer = null; } }, 200);
        resolve();
      }
    }
    requestAnimationFrame(step);
  });
}

async function runScenario() {
  if (enemyEnu === null || selectedCategory === null || running) return;
  running = true;
  updateRunEnabled();
  statusEl.textContent = "Firing...";

  await animateShot(enemyEnu.e, enemyEnu.n, centroid.e, centroid.n, 1200);

  statusEl.textContent = "Running pipeline...";
  try {
    const resp = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ e: enemyEnu.e, n: enemyEnu.n, category: selectedCategory }),
    });
    const result = await resp.json();
    if (result.error) {
      statusEl.textContent = `Error: ${result.error}`;
    } else {
      statusEl.textContent = "Done. Soldier screen updated.";
      refreshLog();
    }
  } catch (err) {
    statusEl.textContent = `Request failed: ${err}`;
  }
  running = false;
  updateRunEnabled();
}

function renderLog(eventLog) {
  logBody.innerHTML = "";
  eventLog.forEach((ev, i) => {
    const tr = document.createElement("tr");
    if (i === 0) tr.className = "newest";
    const t = new Date(ev.timestamp * 1000).toLocaleTimeString();
    const track = ev.track;
    const rangeMethod = track ? track.range_method : "-";
    const range = track && track.range_m !== null ? `${track.range_m.toFixed(0)} m` : "--";
    const conf = track ? track.confidence.toFixed(2) : "-";
    const disposition = track
      ? (track.alert
          ? '<span class="badge alert">ALERT</span>'
          : '<span class="badge none">below threshold</span>')
      : '<span class="badge none">no track</span>';
    tr.innerHTML = `
      <td>${eventLog.length - i}</td>
      <td>${t}</td>
      <td>${ev.category_label}</td>
      <td>${ev.enemy_enu[0].toFixed(0)}, ${ev.enemy_enu[1].toFixed(0)}</td>
      <td>${ev.n_reports}</td>
      <td>${rangeMethod}</td>
      <td>${range}</td>
      <td>${conf}</td>
      <td>${disposition}</td>`;
    logBody.appendChild(tr);
  });
}

async function refreshLog() {
  const resp = await fetch("/api/state");
  const st = await resp.json();
  const top = st.event_log.length ? st.event_log[0].timestamp : null;
  if (top !== lastLogTimestamp) {
    lastLogTimestamp = top;
    renderLog(st.event_log);
  }
}

async function init() {
  const resp = await fetch("/api/squad");
  const data = await resp.json();
  squad = data.nodes;
  centroid = data.centroid;

  drawGrid();
  drawSquad();
  renderCategoryButtons();

  svg.addEventListener("click", (evt) => {
    if (running) return;
    const pt = clientToSvgPoint(evt);
    enemyEnu = pxToEnu(pt.x, pt.y);
    drawEnemyMarker(enemyEnu.e, enemyEnu.n);
    statusEl.textContent = `Enemy placed at (${enemyEnu.e.toFixed(0)}, ${enemyEnu.n.toFixed(0)}) m.`;
    updateRunEnabled();
  });

  runBtn.addEventListener("click", runScenario);

  refreshLog();
  setInterval(refreshLog, 500);
}

init();
