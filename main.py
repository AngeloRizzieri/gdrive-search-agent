# main.py — CLI entrypoint
# Usage:
#   python main.py              → interactive chat mode
#   python main.py --eval       → run eval against both prompts
#   python main.py --eval --prompt a  → eval prompt A only

import argparse

def main():
    parser = argparse.ArgumentParser(description="Google Drive Search Agent")
    parser.add_argument("--eval", action="store_true", help="Run eval mode")
    parser.add_argument("--prompt", choices=["a", "b"], default=None, help="Prompt variant to eval")
    args = parser.parse_args()

    if args.eval:
        from eval.runner import run_eval
        run_eval(prompt_variant=args.prompt)
    else:
        from agent.agent import chat
        chat()

if __name__ == "__main__":
    main()
