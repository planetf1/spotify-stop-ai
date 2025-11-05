"""MusicBrainz API classifier for detecting virtual/AI artists."""
import logging
from typing import Optional, Dict, Any
import httpx
import time
from aiolimiter import AsyncLimiter

logger = logging.getLogger(__name__)


class MusicBrainzClassifier:
    """Classify artists using MusicBrainz tags and metadata."""
    
    VIRTUAL_TAGS = {
        "vocaloid", "vtuber", "virtual", "virtual idol", "virtual singer",
        "fictional", "ai generated", "voice synthesis", "synthesized"
    }
    
    def __init__(self, user_agent: str, timeout: int = 10, rate_limit: float = 1.0):
        """Initialize MusicBrainz classifier.
        
        Args:
            user_agent: User agent string for API requests
            timeout: Request timeout in seconds
            rate_limit: Max requests per second (MusicBrainz requires ≤1/sec)
        """
        self.base_url = "https://musicbrainz.org/ws/2"
        self.user_agent = user_agent
        self.timeout = timeout
        # Rate limiter: 1 request per second
        self.rate_limiter = AsyncLimiter(max_rate=rate_limit, time_period=1.0)
    
    async def classify(self, artist_name: str, artist_id: str) -> Dict[str, Any]:
        """Classify artist using MusicBrainz.
        
        Args:
            artist_name: Artist name to search
            artist_id: Spotify artist ID (for logging)
            
        Returns:
            Classification result dict
        """
        start_time = time.time()
        
        try:
            # Search for artist MBID
            mbid = await self._search_artist(artist_name)
            
            if not mbid:
                return {
                    "success": False,
                    "result": None,
                    "mbid": None,
                    "tags": [],
                    "url": None,
                    "query_time_ms": int((time.time() - start_time) * 1000),
                    "error": "Artist not found"
                }
            
            # Get artist tags
            tags = await self._get_artist_tags(mbid)
            
            query_time_ms = int((time.time() - start_time) * 1000)
            
            # Check for virtual/AI tags
            matching_tags = [
                tag for tag in tags
                if any(vt in tag.lower() for vt in self.VIRTUAL_TAGS)
            ]
            
            if matching_tags:
                # Determine type from tags
                result_type = self._determine_type(matching_tags)
                
                return {
                    "success": True,
                    "result": result_type,
                    "mbid": mbid,
                    "tags": matching_tags,
                    "url": f"https://musicbrainz.org/artist/{mbid}",
                    "query_time_ms": query_time_ms
                }
            else:
                return {
                    "success": True,
                    "result": "human",
                    "mbid": mbid,
                    "tags": [],
                    "url": f"https://musicbrainz.org/artist/{mbid}",
                    "query_time_ms": query_time_ms
                }
        
        except Exception as e:
            logger.error(f"MusicBrainz classification failed for {artist_name}: {e}")
            return {
                "success": False,
                "result": None,
                "mbid": None,
                "tags": [],
                "url": None,
                "query_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }
    
    async def _search_artist(self, artist_name: str) -> Optional[str]:
        """Search for artist MBID.
        
        Args:
            artist_name: Artist name to search
            
        Returns:
            MusicBrainz ID (MBID) or None
        """
        async with self.rate_limiter:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.base_url}/artist/",
                        params={
                            "query": f'artist:"{artist_name}"',
                            "fmt": "json",
                            "limit": 1
                        },
                        headers={"User-Agent": self.user_agent},
                        timeout=self.timeout
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("artists"):
                            return data["artists"][0]["id"]
                    
                    return None
                    
            except Exception as e:
                logger.error(f"MusicBrainz artist search failed: {e}")
                return None
    
    async def _get_artist_tags(self, mbid: str) -> list[str]:
        """Get tags for artist.
        
        Args:
            mbid: MusicBrainz ID
            
        Returns:
            List of tag names
        """
        async with self.rate_limiter:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.base_url}/artist/{mbid}",
                        params={
                            "inc": "tags+genres",
                            "fmt": "json"
                        },
                        headers={"User-Agent": self.user_agent},
                        timeout=self.timeout
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        tags = []
                        
                        # Extract tags
                        if "tags" in data:
                            tags.extend([tag["name"] for tag in data["tags"]])
                        
                        # Extract genres
                        if "genres" in data:
                            tags.extend([genre["name"] for genre in data["genres"]])
                        
                        return tags
                    
                    return []
                    
            except Exception as e:
                logger.error(f"MusicBrainz tag fetch failed: {e}")
                return []
    
    def _determine_type(self, tags: list[str]) -> str:
        """Determine classification type from tags.
        
        Args:
            tags: List of tag names
            
        Returns:
            Classification type string
        """
        tags_lower = [tag.lower() for tag in tags]
        
        if "vocaloid" in tags_lower:
            return "vocaloid"
        elif "vtuber" in tags_lower:
            return "vtuber"
        elif any(tag in tags_lower for tag in ["virtual idol", "virtual singer"]):
            return "virtual_idol"
        elif "fictional" in tags_lower:
            return "fictional"
        elif "ai generated" in tags_lower:
            return "ai_generated"
        else:
            return "virtual"
