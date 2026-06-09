import json
from datetime import datetime, timedelta, timezone
from storage.database import get_connection, db_lock


def insert_results(results: list[dict]):
    """Bulk insert/replace plate check results, logging status transitions."""
    if not results:
        return
    rows = [
        (
            r["plate"],
            r["status"],
            r.get("plate_type"),
            len(r["plate"]),
            r.get("checked_at", datetime.now(timezone.utc).isoformat()),
            r.get("session_id"),
        )
        for r in results
    ]
    plates = [r["plate"] for r in results]
    placeholders = ",".join("?" * len(plates))

    with db_lock:
        conn = get_connection()
        try:
            existing = {
                row["plate"]: row["status"]
                for row in conn.execute(
                    f"SELECT plate, status FROM plates_checked WHERE plate IN ({placeholders})",
                    plates,
                ).fetchall()
            }

            # Only log transitions for plates we've seen before with a different status.
            # First-time sightings are skipped — we can't tell if they just freed up.
            transitions = [
                (r["plate"], existing[r["plate"]], r["status"])
                for r in results
                if r["plate"] in existing and existing[r["plate"]] != r["status"]
            ]

            if transitions:
                conn.executemany(
                    """INSERT INTO plate_transitions (plate, from_status, to_status)
                       VALUES (?, ?, ?)""",
                    transitions,
                )

            conn.executemany(
                """INSERT OR REPLACE INTO plates_checked
                   (plate, status, plate_type, plate_length, checked_at, session_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()
        finally:
            conn.close()


def get_unchecked_plates(candidates: list[str], max_age_hours: int = 24) -> list[str]:
    """Return plates from candidates not yet checked, or not checked within max_age_hours."""
    if not candidates:
        return []
    placeholders = ",".join("?" * len(candidates))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    with db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                f"SELECT plate FROM plates_checked WHERE plate IN ({placeholders}) AND checked_at > ?",
                candidates + [cutoff],
            ).fetchall()
            recently_checked = {r["plate"] for r in rows}
        finally:
            conn.close()
    return [p for p in candidates if p not in recently_checked]


def get_available_plates(
    filters: dict = None,
    sort: str = "checked_at_desc",
    page: int = 1,
    limit: int = 50,
) -> list[dict]:
    """Return paginated available plates with optional filters."""
    filters = filters or {}
    where_clauses = ["status = 'AVAILABLE'"]
    params = []

    if filters.get("plate_type"):
        where_clauses.append("plate_type = ?")
        params.append(filters["plate_type"])
    if filters.get("max_length"):
        where_clauses.append("plate_length <= ?")
        params.append(int(filters["max_length"]))
    if filters.get("min_length"):
        where_clauses.append("plate_length >= ?")
        params.append(int(filters["min_length"]))
    if filters.get("search"):
        where_clauses.append("plate LIKE ?")
        params.append(f"%{filters['search'].upper()}%")

    sort_map = {
        "checked_at_desc": "checked_at DESC",
        "checked_at_asc": "checked_at ASC",
        "plate_asc": "plate ASC",
        "length_asc": "plate_length ASC, plate ASC",
    }
    order_by = sort_map.get(sort, "checked_at DESC")

    offset = (page - 1) * limit
    where_sql = " AND ".join(where_clauses)
    params.extend([limit, offset])

    with db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                f"SELECT * FROM plates_checked WHERE {where_sql} ORDER BY {order_by} LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            count_row = conn.execute(
                f"SELECT COUNT(*) as total FROM plates_checked WHERE {where_sql}",
                params[:-2],
            ).fetchone()
        finally:
            conn.close()

    return {
        "plates": [dict(r) for r in rows],
        "total": count_row["total"],
        "page": page,
        "limit": limit,
    }


def get_recently_freed(page: int = 1, limit: int = 48, length: int | None = None) -> dict:
    """Plates that recently transitioned UNAVAILABLE → AVAILABLE and are still available."""
    offset = (page - 1) * limit

    where = [
        "t.from_status = 'UNAVAILABLE'",
        "t.to_status   = 'AVAILABLE'",
        "p.status      = 'AVAILABLE'",
    ]
    params: list = []
    if length is not None:
        where.append("p.plate_length = ?")
        params.append(length)
    where_sql = " AND ".join(where)

    with db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                f"""
                SELECT t.plate, MAX(t.transitioned_at) AS freed_at
                FROM plate_transitions t
                JOIN plates_checked p ON p.plate = t.plate
                WHERE {where_sql}
                GROUP BY t.plate
                ORDER BY freed_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
            count_row = conn.execute(
                f"""
                SELECT COUNT(*) AS total FROM (
                  SELECT t.plate
                  FROM plate_transitions t
                  JOIN plates_checked p ON p.plate = t.plate
                  WHERE {where_sql}
                  GROUP BY t.plate
                )
                """,
                params,
            ).fetchone()
        finally:
            conn.close()
    return {
        "plates": [{"plate": r["plate"], "freed_at": r["freed_at"]} for r in rows],
        "total": count_row["total"],
        "page": page,
        "limit": limit,
    }


def get_stats() -> dict:
    """Return aggregate statistics."""
    with db_lock:
        conn = get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) as n FROM plates_checked").fetchone()["n"]
            by_status = conn.execute(
                "SELECT status, COUNT(*) as n FROM plates_checked GROUP BY status"
            ).fetchall()
            by_type = conn.execute(
                "SELECT plate_type, COUNT(*) as n FROM plates_checked GROUP BY plate_type"
            ).fetchall()
        finally:
            conn.close()

    stats = {
        "total_checked": total,
        "by_status": {r["status"]: r["n"] for r in by_status},
        "by_type": {(r["plate_type"] or "unknown"): r["n"] for r in by_type},
    }
    stats["available"] = stats["by_status"].get("AVAILABLE", 0)
    return stats


def create_session(session_id: str, config: dict):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO search_sessions (session_id, config) VALUES (?, ?)",
                (session_id, json.dumps(config)),
            )
            conn.commit()
        finally:
            conn.close()


def close_session(session_id: str, plates_checked: int, plates_available: int):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute(
                """UPDATE search_sessions
                   SET ended_at = CURRENT_TIMESTAMP,
                       plates_checked = ?,
                       plates_available = ?
                   WHERE session_id = ?""",
                (plates_checked, plates_available, session_id),
            )
            conn.commit()
        finally:
            conn.close()


def get_plate(plate: str, max_age_hours: int = 24) -> dict | None:
    """Return a cached plate result if checked within max_age_hours, else None."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    with db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM plates_checked WHERE plate = ? AND checked_at > ?",
                (plate, cutoff),
            ).fetchone()
        finally:
            conn.close()
    return dict(row) if row else None


def get_last_checked_at() -> str | None:
    """Return the most recent checked_at timestamp across all plates."""
    with db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT MAX(checked_at) as latest FROM plates_checked"
            ).fetchone()
        finally:
            conn.close()
    return row["latest"] if row else None


def get_last_scanner_run() -> str | None:
    """Return the ended_at timestamp of the most recent completed scanner session."""
    with db_lock:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT MAX(ended_at) as latest FROM search_sessions WHERE ended_at IS NOT NULL"
            ).fetchone()
        finally:
            conn.close()
    return row["latest"] if row else None


def delete_plate(plate: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM plates_checked WHERE plate = ?", (plate,))
            conn.commit()
        finally:
            conn.close()


def get_stats_24h() -> dict:
    """Count plates checked and found available in the last 24 hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with db_lock:
        conn = get_connection()
        try:
            checked = conn.execute(
                "SELECT COUNT(*) as n FROM plates_checked WHERE checked_at > ?",
                (cutoff,),
            ).fetchone()["n"]
            available = conn.execute(
                "SELECT COUNT(*) as n FROM plates_checked WHERE status = 'AVAILABLE' AND checked_at > ?",
                (cutoff,),
            ).fetchone()["n"]
        finally:
            conn.close()
    return {"checked": checked, "available": available}


def get_session_available(session_id: str) -> list[dict]:
    """Return AVAILABLE plates found in a specific scan session, sorted by length."""
    with db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT * FROM plates_checked
                   WHERE session_id = ? AND status = 'AVAILABLE'
                   ORDER BY plate_length ASC, plate ASC""",
                (session_id,),
            ).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]
