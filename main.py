# main.py — CLI entrypoint
# Usage:
#   python main.py              → interactive chat mode
#   python main.py --eval       → run eval with default prompt
#   python main.py --eval --prompt-file p1.txt p2.txt  → compare 1-2 prompt files

import argparse

def main():
    parser = argparse.ArgumentParser(description="Google Drive Search Agent")
    parser.add_argument("--eval", action="store_true", help="Run eval mode")
    parser.add_argument("--prompt-file", nargs="+", metavar="FILE",
                        help="Path(s) to text file(s) containing system prompt(s). Up to 2 for comparison.")
    args = parser.parse_args()

    if args.eval:
        from eval.runner import run_eval
        prompts = None
        if args.prompt_file:
            prompts = []
            for path in args.prompt_file[:2]:
                with open(path) as f:
                    prompts.append(f.read().strip())
        run_eval(prompts=prompts)
    else:
        from agent.agent import chat
        chat()

if __name__ == "__main__":
    main()
