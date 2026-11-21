"""Command line interface: python -m whisperer <command>"""
from __future__ import annotations

import argparse
import os
import json
import sys
from pathlib import Path

from .agent import Whisperer


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="whisperer", description="Codebase Whisperer - repo-aware RAG agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="index a repository (local path or GitHub URL)")
    a.add_argument("source"); a.add_argument("--name")
    q = sub.add_parser("ask", help="ask a question")
    q.add_argument("question"); q.add_argument("--repo"); q.add_argument("--language", default="English")
    ef = sub.add_parser("explain", help="explain one file"); ef.add_argument("path"); ef.add_argument("--repo")
    fu = sub.add_parser("usages", help="find every use of a symbol"); fu.add_argument("symbol"); fu.add_argument("--repo")
    o = sub.add_parser("onboard", help="generate an onboarding guide")
    o.add_argument("--repo"); o.add_argument("--level", default="beginner"); o.add_argument("--goal", default=""); o.add_argument("--language", default="English")
    s = sub.add_parser("sync", help="pull + incrementally re-index"); s.add_argument("--repo")
    e = sub.add_parser("eval", help="run the retrieval evaluation")
    e.add_argument("dataset"); e.add_argument("--repo", required=True); e.add_argument("-k", type=int, default=5); e.add_argument("--out")
    sub.add_parser("repos", help="list indexed repositories")
    ac = sub.add_parser("actions", help="review the approval queue")
    ac.add_argument("op", choices=["list", "approve", "reject"]); ac.add_argument("id", nargs="?"); ac.add_argument("--reason", default="")
    sv = sub.add_parser("serve", help="web UI + HTTP API"); sv.add_argument("--host", default=os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")); sv.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    sub.add_parser("mcp", help="run the MCP server over stdio")

    args = p.parse_args(argv)
    if args.cmd == "mcp":
        from .mcp_server import main as run_mcp
        run_mcp()
        return 0
    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("whisperer.api:app", host=args.host, port=args.port)
        return 0

    w = Whisperer()
    try:
        if args.cmd == "add":
            print(json.dumps(w.add_repo(args.source, args.name), indent=2))
        elif args.cmd == "repos":
            print(json.dumps(w.list_repos(), indent=2))
        elif args.cmd == "ask":
            r = w.ask(args.question, args.repo, args.language)
            print(r["answer"]); print(f"\n[mode={r['mode']} coverage={r['coverage']} confidence={r['confidence']}]")
        elif args.cmd == "explain":
            print(json.dumps(w.explain_file(args.path, args.repo), indent=2))
        elif args.cmd == "usages":
            r = w.find_usages(args.symbol, args.repo)
            print(f"{r['symbol']}: {r['total']} matches")
            for h in r["hits"]:
                print(f"  {h['kind']:<10} {h['path']}:{h['line']}  {h['text']}")
        elif args.cmd == "onboard":
            g = w.onboarding_guide(args.repo, args.level, args.goal, args.language)
            print(g["markdown"])
            if g["unverified_paths"]:
                print("\nWARNING unverified paths:", g["unverified_paths"], file=sys.stderr)
        elif args.cmd == "sync":
            r = w.sync(args.repo)
            print(f"{r['from']} -> {r['to']}\n{r['summary']}\nre-indexed chunks: {r['reindexed_chunks']}")
        elif args.cmd == "eval":
            from .evaluate import evaluate, load_dataset, to_markdown
            md = to_markdown(evaluate(w, args.repo, load_dataset(Path(args.dataset)), args.k))
            print(md)
            if args.out:
                Path(args.out).write_text(md + "\n")
        elif args.cmd == "actions":
            if args.op == "list":
                for i in w.actions.list():
                    print(f"{i['id']}  {i['status']:<9} {i['kind']:<20} {i['repo']}  {i['title']}")
            elif args.op == "approve":
                print(json.dumps(w.actions.approve(args.id, by="cli-user"), indent=2))
            else:
                print(json.dumps(w.actions.reject(args.id, by="cli-user", reason=args.reason), indent=2))
    except (KeyError, ValueError) as ex:
        print(f"error: {str(ex).strip(chr(39))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
