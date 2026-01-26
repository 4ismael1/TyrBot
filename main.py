"""
Tyr Discord Bot - Main Entry Point
Bot de Discord multipropósito con sistema antinuke, moderación, VoiceMaster y más.

Python 3.11+ | discord.py 2.3+
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import discord
from aiohttp import ClientSession, TCPConnector
from discord.ext import commands
from colorama import Fore, init as colorama_init

from config import config
from core.database import database
from core.cache import cache

# Inicializar colorama para Windows
colorama_init()

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format=f"{Fore.LIGHTRED_EX}[{Fore.RESET}{Fore.BLUE}%(asctime)s{Fore.RESET}{Fore.LIGHTRED_EX}]{Fore.RESET} {Fore.GREEN}→{Fore.RESET} {Fore.LIGHTCYAN_EX}%(message)s{Fore.RESET}",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)

logger = logging.getLogger(__name__)


class TyrBot(commands.AutoShardedBot):
    """Bot principal Tyr"""
    
    def __init__(self):
        intents = discord.Intents.all()
        
        super().__init__(
            command_prefix=self.get_prefix,
            help_command=None,  # Usaremos un help command personalizado
            case_insensitive=True,
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Starting up..."
            ),
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                roles=False,
                replied_user=True
            )
        )
        
        # Propiedades del bot
        self.start_time: float = time.time()
        self.owner_ids: set[int] = {config.BOT_OWNER_ID}
        self.http_session: Optional[ClientSession] = None
        
        # Referencias a database y cache
        self.db = database
        self.cache = cache
        
        # Cooldown global
        self.global_cooldown = commands.CooldownMapping.from_cooldown(
            3, 5, commands.BucketType.member
        )
        
        # Cache de prefijos en memoria
        self._prefix_cache: dict[int, str] = {}
    
    async def get_prefix(self, message: discord.Message) -> list[str]:
        """Obtener el prefijo para un servidor"""
        if message.guild is None:
            return commands.when_mentioned_or(config.DEFAULT_PREFIX)(self, message)
        
        guild_id = message.guild.id
        
        # Intentar obtener de caché en memoria
        if guild_id in self._prefix_cache:
            prefix = self._prefix_cache[guild_id]
            return commands.when_mentioned_or(prefix)(self, message)
        
        # Intentar obtener de Redis
        prefix = await cache.get_prefix(guild_id)
        
        if prefix is None:
            # Obtener de MongoDB
            data = await database.prefixes.find_one({"guild_id": guild_id})
            
            if data:
                prefix = data["prefix"]
            else:
                # Insertar prefijo por defecto
                prefix = config.DEFAULT_PREFIX
                await database.prefixes.insert_one({
                    "guild_id": guild_id,
                    "prefix": prefix
                })
            
            # Guardar en Redis
            await cache.set_prefix(guild_id, prefix)
        
        # Guardar en caché de memoria
        self._prefix_cache[guild_id] = prefix
        
        return commands.when_mentioned_or(prefix)(self, message)
    
    async def setup_hook(self) -> None:
        """Configuración inicial del bot"""
        logger.info("🔧 Iniciando configuración del bot...")
        
        # Conectar a bases de datos
        await database.connect()
        await cache.connect()
        
        # Crear sesión HTTP
        self.http_session = ClientSession(
            connector=TCPConnector(limit=100)
        )
        
        # Cargar extensiones
        await self.load_extensions()
        
        logger.info("✅ Configuración completada")
    
    async def load_extensions(self) -> None:
        """Cargar todas las extensiones (cogs)"""
        cogs_dir = Path("cogs")
        
        if not cogs_dir.exists():
            logger.warning("⚠️ Directorio 'cogs' no encontrado")
            return
        
        loaded = 0
        failed = 0
        
        for cog_file in cogs_dir.glob("*.py"):
            if cog_file.name.startswith("_"):
                continue
            
            cog_name = f"cogs.{cog_file.stem}"
            
            try:
                await self.load_extension(cog_name)
                logger.info(f"{Fore.LIGHTGREEN_EX}✓ Cargado: {cog_name}{Fore.RESET}")
                loaded += 1
            except Exception as e:
                logger.error(f"{Fore.RED}✗ Error cargando {cog_name}: {e}{Fore.RESET}")
                failed += 1
        
        # Cargar Jishaku para debugging
        try:
            await self.load_extension("jishaku")
            logger.info(f"{Fore.LIGHTGREEN_EX}✓ Cargado: jishaku{Fore.RESET}")
            loaded += 1
        except Exception as e:
            logger.warning(f"⚠️ No se pudo cargar jishaku: {e}")
        
        logger.info(f"📦 Extensiones: {loaded} cargadas, {failed} fallidas")
        
        # Mostrar estadísticas de listeners y comandos
        await self._log_listeners()
    
    async def _log_listeners(self) -> None:
        """Mostrar listeners y comandos registrados"""
        # Contar listeners
        listeners = {}
        for cog_name, cog in self.cogs.items():
            cog_listeners = [m for m in dir(cog) if m.startswith('on_')]
            for listener in cog_listeners:
                if callable(getattr(cog, listener, None)):
                    event_name = listener[3:]  # Quitar 'on_'
                    if event_name not in listeners:
                        listeners[event_name] = []
                    listeners[event_name].append(cog_name)
        
        # Log de listeners
        logger.info(f"{Fore.CYAN}📡 Listeners registrados:{Fore.RESET}")
        for event, cogs in sorted(listeners.items()):
            logger.info(f"   {Fore.YELLOW}→ {Fore.RESET}Listening to {Fore.GREEN}{event}{Fore.RESET} ({len(cogs)} cogs)")
        
        # Contar comandos
        total_commands = len(list(self.walk_commands()))
        slash_commands = len(self.tree.get_commands())
        
        logger.info(f"{Fore.CYAN}⚡ Comandos registrados:{Fore.RESET}")
        logger.info(f"   {Fore.YELLOW}→ {Fore.RESET}Prefix commands: {Fore.GREEN}{total_commands}{Fore.RESET}")
        logger.info(f"   {Fore.YELLOW}→ {Fore.RESET}Slash commands: {Fore.GREEN}{slash_commands}{Fore.RESET}")
    
    async def on_ready(self) -> None:
        """Evento cuando el bot está listo"""
        logger.info(f"{'=' * 50}")
        logger.info(f"🤖 Bot conectado como: {self.user} ({self.user.id})")
        logger.info(f"📊 Servidores: {len(self.guilds)}")
        logger.info(f"👥 Usuarios: {sum(g.member_count for g in self.guilds if g.member_count):,}")
        logger.info(f"🔗 Shards: {self.shard_count or 1}")
        logger.info(f"{'=' * 50}")
        
        # Cachear estadísticas en Redis
        guild_count = len(self.guilds)
        user_count = sum(g.member_count or 0 for g in self.guilds)
        await self.cache.update_guild_count(guild_count)
        await self.cache.update_user_count(user_count)
        logger.info(f"📊 Stats cached: {guild_count} guilds, {user_count} users")
        
        # Cargar blacklist a Redis
        blacklist_docs = await database.blacklist.find().to_list(length=None)
        blacklist_ids = [doc["user_id"] for doc in blacklist_docs]
        await self.cache.load_blacklist(blacklist_ids)
        logger.info(f"🚫 Blacklist loaded to Redis ({len(blacklist_ids)} users)")
        
        # Actualizar actividad
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{guild_count} servidores | ;help"
            )
        )
    
    async def on_message(self, message: discord.Message) -> None:
        """Procesar mensajes"""
        # Ignorar bots
        if message.author.bot:
            return
        
        # Ignorar DMs (opcional)
        if message.guild is None:
            return
        
        # Verificar blacklist (desde Redis)
        if await self.cache.is_blacklisted(message.author.id):
            return
        
        # Actualizar last seen en Redis
        await self.cache.set_last_seen(message.author.id, message.guild.id)
        
        # Procesar comandos
        await self.process_commands(message)
    
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        """Re-procesar comandos en mensajes editados"""
        if before.content != after.content:
            await self.process_commands(after)
    
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Actualizar caché cuando el bot se une a un servidor"""
        guild_count = len(self.guilds)
        user_count = sum(g.member_count or 0 for g in self.guilds)
        await self.cache.update_guild_count(guild_count)
        await self.cache.update_user_count(user_count)
        logger.info(f"📥 Joined guild: {guild.name} ({guild.id}) | Total: {guild_count}")
    
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Actualizar caché cuando el bot sale de un servidor"""
        guild_count = len(self.guilds)
        user_count = sum(g.member_count or 0 for g in self.guilds)
        await self.cache.update_guild_count(guild_count)
        await self.cache.update_user_count(user_count)
        logger.info(f"📤 Left guild: {guild.name} ({guild.id}) | Total: {guild_count}")
    
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Manejador global de errores de comandos"""
        # Ignorar errores de comandos no encontrados
        if isinstance(error, commands.CommandNotFound):
            return
        
        # Errores de cooldown
        if isinstance(error, commands.CommandOnCooldown):
            embed = discord.Embed(
                description=f"⏳ Comando en cooldown. Intenta de nuevo en **{error.retry_after:.1f}s**",
                color=config.WARNING_COLOR
            )
            await ctx.send(embed=embed, delete_after=5)
            return
        
        # Errores de permisos
        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(f"`{p}`" for p in error.missing_permissions)
            embed = discord.Embed(
                description=f"❌ Te faltan permisos: {perms}",
                color=config.ERROR_COLOR
            )
            await ctx.send(embed=embed, delete_after=10)
            return
        
        if isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(f"`{p}`" for p in error.missing_permissions)
            embed = discord.Embed(
                description=f"❌ Me faltan permisos: {perms}",
                color=config.ERROR_COLOR
            )
            await ctx.send(embed=embed, delete_after=10)
            return
        
        # Errores de argumentos
        if isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                description=f"❌ Falta el argumento: `{error.param.name}`",
                color=config.ERROR_COLOR
            )
            await ctx.send(embed=embed, delete_after=10)
            return
        
        if isinstance(error, commands.BadArgument):
            embed = discord.Embed(
                description=f"❌ Argumento inválido: {error}",
                color=config.ERROR_COLOR
            )
            await ctx.send(embed=embed, delete_after=10)
            return
        
        # Errores de checks
        if isinstance(error, commands.CheckFailure):
            embed = discord.Embed(
                description="❌ No tienes permiso para usar este comando",
                color=config.ERROR_COLOR
            )
            await ctx.send(embed=embed, delete_after=10)
            return
        
        # Error no manejado - log
        logger.error(f"Error en comando {ctx.command}: {error}", exc_info=error)
    
    async def close(self) -> None:
        """Cerrar conexiones al apagar el bot"""
        logger.info("🔌 Cerrando conexiones...")
        
        # Cerrar sesión HTTP
        if self.http_session:
            await self.http_session.close()
        
        # Desconectar bases de datos
        await cache.disconnect()
        await database.disconnect()
        
        await super().close()
        logger.info("👋 Bot desconectado")


async def main() -> None:
    """Función principal"""
    bot = TyrBot()
    
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    # Configurar variables de entorno para Jishaku
    os.environ["JISHAKU_NO_UNDERSCORE"] = "true"
    os.environ["JISHAKU_NO_DM_TRACEBACK"] = "true"
    os.environ["JISHAKU_HIDE"] = "true"
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Bot detenido por el usuario")
    except Exception as e:
        logger.critical(f"💥 Error crítico: {e}", exc_info=True)
