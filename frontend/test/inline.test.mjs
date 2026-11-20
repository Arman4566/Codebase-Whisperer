import test from "node:test";
import assert from "node:assert/strict";
import { tokenizeInline } from "../src/inlineTokens.js";

const join = (toks) => toks.map((t) => t.v).join("");

test("identifiers with underscores are never italicised", () => {
  for (const s of ["def add_completion_class(", "is_flag=True, flag_value", "use get_completion_class and add_completion_class", "__init__.py"]) {
    const toks = tokenizeInline(s);
    assert.ok(toks.every((t) => t.t === "text"), s);
    assert.equal(join(toks), s);
  }
});

test("real italics, bold and code are recognised", () => {
  assert.deepEqual(tokenizeInline("an _emphasised_ word").map((t) => t.t), ["text", "em", "text"]);
  assert.deepEqual(tokenizeInline("**bold** and `code`").map((t) => t.t), ["strong", "text", "code"]);
  assert.equal(tokenizeInline("`add_completion_class`")[0].v, "add_completion_class");
});

test("whole-line italics keep their nested formatting (guide header)", () => {
  const toks = tokenizeInline("_Level: **beginner** - 168 files, commit `08b803c`_");
  assert.equal(toks.length, 1);
  assert.equal(toks[0].t, "em");
  assert.deepEqual(tokenizeInline(toks[0].v).map((t) => t.t), ["text", "strong", "text", "code"]);
});

test("unbalanced markers pass through as text", () => {
  assert.equal(join(tokenizeInline("a _ b ** c `")), "a _ b ** c `");
});
