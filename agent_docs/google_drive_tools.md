# Google Drive Tools

## Tool signatures
- `search_drive(query: str, max_results: int = 10)` → `[{id, name, mimeType}]`
- `list_files(folder_id: str = None)` → `[{id, name, mimeType}]`
- `read_document(file_id: str)` → `str` (plain text, max ~8000 chars)

## Critical token-saving rule
`search_drive` and `list_files` return **metadata only** (id, name, mimeType).
`read_document` is the only tool that returns content.
The agent must use search/list to narrow candidates before calling read_document.

## Supported mime types in read_document
- `application/vnd.google-apps.document` → export as `text/plain`
- `application/vnd.google-apps.spreadsheet` → export as `text/csv`
- `application/pdf` → export as `text/plain` via Drive export API
- `text/plain` → download directly
- All others → return `"Unsupported file type: {mimeType}"`

## Tool schemas
`TOOL_SCHEMAS` list in tools.py must match these signatures exactly for Anthropic API `tools=` param.
`execute_tool(name, inputs)` is the dispatcher used by the agent loop.

## Auth
Drive service is initialized once via `get_drive_service()` using credentials.json + token.json.
Scope: `https://www.googleapis.com/auth/drive.readonly`
token.json is auto-created on first run via browser OAuth flow.
