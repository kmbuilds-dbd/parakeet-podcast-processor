"""Database layer using DuckDB for P³ storage."""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
import duckdb
from pathlib import Path

logger = logging.getLogger(__name__)


class P3Database:
    def __init__(self, db_path: str = "data/p3.duckdb"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        self._initialize_schema()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _row_to_dict(self, row, description) -> Dict[str, Any]:
        """Map a result row to a dict using cursor column names."""
        return {desc[0]: val for desc, val in zip(description, row)}

    def _fetchall_as_dicts(self, cursor) -> List[Dict[str, Any]]:
        """Fetch all rows from a cursor as a list of dicts."""
        description = cursor.description
        return [self._row_to_dict(row, description) for row in cursor.fetchall()]

    def _fetchone_as_dict(self, cursor) -> Optional[Dict[str, Any]]:
        """Fetch one row from a cursor as a dict, or None."""
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row, cursor.description)

    def _initialize_schema(self):
        """Create database schema if not exists."""
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS podcast_id_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS podcasts (
                id INTEGER PRIMARY KEY DEFAULT nextval('podcast_id_seq'),
                title VARCHAR NOT NULL,
                rss_url VARCHAR UNIQUE NOT NULL,
                category VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS episode_id_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY DEFAULT nextval('episode_id_seq'),
                podcast_id INTEGER REFERENCES podcasts(id),
                title VARCHAR NOT NULL,
                date TIMESTAMP,
                url VARCHAR UNIQUE NOT NULL,
                file_path VARCHAR,
                duration_seconds INTEGER,
                status VARCHAR DEFAULT 'downloaded',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS transcript_id_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY DEFAULT nextval('transcript_id_seq'),
                episode_id INTEGER REFERENCES episodes(id),
                speaker VARCHAR,
                timestamp_start REAL,
                timestamp_end REAL,
                text TEXT NOT NULL,
                confidence REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS summary_id_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY DEFAULT nextval('summary_id_seq'),
                episode_id INTEGER REFERENCES episodes(id),
                key_topics JSON,
                themes JSON,
                quotes JSON,
                startups JSON,
                digest_date DATE,
                full_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indexes for common query patterns
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_status ON episodes(status)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_url ON episodes(url)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_transcripts_episode_id ON transcripts(episode_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_digest_date ON summaries(digest_date)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_episode_id ON summaries(episode_id)")

    def add_podcast(self, title: str, rss_url: str, category: str = None) -> int:
        """Add new podcast feed."""
        next_id = self.conn.execute("SELECT nextval('podcast_id_seq')").fetchone()[0]
        self.conn.execute(
            "INSERT INTO podcasts (id, title, rss_url, category) VALUES (?, ?, ?, ?)",
            (next_id, title, rss_url, category)
        )
        return next_id

    def get_podcast_by_url(self, rss_url: str) -> Optional[Dict[str, Any]]:
        """Get podcast by RSS URL."""
        cursor = self.conn.execute(
            "SELECT * FROM podcasts WHERE rss_url = ?", (rss_url,)
        )
        return self._fetchone_as_dict(cursor)

    def add_episode(self, podcast_id: int, title: str, date: datetime, url: str,
                   file_path: str = None) -> int:
        """Add new episode."""
        next_id = self.conn.execute("SELECT nextval('episode_id_seq')").fetchone()[0]
        self.conn.execute("""
            INSERT INTO episodes (id, podcast_id, title, date, url, file_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (next_id, podcast_id, title, date, url, file_path))
        return next_id

    def episode_exists(self, url: str) -> bool:
        """Check if episode already exists."""
        result = self.conn.execute(
            "SELECT 1 FROM episodes WHERE url = ?", (url,)
        ).fetchone()
        return result is not None

    def get_episode_by_id(self, episode_id: int) -> Optional[Dict[str, Any]]:
        """Get a single episode by ID, joined with podcast title."""
        cursor = self.conn.execute("""
            SELECT e.*, p.title as podcast_title
            FROM episodes e
            JOIN podcasts p ON e.podcast_id = p.id
            WHERE e.id = ?
        """, (episode_id,))
        return self._fetchone_as_dict(cursor)

    def get_episodes_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get episodes by processing status."""
        cursor = self.conn.execute("""
            SELECT e.*, p.title as podcast_title
            FROM episodes e
            JOIN podcasts p ON e.podcast_id = p.id
            WHERE e.status = ?
            ORDER BY e.date DESC
        """, (status,))
        return self._fetchall_as_dicts(cursor)

    def update_episode_status(self, episode_id: int, status: str):
        """Update episode processing status."""
        self.conn.execute(
            "UPDATE episodes SET status = ? WHERE id = ?",
            (status, episode_id)
        )

    def add_transcript_segments(self, episode_id: int, segments: List[Dict[str, Any]]):
        """Add transcript segments for an episode."""
        for segment in segments:
            self.conn.execute("""
                INSERT INTO transcripts (episode_id, speaker, timestamp_start, timestamp_end, text, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                episode_id,
                segment.get("speaker"),
                segment.get("start"),
                segment.get("end"),
                segment.get("text"),
                segment.get("confidence")
            ))

    def get_transcripts_for_episode(self, episode_id: int) -> List[Dict[str, Any]]:
        """Get all transcript segments for an episode."""
        cursor = self.conn.execute("""
            SELECT * FROM transcripts WHERE episode_id = ?
            ORDER BY timestamp_start
        """, (episode_id,))
        return self._fetchall_as_dicts(cursor)

    def add_summary(self, episode_id: int, key_topics: List[str], themes: List[str],
                   quotes: List[str], startups: List[str], full_summary: str,
                   digest_date: datetime = None):
        """Add episode summary."""
        if digest_date is None:
            digest_date = datetime.now().date()

        self.conn.execute("""
            INSERT INTO summaries (episode_id, key_topics, themes, quotes, startups, full_summary, digest_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            episode_id,
            json.dumps(key_topics),
            json.dumps(themes),
            json.dumps(quotes),
            json.dumps(startups),
            full_summary,
            digest_date
        ))

    def get_summaries_by_date(self, date: datetime) -> List[Dict[str, Any]]:
        """Get all summaries for a specific date."""
        cursor = self.conn.execute("""
            SELECT s.*, e.title as episode_title, p.title as podcast_title
            FROM summaries s
            JOIN episodes e ON s.episode_id = e.id
            JOIN podcasts p ON e.podcast_id = p.id
            WHERE s.digest_date = ?
            ORDER BY p.title, e.title
        """, (date.date(),))
        rows = self._fetchall_as_dicts(cursor)
        # Deserialize JSON columns
        for row in rows:
            for col in ('key_topics', 'themes', 'quotes', 'startups'):
                if isinstance(row[col], str):
                    row[col] = json.loads(row[col])
        return rows

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
