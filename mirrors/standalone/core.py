"""Data access + serialization, Django-free.

Ports `mirrors/utils.py` (get_mirror_statuses, status_data, annotate_url)
and `mirrors/views/api.py` (the three JSON builders) onto stdlib sqlite3.

Placeholder note: Django used the `format` paramstyle (`%s`); stdlib
sqlite3 uses qmark (`?`). The STRFTIME('%%s', ...) double-percent in the
Django source was escaping for that paramstyle and becomes a single
'%s' here.
"""

import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address

from .countries import country_name

DEFAULT_CUTOFF = timedelta(hours=24)
DEFAULT_DOMAIN = 'archlinux.org'

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schema.sql')


class NotFound(Exception):
    """Raised in place of Django's Http404."""


# --- time helpers -----------------------------------------------------------

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fmt(dt):
    """Datetime -> the text form stored in the DB (matches Django sqlite)."""
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def parse_dt(text):
    if text is None:
        return None
    return datetime.fromisoformat(text)


def iso(dt):
    """ISO 8601 with a 'Z' suffix, matching DjangoJSONEncoder on UTC values.

    Stored datetimes are naive UTC; Django stored tz-aware UTC and rendered
    '+00:00' as 'Z'. Microseconds are trimmed to milliseconds like Django.
    """
    if dt is None:
        return None
    text = dt.isoformat()
    if dt.microsecond:
        text = text[:23]
    return text + 'Z'


def secs(td):
    """Timedelta -> integer seconds (Django dropped microseconds too)."""
    if td is None:
        return None
    return td.days * 24 * 3600 + td.seconds


# --- db ----------------------------------------------------------------------

def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_schema(conn):
    with open(SCHEMA_PATH, encoding='utf-8') as fh:
        conn.executescript(fh.read())
    conn.commit()


def dictfetchall(cursor):
    return [dict(row) for row in cursor.fetchall()]


# --- stats (ports utils.py) --------------------------------------------------

def status_data(conn, cutoff_time, mirror_id=None):
    if mirror_id is not None:
        params = [cutoff_time, mirror_id]
        mirror_where = 'AND u.mirror_id = ?'
    else:
        params = [cutoff_time]
        mirror_where = ''

    # duration_stddev: SQLite lacks STDDEV, so we pull the pieces for a
    # sample stddev (sum, sum-of-squares, n) and finish the sqrt in Python.
    # Matches postgres STDDEV_SAMP, replacing the old 0.0 placeholder.
    sql = """
SELECT l.url_id, u.mirror_id,
    COUNT(l.id) AS check_count,
    COUNT(l.last_sync) AS success_count,
    MAX(l.last_sync) AS last_sync,
    MAX(l.check_time) AS last_check,
    AVG(l.duration) AS duration_avg,
    SUM(l.duration) AS _dur_sum,
    SUM(l.duration * l.duration) AS _dur_sqsum,
    COUNT(l.duration) AS _dur_n,
    AVG(STRFTIME('%s', l.check_time) - STRFTIME('%s', l.last_sync)) AS delay
FROM mirrors_mirrorlog l
JOIN mirrors_mirrorurl u ON u.id = l.url_id
WHERE l.check_time >= ?
""" + mirror_where + """
GROUP BY l.url_id, u.mirror_id
"""
    url_data = dictfetchall(conn.execute(sql, params))

    # sqlite returns the aggregates as raw text/float; normalize types
    for item in url_data:
        if item['delay'] is not None:
            item['delay'] = timedelta(seconds=item['delay'])
        if item['last_sync'] is not None:
            item['last_sync'] = parse_dt(item['last_sync'])
        if item['last_check'] is not None:
            item['last_check'] = parse_dt(item['last_check'])
        item['duration_stddev'] = _sample_stddev(
            item.pop('_dur_sum'), item.pop('_dur_sqsum'), item.pop('_dur_n'))

    return {item['url_id']: item for item in url_data}


def _sample_stddev(total, sqsum, n):
    """Sample standard deviation from running sums; 0.0 for n < 2."""
    if not n or n < 2 or total is None:
        return 0.0
    variance = (sqsum - total * total / n) / (n - 1)
    return math.sqrt(variance) if variance > 0 else 0.0


def annotate_url(url, url_data):
    """Add status fields to a url dict; pure arithmetic, verbatim port."""
    url['success_count'] = 0
    url['check_count'] = 0
    url['completion_pct'] = None
    url['duration_avg'] = None
    url['duration_stddev'] = None
    url['last_check'] = None
    url['last_sync'] = None
    url['delay'] = None
    url['score'] = None
    for k, v in url_data.items():
        if k not in ('url_id', 'mirror_id'):
            url[k] = v

    if url['check_count'] > 0:
        url['completion_pct'] = float(url['success_count']) / url['check_count']

    if url['delay'] is not None:
        hours = url['delay'].days * 24.0 + url['delay'].seconds / 3600.0
        if url['completion_pct'] > 0.0:
            divisor = url['completion_pct']
        else:
            divisor = 0.005
        stddev = url['duration_stddev'] or 0.0
        url['score'] = (hours + url['duration_avg'] + stddev) / divisor

    return url


def get_mirror_statuses(conn, cutoff=DEFAULT_CUTOFF, mirror_id=None, show_all=False):
    cutoff_time = fmt(utcnow() - cutoff)

    where = []
    params = []
    if mirror_id:
        where.append('u.mirror_id = ?')
        params.append(mirror_id)
    if not show_all:
        where.append('u.active = 1 AND m.active = 1 AND m.public = 1')
    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''

    sql = f"""
SELECT u.id, u.url, u.country, u.has_ipv4, u.has_ipv6, u.active,
       p.protocol AS protocol,
       m.id AS mirror_id, m.name AS mirror_name, m.isos, m.tier
FROM mirrors_mirrorurl u
JOIN mirrors_mirror m ON m.id = u.mirror_id
JOIN mirrors_mirrorprotocol p ON p.id = u.protocol_id
{where_sql}
ORDER BY m.id, u.url
"""
    urls = dictfetchall(conn.execute(sql, params))

    if urls:
        url_data = status_data(conn, cutoff_time, mirror_id)
        urls = [annotate_url(u, url_data.get(u['id'], {})) for u in urls]
        last_check = max([u['last_check'] for u in urls if u['last_check']] or [None])
        num_checks = max(u['check_count'] for u in urls)

        cf_where = 'check_time >= ?'
        cf_params = [cutoff_time]
        if mirror_id:
            cf_where += (' AND url_id IN '
                         '(SELECT id FROM mirrors_mirrorurl WHERE mirror_id = ?)')
            cf_params.append(mirror_id)
        row = conn.execute(
            f'SELECT MIN(check_time) AS mn, MAX(check_time) AS mx '
            f'FROM mirrors_mirrorlog WHERE {cf_where}', cf_params).fetchone()

        if num_checks > 1 and row['mn'] and row['mx']:
            check_frequency = (parse_dt(row['mx']) - parse_dt(row['mn'])) / (num_checks - 1)
        else:
            check_frequency = None
    else:
        urls = []
        last_check = None
        num_checks = 0
        check_frequency = None

    return {
        'cutoff': cutoff,
        'last_check': last_check,
        'num_checks': num_checks,
        'check_frequency': check_frequency,
        'urls': urls,
    }


def logs_by_url(conn, mirror_id, cutoff=DEFAULT_CUTOFF):
    cutoff_time = fmt(utcnow() - cutoff)
    rows = dictfetchall(conn.execute("""
SELECT url_id, check_time, last_sync, duration, is_success, location_id, error
FROM mirrors_mirrorlog
WHERE check_time >= ?
  AND url_id IN (SELECT id FROM mirrors_mirrorurl WHERE mirror_id = ?)
ORDER BY check_time
""", [cutoff_time, mirror_id]))
    grouped = {}
    for r in rows:
        grouped.setdefault(r['url_id'], []).append(r)
    return grouped


# --- serialization (ports the api.py encoders) -------------------------------

def _mirror_url(domain, name):
    return f'https://{domain}/mirrors/{name}/'


def _full_url(domain, name, pk):
    return f'https://{domain}/mirrors/{name}/{pk}/'


def url_to_json(u, domain):
    return {
        'url': u['url'],
        'protocol': u['protocol'],
        'last_sync': iso(u['last_sync']),
        'completion_pct': u['completion_pct'],
        'delay': secs(u['delay']),
        'duration_avg': u['duration_avg'],
        'duration_stddev': u['duration_stddev'],
        'score': u['score'],
        'active': bool(u['active']),
        'country': country_name(u['country']),
        'country_code': u['country'],
        'isos': bool(u['isos']),
        'ipv4': bool(u['has_ipv4']),
        'ipv6': bool(u['has_ipv6']),
        'details': _full_url(domain, u['mirror_name'], u['id']),
    }


def log_to_json(log):
    return {
        'check_time': iso(parse_dt(log['check_time'])),
        'last_sync': iso(parse_dt(log['last_sync'])),
        'duration': log['duration'],
        'is_success': bool(log['is_success']),
        'location_id': log['location_id'],
        'error': log['error'] or None,
    }


def ip_version(source_ip):
    try:
        return ip_address(source_ip).version
    except ValueError:
        return None


# --- endpoints (ports api.py) ------------------------------------------------

def status_json(conn, tier=None, domain=DEFAULT_DOMAIN):
    status = get_mirror_statuses(conn)
    urls = status['urls']
    if tier is not None:
        valid_tiers = {0, 1, 2, -1}
        if tier not in valid_tiers:
            raise NotFound
        urls = [u for u in urls if u['tier'] == tier]
    return {
        'cutoff': secs(status['cutoff']),
        'last_check': iso(status['last_check']),
        'num_checks': status['num_checks'],
        'check_frequency': secs(status['check_frequency']),
        'urls': [url_to_json(u, domain) for u in urls],
        'version': 3,
    }


def mirror_details_json(conn, name, domain=DEFAULT_DOMAIN):
    row = conn.execute('SELECT * FROM mirrors_mirror WHERE name = ?', [name]).fetchone()
    if row is None:
        raise NotFound
    mirror = dict(row)
    # Public read-only API: no auth, so private/inactive mirrors are hidden.
    if not (mirror['public'] and mirror['active']):
        raise NotFound

    status = get_mirror_statuses(conn, mirror_id=mirror['id'], show_all=False)
    logs = logs_by_url(conn, mirror['id'])

    urls_json = []
    for u in status['urls']:
        entry = url_to_json(u, domain)
        entry['logs'] = [log_to_json(log) for log in logs.get(u['id'], [])]
        urls_json.append(entry)

    data = {
        'cutoff': secs(status['cutoff']),
        'last_check': iso(status['last_check']),
        'num_checks': status['num_checks'],
        'check_frequency': secs(status['check_frequency']),
        'urls': urls_json,
        'version': 5,
        'tier': mirror['tier'],
    }
    if mirror['upstream_id']:
        up = conn.execute('SELECT name FROM mirrors_mirror WHERE id = ?',
                          [mirror['upstream_id']]).fetchone()
        if up:
            data['upstream'] = up['name']
    data['details'] = _mirror_url(domain, mirror['name'])
    return data


def locations_json(conn):
    rows = dictfetchall(conn.execute(
        'SELECT id, hostname, source_ip, country '
        'FROM mirrors_checklocation ORDER BY id'))
    locations = [{
        'id': r['id'],
        'hostname': r['hostname'],
        'source_ip': r['source_ip'],
        'country': country_name(r['country']),
        'country_code': r['country'],
        'ip_version': ip_version(r['source_ip']),
    } for r in rows]
    return {'version': 1, 'locations': locations}
