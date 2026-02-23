# agent/agent.py
# Core agentic tool-use loop.
#
# Flow:
#   1. Receive user message
#   2. Send to Claude with tools + system prompt
#   3. If stop_reason == "tool_use": execute tool, append result, go to 2
#   4. If stop_reason == "end_turn": return final text response
#
# Guards:
#   - max_turns (default 10) prevents infinite loops
#   - tracks total input/output tokens across all turns for eval
#
# TODO: implement chat() and run(question, system_prompt, max_turns) functions
