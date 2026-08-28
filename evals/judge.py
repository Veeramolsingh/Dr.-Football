"""Phase 2 of the eval: score the recorded agent runs with DeepEval.

Runs in its own venv (deepeval is not a dependency of the app). The judge is
openai/gpt-oss-120b on Groq -- the strongest model already available on this
project's API key.

Metrics per case:
  - Correctness (GEval, LLM-as-a-judge): report vs the golden expected answer.
  - Faithfulness: every claim in the report must be grounded in the SQL rows
    the writer was actually handed (only scored when the query succeeded).

Usage:
    python evals/judge.py <agent_runs.json> <results.json>
"""

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

from groq import Groq, RateLimitError  # noqa: E402
from deepeval.metrics import FaithfulnessMetric, GEval  # noqa: E402
from deepeval.models import DeepEvalBaseLLM  # noqa: E402
from deepeval.test_case import LLMTestCase, LLMTestCaseParams  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

JUDGE_MODEL = "openai/gpt-oss-120b"


class GroqJudge(DeepEvalBaseLLM):
    """DeepEval judge backed by Groq, with JSON-schema enforcement and
    rate-limit backoff (the free tier throttles hard)."""

    def __init__(self):
        self.client = Groq(api_key=os.environ["GROQ_API_KEY"])

    def load_model(self):
        return self.client

    def _chat(self, messages, json_mode: bool) -> str:
        for attempt in range(6):
            try:
                resp = self.client.chat.completions.create(
                    model=JUDGE_MODEL,
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_object"} if json_mode else None,
                )
                return resp.choices[0].message.content
            except RateLimitError:
                wait = 15 * (attempt + 1)
                print(f"    (rate limited, waiting {wait}s)", flush=True)
                time.sleep(wait)
        raise RuntimeError("judge: rate limited 6 times in a row")

    def generate(self, prompt: str, schema=None):
        if schema is None:
            return self._chat([{"role": "user", "content": prompt}], json_mode=False)
        sys_msg = (
            "Respond ONLY with a JSON object matching this JSON schema exactly:\n"
            + json.dumps(schema.model_json_schema())
        )
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}]
        last_err = None
        for _ in range(3):
            raw = self._chat(messages, json_mode=True)
            try:
                return schema.model_validate_json(raw)
            except Exception as exc:
                last_err = exc
        raise RuntimeError(f"judge returned unparseable JSON 3 times: {last_err}")

    async def a_generate(self, prompt: str, schema=None):
        return self.generate(prompt, schema)

    def get_model_name(self):
        return f"groq/{JUDGE_MODEL}"


def main(runs_path: str, out_path: str):
    records = json.loads(Path(runs_path).read_text(encoding="utf-8"))
    judge = GroqJudge()

    correctness = GEval(
        name="Correctness",
        criteria=(
            "Compare the actual output against the expected answer. The actual output is "
            "written in a scout's conversational voice -- style, opinions and extra colour "
            "are fine and must NOT be penalised. Judge only the facts: the right players "
            "named, the right numbers attributed, nothing invented that contradicts the "
            "expected answer. Where the expected answer says a tie or a range is acceptable, "
            "any listed alternative counts as fully correct."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
        ],
        model=judge,
        threshold=0.6,
        async_mode=False,
        verbose_mode=False,
    )

    results = []
    for rec in records:
        print(f"judging {rec['id']} ...", flush=True)
        entry = {
            "id": rec["id"],
            "succeeded": rec.get("succeeded"),
            "retries": rec.get("retries"),
            "latency_s": rec.get("latency_s"),
        }

        if rec.get("crashed"):
            entry["correctness"] = 0.0
            entry["correctness_reason"] = f"agent crashed: {rec['crashed']}"
            results.append(entry)
            continue

        tc = LLMTestCase(
            input=rec["question"],
            actual_output=rec["report"],
            expected_output=rec["expected"],
            retrieval_context=rec.get("rows"),
        )

        correctness.measure(tc)
        entry["correctness"] = round(correctness.score, 3)
        entry["correctness_pass"] = correctness.success
        entry["correctness_reason"] = correctness.reason

        if rec.get("succeeded") and rec.get("rows"):
            faith = FaithfulnessMetric(
                model=judge, threshold=0.7, async_mode=False, verbose_mode=False
            )
            faith.measure(tc)
            entry["faithfulness"] = round(faith.score, 3)
            entry["faithfulness_pass"] = faith.success
            entry["faithfulness_reason"] = faith.reason

        if rec.get("safety"):
            entry["db_unchanged"] = rec.get("db_unchanged")

        results.append(entry)
        print(f"  correctness={entry['correctness']} faithfulness={entry.get('faithfulness')}", flush=True)

    Path(out_path).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
