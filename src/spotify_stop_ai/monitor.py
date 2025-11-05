"""Playback monitor and action engine."""
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Set
import time

logger = logging.getLogger(__name__)


class PlaybackMonitor:
    """Monitor Spotify playback and take actions on AI artists."""
    
    def __init__(self, spotify_client, classifier, database, config: Dict[str, Any]):
        """Initialize monitor.
        
        Args:
            spotify_client: SpotifyClient instance
            classifier: ArtistClassifier instance
            database: Database instance
            config: Configuration dict
        """
        self.spotify = spotify_client
        self.classifier = classifier
        self.db = database
        self.config = config
        
        self.poll_interval = config["monitor"]["poll_interval_seconds"]
        self.rate_limit_backoff = config["monitor"]["rate_limit_backoff_multiplier"]
        self.max_backoff = config["monitor"]["max_backoff_seconds"]
        
        self.auto_skip = config["actions"]["auto_skip"]
        self.remove_from_playlists = config["actions"]["remove_from_user_playlists"]
        self.blocked_playlist_name = config["actions"].get("add_to_blocked_playlist", "")
        
        self.current_backoff = self.poll_interval
        self.last_track_id: Optional[str] = None
        self.processed_tracks: Set[str] = set()  # Track IDs processed in this session
        self.running = False
        self.blocked_playlist_id: Optional[str] = None
        
        # Track current state for web UI
        self.current_track: Optional[Dict[str, Any]] = None
        self.last_decision: Optional[Dict[str, Any]] = None
    
    async def start(self):
        """Start monitoring playback."""
        logger.info("Starting playback monitor...")
        self.running = True
        
        # Initialize blocked playlist if configured
        if self.blocked_playlist_name:
            await self._ensure_blocked_playlist()
        
        while self.running:
            try:
                await self._monitor_cycle()
                await asyncio.sleep(self.current_backoff)
                
            except Exception as e:
                logger.error(f"Monitor cycle error: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)
    
    async def stop(self):
        """Stop monitoring."""
        logger.info("Stopping playback monitor...")
        self.running = False
    
    async def _monitor_cycle(self):
        """Single monitoring cycle."""
        # Get current playback
        playback = self.spotify.get_current_playback()
        
        if not playback:
            # Nothing playing or API error
            self.current_backoff = self.poll_interval
            return
        
        # Check for rate limiting
        if playback == "rate_limited":
            self.current_backoff = min(
                self.current_backoff * self.rate_limit_backoff,
                self.max_backoff
            )
            logger.warning(f"Rate limited, backing off to {self.current_backoff}s")
            return
        
        # Reset backoff on success
        self.current_backoff = self.poll_interval
        
        # Check if playing
        if not playback.get("is_playing"):
            return
        
        # Get track info
        item = playback.get("item")
        if not item or item.get("type") != "track":
            return
        
        track_id = item["id"]
        track_name = item["name"]
        artist_info = item["artists"][0] if item.get("artists") else {}
        artist_id = artist_info.get("id")
        artist_name = artist_info.get("name", "Unknown")
        
        # Update current track for web UI
        self.current_track = {
            "track_id": track_id,
            "track_name": track_name,
            "artist_id": artist_id,
            "artist_name": artist_name,
            "timestamp": datetime.now().isoformat()
        }
        
        # Skip if same track as last check
        if track_id == self.last_track_id:
            return
        
        self.last_track_id = track_id
        
        # Skip if already processed in this session
        if track_id in self.processed_tracks:
            return
        
        self.processed_tracks.add(track_id)
        
        # Process track
        await self._process_track(playback, item)
    
    async def _process_track(self, playback: Dict[str, Any], item: Dict[str, Any]):
        """Process a new track.
        
        Args:
            playback: Full playback state
            item: Track item
        """
        track_id = item["id"]
        track_name = item["name"]
        artists = item.get("artists", [])
        
        if not artists:
            logger.warning(f"Track {track_name} has no artists")
            return
        
        logger.info(f"Processing track: {track_name} by {artists[0]['name']}")
        
        # Log play to database
        play_id = await self._log_play(playback, item)
        
        # Classify primary artist
        primary_artist = artists[0]
        artist_id = primary_artist["id"]
        artist_name = primary_artist["name"]
        
        decision = await self.classifier.classify_artist(
            artist_id, artist_name, track_name
        )
        self.last_decision = decision  # Store for web UI
        
        logger.info(
            f"Classification: {artist_name} -> {decision['label']} "
            f"(artificial: {decision['is_artificial']}, "
            f"confidence: {decision['confidence']:.2f})"
        )
        
        # Take action if artificial
        if decision["is_artificial"] is True:
            await self._take_action(play_id, item, playback, decision)
    
    async def _log_play(self, playback: Dict[str, Any], item: Dict[str, Any]) -> str:
        """Log play to database.
        
        Args:
            playback: Playback state
            item: Track item
            
        Returns:
            Play ID
        """
        try:
            # Extract data
            track_id = item["id"]
            track_name = item["name"]
            track_uri = item["uri"]
            duration_ms = item.get("duration_ms", 0)
            explicit = item.get("explicit", False)
            popularity = item.get("popularity", 0)
            is_local = item.get("is_local", False)
            
            album = item.get("album", {})
            album_id = album.get("id")
            album_name = album.get("name", "")
            album_uri = album.get("uri", "")
            release_date = album.get("release_date")
            
            context = playback.get("context")
            context_uri = context.get("uri") if context else None
            context_type = context.get("type") if context else None
            
            device = playback.get("device", {})
            device_id = device.get("id")
            device_name = device.get("name")
            device_type = device.get("type")
            
            progress_ms = playback.get("progress_ms", 0)
            is_playing = playback.get("is_playing", False)
            
            timestamp = datetime.utcnow().isoformat()
            play_id = f"play_{timestamp}_{track_id}"
            
            # Upsert track
            await self.db.upsert_track(
                track_id, track_name, track_uri, duration_ms,
                explicit, popularity, is_local
            )
            
            # Upsert album
            if album_id:
                await self.db.upsert_album(
                    album_id, album_name, album_uri, release_date
                )
            
            # Upsert artists and link to track
            for idx, artist in enumerate(item.get("artists", [])):
                await self.db.upsert_artist(
                    artist["id"], artist["name"], artist["uri"]
                )
                await self.db.link_track_artist(
                    track_id, artist["id"], idx
                )
            
            # Upsert context
            if context_uri:
                context_name = None
                context_owner = None
                context_href = context.get("href")
                
                # Try to get playlist name if context is a playlist
                if context_type == "playlist":
                    playlist_id = context_uri.split(":")[-1]
                    playlist = self.spotify.get_playlist(playlist_id)
                    if playlist:
                        context_name = playlist.get("name")
                        context_owner = playlist.get("owner", {}).get("id")
                
                await self.db.upsert_context(
                    context_uri, context_type, context_name,
                    context_owner, context_href
                )
            
            # Insert play
            await self.db.insert_play(
                play_id, timestamp, track_id, album_id, context_uri,
                device_id, device_name, device_type, progress_ms, is_playing
            )
            
            return play_id
            
        except Exception as e:
            logger.error(f"Failed to log play: {e}", exc_info=True)
            return f"play_{datetime.utcnow().isoformat()}_{item['id']}"
    
    async def _take_action(self, play_id: str, item: Dict[str, Any],
                          playback: Dict[str, Any], decision: Dict[str, Any]):
        """Take action on artificial track.
        
        Args:
            play_id: Play ID
            item: Track item
            playback: Playback state
            decision: Classification decision
        """
        skipped = False
        removed_from_playlist = False
        added_to_blocked = False
        
        artist_name = item["artists"][0]["name"]
        track_name = item["name"]
        
        logger.warning(
            f"AI/Virtual artist detected: {artist_name} - {track_name} "
            f"(confidence: {decision['confidence']:.2f})"
        )
        
        # Auto-skip
        if self.auto_skip:
            success = self.spotify.skip_to_next()
            if success:
                skipped = True
                logger.info(f"Skipped track: {track_name}")
            else:
                logger.error(f"Failed to skip track: {track_name}")
        
        # Remove from user playlist
        if self.remove_from_playlists:
            context = playback.get("context")
            if context and context.get("type") == "playlist":
                playlist_id = context["uri"].split(":")[-1]
                playlist = self.spotify.get_playlist(playlist_id)
                
                if playlist:
                    owner_id = playlist.get("owner", {}).get("id")
                    current_user = self.spotify.sp.current_user()
                    
                    # Only remove from user-owned playlists
                    if owner_id == current_user["id"]:
                        success = self.spotify.remove_from_playlist(
                            playlist_id, item["uri"]
                        )
                        if success:
                            removed_from_playlist = True
                            logger.info(
                                f"Removed {track_name} from playlist {playlist['name']}"
                            )
        
        # Add to blocked playlist
        if self.blocked_playlist_id:
            success = self.spotify.add_to_playlist(
                self.blocked_playlist_id, item["uri"]
            )
            if success:
                added_to_blocked = True
                logger.info(f"Added {track_name} to blocked playlist")
        
        # Log action
        await self.db.insert_action(
            play_id, skipped, removed_from_playlist, added_to_blocked
        )
    
    async def _ensure_blocked_playlist(self):
        """Ensure blocked playlist exists."""
        if not self.blocked_playlist_name:
            return
        
        try:
            # Search for existing playlist
            user = self.spotify.sp.current_user()
            playlists = self.spotify.sp.current_user_playlists(limit=50)
            
            for playlist in playlists.get("items", []):
                if playlist["name"] == self.blocked_playlist_name:
                    self.blocked_playlist_id = playlist["id"]
                    logger.info(
                        f"Found existing blocked playlist: {self.blocked_playlist_name}"
                    )
                    return
            
            # Create new playlist
            playlist_id = self.spotify.create_playlist(
                self.blocked_playlist_name,
                description="AI-generated and virtual artists blocked by spotify-stop-ai",
                public=False
            )
            
            if playlist_id:
                self.blocked_playlist_id = playlist_id
                logger.info(
                    f"Created blocked playlist: {self.blocked_playlist_name}"
                )
        
        except Exception as e:
            logger.error(f"Failed to ensure blocked playlist: {e}")
