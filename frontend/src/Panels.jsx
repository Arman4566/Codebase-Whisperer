import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Markdown } from "./md.jsx";
import { Reading, Segmented } from "./ui.jsx";

const nf = new Intl.NumberFormat();

// ------------------------------------------------------------------ repositories
export function ReposPanel({ ctx }) {
  const { repos, repo, setRepo, notify, scene, refreshRepos, refreshStatus, bumpGraph } = ctx;
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(e) {
    e.preventDefault();
    const src = source.trim();
    if (!src || busy) return;
    setBusy(true);
    scene.current.setBusy(true);
    try {
      const info = await api.addRepo(src);
      await refreshRepos();
      setRepo(info.name);
      setSource("");
      bumpGraph();
      notify(`Indexed ${info.name}: ${nf.format(info.files)} files.`, "ok");
    } catch (err) {
      notify(err.message, "bad");
    } finally {
      scene.current.setBusy(false);
      setBusy(false);
      refreshStatus();
    }
  }

  return (
    <section aria-labelledby="h-repos">
      <h3 id="h-repos">Repositories</h3>
      <form onSubmit={add} className="stack">
        <label htmlFor="src">Add a repository</label>
        <input id="src" value={source} onChange={(e) => setSource(e.target.value)} placeholder="owner/repo, a GitHub URL, or a folder path" autoComplete="off" spellCheck="false" />
        <button className="btn primary" disabled={busy || !source.trim()}>{busy ? "Indexing" : "Index repository"}</button>
        {busy && <p className="hint">Large repositories can take a minute. The map listens while it works.</p>}
      </form>
      {repos.length === 0 ? (
        <p className="empty">Nothing indexed yet. Add a repository and ask it a question.</p>
      ) : (
        <ul className="repos">
          {repos.length > 1 && (
            <li className={repo === "" ? "on" : ""}>
              <div>
                <strong>All repositories</strong>
                <span>Answers search every index and name the repository in each citation.</span>
              </div>
              <button className="btn ghost" onClick={() => setRepo("")} aria-pressed={repo === ""}>{repo === "" ? "Using" : "Use"}</button>
            </li>
          )}
          {repos.map((r) => (
            <li key={r.name} className={repo === r.name ? "on" : ""}>
              <div>
                <strong>{r.name}</strong>
                <span>{nf.format(r.files)} files, {nf.format(r.chunks)} sections, commit <code>{(r.head || "none").slice(0, 7)}</code></span>
              </div>
              <button className="btn ghost" onClick={() => setRepo(r.name)} aria-pressed={repo === r.name}>{repo === r.name ? "Using" : "Use"}</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ onboarding guide
export function GuidePanel({ ctx }) {
  const { repo, repos, language, notify, scene, refreshStatus } = ctx;
  const [level, setLevel] = useState("beginner");
  const [goal, setGoal] = useState("");
  const [guide, setGuide] = useState(null);
  const [busy, setBusy] = useState(false);
  const target = repo || (repos[0] && repos[0].name) || "";

  async function generate(e) {
    e.preventDefault();
    if (busy || !target) return;
    setBusy(true);
    scene.current.setBusy(true);
    try {
      setGuide(await api.onboarding({ repo: target, level, goal, language }));
    } catch (err) {
      notify(err.message, "bad");
    } finally {
      scene.current.setBusy(false);
      setBusy(false);
      refreshStatus();
    }
  }
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(guide.markdown);
      notify("Guide copied.", "ok");
    } catch {
      notify("Couldn't copy. Select the text and copy it instead.", "bad");
    }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([guide.markdown], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${guide.repo}-onboarding.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section aria-labelledby="h-guide">
      <h3 id="h-guide">Onboarding guide</h3>
      <form onSubmit={generate} className="stack">
        <span className="label" id="lvl">Your level</span>
        <Segmented label="Your level" value={level} onChange={setLevel} options={["beginner", "intermediate", "expert"]} />
        <label htmlFor="goal">What do you want to do? <em>(optional)</em></label>
        <input id="goal" value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Fix a payments bug" autoComplete="off" />
        <button className="btn primary" disabled={busy || !target}>{busy ? "Writing the guide" : guide ? "Write it again" : "Write the guide"}</button>
        {!target && <p className="hint">Index a repository first.</p>}
        {target && !repo && repos.length > 1 && <p className="hint">Writing the guide for <strong>{target}</strong>. Choose a repository at the top to change it.</p>}
      </form>
      {busy && <Reading>Mapping the architecture</Reading>}
      {guide && !busy && (
        <div className="guide">
          <div className="row">
            <button className="btn ghost" onClick={copy}>Copy</button>
            <button className="btn ghost" onClick={download}>Download .md</button>
          </div>
          {guide.unverified_paths.length > 0 ? (
            <p className="warn">These file names aren't in the repository: {guide.unverified_paths.map((p) => <code key={p}>{p}</code>)}</p>
          ) : (
            <p className="ok">Every file named below exists in the repository.</p>
          )}
          <Markdown text={guide.markdown} />
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ approvals
const KIND = { create_issue: "Issue", draft_pull_request: "Pull request" };
const STATUS = { pending: "Waiting for you", approved: "Approved", rejected: "Rejected", failed: "Failed" };

export function ActionsPanel({ ctx }) {
  const { actions, refreshActions, repo, repos, notify, status, scene, refreshStatus } = ctx;
  const [request, setRequest] = useState("");
  const [busy, setBusy] = useState(false);
  const [working, setWorking] = useState(null);
  const target = repo || (repos[0] && repos[0].name) || "";
  const writes = status && status.github_writes;

  async function draft(e) {
    e.preventDefault();
    if (!request.trim() || busy || !target) return;
    setBusy(true);
    scene.current.setBusy(true);
    try {
      await api.draftIssue({ request: request.trim(), repo: repo || target });
      setRequest("");
      await refreshActions();
      notify("Drafted. Review it below. Nothing is sent until you approve.", "ok");
    } catch (err) {
      notify(err.message, "bad");
    } finally {
      scene.current.setBusy(false);
      setBusy(false);
      refreshStatus();
    }
  }

  async function decide(a, kind) {
    setWorking(a.id);
    try {
      const done = await (kind === "approve" ? api.approve(a.id) : api.reject(a.id));
      await refreshActions();
      if (kind === "reject") notify("Rejected. Nothing was sent.", "ok");
      else if (done.status === "failed") notify(done.result.error, "bad");
      else if (done.result.executed) notify(done.result.url ? `Created: ${done.result.url}` : "Created on GitHub.", "ok");
      else notify(`Approved as a dry run. Nothing reached GitHub: ${done.result.reason}`, "ok");
    } catch (err) {
      notify(err.message, "bad");
    } finally {
      setWorking(null);
    }
  }

  return (
    <section aria-labelledby="h-act">
      <h3 id="h-act">Approvals</h3>
      <p className="hint lead">The agent can only propose actions. Nothing is sent to GitHub until you approve it here. {writes ? "GitHub writes are on." : "GitHub writes are off, so approved actions are recorded as dry runs."}</p>
      <form onSubmit={draft} className="stack">
        <label htmlFor="draft">Draft a GitHub issue</label>
        <input id="draft" value={request} onChange={(e) => setRequest(e.target.value)} placeholder="Add connection pooling to the database layer" autoComplete="off" />
        <button className="btn ghost" disabled={busy || !request.trim() || !target}>{busy ? "Drafting" : "Draft the issue"}</button>
      </form>
      {actions.length === 0 ? (
        <p className="empty">No proposals yet. Draft an issue above, or let an MCP client propose one.</p>
      ) : (
        <ul className="actions">
          {actions.map((a) => (
            <li key={a.id} className={"action " + a.status}>
              <div className="head">
                <strong>{a.title}</strong>
                <span className={"chip " + a.status}>{STATUS[a.status] || a.status}</span>
              </div>
              <p className="sub">{KIND[a.kind] || a.kind} for {a.repo}, proposed by {a.proposed_by}</p>
              <details>
                <summary>Read the full text</summary>
                <pre>{a.body}</pre>
              </details>
              {a.status === "pending" && (
                <div className="row">
                  <button className="btn ok" disabled={working === a.id} onClick={() => decide(a, "approve")}>Approve</button>
                  <button className="btn bad" disabled={working === a.id} onClick={() => decide(a, "reject")}>Reject</button>
                </div>
              )}
              {a.result && a.status !== "pending" && (
                <p className="sub">{a.result.url ? <a href={a.result.url} target="_blank" rel="noreferrer">{a.result.url}</a> : a.result.reason || a.result.error || ""}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ sync
export function SyncPanel({ ctx }) {
  const { repo, repos, notify, scene, refreshRepos, refreshStatus, bumpGraph } = ctx;
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState(null);
  const target = repo || (repos.length === 1 ? repos[0].name : "");
  const info = repos.find((r) => r.name === (repo || target));

  async function sync() {
    setBusy(true);
    scene.current.setBusy(true);
    try {
      const r = await api.sync(repo || target || null);
      setLast(r);
      await refreshRepos();
      bumpGraph();
      notify(r.changed ? "Synced. The index now matches the repository." : "Already up to date.", "ok");
    } catch (err) {
      notify(err.message, "bad");
    } finally {
      scene.current.setBusy(false);
      setBusy(false);
      refreshStatus();
    }
  }

  return (
    <section aria-labelledby="h-sync">
      <h3 id="h-sync">Keep in sync</h3>
      <p className="hint lead">Pulls new commits, then re-reads only the files that changed.</p>
      {!target && repos.length > 1 && <p className="hint">Choose one repository to sync.</p>}
      {info && <p className="sub">Indexed at commit <code>{(info.head || "none").slice(0, 7)}</code></p>}
      <button className="btn primary" onClick={sync} disabled={busy || !(repo || target)}>{busy ? "Syncing" : "Sync now"}</button>
      {busy && <Reading>Looking for changes</Reading>}
      {last && !busy && (
        <div className="result">
          <p className="sub">{last.from === last.to ? <>Up to date at <code>{last.to}</code>.</> : <><code>{last.from}</code> to <code>{last.to}</code></>}</p>
          <div className="counts">
            <span>{last.added.length} added</span>
            <span>{last.modified.length} changed</span>
            <span>{last.deleted.length} removed</span>
            <span>{last.reindexed_chunks} sections re-read</span>
          </div>
          <p className="summary-text">{last.summary}</p>
          {last.new_commits.length > 0 && (
            <ul className="commits">
              {last.new_commits.map((c) => (
                <li key={c.sha}><code>{c.sha}</code> {c.subject}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ explore: explain a file, find usages
export function ExplorePanel({ ctx }) {
  const { repo, repos, notify } = ctx;
  const target = repo || (repos.length === 1 ? repos[0].name : null);
  const [mode, setMode] = useState("File");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState(null);
  const [use, setUse] = useState(null);
  const [paths, setPaths] = useState([]);

  useEffect(() => {
    if (!target) return;
    let live = true;
    api.graph(target).then((g) => live && setPaths(g.nodes.map((n) => n.path))).catch(() => {});
    return () => { live = false; };
  }, [target]);

  async function openFile(path) {
    setBusy(true);
    setMode("File");
    setText(path);
    try {
      setFile(await api.file(path, target));
      setUse(null);
    } catch (e) { notify(e.message, "bad"); } finally { setBusy(false); }
  }
  async function run(e) {
    e.preventDefault();
    const v = text.trim();
    if (!v || busy) return;
    if (mode === "File") return openFile(v);
    setBusy(true);
    try {
      setUse(await api.usages(v, target));
      setFile(null);
    } catch (err) { notify(err.message, "bad"); } finally { setBusy(false); }
  }

  if (!target) return (
    <section><h3>Explore</h3><p className="sub">Choose one repository first (Repositories tab, then Use). Exploring needs a single repository.</p></section>
  );
  const PathBtn = ({ p }) => <button type="button" className="link mono" onClick={() => openFile(p)}>{p}</button>;
  return (
    <section aria-labelledby="h-explore">
      <h3 id="h-explore">Explore {target}</h3>
      <form onSubmit={run} className="stack">
        <Segmented value={mode} onChange={(m) => { setMode(m); setText(""); }} options={["File", "Symbol"]} label="What to look up" />
        <label htmlFor="ex">{mode === "File" ? "File path" : "Function, class or variable name"}</label>
        <input id="ex" list={mode === "File" ? "ex-paths" : undefined} value={text} onChange={(e) => setText(e.target.value)}
          placeholder={mode === "File" ? "src/app/main.py" : "parse_args"} autoComplete="off" spellCheck="false" />
        <datalist id="ex-paths">{paths.map((p) => <option key={p} value={p} />)}</datalist>
        <button className="btn primary" disabled={busy || !text.trim()}>{busy ? "Reading" : mode === "File" ? "Explain file" : "Find usages"}</button>
      </form>

      {file && (
        <div className="explore">
          <h4 className="mono">{file.path}</h4>
          <p className="sub">{file.lines} lines{file.summary ? `. ${file.summary}` : ""}</p>
          {file.symbols.length > 0 && <><h5>Defines</h5><ul className="plain">{file.symbols.map((s) => (
            <li key={s.ref}><code>{s.name}</code> <span className="ref">L{s.start}-L{s.end}</span>{s.note && <span className="sub"> {s.note}</span>}</li>))}</ul></>}
          {file.imports.length > 0 && <><h5>Imports</h5><ul className="plain">{file.imports.map((p) => <li key={p}><PathBtn p={p} /></li>)}</ul></>}
          {file.imported_by.length > 0 && <><h5>Used by</h5><ul className="plain">{file.imported_by.map((p) => <li key={p}><PathBtn p={p} /></li>)}</ul></>}
          {file.tests.length > 0 && <><h5>Tests</h5><ul className="plain">{file.tests.map((p) => <li key={p}><PathBtn p={p} /></li>)}</ul></>}
          {file.todos.length > 0 && <><h5>Open TODOs</h5><ul className="plain">{file.todos.map((t) => <li key={t.line}><span className="ref">L{t.line}</span> {t.text}</li>)}</ul></>}
          {file.recent_commits.length > 0 && <><h5>Recent changes</h5><ul className="plain">{file.recent_commits.map((c) => (
            <li key={c.sha}><code>{c.sha}</code> {c.subject} <span className="sub">{c.author}, {c.date}</span></li>))}</ul></>}
        </div>
      )}

      {use && (
        <div className="explore">
          {!use.found ? <p className="sub">No match for <code>{use.symbol}</code> in {use.repo}.</p> : (
            <>
              <p className="sub">{use.total} matches{use.total > use.shown ? `, showing ${use.shown}` : ""}.</p>
              <ul className="plain">{use.hits.map((h) => (
                <li key={h.ref + h.line}>
                  <span className={`kind ${h.kind}`}>{h.kind}</span>
                  <button type="button" className="link mono" onClick={() => openFile(h.path)}>{h.path}:{h.line}</button>
                  <code className="line">{h.text}</code>
                </li>))}</ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}
