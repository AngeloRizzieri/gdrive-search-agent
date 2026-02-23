import os
import anthropic
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


def run(question: str, system_prompt: str = DEFAULT_PROMPT, max_turns: int = 10, credentials=None, model: str = "claude-sonnet-4-6") -> dict:
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
    total_tool_calls = 0
    turns = 0

    while turns < max_turns:
        turns += 1
        kwargs = dict(model=model, max_tokens=4096, tools=TOOL_SCHEMAS, messages=messages)
        if system_prompt:
            kwargs["system"] = system_prompt
        response = client.messages.create(**kwargs)

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        if response.stop_reason == "end_turn":
            answer = ""
            for block in response.content:
                if hasattr(block, "text"):
                    answer += block.text
            return {
                "answer": answer,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "tool_calls": total_tool_calls,
                "turns": turns,
            }

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    total_tool_calls += 1
                    result = execute_tool(block.name, block.input, credentials=credentials)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
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
            print(f"[tokens: {result['input_tokens']} in / {result['output_tokens']} out | "
                  f"tool calls: {result['tool_calls']} | turns: {result['turns']}]\n")
        except MaxTurnsExceeded as e:
            print(f"\n[Error: {e}]\n")
        except Exception as e:
            print(f"\n[Error: {e}]\n")
