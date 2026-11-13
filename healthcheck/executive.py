"""Executive part.

Runs in a separate process. Pipe protocol:
  <- {"value": str, "handlers": [str, ...]}   task parameters
  -> {"value": str, "results": [dict, ...]}    set of results
  <- None                                      shutdown signal
Right after start it sends the registry of available handlers to the UI.
If the task has "trace": True, the reply also carries "trace": a list of
(timestamp, who, event) showing which thread did what and when.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .handlers import HANDLERS, describe


def record(trace, text: str, who: str = None) -> None:
    """Append an event to the trace (if tracing is on). time.perf_counter() is
    system-wide, so timestamps from the UI and executive processes are comparable."""
    if trace is None:
        return
    if who is None:
        who = threading.current_thread().name
        if who == "MainThread":
            who = "executive"
    trace.append((time.perf_counter(), who, text))


def run_handler(name: str, value: str, trace=None) -> dict:
    t0 = time.perf_counter()
    fn = HANDLERS.get(name)
    if fn is None:
        record(trace, f"{name}: unknown")
        return {"handler": name, "ok": False, "score": None,
                "detail": "unknown handler", "ms": 0.0}
    record(trace, f"{name} start")
    try:
        score, detail = fn(value)
        ok = True
    except Exception as e:  # any failed check means the site did not pass it
        score, detail, ok = 0, f"{type(e).__name__}: {e}", False
    record(trace, f"{name} {'done' if ok else 'FAIL'} ({score})")
    return {"handler": name, "ok": ok, "score": score, "detail": detail,
            "ms": (time.perf_counter() - t0) * 1000}


def executive_loop(conn, parallel: bool = True) -> None:
    conn.send({"handlers": describe()})
    with ThreadPoolExecutor(max_workers=max(1, len(HANDLERS)),
                            thread_name_prefix="worker") as pool:
        while True:
            try:
                msg = conn.recv()
            except EOFError:  # the UI process is gone
                break
            if msg is None:
                break
            value, names = msg["value"], msg["handlers"]
            trace = [] if msg.get("trace") else None
            record(trace, "recv task")
            if parallel:
                results = list(pool.map(lambda n: run_handler(n, value, trace), names))
            else:
                results = [run_handler(n, value, trace) for n in names]
            record(trace, "send results")
            conn.send({"value": value, "results": results, "trace": trace})
    conn.close()
