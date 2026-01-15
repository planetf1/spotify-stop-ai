"""Web UI for monitoring and managing Spotify Stop AI."""

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import logging
from pathlib import Path
import time

logger = logging.getLogger(__name__)


def create_web_ui(database, classifier, spotify_client, monitor):
    """Create web UI app.

    Args:
        database: Database instance
        classifier: ArtistClassifier instance
        spotify_client: SpotifyClient instance
        monitor: PlaybackMonitor instance

    Returns:
        FastAPI app
    """
    app = FastAPI(title="Spotify Stop AI - Web UI")

    # Setup templates
    templates_dir = Path(__file__).parent / "templates"
    templates_dir.mkdir(exist_ok=True)
    templates = Jinja2Templates(directory=str(templates_dir))

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        """Home page with current playback."""
        current_track = monitor.current_track

        # Get artist info and related artists
        artist_info = None
        related_artists = None
        artist_is_saved = False
        if current_track and current_track.get("artist_id"):
            artist_id = current_track["artist_id"]
            artist_info = spotify_client.get_artist(artist_id)
            # Removed: get_artist_related() - not used and causes unnecessary API calls
            artist_is_saved = spotify_client.check_artist_saved(artist_id)

        # Get current playlists (for context display)
        user_playlists = spotify_client.get_current_user_playlists(limit=20)

        # Highlight special playlists
        featured_playlists = []
        if user_playlists:
            keywords = [
                "release radar",
                "discover weekly",
                "daily mix",
                "new music",
                "top songs",
            ]
            for playlist in user_playlists:
                playlist_name = playlist.get("name", "").lower()
                if any(keyword in playlist_name for keyword in keywords):
                    featured_playlists.append(playlist)

        # Get detailed classification for current artist if available
        current_artist_details = None
        if current_track and current_track.get("artist_id"):
            artist_id = current_track["artist_id"]
            decisions_with_sources = await database.get_decisions_with_sources(
                artist_id
            )
            if decisions_with_sources:
                # Get the most recent decision
                decision = decisions_with_sources[0]

                # Parse JSON results for sources
                import json

                for source in decision.get("sources", []):
                    if source.get("result") and isinstance(source["result"], str):
                        # Only try to parse if it looks like JSON (starts with { or [)
                        result_str = source["result"].strip()
                        if result_str.startswith("{") or result_str.startswith("["):
                            try:
                                source["result"] = json.loads(result_str)
                            except json.JSONDecodeError:
                                source["result"] = {}
                        # Otherwise leave it as a string (old format: "human", "ai", or "")

                # Parse LLM output if present
                if decision.get("llm_output") and decision["llm_output"].get("output"):
                    if isinstance(decision["llm_output"]["output"], str):
                        try:
                            decision["llm_output"]["output"] = json.loads(
                                decision["llm_output"]["output"]
                            )
                        except json.JSONDecodeError:
                            decision["llm_output"]["output"] = {}

                # Check for override
                override = await database.get_override(artist_id)
                if override:
                    decision["is_artificial"] = override["is_artificial"]
                    decision["overridden"] = True
                    decision["override_reason"] = override.get("reason", "")
                else:
                    decision["overridden"] = False

                current_artist_details = decision

        # Get recent plays
        plays = await database.get_plays(limit=10)

        # Get recent decisions with contexts
        decisions_raw = await database.get_decisions(limit=10)

        # Enrich decisions with context counts and overrides
        decisions = []
        for decision in decisions_raw:
            # Get context count for this decision
            context_count = await database.get_decision_context_count(decision["id"])
            decision["context_count"] = context_count

            # Check for override - if exists, it takes precedence
            override = await database.get_override(decision["artist_id"])
            if override:
                decision["is_artificial"] = override["is_artificial"]
                decision["overridden"] = True
            else:
                decision["overridden"] = False

            decisions.append(decision)

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "current_track": current_track,
                "current_artist_details": current_artist_details,
                "artist_info": artist_info,
                "artist_is_saved": artist_is_saved,
                "related_artists": related_artists,
                "user_playlists": featured_playlists,
                "plays": plays,
                "decisions": decisions,
            },
        )

    @app.get("/plays", response_class=HTMLResponse)
    async def plays_page(request: Request, page: int = 1, search: Optional[str] = None):
        """Browse all plays."""
        limit = 50
        offset = (page - 1) * limit

        if search:
            # Search by artist or track name
            plays = await database.search_plays(search, limit, offset)
        else:
            plays = await database.get_plays(limit=limit, offset=offset)

        return templates.TemplateResponse(
            "plays.html",
            {"request": request, "plays": plays, "page": page, "search": search},
        )

    @app.get("/decisions", response_class=HTMLResponse)
    async def decisions_page(
        request: Request, page: int = 1, filter_artificial: Optional[bool] = None
    ):
        """Browse all decisions."""
        limit = 50
        offset = (page - 1) * limit

        if filter_artificial is not None:
            decisions = await database.get_decisions_filtered(
                filter_artificial, limit, offset
            )
        else:
            decisions = await database.get_decisions(limit=limit, offset=offset)

        return templates.TemplateResponse(
            "decisions.html",
            {
                "request": request,
                "decisions": decisions,
                "page": page,
                "filter_artificial": filter_artificial,
            },
        )

    @app.get("/artist/{artist_id}", response_class=HTMLResponse)
    async def artist_detail(request: Request, artist_id: str):
        """Artist detail page with all classifications."""
        # Get artist
        artist = await database.get_artist(artist_id)
        if not artist:
            return HTMLResponse("Artist not found", status_code=404)

        # Get all decisions with sources
        decisions = await database.get_decisions_with_sources(artist_id)

        # Get override
        override = await database.get_override(artist_id)

        # Get plays for this artist
        plays = await database.get_plays_for_artist(artist_id)

        return templates.TemplateResponse(
            "artist.html",
            {
                "request": request,
                "artist": artist,
                "decisions": decisions,
                "override": override,
                "plays": plays,
            },
        )

    @app.post("/override/{artist_id}")
    async def set_override_form(
        artist_id: str, is_artificial: bool = Form(...), reason: str = Form(None)
    ):
        """Set override from form."""
        await database.set_override(artist_id, is_artificial, reason)
        return RedirectResponse(f"/artist/{artist_id}", status_code=303)

    @app.post("/override/{artist_id}/delete")
    async def delete_override_form(artist_id: str):
        """Delete override from form."""
        await database.delete_override(artist_id)
        return RedirectResponse(f"/artist/{artist_id}", status_code=303)

    @app.post("/reclassify/{artist_id}")
    async def reclassify_form(artist_id: str, artist_name: str = Form(...)):
        """Reclassify artist from form - forces fresh classification."""
        # Invalidate cache to force fresh classification
        await database.invalidate_cache(artist_id)
        # Run classification
        await classifier.classify_artist(artist_id, artist_name)
        return RedirectResponse(f"/artist/{artist_id}", status_code=303)

    @app.get("/api/current")
    async def current_playback_api():
        """Get current playback state (for auto-refresh)."""
        current_track = monitor.current_track

        # Get artist info
        artist_info = None
        related_artists = None
        artist_is_saved = False
        if current_track and current_track.get("artist_id"):
            artist_id = current_track["artist_id"]
            artist_info = spotify_client.get_artist(artist_id)
            # Removed: get_artist_related() - not used and causes unnecessary API calls
            artist_is_saved = spotify_client.check_artist_saved(artist_id)

        # Get playlists
        user_playlists = spotify_client.get_current_user_playlists(limit=20)
        featured_playlists = []
        if user_playlists:
            keywords = [
                "release radar",
                "discover weekly",
                "daily mix",
                "new music",
                "top songs",
            ]
            for playlist in user_playlists:
                playlist_name = playlist.get("name", "").lower()
                if any(keyword in playlist_name for keyword in keywords):
                    featured_playlists.append(playlist)

        # Get detailed classification for current artist if available
        current_artist_details = None
        if current_track and current_track.get("artist_id"):
            import json

            artist_id = current_track["artist_id"]
            decisions_with_sources = await database.get_decisions_with_sources(
                artist_id
            )
            if decisions_with_sources:
                decision = decisions_with_sources[0]

                # Parse JSON results for sources
                for source in decision.get("sources", []):
                    if source.get("result") and isinstance(source["result"], str):
                        # Only try to parse if it looks like JSON (starts with { or [)
                        result_str = source["result"].strip()
                        if result_str.startswith("{") or result_str.startswith("["):
                            try:
                                source["result"] = json.loads(result_str)
                            except json.JSONDecodeError:
                                source["result"] = {}
                        # Otherwise leave it as a string (old format: "human", "ai", or "")

                # Parse LLM output if present
                if decision.get("llm_output") and decision["llm_output"].get("output"):
                    if isinstance(decision["llm_output"]["output"], str):
                        try:
                            decision["llm_output"]["output"] = json.loads(
                                decision["llm_output"]["output"]
                            )
                        except json.JSONDecodeError:
                            decision["llm_output"]["output"] = {}

                # Check for override
                override = await database.get_override(artist_id)
                if override:
                    decision["is_artificial"] = override["is_artificial"]
                    decision["overridden"] = True
                    decision["override_reason"] = override.get("reason", "")
                else:
                    decision["overridden"] = False

                current_artist_details = decision

        return {
            "current_track": current_track,
            "current_artist_details": current_artist_details,
            "artist_info": artist_info,
            "artist_is_saved": artist_is_saved,
            "related_artists": related_artists,
            "user_playlists": featured_playlists,
            "last_decision": monitor.last_decision
            if hasattr(monitor, "last_decision")
            else None,
        }

    @app.get("/api/status")
    async def monitor_status():
        """Get monitor status including rate limit info."""
        current_time = time.time()
        rate_limit_info = {
            "is_rate_limited": monitor.is_rate_limited,
            "current_backoff_seconds": monitor.current_backoff,
            "max_backoff_seconds": monitor.max_backoff,
            "retry_in_seconds": None,
            "retry_at": None,
        }

        # Calculate time remaining if rate limited
        if monitor.is_rate_limited and monitor.rate_limit_until:
            seconds_until_retry = monitor.rate_limit_until - current_time
            if seconds_until_retry > 0:
                rate_limit_info["retry_in_seconds"] = round(seconds_until_retry, 1)
                rate_limit_info["retry_at"] = monitor.rate_limit_until
            else:
                # Should have recovered by now
                monitor.is_rate_limited = False
                monitor.rate_limit_until = None

        return {
            "running": monitor.running,
            "poll_interval": monitor.poll_interval,
            "rate_limit": rate_limit_info,
        }

    # Playback Control Endpoints
    @app.post("/api/playback/play")
    async def play():
        """Resume playback."""
        try:
            spotify_client.start_playback()
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Failed to play: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/playback/pause")
    async def pause():
        """Pause playback."""
        try:
            spotify_client.pause_playback()
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Failed to pause: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/playback/toggle")
    async def toggle_play_pause():
        """Toggle play/pause."""
        try:
            playback = spotify_client.get_current_playback()
            if playback and playback.get("is_playing"):
                spotify_client.pause_playback()
            else:
                spotify_client.start_playback()
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Failed to toggle play/pause: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/playback/next")
    async def next_track():
        """Skip to next track."""
        try:
            spotify_client.skip_to_next()
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Failed to skip: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/playback/previous")
    async def previous_track():
        """Previous track."""
        try:
            spotify_client.skip_to_previous()
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Failed to go to previous: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/playback/shuffle/toggle")
    async def toggle_shuffle():
        """Toggle shuffle."""
        try:
            playback = spotify_client.get_current_playback()
            new_state = not (playback and playback.get("shuffle_state", False))
            spotify_client.set_shuffle(new_state)
            return {"status": "ok", "shuffle": new_state}
        except Exception as e:
            logger.error(f"Failed to toggle shuffle: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/track/like/toggle")
    async def toggle_like():
        """Toggle like on current track."""
        try:
            current_track = monitor.current_track
            if not current_track or not current_track.get("uri"):
                return {"status": "error", "message": "No track playing"}

            track_uri = current_track["uri"]
            # Get current like status
            is_liked = spotify_client.check_track_liked(track_uri)
            if is_liked:
                spotify_client.remove_from_liked(track_uri)
            else:
                spotify_client.add_to_liked(track_uri)
            return {"status": "ok", "liked": not is_liked}
        except Exception as e:
            logger.error(f"Failed to toggle like: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/api/playback/status")
    async def get_playback_status():
        """Get current playback status."""
        try:
            playback = spotify_client.get_current_playback()
            current_track = monitor.current_track

            is_playing = playback and playback.get("is_playing", False)
            is_shuffled = playback and playback.get("shuffle_state", False)
            is_liked = False
            track_uri = None

            if current_track and current_track.get("uri"):
                track_uri = current_track["uri"]
                is_liked = spotify_client.check_track_liked(track_uri)

            return {
                "is_playing": is_playing,
                "is_shuffled": is_shuffled,
                "is_liked": is_liked,
                "track_uri": track_uri,
            }
        except Exception as e:
            logger.error(f"Failed to get playback status: {e}")
            return {
                "is_playing": False,
                "is_shuffled": False,
                "is_liked": False,
                "track_uri": None,
            }

    return app


def run_web_ui(
    database,
    classifier,
    spotify_client,
    monitor,
    host: str = "127.0.0.1",
    port: int = 8890,
):
    """Run the web UI server.

    Args:
        database: Database instance
        classifier: ArtistClassifier instance
        spotify_client: SpotifyClient instance
        monitor: PlaybackMonitor instance
        host: Host to bind to
        port: Port to bind to
    """
    import uvicorn

    app = create_web_ui(database, classifier, spotify_client, monitor)
    logger.info(f"Starting web UI at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
