"""Wikidata SPARQL classifier for detecting virtual/AI artists."""
import logging
from typing import Optional, Dict, Any
from SPARQLWrapper import SPARQLWrapper, JSON
import time

logger = logging.getLogger(__name__)


class WikidataClassifier:
    """Classify artists using Wikidata SPARQL queries."""
    
    # Wikidata QIDs for virtual/AI/fictional entities
    VIRTUAL_QIDS = {
        "Q55155641": "vtuber",
        "Q24236999": "virtual_idol",
        "Q125130106": "vocaloid",
        "Q3736859": "virtual_band",
        "Q4167410": "disambiguation"  # To exclude
    }
    
    def __init__(self, timeout: int = 10):
        """Initialize Wikidata classifier.
        
        Args:
            timeout: Query timeout in seconds
        """
        self.endpoint = "https://query.wikidata.org/sparql"
        self.timeout = timeout
        self.sparql = SPARQLWrapper(self.endpoint)
        self.sparql.setReturnFormat(JSON)
    
    async def classify(self, artist_name: str, artist_id: str) -> Dict[str, Any]:
        """Classify artist using Wikidata.
        
        Args:
            artist_name: Artist name to search
            artist_id: Spotify artist ID (for logging)
            
        Returns:
            Classification result dict
        """
        start_time = time.time()
        
        try:
            # Search for artist entity
            entity_id = await self._find_entity(artist_name)
            
            if not entity_id:
                return {
                    "success": False,
                    "result": None,
                    "signals": [],
                    "url": None,
                    "query_time_ms": int((time.time() - start_time) * 1000),
                    "error": "Entity not found"
                }
            
            # Check if entity matches virtual/AI criteria
            result = await self._check_virtual_properties(entity_id)
            
            query_time_ms = int((time.time() - start_time) * 1000)
            
            if result:
                return {
                    "success": True,
                    "result": result["type"],
                    "signals": result["signals"],
                    "url": f"https://www.wikidata.org/wiki/{entity_id}",
                    "query_time_ms": query_time_ms
                }
            else:
                return {
                    "success": True,
                    "result": "human",  # Default to human if no virtual signals
                    "signals": [],
                    "url": f"https://www.wikidata.org/wiki/{entity_id}",
                    "query_time_ms": query_time_ms
                }
        
        except Exception as e:
            logger.error(f"Wikidata classification failed for {artist_name}: {e}")
            return {
                "success": False,
                "result": None,
                "signals": [],
                "url": None,
                "query_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }
    
    async def _find_entity(self, artist_name: str) -> Optional[str]:
        """Find Wikidata entity ID for artist.
        
        Args:
            artist_name: Artist name to search
            
        Returns:
            Entity ID (Q-number) or None
        """
        # Escape quotes in artist name for SPARQL
        escaped_name = artist_name.replace('"', '\\"')
        
        query = f"""
        SELECT ?item WHERE {{
          {{
            ?item rdfs:label "{escaped_name}"@en .
            ?item wdt:P31/wdt:P279* wd:Q5 .  # Human or subclass
            FILTER NOT EXISTS {{ ?item wdt:P31 wd:Q4167410 }}  # Exclude disambiguation
          }}
          UNION
          {{
            ?item rdfs:label "{escaped_name}"@en .
            ?item wdt:P31/wdt:P279* wd:Q215380 .  # Musical group or subclass
            FILTER NOT EXISTS {{ ?item wdt:P31 wd:Q4167410 }}
          }}
          UNION
          {{
            ?item rdfs:label "{escaped_name}"@en .
            ?item wdt:P106 ?occupation .
            FILTER NOT EXISTS {{ ?item wdt:P31 wd:Q4167410 }}
          }}
        }}
        LIMIT 1
        """
        
        try:
            self.sparql.setQuery(query)
            self.sparql.setTimeout(self.timeout)
            results = self.sparql.query().convert()
            
            if results["results"]["bindings"]:
                entity_uri = results["results"]["bindings"][0]["item"]["value"]
                entity_id = entity_uri.split("/")[-1]
                return entity_id
            
            return None
            
        except Exception as e:
            logger.error(f"Wikidata entity search failed: {e}")
            return None
    
    async def _check_virtual_properties(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Check if entity has virtual/AI properties.
        
        Args:
            entity_id: Wikidata entity ID (Q-number)
            
        Returns:
            Dict with type and signals, or None if not virtual
        """
        query = f"""
        SELECT ?class ?classLabel WHERE {{
          wd:{entity_id} (wdt:P31|wdt:P106)/wdt:P279* ?class .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }}
        """
        
        try:
            self.sparql.setQuery(query)
            self.sparql.setTimeout(self.timeout)
            results = self.sparql.query().convert()
            
            signals = []
            result_type = None
            
            for binding in results["results"]["bindings"]:
                class_uri = binding["class"]["value"]
                class_id = class_uri.split("/")[-1]
                
                if class_id in self.VIRTUAL_QIDS:
                    if class_id == "Q4167410":  # Disambiguation page
                        continue
                    
                    signals.append(class_id)
                    if not result_type:
                        result_type = self.VIRTUAL_QIDS[class_id]
            
            if signals:
                return {
                    "type": result_type,
                    "signals": signals
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Wikidata property check failed: {e}")
            return None
