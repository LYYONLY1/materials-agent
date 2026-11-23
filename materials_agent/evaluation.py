"""Repeatable retrieval comparison without a model or external API."""

import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from .retrieval import INDEX


def evaluate(cases: list[dict], mode: str) -> dict:
    results = []
    for case in cases:
        started = perf_counter()
        hits = INDEX.search(case["query"], case["material"], mode=mode)
        elapsed_ms = (perf_counter() - started) * 1000
        expected = set(case["expected"])
        ids = [hit["id"] for hit in hits]
        matches = [index for index, item in enumerate(ids, 1) if item in expected]
        results.append({
            "query": case["query"], "expected": case["expected"], "returned": ids,
            "recall_at_3": len(matches) / len(expected) if expected else None,
            "reciprocal_rank": 1 / matches[0] if matches else 0,
            "abstained": not ids, "elapsed_ms": round(elapsed_ms, 4),
        })
    answerable = [case for case in results if case["expected"]]
    unanswerable = [case for case in results if not case["expected"]]
    return {
        "mode": mode,
        "answerable_cases": len(answerable),
        "unanswerable_cases": len(unanswerable),
        "recall_at_3": round(mean(case["recall_at_3"] for case in answerable), 4) if answerable else None,
        "mrr": round(mean(case["reciprocal_rank"] for case in answerable), 4) if answerable else None,
        "abstention_rate": round(mean(case["abstained"] for case in unanswerable), 4) if unanswerable else None,
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("evals/retrieval_cases.json"))
    parser.add_argument("--out", type=Path, help="Write detailed JSON for both retrieval modes")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    reports = [evaluate(cases, mode) for mode in ("bm25", "hybrid")]
    for report in reports:
        print(f"{report['mode']:7s} Recall@3={report['recall_at_3']}  "
              f"MRR={report['mrr']}  Abstention={report['abstention_rate']}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
