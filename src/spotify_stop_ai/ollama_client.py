"""Ollama LLM client for artist classification fallback."""

import logging
from typing import Dict, Any, Optional, List
import httpx
import json
import time
from ddgs import DDGS

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client for Ollama local LLM classification."""

    def __init__(self, config: Dict[str, Any], prompt_template_path: str):
        """Initialize Ollama client.

        Args:
            config: Ollama configuration dict
            prompt_template_path: Path to prompt template file
        """
        self.enabled = config.get("enabled", False)
        self.host = config.get("host", "http://127.0.0.1:11434")
        self.model = config.get("model", "granite4:tiny-h")
        self.keep_alive = config.get("keep_alive", "5m")
        self.options = config.get(
            "options", {"temperature": 0.0, "seed": 42, "num_predict": 128}
        )
        self.timeout_ms = config.get("timeout_ms", 8000)
        self.require_citations = config.get("require_citations", True)

        # Load prompt template
        try:
            with open(prompt_template_path, "r") as f:
                self.prompt_template = f.read()
            logger.info("Loaded prompt template from %s", prompt_template_path)
        except Exception as e:
            logger.warning("Failed to load prompt template: %s", e)
            self.prompt_template = self._default_prompt_template()
            logger.info("Using default prompt template")

    async def classify(
        self, artist_name: str, evidence: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Classify artist using LLM fallback with web search.

        Args:
            artist_name: Artist name
            evidence: Dict of evidence from data sources

        Returns:
            Classification result dict or None if disabled/failed
        """
        if not self.enabled:
            logger.debug("LLM classification skipped - disabled in config")
            return None

        logger.info("Starting LLM classification for artist: %s", artist_name)
        start_time = time.time()

        try:
            # Perform web search for additional context (optional - LLM can work without it)
            search_results = await self._web_search(artist_name)
            if not search_results:
                logger.info("No web search results, proceeding with source data only")

            # Build evidence string with or without web search results
            evidence_str = self._format_evidence(artist_name, evidence, search_results)

            # Build prompt - use replace() to avoid issues with curly braces in evidence
            prompt = self.prompt_template.replace("{evidence}", evidence_str)

            # Call Ollama API
            result = await self._generate(prompt)

            if not result:
                return None

            # Parse JSON output
            raw_response = result.get("response", "")
            response_text = ""
            try:
                logger.info(
                    "Raw LLM response (first 500 chars): %s", raw_response[:500]
                )

                # Strip markdown code blocks if present
                response_text = raw_response.strip()
                if response_text.startswith("```json"):
                    response_text = response_text[7:]  # Remove ```json
                elif response_text.startswith("```"):
                    response_text = response_text[3:]  # Remove ```
                if response_text.endswith("```"):
                    response_text = response_text[:-3]  # Remove closing ```
                response_text = response_text.strip()

                logger.info(
                    "After stripping markdown (first 500 chars): %s",
                    response_text[:500],
                )

                # Attempt to parse JSON
                logger.debug("Attempting JSON parse of: %s", response_text[:300])
                output = json.loads(response_text)
                logger.info("✓ JSON parse successful for artist classification")

            except json.JSONDecodeError as e:
                logger.error("✗ Failed to parse LLM JSON output: %s", e)
                logger.error("Raw response was: %s", raw_response[:2000])
                logger.error("After stripping: %s", response_text[:2000])
                logger.error("Error position: %s", str(e))
                return None

            # Validate output
            if not self._validate_output(output):
                logger.warning("✗ LLM output failed validation")
                logger.warning("Output was: %s", json.dumps(output, indent=2)[:500])
                return None

            logger.info("✓ LLM output validated successfully")

            # Calculate durations
            load_duration_ms = result.get("load_duration", 0) // 1_000_000
            eval_duration_ms = result.get("eval_duration", 0) // 1_000_000
            total_duration_ms = result.get("total_duration", 0) // 1_000_000

            return {
                "model": self.model,
                "output": output,
                "prompt": prompt,
                "load_duration_ms": load_duration_ms,
                "eval_duration_ms": eval_duration_ms,
                "total_duration_ms": total_duration_ms,
                "query_time_ms": int((time.time() - start_time) * 1000),
            }

        except Exception as e:  # pylint: disable=broad-except
            logger.error("Ollama classification failed: %s", e)
            import traceback

            logger.error("Traceback: %s", traceback.format_exc())
            return None

    async def _generate(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Call Ollama generate API.

        Args:
            prompt: Prompt text

        Returns:
            Response dict or None
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.host}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": self.options,
                        "keep_alive": self.keep_alive,
                    },
                    timeout=self.timeout_ms / 1000.0,
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(
                        "Ollama API error: %s %s", response.status_code, response.text
                    )
                    return None

        except Exception as e:
            import traceback

            logger.error("Ollama API request failed: %s", str(e))
            logger.error("Traceback: %s", traceback.format_exc())
            return None

    async def _web_search(self, artist_name: str) -> List[Dict[str, Any]]:
        """Perform web search for artist information.

        Args:
            artist_name: Artist name to search

        Returns:
            List of search results
        """
        try:
            # Search for artist + AI/virtual/vocaloid keywords
            queries = [
                f"{artist_name} AI generated music",
                f"{artist_name} virtual artist vocaloid",
                f"{artist_name} artist biography",
            ]

            all_results = []
            with DDGS() as ddgs:
                for query in queries:
                    try:
                        results = list(ddgs.text(query, max_results=3))
                        logger.info(
                            "Query '%s' returned %d results", query, len(results)
                        )
                        if results:
                            logger.debug(
                                "First result keys: %s",
                                list(results[0].keys()) if results else "none",
                            )
                        all_results.extend(results)
                    except Exception as e:  # pylint: disable=broad-except
                        logger.warning(
                            "DuckDuckGo search failed for '%s': %s", query, e
                        )
                        continue

            logger.info(f"Total raw results before dedup: {len(all_results)}")

            # Deduplicate by URL
            seen_urls = set()
            unique_results = []
            for idx, result in enumerate(all_results):
                # Log first few results to debug
                if idx < 3:
                    logger.info(
                        f"Result {idx}: keys={list(result.keys())}, has href={('href' in result)}, has link={('link' in result)}"
                    )

                url = result.get("href", result.get("link", ""))
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_results.append(result)
                elif not url:
                    logger.warning(
                        f"Result {idx} has no URL (keys: {list(result.keys())})"
                    )

            logger.info(
                "Web search for '%s' returned %d unique results",
                artist_name,
                len(unique_results),
            )
            return unique_results[:5]  # Limit to top 5

        except Exception as e:  # pylint: disable=broad-except
            logger.error("Web search failed: %s", e)
            return []

    def _format_evidence(
        self,
        artist_name: str,
        evidence: Dict[str, Any],
        search_results: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Format evidence for prompt.

        Args:
            artist_name: Artist name
            evidence: Evidence dict from data sources
            search_results: Web search results

        Returns:
            Formatted evidence string
        """
        lines = [f"Artist: {artist_name}\n"]

        # Add Spotify metadata first if available (most important for ghost artist detection)
        if "spotify" in evidence and evidence["spotify"].get("success"):
            spotify_data = evidence["spotify"].get("metadata", {})
            lines.append("\n🎵 SPOTIFY METADATA (KEY FOR GHOST ARTIST DETECTION):")
            lines.append(f"  Followers: {spotify_data.get('followers', 0):,}")
            lines.append(f"  Popularity: {spotify_data.get('popularity', 0)}/100")
            lines.append(
                f"  Genres: {', '.join(spotify_data.get('genres', [])) or 'None listed'}"
            )
            lines.append(
                f"  Total Albums/Singles: {spotify_data.get('albums_count', 0)}"
            )

            if "release_pattern" in spotify_data:
                rp = spotify_data["release_pattern"]
                lines.append(f"  📊 RELEASE PATTERN ANALYSIS:")
                lines.append(
                    f"     - Recent releases (last 3 years): {rp.get('recent_releases_last_3_years', 0)}"
                )
                lines.append(
                    f"     - Average per year (recent): {rp.get('avg_per_recent_year', 0)}"
                )
                if rp.get("releases_by_year"):
                    lines.append(f"     - By year: {rp['releases_by_year']}")

            if spotify_data.get("related_artists"):
                lines.append(
                    f"  🔗 Related Artists: {', '.join(spotify_data['related_artists'][:5])}"
                )

            lines.append("")
            lines.append("  ⚠️ GHOST ARTIST CHECK:")
            # Calculate red flags
            red_flags = []
            rp = spotify_data.get("release_pattern", {})
            recent = rp.get("recent_releases_last_3_years", 0)
            followers = spotify_data.get("followers", 0)
            popularity = spotify_data.get("popularity", 0)

            if recent >= 15:
                red_flags.append(f"🚩 EXTREME release volume: {recent} in 3 years")
            if followers < 5000 and recent > 10:
                red_flags.append(
                    f"🚩 LOW engagement: {followers:,} followers with {recent} releases"
                )
            if popularity < 30 and recent > 10:
                red_flags.append(
                    f"🚩 LOW popularity: {popularity}/100 despite {recent} releases"
                )
            if not spotify_data.get("genres"):
                red_flags.append("🚩 NO genres listed (typical for ghost projects)")

            if red_flags:
                for flag in red_flags:
                    lines.append(f"     {flag}")
                lines.append(f"     ⚠️ TOTAL RED FLAGS: {len(red_flags)}")
                if len(red_flags) >= 3:
                    lines.append("     🚨 HIGH CONFIDENCE: Likely AI Ghost Project")
            else:
                lines.append("     ✓ No ghost project red flags detected")

        # Add data source evidence
        for source_name, result in evidence.items():
            if source_name == "spotify":  # Already handled above
                continue
            if not result.get("success"):
                continue

            lines.append(f"\n{source_name.upper()} Source:")

            # Safely get result value
            result_value = result.get("result", "N/A")
            # Handle case where result might be JSON string
            if isinstance(result_value, str) and (
                result_value.startswith("{") or result_value.startswith("[")
            ):
                try:
                    result_value = json.loads(result_value)
                except:
                    pass  # Keep as string if parse fails

            lines.append(f"  Result: {result_value}")

            if "signals" in result and result["signals"]:
                lines.append(f"  Signals: {', '.join(map(str, result['signals']))}")

            if "tags" in result and result["tags"]:
                if isinstance(result["tags"], list):
                    if result["tags"] and isinstance(result["tags"][0], dict):
                        tag_strs = [
                            f"{t['name']} (count: {t['count']})"
                            for t in result["tags"][:5]
                        ]
                    else:
                        tag_strs = result["tags"][:5]
                    lines.append(f"  Tags: {', '.join(tag_strs)}")

            if "url" in result and result["url"]:
                lines.append(f"  URL: {result['url']}")

        # Add web search results
        if search_results:
            lines.append("\n\nWEB SEARCH RESULTS:")
            for idx, result in enumerate(search_results, 1):
                title = result.get("title", "N/A")
                body = result.get("body", result.get("snippet", "N/A"))
                url = result.get("href", result.get("link", "N/A"))

                lines.append(f"\n  [{idx}] {title}")
                lines.append(f"      {body[:200]}...")  # Truncate snippet
                lines.append(f"      URL: {url}")

        return "\n".join(lines)

    def _validate_output(self, output: Dict[str, Any]) -> bool:
        """Validate LLM output structure.

        Args:
            output: Parsed JSON output

        Returns:
            True if valid
        """
        # Core required fields
        required_fields = [
            "label",
            "is_artificial",
            "confidence",
            "reason",
        ]

        for field in required_fields:
            if field not in output:
                logger.warning("LLM output missing required field: %s", field)
                return False

        # Validate types
        if not isinstance(output["label"], str):
            logger.warning(
                "LLM output 'label' is not a string: %s", type(output["label"])
            )
            return False

        if not isinstance(output["is_artificial"], (bool, type(None))):
            logger.warning(
                "LLM output 'is_artificial' is not bool/null: %s",
                type(output["is_artificial"]),
            )
            return False

        if not isinstance(output["confidence"], (int, float)):
            logger.warning(
                "LLM output 'confidence' is not numeric: %s", type(output["confidence"])
            )
            return False

        # Validate confidence is in valid range
        if not (0.0 <= output["confidence"] <= 1.0):
            logger.warning(
                "LLM output 'confidence' out of range: %s", output["confidence"]
            )
            return False

        # Citations are optional but if present must be a list
        if "citations" in output and not isinstance(output["citations"], list):
            logger.warning(
                "LLM output 'citations' is not a list: %s", type(output["citations"])
            )
            return False

        # Check citations if required
        if self.require_citations and (not output.get("citations")):
            logger.warning("LLM output missing required citations")
            return False

        return True

    def _default_prompt_template(self) -> str:
        """Default prompt template if file not found.

        Returns:
            Default prompt template string
        """
        return """You are a music expert assistant helping classify whether an artist is AI-generated, virtual, or uses voice synthesis.

**Task:** Analyze the provided evidence and determine if the artist should be classified as "artificial" (includes virtual idols, VTubers, Vocaloid characters, AI-generated artists, voice synthesis, fictional bands, or any non-human performers).

**Evidence provided:**
{evidence}

**Instructions:**
1. Read the evidence carefully from the sources provided
2. Look for clear indicators of artificial/virtual/fictional nature
3. Only use information from the provided evidence—do not use external knowledge
4. Return your decision in valid JSON format with the exact schema below
5. Include citations (URLs) from the provided evidence only
6. Be conservative: if evidence is ambiguous or contradictory, return "unknown"

**Response format (strict JSON):**
{{
  "label": "virtual_idol|vocaloid|vtuber|fictional|ai_generated|human|band|unknown",
  "is_artificial": true|false|null,
  "confidence": 0.0-1.0,
  "reason": "brief explanation citing specific evidence",
  "citations": ["url1", "url2"],
  "ambiguity_notes": "any contradictions or uncertainty"
}}

**Important:**
- is_artificial should be true for: virtual_idol, vocaloid, vtuber, fictional, ai_generated
- is_artificial should be false for: human, band
- If you cannot determine with confidence ≥0.6, use label "unknown" and is_artificial: null
"""
