import argparse

from .ui import CONSOLIDATORS, run


def main():
    p = argparse.ArgumentParser(
        prog="python -m healthcheck",
        description="Check site health: a series of tasks, parallel handlers, summary statistics.",
    )
    p.add_argument("tasks", nargs="*",
                   help='tasks in quotes: "address [handlers...]", e.g. "github.com dns http"')
    p.add_argument("-c", "--consolidate", choices=CONSOLIDATORS, default="avg",
                   help="function used to consolidate handler results (default: avg)")
    p.add_argument("--sequential", action="store_true",
                   help="run handlers one by one (to compare speed with parallel mode)")
    args = p.parse_args()
    run(args.tasks, how=args.consolidate, parallel=not args.sequential)


if __name__ == "__main__":
    main()
