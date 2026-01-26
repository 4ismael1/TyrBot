"""
Cog Giveaway - Sistema de sorteos
"""

from __future__ import annotations

import discord
from discord.ext import commands, tasks
from typing import Optional, List
from datetime import timedelta
import random
import re
import asyncio

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
            role = interaction.guild.get_role(giveaway["required_role"])
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
            channel = interaction.guild.get_channel(giveaway["channel_id"])
            if channel:
                message = await channel.fetch_message(giveaway["message_id"])
                embed = message.embeds[0]
                
                # Actualizar campo de participantes
                for i, field in enumerate(embed.fields):
                    if "Participantes" in field.name:
                        embed.set_field_at(i, name="👥 Participantes", value=str(entries_count), inline=True)
                        break
                
                await message.edit(embed=embed)
        except:
            pass


class Giveaway(commands.Cog):
    """🎉 Sistema de Sorteos"""
    
    emoji = "🎉"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_giveaways.start()
    
    def cog_unload(self):
        self.check_giveaways.cancel()
    
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
            guild = self.bot.get_guild(giveaway["guild_id"])
            if not guild:
                return
            
            channel = guild.get_channel(giveaway["channel_id"])
            if not channel:
                return
            
            try:
                message = await channel.fetch_message(giveaway["message_id"])
            except discord.NotFound:
                return
            
            entries = giveaway["entries"]
            winners_count = giveaway["winners"]
            
            # Elegir ganadores
            winners = []
            if entries:
                winners = random.sample(entries, min(len(entries), winners_count))
            
            # Actualizar DB
            await database.giveaways.update_one(
                {"_id": giveaway["_id"]},
                {
                    "$set": {
                        "ended": True,
                        "winner_ids": winners
                    }
                }
            )
            
            # Editar mensaje original
            embed = message.embeds[0]
            embed.color = discord.Color.grayed_out()
            
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
                  f"`{ctx.prefix}giveaway end <mensaje_id>` - Terminar sorteo\n"
                  f"`{ctx.prefix}giveaway reroll <mensaje_id>` - Elegir nuevo ganador\n"
                  f"`{ctx.prefix}giveaway list` - Ver sorteos activos\n"
                  f"`{ctx.prefix}giveaway delete <mensaje_id>` - Eliminar sorteo",
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
        """
        Crear un nuevo sorteo en el canal actual.
        
        **Formato de tiempo:** 30m, 1h, 1d, 1w
        
        **Ejemplos:**
        ;giveaway start 1h 1 Nitro Classic
        ;gw start 1d 3 Rol VIP
        ;sorteo start 30m 1 100 robux
        """
        # Parsear tiempo
        duration = parse_time(time_str)
        if not duration:
            return await ctx.send(embed=error_embed(
                f"Formato de tiempo inválido\n"
                f"Ejemplos: `1h`, `30m`, `1d`, `1w`"
            ))
        
        if duration.total_seconds() < 60:
            return await ctx.send(embed=error_embed("El sorteo debe durar al menos 1 minuto"))
        
        if duration.total_seconds() > 2592000:  # 30 días
            return await ctx.send(embed=error_embed("El sorteo no puede durar más de 30 días"))
        
        if winners < 1 or winners > 20:
            return await ctx.send(embed=error_embed("El número de ganadores debe ser entre 1 y 20"))
        
        ends_at = discord.utils.utcnow() + duration
        giveaway_id = f"{ctx.guild.id}-{int(discord.utils.utcnow().timestamp())}"
        
        # Crear embed
        embed = discord.Embed(
            title="🎉 ¡SORTEO!",
            description=f"**{prize}**\n\n"
                       f"Haz clic en el botón para participar!\n",
            color=discord.Color.gold()
        )
        
        embed.add_field(name="⏰ Termina", value=f"<t:{int(ends_at.timestamp())}:R>", inline=True)
        embed.add_field(name="🏆 Ganadores", value=str(winners), inline=True)
        embed.add_field(name="👥 Participantes", value="0", inline=True)
        embed.add_field(name="🎫 Host", value=ctx.author.mention, inline=True)
        
        embed.set_footer(text=f"ID: {giveaway_id}")
        embed.timestamp = ends_at
        
        # Crear vista
        view = GiveawayView(self.bot, giveaway_id)
        
        # Enviar mensaje
        msg = await ctx.send(embed=embed, view=view)
        
        # Guardar en DB
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
        
        await ctx.message.delete(delay=1)
    
    @giveaway.command(name="end", aliases=["stop", "finish"])
    @commands.has_permissions(manage_guild=True)
    async def giveaway_end(self, ctx: commands.Context, message_id: int):
        """Terminar un sorteo antes de tiempo"""
        giveaway = await database.giveaways.find_one({
            "guild_id": ctx.guild.id,
            "message_id": message_id
        })
        
        if not giveaway:
            return await ctx.send(embed=error_embed("Sorteo no encontrado"))
        
        if giveaway["ended"]:
            return await ctx.send(embed=error_embed("Este sorteo ya terminó"))
        
        await self.end_giveaway(giveaway)
        await ctx.send(embed=success_embed("Sorteo terminado"))
    
    @giveaway.command(name="reroll", aliases=["newwinner"])
    @commands.has_permissions(manage_guild=True)
    async def giveaway_reroll(self, ctx: commands.Context, message_id: int):
        """Elegir un nuevo ganador"""
        giveaway = await database.giveaways.find_one({
            "guild_id": ctx.guild.id,
            "message_id": message_id
        })
        
        if not giveaway:
            return await ctx.send(embed=error_embed("Sorteo no encontrado"))
        
        if not giveaway["ended"]:
            return await ctx.send(embed=error_embed("El sorteo aún no ha terminado"))
        
        entries = giveaway["entries"]
        previous_winners = giveaway.get("winner_ids", [])
        
        # Excluir ganadores anteriores
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
        
        embed = discord.Embed(
            title="🎉 Sorteos Activos",
            color=config.BLURPLE_COLOR
        )
        
        for gw in giveaways:
            channel = ctx.guild.get_channel(gw["channel_id"])
            channel_text = channel.mention if channel else "Canal eliminado"
            
            embed.add_field(
                name=f"🎁 {gw['prize']}",
                value=f"Canal: {channel_text}\n"
                      f"Termina: <t:{int(gw['ends_at'].timestamp())}:R>\n"
                      f"Participantes: {len(gw['entries'])}",
                inline=True
            )
        
        await ctx.send(embed=embed)
    
    @giveaway.command(name="delete", aliases=["cancel", "remove"])
    @commands.has_permissions(manage_guild=True)
    async def giveaway_delete(self, ctx: commands.Context, message_id: int):
        """Eliminar un sorteo sin elegir ganador"""
        giveaway = await database.giveaways.find_one({
            "guild_id": ctx.guild.id,
            "message_id": message_id
        })
        
        if not giveaway:
            return await ctx.send(embed=error_embed("Sorteo no encontrado"))
        
        # Eliminar mensaje
        try:
            channel = ctx.guild.get_channel(giveaway["channel_id"])
            if channel:
                msg = await channel.fetch_message(message_id)
                await msg.delete()
        except:
            pass
        
        # Eliminar de DB
        await database.giveaways.delete_one({"_id": giveaway["_id"]})
        
        await ctx.send(embed=success_embed("Sorteo eliminado"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Giveaway(bot))
