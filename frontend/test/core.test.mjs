import test from "node:test";
import assert from "node:assert/strict";
import { SceneCore } from "../src/scene/core.js";
import { layoutGraph, demoGraph } from "../src/scene/layout.js";

const graph = {
  nodes: [
    { path: "app/auth.py", dir: "app", lang: "python", kind: "code", lines: 60, fan_in: 2 },
    { path: "app/orders.py", dir: "app", lang: "python", kind: "code", lines: 33, fan_in: 1 },
    { path: "web/cart.js", dir: "web", lang: "javascript", kind: "code", lines: 30, fan_in: 0 },
    { path: "docs/architecture.md", dir: "docs", lang: "markdown", kind: "doc", lines: 20, fan_in: 0 },
  ],
  edges: [[0, 1]],
};

test("layout is deterministic and finite", () => {
  const a = layoutGraph(graph), b = layoutGraph(graph);
  assert.equal(a.n, 4);
  assert.deepEqual([...a.pos], [...b.pos]);
  assert.ok([...a.pos, ...a.size, ...a.color].every(Number.isFinite));
  assert.ok(a.edges.length >= 2);               // real edge kept (and proximity edges filled in)
});

test("demo graph works with no repository", () => {
  const c = new SceneCore();
  assert.ok(c.n > 50);
  assert.ok(c.camZ >= 30 && c.camZ <= 62);
});

test("highlight matches exact and suffix paths, ignores unknown", () => {
  const c = new SceneCore();
  c.setGraph(graph);
  assert.equal(c.highlight(["app/auth.py", "nope.py"]), 1);
  assert.equal(c.highlight(["auth.py"]), 1);                         // short name matches by path suffix
  assert.equal(c.highlight(["src/app/orders.py"]), 1);               // longer path ends with a known one
  assert.equal(c.highlight([]), 0);
  assert.equal(c.beam.want, false);
});

test("glow eases toward the target, dims others, draws beams", () => {
  const c = new SceneCore({ reduced: false });
  c.setGraph(graph);
  c.highlight(["app/auth.py", "web/cart.js"]);
  assert.equal(c.beam.draw.length, 2);
  for (let i = 0; i < 90; i++) c.step(0.016);
  const i = c.idxOf("app/auth.py");
  assert.ok(c.glow[i] > 0.95);
  assert.ok(c.dim < 0.4);
  assert.equal(c.beam.p, 1);
  assert.ok(c.beam.fade > 0.9);
  c.highlight([]);
  for (let i2 = 0; i2 < 120; i2++) c.step(0.016);
  assert.ok(c.glow[i] < 0.05 && c.dim > 0.95 && c.beam.fade < 0.05);
});

test("hover lights one star without highlight", () => {
  const c = new SceneCore();
  c.setGraph(graph);
  c.hover("web/cart.js");
  for (let i = 0; i < 60; i++) c.step(0.016);
  assert.ok(c.glow[c.idxOf("web/cart.js")] > 0.7);
  c.hover(null);
  for (let i = 0; i < 90; i++) c.step(0.016);
  assert.ok(c.glow[c.idxOf("web/cart.js")] < 0.05);
});

test("ripples expire; busy keeps emitting", () => {
  const c = new SceneCore();
  c.whisper();
  assert.equal(c.ripples.length, 1);
  for (let i = 0; i < 200; i++) c.step(0.016);
  assert.equal(c.ripples.length, 0);
  c.setBusy(true);
  let max = 0;
  for (let i = 0; i < 400; i++) { c.step(0.016); max = Math.max(max, c.ripples.length); }
  assert.ok(max >= 2 && max <= 3);
  c.setBusy(false);
});

test("reduced motion: no rotation or ripples, highlight applies instantly", () => {
  const c = new SceneCore({ reduced: true });
  c.setGraph(graph);
  const yaw = c.yaw;
  c.whisper();
  c.highlight(["app/auth.py"]);
  c.step(0.016);
  assert.equal(c.yaw, yaw);
  assert.equal(c.ripples.length, 0);
  assert.equal(c.glow[c.idxOf("app/auth.py")], 1);
  assert.equal(c.beam.p, 1);
});

test("large graphs are capped", () => {
  const nodes = Array.from({ length: 2000 }, (_, i) => ({ path: `d${i % 40}/f${i}.py`, dir: `d${i % 40}`, lang: "python", kind: "code", lines: 50, fan_in: 0 }));
  assert.equal(new SceneCore({ lowPower: false }).g.n <= 700, true);
  assert.equal(layoutGraph({ nodes, edges: [] }, { maxNodes: 320 }).n, 320);
});
