// WebGL renderer (Three.js, global build r128-r149). Thin: all state lives in SceneCore.
import { ease } from "./core.js";

const VERT = `
attribute float aSize;
attribute vec3 aColor;
attribute float aGlow;
uniform float uTime;
uniform float uScale;
varying vec3 vColor;
varying float vGlow;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  float tw = 1.0 + 0.14 * sin(uTime * 1.4 + position.x * 3.1 + position.y * 1.7);
  float g = clamp(aGlow, 0.0, 1.0);
  vGlow = g;
  vColor = mix(aColor, vec3(1.0, 0.93, 0.70), g * 0.75);
  gl_PointSize = aSize * tw * (1.0 + g * 1.8) * uScale / max(0.1, -mv.z);
  gl_Position = projectionMatrix * mv;
}`;

const FRAG = `
uniform float uDim;
uniform float uAlpha;
varying vec3 vColor;
varying float vGlow;
void main() {
  float d = length(gl_PointCoord - vec2(0.5));
  if (d > 0.5) discard;
  float soft = smoothstep(0.5, 0.0, d);
  float halo = pow(soft, 2.2);
  float dimmed = mix(uDim, 1.0, vGlow);
  float a = (halo * 0.9 + (d < 0.12 ? 0.6 : 0.0)) * dimmed * uAlpha;
  gl_FragColor = vec4(vColor * (0.55 + 0.9 * vGlow), a);
}`;

export function createThreeView(THREE, canvas, core) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !core.lowPower, alpha: true, powerPreference: "high-performance" });
  if (!renderer.getContext()) throw new Error("no webgl context");
  renderer.setClearColor(0x000000, 0);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 300);
  const world = new THREE.Group();
  scene.add(world);

  const shared = { uTime: { value: 0 }, uScale: { value: 800 } };
  const mk = (uDim, uAlpha) =>
    new THREE.ShaderMaterial({
      uniforms: { uTime: shared.uTime, uScale: shared.uScale, uDim: { value: uDim }, uAlpha: { value: uAlpha } },
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
  const starMat = mk(1, 1);
  const dustMat = mk(1, 0.5);
  const coreMat = mk(1, 0);

  function points(mat, pos, size, color, glow) {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
    geo.setAttribute("aColor", new THREE.BufferAttribute(color, 3));
    const ga = new THREE.BufferAttribute(glow, 1);
    if (THREE.DynamicDrawUsage !== undefined && ga.setUsage) ga.setUsage(THREE.DynamicDrawUsage);
    geo.setAttribute("aGlow", ga);
    const p = new THREE.Points(geo, mat);
    p.frustumCulled = false;
    return { obj: p, geo, glowAttr: ga };
  }

  // static layers: dust, query star
  const dust = points(dustMat, core.dust.pos, core.dust.size, core.dust.color, new Float32Array(core.dust.n));
  scene.add(dust.obj);
  const star = points(coreMat, new Float32Array([0, 0, 0]), new Float32Array([1.3]), new Float32Array([1, 0.82, 0.4]), new Float32Array([1]));
  world.add(star.obj);

  // ripples (billboarded rings)
  const rippleGeo = new THREE.RingGeometry(0.97, 1, 128);
  const ripples = [0, 1, 2].map(() => {
    const m = new THREE.Mesh(
      rippleGeo,
      new THREE.MeshBasicMaterial({ color: 0xf0c75e, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending })
    );
    m.visible = false;
    scene.add(m);
    return m;
  });

  // beams (filaments from the query star to cited files)
  const beamPos = new Float32Array(12 * 6);
  const beamGeo = new THREE.BufferGeometry();
  const beamAttr = new THREE.BufferAttribute(beamPos, 3);
  beamGeo.setAttribute("position", beamAttr);
  beamGeo.setDrawRange(0, 0);
  const beamMat = new THREE.LineBasicMaterial({ color: 0xf0c75e, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
  const beams = new THREE.LineSegments(beamGeo, beamMat);
  beams.frustumCulled = false;
  world.add(beams);

  // rebuilt whenever the repository graph changes
  let stars = null;
  let lines = null;
  let lineColors = null;
  let lineAttr = null;

  function disposeDynamic() {
    for (const o of [stars && stars.obj, lines]) {
      if (!o) continue;
      world.remove(o);
      o.geometry.dispose();
      if (o.material && o.material !== starMat) o.material.dispose();
    }
    stars = lines = lineColors = lineAttr = null;
  }

  function rebuild() {
    disposeDynamic();
    const g = core.g;
    stars = points(starMat, g.pos, g.size, g.color, core.glow);
    world.add(stars.obj);
    const E = g.edges.length / 2;
    const lp = new Float32Array(E * 6);
    lineColors = new Float32Array(E * 6);
    for (let e = 0; e < E; e++) {
      const a = g.edges[e * 2], b = g.edges[e * 2 + 1];
      lp.set(g.pos.subarray(a * 3, a * 3 + 3), e * 6);
      lp.set(g.pos.subarray(b * 3, b * 3 + 3), e * 6 + 3);
    }
    const lg = new THREE.BufferGeometry();
    lg.setAttribute("position", new THREE.BufferAttribute(lp, 3));
    lineAttr = new THREE.BufferAttribute(lineColors, 3);
    lg.setAttribute("color", lineAttr);
    lines = new THREE.LineSegments(
      lg,
      new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 1, blending: THREE.AdditiveBlending, depthWrite: false })
    );
    lines.frustumCulled = false;
    world.add(lines);
    core.needsRender = true;
  }

  function updateEdgeColors() {
    const E = core.g.edges.length / 2;
    for (let e = 0; e < E; e++) {
      const { base, lit } = core.edgeBrightness(e);
      const l = Math.min(1, lit);
      const b = base + 0.7 * l;
      const o = e * 6;
      const r = (0.42 * (1 - l) + 1.0 * l) * b, gg = (0.52 * (1 - l) + 0.8 * l) * b, bl = (0.88 * (1 - l) + 0.36 * l) * b;
      lineColors[o] = lineColors[o + 3] = r;
      lineColors[o + 1] = lineColors[o + 4] = gg;
      lineColors[o + 2] = lineColors[o + 5] = bl;
    }
    lineAttr.needsUpdate = true;
  }

  function resize(w, h) {
    const dpr = Math.min(window.devicePixelRatio || 1, core.lowPower ? 1.5 : 2);
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    shared.uScale.value = (h * dpr) / (2 * Math.tan((camera.fov * Math.PI) / 360));
    camera.userData.portrait = w / h < 0.85;
  }

  function render() {
    shared.uTime.value = core.time;
    const z = core.camZ * core.camScale * (camera.userData.portrait ? 1.3 : 1);
    camera.position.set(core.pointerS.x * 2.2, -core.pointerS.y * 1.4, z);
    camera.lookAt(0, 0, 0);
    const halfW = z * Math.tan((camera.fov * Math.PI) / 360) * camera.aspect;
    world.position.x = core.shiftS * halfW;
    world.rotation.y = core.yaw;
    world.rotation.x = core.tilt + core.pointerS.y * 0.1;
    starMat.uniforms.uDim.value = core.dim;
    coreMat.uniforms.uAlpha.value = core.beam.fade;

    stars.glowAttr.needsUpdate = true;
    updateEdgeColors();

    // beams grow outwards from the query star
    const targets = core.beam.draw;
    const p = ease(core.beam.p);
    for (let k = 0; k < targets.length; k++) {
      const i = targets[k] * 3;
      beamPos.set([0, 0, 0, core.g.pos[i] * p, core.g.pos[i + 1] * p, core.g.pos[i + 2] * p], k * 6);
    }
    beamGeo.setDrawRange(0, targets.length * 2);
    beamAttr.needsUpdate = true;
    beamMat.opacity = 0.65 * core.beam.fade;

    for (let r = 0; r < ripples.length; r++) {
      const rp = core.ripples[r];
      const m = ripples[r];
      if (!rp) {
        m.visible = false;
        continue;
      }
      const t = rp.age / rp.dur;
      m.visible = true;
      m.position.set(world.position.x, 0, 0);
      m.scale.setScalar(1.5 + ease(t) * 30);
      m.material.opacity = 0.5 * Math.pow(1 - t, 1.6);
      m.lookAt(camera.position);
    }
    renderer.render(scene, camera);
  }

  function dispose() {
    disposeDynamic();
    for (const o of [dust, star]) o.geo.dispose();
    beamGeo.dispose();
    rippleGeo.dispose();
    ripples.forEach((m) => m.material.dispose());
    beamMat.dispose();
    [starMat, dustMat, coreMat].forEach((m) => m.dispose());
    renderer.dispose();
    if (renderer.forceContextLoss) renderer.forceContextLoss();
  }

  rebuild();
  return { kind: "webgl", resize, render, rebuild, dispose };
}
