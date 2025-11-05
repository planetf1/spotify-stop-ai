"""Artist classification aggregator with multi-source agreement."""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import json

from .classifiers.wikidata import WikidataClassifier
from .classifiers.musicbrainz import MusicBrainzClassifier
from .classifiers.lastfm import LastFmClassifier

logger = logging.getLogger(__name__)


class ArtistClassifier:
    """Aggregate classification from multiple sources."""
    
    # Labels considered "artificial"
    ARTIFICIAL_LABELS = {
        "vocaloid", "vtuber", "virtual_idol", "virtual", "fictional",
        "ai_generated", "virtual_band"
    }
    
    def __init__(self, config: Dict[str, Any], database):
        """Initialize classifier with config.
        
        Args:
            config: Configuration dict
            database: Database instance
        """
        self.config = config
        self.db = database
        
        # Initialize classifiers
        self.classifiers: Dict[str, Any] = {}
        
        if config["sources"]["wikidata"]["enabled"]:
            self.classifiers["wikidata"] = WikidataClassifier(
                timeout=config["sources"]["wikidata"]["timeout_seconds"]
            )
        
        if config["sources"]["musicbrainz"]["enabled"]:
            self.classifiers["musicbrainz"] = MusicBrainzClassifier(
                user_agent=config["sources"]["musicbrainz"]["user_agent"],
                timeout=config["sources"]["musicbrainz"]["timeout_seconds"],
                rate_limit=config["sources"]["musicbrainz"]["rate_limit_per_second"]
            )
        
        if config["sources"]["lastfm"]["enabled"]:
            self.classifiers["lastfm"] = LastFmClassifier(
                api_key=config["sources"]["lastfm"]["api_key"],
                timeout=config["sources"]["lastfm"]["timeout_seconds"],
                min_tag_count=config["sources"]["lastfm"]["min_tag_count"]
            )
        
        self.min_source_agreement = config["classification"]["min_source_agreement"]
        self.band_policy = config["classification"]["band_policy"]["virtual_or_fictional_is_artificial"]
        self.cache_duration = config["classification"]["cache_duration_seconds"]
    
    async def classify_artist(self, artist_id: str, artist_name: str,
                             track_name: Optional[str] = None) -> Dict[str, Any]:
        """Classify artist as artificial or not.
        
        Args:
            artist_id: Spotify artist ID
            artist_name: Artist name
            track_name: Optional track name for context
            
        Returns:
            Classification decision dict
        """
        # Check for user override first
        override = await self.db.get_override(artist_id)
        if override:
            logger.info(f"Using override for artist {artist_name}: {override}")
            return {
                "decision_id": f"override_{artist_id}_{datetime.utcnow().isoformat()}",
                "artist_id": artist_id,
                "artist_name": artist_name,
                "label": "override",
                "is_artificial": bool(override["is_artificial"]),
                "confidence": 1.0,
                "sources_agreeing": 0,
                "min_required": self.min_source_agreement,
                "band_policy_applied": False,
                "llm_used": False,
                "decision_reason": f"User override: {override.get('reason', 'Manual classification')}",
                "sources": {},
                "llm_fallback": None,
                "cached_until": None
            }
        
        # Check cache
        cached = await self.db.get_cached_decision(artist_id)
        if cached:
            logger.info(f"Using cached decision for artist {artist_name}")
            return self._decision_from_db(cached)
        
        # Query all enabled sources
        logger.info(f"Classifying artist: {artist_name} (ID: {artist_id})")
        source_results = {}
        
        for source_name, classifier in self.classifiers.items():
            try:
                result = await classifier.classify(artist_name, artist_id)
                source_results[source_name] = result
                logger.debug(f"Source {source_name} result: {result}")
            except Exception as e:
                logger.error(f"Classifier {source_name} failed: {e}")
                source_results[source_name] = {
                    "success": False,
                    "error": str(e)
                }
        
        # Aggregate results
        decision = self._aggregate_sources(
            artist_id, artist_name, source_results
        )
        
        # Store decision in database
        await self._store_decision(decision)
        
        return decision
    
    def _aggregate_sources(self, artist_id: str, artist_name: str,
                          source_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate results from multiple sources.
        
        Args:
            artist_id: Spotify artist ID
            artist_name: Artist name
            source_results: Dict of source results
            
        Returns:
            Aggregated decision dict
        """
        # Count artificial signals
        artificial_votes = 0
        human_votes = 0
        successful_sources = 0
        labels_found = []
        
        for source_name, result in source_results.items():
            if not result.get("success"):
                continue
            
            successful_sources += 1
            result_label = result.get("result")
            
            if result_label in self.ARTIFICIAL_LABELS:
                artificial_votes += 1
                labels_found.append(result_label)
            elif result_label == "human" or result_label == "band":
                human_votes += 1
        
        # Determine decision
        is_artificial = None
        confidence = 0.0
        label = "unknown"
        band_policy_applied = False
        
        if artificial_votes >= self.min_source_agreement:
            # Enough sources agree it's artificial
            is_artificial = True
            confidence = min(1.0, artificial_votes / len(self.classifiers))
            label = labels_found[0] if labels_found else "artificial"
        elif self.band_policy and artificial_votes > 0 and human_votes == 0:
            # Band policy: any virtual/fictional signal = artificial
            is_artificial = True
            confidence = min(0.8, artificial_votes / len(self.classifiers))
            label = labels_found[0] if labels_found else "artificial"
            band_policy_applied = True
        elif human_votes >= self.min_source_agreement:
            # Enough sources agree it's human
            is_artificial = False
            confidence = min(1.0, human_votes / len(self.classifiers))
            label = "human"
        else:
            # Inconclusive
            is_artificial = None
            confidence = 0.0
            label = "unknown"
        
        # Build decision reason
        reason_parts = []
        if is_artificial is not None:
            if is_artificial:
                reason_parts.append(
                    f"Classified as artificial: {artificial_votes}/{successful_sources} "
                    f"sources agree. Labels: {', '.join(set(labels_found))}"
                )
            else:
                reason_parts.append(
                    f"Classified as human: {human_votes}/{successful_sources} sources agree"
                )
            
            if band_policy_applied:
                reason_parts.append("Band policy applied (any virtual/fictional = artificial)")
            
            reason_parts.append(f"Threshold: {self.min_source_agreement} sources required")
        else:
            reason_parts.append(
                f"Inconclusive: {artificial_votes} artificial, {human_votes} human "
                f"out of {successful_sources} successful sources. "
                f"Threshold: {self.min_source_agreement} required"
            )
        
        decision_reason = ". ".join(reason_parts)
        
        # Cache expiry
        cached_until = (
            datetime.utcnow() + timedelta(seconds=self.cache_duration)
        ).isoformat()
        
        return {
            "decision_id": f"decision_{artist_id}_{datetime.utcnow().isoformat()}",
            "artist_id": artist_id,
            "artist_name": artist_name,
            "label": label,
            "is_artificial": is_artificial,
            "confidence": confidence,
            "sources_agreeing": artificial_votes if is_artificial else human_votes,
            "min_required": self.min_source_agreement,
            "band_policy_applied": band_policy_applied,
            "llm_used": False,
            "decision_reason": decision_reason,
            "sources": source_results,
            "llm_fallback": None,
            "cached_until": cached_until
        }
    
    async def _store_decision(self, decision: Dict[str, Any]) -> None:
        """Store decision in database.
        
        Args:
            decision: Decision dict
        """
        try:
            # Insert decision record
            await self.db.insert_decision(
                decision_id=decision["decision_id"],
                artist_id=decision["artist_id"],
                label=decision["label"],
                is_artificial=decision["is_artificial"],
                confidence=decision["confidence"],
                sources_agreeing=decision["sources_agreeing"],
                min_required=decision["min_required"],
                band_policy_applied=decision["band_policy_applied"],
                llm_used=decision["llm_used"],
                decision_reason=decision["decision_reason"],
                cached_until=decision["cached_until"]
            )
            
            # Insert source results
            for source_name, result in decision["sources"].items():
                await self.db.insert_source_result(
                    decision_id=decision["decision_id"],
                    source_name=source_name,
                    success=result.get("success", False),
                    result=result.get("result"),
                    signals=json.dumps(result.get("signals", [])),
                    url=result.get("url"),
                    query_time_ms=result.get("query_time_ms", 0)
                )
            
            logger.info(f"Stored decision: {decision['decision_id']}")
            
        except Exception as e:
            logger.error(f"Failed to store decision: {e}")
    
    def _decision_from_db(self, db_record: Dict[str, Any]) -> Dict[str, Any]:
        """Convert database record to decision dict.
        
        Args:
            db_record: Database record dict
            
        Returns:
            Decision dict
        """
        return {
            "decision_id": db_record["id"],
            "artist_id": db_record["artist_id"],
            "artist_name": "",  # Not stored in decision table
            "label": db_record["label"],
            "is_artificial": bool(db_record["is_artificial"]) if db_record["is_artificial"] is not None else None,
            "confidence": db_record["confidence"],
            "sources_agreeing": db_record["sources_agreeing"],
            "min_required": db_record["min_required"],
            "band_policy_applied": bool(db_record["band_policy_applied"]),
            "llm_used": bool(db_record["llm_used"]),
            "decision_reason": db_record["decision_reason"],
            "sources": {},  # Would need to join with sources table
            "llm_fallback": None,
            "cached_until": db_record["cached_until"]
        }
