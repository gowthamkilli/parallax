// Soldier display: bearing dial + readout banner only. Polls /api/state and
// redraws only when the latest_result's timestamp actually changes.

const CX = 400, CY = 400, R = 340;
const COLOR_ALERT = "#ff4d5e";
const COLOR_ACCENT = "#00d9a3";
const COLOR_DIM = "#5d7180";
const COLOR_FG = "#c8d6de";

const dial = document.getElementById("dial");
const fAzimuth = document.getElementById("fAzimuth");
const fRange = document.getElementById("fRange");
const fConf = document.getElementById("fConf");

let lastTimestamp = null;

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

// compass bearing (0=N, clockwise) -> screen point at radius r from centre
function bearingPoint(bearingDeg, r) {
  const rad = bearingDeg * Math.PI / 180;
  return [CX + r * Math.sin(rad), CY - r * Math.cos(rad)];
}

function drawDialBase(svg) {
  svg.innerHTML = "";
  // range rings
  for (let i = 1; i <= 4; i++) {
    svg.appendChild(svgEl("circle", {
      cx: CX, cy: CY, r: (R * i) / 4, fill: "none", stroke: "#1f2d37", "stroke-width": 1,
    }));
  }
  // cardinal + 30-degree ticks
  for (let b = 0; b < 360; b += 30) {
    const [x1, y1] = bearingPoint(b, R);
    const [x2, y2] = bearingPoint(b, R - 14);
    svg.appendChild(svgEl("line", { x1, y1, x2, y2, stroke: "#1f2d37", "stroke-width": 1.5 }));
    const [lx, ly] = bearingPoint(b, R + 22);
    const label = svgEl("text", {
      x: lx, y: ly + 4, fill: COLOR_DIM, "font-size": 14, "font-family": "monospace",
      "text-anchor": "middle",
    });
    label.textContent = b === 0 ? "N" : b === 90 ? "E" : b === 180 ? "S" : b === 270 ? "W" : b;
    svg.appendChild(label);
  }
  svg.appendChild(svgEl("circle", { cx: CX, cy: CY, r: R, fill: "none", stroke: "#1f2d37", "stroke-width": 2 }));
}

function render(latest) {
  drawDialBase(dial);

  if (!latest || !latest.track) {
    const t = svgEl("text", {
      x: CX, y: CY, fill: COLOR_DIM, "font-size": 22, "font-family": "monospace",
      "text-anchor": "middle",
    });
    t.textContent = latest ? "NO CONTACT" : "AWAITING CONTACT";
    dial.appendChild(t);
    fAzimuth.textContent = "--";
    fRange.textContent = "--";
    fConf.textContent = "--";
    fAzimuth.style.color = fRange.style.color = fConf.style.color = COLOR_FG;
    return;
  }

  const track = latest.track;
  const color = track.alert ? COLOR_ALERT : COLOR_ACCENT;
  const hasRange = track.range_m !== null && track.range_m !== undefined;
  const needleR = hasRange ? Math.min(R, R * Math.min(track.range_m, 700) / 700) : R;

  // 1-sigma bearing wedge, if we have a sigma
  if (track.bearing_sigma_deg) {
    const sigma = Math.max(track.bearing_sigma_deg, 1.0);
    const steps = 16;
    let d = `M ${CX} ${CY} `;
    for (let i = 0; i <= steps; i++) {
      const b = track.bearing_deg - sigma + (2 * sigma * i) / steps;
      const [x, y] = bearingPoint(b, needleR);
      d += `L ${x} ${y} `;
    }
    d += "Z";
    dial.appendChild(svgEl("path", { d, fill: color, opacity: 0.15, stroke: "none" }));
  }

  // needle
  const [nx, ny] = bearingPoint(track.bearing_deg, needleR);
  dial.appendChild(svgEl("line", {
    x1: CX, y1: CY, x2: nx, y2: ny, stroke: color, "stroke-width": 4,
    "stroke-dasharray": hasRange ? "none" : "10,8",
    opacity: hasRange ? 0.95 : 0.6,
  }));
  if (hasRange) {
    dial.appendChild(svgEl("circle", { cx: nx, cy: ny, r: 9, fill: color, stroke: "white", "stroke-width": 1.5 }));
  } else {
    const t = svgEl("text", {
      x: CX, y: CY + R + 55, fill: color, "font-size": 14, "font-family": "monospace",
      "text-anchor": "middle",
    });
    t.textContent = "BEARING ONLY";
    dial.appendChild(t);
  }

  fAzimuth.textContent = `${track.bearing_deg.toFixed(1)}°`;
  fRange.textContent = hasRange ? `${track.range_m.toFixed(0)} m` : "NO FIX";
  fConf.textContent = track.confidence.toFixed(2);
  fAzimuth.style.color = color;
  fRange.style.color = hasRange ? color : COLOR_DIM;
  fConf.style.color = color;
}

async function poll() {
  try {
    const resp = await fetch("/api/state");
    const st = await resp.json();
    const latest = st.latest_result;
    const ts = latest ? latest.timestamp : null;
    if (ts !== lastTimestamp) {
      lastTimestamp = ts;
      render(latest);
    }
  } catch (err) {
    // transient poll failure -- just retry next tick, don't blank the display
  }
}

drawDialBase(dial);
render(null);
poll();
setInterval(poll, 500);
