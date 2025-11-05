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
        
        # Get recent plays
        plays = await database.get_plays(limit=10)
        
        # Get recent decisions with contexts
        decisions_raw = await database.get_decisions(limit=10)
        
        # Enrich decisions with context counts
        decisions = []
        for decision in decisions_raw:
            # Get context count for this decision
            async with database.db.execute(
                "SELECT COUNT(*) as count FROM decision_contexts WHERE decision_id = ?",
                (decision['id'],)
            ) as cursor:
                row = await cursor.fetchone()
                context_count = dict(row)['count'] if row else 0
            
            decision['context_count'] = context_count
            decisions.append(decision)
        
        return templates.TemplateResponse("index.html", {
            "request": request,
            "current_track": current_track,
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
            async with database.db.execute(
                """SELECT p.*, a.name as artist_name, t.name as track_name
                   FROM plays p
                   JOIN artists a ON p.artist_id = a.id
                   JOIN tracks t ON p.track_id = t.id
                   WHERE a.name LIKE ? OR t.name LIKE ?
                   ORDER BY p.timestamp DESC
                   LIMIT ? OFFSET ?""",
                (f"%{search}%", f"%{search}%", limit, offset)
            ) as cursor:
                rows = await cursor.fetchall()
                plays = [dict(row) for row in rows]
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
            async with database.db.execute(
                """SELECT d.*, a.name as artist_name
                   FROM decisions d
                   JOIN artists a ON d.artist_id = a.id
                   WHERE d.is_artificial = ?
                   ORDER BY d.timestamp DESC
                   LIMIT ? OFFSET ?""",
                (filter_artificial, limit, offset)
            ) as cursor:
                rows = await cursor.fetchall()
                decisions = [dict(row) for row in rows]
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
        async with database.db.execute(
            "SELECT * FROM artists WHERE id = ?", (artist_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return HTMLResponse("Artist not found", status_code=404)
            artist = dict(row)
        
        # Get all decisions with contexts
        async with database.db.execute(
            """SELECT d.*, c.source_name, c.result, c.signals, c.tags, c.url
               FROM decisions d
               LEFT JOIN decision_contexts c ON d.id = c.decision_id
               WHERE d.artist_id = ?
               ORDER BY d.timestamp DESC""",
            (artist_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            
            # Group contexts by decision
            decisions_map = {}
            for row in rows:
                row_dict = dict(row)
                decision_id = row_dict['id']
                
                if decision_id not in decisions_map:
                    decisions_map[decision_id] = {
                        'id': row_dict['id'],
                        'timestamp': row_dict['timestamp'],
                        'label': row_dict['label'],
                        'is_artificial': row_dict['is_artificial'],
                        'confidence': row_dict['confidence'],
                        'reason': row_dict['reason'],
                        'citations': row_dict['citations'],
                        'contexts': []
                    }
                
                if row_dict['source_name']:
                    decisions_map[decision_id]['contexts'].append({
                        'source_name': row_dict['source_name'],
                        'result': row_dict['result'],
                        'signals': row_dict['signals'],
                        'tags': row_dict['tags'],
                        'url': row_dict['url']
                    })
            
            decisions = list(decisions_map.values())
        
        # Get override
        override = await database.get_override(artist_id)
        
        # Get plays for this artist
        async with database.db.execute(
            """SELECT p.*, t.name as track_name
               FROM plays p
               JOIN tracks t ON p.track_id = t.id
               WHERE p.artist_id = ?
               ORDER BY p.timestamp DESC
               LIMIT 20""",
            (artist_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            plays = [dict(row) for row in rows]
        
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
        """Reclassify artist from form."""
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
