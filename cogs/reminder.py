"""
Cog Reminder - Sistema de recordatorios
"""

from __future__ import annotations

import discord
from discord.ext import commands, tasks
from typing import Optional
from datetime import timedelta
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


class Reminder(commands.Cog):
    """⏰ Sistema de Recordatorios"""
    
    emoji = "⏰"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_reminders.start()
    
    def cog_unload(self):
        self.check_reminders.cancel()
    
    @tasks.loop(seconds=30)
    async def check_reminders(self):
        """Verificar y enviar recordatorios pendientes"""
        now = discord.utils.utcnow()
        
        cursor = database.reminders.find({
            "remind_at": {"$lte": now},
            "sent": False
        })
        
        async for reminder in cursor:
            try:
                user = self.bot.get_user(reminder["user_id"])
                if not user:
                    user = await self.bot.fetch_user(reminder["user_id"])
                
                if user:
                    embed = discord.Embed(
                        title="⏰ Recordatorio",
                        description=reminder["message"],
                        color=config.BLURPLE_COLOR,
                        timestamp=reminder["created_at"]
                    )
                    
                    if reminder.get("jump_url"):
                        embed.add_field(
                            name="Mensaje Original",
                            value=f"[Ir al mensaje]({reminder['jump_url']})",
                            inline=False
                        )
                    
                    embed.set_footer(text="Recordatorio creado")
                    
                    try:
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        # Intentar en el canal original
                        if reminder.get("channel_id"):
                            channel = self.bot.get_channel(reminder["channel_id"])
                            if channel:
                                await channel.send(f"{user.mention}", embed=embed)
            except Exception as e:
                print(f"Error enviando recordatorio: {e}")
            
            # Marcar como enviado
            await database.reminders.update_one(
                {"_id": reminder["_id"]},
                {"$set": {"sent": True}}
            )
    
    @check_reminders.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()
    
    @commands.group(
        name="reminder",
        aliases=["remind", "rm"],
        brief="Sistema de recordatorios",
        invoke_without_command=True
    )
    async def reminder(self, ctx: commands.Context, time: str, *, message: str):
        """Crear un recordatorio
        
        Ejemplos:
        - !remind 1h Revisar el código
        - !remind 30m Reunión en Discord
        - !remind 1d 2h Evento especial
        """
        duration = parse_time(time)
        
        if not duration:
            return await ctx.send(embed=error_embed(
                f"Formato de tiempo inválido\n"
                f"Ejemplos: `1h`, `30m`, `1d`, `1w`, `2h30m`"
            ))
        
        if duration.total_seconds() < 60:
            return await ctx.send(embed=error_embed(
                "El recordatorio debe ser de al menos 1 minuto"
            ))
        
        if duration.total_seconds() > 31536000:  # 1 año
            return await ctx.send(embed=error_embed(
                "El recordatorio no puede ser mayor a 1 año"
            ))
        
        # Verificar límite de recordatorios activos
        active_count = await database.reminders.count_documents({
            "user_id": ctx.author.id,
            "sent": False
        })
        
        if active_count >= 25:
            return await ctx.send(embed=error_embed(
                "Tienes demasiados recordatorios activos (máx 25)"
            ))
        
        remind_at = discord.utils.utcnow() + duration
        
        await database.reminders.insert_one({
            "user_id": ctx.author.id,
            "guild_id": ctx.guild.id if ctx.guild else None,
            "channel_id": ctx.channel.id,
            "message": message,
            "created_at": discord.utils.utcnow(),
            "remind_at": remind_at,
            "jump_url": ctx.message.jump_url,
            "sent": False
        })
        
        # Formatear tiempo legible
        time_text = f"<t:{int(remind_at.timestamp())}:R>"
        
        await ctx.send(embed=success_embed(
            f"⏰ Te recordaré {time_text}\n\n"
            f"**Mensaje:** {message[:200]}"
        ))
    
    @reminder.command(name="list", aliases=["ls", "all"])
    async def reminder_list(self, ctx: commands.Context):
        """Ver tus recordatorios activos"""
        reminders = await database.reminders.find({
            "user_id": ctx.author.id,
            "sent": False
        }).sort("remind_at", 1).to_list(length=10)
        
        if not reminders:
            return await ctx.send(embed=warning_embed("No tienes recordatorios activos"))
        
        embed = discord.Embed(
            title="⏰ Tus Recordatorios",
            color=config.BLURPLE_COLOR
        )
        
        for i, reminder in enumerate(reminders, 1):
            message = reminder["message"]
            if len(message) > 50:
                message = message[:50] + "..."
            
            time_text = f"<t:{int(reminder['remind_at'].timestamp())}:R>"
            
            embed.add_field(
                name=f"`{i}.` {time_text}",
                value=message,
                inline=False
            )
        
        total = await database.reminders.count_documents({
            "user_id": ctx.author.id,
            "sent": False
        })
        
        if total > 10:
            embed.set_footer(text=f"Mostrando 10 de {total} recordatorios")
        
        await ctx.send(embed=embed)
    
    @reminder.command(name="delete", aliases=["del", "remove", "cancel"])
    async def reminder_delete(self, ctx: commands.Context, index: int):
        """Eliminar un recordatorio por su número en la lista"""
        reminders = await database.reminders.find({
            "user_id": ctx.author.id,
            "sent": False
        }).sort("remind_at", 1).to_list(length=None)
        
        if not reminders:
            return await ctx.send(embed=warning_embed("No tienes recordatorios activos"))
        
        if index < 1 or index > len(reminders):
            return await ctx.send(embed=error_embed(
                f"Índice inválido. Usa `{ctx.prefix}reminder list` para ver tus recordatorios"
            ))
        
        reminder = reminders[index - 1]
        
        await database.reminders.delete_one({"_id": reminder["_id"]})
        
        await ctx.send(embed=success_embed(
            f"Recordatorio eliminado:\n*{reminder['message'][:100]}*"
        ))
    
    @reminder.command(name="clear")
    async def reminder_clear(self, ctx: commands.Context):
        """Eliminar todos tus recordatorios"""
        result = await database.reminders.delete_many({
            "user_id": ctx.author.id,
            "sent": False
        })
        
        if result.deleted_count == 0:
            return await ctx.send(embed=warning_embed("No tienes recordatorios activos"))
        
        await ctx.send(embed=success_embed(
            f"**{result.deleted_count}** recordatorio(s) eliminado(s)"
        ))
    
    # Comando simplificado
    @commands.command(
        name="remindme",
        aliases=["recordar"],
        brief="Crear un recordatorio rápido"
    )
    async def remindme_shortcut(self, ctx: commands.Context, time: str, *, message: str):
        """Alias para crear recordatorios rápidamente"""
        await self.reminder(ctx, time, message=message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reminder(bot))
