"""
Cog Autorole - Roles automáticos al entrar
"""

from __future__ import annotations

import asyncio
import discord
from discord.ext import commands, tasks
from typing import Optional

from config import config
from core import database, cache
from utils import success_embed, error_embed, warning_embed


class Autorole(commands.Cog):
    """🎭 Roles automáticos"""
    
    emoji = "🎭"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # Cache local
        self._cache: dict[int, list[int]] = {}
        
        # Iniciar tareas
        self.sync_cache.start()
    
    def cog_unload(self):
        self.sync_cache.cancel()
    
    @tasks.loop(minutes=30)
    async def sync_cache(self):
        """Sincronizar configuraciones desde DB"""
        async for doc in database.autoroles.find({}):
            self._cache[doc["guild_id"]] = doc.get("roles", [])
    
    @sync_cache.before_loop
    async def before_sync_cache(self):
        await self.bot.wait_until_ready()
    
    async def invalidate_cache(self, guild_id: int):
        """Invalidar caché de autorole"""
        if guild_id in self._cache:
            del self._cache[guild_id]
        await cache.invalidate_autorole(guild_id)
    
    async def get_autoroles(self, guild_id: int) -> list[int]:
        """Obtener autoroles de un servidor con caché Redis"""
        # Primero cache local
        if guild_id in self._cache:
            return self._cache[guild_id]
        
        # Luego Redis
        cached = await cache.get_autorole(guild_id)
        if cached:
            self._cache[guild_id] = cached.get("roles", [])
            return self._cache[guild_id]
        
        # Finalmente base de datos
        doc = await database.autoroles.find_one({"guild_id": guild_id})
        if doc:
            self._cache[guild_id] = doc.get("roles", [])
            # Guardar en Redis
            await cache.set_autorole(guild_id, {"roles": self._cache[guild_id]})
            return self._cache[guild_id]
        
        return []
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Asignar roles automáticamente cuando un miembro se une"""
        if member.bot:
            return
        
        autoroles = await self.get_autoroles(member.guild.id)
        if not autoroles:
            return
        
        roles_to_add = []
        for role_id in autoroles:
            role = member.guild.get_role(role_id)
            if role and role < member.guild.me.top_role:
                roles_to_add.append(role)
        
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Autorole")
            except discord.HTTPException:
                pass
    
    @commands.group(
        name="autorole",
        aliases=["auto", "arole"],
        brief="Sistema de autoroles",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_roles=True)
    async def autorole(self, ctx: commands.Context):
        """Sistema de roles automáticos"""
        autoroles = await self.get_autoroles(ctx.guild.id)
        
        embed = discord.Embed(
            title="🎭 Autoroles",
            description="Roles que se asignan automáticamente a nuevos miembros",
            color=config.BLURPLE_COLOR
        )
        
        if autoroles:
            roles_text = "\n".join(
                f"`{i+1}.` <@&{role_id}>"
                for i, role_id in enumerate(autoroles)
            )
            embed.add_field(name="Roles activos", value=roles_text, inline=False)
        else:
            embed.add_field(
                name="Sin autoroles",
                value="No hay autoroles configurados",
                inline=False
            )
        
        embed.add_field(
            name="Comandos",
            value=f"`{ctx.prefix}autorole add <rol>` - Añadir autorole\n"
                  f"`{ctx.prefix}autorole remove <rol>` - Quitar autorole\n"
                  f"`{ctx.prefix}autorole clear` - Limpiar todos\n"
                  f"`{ctx.prefix}autorole list` - Ver lista",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @autorole.command(name="add", aliases=["agregar", "new"])
    @commands.has_permissions(manage_roles=True)
    async def autorole_add(self, ctx: commands.Context, role: discord.Role):
        """Añadir un autorole"""
        # Verificar que el bot pueda asignar el rol
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed(
                "No puedo asignar ese rol porque está por encima de mi rol más alto"
            ))
        
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send(embed=error_embed(
                "No puedes añadir un rol igual o superior al tuyo"
            ))
        
        # Verificar límite
        autoroles = await self.get_autoroles(ctx.guild.id)
        if len(autoroles) >= 5:
            return await ctx.send(embed=error_embed(
                "Máximo 5 autoroles por servidor"
            ))
        
        if role.id in autoroles:
            return await ctx.send(embed=error_embed(
                f"{role.mention} ya es un autorole"
            ))
        
        # Añadir
        await database.autoroles.update_one(
            {"guild_id": ctx.guild.id},
            {"$push": {"roles": role.id}},
            upsert=True
        )
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed(
            f"{role.mention} añadido como autorole"
        ))
    
    @autorole.command(name="remove", aliases=["quitar", "del", "delete"])
    @commands.has_permissions(manage_roles=True)
    async def autorole_remove(self, ctx: commands.Context, role: discord.Role):
        """Quitar un autorole"""
        autoroles = await self.get_autoroles(ctx.guild.id)
        
        if role.id not in autoroles:
            return await ctx.send(embed=error_embed(
                f"{role.mention} no es un autorole"
            ))
        
        await database.autoroles.update_one(
            {"guild_id": ctx.guild.id},
            {"$pull": {"roles": role.id}}
        )
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed(
            f"{role.mention} removido de autoroles"
        ))
    
    @autorole.command(name="clear", aliases=["limpiar", "reset"])
    @commands.has_permissions(administrator=True)
    async def autorole_clear(self, ctx: commands.Context):
        """Limpiar todos los autoroles"""
        await database.autoroles.delete_one({"guild_id": ctx.guild.id})
        
        if ctx.guild.id in self._cache:
            del self._cache[ctx.guild.id]
        
        await ctx.send(embed=success_embed("Todos los autoroles han sido eliminados"))
    
    @autorole.command(name="list", aliases=["ls", "view", "ver"])
    @commands.has_permissions(manage_roles=True)
    async def autorole_list(self, ctx: commands.Context):
        """Ver lista de autoroles"""
        autoroles = await self.get_autoroles(ctx.guild.id)
        
        if not autoroles:
            return await ctx.send(embed=warning_embed("No hay autoroles configurados"))
        
        embed = discord.Embed(
            title="🎭 Autoroles",
            color=config.BLURPLE_COLOR
        )
        
        description = ""
        for i, role_id in enumerate(autoroles, 1):
            role = ctx.guild.get_role(role_id)
            if role:
                description += f"`{i}.` {role.mention} ({role.id})\n"
            else:
                description += f"`{i}.` Rol eliminado ({role_id})\n"
        
        embed.description = description
        embed.set_footer(text=f"{len(autoroles)}/5 autoroles")
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Autorole(bot))
