"""
app.py — Flask web server for the Google Drive Search Agent.

Local:   python app.py  →  http://localhost:5000
Railway: gunicorn app:app (via Procfile)
"""

import json
import os
import queue
import threading
from functools import wraps

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, Response, redirect, request, session, send_from_directory
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from werkzeug.middleware.proxy_fix import ProxyFix

from agent.agent import run, MaxTurnsExceeded
from agent.prompts import PROMPT_A, PROMPT_B

# ── Write credential files from env vars at startup ────────────────────────────
# (needed on Railway where the filesystem is ephemeral)
def _bootstrap_credentials():
    import base64
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "./credentials.json")
    b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
    if b64 and not os.path.exists(creds_path):
        with open(creds_path, "wb") as f:
            f.write(base64.b64decode(b64))

_bootstrap_credentials()

# ── Startup diagnostics ────────────────────────────────────────────────────────
print(f"[startup] APP_URL         = {repr(os.getenv('APP_URL'))}")
print(f"[startup] FLASK_SECRET_KEY set = {bool(os.getenv('FLASK_SECRET_KEY'))}")
print(f"[startup] GOOGLE_CREDENTIALS_B64 set = {bool(os.getenv('GOOGLE_CREDENTIALS_B64'))}")

# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder="frontend", static_url_path="")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_port=1)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("APP_URL", "").startswith("https")

# Allow http for local dev
if not os.getenv("APP_URL", "").startswith("https"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly",
          "https://www.googleapis.com/auth/userinfo.email",
          "openid"]

PROMPTS = {"a": PROMPT_A, "b": PROMPT_B}

# ── OAuth helpers ─────────────────────────────────────────────────────────────

def _creds_path():
    return os.getenv("GOOGLE_CREDENTIALS_PATH", "./credentials.json")


def _callback_uri():
    base = os.getenv("APP_URL", "http://localhost:5000").rstrip("/")
    return base + "/auth/callback"


def _make_flow():
    return Flow.from_client_secrets_file(_creds_path(), scopes=SCOPES,
                                         redirect_uri=_callback_uri())


def _creds_to_dict(c: Credentials) -> dict:
    return {
        "token": c.token,
        "refresh_token": c.refresh_token,
        "token_uri": c.token_uri,
        "client_id": c.client_id,
        "client_secret": c.client_secret,
        "scopes": list(c.scopes) if c.scopes else [],
    }


def _session_creds() -> Credentials | None:
    d = session.get("credentials")
    if not d:
        return None
    creds = Credentials(**{k: d[k] for k in
                           ("token", "refresh_token", "token_uri",
                            "client_id", "client_secret", "scopes")})
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        session["credentials"] = _creds_to_dict(creds)
    return creds


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("credentials"):
            return {"error": "Not authenticated", "auth_required": True}, 401
        return f(*args, **kwargs)
    return decorated

# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/auth/login")
def auth_login():
    try:
        flow = _make_flow()
    except FileNotFoundError:
        return ("credentials.json not found. Set GOOGLE_CREDENTIALS_B64 env var in Railway.", 500)
    except ValueError as e:
        return (f"credentials.json error (need 'Web Application' type, not Desktop): {e}", 500)
    except Exception as e:
        return (f"Auth setup error: {e}", 500)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    session["oauth_state"] = state
    return redirect(auth_url)


@app.route("/auth/callback")
def auth_callback():
    flow = _make_flow()
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    session["credentials"] = _creds_to_dict(creds)

    # Fetch user email to display in UI
    try:
        import google.oauth2.id_token
        import google.auth.transport.requests
        req = google.auth.transport.requests.Request()
        info = google.oauth2.id_token.verify_oauth2_token(
            creds.id_token, req, clock_skew_in_seconds=10
        ) if hasattr(creds, "id_token") and creds.id_token else {}
        session["user_email"] = info.get("email", "")
    except Exception:
        session["user_email"] = ""

    return redirect("/")


@app.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/")


@app.route("/auth/status")
def auth_status():
    return {
        "authenticated": bool(session.get("credentials")),
        "email": session.get("user_email", ""),
    }

# ── Static / UI ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")

# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
@require_auth
def chat():
    data = request.get_json(force=True)
    question = (data.get("question") or "").strip()
    prompt_key = data.get("prompt", "b").lower()

    if not question:
        return {"error": "No question provided."}, 400

    system_prompt = PROMPTS.get(prompt_key, PROMPT_B)
    creds = _session_creds()

    q: queue.Queue = queue.Queue()

    def worker():
        try:
            result = run(question, system_prompt=system_prompt, credentials=creds)
            q.put({"type": "done", "payload": result})
        except MaxTurnsExceeded as e:
            q.put({"type": "error", "payload": str(e)})
        except Exception as e:
            q.put({"type": "error", "payload": str(e)})

    threading.Thread(target=worker, daemon=True).start()

    def generate():
        yield f"data: {json.dumps({'type': 'thinking'})}\n\n"
        item = q.get(timeout=120)
        yield f"data: {json.dumps(item)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/files")
@require_auth
def files():
    from agent.tools import list_files
    folder_id = request.args.get("folder_id") or None
    try:
        return {"files": list_files(folder_id=folder_id, credentials=_session_creds())}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/search")
@require_auth
def search():
    from agent.tools import search_drive
    q = request.args.get("q", "").strip()
    if not q:
        return {"error": "No query."}, 400
    try:
        return {"files": search_drive(q, credentials=_session_creds())}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/eval", methods=["POST"])
@require_auth
def eval_endpoint():
    from eval.runner import _load_questions, _is_correct

    data = request.get_json(force=True)
    variant = data.get("prompt", "both")  # "a", "b", or "both"
    creds = _session_creds()

    prompts_to_run = []
    if variant in ("a", "both"):
        prompts_to_run.append(("a", PROMPT_A))
    if variant in ("b", "both"):
        prompts_to_run.append(("b", PROMPT_B))

    questions = _load_questions()

    def generate():
        for label, system_prompt in prompts_to_run:
            for q in questions:
                try:
                    result = run(q["question"], system_prompt=system_prompt, credentials=creds)
                    correct = _is_correct(q["expected_answer"], result["answer"])
                    payload = {
                        "type": "result",
                        "prompt": label,
                        "id": q["id"],
                        "question": q["question"],
                        "correct": correct,
                        "input_tokens": result["input_tokens"],
                        "output_tokens": result["output_tokens"],
                        "tool_calls": result["tool_calls"],
                        "turns": result["turns"],
                    }
                except Exception as e:
                    payload = {
                        "type": "result",
                        "prompt": label,
                        "id": q["id"],
                        "question": q["question"],
                        "correct": False,
                        "error": str(e),
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "tool_calls": 0,
                        "turns": 0,
                    }
                yield f"data: {json.dumps(payload)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"Starting Drive Agent on http://localhost:{port}\n")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
