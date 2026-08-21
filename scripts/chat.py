"""Talk to the scout in a running conversation, from the terminal.

    python -m scripts.chat

Type questions; follow-ups work ("and their goals?"). Commands:
    /sql     show the SQL behind the last answer
    /reset   forget the conversation and start over
    /quit    exit
"""

import sys

from app.agent.graph import build_graph
from app.agent.memory import SessionStore, Turn
from app.agent.state import initial_state

sys.stdout.reconfigure(encoding="utf-8")

SESSION = "cli"


def main():
    graph = build_graph()
    store = SessionStore()
    last_sql = None

    print("Dr. Football is in. Ask away -- /sql, /reset, /quit\n")

    while True:
        try:
            question = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not question:
            continue
        if question == "/quit":
            return
        if question == "/reset":
            store.reset(SESSION)
            last_sql = None
            print("\n(conversation cleared)\n")
            continue
        if question == "/sql":
            print(f"\n{last_sql or '(nothing yet)'}\n")
            continue

        result = graph.invoke(initial_state(question, store.history(SESSION)))
        last_sql = result["sql"]

        print(f"\ndoc > {result['report']}\n")

        if result["error"] is None:
            store.append(SESSION, Turn(question=question, sql=result["sql"], report=result["report"]))


if __name__ == "__main__":
    main()
