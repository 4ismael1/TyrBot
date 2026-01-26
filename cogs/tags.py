"""
Cog Tags - Sistema de tags/snippets personalizados
"""

from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional

from config import config
from core import database, cache
from utils import success_embed, error_embed, warning_embed, paginate


class Tags(commands.Cog):
    """🏷️ Sistema de tags personalizados"""
    
    emoji = "🏷️"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def get_tag(self, guild_id: int, name: str) -> Optional[dict]:
        """Obtener un tag por nombre o alias (con Redis cache)"""
        name_lower = name.lower()
        
        # Primero intentar Redis
        cached = await cache.get_tag(guild_id, name_lower)
        if cached:
            return cached
        
        # Buscar por nombre en DB
        tag = await database.tags.find_one({
            "guild_id": guild_id,
            "name": name_lower
        })
        
        if tag:
            await cache.set_tag(guild_id, name_lower, tag)
            return tag
        
        # Buscar por alias
        tag = await database.tags.find_one({
            "guild_id": guild_id,
            "aliases": name_lower
        })
        
        if tag:
            await cache.set_tag(guild_id, name_lower, tag)
        
        return tag
    
    async def invalidate_tag_cache(self, guild_id: int, name: str, aliases: list = None):
        """Invalidar caché de un tag y sus aliases"""
        await cache.invalidate_tag(guild_id, name.lower())
        if aliases:
            for alias in aliases:
                await cache.invalidate_tag(guild_id, alias.lower())
    
    @commands.group(
        name="tag",
        aliases=["t", "tags"],
        brief="Sistema de tags",
        invoke_without_command=True
    )
    async def tag(self, ctx: commands.Context, *, name: str = None):
        """
        Usar un tag existente.
        
        **Uso:** ;tag <nombre>
        **Ejemplo:** ;tag reglas
        """
        if not name:
            return await ctx.send_help(ctx.command)
        
        tag_data = await self.get_tag(ctx.guild.id, name)
        
        if not tag_data:
            return await ctx.send(embed=error_embed(f"Tag `{name}` no encontrado"))
        
        # Incrementar contador de usos
        await database.tags.update_one(
            {"_id": tag_data["_id"]},
            {"$inc": {"uses": 1}}
        )
        
        await ctx.send(tag_data["content"])
    
    @tag.command(name="create", aliases=["add", "new", "crear"])
    @commands.has_permissions(manage_messages=True)
    async def tag_create(self, ctx: commands.Context, name: str, *, content: str):
        """
        Crear un nuevo tag.
        
        **Uso:** ;tag create <nombre> <contenido>
        **Ejemplo:** ;tag create reglas No spam, sé respetuoso.
        """
        name = name.lower()
        
        # Verificar si existe
        existing = await self.get_tag(ctx.guild.id, name)
        if existing:
            return await ctx.send(embed=error_embed(f"El tag `{name}` ya existe"))
        
        # Verificar longitud
        if len(name) > 50:
            return await ctx.send(embed=error_embed("El nombre no puede tener más de 50 caracteres"))
        
        if len(content) > 2000:
            return await ctx.send(embed=error_embed("El contenido no puede tener más de 2000 caracteres"))
        
        # Crear tag
        await database.tags.insert_one({
            "guild_id": ctx.guild.id,
            "name": name,
            "content": content,
            "owner_id": ctx.author.id,
            "uses": 0,
            "aliases": [],
            "created_at": discord.utils.utcnow()
        })
        
        await ctx.send(embed=success_embed(f"Tag `{name}` creado correctamente"))
    
    @tag.command(name="delete", aliases=["remove", "del", "eliminar"])
    @commands.has_permissions(manage_messages=True)
    async def tag_delete(self, ctx: commands.Context, *, name: str):
        """Eliminar un tag"""
        name = name.lower()
        
        tag = await self.get_tag(ctx.guild.id, name)
        if not tag:
            return await ctx.send(embed=error_embed(f"Tag `{name}` no encontrado"))
        
        # Verificar permisos (dueño o admin)
        if tag["owner_id"] != ctx.author.id and not ctx.author.guild_permissions.administrator:
            return await ctx.send(embed=error_embed("Solo el creador o un admin puede eliminar este tag"))
        
        await database.tags.delete_one({"_id": tag["_id"]})
        
        # Invalidar caché
        await self.invalidate_tag_cache(ctx.guild.id, name, tag.get("aliases", []))
        
        await ctx.send(embed=success_embed(f"Tag `{name}` eliminado"))
    
    @tag.command(name="edit", aliases=["editar", "modify"])
    @commands.has_permissions(manage_messages=True)
    async def tag_edit(self, ctx: commands.Context, name: str, *, content: str):
        """Editar el contenido de un tag"""
        name = name.lower()
        
        tag = await self.get_tag(ctx.guild.id, name)
        if not tag:
            return await ctx.send(embed=error_embed(f"Tag `{name}` no encontrado"))
        
        if tag["owner_id"] != ctx.author.id and not ctx.author.guild_permissions.administrator:
            return await ctx.send(embed=error_embed("Solo el creador o un admin puede editar este tag"))
        
        if len(content) > 2000:
            return await ctx.send(embed=error_embed("El contenido no puede tener más de 2000 caracteres"))
        
        await database.tags.update_one(
            {"_id": tag["_id"]},
            {"$set": {"content": content}}
        )
        
        # Invalidar caché
        await self.invalidate_tag_cache(ctx.guild.id, name, tag.get("aliases", []))
        
        await ctx.send(embed=success_embed(f"Tag `{name}` actualizado"))
    
    @tag.command(name="info", aliases=["información", "details"])
    async def tag_info(self, ctx: commands.Context, *, name: str):
        """Ver información de un tag"""
        name = name.lower()
        
        tag = await self.get_tag(ctx.guild.id, name)
        if not tag:
            return await ctx.send(embed=error_embed(f"Tag `{name}` no encontrado"))
        
        owner = self.bot.get_user(tag["owner_id"])
        
        embed = discord.Embed(
            title=f"🏷️ Tag: {tag['name']}",
            color=config.BLURPLE_COLOR
        )
        embed.add_field(name="Creador", value=str(owner) if owner else f"ID: {tag['owner_id']}", inline=True)
        embed.add_field(name="Usos", value=str(tag["uses"]), inline=True)
        embed.add_field(name="Creado", value=discord.utils.format_dt(tag["created_at"], style="R"), inline=True)
        
        if tag.get("aliases"):
            embed.add_field(name="Aliases", value=", ".join(f"`{a}`" for a in tag["aliases"]), inline=False)
        
        await ctx.send(embed=embed)
    
    @tag.command(name="list", aliases=["all", "lista"])
    async def tag_list(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """Listar tags del servidor o de un usuario"""
        query = {"guild_id": ctx.guild.id}
        
        if member:
            query["owner_id"] = member.id
            title = f"🏷️ Tags de {member.display_name}"
        else:
            title = f"🏷️ Tags de {ctx.guild.name}"
        
        tags = await database.tags.find(query).sort("uses", -1).to_list(length=None)
        
        if not tags:
            return await ctx.send(embed=warning_embed("No hay tags"))
        
        # Crear páginas
        embeds = []
        for i in range(0, len(tags), 10):
            chunk = tags[i:i+10]
            
            description = "\n".join(
                f"`{tag['name']}` - {tag['uses']} usos"
                for tag in chunk
            )
            
            embed = discord.Embed(
                title=title,
                description=description,
                color=config.BLURPLE_COLOR
            )
            embed.set_footer(text=f"Total: {len(tags)} tags")
            embeds.append(embed)
        
        await paginate(ctx, embeds)
    
    @tag.command(name="alias", aliases=["shortcut"])
    @commands.has_permissions(manage_messages=True)
    async def tag_alias(self, ctx: commands.Context, tag_name: str, alias: str):
        """Añadir un alias a un tag"""
        tag_name = tag_name.lower()
        alias = alias.lower()
        
        tag = await self.get_tag(ctx.guild.id, tag_name)
        if not tag:
            return await ctx.send(embed=error_embed(f"Tag `{tag_name}` no encontrado"))
        
        # Verificar que el alias no exista
        existing = await self.get_tag(ctx.guild.id, alias)
        if existing:
            return await ctx.send(embed=error_embed(f"`{alias}` ya está en uso"))
        
        if alias in tag.get("aliases", []):
            return await ctx.send(embed=error_embed(f"`{alias}` ya es un alias de este tag"))
        
        await database.tags.update_one(
            {"_id": tag["_id"]},
            {"$push": {"aliases": alias}}
        )
        
        # Invalidar caché del tag
        await self.invalidate_tag_cache(ctx.guild.id, tag_name, tag.get("aliases", []))
        
        await ctx.send(embed=success_embed(f"Alias `{alias}` añadido al tag `{tag_name}`"))
    
    @tag.command(name="unalias", aliases=["removealias"])
    @commands.has_permissions(manage_messages=True)
    async def tag_unalias(self, ctx: commands.Context, tag_name: str, alias: str):
        """Remover un alias de un tag"""
        tag_name = tag_name.lower()
        alias = alias.lower()
        
        tag = await self.get_tag(ctx.guild.id, tag_name)
        if not tag:
            return await ctx.send(embed=error_embed(f"Tag `{tag_name}` no encontrado"))
        
        if alias not in tag.get("aliases", []):
            return await ctx.send(embed=error_embed(f"`{alias}` no es un alias de este tag"))
        
        await database.tags.update_one(
            {"_id": tag["_id"]},
            {"$pull": {"aliases": alias}}
        )
        
        # Invalidar caché
        await self.invalidate_tag_cache(ctx.guild.id, tag_name, [alias])
        
        await ctx.send(embed=success_embed(f"Alias `{alias}` removido"))
    
    @tag.command(name="search", aliases=["buscar"])
    async def tag_search(self, ctx: commands.Context, *, query: str):
        """Buscar tags por nombre"""
        tags = await database.tags.find({
            "guild_id": ctx.guild.id,
            "name": {"$regex": query, "$options": "i"}
        }).limit(10).to_list(length=10)
        
        if not tags:
            return await ctx.send(embed=warning_embed(f"No se encontraron tags con `{query}`"))
        
        description = "\n".join(f"`{tag['name']}`" for tag in tags)
        
        embed = discord.Embed(
            title=f"🔍 Resultados para '{query}'",
            description=description,
            color=config.BLURPLE_COLOR
        )
        
        await ctx.send(embed=embed)
    
    @tag.command(name="raw")
    async def tag_raw(self, ctx: commands.Context, *, name: str):
        """Ver el contenido raw de un tag (escapado)"""
        name = name.lower()
        
        tag = await self.get_tag(ctx.guild.id, name)
        if not tag:
            return await ctx.send(embed=error_embed(f"Tag `{name}` no encontrado"))
        
        # Escapar el contenido
        escaped = discord.utils.escape_markdown(tag["content"])
        
        await ctx.send(f"```\n{escaped[:1990]}\n```")
    
    @tag.command(name="claim", aliases=["reclamar"])
    async def tag_claim(self, ctx: commands.Context, *, name: str):
        """Reclamar un tag cuyo dueño dejó el servidor"""
        name = name.lower()
        
        tag = await self.get_tag(ctx.guild.id, name)
        if not tag:
            return await ctx.send(embed=error_embed(f"Tag `{name}` no encontrado"))
        
        # Verificar si el dueño aún está en el servidor
        owner = ctx.guild.get_member(tag["owner_id"])
        if owner:
            return await ctx.send(embed=error_embed("El dueño del tag aún está en el servidor"))
        
        await database.tags.update_one(
            {"_id": tag["_id"]},
            {"$set": {"owner_id": ctx.author.id}}
        )
        
        await ctx.send(embed=success_embed(f"Ahora eres el dueño del tag `{name}`"))
    
    @tag.command(name="transfer", aliases=["transferir"])
    async def tag_transfer(self, ctx: commands.Context, name: str, member: discord.Member):
        """Transferir un tag a otro usuario"""
        name = name.lower()
        
        tag = await self.get_tag(ctx.guild.id, name)
        if not tag:
            return await ctx.send(embed=error_embed(f"Tag `{name}` no encontrado"))
        
        if tag["owner_id"] != ctx.author.id and not ctx.author.guild_permissions.administrator:
            return await ctx.send(embed=error_embed("Solo el dueño puede transferir este tag"))
        
        await database.tags.update_one(
            {"_id": tag["_id"]},
            {"$set": {"owner_id": member.id}}
        )
        
        await ctx.send(embed=success_embed(f"Tag `{name}` transferido a {member.mention}"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tags(bot))
