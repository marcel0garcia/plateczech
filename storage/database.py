import sqlite3
import threading
from config import DATABASE_PATH

_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock:
        conn = get_connection()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS plates_checked (
                    plate        TEXT PRIMARY KEY,
                    status       TEXT NOT NULL,
                    plate_type   TEXT,
                    plate_length INTEGER,
                    checked_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                    session_id   TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_status ON plates_checked(status);
                CREATE INDEX IF NOT EXISTS idx_type   ON plates_checked(plate_type);
                CREATE INDEX IF NOT EXISTS idx_length ON plates_checked(plate_length);

                CREATE TABLE IF NOT EXISTS search_sessions (
                    session_id       TEXT PRIMARY KEY,
                    started_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                    ended_at         DATETIME,
                    config           TEXT,
                    plates_checked   INTEGER DEFAULT 0,
                    plates_available INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS plate_transitions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    plate           TEXT NOT NULL,
                    from_status     TEXT NOT NULL,
                    to_status       TEXT NOT NULL,
                    transitioned_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_trans_plate ON plate_transitions(plate);
                CREATE INDEX IF NOT EXISTS idx_trans_at    ON plate_transitions(transitioned_at);
                CREATE INDEX IF NOT EXISTS idx_trans_to    ON plate_transitions(to_status);
            """)
            conn.commit()
        finally:
            conn.close()


# Module-level lock exposed for queries.py to use
db_lock = _lock
