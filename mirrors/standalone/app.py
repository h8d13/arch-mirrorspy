"""Stdlib HTTP server + CLI for the Django-free mirrors JSON API.

Routes (mirroring archweb URLs):
    GET /mirrors/status/json/
    GET /mirrors/status/tier/<n>/json/
    GET /mirrors/<name>/json/
    GET /mirrors/locations/json/

Run:
    python -m mirrors.standalone.app --db mirrors.db --init --seed --serve
"""

import argparse
import json
import os
import re
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import checker, core, importer

# (regex, handler) table. Handlers receive (conn, match) and return a dict.
ROUTES = [
    (re.compile(r'^/mirrors/status/json/?$'),
     lambda conn, m: core.status_json(conn)),
    (re.compile(r'^/mirrors/status/tier/(-?\d+)/json/?$'),
     lambda conn, m: core.status_json(conn, tier=int(m.group(1)))),
    (re.compile(r'^/mirrors/locations/json/?$'),
     lambda conn, m: core.locations_json(conn)),
    (re.compile(r'^/mirrors/([^/]+)/json/?$'),
     lambda conn, m: core.mirror_details_json(conn, m.group(1))),
]


class _TTLCache:
    """Replaces Django's cache_function / cache_control max-age."""

    def __init__(self, ttl):
        self.ttl = ttl
        self._store = {}

    def get_or_set(self, key, producer):
        now = time.monotonic()
        hit = self._store.get(key)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        value = producer()
        self._store[key] = (now, value)
        return value


def make_handler(db_path, cache_ttl=178):
    cache = _TTLCache(cache_ttl)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'mirrors-standalone/1.0'

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            for pattern, fn in ROUTES:
                match = pattern.match(path)
                if not match:
                    continue
                try:
                    payload = cache.get_or_set(
                        path, lambda fn=fn, match=match: fn(core.connect(db_path), match))
                except core.NotFound:
                    return self._send(404, {'error': 'not found'})
                return self._send(200, payload)
            self._send(404, {'error': 'not found'})

        def _send(self, code, payload):
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass  # quiet by default; flip to super() for access logs

    return Handler


def seed(conn):
    """Insert a small, self-consistent dataset for local testing."""
    now = core.utcnow()
    n = core.fmt(now)

    cur = conn.cursor()
    cur.executemany(
        'INSERT INTO mirrors_mirrorprotocol (protocol, is_download, "default", created) '
        'VALUES (?, ?, ?, ?)',
        [('https', 1, 1, n), ('http', 1, 0, n), ('rsync', 0, 0, n)])
    https_id, http_id = 1, 2

    cur.executemany(
        'INSERT INTO mirrors_mirror (name, tier, public, active, isos, created, last_modified) '
        'VALUES (?, ?, 1, 1, 1, ?, ?)',
        [('mirror.example.org', 1, n, n), ('mirror.example.net', 2, n, n)])
    m1, m2 = 1, 2

    cur.executemany(
        'INSERT INTO mirrors_mirrorurl (url, country, has_ipv4, has_ipv6, created, active, '
        'mirror_id, protocol_id) VALUES (?, ?, ?, ?, ?, 1, ?, ?)',
        [('https://mirror.example.org/archlinux/', 'DE', 1, 1, n, m1, https_id),
         ('https://mirror.example.net/archlinux/', 'US', 1, 0, n, m2, https_id),
         ('http://mirror.example.net/archlinux/', 'US', 1, 0, n, m2, http_id)])

    cur.executemany(
        'INSERT INTO mirrors_checklocation (hostname, source_ip, country, created) '
        'VALUES (?, ?, ?, ?)',
        [('check-eu.example.org', '192.0.2.10', 'DE', n),
         ('check-us.example.org', '2001:db8::1', 'US', n)])

    # logs: a handful of recent checks per url so stats have something to chew on
    rows = []
    for url_id in (1, 2, 3):
        for i in range(4):
            ct = core.fmt(now - timedelta(hours=i))
            ls = core.fmt(now - timedelta(hours=i, minutes=30))
            rows.append((ct, ls, 0.25 + 0.1 * i, 1, '', 1, url_id))
    cur.executemany(
        'INSERT INTO mirrors_mirrorlog (check_time, last_sync, duration, is_success, error, '
        'location_id, url_id) VALUES (?, ?, ?, ?, ?, ?, ?)', rows)
    conn.commit()


def main(argv=None):
    p = argparse.ArgumentParser(description='Django-free mirrors JSON API')
    p.add_argument('--db', default='mirrors.db', help='SQLite path (default: mirrors.db)')
    p.add_argument('--init', action='store_true', help='create schema if missing')
    p.add_argument('--seed', action='store_true', help='insert sample data')
    p.add_argument('--import-urls', dest='import_urls', action='store_true',
                   help='seed mirror URLs from the live archweb feed')
    p.add_argument('--feed-url', default=importer.FEED_URL, help='status feed to import')
    p.add_argument('--check', action='store_true',
                   help='poll active mirrors once and store MirrorLog rows')
    p.add_argument('--timeout', type=float, default=10.0, help='per-mirror timeout (s)')
    p.add_argument('--threads', type=int, default=10, help='checker worker threads')
    p.add_argument('--limit', type=int, help='cap number of mirrors polled (testing)')
    p.add_argument('--dump', metavar='DIR', help='write computed JSON files to DIR')
    p.add_argument('--serve', action='store_true', help='start the HTTP server')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8000)
    args = p.parse_args(argv)

    conn = core.connect(args.db)
    if args.init:
        core.init_schema(conn)
    if args.seed:
        seed(conn)
    if args.import_urls:
        n = importer.import_from_feed(conn, args.feed_url)
        total = conn.execute('SELECT COUNT(*) AS c FROM mirrors_mirrorurl').fetchone()['c']
        print(f'imported {n} new mirror URLs ({total} total) from {args.feed_url}')
    if args.check:
        n = checker.run(conn, timeout=args.timeout, num_threads=args.threads, limit=args.limit)
        print(f'polled {n} mirrors, wrote {n} MirrorLog rows')
    if args.dump:
        os.makedirs(args.dump, exist_ok=True)
        written = ['status.json']
        payloads = {'status.json': core.status_json(conn)}
        # locations only exist with local CheckLocation data; skip when empty
        locations = core.locations_json(conn)
        if locations['locations']:
            payloads['locations.json'] = locations
            written.append('locations.json')
        for fname, payload in payloads.items():
            with open(os.path.join(args.dump, fname), 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False)
        print(f"wrote {', '.join(written)} to {args.dump}")
    conn.close()

    if args.serve:
        handler = make_handler(args.db)
        httpd = ThreadingHTTPServer((args.host, args.port), handler)
        print(f'serving on http://{args.host}:{args.port}/mirrors/status/json/')
        httpd.serve_forever()


if __name__ == '__main__':
    main()
