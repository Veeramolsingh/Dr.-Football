from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.agent.schema import SCHEMA_DESCRIPTION
from app.agent.sql_safety import extract_sql, validate_select_only
from app.agent.state import AgentState
from app.config import settings
from app.database import SessionLocal

MAX_RETRIES = 2
QUERY_TIMEOUT_MS = 5000  # guards against an accidental runaway query (e.g. a stray cross join)


def _llm(temperature: float = 0.0) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model, google_api_key=settings.google_api_key, temperature=temperature
    )


def generate_sql(state: AgentState) -> AgentState:
    """The SQL Agent: turns the question (and, on a retry, the previous error) into SQL."""
    messages = [
        SystemMessage(
            content=f"{SCHEMA_DESCRIPTION}\n\nWrite exactly one PostgreSQL SELECT query that answers "
            "the user's question. Return ONLY the SQL -- no explanation, no markdown fences."
        ),
        HumanMessage(content=state["question"]),
    ]
    if state["error"]:
        messages.append(
            HumanMessage(
                content=f"Your previous query:\n{state['sql']}\n\nfailed with this error:\n{state['error']}\n\n"
                "Fix it and return ONLY the corrected SQL."
            )
        )

    try:
        response = _llm().invoke(messages)
        sql = extract_sql(response.content)
        return {**state, "sql": sql, "error": None}
    except Exception as exc:
        # A transient Gemini failure (rate limit, timeout, ...) shouldn't crash the graph.
        # Leaving sql=None means validate_select_only in run_sql reports "Empty query.",
        # which routes through the exact same retry/give_up logic as a bad SQL query --
        # no separate error-handling path needed.
        return {**state, "sql": None, "error": f"LLM call failed: {exc}"}


def run_sql(state: AgentState) -> AgentState:
    """The DB Executor: validates and runs the SQL against Postgres."""
    sql = state["sql"]
    try:
        validate_select_only(sql)
        db = SessionLocal()
        try:
            db.execute(text(f"SET LOCAL statement_timeout = {QUERY_TIMEOUT_MS}"))
            result = db.execute(text(sql))
            rows = [dict(row._mapping) for row in result]
        finally:
            db.close()
        return {**state, "rows": rows, "error": None}
    except (ValueError, SQLAlchemyError) as exc:
        return {**state, "rows": None, "error": str(exc), "retries": state["retries"] + 1}


def should_retry(state: AgentState) -> str:
    if state["error"] and state["retries"] <= MAX_RETRIES:
        return "retry"
    if state["error"]:
        return "give_up"
    return "continue"


def write_report(state: AgentState) -> AgentState:
    """The Scout: turns the query results into a written report."""
    messages = [
        SystemMessage(
            content="You are a professional football scout writing a concise Markdown report. "
            "Base every claim strictly on the query results provided -- do not invent stats "
            "that aren't in the data. If the results are empty, say so plainly instead of "
            "making something up."
        ),
        HumanMessage(
            content=f"Question: {state['question']}\n\nQuery results (JSON): {state['rows']}"
        ),
    ]
    try:
        report = _llm(temperature=0.3).invoke(messages).content
    except Exception as exc:
        # By this point the query already succeeded -- don't throw away real results
        # just because the write-up step hit a transient API error. Degrade gracefully.
        report = (
            f"The query succeeded ({len(state['rows'])} row(s)), but the written report "
            f"could not be generated due to an API error: {exc}\n\nRaw results:\n{state['rows']}"
        )
    return {**state, "report": report}


def give_up(state: AgentState) -> AgentState:
    """Reached when the SQL Agent couldn't produce working SQL within the retry budget."""
    report = (
        f"I couldn't answer that -- the SQL I generated kept failing after "
        f"{state['retries']} attempt(s). Last error: {state['error']}"
    )
    return {**state, "report": report}
