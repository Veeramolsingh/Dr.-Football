# Dr. Football

Ask a football scouting question in plain English. Get an answer backed by real SQL
over real match data — written by a coach who cares more about space than statistics.

```
You:  Find me the top 3 center-backs by pass completion rate

The Professor:
  Van Dijk, 94% — but look at where the passes go. He plays simple, simple,
  simple, and then one pass and the line is broken. This is the thing.
```

Under the hood it is a LangGraph agent that writes PostgreSQL against StatsBomb
World Cup data, runs it, checks its own work, and then explains the numbers.

---

## How it works

```
  question
     |
     v
generate_sql  ──>  run_sql  ──(ok)──>  write_report  ──>  answer
     ^                │
     │                ├──(bad SQL, retries left)──>  back to generate_sql
     └────────────────┤
                      └──(retries exhausted)──────>  give_up
```

Four nodes, one conditional edge. The interesting part is the loop: when Postgres
rejects the generated query, the error text goes back into the prompt and the model
tries again — up to twice — before the agent admits defeat instead of inventing an
answer.

| Node | File | Does |
|---|---|---|
| `generate_sql` | [`app/agent/nodes.py`](app/agent/nodes.py) | Question + schema + history → a `SELECT` |
| `run_sql` | same | Validates, executes, captures errors for the retry loop |
| `write_report` | same | Turns result rows into prose, in character |
| `give_up` | same | Fails honestly when the query can't be salvaged |

## Design decisions worth explaining

**Two models, not one.** `gpt-oss-120b` writes the SQL; `qwen3.6-27b` writes the
prose. This isn't premature optimisation — gpt-oss is excellent at structured output
and effectively immune to persona instructions (verified: same terse list at
temperature 0.4 and 0.8, with the full persona prompt applied). Qwen actually acts.
See [`app/config.py`](app/config.py).

**SQL safety is code, not a prompt.** The SQL agent's prompt says "SELECT only", but
a prompt is a request, not a guarantee. [`app/agent/sql_safety.py`](app/agent/sql_safety.py)
independently rejects multi-statement queries, non-`SELECT` statements, and a
blocklist of mutating keywords before anything reaches the database.

**Memory stores answers, not state.** Deliberately not LangGraph's checkpointer — that
persists the whole graph state including every raw result row, which would bloat the
context and give the model more numbers to misread. [`app/agent/memory.py`](app/agent/memory.py)
keeps only what a follow-up needs: question, SQL, answer. LRU-capped at 200 sessions.

**The personality is outranked by the facts.** [`app/agent/persona.py`](app/agent/persona.py)
carries the voice, and then a block of hard rules that explicitly override it: never
state a count unless exactly that many rows are present, never say a figure that
isn't in the data. The character is a homage to an archetype rather than a named real
manager — the agent gives opinions about real living players, and putting invented
verdicts in a real person's mouth reads badly out of context.

**Penalty shootouts are not goals.** StatsBomb records shootouts as period 5, with
each penalty as an ordinary `Shot` event with `shot_outcome='Goal'`. Counting them
inflated Mbappé to 9 goals in 2022 and Messi to 9. They're dropped at ingestion —
they also skew the match's last recorded minute, which is what `minutes_played` is
measured against.

## Stack

Python 3.11 · FastAPI · LangGraph · SQLAlchemy 2 · PostgreSQL 16 · Groq

Data: [StatsBomb open data](https://github.com/statsbomb/open-data) — World Cup 2018
and 2022, aggregated per player per match.

## Running it

Requires Docker and a free [Groq API key](https://console.groq.com/keys).

```bash
cp .env.example .env          # then paste your GROQ_API_KEY in
docker compose up -d          # Postgres on port 5433
pip install -r requirements.txt
python -m scripts.init_db
python -m scripts.ingest_data # a few minutes; StatsBomb's API is the bottleneck
uvicorn app.main:app --reload
```

Then open **http://localhost:8000** for the chat UI, or `/docs` for Swagger.
`/health` verifies the API can actually reach Postgres, not just that it booted.

There's also a terminal client: `python -m scripts.chat`

## API

```http
POST /scout
{ "question": "Who created the most chances from midfield?", "session_id": "optional" }
```

Returns the answer, the SQL that produced it, the raw rows, and how many retries it
took. Omit `session_id` on the first call and one is issued; send it back to continue
the conversation. `DELETE /scout/{session_id}` forgets it.

## What's in the database

`competitions` · `teams` · `players` · `matches` · `player_match_stats`

Per-appearance stats: minutes, passes attempted/completed, completion rate, shots,
goals, assists, tackles, interceptions, dribbles. Positions are stored three ways —
raw StatsBomb label, normalised role, and broad group — so the agent can filter at
whatever granularity the question implies. Non-appearances are never stored, since
all-zero rows would silently drag down every `AVG()` the agent writes.
