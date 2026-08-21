"""FastAPI wrapper around the Phase 3 LangGraph agent.

Run locally with:
    uvicorn app.main:app --reload

Then either:
  - open http://localhost:8000/docs for an interactive test page, or
  - POST to http://localhost:8000/scout with {"question": "..."}
"""

from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.agent.graph import build_graph
from app.agent.state import initial_state
from app.database import engine
from app.schemas import ScoutRequest, ScoutResponse

app = FastAPI(
    title="Autonomous Football Scout",
    description="Ask a football scouting question in plain English; get a SQL-backed, written report.",
    version="0.1.0",
)

# Compiled once at startup and reused for every request -- compiling just wires
# the node functions together (no I/O), and invoking a compiled graph doesn't
# mutate it, so sharing one instance across concurrent requests is safe.
_graph = build_graph()


@app.get("/health")
def health():
    """Readiness check: confirms the API process can actually reach Postgres,
    not just that the process is running."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unreachable: {exc}")


@app.post("/scout", response_model=ScoutResponse)
def scout(request: ScoutRequest) -> ScoutResponse:
    try:
        result = _graph.invoke(initial_state(request.question))
    except Exception as exc:
        # Last-resort guard: app/agent/nodes.py already handles the failure modes
        # we know about (bad SQL, LLM rate limits) gracefully. This is only for
        # something genuinely unexpected -- it turns a crash into a clean 500
        # instead of taking down the request with a raw traceback.
        raise HTTPException(status_code=500, detail=f"unexpected agent failure: {exc}") from exc

    return ScoutResponse(
        question=result["question"],
        sql=result["sql"],
        rows=result["rows"],
        report=result["report"],
        retries=result["retries"],
        succeeded=result["error"] is None,
    )
