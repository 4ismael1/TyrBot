"""
Cog Filter - Filtros de contenido (invites, links, imágenes, palabras)
"""

from __future__ import annotations

import asyncio
import re
import discord
from discord.ext import commands, tasks
from datetime import datetime
from typing import Optional, Literal

from config import config
from core import database, cache
from utils import success_embed, error_embed, warning_embed


# Patrones regex
INVITE_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discordapp\.com/invite)/([a-zA-Z0-9-]+)",
    re.IGNORECASE
)
LINK_PATTERN = re.compile(
    r"https?://[^\s<>\"{}|\\^`\[\]]+",
    re.IGNORECASE
)


class Filter(commands.Cog):
    """🔒 Filtros de contenido"""
    
    emoji = "🔒"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # Cache local
        self._settings_cache: dict[int, dict] = {}
        
        # Iniciar tareas
        self.sync_cache.start()
    
    def cog_unload(self):
        self.sync_cache.cancel()
    
    @tasks.loop(minutes=10)
    async def sync_cache(self):
        """Sincronizar configuraciones desde DB"""
        async for doc in database.filter_settings.find({}):
            self._settings_cache[doc["guild_id"]] = doc
    
    @sync_cache.before_loop
    async def before_sync_cache(self):
        await self.bot.wait_until_ready()
    
    async def invalidate_cache(self, guild_id: int):
        """Invalidar cache para un guild específico"""
        if guild_id in self._settings_cache:
            del self._settings_cache[guild_id]
        await cache.invalidate_filter(guild_id)
    
    async def get_settings(self, guild_id: int) -> dict:
        """Obtener configuración de filtros con caché Redis"""
        # Primero cache local
        if guild_id in self._settings_cache:
            return self._settings_cache[guild_id]
        
        # Luego Redis
        cached = await cache.get_filter_settings(guild_id)
        if cached:
            self._settings_cache[guild_id] = cached
            return cached
        
        # Finalmente base de datos
        doc = await database.filter_settings.find_one({"guild_id": guild_id})
        if doc:
            self._settings_cache[guild_id] = doc
            # Guardar en Redis (sin _id de MongoDB)
            cache_doc = {k: v for k, v in doc.items() if k != "_id"}
            await cache.set_filter_settings(guild_id, cache_doc)
            return doc
        
        return {}
    
    async def is_whitelisted(self, message: discord.Message, filter_type: str) -> bool:
        """Verificar si el canal/rol está en whitelist"""
        settings = await self.get_settings(message.guild.id)
        
        # Verificar permisos
        if message.author.guild_permissions.administrator:
            return True
        if message.author.guild_permissions.manage_messages:
            return True
        
        # Verificar whitelist de canales
        whitelist_channels = settings.get(f"{filter_type}_whitelist_channels", [])
        if message.channel.id in whitelist_channels:
            return True
        
        # Verificar whitelist de roles
        whitelist_roles = settings.get(f"{filter_type}_whitelist_roles", [])
        member_role_ids = [r.id for r in message.author.roles]
        if any(role_id in whitelist_roles for role_id in member_role_ids):
            return True
        
        return False
    
    async def log_filter(self, message: discord.Message, filter_type: str, content: str):
        """Registrar acción de filtro"""
        settings = await self.get_settings(message.guild.id)
        log_channel_id = settings.get("log_channel")
        
        if not log_channel_id:
            return
        
        channel = message.guild.get_channel(log_channel_id)
        if not channel:
            return
        
        embed = discord.Embed(
            title=f"🔒 Contenido Filtrado",
            color=config.WARNING_COLOR,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Usuario", value=f"{message.author.mention}", inline=True)
        embed.add_field(name="Canal", value=f"{message.channel.mention}", inline=True)
        embed.add_field(name="Tipo", value=filter_type.capitalize(), inline=True)
        embed.add_field(name="Contenido", value=content[:1000], inline=False)
        
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Procesar filtros en mensajes"""
        if not message.guild:
            return
        if message.author.bot:
            return
        
        settings = await self.get_settings(message.guild.id)
        if not settings:
            return
        
        # Filtro de invitaciones
        if settings.get("invite_filter_enabled"):
            if not await self.is_whitelisted(message, "invite"):
                matches = INVITE_PATTERN.findall(message.content)
                if matches:
                    try:
                        await message.delete()
                        await self.log_filter(message, "invite", message.content)
                        
                        # Advertir al usuario
                        warn_msg = await message.channel.send(
                            f"{message.author.mention}, no puedes enviar invitaciones aquí.",
                            delete_after=5
                        )
                    except discord.HTTPException:
                        pass
                    return
        
        # Filtro de links
        if settings.get("link_filter_enabled"):
            if not await self.is_whitelisted(message, "link"):
                matches = LINK_PATTERN.findall(message.content)
                if matches:
                    # Verificar whitelist de dominios
                    whitelist_domains = settings.get("link_whitelist_domains", [])
                    blocked = False
                    
                    for link in matches:
                        is_whitelisted = False
                        for domain in whitelist_domains:
                            if domain.lower() in link.lower():
                                is_whitelisted = True
                                break
                        if not is_whitelisted:
                            blocked = True
                            break
                    
                    if blocked:
                        try:
                            await message.delete()
                            await self.log_filter(message, "link", message.content)
                            
                            warn_msg = await message.channel.send(
                                f"{message.author.mention}, no puedes enviar links aquí.",
                                delete_after=5
                            )
                        except discord.HTTPException:
                            pass
                        return
        
        # Filtro de palabras prohibidas
        if settings.get("word_filter_enabled"):
            banned_words = settings.get("banned_words", [])
            content_lower = message.content.lower()
            
            for word in banned_words:
                if word.lower() in content_lower:
                    try:
                        await message.delete()
                        await self.log_filter(message, "word", f"Palabra: {word}")
                        
                        warn_msg = await message.channel.send(
                            f"{message.author.mention}, tu mensaje contenía palabras prohibidas.",
                            delete_after=5
                        )
                    except discord.HTTPException:
                        pass
                    return
        
        # Filtro de imágenes (solo imágenes en canales específicos)
        if settings.get("image_only_channels"):
            image_channels = settings.get("image_only_channels", [])
            if message.channel.id in image_channels:
                has_image = bool(message.attachments) and any(
                    a.content_type and a.content_type.startswith("image")
                    for a in message.attachments
                )
                has_embed_image = any(e.image or e.thumbnail for e in message.embeds)
                
                if not has_image and not has_embed_image:
                    try:
                        await message.delete()
                        warn_msg = await message.channel.send(
                            f"{message.author.mention}, este canal es solo para imágenes.",
                            delete_after=5
                        )
                    except discord.HTTPException:
                        pass
                    return
    
    # ========== Commands ==========
    
    @commands.group(
        name="filter",
        aliases=["filtro", "automod"],
        brief="Sistema de filtros",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_messages=True)
    async def filter(self, ctx: commands.Context):
        """Sistema de filtros de contenido"""
        settings = await self.get_settings(ctx.guild.id)
        
        embed = discord.Embed(
            title="🔒 Filtros de Contenido",
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(
            name="Filtro de Invitaciones",
            value="✅ Activo" if settings.get("invite_filter_enabled") else "❌ Inactivo",
            inline=True
        )
        embed.add_field(
            name="Filtro de Links",
            value="✅ Activo" if settings.get("link_filter_enabled") else "❌ Inactivo",
            inline=True
        )
        embed.add_field(
            name="Filtro de Palabras",
            value="✅ Activo" if settings.get("word_filter_enabled") else "❌ Inactivo",
            inline=True
        )
        
        embed.add_field(
            name="Comandos",
            value=f"`{ctx.prefix}filter invite <on/off>` - Filtro de invitaciones\n"
                  f"`{ctx.prefix}filter links <on/off>` - Filtro de links\n"
                  f"`{ctx.prefix}filter words add/remove <palabra>` - Palabras prohibidas\n"
                  f"`{ctx.prefix}filter whitelist <tipo> <canal/rol>` - Whitelist\n"
                  f"`{ctx.prefix}filter logs <canal>` - Canal de logs",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @filter.command(name="invite", aliases=["invites", "inv"])
    @commands.has_permissions(manage_messages=True)
    async def filter_invite(self, ctx: commands.Context, toggle: Literal["on", "off"]):
        """Activar/desactivar filtro de invitaciones"""
        enabled = toggle == "on"
        
        await database.filter_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"guild_id": ctx.guild.id, "invite_filter_enabled": enabled}},
            upsert=True
        )
        
        if ctx.guild.id in self._settings_cache:
            self._settings_cache[ctx.guild.id]["invite_filter_enabled"] = enabled
        else:
            self._settings_cache[ctx.guild.id] = {"guild_id": ctx.guild.id, "invite_filter_enabled": enabled}
        
        if enabled:
            await ctx.send(embed=success_embed("Filtro de invitaciones **activado**"))
        else:
            await ctx.send(embed=success_embed("Filtro de invitaciones **desactivado**"))
    
    @filter.command(name="links", aliases=["link", "urls"])
    @commands.has_permissions(manage_messages=True)
    async def filter_links(self, ctx: commands.Context, toggle: Literal["on", "off"]):
        """Activar/desactivar filtro de links"""
        enabled = toggle == "on"
        
        await database.filter_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"guild_id": ctx.guild.id, "link_filter_enabled": enabled}},
            upsert=True
        )
        
        if ctx.guild.id in self._settings_cache:
            self._settings_cache[ctx.guild.id]["link_filter_enabled"] = enabled
        else:
            self._settings_cache[ctx.guild.id] = {"guild_id": ctx.guild.id, "link_filter_enabled": enabled}
        
        if enabled:
            await ctx.send(embed=success_embed("Filtro de links **activado**"))
        else:
            await ctx.send(embed=success_embed("Filtro de links **desactivado**"))
    
    @filter.group(name="words", aliases=["word", "palabras"], invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def filter_words(self, ctx: commands.Context):
        """Gestionar palabras prohibidas"""
        settings = await self.get_settings(ctx.guild.id)
        banned = settings.get("banned_words", [])
        
        if not banned:
            return await ctx.send(embed=warning_embed("No hay palabras prohibidas"))
        
        embed = discord.Embed(
            title="🚫 Palabras Prohibidas",
            description="\n".join(f"`{i+1}.` {w}" for i, w in enumerate(banned[:20])),
            color=config.BLURPLE_COLOR
        )
        
        if len(banned) > 20:
            embed.set_footer(text=f"Y {len(banned) - 20} más...")
        
        await ctx.send(embed=embed)
    
    @filter_words.command(name="add", aliases=["agregar"])
    @commands.has_permissions(manage_messages=True)
    async def filter_words_add(self, ctx: commands.Context, *, word: str):
        """Añadir palabra prohibida"""
        word = word.lower().strip()
        
        settings = await self.get_settings(ctx.guild.id)
        banned = settings.get("banned_words", [])
        
        if word in banned:
            return await ctx.send(embed=error_embed(f"`{word}` ya está en la lista"))
        
        await database.filter_settings.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {"guild_id": ctx.guild.id, "word_filter_enabled": True},
                "$push": {"banned_words": word}
            },
            upsert=True
        )
        
        if ctx.guild.id in self._settings_cache:
            if "banned_words" not in self._settings_cache[ctx.guild.id]:
                self._settings_cache[ctx.guild.id]["banned_words"] = []
            self._settings_cache[ctx.guild.id]["banned_words"].append(word)
            self._settings_cache[ctx.guild.id]["word_filter_enabled"] = True
        
        await ctx.send(embed=success_embed(f"Palabra `{word}` añadida a la lista"))
    
    @filter_words.command(name="remove", aliases=["quitar", "del"])
    @commands.has_permissions(manage_messages=True)
    async def filter_words_remove(self, ctx: commands.Context, *, word: str):
        """Quitar palabra prohibida"""
        word = word.lower().strip()
        
        await database.filter_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$pull": {"banned_words": word}}
        )
        
        if ctx.guild.id in self._settings_cache:
            if "banned_words" in self._settings_cache[ctx.guild.id]:
                try:
                    self._settings_cache[ctx.guild.id]["banned_words"].remove(word)
                except ValueError:
                    pass
        
        await ctx.send(embed=success_embed(f"Palabra `{word}` removida de la lista"))
    
    @filter_words.command(name="clear", aliases=["limpiar"])
    @commands.has_permissions(administrator=True)
    async def filter_words_clear(self, ctx: commands.Context):
        """Limpiar todas las palabras prohibidas"""
        await database.filter_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"banned_words": [], "word_filter_enabled": False}}
        )
        
        if ctx.guild.id in self._settings_cache:
            self._settings_cache[ctx.guild.id]["banned_words"] = []
            self._settings_cache[ctx.guild.id]["word_filter_enabled"] = False
        
        await ctx.send(embed=success_embed("Lista de palabras prohibidas **limpiada**"))
    
    @filter.group(name="whitelist", aliases=["wl"], invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def filter_whitelist(self, ctx: commands.Context):
        """Gestionar whitelist de filtros"""
        await ctx.send_help(ctx.command)
    
    @filter_whitelist.command(name="channel", aliases=["canal"])
    @commands.has_permissions(manage_messages=True)
    async def whitelist_channel(
        self, 
        ctx: commands.Context, 
        filter_type: Literal["invite", "link"],
        channel: discord.TextChannel
    ):
        """Añadir canal a whitelist"""
        field = f"{filter_type}_whitelist_channels"
        
        await database.filter_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$addToSet": {field: channel.id}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(
            f"{channel.mention} añadido a whitelist de {filter_type}"
        ))
    
    @filter_whitelist.command(name="role", aliases=["rol"])
    @commands.has_permissions(manage_messages=True)
    async def whitelist_role(
        self, 
        ctx: commands.Context, 
        filter_type: Literal["invite", "link"],
        role: discord.Role
    ):
        """Añadir rol a whitelist"""
        field = f"{filter_type}_whitelist_roles"
        
        await database.filter_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$addToSet": {field: role.id}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(
            f"{role.mention} añadido a whitelist de {filter_type}"
        ))
    
    @filter.command(name="logs", aliases=["log"])
    @commands.has_permissions(manage_messages=True)
    async def filter_logs(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Establecer canal de logs de filtros"""
        if channel is None:
            await database.filter_settings.update_one(
                {"guild_id": ctx.guild.id},
                {"$unset": {"log_channel": ""}}
            )
            return await ctx.send(embed=success_embed("Canal de logs **removido**"))
        
        await database.filter_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"guild_id": ctx.guild.id, "log_channel": channel.id}},
            upsert=True
        )
        
        if ctx.guild.id in self._settings_cache:
            self._settings_cache[ctx.guild.id]["log_channel"] = channel.id
        
        await ctx.send(embed=success_embed(f"Canal de logs: {channel.mention}"))
    
    @filter.command(name="imageonly", aliases=["images", "imagenes"])
    @commands.has_permissions(manage_messages=True)
    async def filter_imageonly(
        self, 
        ctx: commands.Context, 
        action: Literal["add", "remove"],
        channel: discord.TextChannel
    ):
        """Configurar canales de solo imágenes"""
        if action == "add":
            await database.filter_settings.update_one(
                {"guild_id": ctx.guild.id},
                {"$addToSet": {"image_only_channels": channel.id}},
                upsert=True
            )
            await ctx.send(embed=success_embed(f"{channel.mention} es ahora un canal de solo imágenes"))
        else:
            await database.filter_settings.update_one(
                {"guild_id": ctx.guild.id},
                {"$pull": {"image_only_channels": channel.id}}
            )
            await ctx.send(embed=success_embed(f"{channel.mention} ya no es un canal de solo imágenes"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Filter(bot))
