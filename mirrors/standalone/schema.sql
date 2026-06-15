-- Mirror of the Django `mirrors` app schema (SQLite).
-- Table/column names match Django's ORM conventions so the same DB
-- file is readable by both implementations. Only the tables the JSON
-- API needs are defined here (MirrorRsync is omitted).

CREATE TABLE IF NOT EXISTS mirrors_mirrorprotocol (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol    VARCHAR(10) UNIQUE NOT NULL,
    is_download BOOLEAN NOT NULL DEFAULT 1,
    "default"   BOOLEAN NOT NULL DEFAULT 1,
    created     DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS mirrors_mirror (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            VARCHAR(255) UNIQUE NOT NULL,
    tier            SMALLINT NOT NULL DEFAULT 2,
    admin_email     VARCHAR(255) NOT NULL DEFAULT '',
    alternate_email VARCHAR(255) NOT NULL DEFAULT '',
    public          BOOLEAN NOT NULL DEFAULT 1,
    active          BOOLEAN NOT NULL DEFAULT 1,
    isos            BOOLEAN NOT NULL DEFAULT 1,
    rsync_user      VARCHAR(50) NOT NULL DEFAULT '',
    rsync_password  VARCHAR(50) NOT NULL DEFAULT '',
    bug             INTEGER,
    notes           TEXT NOT NULL DEFAULT '',
    created         DATETIME NOT NULL,
    last_modified   DATETIME NOT NULL,
    upstream_id     INTEGER REFERENCES mirrors_mirror(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS mirrors_mirrorurl (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         VARCHAR(255) UNIQUE NOT NULL,
    country     VARCHAR(2) NOT NULL DEFAULT '',
    has_ipv4    BOOLEAN NOT NULL DEFAULT 1,
    has_ipv6    BOOLEAN NOT NULL DEFAULT 0,
    created     DATETIME NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT 1,
    bandwidth   REAL,
    mirror_id   INTEGER NOT NULL REFERENCES mirrors_mirror(id) ON DELETE CASCADE,
    protocol_id INTEGER NOT NULL REFERENCES mirrors_mirrorprotocol(id)
);

CREATE TABLE IF NOT EXISTS mirrors_checklocation (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname  VARCHAR(255) NOT NULL,
    source_ip VARCHAR(39) UNIQUE NOT NULL,
    country   VARCHAR(2) NOT NULL,
    created   DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS mirrors_mirrorlog (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    check_time  DATETIME NOT NULL,
    last_sync   DATETIME,
    duration    REAL,
    is_success  BOOLEAN NOT NULL DEFAULT 1,
    error       TEXT NOT NULL DEFAULT '',
    location_id INTEGER REFERENCES mirrors_checklocation(id) ON DELETE CASCADE,
    url_id      INTEGER NOT NULL REFERENCES mirrors_mirrorurl(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS mirrors_mirrorlog_check_time ON mirrors_mirrorlog(check_time);
CREATE INDEX IF NOT EXISTS mirrors_mirrorurl_country ON mirrors_mirrorurl(country);
