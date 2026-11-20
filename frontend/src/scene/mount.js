// Mounts the animated repository map into a container element.
// Starts with the 2D view immediately, upgrades to WebGL once Three.js has loaded, and keeps the 2D view if it can't.
import { SceneCore } from "./core.js";
import { createThreeView } from "./threeView.js";
import { create2DView } from "./view2d.js";

// Tried in order: a local copy (works offline), then two CDNs. All expose the same global THREE API we use.
const THREE_SOURCES = [
  "/static/vendor/three.min.js",
  "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js",
  "https://cdn.jsdelivr.net/npm/three@0.149.0/build/three.min.js",
];

export function loadThree(sources = THREE_SOURCES, timeoutMs = 8000) {
  if (typeof window !== "undefined" && window.THREE) return Promise.resolve(window.THREE);
  return new Promise((resolve) => {
    let i = 0;
    const next = () => {
      if (i >= sources.length) return resolve(null);
      const s = document.createElement("script");
      s.src = sources[i++];
      s.async = true;
      const timer = setTimeout(() => {
        s.remove();
        next();
      }, timeoutMs);
      s.onload = () => {
        clearTimeout(timer);
        window.THREE ? resolve(window.THREE) : next();
      };
      s.onerror = () => {
        clearTimeout(timer);
        s.remove();
        next();
      };
      document.head.appendChild(s);
    };
    next();
  });
}

export function mountScene(container, { onMode, sources } = {}) {
  const reducedQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const small = Math.min(window.innerWidth, window.innerHeight) < 700;
  const core = new SceneCore({ lowPower: small && /Mobi|Android/i.test(navigator.userAgent), reduced: reducedQuery.matches });
  let view = null;
  let canvas = null;
  let raf = 0;
  let last = performance.now();
  let lastRender = 0;
  let destroyed = false;

  function resize() {
    if (!view) return;
    const w = container.clientWidth || window.innerWidth;
    const h = container.clientHeight || window.innerHeight;
    view.resize(w, h);
    core.needsRender = true;
  }

  function attach(kind, THREE) {
    if (view) view.dispose();
    if (canvas) canvas.remove();
    canvas = document.createElement("canvas");
    canvas.setAttribute("aria-hidden", "true");
    container.appendChild(canvas);
    view = kind === "webgl" ? createThreeView(THREE, canvas, core) : create2DView(canvas, core);
    if (onMode) onMode(view.kind);
    resize();
  }

  function frame(t) {
    raf = requestAnimationFrame(frame);
    const dt = (t - last) / 1000;
    last = t;
    if (core.lowPower && t - lastRender < 33) return; // 30fps on weak phones
    if (!core.reduced || core.needsRender) {
      core.step(dt);
      view.render();
      core.needsRender = false;
      lastRender = t;
    }
  }

  function start() {
    if (!raf && !destroyed) {
      last = performance.now();
      raf = requestAnimationFrame(frame);
    }
  }
  function stop() {
    cancelAnimationFrame(raf);
    raf = 0;
  }

  const onVisibility = () => (document.hidden ? stop() : start());
  const onPointer = (e) => core.setPointer((e.clientX / window.innerWidth) * 2 - 1, (e.clientY / window.innerHeight) * 2 - 1);
  const onReduced = () => {
    core.reduced = reducedQuery.matches;
    core.needsRender = true;
    if (!core.reduced) {
      core.setGraph(core._graphSrc || null);
      view.rebuild();
    }
  };
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("pointermove", onPointer, { passive: true });
  reducedQuery.addEventListener && reducedQuery.addEventListener("change", onReduced);
  const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
  ro ? ro.observe(container) : window.addEventListener("resize", resize);

  attach("2d");
  start();
  loadThree(sources).then((THREE) => {
    if (destroyed || !THREE) return;
    try {
      attach("webgl", THREE);
    } catch (err) {
      console.warn("WebGL unavailable, keeping the 2D view:", err);
      attach("2d");
    }
  });

  return {
    setGraph(graph) {
      core._graphSrc = graph;
      core.setGraph(graph);
      view.rebuild();
    },
    whisper: () => core.whisper(),
    setBusy: (b) => core.setBusy(b),
    highlight: (paths) => core.highlight(paths),
    hover: (path) => core.hover(path),
    setShift: (f) => core.setShift(f),
    mode: () => (view ? view.kind : "none"),
    core,
    destroy() {
      destroyed = true;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pointermove", onPointer);
      reducedQuery.removeEventListener && reducedQuery.removeEventListener("change", onReduced);
      ro ? ro.disconnect() : window.removeEventListener("resize", resize);
      if (view) view.dispose();
      if (canvas) canvas.remove();
    },
  };
}
