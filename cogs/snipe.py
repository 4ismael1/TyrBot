"""
Cog Snipe - Sistema de snipe para mensajes eliminados/editados
"""

from __future__ import annotations

import discord
from discord.ext import commands
from collections import defaultdict
from datetime import datetime
from typing import Optional
import time

from config import config
from core import cache
from utils import error_embed, paginate


class Snipe(commands.Cog):
    """👀 Sistema de snipe"""
    
    emoji = "👀"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache local de respaldo si Redis falla
        self.deleted_messages: dict[int, list[dict]] = defaultdict(list)
        self.edited_messages: dict[int, list[dict]] = defaultdict(list)
        self.max_messages = 10
    
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Guardar mensajes eliminados"""
        if message.author.bot or not message.guild:
            return
        
        if not message.content and not message.attachments:
            return
        
        timestamp = int(time.time())
        
        # Guardar en Redis
        await cache.add_deleted_message(
            channel_id=message.channel.id,
            author_id=message.author.id,
            author_name=str(message.author),
            content=message.content,
            timestamp=timestamp
        )
        
        # Backup local
        data = {
            "author_id": message.author.id,
            "author_name": str(message.author),
            "author_avatar": message.author.display_avatar.url,
            "content": message.content,
            "attachments": [a.url for a in message.attachments],
            "timestamp": timestamp,
            "channel_id": message.channel.id
        }
        
        self.deleted_messages[message.channel.id].append(data)
        if len(self.deleted_messages[message.channel.id]) > self.max_messages:
            self.deleted_messages[message.channel.id].pop(0)
    
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Guardar mensajes editados"""
        if before.author.bot or not before.guild:
            return
        
        if before.content == after.content:
            return
        
        timestamp = int(time.time())
        
        # Guardar en Redis
        await cache.add_edited_message(
            channel_id=before.channel.id,
            author_id=before.author.id,
            author_name=str(before.author),
            before=before.content,
            after=after.content,
            timestamp=timestamp,
            jump_url=after.jump_url
        )
        
        # Backup local
        data = {
            "author_id": before.author.id,
            "author_name": str(before.author),
            "author_avatar": before.author.display_avatar.url,
            "before": before.content,
            "after": after.content,
            "timestamp": timestamp,
            "channel_id": before.channel.id,
            "jump_url": after.jump_url
        }
        
        self.edited_messages[before.channel.id].append(data)
        if len(self.edited_messages[before.channel.id]) > self.max_messages:
            self.edited_messages[before.channel.id].pop(0)
    
    async def get_deleted(self, channel_id: int) -> list:
        """Obtener mensajes eliminados (Redis primero, luego local)"""
        messages = await cache.get_deleted_messages(channel_id)
        if messages:
            return messages
        return self.deleted_messages.get(channel_id, [])
    
    async def get_edited(self, channel_id: int) -> list:
        """Obtener mensajes editados (Redis primero, luego local)"""
        messages = await cache.get_edited_messages(channel_id)
        if messages:
            return messages
        return self.edited_messages.get(channel_id, [])
    
    @commands.hybrid_command(
        name="snipe",
        brief="Ver mensaje eliminado",
        description="Ver un mensaje eliminado recientemente en este canal"
    )
    async def snipe(self, ctx: commands.Context, index: int = 1):
        """
        Ver un mensaje eliminado recientemente.
        
        **Uso:** ;snipe [número]
        **Ejemplo:** ;snipe 2 (para ver el segundo mensaje más reciente)
        """
        messages = await self.get_deleted(ctx.channel.id)
        
        if not messages:
            return await ctx.send(embed=error_embed("No hay mensajes eliminados recientes"))
        
        # Índice válido (1-based)
        if index < 1 or index > len(messages):
            return await ctx.send(embed=error_embed(f"Índice inválido. Hay {len(messages)} mensaje(s) disponible(s)"))
        
        # Obtener mensaje (más reciente primero)
        data = messages[-(index)]
        
        # Convertir timestamp a datetime si es int
        ts = data["timestamp"]
        if isinstance(ts, int):
            ts = datetime.fromtimestamp(ts)
        
        embed = discord.Embed(
            description=data["content"] or "*Sin contenido de texto*",
            color=config.ERROR_COLOR,
            timestamp=ts
        )
        embed.set_author(
            name=data["author_name"],
            icon_url=data["author_avatar"]
        )
        
        if data["attachments"]:
            embed.add_field(
                name="📎 Archivos adjuntos",
                value="\n".join(data["attachments"][:5]),
                inline=False
            )
            # Mostrar imagen si es una
            if data["attachments"][0].endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                embed.set_image(url=data["attachments"][0])
        
        embed.set_footer(text=f"Mensaje {index}/{len(messages)}")
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="editsnipe",
        aliases=["esnipe", "es"],
        brief="Ver mensaje editado",
        description="Ver un mensaje editado recientemente en este canal"
    )
    async def editsnipe(self, ctx: commands.Context, index: int = 1):
        """
        Ver un mensaje editado recientemente.
        
        **Uso:** ;editsnipe [número]
        """
        messages = await self.get_edited(ctx.channel.id)
        
        if not messages:
            return await ctx.send(embed=error_embed("No hay mensajes editados recientes"))
        
        if index < 1 or index > len(messages):
            return await ctx.send(embed=error_embed(f"Índice inválido. Hay {len(messages)} mensaje(s) disponible(s)"))
        
        data = messages[index - 1]  # Redis ya está ordenado
        
        # Convertir timestamp a datetime si es int
        ts = data.get("timestamp")
        if isinstance(ts, int):
            ts = datetime.fromtimestamp(ts)
        
        embed = discord.Embed(
            color=config.WARNING_COLOR,
            timestamp=ts
        )
        embed.set_author(
            name=data.get("author_name", "Desconocido")
        )
        
        embed.add_field(
            name="Antes",
            value=(data.get("before", "") or "*Vacío*")[:1024],
            inline=False
        )
        embed.add_field(
            name="Después",
            value=(data.get("after", "") or "*Vacío*")[:1024],
            inline=False
        )
        
        if data.get("jump_url"):
            embed.add_field(
                name="Link",
                value=f"[Ir al mensaje]({data['jump_url']})",
                inline=False
            )
        
        embed.set_footer(text=f"Mensaje {index}/{len(messages)}")
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="snipelist",
        aliases=["slist"],
        brief="Lista de mensajes eliminados",
        description="Ver lista de todos los mensajes eliminados recientes"
    )
    async def snipelist(self, ctx: commands.Context):
        """Ver lista de mensajes eliminados recientes"""
        messages = await self.get_deleted(ctx.channel.id)
        
        if not messages:
            return await ctx.send(embed=error_embed("No hay mensajes eliminados recientes"))
        
        description = ""
        for i, msg in enumerate(messages, 1):
            content = msg.get("content", "")
            content = content[:50] + "..." if len(content) > 50 else content
            content = content or "*[archivo/embed]*"
            author = msg.get("author_name", "Desconocido")
            description += f"**{i}.** {author}: {content}\n"
        
        embed = discord.Embed(
            title="👀 Mensajes Eliminados",
            description=description,
            color=config.ERROR_COLOR
        )
        embed.set_footer(text=f"Usa ;snipe <número> para ver detalles")
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="clearsnipe",
        aliases=["cs"],
        brief="Limpiar snipes",
        description="Limpiar el historial de snipes del canal"
    )
    @commands.has_permissions(manage_messages=True)
    async def clearsnipe(self, ctx: commands.Context):
        """Limpiar el historial de snipes del canal"""
        # Limpiar en Redis
        await cache.clear_snipe_cache(ctx.channel.id)
        
        # Limpiar local
        self.deleted_messages[ctx.channel.id] = []
        self.edited_messages[ctx.channel.id] = []
        
        await ctx.send(
            embed=discord.Embed(
                description="✅ Historial de snipes limpiado",
                color=config.SUCCESS_COLOR
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Snipe(bot))
