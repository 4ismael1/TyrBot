"""
Cog de Moderación - Sistema completo de moderación con casos editables
"""

from __future__ import annotations

import asyncio
import discord
import logging
from discord.ext import commands
from discord import ui
from datetime import timedelta, timezone
from typing import Optional, Union, Literal

from config import config
from core import database, cache
from utils import (
    success_embed, error_embed, warning_embed,
    can_moderate, can_bot_moderate,
    parse_time, format_time, confirm, paginate
)


def ensure_utc(dt):
    """Convierte datetime naive a aware UTC para que Discord lo muestre correctamente."""
    if dt is None:
        return discord.utils.utcnow()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# Emojis y colores para cada acción
MOD_ACTIONS = {
    "warn": {"emoji": "⚠️", "color": 0xFFCC00, "name": "Advertencia"},
    "kick": {"emoji": "👢", "color": 0xFF6600, "name": "Expulsión"},
    "ban": {"emoji": "🔨", "color": 0xFF0000, "name": "Ban"},
    "unban": {"emoji": "✅", "color": 0x00FF00, "name": "Unban"},
    "softban": {"emoji": "🔄", "color": 0xFF6600, "name": "Softban"},
    "timeout": {"emoji": "🔇", "color": 0xFF9900, "name": "Timeout"},
    "untimeout": {"emoji": "🔊", "color": 0x00FF00, "name": "Untimeout"},
    "quarantine": {"emoji": "🔒", "color": 0x800080, "name": "Cuarentena"},
    "unquarantine": {"emoji": "🔓", "color": 0x00FF00, "name": "Fin Cuarentena"},
    "note": {"emoji": "📝", "color": 0x5865F2, "name": "Nota"},
}


# ========== Permission Checks con FakePerms ==========

def has_mod_permissions():
    """Check que verifica permisos reales O fakeperms"""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id == ctx.guild.owner_id:
            return True
        if ctx.author.guild_permissions.moderate_members:
            return True
        
        fakeperms_cog = ctx.bot.get_cog("FakePerms")
        if fakeperms_cog:
            if await fakeperms_cog.has_fakeperm(ctx.guild, ctx.author, "moderate_members"):
                return True
            if await fakeperms_cog.has_fakeperm(ctx.guild, ctx.author, "administrator"):
                return True
        
        raise commands.MissingPermissions(["moderate_members"])
    
    return commands.check(predicate)


def has_kick_permissions():
    """Check para kick con fakeperms"""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id == ctx.guild.owner_id:
            return True
        if ctx.author.guild_permissions.kick_members:
            return True
        
        fakeperms_cog = ctx.bot.get_cog("FakePerms")
        if fakeperms_cog:
            if await fakeperms_cog.has_fakeperm(ctx.guild, ctx.author, "kick_members"):
                return True
            if await fakeperms_cog.has_fakeperm(ctx.guild, ctx.author, "administrator"):
                return True
        
        raise commands.MissingPermissions(["kick_members"])
    
    return commands.check(predicate)


def has_ban_permissions():
    """Check para ban con fakeperms"""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id == ctx.guild.owner_id:
            return True
        if ctx.author.guild_permissions.ban_members:
            return True
        
        fakeperms_cog = ctx.bot.get_cog("FakePerms")
        if fakeperms_cog:
            if await fakeperms_cog.has_fakeperm(ctx.guild, ctx.author, "ban_members"):
                return True
            if await fakeperms_cog.has_fakeperm(ctx.guild, ctx.author, "administrator"):
                return True
        
        raise commands.MissingPermissions(["ban_members"])
    
    return commands.check(predicate)


def has_manage_messages():
    """Check para manage_messages con fakeperms"""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id == ctx.guild.owner_id:
            return True
        if ctx.author.guild_permissions.manage_messages:
            return True
        
        fakeperms_cog = ctx.bot.get_cog("FakePerms")
        if fakeperms_cog:
            if await fakeperms_cog.has_fakeperm(ctx.guild, ctx.author, "manage_messages"):
                return True
            if await fakeperms_cog.has_fakeperm(ctx.guild, ctx.author, "administrator"):
                return True
        
        raise commands.MissingPermissions(["manage_messages"])
    
    return commands.check(predicate)


class Moderation(commands.Cog):
    """⚔️ Comandos de moderación para administrar tu servidor"""
    
    emoji = "⚔️"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._logger = logging.getLogger(__name__)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Reaplicar cuarentena si el usuario salió y volvió a entrar"""
        if member.bot:
            return

        quarantine_data = await database.quarantine.find_one({
            "guild_id": member.guild.id,
            "user_id": member.id
        })
        if not quarantine_data:
            return

        # Esperar un poco para que otros cogs (autorole/verification) terminen
        await asyncio.sleep(1)

        # Verificar que la cuarentena sigue activa
        still_quarantined = await database.quarantine.find_one({
            "guild_id": member.guild.id,
            "user_id": member.id
        })
        if not still_quarantined:
            return

        settings = None
        antinuke_cog = self.bot.get_cog("Antinuke")
        if antinuke_cog:
            try:
                settings = await antinuke_cog.get_settings(member.guild.id)
            except Exception:
                settings = None

        if not settings:
            settings = await database.antinuke_servers.find_one(
                {"guild_id": member.guild.id},
                {"quarantine_role": 1}
            )

        quarantine_role_id = settings.get("quarantine_role") if settings else None
        if not quarantine_role_id:
            return

        quarantine_role = member.guild.get_role(quarantine_role_id)
        if not quarantine_role:
            return

        me = member.guild.me or member.guild.get_member(self.bot.user.id)
        if not me or not me.guild_permissions.manage_roles:
            return
        if quarantine_role >= me.top_role:
            return

        roles_to_remove = [
            r for r in member.roles
            if r != member.guild.default_role and r != quarantine_role and r < me.top_role
        ]

        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Cuarentena persistente (rejoin)")
            if quarantine_role not in member.roles:
                await member.add_roles(quarantine_role, reason="Cuarentena persistente (rejoin)")

            reason = quarantine_data.get("reason") or "Sin razón especificada"
            dm_embed = discord.Embed(
                title="🔒 Tu cuarentena sigue activa",
                description=(
                    f"Salirte y volver a entrar **no elimina** la sanción en **{member.guild.name}**.\n"
                    "La cuarentena es persistente hasta que un moderador la quite."
                ),
                color=0x800080
            )
            dm_embed.add_field(name="Razón", value=reason, inline=False)
            dm_embed.set_footer(text=f"Servidor: {member.guild.name}")
            try:
                await member.send(embed=dm_embed)
            except discord.HTTPException:
                pass
        except discord.HTTPException:
            pass

    # ========== Helpers ==========
    
    async def send_mod_log(
        self,
        guild: discord.Guild,
        action: str,
        moderator: Union[discord.Member, discord.User],
        target: Union[discord.Member, discord.User],
        reason: str,
        case_id: int,
        duration: str = None
    ):
        """Enviar log de moderación al canal configurado"""
        logging_cog = self.bot.get_cog("Logging")
        if not logging_cog:
            self._logger.debug("[MOD_LOG] No se encontró el cog Logging")
            return
        
        event_map = {
            "warn": "mod_warn",
            "kick": "mod_kick",
            "ban": "mod_ban",
            "unban": "mod_unban",
            "softban": "mod_kick",
            "timeout": "mod_timeout",
            "untimeout": "mod_untimeout",
            "quarantine": "mod_quarantine",
            "unquarantine": "mod_unquarantine",
        }
        
        event = event_map.get(action, f"mod_{action}")
        
        is_enabled = await logging_cog.is_event_enabled(guild.id, event)
        self._logger.debug("[MOD_LOG] Evento '%s' habilitado: %s", event, is_enabled)
        
        if not is_enabled:
            return
        
        channel = await logging_cog.get_log_channel(guild, event)
        self._logger.debug("[MOD_LOG] Canal obtenido: %s", channel)
        
        if not channel:
            return
        
        action_info = MOD_ACTIONS.get(action, {"emoji": "⚙️", "color": config.BLURPLE_COLOR, "name": action.title()})
        
        embed = discord.Embed(
            title=f"{action_info['emoji']} {action_info['name']} | Caso #{case_id}",
            color=action_info['color'],
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(name="Usuario", value=f"{target.mention}\n`{target.id}`", inline=True)
        embed.add_field(name="Moderador", value=f"{moderator.mention}", inline=True)
        
        if duration:
            embed.add_field(name="Duración", value=duration, inline=True)
        
        embed.add_field(name="Razón", value=reason or "Sin razón especificada", inline=False)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text=f"ID del usuario: {target.id}")
        
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass
    
    async def create_case(
        self,
        guild_id: int,
        moderator_id: int,
        target_id: int,
        action: str,
        reason: Optional[str] = None,
        duration: Optional[int] = None,
        expires_at: Optional[datetime] = None
    ) -> int:
        """Crear un caso de moderación y retornar case_id"""
        last_case = await database.modlogs.find_one(
            {"guild_id": guild_id},
            sort=[("case_id", -1)]
        )
        case_id = (last_case["case_id"] + 1) if last_case else 1
        
        case_data = {
            "guild_id": guild_id,
            "case_id": case_id,
            "moderator_id": moderator_id,
            "target_id": target_id,
            "action": action,
            "reason": reason,
            "timestamp": discord.utils.utcnow(),
            "active": True
        }
        
        if duration:
            case_data["duration"] = duration
        if expires_at:
            case_data["expires_at"] = expires_at
        
        await database.modlogs.insert_one(case_data)
        return case_id
    
    async def get_case(self, guild_id: int, case_id: int) -> Optional[dict]:
        """Obtener un caso específico"""
        return await database.modlogs.find_one({
            "guild_id": guild_id,
            "case_id": case_id
        })
    
    async def get_user_cases(self, guild_id: int, user_id: int, action: str = None) -> list:
        """Obtener todos los casos de un usuario"""
        query = {"guild_id": guild_id, "target_id": user_id}
        if action:
            query["action"] = action
        
        return await database.modlogs.find(query).sort("case_id", -1).to_list(length=None)
    
    # ========== Comandos de Casos ==========
    
    @commands.group(
        name="case",
        aliases=["caso", "cases"],
        brief="Sistema de casos de moderación",
        invoke_without_command=True
    )
    @has_mod_permissions()
    async def case(self, ctx: commands.Context, case_id: int = None):
        """
        Ver información de un caso específico.
        
        **Uso:** ;case <número>
        **Ejemplo:** ;case 15
        """
        if case_id is None:
            embed = discord.Embed(
                title="📋 Sistema de Casos",
                description="Gestiona los casos de moderación del servidor.",
                color=config.BLURPLE_COLOR
            )
            
            embed.add_field(
                name="Comandos Disponibles",
                value=(
                    f"`{ctx.prefix}case <número>` - Ver un caso\n"
                    f"`{ctx.prefix}case edit <número> <razón>` - Editar razón\n"
                    f"`{ctx.prefix}case delete <número>` - Eliminar caso\n"
                    f"`{ctx.prefix}case list [usuario]` - Ver casos\n"
                    f"`{ctx.prefix}case search <usuario>` - Buscar por usuario\n"
                    f"`{ctx.prefix}case recent` - Casos recientes\n"
                    f"`{ctx.prefix}case clear <usuario> [tipo]` - Limpiar casos"
                ),
                inline=False
            )
            
            embed.set_footer(text="Los casos registran todas las acciones de moderación")
            return await ctx.send(embed=embed)
        
        case_data = await self.get_case(ctx.guild.id, case_id)
        
        if not case_data:
            return await ctx.send(embed=error_embed(f"Caso #{case_id} no encontrado"))
        
        action_info = MOD_ACTIONS.get(case_data["action"], {"emoji": "⚙️", "color": config.BLURPLE_COLOR, "name": case_data["action"].title()})
        
        embed = discord.Embed(
            title=f"{action_info['emoji']} Caso #{case_id}",
            color=action_info["color"],
            timestamp=case_data["timestamp"]
        )
        
        target = self.bot.get_user(case_data["target_id"])
        target_str = f"{target.mention} (`{target.id}`)" if target else f"ID: `{case_data['target_id']}`"
        embed.add_field(name="👤 Usuario", value=target_str, inline=True)
        
        mod = self.bot.get_user(case_data["moderator_id"])
        mod_str = f"{mod.mention}" if mod else f"ID: `{case_data['moderator_id']}`"
        embed.add_field(name="🛡️ Moderador", value=mod_str, inline=True)
        
        embed.add_field(name="📌 Acción", value=action_info["name"], inline=True)
        embed.add_field(name="📝 Razón", value=case_data.get("reason") or "Sin razón especificada", inline=False)
        
        if case_data.get("duration"):
            embed.add_field(name="⏱️ Duración", value=format_time(case_data["duration"]), inline=True)
        
        if case_data.get("edited_by"):
            editor = self.bot.get_user(case_data["edited_by"])
            editor_str = str(editor) if editor else f"ID: {case_data['edited_by']}"
            edit_time = discord.utils.format_dt(ensure_utc(case_data.get("edited_at")), "f")
            embed.add_field(name="✏️ Editado", value=f"Por {editor_str} {edit_time}", inline=False)
        
        if target:
            embed.set_thumbnail(url=target.display_avatar.url)
        
        embed.set_footer(text=f"Caso #{case_id}")
        
        await ctx.send(embed=embed)
    
    @case.command(name="edit", aliases=["editar", "reason"])
    @has_mod_permissions()
    async def case_edit(self, ctx: commands.Context, case_id: int, *, new_reason: str):
        """
        Editar la razón de un caso.
        
        **Uso:** ;case edit <número> <nueva razón>
        **Ejemplo:** ;case edit 15 Spam repetido en múltiples canales
        """
        case_data = await self.get_case(ctx.guild.id, case_id)
        
        if not case_data:
            return await ctx.send(embed=error_embed(f"Caso #{case_id} no encontrado"))
        
        old_reason = case_data.get("reason") or "Sin razón"
        
        await database.modlogs.update_one(
            {"guild_id": ctx.guild.id, "case_id": case_id},
            {"$set": {
                "reason": new_reason,
                "edited_by": ctx.author.id,
                "edited_at": discord.utils.utcnow()
            }}
        )
        
        embed = success_embed(f"✅ Caso #{case_id} actualizado")
        embed.add_field(name="Razón anterior", value=old_reason[:200], inline=False)
        embed.add_field(name="Nueva razón", value=new_reason[:200], inline=False)
        await ctx.send(embed=embed)
    
    @case.command(name="delete", aliases=["remove", "eliminar", "del"])
    @commands.has_permissions(administrator=True)
    async def case_delete(self, ctx: commands.Context, case_id: int):
        """
        Eliminar un caso específico (solo administradores).
        
        **Uso:** ;case delete <número>
        """
        case_data = await self.get_case(ctx.guild.id, case_id)
        
        if not case_data:
            return await ctx.send(embed=error_embed(f"Caso #{case_id} no encontrado"))
        
        action_info = MOD_ACTIONS.get(case_data['action'], {'name': case_data['action']})
        
        confirmed = await confirm(
            ctx,
            f"¿Eliminar el caso **#{case_id}** ({action_info['name']})?\n"
            "Esta acción no se puede deshacer."
        )
        
        if not confirmed:
            return await ctx.send(embed=warning_embed("Cancelado"))
        
        await database.modlogs.delete_one({"guild_id": ctx.guild.id, "case_id": case_id})
        
        await ctx.send(embed=success_embed(f"🗑️ Caso #{case_id} eliminado"))
    
    @case.command(name="list", aliases=["lista", "all"])
    @has_mod_permissions()
    async def case_list(self, ctx: commands.Context, member: discord.Member = None):
        """
        Ver lista de casos recientes o de un usuario.
        
        **Uso:** ;case list [usuario]
        """
        if member:
            cases = await self.get_user_cases(ctx.guild.id, member.id)
            title = f"📋 Casos de {member}"
        else:
            cases = await database.modlogs.find(
                {"guild_id": ctx.guild.id}
            ).sort("case_id", -1).limit(50).to_list(length=None)
            title = "📋 Casos del Servidor"
        
        if not cases:
            return await ctx.send(embed=warning_embed("No hay casos registrados"))
        
        embeds = []
        for i in range(0, len(cases), 10):
            chunk = cases[i:i+10]
            
            embed = discord.Embed(title=title, color=config.BLURPLE_COLOR)
            
            if member:
                embed.set_thumbnail(url=member.display_avatar.url)
            
            lines = []
            for case in chunk:
                action_info = MOD_ACTIONS.get(case["action"], {"emoji": "⚙️", "name": case["action"]})
                target = self.bot.get_user(case["target_id"])
                target_str = str(target) if target else f"ID:{case['target_id']}"
                
                time_str = discord.utils.format_dt(ensure_utc(case["timestamp"]), "f")
                reason = (case.get("reason") or "Sin razón")[:40]
                
                if member:
                    lines.append(f"`#{case['case_id']}` {action_info['emoji']} **{action_info['name']}** {time_str}\n└ {reason}")
                else:
                    lines.append(f"`#{case['case_id']}` {action_info['emoji']} **{target_str}** - {reason}")
            
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"Total: {len(cases)} casos • Página {i//10 + 1}/{(len(cases)-1)//10 + 1}")
            embeds.append(embed)
        
        await paginate(ctx, embeds)
    
    @case.command(name="search", aliases=["buscar", "user"])
    @has_mod_permissions()
    async def case_search(self, ctx: commands.Context, user: discord.User):
        """
        Buscar todos los casos de un usuario (incluso si no está en el servidor).
        
        **Uso:** ;case search <usuario/ID>
        """
        cases = await self.get_user_cases(ctx.guild.id, user.id)
        
        if not cases:
            return await ctx.send(embed=warning_embed(f"No hay casos registrados para **{user}**"))
        
        counts = {}
        for case in cases:
            action = case["action"]
            counts[action] = counts.get(action, 0) + 1
        
        embed = discord.Embed(
            title=f"📋 Historial de {user}",
            color=config.BLURPLE_COLOR
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        summary_lines = []
        for action, count in counts.items():
            info = MOD_ACTIONS.get(action, {"emoji": "⚙️", "name": action})
            summary_lines.append(f"{info['emoji']} {info['name']}: **{count}**")
        
        embed.add_field(name="📊 Resumen", value="\n".join(summary_lines) or "Ninguno", inline=False)
        
        recent = cases[:5]
        recent_lines = []
        for case in recent:
            info = MOD_ACTIONS.get(case["action"], {"emoji": "⚙️"})
            time_str = discord.utils.format_dt(ensure_utc(case["timestamp"]), "f")
            recent_lines.append(f"`#{case['case_id']}` {info['emoji']} {time_str}")
        
        embed.add_field(name="🕐 Recientes", value="\n".join(recent_lines), inline=False)
        embed.set_footer(text=f"Total: {len(cases)} casos • ID: {user.id}")
        
        await ctx.send(embed=embed)
    
    @case.command(name="recent", aliases=["recientes"])
    @has_mod_permissions()
    async def case_recent(self, ctx: commands.Context, amount: int = 10):
        """
        Ver los casos más recientes del servidor.
        
        **Uso:** ;case recent [cantidad]
        """
        amount = min(amount, 25)
        
        cases = await database.modlogs.find(
            {"guild_id": ctx.guild.id}
        ).sort("case_id", -1).limit(amount).to_list(length=None)
        
        if not cases:
            return await ctx.send(embed=warning_embed("No hay casos registrados"))
        
        embed = discord.Embed(
            title=f"📋 Últimos {len(cases)} Casos",
            color=config.BLURPLE_COLOR
        )
        
        lines = []
        for case in cases:
            info = MOD_ACTIONS.get(case["action"], {"emoji": "⚙️", "name": case["action"]})
            target = self.bot.get_user(case["target_id"])
            target_str = str(target) if target else f"ID:{case['target_id']}"
            time_str = discord.utils.format_dt(ensure_utc(case["timestamp"]), "f")
            
            lines.append(f"`#{case['case_id']}` {info['emoji']} **{target_str}** {time_str}")
        
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)
    
    @case.command(name="clear", aliases=["limpiar", "purge"])
    @commands.has_permissions(administrator=True)
    async def case_clear(self, ctx: commands.Context, user: discord.User, action_type: str = None):
        """
        Limpiar casos de un usuario (solo administradores).
        
        **Uso:** ;case clear <usuario> [tipo]
        **Ejemplo:** ;case clear @usuario warn
        **Tipos:** warn, kick, ban, timeout, note
        """
        query = {"guild_id": ctx.guild.id, "target_id": user.id}
        
        if action_type:
            action_type = action_type.lower()
            if action_type not in MOD_ACTIONS:
                types = ", ".join(f"`{t}`" for t in MOD_ACTIONS.keys())
                return await ctx.send(embed=error_embed(f"Tipo inválido. Usa: {types}"))
            query["action"] = action_type
            type_str = MOD_ACTIONS[action_type]["name"]
        else:
            type_str = "todos los casos"
        
        count = await database.modlogs.count_documents(query)
        
        if count == 0:
            return await ctx.send(embed=warning_embed(f"No hay casos para eliminar de **{user}**"))
        
        confirmed = await confirm(
            ctx,
            f"¿Eliminar **{count}** casos ({type_str}) de **{user}**?\n"
            "Esta acción no se puede deshacer."
        )
        
        if not confirmed:
            return await ctx.send(embed=warning_embed("Cancelado"))
        
        result = await database.modlogs.delete_many(query)
        
        await ctx.send(embed=success_embed(f"🗑️ Se eliminaron **{result.deleted_count}** casos de **{user}**"))
    
    # ========== Comando Historial ==========
    
    @commands.command(
        name="history",
        aliases=["historial", "modlogs", "infractions"],
        brief="Ver historial de moderación de un usuario"
    )
    @has_mod_permissions()
    async def history(self, ctx: commands.Context, user: discord.User):
        """
        Ver el historial completo de moderación de un usuario.
        
        **Uso:** ;history <usuario>
        **Ejemplo:** ;history @usuario
        """
        await ctx.invoke(self.case_search, user=user)
    
    # ========== Nota ==========
    
    @commands.command(
        name="note",
        aliases=["nota"],
        brief="Añadir una nota a un usuario"
    )
    @has_mod_permissions()
    async def note(self, ctx: commands.Context, user: discord.User, *, content: str):
        """
        Añadir una nota sobre un usuario (no es una sanción).
        
        **Uso:** ;note <usuario> <contenido>
        **Ejemplo:** ;note @usuario Posible alt de Usuario#1234
        """
        case_id = await self.create_case(
            ctx.guild.id, ctx.author.id, user.id, "note", content
        )
        embed = success_embed(f"`Caso #{case_id}` {user} recibió una nota.")
        await ctx.send(embed=embed)
    
    # ========== Comandos de Kick/Ban ==========
    
    @commands.command(
        name="kick",
        aliases=["expulsar"],
        brief="Expulsar a un miembro del servidor"
    )
    @has_kick_permissions()
    @commands.bot_has_permissions(kick_members=True)
    async def kick(
        self, 
        ctx: commands.Context, 
        member: discord.Member,
        *, 
        reason: Optional[str] = "Sin razón especificada"
    ):
        """
        Expulsar a un miembro del servidor.
        
        **Uso:** ;kick <miembro> [razón]
        **Ejemplo:** ;kick @usuario Spam
        """
        can_mod, error_msg = can_moderate(ctx.author, member, "expulsar")
        if not can_mod:
            return await ctx.send(embed=error_embed(error_msg))
        
        can_bot, error_msg = can_bot_moderate(ctx.guild.me, member, "expulsar")
        if not can_bot:
            return await ctx.send(embed=error_embed(error_msg))
        
        # DM al usuario
        try:
            dm_embed = discord.Embed(
                title=f"👢 Has sido expulsado de {ctx.guild.name}",
                description=f"**Razón:** {reason}",
                color=config.ERROR_COLOR
            )
            dm_embed.set_footer(text=f"Moderador: {ctx.author}")
            await member.send(embed=dm_embed)
        except discord.HTTPException:
            pass
        
        await member.kick(reason=f"{ctx.author}: {reason}")
        
        case_id = await self.create_case(
            ctx.guild.id, ctx.author.id, member.id, "kick", reason
        )
        
        await self.send_mod_log(ctx.guild, "kick", ctx.author, member, reason, case_id)
        embed = success_embed(f"`Caso #{case_id}` {member} ha sido expulsado.")
        await ctx.send(embed=embed)
    
    @commands.command(
        name="ban",
        aliases=["banear"],
        brief="Banear a un usuario del servidor"
    )
    @has_ban_permissions()
    @commands.bot_has_permissions(ban_members=True)
    async def ban(
        self,
        ctx: commands.Context,
        user: Union[discord.Member, discord.User],
        *,
        reason: Optional[str] = "Sin razón especificada"
    ):
        """
        Banear a un usuario del servidor.
        Puedes banear usuarios que no están en el servidor usando su ID.
        
        **Uso:** ;ban <usuario> [razón]
        **Ejemplo:** ;ban @usuario Toxicidad
        """
        if isinstance(user, discord.Member):
            can_mod, error_msg = can_moderate(ctx.author, user, "banear")
            if not can_mod:
                return await ctx.send(embed=error_embed(error_msg))
            
            can_bot, error_msg = can_bot_moderate(ctx.guild.me, user, "banear")
            if not can_bot:
                return await ctx.send(embed=error_embed(error_msg))
            
            # DM
            try:
                dm_embed = discord.Embed(
                    title=f"🔨 Has sido baneado de {ctx.guild.name}",
                    description=f"**Razón:** {reason}",
                    color=config.ERROR_COLOR
                )
                dm_embed.set_footer(text=f"Moderador: {ctx.author}")
                await user.send(embed=dm_embed)
            except discord.HTTPException:
                pass
        
        await ctx.guild.ban(user, reason=f"{ctx.author}: {reason}", delete_message_days=0)
        
        case_id = await self.create_case(
            ctx.guild.id, ctx.author.id, user.id, "ban", reason
        )
        
        await self.send_mod_log(ctx.guild, "ban", ctx.author, user, reason, case_id)
        embed = success_embed(f"`Caso #{case_id}` {user} ha sido baneado.")
        await ctx.send(embed=embed)
    
    @commands.command(
        name="unban",
        aliases=["desbanear"],
        brief="Desbanear a un usuario"
    )
    @has_ban_permissions()
    @commands.bot_has_permissions(ban_members=True)
    async def unban(
        self,
        ctx: commands.Context,
        user: discord.User,
        *,
        reason: Optional[str] = "Sin razón especificada"
    ):
        """
        Desbanear a un usuario del servidor.
        
        **Uso:** ;unban <usuario_id> [razón]
        """
        try:
            await ctx.guild.unban(user, reason=f"{ctx.author}: {reason}")
        except discord.NotFound:
            return await ctx.send(embed=error_embed(f"**{user}** no está baneado"))
        
        case_id = await self.create_case(
            ctx.guild.id, ctx.author.id, user.id, "unban", reason
        )
        
        await self.send_mod_log(ctx.guild, "unban", ctx.author, user, reason, case_id)
        embed = success_embed(f"`Caso #{case_id}` {user} ha sido desbaneado.")
        await ctx.send(embed=embed)
    
    @commands.command(
        name="softban",
        brief="Banear y desbanear para eliminar mensajes"
    )
    @has_ban_permissions()
    @commands.bot_has_permissions(ban_members=True)
    async def softban(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: Optional[str] = "Sin razón especificada"
    ):
        """
        Softban: banear y desbanear inmediatamente (elimina mensajes de 7 días).
        
        **Uso:** ;softban <miembro> [razón]
        """
        can_mod, error_msg = can_moderate(ctx.author, member, "softbanear")
        if not can_mod:
            return await ctx.send(embed=error_embed(error_msg))
        
        can_bot, error_msg = can_bot_moderate(ctx.guild.me, member, "softbanear")
        if not can_bot:
            return await ctx.send(embed=error_embed(error_msg))
        
        await ctx.guild.ban(member, reason=f"Softban por {ctx.author}: {reason}", delete_message_days=7)
        await ctx.guild.unban(member, reason="Softban completado")
        
        case_id = await self.create_case(
            ctx.guild.id, ctx.author.id, member.id, "softban", reason
        )
        
        await self.send_mod_log(ctx.guild, "softban", ctx.author, member, reason, case_id)
        embed = success_embed(f"`Caso #{case_id}` {member} ha sido softbaneado.")
        await ctx.send(embed=embed)
    
    # ========== Timeout/Mute ==========
    
    @commands.command(
        name="timeout",
        aliases=["mute", "silenciar", "to"],
        brief="Silenciar a un miembro temporalmente"
    )
    @has_mod_permissions()
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout(
        self,
        ctx: commands.Context,
        member: discord.Member,
        duration: str,
        *,
        reason: Optional[str] = "Sin razón especificada"
    ):
        """
        Silenciar a un miembro usando timeout de Discord.
        
        **Uso:** ;timeout <miembro> <duración> [razón]
        **Ejemplo:** ;timeout @usuario 1h Spam
        **Duraciones:** 30s, 5m, 1h, 1d, 1w
        """
        can_mod, error_msg = can_moderate(ctx.author, member, "silenciar")
        if not can_mod:
            return await ctx.send(embed=error_embed(error_msg))
        
        can_bot, error_msg = can_bot_moderate(ctx.guild.me, member, "silenciar")
        if not can_bot:
            return await ctx.send(embed=error_embed(error_msg))
        
        seconds = parse_time(duration)
        if seconds is None:
            return await ctx.send(embed=error_embed("Duración inválida. Usa: 30s, 5m, 1h, 1d, 1w"))
        
        if seconds > 2419200:  # 28 días
            return await ctx.send(embed=error_embed("La duración máxima es 28 días"))
        
        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        await member.timeout(until, reason=f"{ctx.author}: {reason}")
        
        case_id = await self.create_case(
            ctx.guild.id, ctx.author.id, member.id, "timeout", reason,
            duration=seconds, expires_at=until
        )
        
        await self.send_mod_log(ctx.guild, "timeout", ctx.author, member, reason, case_id, format_time(seconds))
        embed = success_embed(f"`Caso #{case_id}` {member} ha sido silenciado.")
        await ctx.send(embed=embed)
        
        # DM
        try:
            dm_embed = discord.Embed(
                title=f"🔇 Has sido silenciado en {ctx.guild.name}",
                description=f"**Duración:** {format_time(seconds)}\n**Razón:** {reason}",
                color=config.WARNING_COLOR
            )
            await member.send(embed=dm_embed)
        except discord.HTTPException:
            pass
    
    @commands.command(
        name="untimeout",
        aliases=["unmute", "desilenciar"],
        brief="Quitar timeout a un miembro"
    )
    @has_mod_permissions()
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: Optional[str] = "Sin razón especificada"
    ):
        """
        Quitar el timeout de un miembro.
        
        **Uso:** ;untimeout <miembro> [razón]
        """
        if not member.is_timed_out():
            return await ctx.send(embed=error_embed(f"**{member}** no está silenciado"))
        
        await member.timeout(None, reason=f"{ctx.author}: {reason}")
        
        case_id = await self.create_case(
            ctx.guild.id, ctx.author.id, member.id, "untimeout", reason
        )
        
        await self.send_mod_log(ctx.guild, "untimeout", ctx.author, member, reason, case_id)
        embed = success_embed(f"`Caso #{case_id}` {member} ya no tiene timeout.")
        await ctx.send(embed=embed)
    
    # ========== Quarantine ==========
    
    @commands.command(
        name="quarantine",
        aliases=["cuarentena", "jail"],
        brief="Poner a un miembro en cuarentena"
    )
    @has_mod_permissions()
    @commands.bot_has_permissions(manage_roles=True)
    async def quarantine(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: Optional[str] = "Sin razón especificada"
    ):
        """
        Poner a un miembro en cuarentena (quita todos sus roles y asigna rol de cuarentena).
        
        **Configuración previa:**
        1. Crea un rol llamado "Cuarentena" o similar
        2. Configúralo para que no tenga acceso a nada
        3. Usa `;antinuke setroles quarantine @Cuarentena`
        
        **Uso:** ;quarantine <miembro> [razón]
        **Ejemplo:** ;quarantine @user Comportamiento sospechoso
        """
        if member.bot:
            return await ctx.send(embed=error_embed("No puedes poner en cuarentena a un bot"))
        
        if not await can_moderate(ctx, member):
            return await ctx.send(embed=error_embed("No puedes moderar a este usuario"))
        
        if not await can_bot_moderate(ctx, member):
            return await ctx.send(embed=error_embed("No puedo moderar a este usuario"))
        
        # Obtener rol de cuarentena
        antinuke_settings = await database.antinuke_servers.find_one({"guild_id": ctx.guild.id})
        quarantine_role_id = antinuke_settings.get("quarantine_role") if antinuke_settings else None
        
        if not quarantine_role_id:
            return await ctx.send(embed=error_embed(
                "No hay rol de cuarentena configurado.\n"
                "Usa: `;antinuke setroles quarantine @rol`"
            ))
        
        quarantine_role = ctx.guild.get_role(quarantine_role_id)
        if not quarantine_role:
            return await ctx.send(embed=error_embed(
                "El rol de cuarentena configurado ya no existe.\n"
                "Configura uno nuevo: `;antinuke setroles quarantine @rol`"
            ))
        
        # Verificar si ya está en cuarentena
        if quarantine_role in member.roles:
            return await ctx.send(embed=error_embed(f"**{member}** ya está en cuarentena"))
        
        # Guardar roles actuales para poder restaurarlos después
        current_roles = [r.id for r in member.roles if r != ctx.guild.default_role and r != quarantine_role]
        
        # Guardar en base de datos
        await database.quarantine.update_one(
            {"guild_id": ctx.guild.id, "user_id": member.id},
            {"$set": {
                "guild_id": ctx.guild.id,
                "user_id": member.id,
                "previous_roles": current_roles,
                "moderator_id": ctx.author.id,
                "reason": reason,
                "timestamp": discord.utils.utcnow()
            }},
            upsert=True
        )
        
        # Quitar todos los roles y asignar cuarentena
        try:
            roles_to_remove = [r for r in member.roles if r != ctx.guild.default_role]
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason=f"Cuarentena por {ctx.author}: {reason}")
            await member.add_roles(quarantine_role, reason=f"Cuarentena por {ctx.author}: {reason}")
        except discord.HTTPException as e:
            return await ctx.send(embed=error_embed(f"Error al aplicar cuarentena: {e}"))
        
        # Crear caso
        case_id = await self.create_case(
            ctx.guild.id, ctx.author.id, member.id, "quarantine", reason
        )
        
        await self.send_mod_log(ctx.guild, "quarantine", ctx.author, member, reason, case_id)
        embed = success_embed(f"`Caso #{case_id}` {member} ha sido puesto en cuarentena.")
        await ctx.send(embed=embed)
        
        # Intentar enviar DM
        try:
            dm_embed = discord.Embed(
                title="🔒 Has sido puesto en cuarentena",
                description=f"Un moderador te ha puesto en cuarentena en **{ctx.guild.name}**",
                color=0x800080
            )
            dm_embed.add_field(name="Razón", value=reason, inline=False)
            dm_embed.add_field(name="Moderador", value=str(ctx.author), inline=True)
            await member.send(embed=dm_embed)
        except discord.HTTPException:
            pass
    
    @commands.command(
        name="unquarantine",
        aliases=["unjail", "descuarentenar"],
        brief="Quitar la cuarentena de un miembro"
    )
    @has_mod_permissions()
    @commands.bot_has_permissions(manage_roles=True)
    async def unquarantine(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: Optional[str] = "Sin razón especificada"
    ):
        """
        Quitar la cuarentena de un miembro y restaurar sus roles anteriores.
        
        **Uso:** ;unquarantine <miembro> [razón]
        """
        # Obtener rol de cuarentena
        antinuke_settings = await database.antinuke_servers.find_one({"guild_id": ctx.guild.id})
        quarantine_role_id = antinuke_settings.get("quarantine_role") if antinuke_settings else None
        
        if not quarantine_role_id:
            return await ctx.send(embed=error_embed("No hay rol de cuarentena configurado"))
        
        quarantine_role = ctx.guild.get_role(quarantine_role_id)
        if not quarantine_role:
            return await ctx.send(embed=error_embed("El rol de cuarentena ya no existe"))
        
        # Verificar si está en cuarentena
        if quarantine_role not in member.roles:
            return await ctx.send(embed=error_embed(f"**{member}** no está en cuarentena"))
        
        # Obtener roles anteriores guardados
        quarantine_data = await database.quarantine.find_one({
            "guild_id": ctx.guild.id,
            "user_id": member.id
        })
        
        previous_role_ids = quarantine_data.get("previous_roles", []) if quarantine_data else []
        
        # Quitar rol de cuarentena
        try:
            await member.remove_roles(quarantine_role, reason=f"Fin cuarentena por {ctx.author}: {reason}")
            
            # Restaurar roles anteriores
            roles_restored = 0
            for role_id in previous_role_ids:
                role = ctx.guild.get_role(role_id)
                if role and role < ctx.guild.me.top_role:
                    try:
                        await member.add_roles(role, reason=f"Restauración post-cuarentena por {ctx.author}")
                        roles_restored += 1
                    except discord.HTTPException:
                        pass
        except discord.HTTPException as e:
            return await ctx.send(embed=error_embed(f"Error al quitar cuarentena: {e}"))
        
        # Eliminar registro de cuarentena
        await database.quarantine.delete_one({
            "guild_id": ctx.guild.id,
            "user_id": member.id
        })
        
        # Crear caso
        case_id = await self.create_case(
            ctx.guild.id, ctx.author.id, member.id, "unquarantine", reason
        )
        
        await self.send_mod_log(ctx.guild, "unquarantine", ctx.author, member, reason, case_id)

        embed = success_embed(f"`Caso #{case_id}` {member} ya no está en cuarentena.")
        await ctx.send(embed=embed)
        
        # Intentar enviar DM
        try:
            dm_embed = discord.Embed(
                title="🔓 Tu cuarentena ha sido removida",
                description=f"Un moderador te ha quitado la cuarentena en **{ctx.guild.name}**",
                color=0x00FF00
            )
            dm_embed.add_field(name="Razón", value=reason, inline=False)
            dm_embed.add_field(name="Moderador", value=str(ctx.author), inline=True)
            await member.send(embed=dm_embed)
        except discord.HTTPException:
            pass
    
    # ========== Purge/Clear ==========
    
    @commands.command(
        name="purge",
        aliases=["clear", "limpiar", "prune"],
        brief="Eliminar mensajes del canal"
    )
    @has_manage_messages()
    @commands.bot_has_permissions(manage_messages=True)
    async def purge(
        self,
        ctx: commands.Context,
        amount: int,
        member: Optional[discord.Member] = None
    ):
        """
        Eliminar mensajes del canal.
        
        **Uso:** ;purge <cantidad> [miembro]
        **Ejemplo:** ;purge 50
        **Ejemplo:** ;purge 20 @usuario
        """
        if amount < 1 or amount > 1000:
            return await ctx.send(embed=error_embed("La cantidad debe estar entre 1 y 1000"))
        
        await ctx.message.delete()
        
        def check(m):
            if member:
                return m.author == member
            return True
        
        deleted = await ctx.channel.purge(limit=amount, check=check, bulk=True)
        
        embed = success_embed(
            f"🗑️ Se eliminaron **{len(deleted)}** mensajes"
            + (f" de **{member}**" if member else "")
        )
        msg = await ctx.send(embed=embed)
        await asyncio.sleep(3)
        await msg.delete()
    
    @commands.command(
        name="nuke",
        brief="Recrear el canal (eliminar todos los mensajes)"
    )
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def nuke(self, ctx: commands.Context):
        """Recrear el canal para eliminar todos los mensajes."""
        confirmed = await confirm(
            ctx,
            f"⚠️ **ADVERTENCIA:** Esto eliminará TODOS los mensajes de #{ctx.channel.name}."
        )
        
        if not confirmed:
            return
        
        position = ctx.channel.position
        new_channel = await ctx.channel.clone(reason=f"Nuke por {ctx.author}")
        await new_channel.edit(position=position)
        await ctx.channel.delete(reason=f"Nuke por {ctx.author}")
        
        embed = discord.Embed(
            description=f"💥 Canal recreado por {ctx.author.mention}",
            color=config.SUCCESS_COLOR
        )
        await new_channel.send(embed=embed)
    
    # ========== Warnings ==========
    
    @commands.group(
        name="warn",
        aliases=["advertir", "warning"],
        brief="Sistema de advertencias",
        invoke_without_command=True
    )
    @has_mod_permissions()
    async def warn(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str = "Sin razón especificada"
    ):
        """
        Advertir a un miembro.
        
        **Uso:** ;warn <miembro> [razón]
        **Ejemplo:** ;warn @usuario Comportamiento inapropiado
        """
        can_mod, error_msg = can_moderate(ctx.author, member, "advertir")
        if not can_mod:
            return await ctx.send(embed=error_embed(error_msg))
        
        case_id = await self.create_case(
            ctx.guild.id, ctx.author.id, member.id, "warn", reason
        )
        
        # Contar warns
        warn_count = await database.modlogs.count_documents({
            "guild_id": ctx.guild.id,
            "target_id": member.id,
            "action": "warn"
        })
        
        await self.send_mod_log(ctx.guild, "warn", ctx.author, member, reason, case_id)
        embed = success_embed(f"`Caso #{case_id}` {member} ha sido advertido.")
        await ctx.send(embed=embed)
        
        # DM
        try:
            dm_embed = discord.Embed(
                title=f"⚠️ Has recibido una advertencia en {ctx.guild.name}",
                description=f"**Razón:** {reason}\n**Advertencias:** {warn_count}",
                color=config.WARNING_COLOR
            )
            await member.send(embed=dm_embed)
        except discord.HTTPException:
            pass
    
    @warn.command(name="list", aliases=["ver", "check"])
    @has_mod_permissions()
    async def warn_list(self, ctx: commands.Context, member: discord.Member):
        """
        Ver las advertencias de un miembro.
        
        **Uso:** ;warn list <miembro>
        """
        cases = await self.get_user_cases(ctx.guild.id, member.id, "warn")
        
        if not cases:
            return await ctx.send(embed=warning_embed(f"**{member}** no tiene advertencias"))
        
        embed = discord.Embed(
            title=f"⚠️ Advertencias de {member}",
            description=f"Total: **{len(cases)}** advertencias",
            color=config.WARNING_COLOR
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        
        for case in cases[:10]:
            mod = self.bot.get_user(case["moderator_id"])
            mod_str = str(mod) if mod else f"ID:{case['moderator_id']}"
            time_str = discord.utils.format_dt(ensure_utc(case["timestamp"]), "f")
            
            embed.add_field(
                name=f"Caso #{case['case_id']} - {time_str}",
                value=f"**Mod:** {mod_str}\n**Razón:** {(case.get('reason') or 'Sin razón')[:100]}",
                inline=False
            )
        
        if len(cases) > 10:
            embed.set_footer(text=f"Mostrando 10 de {len(cases)} • Usa ;case list @usuario para ver todo")
        
        await ctx.send(embed=embed)
    
    @warn.command(name="remove", aliases=["delete", "del"])
    @has_mod_permissions()
    async def warn_remove(self, ctx: commands.Context, member: discord.Member, case_id: int):
        """
        Eliminar una advertencia específica.
        
        **Uso:** ;warn remove <miembro> <número_caso>
        **Ejemplo:** ;warn remove @usuario 15
        """
        case = await database.modlogs.find_one({
            "guild_id": ctx.guild.id,
            "case_id": case_id,
            "target_id": member.id,
            "action": "warn"
        })
        
        if not case:
            return await ctx.send(embed=error_embed(f"No se encontró el warn #{case_id} para **{member}**"))
        
        await database.modlogs.delete_one({"_id": case["_id"]})
        
        remaining = await database.modlogs.count_documents({
            "guild_id": ctx.guild.id,
            "target_id": member.id,
            "action": "warn"
        })
        
        await ctx.send(embed=success_embed(
            f"🗑️ Warn #{case_id} eliminado de **{member}**\n"
            f"Advertencias restantes: **{remaining}**"
        ))
    
    @warn.command(name="clear", aliases=["limpiar", "reset"])
    @commands.has_permissions(administrator=True)
    async def warn_clear(self, ctx: commands.Context, member: discord.Member):
        """
        Eliminar todas las advertencias de un miembro.
        
        **Uso:** ;warn clear <miembro>
        """
        result = await database.modlogs.delete_many({
            "guild_id": ctx.guild.id,
            "target_id": member.id,
            "action": "warn"
        })
        
        if result.deleted_count == 0:
            return await ctx.send(embed=warning_embed(f"**{member}** no tenía advertencias"))
        
        await ctx.send(embed=success_embed(
            f"🗑️ Se eliminaron **{result.deleted_count}** advertencias de **{member}**"
        ))
    
    # ========== Role Management ==========
    
    @commands.group(
        name="role",
        aliases=["rol"],
        brief="Gestión de roles",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role(self, ctx: commands.Context, member: discord.Member, *, role: discord.Role):
        """
        Añadir o quitar un rol de un miembro.
        
        **Uso:** ;role <miembro> <rol>
        """
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send(embed=error_embed("No puedes gestionar un rol igual o superior al tuyo"))
        
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("No puedo gestionar un rol igual o superior al mío"))
        
        if role in member.roles:
            await member.remove_roles(role, reason=f"Removido por {ctx.author}")
            embed = success_embed(f"➖ Removido **{role.name}** de **{member}**")
        else:
            await member.add_roles(role, reason=f"Añadido por {ctx.author}")
            embed = success_embed(f"➕ Añadido **{role.name}** a **{member}**")
        
        await ctx.send(embed=embed)
    
    @role.command(name="create", aliases=["crear"])
    @commands.has_permissions(manage_roles=True)
    async def role_create(self, ctx: commands.Context, *, name: str):
        """Crear un nuevo rol."""
        role = await ctx.guild.create_role(name=name, reason=f"Creado por {ctx.author}")
        await ctx.send(embed=success_embed(f"✅ Rol **{role.name}** creado"))
    
    @role.command(name="delete", aliases=["eliminar", "del"])
    @commands.has_permissions(manage_roles=True)
    async def role_delete(self, ctx: commands.Context, *, role: discord.Role):
        """Eliminar un rol."""
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send(embed=error_embed("No puedes eliminar un rol igual o superior al tuyo"))
        
        name = role.name
        await role.delete(reason=f"Eliminado por {ctx.author}")
        await ctx.send(embed=success_embed(f"🗑️ Rol **{name}** eliminado"))
    
    @role.command(name="all", aliases=["todos"])
    @commands.has_permissions(administrator=True)
    async def role_all(self, ctx: commands.Context, *, role: discord.Role):
        """Dar un rol a todos los miembros."""
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("No puedo asignar este rol"))
        
        confirmed = await confirm(ctx, f"¿Dar **{role.name}** a todos los miembros?")
        if not confirmed:
            return
        
        msg = await ctx.send(embed=warning_embed("⏳ Procesando..."))
        
        count = 0
        for member in ctx.guild.members:
            if role not in member.roles and not member.bot:
                try:
                    await member.add_roles(role)
                    count += 1
                except discord.HTTPException:
                    pass
        
        await msg.edit(embed=success_embed(f"✅ Rol dado a **{count}** miembros"))
    
    @role.command(name="humans", aliases=["humanos"])
    @commands.has_permissions(administrator=True)
    async def role_humans(self, ctx: commands.Context, *, role: discord.Role):
        """Dar un rol solo a los humanos (no bots)."""
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("No puedo asignar este rol"))
        
        human_count = len([m for m in ctx.guild.members if not m.bot])
        confirmed = await confirm(ctx, f"¿Dar **{role.name}** a **{human_count}** humanos?")
        if not confirmed:
            return
        
        msg = await ctx.send(embed=warning_embed("⏳ Procesando..."))
        
        count = 0
        for member in ctx.guild.members:
            if not member.bot and role not in member.roles:
                try:
                    await member.add_roles(role)
                    count += 1
                except discord.HTTPException:
                    pass
        
        await msg.edit(embed=success_embed(f"✅ Rol dado a **{count}** humanos"))
    
    @role.command(name="bots")
    @commands.has_permissions(administrator=True)
    async def role_bots(self, ctx: commands.Context, *, role: discord.Role):
        """Dar un rol solo a los bots."""
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("No puedo asignar este rol"))
        
        bot_count = len([m for m in ctx.guild.members if m.bot])
        confirmed = await confirm(ctx, f"¿Dar **{role.name}** a **{bot_count}** bots?")
        if not confirmed:
            return
        
        msg = await ctx.send(embed=warning_embed("⏳ Procesando..."))
        
        count = 0
        for member in ctx.guild.members:
            if member.bot and role not in member.roles:
                try:
                    await member.add_roles(role)
                    count += 1
                except discord.HTTPException:
                    pass
        
        await msg.edit(embed=success_embed(f"✅ Rol dado a **{count}** bots"))
    
    # ========== Slowmode ==========
    
    @commands.command(
        name="slowmode",
        aliases=["sm", "slow"],
        brief="Configurar slowmode del canal"
    )
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx: commands.Context, duration: str = "0"):
        """
        Configurar el slowmode del canal.
        
        **Uso:** ;slowmode <duración>
        **Ejemplo:** ;slowmode 5s (usar 0 para desactivar)
        """
        seconds = parse_time(duration) if duration != "0" else 0
        
        if seconds is None:
            seconds = 0
        
        if seconds > 21600:
            return await ctx.send(embed=error_embed("El slowmode máximo es 6 horas"))
        
        await ctx.channel.edit(slowmode_delay=seconds)
        
        if seconds == 0:
            await ctx.send(embed=success_embed("⚡ Slowmode desactivado"))
        else:
            await ctx.send(embed=success_embed(f"🐢 Slowmode: **{format_time(seconds)}**"))
    
    # ========== Lockdown ==========
    
    @commands.command(
        name="lock",
        aliases=["lockdown", "bloquear"],
        brief="Bloquear el canal"
    )
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Bloquear un canal."""
        channel = channel or ctx.channel
        
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Bloqueado por {ctx.author}")
        
        await ctx.send(embed=success_embed(f"🔒 {channel.mention} bloqueado"))
    
    @commands.command(
        name="unlock",
        aliases=["desbloquear"],
        brief="Desbloquear el canal"
    )
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Desbloquear un canal."""
        channel = channel or ctx.channel
        
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Desbloqueado por {ctx.author}")
        
        await ctx.send(embed=success_embed(f"🔓 {channel.mention} desbloqueado"))
    
    # ========== Mass Actions ==========
    
    @commands.command(name="massban", brief="Banear múltiples usuarios")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def massban(self, ctx: commands.Context, users: commands.Greedy[discord.User], *, reason: str = "Massban"):
        """
        Banear múltiples usuarios a la vez.
        
        **Uso:** ;massban <usuario1> <usuario2> ... [razón]
        """
        if not users:
            return await ctx.send(embed=error_embed("Debes especificar al menos un usuario"))
        
        if len(users) > 50:
            return await ctx.send(embed=error_embed("Máximo 50 usuarios a la vez"))
        
        confirmed = await confirm(ctx, f"¿Banear a **{len(users)}** usuarios?\nRazón: {reason}")
        if not confirmed:
            return
        
        msg = await ctx.send(embed=warning_embed("⏳ Procesando..."))
        
        success = 0
        failed = 0
        
        for user in users:
            try:
                await ctx.guild.ban(user, reason=f"Massban por {ctx.author}: {reason}")
                await self.create_case(ctx.guild.id, ctx.author.id, user.id, "ban", f"[Massban] {reason}")
                success += 1
            except:
                failed += 1
        
        await msg.edit(embed=success_embed(f"🔨 Baneados: **{success}**\n❌ Fallidos: **{failed}**"))
    
    @commands.command(name="masskick", brief="Expulsar múltiples usuarios")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def masskick(self, ctx: commands.Context, members: commands.Greedy[discord.Member], *, reason: str = "Masskick"):
        """
        Expulsar múltiples miembros a la vez.
        
        **Uso:** ;masskick <miembro1> <miembro2> ... [razón]
        """
        if not members:
            return await ctx.send(embed=error_embed("Debes especificar al menos un miembro"))
        
        if len(members) > 50:
            return await ctx.send(embed=error_embed("Máximo 50 miembros a la vez"))
        
        confirmed = await confirm(ctx, f"¿Expulsar a **{len(members)}** miembros?\nRazón: {reason}")
        if not confirmed:
            return
        
        msg = await ctx.send(embed=warning_embed("⏳ Procesando..."))
        
        success = 0
        failed = 0
        
        for member in members:
            try:
                if member.top_role < ctx.guild.me.top_role:
                    await member.kick(reason=f"Masskick por {ctx.author}: {reason}")
                    await self.create_case(ctx.guild.id, ctx.author.id, member.id, "kick", f"[Masskick] {reason}")
                    success += 1
                else:
                    failed += 1
            except:
                failed += 1
        
        await msg.edit(embed=success_embed(f"👢 Expulsados: **{success}**\n❌ Fallidos: **{failed}**"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
