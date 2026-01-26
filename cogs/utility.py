"""
Cog Utility - Comandos de utilidad general
"""

from __future__ import annotations

import discord
from discord.ext import commands
from datetime import datetime
import platform
import psutil
import time

from config import config
from core import database
from utils import success_embed, error_embed, paginate


class Utility(commands.Cog):
    """🔧 Comandos de utilidad e información"""
    
    emoji = "🔧"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = datetime.utcnow()
    
    @commands.hybrid_command(
        name="userinfo",
        aliases=["ui", "user", "whois"],
        brief="Información de un usuario"
    )
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        """
        Ver información detallada de un usuario.
        
        **Uso:** ;userinfo [usuario]
        """
        member = member or ctx.author
        
        # Roles (sin @everyone)
        roles = [r.mention for r in reversed(member.roles[1:])]
        roles_text = ", ".join(roles[:10]) if roles else "Ninguno"
        if len(roles) > 10:
            roles_text += f" (+{len(roles) - 10} más)"
        
        # Badges
        flags = member.public_flags
        badges = []
        if flags.staff: badges.append("👨‍💻 Staff Discord")
        if flags.partner: badges.append("🤝 Partner")
        if flags.hypesquad: badges.append("🏠 HypeSquad Events")
        if flags.hypesquad_bravery: badges.append("💜 HypeSquad Bravery")
        if flags.hypesquad_brilliance: badges.append("🧡 HypeSquad Brilliance")
        if flags.hypesquad_balance: badges.append("💚 HypeSquad Balance")
        if flags.bug_hunter: badges.append("🐛 Bug Hunter")
        if flags.bug_hunter_level_2: badges.append("🐛 Bug Hunter Lvl 2")
        if flags.early_supporter: badges.append("👑 Early Supporter")
        if flags.verified_bot_developer: badges.append("🤖 Verified Bot Dev")
        if flags.active_developer: badges.append("👨‍💻 Active Developer")
        if member.premium_since: badges.append("💎 Nitro Booster")
        
        embed = discord.Embed(
            color=member.color if member.color != discord.Color.default() else config.BLURPLE_COLOR
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Apodo", value=member.nick or "Ninguno", inline=True)
        embed.add_field(name="Bot", value="Sí" if member.bot else "No", inline=True)
        
        embed.add_field(
            name="Cuenta creada",
            value=f"{discord.utils.format_dt(member.created_at, 'D')}\n({discord.utils.format_dt(member.created_at, 'R')})",
            inline=True
        )
        embed.add_field(
            name="Se unió",
            value=f"{discord.utils.format_dt(member.joined_at, 'D')}\n({discord.utils.format_dt(member.joined_at, 'R')})",
            inline=True
        )
        
        # Posición en join order
        join_pos = sorted(ctx.guild.members, key=lambda m: m.joined_at or datetime.utcnow()).index(member) + 1
        embed.add_field(name="Posición", value=f"#{join_pos}/{ctx.guild.member_count}", inline=True)
        
        if badges:
            embed.add_field(name="Insignias", value="\n".join(badges), inline=False)
        
        embed.add_field(name=f"Roles [{len(roles)}]", value=roles_text, inline=False)
        
        if member.activities:
            activity = member.activities[0]
            if isinstance(activity, discord.Spotify):
                embed.add_field(
                    name="🎵 Spotify",
                    value=f"**{activity.title}**\npor {activity.artist}",
                    inline=False
                )
            elif isinstance(activity, discord.CustomActivity):
                if activity.name:
                    embed.add_field(name="Estado", value=activity.name, inline=False)
            elif isinstance(activity, discord.Game):
                embed.add_field(name="🎮 Jugando", value=activity.name, inline=False)
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="serverinfo",
        aliases=["si", "server", "guild"],
        brief="Información del servidor"
    )
    async def serverinfo(self, ctx: commands.Context):
        """
        Ver información detallada del servidor.
        """
        guild = ctx.guild
        
        # Contar canales
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        
        # Contar miembros
        bots = sum(1 for m in guild.members if m.bot)
        humans = guild.member_count - bots
        
        # Features
        features = [f.replace("_", " ").title() for f in guild.features]
        
        # Nivel de verificación
        verification = {
            discord.VerificationLevel.none: "Ninguno",
            discord.VerificationLevel.low: "Bajo",
            discord.VerificationLevel.medium: "Medio",
            discord.VerificationLevel.high: "Alto",
            discord.VerificationLevel.highest: "Muy Alto"
        }
        
        embed = discord.Embed(
            title=guild.name,
            color=config.BLURPLE_COLOR
        )
        
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
        if guild.banner:
            embed.set_image(url=guild.banner.url)
        
        embed.add_field(name="ID", value=guild.id, inline=True)
        embed.add_field(name="Dueño", value=guild.owner.mention if guild.owner else "Desconocido", inline=True)
        embed.add_field(
            name="Creado",
            value=f"{discord.utils.format_dt(guild.created_at, 'D')}\n({discord.utils.format_dt(guild.created_at, 'R')})",
            inline=True
        )
        
        embed.add_field(
            name=f"Miembros [{guild.member_count}]",
            value=f"👤 Humanos: {humans}\n🤖 Bots: {bots}",
            inline=True
        )
        embed.add_field(
            name=f"Canales [{text_channels + voice_channels}]",
            value=f"💬 Texto: {text_channels}\n🔊 Voz: {voice_channels}\n📁 Categorías: {categories}",
            inline=True
        )
        embed.add_field(
            name="Otros",
            value=f"👥 Roles: {len(guild.roles)}\n😀 Emojis: {len(guild.emojis)}\n🎉 Stickers: {len(guild.stickers)}",
            inline=True
        )
        
        embed.add_field(name="Nivel de verificación", value=verification.get(guild.verification_level, "Desconocido"), inline=True)
        embed.add_field(name="Boosts", value=f"Nivel {guild.premium_tier} ({guild.premium_subscription_count} boosts)", inline=True)
        
        if features:
            embed.add_field(name="Características", value=", ".join(features[:10]) if len(features) <= 10 else ", ".join(features[:10]) + "...", inline=False)
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="avatar",
        aliases=["av", "pfp"],
        brief="Ver avatar de un usuario"
    )
    async def avatar(self, ctx: commands.Context, member: discord.Member = None):
        """
        Ver el avatar de un usuario.
        
        **Uso:** ;avatar [usuario]
        """
        member = member or ctx.author
        
        embed = discord.Embed(
            title=f"Avatar de {member.display_name}",
            color=member.color if member.color != discord.Color.default() else config.BLURPLE_COLOR
        )
        embed.set_image(url=member.display_avatar.url)
        
        # Links a diferentes formatos
        avatar = member.display_avatar
        links = []
        for fmt in ["png", "jpg", "webp"]:
            links.append(f"[{fmt.upper()}]({avatar.replace(format=fmt, size=1024)})")
        if avatar.is_animated():
            links.append(f"[GIF]({avatar.replace(format='gif', size=1024)})")
        
        embed.description = " | ".join(links)
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="serveravatar",
        aliases=["sav", "serverpfp", "gavatar"],
        brief="Ver avatar de servidor de un usuario"
    )
    async def serveravatar(self, ctx: commands.Context, member: discord.Member = None):
        """
        Ver el avatar específico del servidor de un usuario.
        """
        member = member or ctx.author
        
        if not member.guild_avatar:
            return await ctx.send(embed=error_embed(f"{member.display_name} no tiene avatar de servidor"))
        
        embed = discord.Embed(
            title=f"Avatar de servidor de {member.display_name}",
            color=member.color if member.color != discord.Color.default() else config.BLURPLE_COLOR
        )
        embed.set_image(url=member.guild_avatar.url)
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="banner",
        brief="Ver banner de un usuario"
    )
    async def banner(self, ctx: commands.Context, user: discord.User = None):
        """
        Ver el banner de un usuario.
        """
        user = user or ctx.author
        
        # Necesitamos fetch para obtener el banner
        user = await self.bot.fetch_user(user.id)
        
        if not user.banner:
            return await ctx.send(embed=error_embed(f"{user.display_name} no tiene banner"))
        
        embed = discord.Embed(
            title=f"Banner de {user.display_name}",
            color=config.BLURPLE_COLOR
        )
        embed.set_image(url=user.banner.url)
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="roleinfo",
        aliases=["ri", "rinfo"],
        brief="Información de un rol"
    )
    async def roleinfo(self, ctx: commands.Context, *, role: discord.Role):
        """
        Ver información de un rol.
        """
        embed = discord.Embed(
            title=f"Rol: {role.name}",
            color=role.color if role.color != discord.Color.default() else config.BLURPLE_COLOR
        )
        
        embed.add_field(name="ID", value=role.id, inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="Posición", value=f"{role.position}/{len(ctx.guild.roles)}", inline=True)
        embed.add_field(name="Miembros", value=len(role.members), inline=True)
        embed.add_field(name="Mencionable", value="Sí" if role.mentionable else "No", inline=True)
        embed.add_field(name="Separado", value="Sí" if role.hoist else "No", inline=True)
        embed.add_field(
            name="Creado",
            value=f"{discord.utils.format_dt(role.created_at, 'D')}\n({discord.utils.format_dt(role.created_at, 'R')})",
            inline=False
        )
        
        # Permisos importantes
        perms = []
        if role.permissions.administrator: perms.append("Administrator")
        if role.permissions.manage_guild: perms.append("Manage Server")
        if role.permissions.manage_roles: perms.append("Manage Roles")
        if role.permissions.manage_channels: perms.append("Manage Channels")
        if role.permissions.kick_members: perms.append("Kick Members")
        if role.permissions.ban_members: perms.append("Ban Members")
        if role.permissions.manage_messages: perms.append("Manage Messages")
        
        if perms:
            embed.add_field(name="Permisos clave", value=", ".join(perms), inline=False)
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="botinfo",
        aliases=["bi", "about", "info"],
        brief="Información del bot"
    )
    async def botinfo(self, ctx: commands.Context):
        """
        Ver información del bot.
        """
        # Stats
        total_members = sum(g.member_count for g in self.bot.guilds)
        total_channels = sum(len(g.channels) for g in self.bot.guilds)
        
        # Uptime
        uptime = datetime.utcnow() - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        
        # Sistema
        cpu = psutil.cpu_percent()
        memory = psutil.Process().memory_info()
        mem_mb = memory.rss / 1024 / 1024
        
        embed = discord.Embed(
            title=f"{self.bot.user.name}",
            description=config.BOT_DESCRIPTION,
            color=config.BLURPLE_COLOR
        )
        
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        embed.add_field(
            name="📊 Estadísticas",
            value=f"Servidores: {len(self.bot.guilds)}\n"
                  f"Usuarios: {total_members:,}\n"
                  f"Canales: {total_channels:,}",
            inline=True
        )
        embed.add_field(
            name="⏰ Uptime",
            value=f"{days}d {hours}h {minutes}m {seconds}s",
            inline=True
        )
        embed.add_field(
            name="🖥️ Sistema",
            value=f"CPU: {cpu}%\n"
                  f"RAM: {mem_mb:.1f} MB\n"
                  f"Python: {platform.python_version()}",
            inline=True
        )
        embed.add_field(
            name="📚 Librerías",
            value=f"discord.py: {discord.__version__}",
            inline=True
        )
        embed.add_field(
            name="🔗 Links",
            value=f"[Invitar]({config.INVITE_URL}) | [Soporte]({config.SUPPORT_URL})",
            inline=True
        )
        
        embed.set_footer(text=f"Desarrollado con ❤️ | Shard: {ctx.guild.shard_id if hasattr(ctx.guild, 'shard_id') else 0}")
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="ping",
        brief="Ver la latencia del bot"
    )
    async def ping(self, ctx: commands.Context):
        """
        Ver la latencia del bot y la API.
        """
        # Latencia de WebSocket
        ws_latency = round(self.bot.latency * 1000)
        
        # Latencia de API
        start = time.perf_counter()
        msg = await ctx.send("🏓 Calculando...")
        api_latency = round((time.perf_counter() - start) * 1000)
        
        # Latencia de DB
        db_start = time.perf_counter()
        await database.prefixes.find_one({"guild_id": ctx.guild.id})
        db_latency = round((time.perf_counter() - db_start) * 1000)
        
        embed = discord.Embed(
            title="🏓 Pong!",
            color=config.SUCCESS_COLOR if ws_latency < 200 else config.WARNING_COLOR
        )
        embed.add_field(name="WebSocket", value=f"{ws_latency}ms", inline=True)
        embed.add_field(name="API", value=f"{api_latency}ms", inline=True)
        embed.add_field(name="Database", value=f"{db_latency}ms", inline=True)
        
        await msg.edit(content=None, embed=embed)
    
    @commands.hybrid_command(
        name="invite",
        aliases=["inv"],
        brief="Obtener link de invitación"
    )
    async def invite(self, ctx: commands.Context):
        """
        Obtener el link de invitación del bot.
        """
        embed = discord.Embed(
            title="🔗 Invitar Bot",
            description=f"[Click aquí para invitarme]({config.INVITE_URL})",
            color=config.BLURPLE_COLOR
        )
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="membercount",
        aliases=["members", "count"],
        brief="Ver conteo de miembros"
    )
    async def membercount(self, ctx: commands.Context):
        """
        Ver el conteo de miembros del servidor.
        """
        guild = ctx.guild
        
        total = guild.member_count
        humans = sum(1 for m in guild.members if not m.bot)
        bots = total - humans
        online = sum(1 for m in guild.members if m.status != discord.Status.offline)
        
        embed = discord.Embed(
            title=f"👥 Miembros de {guild.name}",
            color=config.BLURPLE_COLOR
        )
        embed.add_field(name="Total", value=f"{total:,}", inline=True)
        embed.add_field(name="Humanos", value=f"{humans:,}", inline=True)
        embed.add_field(name="Bots", value=f"{bots:,}", inline=True)
        embed.add_field(name="En línea", value=f"{online:,}", inline=True)
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="firstmessage",
        aliases=["firstmsg"],
        brief="Ver primer mensaje del canal"
    )
    async def firstmessage(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """
        Obtener el primer mensaje de un canal.
        """
        channel = channel or ctx.channel
        
        async for message in channel.history(limit=1, oldest_first=True):
            embed = discord.Embed(
                title=f"Primer mensaje en #{channel.name}",
                description=message.content[:2000] if message.content else "*Sin contenido*",
                color=config.BLURPLE_COLOR,
                timestamp=message.created_at
            )
            embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
            embed.add_field(name="Link", value=f"[Ir al mensaje]({message.jump_url})", inline=False)
            
            return await ctx.send(embed=embed)
        
        await ctx.send(embed=error_embed("No se encontraron mensajes"))


# Prefix commands
class PrefixManagement(commands.Cog):
    """⚙️ Gestión de prefijo"""
    
    emoji = "⚙️"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.group(
        name="prefix",
        aliases=["prefijo"],
        invoke_without_command=True
    )
    async def prefix(self, ctx: commands.Context):
        """Ver o cambiar el prefijo del servidor"""
        prefixes = await self.bot.get_prefix(ctx.message)
        
        # Filtrar menciones
        text_prefixes = [p for p in prefixes if not p.startswith("<@")]
        
        embed = discord.Embed(
            title="⚙️ Prefijos",
            description=f"Prefijo actual: `{text_prefixes[0] if text_prefixes else config.DEFAULT_PREFIX}`",
            color=config.BLURPLE_COLOR
        )
        embed.add_field(
            name="Cambiar prefijo",
            value=f"Usa `{ctx.prefix}prefix set <nuevo_prefijo>`",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @prefix.command(name="set", aliases=["cambiar"])
    @commands.has_permissions(manage_guild=True)
    async def prefix_set(self, ctx: commands.Context, *, new_prefix: str):
        """Cambiar el prefijo del servidor"""
        if len(new_prefix) > 10:
            return await ctx.send(embed=error_embed("El prefijo no puede tener más de 10 caracteres"))
        
        # Actualizar en DB
        await database.prefixes.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"prefix": new_prefix}},
            upsert=True
        )
        
        # Actualizar caché Redis
        from core import cache
        await cache.set_prefix(ctx.guild.id, new_prefix)
        
        # Actualizar caché en memoria del bot
        self.bot._prefix_cache[ctx.guild.id] = new_prefix
        
        await ctx.send(embed=success_embed(f"Prefijo cambiado a `{new_prefix}`"))
    
    @prefix.command(name="reset", aliases=["default", "resetear"])
    @commands.has_permissions(manage_guild=True)
    async def prefix_reset(self, ctx: commands.Context):
        """Restablecer el prefijo al valor por defecto"""
        await database.prefixes.delete_one({"guild_id": ctx.guild.id})
        
        from core import cache
        await cache.delete_prefix(ctx.guild.id)
        
        # Actualizar caché en memoria del bot
        self.bot._prefix_cache[ctx.guild.id] = config.DEFAULT_PREFIX
        
        await ctx.send(embed=success_embed(f"Prefijo restablecido a `{config.DEFAULT_PREFIX}`"))


class LastSeenCog(commands.Cog):
    """⏰ Tracking de última actividad"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.hybrid_command(
        name="lastseen",
        aliases=["seen", "ls"],
        brief="Ver última actividad de un usuario"
    )
    async def lastseen(self, ctx: commands.Context, member: discord.Member = None):
        """
        Ver cuándo fue la última vez que un usuario envió un mensaje.
        
        **Uso:** ;lastseen [usuario]
        """
        member = member or ctx.author
        
        from core import cache
        data = await cache.get_last_seen(member.id)
        
        if not data:
            return await ctx.send(embed=error_embed(f"No tengo registros de actividad de {member.display_name}"))
        
        # Parsear timestamp
        from datetime import datetime
        timestamp = datetime.fromisoformat(data["timestamp"])
        
        # Obtener servidor si es posible
        guild_info = ""
        if data.get("guild_id"):
            guild = self.bot.get_guild(data["guild_id"])
            if guild:
                guild_info = f"\n📍 **Servidor:** {guild.name}"
        
        embed = discord.Embed(
            title=f"⏰ Última actividad de {member.display_name}",
            description=f"**Visto:** {discord.utils.format_dt(timestamp, 'F')}\n"
                       f"({discord.utils.format_dt(timestamp, 'R')}){guild_info}",
            color=config.BLURPLE_COLOR
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Utility(bot))
    await bot.add_cog(PrefixManagement(bot))
    await bot.add_cog(LastSeenCog(bot))
