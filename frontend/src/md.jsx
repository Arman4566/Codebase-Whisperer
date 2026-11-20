// Small, safe Markdown renderer (builds React elements; never injects HTML), enough for onboarding guides.
import { Fragment } from "react";
import { tokenizeInline } from "./inlineTokens.js";

export function inline(text) {
  return tokenizeInline(text).map((tok, i) => {
    if (tok.t === "code") return <code key={i}>{tok.v}</code>;
    if (tok.t === "strong") return <strong key={i}>{inline(tok.v)}</strong>;
    if (tok.t === "em") return <em key={i}>{inline(tok.v)}</em>;
    return <Fragment key={i}>{tok.v}</Fragment>;
  });
}

function cells(line) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
}

export function Markdown({ text }) {
  const lines = String(text || "").split("\n");
  const out = [];
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (/^```/.test(line)) {
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(<pre key={k++} className="md-code"><code>{buf.join("\n")}</code></pre>);
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      const Tag = `h${Math.min(h[1].length + 1, 5)}`;
      out.push(<Tag key={k++}>{inline(h[2])}</Tag>);
      i++;
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(
        <div key={k++} className="md-table" tabIndex={0}>
          <table>
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead>
            <tbody>{rows.map((r, j) => <tr key={j}>{r.map((c, n) => <td key={n}>{inline(c)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      );
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
      const L = ordered ? "ol" : "ul";
      out.push(<L key={k++}>{items.map((t, j) => <li key={j}>{inline(t)}</li>)}</L>);
      continue;
    }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
      out.push(<blockquote key={k++}>{inline(buf.join(" "))}</blockquote>);
      continue;
    }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|>\s?|\s*([-*]|\d+\.)\s+|\s*\|.*\|\s*$)/.test(lines[i])) buf.push(lines[i++]);
    out.push(<p key={k++}>{inline(buf.join(" "))}</p>);
  }
  return <div className="md">{out}</div>;
}
