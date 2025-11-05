"""Database schema and operations for Spotify Stop AI."""
import aiosqlite
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager for tracking plays and decisions."""
    
    def __init__(self, db_path: str):
        """Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
    async def initialize(self):
        """Create database schema if not exists."""
        async with aiosqlite.connect(self.db_path) as db:
            # Artists table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS artists (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    uri TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    play_count INTEGER DEFAULT 0
                )
            """)
            
            # Tracks table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    uri TEXT,
                    duration_ms INTEGER,
                    explicit INTEGER DEFAULT 0,
                    popularity INTEGER,
                    is_local INTEGER DEFAULT 0,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    play_count INTEGER DEFAULT 0
                )
            """)
            
            # Albums table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS albums (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    uri TEXT,
                    release_date TEXT,
                    first_seen TEXT NOT NULL
                )
            """)
            
            # Track-Artist relationship
            await db.execute("""
                CREATE TABLE IF NOT EXISTS track_artists (
                    track_id TEXT NOT NULL,
                    artist_id TEXT NOT NULL,
                    position INTEGER DEFAULT 0,
                    PRIMARY KEY (track_id, artist_id),
                    FOREIGN KEY (track_id) REFERENCES tracks(id),
                    FOREIGN KEY (artist_id) REFERENCES artists(id)
                )
            """)
            
            # Contexts (playlists, albums, etc.)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS contexts (
                    uri TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    name TEXT,
                    owner TEXT,
                    href TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                )
            """)
            
            # Plays table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS plays (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    album_id TEXT,
                    context_uri TEXT,
                    device_id TEXT,
                    device_name TEXT,
                    device_type TEXT,
                    progress_ms INTEGER,
                    is_playing INTEGER DEFAULT 1,
                    FOREIGN KEY (track_id) REFERENCES tracks(id),
                    FOREIGN KEY (album_id) REFERENCES albums(id),
                    FOREIGN KEY (context_uri) REFERENCES contexts(uri)
                )
            """)
            
            # Decisions table (classification results)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    artist_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    label TEXT NOT NULL,
                    is_artificial INTEGER,
                    confidence REAL NOT NULL,
                    sources_agreeing INTEGER NOT NULL,
                    min_required INTEGER NOT NULL,
                    band_policy_applied INTEGER DEFAULT 0,
                    llm_used INTEGER DEFAULT 0,
                    decision_reason TEXT,
                    cached_until TEXT,
                    FOREIGN KEY (artist_id) REFERENCES artists(id)
                )
            """)
            
            # Sources table (per-source classification results)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    result TEXT,
                    signals TEXT,
                    url TEXT,
                    query_time_ms INTEGER,
                    FOREIGN KEY (decision_id) REFERENCES decisions(id)
                )
            """)
            
            # LLM outputs table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS llm_outputs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt TEXT,
                    output TEXT,
                    load_duration_ms INTEGER,
                    eval_duration_ms INTEGER,
                    total_duration_ms INTEGER,
                    FOREIGN KEY (decision_id) REFERENCES decisions(id)
                )
            """)
            
            # Actions table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    play_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    skipped INTEGER DEFAULT 0,
                    removed_from_playlist INTEGER DEFAULT 0,
                    added_to_blocked_playlist INTEGER DEFAULT 0,
                    FOREIGN KEY (play_id) REFERENCES plays(id)
                )
            """)
            
            # Overrides table (user manual corrections)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS overrides (
                    artist_id TEXT PRIMARY KEY,
                    is_artificial INTEGER NOT NULL,
                    reason TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (artist_id) REFERENCES artists(id)
                )
            """)
            
            # Indexes
            await db.execute("CREATE INDEX IF NOT EXISTS idx_plays_timestamp ON plays(timestamp)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_plays_track ON plays(track_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_decisions_artist ON decisions(artist_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_sources_decision ON sources(decision_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_actions_play ON actions(play_id)")
            
            await db.commit()
            logger.info(f"Database initialized at {self.db_path}")
    
    async def upsert_artist(self, artist_id: str, name: str, uri: str) -> None:
        """Insert or update artist record."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO artists (id, name, uri, first_seen, last_seen, play_count)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    uri = excluded.uri,
                    last_seen = excluded.last_seen,
                    play_count = play_count + 1
            """, (artist_id, name, uri, now, now))
            await db.commit()
    
    async def upsert_track(self, track_id: str, name: str, uri: str,
                          duration_ms: int, explicit: bool, popularity: int,
                          is_local: bool) -> None:
        """Insert or update track record."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO tracks (id, name, uri, duration_ms, explicit, popularity,
                                   is_local, first_seen, last_seen, play_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    uri = excluded.uri,
                    duration_ms = excluded.duration_ms,
                    explicit = excluded.explicit,
                    popularity = excluded.popularity,
                    is_local = excluded.is_local,
                    last_seen = excluded.last_seen,
                    play_count = play_count + 1
            """, (track_id, name, uri, duration_ms, int(explicit),
                  popularity, int(is_local), now, now))
            await db.commit()
    
    async def upsert_album(self, album_id: str, name: str, uri: str,
                          release_date: Optional[str]) -> None:
        """Insert or update album record."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO albums (id, name, uri, release_date, first_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    uri = excluded.uri,
                    release_date = excluded.release_date
            """, (album_id, name, uri, release_date, now))
            await db.commit()
    
    async def link_track_artist(self, track_id: str, artist_id: str,
                               position: int = 0) -> None:
        """Link track to artist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO track_artists (track_id, artist_id, position)
                VALUES (?, ?, ?)
            """, (track_id, artist_id, position))
            await db.commit()
    
    async def upsert_context(self, uri: str, context_type: str, name: Optional[str],
                            owner: Optional[str], href: Optional[str]) -> None:
        """Insert or update context (playlist/album/etc.)."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO contexts (uri, type, name, owner, href, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uri) DO UPDATE SET
                    type = excluded.type,
                    name = excluded.name,
                    owner = excluded.owner,
                    href = excluded.href,
                    last_seen = excluded.last_seen
            """, (uri, context_type, name, owner, href, now, now))
            await db.commit()
    
    async def insert_play(self, play_id: str, timestamp: str, track_id: str,
                         album_id: Optional[str], context_uri: Optional[str],
                         device_id: Optional[str], device_name: Optional[str],
                         device_type: Optional[str], progress_ms: int,
                         is_playing: bool) -> None:
        """Insert play record."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO plays (id, timestamp, track_id, album_id, context_uri,
                                  device_id, device_name, device_type, progress_ms, is_playing)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (play_id, timestamp, track_id, album_id, context_uri,
                  device_id, device_name, device_type, progress_ms, int(is_playing)))
            await db.commit()
    
    async def insert_decision(self, decision_id: str, artist_id: str,
                             label: str, is_artificial: Optional[bool],
                             confidence: float, sources_agreeing: int,
                             min_required: int, band_policy_applied: bool,
                             llm_used: bool, decision_reason: str,
                             cached_until: str) -> None:
        """Insert classification decision."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO decisions (id, artist_id, timestamp, label, is_artificial,
                                      confidence, sources_agreeing, min_required,
                                      band_policy_applied, llm_used, decision_reason,
                                      cached_until)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (decision_id, artist_id, now, label,
                  None if is_artificial is None else int(is_artificial),
                  confidence, sources_agreeing, min_required,
                  int(band_policy_applied), int(llm_used), decision_reason,
                  cached_until))
            await db.commit()
    
    async def insert_source_result(self, decision_id: str, source_name: str,
                                   success: bool, result: Optional[str],
                                   signals: Optional[str], url: Optional[str],
                                   query_time_ms: int) -> None:
        """Insert source classification result."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO sources (decision_id, source_name, success, result,
                                    signals, url, query_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (decision_id, source_name, int(success), result,
                  signals, url, query_time_ms))
            await db.commit()
    
    async def insert_llm_output(self, decision_id: str, model: str,
                               prompt: str, output: str,
                               load_duration_ms: int, eval_duration_ms: int,
                               total_duration_ms: int) -> None:
        """Insert LLM output record."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO llm_outputs (decision_id, model, prompt, output,
                                        load_duration_ms, eval_duration_ms,
                                        total_duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (decision_id, model, prompt, output,
                  load_duration_ms, eval_duration_ms, total_duration_ms))
            await db.commit()
    
    async def insert_action(self, play_id: str, skipped: bool,
                           removed_from_playlist: bool,
                           added_to_blocked_playlist: bool) -> None:
        """Insert action record."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO actions (play_id, timestamp, skipped,
                                    removed_from_playlist, added_to_blocked_playlist)
                VALUES (?, ?, ?, ?, ?)
            """, (play_id, now, int(skipped),
                  int(removed_from_playlist), int(added_to_blocked_playlist)))
            await db.commit()
    
    async def get_override(self, artist_id: str) -> Optional[Dict[str, Any]]:
        """Get user override for artist."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM overrides WHERE artist_id = ?
            """, (artist_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    
    async def set_override(self, artist_id: str, is_artificial: bool,
                          reason: Optional[str]) -> None:
        """Set user override for artist."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO overrides (artist_id, is_artificial, reason, timestamp)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(artist_id) DO UPDATE SET
                    is_artificial = excluded.is_artificial,
                    reason = excluded.reason,
                    timestamp = excluded.timestamp
            """, (artist_id, int(is_artificial), reason, now))
            await db.commit()
    
    async def delete_override(self, artist_id: str) -> None:
        """Delete user override for artist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM overrides WHERE artist_id = ?",
                           (artist_id,))
            await db.commit()
    
    async def get_cached_decision(self, artist_id: str) -> Optional[Dict[str, Any]]:
        """Get cached decision for artist if not expired."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM decisions
                WHERE artist_id = ? AND cached_until > ?
                ORDER BY timestamp DESC LIMIT 1
            """, (artist_id, now)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    
    async def get_plays(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get recent plays."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT p.*, t.name as track_name, a.name as album_name,
                       c.name as context_name, c.type as context_type
                FROM plays p
                LEFT JOIN tracks t ON p.track_id = t.id
                LEFT JOIN albums a ON p.album_id = a.id
                LEFT JOIN contexts c ON p.context_uri = c.uri
                ORDER BY p.timestamp DESC
                LIMIT ? OFFSET ?
            """, (limit, offset)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_decisions(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get recent decisions."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT d.*, a.name as artist_name
                FROM decisions d
                LEFT JOIN artists a ON d.artist_id = a.id
                ORDER BY d.timestamp DESC
                LIMIT ? OFFSET ?
            """, (limit, offset)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
