"""
Cog AFK - Sistema de estado AFK
"""

from __future__ import annotations

import discord
from discord.ext import commands, tasks
import time
import humanize

from config import config
from core import database, cache
from utils import success_embed, error_embed


class AFK(commands.Cog):
    """💤 Sistema de estado AFK (Away From Keyboard)"""
    
    emoji = "💤"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache local de AFKs
        self._afk_cache: dict[tuple[int, int], dict] = {}  # (guild_id, user_id) -> data
        self.sync_cache.start()
    
    def cog_unload(self):
        self.sync_cache.cancel()
    
    @tasks.loop(minutes=5)
    async def sync_cache(self):
        """Sincronizar caché de AFKs"""
        async for doc in database.afk.find({}):
            key = (doc["guild_id"], doc["user_id"])
            self._afk_cache[key] = doc
    
    @sync_cache.before_loop
    async def before_sync(self):
        await self.bot.wait_until_ready()
    
    async def get_afk(self, guild_id: int, user_id: int) -> dict | None:
        """Obtener estado AFK de un usuario"""
        key = (guild_id, user_id)
        
        # Cache local
        if key in self._afk_cache:
            return self._afk_cache[key]
        
        # Redis
        cached = await cache.get_afk(guild_id, user_id)
        if cached:
            self._afk_cache[key] = cached
            return cached
        
        # MongoDB
        doc = await database.afk.find_one({
            "guild_id": guild_id,
            "user_id": user_id
        })
        
        if doc:
            self._afk_cache[key] = doc
            await cache.set_afk(guild_id, user_id, doc["reason"], doc["timestamp"])
        
        return doc
    
    async def set_afk(self, guild_id: int, user_id: int, reason: str) -> None:
        """Establecer estado AFK"""
        timestamp = int(time.time())
        
        await database.afk.update_one(
            {"guild_id": guild_id, "user_id": user_id},
            {
                "$set": {
                    "guild_id": guild_id,
                    "user_id": user_id,
                    "reason": reason,
                    "timestamp": timestamp
                }
            },
            upsert=True
        )
        
        # Actualizar caches
        key = (guild_id, user_id)
        self._afk_cache[key] = {
            "guild_id": guild_id,
            "user_id": user_id,
            "reason": reason,
            "timestamp": timestamp
        }
        await cache.set_afk(guild_id, user_id, reason, timestamp)
    
    async def remove_afk(self, guild_id: int, user_id: int) -> dict | None:
        """Remover estado AFK y retornar datos anteriores"""
        key = (guild_id, user_id)
        
        # Obtener datos antes de eliminar
        old_data = self._afk_cache.pop(key, None)
        
        # Eliminar de MongoDB
        await database.afk.delete_one({
            "guild_id": guild_id,
            "user_id": user_id
        })
        
        # Eliminar de Redis
        await cache.delete_afk(guild_id, user_id)
        
        return old_data
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Detectar cuando alguien menciona a un AFK o cuando un AFK vuelve"""
        if message.author.bot or not message.guild:
            return
        
        # Verificar si el autor está AFK (volvió)
        afk_data = await self.get_afk(message.guild.id, message.author.id)
        
        if afk_data:
            old_data = await self.remove_afk(message.guild.id, message.author.id)
            
            if old_data:
                # Calcular tiempo AFK
                afk_time = int(time.time()) - old_data["timestamp"]
                time_str = humanize.naturaldelta(afk_time)
                
                embed = discord.Embed(
                    title="👋 ¡Bienvenido de vuelta!",
                    description=f"Estuviste AFK por **{time_str}**",
                    color=config.BLURPLE_COLOR,
                    timestamp=discord.utils.utcnow()
                )
                embed.set_author(
                    name=message.author.display_name,
                    icon_url=message.author.display_avatar.url
                )
                embed.set_thumbnail(url=message.author.display_avatar.url)
                
                try:
                    await message.channel.send(embed=embed, delete_after=10)
                except discord.HTTPException:
                    pass
        
        # Verificar menciones a usuarios AFK
        if message.mentions:
            for mentioned in message.mentions:
                if mentioned.bot or mentioned.id == message.author.id:
                    continue
                
                mentioned_afk = await self.get_afk(message.guild.id, mentioned.id)
                
                if mentioned_afk:
                    afk_time = int(time.time()) - mentioned_afk["timestamp"]
                    time_str = humanize.naturaldelta(afk_time)
                    reason = mentioned_afk.get("reason", "AFK")
                    
                    embed = discord.Embed(
                        title="💤 Usuario AFK",
                        description=f"**{mentioned.display_name}** no está disponible",
                        color=config.WARNING_COLOR,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_author(
                        name=mentioned.display_name,
                        icon_url=mentioned.display_avatar.url
                    )
                    embed.set_thumbnail(url=mentioned.display_avatar.url)
                    embed.add_field(name="📝 Razón", value=reason, inline=True)
                    embed.add_field(name="⏰ Desde hace", value=time_str, inline=True)
                    
                    try:
                        await message.channel.send(embed=embed, delete_after=10)
                    except discord.HTTPException:
                        pass
    
    @commands.hybrid_command(
        name="afk",
        brief="Establecer estado AFK",
        description="Establecer tu estado como AFK. El bot notificará a quienes te mencionen."
    )
    async def afk(self, ctx: commands.Context, *, reason: str = "AFK"):
        """
        Establecer tu estado como AFK (Away From Keyboard).
        
        Cuando alguien te mencione, el bot les notificará que estás AFK.
        Tu estado AFK se removerá automáticamente cuando envíes un mensaje.
        
        **Uso:** ;afk [razón]
        **Ejemplo:** ;afk Almorzando
        """
        # Verificar si ya está AFK
        existing = await self.get_afk(ctx.guild.id, ctx.author.id)
        if existing:
            return await ctx.send(
                embed=error_embed("Ya estás AFK. Envía un mensaje para quitar el estado."),
                delete_after=5
            )
        
        # Limitar longitud de razón
        if len(reason) > 100:
            reason = reason[:100] + "..."
        
        await self.set_afk(ctx.guild.id, ctx.author.id, reason)
        
        embed = discord.Embed(
            title="💤 Modo AFK Activado",
            description=f"Tu estado ha sido establecido como AFK",
            color=config.BLURPLE_COLOR,
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(
            name=ctx.author.display_name,
            icon_url=ctx.author.display_avatar.url
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.add_field(name="📝 Razón", value=reason, inline=False)
        embed.set_footer(text="Envía un mensaje para quitar el estado AFK")
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AFK(bot))
