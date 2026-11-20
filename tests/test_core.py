import json

import pytest

from conftest import FakeLLM, git
from whisperer.actions import ActionError
from whisperer.agent import Whisperer
from whisperer.chunker import chunk_file
from whisperer.config import Settings


# ------------------------------------------------------------------ chunking
def test_python_chunks_follow_functions_with_exact_lines():
    src = "import os\n\n\ndef a():\n    return 1\n\n\nclass B:\n    def m(self):\n        return 2\n"
    refs = {c.symbol: (c.start_line, c.end_line) for c in chunk_file("r", "x.py", src)}
    assert refs["a"] == (4, 5)
    assert refs["B"] == (8, 10)
    assert refs["(module-level)"] == (1, 1)


def test_decorator_line_is_part_of_the_chunk():
    src = "@deco\ndef f():\n    pass\n"
    c = next(c for c in chunk_file("r", "x.py", src) if c.symbol == "f")
    assert c.start_line == 1


def test_js_function_boundaries():
    src = "function login(a) {\n  if (a) {\n    return 1;\n  }\n  return 2;\n}\n\nconst out = async (x) => {\n  return 3;\n};\n"
    refs = {c.symbol: (c.start_line, c.end_line) for c in chunk_file("r", "a.js", src)}
    assert refs["login"] == (1, 6)
    assert refs["out"] == (8, 10)


def test_markdown_split_by_heading():
    syms = [c.symbol for c in chunk_file("r", "README.md", "# A\ntext\n\n## B\nmore\n")]
    assert syms == ["A", "B"]


def test_large_function_is_windowed_with_overlap():
    body = "\n".join(f"    x{i} = {i}" for i in range(300))
    chunks = chunk_file("r", "big.py", f"def big():\n{body}\n", max_lines=100)
    assert len(chunks) > 2
    assert all(c.end_line - c.start_line + 1 <= 100 for c in chunks)
    assert chunks[1].start_line < chunks[0].end_line  # overlap


# ------------------------------------------------------------------ retrieval / answers
def test_search_finds_the_right_file_and_lines(w):
    top = w.search("how are failed payments retried", "tinyshop", k=3)
    refs = [r["chunk"].ref for r in top]
    assert any(r.startswith("app/payments.py:L17") for r in refs)


def test_identifier_exact_match(w):
    top = w.search("login_required", "tinyshop", k=2)
    assert top[0]["chunk"].path in ("app/auth.py", "app/main.py")


def test_agent_abstains_when_repo_has_no_evidence(w):
    r = w.ask("How does the Kafka consumer process email notifications?")
    assert r["abstained"] is True
    assert r["claims"] == []


def test_answerable_question_is_not_abstained(w):
    r = w.ask("How does authentication work?")
    assert not r["abstained"] and r["claims"]
    assert all(c["citations"] for c in r["claims"])


def test_llm_answer_validates_citations_and_downgrades_unsupported_claims(settings, repo_copy):
    reply = {"found": True, "summary": "Auth uses signed tokens.", "claims": [
        {"text": "Tokens are HMAC signed.", "status": "verified", "sources": [{"n": 1, "lines": "1-2"}]},
        {"text": "Tokens live in Redis.", "status": "verified", "sources": [{"n": 99}]},        # invalid source number
        {"text": "Probably rotated daily.", "status": "assumption", "sources": []},
    ]}
    w = Whisperer(settings, llm=FakeLLM(settings, reply))
    w.add_repo(str(repo_copy), "tinyshop")
    r = w.ask("How does authentication use signed tokens?", "tinyshop")
    assert r["mode"] == "llm" and not r["abstained"]
    c0, c1, c2 = r["claims"]
    assert c0["status"] == "verified" and c0["citations"]
    assert c1["status"] == "assumption" and c1["citations"] == []     # downgraded: nothing valid to cite
    assert c2["status"] == "assumption"


def test_llm_not_found_becomes_abstain(settings, repo_copy):
    w = Whisperer(settings, llm=FakeLLM(settings, {"found": False, "summary": "Not in the repo.", "claims": []}))
    w.add_repo(str(repo_copy), "tinyshop")
    r = w.ask("How does authentication use signed tokens?", "tinyshop")
    assert r["abstained"] is True


# ------------------------------------------------------------------ onboarding
def test_onboarding_has_real_paths_only(w):
    g = w.onboarding_guide("tinyshop")
    assert g["unverified_paths"] == []
    assert "app/main.py" in g["markdown"]
    assert any(m["path"] == "app/orders.py" for m in g["profile"]["key_modules"])
    assert any(o["type"] == "todo" for o in g["profile"]["opportunities"])


# ------------------------------------------------------------------ sync
def test_sync_is_incremental_and_summarises_changes(w, repo_copy):
    assert w.sync("tinyshop")["changed"] is False
    (repo_copy / "app" / "notify.py").write_text('"""Email notifications."""\n\n\ndef send_email(to, subject):\n    return True\n')
    (repo_copy / "app" / "utils.py").write_text("def slugify(t):\n    return t\n")
    (repo_copy / "web" / "cart.js").unlink()
    git(repo_copy, "add", "-A")
    git(repo_copy, "commit", "-qm", "Add email notifications and simplify slugify")
    r = w.sync("tinyshop")
    assert r["added"] == ["app/notify.py"] and r["modified"] == ["app/utils.py"] and r["deleted"] == ["web/cart.js"]
    assert r["new_commits"][0]["subject"].startswith("Add email notifications")
    assert r["reindexed_chunks"] < 10            # only changed files + the new commit
    assert w.search("send_email notifications", "tinyshop", k=1)[0]["chunk"].path == "app/notify.py"
    assert not [x for x in w.repos["tinyshop"].index.chunks if x.path == "web/cart.js"]
    answer = w.ask("how does the browser cart work with localStorage", "tinyshop")
    assert not any("web/cart.js" in s["ref"] for s in answer["sources"])      # deleted file is never cited
    assert not any("web/cart.js" in c for cl in answer["claims"] for c in cl["citations"])


def test_index_survives_restart(settings, repo_copy):
    Whisperer(settings).add_repo(str(repo_copy), "tinyshop")
    again = Whisperer(settings)
    assert "tinyshop" in again.repos and again.search("charge_card", "tinyshop", k=1)


# ------------------------------------------------------------------ human approval
def test_nothing_executes_without_approval(w):
    item = w.actions.propose("create_issue", "tinyshop", "Add pooling", "body")
    assert item["status"] == "pending" and item["result"] is None
    assert w.actions.list("pending")[0]["id"] == item["id"]


def test_approve_is_dry_run_when_github_writes_disabled(w):
    item = w.actions.propose("create_issue", "tinyshop", "Add pooling", "body")
    done = w.actions.approve(item["id"], by="tester")
    assert done["status"] == "approved" and done["result"]["executed"] is False and done["result"]["dry_run"]
    with pytest.raises(ActionError):
        w.actions.approve(item["id"])           # cannot be executed twice
    with pytest.raises(ActionError):
        w.actions.reject(item["id"])


def test_reject_and_audit_log(w):
    item = w.actions.propose("draft_pull_request", "tinyshop", "Fix typo", "body", head="fix", base="main")
    w.actions.reject(item["id"], by="tester", reason="not needed")
    events = [json.loads(l)["event"] for l in w.s.data_dir.joinpath("audit.log").read_text().splitlines()]
    assert events == ["proposed", "rejected"]


def test_unknown_action_kind_rejected(w):
    with pytest.raises(ActionError):
        w.actions.propose("delete_repo", "tinyshop", "x", "y")


def test_mcp_exposes_no_approval_tool():
    import asyncio
    from whisperer import mcp_server
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"ask_codebase", "propose_github_issue", "draft_pull_request", "sync_repository"} <= names
    assert not [n for n in names if "approve" in n or "execute" in n]


# ------------------------------------------------------------------ multi-repo
def test_multi_repo_search_labels_repo(settings, repo_copy, tmp_path):
    import shutil
    other = tmp_path / "other"
    shutil.copytree(repo_copy, other)
    w = Whisperer(settings)
    w.add_repo(str(repo_copy), "shop-a")
    w.add_repo(str(other), "shop-b")
    r = w.ask("How does authentication work?")
    assert not r["abstained"]
    assert all(":" in c["citations"][0] for c in r["claims"])      # repo-qualified citations
    with pytest.raises(KeyError):
        w.get(None)


# ------------------------------------------------------------------ polish found while testing the UI
def test_readme_intro_skips_html_header_and_badges(w, repo_copy):
    (repo_copy / "README.md").write_text(
        '<div align="center"><img src="logo.svg" height="150"></div>\n\n# Project\n\n[![CI](x.svg)](y)\n\n'
        'A real description of the project.\n\n## Install\n')
    w.sync("tinyshop")
    prof = w.onboarding_guide("tinyshop")["profile"]
    assert prof["readme_intro"].startswith("A real description"), prof["readme_intro"]
    assert "<" not in prof["readme_intro"]


def test_abstain_reports_the_users_words_not_stems(w):
    r = w.ask("How does the Kafka consumer process email notifications?")
    assert r["abstained"] and "kafka" in r["missing_terms"]
    assert all(t == t.lower() and not t.endswith("kafk") for t in r["missing_terms"])


def test_extractive_evidence_has_no_raw_markdown_hashes(w):
    r = w.ask("What is the overall architecture and request flow?")
    assert all(not c["text"].split(": ", 1)[-1].startswith("#") for c in r["claims"])


def test_graph_endpoint_data(w):
    g = w.graph("tinyshop")
    paths = {n["path"] for n in g["nodes"]}
    assert {"app/auth.py", "app/orders.py", "web/cart.js"} <= paths
    assert all(0 <= a < len(g["nodes"]) and 0 <= b < len(g["nodes"]) for a, b in g["edges"])
    imports = {(g["nodes"][a]["path"], g["nodes"][b]["path"]) for a, b in g["edges"]}
    assert ("app/orders.py", "app/payments.py") in imports      # a real import, not a guess
    assert w.graph("tinyshop") is g                              # cached until the next sync


# ------------------------------------------------------------------ navigation features
def test_explain_file_lists_real_symbols_and_relations(w):
    e = w.explain_file("app/orders.py", "tinyshop")
    assert e["path"] == "app/orders.py" and e["symbols"]
    assert all(s["start"] <= s["end"] for s in e["symbols"])
    assert "app/payments.py" in e["imports"]
    assert e["recent_commits"] and e["verified"]
    with pytest.raises(KeyError):
        w.explain_file("app/nope.py", "tinyshop")
    with pytest.raises(KeyError):
        w.explain_file("../etc/passwd", "tinyshop")


def test_find_usages_separates_definition_from_calls(w):
    u = w.find_usages("charge_card", "tinyshop")
    assert u["found"] and u["hits"][0]["kind"] == "definition"
    assert any(h["kind"] == "usage" for h in u["hits"])
    assert all(h["ref"].startswith(h["path"]) for h in u["hits"])
    assert not w.find_usages("zzz_not_a_symbol", "tinyshop")["found"]
    with pytest.raises(ValueError):
        w.find_usages("a b; rm -rf", "tinyshop")


def test_followup_borrows_previous_terms_but_keeps_user_wording(w):
    hist = [{"q": "How does authentication work?"}]
    r = w.ask("and where is it tested?", "tinyshop", history=hist)
    assert r["question"] == "and where is it tested?"
    assert r["retrieval_query"] and "authent" in r["retrieval_query"]
    assert w.ask("How does authentication work?", "tinyshop", history=hist)["retrieval_query"] is None


def test_mcp_has_navigation_tools():
    import asyncio
    from whisperer import mcp_server
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"explain_file", "find_usages"} <= names
