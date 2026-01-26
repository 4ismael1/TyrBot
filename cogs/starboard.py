"""
Cog Starboard - Sistema de mensajes destacados
"""

from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional, Dict
from datetime import datetime

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed


class Starboard(commands.Cog):
    """⭐ Sistema de Starboard"""
    
    emoji = "⭐"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache de configuraciones
        self.configs: Dict[int, dict] = {}
        # Cache de mensajes ya publicados {original_msg_id: star_msg_id}
        self.posted: Dict[int, int] = {}
    
    async def cog_load(self):
        """Cargar configuraciones"""
        async for doc in database.starboard.find():
            self.configs[doc["guild_id"]] = doc
        
        # Cargar mensajes ya publicados
        async for doc in database.starboard_messages.find():
            self.posted[doc["original_id"]] = doc["star_id"]
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Manejar reacciones de estrella"""
        if not payload.guild_id:
            return
        
        # Verificar configuración
        if payload.guild_id not in self.configs:
            return
        
        config_data = self.configs[payload.guild_id]
        
        if not config_data.get("enabled"):
            return
        
        # Verificar emoji
        emoji_str = str(payload.emoji)
        star_emoji = config_data.get("emoji", "⭐")
        
        if emoji_str != star_emoji and not (payload.emoji.name == "⭐" and star_emoji == "⭐"):
            return
        
        # Obtener canal y mensaje
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
        
        # Verificar si el canal está en la blacklist
        if payload.channel_id in config_data.get("blacklist_channels", []):
            return
        
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return
        
        # Contar estrellas
        star_count = 0
        for reaction in message.reactions:
            if str(reaction.emoji) == star_emoji or (reaction.emoji == "⭐" and star_emoji == "⭐"):
                star_count = reaction.count
                break
        
        threshold = config_data.get("threshold", 3)
        
        # Verificar umbral
        if star_count < threshold:
            return
        
        # Obtener canal de starboard
        starboard_channel = guild.get_channel(config_data.get("channel_id"))
        if not starboard_channel:
            return
        
        # Crear/actualizar embed
        await self._post_or_update_star(message, star_count, starboard_channel, config_data)
    
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Actualizar cuando se quita una estrella"""
        if not payload.guild_id:
            return
        
        if payload.guild_id not in self.configs:
            return
        
        config_data = self.configs[payload.guild_id]
        
        if not config_data.get("enabled"):
            return
        
        # Verificar si el mensaje está en starboard
        if payload.message_id not in self.posted:
            return
        
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
        
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return
        
        # Contar estrellas
        star_emoji = config_data.get("emoji", "⭐")
        star_count = 0
        for reaction in message.reactions:
            if str(reaction.emoji) == star_emoji or (reaction.emoji == "⭐" and star_emoji == "⭐"):
                star_count = reaction.count
                break
        
        starboard_channel = guild.get_channel(config_data.get("channel_id"))
        if not starboard_channel:
            return
        
        threshold = config_data.get("threshold", 3)
        
        # Si está bajo el umbral, eliminar del starboard
        if star_count < threshold:
            try:
                star_msg = await starboard_channel.fetch_message(self.posted[payload.message_id])
                await star_msg.delete()
                del self.posted[payload.message_id]
                await database.starboard_messages.delete_one({"original_id": payload.message_id})
            except:
                pass
        else:
            # Actualizar contador
            await self._post_or_update_star(message, star_count, starboard_channel, config_data)
    
    async def _post_or_update_star(
        self, 
        message: discord.Message, 
        star_count: int, 
        starboard_channel: discord.TextChannel,
        config_data: dict
    ):
        """Publicar o actualizar mensaje en starboard"""
        star_emoji = config_data.get("emoji", "⭐")
        
        # Crear embed
        embed = discord.Embed(
            description=message.content[:4000] if message.content else None,
            color=discord.Color.gold(),
            timestamp=message.created_at
        )
        
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url
        )
        
        # Añadir imagen si existe
        if message.attachments:
            attachment = message.attachments[0]
            if attachment.content_type and attachment.content_type.startswith("image"):
                embed.set_image(url=attachment.url)
        
        # Añadir enlace al mensaje original
        embed.add_field(
            name="Mensaje Original",
            value=f"[Ir al mensaje]({message.jump_url})",
            inline=False
        )
        
        embed.set_footer(text=f"ID: {message.id}")
        
        content = f"{star_emoji} **{star_count}** | {message.channel.mention}"
        
        if message.id in self.posted:
            # Actualizar mensaje existente
            try:
                star_msg = await starboard_channel.fetch_message(self.posted[message.id])
                await star_msg.edit(content=content, embed=embed)
            except discord.NotFound:
                # El mensaje fue eliminado, crear nuevo
                del self.posted[message.id]
        
        if message.id not in self.posted:
            # Crear nuevo mensaje
            star_msg = await starboard_channel.send(content=content, embed=embed)
            self.posted[message.id] = star_msg.id
            
            await database.starboard_messages.insert_one({
                "guild_id": message.guild.id,
                "original_id": message.id,
                "star_id": star_msg.id,
                "channel_id": message.channel.id,
                "author_id": message.author.id
            })
    
    @commands.group(
        name="starboard",
        aliases=["sb", "star"],
        brief="Sistema de mensajes destacados",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_guild=True)
    async def starboard(self, ctx: commands.Context):
        """Sistema de mensajes destacados con estrellas"""
        embed = discord.Embed(
            title="⭐ Starboard",
            description="Los mensajes con suficientes estrellas aparecerán en un canal especial.",
            color=discord.Color.gold()
        )
        
        embed.add_field(
            name="Comandos",
            value=f"`{ctx.prefix}starboard channel <canal>` - Establecer canal\n"
                  f"`{ctx.prefix}starboard threshold <número>` - Mínimo de estrellas\n"
                  f"`{ctx.prefix}starboard emoji <emoji>` - Cambiar emoji\n"
                  f"`{ctx.prefix}starboard toggle` - Activar/desactivar\n"
                  f"`{ctx.prefix}starboard blacklist <canal>` - Ignorar canal\n"
                  f"`{ctx.prefix}starboard settings` - Ver configuración",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @starboard.command(name="channel", aliases=["set"])
    @commands.has_permissions(manage_guild=True)
    async def starboard_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Establecer canal de starboard"""
        await database.starboard.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {
                    "guild_id": ctx.guild.id,
                    "channel_id": channel.id,
                    "enabled": True
                },
                "$setOnInsert": {
                    "threshold": 3,
                    "emoji": "⭐",
                    "blacklist_channels": []
                }
            },
            upsert=True
        )
        
        # Actualizar cache
        if ctx.guild.id not in self.configs:
            self.configs[ctx.guild.id] = {"guild_id": ctx.guild.id}
        self.configs[ctx.guild.id]["channel_id"] = channel.id
        self.configs[ctx.guild.id]["enabled"] = True
        
        await ctx.send(embed=success_embed(f"Canal de starboard: {channel.mention}"))
    
    @starboard.command(name="threshold", aliases=["min", "minimum"])
    @commands.has_permissions(manage_guild=True)
    async def starboard_threshold(self, ctx: commands.Context, threshold: int):
        """Establecer mínimo de estrellas"""
        if threshold < 1 or threshold > 50:
            return await ctx.send(embed=error_embed("El umbral debe ser entre 1 y 50"))
        
        await database.starboard.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"threshold": threshold}},
            upsert=True
        )
        
        if ctx.guild.id in self.configs:
            self.configs[ctx.guild.id]["threshold"] = threshold
        
        await ctx.send(embed=success_embed(f"Umbral establecido: **{threshold}** estrellas"))
    
    @starboard.command(name="emoji")
    @commands.has_permissions(manage_guild=True)
    async def starboard_emoji(self, ctx: commands.Context, emoji: str):
        """Cambiar emoji de starboard"""
        await database.starboard.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"emoji": emoji}},
            upsert=True
        )
        
        if ctx.guild.id in self.configs:
            self.configs[ctx.guild.id]["emoji"] = emoji
        
        await ctx.send(embed=success_embed(f"Emoji de starboard: {emoji}"))
    
    @starboard.command(name="toggle", aliases=["on", "off"])
    @commands.has_permissions(manage_guild=True)
    async def starboard_toggle(self, ctx: commands.Context):
        """Activar/desactivar starboard"""
        current = self.configs.get(ctx.guild.id, {}).get("enabled", False)
        new_state = not current
        
        await database.starboard.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"enabled": new_state}},
            upsert=True
        )
        
        if ctx.guild.id in self.configs:
            self.configs[ctx.guild.id]["enabled"] = new_state
        
        status = "activado" if new_state else "desactivado"
        await ctx.send(embed=success_embed(f"Starboard **{status}**"))
    
    @starboard.command(name="blacklist", aliases=["ignore"])
    @commands.has_permissions(manage_guild=True)
    async def starboard_blacklist(self, ctx: commands.Context, channel: discord.TextChannel):
        """Añadir/quitar canal de la blacklist"""
        current = self.configs.get(ctx.guild.id, {}).get("blacklist_channels", [])
        
        if channel.id in current:
            current.remove(channel.id)
            action = "quitado de"
        else:
            current.append(channel.id)
            action = "añadido a"
        
        await database.starboard.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"blacklist_channels": current}},
            upsert=True
        )
        
        if ctx.guild.id in self.configs:
            self.configs[ctx.guild.id]["blacklist_channels"] = current
        
        await ctx.send(embed=success_embed(f"{channel.mention} {action} la blacklist"))
    
    @starboard.command(name="settings", aliases=["config", "info"])
    @commands.has_permissions(manage_guild=True)
    async def starboard_settings(self, ctx: commands.Context):
        """Ver configuración actual"""
        config_data = self.configs.get(ctx.guild.id)
        
        if not config_data:
            return await ctx.send(embed=warning_embed("Starboard no está configurado"))
        
        embed = discord.Embed(
            title="⭐ Configuración de Starboard",
            color=discord.Color.gold()
        )
        
        channel = ctx.guild.get_channel(config_data.get("channel_id"))
        
        embed.add_field(name="Estado", value="✅ Activado" if config_data.get("enabled") else "❌ Desactivado", inline=True)
        embed.add_field(name="Canal", value=channel.mention if channel else "No configurado", inline=True)
        embed.add_field(name="Umbral", value=f"{config_data.get('threshold', 3)} estrellas", inline=True)
        embed.add_field(name="Emoji", value=config_data.get("emoji", "⭐"), inline=True)
        
        blacklist = config_data.get("blacklist_channels", [])
        if blacklist:
            channels_text = ", ".join([f"<#{c}>" for c in blacklist[:5]])
            embed.add_field(name="Canales Ignorados", value=channels_text, inline=False)
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Starboard(bot))
