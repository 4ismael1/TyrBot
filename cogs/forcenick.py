"""
Cog ForceNick - Forzar apodos a usuarios
"""

from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed


class ForceNick(commands.Cog):
    """📛 Forzar apodos"""
    
    emoji = "📛"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Revertir cambio de apodo si está forzado"""
        if before.nick == after.nick:
            return
        
        doc = await database.forcenick.find_one({
            "guild_id": before.guild.id,
            "user_id": before.id
        })
        
        if not doc:
            return
        
        forced_nick = doc["nickname"]
        
        # Si el apodo actual es diferente al forzado, revertir
        if after.nick != forced_nick:
            try:
                await after.edit(nick=forced_nick, reason="ForceNick activo")
            except discord.HTTPException:
                pass
    
    @commands.group(
        name="forcenick",
        aliases=["fn", "forcenickname"],
        brief="Sistema de apodos forzados",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_nicknames=True)
    async def forcenick(self, ctx: commands.Context):
        """Sistema para forzar apodos a usuarios"""
        embed = discord.Embed(
            title="📛 Force Nickname",
            description="Fuerza un apodo a un usuario. Si lo cambian, se revertirá automáticamente.",
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(
            name="Comandos",
            value=f"`{ctx.prefix}forcenick add <usuario> <apodo>` - Forzar apodo\n"
                  f"`{ctx.prefix}forcenick remove <usuario>` - Quitar apodo forzado\n"
                  f"`{ctx.prefix}forcenick list` - Ver apodos forzados",
            inline=False
        )
        
        embed.add_field(
            name="Ejemplo",
            value=f"`{ctx.prefix}forcenick add @Usuario NuevoNick`",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @forcenick.command(name="add", aliases=["set", "force"])
    @commands.has_permissions(manage_nicknames=True)
    async def forcenick_add(self, ctx: commands.Context, member: discord.Member, *, nickname: str):
        """Forzar un apodo a un usuario"""
        # Verificar jerarquía
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send(embed=error_embed(
                "No puedes forzar apodo a alguien con rol igual o superior al tuyo"
            ))
        
        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed(
                "No puedo cambiar el apodo de ese usuario"
            ))
        
        # Verificar longitud
        if len(nickname) > 32:
            return await ctx.send(embed=error_embed(
                "El apodo no puede tener más de 32 caracteres"
            ))
        
        # Verificar si ya tiene forcenick
        existing = await database.forcenick.find_one({
            "guild_id": ctx.guild.id,
            "user_id": member.id
        })
        
        if existing:
            # Actualizar
            await database.forcenick.update_one(
                {"guild_id": ctx.guild.id, "user_id": member.id},
                {"$set": {"nickname": nickname}}
            )
        else:
            # Crear
            await database.forcenick.insert_one({
                "guild_id": ctx.guild.id,
                "user_id": member.id,
                "nickname": nickname,
                "set_by": ctx.author.id
            })
        
        # Aplicar apodo
        try:
            await member.edit(nick=nickname, reason=f"ForceNick por {ctx.author}")
        except discord.HTTPException as e:
            return await ctx.send(embed=error_embed(f"Error al cambiar apodo: {e}"))
        
        await ctx.send(embed=success_embed(
            f"Apodo de {member.mention} forzado a **{nickname}**"
        ))
    
    @forcenick.command(name="remove", aliases=["del", "delete", "clear"])
    @commands.has_permissions(manage_nicknames=True)
    async def forcenick_remove(self, ctx: commands.Context, member: discord.Member):
        """Quitar apodo forzado de un usuario"""
        result = await database.forcenick.delete_one({
            "guild_id": ctx.guild.id,
            "user_id": member.id
        })
        
        if result.deleted_count == 0:
            return await ctx.send(embed=error_embed(
                f"{member.mention} no tiene un apodo forzado"
            ))
        
        # Limpiar apodo
        try:
            await member.edit(nick=None, reason="ForceNick removido")
        except discord.HTTPException:
            pass
        
        await ctx.send(embed=success_embed(
            f"Apodo forzado de {member.mention} **removido**"
        ))
    
    @forcenick.command(name="list", aliases=["ls", "view", "all"])
    @commands.has_permissions(manage_nicknames=True)
    async def forcenick_list(self, ctx: commands.Context):
        """Ver lista de apodos forzados"""
        docs = await database.forcenick.find(
            {"guild_id": ctx.guild.id}
        ).to_list(length=None)
        
        if not docs:
            return await ctx.send(embed=warning_embed("No hay apodos forzados en este servidor"))
        
        embed = discord.Embed(
            title="📛 Apodos Forzados",
            color=config.BLURPLE_COLOR
        )
        
        description = ""
        for i, doc in enumerate(docs[:15], 1):
            member = ctx.guild.get_member(doc["user_id"])
            member_text = member.mention if member else f"Usuario salió ({doc['user_id']})"
            description += f"`{i}.` {member_text} → **{doc['nickname']}**\n"
        
        embed.description = description
        
        if len(docs) > 15:
            embed.set_footer(text=f"Y {len(docs) - 15} más...")
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ForceNick(bot))
