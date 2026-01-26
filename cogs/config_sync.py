"""
Config Sync - Escucha cambios de configuración desde el dashboard
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from core import cache

if TYPE_CHECKING:
    from bot import TyrBot

logger = logging.getLogger(__name__)


class ConfigSync(commands.Cog):
    """🔄 Sincronización de configuración con el Dashboard"""
    
    emoji = "🔄"
    
    def __init__(self, bot: TyrBot):
        self.bot = bot
        self.pubsub = None
        self._running = False
    
    async def cog_load(self):
        """Iniciar listener cuando se carga el cog"""
        self.listen_config_updates.start()
    
    async def cog_unload(self):
        """Detener listener cuando se descarga el cog"""
        self._running = False
        self.listen_config_updates.cancel()
        if self.pubsub:
            await self.pubsub.unsubscribe()
            await self.pubsub.close()
    
    @tasks.loop(seconds=1)
    async def listen_config_updates(self):
        """Escuchar actualizaciones de configuración desde Redis pub/sub"""
        if not self._running:
            # Inicializar pubsub
            self.pubsub = await cache.subscribe_config_updates()
            if self.pubsub:
                self._running = True
                logger.info("📡 Escuchando actualizaciones de configuración desde dashboard")
            else:
                # Redis no disponible, reintentar después
                await asyncio.sleep(30)
                return
        
        if not self.pubsub:
            return
        
        try:
            message = await asyncio.wait_for(
                self.pubsub.get_message(ignore_subscribe_messages=True),
                timeout=0.5
            )
            
            if message and message.get("type") == "message":
                await self.handle_config_update(message["data"])
                
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error(f"Error en listener de config: {e}")
            self._running = False
            if self.pubsub:
                try:
                    await self.pubsub.unsubscribe()
                    await self.pubsub.close()
                except:
                    pass
                self.pubsub = None
    
    @listen_config_updates.before_loop
    async def before_listen(self):
        await self.bot.wait_until_ready()
    
    async def handle_config_update(self, data: str):
        """Manejar una actualización de configuración"""
        try:
            update = json.loads(data)
            guild_id = update.get("guild_id")
            config_type = update.get("type")
            
            if not guild_id or not config_type:
                return
            
            logger.info(f"📥 Config update recibida: {config_type} para guild {guild_id}")
            
            # Invalidar cache en Redis
            await cache.invalidate_guild_config(guild_id, config_type)
            
            # Invalidar cache en memoria de los cogs
            await self.invalidate_cog_cache(guild_id, config_type)
            
        except json.JSONDecodeError:
            logger.error(f"Error decodificando config update: {data}")
        except Exception as e:
            logger.error(f"Error manejando config update: {e}")
    
    async def invalidate_cog_cache(self, guild_id: int, config_type: str):
        """Invalidar cache en memoria de los cogs"""
        
        # Mapeo de tipo de config a nombre del cog y atributo de cache
        cache_mappings = {
            "antinuke": ("Antinuke", "_settings_cache"),
            "antiraid": ("Antiraid", "_settings_cache"),
            "welcome": ("Welcome", "_settings_cache"),
            "goodbye": ("Welcome", "_goodbye_cache"),  # Welcome maneja ambos
            "logging": ("Logging", "_log_channels"),
            "levels": ("Levels", "_settings_cache"),
            "starboard": ("Starboard", "_settings_cache"),
            "filter": ("Filter", "_settings_cache"),
            "autoroles": ("Autorole", "_cache"),
        }
        
        mapping = cache_mappings.get(config_type)
        if not mapping:
            return
        
        cog_name, cache_attr = mapping
        cog = self.bot.get_cog(cog_name)
        
        if cog:
            # Intentar limpiar el cache del cog
            if hasattr(cog, cache_attr):
                cog_cache = getattr(cog, cache_attr)
                if isinstance(cog_cache, dict) and guild_id in cog_cache:
                    del cog_cache[guild_id]
                    logger.debug(f"🗑️ Cache de {cog_name} invalidado para guild {guild_id}")
            
            # Método alternativo: llamar a un método de invalidación si existe
            if hasattr(cog, "invalidate_cache"):
                await cog.invalidate_cache(guild_id)
                logger.debug(f"🗑️ Cache de {cog_name} invalidado via método")


async def setup(bot: TyrBot):
    await bot.add_cog(ConfigSync(bot))
