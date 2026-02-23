# Google Drive Search Agent

## WHY
LLM-powered chatbot that searches Google Drive and answers questions about documents.
Includes an eval framework comparing two system prompt variants by token efficiency.

## WHAT
- `main.py` — CLI entrypoint (chat mode + eval mode)
- `agent/agent.py` — agentic tool-use loop (send → tool_use → execute → repeat → end_turn)
- `agent/tools.py` — Google Drive tool functions + Anthropic tool schemas
- `agent/prompts.py` — PROMPT_A (baseline) and PROMPT_B (optimized) system prompts
- `eval/runner.py` — runs questions.json against both prompts, records token metrics
- `eval/questions.json` — test questions with expected answers

## HOW

### Run the project
```bash
python main.py              # interactive chat
python main.py --eval       # eval both prompts
python main.py --eval --prompt b
```

### Install
```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in keys
```

### Secrets
Never commit `.env`, `credentials.json`, or `token.json` — all gitignored.

## Reference docs
Read these only when working on the relevant area:

- `agent_docs/agent_loop.md` — tool-use loop contract, max_turns guard, return shape
- `agent_docs/google_drive_tools.md` — tool specs, mime type handling, token-saving rules
- `agent_docs/eval_framework.md` — eval metric definitions, correctness check, output format
- `agent_docs/auth_setup.md` — Anthropic + Google OAuth setup steps
