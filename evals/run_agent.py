"""Phase 1 of the eval: run every dataset case through the real LangGraph agent
and record what happened. Judging happens separately (evals/judge.py) so the
agent's own venv never needs the eval framework installed.

Usage:
    python -m evals.run_agent <output.json>
"""

import json
import sys
import time
from pathlib import Path

from sqlalchemy import text

from app.agent.graph import build_graph
from app.agent.memory import Turn
from app.agent.state import initial_state
from app.database import SessionLocal

sys.stdout.reconfigure(encoding="utf-8")

DATASET = Path(__file__).parent / "dataset.json"


def row_count(table: str) -> int:
    db = SessionLocal()
    try:
        return db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    finally:
        db.close()


def format_rows(rows):
    """Mirror of the numbered format the report model sees, reused as the
    judge's retrieval context so faithfulness is checked against exactly the
    facts the writer was handed."""
    if not rows:
        return ["(no rows returned)"]
    return [
        f"{i}. " + ", ".join(f"{k}={v}" for k, v in row.items())
        for i, row in enumerate(rows[:25], start=1)
    ]


def run_case(graph, case):
    history = []
    if case.get("setup_question"):
        setup = graph.invoke(initial_state(case["setup_question"]))
        history = [Turn(question=setup["question"], sql=setup["sql"], report=setup["report"])]

    before = row_count("player_match_stats") if case.get("safety") else None

    t0 = time.perf_counter()
    result = graph.invoke(initial_state(case["question"], history))
    latency = round(time.perf_counter() - t0, 2)

    record = {
        "id": case["id"],
        "question": case["question"],
        "expected": case["expected"],
        "safety": case.get("safety", False),
        "sql": result["sql"],
        "rows": format_rows(result["rows"]) if result["rows"] is not None else None,
        "row_count": len(result["rows"]) if result["rows"] is not None else None,
        "report": result["report"],
        "retries": result["retries"],
        "succeeded": result["error"] is None,
        "latency_s": latency,
    }
    if case.get("setup_question"):
        record["setup_question"] = case["setup_question"]
        record["setup_report"] = history[0].report
    if case.get("safety"):
        record["db_unchanged"] = row_count("player_match_stats") == before
    return record


def main(out_path: str):
    cases = json.loads(DATASET.read_text(encoding="utf-8"))["cases"]
    graph = build_graph()
    records = []
    for case in cases:
        print(f"running {case['id']} ...", flush=True)
        try:
            records.append(run_case(graph, case))
        except Exception as exc:  # a crash is itself a finding, not a reason to stop
            records.append(
                {"id": case["id"], "question": case["question"], "expected": case["expected"],
                 "safety": case.get("safety", False), "crashed": str(exc), "succeeded": False}
            )
        print(f"  done: succeeded={records[-1].get('succeeded')} "
              f"retries={records[-1].get('retries')} latency={records[-1].get('latency_s')}s", flush=True)

    Path(out_path).write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {len(records)} records to {out_path}")


if __name__ == "__main__":
    main(sys.argv[1])
