// Smoke test: drives the real Three view code against a recording mock of THREE.
// It cannot prove the pixels are right, but it catches typos, wrong flow and exceptions in the render path.
import test from "node:test";
import assert from "node:assert/strict";
import { SceneCore } from "../src/scene/core.js";
import { createThreeView } from "../src/scene/threeView.js";

function mockThree() {
  const calls = [];
  const cls = (name, extra = {}) =>
    class {
      constructor(...a) { this.args = a; this.name = name; this.position = { x: 0, y: 0, z: 0, set(x, y, z) { this.x = x; this.y = y; this.z = z; } }; this.rotation = { x: 0, y: 0 }; this.scale = { setScalar() {} };
        this.uniforms = a[0] && a[0].uniforms; this.material = a[1]; this.geometry = a[0]; this.userData = {}; this.children = []; Object.assign(this, extra); calls.push(name); }
      add(c) { this.children.push(c); } remove() {} dispose() {} lookAt() {} updateProjectionMatrix() {} setAttribute() {} setDrawRange() {} setUsage() {} render() {}
      getContext() { return {}; } setClearColor() {} setPixelRatio() {} setSize() {} forceContextLoss() {}
    };
  const T = {};
  for (const n of ["WebGLRenderer", "Scene", "PerspectiveCamera", "Group", "ShaderMaterial", "BufferGeometry", "BufferAttribute", "Points", "RingGeometry", "Mesh", "MeshBasicMaterial", "LineBasicMaterial", "LineSegments"]) T[n] = cls(n);
  T.AdditiveBlending = 2; T.DoubleSide = 2; T.DynamicDrawUsage = 35048;
  T.calls = calls;
  return T;
}

test("three view builds, renders and disposes without throwing", () => {
  const THREE = mockThree();
  const canvas = { style: {} };
  globalThis.window = { devicePixelRatio: 2 };
  const core = new SceneCore();
  const view = createThreeView(THREE, canvas, core);
  view.resize(1200, 800);
  core.highlight([...core.g.index.keys()].slice(0, 5));
  core.whisper();
  for (let i = 0; i < 30; i++) { core.step(0.016); view.render(); }
  core.setGraph(null);
  view.rebuild();
  view.render();
  view.dispose();
  assert.ok(THREE.calls.includes("Points") && THREE.calls.includes("LineSegments") && THREE.calls.includes("Mesh"));
});
