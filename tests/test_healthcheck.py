"""Offline tests: a local HTTP server is started for them.
Run: python -m unittest -v
"""
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
import multiprocessing as mp

from healthcheck.executive import executive_loop, run_handler
from healthcheck.handlers import parse_target, speed_score
from healthcheck.ui import consolidate, parse_task, verdict


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = 500 if self.path == "/broken" else 200
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b"hello")

    def log_message(self, *args):
        pass


class LocalServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.addr = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()


class TestParsing(unittest.TestCase):
    def test_default_https(self):
        t = parse_target("example.com")
        self.assertEqual((t.scheme, t.host, t.port), ("https", "example.com", 443))

    def test_explicit_port_and_scheme(self):
        t = parse_target("http://localhost:8000/status")
        self.assertEqual((t.scheme, t.port, t.url), ("http", 8000, "http://localhost:8000/status"))

    def test_bad_address(self):
        with self.assertRaises(ValueError):
            parse_target("ftp://x")

    def test_task_without_handlers_means_all(self):
        self.assertEqual(parse_task("a.com", {"dns": "", "http": ""}), ("a.com", ["dns", "http"]))


class TestScoring(unittest.TestCase):
    def test_speed_score_bounds(self):
        self.assertEqual(speed_score(10, 50, 1000), 100)
        self.assertEqual(speed_score(5000, 50, 1000), 20)
        self.assertTrue(20 < speed_score(500, 50, 1000) < 100)

    def test_consolidate(self):
        self.assertEqual(consolidate([100, 50, 0], "avg"), 50)
        self.assertEqual(consolidate([100, 50, 0], "min"), 0)
        self.assertIsNone(consolidate([], "avg"))

    def test_verdict(self):
        self.assertEqual([verdict(90), verdict(60), verdict(10)], ["OK", "WARN", "FAIL"])


class TestHandlers(LocalServer):
    def test_http_ok(self):
        r = run_handler("http", self.addr)
        self.assertTrue(r["ok"])
        self.assertIn("HTTP 200", r["detail"])

    def test_http_500(self):
        r = run_handler("http", self.addr + "/broken")
        self.assertEqual(r["score"], 10)

    def test_ssl_on_plain_http(self):
        self.assertEqual(run_handler("ssl", self.addr)["score"], 0)

    def test_closed_port_is_error_not_crash(self):
        r = run_handler("tcp", "http://127.0.0.1:1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["score"], 0)

    def test_unknown_handler(self):
        r = run_handler("magic", self.addr)
        self.assertIsNone(r["score"])


class TestProtocol(LocalServer):
    def test_round_trip_through_pipe(self):
        ctx = mp.get_context("spawn")
        ui, ex = ctx.Pipe()
        p = ctx.Process(target=executive_loop, args=(ex,))
        p.start()
        self.assertIn("dns", ui.recv()["handlers"])
        ui.send({"value": self.addr, "handlers": ["dns", "tcp", "http"]})
        reply = ui.recv()
        ui.send(None)
        p.join(5)
        self.assertEqual([r["handler"] for r in reply["results"]], ["dns", "tcp", "http"])
        self.assertTrue(all(r["ok"] for r in reply["results"]))
        self.assertEqual(p.exitcode, 0)


if __name__ == "__main__":
    unittest.main()
