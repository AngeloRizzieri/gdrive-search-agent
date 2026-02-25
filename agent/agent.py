import os
import anthropic
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from agent.tools import TOOL_SCHEMAS, execute_tool
from agent.prompts import DEFAULT_PROMPT

load_dotenv()

_client = None


def _get_client():
    global _client
    if not _client:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


class MaxTurnsExceeded(Exception):
    pass


def run(question: str, system_prompt: str = DEFAULT_PROMPT, max_turns: int = 12, credentials=None, model: str = "claude-sonnet-4-6", max_tokens: int = 8192) -> dict:
    """
    Run a single question through the agent loop.
    credentials: google.oauth2.credentials.Credentials for the current user (web app),
                 or None to use local file-based auth (CLI).
    Returns: { answer, input_tokens, output_tokens, tool_calls, turns }
    """
    client = _get_client()
    messages = [{"role": "user", "content": question}]

    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read_tokens = 0
    total_cache_creation_tokens = 0
    total_tool_calls = 0
    turns = 0

    # Cache the system prompt so repeated turns (and repeated questions with the
    # same prompt) are billed at ~10% of normal for that portion.
    system_payload = (
        [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
        if system_prompt else None
    )

    while turns < max_turns:
        turns += 1
        kwargs = dict(model=model, max_tokens=max_tokens, tools=TOOL_SCHEMAS, messages=messages)
        if system_payload:
            kwargs["system"] = system_payload
        response = client.messages.create(**kwargs)

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        total_cache_read_tokens += getattr(response.usage, "cache_read_input_tokens", 0) or 0
        total_cache_creation_tokens += getattr(response.usage, "cache_creation_input_tokens", 0) or 0

        if response.stop_reason == "end_turn":
            answer = ""
            for block in response.content:
                if hasattr(block, "text"):
                    answer += block.text
            return {
                "answer": answer,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cache_read_tokens": total_cache_read_tokens,
                "cache_creation_tokens": total_cache_creation_tokens,
                "tool_calls": total_tool_calls,
                "turns": turns,
            }

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            total_tool_calls += len(tool_blocks)

            # Execute all tool calls in parallel (Drive API calls are I/O-bound).
            with ThreadPoolExecutor(max_workers=len(tool_blocks)) as executor:
                raw_results = list(executor.map(
                    lambda b: execute_tool(b.name, b.input, credentials=credentials),
                    tool_blocks,
                ))

            # Cache the last (largest) tool result so it's billed at ~10% on
            # subsequent turns when the message history is re-sent. The Anthropic
            # API supports up to 4 cache breakpoints per request total; we use 1
            # here (system + tools already consume the other 2).
            tool_results = []
            for i, (block, result) in enumerate(zip(tool_blocks, raw_results)):
                is_last = i == len(tool_blocks) - 1
                if is_last and len(result) >= 200:
                    content = [{"type": "text", "text": result,
                                "cache_control": {"type": "ephemeral"}}]
                else:
                    content = result
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                })

            messages.append({"role": "user", "content": tool_results})
            continue

        break

    raise MaxTurnsExceeded(f"Exceeded max_turns={max_turns}")


def chat(system_prompt: str = DEFAULT_PROMPT):
    print("Google Drive Search Agent — type 'quit' to exit\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            print("Goodbye.")
            break

        try:
            result = run(user_input, system_prompt=system_prompt)
            print(f"\nAgent: {result['answer']}")
            cache_read = result.get("cache_read_tokens", 0)
            cache_note = f" | cache_read={cache_read}" if cache_read else ""
            print(f"[tokens: {result['input_tokens']} in / {result['output_tokens']} out"
                  f"{cache_note} | tool calls: {result['tool_calls']} | turns: {result['turns']}]\n")
        except MaxTurnsExceeded as e:
            print(f"\n[Error: {e}]\n")
        except Exception as e:
            print(f"\n[Error: {e}]\n")
