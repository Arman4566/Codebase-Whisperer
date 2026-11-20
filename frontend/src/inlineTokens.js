// Splits inline Markdown into tokens. Pure JS so it can be unit-tested without React.
// `_italic_` only counts at word boundaries, so identifiers like add_completion_class stay intact.
const TOKEN = /`[^`]+`|\*\*[^*]+\*\*|_[^_\s][^_]*_/g;
const WORD = /\w/;

export function tokenizeInline(text) {
  const s = String(text);
  const out = [];
  let last = 0;
  TOKEN.lastIndex = 0;
  let m;
  while ((m = TOKEN.exec(s))) {
    const tok = m[0];
    const i = m.index;
    if (tok[0] === "_") {
      const before = s[i - 1];
      const after = s[i + tok.length];
      if ((before && WORD.test(before)) || (after && WORD.test(after))) {
        TOKEN.lastIndex = i + 1; // not italics: an underscore inside an identifier; keep scanning inside it
        continue;
      }
    }
    if (i > last) out.push({ t: "text", v: s.slice(last, i) });
    if (tok[0] === "`") out.push({ t: "code", v: tok.slice(1, -1) });
    else if (tok[0] === "*") out.push({ t: "strong", v: tok.slice(2, -2) });
    else out.push({ t: "em", v: tok.slice(1, -1) });
    last = i + tok.length;
  }
  if (last < s.length) out.push({ t: "text", v: s.slice(last) });
  return out;
}
