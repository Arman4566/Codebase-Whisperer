# Codebase Whisperer

A repo-aware AI agent (PS-04 · RAG & MCP). It indexes a repository - code, docs, issues and commit history - answers
questions with **file + line citations**, tags every claim **verified vs assumption**, says so when the repo does **not**
contain the answer, writes **personalised onboarding guides**, keeps itself **in sync** with the repo, and performs
GitHub actions through **MCP tools that always wait for human approval**.

```
repo ──► loader ──► code-aware chunker ──► hybrid index (BM25 + dense, rank-fused) ──► agent ──► answers + citations
 │         (git log, issues)   (functions/classes/headings,                              │
 │                              exact path:L10-L42)                                       ├─► onboarding guide
 └── sync (hash diff + git log) ─► re-index only changed files                            ├─► MCP server (propose only)
                                                                                          └─► approval queue ─► human ─► GitHub
```

## Run it

```bash
pip install -r requirements.txt
# optional but recommended: real LLM + embeddings
export OPENAI_API_KEY=sk-...            # Windows: set OPENAI_API_KEY=sk-...

python -m whisperer add sample_repo --name tinyshop     # or: add https://github.com/pallets/click
python -m whisperer ask "How are failed payments retried?"
python -m whisperer onboard --level beginner --goal "fix a payments bug"
python -m whisperer serve                                # web UI + API on http://127.0.0.1:8000
python -m whisperer mcp                                  # MCP server over stdio
python -m whisperer eval eval/tinyshop_dataset.json --repo tinyshop
pytest -q                                                # 20 tests
```

Without `OPENAI_API_KEY` everything still runs offline (local TF-IDF retrieval, extractive answers). With a key you get
OpenAI embeddings (cached, only new/changed chunks are embedded) and LLM-written answers, guides and change summaries.
The web UI shows an estimated API spend so you can watch the $50 budget.

### Use from an MCP client (Claude Desktop, Cursor, ...)
```json
{ "mcpServers": { "codebase-whisperer": {
    "command": "python", "args": ["-m", "whisperer", "mcp"], "cwd": "/path/to/codebase-whisperer",
    "env": { "OPENAI_API_KEY": "sk-...", "WHISPERER_DATA": "/path/to/codebase-whisperer/data" } } } }
```
Tools: `ask_codebase`, `search_code`, `get_onboarding_guide`, `sync_repository`, `list_repositories`,
`propose_github_issue`, `draft_pull_request`, `list_pending_actions`.

## Navigation features

- **Explain file** (Explore tab, `GET /api/file`, `whisperer explain <path>`, MCP `explain_file`): symbols with exact line ranges,
  what the file imports, what imports it, related tests, open TODOs and its last five commits. Read from the checkout, no model involved.
- **Find usages** (Explore tab, `GET /api/usages`, `whisperer usages <symbol>`, MCP `find_usages`): every definition and use with
  `path:line`, definitions first and tests last.
- **Follow-up questions**: a short question like "and where is it tested?" borrows key terms from your previous question for retrieval.
  Your own wording is what is shown, and the response includes `retrieval_query` so nothing is hidden.
- **Save as Markdown**: each answer can be downloaded with its verified/assumption tags and citations.

## Frontend (React + Three.js)

The web UI at `/` is a React 19 app. Behind the conversation, your repository is drawn as a star map in Three.js:
each file is a star, folders form clusters, imports are faint lines. Asking a question sends a ripple from the query
star, and beams light up the files the answer cites. Verified claims have a solid teal rule; assumptions have a dashed
lilac rule, so the difference does not depend on colour alone.

- Responsive: side panel on desktop, bottom tab bar on phones, lighter rendering on low-power devices.
- Graceful fallback: a Canvas 2D renderer draws the same scene instantly and is kept if WebGL is unavailable.
  `prefers-reduced-motion` freezes the map; highlights still apply. `/classic` serves the original plain page.
- Offline: Three.js loads from a CDN. To work without internet, put `three.min.js` (r128-r149 global build) in
  `whisperer/static/vendor/`.
- Rebuild after editing `frontend/src`: `cd frontend && npm install && npm run build`
  (writes `whisperer/static/app.js` and `app.css`). Tests: `node --test test/core.test.mjs test/threeview.test.mjs test/inline.test.mjs`.

Tested honestly: 29 browser checks (Playwright, Chromium) cover layout at 320-1440px, no horizontal scroll, no JS errors,
reduced motion and the 2D fallback. The sandbox had no Three.js access, so the WebGL path was verified only against a
mock of the Three API, not rendered on a real GPU. Open it once on your machine and check the map; if it fails,
the 2D map takes over automatically.

## How each requirement is met

| Requirement | Where |
|---|---|
| Code-specific chunking | `chunker.py` - Python via `ast` (functions/classes/methods, decorators included), brace languages via a declaration scanner, Markdown by heading. Every chunk keeps exact `path:Lstart-Lend`. |
| Code + docs + issues + commit history | `loader.py` - files, `git log`, GitHub issues/PRs |
| Retrieval | `index.py` - BM25 (identifier-aware, camelCase/snake_case split) + dense, fused with reciprocal rank fusion, plus exact-symbol lookup for "where is X defined" |
| Precise citations | LLM sees line-numbered code and cites ranges; `agent._answer_llm` clamps each range to the retrieved chunk, drops citations that don't resolve to a real file, and **downgrades "verified" claims that have no valid citation to "assumption"** |
| Acknowledge missing info | `agent.ask` abstains when key terms have no evidence; the LLM may also return `found:false` |
| Verified vs assumption | every claim is tagged; onboarding guide marks inferences as assumptions |
| Onboarding guide | `onboarding.py` - facts computed from the repo (tree, entry points, import graph → key modules, `good first issue` labels, TODO/FIXME, undocumented functions, untested modules); LLM only personalises; every path in the output is re-checked against the real file list |
| MCP + human approval | `mcp_server.py` only **proposes**; `actions.py` executes only on `approve()`, which is **not an MCP tool**. Audit log in `data/audit.log`. |
| Repository sync | `agent.sync` - content-hash diff + `git log old..HEAD`; re-chunks only added/modified files, drops deleted ones |
| Measurable accuracy | `evaluate.py` + `eval/*.json` - File/Line Hit@k, MRR, abstain accuracy; bm25 vs dense vs hybrid |
| Multiple repos | add several; `ask` without `--repo` searches all and prefixes citations with the repo name |
| Multilingual | `language` parameter on answers, guides and change summaries (LLM mode) |
| Change summaries | `sync` returns a summary of new commits and changed files |

GitHub writes are **off by default**: an approved action is recorded as a dry run until you set
`WHISPERER_ALLOW_GITHUB_WRITES=1` and `GITHUB_TOKEN`. A pull request needs an already-pushed branch (`head`).

## Evaluation (offline mode, no API key)

Hit@5 on labelled questions (`eval/`). **Read the caveats below before quoting these.**

| Repo | Questions | Mode | File Hit@5 | Line Hit@5 | MRR |
|---|---|---|---|---|---|
| sample_repo (14 files) | 16 + 4 unanswerable | hybrid | 94% | 94% | 0.81 |
| pallets/click (163 files) | 16 + 4 unanswerable | bm25 | 69% | 56% | 0.35 |
| pallets/click | | dense | 56% | 50% | 0.22 |
| pallets/click | | **hybrid** | **94%** | **88%** | **0.66** |

On click, before retrieval fixes (stopword-free BM25 queries, stemming, exact-symbol lookup, demoting tests/changelogs)
hybrid scored 69% / 50% / 0.37. Refusing unanswerable questions: 4/4 on the sample repo, 3/4 on click; 0 valid
questions wrongly refused on either.

### Caveats (please read)
- The datasets are small (16-20 questions), I wrote the labels, and I **tuned the retrieval and abstain rules on these same
  questions**, so the numbers are optimistic. Build your own held-out set for the demo.
- On 12 click questions I did not tune on: all 10 answerable ones were answered with plausible citations, but the **2
  unanswerable ones were not refused** ("Flask integration", "send HTTP requests" - those words appear somewhere in the
  docs). Offline refusal is a heuristic; with an API key, the LLM's `found:false` path is the main safeguard.
- **The OpenAI paths (embeddings, answers, guides, summaries) and real GitHub writes are untested against the live APIs** -
  they were built and tested with a fake LLM because this was developed without network access to OpenAI. Run
  `python -m whisperer ask ...` with your key and test unanswerable questions before the demo.
- Chunking for non-Python languages is a heuristic scanner, not tree-sitter. Swapping in tree-sitter is the obvious upgrade.
- The abstain rule is repo-size-aware (strict above 2,000 distinct tokens, conservative below) because on a tiny repo the
  strict rule wrongly refused 9 of 16 valid questions.

## Layout
```
whisperer/  chunker.py loader.py index.py agent.py onboarding.py actions.py evaluate.py mcp_server.py api.py cli.py static/index.html
sample_repo/  demo repo with real git history      eval/  datasets + results      tests/  20 tests
```
Built against `mcp>=2` (`mcp.server.mcpserver.MCPServer`); the web layer is Starlette (FastAPI is not required).
