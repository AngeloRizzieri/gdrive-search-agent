# Eval Framework

## Purpose
Compare PROMPT_A vs PROMPT_B on the same question set.
Winner = same or better accuracy at fewer total tokens.

## questions.json schema
```json
[{ "id": "q1", "question": "...", "expected_answer": "...", "source_file": "...", "notes": "..." }]
```

## Correctness check
`expected_answer.lower() in response.lower()` — simple substring match, case-insensitive.

## Metrics recorded per question per prompt
| Field | Description |
|---|---|
| `correct` | bool |
| `input_tokens` | total input tokens across all turns |
| `output_tokens` | total output tokens across all turns |
| `tool_calls` | number of tool calls made |
| `turns` | number of loop iterations |

## Output
- Print comparison table to stdout (Prompt A vs B, per question + averages)
- Save full results to `eval/results/run_{timestamp}.json`

## Usage
```bash
python main.py --eval            # both prompts
python main.py --eval --prompt a # one prompt
```
