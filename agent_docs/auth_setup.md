# Auth Setup

## Anthropic API Key
1. Go to console.anthropic.com → API Keys → Create Key
2. Add to .env: `ANTHROPIC_API_KEY=sk-ant-...`

## Google Drive OAuth
1. console.cloud.google.com → New Project
2. APIs & Services → Library → "Google Drive API" → Enable
3. APIs & Services → Credentials → Create OAuth 2.0 Client ID → Desktop App → Download JSON
4. Rename downloaded file to `credentials.json`, place in project root
5. First `python main.py` opens browser OAuth flow → creates `token.json` automatically

## .env variables
```
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_CREDENTIALS_PATH=./credentials.json
GOOGLE_TOKEN_PATH=./token.json
```

## Security reminders
- .env, credentials.json, token.json are all in .gitignore
- If a key is accidentally committed: rotate it immediately, then scrub git history
