"""In-process conversation memory, keyed by session id.

Deliberately NOT LangGraph's built-in checkpointer: a checkpointer persists the
whole graph state, which includes the full `rows` result of every query. Feeding
those raw blobs back into the prompt on each follow-up would bloat the context
fast and give the model more chances to misread numbers. What a follow-up
actually needs is much smaller -- what was asked, what SQL answered it, and what
we told the user -- so we store exactly that and nothing else.

Scope note: this lives in the API process's memory, so it resets on restart and
wouldn't be shared across multiple server instances. That's the right trade-off
for a single-instance portfolio project; swapping this class for Redis or a
`conversations` table later would not require touching any other file.
"""

from collections import OrderedDict
from dataclasses import dataclass

MAX_TURNS_REMEMBERED = 6  # how much of a conversation the agent can see
MAX_SESSIONS = 200  # oldest conversations are evicted past this, so memory can't grow forever


@dataclass
class Turn:
    question: str
    sql: str | None
    report: str


class SessionStore:
    def __init__(self, max_turns: int = MAX_TURNS_REMEMBERED, max_sessions: int = MAX_SESSIONS):
        self._sessions: OrderedDict[str, list[Turn]] = OrderedDict()
        self._max_turns = max_turns
        self._max_sessions = max_sessions

    def history(self, session_id: str) -> list[Turn]:
        turns = self._sessions.get(session_id, [])
        if turns:
            self._sessions.move_to_end(session_id)  # mark as recently used
        return turns

    def append(self, session_id: str, turn: Turn) -> None:
        turns = self._sessions.setdefault(session_id, [])
        turns.append(turn)
        # Keep only the most recent turns: older context stops being useful and
        # every extra turn spends prompt budget.
        if len(turns) > self._max_turns:
            del turns[: len(turns) - self._max_turns]
        self._sessions.move_to_end(session_id)
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)  # evict least recently used

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


store = SessionStore()
