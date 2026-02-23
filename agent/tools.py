# agent/tools.py
# Google Drive tool implementations + Anthropic tool schema definitions.
#
# Tools exposed to the agent:
#   - search_drive(query, max_results=10)   → list of {id, name, mimeType}
#   - list_files(folder_id=None)            → list of {id, name, mimeType}
#   - read_document(file_id)                → plain text, truncated to ~8000 chars
#
# IMPORTANT: search/list return metadata only (not content) to save tokens.
# read_document is the only tool that returns content.
# Handles: Google Docs, plain text, PDFs — graceful error for unsupported types.
#
# TODO: implement drive auth, tool functions, and TOOL_SCHEMAS list
