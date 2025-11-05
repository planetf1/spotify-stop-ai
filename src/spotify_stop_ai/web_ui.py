"""Web UI for monitoring and managing Spotify Stop AI."""
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import logging
from pathlib import Path

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
        
        # Get detailed classification for current artist if available
        current_artist_details = None
        if current_track and current_track.get('artist_id'):
            artist_id = current_track['artist_id']
            decisions_with_sources = await database.get_decisions_with_sources(artist_id)
            if decisions_with_sources:
                # Get the most recent decision
                decision = decisions_with_sources[0]
                
                # Check for override
                override = await database.get_override(artist_id)
                if override:
                    decision['is_artificial'] = override['is_artificial']
                    decision['overridden'] = True
                    decision['override_reason'] = override.get('reason', '')
                else:
                    decision['overridden'] = False
                
                current_artist_details = decision
        
        # Get recent plays
        plays = await database.get_plays(limit=10)
        
        # Get recent decisions with contexts
        decisions_raw = await database.get_decisions(limit=10)
        
        # Enrich decisions with context counts and overrides
        decisions = []
        for decision in decisions_raw:
            # Get context count for this decision
            context_count = await database.get_decision_context_count(decision['id'])
            decision['context_count'] = context_count
            
            # Check for override - if exists, it takes precedence
            override = await database.get_override(decision['artist_id'])
            if override:
                decision['is_artificial'] = override['is_artificial']
                decision['overridden'] = True
            else:
                decision['overridden'] = False
            
            decisions.append(decision)
        
        return templates.TemplateResponse("index.html", {
            "request": request,
            "current_track": current_track,
            "current_artist_details": current_artist_details,
            "plays": plays,
            "decisions": decisions
        })
    
    @app.get("/plays", response_class=HTMLResponse)
    async def plays_page(
        request: Request,
        page: int = 1,
        search: Optional[str] = None
    ):
        """Browse all plays."""
        limit = 50
        offset = (page - 1) * limit
        
        if search:
            # Search by artist or track name
            plays = await database.search_plays(search, limit, offset)
        else:
            plays = await database.get_plays(limit=limit, offset=offset)
        
        return templates.TemplateResponse("plays.html", {
            "request": request,
            "plays": plays,
            "page": page,
            "search": search
        })
    
    @app.get("/decisions", response_class=HTMLResponse)
    async def decisions_page(
        request: Request,
        page: int = 1,
        filter_artificial: Optional[bool] = None
    ):
        """Browse all decisions."""
        limit = 50
        offset = (page - 1) * limit
        
        if filter_artificial is not None:
            decisions = await database.get_decisions_filtered(filter_artificial, limit, offset)
        else:
            decisions = await database.get_decisions(limit=limit, offset=offset)
        
        return templates.TemplateResponse("decisions.html", {
            "request": request,
            "decisions": decisions,
            "page": page,
            "filter_artificial": filter_artificial
        })
    
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
        
        return templates.TemplateResponse("artist.html", {
            "request": request,
            "artist": artist,
            "decisions": decisions,
            "override": override,
            "plays": plays
        })
    
    @app.post("/override/{artist_id}")
    async def set_override_form(
        artist_id: str,
        is_artificial: bool = Form(...),
        reason: str = Form(None)
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
        return {
            "current_track": monitor.current_track,
            "last_decision": monitor.last_decision if hasattr(monitor, 'last_decision') else None
        }
    
    return app


def run_web_ui(database, classifier, spotify_client, monitor, 
               host: str = "127.0.0.1", port: int = 8890):
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
