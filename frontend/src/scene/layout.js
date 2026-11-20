// Turns the repository graph from /api/graph into 3D positions. Deterministic: the same repo always looks the same.

export function hash32(str) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Star colours, tuned for a deep indigo sky (rgb 0..1).
const LANG = {
  python: [0.5, 0.7, 1.0],
  javascript: [0.97, 0.63, 0.48],
  typescript: [0.97, 0.63, 0.48],
  java: [0.97, 0.63, 0.48],
  go: [0.45, 0.85, 0.85],
  rust: [0.95, 0.6, 0.5],
};
const KIND = { doc: [0.82, 0.78, 0.7], config: [0.6, 0.84, 0.79] };
const FALLBACK = [0.72, 0.65, 1.0];

export function colorFor(node) {
  return LANG[node.lang] || KIND[node.kind] || FALLBACK;
}

function groupKey(node) {
  const d = node.dir || "";
  return d ? d.split("/").slice(0, 2).join("/") : "(root)";
}

export function layoutGraph(graph, { maxNodes = 700 } = {}) {
  const nodes = (graph && graph.nodes ? graph.nodes : []).slice(0, maxNodes);
  const n = nodes.length;
  const groups = new Map();
  nodes.forEach((nd, i) => {
    const k = groupKey(nd);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(i);
  });

  // Folder cluster centres spread on a sphere (Fibonacci lattice), biggest folders first.
  const keys = [...groups.keys()].sort((a, b) => groups.get(b).length - groups.get(a).length || (a < b ? -1 : 1));
  const G = keys.length;
  const R = Math.min(16, Math.max(9, 7 + 1.7 * Math.sqrt(G)));
  const centres = new Map();
  keys.forEach((k, gi) => {
    const y = G === 1 ? 0 : 1 - (gi / (G - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const phi = gi * 2.399963229728653;
    centres.set(k, [Math.cos(phi) * r * R, y * R * 0.82, Math.sin(phi) * r * R]);
  });

  const pos = new Float32Array(n * 3);
  const size = new Float32Array(n);
  const color = new Float32Array(n * 3);
  const index = new Map();
  nodes.forEach((nd, i) => {
    index.set(nd.path, i);
    const k = groupKey(nd);
    const c = centres.get(k);
    const spread = 1.5 + 0.62 * Math.sqrt(groups.get(k).length);
    const rnd = mulberry32(hash32(nd.path));
    // point inside a ball: random direction, radius ~ cbrt(u)
    const th = rnd() * Math.PI * 2;
    const ph = Math.acos(2 * rnd() - 1);
    const rr = Math.cbrt(rnd()) * spread;
    pos[i * 3] = c[0] + Math.sin(ph) * Math.cos(th) * rr;
    pos[i * 3 + 1] = c[1] + Math.cos(ph) * rr;
    pos[i * 3 + 2] = c[2] + Math.sin(ph) * Math.sin(th) * rr;
    size[i] = Math.min(1.15, 0.3 + 0.2 * Math.log2(1 + (nd.lines || 10) / 25) + 0.08 * (nd.fan_in || 0));
    const col = colorFor(nd);
    color.set(col, i * 3);
  });

  // Edges: real imports from the server; if the repo has few (non Python/JS), link each star to its nearest neighbours in the folder.
  const edgeList = [];
  const seen = new Set();
  const add = (a, b) => {
    if (a === b || a < 0 || b < 0 || a >= n || b >= n) return;
    const key = a < b ? a * 100000 + b : b * 100000 + a;
    if (seen.has(key)) return;
    seen.add(key);
    edgeList.push(a, b);
  };
  const raw = graph && graph.edges ? graph.edges : [];
  for (const e of raw) add(e[0], e[1]);
  if (edgeList.length / 2 < n * 0.6) {
    for (const members of groups.values()) {
      for (const i of members) {
        const near = members
          .filter((j) => j !== i)
          .map((j) => {
            const dx = pos[i * 3] - pos[j * 3], dy = pos[i * 3 + 1] - pos[j * 3 + 1], dz = pos[i * 3 + 2] - pos[j * 3 + 2];
            return [dx * dx + dy * dy + dz * dz, j];
          })
          .sort((a, b) => a[0] - b[0])
          .slice(0, 2);
        for (const [, j] of near) add(i, j);
      }
    }
  }
  return { n, pos, size, color, edges: new Uint32Array(edgeList), index, radius: R + 3, nodes };
}

// Something pretty to show before any repository is indexed.
export function demoGraph() {
  const dirs = ["core", "api", "ui", "docs", "tests", "tools", "data"];
  const langs = ["python", "javascript", "python", "markdown", "python", "python", "config"];
  const rnd = mulberry32(7);
  const nodes = [];
  for (let i = 0; i < 130; i++) {
    const d = Math.floor(rnd() * dirs.length);
    nodes.push({ path: `demo/${dirs[d]}/file${i}.x`, dir: `demo/${dirs[d]}`, lang: langs[d], kind: langs[d] === "markdown" ? "doc" : "code", lines: 10 + Math.floor(rnd() * 300), fan_in: rnd() < 0.15 ? 3 : 0 });
  }
  const edges = [];
  for (let i = 0; i < 150; i++) edges.push([Math.floor(rnd() * nodes.length), Math.floor(rnd() * nodes.length)]);
  return { nodes, edges };
}

export function makeDust(count, seed = 11) {
  const rnd = mulberry32(seed);
  const pos = new Float32Array(count * 3);
  const size = new Float32Array(count);
  const color = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const th = rnd() * Math.PI * 2, ph = Math.acos(2 * rnd() - 1), r = 24 + rnd() * 34;
    pos[i * 3] = Math.sin(ph) * Math.cos(th) * r;
    pos[i * 3 + 1] = Math.cos(ph) * r * 0.7;
    pos[i * 3 + 2] = Math.sin(ph) * Math.sin(th) * r;
    size[i] = 0.1 + rnd() * 0.22;
    const warm = rnd();
    color.set([0.78 + warm * 0.15, 0.78 + warm * 0.1, 0.9 - warm * 0.1], i * 3);
  }
  return { n: count, pos, size, color };
}
