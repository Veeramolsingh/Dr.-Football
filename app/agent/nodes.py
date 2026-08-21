import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.agent.persona import PERSONA
from app.agent.schema import SCHEMA_DESCRIPTION
from app.agent.sql_safety import extract_sql, validate_select_only
from app.agent.state import AgentState
from app.config import settings
from app.database import SessionLocal

MAX_RETRIES = 2
QUERY_TIMEOUT_MS = 5000  # guards against an accidental runaway query (e.g. a stray cross join)

# The report node needs enough freedom to sound like a person rather than a
# template, but the persona's hard "never invent a number" rules have to survive
# it. A hallucinated player was observed at 0.3 when rows were passed as raw
# JSON; with the numbered-row format below, this has held up in testing.
REPORT_TEMPERATURE = 0.5

# Reasoning models (Qwen among them) can emit their scratchpad in <think> tags.
# That's internal working, not something to show the user. The second pattern
# matters as much as the first: if the model hits its token limit mid-thought
# there is no closing tag, and a close-tag-only regex silently passes the entire
# raw scratchpad through to the user.
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
UNCLOSED_THINK_RE = re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE)

# Qwen is a reasoning model and, left alone, spends most of its budget in a
# <think> scratchpad before writing a word -- 6000 tokens and ~4s to produce
# ~500 characters of actual answer, and at 2000 tokens it ran out mid-thought
# and returned nothing usable. reasoning_effort='none' turns that off: same
# quality answer in ~1s. The report node describes rows it has already been
# handed; it doesn't need to reason its way to them.
REPORT_MAX_TOKENS = 1200
REPORT_REASONING_EFFORT = "none"

# A report is a briefing, not a database dump. Past this many rows the writer
# gets a truncated view -- it can still describe the leaders, which is what
# ranking questions actually want, without burning the token budget on a tail
# of one-goal players.
MAX_ROWS_IN_PROMPT = 25


def _llm(
    model: str,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> ChatGroq:
    extra = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    return ChatGroq(
        model=model,
        groq_api_key=settings.groq_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        model_kwargs=extra,
    )


def _strip_think(text_out: str) -> str:
    cleaned = THINK_BLOCK_RE.sub("", text_out)
    cleaned = UNCLOSED_THINK_RE.sub("", cleaned)
    return cleaned.strip()


def _sql_history_block(state: AgentState) -> str:
    """Prior turns as question/SQL pairs, so a follow-up like "and their goals?"
    can be resolved against what was actually asked and queried before."""
    if not state["history"]:
        return ""
    lines = ["Earlier in this conversation (oldest first):"]
    for i, turn in enumerate(state["history"], start=1):
        lines.append(f"[{i}] They asked: {turn.question}")
        if turn.sql:
            lines.append(f"    You answered with this SQL:\n{turn.sql}")
    lines.append(
        "\nThe new question may refer back to any of the above ('them', 'those players', "
        "'that team', 'what about 2022'). Resolve those references yourself and write a "
        "complete, standalone query -- the database has no idea a conversation is happening."
    )
    return "\n".join(lines) + "\n\n"


def generate_sql(state: AgentState) -> AgentState:
    """The SQL Agent: turns the question (and, on a retry, the previous error) into SQL."""
    messages = [
        SystemMessage(
            content=f"{SCHEMA_DESCRIPTION}\n\n{_sql_history_block(state)}"
            "Write exactly one PostgreSQL SELECT query that answers the user's question. "
            "Return ONLY the SQL -- no explanation, no markdown fences."
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
        response = _llm(settings.groq_sql_model).invoke(messages)
        sql = extract_sql(_strip_think(response.content))
        return {**state, "sql": sql, "error": None}
    except Exception as exc:
        # A transient LLM API failure (rate limit, timeout, ...) shouldn't crash the graph.
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


def _format_rows_for_prompt(rows: list[dict]) -> str:
    """Numbered, plain-text rows are noticeably easier for the model to count and
    reference accurately than a raw JSON dump -- a real hallucination (a player
    who doesn't exist in the data, and a wrong count of how many were named) was
    observed with JSON-formatted rows and did not reproduce after this change."""
    if not rows:
        return "(no rows returned)"
    shown = rows[:MAX_ROWS_IN_PROMPT]
    lines = []
    for i, row in enumerate(shown, start=1):
        pairs = ", ".join(f"{k}={v}" for k, v in row.items())
        lines.append(f"{i}. {pairs}")
    if len(rows) > len(shown):
        lines.append(
            f"(showing the first {len(shown)} of {len(rows)} rows -- describe these, "
            f"and don't speculate about the rest)"
        )
    return "\n".join(lines)


def write_report(state: AgentState) -> AgentState:
    """The Scout: turns the query results into the spoken-aloud answer."""
    messages: list = [
        SystemMessage(
            content=PERSONA
            + "\nOnly discuss rows that actually bear on the question. If a player "
            "contributed nothing relevant (zero goals in a goals question), leave them out "
            "rather than listing them.\n\n"
            "Use plain prose. Reach for a Markdown table only when the question genuinely "
            "asks to compare many players across several columns at once.\n\n"
            "The rows you're given are filtered to answer this exact question -- they are not "
            "the full picture, and a query that returns one row does not mean only one player "
            "exists. Never draw a conclusion about anyone who isn't listed: don't say they "
            "lack data, didn't play, didn't feature, or anything else about them. Don't remark "
            "on how many rows you were handed. Talk only about who is actually in front of you."
        )
    ]

    # Replay the conversation as real turns rather than describing it in text --
    # the model then treats a follow-up as continuing a chat it was part of, and
    # can naturally say things like "same lad as before".
    for turn in state["history"]:
        messages.append(HumanMessage(content=turn.question))
        messages.append(AIMessage(content=turn.report))

    messages.append(
        HumanMessage(
            content=f"{state['question']}\n\n"
            f"(Data for this question -- these numbered rows are the only facts you have; "
            f"every name and number you say must come from here)\n"
            f"{_format_rows_for_prompt(state['rows'])}"
        )
    )

    try:
        raw = (
            _llm(
                settings.groq_report_model,
                REPORT_TEMPERATURE,
                REPORT_MAX_TOKENS,
                REPORT_REASONING_EFFORT,
            )
            .invoke(messages)
            .content
        )
        report = _strip_think(raw)
        if not report:
            # The model spent its whole budget thinking and never wrote an answer.
            # Better to say so than to return an empty string.
            report = (
                "I couldn't put that into words -- the write-up ran out of room. "
                "Try asking for a narrower slice."
            )
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
    # Stays plain and honest rather than in-character: when something is broken,
    # the useful thing is a clear signal and the actual error, not a joke.
    report = (
        f"I can't get you an answer on that one -- my query kept failing after "
        f"{state['retries']} attempt(s). Try rephrasing it. (Last error: {state['error']})"
    )
    return {**state, "report": report}
