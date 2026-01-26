"""
Cog Welcome/Goodbye - Sistema de bienvenida y despedida
"""

from __future__ import annotations

import discord
from discord.ext import commands, tasks
from datetime import datetime
from typing import Optional

from config import config
from core import database, cache
from utils import (
    success_embed, error_embed, warning_embed,
    parse_message_variables, parse_embed_json
)


class Welcome(commands.Cog):
    """👋 Sistema de mensajes de bienvenida y despedida"""
    
    emoji = "👋"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._welcome_cache: dict[int, dict] = {}
        self._goodbye_cache: dict[int, dict] = {}
        self.sync_cache.start()
    
    def cog_unload(self):
        self.sync_cache.cancel()
    
    @tasks.loop(minutes=10)
    async def sync_cache(self):
        """Sincronizar caché de configuraciones"""
        # Welcome
        async for doc in database.welcome.find({"enabled": True}):
            self._welcome_cache[doc["guild_id"]] = doc
        
        # Goodbye
        async for doc in database.goodbye.find({"enabled": True}):
            self._goodbye_cache[doc["guild_id"]] = doc
    
    @sync_cache.before_loop
    async def before_sync(self):
        await self.bot.wait_until_ready()
    
    # ========== Helpers ==========
    
    async def get_welcome_config(self, guild_id: int) -> Optional[dict]:
        """Obtener configuración de bienvenida"""
        if guild_id in self._welcome_cache:
            return self._welcome_cache[guild_id]
        
        cached = await cache.get_welcome_config(guild_id)
        if cached:
            return cached
        
        doc = await database.welcome.find_one({"guild_id": guild_id})
        if doc:
            self._welcome_cache[guild_id] = doc
            await cache.set_welcome_config(guild_id, doc)
        
        return doc
    
    async def send_welcome_message(self, member: discord.Member, config_data: dict):
        """Enviar mensaje de bienvenida"""
        channel_id = config_data.get("channel_id")
        channel = member.guild.get_channel(channel_id)
        
        if not channel:
            return
        
        message_text = config_data.get("message")
        embed_data = config_data.get("embed")
        
        # Parsear variables
        content = None
        embed = None
        
        if message_text:
            content = await parse_message_variables(message_text, member)
        
        if embed_data:
            # Si es JSON, parsearlo
            if isinstance(embed_data, dict):
                # Parsear variables en campos del embed
                if "description" in embed_data:
                    embed_data["description"] = await parse_message_variables(
                        embed_data["description"], member
                    )
                if "title" in embed_data:
                    embed_data["title"] = await parse_message_variables(
                        embed_data["title"], member
                    )
                
                embed = parse_embed_json(embed_data)
            else:
                # Embed simple con descripción
                description = await parse_message_variables(str(embed_data), member)
                embed = discord.Embed(
                    description=description,
                    color=config.BLURPLE_COLOR
                )
        
        # Si no hay mensaje ni embed, crear uno por defecto
        if not content and not embed:
            embed = discord.Embed(
                description=f"👋 Bienvenido {member.mention} a **{member.guild.name}**!",
                color=config.BLURPLE_COLOR
            )
            embed.set_thumbnail(url=member.display_avatar.url)
        
        try:
            msg = await channel.send(content=content, embed=embed)
            
            # Auto-delete si está configurado
            delete_after = config_data.get("delete_after")
            if delete_after and delete_after > 0:
                await msg.delete(delay=delete_after)
                
        except discord.HTTPException:
            pass
    
    # ========== Event Listeners ==========
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Manejar entrada de miembros"""
        # Bienvenida
        welcome_config = await self.get_welcome_config(member.guild.id)
        if welcome_config and welcome_config.get("enabled"):
            await self.send_welcome_message(member, welcome_config)
        
        # DM de bienvenida
        dm_config = welcome_config.get("dm") if welcome_config else None
        if dm_config and dm_config.get("enabled"):
            try:
                message = await parse_message_variables(dm_config.get("message", ""), member)
                await member.send(message)
            except discord.HTTPException:
                pass
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Manejar salida de miembros"""
        if member.guild.id not in self._goodbye_cache:
            doc = await database.goodbye.find_one({"guild_id": member.guild.id})
            if doc:
                self._goodbye_cache[member.guild.id] = doc
            else:
                return
        
        goodbye_config = self._goodbye_cache.get(member.guild.id)
        if not goodbye_config or not goodbye_config.get("enabled"):
            return
        
        channel_id = goodbye_config.get("channel_id")
        channel = member.guild.get_channel(channel_id)
        
        if not channel:
            return
        
        message_text = goodbye_config.get("message")
        
        if message_text:
            content = await parse_message_variables(message_text, member)
        else:
            content = f"👋 **{member}** ha salido del servidor."
        
        try:
            await channel.send(content)
        except discord.HTTPException:
            pass
    
    # ========== Welcome Commands ==========
    
    @commands.group(
        name="welcome",
        aliases=["bienvenida", "welc"],
        brief="Sistema de bienvenida",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_guild=True)
    async def welcome(self, ctx: commands.Context):
        """
        Sistema de mensajes de bienvenida.
        
        **Variables disponibles:**
        `{user}` - Nombre del usuario
        `{user.mention}` - Mención del usuario
        `{user.name}` - Nombre de usuario
        `{user.avatar}` - URL del avatar
        `{guild.name}` - Nombre del servidor
        `{guild.count}` - Número de miembros
        """
        welcome_config = await self.get_welcome_config(ctx.guild.id)
        
        if not welcome_config:
            return await ctx.send(embed=warning_embed(
                f"Bienvenida no configurada. Usa `{ctx.clean_prefix}welcome setup`"
            ))
        
        status = "✅ Activado" if welcome_config.get("enabled") else "❌ Desactivado"
        channel = ctx.guild.get_channel(welcome_config.get("channel_id"))
        
        embed = discord.Embed(
            title="👋 Configuración de Bienvenida",
            color=config.BLURPLE_COLOR
        )
        embed.add_field(name="Estado", value=status, inline=True)
        embed.add_field(name="Canal", value=channel.mention if channel else "No configurado", inline=True)
        
        message = welcome_config.get("message") or "No configurado"
        embed.add_field(name="Mensaje", value=f"```{message[:200]}```", inline=False)
        
        embed.add_field(
            name="Comandos",
            value=(
                f"`{ctx.clean_prefix}welcome setup` - Configurar\n"
                f"`{ctx.clean_prefix}welcome channel #canal` - Canal\n"
                f"`{ctx.clean_prefix}welcome message <mensaje>` - Mensaje\n"
                f"`{ctx.clean_prefix}welcome toggle` - Activar/Desactivar\n"
                f"`{ctx.clean_prefix}welcome test` - Probar"
            ),
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @welcome.command(name="setup", aliases=["configurar"])
    @commands.has_permissions(manage_guild=True)
    async def welcome_setup(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        *,
        message: str = "👋 Bienvenido {user.mention} a **{guild.name}**!"
    ):
        """
        Configurar el sistema de bienvenida rápidamente.
        
        **Variables:** {user.mention}, {user.name}, {guild.name}, {guild.count}
        
        **Ejemplos:**
        ;welcome setup #bienvenidas
        ;welcome setup #general Bienvenido {user.mention}!
        ;welcome setup #entrada Eres el miembro #{guild.count}
        """
        await database.welcome.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {
                    "guild_id": ctx.guild.id,
                    "enabled": True,
                    "channel_id": channel.id,
                    "message": message,
                    "embed": None,
                    "delete_after": None,
                    "dm": {"enabled": False, "message": None}
                }
            },
            upsert=True
        )
        
        # Actualizar caché
        self._welcome_cache.pop(ctx.guild.id, None)
        await cache.invalidate_welcome_config(ctx.guild.id)
        
        embed = success_embed(
            f"✅ Bienvenida configurada en {channel.mention}\n\n"
            f"**Mensaje:** {message}",
            ctx.author
        )
        await ctx.send(embed=embed)
    
    @welcome.command(name="channel", aliases=["canal"])
    @commands.has_permissions(manage_guild=True)
    async def welcome_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """
        Cambiar el canal donde se envían las bienvenidas.
        
        **Ejemplos:**
        ;welcome channel #bienvenidas
        ;welcome canal #general
        """
        await database.welcome.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"channel_id": channel.id}},
            upsert=True
        )
        
        self._welcome_cache.pop(ctx.guild.id, None)
        await cache.invalidate_welcome_config(ctx.guild.id)
        
        await ctx.send(embed=success_embed(f"Canal cambiado a {channel.mention}"))
    
    @welcome.command(name="message", aliases=["mensaje"])
    @commands.has_permissions(manage_guild=True)
    async def welcome_message(self, ctx: commands.Context, *, message: str):
        """
        Cambiar el mensaje de bienvenida.
        
        **Variables:** {user.mention}, {user.name}, {guild.name}, {guild.count}
        
        **Ejemplos:**
        ;welcome message ¡Bienvenido {user.mention}!
        ;welcome mensaje Hola {user.name}, eres el miembro #{guild.count}
        """
        await database.welcome.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"message": message}},
            upsert=True
        )
        
        self._welcome_cache.pop(ctx.guild.id, None)
        await cache.invalidate_welcome_config(ctx.guild.id)
        
        await ctx.send(embed=success_embed(f"Mensaje actualizado:\n```{message}```"))
    
    @welcome.command(name="toggle", aliases=["activar"])
    @commands.has_permissions(manage_guild=True)
    async def welcome_toggle(self, ctx: commands.Context):
        """Activar/desactivar bienvenida"""
        current = await self.get_welcome_config(ctx.guild.id)
        new_state = not (current.get("enabled") if current else False)
        
        await database.welcome.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"enabled": new_state}},
            upsert=True
        )
        
        self._welcome_cache.pop(ctx.guild.id, None)
        await cache.invalidate_welcome_config(ctx.guild.id)
        
        status = "activada" if new_state else "desactivada"
        await ctx.send(embed=success_embed(f"Bienvenida **{status}**"))
    
    @welcome.command(name="test", aliases=["probar"])
    @commands.has_permissions(manage_guild=True)
    async def welcome_test(self, ctx: commands.Context):
        """Probar el mensaje de bienvenida"""
        welcome_config = await self.get_welcome_config(ctx.guild.id)
        
        if not welcome_config:
            return await ctx.send(embed=error_embed("Bienvenida no configurada"))
        
        await self.send_welcome_message(ctx.author, welcome_config)
        await ctx.send(embed=success_embed("Mensaje de prueba enviado"))
    
    @welcome.command(name="delete", aliases=["eliminar"])
    @commands.has_permissions(manage_guild=True)
    async def welcome_delete(self, ctx: commands.Context, seconds: int = 0):
        """Configurar auto-eliminación del mensaje (0 = no eliminar)"""
        if seconds < 0 or seconds > 300:
            return await ctx.send(embed=error_embed("El tiempo debe estar entre 0 y 300 segundos"))
        
        await database.welcome.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"delete_after": seconds if seconds > 0 else None}},
            upsert=True
        )
        
        self._welcome_cache.pop(ctx.guild.id, None)
        await cache.invalidate_welcome_config(ctx.guild.id)
        
        if seconds > 0:
            await ctx.send(embed=success_embed(f"Mensajes se eliminarán después de **{seconds}** segundos"))
        else:
            await ctx.send(embed=success_embed("Auto-eliminación desactivada"))
    
    # ========== Goodbye Commands ==========
    
    @commands.group(
        name="goodbye",
        aliases=["despedida", "bye"],
        brief="Sistema de despedida",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_guild=True)
    async def goodbye(self, ctx: commands.Context):
        """Sistema de mensajes de despedida"""
        goodbye_config = self._goodbye_cache.get(ctx.guild.id)
        if not goodbye_config:
            goodbye_config = await database.goodbye.find_one({"guild_id": ctx.guild.id})
        
        if not goodbye_config:
            return await ctx.send(embed=warning_embed(
                f"Despedida no configurada. Usa `{ctx.clean_prefix}goodbye setup`"
            ))
        
        status = "✅ Activado" if goodbye_config.get("enabled") else "❌ Desactivado"
        channel = ctx.guild.get_channel(goodbye_config.get("channel_id"))
        
        embed = discord.Embed(
            title="👋 Configuración de Despedida",
            color=config.BLURPLE_COLOR
        )
        embed.add_field(name="Estado", value=status, inline=True)
        embed.add_field(name="Canal", value=channel.mention if channel else "No configurado", inline=True)
        
        message = goodbye_config.get("message") or "No configurado"
        embed.add_field(name="Mensaje", value=f"```{message[:200]}```", inline=False)
        
        await ctx.send(embed=embed)
    
    @goodbye.command(name="setup", aliases=["configurar"])
    @commands.has_permissions(manage_guild=True)
    async def goodbye_setup(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        *,
        message: str = "👋 **{user}** ha dejado el servidor."
    ):
        """Configurar despedida"""
        await database.goodbye.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {
                    "guild_id": ctx.guild.id,
                    "enabled": True,
                    "channel_id": channel.id,
                    "message": message
                }
            },
            upsert=True
        )
        
        self._goodbye_cache.pop(ctx.guild.id, None)
        
        embed = success_embed(
            f"✅ Despedida configurada en {channel.mention}",
            ctx.author
        )
        await ctx.send(embed=embed)
    
    @goodbye.command(name="toggle", aliases=["activar"])
    @commands.has_permissions(manage_guild=True)
    async def goodbye_toggle(self, ctx: commands.Context):
        """Activar/desactivar despedida"""
        current = self._goodbye_cache.get(ctx.guild.id)
        if not current:
            current = await database.goodbye.find_one({"guild_id": ctx.guild.id})
        
        new_state = not (current.get("enabled") if current else False)
        
        await database.goodbye.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"enabled": new_state}},
            upsert=True
        )
        
        self._goodbye_cache.pop(ctx.guild.id, None)
        
        status = "activada" if new_state else "desactivada"
        await ctx.send(embed=success_embed(f"Despedida **{status}**"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
