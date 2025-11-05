"""Spotify API client with PKCE OAuth flow."""
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SpotifyClient:
    """Spotify API client with OAuth PKCE authentication."""
    
    def __init__(self, client_id: str, redirect_uri: str, cache_path: str, client_secret: Optional[str] = None):
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
            "user-library-modify"
        ]
        
        self.sp: Optional[spotipy.Spotify] = None
        self.auth_manager: Optional[SpotifyOAuth] = None
    
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
                "open_browser": True
            }
            
            # Add client_secret if provided, otherwise use PKCE
            if self.client_secret:
                auth_params["client_secret"] = self.client_secret
            
            self.auth_manager = SpotifyOAuth(**auth_params)
            
            self.sp = spotipy.Spotify(auth_manager=self.auth_manager)
            
            # Test authentication with a simple call
            user = self.sp.current_user()
            logger.info(f"Authenticated as Spotify user: {user['display_name']} ({user['id']})")
            
            return True
            
        except Exception as e:
            logger.error(f"Spotify authentication failed: {e}")
            return False
    
    def get_current_playback(self) -> Optional[Dict[str, Any]]:
        """Get current playback state.
        
        Returns:
            Playback state dict or None if nothing playing
        """
        try:
            if not self.sp:
                logger.error("Spotify client not authenticated")
                return None
            
            playback = self.sp.current_playback()
            return playback
            
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
            
            self.sp.playlist_remove_all_occurrences_of_items(
                playlist_id, [track_uri]
            )
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
    
    def create_playlist(self, name: str, description: str = "",
                       public: bool = False) -> Optional[str]:
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
                user['id'], name, public=public, description=description
            )
            logger.info(f"Created playlist: {name} ({playlist['id']})")
            return playlist['id']
            
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
