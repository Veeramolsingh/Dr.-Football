from typing import Optional, TypedDict


class AgentState(TypedDict):
    question: str
    sql: Optional[str]
    error: Optional[str]
    rows: Optional[list[dict]]
    retries: int
    report: Optional[str]


def initial_state(question: str) -> AgentState:
    return {
        "question": question,
        "sql": None,
        "error": None,
        "rows": None,
        "retries": 0,
        "report": None,
    }
