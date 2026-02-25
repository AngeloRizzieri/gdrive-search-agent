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
from agent.prompts import DEFAULT_PROMPT

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

# ── OAuth helpers ─────────────────────────────────────────────────────────────

def _creds_path():
    return os.getenv("GOOGLE_CREDENTIALS_PATH", "./credentials.json")


def _callback_uri():
    app_url = os.getenv("APP_URL")
    if not app_url:
        railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
        if railway_domain:
            app_url = f"https://{railway_domain}"
        else:
            app_url = "http://localhost:5000"
    return app_url.rstrip("/") + "/auth/callback"


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
    # Build the callback URL explicitly from our known base to avoid
    # http/https scheme mismatch when Railway terminates TLS at its load balancer.
    callback_url = _callback_uri() + "?" + request.query_string.decode("utf-8")
    flow.fetch_token(authorization_response=callback_url)
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


@app.route("/api/default-prompt")
def default_prompt():
    return {"prompt": DEFAULT_PROMPT}

# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
@require_auth
def chat():
    data = request.get_json(force=True)
    question = (data.get("question") or "").strip()
    system_prompt = (data.get("system_prompt") or "").strip()
    _ALLOWED_MODELS = {"claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-6"}
    model = (data.get("model") or "").strip()
    if model not in _ALLOWED_MODELS:
        model = "claude-sonnet-4-6"

    if not question:
        return {"error": "No question provided."}, 400
    creds = _session_creds()

    q: queue.Queue = queue.Queue()

    def worker():
        try:
            result = run(question, system_prompt=system_prompt, credentials=creds,
                         model=model, event_queue=q)
            q.put({"type": "done", "payload": result})
        except MaxTurnsExceeded as e:
            q.put({"type": "error", "payload": str(e)})
        except Exception as e:
            q.put({"type": "error", "payload": str(e)})

    threading.Thread(target=worker, daemon=True).start()

    def generate():
        yield f"data: {json.dumps({'type': 'thinking'})}\n\n"
        while True:
            try:
                item = q.get(timeout=180)
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("type") in ("done", "error"):
                    return
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'error', 'payload': 'Request timed out'})}\n\n"
                return

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/files")
@require_auth
def files():
    from agent.tools import list_files
    folder_id = request.args.get("folder_id") or None
    try:
        return {"files": list_files(folder_id=folder_id, max_results=50, credentials=_session_creds())}
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
    # prompts: list of up to 2 prompt strings (or empty string = no system prompt).
    prompts_input = data.get("prompts") or [""]
    prompts_to_run = [
        (str(i + 1), t.strip())
        for i, t in enumerate(prompts_input[:2])
    ]
    _ALLOWED_MODELS = {"claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-6"}
    model = (data.get("model") or "").strip()
    if model not in _ALLOWED_MODELS:
        model = "claude-sonnet-4-6"
    creds = _session_creds()

    # Accept inline questions from the UI, or fall back to questions.json
    custom_questions = data.get("questions")
    questions = custom_questions if custom_questions else _load_questions()

    def generate():
        for label, system_prompt in prompts_to_run:
            for q in questions:
                try:
                    result = run(q["question"], system_prompt=system_prompt, credentials=creds, model=model)
                    correct = _is_correct(q["question"], q["expected_answer"], result["answer"])
                    payload = {
                        "type": "result",
                        "prompt": label,
                        "id": q["id"],
                        "question": q["question"],
                        "expected_answer": q["expected_answer"],
                        "response": result["answer"],
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
                        "expected_answer": q.get("expected_answer", ""),
                        "response": f"ERROR: {e}",
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


# ── Eval question management ──────────────────────────────────────────────────

@app.route("/eval/questions", methods=["GET"])
@require_auth
def get_questions():
    from eval.runner import _load_questions
    try:
        return {"questions": _load_questions()}
    except Exception as e:
        return {"questions": [], "error": str(e)}


@app.route("/eval/questions", methods=["POST"])
@require_auth
def save_questions():
    data = request.get_json(force=True)
    questions = data.get("questions", [])
    for q in questions:
        if not all(k in q for k in ("id", "question", "expected_answer")):
            return {"error": "Each question needs id, question, expected_answer"}, 400
    try:
        path = os.path.join(os.path.dirname(__file__), "eval", "questions.json")
        with open(path, "w") as f:
            json.dump(questions, f, indent=2)
        return {"ok": True, "count": len(questions)}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/eval/generate-questions", methods=["POST"])
@require_auth
def generate_questions():
    import re
    data = request.get_json(force=True)
    count = max(1, min(int(data.get("count", 5)), 20))
    _ALLOWED_MODELS = {"claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-6"}
    model = (data.get("model") or "").strip()
    if model not in _ALLOWED_MODELS:
        model = "claude-sonnet-4-6"
    creds = _session_creds()

    gen_system = f"""You are a test-dataset creator for a Google Drive search agent evaluation.

Your job: generate {count} diverse question-answer pairs that will be used to benchmark an agent's ability to find information in Google Drive.

Steps:
1. Use list_files or search_drive to discover what files exist.
2. Use read_document to read the content of several files.
3. For each file you read, create 1-2 questions whose answers appear literally in the document text.

Requirements:
- expected_answer should be a short, specific phrase or value from the document (the evaluator uses semantic matching, so exact wording is not required but specificity helps).
- Questions should be diverse: different files, different info types (dates, names, numbers, topics).
- Assign sequential ids: q1, q2, q3, ...

Return ONLY a valid JSON array, no prose before or after:
[{{"id":"q1","question":"...","expected_answer":"..."}}]"""

    q: queue.Queue = queue.Queue()

    def worker():
        try:
            result = run(
                f"Generate {count} evaluation questions from my Google Drive files. Return only a JSON array.",
                system_prompt=gen_system,
                credentials=creds,
                model=model,
            )
            q.put({"type": "done", "payload": result})
        except Exception as e:
            q.put({"type": "error", "payload": str(e)})

    threading.Thread(target=worker, daemon=True).start()

    def generate():
        yield f"data: {json.dumps({'type': 'thinking'})}\n\n"
        try:
            item = q.get(timeout=180)
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'payload': 'Timed out'})}\n\n"
            return
        if item["type"] == "error":
            yield f"data: {json.dumps(item)}\n\n"
            return
        answer = item["payload"]["answer"]
        match = re.search(r'\[.*\]', answer, re.DOTALL)
        if not match:
            yield f"data: {json.dumps({'type': 'error', 'payload': 'Model did not return valid JSON array'})}\n\n"
            return
        try:
            questions = json.loads(match.group())
            yield f"data: {json.dumps({'type': 'done', 'questions': questions, 'tokens': item['payload']})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'payload': f'JSON parse error: {e}'})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"Starting Drive Agent on http://localhost:{port}\n")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
