"""
Cog JoinDM - Mensajes de bienvenida por DM
"""

from __future__ import annotations

import asyncio
import textwrap
import discord
from discord.ext import commands, tasks
from datetime import datetime
from typing import Optional
from collections import defaultdict

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed


class JoinDM(commands.Cog):
    """📬 Mensajes de bienvenida por DM"""
    
    emoji = "📬"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # Rate limiting: no más de 20 DMs por minuto por servidor
        self._dm_count: dict[int, int] = defaultdict(int)
        
        # Iniciar tareas
        self.clear_dm_count.start()
    
    def cog_unload(self):
        self.clear_dm_count.cancel()
    
    @tasks.loop(seconds=60)
    async def clear_dm_count(self):
        """Limpiar contador de DMs"""
        self._dm_count.clear()
    
    async def get_joindm_settings(self, guild_id: int) -> Optional[dict]:
        """Obtener configuración de JoinDM"""
        return await database.joindm.find_one({"guild_id": guild_id})
    
    def parse_variables(self, message: str, member: discord.Member) -> str:
        """Parsear variables en el mensaje"""
        replacements = {
            # Usuario
            "{user}": str(member),
            "{user.mention}": member.mention,
            "{user.name}": member.name,
            "{user.id}": str(member.id),
            "{user.avatar}": str(member.display_avatar.url),
            "{user.created}": discord.utils.format_dt(member.created_at, "R"),
            
            # Servidor
            "{server}": member.guild.name,
            "{server.name}": member.guild.name,
            "{server.id}": str(member.guild.id),
            "{server.members}": str(member.guild.member_count),
            "{server.count}": str(member.guild.member_count),
            
            # Aliases del bot original
            "$(user)": str(member),
            "$(user.mention)": member.mention,
            "$(user.name)": member.name,
            "$(user.avatar)": str(member.display_avatar.url),
            "$(guild.name)": member.guild.name,
            "$(guild.count)": str(member.guild.member_count),
            "$(guild.id)": str(member.guild.id),
        }
        
        for var, value in replacements.items():
            message = message.replace(var, value)
        
        return message
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Enviar DM de bienvenida"""
        if member.bot:
            return
        
        # Verificar rate limit
        if self._dm_count[member.guild.id] >= 20:
            return
        
        settings = await self.get_joindm_settings(member.guild.id)
        if not settings or not settings.get("enabled"):
            return
        
        message = settings.get("message")
        if not message:
            return
        
        # Parsear variables
        message = self.parse_variables(message, member)
        
        # Crear view con botón del servidor
        view = discord.ui.View()
        server_name = textwrap.shorten(member.guild.name, width=55, placeholder="...")
        view.add_item(discord.ui.Button(
            label=f"Enviado desde: {server_name}",
            disabled=True
        ))
        
        try:
            await member.send(message, view=view)
            self._dm_count[member.guild.id] += 1
        except discord.HTTPException:
            pass
    
    @commands.group(
        name="joindm",
        aliases=["jdm", "welcomedm"],
        brief="Sistema de DMs de bienvenida",
        invoke_without_command=True
    )
    @commands.has_permissions(administrator=True)
    async def joindm(self, ctx: commands.Context):
        """Sistema de mensajes de bienvenida por DM"""
        settings = await self.get_joindm_settings(ctx.guild.id)
        
        embed = discord.Embed(
            title="📬 Join DM",
            description="Envía un mensaje de bienvenida por DM a nuevos miembros",
            color=config.BLURPLE_COLOR
        )
        
        if settings and settings.get("enabled"):
            embed.add_field(
                name="Estado",
                value="✅ Habilitado",
                inline=True
            )
            embed.add_field(
                name="Mensaje actual",
                value=f"```{settings.get('message', 'No configurado')[:500]}```",
                inline=False
            )
        else:
            embed.add_field(name="Estado", value="❌ Deshabilitado", inline=True)
        
        embed.add_field(
            name="Comandos",
            value=f"`{ctx.prefix}joindm enable` - Habilitar\n"
                  f"`{ctx.prefix}joindm disable` - Deshabilitar\n"
                  f"`{ctx.prefix}joindm message <mensaje>` - Establecer mensaje\n"
                  f"`{ctx.prefix}joindm test` - Probar mensaje\n"
                  f"`{ctx.prefix}joindm variables` - Ver variables",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @joindm.command(name="enable", aliases=["on"])
    @commands.has_permissions(administrator=True)
    async def joindm_enable(self, ctx: commands.Context):
        """Habilitar JoinDM"""
        await database.joindm.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"guild_id": ctx.guild.id, "enabled": True}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed("Join DM **habilitado**"))
    
    @joindm.command(name="disable", aliases=["off"])
    @commands.has_permissions(administrator=True)
    async def joindm_disable(self, ctx: commands.Context):
        """Deshabilitar JoinDM"""
        await database.joindm.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"enabled": False}}
        )
        
        await ctx.send(embed=success_embed("Join DM **deshabilitado**"))
    
    @joindm.command(name="message", aliases=["msg", "set"])
    @commands.has_permissions(administrator=True)
    async def joindm_message(self, ctx: commands.Context, *, message: str):
        """Establecer mensaje de JoinDM"""
        if len(message) > 2000:
            return await ctx.send(embed=error_embed("El mensaje no puede tener más de 2000 caracteres"))
        
        await database.joindm.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {
                "guild_id": ctx.guild.id,
                "enabled": True,
                "message": message
            }},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(f"Mensaje de Join DM establecido:\n```{message[:500]}```"))
    
    @joindm.command(name="test", aliases=["preview", "ver"])
    @commands.has_permissions(administrator=True)
    async def joindm_test(self, ctx: commands.Context):
        """Probar el mensaje de JoinDM"""
        settings = await self.get_joindm_settings(ctx.guild.id)
        
        if not settings or not settings.get("message"):
            return await ctx.send(embed=error_embed("No hay mensaje configurado"))
        
        message = self.parse_variables(settings["message"], ctx.author)
        
        view = discord.ui.View()
        server_name = textwrap.shorten(ctx.guild.name, width=55, placeholder="...")
        view.add_item(discord.ui.Button(
            label=f"Enviado desde: {server_name}",
            disabled=True
        ))
        
        try:
            await ctx.author.send(message, view=view)
            await ctx.send(embed=success_embed("Mensaje de prueba enviado a tu DM"))
        except discord.HTTPException:
            await ctx.send(embed=error_embed("No pude enviarte un DM. Verifica tu configuración de privacidad"))
    
    @joindm.command(name="variables", aliases=["vars", "placeholders"])
    @commands.has_permissions(administrator=True)
    async def joindm_variables(self, ctx: commands.Context):
        """Ver variables disponibles"""
        embed = discord.Embed(
            title="📬 Variables de Join DM",
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(
            name="Usuario",
            value="`{user}` - Usuario completo\n"
                  "`{user.mention}` - Mención\n"
                  "`{user.name}` - Nombre\n"
                  "`{user.id}` - ID\n"
                  "`{user.avatar}` - URL del avatar\n"
                  "`{user.created}` - Fecha de creación",
            inline=True
        )
        
        embed.add_field(
            name="Servidor",
            value="`{server}` - Nombre del servidor\n"
                  "`{server.name}` - Nombre\n"
                  "`{server.id}` - ID\n"
                  "`{server.members}` - Cantidad de miembros",
            inline=True
        )
        
        embed.add_field(
            name="Ejemplo",
            value=f"```¡Bienvenido {{user.name}} a {{server}}! "
                  f"Eres el miembro #{{server.members}}```",
            inline=False
        )
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(JoinDM(bot))
