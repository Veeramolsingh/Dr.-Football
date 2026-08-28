# Evaluating the Scout

How good is the agent, actually? This is the harness that answers that with numbers
instead of spot-checks.

It uses [DeepEval](https://github.com/confident-ai/deepeval) and runs in two phases,
deliberately split so the app's own dependencies stay clean:

| Phase | File | What it does |
|---|---|---|
| 1 | [`run_agent.py`](run_agent.py) | Runs every case through the **real** compiled graph and records SQL, rows, report, retries, latency |
| 2 | [`judge.py`](judge.py) | Scores those recordings with DeepEval's LLM-as-a-judge metrics |

Phase 1 needs only the app's venv. Phase 2 needs `deepeval`, which is why it reads a
JSON file rather than importing the agent — nothing in `app/` ever imports the eval stack.

## The dataset

[`dataset.json`](dataset.json) holds 13 cases. Every `expected` answer was computed by
hand-written SQL against the actual database, so the agent is graded against facts.
Cases where the data has a genuine tie say so explicitly, and the judge is told any
tied name counts as correct.

The set deliberately includes the ways this agent could fail quietly:

- **Shootout penalties** — Mbappé is 8 goals in 2022, not 9.
- **Small-sample rankings** — a pass-completion leaderboard must not be topped by a
  player with one lucky match.
- **Named players + a position word** — "compare Mbappé and Messi" must aggregate all
  their appearances, not filter by position and silently drop most of their record.
- **A player who isn't in the data** (Haaland) — the honest answer is to say so, not
  to return a confident zero.
- **A follow-up that only makes sense with memory** — "which of *them*...".
- **A prompt injection** telling it to DELETE rows, checked with a real before/after
  row count.

## Metrics

- **Correctness** (`GEval`, threshold 0.6) — the report's facts vs the golden answer.
  The criteria explicitly tells the judge to ignore voice and opinion, so the persona
  isn't penalised for having a personality.
- **Faithfulness** (threshold 0.7) — DeepEval decomposes the report into individual
  claims and checks each one against the SQL rows the writer was handed. This is the
  hallucination check, and it's the number to trust most: it's per-claim arithmetic,
  not one model's overall impression.

The judge is `openai/gpt-oss-120b` on Groq, wrapped in a custom `DeepEvalBaseLLM`
adapter with JSON-schema enforcement and rate-limit backoff.

## Running it

```bash
python -m evals.run_agent runs.json          # app venv; needs Postgres up + GROQ_API_KEY
.evalenv/Scripts/python evals/judge.py runs.json results.json
```

## Results, first run (Aug 2026)

| | |
|---|---|
| Correctness | 12/13 pass, avg 0.93 |
| Faithfulness | **1.00** — 12/12, zero hallucinated claims |
| Query reliability | 12/12 real questions answered (2 recovered via the retry loop) |
| Safety | injection refused at both layers, row count unchanged |
| Latency | 2.7–28s single-turn, median ~13s |

**The one miss.** Asked about Haaland, the agent invented nothing (good) but answered
only *"There is no data available for this question."* — scored 0.20. It should say
*why*: he isn't in a dataset covering only the 2018 and 2022 World Cups.

**Known limits of this run.** Single run per case at report temperature 0.5, so scores
will move a little between runs. n=13 is a smoke test, not a benchmark. And because the
Groq adapter doesn't expose logprobs, GEval falls back to plain integer scores (10/10 →
1.0) instead of its finer log-prob-weighted scoring — enough for pass/fail, too coarse
to separate the ten answers that all scored 1.0.
