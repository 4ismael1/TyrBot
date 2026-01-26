"""
Configuración centralizada del bot
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Clase de configuración del bot"""
    
    # Discord
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    BOT_OWNER_ID: int = int(os.getenv("BOT_OWNER_ID", "0"))
    DEFAULT_PREFIX: str = os.getenv("DEFAULT_PREFIX", ";")
    
    # MongoDB
    MONGODB_URI: str = os.getenv("MONGODB_URI", "")
    DATABASE: str = os.getenv("DATABASE", "Tyr")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    
    # APIs
    TWITCH_CLIENT_ID: str = os.getenv("TWITCH_CLIENT_ID", "")
    TWITCH_CLIENT_SECRET: str = os.getenv("TWITCH_CLIENT_SECRET", "")
    SPOTIFY_CLIENT_ID: str = os.getenv("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    LASTFM_API_KEY: str = os.getenv("LASTFM_API_KEY", "")
    
    # Colors
    SUCCESS_COLOR: int = 0x43B581
    ERROR_COLOR: int = 0xA90F25
    WARNING_COLOR: int = 0xF3DD6C
    BLURPLE_COLOR: int = 0x5865F2
    
    # Emojis
    SUCCESS_EMOJI: str = "✅"
    ERROR_EMOJI: str = "❌"
    WARNING_EMOJI: str = "⚠️"
    LOADING_EMOJI: str = "⏳"


config = Config()
