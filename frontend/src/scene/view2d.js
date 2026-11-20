// Canvas 2D renderer: same scene, no WebGL needed. Shown instantly while Three.js loads, and kept if WebGL is unavailable.
import { ease } from "./core.js";

const TAN = Math.tan((55 * Math.PI) / 360);

export function create2DView(canvas, core) {
  const ctx = canvas.getContext("2d");
  let W = 1, H = 1, dpr = 1;
  const sprites = new Map();

  function sprite(rgb) {
    const key = rgb.map((v) => Math.round(v * 20)).join(",");
    if (sprites.has(key)) return sprites.get(key);
    const s = document.createElement("canvas");
    s.width = s.height = 64;
    const c = s.getContext("2d");
    const [r, g, b] = rgb.map((v) => Math.round(v * 255));
    const grd = c.createRadialGradient(32, 32, 0, 32, 32, 32);
    grd.addColorStop(0, `rgba(${r},${g},${b},1)`);
    grd.addColorStop(0.18, `rgba(${r},${g},${b},0.8)`);
    grd.addColorStop(0.45, `rgba(${r},${g},${b},0.22)`);
    grd.addColorStop(1, `rgba(${r},${g},${b},0)`);
    c.fillStyle = grd;
    c.fillRect(0, 0, 64, 64);
    sprites.set(key, s);
    return s;
  }
  const GOLD = [1, 0.84, 0.45];

  function resize(w, h) {
    dpr = Math.min(window.devicePixelRatio || 1, core.lowPower ? 1.5 : 2);
    W = w;
    H = h;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
  }

  function render() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = "lighter";

    const portrait = W / H < 0.85;
    const camZ = core.camZ * core.camScale * (portrait ? 1.3 : 1);
    const f = H / 2 / TAN;
    const cy = Math.cos(core.yaw), sy = Math.sin(core.yaw);
    const tilt = core.tilt + core.pointerS.y * 0.1, ct = Math.cos(tilt), st = Math.sin(tilt);
    const camX = core.pointerS.x * 2.2, camY = -core.pointerS.y * 1.4;
    const offX = W / 2 + core.shiftS * (W / 2);
    const out = [0, 0, 0];
    const project = (x, y, z, rotate = true) => {
      let rx = x, ry = y, rz = z;
      if (rotate) {
        rx = x * cy + z * sy;
        rz = -x * sy + z * cy;
        const y2 = y * ct - rz * st;
        rz = y * st + rz * ct;
        ry = y2;
      }
      const depth = camZ - rz;
      const k = f / Math.max(1, depth);
      out[0] = offX + (rx - camX) * k;
      out[1] = H / 2 - (ry - camY) * k;
      out[2] = k;
      return out;
    };

    // dust (rotates with the sky but not with the repository's offset)
    const D = core.dust;
    for (let i = 0; i < D.n; i++) {
      const p = project(D.pos[i * 3], D.pos[i * 3 + 1], D.pos[i * 3 + 2]);
      const x = p[0] - (core.shiftS * (W / 2)), y = p[1];
      if (x < -5 || x > W + 5 || y < -5 || y > H + 5) continue;
      const tw = 0.5 + 0.5 * Math.sin(core.time * 1.2 + i);
      ctx.globalAlpha = 0.2 + 0.25 * tw;
      ctx.fillStyle = "#cfd0ee";
      ctx.beginPath();
      ctx.arc(x, y, Math.min(1.6, Math.max(0.5, D.size[i] * p[2] * 0.22)), 0, Math.PI * 2);
      ctx.fill();
    }

    // project all stars once
    const g = core.g;
    const sx = new Float32Array(g.n), sy2 = new Float32Array(g.n), sk = new Float32Array(g.n);
    for (let i = 0; i < g.n; i++) {
      const p = project(g.pos[i * 3], g.pos[i * 3 + 1], g.pos[i * 3 + 2]);
      sx[i] = p[0];
      sy2[i] = p[1];
      sk[i] = p[2];
    }

    // edges: one path for the quiet ones, individual strokes for lit ones
    const E = g.edges.length / 2;
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.16 * (0.55 + 0.45 * core.dim);
    ctx.strokeStyle = "#8da0ea";
    ctx.beginPath();
    const litEdges = [];
    for (let e = 0; e < E; e++) {
      const a = g.edges[e * 2], b = g.edges[e * 2 + 1];
      if (Math.max(core.glow[a], core.glow[b]) > 0.2) {
        litEdges.push(e);
        continue;
      }
      ctx.moveTo(sx[a], sy2[a]);
      ctx.lineTo(sx[b], sy2[b]);
    }
    ctx.stroke();
    ctx.strokeStyle = "#f4cf6a";
    for (const e of litEdges) {
      const a = g.edges[e * 2], b = g.edges[e * 2 + 1];
      ctx.globalAlpha = 0.15 + 0.5 * Math.min(1, Math.max(core.glow[a], core.glow[b]));
      ctx.beginPath();
      ctx.moveTo(sx[a], sy2[a]);
      ctx.lineTo(sx[b], sy2[b]);
      ctx.stroke();
    }

    // stars
    for (let i = 0; i < g.n; i++) {
      const gl = Math.min(1, core.glow[i]);
      const dim = core.dim + (1 - core.dim) * gl;
      const tw = 1 + 0.14 * Math.sin(core.time * 1.4 + g.pos[i * 3] * 3.1 + g.pos[i * 3 + 1] * 1.7);
      const rad = g.size[i] * tw * (1 + gl * 1.8) * sk[i] * 0.9;
      const col = gl > 0.05 ? [g.color[i * 3] * (1 - gl * 0.7) + 1 * gl * 0.7, g.color[i * 3 + 1] * (1 - gl * 0.7) + 0.93 * gl * 0.7, g.color[i * 3 + 2] * (1 - gl * 0.7) + 0.7 * gl * 0.7] : [g.color[i * 3], g.color[i * 3 + 1], g.color[i * 3 + 2]];
      ctx.globalAlpha = Math.min(1, 0.95 * dim);
      ctx.drawImage(sprite(col), sx[i] - rad, sy2[i] - rad, rad * 2, rad * 2);
    }

    // beams from the query star
    const o = project(0, 0, 0);
    const ox = o[0], oy = o[1];
    if (core.beam.fade > 0.01) {
      const p = ease(core.beam.p);
      ctx.strokeStyle = "#f0c75e";
      ctx.lineWidth = 1.2;
      ctx.globalAlpha = 0.7 * core.beam.fade;
      ctx.beginPath();
      for (const i of core.beam.draw) {
        ctx.moveTo(ox, oy);
        ctx.lineTo(ox + (sx[i] - ox) * p, oy + (sy2[i] - oy) * p);
      }
      ctx.stroke();
      ctx.globalAlpha = core.beam.fade;
      const r = 20 * o[2] * 0.4;
      ctx.drawImage(sprite(GOLD), ox - r, oy - r, r * 2, r * 2);
    }

    // ripples
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#f0c75e";
    for (const rp of core.ripples) {
      const t = rp.age / rp.dur;
      ctx.globalAlpha = 0.45 * Math.pow(1 - t, 1.6);
      ctx.beginPath();
      ctx.arc(ox, oy, (1.5 + ease(t) * 30) * o[2], 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }

  return { kind: "2d", resize, render, rebuild() {}, dispose() {} };
}
