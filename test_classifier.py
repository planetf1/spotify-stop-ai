"""Automated tests for artist classifier with known ground truth examples."""

import asyncio
import logging
from typing import Dict, List, Tuple
from spotify_stop_ai.database import Database
from spotify_stop_ai.classifier import ArtistClassifier
from spotify_stop_ai.main import load_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Ground truth test cases
KNOWN_HUMAN_ARTISTS = {
    # Major established artists - should NEVER be classified as AI
    "5nGIFgo0shDenQYSE0Sn7c": "Evanescence",  # Famous rock band, extensive touring
    "31jvzuB4ikftPQZJwrYfCF": "Enter Shikari",  # Well-known UK band
    "1189BemPY7h2lgaH1pkzGX": "Mono Inc.",  # German rock band
    "3gjygQY5Q2P3b5F1ZIP0Dj": "BLACKBOOK",  # Real band (if confirmed)
    "7lAi1Cv19DsukgGjbZQxFg": "Annisokay",  # German metalcore band
    "6niO7WSbw5n0nD58jPi2Mx": "Priest",  # Swedish heavy metal
    # Add more known human artists here
}

KNOWN_AI_ARTISTS = {
    # Confirmed AI ghost projects
    "6eSbN6VGT0gaEibTe82iJT": "HIMITZU",  # AI-generated, low engagement
    "1aTnr4XWyegVTZf7kwjnot": "Added Color",  # Ghost project pattern
    "0O0PiBo2EwJiL2x1k13J7E": "Sammy Boller",  # Extreme release volume, low followers
    "7y25aQ8W1jYhdkTdDdiUjH": "KARAVIRS",  # 15 releases in 3 years, <5k followers
    # Add more confirmed AI artists here
}

UNCERTAIN_ARTISTS = {
    # Cases where classification is genuinely difficult
    "4PRHkf31ZSxZ5tbYe8xMZm": "Major Moment",  # Has tour dates but suspicious patterns
    "1uS4cYRRZRtauASIM9RxBG": "Mesh",  # Ambiguous signals
}


class ClassifierEvaluator:
    """Evaluate classifier performance on ground truth test cases."""
    
    def __init__(self, database: Database, classifier: ArtistClassifier):
        self.database = database
        self.classifier = classifier
        
    async def evaluate_artist(self, artist_id: str, expected_human: bool) -> Dict:
        """Evaluate a single artist classification.
        
        Args:
            artist_id: Spotify artist ID
            expected_human: True if human, False if AI
            
        Returns:
            Dictionary with evaluation results
        """
        try:
            # Get or create classification
            artist = await self.database.get_artist(artist_id)
            if not artist:
                logger.warning(f"Artist {artist_id} not in database, need to fetch from Spotify first")
                return {
                    "artist_id": artist_id,
                    "status": "not_found",
                    "error": "Artist not in database"
                }
            
            decisions = await self.database.get_decisions_with_sources(artist_id)
            
            if not decisions:
                logger.info(f"No decision found for {artist['name']}, classifying now...")
                decision = await self.classifier.classify_artist(artist_id, force_refresh=True)
            else:
                decision = decisions[0]
                
            # Evaluate result
            is_human = decision["is_artificial"] == 0
            correct = (is_human == expected_human)
            confidence = decision["confidence"]
            
            # Check LLM vote specifically
            llm_vote = None
            if decision.get("llm_result"):
                llm_vote = decision["llm_result"].get("is_artificial")
            
            return {
                "artist_id": artist_id,
                "artist_name": decision.get("artist_name", "Unknown"),
                "expected_human": expected_human,
                "classified_human": is_human,
                "correct": correct,
                "confidence": confidence,
                "llm_vote": "human" if llm_vote == False else ("ai" if llm_vote == True else "none"),
                "llm_correct": (llm_vote == False) == expected_human if llm_vote is not None else None,
                "sources_agreeing": decision.get("sources_agreeing", 0),
                "decision_reason": decision.get("decision_reason", "")[:200]
            }
            
        except Exception as e:
            logger.error(f"Error evaluating {artist_id}: {e}")
            return {
                "artist_id": artist_id,
                "status": "error",
                "error": str(e)
            }
    
    async def run_evaluation(self) -> Dict:
        """Run full evaluation on all test cases.
        
        Returns:
            Dictionary with evaluation metrics
        """
        logger.info("Starting classifier evaluation...")
        
        results = {
            "human": [],
            "ai": [],
            "uncertain": []
        }
        
        # Test human artists
        logger.info(f"\nEvaluating {len(KNOWN_HUMAN_ARTISTS)} known human artists...")
        for artist_id, name in KNOWN_HUMAN_ARTISTS.items():
            logger.info(f"  Testing: {name}")
            result = await self.evaluate_artist(artist_id, expected_human=True)
            results["human"].append(result)
            
        # Test AI artists
        logger.info(f"\nEvaluating {len(KNOWN_AI_ARTISTS)} known AI artists...")
        for artist_id, name in KNOWN_AI_ARTISTS.items():
            logger.info(f"  Testing: {name}")
            result = await self.evaluate_artist(artist_id, expected_human=False)
            results["ai"].append(result)
            
        # Test uncertain cases
        logger.info(f"\nEvaluating {len(UNCERTAIN_ARTISTS)} uncertain artists...")
        for artist_id, name in UNCERTAIN_ARTISTS.items():
            logger.info(f"  Testing: {name} (uncertain)")
            # Don't count these toward metrics
            result = await self.evaluate_artist(artist_id, expected_human=True)  # arbitrary
            results["uncertain"].append(result)
        
        # Calculate metrics
        metrics = self._calculate_metrics(results)
        
        return {
            "results": results,
            "metrics": metrics
        }
    
    def _calculate_metrics(self, results: Dict) -> Dict:
        """Calculate precision, recall, F1, and accuracy."""
        
        # Combine human and AI results (exclude uncertain)
        all_results = results["human"] + results["ai"]
        valid_results = [r for r in all_results if r.get("status") != "error" and r.get("status") != "not_found"]
        
        if not valid_results:
            return {"error": "No valid results"}
        
        # Overall classification metrics
        correct = sum(1 for r in valid_results if r.get("correct"))
        total = len(valid_results)
        accuracy = correct / total if total > 0 else 0
        
        # True positives: Correctly identified AI
        # False positives: Incorrectly classified human as AI
        # True negatives: Correctly identified human
        # False negatives: Incorrectly classified AI as human
        
        tp = sum(1 for r in results["ai"] if not r.get("classified_human") and r.get("status") not in ["error", "not_found"])
        fp = sum(1 for r in results["human"] if not r.get("classified_human") and r.get("status") not in ["error", "not_found"])
        tn = sum(1 for r in results["human"] if r.get("classified_human") and r.get("status") not in ["error", "not_found"])
        fn = sum(1 for r in results["ai"] if r.get("classified_human") and r.get("status") not in ["error", "not_found"])
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
        
        # LLM-specific metrics
        llm_correct = sum(1 for r in valid_results if r.get("llm_correct") == True)
        llm_total = sum(1 for r in valid_results if r.get("llm_correct") is not None)
        llm_accuracy = llm_correct / llm_total if llm_total > 0 else 0
        
        # Critical failures (major artists misclassified)
        critical_failures = [
            r for r in results["human"] 
            if not r.get("correct") and r.get("status") not in ["error", "not_found"]
        ]
        
        return {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
            "correct": correct,
            "total": total,
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "llm_accuracy": llm_accuracy,
            "llm_correct": llm_correct,
            "llm_total": llm_total,
            "critical_failures": len(critical_failures),
            "critical_failure_names": [r.get("artist_name") for r in critical_failures]
        }
    
    def print_report(self, evaluation: Dict):
        """Print a formatted evaluation report."""
        metrics = evaluation["metrics"]
        results = evaluation["results"]
        
        print("\n" + "="*80)
        print("CLASSIFIER EVALUATION REPORT")
        print("="*80)
        
        print("\n📊 OVERALL METRICS:")
        print(f"  Accuracy:  {metrics['accuracy']:.1%} ({metrics['correct']}/{metrics['total']} correct)")
        print(f"  Precision: {metrics['precision']:.1%} (AI detections that are correct)")
        print(f"  Recall:    {metrics['recall']:.1%} (AI artists successfully detected)")
        print(f"  F1 Score:  {metrics['f1_score']:.1%}")
        
        print(f"\n🤖 LLM PERFORMANCE:")
        print(f"  LLM Accuracy: {metrics['llm_accuracy']:.1%} ({metrics['llm_correct']}/{metrics['llm_total']})")
        
        print(f"\n🔢 CONFUSION MATRIX:")
        print(f"  True Positives (AI detected correctly):  {metrics['true_positives']}")
        print(f"  False Positives (Human called AI):       {metrics['false_positives']} ⚠️")
        print(f"  True Negatives (Human detected correctly): {metrics['true_negatives']}")
        print(f"  False Negatives (AI called Human):       {metrics['false_negatives']} ⚠️")
        
        if metrics.get('critical_failures', 0) > 0:
            print(f"\n🚨 CRITICAL FAILURES ({metrics['critical_failures']}):")
            for name in metrics.get('critical_failure_names', []):
                print(f"  ❌ {name} - Famous artist misclassified as AI!")
        
        # Show failures in detail
        print("\n" + "="*80)
        print("DETAILED FAILURES:")
        print("="*80)
        
        all_results = results["human"] + results["ai"]
        failures = [r for r in all_results if not r.get("correct") and r.get("status") not in ["error", "not_found"]]
        
        if not failures:
            print("\n✅ No failures! All test cases classified correctly.")
        else:
            for result in failures:
                print(f"\n❌ {result['artist_name']} (ID: {result['artist_id']})")
                print(f"   Expected: {'Human' if result['expected_human'] else 'AI'}")
                print(f"   Got: {'Human' if result['classified_human'] else 'AI'} (confidence: {result['confidence']:.0%})")
                print(f"   LLM voted: {result['llm_vote']}")
                print(f"   Reason: {result['decision_reason'][:150]}...")
        
        print("\n" + "="*80)


async def main():
    """Run classifier evaluation."""
    # Load config
    config = load_config()
    
    # Initialize database
    db_path = config.get("database", {}).get("path", "spotify-stop-ai.db")
    database = Database(db_path)
    await database.initialize()
    
    # Initialize classifier
    classifier = ArtistClassifier(config, database)
    
    # Run evaluation
    evaluator = ClassifierEvaluator(database, classifier)
    evaluation = await evaluator.run_evaluation()
    
    # Print report
    evaluator.print_report(evaluation)
    
    # Return exit code based on critical failures
    metrics = evaluation["metrics"]
    if metrics.get("critical_failures", 0) > 0:
        print("\n⚠️  CRITICAL FAILURES DETECTED - Famous artists misclassified!")
        return 1
    elif metrics["accuracy"] < 0.9:
        print("\n⚠️  Accuracy below 90% threshold")
        return 1
    else:
        print("\n✅ All tests passed!")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
