"""SQLite database connection, schema initialization, and query helpers."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
-- ============================================================
-- CORE KNOWLEDGE BASE
-- ============================================================

CREATE TABLE IF NOT EXISTS playbooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    key_insights TEXT NOT NULL,
    action_items TEXT NOT NULL,
    sources TEXT NOT NULL,
    relevance_score REAL NOT NULL,
    research_data TEXT,
    deep_dive_data TEXT,
    mode TEXT DEFAULT 'standard',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS playbooks_fts USING fts5(
    title, summary, key_insights, action_items,
    content='playbooks', content_rowid='id'
);

-- Keep FTS in sync
CREATE TRIGGER IF NOT EXISTS playbooks_ai AFTER INSERT ON playbooks BEGIN
    INSERT INTO playbooks_fts(rowid, title, summary, key_insights, action_items)
    VALUES (new.id, new.title, new.summary, new.key_insights, new.action_items);
END;

CREATE TRIGGER IF NOT EXISTS playbooks_ad AFTER DELETE ON playbooks BEGIN
    INSERT INTO playbooks_fts(playbooks_fts, rowid, title, summary, key_insights, action_items)
    VALUES ('delete', old.id, old.title, old.summary, old.key_insights, old.action_items);
END;

-- ============================================================
-- RESEARCH SESSIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS research_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    mode TEXT DEFAULT 'standard',
    playbook_id INTEGER REFERENCES playbooks(id),
    tavily_research_id TEXT,
    search_queries TEXT,
    urls_extracted TEXT,
    cost_usd REAL DEFAULT 0,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    status TEXT DEFAULT 'running'
);

-- ============================================================
-- API COSTS
-- ============================================================

CREATE TABLE IF NOT EXISTS api_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost_usd REAL,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- NOTION SYNC
-- ============================================================

CREATE TABLE IF NOT EXISTS notion_sync (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playbook_id INTEGER NOT NULL REFERENCES playbooks(id),
    notion_page_id TEXT,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sync_status TEXT DEFAULT 'synced'
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_playbooks_domain ON playbooks(domain);
CREATE INDEX IF NOT EXISTS idx_playbooks_relevance ON playbooks(relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_playbooks_created ON playbooks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_sessions_status ON research_sessions(status);
CREATE INDEX IF NOT EXISTS idx_notion_sync_playbook ON notion_sync(playbook_id);
"""


def get_db(db_path: str | Path = "information_engine.db") -> sqlite3.Connection:
    """Get a database connection."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db: sqlite3.Connection) -> None:
    """Initialize the database schema."""
    db.executescript(SCHEMA)
    db.commit()


def insert_playbook(
    db: sqlite3.Connection,
    topic: str,
    domain: str,
    title: str,
    summary: str,
    key_insights: list[str],
    action_items: list[str],
    sources: list[dict],
    relevance_score: float,
    research_data: dict | None = None,
    deep_dive_data: dict | None = None,
    mode: str = "standard",
) -> int:
    """Insert a playbook and return its ID."""
    cursor = db.execute(
        """INSERT INTO playbooks
           (topic, domain, title, summary, key_insights, action_items, sources,
            relevance_score, research_data, deep_dive_data, mode, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            topic,
            domain,
            title,
            summary,
            json.dumps(key_insights),
            json.dumps(action_items),
            json.dumps(sources),
            relevance_score,
            json.dumps(research_data) if research_data else None,
            json.dumps(deep_dive_data) if deep_dive_data else None,
            mode,
            datetime.now(UTC).isoformat(),
        ),
    )
    db.commit()
    return cursor.lastrowid


def get_playbook(db: sqlite3.Connection, playbook_id: int) -> dict | None:
    """Get a playbook by ID."""
    row = db.execute("SELECT * FROM playbooks WHERE id = ?", (playbook_id,)).fetchone()
    if not row:
        return None
    return _row_to_playbook(row)


def list_playbooks(
    db: sqlite3.Connection,
    domain: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """List playbooks, optionally filtered by domain."""
    if domain:
        rows = db.execute(
            "SELECT * FROM playbooks WHERE domain = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (domain, limit, offset),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM playbooks ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [_row_to_playbook(r) for r in rows]


def search_playbooks(db: sqlite3.Connection, query: str, limit: int = 20) -> list[dict]:
    """Full-text search across playbooks."""
    # Sanitize query for FTS5: quote each word to avoid syntax errors
    sanitized = " ".join(f'"{word}"' for word in query.split() if word.strip())
    if not sanitized:
        return []
    rows = db.execute(
        """SELECT p.* FROM playbooks p
           JOIN playbooks_fts fts ON p.id = fts.rowid
           WHERE playbooks_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (sanitized, limit),
    ).fetchall()
    return [_row_to_playbook(r) for r in rows]


def start_research_session(
    db: sqlite3.Connection,
    topic: str,
    mode: str = "standard",
) -> int:
    """Start a research session and return its ID."""
    cursor = db.execute(
        """INSERT INTO research_sessions (topic, mode, started_at)
           VALUES (?, ?, ?)""",
        (topic, mode, datetime.now(UTC).isoformat()),
    )
    db.commit()
    return cursor.lastrowid


def complete_research_session(
    db: sqlite3.Connection,
    session_id: int,
    playbook_id: int | None = None,
    tavily_research_id: str | None = None,
    search_queries: list[str] | None = None,
    urls_extracted: list[str] | None = None,
    cost_usd: float = 0,
    status: str = "completed",
) -> None:
    """Mark a research session as complete."""
    db.execute(
        """UPDATE research_sessions
           SET playbook_id = ?, tavily_research_id = ?, search_queries = ?,
               urls_extracted = ?, cost_usd = ?, completed_at = ?, status = ?
           WHERE id = ?""",
        (
            playbook_id,
            tavily_research_id,
            json.dumps(search_queries) if search_queries else None,
            json.dumps(urls_extracted) if urls_extracted else None,
            cost_usd,
            datetime.now(UTC).isoformat(),
            status,
            session_id,
        ),
    )
    db.commit()


def get_playbook_count(db: sqlite3.Connection) -> dict:
    """Get counts by domain and total."""
    total = db.execute("SELECT COUNT(*) FROM playbooks").fetchone()[0]
    domain_rows = db.execute(
        "SELECT domain, COUNT(*) as cnt FROM playbooks GROUP BY domain ORDER BY cnt DESC"
    ).fetchall()
    return {
        "total": total,
        "by_domain": {r["domain"]: r["cnt"] for r in domain_rows},
    }


def get_unsynced_playbooks(db: sqlite3.Connection, min_relevance: float = 0.5) -> list[dict]:
    """Get playbooks not yet synced to Notion."""
    rows = db.execute(
        """SELECT p.* FROM playbooks p
           LEFT JOIN notion_sync ns ON ns.playbook_id = p.id
           WHERE ns.id IS NULL AND p.relevance_score >= ?
           ORDER BY p.relevance_score DESC""",
        (min_relevance,),
    ).fetchall()
    return [_row_to_playbook(r) for r in rows]


def record_notion_sync(db: sqlite3.Connection, playbook_id: int, notion_page_id: str) -> None:
    """Record a successful Notion sync."""
    db.execute(
        "INSERT INTO notion_sync (playbook_id, notion_page_id) VALUES (?, ?)",
        (playbook_id, notion_page_id),
    )
    db.commit()


def _row_to_playbook(row: sqlite3.Row) -> dict:
    """Convert a database row to a playbook dict with parsed JSON fields."""
    d = dict(row)
    for field in ("key_insights", "action_items", "sources"):
        if d.get(field) and isinstance(d[field], str):
            d[field] = json.loads(d[field])
    return d
