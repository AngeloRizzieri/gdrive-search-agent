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


# All useful metadata fields from Drive API v3
_FILE_FIELDS = (
    "id, name, mimeType, description, starred, shared, trashed, "
    "createdTime, modifiedTime, viewedByMeTime, "
    "size, quotaBytesUsed, version, md5Checksum, "
    "fileExtension, originalFilename, "
    "owners(displayName, emailAddress), "
    "lastModifyingUser(displayName, emailAddress), "
    "sharingUser(displayName, emailAddress), "
    "webViewLink, webContentLink, parents"
)


def search_drive(query: str, max_results: int = 10, credentials=None) -> list[dict]:
    service = get_drive_service(credentials)
    result = service.files().list(
        q=f"fullText contains '{query}' and trashed=false",
        pageSize=max_results,
        fields=f"files({_FILE_FIELDS})",
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
        fields=f"files({_FILE_FIELDS})",
    ).execute()
    return result.get("files", [])


# ── File type handling ────────────────────────────────────────────────────────

# Google Workspace native types → export as text
_EXPORT_MAP = {
    "application/vnd.google-apps.document":     "text/plain",
    "application/vnd.google-apps.spreadsheet":  "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.drawing":      "image/svg+xml",
    "application/vnd.google-apps.script":       "application/vnd.google-apps.script+json",
    "application/vnd.google-apps.form":         "application/zip",  # responses export
}

# Text-decodable uploaded types — download raw bytes
_TEXT_TYPES = {
    "text/plain", "text/csv", "text/markdown", "text/html",
    "text/xml", "text/javascript", "text/x-python",
    "application/json", "application/xml",
    "application/javascript", "application/rtf", "text/rtf",
    "image/svg+xml",
}

# Binary types needing a parser
_BINARY_PARSEABLE = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",        # .xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation", # .pptx
    "application/vnd.ms-powerpoint",                                             # .ppt (fallback)
}

# Truly binary — metadata only
_BINARY_OPAQUE = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff",
    "audio/mpeg", "audio/wav", "audio/ogg", "audio/mp4",
    "video/mp4", "video/mpeg", "video/quicktime", "video/x-msvideo",
    "application/zip", "application/x-tar", "application/x-gzip",
    "application/octet-stream",
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

    if mime in ("application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "application/vnd.ms-powerpoint"):
        try:
            from pptx import Presentation
            prs = Presentation(io.BytesIO(data))
            slides = []
            for i, slide in enumerate(prs.slides, 1):
                texts = [shape.text for shape in slide.shapes if hasattr(shape, "text") and shape.text.strip()]
                slides.append(f"[Slide {i}] " + " | ".join(texts))
            return "\n".join(slides)
        except ImportError:
            return "[PPTX parsing unavailable — install python-pptx]"

    return data.decode("utf-8", errors="replace")


def read_document(file_id: str, credentials=None) -> str:
    service = get_drive_service(credentials)
    meta = service.files().get(fileId=file_id, fields=_FILE_FIELDS).execute()
    mime = meta.get("mimeType", "")

    owner = meta.get("owners", [{}])[0].get("displayName", "unknown")
    owner_email = meta.get("owners", [{}])[0].get("emailAddress", "")
    header = (
        f"File: {meta.get('name')}\n"
        f"Type: {mime}\n"
        f"Created: {meta.get('createdTime', 'unknown')}\n"
        f"Modified: {meta.get('modifiedTime', 'unknown')}\n"
        f"Owner: {owner} <{owner_email}>\n"
        f"Size: {meta.get('size', 'N/A')} bytes\n"
        f"Version: {meta.get('version', 'N/A')}\n"
        f"MD5: {meta.get('md5Checksum', 'N/A')}\n"
        f"Link: {meta.get('webViewLink', 'N/A')}\n"
        f"---\n"
    )

    if mime in _BINARY_OPAQUE:
        return header + f"[Binary file — content not extractable. Download: {meta.get('webContentLink', 'N/A')}]"

    try:
        if mime in _EXPORT_MAP:
            response = service.files().export(
                fileId=file_id, mimeType=_EXPORT_MAP[mime]
            ).execute()
            text = response.decode("utf-8") if isinstance(response, bytes) else str(response)
        elif mime in _TEXT_TYPES:
            data = _download_bytes(service, file_id)
            text = data.decode("utf-8", errors="replace")
        elif mime in _BINARY_PARSEABLE:
            data = _download_bytes(service, file_id)
            text = _parse_bytes(data, mime)
        else:
            # Unknown type — attempt raw text decode as last resort
            try:
                data = _download_bytes(service, file_id)
                text = data.decode("utf-8", errors="replace")
            except Exception:
                return header + f"[Unsupported file type: {mime}]"
    except Exception as e:
        return header + f"[Error reading content: {e}]"

    return header + text[:8000]


# ── Formatting ────────────────────────────────────────────────────────────────

def _fmt_file(f: dict) -> str:
    owner = f.get("owners", [{}])[0]
    owner_str = f"{owner.get('displayName', 'unknown')} <{owner.get('emailAddress', '')}>"
    modifier = f.get("lastModifyingUser", {})
    modifier_str = f"{modifier.get('displayName', 'unknown')} <{modifier.get('emailAddress', '')}>"
    size_bytes = f.get("size") or f.get("quotaBytesUsed")
    size = f"{int(size_bytes):,} bytes" if size_bytes else "N/A"
    shared_by = f.get("sharingUser", {}).get("displayName", "")
    return (
        f"- {f['name']}\n"
        f"  id: {f['id']}\n"
        f"  type: {f.get('mimeType', 'unknown')}\n"
        f"  extension: {f.get('fileExtension') or f.get('originalFilename', 'N/A')}\n"
        f"  created: {f.get('createdTime', 'unknown')}\n"
        f"  modified: {f.get('modifiedTime', 'unknown')} by {modifier_str}\n"
        f"  last viewed by me: {f.get('viewedByMeTime', 'never')}\n"
        f"  owner: {owner_str}\n"
        + (f"  shared by: {shared_by}\n" if shared_by else "")
        + f"  size: {size}\n"
        f"  version: {f.get('version', 'N/A')}\n"
        f"  md5: {f.get('md5Checksum', 'N/A')}\n"
        f"  starred: {f.get('starred', False)} | shared: {f.get('shared', False)}\n"
        f"  link: {f.get('webViewLink', 'N/A')}"
    )


def execute_tool(name: str, inputs: dict, credentials=None) -> str:
    if name == "search_drive":
        results = search_drive(credentials=credentials, **inputs)
        if not results:
            return "No files found."
        return "\n\n".join(_fmt_file(f) for f in results)
    elif name == "list_files":
        results = list_files(credentials=credentials, **inputs)
        if not results:
            return "No files found."
        return "\n\n".join(_fmt_file(f) for f in results)
    elif name == "read_document":
        return read_document(credentials=credentials, **inputs)
    else:
        return f"Unknown tool: {name}"


TOOL_SCHEMAS = [
    {
        "name": "search_drive",
        "description": (
            "Search Google Drive for files matching a query. Returns rich metadata: "
            "id, name, type, created/modified timestamps, owner, size, version, md5, sharing info, link."
        ),
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
        "description": (
            "List files in Google Drive with rich metadata. Optionally filter to a specific folder. "
            "Returns timestamps, owner, size, version, md5, sharing info, and links."
        ),
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
        "description": (
            "Read the content of a Google Drive file by ID. "
            "Supports: Google Docs/Sheets/Slides/Drawings/Scripts, PDF, DOCX, XLSX, PPTX, "
            "plain text, HTML, JSON, CSV, Markdown, XML, SVG, JavaScript, Python, RTF. "
            "Binary files (images, video, audio, zip) return metadata + download link. "
            "Always prepends file metadata (created, modified, owner, size, md5). "
            "Returns up to 8000 characters of content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "The Google Drive file ID to read."},
            },
            "required": ["file_id"],
        },
    },
]
