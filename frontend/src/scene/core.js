// Renderer-agnostic scene state. Both the Three.js view and the 2D fallback read from this,
// so behaviour (glow, ripples, beams, rotation) is identical and testable without a GPU.
import { layoutGraph, demoGraph, makeDust } from "./layout.js";

const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
export const ease = (t) => 1 - Math.pow(1 - clamp(t, 0, 1), 3);
const MAX_BEAMS = 12;

export class SceneCore {
  constructor({ lowPower = false, reduced = false } = {}) {
    this.lowPower = lowPower;
    this.reduced = reduced;
    this.time = 0;
    this.yaw = 0.6;
    this.tilt = 0.3;
    this.pointer = { x: 0, y: 0 };
    this.pointerS = { x: 0, y: 0 };
    this.camScale = 1;
    this.shift = 0; // fraction of the half-width to push the map to the right (leaves room for text on wide screens)
    this.shiftS = 0;
    this.ripples = [];
    this.busy = false;
    this._busyT = 0;
    this.beam = { draw: [], want: false, p: 1, fade: 0 };
    this.dim = 1;
    this.dimTarget = 1;
    this.hoverIdx = -1;
    this.lit = new Set();
    this.needsRender = true;
    this.dust = makeDust(lowPower ? 140 : 320);
    this.setGraph(null);
  }

  setGraph(graph) {
    this.g = layoutGraph(graph || demoGraph(), { maxNodes: this.lowPower ? 320 : 700 });
    this.n = this.g.n;
    this.glow = new Float32Array(this.n);
    this.target = new Float32Array(this.n);
    this.lit = new Set();
    this.hoverIdx = -1;
    this.beam = { draw: [], want: false, p: 1, fade: 0 };
    this.dimTarget = 1;
    this.dim = 1;
    this.camZ = clamp(this.g.radius * 2.5 + 10, 30, 62);
    this.needsRender = true;
  }

  idxOf(path) {
    if (!path) return -1;
    const m = this.g.index;
    if (m.has(path)) return m.get(path);
    for (const [p, i] of m) if (p.endsWith("/" + path) || path.endsWith("/" + p)) return i;
    return -1;
  }

  _applyTargets() {
    this.target.fill(0);
    for (const i of this.lit) this.target[i] = 1;
    if (this.hoverIdx >= 0) this.target[this.hoverIdx] = Math.max(this.target[this.hoverIdx], 0.85);
    if (this.reduced) this.glow.set(this.target);
    this.needsRender = true;
  }

  /** Ignite the stars for cited files and draw filaments to them. Returns how many matched. */
  highlight(paths) {
    this.lit = new Set();
    for (const p of paths || []) {
      const i = this.idxOf(p);
      if (i >= 0) this.lit.add(i);
    }
    const idx = [...this.lit].slice(0, MAX_BEAMS);
    this.beam.want = idx.length > 0;
    if (idx.length) {
      this.beam.draw = idx;
      this.beam.p = this.reduced ? 1 : 0;
    }
    this.dimTarget = idx.length ? 0.32 : 1;
    if (this.reduced) {
      this.dim = this.dimTarget;
      this.beam.fade = this.beam.want ? 1 : 0;
    }
    this._applyTargets();
    return this.lit.size;
  }

  hover(path) {
    this.hoverIdx = path ? this.idxOf(path) : -1;
    this._applyTargets();
  }

  whisper() {
    if (this.reduced) return;
    this.ripples.push({ age: 0, dur: 2.6 });
    if (this.ripples.length > 3) this.ripples.shift();
  }

  setBusy(b) {
    this.busy = !!b;
    this._busyT = 0.9; // first ripple shortly after starting
  }

  setPointer(x, y) {
    this.pointer.x = x;
    this.pointer.y = y;
  }

  setShift(f, scale = 1) {
    this.shift = f;
    this.camScale = scale;
    if (this.reduced) this.shiftS = f;
    this.needsRender = true;
  }

  edgeBrightness(e) {
    const a = this.g.edges[e * 2], b = this.g.edges[e * 2 + 1];
    const lit = Math.max(this.glow[a], this.glow[b]);
    return { base: 0.15 * (0.55 + 0.45 * this.dim), lit };
  }

  step(dt) {
    dt = clamp(dt, 0, 0.05);
    this.time += dt;
    const k = Math.min(1, dt * 6);
    if (this.reduced) {
      this.pointerS.x = this.pointerS.y = 0;
      this.shiftS = this.shift;
      return;
    }
    this.yaw += dt * 0.045;
    this.pointerS.x += (this.pointer.x - this.pointerS.x) * Math.min(1, dt * 2.5);
    this.pointerS.y += (this.pointer.y - this.pointerS.y) * Math.min(1, dt * 2.5);
    this.shiftS += (this.shift - this.shiftS) * Math.min(1, dt * 3);
    for (let i = 0; i < this.n; i++) this.glow[i] += (this.target[i] - this.glow[i]) * k;
    this.dim += (this.dimTarget - this.dim) * k;
    for (const r of this.ripples) r.age += dt;
    this.ripples = this.ripples.filter((r) => r.age < r.dur);
    if (this.beam.p < 1) this.beam.p = Math.min(1, this.beam.p + dt / 0.95);
    this.beam.fade += ((this.beam.want ? 1 : 0) - this.beam.fade) * Math.min(1, dt * 3);
    if (this.busy) {
      this._busyT -= dt;
      if (this._busyT <= 0) {
        this.whisper();
        this._busyT = 1.25;
      }
    }
  }
}
