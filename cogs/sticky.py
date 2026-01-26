"""
Cog Sticky - Mensajes pegajosos en canales
"""

from __future__ import annotations

import discord
from discord.ext import commands
from typing import Dict, Optional
import asyncio
import time

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed


class Sticky(commands.Cog):
    """📌 Mensajes Pegajosos"""
    
    emoji = "📌"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache: {channel_id: {"message_id": int, "content": str, "embed": dict, "last_sent": float}}
        self.stickies: Dict[int, dict] = {}
        # Lock para evitar spam
        self.locks: Dict[int, asyncio.Lock] = {}
        # Cooldown (segundos entre re-sticks)
        self.cooldown = 3
    
    async def cog_load(self):
        """Cargar stickies de la DB"""
        async for doc in database.stickies.find():
            self.stickies[doc["channel_id"]] = {
                "message_id": doc.get("message_id"),
                "content": doc.get("content"),
                "embed": doc.get("embed"),
                "last_sent": 0
            }
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Re-enviar sticky cuando alguien envía mensaje"""
        if message.author.bot:
            return
        
        if not message.guild:
            return
        
        channel_id = message.channel.id
        
        if channel_id not in self.stickies:
            return
        
        sticky = self.stickies[channel_id]
        
        # Verificar cooldown
        if time.time() - sticky.get("last_sent", 0) < self.cooldown:
            return
        
        # Obtener lock para el canal
        if channel_id not in self.locks:
            self.locks[channel_id] = asyncio.Lock()
        
        async with self.locks[channel_id]:
            try:
                # Borrar mensaje sticky anterior
                if sticky.get("message_id"):
                    try:
                        old_msg = await message.channel.fetch_message(sticky["message_id"])
                        await old_msg.delete()
                    except (discord.NotFound, discord.HTTPException):
                        pass
                
                # Enviar nuevo sticky
                content = sticky.get("content")
                embed_data = sticky.get("embed")
                
                if embed_data:
                    embed = discord.Embed.from_dict(embed_data)
                    new_msg = await message.channel.send(content=content, embed=embed)
                else:
                    new_msg = await message.channel.send(content=content)
                
                # Actualizar cache
                self.stickies[channel_id]["message_id"] = new_msg.id
                self.stickies[channel_id]["last_sent"] = time.time()
                
                # Actualizar DB
                await database.stickies.update_one(
                    {"channel_id": channel_id},
                    {"$set": {"message_id": new_msg.id}}
                )
            
            except discord.HTTPException:
                pass
    
    @commands.group(
        name="sticky",
        aliases=["stickymsg", "stickmessage"],
        brief="Sistema de mensajes pegajosos",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_messages=True)
    async def sticky(self, ctx: commands.Context, *, message: Optional[str] = None):
        """Crear un mensaje pegajoso en el canal actual"""
        if message is None:
            # Mostrar ayuda
            embed = discord.Embed(
                title="📌 Sticky Messages",
                description="Los mensajes pegajosos se reenvían automáticamente al final del canal cada vez que alguien envía un mensaje.",
                color=config.BLURPLE_COLOR
            )
            
            embed.add_field(
                name="Comandos",
                value=f"`{ctx.prefix}sticky <mensaje>` - Crear sticky\n"
                      f"`{ctx.prefix}sticky embed <título> | <descripción>` - Crear sticky con embed\n"
                      f"`{ctx.prefix}sticky remove` - Quitar sticky\n"
                      f"`{ctx.prefix}sticky view` - Ver sticky actual",
                inline=False
            )
            
            return await ctx.send(embed=embed)
        
        # Crear sticky
        channel_id = ctx.channel.id
        
        self.stickies[channel_id] = {
            "message_id": None,
            "content": message,
            "embed": None,
            "last_sent": 0
        }
        
        # Guardar en DB
        await database.stickies.update_one(
            {"channel_id": channel_id},
            {
                "$set": {
                    "guild_id": ctx.guild.id,
                    "channel_id": channel_id,
                    "content": message,
                    "embed": None,
                    "message_id": None
                }
            },
            upsert=True
        )
        
        # Enviar sticky inicial
        sticky_msg = await ctx.channel.send(f"📌 **Sticky Message**\n\n{message}")
        
        self.stickies[channel_id]["message_id"] = sticky_msg.id
        self.stickies[channel_id]["last_sent"] = time.time()
        
        await database.stickies.update_one(
            {"channel_id": channel_id},
            {"$set": {"message_id": sticky_msg.id}}
        )
        
        await ctx.send(embed=success_embed("Mensaje pegajoso creado"), delete_after=5)
        await ctx.message.delete(delay=1)
    
    @sticky.command(name="embed")
    @commands.has_permissions(manage_messages=True)
    async def sticky_embed(self, ctx: commands.Context, *, content: str):
        """Crear sticky con embed (título | descripción)"""
        parts = content.split("|", 1)
        title = parts[0].strip()
        description = parts[1].strip() if len(parts) > 1 else ""
        
        embed_dict = {
            "title": title,
            "description": description,
            "color": config.BLURPLE_COLOR
        }
        
        channel_id = ctx.channel.id
        
        self.stickies[channel_id] = {
            "message_id": None,
            "content": None,
            "embed": embed_dict,
            "last_sent": 0
        }
        
        await database.stickies.update_one(
            {"channel_id": channel_id},
            {
                "$set": {
                    "guild_id": ctx.guild.id,
                    "channel_id": channel_id,
                    "content": None,
                    "embed": embed_dict,
                    "message_id": None
                }
            },
            upsert=True
        )
        
        # Enviar sticky inicial
        embed = discord.Embed.from_dict(embed_dict)
        embed.set_footer(text="📌 Sticky Message")
        sticky_msg = await ctx.channel.send(embed=embed)
        
        self.stickies[channel_id]["message_id"] = sticky_msg.id
        self.stickies[channel_id]["last_sent"] = time.time()
        
        await database.stickies.update_one(
            {"channel_id": channel_id},
            {"$set": {"message_id": sticky_msg.id}}
        )
        
        await ctx.send(embed=success_embed("Sticky embed creado"), delete_after=5)
        await ctx.message.delete(delay=1)
    
    @sticky.command(name="remove", aliases=["delete", "del", "clear"])
    @commands.has_permissions(manage_messages=True)
    async def sticky_remove(self, ctx: commands.Context):
        """Quitar el mensaje pegajoso del canal"""
        channel_id = ctx.channel.id
        
        if channel_id not in self.stickies:
            return await ctx.send(embed=warning_embed("No hay sticky en este canal"))
        
        # Borrar mensaje actual
        sticky = self.stickies[channel_id]
        if sticky.get("message_id"):
            try:
                msg = await ctx.channel.fetch_message(sticky["message_id"])
                await msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
        
        # Limpiar cache y DB
        del self.stickies[channel_id]
        await database.stickies.delete_one({"channel_id": channel_id})
        
        await ctx.send(embed=success_embed("Sticky eliminado"))
    
    @sticky.command(name="view", aliases=["show", "current"])
    @commands.has_permissions(manage_messages=True)
    async def sticky_view(self, ctx: commands.Context):
        """Ver el sticky actual del canal"""
        channel_id = ctx.channel.id
        
        if channel_id not in self.stickies:
            return await ctx.send(embed=warning_embed("No hay sticky en este canal"))
        
        sticky = self.stickies[channel_id]
        
        embed = discord.Embed(
            title="📌 Sticky Actual",
            color=config.BLURPLE_COLOR
        )
        
        if sticky.get("content"):
            embed.add_field(name="Contenido", value=sticky["content"][:1000], inline=False)
        
        if sticky.get("embed"):
            embed_data = sticky["embed"]
            if embed_data.get("title"):
                embed.add_field(name="Título del Embed", value=embed_data["title"], inline=True)
            if embed_data.get("description"):
                embed.add_field(name="Descripción", value=embed_data["description"][:500], inline=False)
        
        await ctx.send(embed=embed)
    
    @sticky.command(name="list", aliases=["all"])
    @commands.has_permissions(manage_messages=True)
    async def sticky_list(self, ctx: commands.Context):
        """Ver todos los stickies del servidor"""
        docs = await database.stickies.find({"guild_id": ctx.guild.id}).to_list(length=None)
        
        if not docs:
            return await ctx.send(embed=warning_embed("No hay stickies en este servidor"))
        
        embed = discord.Embed(
            title="📌 Stickies del Servidor",
            color=config.BLURPLE_COLOR
        )
        
        description = ""
        for doc in docs[:15]:
            channel = ctx.guild.get_channel(doc["channel_id"])
            if channel:
                content = doc.get("content") or doc.get("embed", {}).get("title", "Embed")
                if len(content) > 50:
                    content = content[:50] + "..."
                description += f"• {channel.mention}: `{content}`\n"
        
        embed.description = description or "No hay stickies"
        
        if len(docs) > 15:
            embed.set_footer(text=f"Y {len(docs) - 15} más...")
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Sticky(bot))
