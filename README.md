# Site Health Checker

A command-line tool that checks the health of websites: whether the domain resolves, the port is open, the server responds, and the SSL certificate is valid. The checks for one site run in parallel, and their results are combined into a single score from 0 to 100.

Built as an independent assignment for an Operating Systems course. The main point is the architecture: two processes that communicate only by passing messages through a pipe.

![Architecture](docs/architecture.png)

## Architecture

| Part | File | Responsibility |
|---|---|---|
| Interface (UI) | `healthcheck/ui.py` | accepts a series of tasks, sends parameters, consolidates results, keeps statistics |
| Executive | `healthcheck/executive.py` | separate process; runs handlers in parallel (thread pool) and returns a set of results |
| Handler registry | `healthcheck/handlers.py` | `dns`, `tcp`, `http`, `ssl`; each returns a 0–100 score and a description |

**Message protocol** (`multiprocessing.Pipe`):

```
Executive → UI   {"handlers": {name: description}}        once, on start
UI → Executive   {"value": address, "handlers": [...]}    task parameters
Executive → UI   {"value": address, "results": [...]}     set of results
UI → Executive   None                                     shutdown
```

**A task** is a value (a site address) plus a list of handlers. If no handlers are given, all of them run.
**Consolidation**: average by default (`avg`), or `min` to score a site by its weakest check.
**Verdict**: ≥80 is `OK`, 50–79 is `WARN`, <50 is `FAIL`.

## Usage

Requires Python 3.9+ and nothing else: only the standard library is used.

```bash
# tasks from arguments
python -m healthcheck "github.com" "wikipedia.org dns http" "http://localhost:8000"

# interactive: the system prompts for tasks, an empty line quits
python -m healthcheck

# consolidate by minimum / run handlers sequentially to compare timing
python -m healthcheck -c min "github.com"
python -m healthcheck --sequential "github.com" "wikipedia.org"
```

Example output:

```
[1] http://localhost:8765
    dns   100  1 address(es), e.g. 127.0.0.1
    tcp   100  port 8765 open, 2 ms
    http  100  HTTP 200, 8 ms
    ssl     0  site does not use HTTPS
    => health: 75/100 (WARN), 10 ms

=== Summary ===
Sites checked:   2
Invalid inputs:  1
Verdicts:        OK: 1, WARN: 1
Average health:  88/100
handler     calls  failed   avg time
dns             2       0       1 ms
http            2       0       4 ms
...
```

## Tests

The tests need no internet connection: they start a local HTTP server.

```bash
python -m unittest -v
```

## Adding a handler

Write a function in `handlers.py` that takes an address and returns `(score, detail)`, then add it to the `HANDLERS` dict. The first line of its docstring becomes its description in the menu.
