import json
import os
from datetime import datetime
from agent.agent import run
from agent.prompts import DEFAULT_PROMPT

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
        print(f"  [prompt {prompt_label}] {q['id']}: {q['question'][:60]}...")
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


def _print_table(prompt_results: list[tuple[str, list[dict]]]):
    all_ids = prompt_results[0][1] and [r["id"] for r in prompt_results[0][1]] or []
    header = f"{'Question':<12} {'Prompt':>8} {'Correct':>8} {'In Tok':>8} {'Out Tok':>8} {'Tools':>6} {'Turns':>6}"
    print("\n" + "=" * len(header))
    print(header)
    print("=" * len(header))

    def row(r, label):
        return (f"{r['id']:<12} {label:>8} {'YES' if r['correct'] else 'NO':>8} "
                f"{r['input_tokens']:>8} {r['output_tokens']:>8} {r['tool_calls']:>6} {r['turns']:>6}")

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
              f"{avg['avg_tool_calls']:>6.1f} {avg['avg_turns']:>6.1f}")
    print("=" * len(header) + "\n")


def run_eval(prompts: list[str] | None = None):
    """
    Run eval against one or two system prompts.
    prompts: list of prompt strings. If None/empty, uses DEFAULT_PROMPT.
    """
    if not prompts:
        prompts = [DEFAULT_PROMPT]
    prompts = prompts[:2]

    questions = _load_questions()
    print(f"Running eval on {len(questions)} question(s) with {len(prompts)} prompt(s)...\n")

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
        "questions": len(questions),
        "prompts": [{"label": label, "results": results} for label, results in prompt_results],
    }
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Results saved to {output_path}")
