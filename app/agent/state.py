from typing import Optional, TypedDict

from app.agent.memory import Turn


class AgentState(TypedDict):
    question: str
    history: list[Turn]  # earlier turns in this conversation, oldest first
    sql: Optional[str]
    error: Optional[str]
    rows: Optional[list[dict]]
    retries: int
    report: Optional[str]


def initial_state(question: str, history: Optional[list[Turn]] = None) -> AgentState:
    return {
        "question": question,
        "history": history or [],
        "sql": None,
        "error": None,
        "rows": None,
        "retries": 0,
        "report": None,
    }
