"""Interface part (UI).

Accepts a series of tasks (from arguments or by prompting), sends parameters
to the executive part, consolidates its results into a site health score,
and prints summary statistics before exit.
"""
import multiprocessing as mp
import statistics
import time

from .executive import executive_loop, record
from .handlers import parse_target

# Consolidation functions: handler scores -> a single task score
CONSOLIDATORS = {
    "avg": lambda scores: round(sum(scores) / len(scores)),  # average
    "min": min,                                              # weakest link
    "median": lambda scores: round(statistics.median(scores)),  # robust to one outlier
}


def consolidate(scores, how: str = "avg"):
    return CONSOLIDATORS[how](scores) if scores else None


def verdict(score) -> str:
    if score is None:
        return "N/A"
    if score >= 80:
        return "OK"
    if score >= 50:
        return "WARN"
    return "FAIL"


def parse_task(line: str, available) -> tuple:
    """'site.com dns http' -> ('site.com', ['dns', 'http']). No handlers means all."""
    tokens = line.split()
    value, handlers = tokens[0], tokens[1:]
    parse_target(value)  # validate the address before sending it
    if not handlers or handlers == ["all"]:
        handlers = list(available)
    return value, handlers


class Stats:
    def __init__(self):
        self.started = time.perf_counter()
        self.tasks = 0
        self.bad_input = 0
        self.verdicts = {"OK": 0, "WARN": 0, "FAIL": 0, "N/A": 0}
        self.scores = []
        self.per_handler = {}  # name -> [calls, failures, total ms]

    def add(self, results, score):
        self.tasks += 1
        self.verdicts[verdict(score)] += 1
        if score is not None:
            self.scores.append(score)
        for r in results:
            h = self.per_handler.setdefault(r["handler"], [0, 0, 0.0])
            h[0] += 1
            h[1] += 0 if r["ok"] else 1
            h[2] += r["ms"]

    def report(self) -> str:
        lines = ["", "=== Summary ===",
                 f"Sites checked:   {self.tasks}",
                 f"Invalid inputs:  {self.bad_input}",
                 "Verdicts:        " + ", ".join(f"{k}: {v}" for k, v in self.verdicts.items() if v)]
        if self.scores:
            lines.append(f"Average health:  {sum(self.scores) / len(self.scores):.0f}/100")
        if self.per_handler:
            lines.append(f"{'handler':<10}{'calls':>7}{'failed':>8}{'avg time':>11}")
            for name, (calls, fails, ms) in sorted(self.per_handler.items()):
                lines.append(f"{name:<10}{calls:>7}{fails:>8}{ms / calls:>8.0f} ms")
        lines.append(f"Total run time:  {time.perf_counter() - self.started:.2f} s")
        return "\n".join(lines)


def print_result(n, value, results, score, elapsed_ms):
    print(f"[{n}] {value}")
    for r in results:
        sc = "  -" if r["score"] is None else f"{r['score']:>3}"
        mark = "" if r["ok"] else "  ✗"
        print(f"    {r['handler']:<8} {sc}  {r['detail']}{mark}")
    print(f"    => health: {score if score is not None else '-'}/100 "
          f"({verdict(score)}), {elapsed_ms:.0f} ms\n")


def print_trace(events):
    """Print events as a timeline: one column per process/thread, like OSTEP's x86.py -c."""
    workers = sorted({who for _, who, _ in events} - {"ui", "executive"})
    columns = ["ui", "executive"] + workers
    width = {c: max([len(c)] + [len(text) for _, who, text in events if who == c]) + 2
             for c in columns}  # each column is as wide as its longest entry
    t0 = events[0][0]
    header = f"{'ms':>8}  " + "".join(f"{c:<{width[c]}}" for c in columns)
    print("    " + header.rstrip())
    print("    " + "-" * len(header.rstrip()))
    for ts, who, text in events:
        cells = "".join(f"{(text if c == who else ''):<{width[c]}}" for c in columns)
        print(f"    {(ts - t0) * 1000:>8.1f}  {cells.rstrip()}")
    print()


def task_source(tasks):
    """Tasks from arguments, or, if there are none, prompted from the user."""
    if tasks:
        yield from tasks
        return
    while True:
        try:
            line = input("Task (address [handlers...]), Enter to quit: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            return
        yield line


def run(tasks=None, how: str = "avg", parallel: bool = True, trace: bool = False) -> Stats:
    ctx = mp.get_context("spawn")  # same behaviour on Linux, macOS and Windows
    ui_conn, ex_conn = ctx.Pipe()
    executive = ctx.Process(target=executive_loop, args=(ex_conn, parallel), daemon=True)
    executive.start()

    available = ui_conn.recv()["handlers"]
    print("Available handlers:")
    for name, desc in available.items():
        print(f"  {name:<8} - {desc}")
    print(f"Consolidation: {how}; mode: {'parallel' if parallel else 'sequential'}"
          f"{'; trace: on' if trace else ''}\n")

    stats = Stats()
    try:
        for line in task_source(tasks):
            try:
                value, handlers = parse_task(line, available)
            except (ValueError, IndexError) as e:
                print(f"    Invalid input: {e}\n")
                stats.bad_input += 1
                continue

            events = [] if trace else None
            t0 = time.perf_counter()
            record(events, "send task", who="ui")
            ui_conn.send({"value": value, "handlers": handlers, "trace": trace})  # parameters ->
            reply = ui_conn.recv()                                                 # <- results
            record(events, "recv results", who="ui")
            elapsed = (time.perf_counter() - t0) * 1000

            scores = [r["score"] for r in reply["results"] if r["score"] is not None]
            score = consolidate(scores, how)
            stats.add(reply["results"], score)
            print_result(stats.tasks, value, reply["results"], score, elapsed)
            if trace:
                timeline = [events[0]] + reply["trace"] + events[1:]
                print_trace(sorted(timeline, key=lambda e: e[0]))
    finally:
        ui_conn.send(None)
        executive.join(timeout=10)
        print(stats.report())
    return stats
