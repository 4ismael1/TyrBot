"""
Cog Antiraid - Protección contra raids masivos
"""

from __future__ import annotations

import asyncio
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from typing import Optional, Literal

from config import config
from core import database, cache
from utils import success_embed, error_embed, warning_embed


def antiraid_trusted():
    """Check que verifica si el usuario es owner o está en la lista de trusted"""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return False
        # El owner siempre puede
        if ctx.author.id == ctx.guild.owner_id:
            return True
        # Verificar si está en la lista de trusted
        cog = ctx.bot.get_cog("Antiraid")
        if cog and await cog.is_trusted(ctx.guild.id, ctx.author.id):
            return True
        raise commands.CheckFailure("Solo el **owner** o usuarios **trusted** pueden usar esto")
    return commands.check(predicate)


class Antiraid(commands.Cog):
    """🛡️ Protección contra raids masivos"""
    
    emoji = "🛡️"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # Cache local (backup si Redis falla)
        self._settings_cache: dict[int, dict] = {}
        self._trusted_cache: dict[int, set[int]] = {}
        
        # Iniciar tareas
        self.sync_cache.start()
    
    def cog_unload(self):
        self.sync_cache.cancel()
    
    # ========== Tasks ==========
    
    @tasks.loop(minutes=5)
    async def sync_cache(self):
        """Sincronizar configuraciones desde DB a caché local"""
        async for doc in database.antiraid.find({"enabled": True}):
            self._settings_cache[doc["guild_id"]] = doc
            # También actualizar Redis (sin el _id de MongoDB)
            cache_doc = {k: v for k, v in doc.items() if k != "_id"}
            await cache.antiraid_set_settings(doc["guild_id"], cache_doc)
    
    @sync_cache.before_loop
    async def before_sync_cache(self):
        await self.bot.wait_until_ready()
    
    # ========== Helpers ==========
    
    async def update_settings(self, guild_id: int, update_data: dict):
        """Actualizar configuración y limpiar caché"""
        await database.antiraid.update_one(
            {"guild_id": guild_id},
            {"$set": update_data},
            upsert=True
        )
        await self.invalidate_cache(guild_id)
    
    async def is_trusted(self, guild_id: int, user_id: int) -> bool:
        """Verificar si un usuario está en la lista de trusted"""
        if guild_id in self._trusted_cache:
            return user_id in self._trusted_cache[guild_id]
        
        settings = await self.get_settings(guild_id)
        if not settings:
            return False
        trusted = set(settings.get("trusted", []))
        self._trusted_cache[guild_id] = trusted
        return user_id in trusted
    
    async def get_settings(self, guild_id: int) -> Optional[dict]:
        """Obtener configuración de antiraid con caché"""
        # Primero cache local
        if guild_id in self._settings_cache:
            return self._settings_cache[guild_id]
        
        # Luego Redis
        cached = await cache.antiraid_get_settings(guild_id)
        if cached:
            self._settings_cache[guild_id] = cached
            return cached
        
        # Finalmente base de datos
        doc = await database.antiraid.find_one({"guild_id": guild_id})
        if doc:
            self._settings_cache[guild_id] = doc
            await cache.antiraid_set_settings(guild_id, doc)
        return doc
    
    async def invalidate_cache(self, guild_id: int):
        """Invalidar caché de antiraid"""
        if guild_id in self._settings_cache:
            del self._settings_cache[guild_id]
        if guild_id in self._trusted_cache:
            del self._trusted_cache[guild_id]
        await cache.antiraid_invalidate(guild_id)
    
    async def log_action(self, guild: discord.Guild, settings: dict, action: str, details: str):
        """Enviar log de acción"""
        if not settings.get("log_channel"):
            return
        
        channel = guild.get_channel(settings["log_channel"])
        if not channel:
            return
        
        embed = discord.Embed(
            title=f"🛡️ Antiraid - {action}",
            description=details,
            color=config.WARNING_COLOR,
            timestamp=datetime.utcnow()
        )
        
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
    
    async def execute_penalty(self, member: discord.Member, settings: dict, reason: str, detection_type: str = "Actividad sospechosa") -> bool:
        """
        Ejecutar la penalidad configurada contra un miembro.
        Retorna True si se ejecutó correctamente.
        """
        penalty = settings.get("penalty", "kick")
        guild = member.guild
        
        # Enviar DM al usuario antes del castigo
        penalty_names = {
            "ban": ("baneado permanentemente", "🔨"),
            "kick": ("expulsado", "👢"),
            "quarantine": ("puesto en cuarentena", "🔒")
        }
        action_name, emoji = penalty_names.get(penalty, ("castigado", "⚠️"))
        
        try:
            dm_embed = discord.Embed(
                title=f"{emoji} Acción de Antiraid",
                description=f"Has sido **{action_name}** de **{guild.name}**",
                color=discord.Color.orange()
            )
            dm_embed.add_field(
                name="📋 Motivo",
                value=f"El sistema de protección contra raids detectó:\n**{detection_type}**",
                inline=False
            )
            dm_embed.add_field(
                name="ℹ️ Info",
                value="Si crees que esto fue un error, contacta a un administrador del servidor.",
                inline=False
            )
            dm_embed.set_footer(text=f"Servidor: {guild.name}", icon_url=guild.icon.url if guild.icon else None)
            await member.send(embed=dm_embed)
        except discord.HTTPException:
            pass  # No se pudo enviar DM, continuar con el castigo
        
        try:
            if penalty == "ban":
                await member.ban(reason=reason)
            elif penalty == "kick":
                await member.kick(reason=reason)
            elif penalty == "quarantine":
                # Obtener rol de cuarentena desde antinuke
                antinuke_cog = self.bot.get_cog("Antinuke")
                quarantine_role_id = None
                
                if antinuke_cog:
                    an_settings = await antinuke_cog.get_settings(guild.id)
                    quarantine_role_id = an_settings.get("quarantine_role")
                
                if quarantine_role_id:
                    quarantine_role = guild.get_role(quarantine_role_id)
                    if quarantine_role:
                        # Guardar roles actuales para poder restaurarlos después
                        current_roles = [r.id for r in member.roles if r != guild.default_role and r != quarantine_role]
                        
                        # Guardar en base de datos
                        await database.quarantine.update_one(
                            {"guild_id": guild.id, "user_id": member.id},
                            {"$set": {
                                "guild_id": guild.id,
                                "user_id": member.id,
                                "previous_roles": current_roles,
                                "moderator_id": self.bot.user.id,
                                "reason": reason,
                                "source": "antiraid",
                                "detection_type": detection_type,
                                "timestamp": datetime.utcnow()
                            }},
                            upsert=True
                        )
                        
                        # Quitar todos los roles y asignar cuarentena
                        roles_to_remove = [r for r in member.roles if r != guild.default_role]
                        if roles_to_remove:
                            await member.remove_roles(*roles_to_remove, reason=reason)
                        await member.add_roles(quarantine_role, reason=reason)
                    else:
                        # Fallback a kick si no existe el rol
                        await member.kick(reason=reason + " (rol de cuarentena no encontrado)")
                else:
                    # Fallback a kick si no hay rol configurado
                    await member.kick(reason=reason + " (rol de cuarentena no configurado)")
            
            return True
        except discord.HTTPException:
            return False
    
    async def log_action(self, guild: discord.Guild, settings: dict, action: str, details: str):
        """Enviar log de una acción antiraid"""
        if not settings.get("log_channel"):
            return
        
        channel = guild.get_channel(settings["log_channel"])
        if not channel:
            return
        
        # Color según severidad
        if "RAID" in action.upper():
            color = 0xFF0000  # Rojo para raids
            ping_owner = True
        else:
            color = config.WARNING_COLOR
            ping_owner = False
        
        embed = discord.Embed(
            title=f"🚨 {action}",
            description=details,
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Antiraid System")
        
        try:
            content = None
            if ping_owner and guild.owner:
                content = f"⚠️ {guild.owner.mention} - ¡ALERTA DE RAID!"
            await channel.send(content=content, embed=embed)
        except discord.HTTPException:
            pass
    
    # ========== Events ==========
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Detectar raids por joins masivos"""
        if member.bot:
            return
        
        settings = await self.get_settings(member.guild.id)
        if not settings or not settings.get("enabled"):
            return
        
        guild_id = member.guild.id
        penalty = settings.get("penalty", "kick")
        
        # Si estamos en raid mode (verificar en Redis), castigar inmediatamente
        if await cache.antiraid_is_raid_mode(guild_id):
            reason = "Antiraid: Servidor en modo raid"
            await self.execute_penalty(member, settings, reason, "Servidor en modo raid por joins masivos")
            return
        
        # Registrar join en Redis (retorna cantidad total)
        await cache.antiraid_add_join(guild_id, member.id)
        
        # Verificar threshold de mass join
        if settings.get("massjoin_enabled"):
            threshold = settings.get("massjoin_threshold", 10)
            timeframe = settings.get("massjoin_timeframe", 10)  # segundos
            
            # Obtener joins recientes desde Redis
            recent_member_ids = await cache.antiraid_get_recent_joins(guild_id, timeframe)
            
            if len(recent_member_ids) >= threshold:
                # Activar raid mode en Redis (dura 60 segundos)
                await cache.antiraid_set_raid_mode(guild_id, 60)
                
                # Raid detectado - Log
                await self.log_action(
                    member.guild, settings, "🚨 RAID DETECTADO",
                    f"{len(recent_member_ids)} joins en {timeframe}s - Activando modo raid por 60s"
                )
                
                # Ejecutar penalización a TODOS los que se unieron recientemente
                reason = f"Antiraid: Mass join detectado ({len(recent_member_ids)} joins en {timeframe}s)"
                
                action_count = 0
                for member_id in recent_member_ids:
                    try:
                        raid_member = member.guild.get_member(member_id)
                        if raid_member and not raid_member.bot:
                            if await self.execute_penalty(raid_member, settings, reason, f"Raid detectado ({len(recent_member_ids)} joins en {timeframe}s)"):
                                action_count += 1
                    except discord.HTTPException:
                        pass
                
                # Log del resultado
                action_word = "en cuarentena" if penalty == "quarantine" else ("baneados" if penalty == "ban" else "expulsados")
                await self.log_action(
                    member.guild, settings, "Raid Mitigado",
                    f"{action_count} usuarios {action_word}"
                )
                
                # Limpiar el tracker en Redis después de actuar
                await cache.antiraid_clear_joins(guild_id)
                
                return
        
        # Verificar edad de cuenta
        if settings.get("account_age_enabled"):
            now = datetime.utcnow()
            min_age_days = settings.get("min_account_age", 7)
            account_age = (now - member.created_at.replace(tzinfo=None)).days
            
            if account_age < min_age_days:
                await self.log_action(
                    member.guild, settings, "New Account Blocked",
                    f"{member} - Cuenta creada hace {account_age} días (mínimo: {min_age_days})"
                )
                
                reason = f"Antiraid: Cuenta muy nueva ({account_age} días)"
                
                try:
                    await self.execute_penalty(member, settings, reason, f"Cuenta muy nueva ({account_age} días, mínimo requerido: {min_age_days})")
                except discord.HTTPException:
                    pass
                
                return
        
        # Verificar avatar por defecto
        if settings.get("no_avatar_enabled"):
            # Verificar si no tiene avatar personalizado (ni global ni de servidor)
            has_avatar = member.avatar is not None or member.guild_avatar is not None
            
            if not has_avatar:
                await self.log_action(
                    member.guild, settings, "No Avatar Blocked",
                    f"{member} - Sin avatar de perfil"
                )
                
                reason = "Antiraid: Usuario sin avatar"
                
                try:
                    await self.execute_penalty(member, settings, reason, "Usuario sin foto de perfil")
                except discord.HTTPException:
                    pass
    
    # ========== Commands ==========
    
    @commands.group(
        name="antiraid",
        aliases=["raid"],
        brief="Sistema antiraid",
        invoke_without_command=True
    )
    @antiraid_trusted()
    async def antiraid(self, ctx: commands.Context):
        """
        Sistema de protección contra raids masivos.
        
        Protege tu servidor de:
        • Joins masivos
        • Cuentas nuevas
        • Cuentas sin avatar
        """
        settings = await self.get_settings(ctx.guild.id)
        
        if not settings:
            # Crear configuración por defecto
            settings = {
                "guild_id": ctx.guild.id,
                "enabled": False,
                "penalty": "kick",
                "massjoin_enabled": False,
                "massjoin_threshold": 10,
                "massjoin_timeframe": 10,
                "account_age_enabled": False,
                "min_account_age": 7,
                "no_avatar_enabled": False
            }
        
        # Crear vista con botones
        view = AntiraidSettingsView(self, ctx, settings)
        embed = view.create_embed()
        view.message = await ctx.send(embed=embed, view=view)
    
    @antiraid.command(name="enable", aliases=["on"])
    @antiraid_trusted()
    async def antiraid_enable(self, ctx: commands.Context):
        """Habilitar el sistema antiraid"""
        await database.antiraid.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {
                "guild_id": ctx.guild.id,
                "enabled": True,
                "penalty": "kick",
                "massjoin_enabled": False,
                "massjoin_threshold": 10,
                "massjoin_timeframe": 10,
                "account_age_enabled": False,
                "min_account_age": 7,
                "no_avatar_enabled": False
            }},
            upsert=True
        )
        
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed("Sistema antiraid **habilitado**"))
    
    @antiraid.command(name="disable", aliases=["off"])
    @antiraid_trusted()
    async def antiraid_disable(self, ctx: commands.Context):
        """Deshabilitar el sistema antiraid"""
        await database.antiraid.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"enabled": False}},
            upsert=True
        )
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed("Sistema antiraid **deshabilitado**"))
    
    @antiraid.command(name="penalty", aliases=["punishment", "do"])
    @antiraid_trusted()
    async def antiraid_penalty(self, ctx: commands.Context, action: Literal["ban", "kick", "quarantine"]):
        """
        Establecer la penalización para raids.
        
        **Opciones:**
        • `ban` - Banear permanentemente
        • `kick` - Expulsar del servidor
        • `quarantine` - Poner en cuarentena (requiere configurar rol)
        
        **Uso:** ;antiraid penalty <ban/kick/quarantine>
        """
        # Si es quarantine, verificar que existe el rol configurado
        if action == "quarantine":
            # Obtener rol de antinuke settings
            antinuke_settings = await database.antinuke.find_one({"guild_id": ctx.guild.id})
            quarantine_role_id = antinuke_settings.get("quarantine_role") if antinuke_settings else None
            
            if not quarantine_role_id:
                return await ctx.send(embed=error_embed(
                    "Debes configurar un **rol de cuarentena** primero.\n"
                    "Usa: `;antinuke setroles quarantine @rol`"
                ))
            
            role = ctx.guild.get_role(quarantine_role_id)
            if not role:
                return await ctx.send(embed=error_embed(
                    "El rol de cuarentena configurado ya no existe.\n"
                    "Configura uno nuevo: `;antinuke setroles quarantine @rol`"
                ))
        
        await database.antiraid.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"penalty": action}},
            upsert=True
        )
        
        if ctx.guild.id in self._settings_cache:
            self._settings_cache[ctx.guild.id]["penalty"] = action
        
        action_names = {"ban": "Ban", "kick": "Kick", "quarantine": "Cuarentena"}
        await ctx.send(embed=success_embed(f"Penalización establecida a **{action_names[action]}**"))
    
    @antiraid.command(name="massjoin", aliases=["mj"])
    @antiraid_trusted()
    async def antiraid_massjoin(
        self, 
        ctx: commands.Context, 
        toggle: Literal["on", "off"],
        threshold: int = 10,
        timeframe: int = 10
    ):
        """
        Configurar detección de mass join.
        
        **Uso:** ;antiraid massjoin <on/off> [threshold] [timeframe]
        **Ejemplo:** ;antiraid massjoin on 10 10 (10 joins en 10 segundos)
        """
        enabled = toggle == "on"
        
        await database.antiraid.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {
                "massjoin_enabled": enabled,
                "massjoin_threshold": threshold,
                "massjoin_timeframe": timeframe
            }},
            upsert=True
        )
        
        if ctx.guild.id in self._settings_cache:
            self._settings_cache[ctx.guild.id]["massjoin_enabled"] = enabled
            self._settings_cache[ctx.guild.id]["massjoin_threshold"] = threshold
            self._settings_cache[ctx.guild.id]["massjoin_timeframe"] = timeframe
        
        if enabled:
            await ctx.send(embed=success_embed(
                f"Detección de mass join **habilitada**\n"
                f"Threshold: {threshold} joins en {timeframe} segundos"
            ))
        else:
            await ctx.send(embed=success_embed("Detección de mass join **deshabilitada**"))
    
    @antiraid.command(name="accountage", aliases=["age", "minage"])
    @antiraid_trusted()
    async def antiraid_accountage(self, ctx: commands.Context, days: int = None):
        """
        Configurar edad mínima de cuenta.
        
        **Uso:** ;antiraid accountage <días>
        **Ejemplo:** ;antiraid accountage 7
        
        Usa 0 para deshabilitar.
        """
        if days is None:
            return await ctx.send(embed=error_embed("Especifica los días mínimos (0 para deshabilitar)"))
        
        enabled = days > 0
        
        await database.antiraid.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {
                "account_age_enabled": enabled,
                "min_account_age": days
            }},
            upsert=True
        )
        
        if ctx.guild.id in self._settings_cache:
            self._settings_cache[ctx.guild.id]["account_age_enabled"] = enabled
            self._settings_cache[ctx.guild.id]["min_account_age"] = days
        
        if enabled:
            await ctx.send(embed=success_embed(
                f"Edad mínima de cuenta: **{days} días**"
            ))
        else:
            await ctx.send(embed=success_embed("Verificación de edad de cuenta **deshabilitada**"))
    
    @antiraid.command(name="noavatar", aliases=["defaultpfp", "nopfp"])
    @antiraid_trusted()
    async def antiraid_noavatar(self, ctx: commands.Context, toggle: Literal["on", "off"]):
        """Bloquear usuarios sin avatar"""
        enabled = toggle == "on"
        
        await database.antiraid.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"no_avatar_enabled": enabled}},
            upsert=True
        )
        
        if ctx.guild.id in self._settings_cache:
            self._settings_cache[ctx.guild.id]["no_avatar_enabled"] = enabled
        
        if enabled:
            await ctx.send(embed=success_embed("Bloqueo de usuarios sin avatar **habilitado**"))
        else:
            await ctx.send(embed=success_embed("Bloqueo de usuarios sin avatar **deshabilitado**"))
    
    @antiraid.command(name="logs", aliases=["log", "channel"])
    @antiraid_trusted()
    async def antiraid_logs(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Establecer canal de logs del antiraid"""
        if channel is None:
            await database.antiraid.update_one(
                {"guild_id": ctx.guild.id},
                {"$unset": {"log_channel": ""}},
                upsert=True
            )
            if ctx.guild.id in self._settings_cache:
                self._settings_cache[ctx.guild.id].pop("log_channel", None)
            return await ctx.send(embed=success_embed("Canal de logs **removido**"))
        
        await database.antiraid.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"log_channel": channel.id}},
            upsert=True
        )
        
        if ctx.guild.id in self._settings_cache:
            self._settings_cache[ctx.guild.id]["log_channel"] = channel.id
        
        await ctx.send(embed=success_embed(f"Canal de logs: {channel.mention}"))
    
    @antiraid.command(name="settings", aliases=["config", "status", "comandos"])
    @antiraid_trusted()
    async def antiraid_settings(self, ctx: commands.Context):
        """Ver configuración actual y comandos disponibles"""
        settings = await self.get_settings(ctx.guild.id)
        
        embed = discord.Embed(
            title="🛡️ Antiraid - Configuración",
            description="Protección contra raids masivos",
            color=config.BLURPLE_COLOR
        )
        
        if settings and settings.get("enabled"):
            status = "✅ Habilitado"
            log_channel = ctx.guild.get_channel(settings.get("log_channel", 0))
            
            embed.add_field(
                name="Configuración Actual",
                value=f"**Penalización:** {settings.get('penalty', 'kick')}\n"
                      f"**Canal de logs:** {log_channel.mention if log_channel else 'No configurado'}\n"
                      f"**Mass Join:** {'✅' if settings.get('massjoin_enabled') else '❌'} ({settings.get('massjoin_threshold', 10)} joins en {settings.get('massjoin_timeframe', 10)}s)\n"
                      f"**Edad mínima:** {'✅' if settings.get('account_age_enabled') else '❌'} ({settings.get('min_account_age', 7)} días)\n"
                      f"**Sin avatar:** {'✅' if settings.get('no_avatar_enabled') else '❌'}",
                inline=False
            )
        else:
            status = "❌ Deshabilitado"
        
        embed.add_field(name="Estado", value=status, inline=False)
        
        embed.add_field(
            name="Subcomandos",
            value=f"`{ctx.prefix}antiraid enable` - Habilitar antiraid\n"
                  f"`{ctx.prefix}antiraid disable` - Deshabilitar antiraid\n"
                  f"`{ctx.prefix}antiraid penalty <ban/kick>` - Penalización\n"
                  f"`{ctx.prefix}antiraid massjoin <on/off> [threshold] [timeframe]` - Mass join\n"
                  f"`{ctx.prefix}antiraid accountage <días>` - Edad mínima de cuenta\n"
                  f"`{ctx.prefix}antiraid noavatar <on/off>` - Detectar sin avatar\n"
                  f"`{ctx.prefix}antiraid logs <canal>` - Canal de logs\n"
                  f"`{ctx.prefix}antiraid trusted` - Ver/gestionar usuarios trusted",
            inline=False
        )
        
        embed.set_footer(text=f"Usa {ctx.prefix}antiraid para el panel interactivo")
        
        await ctx.send(embed=embed)
    
    # ========== Trusted ==========
    
    @antiraid.group(name="trusted", aliases=["trust"], invoke_without_command=True)
    @antiraid_trusted()
    async def trusted(self, ctx: commands.Context):
        """Ver los usuarios de confianza que pueden configurar el antiraid"""
        settings = await self.get_settings(ctx.guild.id)
        trusted_users = settings.get("trusted", []) if settings else []
        
        if not trusted_users:
            return await ctx.send(embed=warning_embed("No hay usuarios trusted configurados\nSolo el **owner** puede configurar el antiraid"))
        
        lines = []
        for user_id in trusted_users:
            user = self.bot.get_user(user_id)
            name = str(user) if user else f"ID: {user_id}"
            lines.append(f"• {name}")
        
        embed = discord.Embed(
            title="🛡️ Antiraid - Usuarios Trusted",
            description="\n".join(lines) + "\n\n*Estos usuarios pueden configurar el antiraid*",
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
        
        await database.antiraid.update_one(
            {"guild_id": ctx.guild.id},
            {"$addToSet": {"trusted": user.id}},
            upsert=True
        )
        
        if ctx.guild.id in self._trusted_cache:
            self._trusted_cache[ctx.guild.id].add(user.id)
        self._settings_cache.pop(ctx.guild.id, None)
        
        embed = success_embed(f"**{user}** ahora puede configurar el antiraid", ctx.author)
        await ctx.send(embed=embed)
    
    @trusted.command(name="remove", aliases=["quitar", "del"])
    async def trusted_remove(self, ctx: commands.Context, user: discord.User):
        """Quitar usuario trusted (solo owner)"""
        if ctx.author.id != ctx.guild.owner_id:
            return await ctx.send(embed=error_embed(
                "Solo el **owner** puede quitar usuarios trusted"
            ))
        
        await database.antiraid.update_one(
            {"guild_id": ctx.guild.id},
            {"$pull": {"trusted": user.id}}
        )
        
        if ctx.guild.id in self._trusted_cache:
            self._trusted_cache[ctx.guild.id].discard(user.id)
        self._settings_cache.pop(ctx.guild.id, None)
        
        embed = success_embed(f"**{user}** ya no puede configurar el antiraid", ctx.author)
        await ctx.send(embed=embed)


class AntiraidSettingsView(discord.ui.View):
    """Vista interactiva para configurar antiraid"""
    
    def __init__(self, cog: Antiraid, ctx: commands.Context, settings: dict):
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        self.settings = settings
        self.message: Optional[discord.Message] = None
    
    def create_embed(self) -> discord.Embed:
        """Crear embed con el estado actual"""
        status = "✅ Habilitado" if self.settings.get("enabled") else "❌ Deshabilitado"
        penalty = self.settings.get("penalty", "kick").upper()
        log_channel = self.settings.get("log_channel")
        log_text = f"<#{log_channel}>" if log_channel else "No configurado"
        
        embed = discord.Embed(
            title="🛡️ Antiraid - Configuración",
            description=(
                f"**Estado:** {status}\n"
                f"**Penalización:** {penalty}\n"
                f"**Canal de logs:** {log_text}\n\n"
                "Usa los botones para configurar las protecciones."
            ),
            color=config.BLURPLE_COLOR
        )
        
        # Protecciones
        protections = []
        
        # Mass Join
        mj_enabled = self.settings.get("massjoin_enabled", False)
        mj_threshold = self.settings.get("massjoin_threshold", 10)
        mj_timeframe = self.settings.get("massjoin_timeframe", 10)
        mj_status = "✅" if mj_enabled else "❌"
        protections.append(f"{mj_status} **Mass Join** — {mj_threshold} joins en {mj_timeframe}s")
        
        # Account Age
        age_enabled = self.settings.get("account_age_enabled", False)
        min_age = self.settings.get("min_account_age", 7)
        age_status = "✅" if age_enabled else "❌"
        protections.append(f"{age_status} **Edad Mínima** — {min_age} días")
        
        # No Avatar
        avatar_enabled = self.settings.get("no_avatar_enabled", False)
        avatar_status = "✅" if avatar_enabled else "❌"
        protections.append(f"{avatar_status} **Sin Avatar** — Bloquear usuarios sin foto de perfil")
        
        embed.add_field(
            name="Protecciones",
            value="\n".join(protections),
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
        self.settings = await self.cog.get_settings(self.ctx.guild.id) or self.settings
        embed = self.create_embed()
        await self.message.edit(embed=embed, view=self)
    
    @discord.ui.button(label="Activar/Desactivar", style=discord.ButtonStyle.primary, emoji="⚡", row=0)
    async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle antiraid on/off"""
        new_state = not self.settings.get("enabled", False)
        
        await database.antiraid.update_one(
            {"guild_id": self.ctx.guild.id},
            {"$set": {"enabled": new_state, "guild_id": self.ctx.guild.id}},
            upsert=True
        )
        
        if self.ctx.guild.id in self.cog._settings_cache:
            self.cog._settings_cache[self.ctx.guild.id]["enabled"] = new_state
        else:
            self.cog._settings_cache[self.ctx.guild.id] = {"enabled": new_state}
        
        self.settings["enabled"] = new_state
        status = "habilitado" if new_state else "deshabilitado"
        await interaction.response.send_message(f"🛡️ Antiraid **{status}**", ephemeral=True)
        await self.refresh()
    
    @discord.ui.button(label="Penalización", style=discord.ButtonStyle.secondary, emoji="⚖️", row=0)
    async def change_penalty(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cambiar penalización"""
        view = AntiraidPenaltyView(self)
        await interaction.response.send_message(
            "**Selecciona la penalización para usuarios detectados:**\n\n"
            "🔨 **Ban** — Banear permanentemente\n"
            "👢 **Kick** — Expulsar del servidor\n"
            "🔒 **Quarantine** — Aislar en canal de cuarentena",
            view=view,
            ephemeral=True
        )
    
    @discord.ui.button(label="Canal de Logs", style=discord.ButtonStyle.secondary, emoji="📝", row=0)
    async def set_log_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Configurar canal de logs"""
        modal = AntiraidLogChannelModal(self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Mass Join", style=discord.ButtonStyle.primary, emoji="👥", row=1)
    async def toggle_massjoin(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle mass join"""
        modal = MassJoinModal(self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Edad Mínima", style=discord.ButtonStyle.primary, emoji="📅", row=1)
    async def toggle_account_age(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle account age"""
        modal = AccountAgeModal(self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Sin Avatar", style=discord.ButtonStyle.primary, emoji="🖼️", row=1)
    async def toggle_no_avatar(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle no avatar"""
        new_state = not self.settings.get("no_avatar_enabled", False)
        
        await database.antiraid.update_one(
            {"guild_id": self.ctx.guild.id},
            {"$set": {"no_avatar_enabled": new_state}},
            upsert=True
        )
        
        if self.ctx.guild.id in self.cog._settings_cache:
            self.cog._settings_cache[self.ctx.guild.id]["no_avatar_enabled"] = new_state
        
        self.settings["no_avatar_enabled"] = new_state
        status = "habilitado" if new_state else "deshabilitado"
        await interaction.response.send_message(f"🖼️ Bloqueo sin avatar **{status}**", ephemeral=True)
        await self.refresh()
    
    @discord.ui.button(label="Activar Todo", style=discord.ButtonStyle.success, emoji="✅", row=2)
    async def enable_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Activar todas las protecciones"""
        await database.antiraid.update_one(
            {"guild_id": self.ctx.guild.id},
            {"$set": {
                "enabled": True,
                "massjoin_enabled": True,
                "account_age_enabled": True,
                "no_avatar_enabled": True
            }},
            upsert=True
        )
        
        self.settings["enabled"] = True
        self.settings["massjoin_enabled"] = True
        self.settings["account_age_enabled"] = True
        self.settings["no_avatar_enabled"] = True
        
        if self.ctx.guild.id in self.cog._settings_cache:
            self.cog._settings_cache[self.ctx.guild.id].update(self.settings)
        
        await interaction.response.send_message("✅ Todas las protecciones activadas", ephemeral=True)
        await self.refresh()
    
    @discord.ui.button(label="Desactivar Todo", style=discord.ButtonStyle.danger, emoji="❌", row=2)
    async def disable_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Desactivar todas las protecciones"""
        await database.antiraid.update_one(
            {"guild_id": self.ctx.guild.id},
            {"$set": {
                "enabled": False,
                "massjoin_enabled": False,
                "account_age_enabled": False,
                "no_avatar_enabled": False
            }},
            upsert=True
        )
        
        self.settings["enabled"] = False
        self.settings["massjoin_enabled"] = False
        self.settings["account_age_enabled"] = False
        self.settings["no_avatar_enabled"] = False
        
        if self.ctx.guild.id in self.cog._settings_cache:
            self.cog._settings_cache[self.ctx.guild.id].update(self.settings)
        
        await interaction.response.send_message("❌ Todas las protecciones desactivadas", ephemeral=True)
        await self.refresh()


class AntiraidPenaltySelect(discord.ui.Select):
    """Select para elegir la penalización"""
    
    def __init__(self, view: AntiraidSettingsView):
        self.parent_view = view
        current = view.settings.get("penalty", "kick")
        
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
                label="Quarantine",
                description="Aislar al usuario (requiere configuración)",
                value="quarantine",
                emoji="🔒",
                default=current == "quarantine"
            )
        ]
        
        super().__init__(
            placeholder="Selecciona la penalización...",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        
        # Si es quarantine, verificar que existe el rol configurado
        if value == "quarantine":
            antinuke_settings = await database.antinuke.find_one({"guild_id": self.parent_view.ctx.guild.id})
            quarantine_role_id = antinuke_settings.get("quarantine_role") if antinuke_settings else None
            
            if not quarantine_role_id:
                return await interaction.response.send_message(
                    "❌ Primero configura el sistema de cuarentena:\n"
                    "`;antinuke setroles quarantine`",
                    ephemeral=True
                )
            
            role = self.parent_view.ctx.guild.get_role(quarantine_role_id)
            if not role:
                return await interaction.response.send_message(
                    "❌ El rol de cuarentena ya no existe.\n"
                    "Configúralo de nuevo: `;antinuke setroles quarantine`",
                    ephemeral=True
                )
        
        await database.antiraid.update_one(
            {"guild_id": self.parent_view.ctx.guild.id},
            {"$set": {"penalty": value}},
            upsert=True
        )
        
        self.parent_view.settings["penalty"] = value
        if self.parent_view.ctx.guild.id in self.parent_view.cog._settings_cache:
            self.parent_view.cog._settings_cache[self.parent_view.ctx.guild.id]["penalty"] = value
        
        penalty_names = {"ban": "BAN", "kick": "KICK", "quarantine": "CUARENTENA"}
        await interaction.response.send_message(
            f"⚖️ Penalización establecida en **{penalty_names[value]}**", 
            ephemeral=True
        )
        await self.parent_view.refresh()


class AntiraidPenaltyView(discord.ui.View):
    """Vista temporal para el select de penalización"""
    
    def __init__(self, parent_view: AntiraidSettingsView):
        super().__init__(timeout=60)
        self.parent_view = parent_view
        self.add_item(AntiraidPenaltySelect(parent_view))


class AntiraidLogChannelModal(discord.ui.Modal, title="Canal de Logs"):
    """Modal para configurar el canal de logs"""
    
    channel_id = discord.ui.TextInput(
        label="ID del canal (vacío para desactivar)",
        placeholder="123456789012345678",
        required=False,
        max_length=20
    )
    
    def __init__(self, view: AntiraidSettingsView):
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
        
        await database.antiraid.update_one(
            {"guild_id": self.parent_view.ctx.guild.id},
            {"$set": {"log_channel": channel_id}},
            upsert=True
        )
        
        self.parent_view.settings["log_channel"] = channel_id
        if self.parent_view.ctx.guild.id in self.parent_view.cog._settings_cache:
            self.parent_view.cog._settings_cache[self.parent_view.ctx.guild.id]["log_channel"] = channel_id
        
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


class MassJoinModal(discord.ui.Modal, title="Configurar Mass Join"):
    """Modal para configurar mass join"""
    
    enabled = discord.ui.TextInput(
        label="Habilitado (on/off)",
        placeholder="on",
        max_length=3,
        required=True
    )
    
    threshold = discord.ui.TextInput(
        label="Cantidad de joins",
        placeholder="10",
        default="10",
        max_length=3,
        required=True
    )
    
    timeframe = discord.ui.TextInput(
        label="En cuántos segundos",
        placeholder="10",
        default="10",
        max_length=3,
        required=True
    )
    
    def __init__(self, view: AntiraidSettingsView):
        super().__init__()
        self.parent_view = view
        self.enabled.default = "on" if view.settings.get("massjoin_enabled") else "off"
        self.threshold.default = str(view.settings.get("massjoin_threshold", 10))
        self.timeframe.default = str(view.settings.get("massjoin_timeframe", 10))
    
    async def on_submit(self, interaction: discord.Interaction):
        enabled = self.enabled.value.lower().strip() == "on"
        
        try:
            threshold = int(self.threshold.value)
            timeframe = int(self.timeframe.value)
            if threshold < 1 or timeframe < 1:
                raise ValueError()
        except ValueError:
            return await interaction.response.send_message(
                "❌ Los valores deben ser números positivos",
                ephemeral=True
            )
        
        await database.antiraid.update_one(
            {"guild_id": self.parent_view.ctx.guild.id},
            {"$set": {
                "massjoin_enabled": enabled,
                "massjoin_threshold": threshold,
                "massjoin_timeframe": timeframe
            }},
            upsert=True
        )
        
        self.parent_view.settings["massjoin_enabled"] = enabled
        self.parent_view.settings["massjoin_threshold"] = threshold
        self.parent_view.settings["massjoin_timeframe"] = timeframe
        
        if self.parent_view.ctx.guild.id in self.parent_view.cog._settings_cache:
            self.parent_view.cog._settings_cache[self.parent_view.ctx.guild.id].update({
                "massjoin_enabled": enabled,
                "massjoin_threshold": threshold,
                "massjoin_timeframe": timeframe
            })
        
        status = "habilitado" if enabled else "deshabilitado"
        await interaction.response.send_message(
            f"👥 Mass Join **{status}** ({threshold} joins en {timeframe}s)", 
            ephemeral=True
        )
        await self.parent_view.refresh()


class AccountAgeModal(discord.ui.Modal, title="Configurar Edad Mínima"):
    """Modal para configurar edad mínima de cuenta"""
    
    enabled = discord.ui.TextInput(
        label="Habilitado (on/off)",
        placeholder="on",
        max_length=3,
        required=True
    )
    
    days = discord.ui.TextInput(
        label="Días mínimos de la cuenta",
        placeholder="7",
        default="7",
        max_length=4,
        required=True
    )
    
    def __init__(self, view: AntiraidSettingsView):
        super().__init__()
        self.parent_view = view
        self.enabled.default = "on" if view.settings.get("account_age_enabled") else "off"
        self.days.default = str(view.settings.get("min_account_age", 7))
    
    async def on_submit(self, interaction: discord.Interaction):
        enabled = self.enabled.value.lower().strip() == "on"
        
        try:
            days = int(self.days.value)
            if days < 1:
                raise ValueError()
        except ValueError:
            return await interaction.response.send_message(
                "❌ Los días deben ser un número positivo",
                ephemeral=True
            )
        
        await database.antiraid.update_one(
            {"guild_id": self.parent_view.ctx.guild.id},
            {"$set": {
                "account_age_enabled": enabled,
                "min_account_age": days
            }},
            upsert=True
        )
        
        self.parent_view.settings["account_age_enabled"] = enabled
        self.parent_view.settings["min_account_age"] = days
        
        if self.parent_view.ctx.guild.id in self.parent_view.cog._settings_cache:
            self.parent_view.cog._settings_cache[self.parent_view.ctx.guild.id].update({
                "account_age_enabled": enabled,
                "min_account_age": days
            })
        
        status = "habilitado" if enabled else "deshabilitado"
        await interaction.response.send_message(
            f"📅 Edad mínima **{status}** ({days} días)", 
            ephemeral=True
        )
        await self.parent_view.refresh()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Antiraid(bot))
