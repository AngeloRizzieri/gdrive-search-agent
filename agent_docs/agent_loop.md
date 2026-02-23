# Agent Loop

## Contract
`agent.run(question, system_prompt, max_turns=10)` runs a single question and returns:
```python
{ "answer": str, "input_tokens": int, "output_tokens": int, "tool_calls": int, "turns": int }
```

`agent.chat()` is the interactive REPL — wraps run() with a print loop.

## Loop logic
1. Send messages array to Claude with tools + system prompt
2. If `stop_reason == "tool_use"`: call `execute_tool()`, append `tool_result` block, go to 1
3. If `stop_reason == "end_turn"`: return final text + accumulated token counts
4. If `turns >= max_turns`: raise `MaxTurnsExceeded`

## Token tracking
Accumulate `response.usage.input_tokens` and `response.usage.output_tokens` across ALL turns,
not just the final one. Eval depends on the full chain total.

## Message format
Tool results must be appended as a `user` role message with `tool_result` content blocks.
The next call must include the full message history.
