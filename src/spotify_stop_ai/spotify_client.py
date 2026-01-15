"""Spotify API client with PKCE OAuth flow."""

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SpotifyClient:
    """Spotify API client with OAuth PKCE authentication."""

    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        cache_path: str,
        client_secret: Optional[str] = None,
    ):
        """Initialize Spotify client with PKCE auth.

        Args:
            client_id: Spotify app client ID
            redirect_uri: OAuth redirect URI
            cache_path: Path to token cache file
            client_secret: Optional client secret (if not using PKCE)
        """
        self.client_id = client_id
        self.client_secret = client_secret or os.getenv("SPOTIFY_CLIENT_SECRET")
        self.redirect_uri = redirect_uri
        self.cache_path = cache_path

        # Required scopes for playback monitoring and control
        self.scopes = [
            "user-read-currently-playing",
            "user-read-playback-state",
            "user-modify-playback-state",
            "playlist-modify-private",
            "playlist-modify-public",
            "user-library-modify",
            "user-library-read",
        ]

        self.sp: Optional[spotipy.Spotify] = None
        self.auth_manager: Optional[SpotifyOAuth] = None

        # Cache for failed API calls to avoid repeated 404s
        self._failed_artist_lookups = set()

    def authenticate(self) -> bool:
        """Authenticate with Spotify using PKCE flow.

        Returns:
            True if authentication successful
        """
        try:
            auth_params = {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "scope": " ".join(self.scopes),
                "cache_path": self.cache_path,
                "open_browser": True,
            }

            # Add client_secret if provided, otherwise use PKCE
            if self.client_secret:
                auth_params["client_secret"] = self.client_secret

            self.auth_manager = SpotifyOAuth(**auth_params)

            # Create client with retries disabled - we handle rate limiting ourselves
            self.sp = spotipy.Spotify(
                auth_manager=self.auth_manager,
                requests_session=False,  # Use default session
                retries=0,  # Disable Spotipy's automatic retries
            )

            # Test authentication with a simple call
            user = self.sp.current_user()
            logger.info(
                f"Authenticated as Spotify user: {user['display_name']} ({user['id']})"
            )

            return True

        except Exception as e:
            logger.error(f"Spotify authentication failed: {e}")
            return False

    def get_current_playback(self) -> Optional[Dict[str, Any]]:
        """Get current playback state.

        Returns:
            Playback state dict, "rate_limited" string, or None if nothing playing
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return None

            playback = self.sp.current_playback()
            return playback

        except spotipy.SpotifyException as e:
            # Distinguish between rate limit and other errors
            if e.http_status == 429:
                logger.warning("Rate limited by Spotify (429)")
                return "rate_limited"
            logger.error(f"Spotify API error ({e.http_status}): {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get current playback: {e}")
            return None

    def get_currently_playing(self) -> Optional[Dict[str, Any]]:
        """Get currently playing track (lighter endpoint).

        Returns:
            Currently playing track dict or None
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return None

            currently_playing = self.sp.currently_playing()
            return currently_playing

        except Exception as e:
            logger.error(f"Failed to get currently playing: {e}")
            return None

    def skip_to_next(self) -> bool:
        """Skip to next track.

        Returns:
            True if skip successful
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return False

            self.sp.next_track()
            logger.info("Skipped to next track")
            return True

        except Exception as e:
            logger.error(f"Failed to skip track: {e}")
            return False

    def skip_to_previous(self) -> bool:
        """Skip to previous track.

        Returns:
            True if skip successful
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return False

            self.sp.previous_track()
            logger.info("Skipped to previous track")
            return True

        except Exception as e:
            logger.error(f"Failed to skip to previous: {e}")
            return False

    def pause_playback(self, device_id: Optional[str] = None) -> bool:
        """Pause playback.

        Args:
            device_id: Optional device ID (if None, pauses on current device)

        Returns:
            True if pause successful
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return False

            self.sp.pause_playback(device_id=device_id)
            logger.info("Paused playback")
            return True

        except Exception as e:
            logger.error(f"Failed to pause playback: {e}")
            return False

    def start_playback(
        self,
        device_id: Optional[str] = None,
        context_uri: Optional[str] = None,
        uris: Optional[list] = None,
        offset: Optional[int] = None,
    ) -> bool:
        """Start or resume playback.

        Args:
            device_id: Optional device ID
            context_uri: Optional context URI (playlist, album, artist)
            uris: Optional list of track URIs to play
            offset: Optional offset in context

        Returns:
            True if start successful
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return False

            self.sp.start_playback(
                device_id=device_id, context_uri=context_uri, uris=uris, offset=offset
            )
            logger.info("Started playback")
            return True

        except Exception as e:
            logger.error(f"Failed to start playback: {e}")
            return False

    def set_shuffle(self, state: bool, device_id: Optional[str] = None) -> bool:
        """Set shuffle state.

        Args:
            state: True to enable shuffle, False to disable
            device_id: Optional device ID

        Returns:
            True if successful
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return False

            self.sp.shuffle(state, device_id=device_id)
            logger.info(f"Set shuffle to {state}")
            return True

        except Exception as e:
            logger.error(f"Failed to set shuffle: {e}")
            return False

    def check_track_liked(self, track_uri: str) -> bool:
        """Check if current user has liked a track.

        Args:
            track_uri: Spotify track URI

        Returns:
            True if track is liked by user
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return False

            # Extract track ID from URI (format: spotify:track:ID)
            track_id = track_uri.split(":")[-1] if ":" in track_uri else track_uri

            results = self.sp.current_user_saved_tracks_contains([track_id])
            return results[0] if results else False

        except Exception as e:
            logger.error(f"Failed to check track liked status: {e}")
            return False

    def add_to_liked(self, track_uri: str) -> bool:
        """Add track to user's liked tracks.

        Args:
            track_uri: Spotify track URI

        Returns:
            True if successful
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return False

            # Extract track ID from URI
            track_id = track_uri.split(":")[-1] if ":" in track_uri else track_uri

            self.sp.current_user_saved_tracks_add([track_id])
            logger.info(f"Added track {track_uri} to liked tracks")
            return True

        except Exception as e:
            logger.error(f"Failed to add track to liked: {e}")
            return False

    def remove_from_liked(self, track_uri: str) -> bool:
        """Remove track from user's liked tracks.

        Args:
            track_uri: Spotify track URI

        Returns:
            True if successful
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return False

            # Extract track ID from URI
            track_id = track_uri.split(":")[-1] if ":" in track_uri else track_uri

            self.sp.current_user_saved_tracks_delete([track_id])
            logger.info(f"Removed track {track_uri} from liked tracks")
            return True

        except Exception as e:
            logger.error(f"Failed to remove track from liked: {e}")
            return False

    def remove_from_playlist(self, playlist_id: str, track_uri: str) -> bool:
        """Remove track from playlist.

        Args:
            playlist_id: Spotify playlist ID
            track_uri: Spotify track URI

        Returns:
            True if removal successful
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return False

            self.sp.playlist_remove_all_occurrences_of_items(playlist_id, [track_uri])
            logger.info(f"Removed track {track_uri} from playlist {playlist_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to remove track from playlist: {e}")
            return False

    def add_to_playlist(self, playlist_id: str, track_uri: str) -> bool:
        """Add track to playlist.

        Args:
            playlist_id: Spotify playlist ID
            track_uri: Spotify track URI

        Returns:
            True if addition successful
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return False

            self.sp.playlist_add_items(playlist_id, [track_uri])
            logger.info(f"Added track {track_uri} to playlist {playlist_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to add track to playlist: {e}")
            return False

    def get_playlist(self, playlist_id: str) -> Optional[Dict[str, Any]]:
        """Get playlist details.

        Args:
            playlist_id: Spotify playlist ID

        Returns:
            Playlist dict or None
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return None

            playlist = self.sp.playlist(playlist_id)
            return playlist

        except Exception as e:
            # Some playlists (like algorithmic mixes, radio stations) may not be publicly accessible
            # This is expected behavior, not an error
            logger.debug(f"Could not fetch playlist {playlist_id}: {e}")
            return None

    def create_playlist(
        self, name: str, description: str = "", public: bool = False
    ) -> Optional[str]:
        """Create a new playlist.

        Args:
            name: Playlist name
            description: Playlist description
            public: Whether playlist is public

        Returns:
            Playlist ID or None
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return None

            user = self.sp.current_user()
            playlist = self.sp.user_playlist_create(
                user["id"], name, public=public, description=description
            )
            logger.info(f"Created playlist: {name} ({playlist['id']})")
            return playlist["id"]

        except Exception as e:
            logger.error(f"Failed to create playlist: {e}")
            return None

    def get_devices(self) -> Optional[Dict[str, Any]]:
        """Get available Spotify Connect devices.

        Returns:
            Devices dict or None
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return None

            devices = self.sp.devices()
            return devices

        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            return None

    def get_artist(self, artist_id: str) -> Optional[Dict[str, Any]]:
        """Get artist details including genres and popularity.

        Args:
            artist_id: Spotify artist ID

        Returns:
            Artist dict or None
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return None

            artist = self.sp.artist(artist_id)
            return artist

        except Exception as e:
            logger.error(f"Failed to get artist {artist_id}: {e}")
            return None

    def get_artist_related(self, artist_id: str, limit: int = 5) -> Optional[list]:
        """Get artists similar to the given artist.

        Args:
            artist_id: Spotify artist ID
            limit: Max number of related artists

        Returns:
            List of related artists or None
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return None

            # Check if we've already failed to get this artist's related artists
            if artist_id in self._failed_artist_lookups:
                return None

            results = self.sp.artist_related_artists(artist_id)
            artists = results.get("artists", [])[:limit]
            return artists

        except Exception as e:
            # Cache 404 failures to avoid repeated API calls
            if "404" in str(e) or "Not Found" in str(e):
                self._failed_artist_lookups.add(artist_id)
                logger.debug(
                    f"Artist {artist_id} has no related artists available (cached)"
                )
            else:
                logger.error(f"Failed to get related artists for {artist_id}: {e}")
            return None

    def get_current_user_playlists(self, limit: int = 50) -> Optional[list]:
        """Get current user's playlists.

        Args:
            limit: Max number of playlists to return

        Returns:
            List of playlist dicts or None
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return None

            results = self.sp.current_user_playlists(limit=limit)
            return results.get("items", [])

        except Exception as e:
            logger.error(f"Failed to get user playlists: {e}")
            return None

    def get_playlist(self, playlist_id: str) -> Optional[Dict[str, Any]]:
        """Get playlist details.

        Args:
            playlist_id: Spotify playlist ID

        Returns:
            Playlist dict or None
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return None

            playlist = self.sp.playlist(playlist_id)
            return playlist

        except Exception as e:
            # Some playlists (like algorithmic mixes, radio stations) may not be publicly accessible
            # This is expected behavior, not an error
            logger.debug(f"Could not fetch playlist {playlist_id}: {e}")
            return None

    def check_artist_saved(self, artist_id: str) -> bool:
        """Check if artist is in user's favorite artists.

        Args:
            artist_id: Spotify artist ID

        Returns:
            True if artist is favorited, False otherwise
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return False

            # Check if artist is in user's saved artists
            results = self.sp.current_user_saved_artists_contains([artist_id])
            return results[0] if results else False

        except Exception as e:
            logger.debug(f"Failed to check if artist {artist_id} is saved: {e}")
            return False
