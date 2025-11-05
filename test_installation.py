#!/usr/bin/env python3
"""Test script to validate Spotify Stop AI installation and configuration."""
import asyncio
import sys
from pathlib import Path

# Test imports
print("Testing imports...")
try:
    from spotify_stop_ai.main import load_config
    from spotify_stop_ai.database import Database
    from spotify_stop_ai.classifier import ArtistClassifier
    from spotify_stop_ai.monitor import PlaybackMonitor
    from spotify_stop_ai.spotify_client import SpotifyClient
    from spotify_stop_ai.ollama_client import OllamaClient
    from spotify_stop_ai.api import app
    from spotify_stop_ai.classifiers.wikidata import WikidataClassifier
    from spotify_stop_ai.classifiers.musicbrainz import MusicBrainzClassifier
    from spotify_stop_ai.classifiers.lastfm import LastFmClassifier
    print("✓ All modules import successfully")
except ImportError as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)

# Test configuration
print("\nTesting configuration...")
try:
    config = load_config()
    print("✓ Config loads successfully")
    
    # Verify key settings
    assert config["monitor"]["poll_interval_seconds"] == 2, "Poll interval should be 2"
    assert config["classification"]["min_source_agreement"] == 2, "Min source agreement should be 2"
    assert config["actions"]["auto_skip"] is True, "Auto skip should be enabled"
    assert config["ollama"]["enabled"] is False, "Ollama should be disabled by default"
    assert config["ollama"]["model"] == "granite4:tiny-h", "Ollama model should be granite4:tiny-h"
    assert config["classification"]["band_policy"]["virtual_or_fictional_is_artificial"] is True
    print("✓ All configuration settings correct")
    
except Exception as e:
    print(f"✗ Configuration error: {e}")
    sys.exit(1)

# Test database
print("\nTesting database...")
async def test_database():
    try:
        db = Database('data/test_validation.db')
        await db.initialize()
        print("✓ Database schema created successfully")
        
        # Test basic operations
        await db.upsert_artist('test_artist', 'Test Artist', 'spotify:artist:test')
        print("✓ Can upsert artists")
        
        await db.set_override('test_artist', True, 'Test override')
        override = await db.get_override('test_artist')
        assert override is not None, "Override should be set"
        assert override['is_artificial'] == 1, "Override should be artificial (SQLite returns 1 for True)"
        print("✓ Can set and get overrides")
        
        await db.delete_override('test_artist')
        override = await db.get_override('test_artist')
        assert override is None, "Override should be deleted"
        print("✓ Can delete overrides")
        
        # Clean up
        Path('data/test_validation.db').unlink(missing_ok=True)
        
    except Exception as e:
        print(f"✗ Database error: {e}")
        sys.exit(1)

asyncio.run(test_database())

# Test classifiers (without actual API calls)
print("\nTesting classifier initialization...")
try:
    wikidata = WikidataClassifier(timeout=10)
    print("✓ WikidataClassifier initializes")
    
    musicbrainz = MusicBrainzClassifier(
        user_agent="test/1.0",
        rate_limit=1.0,
        timeout=10
    )
    print("✓ MusicBrainzClassifier initializes")
    
    lastfm = LastFmClassifier(
        api_key="test_key",
        min_tag_count=5,
        timeout=10
    )
    print("✓ LastFmClassifier initializes")
    
    # OllamaClient requires a prompt template path, skip for now
    print("✓ OllamaClient skipped (requires prompt template)")
    
except Exception as e:
    print(f"✗ Classifier initialization error: {e}")
    sys.exit(1)

# Verify example files exist
print("\nVerifying example files...")
required_files = [
    "config.example.yaml",
    ".env.example",
    "examples/logged_play.json",
    "examples/decision_record.json",
    "examples/com.spotify-stop-ai.guard.plist",
    "README.md"
]

for file in required_files:
    if Path(file).exists():
        print(f"✓ {file} exists")
    else:
        print(f"✗ {file} missing")
        sys.exit(1)

# Summary
print("\n" + "="*60)
print("✓ All validation tests passed!")
print("="*60)
print("\nNext steps:")
print("1. Set SPOTIFY_CLIENT_ID in .env (get from https://developer.spotify.com/dashboard)")
print("2. Set LASTFM_API_KEY in .env (optional, get from https://www.last.fm/api/account/create)")
print("3. Optional: Install Ollama and run: ollama pull granite4:tiny-h")
print("4. Start the service: python -m spotify_stop_ai.main")
print("5. Review API at: http://127.0.0.1:8889/docs")
print("\nFor background autostart, see: examples/com.spotify-stop-ai.guard.plist")
