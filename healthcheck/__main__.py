import argparse

from .handlers import describe
from .ui import CONSOLIDATORS, run

EPILOG = """\
task format:
  "ADDRESS [HANDLER ...]"   address of a site plus the checks to run;
                            no handlers (or "all") runs every check
  ADDRESS                   example.com | example.com:8443 | http://localhost:8000/path
                            (https:// is assumed when no scheme is given)

handlers:
{handlers}

consolidation (-c):
  avg      average of the handler scores (default)
  min      the worst score: a site is only as healthy as its weakest check
  median   middle score: one bad check does not dominate the result

verdicts:  OK >= 80,  WARN 50-79,  FAIL < 50

examples:
  python -m healthcheck "github.com" "wikipedia.org dns http"
  python -m healthcheck -c min "http://neverssl.com"
  python -m healthcheck -s -t "github.com"     # sequential run, with a timeline
  python -m healthcheck                        # interactive: the system asks for tasks
"""


def main():
    handlers = "\n".join(f"  {name:<8} {desc}" for name, desc in describe().items())
    p = argparse.ArgumentParser(
        prog="python -m healthcheck",
        description="Check site health: a series of tasks, parallel handlers, summary statistics.",
        epilog=EPILOG.format(handlers=handlers),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("tasks", nargs="*", metavar="TASK",
                   help='a task in quotes, e.g. "github.com dns http"; '
                        "if none are given, the system prompts for them")
    p.add_argument("-c", "--consolidate", choices=CONSOLIDATORS, default="avg", metavar="FUNC",
                   help="how to combine handler scores: %(choices)s (default: %(default)s)")
    p.add_argument("-s", "--sequential", action="store_true",
                   help="run handlers one by one instead of in parallel")
    p.add_argument("-t", "--trace", action="store_true",
                   help="show a timeline of which process/thread did what for each task")
    args = p.parse_args()
    run(args.tasks, how=args.consolidate, parallel=not args.sequential, trace=args.trace)


if __name__ == "__main__":
    main()
