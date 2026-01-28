"""
Sistema de base de datos MongoDB con Motor (async)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

import motor.motor_asyncio
from pymongo.errors import ConnectionFailure

from config import config

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection

logger = logging.getLogger(__name__)


class Database:
    """Clase para manejar la conexión a MongoDB"""
    
    _instance: Optional[Database] = None
    _client: Optional[AsyncIOMotorClient] = None
    _db: Optional[AsyncIOMotorDatabase] = None
    
    def __new__(cls) -> Database:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def connect(self) -> None:
        """Conectar a MongoDB"""
        if self._client is not None:
            return
            
        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(
                config.MONGODB_URI,
                serverSelectionTimeoutMS=5000
            )
            # Verificar conexión
            await self._client.admin.command('ping')
            self._db = self._client[config.DATABASE]
            logger.info(f"✅ Conectado a MongoDB - Base de datos: {config.DATABASE}")
            
            # Crear índices necesarios
            await self._create_indexes()
            
        except ConnectionFailure as e:
            logger.error(f"❌ Error conectando a MongoDB: {e}")
            raise
    
    async def _create_indexes(self) -> None:
        """Crear índices para optimizar consultas"""
        try:
            # Índices para prefijos
            await self.prefixes.create_index("guild_id", unique=True)
            
            # Índices para antinuke
            await self.antinuke_servers.create_index("guild_id", unique=True)
            await self.antinuke_settings.create_index("guild_id", unique=True)
            await self.antinuke_whitelist.create_index([("guild_id", 1), ("user_id", 1)])
            
            # Índices para welcome/goodbye
            await self.welcome.create_index("guild_id", unique=True)
            await self.goodbye.create_index("guild_id", unique=True)
            
            # Índices para VoiceMaster
            await self.voicemaster_guilds.create_index("guild_id", unique=True)
            await self.voicemaster_channels.create_index([("guild_id", 1), ("channel_id", 1)])
            
            # Índices para AFK
            await self.afk.create_index([("guild_id", 1), ("user_id", 1)], unique=True)
            
            # Índices para tags
            await self.tags.create_index([("guild_id", 1), ("name", 1)], unique=True)
            
            # Índices para autoresponder
            await self.autoresponder.create_index([("guild_id", 1), ("trigger", 1)])
            
            # Índices para moderación
            await self.warnings.create_index([("guild_id", 1), ("user_id", 1)])
            await self.modlogs.create_index([("guild_id", 1), ("case_id", 1)])

            # Índices para licencias
            await self.licenses.create_index("key", unique=True)
            await self.licenses.create_index("guild_id")
            
            logger.info("✅ Índices de MongoDB creados correctamente")
            
        except Exception as e:
            logger.warning(f"⚠️ Error creando índices: {e}")
    
    async def disconnect(self) -> None:
        """Desconectar de MongoDB"""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("🔌 Desconectado de MongoDB")
    
    @property
    def client(self) -> AsyncIOMotorClient:
        if self._client is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._client
    
    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db
    
    # ========== Colecciones ==========
    
    @property
    def prefixes(self) -> AsyncIOMotorCollection:
        """Colección de prefijos por servidor"""
        return self.db["prefixes"]
    
    @property
    def guilds(self) -> AsyncIOMotorCollection:
        """Colección de configuración de servidores"""
        return self.db["guilds"]
    
    # Antinuke
    @property
    def antinuke_servers(self) -> AsyncIOMotorCollection:
        return self.db["antinuke_servers"]
    
    @property
    def antinuke_settings(self) -> AsyncIOMotorCollection:
        return self.db["antinuke_settings"]
    
    @property
    def antinuke_whitelist(self) -> AsyncIOMotorCollection:
        return self.db["antinuke_whitelist"]
    
    @property
    def antinuke_logs(self) -> AsyncIOMotorCollection:
        return self.db["antinuke_logs"]
    
    # Welcome/Goodbye
    @property
    def welcome(self) -> AsyncIOMotorCollection:
        return self.db["welcome"]
    
    @property
    def goodbye(self) -> AsyncIOMotorCollection:
        return self.db["goodbye"]
    
    # VoiceMaster
    @property
    def voicemaster_guilds(self) -> AsyncIOMotorCollection:
        return self.db["voicemaster_guilds"]
    
    @property
    def voicemaster_channels(self) -> AsyncIOMotorCollection:
        return self.db["voicemaster_channels"]
    
    # AFK
    @property
    def afk(self) -> AsyncIOMotorCollection:
        return self.db["afk"]
    
    # Tags
    @property
    def tags(self) -> AsyncIOMotorCollection:
        return self.db["tags"]
    
    # Autoresponder
    @property
    def autoresponder(self) -> AsyncIOMotorCollection:
        return self.db["autoresponder"]
    
    # Moderación
    @property
    def warnings(self) -> AsyncIOMotorCollection:
        return self.db["warnings"]
    
    @property
    def modlogs(self) -> AsyncIOMotorCollection:
        return self.db["modlogs"]

    # Licencias
    @property
    def licenses(self) -> AsyncIOMotorCollection:
        return self.db["licenses"]
    
    @property
    def quarantine(self) -> AsyncIOMotorCollection:
        """Usuarios en cuarentena con sus roles guardados"""
        return self.db["quarantine"]
    
    @property
    def command_status(self) -> AsyncIOMotorCollection:
        """Comandos deshabilitados por servidor"""
        return self.db["command_status"]
    
    # LastFM
    @property
    def lastfm(self) -> AsyncIOMotorCollection:
        return self.db["lastfm"]
    
    @property
    def lastfm_reactions(self) -> AsyncIOMotorCollection:
        return self.db["lastfm_reactions"]
    
    # Autoroles
    @property
    def autoroles(self) -> AsyncIOMotorCollection:
        return self.db["autoroles"]
    
    # Reaction Roles
    @property
    def reaction_roles(self) -> AsyncIOMotorCollection:
        return self.db["reaction_roles"]
    
    # Blacklist (usuarios baneados del bot)
    @property
    def blacklist(self) -> AsyncIOMotorCollection:
        return self.db["blacklist"]
    
    # ========== Nuevas colecciones de seguridad y utilidades ==========
    
    # Antiraid
    @property
    def antiraid(self) -> AsyncIOMotorCollection:
        return self.db["antiraid"]
    
    # Filter settings (invites, links, words)
    @property
    def filter_settings(self) -> AsyncIOMotorCollection:
        return self.db["filter_settings"]
    
    # Autoroles (nuevo)
    @property
    def autorole(self) -> AsyncIOMotorCollection:
        return self.db["autorole"]
    
    # Reaction roles
    @property
    def reactionroles(self) -> AsyncIOMotorCollection:
        return self.db["reactionroles"]
    
    # Join DM
    @property
    def joindm(self) -> AsyncIOMotorCollection:
        return self.db["joindm"]
    
    # Force Nickname
    @property
    def forcenick(self) -> AsyncIOMotorCollection:
        return self.db["forcenick"]
    
    # Fake Permissions
    @property
    def fakeperms(self) -> AsyncIOMotorCollection:
        return self.db["fakeperms"]
    
    # Sticky Messages
    @property
    def stickies(self) -> AsyncIOMotorCollection:
        return self.db["stickies"]
    
    # Giveaways
    @property
    def giveaways(self) -> AsyncIOMotorCollection:
        return self.db["giveaways"]
    
    # Tickets
    @property
    def tickets(self) -> AsyncIOMotorCollection:
        return self.db["tickets"]
    
    @property
    def ticket_settings(self) -> AsyncIOMotorCollection:
        return self.db["ticket_settings"]
    
    # VoiceMaster (mejorado)
    @property
    def voicemaster(self) -> AsyncIOMotorCollection:
        return self.db["voicemaster"]
    
    @property
    def temp_voice(self) -> AsyncIOMotorCollection:
        return self.db["temp_voice"]
    
    # Starboard
    @property
    def starboard(self) -> AsyncIOMotorCollection:
        return self.db["starboard"]
    
    @property
    def starboard_messages(self) -> AsyncIOMotorCollection:
        return self.db["starboard_messages"]
    
    # Levels
    @property
    def levels(self) -> AsyncIOMotorCollection:
        return self.db["levels"]
    
    @property
    def level_settings(self) -> AsyncIOMotorCollection:
        return self.db["level_settings"]
    
    # Booster
    @property
    def booster_settings(self) -> AsyncIOMotorCollection:
        return self.db["booster_settings"]
    
    @property
    def booster_roles(self) -> AsyncIOMotorCollection:
        return self.db["booster_roles"]
    
    # Reminders
    @property
    def reminders(self) -> AsyncIOMotorCollection:
        return self.db["reminders"]
    
    # Confessions
    @property
    def confession_settings(self) -> AsyncIOMotorCollection:
        return self.db["confession_settings"]
    
    @property
    def confessions(self) -> AsyncIOMotorCollection:
        return self.db["confessions"]
    
    # Verification
    @property
    def verification_settings(self) -> AsyncIOMotorCollection:
        return self.db["verification_settings"]
    
    # Logging
    @property
    def logging(self) -> AsyncIOMotorCollection:
        return self.db["logging"]


# Instancia global
database = Database()
