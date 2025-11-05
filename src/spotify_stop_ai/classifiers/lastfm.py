"""Last.fm API classifier for detecting virtual/AI artists."""
import logging
from typing import Optional, Dict, Any
import httpx
import time

logger = logging.getLogger(__name__)


class LastFmClassifier:
    """Classify artists using Last.fm tag data."""
    
    VIRTUAL_KEYWORDS = {
        "vocaloid", "vtuber", "virtual idol", "virtual singer", "virtual",
        "fictional", "ai generated", "voice synthesis", "synthesized voice"
    }
    
    def __init__(self, api_key: str, timeout: int = 10, min_tag_count: int = 5):
        """Initialize Last.fm classifier.
        
        Args:
            api_key: Last.fm API key
            timeout: Request timeout in seconds
            min_tag_count: Minimum tag count to consider (filters noise)
        """
        self.api_key = api_key
        self.base_url = "http://ws.audioscrobbler.com/2.0/"
        self.timeout = timeout
        self.min_tag_count = min_tag_count
    
    async def classify(self, artist_name: str, artist_id: str) -> Dict[str, Any]:
        """Classify artist using Last.fm tags.
        
        Args:
            artist_name: Artist name to search
            artist_id: Spotify artist ID (for logging)
            
        Returns:
            Classification result dict
        """
        start_time = time.time()
        
        try:
            # Get top tags for artist
            tags = await self._get_artist_tags(artist_name)
            
            query_time_ms = int((time.time() - start_time) * 1000)
            
            if not tags:
                return {
                    "success": False,
                    "result": None,
                    "tags": [],
                    "url": None,
                    "query_time_ms": query_time_ms,
                    "error": "No tags found"
                }
            
            # Filter tags by minimum count and check for virtual keywords
            matching_tags = [
                tag for tag in tags
                if tag["count"] >= self.min_tag_count and
                any(kw in tag["name"].lower() for kw in self.VIRTUAL_KEYWORDS)
            ]
            
            if matching_tags:
                result_type = self._determine_type(matching_tags)
                
                return {
                    "success": True,
                    "result": result_type,
                    "tags": matching_tags,
                    "url": f"https://www.last.fm/music/{artist_name.replace(' ', '+')}",
                    "query_time_ms": query_time_ms
                }
            else:
                return {
                    "success": True,
                    "result": "human",
                    "tags": [],
                    "url": f"https://www.last.fm/music/{artist_name.replace(' ', '+')}",
                    "query_time_ms": query_time_ms
                }
        
        except Exception as e:
            logger.error(f"Last.fm classification failed for {artist_name}: {e}")
            return {
                "success": False,
                "result": None,
                "tags": [],
                "url": None,
                "query_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }
    
    async def _get_artist_tags(self, artist_name: str) -> list[Dict[str, Any]]:
        """Get top tags for artist.
        
        Args:
            artist_name: Artist name
            
        Returns:
            List of tag dicts with name and count
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.base_url,
                    params={
                        "method": "artist.getTopTags",
                        "artist": artist_name,
                        "api_key": self.api_key,
                        "format": "json"
                    },
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if "toptags" in data and "tag" in data["toptags"]:
                        tags = data["toptags"]["tag"]
                        
                        # Convert to list of dicts
                        return [
                            {
                                "name": tag["name"],
                                "count": int(tag["count"])
                            }
                            for tag in tags
                        ]
                
                return []
                
        except Exception as e:
            logger.error(f"Last.fm tag fetch failed: {e}")
            return []
    
    def _determine_type(self, tags: list[Dict[str, Any]]) -> str:
        """Determine classification type from tags.
        
        Args:
            tags: List of tag dicts
            
        Returns:
            Classification type string
        """
        tag_names = [tag["name"].lower() for tag in tags]
        
        if "vocaloid" in tag_names:
            return "vocaloid"
        elif "vtuber" in tag_names:
            return "vtuber"
        elif any(tag in tag_names for tag in ["virtual idol", "virtual singer"]):
            return "virtual_idol"
        elif "fictional" in tag_names:
            return "fictional"
        elif "ai generated" in tag_names:
            return "ai_generated"
        else:
            return "virtual"
