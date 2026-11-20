import { useCallback, useEffect, useRef, useState } from "react";
import { api, citedPaths } from "./api.js";
import { ActionsPanel, ExplorePanel, GuidePanel, ReposPanel, SyncPanel } from "./Panels.jsx";
import { Turn } from "./Thread.jsx";
import { mountScene } from "./scene/mount.js";
import { Glyph, Icon, Toasts, useMedia } from "./ui.jsx";

const LANGUAGES = ["English", "Hindi", "Bengali", "Spanish", "French", "German"];
const SUGGESTIONS = ["How is this project structured?", "Where does a request enter the code?", "What should I read first?"];
const TABS = [
  ["repos", "Repositories"],
  ["guide", "Guide"],
  ["explore", "Explore"],
  ["actions", "Approvals"],
  ["sync", "Sync"],
];

export default function App() {
  const scene = useRef(null);
  const wide = useMedia("(min-width: 980px)");
  const [mapMode, setMapMode] = useState("2d");
  const [status, setStatus] = useState(null);
  const [repos, setRepos] = useState([]);
  const [repo, setRepo] = useState("");
  const [actions, setActions] = useState([]);
  const [thread, setThread] = useState([]);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState("ask");
  const [language, setLanguage] = useState("English");
  const [draft, setDraft] = useState("");
  const [toasts, setToasts] = useState([]);
  const [offline, setOffline] = useState(false);
  const [graphStamp, setGraphStamp] = useState(0);
  const seq = useRef(0);
  const lastTurn = useRef(null);
  const input = useRef(null);

  // ---- the 3D map
  useEffect(() => {
    const el = document.getElementById("sky");
    const s = mountScene(el, { onMode: (m) => { el.dataset.mode = m; setMapMode(m); } });
    scene.current = s;
    window.__scene = s; // debugging and tests
    return () => s.destroy();
  }, []);
  useEffect(() => { scene.current && scene.current.setShift(wide ? 0.2 : 0, wide ? 1.2 : 1); }, [wide]);

  // ---- data
  const notify = useCallback((text, kind = "") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t.slice(-2), { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6500);
  }, []);
  const refreshStatus = useCallback(() => api.status().then(setStatus).catch(() => {}), []);
  const refreshActions = useCallback(() => api.actions().then(setActions).catch(() => {}), []);
  const refreshRepos = useCallback(() => api.repos().then((r) => { setRepos(r); return r; }), []);
  const bumpGraph = useCallback(() => setGraphStamp((n) => n + 1), []);

  useEffect(() => {
    Promise.all([refreshStatus(), refreshRepos(), refreshActions()])
      .then(([, r]) => { if (r && r.length === 1) setRepo(r[0].name); })
      .catch(() => setOffline(true));
  }, [refreshStatus, refreshRepos, refreshActions]);

  const graphRepo = repo || (repos[0] && repos[0].name) || "";
  useEffect(() => {
    let dead = false;
    if (!graphRepo) {
      scene.current && scene.current.setGraph(null);
      return undefined;
    }
    api.graph(graphRepo).then((g) => { if (!dead && scene.current) scene.current.setGraph(g); }).catch(() => {});
    return () => { dead = true; };
  }, [graphRepo, graphStamp]);

  // ---- asking
  async function ask(question) {
    const q = question.trim();
    if (!q || busy || !repos.length) return;
    const id = ++seq.current;
    setView("ask");
    setDraft("");
    setThread((t) => [...t, { id, q, pending: true }]);
    setBusy(true);
    const s = scene.current;
    s.highlight([]);
    s.whisper();
    s.setBusy(true);
    try {
      const history = thread.filter((t) => t.a && !t.a.abstained).slice(-3).map((t) => ({ q: t.q }));
      const a = await api.ask(q, repo || null, language, history);
      setThread((t) => t.map((x) => (x.id === id ? { ...x, a, pending: false } : x)));
      s.setBusy(false);
      s.highlight(citedPaths(a));
    } catch (err) {
      setThread((t) => t.map((x) => (x.id === id ? { ...x, error: err.message, pending: false } : x)));
      s.setBusy(false);
    } finally {
      setBusy(false);
      refreshStatus();
    }
  }

  useEffect(() => {
    if (lastTurn.current) {
      const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      lastTurn.current.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
    }
  }, [thread.length]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
        e.preventDefault();
        setView("ask");
        input.current && input.current.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const growInput = (el) => {
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 150) + "px";
  };
  useEffect(() => growInput(input.current), [draft]);

  const ctx = { repos, repo, setRepo, actions, status, scene, notify, language, refreshRepos, refreshActions, refreshStatus, bumpGraph };
  const pending = actions.filter((a) => a.status === "pending").length;
  const sideView = view === "ask" ? "repos" : view;
  const hasRepos = repos.length > 0;
  const showAsk = wide || view === "ask";
  const showSide = wide || view !== "ask";
  const model = status && status.llm ? status.chat_model : null;

  const Panel = { repos: ReposPanel, guide: GuidePanel, explore: ExplorePanel, actions: ActionsPanel, sync: SyncPanel }[sideView];

  return (
    <div className="shell">
      <header className="top">
        <a className="wordmark" href="/" aria-label="Codebase Whisperer, home">
          <Glyph />
          <span>whisperer</span>
        </a>
        <span className="grow" />
        {status && (
          <span className={"pill " + (status.llm ? "live" : "")} title={`Map renderer: ${mapMode === "webgl" ? "WebGL" : "2D canvas"}`}>
            {status.llm ? `Model ${status.chat_model}` : "Offline mode"}
          </span>
        )}
        {status && status.llm && <span className="spend" title="Estimated OpenAI spend this session">${status.est_cost_usd.toFixed(3)} used</span>}
        {repos.length > 0 && (
          <label className="pick">
            <span className="sr">Repository</span>
            <select value={repo} onChange={(e) => setRepo(e.target.value)}>
              {repos.length > 1 && <option value="">All repositories</option>}
              {repos.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
            </select>
          </label>
        )}
      </header>

      {offline && (
        <p className="banner" role="alert">
          Can't reach the Whisperer server. Start it with <code>python -m whisperer serve</code>, then reload.
        </p>
      )}

      <main className="main" data-wide={wide}>
        {showAsk && (
          <div className="col-ask">
            <div className="thread" aria-live="off">
              {thread.length === 0 ? (
                <section className="hero">
                  <h1>{hasRepos ? "Ask this codebase." : "Add a repository to begin."}</h1>
                  <p>
                    {hasRepos
                      ? "Every answer points to the lines behind it. When the repository doesn't say, neither do we."
                      : "Index a GitHub repository or a folder on this machine. Each file becomes a star on the map."}
                  </p>
                  {hasRepos ? (
                    <div className="suggest">
                      {SUGGESTIONS.map((s) => (
                        <button key={s} type="button" onClick={() => ask(s)}>{s}</button>
                      ))}
                    </div>
                  ) : (
                    <button className="btn primary" onClick={() => setView("repos")}>Add a repository</button>
                  )}
                </section>
              ) : (
                thread.map((t, i) => (
                  <Turn
                    key={t.id}
                    turn={t}
                    fresh={i === thread.length - 1}
                    model={model}
                    innerRef={i === thread.length - 1 ? lastTurn : null}
                    onHover={(p) => scene.current && scene.current.hover(p)}
                    onShow={(paths) => scene.current && (scene.current.highlight(paths), scene.current.whisper())}
                  />
                ))
              )}
            </div>
            <div className="composer">
              <form onSubmit={(e) => { e.preventDefault(); ask(draft); }}>
                <label className="sr" htmlFor="q">Your question</label>
                <textarea
                  id="q"
                  ref={input}
                  rows={1}
                  value={draft}
                  disabled={!hasRepos}
                  placeholder={hasRepos ? "Ask about the code" : "Index a repository first"}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(draft); } }}
                />
                <label className="sr" htmlFor="lang">Answer language</label>
                <select id="lang" value={language} onChange={(e) => setLanguage(e.target.value)} title="Answer language">
                  {LANGUAGES.map((l) => <option key={l}>{l}</option>)}
                </select>
                <button className="btn primary send" disabled={busy || !draft.trim() || !hasRepos}>{busy ? "Reading" : "Ask"}</button>
              </form>
              <p className="keys">Enter to ask, Shift and Enter for a new line, / to jump here.</p>
            </div>
          </div>
        )}

        {showSide && (
          <aside className="side" aria-label="Tools">
            {wide && (
              <div className="tabs" role="tablist">
                {TABS.map(([id, label]) => (
                  <button key={id} role="tab" aria-selected={sideView === id} className={sideView === id ? "on" : ""} onClick={() => setView(id)}>
                    {label}
                    {id === "actions" && pending > 0 && <b className="badge" aria-label={`${pending} waiting`}>{pending}</b>}
                  </button>
                ))}
              </div>
            )}
            <div className="sheet" role="tabpanel">
              <Panel ctx={ctx} />
            </div>
          </aside>
        )}
      </main>

      {!wide && (
        <nav className="tabbar" aria-label="Sections">
          {[["ask", "Ask"], ...TABS].map(([id, label]) => (
            <button key={id} className={view === id ? "on" : ""} aria-current={view === id ? "page" : undefined} onClick={() => setView(id)}>
              <Icon name={id} />
              <span>{label}</span>
              {id === "actions" && pending > 0 && <b className="badge" aria-label={`${pending} waiting`}>{pending}</b>}
            </button>
          ))}
        </nav>
      )}

      <Toasts items={toasts} />
    </div>
  );
}
