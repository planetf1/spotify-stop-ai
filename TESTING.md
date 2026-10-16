# Classifier Testing & Evaluation

This directory contains automated tests to ensure the AI artist classification system works correctly and doesn't misclassify famous human artists.

## Test Files

### 🔥 `test_critical_artists.py` - Quick Smoke Test
**Run this before deploying any prompt changes!**

Tests only the most famous artists that should NEVER be misclassified (e.g., Evanescence, Enter Shikari). Takes ~5 seconds.

```bash
python test_critical_artists.py
```

**Exit codes:**
- `0` = All critical artists correctly classified
- `1` = One or more critical failures detected

### 📊 `test_classifier.py` - Full Evaluation Suite
Comprehensive test with ground truth examples:
- Known human artists
- Known AI ghost projects
- Uncertain/ambiguous cases

Calculates metrics: accuracy, precision, recall, F1 score

```bash
python test_classifier.py
```

**Output includes:**
- Overall accuracy and performance metrics
- LLM-specific accuracy
- Confusion matrix (TP, FP, TN, FN)
- Critical failure alerts
- Detailed failure analysis with reasons

## Adding Test Cases

### Critical Artists (Smoke Test)
Edit `test_critical_artists.py` and add to `CRITICAL_HUMAN_ARTISTS`:

```python
CRITICAL_HUMAN_ARTISTS = {
    "spotify_artist_id": "Artist Name",
}
```

### Full Evaluation Suite
Edit `test_classifier.py` and add to the appropriate dictionary:

```python
# For confirmed human artists
KNOWN_HUMAN_ARTISTS = {
    "spotify_artist_id": "Artist Name",
}

# For confirmed AI ghost projects
KNOWN_AI_ARTISTS = {
    "spotify_artist_id": "Project Name",
}

# For genuinely ambiguous cases
UNCERTAIN_ARTISTS = {
    "spotify_artist_id": "Artist Name",
}
```

## Quality Thresholds

### Critical Failures
Any famous artist misclassified as AI is a CRITICAL FAILURE and must be fixed immediately.

### Accuracy Targets
- **Minimum acceptable:** 90% overall accuracy
- **Target:** 95%+ overall accuracy
- **LLM accuracy:** Should be comparable to overall accuracy
- **False positives:** Should be < 5% (prefer false negatives over false positives)

## Testing Workflow

### Before Making Prompt Changes
```bash
# 1. Run smoke test to establish baseline
python test_critical_artists.py

# 2. Make your prompt changes
vim prompts/classify_artist.txt

# 3. Re-run smoke test
python test_critical_artists.py

# 4. If passed, run full evaluation
python test_classifier.py
```

### After Finding a Misclassification
1. Add the artist to the appropriate test case dictionary
2. Fix the underlying issue (prompt, thresholds, logic)
3. Re-run tests to ensure fix works
4. Keep the test case to prevent regression

## Interpreting Results

### Confusion Matrix
- **True Positive (TP):** AI correctly identified as AI ✅
- **False Positive (FP):** Human incorrectly called AI ⚠️ **BAD**
- **True Negative (TN):** Human correctly identified as human ✅
- **False Negative (FN):** AI incorrectly called human ⚠️ **Better than FP**

### Metrics
- **Precision:** Of all AI detections, how many are correct? (TP / (TP + FP))
- **Recall:** Of all actual AI artists, how many did we catch? (TP / (TP + FN))
- **F1 Score:** Harmonic mean of precision and recall
- **Accuracy:** Overall correctness ((TP + TN) / Total)

## Continuous Improvement

As you discover new cases:
1. **Add them to the test suite immediately**
2. **Investigate the root cause** (prompt too aggressive? missing data source?)
3. **Fix the underlying issue** (don't just add artist-specific hacks)
4. **Re-run all tests** to ensure no regressions
5. **Document the fix** in ENHANCEMENTS.md

## Known Issues / Edge Cases

Track difficult cases here:

- **Major Moment:** Has tour dates but triggers ghost project patterns (5 releases/year, Novamozic label)
- **Evanescence:** LLM sometimes votes AI despite 3/4 sources saying human (reason: claims "digital-only presence" which is false)
- **Indie labels:** Novamozic, DistroKid artists can be legitimate but trigger suspicion

## Future Enhancements

- [ ] Add automated test runs on file changes
- [ ] Create GitHub Actions workflow for PR testing
- [ ] Build dataset of 100+ confirmed human/AI artists
- [ ] Add performance benchmarks (classification speed)
- [ ] Test with different LLM models (compare Ollama models)
- [ ] Add integration tests for full pipeline
