import json
import os
from datetime import datetime
from agent.agent import run
from agent.prompts import PROMPT_A, PROMPT_B

QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), "questions.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def _load_questions() -> list[dict]:
    with open(QUESTIONS_PATH) as f:
        return json.load(f)


def _is_correct(expected: str, response: str) -> bool:
    return expected.lower() in response.lower()


def _run_prompt(questions: list[dict], prompt_label: str, system_prompt: str) -> list[dict]:
    results = []
    for q in questions:
        print(f"  [{prompt_label}] {q['id']}: {q['question'][:60]}...")
        try:
            result = run(q["question"], system_prompt=system_prompt)
            correct = _is_correct(q["expected_answer"], result["answer"])
        except Exception as e:
            result = {"answer": f"ERROR: {e}", "input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "turns": 0}
            correct = False

        results.append({
            "id": q["id"],
            "question": q["question"],
            "expected_answer": q["expected_answer"],
            "response": result["answer"],
            "correct": correct,
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "tool_calls": result["tool_calls"],
            "turns": result["turns"],
        })
        status = "PASS" if correct else "FAIL"
        print(f"    → {status} | in={result['input_tokens']} out={result['output_tokens']} tools={result['tool_calls']}")
    return results


def _averages(results: list[dict]) -> dict:
    n = len(results)
    if n == 0:
        return {}
    return {
        "accuracy": sum(r["correct"] for r in results) / n,
        "avg_input_tokens": sum(r["input_tokens"] for r in results) / n,
        "avg_output_tokens": sum(r["output_tokens"] for r in results) / n,
        "avg_tool_calls": sum(r["tool_calls"] for r in results) / n,
        "avg_turns": sum(r["turns"] for r in results) / n,
    }


def _print_table(results_a: list[dict] | None, results_b: list[dict] | None):
    all_ids = []
    if results_a:
        all_ids = [r["id"] for r in results_a]
    elif results_b:
        all_ids = [r["id"] for r in results_b]

    col = 10
    header = f"{'Question':<12} {'Prompt':>8} {'Correct':>8} {'In Tok':>8} {'Out Tok':>8} {'Tools':>6} {'Turns':>6}"
    print("\n" + "=" * len(header))
    print(header)
    print("=" * len(header))

    def row(r, label):
        return (f"{r['id']:<12} {label:>8} {'YES' if r['correct'] else 'NO':>8} "
                f"{r['input_tokens']:>8} {r['output_tokens']:>8} {r['tool_calls']:>6} {r['turns']:>6}")

    for qid in all_ids:
        if results_a:
            ra = next((r for r in results_a if r["id"] == qid), None)
            if ra:
                print(row(ra, "A"))
        if results_b:
            rb = next((r for r in results_b if r["id"] == qid), None)
            if rb:
                print(row(rb, "B"))

    print("-" * len(header))
    if results_a:
        avg = _averages(results_a)
        print(f"{'AVERAGE':<12} {'A':>8} {avg['accuracy']*100:>7.0f}% "
              f"{avg['avg_input_tokens']:>8.0f} {avg['avg_output_tokens']:>8.0f} "
              f"{avg['avg_tool_calls']:>6.1f} {avg['avg_turns']:>6.1f}")
    if results_b:
        avg = _averages(results_b)
        print(f"{'AVERAGE':<12} {'B':>8} {avg['accuracy']*100:>7.0f}% "
              f"{avg['avg_input_tokens']:>8.0f} {avg['avg_output_tokens']:>8.0f} "
              f"{avg['avg_tool_calls']:>6.1f} {avg['avg_turns']:>6.1f}")
    print("=" * len(header) + "\n")


def run_eval(prompt_variant: str | None = None):
    questions = _load_questions()
    print(f"Running eval on {len(questions)} question(s)...\n")

    results_a = None
    results_b = None

    if prompt_variant in (None, "a"):
        print("--- Prompt A ---")
        results_a = _run_prompt(questions, "A", PROMPT_A)

    if prompt_variant in (None, "b"):
        print("--- Prompt B ---")
        results_b = _run_prompt(questions, "B", PROMPT_B)

    _print_table(results_a, results_b)

    # Save results
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(RESULTS_DIR, f"run_{timestamp}.json")
    payload = {
        "timestamp": timestamp,
        "questions": len(questions),
        "prompt_a": results_a,
        "prompt_b": results_b,
    }
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Results saved to {output_path}")
