import json
import os
import anthropic
from datetime import datetime
from dotenv import load_dotenv
from agent.agent import run
from agent.prompts import DEFAULT_PROMPT

load_dotenv()

QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), "questions.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

# Haiku is ~20x cheaper than Sonnet — used for both agent runs and judging
EVAL_MODEL = "claude-haiku-4-5-20251001"

_judge_client = None


def _get_judge_client():
    global _judge_client
    if _judge_client is None:
        _judge_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _judge_client


def _load_questions() -> list[dict]:
    with open(QUESTIONS_PATH) as f:
        return json.load(f)


_JUDGE_PROMPT = """\
You are an expert evaluator. Assess whether the model answer correctly answers the question.

Question: {question}
Expected answer: {expected}
Model answer: {actual}

Reason step by step:
1. What is the core factual claim in the expected answer?
2. Does the model answer convey the same fact, even if worded differently or with more detail?
3. Does the model answer contradict or omit the expected fact?

After your reasoning, output your verdict on the very last line in exactly this format:
VERDICT: YES
or
VERDICT: NO"""


def _is_correct(question: str, expected: str, response: str) -> bool:
    """G-Eval style judge: chain-of-thought reasoning → structured VERDICT line.
    More reliable than raw YES/NO for paraphrased or human-written expected answers."""
    client = _get_judge_client()
    msg = client.messages.create(
        model=EVAL_MODEL,
        max_tokens=256,  # room for CoT reasoning + verdict
        messages=[{"role": "user", "content": _JUDGE_PROMPT.format(
            question=question,
            expected=expected,
            actual=response[:600],
        )}],
    )
    text = msg.content[0].text.strip()
    for line in reversed(text.splitlines()):
        if "VERDICT:" in line.upper():
            return "YES" in line.upper()
    return False  # fail-safe: no verdict found → mark as incorrect


def _run_prompt(questions: list[dict], prompt_label: str, system_prompt: str) -> list[dict]:
    results = []
    for q in questions:
        print(f"  [prompt {prompt_label}] {q['id']}: {q['question'][:60]}...")
        try:
            result = run(q["question"], system_prompt=system_prompt, model=EVAL_MODEL,
                         max_turns=5, max_tokens=1024)
            correct = _is_correct(q["question"], q["expected_answer"], result["answer"])
        except Exception as e:
            result = {"answer": f"ERROR: {e}", "input_tokens": 0, "output_tokens": 0,
                      "cache_read_tokens": 0, "cache_creation_tokens": 0, "tool_calls": 0, "turns": 0}
            correct = False

        results.append({
            "id": q["id"],
            "question": q["question"],
            "expected_answer": q["expected_answer"],
            "response": result["answer"],
            "correct": correct,
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "cache_read_tokens": result.get("cache_read_tokens", 0),
            "cache_creation_tokens": result.get("cache_creation_tokens", 0),
            "tool_calls": result["tool_calls"],
            "turns": result["turns"],
        })
        status = "PASS" if correct else "FAIL"
        cache_read = result.get("cache_read_tokens", 0)
        print(f"    → {status} | in={result['input_tokens']} out={result['output_tokens']} "
              f"cache_read={cache_read} tools={result['tool_calls']}")
        print(f"    Expected : {q['expected_answer']}")
        print(f"    Got      : {result['answer'][:300]}")
    return results


def _averages(results: list[dict]) -> dict:
    n = len(results)
    if n == 0:
        return {}
    return {
        "accuracy": sum(r["correct"] for r in results) / n,
        "avg_input_tokens": sum(r["input_tokens"] for r in results) / n,
        "avg_output_tokens": sum(r["output_tokens"] for r in results) / n,
        "avg_cache_read_tokens": sum(r.get("cache_read_tokens", 0) for r in results) / n,
        "avg_cache_creation_tokens": sum(r.get("cache_creation_tokens", 0) for r in results) / n,
        "avg_tool_calls": sum(r["tool_calls"] for r in results) / n,
        "avg_turns": sum(r["turns"] for r in results) / n,
    }


def _print_table(prompt_results: list[tuple[str, list[dict]]]):
    all_ids = prompt_results[0][1] and [r["id"] for r in prompt_results[0][1]] or []
    header = (f"{'Question':<12} {'Prompt':>8} {'Correct':>8} {'In Tok':>8} {'Out Tok':>8} "
              f"{'CacheRd':>8} {'Tools':>6} {'Turns':>6}")
    print("\n" + "=" * len(header))
    print(header)
    print("=" * len(header))

    def row(r, label):
        return (f"{r['id']:<12} {label:>8} {'YES' if r['correct'] else 'NO':>8} "
                f"{r['input_tokens']:>8} {r['output_tokens']:>8} "
                f"{r.get('cache_read_tokens', 0):>8} {r['tool_calls']:>6} {r['turns']:>6}")

    for qid in all_ids:
        for label, results in prompt_results:
            r = next((r for r in results if r["id"] == qid), None)
            if r:
                print(row(r, label))

    print("-" * len(header))
    for label, results in prompt_results:
        if not results:
            continue
        avg = _averages(results)
        print(f"{'AVERAGE':<12} {label:>8} {avg['accuracy']*100:>7.0f}% "
              f"{avg['avg_input_tokens']:>8.0f} {avg['avg_output_tokens']:>8.0f} "
              f"{avg['avg_cache_read_tokens']:>8.0f} "
              f"{avg['avg_tool_calls']:>6.1f} {avg['avg_turns']:>6.1f}")
    print("=" * len(header))

    # Detailed answer breakdown
    print("\n--- Answer Details ---")
    for qid in all_ids:
        for label, results in prompt_results:
            r = next((r for r in results if r["id"] == qid), None)
            if not r:
                continue
            status = "PASS" if r["correct"] else "FAIL"
            print(f"\n[{r['id']}] Prompt {label} — {status}")
            print(f"  Q        : {r['question']}")
            print(f"  Expected : {r['expected_answer']}")
            print(f"  Got      : {r['response'][:400]}")
    print()


def run_eval(prompts: list[str] | None = None):
    """
    Run eval against one or two system prompts.
    prompts: list of prompt strings. If None/empty, uses DEFAULT_PROMPT.
    """
    if not prompts:
        prompts = [DEFAULT_PROMPT]
    prompts = prompts[:2]

    questions = _load_questions()
    print(f"Running eval on {len(questions)} question(s) with {len(prompts)} prompt(s)...")
    print(f"Agent model: {EVAL_MODEL}\n")

    prompt_results = []
    for i, system_prompt in enumerate(prompts):
        label = str(i + 1)
        print(f"--- Prompt {label} ---")
        results = _run_prompt(questions, label, system_prompt)
        prompt_results.append((label, results))

    _print_table(prompt_results)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(RESULTS_DIR, f"run_{timestamp}.json")
    payload = {
        "timestamp": timestamp,
        "model": EVAL_MODEL,
        "questions": len(questions),
        "prompts": [{"label": label, "results": results} for label, results in prompt_results],
    }
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Results saved to {output_path}")
