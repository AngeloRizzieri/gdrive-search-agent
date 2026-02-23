# eval/runner.py
# Runs fixed question set against both prompt variants and compares token efficiency.
#
# For each question x each prompt:
#   1. agent.run(question, system_prompt=PROMPT_X)
#   2. Check expected_answer in response (case-insensitive)
#   3. Record: correct, input_tokens, output_tokens, tool_calls, turns
#
# Output: comparison table printed to stdout + saved to eval/results/run_{timestamp}.json
#
# TODO: implement run_eval(prompt_variant=None)
