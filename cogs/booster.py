"""
Cog Booster - Funciones para boosters del servidor
"""

from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional
from datetime import datetime

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed


class Booster(commands.Cog):
    """💎 Funciones para Boosters"""
    
    emoji = "💎"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Detectar cuando alguien empieza/deja de boostear"""
        # Verificar si cambió el estado de booster
        was_booster = before.premium_since is not None
        is_booster = after.premium_since is not None
        
        if was_booster == is_booster:
            return
        
        # Obtener configuración
        settings = await database.booster_settings.find_one({
            "guild_id": after.guild.id
        })
        
        if not settings:
            return
        
        if is_booster and not was_booster:
            # Nuevo booster
            if settings.get("boost_channel"):
                channel = after.guild.get_channel(settings["boost_channel"])
                if channel:
                    message = settings.get("boost_message", 
                        "🎉 ¡Gracias {user} por boostear el servidor!")
                    message = message.format(
                        user=after.mention,
                        username=after.name,
                        server=after.guild.name,
                        boosts=after.guild.premium_subscription_count
                    )
                    await channel.send(message)
            
            # Dar rol de booster personalizado
            if settings.get("boost_role"):
                role = after.guild.get_role(settings["boost_role"])
                if role:
                    try:
                        await after.add_roles(role, reason="Nuevo booster")
                    except:
                        pass
        
        elif was_booster and not is_booster:
            # Dejó de boostear
            # Quitar rol personalizado
            booster_data = await database.booster_roles.find_one({
                "guild_id": after.guild.id,
                "user_id": after.id
            })
            
            if booster_data and booster_data.get("custom_role_id"):
                role = after.guild.get_role(booster_data["custom_role_id"])
                if role:
                    try:
                        await role.delete(reason="Usuario dejó de boostear")
                    except:
                        pass
                
                await database.booster_roles.delete_one({
                    "guild_id": after.guild.id,
                    "user_id": after.id
                })
    
    async def is_booster(self, member: discord.Member) -> bool:
        """Verificar si un miembro es booster"""
        return member.premium_since is not None
    
    @commands.group(
        name="booster",
        aliases=["boost"],
        brief="Funciones para boosters",
        invoke_without_command=True
    )
    async def booster(self, ctx: commands.Context):
        """Funciones especiales para boosters del servidor"""
        embed = discord.Embed(
            title="💎 Funciones de Booster",
            description="Beneficios exclusivos para quienes boostean el servidor.",
            color=discord.Color.nitro_pink()
        )
        
        embed.add_field(
            name="Comandos para Boosters",
            value=f"`{ctx.prefix}booster role <color> [nombre]` - Crear rol personalizado\n"
                  f"`{ctx.prefix}booster color <color>` - Cambiar color del rol\n"
                  f"`{ctx.prefix}booster name <nombre>` - Cambiar nombre del rol\n"
                  f"`{ctx.prefix}booster icon <emoji/url>` - Icono del rol\n"
                  f"`{ctx.prefix}booster delete` - Eliminar rol personalizado",
            inline=False
        )
        
        embed.add_field(
            name="Comandos de Administración",
            value=f"`{ctx.prefix}booster setup` - Configurar sistema\n"
                  f"`{ctx.prefix}booster channel <canal>` - Canal de anuncios\n"
                  f"`{ctx.prefix}booster message <mensaje>` - Mensaje de boost\n"
                  f"`{ctx.prefix}booster baserole <rol>` - Rol base para posición",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @booster.command(name="role", aliases=["create"])
    async def booster_role(self, ctx: commands.Context, color: discord.Color, *, name: Optional[str] = None):
        """Crear un rol personalizado (solo boosters)"""
        if not await self.is_booster(ctx.author):
            return await ctx.send(embed=error_embed("Solo los boosters pueden usar este comando"))
        
        # Verificar si ya tiene rol
        existing = await database.booster_roles.find_one({
            "guild_id": ctx.guild.id,
            "user_id": ctx.author.id
        })
        
        if existing and existing.get("custom_role_id"):
            role = ctx.guild.get_role(existing["custom_role_id"])
            if role:
                return await ctx.send(embed=warning_embed(
                    f"Ya tienes un rol personalizado: {role.mention}\n"
                    f"Usa `{ctx.prefix}booster color` para cambiarlo."
                ))
        
        # Obtener configuración
        settings = await database.booster_settings.find_one({
            "guild_id": ctx.guild.id
        })
        
        # Posición del rol
        position = 1
        if settings and settings.get("base_role"):
            base_role = ctx.guild.get_role(settings["base_role"])
            if base_role:
                position = base_role.position
        
        role_name = name or f"✨ {ctx.author.display_name}"
        
        try:
            new_role = await ctx.guild.create_role(
                name=role_name,
                color=color,
                reason=f"Rol de booster para {ctx.author}"
            )
            
            # Mover a posición
            await new_role.edit(position=position)
            
            # Dar rol al usuario
            await ctx.author.add_roles(new_role)
            
            # Guardar en DB
            await database.booster_roles.update_one(
                {"guild_id": ctx.guild.id, "user_id": ctx.author.id},
                {
                    "$set": {
                        "custom_role_id": new_role.id,
                        "created_at": datetime.utcnow()
                    }
                },
                upsert=True
            )
            
            await ctx.send(embed=success_embed(f"Rol creado: {new_role.mention}"))
        
        except discord.HTTPException as e:
            await ctx.send(embed=error_embed(f"Error al crear rol: {e}"))
    
    @booster.command(name="color")
    async def booster_color(self, ctx: commands.Context, color: discord.Color):
        """Cambiar color del rol personalizado"""
        if not await self.is_booster(ctx.author):
            return await ctx.send(embed=error_embed("Solo los boosters pueden usar este comando"))
        
        data = await database.booster_roles.find_one({
            "guild_id": ctx.guild.id,
            "user_id": ctx.author.id
        })
        
        if not data or not data.get("custom_role_id"):
            return await ctx.send(embed=error_embed(
                f"No tienes rol personalizado. Usa `{ctx.prefix}booster role <color>`"
            ))
        
        role = ctx.guild.get_role(data["custom_role_id"])
        if not role:
            return await ctx.send(embed=error_embed("Tu rol fue eliminado"))
        
        await role.edit(color=color)
        await ctx.send(embed=success_embed(f"Color de {role.mention} actualizado"))
    
    @booster.command(name="name", aliases=["rename"])
    async def booster_name(self, ctx: commands.Context, *, name: str):
        """Cambiar nombre del rol personalizado"""
        if not await self.is_booster(ctx.author):
            return await ctx.send(embed=error_embed("Solo los boosters pueden usar este comando"))
        
        if len(name) > 100:
            return await ctx.send(embed=error_embed("El nombre es muy largo (máx 100)"))
        
        data = await database.booster_roles.find_one({
            "guild_id": ctx.guild.id,
            "user_id": ctx.author.id
        })
        
        if not data or not data.get("custom_role_id"):
            return await ctx.send(embed=error_embed("No tienes rol personalizado"))
        
        role = ctx.guild.get_role(data["custom_role_id"])
        if not role:
            return await ctx.send(embed=error_embed("Tu rol fue eliminado"))
        
        await role.edit(name=name)
        await ctx.send(embed=success_embed(f"Rol renombrado a: **{name}**"))
    
    @booster.command(name="icon", aliases=["emoji"])
    async def booster_icon(self, ctx: commands.Context, emoji: Optional[str] = None):
        """Establecer icono del rol (requiere nivel 2 de boost)"""
        if not await self.is_booster(ctx.author):
            return await ctx.send(embed=error_embed("Solo los boosters pueden usar este comando"))
        
        if ctx.guild.premium_tier < 2:
            return await ctx.send(embed=error_embed(
                "El servidor necesita nivel 2 de boost para iconos de rol"
            ))
        
        data = await database.booster_roles.find_one({
            "guild_id": ctx.guild.id,
            "user_id": ctx.author.id
        })
        
        if not data or not data.get("custom_role_id"):
            return await ctx.send(embed=error_embed("No tienes rol personalizado"))
        
        role = ctx.guild.get_role(data["custom_role_id"])
        if not role:
            return await ctx.send(embed=error_embed("Tu rol fue eliminado"))
        
        if emoji:
            # Intentar usar emoji personalizado
            try:
                # Verificar si es emoji del servidor
                partial_emoji = discord.PartialEmoji.from_str(emoji)
                if partial_emoji.id:
                    emoji_bytes = await partial_emoji.read()
                    await role.edit(display_icon=emoji_bytes)
                else:
                    await role.edit(display_icon=emoji)
                
                await ctx.send(embed=success_embed(f"Icono de {role.mention} actualizado"))
            except Exception as e:
                await ctx.send(embed=error_embed(f"Error: {e}"))
        else:
            # Quitar icono
            await role.edit(display_icon=None)
            await ctx.send(embed=success_embed("Icono eliminado"))
    
    @booster.command(name="delete", aliases=["remove"])
    async def booster_delete(self, ctx: commands.Context):
        """Eliminar tu rol personalizado"""
        data = await database.booster_roles.find_one({
            "guild_id": ctx.guild.id,
            "user_id": ctx.author.id
        })
        
        if not data or not data.get("custom_role_id"):
            return await ctx.send(embed=error_embed("No tienes rol personalizado"))
        
        role = ctx.guild.get_role(data["custom_role_id"])
        if role:
            await role.delete(reason="Eliminado por el usuario")
        
        await database.booster_roles.delete_one({
            "guild_id": ctx.guild.id,
            "user_id": ctx.author.id
        })
        
        await ctx.send(embed=success_embed("Rol personalizado eliminado"))
    
    # Comandos de administración
    @booster.command(name="setup")
    @commands.has_permissions(administrator=True)
    async def booster_setup(self, ctx: commands.Context):
        """Configurar sistema de boosters"""
        await database.booster_settings.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {"guild_id": ctx.guild.id},
                "$setOnInsert": {
                    "boost_channel": None,
                    "boost_message": "🎉 ¡Gracias {user} por boostear el servidor!",
                    "base_role": None
                }
            },
            upsert=True
        )
        
        await ctx.send(embed=success_embed(
            f"Sistema de boosters configurado!\n\n"
            f"Usa `{ctx.prefix}booster channel` para establecer el canal de anuncios."
        ))
    
    @booster.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def booster_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Establecer canal de anuncios de boost"""
        await database.booster_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"boost_channel": channel.id}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(f"Canal de boost: {channel.mention}"))
    
    @booster.command(name="message")
    @commands.has_permissions(administrator=True)
    async def booster_message(self, ctx: commands.Context, *, message: str):
        """Establecer mensaje de boost"""
        await database.booster_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"boost_message": message}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(
            f"Mensaje actualizado:\n{message}\n\n"
            f"Variables: `{{user}}`, `{{username}}`, `{{server}}`, `{{boosts}}`"
        ))
    
    @booster.command(name="baserole", aliases=["base"])
    @commands.has_permissions(administrator=True)
    async def booster_baserole(self, ctx: commands.Context, role: discord.Role):
        """Establecer rol base para posición de roles personalizados"""
        await database.booster_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"base_role": role.id}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(
            f"Rol base establecido: {role.mention}\n"
            f"Los roles de boosters se crearán justo encima de este rol."
        ))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Booster(bot))
