# Spotify Stop AI

**Automatically skip AI-generated and virtual artists on Spotify in real-time.**

Spotify Stop AI is a macOS background service that monitors your Spotify playback via the Web API, classifies artists using open data sources (Wikidata, MusicBrainz, Last.fm), and automatically skips tracks from AI/virtual artists. All plays and decisions are logged to a local SQLite database with unlimited retention, and you can override any classification via a simple review API.

## Features

- **Real-time monitoring**: Polls Spotify playback every 2-3 seconds (configurable)
- **Multi-source classification**: Requires agreement from ≥2 sources (Wikidata, MusicBrainz, Last.fm) to avoid false positives
- **Band policy**: Configurable rule to treat any virtual/fictional signals as "artificial"
- **Auto-skip**: Skip to next track when AI/virtual artist detected (default enabled)
- **Optional playlist management**: Remove from user-owned playlists, add to a private "blocked" playlist
- **Local LLM fallback**: Optional Ollama integration (Granite 4, LLaMA 3.2, etc.) for inconclusive cases
- **SQLite logging**: Unlimited retention of all plays, contexts, decisions, and sources
- **Review API**: FastAPI endpoints to view plays, decisions, and override artist classifications
- **Manual overrides**: Mark artists as artificial or human, with optional reason

## Requirements

- **macOS** 10.14+ (tested on macOS Sonoma/Sequoia)
- **Python** 3.10+
- **Spotify Premium** account (required for playback control via API)
- **Spotify application** running on at least one device (desktop, mobile, or web player)
- **Spotify Developer App** credentials (free, see setup below)
- **Last.fm API key** (free, optional but recommended)
- **Ollama** (optional, for local LLM fallback)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/spotify-stop-ai.git
cd spotify-stop-ai
```

### 2. Install Python dependencies

Using pip:

```bash
pip install -r requirements.txt
```

Or using the package:

```bash
pip install -e .
```

### 3. Create Spotify Developer App

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Log in with your Spotify account
3. Click "Create app"
4. Fill in:
   - **App name**: `Spotify Stop AI` (or any name)
   - **App description**: `Auto-skip AI-generated artists`
   - **Redirect URI**: `http://localhost:8888/callback`
   - **APIs used**: Select "Web API"
5. Save and copy your **Client ID**

### 4. Get Last.fm API Key (optional but recommended)

1. Go to [Last.fm API Account Creation](https://www.last.fm/api/account/create)
2. Fill in the form (any values work for personal use)
3. Copy your **API key**

### 5. Configure the application

Copy the example config and environment files:

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

Edit `.env` and add your credentials:

```bash
SPOTIFY_CLIENT_ID=your_spotify_client_id_here
LASTFM_API_KEY=your_lastfm_api_key_here
```

Edit `config.yaml` to adjust settings (see [Configuration](#configuration) section).

### 6. Optional: Install Ollama and pull a model

If you want to enable the LLM fallback for inconclusive cases:

1. Install Ollama:
   ```bash
   brew install ollama
   ```
   
   Or download from [ollama.com/download](https://ollama.com/download)

2. Pull the Granite 4 tiny model (recommended, ~4GB):
   ```bash
   ollama pull granite4:tiny-h
   ```
   
   Alternative lightweight models:
   ```bash
   ollama pull llama3.2:1b
   ollama pull granite4:350m-h
   ```

3. Enable in `config.yaml`:
   ```yaml
   ollama:
     enabled: true
     model: "granite4:tiny-h"
   ```

## Usage

### Run the service

```bash
python -m spotify_stop_ai.main
```

Or if installed as a package:

```bash
spotify-stop-ai
```

On first run, your browser will open for Spotify OAuth authentication. Log in and authorize the app.

### Web UI

The web UI runs on `http://127.0.0.1:8890` by default.

**Features:**

- 🎵 **Real-time monitoring** - See currently playing track with auto-refresh
- 📊 **Browse plays** - Search and filter all playback history
- 🤖 **View decisions** - See classification results with confidence scores
- 🎤 **Artist details** - View all classifications with source breakdowns (Wikidata, MusicBrainz, Last.fm, web search)
- ⚙️ **Manual overrides** - Set or remove artist classifications directly from the UI
- 🔄 **Reclassify** - Trigger new classification for any artist

Open the UI in your browser while the service is running to monitor and manage classifications.

### Review API

The review API runs on `http://127.0.0.1:8889` by default.

**Endpoints:**

- `GET /plays?limit=100&offset=0` - List recent plays
- `GET /decisions?limit=100&offset=0` - List recent classification decisions
- `GET /overrides` - List all user overrides
- `GET /overrides/{artist_id}` - Get override for specific artist
- `POST /overrides/{artist_id}?is_artificial=true&reason=...` - Set override
- `DELETE /overrides/{artist_id}` - Delete override
- `GET /artists/{artist_id}` - Get artist info with decisions
- `POST /classify/{artist_id}?artist_name=...` - Manually reclassify artist

**Example: Override an artist**

```bash
curl -X POST "http://127.0.0.1:8889/overrides/4Z8W4fKeB5YxbusRsdQVPb?is_artificial=false&reason=Real%20artist"
```

### Run as a background service (LaunchAgent)

To auto-start on login:

1. Edit the example LaunchAgent plist:

```bash
cp examples/com.spotify-stop-ai.guard.plist ~/Library/LaunchAgents/
```

2. Update the plist with your paths:
   - Replace `/path/to/python` with your Python interpreter path (run `which python3`)
   - Replace `/path/to/spotify-stop-ai` with your repo path
   - Update `SPOTIFY_CLIENT_ID` and `LASTFM_API_KEY` environment variables

3. Load the agent:

```bash
launchctl load ~/Library/LaunchAgents/com.spotify-stop-ai.guard.plist
```

4. Check status:

```bash
launchctl list | grep spotify-stop-ai
```

5. View logs:

```bash
tail -f ~/Library/Logs/spotify-stop-ai.log
```

To stop and unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.spotify-stop-ai.guard.plist
```

## Configuration

See `config.example.yaml` for all options. Key settings:

### Classification

```yaml
classification:
  # Minimum sources that must agree (1-3, recommended: 2)
  min_source_agreement: 2
  
  # Band policy: treat any virtual/fictional signal as artificial
  band_policy:
    virtual_or_fictional_is_artificial: true
  
  # Cache artist decisions for 24 hours
  cache_duration_seconds: 86400
```

### Actions

```yaml
actions:
  # Auto-skip AI artists (default: true)
  auto_skip: true
  
  # Remove from user-owned playlists (default: false)
  remove_from_user_playlists: false
  
  # Add to a private playlist (leave empty to disable)
  add_to_blocked_playlist: ""
```

### Data Sources

Enable/disable sources:

```yaml
sources:
  wikidata:
    enabled: true
  musicbrainz:
    enabled: true
    user_agent: "spotify-stop-ai/0.1.0 (your.email@example.com)"
  lastfm:
    enabled: true
    min_tag_count: 5
```

### Ollama LLM Fallback

```yaml
ollama:
  enabled: false  # Set to true to enable
  model: "granite4:tiny-h"
  options:
    temperature: 0.0
    seed: 42
```

## How It Works

1. **Playback monitoring**: Polls `/me/player/currently-playing` every 2-3 seconds
2. **Track detection**: Detects new tracks and extracts artist metadata
3. **Classification**:
   - Check user override first (highest priority)
   - Check cached decision (24-hour TTL by default)
   - Query enabled sources in parallel (Wikidata, MusicBrainz, Last.fm)
   - Aggregate results: require ≥2 sources agreeing
   - Apply band policy if configured
   - Optional: use Ollama LLM for inconclusive cases
4. **Action**: If artificial with sufficient confidence, skip to next track (and optionally remove/block)
5. **Logging**: Store play, decision, and action in SQLite

### Classification Labels

- `vocaloid` - Vocaloid or similar voice synthesis
- `vtuber` - VTuber or virtual YouTuber
- `virtual_idol` - Virtual idol or digital persona
- `virtual` - Generic virtual artist
- `fictional` - Fictional character or band
- `ai_generated` - AI-generated music
- `human` - Human artist (real person)
- `band` - Traditional band (human members)
- `unknown` - Insufficient or contradictory evidence

Labels `vocaloid`, `vtuber`, `virtual_idol`, `virtual`, `fictional`, `ai_generated` are considered "artificial."

## Example Artifacts

See `examples/` directory:

- `logged_play.json` - Example play record structure
- `decision_record.json` - Example classification decision structure
- `com.spotify-stop-ai.guard.plist` - Example LaunchAgent plist

## Troubleshooting

### "No active Spotify devices found"

Ensure Spotify is open on at least one device (desktop, mobile, or web player). Playback control requires an active Spotify Connect device.

### "Rate limit exceeded"

The service backs off automatically on 429 responses. If persistent, increase `poll_interval_seconds` in `config.yaml`.

### "Spotify authentication failed"

- Verify `SPOTIFY_CLIENT_ID` in `.env`
- Check redirect URI matches your app settings: `http://localhost:8888/callback`
- Delete `.cache-spotify` and re-authenticate

### LLM fallback not working

- Ensure Ollama is running: `ollama serve`
- Verify model is pulled: `ollama list`
- Check `ollama.enabled: true` in `config.yaml`
- Review logs for Ollama connection errors

### False positives/negatives

- Adjust `min_source_agreement` (increase to reduce false positives)
- Use manual overrides via the API: `POST /overrides/{artist_id}`
- Enable more sources (Wikidata, MusicBrainz, Last.fm)
- Tune `min_tag_count` for Last.fm to filter noise

## Legal & Ethics

- **Spotify Developer Policy**: This app uses Spotify's Web API for playback monitoring and control on your own account. It does not manipulate streams across accounts, does not simulate user growth metrics, and operates with explicit user consent.
- **Rate Limiting**: The app respects Spotify's rate limits and backs off on 429 responses.
- **Data Privacy**: All data (plays, decisions, overrides) is stored locally in SQLite. No data is sent to third parties except API queries to Wikidata, MusicBrainz, Last.fm, and optionally a local Ollama instance.
- **Terms of Service**: Use at your own risk. Ensure compliance with Spotify's [Terms of Service](https://www.spotify.com/legal/end-user-agreement/) and [Developer Terms](https://developer.spotify.com/terms).

## Contributing

Contributions welcome! Please open an issue or PR.

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- [Spotipy](https://github.com/spotipy-dev/spotipy) - Spotify Web API Python library
- [Wikidata](https://www.wikidata.org/) - Structured knowledge base
- [MusicBrainz](https://musicbrainz.org/) - Open music encyclopedia
- [Last.fm](https://www.last.fm/) - Music discovery and tagging
- [Ollama](https://ollama.com/) - Local LLM runtime
- [IBM Granite](https://github.com/ibm-granite/granite-4.0-language-models) - Open-source language models

## Support

For issues, questions, or feature requests, please open an issue on GitHub.

---

**Disclaimer**: This project is not affiliated with Spotify, Wikidata, MusicBrainz, Last.fm, Ollama, or IBM. All trademarks belong to their respective owners.
