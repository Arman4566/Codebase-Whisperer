async function req(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let j = {};
  try {
    j = await r.json();
  } catch {
    /* non-JSON error page */
  }
  if (!r.ok) throw new Error(j.error || `${r.status} ${r.statusText}`.trim());
  return j;
}

export const api = {
  status: () => req("/api/status"),
  repos: () => req("/api/repos"),
  addRepo: (source, name) => req("/api/repos/add", { source, name: name || undefined }),
  ask: (question, repo, language, history) => req("/api/ask", { question, repo: repo || null, language, history }),
  file: (path, repo) => req(`/api/file?path=${encodeURIComponent(path)}${repo ? `&repo=${encodeURIComponent(repo)}` : ""}`),
  usages: (symbol, repo) => req(`/api/usages?symbol=${encodeURIComponent(symbol)}${repo ? `&repo=${encodeURIComponent(repo)}` : ""}`),
  onboarding: (o) => req("/api/onboarding", o),
  sync: (repo) => req("/api/sync", { repo: repo || null }),
  graph: (repo) => req("/api/graph" + (repo ? `?repo=${encodeURIComponent(repo)}` : "")),
  actions: () => req("/api/actions"),
  draftIssue: (o) => req("/api/actions/draft-issue", o),
  approve: (id) => req(`/api/actions/${id}/approve`, { by: "web-user" }),
  reject: (id) => req(`/api/actions/${id}/reject`, { by: "web-user" }),
};

/** "src/a.py:L10-L42", "repo:src/a.py:L10-L42", "commit:abc1234", "issue#12" -> structured. */
export function parseRef(ref) {
  const bare = ref.replace(/^[\w.-]+:(?=commit:|issue#)/, "");
  if (/^commit:/.test(bare)) return { kind: "commit", label: bare, ref };
  if (/^issue#\d+$/.test(bare)) return { kind: "issue", label: bare, ref };
  const m = ref.match(/^(?:([\w.-]+):)?(.+?):L(\d+)-L(\d+)$/);
  if (!m) return { kind: "other", label: ref, ref };
  return { kind: "code", repo: m[1], path: m[2], start: +m[3], end: +m[4], label: ref, ref };
}

export function citedPaths(answer) {
  if (!answer || answer.abstained) return [];
  const out = [];
  for (const c of answer.claims || []) for (const ref of c.citations || []) {
    const p = parseRef(ref);
    if (p.kind === "code" && !out.includes(p.path)) out.push(p.path);
  }
  return out;
}
