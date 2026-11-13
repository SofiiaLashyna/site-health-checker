"""Registry of available handlers.

Each handler takes the task value (a site address) and returns
a tuple (score 0..100, human-readable detail).
If a check cannot be performed, the handler raises an exception;
the executive part turns it into a score of 0.
"""
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import NamedTuple
from urllib.parse import urlsplit

TIMEOUT = 5.0  # seconds per check


class Target(NamedTuple):
    scheme: str
    host: str
    port: int
    url: str


def parse_target(value: str) -> Target:
    """'example.com', 'example.com:8443', 'http://localhost:8000/path' -> Target."""
    raw = value.strip()
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"invalid address: {value!r}")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise ValueError(f"invalid port in address: {value!r}")
    url = f"{parts.scheme}://{parts.netloc}{parts.path or '/'}"
    if parts.query:
        url += "?" + parts.query
    return Target(parts.scheme, parts.hostname, port, url)


def speed_score(ms: float, good: float, bad: float) -> int:
    """100 if faster than `good` ms, 20 if slower than `bad`, linear in between."""
    if ms <= good:
        return 100
    if ms >= bad:
        return 20
    return round(100 - 80 * (ms - good) / (bad - good))


def _ms_since(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


# ---------------------------------------------------------------- handlers

def check_dns(value: str):
    """DNS: does the name resolve, and how fast"""
    t = parse_target(value)
    t0 = time.perf_counter()
    infos = socket.getaddrinfo(t.host, t.port, proto=socket.IPPROTO_TCP)
    ms = _ms_since(t0)
    ips = sorted({info[4][0] for info in infos})
    return speed_score(ms, good=50, bad=1000), f"{len(ips)} address(es), e.g. {ips[0]}"


def check_tcp(value: str):
    """TCP: is the port open, and connection time"""
    t = parse_target(value)
    t0 = time.perf_counter()
    with socket.create_connection((t.host, t.port), timeout=TIMEOUT):
        ms = _ms_since(t0)
    return speed_score(ms, good=100, bad=1500), f"port {t.port} open, {ms:.0f} ms"


def check_http(value: str):
    """HTTP: response status and page load time"""
    t = parse_target(value)
    req = urllib.request.Request(t.url, headers={"User-Agent": "site-health-checker/1.0"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            resp.read(64 * 1024)  # read the beginning of the page, not the whole site
            code = resp.status
    except urllib.error.HTTPError as e:  # 4xx / 5xx: server is up but returns an error
        code = e.code
    ms = _ms_since(t0)
    if code < 400:
        score = speed_score(ms, good=300, bad=3000)
    elif code < 500:
        score = 40
    else:
        score = 10
    return score, f"HTTP {code}, {ms:.0f} ms"


def check_ssl(value: str):
    """SSL: is the certificate valid, and days until it expires"""
    t = parse_target(value)
    if t.scheme != "https":
        return 0, "site does not use HTTPS"
    ctx = ssl.create_default_context()
    with socket.create_connection((t.host, t.port), timeout=TIMEOUT) as sock:
        with ctx.wrap_socket(sock, server_hostname=t.host) as tls:
            cert = tls.getpeercert()
    days = int((ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) // 86400)
    if days > 30:
        score = 100
    elif days > 7:
        score = 60
    elif days >= 0:
        score = 20
    else:
        score = 0
    return score, f"certificate valid for {days} more day(s)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Makes urllib report a 3xx response instead of silently following it."""
    def redirect_request(self, *args, **kwargs):
        return None


def check_redirect(value: str):
    """Redirect: does plain http:// send visitors to https://"""
    t = parse_target(value)
    parts = urlsplit(t.url)
    path = parts.path + ("?" + parts.query if parts.query else "")
    # for an https site, check what its plain-HTTP twin on port 80 does
    url = t.url if t.scheme == "http" else f"http://{t.host}{path}"
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=TIMEOUT) as resp:
            return 20, f"serves plain HTTP ({resp.status}) without redirect"
    except urllib.error.HTTPError as e:
        location = e.headers.get("Location", "")
        if 300 <= e.code < 400:
            if location.startswith("https://"):
                return 100, f"{e.code} -> {location}"
            return 40, f"{e.code} -> {location or '?'} (not HTTPS)"
        return 30, f"plain HTTP answers with {e.code}"
    except urllib.error.URLError as e:
        if isinstance(e.reason, ConnectionRefusedError):
            return 100, "plain HTTP is not served at all"
        raise


SECURITY_HEADERS = [
    "Strict-Transport-Security",
    "Content-Security-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
]


def check_headers(value: str):
    """Headers: how many common security headers the site sends"""
    t = parse_target(value)
    req = urllib.request.Request(t.url, headers={"User-Agent": "site-health-checker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            headers = resp.headers
    except urllib.error.HTTPError as e:  # error pages still carry headers
        headers = e.headers
    missing = [h for h in SECURITY_HEADERS if h not in headers]
    found = len(SECURITY_HEADERS) - len(missing)
    score = round(100 * found / len(SECURITY_HEADERS))
    detail = f"{found}/{len(SECURITY_HEADERS)} security headers"
    if missing:
        detail += ", missing: " + ", ".join(missing)
    return score, detail


def check_ipv6(value: str):
    """IPv6: does the domain have an IPv6 (AAAA) address"""
    t = parse_target(value)
    try:
        infos = socket.getaddrinfo(t.host, t.port, socket.AF_INET6, socket.SOCK_STREAM)
        return 100, f"IPv6 address {infos[0][4][0]}"
    except socket.gaierror:
        # no AAAA record; make sure the name resolves at all (otherwise it's a real failure)
        socket.getaddrinfo(t.host, t.port, socket.AF_INET, socket.SOCK_STREAM)
        return 50, "IPv4 only, no IPv6 address"


HANDLERS = {
    "dns": check_dns,
    "tcp": check_tcp,
    "http": check_http,
    "ssl": check_ssl,
    "redirect": check_redirect,
    "headers": check_headers,
    "ipv6": check_ipv6,
}


def describe() -> dict:
    """Handler name -> short description (shown to the user)."""
    return {name: fn.__doc__.strip() for name, fn in HANDLERS.items()}
