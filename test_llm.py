#!/usr/bin/env python3
"""Test LLM classification."""

import asyncio
import logging
from src.spotify_stop_ai.ollama_client import OllamaClient

# Set up logging
logging.basicConfig(level=logging.DEBUG)


async def test_llm():
    """Test LLM classification."""
    config = {
        "enabled": True,
        "host": "http://127.0.0.1:11434",
        "model": "granite4:tiny-h",
        "keep_alive": "5m",
        "options": {"temperature": 0.0, "seed": 42, "num_predict": 128},
        "timeout_ms": 8000,
        "require_citations": False,  # Set to False to make testing easier
    }

    client = OllamaClient(
        config, "/Users/jonesn/src/spotify-stop-ai/prompts/classify_artist.txt"
    )

    # Test with a simple artist
    evidence = {
        "wikidata": {
            "success": True,
            "result": "human",
            "tags": [],
            "url": "https://www.wikidata.org/wiki/Q12345",
        },
        "musicbrainz": {
            "success": False,
            "result": None,
            "url": None,
        },
        "lastfm": {
            "success": True,
            "result": "human",
            "tags": ["rock", "alternative"],
            "url": "https://www.last.fm/music/Test+Artist",
        },
    }

    result = await client.classify("Test Artist", evidence)
    print("Result:", result)


if __name__ == "__main__":
    asyncio.run(test_llm())
