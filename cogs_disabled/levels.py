"""
Cog Levels - Sistema de niveles y experiencia
"""

from __future__ import annotations

import discord
from discord.ext import commands, tasks
from typing import Optional, Dict, List
from datetime import datetime
import math
import random

from config import config
from core import database, cache
from utils import success_embed, error_embed, warning_embed


def xp_for_level(level: int) -> int:
    """Calcular XP necesaria para un nivel"""
    return 5 * (level ** 2) + 50 * level + 100


def level_from_xp(xp: int) -> int:
    """Calcular nivel desde XP"""
    level = 0
    while xp >= xp_for_level(level):
        xp -= xp_for_level(level)
        level += 1
    return level


class Levels(commands.Cog):
    """📊 Sistema de Niveles"""
    
    emoji = "📊"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cooldowns para XP: {guild_id: {user_id: timestamp}}
        self.cooldowns: Dict[int, Dict[int, float]] = {}
        # Cache de configuraciones
        self.configs: Dict[int, dict] = {}
        # Sync periódico
        self.sync_cache.start()
    
    def cog_unload(self):
        self.sync_cache.cancel()
    
    async def cog_load(self):
        """Cargar configuraciones"""
        async for doc in database.level_settings.find():
            self.configs[doc["guild_id"]] = doc
    
    @tasks.loop(minutes=5)
    async def sync_cache(self):
        """Sincronizar cache de configuraciones"""
        self.configs.clear()
        async for doc in database.level_settings.find():
            self.configs[doc["guild_id"]] = doc
    
    @sync_cache.before_loop
    async def before_sync(self):
        await self.bot.wait_until_ready()
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Dar XP por mensajes"""
        if message.author.bot or not message.guild:
            return
        
        guild_id = message.guild.id
        user_id = message.author.id
        
        # Verificar si el sistema está habilitado
        if guild_id not in self.configs:
            return
        
        config_data = self.configs[guild_id]
        
        if not config_data.get("enabled", True):
            return
        
        # Verificar canales bloqueados
        if message.channel.id in config_data.get("blocked_channels", []):
            return
        
        # Verificar roles bloqueados
        blocked_roles = config_data.get("blocked_roles", [])
        if any(role.id in blocked_roles for role in message.author.roles):
            return
        
        # Verificar cooldown (60 segundos por defecto)
        cooldown = config_data.get("cooldown", 60)
        now = datetime.utcnow().timestamp()
        
        if guild_id not in self.cooldowns:
            self.cooldowns[guild_id] = {}
        
        last_xp = self.cooldowns[guild_id].get(user_id, 0)
        if now - last_xp < cooldown:
            return
        
        self.cooldowns[guild_id][user_id] = now
        
        # Dar XP (15-25 por mensaje por defecto)
        min_xp = config_data.get("min_xp", 15)
        max_xp = config_data.get("max_xp", 25)
        xp_gained = random.randint(min_xp, max_xp)
        
        # Multiplicador por rol
        multipliers = config_data.get("multipliers", {})
        for role in message.author.roles:
            if str(role.id) in multipliers:
                xp_gained = int(xp_gained * multipliers[str(role.id)])
        
        # Obtener datos actuales
        user_data = await database.levels.find_one({
            "guild_id": guild_id,
            "user_id": user_id
        })
        
        if user_data:
            old_xp = user_data["xp"]
            new_xp = old_xp + xp_gained
            old_level = level_from_xp(old_xp)
            new_level = level_from_xp(new_xp)
            
            await database.levels.update_one(
                {"guild_id": guild_id, "user_id": user_id},
                {
                    "$inc": {"xp": xp_gained, "messages": 1},
                    "$set": {"level": new_level}
                }
            )
        else:
            new_xp = xp_gained
            old_level = 0
            new_level = level_from_xp(new_xp)
            
            await database.levels.insert_one({
                "guild_id": guild_id,
                "user_id": user_id,
                "xp": new_xp,
                "level": new_level,
                "messages": 1
            })
        
        # Verificar level up
        if new_level > old_level:
            await self._handle_level_up(message, old_level, new_level, config_data)
    
    async def _handle_level_up(
        self, 
        message: discord.Message, 
        old_level: int, 
        new_level: int,
        config_data: dict
    ):
        """Manejar subida de nivel"""
        # Enviar mensaje de level up
        levelup_channel_id = config_data.get("levelup_channel")
        levelup_message = config_data.get("levelup_message", 
            "🎉 ¡Felicidades {user}! Has subido al nivel **{level}**!")
        
        # Formatear mensaje
        levelup_message = levelup_message.format(
            user=message.author.mention,
            username=message.author.name,
            level=new_level,
            server=message.guild.name
        )
        
        if levelup_channel_id:
            channel = message.guild.get_channel(levelup_channel_id)
            if channel:
                await channel.send(levelup_message)
        else:
            await message.channel.send(levelup_message)
        
        # Dar roles por nivel
        level_roles = config_data.get("level_roles", {})
        for level_str, role_id in level_roles.items():
            if int(level_str) == new_level:
                role = message.guild.get_role(role_id)
                if role:
                    try:
                        await message.author.add_roles(role, reason=f"Nivel {new_level} alcanzado")
                    except discord.HTTPException:
                        pass
    
    @commands.group(
        name="level",
        aliases=["lvl", "rank", "xp"],
        brief="Sistema de niveles",
        invoke_without_command=True
    )
    async def level(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """
        Ver tu nivel, XP y ranking en el servidor.
        
        Ganas XP enviando mensajes (cooldown de 1 minuto).
        
        **Ejemplos:**
        ;level
        ;rank @usuario
        ;xp
        """
        member = member or ctx.author
        
        user_data = await database.levels.find_one({
            "guild_id": ctx.guild.id,
            "user_id": member.id
        })
        
        if not user_data:
            return await ctx.send(embed=warning_embed(
                f"{member.mention} no tiene experiencia aún"
            ))
        
        xp = user_data["xp"]
        level = user_data["level"]
        messages = user_data.get("messages", 0)
        
        # Calcular XP para siguiente nivel
        xp_for_current = sum(xp_for_level(i) for i in range(level))
        xp_for_next = xp_for_level(level)
        current_xp = xp - xp_for_current
        
        # Calcular posición en el ranking
        rank = await database.levels.count_documents({
            "guild_id": ctx.guild.id,
            "xp": {"$gt": xp}
        }) + 1
        
        # Crear embed
        embed = discord.Embed(
            title=f"📊 Nivel de {member.display_name}",
            color=config.BLURPLE_COLOR
        )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        
        embed.add_field(name="Nivel", value=f"**{level}**", inline=True)
        embed.add_field(name="XP", value=f"**{current_xp:,}** / {xp_for_next:,}", inline=True)
        embed.add_field(name="XP Total", value=f"**{xp:,}**", inline=True)
        embed.add_field(name="Ranking", value=f"#{rank}", inline=True)
        embed.add_field(name="Mensajes", value=f"{messages:,}", inline=True)
        
        # Barra de progreso
        progress = int((current_xp / xp_for_next) * 10)
        bar = "▓" * progress + "░" * (10 - progress)
        embed.add_field(name="Progreso", value=f"`{bar}` {int((current_xp/xp_for_next)*100)}%", inline=False)
        
        await ctx.send(embed=embed)
    
    @level.command(name="leaderboard", aliases=["lb", "top"])
    async def level_leaderboard(self, ctx: commands.Context, page: int = 1):
        """
        Ver el ranking de niveles del servidor.
        
        **Ejemplos:**
        ;level leaderboard
        ;level top
        ;level lb 2
        """
        if page < 1:
            page = 1
        
        per_page = 10
        skip = (page - 1) * per_page
        
        # Obtener usuarios ordenados por XP
        cursor = database.levels.find(
            {"guild_id": ctx.guild.id}
        ).sort("xp", -1).skip(skip).limit(per_page)
        
        users = await cursor.to_list(length=per_page)
        
        if not users:
            return await ctx.send(embed=warning_embed("No hay datos de niveles"))
        
        total = await database.levels.count_documents({"guild_id": ctx.guild.id})
        total_pages = math.ceil(total / per_page)
        
        embed = discord.Embed(
            title=f"🏆 Ranking de {ctx.guild.name}",
            color=discord.Color.gold()
        )
        
        description = ""
        for i, user_data in enumerate(users, start=skip + 1):
            member = ctx.guild.get_member(user_data["user_id"])
            name = member.display_name if member else f"Usuario ({user_data['user_id']})"
            
            # Emoji para top 3
            if i == 1:
                emoji = "🥇"
            elif i == 2:
                emoji = "🥈"
            elif i == 3:
                emoji = "🥉"
            else:
                emoji = f"`{i}.`"
            
            description += f"{emoji} **{name}** - Nivel {user_data['level']} ({user_data['xp']:,} XP)\n"
        
        embed.description = description
        embed.set_footer(text=f"Página {page}/{total_pages}")
        
        await ctx.send(embed=embed)
    
    @level.command(name="set")
    @commands.has_permissions(administrator=True)
    async def level_set(self, ctx: commands.Context, member: discord.Member, level: int):
        """Establecer nivel de un usuario"""
        if level < 0:
            return await ctx.send(embed=error_embed("El nivel no puede ser negativo"))
        
        # Calcular XP para el nivel
        xp = sum(xp_for_level(i) for i in range(level))
        
        await database.levels.update_one(
            {"guild_id": ctx.guild.id, "user_id": member.id},
            {
                "$set": {"level": level, "xp": xp},
                "$setOnInsert": {"messages": 0}
            },
            upsert=True
        )
        
        await ctx.send(embed=success_embed(f"Nivel de {member.mention} establecido a **{level}**"))
    
    @level.command(name="addxp", aliases=["givexp"])
    @commands.has_permissions(administrator=True)
    async def level_addxp(self, ctx: commands.Context, member: discord.Member, xp: int):
        """Dar XP a un usuario"""
        user_data = await database.levels.find_one({
            "guild_id": ctx.guild.id,
            "user_id": member.id
        })
        
        if user_data:
            new_xp = max(0, user_data["xp"] + xp)
        else:
            new_xp = max(0, xp)
        
        new_level = level_from_xp(new_xp)
        
        await database.levels.update_one(
            {"guild_id": ctx.guild.id, "user_id": member.id},
            {
                "$set": {"xp": new_xp, "level": new_level},
                "$setOnInsert": {"messages": 0}
            },
            upsert=True
        )
        
        action = "añadida" if xp >= 0 else "quitada"
        await ctx.send(embed=success_embed(
            f"**{abs(xp)} XP** {action} a {member.mention}\n"
            f"Nivel actual: **{new_level}** ({new_xp:,} XP)"
        ))
    
    @level.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def level_reset(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """Resetear niveles de un usuario o todo el servidor"""
        if member:
            await database.levels.delete_one({
                "guild_id": ctx.guild.id,
                "user_id": member.id
            })
            await ctx.send(embed=success_embed(f"Niveles de {member.mention} reseteados"))
        else:
            # Confirmar reset de todo el servidor
            await ctx.send(embed=warning_embed(
                f"⚠️ ¿Estás seguro de resetear TODOS los niveles del servidor?\n"
                f"Escribe `confirmar` para proceder."
            ))
            
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=30)
                if msg.content.lower() == "confirmar":
                    result = await database.levels.delete_many({"guild_id": ctx.guild.id})
                    await ctx.send(embed=success_embed(
                        f"**{result.deleted_count}** registros eliminados"
                    ))
                else:
                    await ctx.send(embed=warning_embed("Operación cancelada"))
            except:
                await ctx.send(embed=warning_embed("Tiempo agotado"))
    
    @commands.group(
        name="levelconfig",
        aliases=["levelset", "lvlconfig"],
        brief="Configurar sistema de niveles",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_guild=True)
    async def levelconfig(self, ctx: commands.Context):
        """Configurar el sistema de niveles"""
        embed = discord.Embed(
            title="📊 Configuración de Niveles",
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(
            name="Comandos",
            value=f"`{ctx.prefix}levelconfig enable` - Activar sistema\n"
                  f"`{ctx.prefix}levelconfig disable` - Desactivar sistema\n"
                  f"`{ctx.prefix}levelconfig channel <canal>` - Canal de level-ups\n"
                  f"`{ctx.prefix}levelconfig message <mensaje>` - Mensaje de level-up\n"
                  f"`{ctx.prefix}levelconfig role <nivel> <rol>` - Rol por nivel\n"
                  f"`{ctx.prefix}levelconfig multiplier <rol> <x>` - Multiplicador de XP\n"
                  f"`{ctx.prefix}levelconfig block <canal/rol>` - Bloquear XP\n"
                  f"`{ctx.prefix}levelconfig settings` - Ver configuración",
            inline=False
        )
        
        embed.add_field(
            name="Variables del mensaje",
            value="`{user}` - Mención\n`{username}` - Nombre\n`{level}` - Nivel\n`{server}` - Servidor",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @levelconfig.command(name="enable")
    @commands.has_permissions(manage_guild=True)
    async def levelconfig_enable(self, ctx: commands.Context):
        """Activar sistema de niveles"""
        await database.level_settings.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {"enabled": True, "guild_id": ctx.guild.id},
                "$setOnInsert": {
                    "cooldown": 60,
                    "min_xp": 15,
                    "max_xp": 25,
                    "blocked_channels": [],
                    "blocked_roles": [],
                    "level_roles": {},
                    "multipliers": {}
                }
            },
            upsert=True
        )
        
        self.configs[ctx.guild.id] = {"enabled": True, "guild_id": ctx.guild.id}
        
        await ctx.send(embed=success_embed("Sistema de niveles **activado**"))
    
    @levelconfig.command(name="disable")
    @commands.has_permissions(manage_guild=True)
    async def levelconfig_disable(self, ctx: commands.Context):
        """Desactivar sistema de niveles"""
        await database.level_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"enabled": False}}
        )
        
        if ctx.guild.id in self.configs:
            self.configs[ctx.guild.id]["enabled"] = False
        
        await ctx.send(embed=success_embed("Sistema de niveles **desactivado**"))
    
    @levelconfig.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def levelconfig_channel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Establecer canal de level-ups (ninguno = canal actual)"""
        channel_id = channel.id if channel else None
        
        await database.level_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"levelup_channel": channel_id}},
            upsert=True
        )
        
        if ctx.guild.id in self.configs:
            self.configs[ctx.guild.id]["levelup_channel"] = channel_id
        
        if channel:
            await ctx.send(embed=success_embed(f"Canal de level-ups: {channel.mention}"))
        else:
            await ctx.send(embed=success_embed("Level-ups se enviarán en el canal actual"))
    
    @levelconfig.command(name="message", aliases=["msg"])
    @commands.has_permissions(manage_guild=True)
    async def levelconfig_message(self, ctx: commands.Context, *, message: str):
        """Establecer mensaje de level-up"""
        await database.level_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"levelup_message": message}},
            upsert=True
        )
        
        if ctx.guild.id in self.configs:
            self.configs[ctx.guild.id]["levelup_message"] = message
        
        await ctx.send(embed=success_embed(f"Mensaje de level-up actualizado:\n{message}"))
    
    @levelconfig.command(name="role", aliases=["levelrole"])
    @commands.has_permissions(manage_guild=True)
    async def levelconfig_role(self, ctx: commands.Context, level: int, role: discord.Role):
        """Establecer rol que se da al alcanzar un nivel"""
        if level < 1:
            return await ctx.send(embed=error_embed("El nivel debe ser mayor a 0"))
        
        await database.level_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {f"level_roles.{level}": role.id}},
            upsert=True
        )
        
        if ctx.guild.id in self.configs:
            if "level_roles" not in self.configs[ctx.guild.id]:
                self.configs[ctx.guild.id]["level_roles"] = {}
            self.configs[ctx.guild.id]["level_roles"][str(level)] = role.id
        
        await ctx.send(embed=success_embed(f"Rol {role.mention} se dará al alcanzar nivel **{level}**"))
    
    @levelconfig.command(name="settings", aliases=["config"])
    @commands.has_permissions(manage_guild=True)
    async def levelconfig_settings(self, ctx: commands.Context):
        """Ver configuración actual"""
        config_data = self.configs.get(ctx.guild.id, {})
        
        embed = discord.Embed(
            title="📊 Configuración de Niveles",
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(name="Estado", value="✅ Activado" if config_data.get("enabled") else "❌ Desactivado", inline=True)
        embed.add_field(name="Cooldown", value=f"{config_data.get('cooldown', 60)}s", inline=True)
        embed.add_field(name="XP/Mensaje", value=f"{config_data.get('min_xp', 15)}-{config_data.get('max_xp', 25)}", inline=True)
        
        channel_id = config_data.get("levelup_channel")
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        embed.add_field(name="Canal Level-ups", value=channel.mention if channel else "Canal actual", inline=True)
        
        # Roles por nivel
        level_roles = config_data.get("level_roles", {})
        if level_roles:
            roles_text = "\n".join([f"Nivel {lvl}: <@&{rid}>" for lvl, rid in list(level_roles.items())[:5]])
            embed.add_field(name="Roles por Nivel", value=roles_text, inline=False)
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Levels(bot))
