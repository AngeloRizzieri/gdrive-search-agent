# Google Drive Tools

## Tool signatures
- `search_drive(query: str, max_results: int = 10)` → `[{id, name, mimeType}]`
- `list_files(folder_id: str = None)` → `[{id, name, mimeType}]`
- `read_document(file_id: str)` → `str` (plain text, max ~8000 chars)

## Critical token-saving rule
`search_drive` and `list_files` return **metadata only** (id, name, mimeType).
`read_document` is the only tool that returns content.
The agent must use search/list to narrow candidates before calling read_document.

## Supported file types in read_document

### Google Workspace native files → Drive export API
| mimeType | Exported as |
|---|---|
| `application/vnd.google-apps.document` | `text/plain` |
| `application/vnd.google-apps.spreadsheet` | `text/csv` |
| `application/vnd.google-apps.presentation` | `text/plain` |

### Uploaded binary files → downloaded raw, parsed locally
| mimeType | Parser | Dep |
|---|---|---|
| `application/pdf` | `pypdf` | `pypdf` |
| `.docx` (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`) | `python-docx` | `python-docx` |
| `.xlsx` (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`) | `openpyxl` | `openpyxl` |
| `text/plain`, `text/csv`, `text/markdown` | UTF-8 decode | — |

**All others** → return `"Unsupported file type: {mimeType}"`

### Why PDFs can't use export()
`files().export()` is only available for **Google Workspace native files**.
Uploaded PDFs/DOCX/XLSX must be downloaded with `files().get_media()` and parsed locally.
This was the original bug — `application/pdf` was in `_EXPORT_MAP`, causing silent failures.

## Tool schemas
`TOOL_SCHEMAS` list in tools.py must match these signatures exactly for Anthropic API `tools=` param.
`execute_tool(name, inputs)` is the dispatcher used by the agent loop.

## Auth
Drive service is initialized once via `get_drive_service()` using credentials.json + token.json.
Scope: `https://www.googleapis.com/auth/drive.readonly`
token.json is auto-created on first run via browser OAuth flow.
