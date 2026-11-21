"""HTTP API + web UI (Starlette). Run: python -m whisperer serve"""
from __future__ import annotations

from pathlib import Path

import base64
import hmac
import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .actions import ActionError
from .agent import Whisperer
from .llm import LLMError

STATIC = Path(__file__).parent / "static"
W = Whisperer()


async def body(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


def guard(fn):
    async def wrapper(request: Request):
        try:
            return await fn(request)
        except (KeyError, ValueError, ActionError) as e:
            return JSONResponse({"error": str(e).strip("'\"")}, status_code=400)
        except LLMError as e:
            return JSONResponse({"error": f"LLM error: {e}"}, status_code=502)
        except Exception as e:  # keep the demo alive
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
    return wrapper


async def index(_): return FileResponse(STATIC / "index.html")


async def classic(_): return FileResponse(STATIC / "classic.html")  # the original lightweight UI, no JS libraries


@guard
async def status(_): return JSONResponse({"llm": W.llm.available, "chat_model": W.s.chat_model, "usage": W.llm.usage,
                                          "est_cost_usd": W.llm.cost_estimate(), "github_writes": W.s.allow_github_writes})


@guard
async def repos(_): return JSONResponse(W.list_repos())


@guard
async def graph(request): return JSONResponse(W.graph(request.query_params.get("repo") or None))


@guard
async def file_info(request):
    q = request.query_params
    if not q.get("path"):
        raise ValueError("path is required")
    return JSONResponse(W.explain_file(q["path"], q.get("repo") or None))


@guard
async def usages(request):
    q = request.query_params
    if not q.get("symbol"):
        raise ValueError("symbol is required")
    return JSONResponse(W.find_usages(q["symbol"], q.get("repo") or None))


@guard
async def add_repo(request):
    b = await body(request)
    if not b.get("source"):
        raise ValueError("source (local path or GitHub URL) is required")
    return JSONResponse(W.add_repo(b["source"], b.get("name")))


@guard
async def ask(request):
    b = await body(request)
    if not b.get("question"):
        raise ValueError("question is required")
    return JSONResponse(W.ask(b["question"], b.get("repo") or None, b.get("language", "English"), history=b.get("history") or None))


@guard
async def onboarding(request):
    b = await body(request)
    return JSONResponse(W.onboarding_guide(b.get("repo") or None, b.get("level", "beginner"), b.get("goal", ""), b.get("language", "English")))


@guard
async def sync(request):
    b = await body(request)
    return JSONResponse(W.sync(b.get("repo") or None))


@guard
async def actions(request):
    return JSONResponse(W.actions.list(request.query_params.get("status")))


@guard
async def propose(request):
    b = await body(request)
    return JSONResponse(W.actions.propose(b.get("kind", "create_issue"), b["repo"], b.get("title", ""), b.get("body", ""),
                                          labels=b.get("labels"), head=b.get("head", ""), base=b.get("base", "main"),
                                          proposed_by=b.get("proposed_by", "ui")))


@guard
async def approve(request):
    b = await body(request)
    return JSONResponse(W.actions.approve(request.path_params["id"], by=b.get("by", "human"), edits=b.get("edits")))


@guard
async def reject(request):
    b = await body(request)
    return JSONResponse(W.actions.reject(request.path_params["id"], by=b.get("by", "human"), reason=b.get("reason", "")))


@guard
async def draft_issue(request):
    """Ask the agent to DRAFT an issue from a question/finding; it only lands in the approval queue."""
    b = await body(request)
    repo = b.get("repo") or None
    ans = W.ask(b["request"], repo)
    st = W.get(repo)
    cites = sorted({c for cl in ans["claims"] for c in cl["citations"]})
    text = f"{b['request']}\n\n**Findings**\n{ans['answer']}\n\n_Drafted by Codebase Whisperer at commit {(st.head or '')[:7]}; awaiting human approval._"
    return JSONResponse(W.actions.propose("create_issue", st.name, b.get("title") or b["request"][:80], text, labels=b.get("labels"), proposed_by="agent"))


class PasswordGate:
    """Optional HTTP Basic auth for the whole site. Active only when WHISPERER_PASSWORD is set (do this on any public deployment:
    the UI can add repositories, spend your OpenAI credits and approve GitHub actions). /healthz stays open for the host's checks."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        pw = os.environ.get("WHISPERER_PASSWORD", "")
        if scope["type"] != "http" or not pw or scope["path"] == "/healthz":
            return await self.app(scope, receive, send)
        auth = dict(scope["headers"]).get(b"authorization", b"").decode()
        ok = False
        if auth.lower().startswith("basic "):
            try:
                given = base64.b64decode(auth[6:]).decode().partition(":")[2]
                ok = hmac.compare_digest(given.encode(), pw.encode())
            except Exception:
                ok = False
        if ok:
            return await self.app(scope, receive, send)
        resp = PlainTextResponse("Password required", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Codebase Whisperer"'})
        return await resp(scope, receive, send)


async def healthz(_): return PlainTextResponse("ok")


app = Starlette(middleware=[Middleware(PasswordGate)], routes=[
    Route("/healthz", healthz),
    Route("/", index), Route("/classic", classic), Route("/api/graph", graph), Route("/api/file", file_info), Route("/api/usages", usages), Route("/api/status", status), Route("/api/repos", repos), Route("/api/repos/add", add_repo, methods=["POST"]),
    Route("/api/ask", ask, methods=["POST"]), Route("/api/onboarding", onboarding, methods=["POST"]), Route("/api/sync", sync, methods=["POST"]),
    Route("/api/actions", actions), Route("/api/actions/propose", propose, methods=["POST"]), Route("/api/actions/draft-issue", draft_issue, methods=["POST"]),
    Route("/api/actions/{id}/approve", approve, methods=["POST"]), Route("/api/actions/{id}/reject", reject, methods=["POST"]),
    Mount("/static", StaticFiles(directory=STATIC), name="static"),
])
