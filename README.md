# Google Drive Search Agent

LLM-powered agent (Anthropic SDK only) that searches Google Drive and answers questions about documents. Includes an eval framework to benchmark two system prompt variants by token efficiency.

## Setup

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Configure secrets
cp .env.example .env
# → fill in ANTHROPIC_API_KEY in .env

# 3. Add credentials.json from Google Cloud Console (see CLAUDE.md)

# 4. First run triggers OAuth browser flow
python main.py
```

## Usage

```bash
python main.py              # interactive chat
python main.py --eval       # run eval, both prompts
python main.py --eval --prompt a  # eval prompt A only
```

## Security

- `.env`, `credentials.json`, `token.json` are all gitignored
- Never commit secrets — use `.env.example` as the template
- See CLAUDE.md for full architecture notes
