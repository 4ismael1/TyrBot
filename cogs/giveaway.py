"""
Cog Giveaway - Sistema de sorteos
"""

from __future__ import annotations

import discord
from discord.ext import commands, tasks
from typing import Optional, Dict, Any
from datetime import timedelta
import random
import re

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed


def parse_time(time_str: str) -> Optional[timedelta]:
    """Parsear string de tiempo a timedelta"""
    time_regex = re.compile(r"(\d+)\s*([smhdwSMHDW])")
    matches = time_regex.findall(time_str)

    if not matches:
        return None

    total_seconds = 0
    for value, unit in matches:
        value = int(value)
        unit = unit.lower()

        if unit == "s":
            total_seconds += value
        elif unit == "m":
            total_seconds += value * 60
        elif unit == "h":
            total_seconds += value * 3600
        elif unit == "d":
            total_seconds += value * 86400
        elif unit == "w":
            total_seconds += value * 604800

    return timedelta(seconds=total_seconds)


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _within_int64(n: int) -> bool:
    # Mongo int64 signed range
    return -(2**63) <= n <= (2**63 - 1)


def parse_giveaway_ref(ref: str) -> Optional[Dict[str, str]]:
    """
    Acepta:
    - message_id (solo números)
    - link de mensaje: https://discord.com/channels/guild/channel/message
    - giveaway_id del embed: "<guild_id>-<timestamp>"
    """
    if not ref:
        return None

    ref = ref.strip()

    # Mensaje link
    m = re.search(
        r"(?:discord(?:app)?\.com/channels|ptb\.discord\.com/channels|canary\.discord\.com/channels)/(\d+)/(\d+)/(\d+)",
        ref
    )
    if m:
        return {"message_id": m.group(3)}

    # Limpieza básica por si viene entre < >
    ref_clean = ref.strip("<> ").strip()

    # giveaway_id del embed: guildid-timestamp
    if re.fullmatch(r"\d+-\d+", ref_clean):
        return {"giveaway_id": ref_clean}

    # message_id numérico
    if ref_clean.isdigit():
        return {"message_id": ref_clean}

    return None


class GiveawayView(discord.ui.View):
    """Vista para participar en sorteos"""

    def __init__(self, bot: commands.Bot, giveaway_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.giveaway_id = giveaway_id

    @discord.ui.button(
        label="🎉 Participar",
        style=discord.ButtonStyle.green,
        custom_id="giveaway:enter"
    )
    async def enter_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Botón para entrar al sorteo"""
        giveaway = await database.giveaways.find_one({"_id": self.giveaway_id})

        if not giveaway:
            return await interaction.response.send_message(
                "Este sorteo ya no existe.",
                ephemeral=True
            )

        if giveaway["ended"]:
            return await interaction.response.send_message(
                "Este sorteo ya terminó.",
                ephemeral=True
            )

        user_id = interaction.user.id

        # Verificar requisito de rol
        if giveaway.get("required_role"):
            req_role_id = _to_int(giveaway["required_role"])
            role = interaction.guild.get_role(req_role_id) if req_role_id else None
            if role and role not in interaction.user.roles:
                return await interaction.response.send_message(
                    f"Necesitas el rol {role.mention} para participar.",
                    ephemeral=True
                )

        # Verificar si ya está participando
        if user_id in giveaway["entries"]:
            # Quitar participación
            await database.giveaways.update_one(
                {"_id": self.giveaway_id},
                {"$pull": {"entries": user_id}}
            )
            return await interaction.response.send_message(
                "❌ Ya no participas en el sorteo.",
                ephemeral=True
            )

        # Agregar participación
        await database.giveaways.update_one(
            {"_id": self.giveaway_id},
            {"$push": {"entries": user_id}}
        )

        await interaction.response.send_message(
            "✅ ¡Estás participando en el sorteo!",
            ephemeral=True
        )

        # Actualizar contador en el embed
        giveaway = await database.giveaways.find_one({"_id": self.giveaway_id})
        entries_count = len(giveaway["entries"])

        try:
            channel_id = _to_int(giveaway.get("channel_id"))
            message_id = _to_int(giveaway.get("message_id"))
            if not channel_id or not message_id:
                return

            channel = interaction.guild.get_channel(channel_id)
            if channel:
                message = await channel.fetch_message(message_id)
                if not message.embeds:
                    return
                embed = message.embeds[0]

                # Actualizar campo de participantes
                for i, field in enumerate(embed.fields):
                    if "Participantes" in field.name:
                        embed.set_field_at(i, name="👥 Participantes", value=str(entries_count), inline=True)
                        break

                await message.edit(embed=embed)
        except Exception:
            pass


class Giveaway(commands.Cog):
    """🎉 Sistema de Sorteos"""

    emoji = "🎉"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    async def _find_giveaway_by_ref(self, guild_id: int, ref: str) -> Optional[dict]:
        """
        Busca giveaway por:
        - _id (giveaway_id del embed: guildid-timestamp)
        - message_id (numérico o link)
        Evita OverflowError de Mongo si el int excede int64.
        """
        parsed = parse_giveaway_ref(ref)
        if not parsed:
            return None

        # Por giveaway_id del embed
        if "giveaway_id" in parsed:
            return await database.giveaways.find_one({
                "_id": parsed["giveaway_id"],
                "guild_id": guild_id
            })

        # Por message_id
        mid_str = parsed["message_id"]
        ors = [{"message_id": mid_str}]

        mid_int = _to_int(mid_str)
        if mid_int is not None and _within_int64(mid_int):
            ors.append({"message_id": mid_int})

        return await database.giveaways.find_one({
            "guild_id": guild_id,
            "$or": ors
        })

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        """Verificar sorteos que deben terminar"""
        now = discord.utils.utcnow()

        cursor = database.giveaways.find({
            "ended": False,
            "ends_at": {"$lte": now}
        })

        async for giveaway in cursor:
            await self.end_giveaway(giveaway)

    @check_giveaways.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def end_giveaway(self, giveaway: dict):
        """Terminar un sorteo y elegir ganadores"""
        try:
            guild = self.bot.get_guild(_to_int(giveaway.get("guild_id")) or 0)
            if not guild:
                return

            channel_id = _to_int(giveaway.get("channel_id"))
            if not channel_id:
                return
            channel = guild.get_channel(channel_id)
            if not channel:
                return

            message_id = _to_int(giveaway.get("message_id"))
            if not message_id:
                return

            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                return

            entries = giveaway.get("entries", [])
            winners_count = int(giveaway.get("winners", 1))

            # Elegir ganadores
            winners = []
            if entries:
                winners = random.sample(entries, min(len(entries), winners_count))

            # Actualizar DB
            await database.giveaways.update_one(
                {"_id": giveaway["_id"]},
                {"$set": {"ended": True, "winner_ids": winners}}
            )

            # Editar mensaje original
            if not message.embeds:
                return
            embed = message.embeds[0]

            # PARCHE: grayed_out() no existe en tu librería
            embed.color = discord.Color.dark_grey()

            if winners:
                winners_mention = ", ".join([f"<@{w}>" for w in winners])
                embed.description = f"**Ganador(es):** {winners_mention}"
            else:
                embed.description = "No hubo participantes suficientes."

            embed.set_footer(text="Sorteo terminado")
            embed.timestamp = discord.utils.utcnow()

            # Quitar botón
            await message.edit(embed=embed, view=None)

            # Anunciar ganadores
            if winners:
                winners_mention = ", ".join([f"<@{w}>" for w in winners])
                await channel.send(
                    f"🎉 ¡Felicidades {winners_mention}!\n"
                    f"Ganaste **{giveaway['prize']}**!"
                )
            else:
                await channel.send(
                    f"😔 El sorteo de **{giveaway['prize']}** terminó sin participantes."
                )

        except Exception as e:
            print(f"Error al terminar sorteo: {e}")

    @commands.group(
        name="giveaway",
        aliases=["gw", "sorteo"],
        brief="Sistema de sorteos",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_guild=True)
    async def giveaway(self, ctx: commands.Context):
        """Sistema de sorteos"""
        embed = discord.Embed(
            title="🎉 Sistema de Sorteos",
            description="Crea y gestiona sorteos en tu servidor.",
            color=config.BLURPLE_COLOR
        )

        embed.add_field(
            name="Comandos",
            value=f"`{ctx.prefix}giveaway start <tiempo> <ganadores> <premio>` - Crear sorteo\n"
                  f"`{ctx.prefix}giveaway end <mensaje_id|link|id_embed>` - Terminar sorteo\n"
                  f"`{ctx.prefix}giveaway reroll <mensaje_id|link|id_embed>` - Elegir nuevo ganador\n"
                  f"`{ctx.prefix}giveaway list` - Ver sorteos activos\n"
                  f"`{ctx.prefix}giveaway delete <mensaje_id|link|id_embed>` - Eliminar sorteo",
            inline=False
        )

        embed.add_field(
            name="Formato de Tiempo",
            value="`1h` = 1 hora\n`30m` = 30 minutos\n`1d` = 1 día\n`1w` = 1 semana",
            inline=False
        )

        embed.add_field(
            name="Ejemplo",
            value=f"`{ctx.prefix}giveaway start 1d 1 Nitro Classic`",
            inline=False
        )

        await ctx.send(embed=embed)

    @giveaway.command(name="start", aliases=["create", "new"])
    @commands.has_permissions(manage_guild=True)
    async def giveaway_start(
        self,
        ctx: commands.Context,
        time_str: str,
        winners: int,
        *,
        prize: str
    ):
        """Crear un nuevo sorteo en el canal actual."""
        duration = parse_time(time_str)
        if not duration:
            return await ctx.send(embed=error_embed(
                "Formato de tiempo inválido\nEjemplos: `1h`, `30m`, `1d`, `1w`"
            ))

        if duration.total_seconds() < 60:
            return await ctx.send(embed=error_embed("El sorteo debe durar al menos 1 minuto"))

        if duration.total_seconds() > 2592000:  # 30 días
            return await ctx.send(embed=error_embed("El sorteo no puede durar más de 30 días"))

        if winners < 1 or winners > 20:
            return await ctx.send(embed=error_embed("El número de ganadores debe ser entre 1 y 20"))

        ends_at = discord.utils.utcnow() + duration
        giveaway_id = f"{ctx.guild.id}-{int(discord.utils.utcnow().timestamp())}"

        embed = discord.Embed(
            title="🎉 ¡SORTEO!",
            description=f"**{prize}**\n\nHaz clic en el botón para participar!\n",
            color=discord.Color.gold()
        )
        embed.add_field(name="⏰ Termina", value=f"<t:{int(ends_at.timestamp())}:R>", inline=True)
        embed.add_field(name="🏆 Ganadores", value=str(winners), inline=True)
        embed.add_field(name="👥 Participantes", value="0", inline=True)
        embed.add_field(name="🎫 Host", value=ctx.author.mention, inline=True)
        embed.set_footer(text=f"ID: {giveaway_id}")
        embed.timestamp = ends_at

        view = GiveawayView(self.bot, giveaway_id)
        msg = await ctx.send(embed=embed, view=view)

        await database.giveaways.insert_one({
            "_id": giveaway_id,
            "guild_id": ctx.guild.id,
            "channel_id": ctx.channel.id,
            "message_id": msg.id,
            "host_id": ctx.author.id,
            "prize": prize,
            "winners": winners,
            "entries": [],
            "winner_ids": [],
            "ends_at": ends_at,
            "ended": False,
            "required_role": None
        })

        try:
            await ctx.message.delete(delay=1)
        except Exception:
            pass

    @giveaway.command(name="end", aliases=["stop", "finish"])
    @commands.has_permissions(manage_guild=True)
    async def giveaway_end(self, ctx: commands.Context, ref: str):
        """Terminar un sorteo antes de tiempo (acepta message_id, link o ID del embed)"""
        giveaway = await self._find_giveaway_by_ref(ctx.guild.id, ref)
        if not giveaway:
            return await ctx.send(embed=error_embed(
                "Sorteo no encontrado.\nUsa el **ID del mensaje**, el **link del mensaje** o el **ID del embed**."
            ))

        if giveaway.get("ended"):
            return await ctx.send(embed=error_embed("Este sorteo ya terminó"))

        await self.end_giveaway(giveaway)
        await ctx.send(embed=success_embed("Sorteo terminado"))

    @giveaway.command(name="reroll", aliases=["newwinner"])
    @commands.has_permissions(manage_guild=True)
    async def giveaway_reroll(self, ctx: commands.Context, ref: str):
        """Elegir un nuevo ganador (acepta message_id, link o ID del embed)"""
        giveaway = await self._find_giveaway_by_ref(ctx.guild.id, ref)
        if not giveaway:
            return await ctx.send(embed=error_embed(
                "Sorteo no encontrado.\nUsa el **ID del mensaje**, el **link del mensaje** o el **ID del embed**."
            ))

        if not giveaway.get("ended"):
            return await ctx.send(embed=error_embed("El sorteo aún no ha terminado"))

        entries = giveaway.get("entries", [])
        previous_winners = giveaway.get("winner_ids", [])
        available = [e for e in entries if e not in previous_winners]

        if not available:
            return await ctx.send(embed=error_embed("No hay más participantes disponibles"))

        new_winner = random.choice(available)
        await ctx.send(f"🎉 ¡El nuevo ganador es <@{new_winner}>!")

    @giveaway.command(name="list", aliases=["active", "ls"])
    @commands.has_permissions(manage_guild=True)
    async def giveaway_list(self, ctx: commands.Context):
        """Ver sorteos activos"""
        giveaways = await database.giveaways.find({
            "guild_id": ctx.guild.id,
            "ended": False
        }).to_list(length=10)

        if not giveaways:
            return await ctx.send(embed=warning_embed("No hay sorteos activos"))

        embed = discord.Embed(title="🎉 Sorteos Activos", color=config.BLURPLE_COLOR)

        for gw in giveaways:
            channel_id = _to_int(gw.get("channel_id"))
            channel = ctx.guild.get_channel(channel_id) if channel_id else None
            channel_text = channel.mention if channel else "Canal eliminado"

            ends_at = gw.get("ends_at")
            ends_ts = int(ends_at.timestamp()) if ends_at else 0

            embed.add_field(
                name=f"🎁 {gw.get('prize', 'Premio')}",
                value=f"Canal: {channel_text}\n"
                      f"Termina: <t:{ends_ts}:R>\n"
                      f"Participantes: {len(gw.get('entries', []))}",
                inline=True
            )

        await ctx.send(embed=embed)

    @giveaway.command(name="delete", aliases=["cancel", "remove"])
    @commands.has_permissions(manage_guild=True)
    async def giveaway_delete(self, ctx: commands.Context, ref: str):
        """Eliminar un sorteo sin elegir ganador (acepta message_id, link o ID del embed)"""
        giveaway = await self._find_giveaway_by_ref(ctx.guild.id, ref)
        if not giveaway:
            return await ctx.send(embed=error_embed(
                "Sorteo no encontrado.\nUsa el **ID del mensaje**, el **link del mensaje** o el **ID del embed**."
            ))

        try:
            channel_id = _to_int(giveaway.get("channel_id"))
            message_id = _to_int(giveaway.get("message_id"))
            if channel_id and message_id:
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                    msg = await channel.fetch_message(message_id)
                    await msg.delete()
        except Exception:
            pass

        await database.giveaways.delete_one({"_id": giveaway["_id"]})
        await ctx.send(embed=success_embed("Sorteo eliminado"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Giveaway(bot))
