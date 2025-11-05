"""FastAPI review API for plays and decisions."""
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Spotify Stop AI - Review API",
    description="API for reviewing plays, decisions, and managing artist overrides",
    version="0.1.0"
)


def create_api(database, classifier):
    """Create FastAPI app with database and classifier instances.
    
    Args:
        database: Database instance
        classifier: ArtistClassifier instance
        
    Returns:
        FastAPI app
    """
    
    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "message": "Spotify Stop AI Review API",
            "version": "0.1.0",
            "endpoints": {
                "plays": "/plays",
                "decisions": "/decisions",
                "overrides": "/overrides",
                "artists": "/artists/{artist_id}"
            }
        }
    
    @app.get("/plays")
    async def get_plays(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0)
    ):
        """Get recent plays.
        
        Args:
            limit: Maximum number of plays to return
            offset: Offset for pagination
            
        Returns:
            List of plays
        """
        try:
            plays = await database.get_plays(limit=limit, offset=offset)
            return JSONResponse(content={
                "plays": plays,
                "count": len(plays),
                "limit": limit,
                "offset": offset
            })
        except Exception as e:
            logger.error(f"Failed to get plays: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/decisions")
    async def get_decisions(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0)
    ):
        """Get recent decisions.
        
        Args:
            limit: Maximum number of decisions to return
            offset: Offset for pagination
            
        Returns:
            List of decisions
        """
        try:
            decisions = await database.get_decisions(limit=limit, offset=offset)
            return JSONResponse(content={
                "decisions": decisions,
                "count": len(decisions),
                "limit": limit,
                "offset": offset
            })
        except Exception as e:
            logger.error(f"Failed to get decisions: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/overrides")
    async def get_all_overrides():
        """Get all artist overrides.
        
        Returns:
            List of overrides
        """
        try:
            # Query overrides table
            async with database.db.execute(
                "SELECT * FROM overrides ORDER BY timestamp DESC"
            ) as cursor:
                rows = await cursor.fetchall()
                overrides = [dict(row) for row in rows]
            
            return JSONResponse(content={
                "overrides": overrides,
                "count": len(overrides)
            })
        except Exception as e:
            logger.error(f"Failed to get overrides: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/overrides/{artist_id}")
    async def get_override(artist_id: str):
        """Get override for specific artist.
        
        Args:
            artist_id: Spotify artist ID
            
        Returns:
            Override dict or 404
        """
        try:
            override = await database.get_override(artist_id)
            if override:
                return JSONResponse(content=override)
            else:
                raise HTTPException(status_code=404, detail="Override not found")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get override: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/overrides/{artist_id}")
    async def set_override(
        artist_id: str,
        is_artificial: bool,
        reason: Optional[str] = None
    ):
        """Set override for artist.
        
        Args:
            artist_id: Spotify artist ID
            is_artificial: Whether artist is artificial
            reason: Optional reason for override
            
        Returns:
            Success message
        """
        try:
            await database.set_override(artist_id, is_artificial, reason)
            logger.info(
                f"Set override for artist {artist_id}: "
                f"is_artificial={is_artificial}, reason={reason}"
            )
            return JSONResponse(content={
                "message": "Override set successfully",
                "artist_id": artist_id,
                "is_artificial": is_artificial,
                "reason": reason
            })
        except Exception as e:
            logger.error(f"Failed to set override: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.delete("/overrides/{artist_id}")
    async def delete_override(artist_id: str):
        """Delete override for artist.
        
        Args:
            artist_id: Spotify artist ID
            
        Returns:
            Success message
        """
        try:
            await database.delete_override(artist_id)
            logger.info(f"Deleted override for artist {artist_id}")
            return JSONResponse(content={
                "message": "Override deleted successfully",
                "artist_id": artist_id
            })
        except Exception as e:
            logger.error(f"Failed to delete override: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/artists/{artist_id}")
    async def get_artist_info(artist_id: str):
        """Get artist information and decisions.
        
        Args:
            artist_id: Spotify artist ID
            
        Returns:
            Artist info with decisions
        """
        try:
            # Get artist record
            async with database.db.execute(
                "SELECT * FROM artists WHERE id = ?", (artist_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Artist not found")
                artist = dict(row)
            
            # Get decisions for artist
            async with database.db.execute(
                """SELECT * FROM decisions 
                   WHERE artist_id = ? 
                   ORDER BY timestamp DESC 
                   LIMIT 10""",
                (artist_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                decisions = [dict(row) for row in rows]
            
            # Get override
            override = await database.get_override(artist_id)
            
            return JSONResponse(content={
                "artist": artist,
                "decisions": decisions,
                "override": override
            })
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get artist info: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/classify/{artist_id}")
    async def reclassify_artist(artist_id: str, artist_name: str):
        """Manually trigger reclassification of artist.
        
        Args:
            artist_id: Spotify artist ID
            artist_name: Artist name
            
        Returns:
            Classification decision
        """
        try:
            decision = await classifier.classify_artist(artist_id, artist_name)
            return JSONResponse(content=decision)
        except Exception as e:
            logger.error(f"Failed to classify artist: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    return app


def run_api(database, classifier, host: str = "127.0.0.1", port: int = 8889):
    """Run the FastAPI server.
    
    Args:
        database: Database instance
        classifier: ArtistClassifier instance
        host: Host to bind to
        port: Port to bind to
    """
    import uvicorn
    
    api = create_api(database, classifier)
    uvicorn.run(api, host=host, port=port, log_level="info")
