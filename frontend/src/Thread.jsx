import { useState } from "react";
import { citedPaths, parseRef } from "./api.js";
import { inline } from "./md.jsx";
import { Reading } from "./ui.jsx";

function findSource(a, cite) {
  const sources = a.sources || [];
  if (cite.kind === "code") {
    return (
      sources.find((s) => s.path === cite.path && s.start_line <= cite.start && s.end_line >= cite.end) ||
      sources.find((s) => s.path === cite.path) ||
      null
    );
  }
  return sources.find((s) => s.ref === cite.label || s.path === cite.label) || null;
}

function Snippet({ source, cite }) {
  const numbered = cite.kind === "code" && source.start_line > 0;
  const lines = String(source.snippet || "").split("\n");
  const truncated = (source.snippet || "").length >= 600;
  return (
    <figure className="snippet">
      <figcaption>{source.ref}</figcaption>
      <pre tabIndex={0} aria-label={`Source for ${cite.label}`}>
        {lines.map((ln, i) => {
          const n = source.start_line + i;
          const hot = numbered && n >= cite.start && n <= cite.end;
          return (
            <div key={i} className={"ln" + (hot ? " hot" : "")}>
              {numbered && <span className="no">{n}</span>}
              <span className="tx">{ln || " "}</span>
            </div>
          );
        })}
      </pre>
      {truncated && <p className="trunc">Showing the start of this section.</p>}
    </figure>
  );
}

function Cite({ cite, open, onToggle, onHover }) {
  const path = cite.kind === "code" ? cite.path : null;
  return (
    <button
      type="button"
      className="cite"
      aria-expanded={open}
      title={open ? "Hide the source" : "Show the source"}
      onClick={onToggle}
      onMouseEnter={() => path && onHover(path)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => path && onHover(path)}
      onBlur={() => onHover(null)}
    >
      {cite.label}
    </button>
  );
}

const MODE_TEXT = { extractive: "Closest evidence, no model", abstain: "No evidence found" };

export function Turn({ turn, fresh, model, onHover, onShow, innerRef }) {
  const { q, a, error, pending } = turn;
  const [open, setOpen] = useState(null); // "claimIndex|ref"
  const paths = a ? citedPaths(a) : [];

  const sourceFor = (ref) => {
    const cite = parseRef(ref);
    const source = findSource(a, cite);
    return { cite, source };
  };

  return (
    <article className={"turn" + (fresh ? " fresh" : "")} ref={innerRef} aria-busy={!!pending}>
      <h2 className="q">{q}</h2>

      {pending && <Reading>Reading the repository</Reading>}
      {error && <p className="error" role="alert">{error}</p>}

      {a && a.abstained && (
        <div className="nothing">
          <h3>Not in this repository.</h3>
          <p>
            {a.missing_terms && a.missing_terms.length
              ? `Nothing in the indexed code, docs or history mentions ${a.missing_terms.join(", ")}.`
              : a.answer}
          </p>
          {(a.sources || []).length > 0 && <p className="sub">Closest matches, probably unrelated:</p>}
          {(a.sources || []).length > 0 && (
            <div className="cites">
              {a.sources.slice(0, 3).map((s) => {
                const { cite, source } = sourceFor(s.ref);
                const key = "n|" + s.ref;
                return (
                  <span key={key}>
                    <Cite cite={cite} open={open === key} onToggle={() => setOpen(open === key ? null : key)} onHover={onHover} />
                    {open === key && source && <Snippet source={source} cite={cite} />}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      )}

      {a && !a.abstained && (
        <>
          {a.mode === "llm" && a.summary && <p className="summary">{inline(a.summary)}</p>}
          {a.mode === "extractive" && <p className="note">Showing the closest evidence. Add an OpenAI key to <code>.env</code> to get written answers.</p>}
          <ol className="claims">
            {a.claims.map((c, i) => (
              <li key={i} className={"claim " + c.status} style={{ "--i": i }}>
                <span className="verdict">{c.status === "verified" ? "Verified" : "Assumption"}</span>
                <p>{inline(c.text)}</p>
                {c.citations.length > 0 && (
                  <div className="cites">
                    {c.citations.map((ref) => {
                      const { cite } = sourceFor(ref);
                      const key = i + "|" + ref;
                      return <Cite key={key} cite={cite} open={open === key} onToggle={() => setOpen(open === key ? null : key)} onHover={onHover} />;
                    })}
                  </div>
                )}
                {c.citations.map((ref) => {
                  const key = i + "|" + ref;
                  if (open !== key) return null;
                  const { cite, source } = sourceFor(ref);
                  return source ? <Snippet key={key} source={source} cite={cite} /> : <p key={key} className="trunc">That section is no longer in the latest results.</p>;
                })}
              </li>
            ))}
          </ol>
        </>
      )}

      {a && (
        <div className="meta">
          <span>{a.mode === "llm" ? `Written by ${model || "the model"}` : MODE_TEXT[a.mode] || a.mode}</span>
          <span>Evidence coverage {Math.round((a.coverage || 0) * 100)}%</span>
          <span>{a.elapsed_s}s</span>
          {Object.values(a.indexed_commit || {})[0] && <span>Commit <code>{Object.values(a.indexed_commit)[0]}</code></span>}
          <button type="button" className="link" onClick={() => exportAnswer(turn.q, a)}>Save as Markdown</button>
          {paths.length > 0 && (
            <button type="button" className="link" onClick={() => onShow(paths)}>
              Show on the map
            </button>
          )}
        </div>
      )}
    </article>
  );
}

function exportAnswer(q, a) {
  const lines = [`# ${q}`, "", a.summary || "", ""];
  for (const c of a.claims || []) lines.push(`- **${c.status === "verified" ? "Verified" : "Assumption"}:** ${c.text}${(c.citations || []).length ? ` (${c.citations.map((r) => `\`${r}\``).join(", ")})` : ""}`);
  lines.push("", `_Indexed commit ${Object.values(a.indexed_commit || {})[0] || "unknown"}, evidence coverage ${Math.round((a.coverage || 0) * 100)}%._`);
  const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/markdown" }));
  const el = document.createElement("a");
  el.href = url;
  el.download = "answer.md";
  el.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
