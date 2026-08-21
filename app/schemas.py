"""Pydantic request/response models for the API layer.

Kept separate from app/agent/state.py (the internal LangGraph state) on purpose:
the internal state is free to change shape as the agent evolves, but the public
API's contract shouldn't shift just because we refactor the pipeline internally.
"""

from pydantic import BaseModel, Field


class ScoutRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=500,
        examples=["Find me the top 3 center-backs by pass completion rate"],
    )
    session_id: str | None = Field(
        default=None,
        description=(
            "Omit on the first message and one will be created for you; send the same "
            "value back on later messages to continue that conversation, so follow-ups "
            "like 'and their goals?' resolve against what was already asked."
        ),
    )


class ScoutResponse(BaseModel):
    session_id: str
    question: str
    sql: str | None
    rows: list[dict] | None
    report: str
    retries: int
    succeeded: bool
