"""Ollama LLM client for artist classification fallback."""
import logging
from typing import Dict, Any, Optional, List
import httpx
import json
import time
from duckduckgo_search import DDGS

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
        self.options = config.get("options", {
            "temperature": 0.0,
            "seed": 42,
            "num_predict": 128
        })
        self.timeout_ms = config.get("timeout_ms", 8000)
        self.require_citations = config.get("require_citations", True)
        
        # Load prompt template
        try:
            with open(prompt_template_path, 'r') as f:
                self.prompt_template = f.read()
            logger.info("Loaded prompt template from %s", prompt_template_path)
        except Exception as e:
            logger.warning("Failed to load prompt template: %s", e)
            self.prompt_template = self._default_prompt_template()
            logger.info("Using default prompt template")
    
    async def classify(self, artist_name: str, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
            # Perform web search for additional context
            search_results = await self._web_search(artist_name)
            
            # Build evidence string with web search results
            evidence_str = self._format_evidence(artist_name, evidence, search_results)
            
            # Build prompt
            prompt = self.prompt_template.format(evidence=evidence_str)
            
            # Call Ollama API
            result = await self._generate(prompt)
            
            if not result:
                return None
            
            # Parse JSON output
            try:
                raw_response = result["response"]
                logger.debug("Raw LLM response: %s", raw_response[:500])  # Log first 500 chars
                
                # Strip markdown code blocks if present
                response_text = raw_response.strip()
                if response_text.startswith("```json"):
                    response_text = response_text[7:]  # Remove ```json
                elif response_text.startswith("```"):
                    response_text = response_text[3:]  # Remove ```
                if response_text.endswith("```"):
                    response_text = response_text[:-3]  # Remove closing ```
                response_text = response_text.strip()
                
                output = json.loads(response_text)
            except json.JSONDecodeError as e:
                logger.error("Failed to parse LLM JSON output: %s", e)
                logger.error("Raw response was: %s", result.get('response', 'N/A')[:1000])
                return None
            except Exception as e:  # pylint: disable=broad-except
                logger.error("Error processing LLM response: %s", e)
                return None
            
            # Validate output
            if not self._validate_output(output):
                logger.warning("LLM output failed validation")
                return None
            
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
                "query_time_ms": int((time.time() - start_time) * 1000)
            }
        
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Ollama classification failed: %s", e)
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
                        "keep_alive": self.keep_alive
                    },
                    timeout=self.timeout_ms / 1000.0
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error("Ollama API error: %s %s", response.status_code, response.text)
                    return None
        
        except Exception as e:
            logger.error("Ollama API request failed: %s", e)
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
                f"{artist_name} artist biography"
            ]
            
            all_results = []
            with DDGS() as ddgs:
                for query in queries:
                    try:
                        results = list(ddgs.text(query, max_results=3))
                        logger.debug("Query '%s' returned %d results", query, len(results))
                        all_results.extend(results)
                    except Exception as e:  # pylint: disable=broad-except
                        logger.warning("DuckDuckGo search failed for '%s': %s", query, e)
                        continue
            
            # Deduplicate by URL
            seen_urls = set()
            unique_results = []
            for result in all_results:
                url = result.get('href', result.get('link', ''))
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_results.append(result)
            
            logger.info("Web search for '%s' returned %d unique results", artist_name, len(unique_results))
            return unique_results[:5]  # Limit to top 5
            
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Web search failed: %s", e)
            return []
    
    def _format_evidence(self, artist_name: str, evidence: Dict[str, Any], 
                        search_results: Optional[List[Dict[str, Any]]] = None) -> str:
        """Format evidence for prompt.
        
        Args:
            artist_name: Artist name
            evidence: Evidence dict from data sources
            search_results: Web search results
            
        Returns:
            Formatted evidence string
        """
        lines = [f"Artist: {artist_name}\n"]
        
        # Add data source evidence
        for source_name, result in evidence.items():
            if not result.get("success"):
                continue
            
            lines.append(f"\n{source_name.upper()} Source:")
            lines.append(f"  Result: {result.get('result', 'N/A')}")
            
            if "signals" in result and result["signals"]:
                lines.append(f"  Signals: {', '.join(map(str, result['signals']))}")
            
            if "tags" in result and result["tags"]:
                if isinstance(result["tags"], list):
                    if result["tags"] and isinstance(result["tags"][0], dict):
                        tag_strs = [f"{t['name']} (count: {t['count']})" for t in result["tags"][:5]]
                    else:
                        tag_strs = result["tags"][:5]
                    lines.append(f"  Tags: {', '.join(tag_strs)}")
            
            if "url" in result and result["url"]:
                lines.append(f"  URL: {result['url']}")
        
        # Add web search results
        if search_results:
            lines.append("\n\nWEB SEARCH RESULTS:")
            for idx, result in enumerate(search_results, 1):
                title = result.get('title', 'N/A')
                body = result.get('body', result.get('snippet', 'N/A'))
                url = result.get('href', result.get('link', 'N/A'))
                
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
        required_fields = ["label", "is_artificial", "confidence", "reason", "citations"]
        
        for field in required_fields:
            if field not in output:
                logger.warning("LLM output missing required field: %s", field)
                return False
        
        # Validate types
        if not isinstance(output["label"], str):
            return False
        
        if not isinstance(output["is_artificial"], (bool, type(None))):
            return False
        
        if not isinstance(output["confidence"], (int, float)):
            return False
        
        if not isinstance(output["citations"], list):
            return False
        
        # Check citations if required
        if self.require_citations and not output["citations"]:
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
