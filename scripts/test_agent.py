"""Run the Phase 3 LangGraph pipeline from the terminal -- no FastAPI yet.

Usage:
    python -m scripts.test_agent "find me the top 3 center-backs by pass completion rate"
"""

import argparse
import json

from app.agent.graph import build_graph
from app.agent.state import initial_state


def main(question: str):
    graph = build_graph()
    result = graph.invoke(initial_state(question))

    print("=== SQL ===")
    print(result["sql"])
    print()

    if result["error"]:
        print("=== FAILED (ran out of retries) ===")
        print(f"retries used: {result['retries']}")
        print(f"last error:   {result['error']}")
    elif result["rows"] is not None:
        print(f"=== ROWS ({len(result['rows'])}) ===")
        print(json.dumps(result["rows"][:5], indent=2, default=str))
        if len(result["rows"]) > 5:
            print(f"... and {len(result['rows']) - 5} more")

    print()
    print("=== REPORT ===")
    print(result["report"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    args = parser.parse_args()
    main(args.question)
