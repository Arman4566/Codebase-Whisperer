"""Retrieval evaluation against a labelled test dataset.

Dataset item: {"q": str, "expect": [{"path": str, "lines": [start, end]?}], "answerable": bool}
Metrics (per retrieval mode): file Hit@k, line-level Hit@k, MRR, and abstain accuracy on
unanswerable questions (does the agent correctly say "not in the repo"?).
"""
from __future__ import annotations

import json
from pathlib import Path

from .agent import Whisperer


def _is_hit(chunk, exp: dict, line_level: bool) -> bool:
    if chunk.path != exp["path"]:
        return False
    if not line_level or "lines" not in exp:
        return True
    lo, hi = exp["lines"]
    return chunk.start_line <= hi and chunk.end_line >= lo


def evaluate(w: Whisperer, repo: str, dataset: list[dict], k: int = 5) -> dict:
    modes = ["bm25", "dense", "hybrid"]
    ans = [d for d in dataset if d.get("answerable", True)]
    res: dict = {"k": k, "n_answerable": len(ans), "n_unanswerable": len(dataset) - len(ans), "modes": {}, "misses": []}
    for mode in modes:
        file_hits = line_hits = 0
        rr = 0.0
        for d in ans:
            results = w.search(d["q"], repo, k=k, mode=mode)
            rank_file = next((i for i, r in enumerate(results, 1) if any(_is_hit(r["chunk"], e, False) for e in d["expect"])), None)
            rank_line = next((i for i, r in enumerate(results, 1) if any(_is_hit(r["chunk"], e, True) for e in d["expect"])), None)
            file_hits += rank_file is not None
            line_hits += rank_line is not None
            rr += 1 / rank_line if rank_line else 0
            if mode == "hybrid" and rank_line is None:
                res["misses"].append({"q": d["q"], "expected": d["expect"], "got": [r["chunk"].ref for r in results]})
        n = max(len(ans), 1)
        res["modes"][mode] = {"file_hit@k": round(file_hits / n, 3), "line_hit@k": round(line_hits / n, 3), "mrr": round(rr / n, 3)}
    unans = [d for d in dataset if not d.get("answerable", True)]
    correct = sum(1 for d in unans if w.ask(d["q"], repo)["abstained"])
    false_abstain = sum(1 for d in ans if w.ask(d["q"], repo)["abstained"])
    res["abstain"] = {"correct_on_unanswerable": f"{correct}/{len(unans)}", "false_abstain_on_answerable": f"{false_abstain}/{len(ans)}"}
    return res


def to_markdown(res: dict, title: str = "Retrieval evaluation") -> str:
    out = [f"# {title}", "", f"{res['n_answerable']} answerable + {res['n_unanswerable']} unanswerable questions, k={res['k']}", "",
           "| Retrieval mode | File Hit@k | Line Hit@k | MRR |", "|---|---|---|---|"]
    for m, v in res["modes"].items():
        out.append(f"| {m} | {v['file_hit@k']:.0%} | {v['line_hit@k']:.0%} | {v['mrr']} |")
    out += ["", f"**Abstain check** - correctly refused unanswerable: {res['abstain']['correct_on_unanswerable']}; "
            f"wrongly refused answerable: {res['abstain']['false_abstain_on_answerable']}"]
    if res["misses"]:
        out += ["", "## Hybrid misses"] + [f"- `{m['q']}` expected {m['expected']} got {m['got'][:3]}" for m in res["misses"]]
    return "\n".join(out)


def load_dataset(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text())
