import io
import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_drive_service = None  # cached only for CLI / local fallback


def _write_from_env_b64(env_var: str, path: str):
    import base64
    val = os.getenv(env_var)
    if val and not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(base64.b64decode(val))


def get_drive_service(credentials=None):
    """
    If credentials (google.oauth2.credentials.Credentials) are provided,
    build a Drive service for that user — used by the web app (multi-user).
    Otherwise fall back to local file-based auth — used by `python main.py`.
    """
    if credentials is not None:
        return build("drive", "v3", credentials=credentials)

    # Local CLI fallback
    global _drive_service
    if _drive_service:
        return _drive_service

    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "./credentials.json")
    token_path = os.getenv("GOOGLE_TOKEN_PATH", "./token.json")

    _write_from_env_b64("GOOGLE_CREDENTIALS_B64", creds_path)
    _write_from_env_b64("GOOGLE_TOKEN_B64", token_path)

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    _drive_service = build("drive", "v3", credentials=creds)
    return _drive_service


def search_drive(query: str, max_results: int = 10, credentials=None) -> list[dict]:
    service = get_drive_service(credentials)
    result = service.files().list(
        q=f"fullText contains '{query}' and trashed=false",
        pageSize=max_results,
        fields="files(id, name, mimeType)",
    ).execute()
    return result.get("files", [])


def list_files(folder_id: str = None, credentials=None) -> list[dict]:
    service = get_drive_service(credentials)
    q = "trashed=false"
    if folder_id:
        q += f" and '{folder_id}' in parents"
    result = service.files().list(
        q=q,
        pageSize=50,
        fields="files(id, name, mimeType)",
    ).execute()
    return result.get("files", [])


# Google Workspace native types — use export API
_EXPORT_MAP = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

# Uploaded binary types — download raw bytes and parse locally
_BINARY_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",        # .xlsx
    "text/plain",
    "text/csv",
    "text/markdown",
}


def _download_bytes(service, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def _parse_bytes(data: bytes, mime: str) -> str:
    if mime == "application/pdf":
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        import docx
        doc = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs)

    if mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        rows = []
        for sheet in wb.worksheets:
            rows.append(f"=== {sheet.title} ===")
            for row in sheet.iter_rows(values_only=True):
                rows.append(",".join("" if v is None else str(v) for v in row))
        return "\n".join(rows)

    return data.decode("utf-8", errors="replace")


def read_document(file_id: str, credentials=None) -> str:
    service = get_drive_service(credentials)
    meta = service.files().get(fileId=file_id, fields="mimeType, name").execute()
    mime = meta.get("mimeType", "")

    try:
        if mime in _EXPORT_MAP:
            response = service.files().export(
                fileId=file_id, mimeType=_EXPORT_MAP[mime]
            ).execute()
            text = response.decode("utf-8") if isinstance(response, bytes) else response
        elif mime in _BINARY_TYPES:
            data = _download_bytes(service, file_id)
            text = _parse_bytes(data, mime)
        else:
            return f"Unsupported file type: {mime}"
    except Exception as e:
        return f"Error reading file: {e}"

    return text[:8000]


def execute_tool(name: str, inputs: dict, credentials=None) -> str:
    if name == "search_drive":
        results = search_drive(credentials=credentials, **inputs)
        if not results:
            return "No files found."
        return "\n".join(f"- {f['name']} (id={f['id']}, type={f['mimeType']})" for f in results)
    elif name == "list_files":
        results = list_files(credentials=credentials, **inputs)
        if not results:
            return "No files found."
        return "\n".join(f"- {f['name']} (id={f['id']}, type={f['mimeType']})" for f in results)
    elif name == "read_document":
        return read_document(credentials=credentials, **inputs)
    else:
        return f"Unknown tool: {name}"


TOOL_SCHEMAS = [
    {
        "name": "search_drive",
        "description": "Search Google Drive for files matching a query. Returns metadata only (id, name, mimeType) — not file content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Full-text search query string."},
                "max_results": {"type": "integer", "description": "Maximum results to return. Default 10.", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in Google Drive, optionally filtered to a specific folder. Returns metadata only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_id": {"type": "string", "description": "Folder ID to list from. Omit for all files."},
            },
            "required": [],
        },
    },
    {
        "name": "read_document",
        "description": "Read the text content of a Google Drive file by its ID. Supports Docs, Sheets (CSV), PDFs, DOCX, XLSX, plain text. Returns up to 8000 characters.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "The Google Drive file ID to read."},
            },
            "required": ["file_id"],
        },
    },
]
