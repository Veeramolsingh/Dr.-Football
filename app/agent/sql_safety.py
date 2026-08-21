"""Guards the DB Executor node: this is a code-level check, not something we
trust the LLM to police itself. The SQL Agent's prompt already says
"SELECT only", but a prompt is a request, not a guarantee -- this is the
actual enforcement.
"""

import re

FENCE_RE = re.compile(r"^```(?:sql)?\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)
FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXEC|EXECUTE|CALL|MERGE|COPY|VACUUM|ATTACH|REPLACE)\b",
    re.IGNORECASE,
)


def extract_sql(raw: str) -> str:
    """The LLM sometimes wraps its answer in a ```sql ... ``` fence; strip it if present."""
    text = raw.strip()
    fence = FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    return text.rstrip(";").strip()


def validate_select_only(sql: str) -> None:
    """Raises ValueError if `sql` is not a single, plain SELECT statement."""
    if not sql:
        raise ValueError("Empty query.")
    if ";" in sql:
        raise ValueError("Only a single statement is allowed (no semicolons).")
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise ValueError("Only SELECT statements are allowed.")
    if FORBIDDEN_RE.search(sql):
        raise ValueError("Query contains a forbidden keyword.")
