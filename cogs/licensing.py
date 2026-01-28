"""
Licensing Cog - Sistema de licencias por servidor
"""

from __future__ import annotations

from datetime import timezone
from typing import Optional, Literal

import discord
from discord.ext import commands

from config import config
from core.licenses import license_manager
from utils import success_embed, error_embed, warning_embed, paginate


def is_owner():
    """Check para owner del bot"""
    async def predicate(ctx: commands.Context) -> bool:
        return ctx.author.id in ctx.bot.owner_ids
    return commands.check(predicate)


def _format_dt(dt) -> str:
    if not dt:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return discord.utils.format_dt(dt, "f")


class Licensing(commands.Cog):
    """🔑 Sistema de licencias para el bot"""

    emoji = "🔑"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _resolve_owner(self, guild_id: int, guild: Optional[discord.Guild] = None) -> Optional[discord.User]:
        if guild is None:
            guild = self.bot.get_guild(guild_id)
        if guild:
            if guild.owner:
                return guild.owner
            owner_id = guild.owner_id
        else:
            owner_id = None
            try:
                fetched = await self.bot.fetch_guild(guild_id)
                owner_id = fetched.owner_id
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                return None
        if not owner_id:
            return None
        try:
            return await self.bot.fetch_user(owner_id)
        except discord.HTTPException:
            return None

    async def _send_owner_notice(
        self,
        guild_id: int,
        embed: discord.Embed,
        guild: Optional[discord.Guild] = None
    ) -> None:
        owner = await self._resolve_owner(guild_id, guild)
        if not owner:
            return
        try:
            await owner.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.group(
        name="license",
        aliases=["licencia", "licence"],
        invoke_without_command=True
    )
    async def license(self, ctx: commands.Context):
        """Sistema de licencias"""
        embed = discord.Embed(
            title="🔑 Licencias",
            description=(
                f"`{ctx.clean_prefix}license redeem <key>` - Canjear licencia\n"
                f"`{ctx.clean_prefix}license status` - Estado de licencia\n"
                f"`{ctx.clean_prefix}license info <key>` - Info (owner)\n"
                f"`{ctx.clean_prefix}license generate <n>` - Generar (owner)\n"
                f"`{ctx.clean_prefix}license revoke <key>` - Revocar (owner)\n"
                f"`{ctx.clean_prefix}license list [active/unused/revoked/all]` - Listar (owner)"
            ),
            color=config.BLURPLE_COLOR
        )
        await ctx.send(embed=embed)

    @license.command(name="redeem", aliases=["canjear", "activar"])
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def license_redeem(self, ctx: commands.Context, key: str):
        """Canjear licencia para este servidor"""
        ok, status = await license_manager.redeem(key, ctx.guild.id, ctx.author.id)
        if ok and status == "already":
            return await ctx.send(embed=warning_embed("Este servidor ya tiene esta licencia activa."))
        if ok:
            await ctx.send(embed=success_embed("Licencia activada correctamente."))

            guild_name = ctx.guild.name if ctx.guild else "tu servidor"
            prefix = ctx.clean_prefix
            dm_embed = discord.Embed(
                title="Licencia activada",
                description=(
                    f"La licencia fue activada en **{guild_name}**.\n"
                    "Ya puedes usar los comandos normalmente."
                ),
                color=config.SUCCESS_COLOR
            )
            dm_embed.add_field(
                name="Recomendaciones",
                value=(
                    f"- Revisa el panel de Antinuke: `{prefix}antinuke`\n"
                    f"- Revisa el panel de Antiraid: `{prefix}antiraid`\n"
                    f"- Configura logs: `{prefix}logs`"
                ),
                inline=False
            )
            dm_embed.add_field(
                name="Whitelist",
                value="Agrega bots y roles confiables a la whitelist para evitar falsos castigos.",
                inline=False
            )
            dm_embed.add_field(
                name="Estado",
                value=f"Usa `{prefix}license status` para ver el estado de la licencia.",
                inline=False
            )
            await self._send_owner_notice(ctx.guild.id, dm_embed, guild=ctx.guild)
            return
        if status == "invalid":
            return await ctx.send(embed=error_embed("Licencia inválida."))
        if status == "revoked":
            return await ctx.send(embed=error_embed("Esta licencia fue revocada."))
        if status == "used_other":
            return await ctx.send(embed=error_embed("Esta licencia ya fue usada en otro servidor."))
        return await ctx.send(embed=error_embed("No se pudo canjear la licencia."))

    @license.command(name="status", aliases=["estado"])
    @commands.guild_only()
    async def license_status(self, ctx: commands.Context):
        """Ver estado de licencia del servidor"""
        doc = await license_manager.get_guild_license(ctx.guild.id)
        if not doc:
            return await ctx.send(embed=warning_embed(
                "Este servidor no tiene una licencia activa.\n"
                f"Usa `{ctx.clean_prefix}license redeem <key>` o contacta al desarrollador."
            ))

        embed = discord.Embed(
            title="🔑 Licencia activa",
            color=config.SUCCESS_COLOR
        )
        embed.add_field(name="Key", value=f"`{doc.get('key', 'N/A')}`", inline=False)
        embed.add_field(name="Activada", value=_format_dt(doc.get("redeemed_at")), inline=True)
        embed.add_field(name="Estado", value=doc.get("status", "active"), inline=True)
        await ctx.send(embed=embed)

    @license.command(name="generate", aliases=["gen", "crear"])
    @is_owner()
    async def license_generate(self, ctx: commands.Context, count: int = 1):
        """Generar licencias nuevas (owner)"""
        if count < 1 or count > 50:
            return await ctx.send(embed=error_embed("Cantidad inválida. Usa un número entre 1 y 50."))

        keys = await license_manager.generate_keys(count, ctx.author.id)
        lines = [f"`{k}`" for k in keys]

        embeds = []
        for i in range(0, len(lines), 10):
            chunk = lines[i:i + 10]
            embed = discord.Embed(
                title="🔑 Licencias generadas",
                description="\n".join(chunk),
                color=config.BLURPLE_COLOR
            )
            embeds.append(embed)

        await paginate(ctx, embeds)

    @license.command(name="revoke", aliases=["revocar"])
    @is_owner()
    async def license_revoke(self, ctx: commands.Context, key: str):
        """Revocar una licencia (owner)"""
        ok, doc = await license_manager.revoke(key, ctx.author.id)
        if not ok:
            return await ctx.send(embed=error_embed("Licencia no encontrada."))
        guild_id = doc.get("guild_id")
        extra = f"Guild: `{guild_id}`" if guild_id else "Guild: N/A"
        await ctx.send(embed=success_embed(f"Licencia revocada. {extra}"))

        if guild_id:
            guild = self.bot.get_guild(guild_id)
            guild_name = guild.name if guild else "tu servidor"
            dm_embed = discord.Embed(
                title="Licencia revocada",
                description=(
                    f"La licencia de **{guild_name}** fue revocada.\n"
                    "Por seguridad, los modulos de proteccion siguen activos, "
                    "pero los comandos quedan bloqueados hasta canjear una nueva licencia."
                ),
                color=config.ERROR_COLOR
            )
            dm_embed.add_field(
                name="Accion requerida",
                value="Canjea una nueva licencia para recuperar el acceso a los comandos.",
                inline=False
            )
            dm_embed.add_field(
                name="Contacto",
                value="Ismael (Discord: 4.hz)",
                inline=False
            )
            await self._send_owner_notice(guild_id, dm_embed, guild=guild)

    @license.command(name="info")
    @is_owner()
    async def license_info(self, ctx: commands.Context, key: str):
        """Ver info de una licencia (owner)"""
        doc = await license_manager.get_license(key)
        if not doc:
            return await ctx.send(embed=error_embed("Licencia no encontrada."))

        embed = discord.Embed(
            title="🔑 Info de licencia",
            color=config.BLURPLE_COLOR
        )
        embed.add_field(name="Key", value=f"`{doc.get('key')}`", inline=False)
        embed.add_field(name="Estado", value=doc.get("status", "active"), inline=True)
        embed.add_field(name="Guild", value=str(doc.get("guild_id") or "N/A"), inline=True)
        embed.add_field(name="Creada", value=_format_dt(doc.get("created_at")), inline=True)
        embed.add_field(name="Activada", value=_format_dt(doc.get("redeemed_at")), inline=True)
        embed.add_field(name="Revocada", value=_format_dt(doc.get("revoked_at")), inline=True)
        await ctx.send(embed=embed)

    @license.command(name="list", aliases=["listar"])
    @is_owner()
    async def license_list(
        self,
        ctx: commands.Context,
        status: Optional[Literal["active", "unused", "revoked", "all"]] = "active"
    ):
        """Listar licencias (owner)"""
        status = status or "active"
        filter_status = None if status == "all" else status

        docs = await license_manager.list_licenses(filter_status, limit=200)
        if not docs:
            return await ctx.send(embed=warning_embed("No hay licencias para mostrar."))

        lines = []
        for doc in docs:
            key = doc.get("key", "N/A")
            state = doc.get("status", "active")
            guild_id = doc.get("guild_id")
            if state == "active" and guild_id:
                label = f"Activo | Guild {guild_id}"
            elif state == "active":
                label = "Libre"
            else:
                label = "Revocado"
            lines.append(f"`{key}` - {label}")

        embeds = []
        for i in range(0, len(lines), 10):
            chunk = lines[i:i + 10]
            embed = discord.Embed(
                title=f"🔑 Licencias ({status})",
                description="\n".join(chunk),
                color=config.BLURPLE_COLOR
            )
            embeds.append(embed)

        await paginate(ctx, embeds)


async def setup(bot: commands.Bot):
    await bot.add_cog(Licensing(bot))
