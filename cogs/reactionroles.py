"""
Cog ReactionRoles - Roles por reacción
"""

from __future__ import annotations

import asyncio
import discord
from discord.ext import commands
from typing import Optional, Union

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed


class ReactionRoles(commands.Cog):
    """🎯 Roles por reacción"""
    
    emoji = "🎯"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def get_reaction_role(
        self, 
        guild_id: int, 
        message_id: int, 
        emoji: Union[str, int]
    ) -> Optional[dict]:
        """Obtener reaction role"""
        query = {
            "guild_id": guild_id,
            "message_id": message_id
        }
        
        if isinstance(emoji, int):
            query["emoji_id"] = emoji
        else:
            query["emoji"] = emoji
        
        return await database.reaction_roles.find_one(query)
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Añadir rol cuando se añade reacción"""
        if payload.member is None or payload.member.bot:
            return
        
        # Buscar reaction role
        emoji_id = payload.emoji.id if payload.emoji.id else str(payload.emoji)
        
        rr = await self.get_reaction_role(
            payload.guild_id,
            payload.message_id,
            emoji_id
        )
        
        if not rr:
            return
        
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        role = guild.get_role(rr["role_id"])
        if not role:
            return
        
        try:
            await payload.member.add_roles(role, reason="Reaction Role")
        except discord.HTTPException:
            pass
    
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Quitar rol cuando se quita reacción"""
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return
        
        # Buscar reaction role
        emoji_id = payload.emoji.id if payload.emoji.id else str(payload.emoji)
        
        rr = await self.get_reaction_role(
            payload.guild_id,
            payload.message_id,
            emoji_id
        )
        
        if not rr:
            return
        
        role = guild.get_role(rr["role_id"])
        if not role:
            return
        
        try:
            await member.remove_roles(role, reason="Reaction Role removed")
        except discord.HTTPException:
            pass
    
    @commands.group(
        name="reactionrole",
        aliases=["rr", "reactionroles"],
        brief="Sistema de reaction roles",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_roles=True)
    async def reactionrole(self, ctx: commands.Context):
        """Sistema de roles por reacción"""
        embed = discord.Embed(
            title="🎯 Reaction Roles",
            description="Permite que los usuarios obtengan roles al reaccionar a mensajes",
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(
            name="Comandos",
            value=f"`{ctx.prefix}rr add <mensaje_id> <rol> <emoji>` - Añadir reaction role\n"
                  f"`{ctx.prefix}rr remove <mensaje_id> <emoji>` - Quitar reaction role\n"
                  f"`{ctx.prefix}rr list` - Ver reaction roles\n"
                  f"`{ctx.prefix}rr clear <mensaje_id>` - Limpiar de un mensaje",
            inline=False
        )
        
        embed.add_field(
            name="Ejemplo",
            value=f"`{ctx.prefix}rr add 123456789 @Miembro 👋`",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @reactionrole.command(name="add", aliases=["create", "new"])
    @commands.has_permissions(manage_roles=True)
    async def rr_add(
        self, 
        ctx: commands.Context, 
        message_id: int,
        role: discord.Role,
        emoji: Union[discord.Emoji, str]
    ):
        """Añadir un reaction role"""
        # Verificar que el bot pueda asignar el rol
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed(
                "No puedo asignar ese rol porque está por encima de mi rol más alto"
            ))
        
        # Verificar permisos peligrosos
        dangerous_perms = [
            role.permissions.administrator,
            role.permissions.ban_members,
            role.permissions.kick_members,
            role.permissions.manage_channels,
            role.permissions.manage_guild,
            role.permissions.manage_webhooks
        ]
        
        if any(dangerous_perms):
            return await ctx.send(embed=error_embed(
                "No se pueden usar roles con permisos peligrosos como reaction roles"
            ))
        
        # Intentar obtener el mensaje
        try:
            message = await ctx.channel.fetch_message(message_id)
        except discord.NotFound:
            return await ctx.send(embed=error_embed("Mensaje no encontrado en este canal"))
        except discord.HTTPException:
            return await ctx.send(embed=error_embed("Error al obtener el mensaje"))
        
        # Preparar datos
        emoji_id = emoji.id if isinstance(emoji, discord.Emoji) else str(emoji)
        emoji_str = str(emoji)
        
        # Verificar si ya existe
        existing = await self.get_reaction_role(ctx.guild.id, message_id, emoji_id)
        if existing:
            return await ctx.send(embed=error_embed(
                f"Ya existe un reaction role para ese emoji en ese mensaje"
            ))
        
        # Guardar en DB
        doc = {
            "guild_id": ctx.guild.id,
            "message_id": message_id,
            "channel_id": ctx.channel.id,
            "role_id": role.id,
            "emoji": emoji_str if isinstance(emoji, str) else None,
            "emoji_id": emoji.id if isinstance(emoji, discord.Emoji) else None
        }
        
        await database.reaction_roles.insert_one(doc)
        
        # Añadir reacción al mensaje
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            pass
        
        await ctx.send(embed=success_embed(
            f"Reaction role creado:\n"
            f"**Mensaje:** {message_id}\n"
            f"**Rol:** {role.mention}\n"
            f"**Emoji:** {emoji_str}"
        ))
    
    @reactionrole.command(name="remove", aliases=["delete", "del"])
    @commands.has_permissions(manage_roles=True)
    async def rr_remove(
        self, 
        ctx: commands.Context, 
        message_id: int,
        emoji: Union[discord.Emoji, str]
    ):
        """Quitar un reaction role"""
        emoji_id = emoji.id if isinstance(emoji, discord.Emoji) else str(emoji)
        
        result = await database.reaction_roles.delete_one({
            "guild_id": ctx.guild.id,
            "message_id": message_id,
            "$or": [
                {"emoji_id": emoji_id if isinstance(emoji, discord.Emoji) else None},
                {"emoji": emoji_id if isinstance(emoji, str) else None}
            ]
        })
        
        if result.deleted_count == 0:
            return await ctx.send(embed=error_embed("No se encontró ese reaction role"))
        
        await ctx.send(embed=success_embed("Reaction role eliminado"))
    
    @reactionrole.command(name="list", aliases=["ls", "view"])
    @commands.has_permissions(manage_roles=True)
    async def rr_list(self, ctx: commands.Context):
        """Ver lista de reaction roles"""
        rrs = await database.reaction_roles.find(
            {"guild_id": ctx.guild.id}
        ).to_list(length=None)
        
        if not rrs:
            return await ctx.send(embed=warning_embed("No hay reaction roles en este servidor"))
        
        embed = discord.Embed(
            title="🎯 Reaction Roles",
            color=config.BLURPLE_COLOR
        )
        
        description = ""
        for i, rr in enumerate(rrs[:15], 1):
            role = ctx.guild.get_role(rr["role_id"])
            role_text = role.mention if role else f"Rol eliminado ({rr['role_id']})"
            
            emoji_text = rr.get("emoji") or f"<:e:{rr.get('emoji_id')}>"
            
            description += f"`{i}.` Mensaje: `{rr['message_id']}` | {emoji_text} → {role_text}\n"
        
        embed.description = description
        
        if len(rrs) > 15:
            embed.set_footer(text=f"Y {len(rrs) - 15} más...")
        
        await ctx.send(embed=embed)
    
    @reactionrole.command(name="clear", aliases=["limpiar"])
    @commands.has_permissions(administrator=True)
    async def rr_clear(self, ctx: commands.Context, message_id: int = None):
        """Limpiar reaction roles de un mensaje o todos"""
        if message_id:
            result = await database.reaction_roles.delete_many({
                "guild_id": ctx.guild.id,
                "message_id": message_id
            })
            await ctx.send(embed=success_embed(
                f"Eliminados {result.deleted_count} reaction roles del mensaje"
            ))
        else:
            result = await database.reaction_roles.delete_many({
                "guild_id": ctx.guild.id
            })
            await ctx.send(embed=success_embed(
                f"Eliminados {result.deleted_count} reaction roles del servidor"
            ))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReactionRoles(bot))
