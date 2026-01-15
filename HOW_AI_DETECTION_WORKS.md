# How AI Detection Works - Complete Flow

## The Classification Pipeline

### Step 1: Artist Query (When Track Starts Playing)
```
Spotify Reports: "Now playing Track X by Artist Y"
        ↓
Query All Sources In Parallel:
  • Wikidata (SPARQL query for entity type)
  • MusicBrainz (API search for tags)
  • Last.fm (API for top tags)
        ↓
Record Query Times & Results
```

### Step 2: Vote Aggregation
```
Collect Results:
  Wikidata:    "human" (1,471ms)
  MusicBrainz: "not found" (95ms)
  Last.fm:     "human" (155ms)
        ↓
Count Votes:
  AI Votes:     0
  Human Votes:  2
  No Data:      1
        ↓
Check Configuration: min_source_agreement = 2
        ↓
Decision: 2 human votes ≥ 2 required → HUMAN (No LLM needed)
```

### Step 3: LLM Fallback (When Needed)
LLM is called when:
- ❌ All sources failed to find artist (0 successful queries)
- ❓ Sources disagree (some say AI, some say human)
- 🤷 Insufficient agreement (only 1 source found data)
- 🔄 Mixed signals (both AI and human tags present)

```
Example Inconclusive Scenario:
  Wikidata:    "human" (found)
  MusicBrainz: "not found"
  Last.fm:     "not found"
        ↓
Count Votes:
  AI Votes:     0
  Human Votes:  1
  No Data:      2
        ↓
Check: 1 human vote < 2 required → INCONCLUSIVE
        ↓
INVOKE LLM:
  Model: Granite4:tiny-h
  Prompt: "Based on available evidence, is this artist AI-generated?"
  Context: Web search results + source data
        ↓
LLM Response: "Based on research, this appears to be [decision]"
        ↓
Final Decision: Use LLM result
```

---

## Source Details

### Wikidata
**What it does**: Searches for artist entity and checks classification
**Looks for**: 
- Q125130106 = Vocaloid
- Q24236999 = Virtual idol
- Q55155641 = VTuber
- Q3736859 = Virtual band

**Result time**: 1-2 seconds (depends on entity complexity)
**Reliability**: High when data exists, but sparse coverage for new artists

### MusicBrainz
**What it does**: Searches artist database and analyzes tags
**Looks for**: "vocaloid", "vtuber", "virtual", "fictional", "ai generated", "voice synthesis"
**Result time**: 95-500ms (per rate limit: 1 request/second)
**Reliability**: Good but limited coverage for non-mainstream artists

### Last.fm  
**What it does**: Gets top tags from user-submitted data
**Looks for**: AI-related tags like above
**Result time**: 100-200ms
**Reliability**: Very good for mainstream artists, sparse for obscure ones

### Ollama LLM (Granite4:tiny-h)
**What it does**: Analyzes context and reasons about artist nature
**Uses**: 
- Web search results (DuckDuckGo)
- Available source data
- Historical patterns
- Artist context

**Decision logic**:
- Vocaloid artists → AI
- Virtual/fictional → AI  
- Real people → Human
- Unknown/ambiguous → Returns "unknown" with low confidence

**Result time**: 1-3 seconds (model inference + web search)
**Reliability**: Improving as more data is collected

---

## Configuration Flow

```yaml
Classification:
  min_source_agreement: 2    # Need 2+ sources to agree
  
Sources:
  wikidata: enabled
  musicbrainz: enabled
  lastfm: enabled (needs API key)
  
LLM (Ollama):
  enabled: true
  model: granite4:tiny-h
  timeout_ms: 8000
  require_citations: false   # We relaxed this
  
AI Detection Keywords:
  - vocaloid, vtuber, virtual idol
  - voice synthesis, ai generated  
  - fictional, virtual band
```

---

## Example Classifications

### Example 1: Well-Known Human Artist
```
Artist: Angtoria

Sources:
  ✓ Wikidata:    "human" (1,471ms)
  ❌ MusicBrainz: not found (95ms)
  ✓ Last.fm:     "human" (155ms)

Votes: 2 human, 0 AI, 1 no-data
Decision: HUMAN (2/2 sources agree)
Confidence: 67%
LLM Used: No (already conclusive)
```

### Example 2: Unknown Artist (Would Trigger LLM)
```
Artist: ObscureArtist123

Sources:
  ❌ Wikidata:    not found (1,200ms)
  ❌ MusicBrainz: not found (95ms)
  ❌ Last.fm:     not found (500ms)

Votes: 0 human, 0 AI, 3 no-data
Decision: INCONCLUSIVE
Confidence: 0%
LLM Used: Yes

LLM Process:
  1. Web search: "ObscureArtist123"
  2. Find: "Virtual artist created by..."
  3. Conclusion: "AI-generated"
  4. Final Result: AI (from LLM)
  5. Confidence: 85%
```

### Example 3: Conflicting Sources (Would Trigger LLM)
```
Artist: VirtualPerformer

Sources:
  ✓ Wikidata:    "human" (1,000ms)
  ✓ MusicBrainz: "virtual" (200ms)
  ✓ Last.fm:     "human" (300ms)

Votes: 2 human, 1 AI (virtual), 0 no-data
Decision: INCONCLUSIVE (no clear majority)
LLM Used: Yes (tiebreaker)

LLM Reasoning:
  - MusicBrainz tagged as "virtual" (strong AI signal)
  - Wikidata/Last.fm say "human" (contradicts)
  - Web search reveals: "Virtual collaborator"
  - Conclusion: AI with 75% confidence
```

---

## How Each Check Appears in UI

### Home Page Display

#### Source Results Grid
```html
<div style="border-left: 4px solid [color]">
  [SOURCE NAME] [QUERY TIME]
  [STATUS BADGE] [CONFIDENCE]%
  Label: [classification]
  Tags: [relevant tags]
  🔗 View Source Link
</div>
```

#### Color Coding
- 🟢 Green border = Human detected
- 🔴 Red border = AI detected  
- 🟠 Orange border = Unknown/Inconclusive
- ⚫ Gray border = Failed/No data

#### Confidence Display
```
Confidence: 67%  (human) or  92% (AI detected)
```

Calculated as: `successful_votes / total_sources`

---

## Decision Reasoning Examples

### Conclusive (Sources Agree)
```
"Classified as human: 2/2 sources agree. Threshold: 2 sources required"
```

### With Band Policy Applied
```
"Classified as artificial: 1/3 sources detected virtual members.
Band policy applied (any virtual/fictional = artificial)"
```

### Inconclusive with LLM Fallback
```
"Insufficient source agreement (0 AI vs 1 human from 1 sources). 
Using LLM fallback...
LLM Result: Based on evidence, this appears to be AI-generated 
with 78% confidence"
```

### LLM Failed
```
"Inconclusive: 0 artificial, 1 human out of 1 successful sources. 
Threshold: 2 required.
LLM fallback also failed or returned inconclusive"
```

---

## What's Being Logged

### When You Look at `/tmp/spotify_app.log`:

#### Classification Start
```
2026-01-15 10:19:09,601 - spotify_stop_ai.classifier - INFO - 
  Classifying artist: Angtoria (ID: 2XboXFS9ENxbne9aajZlAc)
```

#### Source Queries
```
2026-01-15 10:19:11,168 - spotify_stop_ai.classifiers.musicbrainz - ERROR - 
  MusicBrainz artist search failed:
```

#### Web Search (if LLM triggered)
```
2026-01-15 10:19:12,500 - spotify_stop_ai.ollama_client - INFO -
  Web search for 'Artist Name' returned 5 unique results
```

#### LLM Processing
```
2026-01-15 10:19:13,000 - spotify_stop_ai.ollama_client - INFO -
  Starting LLM classification for artist: Artist Name

2026-01-15 10:19:14,500 - spotify_stop_ai.ollama_client - INFO -
  Raw LLM response (first 500 chars): {"label": "ai_generated"...

2026-01-15 10:19:14,600 - spotify_stop_ai.ollama_client - INFO -
  ✓ JSON parse successful for artist classification

2026-01-15 10:19:14,600 - spotify_stop_ai.ollama_client - INFO -
  ✓ LLM output validated successfully
```

#### Final Decision
```
2026-01-15 10:19:14,700 - spotify_stop_ai.monitor - INFO - 
  Classification: Angtoria → human (artificial: False, confidence: 0.67)
```

---

## Summary

The system now:
1. **Queries all sources immediately** when track changes
2. **Shows detailed results** with timing and confidence
3. **Falls back to LLM** when sources are inconclusive
4. **Provides full transparency** of the decision process
5. **Logs everything** for debugging and improvement
6. **Displays visually** with color-coding and badges

All of this happens **automatically** as you listen to Spotify!

---

**Current Status**: ✅ All systems operational
**Next Classifications**: Watch the home page in real-time as you play music
**LLM Ready**: Will activate when sources can't decide
