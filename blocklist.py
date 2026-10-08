#!/usr/bin/env python3
"""Hämtar uppströms blocklistor, slår ihop dem och serverar resultatet över HTTP.

    python3 blocklist.py build          # bygg output/blocklist.txt en gång
    python3 blocklist.py serve          # bygg, servera och bygg om periodiskt

Endast standardbiblioteket används.
"""

import argparse
import concurrent.futures
import datetime
import hashlib
import http.server
import json
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LISTS_DIR = Path(os.environ.get("LISTS_DIR", ROOT / "lists"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", ROOT / "output"))
CACHE_DIR = OUTPUT_DIR / "cache"

USER_AGENT = "pihole-blocklist/1.0 (+https://firebog.net/)"
FETCH_TIMEOUT = 60
MAX_WORKERS = 8

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9_-]{1,63}(?<!-)(\.(?!-)[a-z0-9_-]{1,63}(?<!-))*\.[a-z][a-z0-9-]{1,62}$"
)
SINK_IPS = {"0.0.0.0", "127.0.0.1", "::", "::1", "0", "255.255.255.255"}
IGNORED = {"localhost", "localhost.localdomain", "local", "broadcasthost", "ip6-localhost", "ip6-loopback"}

build_lock = threading.Lock()


def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def read_list_file(path):
    if not path.exists():
        return []
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def parse_line(line):
    """Returnerar en domän från en rad i hosts-, domän- eller adblock-format, annars None."""
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("!") or line.startswith("["):
        return None
    # Adblock: ||example.com^  (bara rena domänregler, inga sökvägar/modifierare)
    if line.startswith("||"):
        rule = line[2:]
        if not rule.endswith("^"):
            return None
        line = rule[:-1]
    else:
        parts = line.split()
        if len(parts) >= 2 and parts[0] in SINK_IPS:
            line = parts[1]
        elif len(parts) == 1:
            line = parts[0]
        else:
            return None
    domain = line.strip().strip(".").lower()
    if domain in IGNORED or not DOMAIN_RE.match(domain):
        return None
    return domain


def cache_path(url):
    return CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".txt")


def fetch(url):
    """Hämtar en lista. Vid fel används senast lyckade kopian från cachen."""
    path = cache_path(url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        path.write_text(text, encoding="utf-8")
        return url, text, "ok"
    except Exception as e:
        if path.exists():
            return url, path.read_text(encoding="utf-8"), f"cached ({e})"
        return url, "", f"failed ({e})"


def build():
    with build_lock:
        started = time.time()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        sources = read_list_file(LISTS_DIR / "sources.txt")
        allow = {d.lower() for d in read_list_file(LISTS_DIR / "allowlist.txt")}
        custom = {d.lower() for d in read_list_file(LISTS_DIR / "blocklist.txt")}

        log(f"Hämtar {len(sources)} listor ...")
        domains = set(custom)
        stats = []
        with concurrent.futures.ThreadPoolExecutor(MAX_WORKERS) as pool:
            for url, text, status in pool.map(fetch, sources):
                found = {d for d in map(parse_line, text.splitlines()) if d}
                domains |= found
                stats.append({"url": url, "status": status, "domains": len(found)})
                log(f"  {len(found):>8}  {status:<6.6}  {url}")

        failed = [s for s in stats if s["status"].startswith("failed")]
        if sources and len(failed) == len(sources):
            log("Alla källor misslyckades, behåller tidigare lista.")
            return False

        domains -= allow
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        header = (
            f"# Sammanslagen blocklista\n"
            f"# Genererad: {now}\n"
            f"# Källor: {len(sources)} ({len(failed)} misslyckade)\n"
            f"# Domäner: {len(domains)}\n"
        )
        out = OUTPUT_DIR / "blocklist.txt"
        tmp = out.with_suffix(".tmp")
        tmp.write_text(header + "\n".join(sorted(domains)) + "\n", encoding="utf-8")
        tmp.replace(out)

        summary = {
            "generated": now,
            "domains": len(domains),
            "duration_s": round(time.time() - started, 1),
            "sources": stats,
        }
        (OUTPUT_DIR / "stats.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        log(f"Klar: {len(domains)} unika domäner på {summary['duration_s']} s.")
        return True


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OUTPUT_DIR), **kwargs)

    def do_GET(self):
        if self.path in ("/", "/blocklist.txt", "/stats.json", "/health"):
            if self.path == "/":
                self.path = "/blocklist.txt"
            if self.path == "/health":
                ok = (OUTPUT_DIR / "blocklist.txt").exists()
                self.send_response(200 if ok else 503)
                self.end_headers()
                self.wfile.write(b"ok\n" if ok else b"not ready\n")
                return
            return super().do_GET()
        self.send_error(404)

    def guess_type(self, path):
        if str(path).endswith(".txt"):
            return "text/plain; charset=utf-8"
        return super().guess_type(path)

    def log_message(self, fmt, *args):
        log(f"{self.address_string()} {fmt % args}")


def refresher(interval_h):
    while True:
        time.sleep(interval_h * 3600)
        try:
            build()
        except Exception as e:
            log(f"Bygget misslyckades: {e}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    s = sub.add_parser("serve")
    s.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    s.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    s.add_argument("--interval", type=float, default=float(os.environ.get("REFRESH_HOURS", 12)),
                   help="timmar mellan ombyggen (default 12)")
    args = p.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.cmd == "build":
        sys.exit(0 if build() else 1)

    build()
    threading.Thread(target=refresher, args=(args.interval,), daemon=True).start()
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    log(f"Serverar på http://{args.host}:{args.port}/blocklist.txt (bygger om var {args.interval}:e timme)")
    server.serve_forever()


if __name__ == "__main__":
    main()
