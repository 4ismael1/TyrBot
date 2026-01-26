"""
Utilidades y helpers para el bot
"""

from __future__ import annotations

import re
import discord
from typing import TYPE_CHECKING, Optional, Any, Union
from datetime import datetime

if TYPE_CHECKING:
    from discord.ext import commands

from config import config


# ========== Formateo de texto ==========

def format_number(number: int) -> str:
    """Formatear número con separadores de miles"""
    return "{:,}".format(number)


def truncate(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncar texto a una longitud máxima"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def plural(count: int, singular: str, plural_form: Optional[str] = None) -> str:
    """Retornar forma singular o plural según el conteo"""
    if plural_form is None:
        plural_form = singular + "s"
    return singular if count == 1 else plural_form


# ========== Variables de mensaje ==========

async def parse_message_variables(
    text: str, 
    member: discord.Member,
    guild: Optional[discord.Guild] = None
) -> str:
    """
    Parsear variables de mensaje para welcome/goodbye/autoresponder
    
    Variables soportadas:
    - {user} - Nombre completo del usuario
    - {user.mention} - Mención del usuario
    - {user.name} - Nombre del usuario
    - {user.id} - ID del usuario
    - {user.avatar} - URL del avatar
    - {user.joined_at} - Fecha de entrada (formato relativo)
    - {user.created_at} - Fecha de creación de cuenta
    - {guild.name} - Nombre del servidor
    - {guild.count} - Cantidad de miembros
    - {guild.id} - ID del servidor
    - {guild.icon} - URL del icono
    - {guild.boost_count} - Cantidad de boosts
    - {guild.boost_tier} - Tier de boost
    """
    if guild is None:
        guild = member.guild
    
    replacements = {
        "{user}": str(member),
        "{user.mention}": member.mention,
        "{user.name}": member.name,
        "{user.display_name}": member.display_name,
        "{user.id}": str(member.id),
        "{user.avatar}": str(member.display_avatar.url),
        "{user.joined_at}": discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "N/A",
        "{user.created_at}": discord.utils.format_dt(member.created_at, style="R"),
        "{guild.name}": guild.name,
        "{guild.count}": str(guild.member_count),
        "{guild.id}": str(guild.id),
        "{guild.icon}": str(guild.icon.url) if guild.icon else "",
        "{guild.boost_count}": str(guild.premium_subscription_count),
        "{guild.boost_tier}": str(guild.premium_tier),
    }
    
    for var, value in replacements.items():
        text = text.replace(var, value)
    
    return text


# ========== Embed helpers ==========

def success_embed(description: str, author: Optional[discord.Member] = None) -> discord.Embed:
    """Crear embed de éxito"""
    embed = discord.Embed(
        description=f"{config.SUCCESS_EMOJI} {description}",
        color=config.SUCCESS_COLOR
    )
    if author:
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    return embed


def error_embed(description: str, author: Optional[discord.Member] = None) -> discord.Embed:
    """Crear embed de error"""
    embed = discord.Embed(
        description=f"{config.ERROR_EMOJI} {description}",
        color=config.ERROR_COLOR
    )
    if author:
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    return embed


def warning_embed(description: str, author: Optional[discord.Member] = None) -> discord.Embed:
    """Crear embed de advertencia"""
    embed = discord.Embed(
        description=f"{config.WARNING_EMOJI} {description}",
        color=config.WARNING_COLOR
    )
    if author:
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    return embed


def info_embed(
    title: Optional[str] = None,
    description: Optional[str] = None,
    color: int = config.BLURPLE_COLOR
) -> discord.Embed:
    """Crear embed de información"""
    return discord.Embed(title=title, description=description, color=color)


# ========== Permisos ==========

def get_permission_name(permission: str) -> str:
    """Convertir nombre de permiso a formato legible"""
    return permission.replace("_", " ").title()


def format_permissions(permissions: discord.Permissions) -> list[str]:
    """Formatear lista de permisos activos"""
    return [
        get_permission_name(perm) 
        for perm, value in permissions 
        if value
    ]


# ========== Role hierarchy ==========

def can_moderate(
    moderator: discord.Member,
    target: discord.Member,
    action: str = "moderate"
) -> tuple[bool, Optional[str]]:
    """
    Verificar si un moderador puede actuar sobre un miembro
    Retorna (puede_actuar, mensaje_error)
    """
    # No puede moderarse a sí mismo
    if moderator.id == target.id:
        return False, f"No puedes {action} a ti mismo"
    
    # No puede moderar bots (incluido el propio bot)
    if target.bot:
        return False, f"No puedes {action} a un bot"
    
    # No puede moderar al dueño del servidor
    if target.id == target.guild.owner_id:
        return False, f"No puedes {action} al dueño del servidor"
    
    # Verificar jerarquía de roles
    if moderator.top_role <= target.top_role and moderator.id != target.guild.owner_id:
        return False, f"No puedes {action} a alguien con un rol igual o superior al tuyo"
    
    return True, None


def can_bot_moderate(
    bot_member: discord.Member,
    target: discord.Member,
    action: str = "moderate"
) -> tuple[bool, Optional[str]]:
    """
    Verificar si el bot puede actuar sobre un miembro
    Retorna (puede_actuar, mensaje_error)
    """
    if target.id == target.guild.owner_id:
        return False, f"No puedo {action} al dueño del servidor"
    
    if bot_member.top_role <= target.top_role:
        return False, f"No puedo {action} a alguien con un rol igual o superior al mío"
    
    return True, None


# ========== Parseo de tiempo ==========

TIME_UNITS = {
    's': 1,
    'm': 60,
    'h': 3600,
    'd': 86400,
    'w': 604800,
}


def parse_time(time_string: str) -> Optional[int]:
    """
    Parsear string de tiempo a segundos
    Ejemplos: 1h, 30m, 1d, 1w, 1h30m
    """
    time_string = time_string.lower().strip()
    
    if time_string.isdigit():
        return int(time_string) * 60  # Default a minutos
    
    total_seconds = 0
    pattern = re.compile(r'(\d+)([smhdw])')
    matches = pattern.findall(time_string)
    
    if not matches:
        return None
    
    for value, unit in matches:
        total_seconds += int(value) * TIME_UNITS[unit]
    
    return total_seconds if total_seconds > 0 else None


def format_time(seconds: int) -> str:
    """Formatear segundos a string legible"""
    if seconds < 60:
        return f"{seconds} segundo{'s' if seconds != 1 else ''}"
    
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    weeks, days = divmod(days, 7)
    
    parts = []
    if weeks:
        parts.append(f"{weeks} semana{'s' if weeks != 1 else ''}")
    if days:
        parts.append(f"{days} día{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hora{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minuto{'s' if minutes != 1 else ''}")
    if secs and not weeks and not days:
        parts.append(f"{secs} segundo{'s' if secs != 1 else ''}")
    
    return ", ".join(parts[:2]) if parts else "0 segundos"


# ========== JSON Embed Parser ==========

def parse_embed_json(data: dict) -> discord.Embed:
    """Parsear diccionario JSON a discord.Embed"""
    embed = discord.Embed()
    
    if "title" in data:
        embed.title = data["title"]
    if "description" in data:
        embed.description = data["description"]
    if "color" in data:
        color = data["color"]
        if isinstance(color, str):
            color = int(color.lstrip("#"), 16)
        embed.color = color
    if "url" in data:
        embed.url = data["url"]
    if "timestamp" in data:
        embed.timestamp = datetime.fromisoformat(data["timestamp"])
    
    if "author" in data:
        author = data["author"]
        embed.set_author(
            name=author.get("name", ""),
            url=author.get("url"),
            icon_url=author.get("icon_url")
        )
    
    if "footer" in data:
        footer = data["footer"]
        embed.set_footer(
            text=footer.get("text", ""),
            icon_url=footer.get("icon_url")
        )
    
    if "thumbnail" in data:
        embed.set_thumbnail(url=data["thumbnail"]["url"])
    
    if "image" in data:
        embed.set_image(url=data["image"]["url"])
    
    if "fields" in data:
        for field in data["fields"]:
            embed.add_field(
                name=field.get("name", ""),
                value=field.get("value", ""),
                inline=field.get("inline", True)
            )
    
    return embed


# ========== Utilidades de Discord ==========

async def safe_send(
    destination: Union[discord.TextChannel, discord.Member, discord.User],
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    **kwargs
) -> Optional[discord.Message]:
    """Enviar mensaje de forma segura, manejando excepciones"""
    try:
        return await destination.send(content=content, embed=embed, **kwargs)
    except (discord.Forbidden, discord.HTTPException):
        return None


async def safe_delete(message: discord.Message) -> bool:
    """Eliminar mensaje de forma segura"""
    try:
        await message.delete()
        return True
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return False


def get_guild_icon(guild: discord.Guild) -> Optional[str]:
    """Obtener URL del icono del servidor de forma segura"""
    return str(guild.icon.url) if guild.icon else None
