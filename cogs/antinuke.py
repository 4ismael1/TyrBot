"""
Cog de Antinuke - Protección avanzada del servidor
"""

from __future__ import annotations

import asyncio
import discord
from discord.ext import commands, tasks
from discord import AuditLogAction
from datetime import datetime, timedelta
from typing import Optional, Literal
from enum import Enum

from config import config
from core import database, cache
from utils import success_embed, error_embed, warning_embed, paginate


class Punishment(Enum):
    """Tipos de castigo disponibles"""
    BAN = "ban"
    KICK = "kick"
    STRIP = "strip"  # Quitar todos los roles
    QUARANTINE = "quarantine"  # Asignar rol de cuarentena


class AntinukeAction(Enum):
    """Acciones monitoreadas por antinuke"""
    BAN_MEMBERS = "ban_members"
    KICK_MEMBERS = "kick_members"
    CREATE_CHANNELS = "create_channels"
    DELETE_CHANNELS = "delete_channels"
    CREATE_ROLES = "create_roles"
    DELETE_ROLES = "delete_roles"
    CREATE_WEBHOOKS = "create_webhooks"
    MENTION_EVERYONE = "mention_everyone"
    ADD_BOT = "add_bot"


def antinuke_trusted():
    """Check que verifica si el usuario es owner o está en la lista de trusted"""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return False
        # El owner siempre puede
        if ctx.author.id == ctx.guild.owner_id:
            return True
        # Verificar si está en la lista de trusted
        cog = ctx.bot.get_cog("Antinuke")
        if cog and await cog.is_trusted(ctx.guild.id, ctx.author.id):
            return True
        raise commands.CheckFailure("Solo el **owner** o usuarios **trusted** pueden usar esto")
    return commands.check(predicate)


class Antinuke(commands.Cog):
    """🛡️ Sistema de protección antinuke para tu servidor"""
    
    emoji = "🛡️"
    
    # Configuración por defecto
    DEFAULT_SETTINGS = {
        "enabled": False,
        "punishment": Punishment.BAN.value,
        "log_channel": None,
        "alert_role": None,  # Rol a mencionar en alertas
        "quarantine_role": None,  # Rol de cuarentena
        "mute_role": None,  # Rol de mute
        "revert_actions": True,  # Revertir acciones (eliminar canales/roles creados)
        "trusted": [],  # Lista de usuarios que pueden configurar
        "actions": {
            AntinukeAction.BAN_MEMBERS.value: {"enabled": False, "limit": 3},
            AntinukeAction.KICK_MEMBERS.value: {"enabled": False, "limit": 3},
            AntinukeAction.CREATE_CHANNELS.value: {"enabled": False, "limit": 5},
            AntinukeAction.DELETE_CHANNELS.value: {"enabled": False, "limit": 3},
            AntinukeAction.CREATE_ROLES.value: {"enabled": False, "limit": 5},
            AntinukeAction.DELETE_ROLES.value: {"enabled": False, "limit": 3},
            AntinukeAction.CREATE_WEBHOOKS.value: {"enabled": False, "limit": 3},
            AntinukeAction.MENTION_EVERYONE.value: {"enabled": False, "limit": 3},
            AntinukeAction.ADD_BOT.value: {"enabled": False, "limit": 1},
        }
    }
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # Cache local de configuraciones
        self._settings_cache: dict[int, dict] = {}
        self._whitelist_cache: dict[int, set[int]] = {}
        self._trusted_cache: dict[int, set[int]] = {}
        
        # Contadores de acciones (para rate limiting)
        self._action_counts: dict[str, int] = {}
        
        # Iniciar tareas
        self.clear_action_counts.start()
        self.sync_cache.start()
    
    def cog_unload(self):
        self.clear_action_counts.cancel()
        self.sync_cache.cancel()
    
    # ========== Tasks ==========
    
    @tasks.loop(seconds=30)
    async def clear_action_counts(self):
        """Limpiar contadores de acciones cada 30 segundos"""
        self._action_counts.clear()
    
    @tasks.loop(minutes=5)
    async def sync_cache(self):
        """Sincronizar caché desde la base de datos"""
        async for doc in database.antinuke_servers.find({"enabled": True}):
            guild_id = doc["guild_id"]
            self._settings_cache[guild_id] = doc
            
            # Cargar whitelist
            whitelist = await database.antinuke_whitelist.find(
                {"guild_id": guild_id}
            ).to_list(length=None)
            self._whitelist_cache[guild_id] = {w["user_id"] for w in whitelist}
            
            # Cargar admins
            self._trusted_cache[guild_id] = set(doc.get("trusted", []))
    
    @sync_cache.before_loop
    async def before_sync_cache(self):
        await self.bot.wait_until_ready()
    
    # ========== Helpers ==========
    
    async def get_settings(self, guild_id: int) -> dict:
        """Obtener configuración de antinuke para un servidor"""
        # Primero intentar cache local
        if guild_id in self._settings_cache:
            return self._settings_cache[guild_id]
        
        # Luego intentar Redis
        cached = await cache.get_antinuke_settings(guild_id)
        if cached:
            self._settings_cache[guild_id] = cached
            return cached
        
        # Finalmente, base de datos
        doc = await database.antinuke_servers.find_one({"guild_id": guild_id})
        
        if doc:
            self._settings_cache[guild_id] = doc
            await cache.set_antinuke_settings(guild_id, doc)
            return doc
        
        return self.DEFAULT_SETTINGS.copy()
    
    async def invalidate_cache(self, guild_id: int):
        """Invalidar cache para un guild específico"""
        if guild_id in self._settings_cache:
            del self._settings_cache[guild_id]
        if guild_id in self._whitelist_cache:
            del self._whitelist_cache[guild_id]
        if guild_id in self._trusted_cache:
            del self._trusted_cache[guild_id]
    
    async def is_whitelisted(self, guild_id: int, user_id: int) -> bool:
        """Verificar si un usuario está en la whitelist"""
        if guild_id in self._whitelist_cache:
            return user_id in self._whitelist_cache[guild_id]
        
        # Cargar whitelist si no está en caché
        whitelist = await cache.get_antinuke_whitelist(guild_id)
        if whitelist is None:
            docs = await database.antinuke_whitelist.find(
                {"guild_id": guild_id}
            ).to_list(length=None)
            whitelist = [d["user_id"] for d in docs]
            await cache.set_antinuke_whitelist(guild_id, whitelist)
        
        self._whitelist_cache[guild_id] = set(whitelist)
        return user_id in self._whitelist_cache[guild_id]
    
    async def is_trusted(self, guild_id: int, user_id: int) -> bool:
        """Verificar si un usuario está en la lista de trusted"""
        if guild_id in self._trusted_cache:
            return user_id in self._trusted_cache[guild_id]
        
        settings = await self.get_settings(guild_id)
        trusted = set(settings.get("trusted", []))
        self._trusted_cache[guild_id] = trusted
        return user_id in trusted
    
    async def increment_action(
        self, 
        guild_id: int, 
        user_id: int, 
        action: AntinukeAction
    ) -> int:
        """Incrementar contador de acción y retornar el total"""
        key = f"{guild_id}:{user_id}:{action.value}"
        
        # Usar Redis para conteo distribuido
        count = await cache.increment_action_count(guild_id, user_id, action.value)
        
        # Backup en memoria si Redis falla
        if count == 0:
            if key not in self._action_counts:
                self._action_counts[key] = 0
            self._action_counts[key] += 1
            count = self._action_counts[key]
        
        return count
    
    async def execute_punishment(
        self,
        guild: discord.Guild,
        perpetrator: discord.Member,
        action: AntinukeAction,
        punishment: Punishment
    ) -> bool:
        """Ejecutar castigo al perpetrador"""
        reason = f"Antinuke: Excedió el límite de {action.value}"
        
        # Enviar DM al usuario antes del castigo
        punishment_names = {
            Punishment.BAN: ("baneado", "🔨"),
            Punishment.KICK: ("expulsado", "👢"),
            Punishment.STRIP: ("despojado de roles", "📛"),
            Punishment.QUARANTINE: ("puesto en cuarentena", "🔒")
        }
        action_name, emoji = punishment_names.get(punishment, ("castigado", "⚠️"))
        
        try:
            dm_embed = discord.Embed(
                title=f"{emoji} Acción de Antinuke",
                description=f"Has sido **{action_name}** en **{guild.name}**",
                color=discord.Color.red()
            )
            dm_embed.add_field(
                name="📋 Motivo",
                value=f"El sistema de protección detectó actividad sospechosa:\n**{action.value}**",
                inline=False
            )
            dm_embed.add_field(
                name="ℹ️ Info",
                value="Si crees que esto fue un error, contacta a un administrador del servidor.",
                inline=False
            )
            dm_embed.set_footer(text=f"Servidor: {guild.name}", icon_url=guild.icon.url if guild.icon else None)
            await perpetrator.send(embed=dm_embed)
        except discord.HTTPException:
            pass  # No se pudo enviar DM, continuar con el castigo
        
        try:
            if punishment == Punishment.BAN:
                await guild.ban(perpetrator, reason=reason)
            elif punishment == Punishment.KICK:
                await guild.kick(perpetrator, reason=reason)
            elif punishment == Punishment.STRIP:
                # Quitar todos los roles (excepto @everyone)
                roles_to_remove = [r for r in perpetrator.roles if r != guild.default_role]
                await perpetrator.remove_roles(*roles_to_remove, reason=reason)
            elif punishment == Punishment.QUARANTINE:
                # Asignar rol de cuarentena y quitar otros roles
                settings = await self.get_settings(guild.id)
                quarantine_role_id = settings.get("quarantine_role")
                
                if quarantine_role_id:
                    quarantine_role = guild.get_role(quarantine_role_id)
                    if quarantine_role:
                        # Guardar roles actuales para poder restaurarlos después
                        current_roles = [r.id for r in perpetrator.roles if r != guild.default_role and r != quarantine_role]
                        
                        # Guardar en base de datos
                        await database.quarantine.update_one(
                            {"guild_id": guild.id, "user_id": perpetrator.id},
                            {"$set": {
                                "guild_id": guild.id,
                                "user_id": perpetrator.id,
                                "previous_roles": current_roles,
                                "moderator_id": self.bot.user.id,
                                "reason": reason,
                                "source": "antinuke",
                                "timestamp": datetime.utcnow()
                            }},
                            upsert=True
                        )
                        
                        # Quitar todos los roles y asignar cuarentena
                        roles_to_remove = [r for r in perpetrator.roles if r != guild.default_role]
                        await perpetrator.remove_roles(*roles_to_remove, reason=reason)
                        await perpetrator.add_roles(quarantine_role, reason=reason)
                    else:
                        # Si no existe el rol, hacer strip
                        roles_to_remove = [r for r in perpetrator.roles if r != guild.default_role]
                        await perpetrator.remove_roles(*roles_to_remove, reason=reason)
                else:
                    # Si no hay rol configurado, hacer strip
                    roles_to_remove = [r for r in perpetrator.roles if r != guild.default_role]
                    await perpetrator.remove_roles(*roles_to_remove, reason=reason)
            
            return True
        except discord.HTTPException:
            return False
    
    async def log_action(
        self,
        guild: discord.Guild,
        perpetrator: discord.Member,
        action: AntinukeAction,
        punishment: str,
        success: bool
    ):
        """Registrar acción en el canal de logs"""
        settings = await self.get_settings(guild.id)
        log_channel_id = settings.get("log_channel")
        
        if not log_channel_id:
            return
        
        channel = guild.get_channel(log_channel_id)
        if not channel:
            return
        
        color = config.SUCCESS_COLOR if success else config.ERROR_COLOR
        status = "✅ Acción tomada" if success else "❌ No se pudo tomar acción"
        
        embed = discord.Embed(
            title="🛡️ Antinuke Activado",
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Perpetrador", value=f"{perpetrator} ({perpetrator.id})", inline=True)
        embed.add_field(name="Acción detectada", value=action.value, inline=True)
        embed.add_field(name="Castigo", value=punishment, inline=True)
        embed.add_field(name="Estado", value=status, inline=False)
        embed.set_thumbnail(url=perpetrator.display_avatar.url)
        
        # Mención de rol de alerta
        alert_role_id = settings.get("alert_role")
        content = None
        if alert_role_id:
            alert_role = guild.get_role(alert_role_id)
            if alert_role:
                content = alert_role.mention
        
        try:
            await channel.send(content=content, embed=embed)
        except discord.HTTPException:
            pass
    
    async def check_and_punish(
        self,
        guild: discord.Guild,
        user_id: int,
        action: AntinukeAction
    ) -> bool:
        """
        Verificar si se debe castigar y ejecutar castigo si corresponde.
        Retorna True si se tomó acción.
        """
        # Obtener configuración
        settings = await self.get_settings(guild.id)
        
        if not settings.get("enabled"):
            return False
        
        action_config = settings.get("actions", {}).get(action.value, {})
        if not action_config.get("enabled"):
            return False
        
        # SOLO excluir whitelist y owner - nadie más
        # El antinuke debe actuar contra CUALQUIERA que abuse, incluso admins
        if await self.is_whitelisted(guild.id, user_id):
            return False
        
        # El dueño nunca es castigado
        if user_id == guild.owner_id:
            return False
        
        # Incrementar contador
        limit = action_config.get("limit", 3)
        count = await self.increment_action(guild.id, user_id, action)
        
        if count < limit:
            return False
        
        # Obtener miembro
        member = guild.get_member(user_id)
        if not member:
            return False
        
        # Verificar que podemos tomar acción
        if member.top_role >= guild.me.top_role:
            return False
        
        # Ejecutar castigo
        punishment = Punishment(settings.get("punishment", Punishment.BAN.value))
        success = await self.execute_punishment(guild, member, action, punishment)
        
        # Log
        await self.log_action(guild, member, action, punishment.value, success)
        
        return success
    
    # ========== Event Listeners ==========
    
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        """Detectar baneos masivos"""
        # Obtener el responsable del audit log
        async for entry in guild.audit_logs(action=AuditLogAction.ban, limit=1):
            if entry.target.id == user.id:
                await self.check_and_punish(
                    guild, 
                    entry.user.id, 
                    AntinukeAction.BAN_MEMBERS
                )
                break
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Detectar kicks masivos"""
        guild = member.guild
        
        # Verificar si fue kick (no ban ni salida voluntaria)
        async for entry in guild.audit_logs(action=AuditLogAction.kick, limit=1):
            if entry.target.id == member.id:
                # Verificar que fue reciente (últimos 5 segundos)
                if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).seconds < 5:
                    await self.check_and_punish(
                        guild,
                        entry.user.id,
                        AntinukeAction.KICK_MEMBERS
                    )
                break
    
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        """Detectar creación masiva de canales"""
        async for entry in channel.guild.audit_logs(action=AuditLogAction.channel_create, limit=1):
            if entry.target.id == channel.id:
                punished = await self.check_and_punish(
                    channel.guild,
                    entry.user.id,
                    AntinukeAction.CREATE_CHANNELS
                )
                
                # Si se castigó, revertir la acción (eliminar el canal)
                if punished:
                    settings = await self.get_settings(channel.guild.id)
                    if settings.get("revert_actions", True):
                        try:
                            await channel.delete(reason="Antinuke: Revirtiendo canal creado maliciosamente")
                        except discord.HTTPException:
                            pass
                break
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        """Detectar eliminación masiva de canales"""
        async for entry in channel.guild.audit_logs(action=AuditLogAction.channel_delete, limit=1):
            await self.check_and_punish(
                channel.guild,
                entry.user.id,
                AntinukeAction.DELETE_CHANNELS
            )
            break
    
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        """Detectar creación masiva de roles"""
        async for entry in role.guild.audit_logs(action=AuditLogAction.role_create, limit=1):
            if entry.target.id == role.id:
                punished = await self.check_and_punish(
                    role.guild,
                    entry.user.id,
                    AntinukeAction.CREATE_ROLES
                )
                
                # Si se castigó, revertir la acción (eliminar el rol)
                if punished:
                    settings = await self.get_settings(role.guild.id)
                    if settings.get("revert_actions", True):
                        try:
                            await role.delete(reason="Antinuke: Revirtiendo rol creado maliciosamente")
                        except discord.HTTPException:
                            pass
                break
    
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        """Detectar eliminación masiva de roles"""
        async for entry in role.guild.audit_logs(action=AuditLogAction.role_delete, limit=1):
            await self.check_and_punish(
                role.guild,
                entry.user.id,
                AntinukeAction.DELETE_ROLES
            )
            break
    
    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.TextChannel):
        """Detectar creación masiva de webhooks"""
        async for entry in channel.guild.audit_logs(action=AuditLogAction.webhook_create, limit=1):
            # Verificar que fue reciente
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).seconds < 5:
                punished = await self.check_and_punish(
                    channel.guild,
                    entry.user.id,
                    AntinukeAction.CREATE_WEBHOOKS
                )
                
                # Si se castigó, revertir la acción (eliminar el webhook)
                if punished:
                    settings = await self.get_settings(channel.guild.id)
                    if settings.get("revert_actions", True):
                        try:
                            webhooks = await channel.webhooks()
                            for webhook in webhooks:
                                if webhook.id == entry.target.id:
                                    await webhook.delete(reason="Antinuke: Revirtiendo webhook creado maliciosamente")
                                    break
                        except discord.HTTPException:
                            pass
            break
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Detectar menciones masivas de @everyone/@here"""
        # Ignorar bots y mensajes sin guild
        if not message.guild or message.author.bot:
            return
        
        # Detectar si el mensaje contiene @everyone o @here
        # message.mention_everyone = True cuando el usuario TIENE permiso y mencionó
        # También detectar intentos de mención sin permiso (texto literal)
        has_everyone_mention = message.mention_everyone
        has_everyone_text = "@everyone" in message.content or "@here" in message.content
        
        if not has_everyone_mention and not has_everyone_text:
            return
        
        settings = await self.get_settings(message.guild.id)
        if not settings.get("enabled"):
            return
        
        action_config = settings.get("actions", {}).get(AntinukeAction.MENTION_EVERYONE.value, {})
        if not action_config.get("enabled"):
            return
        
        user_id = message.author.id
        
        # SOLO excluir whitelist y owner - NADIE MÁS
        # Si alguien tiene el permiso por accidente, el antinuke DEBE actuar
        if await self.is_whitelisted(message.guild.id, user_id):
            return
        if user_id == message.guild.owner_id:
            return
        
        # Intentar eliminar el mensaje
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        
        # Verificar y castigar
        await self.check_and_punish(
            message.guild,
            user_id,
            AntinukeAction.MENTION_EVERYONE
        )
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Detectar adición de bots no autorizados"""
        if not member.bot:
            return
        
        settings = await self.get_settings(member.guild.id)
        if not settings.get("enabled"):
            return
        
        action_config = settings.get("actions", {}).get(AntinukeAction.ADD_BOT.value, {})
        if not action_config.get("enabled"):
            return
        
        # Verificar quién añadió el bot
        async for entry in member.guild.audit_logs(action=AuditLogAction.bot_add, limit=1):
            if entry.target.id == member.id:
                user_id = entry.user.id
                adder = member.guild.get_member(user_id)
                
                # SOLO whitelist y owner pueden añadir bots sin consecuencias
                # Los trusted NO están exentos de esto
                if await self.is_whitelisted(member.guild.id, user_id):
                    return
                if user_id == member.guild.owner_id:
                    return
                
                # Expulsar el bot
                try:
                    await member.kick(reason="Antinuke: Bot no autorizado")
                except discord.HTTPException:
                    pass
                
                # Castigar al que añadió el bot (incluso si es trusted)
                # Para add_bot, el límite es 1, así que siempre castiga
                if adder and adder.top_role < member.guild.me.top_role:
                    punishment = Punishment(settings.get("punishment", Punishment.BAN.value))
                    success = await self.execute_punishment(
                        member.guild, adder, AntinukeAction.ADD_BOT, punishment
                    )
                    await self.log_action(
                        member.guild, adder, AntinukeAction.ADD_BOT, punishment.value, success
                    )
                else:
                    # Si no podemos castigar, al menos logueamos
                    await self.log_action(
                        member.guild, adder or member, AntinukeAction.ADD_BOT, "N/A", False
                    )
                break
    
    # ========== Commands ==========
    
    @commands.group(
        name="antinuke",
        aliases=["an", "anti"],
        brief="Sistema de protección antinuke",
        invoke_without_command=True
    )
    @antinuke_trusted()
    async def antinuke(self, ctx: commands.Context):
        """
        Sistema de protección antinuke para tu servidor.
        
        Protege contra:
        • Baneos/kicks masivos
        • Eliminación de canales/roles
        • Creación masiva de webhooks
        • Bots no autorizados
        """
        settings = await self.get_settings(ctx.guild.id)
        
        # Crear vista con botones
        view = AntinukeSettingsView(self, ctx, settings)
        embed = view.create_embed()
        view.message = await ctx.send(embed=embed, view=view)
    
    @antinuke.command(name="enable", aliases=["on", "activar"])
    @antinuke_trusted()
    async def antinuke_enable(self, ctx: commands.Context):
        """Activar el sistema antinuke"""
        # Solo el dueño puede activar
        if ctx.author.id != ctx.guild.owner_id:
            return await ctx.send(embed=error_embed(
                "Solo el dueño del servidor puede activar el antinuke"
            ))
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {
                    "enabled": True,
                    "guild_id": ctx.guild.id
                },
                "$setOnInsert": {
                    "punishment": Punishment.BAN.value,
                    "trusted": [ctx.author.id],
                    "actions": self.DEFAULT_SETTINGS["actions"]
                }
            },
            upsert=True
        )
        
        # Actualizar caché
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        embed = success_embed("🛡️ Antinuke **activado**", ctx.author)
        embed.add_field(
            name="⚠️ Importante",
            value="Configura las protecciones con `;antinuke settings`",
            inline=False
        )
        await ctx.send(embed=embed)
    
    @antinuke.command(name="disable", aliases=["off", "desactivar"])
    @antinuke_trusted()
    async def antinuke_disable(self, ctx: commands.Context):
        """Desactivar el sistema antinuke"""
        if ctx.author.id != ctx.guild.owner_id:
            return await ctx.send(embed=error_embed(
                "Solo el dueño del servidor puede desactivar el antinuke"
            ))
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"enabled": False}}
        )
        
        # Actualizar caché
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        embed = success_embed("🛡️ Antinuke **desactivado**", ctx.author)
        await ctx.send(embed=embed)
    
    @antinuke.command(name="punishment", aliases=["castigo"])
    @antinuke_trusted()
    async def antinuke_punishment(
        self, 
        ctx: commands.Context, 
        punishment: Literal["ban", "kick", "strip", "quarantine"]
    ):
        """
        Configurar el castigo para infractores
        
        **Opciones:**
        - ban: Banear al usuario
        - kick: Expulsar al usuario
        - strip: Quitar todos los roles
        - quarantine: Quitar roles y asignar rol de cuarentena
        
        **Nota:** Para quarantine, configura primero el rol con ;antinuke setup quarantine
        """
        if punishment == "quarantine":
            settings = await self.get_settings(ctx.guild.id)
            if not settings.get("quarantine_role"):
                return await ctx.send(embed=warning_embed(
                    f"⚠️ Primero configura el rol de cuarentena con:\n`{ctx.clean_prefix}antinuke setup quarantine`"
                ))
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"punishment": punishment}}
        )
        
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        embed = success_embed(f"Castigo establecido en **{punishment.upper()}**", ctx.author)
        await ctx.send(embed=embed)
    
    @antinuke.command(name="revert", aliases=["revertir"])
    @antinuke_trusted()
    async def antinuke_revert(self, ctx: commands.Context):
        """
        Activar/desactivar la reversión de acciones.
        
        Cuando está activado, el bot eliminará automáticamente
        los canales, roles y webhooks creados maliciosamente.
        """
        settings = await self.get_settings(ctx.guild.id)
        current = settings.get("revert_actions", True)
        new_state = not current
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"revert_actions": new_state}},
            upsert=True
        )
        
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        status = "activada" if new_state else "desactivada"
        await ctx.send(embed=success_embed(
            f"🔄 Reversión de acciones **{status}**\n"
            f"{'El bot eliminará canales/roles/webhooks maliciosos automáticamente.' if new_state else 'Las acciones maliciosas NO serán revertidas.'}"
        ))
    
    @antinuke.command(name="toggle")
    @antinuke_trusted()
    async def antinuke_toggle(
        self, 
        ctx: commands.Context,
        action: str,
        limit: Optional[int] = None
    ):
        """
        Activar/desactivar una protección específica
        
        **Acciones disponibles:**
        - ban_members
        - kick_members
        - create_channels
        - delete_channels
        - create_roles
        - delete_roles
        - create_webhooks
        - mention_everyone
        - add_bot
        
        **Uso:** ;antinuke toggle <acción> [límite]
        """
        # Validar acción
        valid_actions = [a.value for a in AntinukeAction]
        if action not in valid_actions:
            return await ctx.send(embed=error_embed(
                f"Acción inválida. Opciones: {', '.join(valid_actions)}"
            ))
        
        settings = await self.get_settings(ctx.guild.id)
        current = settings.get("actions", {}).get(action, {})
        new_enabled = not current.get("enabled", False)
        new_limit = limit or current.get("limit", 3)
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {
                    f"actions.{action}.enabled": new_enabled,
                    f"actions.{action}.limit": new_limit
                }
            }
        )
        
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        status = "activada" if new_enabled else "desactivada"
        embed = success_embed(
            f"Protección **{action}** {status} (límite: {new_limit})",
            ctx.author
        )
        await ctx.send(embed=embed)

    # ========== Comandos de acceso rápido para cada protección ==========
    
    @antinuke.command(name="ban", aliases=["bans", "banmembers"])
    @antinuke_trusted()
    async def antinuke_ban(self, ctx: commands.Context, toggle: Literal["on", "off"], limit: int = 3):
        """
        Configurar protección contra baneos masivos.
        
        **Uso:** ;antinuke ban <on/off> [límite]
        **Ejemplo:** ;antinuke ban on 3
        """
        enabled = toggle == "on"
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {
                "actions.ban_members.enabled": enabled,
                "actions.ban_members.limit": limit
            }}
        )
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        if enabled:
            await ctx.send(embed=success_embed(f"Protección contra baneos **habilitada** (límite: {limit})"))
        else:
            await ctx.send(embed=success_embed("Protección contra baneos **deshabilitada**"))
    
    @antinuke.command(name="kick", aliases=["kicks", "kickmembers"])
    @antinuke_trusted()
    async def antinuke_kick(self, ctx: commands.Context, toggle: Literal["on", "off"], limit: int = 3):
        """
        Configurar protección contra kicks masivos.
        
        **Uso:** ;antinuke kick <on/off> [límite]
        """
        enabled = toggle == "on"
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {
                "actions.kick_members.enabled": enabled,
                "actions.kick_members.limit": limit
            }}
        )
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        if enabled:
            await ctx.send(embed=success_embed(f"Protección contra kicks **habilitada** (límite: {limit})"))
        else:
            await ctx.send(embed=success_embed("Protección contra kicks **deshabilitada**"))
    
    @antinuke.command(name="channel", aliases=["channels", "deletechannels", "createchannels"])
    @antinuke_trusted()
    async def antinuke_channel(self, ctx: commands.Context, action: Literal["create", "delete", "both"], toggle: Literal["on", "off"], limit: int = 3):
        """
        Configurar protección de canales.
        
        **Uso:** ;antinuke channel <create/delete/both> <on/off> [límite]
        **Ejemplo:** ;antinuke channel both on 3
        """
        enabled = toggle == "on"
        updates = {}
        
        if action in ["create", "both"]:
            updates["actions.create_channels.enabled"] = enabled
            updates["actions.create_channels.limit"] = limit
        if action in ["delete", "both"]:
            updates["actions.delete_channels.enabled"] = enabled
            updates["actions.delete_channels.limit"] = limit
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": updates}
        )
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        action_text = "creación/eliminación" if action == "both" else ("creación" if action == "create" else "eliminación")
        if enabled:
            await ctx.send(embed=success_embed(f"Protección de {action_text} de canales **habilitada** (límite: {limit})"))
        else:
            await ctx.send(embed=success_embed(f"Protección de {action_text} de canales **deshabilitada**"))
    
    @antinuke.command(name="role", aliases=["roles", "deleteroles", "createroles"])
    @antinuke_trusted()
    async def antinuke_role(self, ctx: commands.Context, action: Literal["create", "delete", "both"], toggle: Literal["on", "off"], limit: int = 3):
        """
        Configurar protección de roles.
        
        **Uso:** ;antinuke role <create/delete/both> <on/off> [límite]
        **Ejemplo:** ;antinuke role both on 3
        """
        enabled = toggle == "on"
        updates = {}
        
        if action in ["create", "both"]:
            updates["actions.create_roles.enabled"] = enabled
            updates["actions.create_roles.limit"] = limit
        if action in ["delete", "both"]:
            updates["actions.delete_roles.enabled"] = enabled
            updates["actions.delete_roles.limit"] = limit
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": updates}
        )
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        action_text = "creación/eliminación" if action == "both" else ("creación" if action == "create" else "eliminación")
        if enabled:
            await ctx.send(embed=success_embed(f"Protección de {action_text} de roles **habilitada** (límite: {limit})"))
        else:
            await ctx.send(embed=success_embed(f"Protección de {action_text} de roles **deshabilitada**"))
    
    @antinuke.command(name="webhook", aliases=["webhooks"])
    @antinuke_trusted()
    async def antinuke_webhook(self, ctx: commands.Context, toggle: Literal["on", "off"], limit: int = 3):
        """
        Configurar protección contra webhooks maliciosos.
        
        **Uso:** ;antinuke webhook <on/off> [límite]
        """
        enabled = toggle == "on"
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {
                "actions.create_webhooks.enabled": enabled,
                "actions.create_webhooks.limit": limit
            }}
        )
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        if enabled:
            await ctx.send(embed=success_embed(f"Protección contra webhooks **habilitada** (límite: {limit})"))
        else:
            await ctx.send(embed=success_embed("Protección contra webhooks **deshabilitada**"))
    
    @antinuke.command(name="everyone", aliases=["mentioneveryone", "massping"])
    @antinuke_trusted()
    async def antinuke_everyone(self, ctx: commands.Context, toggle: Literal["on", "off"], limit: int = 3):
        """
        Configurar protección contra @everyone/@here spam.
        
        **Uso:** ;antinuke everyone <on/off> [límite]
        """
        enabled = toggle == "on"
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {
                "actions.mention_everyone.enabled": enabled,
                "actions.mention_everyone.limit": limit
            }}
        )
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        if enabled:
            await ctx.send(embed=success_embed(f"Protección contra @everyone spam **habilitada** (límite: {limit})"))
        else:
            await ctx.send(embed=success_embed("Protección contra @everyone spam **deshabilitada**"))
    
    @antinuke.command(name="bot", aliases=["bots", "antibot"])
    @antinuke_trusted()
    async def antinuke_bot(self, ctx: commands.Context, toggle: Literal["on", "off"]):
        """
        Configurar protección contra bots no autorizados.
        
        **Uso:** ;antinuke bot <on/off>
        """
        enabled = toggle == "on"
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {
                "actions.add_bot.enabled": enabled,
                "actions.add_bot.limit": 1
            }}
        )
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        if enabled:
            await ctx.send(embed=success_embed("Protección contra bots no autorizados **habilitada**"))
        else:
            await ctx.send(embed=success_embed("Protección contra bots no autorizados **deshabilitada**"))
    
    @antinuke.command(name="all", aliases=["enableall", "activarall"])
    @antinuke_trusted()
    async def antinuke_all(self, ctx: commands.Context, toggle: Literal["on", "off"], limit: int = 3):
        """
        Activar o desactivar TODAS las protecciones.
        
        **Uso:** ;antinuke all <on/off> [límite]
        """
        enabled = toggle == "on"
        updates = {}
        for action in AntinukeAction:
            updates[f"actions.{action.value}.enabled"] = enabled
            if action != AntinukeAction.ADD_BOT:
                updates[f"actions.{action.value}.limit"] = limit
            else:
                updates[f"actions.{action.value}.limit"] = 1
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": updates}
        )
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        if enabled:
            await ctx.send(embed=success_embed(f"✅ **Todas** las protecciones **habilitadas** (límite: {limit})"))
        else:
            await ctx.send(embed=success_embed("❌ **Todas** las protecciones **deshabilitadas**"))

    @antinuke.command(name="logchannel", aliases=["logs"])
    @antinuke_trusted()
    async def antinuke_logchannel(
        self, 
        ctx: commands.Context, 
        channel: Optional[discord.TextChannel] = None
    ):
        """Configurar canal de logs del antinuke"""
        channel_id = channel.id if channel else None
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"log_channel": channel_id}}
        )
        
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        if channel:
            embed = success_embed(f"Logs configurados en {channel.mention}", ctx.author)
        else:
            embed = success_embed("Logs desactivados", ctx.author)
        
        await ctx.send(embed=embed)
    
    @antinuke.command(name="alertrole", aliases=["alert", "pingrole"])
    @antinuke_trusted()
    async def antinuke_alertrole(
        self,
        ctx: commands.Context,
        role: Optional[discord.Role] = None
    ):
        """
        Configurar rol que será mencionado en alertas.
        
        **Uso:** 
        ;antinuke alertrole @rol - Configurar rol
        ;antinuke alertrole - Quitar rol
        """
        role_id = role.id if role else None
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"alert_role": role_id}}
        )
        
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        if role:
            embed = success_embed(f"🔔 Rol de alertas: {role.mention}", ctx.author)
        else:
            embed = success_embed("🔔 Rol de alertas desactivado", ctx.author)
        
        await ctx.send(embed=embed)
    
    # ========== Setup Commands ==========
    
    @antinuke.group(name="setroles", invoke_without_command=True)
    @antinuke_trusted()
    async def antinuke_setup(self, ctx: commands.Context):
        """
        Configurar roles especiales del antinuke.
        
        **Subcomandos:**
        - ;antinuke setroles quarantine - Crear/configurar rol de cuarentena
        - ;antinuke setroles mute - Crear/configurar rol de mute
        """
        settings = await self.get_settings(ctx.guild.id)
        
        embed = discord.Embed(
            title="🛡️ Antinuke - Setup de Roles",
            color=config.BLURPLE_COLOR
        )
        
        # Rol de cuarentena
        quarantine_id = settings.get("quarantine_role")
        if quarantine_id:
            q_role = ctx.guild.get_role(quarantine_id)
            q_status = f"✅ {q_role.mention}" if q_role else "⚠️ Rol no encontrado"
        else:
            q_status = "❌ No configurado"
        
        # Rol de mute
        mute_id = settings.get("mute_role")
        if mute_id:
            m_role = ctx.guild.get_role(mute_id)
            m_status = f"✅ {m_role.mention}" if m_role else "⚠️ Rol no encontrado"
        else:
            m_status = "❌ No configurado"
        
        # Rol de alertas
        alert_id = settings.get("alert_role")
        if alert_id:
            a_role = ctx.guild.get_role(alert_id)
            a_status = f"✅ {a_role.mention}" if a_role else "⚠️ Rol no encontrado"
        else:
            a_status = "❌ No configurado"
        
        embed.add_field(name="🔒 Rol de Cuarentena", value=q_status, inline=True)
        embed.add_field(name="🔇 Rol de Mute", value=m_status, inline=True)
        embed.add_field(name="🔔 Rol de Alertas", value=a_status, inline=True)
        
        embed.add_field(
            name="📋 Comandos",
            value=(
                f"`{ctx.clean_prefix}antinuke setroles quarantine` - Crear rol de cuarentena\n"
                f"`{ctx.clean_prefix}antinuke setroles mute` - Crear rol de mute\n"
                f"`{ctx.clean_prefix}antinuke alertrole @rol` - Configurar rol de alertas"
            ),
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @antinuke_setup.command(name="quarantine", aliases=["cuarentena"])
    @antinuke_trusted()
    async def setup_quarantine(self, ctx: commands.Context, role: Optional[discord.Role] = None):
        """
        Configuración automática completa del sistema de cuarentena.
        
        **Uso:**
        ;antinuke setroles quarantine - Setup automático completo
        ;antinuke setroles quarantine @rol - Usar rol existente
        
        **El setup automático:**
        1. Crea el rol de cuarentena
        2. Lo configura sin permisos en TODOS los canales
        3. Crea un canal #cuarentena donde SÍ pueden hablar
        4. Mueve el rol lo más arriba posible
        """
        status_msg = await ctx.send(embed=discord.Embed(
            description="⏳ **Configurando sistema de cuarentena...**\n\n"
                       "• Creando rol...\n"
                       "• Configurando canales...\n"
                       "• Creando canal de cuarentena...",
            color=config.BLURPLE_COLOR
        ))
        
        # Paso 1: Crear o usar rol existente
        if role is None:
            try:
                role = await ctx.guild.create_role(
                    name="🔒 Cuarentena",
                    color=discord.Color.dark_red(),
                    hoist=True,  # Mostrar separado en la lista
                    reason="Antinuke: Rol de cuarentena creado automáticamente"
                )
                await status_msg.edit(embed=discord.Embed(
                    description="⏳ **Configurando sistema de cuarentena...**\n\n"
                               f"✅ Rol creado: {role.mention}\n"
                               "• Configurando canales...\n"
                               "• Creando canal de cuarentena...",
                    color=config.BLURPLE_COLOR
                ))
            except discord.HTTPException as e:
                return await status_msg.edit(embed=error_embed(f"Error al crear rol: {e}"))
        
        # Paso 2: Mover rol lo más arriba posible (para poder quitar otros roles)
        try:
            bot_top_role = ctx.guild.me.top_role
            new_position = max(1, bot_top_role.position - 1)
            await role.edit(position=new_position)
        except discord.HTTPException:
            pass  # No es crítico
        
        # Paso 3: Configurar permisos en TODOS los canales (denegar todo)
        channel_errors = 0
        total_channels = len(ctx.guild.channels)
        
        for channel in ctx.guild.channels:
            try:
                await channel.set_permissions(
                    role,
                    view_channel=False,
                    send_messages=False,
                    add_reactions=False,
                    speak=False,
                    connect=False,
                    create_instant_invite=False,
                    reason="Antinuke: Configurando cuarentena - sin acceso"
                )
            except discord.HTTPException:
                channel_errors += 1
        
        await status_msg.edit(embed=discord.Embed(
            description="⏳ **Configurando sistema de cuarentena...**\n\n"
                       f"✅ Rol creado: {role.mention}\n"
                       f"✅ Configurados {total_channels - channel_errors}/{total_channels} canales\n"
                       "• Creando canal de cuarentena...",
            color=config.BLURPLE_COLOR
        ))
        
        # Paso 4: Crear canal de cuarentena
        quarantine_channel = None
        try:
            # Buscar o crear categoría de moderación
            mod_category = discord.utils.get(ctx.guild.categories, name="Moderación")
            if not mod_category:
                mod_category = discord.utils.get(ctx.guild.categories, name="Moderation")
            
            # Permisos del canal: solo usuarios en cuarentena y staff
            overwrites = {
                ctx.guild.default_role: discord.PermissionOverwrite(
                    view_channel=False
                ),
                role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=False,
                    embed_links=False
                ),
                ctx.guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True
                )
            }
            
            # Agregar permisos para roles con manage_guild
            for r in ctx.guild.roles:
                if r.permissions.manage_guild or r.permissions.administrator:
                    overwrites[r] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True
                    )
            
            quarantine_channel = await ctx.guild.create_text_channel(
                name="🔒・cuarentena",
                category=mod_category,
                overwrites=overwrites,
                topic="Canal para usuarios en cuarentena. Aquí pueden comunicarse con el staff.",
                reason="Antinuke: Canal de cuarentena creado automáticamente"
            )
        except discord.HTTPException as e:
            # No es crítico, el sistema funciona sin este canal
            pass
        
        # Paso 5: Guardar en DB
        update_data = {"quarantine_role": role.id}
        if quarantine_channel:
            update_data["quarantine_channel"] = quarantine_channel.id
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": update_data},
            upsert=True
        )
        
        # Limpiar caché
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        # Embed final
        embed = discord.Embed(
            title="✅ Sistema de Cuarentena Configurado",
            color=config.SUCCESS_COLOR
        )
        
        embed.add_field(
            name="🔒 Rol de Cuarentena",
            value=role.mention,
            inline=True
        )
        
        if quarantine_channel:
            embed.add_field(
                name="💬 Canal de Cuarentena",
                value=quarantine_channel.mention,
                inline=True
            )
        
        embed.add_field(
            name="📊 Canales Configurados",
            value=f"{total_channels - channel_errors}/{total_channels}",
            inline=True
        )
        
        embed.add_field(
            name="📋 Cómo usar",
            value=(
                f"**Manual:** `{ctx.clean_prefix}quarantine @usuario razón`\n"
                f"**Auto:** `{ctx.clean_prefix}antinuke punishment quarantine`\n"
                f"**Quitar:** `{ctx.clean_prefix}unquarantine @usuario`"
            ),
            inline=False
        )
        
        if quarantine_channel:
            embed.add_field(
                name="💡 Info",
                value=(
                    "Los usuarios en cuarentena:\n"
                    "• No pueden ver ningún canal excepto el de cuarentena\n"
                    "• Pueden escribir en el canal de cuarentena para apelar\n"
                    "• Staff puede ver y responder en ese canal"
                ),
                inline=False
            )
        
        if channel_errors:
            embed.set_footer(text=f"⚠️ No se pudieron configurar {channel_errors} canales (permisos insuficientes)")
        
        await status_msg.edit(embed=embed)
    
    @antinuke_setup.command(name="mute", aliases=["silencio"])
    @antinuke_trusted()
    async def setup_mute(self, ctx: commands.Context, role: Optional[discord.Role] = None):
        """
        Crear o configurar el rol de mute.
        
        **Uso:**
        ;antinuke setup mute - Crear rol automáticamente
        ;antinuke setup mute @rol - Usar rol existente
        
        El rol de mute:
        - Impide enviar mensajes y hablar en voz
        - Se puede usar con el sistema de moderación
        """
        status_msg = await ctx.send(embed=discord.Embed(
            description="⏳ Configurando rol de mute...",
            color=config.BLURPLE_COLOR
        ))
        
        if role is None:
            # Crear rol de mute
            try:
                role = await ctx.guild.create_role(
                    name="🔇 Muted",
                    color=discord.Color.dark_grey(),
                    reason="Antinuke: Rol de mute creado"
                )
            except discord.HTTPException as e:
                return await status_msg.edit(embed=error_embed(f"Error al crear rol: {e}"))
        
        # Configurar permisos en todos los canales
        errors = 0
        for channel in ctx.guild.channels:
            try:
                await channel.set_permissions(
                    role,
                    send_messages=False,
                    send_messages_in_threads=False,
                    create_public_threads=False,
                    create_private_threads=False,
                    add_reactions=False,
                    speak=False,
                    reason="Antinuke: Configurando permisos de mute"
                )
            except discord.HTTPException:
                errors += 1
        
        # Guardar en DB
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"mute_role": role.id}},
            upsert=True
        )
        
        self._settings_cache.pop(ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{ctx.guild.id}")
        
        # Mover rol
        try:
            bot_top_role = ctx.guild.me.top_role
            await role.edit(position=bot_top_role.position - 1)
        except:
            pass
        
        embed = success_embed(f"✅ Rol de mute configurado: {role.mention}")
        if errors:
            embed.add_field(name="⚠️ Advertencia", value=f"No se pudo configurar {errors} canales")
        
        await status_msg.edit(embed=embed)
    
    # ========== Whitelist ==========
    
    @antinuke.group(name="whitelist", aliases=["wl"], invoke_without_command=True)
    @antinuke_trusted()
    async def whitelist(self, ctx: commands.Context):
        """Ver la whitelist del antinuke"""
        whitelist = await database.antinuke_whitelist.find(
            {"guild_id": ctx.guild.id}
        ).to_list(length=None)
        
        if not whitelist:
            return await ctx.send(embed=warning_embed("La whitelist está vacía"))
        
        lines = []
        for entry in whitelist:
            user = self.bot.get_user(entry["user_id"])
            name = str(user) if user else f"ID: {entry['user_id']}"
            lines.append(f"• {name}")
        
        embed = discord.Embed(
            title="🛡️ Antinuke - Whitelist",
            description="\n".join(lines),
            color=config.BLURPLE_COLOR
        )
        await ctx.send(embed=embed)
    
    @whitelist.command(name="add", aliases=["añadir"])
    @antinuke_trusted()
    async def whitelist_add(self, ctx: commands.Context, user: discord.User):
        """Añadir usuario a la whitelist"""
        # Verificar si ya está
        exists = await database.antinuke_whitelist.find_one({
            "guild_id": ctx.guild.id,
            "user_id": user.id
        })
        
        if exists:
            return await ctx.send(embed=error_embed(f"**{user}** ya está en la whitelist"))
        
        await database.antinuke_whitelist.insert_one({
            "guild_id": ctx.guild.id,
            "user_id": user.id,
            "added_by": ctx.author.id,
            "added_at": datetime.utcnow()
        })
        
        # Actualizar caché
        if ctx.guild.id in self._whitelist_cache:
            self._whitelist_cache[ctx.guild.id].add(user.id)
        await cache.delete(f"antinuke:whitelist:{ctx.guild.id}")
        
        embed = success_embed(f"**{user}** añadido a la whitelist", ctx.author)
        await ctx.send(embed=embed)
    
    @whitelist.command(name="remove", aliases=["quitar", "del"])
    @antinuke_trusted()
    async def whitelist_remove(self, ctx: commands.Context, user: discord.User):
        """Quitar usuario de la whitelist"""
        result = await database.antinuke_whitelist.delete_one({
            "guild_id": ctx.guild.id,
            "user_id": user.id
        })
        
        if result.deleted_count == 0:
            return await ctx.send(embed=error_embed(f"**{user}** no está en la whitelist"))
        
        # Actualizar caché
        if ctx.guild.id in self._whitelist_cache:
            self._whitelist_cache[ctx.guild.id].discard(user.id)
        await cache.delete(f"antinuke:whitelist:{ctx.guild.id}")
        
        embed = success_embed(f"**{user}** removido de la whitelist", ctx.author)
        await ctx.send(embed=embed)
    
    # ========== Trusted ==========
    
    @antinuke.group(name="trusted", aliases=["trust"], invoke_without_command=True)
    @antinuke_trusted()
    async def trusted(self, ctx: commands.Context):
        """Ver los usuarios de confianza que pueden configurar el antinuke"""
        settings = await self.get_settings(ctx.guild.id)
        trusted_users = settings.get("trusted", [])
        
        if not trusted_users:
            return await ctx.send(embed=warning_embed("No hay usuarios trusted configurados\nSolo el **owner** puede configurar el antinuke"))
        
        lines = []
        for user_id in trusted_users:
            user = self.bot.get_user(user_id)
            name = str(user) if user else f"ID: {user_id}"
            lines.append(f"• {name}")
        
        embed = discord.Embed(
            title="🛡️ Antinuke - Usuarios Trusted",
            description="\n".join(lines) + "\n\n*Estos usuarios pueden configurar el antinuke*",
            color=config.BLURPLE_COLOR
        )
        embed.set_footer(text="Solo el owner puede agregar/quitar usuarios trusted")
        await ctx.send(embed=embed)
    
    @trusted.command(name="add", aliases=["añadir"])
    async def trusted_add(self, ctx: commands.Context, user: discord.User):
        """Añadir usuario trusted (solo owner)"""
        if ctx.author.id != ctx.guild.owner_id:
            return await ctx.send(embed=error_embed(
                "Solo el **owner** puede añadir usuarios trusted"
            ))
        
        if user.id == ctx.guild.owner_id:
            return await ctx.send(embed=error_embed("El owner ya tiene acceso total"))
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$addToSet": {"trusted": user.id}}
        )
        
        if ctx.guild.id in self._trusted_cache:
            self._trusted_cache[ctx.guild.id].add(user.id)
        self._settings_cache.pop(ctx.guild.id, None)
        
        embed = success_embed(f"**{user}** ahora puede configurar el antinuke", ctx.author)
        await ctx.send(embed=embed)
    
    @trusted.command(name="remove", aliases=["quitar", "del"])
    async def trusted_remove(self, ctx: commands.Context, user: discord.User):
        """Quitar usuario trusted (solo owner)"""
        if ctx.author.id != ctx.guild.owner_id:
            return await ctx.send(embed=error_embed(
                "Solo el **owner** puede quitar usuarios trusted"
            ))
        
        await database.antinuke_servers.update_one(
            {"guild_id": ctx.guild.id},
            {"$pull": {"trusted": user.id}}
        )
        
        if ctx.guild.id in self._trusted_cache:
            self._trusted_cache[ctx.guild.id].discard(user.id)
        self._settings_cache.pop(ctx.guild.id, None)
        
        embed = success_embed(f"**{user}** ya no puede configurar el antinuke", ctx.author)
        await ctx.send(embed=embed)

    # ========== Settings (Embed extendido) ==========
    
    @antinuke.command(name="settings", aliases=["config", "configurar", "setup", "comandos"])
    @antinuke_trusted()
    async def antinuke_settings(self, ctx: commands.Context):
        """Ver configuración actual y comandos disponibles"""
        settings = await self.get_settings(ctx.guild.id)
        
        embed = discord.Embed(
            title="🛡️ Antinuke - Configuración",
            description="Protección avanzada contra nukers",
            color=config.BLURPLE_COLOR
        )
        
        if settings.get("enabled"):
            status = "✅ Habilitado"
            punishment = settings.get("punishment", "ban").upper()
            log_channel = ctx.guild.get_channel(settings.get("log_channel", 0))
            
            embed.add_field(
                name="Configuración Actual",
                value=f"**Castigo:** {punishment}\n"
                      f"**Canal de logs:** {log_channel.mention if log_channel else 'No configurado'}",
                inline=False
            )
            
            # Mostrar protecciones activas
            actions_enabled = []
            actions_disabled = []
            for action in AntinukeAction:
                action_config = settings.get("actions", {}).get(action.value, {})
                enabled = action_config.get("enabled", False)
                limit = action_config.get("limit", 3)
                if enabled:
                    actions_enabled.append(f"✅ `{action.value}` (límite: {limit})")
                else:
                    actions_disabled.append(f"❌ `{action.value}`")
            
            if actions_enabled:
                embed.add_field(name="Protecciones Activas", value="\n".join(actions_enabled), inline=True)
            if actions_disabled:
                embed.add_field(name="Protecciones Inactivas", value="\n".join(actions_disabled), inline=True)
        else:
            status = "❌ Deshabilitado"
        
        embed.add_field(name="Estado", value=status, inline=False)
        
        embed.add_field(
            name="Subcomandos Principales",
            value=f"`{ctx.prefix}antinuke enable` - Habilitar antinuke\n"
                  f"`{ctx.prefix}antinuke disable` - Deshabilitar antinuke\n"
                  f"`{ctx.prefix}antinuke punishment <ban/kick/strip>` - Cambiar castigo\n"
                  f"`{ctx.prefix}antinuke logs <canal>` - Canal de logs\n"
                  f"`{ctx.prefix}antinuke all <on/off> [límite]` - Todas las protecciones",
            inline=False
        )
        
        embed.add_field(
            name="Protecciones Individuales",
            value=f"`{ctx.prefix}antinuke ban <on/off> [límite]` - Baneos masivos\n"
                  f"`{ctx.prefix}antinuke kick <on/off> [límite]` - Kicks masivos\n"
                  f"`{ctx.prefix}antinuke channel <create/delete/both> <on/off> [límite]` - Canales\n"
                  f"`{ctx.prefix}antinuke role <create/delete/both> <on/off> [límite]` - Roles\n"
                  f"`{ctx.prefix}antinuke webhook <on/off> [límite]` - Webhooks\n"
                  f"`{ctx.prefix}antinuke everyone <on/off> [límite]` - @everyone spam\n"
                  f"`{ctx.prefix}antinuke bot <on/off>` - Bots no autorizados",
            inline=False
        )
        
        embed.add_field(
            name="Gestión",
            value=f"`{ctx.prefix}antinuke whitelist` - Ver/gestionar whitelist\n"
                  f"`{ctx.prefix}antinuke trusted` - Ver/gestionar usuarios trusted",
            inline=False
        )
        
        embed.set_footer(text=f"Usa {ctx.prefix}antinuke para el panel interactivo | Solo owner y trusted pueden configurar")
        
        await ctx.send(embed=embed)


class AntinukeSettingsView(discord.ui.View):
    """Vista interactiva para configurar antinuke"""
    
    def __init__(self, cog: Antinuke, ctx: commands.Context, settings: dict):
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        self.settings = settings
        self.message: Optional[discord.Message] = None
        
        # Añadir select menu para las acciones
        self.add_item(AntinukeActionSelect(self))
    
    def create_embed(self) -> discord.Embed:
        """Crear embed con el estado actual"""
        status = "✅ Activado" if self.settings.get("enabled") else "❌ Desactivado"
        punishment = self.settings.get("punishment", "ban").upper()
        log_channel = self.settings.get("log_channel")
        log_text = f"<#{log_channel}>" if log_channel else "No configurado"
        
        embed = discord.Embed(
            title="🛡️ Antinuke - Configuración",
            description=(
                f"**Estado:** {status}\n"
                f"**Castigo:** {punishment}\n"
                f"**Canal de logs:** {log_text}\n\n"
                "Usa el menú desplegable para activar/desactivar protecciones.\n"
                "Usa los botones para cambiar otras opciones."
            ),
            color=config.BLURPLE_COLOR
        )
        
        # Mostrar protecciones
        actions_text = []
        for action in AntinukeAction:
            action_config = self.settings.get("actions", {}).get(action.value, {})
            enabled = action_config.get("enabled", False)
            limit = action_config.get("limit", 3)
            status_emoji = "✅" if enabled else "❌"
            actions_text.append(f"{status_emoji} `{action.value}` → Límite: **{limit}**")
        
        embed.add_field(
            name="📋 Protecciones",
            value="\n".join(actions_text),
            inline=False
        )
        
        return embed
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Solo quien ejecutó el comando puede usar esto.", 
                ephemeral=True
            )
            return False
        return True
    
    async def on_timeout(self):
        if self.message:
            try:
                for item in self.children:
                    item.disabled = True
                await self.message.edit(view=self)
            except:
                pass
    
    async def refresh(self):
        """Refrescar el embed con datos actualizados"""
        self.settings = await self.cog.get_settings(self.ctx.guild.id)
        embed = self.create_embed()
        await self.message.edit(embed=embed, view=self)
    
    @discord.ui.button(label="Activar/Desactivar", style=discord.ButtonStyle.primary, emoji="⚡", row=1)
    async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle antinuke on/off"""
        if interaction.user.id != self.ctx.guild.owner_id:
            return await interaction.response.send_message(
                "Solo el dueño puede activar/desactivar el antinuke", 
                ephemeral=True
            )
        
        new_state = not self.settings.get("enabled", False)
        
        await database.antinuke_servers.update_one(
            {"guild_id": self.ctx.guild.id},
            {
                "$set": {"enabled": new_state, "guild_id": self.ctx.guild.id},
                "$setOnInsert": {
                    "punishment": Punishment.BAN.value,
                    "trusted": [self.ctx.author.id],
                    "actions": self.cog.DEFAULT_SETTINGS["actions"]
                }
            },
            upsert=True
        )
        
        self.cog._settings_cache.pop(self.ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{self.ctx.guild.id}")
        
        status = "activado" if new_state else "desactivado"
        await interaction.response.send_message(f"🛡️ Antinuke **{status}**", ephemeral=True)
        await self.refresh()
    
    @discord.ui.button(label="Castigo", style=discord.ButtonStyle.secondary, emoji="⚖️", row=1)
    async def change_punishment(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cambiar castigo"""
        view = PunishmentView(self)
        await interaction.response.send_message(
            "**Selecciona el castigo para infractores:**\n\n"
            "🔨 **Ban** — Banear permanentemente\n"
            "👢 **Kick** — Expulsar del servidor\n"
            "📛 **Strip** — Quitar todos los roles\n"
            "🔒 **Quarantine** — Aislar en canal de cuarentena",
            view=view,
            ephemeral=True
        )
    
    @discord.ui.button(label="Canal de Logs", style=discord.ButtonStyle.secondary, emoji="📝", row=1)
    async def set_log_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Configurar canal de logs"""
        modal = LogChannelModal(self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Cambiar Límite", style=discord.ButtonStyle.secondary, emoji="🔢", row=2)
    async def change_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cambiar límite de una acción"""
        modal = LimitModal(self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Activar Todo", style=discord.ButtonStyle.success, emoji="✅", row=2)
    async def enable_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Activar todas las protecciones"""
        updates = {}
        for action in AntinukeAction:
            updates[f"actions.{action.value}.enabled"] = True
        
        await database.antinuke_servers.update_one(
            {"guild_id": self.ctx.guild.id},
            {"$set": updates}
        )
        
        self.cog._settings_cache.pop(self.ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{self.ctx.guild.id}")
        
        await interaction.response.send_message("✅ Todas las protecciones activadas", ephemeral=True)
        await self.refresh()
    
    @discord.ui.button(label="Desactivar Todo", style=discord.ButtonStyle.danger, emoji="❌", row=2)
    async def disable_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Desactivar todas las protecciones"""
        updates = {}
        for action in AntinukeAction:
            updates[f"actions.{action.value}.enabled"] = False
        
        await database.antinuke_servers.update_one(
            {"guild_id": self.ctx.guild.id},
            {"$set": updates}
        )
        
        self.cog._settings_cache.pop(self.ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{self.ctx.guild.id}")
        
        await interaction.response.send_message("❌ Todas las protecciones desactivadas", ephemeral=True)
        await self.refresh()


class AntinukeActionSelect(discord.ui.Select):
    """Menú para seleccionar y toggle una acción"""
    
    def __init__(self, view: AntinukeSettingsView):
        self.parent_view = view
        
        options = []
        for action in AntinukeAction:
            action_config = view.settings.get("actions", {}).get(action.value, {})
            enabled = action_config.get("enabled", False)
            emoji = "✅" if enabled else "❌"
            
            # Descripciones amigables
            descriptions = {
                "ban_members": "Protección contra baneos masivos",
                "kick_members": "Protección contra kicks masivos",
                "create_channels": "Protección contra creación de canales",
                "delete_channels": "Protección contra eliminación de canales",
                "create_roles": "Protección contra creación de roles",
                "delete_roles": "Protección contra eliminación de roles",
                "create_webhooks": "Protección contra webhooks maliciosos",
                "mention_everyone": "Protección contra @everyone spam",
                "add_bot": "Protección contra bots no autorizados"
            }
            
            options.append(discord.SelectOption(
                label=action.value.replace("_", " ").title(),
                value=action.value,
                description=descriptions.get(action.value, ""),
                emoji=emoji
            ))
        
        super().__init__(
            placeholder="🛡️ Selecciona una protección para activar/desactivar",
            options=options,
            row=0
        )
    
    async def callback(self, interaction: discord.Interaction):
        action = self.values[0]
        current = self.parent_view.settings.get("actions", {}).get(action, {})
        new_enabled = not current.get("enabled", False)
        
        await database.antinuke_servers.update_one(
            {"guild_id": self.parent_view.ctx.guild.id},
            {"$set": {f"actions.{action}.enabled": new_enabled}}
        )
        
        self.parent_view.cog._settings_cache.pop(self.parent_view.ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{self.parent_view.ctx.guild.id}")
        
        status = "activada" if new_enabled else "desactivada"
        await interaction.response.send_message(
            f"Protección **{action}** {status}", 
            ephemeral=True
        )
        await self.parent_view.refresh()


class PunishmentSelect(discord.ui.Select):
    """Select para elegir el castigo"""
    
    def __init__(self, view: AntinukeSettingsView):
        self.parent_view = view
        current = view.settings.get("punishment", "ban")
        
        options = [
            discord.SelectOption(
                label="Ban",
                description="Banear permanentemente al usuario",
                value="ban",
                emoji="🔨",
                default=current == "ban"
            ),
            discord.SelectOption(
                label="Kick",
                description="Expulsar al usuario del servidor",
                value="kick",
                emoji="👢",
                default=current == "kick"
            ),
            discord.SelectOption(
                label="Strip",
                description="Quitar todos los roles al usuario",
                value="strip",
                emoji="📛",
                default=current == "strip"
            ),
            discord.SelectOption(
                label="Quarantine",
                description="Aislar al usuario (requiere configuración)",
                value="quarantine",
                emoji="🔒",
                default=current == "quarantine"
            )
        ]
        
        super().__init__(
            placeholder="Selecciona el castigo...",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        
        # Verificar quarantine
        if value == "quarantine":
            settings = await self.parent_view.cog.get_settings(self.parent_view.ctx.guild.id)
            if not settings.get("quarantine_role"):
                return await interaction.response.send_message(
                    "❌ Primero configura el sistema de cuarentena:\n"
                    "`;antinuke setroles quarantine`",
                    ephemeral=True
                )
        
        await database.antinuke_servers.update_one(
            {"guild_id": self.parent_view.ctx.guild.id},
            {"$set": {"punishment": value}}
        )
        
        self.parent_view.cog._settings_cache.pop(self.parent_view.ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{self.parent_view.ctx.guild.id}")
        
        # Actualizar el view con el nuevo select
        self.parent_view.settings["punishment"] = value
        
        punishment_names = {"ban": "BAN", "kick": "KICK", "strip": "STRIP (quitar roles)", "quarantine": "CUARENTENA"}
        await interaction.response.send_message(
            f"⚖️ Castigo establecido en **{punishment_names[value]}**", 
            ephemeral=True
        )
        await self.parent_view.refresh()


class PunishmentView(discord.ui.View):
    """Vista temporal para el select de castigo"""
    
    def __init__(self, parent_view: AntinukeSettingsView):
        super().__init__(timeout=60)
        self.parent_view = parent_view
        self.add_item(PunishmentSelect(parent_view))


class LogChannelModal(discord.ui.Modal, title="Canal de Logs"):
    """Modal para configurar el canal de logs"""
    
    channel_id = discord.ui.TextInput(
        label="ID del canal (vacío para desactivar)",
        placeholder="123456789012345678",
        required=False,
        max_length=20
    )
    
    def __init__(self, view: AntinukeSettingsView):
        super().__init__()
        self.parent_view = view
        current = view.settings.get("log_channel")
        if current:
            self.channel_id.default = str(current)
    
    async def on_submit(self, interaction: discord.Interaction):
        value = self.channel_id.value.strip()
        
        if not value:
            channel_id = None
        else:
            try:
                channel_id = int(value)
                channel = self.parent_view.ctx.guild.get_channel(channel_id)
                if not channel:
                    return await interaction.response.send_message(
                        "❌ Canal no encontrado en este servidor",
                        ephemeral=True
                    )
            except ValueError:
                return await interaction.response.send_message(
                    "❌ ID de canal inválido",
                    ephemeral=True
                )
        
        await database.antinuke_servers.update_one(
            {"guild_id": self.parent_view.ctx.guild.id},
            {"$set": {"log_channel": channel_id}}
        )
        
        self.parent_view.cog._settings_cache.pop(self.parent_view.ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{self.parent_view.ctx.guild.id}")
        
        if channel_id:
            await interaction.response.send_message(
                f"📝 Canal de logs: <#{channel_id}>", 
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "📝 Canal de logs desactivado", 
                ephemeral=True
            )
        await self.parent_view.refresh()


class LimitModal(discord.ui.Modal, title="Cambiar Límite"):
    """Modal para cambiar el límite de una acción"""
    
    action = discord.ui.TextInput(
        label="Nombre de la acción",
        placeholder="ban_members, kick_members, etc.",
        required=True
    )
    
    limit = discord.ui.TextInput(
        label="Nuevo límite (1-10)",
        placeholder="3",
        default="3",
        max_length=2,
        required=True
    )
    
    def __init__(self, view: AntinukeSettingsView):
        super().__init__()
        self.parent_view = view
    
    async def on_submit(self, interaction: discord.Interaction):
        action_name = self.action.value.lower().strip()
        
        valid_actions = [a.value for a in AntinukeAction]
        if action_name not in valid_actions:
            return await interaction.response.send_message(
                f"❌ Acción inválida. Opciones: {', '.join(valid_actions)}",
                ephemeral=True
            )
        
        try:
            limit_value = int(self.limit.value)
            if not 1 <= limit_value <= 10:
                raise ValueError()
        except ValueError:
            return await interaction.response.send_message(
                "❌ El límite debe ser un número entre 1 y 10",
                ephemeral=True
            )
        
        await database.antinuke_servers.update_one(
            {"guild_id": self.parent_view.ctx.guild.id},
            {"$set": {f"actions.{action_name}.limit": limit_value}}
        )
        
        self.parent_view.cog._settings_cache.pop(self.parent_view.ctx.guild.id, None)
        await cache.delete(f"antinuke:settings:{self.parent_view.ctx.guild.id}")
        
        await interaction.response.send_message(
            f"🔢 Límite de **{action_name}** establecido en **{limit_value}**", 
            ephemeral=True
        )
        await self.parent_view.refresh()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Antinuke(bot))
