"""Executive part.

Runs in a separate process. Pipe protocol:
  <- {"value": str, "handlers": [str, ...]}   task parameters
  -> {"value": str, "results": [dict, ...]}    set of results
  <- None                                      shutdown signal
Right after start it sends the registry of available handlers to the UI.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from .handlers import HANDLERS, describe


def run_handler(name: str, value: str) -> dict:
    t0 = time.perf_counter()
    fn = HANDLERS.get(name)
    if fn is None:
        return {"handler": name, "ok": False, "score": None,
                "detail": "unknown handler", "ms": 0.0}
    try:
        score, detail = fn(value)
        ok = True
    except Exception as e:  # any failed check means the site did not pass it
        score, detail, ok = 0, f"{type(e).__name__}: {e}", False
    return {"handler": name, "ok": ok, "score": score, "detail": detail,
            "ms": (time.perf_counter() - t0) * 1000}


def executive_loop(conn, parallel: bool = True) -> None:
    conn.send({"handlers": describe()})
    with ThreadPoolExecutor(max_workers=max(1, len(HANDLERS))) as pool:
        while True:
            try:
                msg = conn.recv()
            except EOFError:  # the UI process is gone
                break
            if msg is None:
                break
            value, names = msg["value"], msg["handlers"]
            if parallel:
                results = list(pool.map(lambda n: run_handler(n, value), names))
            else:
                results = [run_handler(n, value) for n in names]
            conn.send({"value": value, "results": results})
    conn.close()
