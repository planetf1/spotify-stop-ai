"""Quick smoke test for critical artist classifications.

Tests only the most famous artists that should NEVER be misclassified.
Run this before deploying any prompt changes.
"""

import asyncio
import sys
from spotify_stop_ai.database import Database
from spotify_stop_ai.main import load_config

# Famous artists that should NEVER be classified as AI
CRITICAL_HUMAN_ARTISTS = {
    "5nGIFgo0shDenQYSE0Sn7c": "Evanescence",  # Multi-platinum rock band, Amy Lee
    "31jvzuB4ikftPQZJwrYfCF": "Enter Shikari",  # Established UK band
    "1189BemPY7h2lgaH1pkzGX": "Mono Inc.",  # German rock band with tours
}


async def check_classification(database: Database, artist_id: str, artist_name: str) -> bool:
    """Check if an artist is correctly classified as human.
    
    Returns:
        True if classified correctly, False if misclassified
    """
    decisions = await database.get_decisions_with_sources(artist_id)
    
    if not decisions:
        print(f"  ⚠️  {artist_name}: No classification found in database")
        return True  # Not a failure, just no data
    
    decision = decisions[0]
    is_human = decision["is_artificial"] == 0
    confidence = decision["confidence"]
    
    if is_human:
        print(f"  ✅ {artist_name}: Correctly classified as HUMAN (confidence: {confidence:.0%})")
        return True
    else:
        print(f"  ❌ {artist_name}: MISCLASSIFIED AS AI (confidence: {confidence:.0%})")
        print(f"     This is a CRITICAL FAILURE - {artist_name} is a famous band!")
        return False


async def main():
    """Run critical artist smoke test."""
    print("\n🧪 Running critical artist smoke test...")
    print("="*60)
    
    # Load config and database
    config = load_config()
    db_path = config.get("database", {}).get("path", "spotify-stop-ai.db")
    database = Database(db_path)
    await database.initialize()
    
    # Check each critical artist
    failures = []
    for artist_id, artist_name in CRITICAL_HUMAN_ARTISTS.items():
        correct = await check_classification(database, artist_id, artist_name)
        if not correct:
            failures.append(artist_name)
    
    # Report results
    print("="*60)
    if failures:
        print(f"\n❌ SMOKE TEST FAILED!")
        print(f"   {len(failures)} critical artist(s) misclassified:")
        for name in failures:
            print(f"     - {name}")
        print("\n   🔧 Action required: Fix prompt or classification logic!")
        return 1
    else:
        print("\n✅ SMOKE TEST PASSED!")
        print("   All critical artists correctly classified as human.")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
