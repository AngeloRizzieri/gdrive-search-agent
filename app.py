"""
app.py — Flask web server for the Google Drive Search Agent.
Run: python app.py
Then open: http://localhost:5000
"""

import json
import queue
import threading
from flask import Flask, Response, request, send_from_directory

from agent.agent import run, MaxTurnsExceeded
from agent.prompts import PROMPT_A, PROMPT_B

app = Flask(__name__, static_folder="frontend", static_url_path="")

PROMPTS = {"a": PROMPT_A, "b": PROMPT_B}


@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    question = (data.get("question") or "").strip()
    prompt_key = data.get("prompt", "b").lower()

    if not question:
        return {"error": "No question provided."}, 400

    system_prompt = PROMPTS.get(prompt_key, PROMPT_B)

    # Stream progress to the client via Server-Sent Events
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            result = run(question, system_prompt=system_prompt)
            q.put({"type": "done", "payload": result})
        except MaxTurnsExceeded as e:
            q.put({"type": "error", "payload": str(e)})
        except Exception as e:
            q.put({"type": "error", "payload": str(e)})

    threading.Thread(target=worker, daemon=True).start()

    def generate():
        yield f"data: {json.dumps({'type': 'thinking'})}\n\n"
        item = q.get()
        yield f"data: {json.dumps(item)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/search", methods=["GET"])
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return {"error": "No query provided."}, 400
    from agent.tools import search_drive
    try:
        results = search_drive(query)
        return {"files": results}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/files", methods=["GET"])
def files():
    folder_id = request.args.get("folder_id") or None
    from agent.tools import list_files
    try:
        results = list_files(folder_id=folder_id)
        return {"files": results}
    except Exception as e:
        return {"error": str(e)}, 500


if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 5000))
    print(f"Starting Google Drive Search Agent on port {port}...")
    print(f"Open http://localhost:{port} in your browser\n")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
