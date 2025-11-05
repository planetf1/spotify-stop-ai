"""Main entry point for Spotify Stop AI."""
import asyncio
import logging
import sys
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

from spotify_stop_ai.database import Database
from spotify_stop_ai.spotify_client import SpotifyClient
from spotify_stop_ai.classifier import ArtistClassifier
from spotify_stop_ai.monitor import PlaybackMonitor
from spotify_stop_ai.api import run_api

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file.
    
    Args:
        config_path: Path to config file
        
    Returns:
        Configuration dict
    """
    # Load environment variables
    load_dotenv()
    
    # Load config file
    if not os.path.exists(config_path):
        logger.error(f"Config file not found: {config_path}")
        logger.info("Please copy config.example.yaml to config.yaml and configure it")
        sys.exit(1)
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Replace environment variable placeholders
    def replace_env_vars(obj):
        """Recursively replace ${VAR} with environment variables."""
        if isinstance(obj, dict):
            return {k: replace_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [replace_env_vars(item) for item in obj]
        elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            var_name = obj[2:-1]
            value = os.getenv(var_name)
            if not value:
                logger.warning(f"Environment variable not set: {var_name}")
            return value
        else:
            return obj
    
    config = replace_env_vars(config)
    
    return config


async def main():
    """Main entry point."""
    logger.info("Starting Spotify Stop AI...")
    
    # Load configuration
    config = load_config()
    
    # Set log level from config
    log_level = config.get("logging", {}).get("level", "INFO")
    logging.getLogger().setLevel(getattr(logging, log_level))
    
    # Initialize database
    db_path = config["database"]["path"]
    logger.info(f"Initializing database: {db_path}")
    database = Database(db_path)
    await database.initialize()
    
    # Initialize Spotify client
    logger.info("Initializing Spotify client...")
    spotify_client = SpotifyClient(
        client_id=config["spotify"]["client_id"],
        redirect_uri=config["spotify"]["redirect_uri"],
        cache_path=config["spotify"]["cache_path"]
    )
    
    # Authenticate
    if not spotify_client.authenticate():
        logger.error("Spotify authentication failed")
        sys.exit(1)
    
    # Check for active devices
    devices = spotify_client.get_devices()
    if not devices or not devices.get("devices"):
        logger.warning(
            "No active Spotify devices found. Please open Spotify on a device "
            "to enable playback control."
        )
    else:
        active_devices = [d for d in devices["devices"] if d.get("is_active")]
        if active_devices:
            logger.info(f"Active device: {active_devices[0]['name']}")
        else:
            logger.info(
                f"Available devices: {', '.join(d['name'] for d in devices['devices'])}"
            )
    
    # Initialize classifier
    logger.info("Initializing classifier...")
    classifier = ArtistClassifier(config, database)
    
    # Initialize monitor
    logger.info("Initializing playback monitor...")
    monitor = PlaybackMonitor(spotify_client, classifier, database, config)
    
    # Start API if enabled
    api_task = None
    web_ui_task = None
    api_host = config["api"]["host"]
    api_port = config["api"]["port"]
    web_ui_host = config["api"]["host"]
    web_ui_port = config.get("web_ui", {}).get("port", 8890)
    
    if config.get("api", {}).get("enabled", True):
        logger.info("Starting review API...")
        logger.info(f"Review API available at http://{api_host}:{api_port}")
        
        # Run API in background task
        async def run_api_async():
            """Run API in async context."""
            import uvicorn
            from spotify_stop_ai.api import create_api
            
            api = create_api(database, classifier)
            config_uvicorn = uvicorn.Config(
                api, host=api_host, port=api_port, log_level="info"
            )
            server = uvicorn.Server(config_uvicorn)
            await server.serve()
        
        api_task = asyncio.create_task(run_api_async())
        
        # Start Web UI
        logger.info("Starting web UI...")
        logger.info(f"Web UI available at http://{web_ui_host}:{web_ui_port}")
        
        async def run_web_ui_async():
            """Run Web UI in async context."""
            import uvicorn
            from spotify_stop_ai.web_ui import create_web_ui
            
            app = create_web_ui(database, classifier, spotify_client, monitor)
            config_uvicorn = uvicorn.Config(
                app, host=web_ui_host, port=web_ui_port, log_level="info"
            )
            server = uvicorn.Server(config_uvicorn)
            await server.serve()
        
        web_ui_task = asyncio.create_task(run_web_ui_async())
    
    # Print startup info
    if api_task and web_ui_task:
        print("\n" + "="*60)
        print("🎵 Spotify Stop AI - Running")
        print("="*60)
        print(f"📊 Web UI:  http://{web_ui_host}:{web_ui_port}")
        print(f"🔌 API:     http://{api_host}:{api_port}/docs")
        print("="*60 + "\n")
    
    # Start monitoring
    try:
        await monitor.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await monitor.stop()
        if api_task:
            api_task.cancel()
        if web_ui_task:
            web_ui_task.cancel()
        logger.info("Spotify Stop AI stopped")


def cli_main():
    """CLI entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
