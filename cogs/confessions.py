"""
Cog Confessions - Sistema de confesiones anónimas
"""

from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional, Dict
from datetime import datetime

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed


class ConfessionModal(discord.ui.Modal, title="Nueva Confesión"):
    """Modal para enviar confesiones"""
    
    confession_text = discord.ui.TextInput(
        label="Tu Confesión",
        style=discord.TextStyle.paragraph,
        placeholder="Escribe tu confesión aquí... será completamente anónima",
        min_length=10,
        max_length=2000,
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Obtener configuración
        settings = await database.confession_settings.find_one({
            "guild_id": interaction.guild.id
        })
        
        if not settings or not settings.get("channel_id"):
            return await interaction.followup.send(
                "❌ El sistema de confesiones no está configurado.",
                ephemeral=True
            )
        
        channel = interaction.guild.get_channel(settings["channel_id"])
        if not channel:
            return await interaction.followup.send(
                "❌ El canal de confesiones no existe.",
                ephemeral=True
            )
        
        # Obtener número de confesión
        count = await database.confessions.count_documents({
            "guild_id": interaction.guild.id
        })
        confession_number = count + 1
        
        # Crear embed
        embed = discord.Embed(
            title=f"📝 Confesión #{confession_number}",
            description=self.confession_text.value,
            color=config.BLURPLE_COLOR,
            timestamp=datetime.utcnow()
        )
        
        embed.set_footer(text="Confesión anónima")
        
        # Enviar confesión
        msg = await channel.send(embed=embed)
        
        # Guardar en DB (sin datos del usuario para mantener anonimato)
        await database.confessions.insert_one({
            "guild_id": interaction.guild.id,
            "message_id": msg.id,
            "number": confession_number,
            "content": self.confession_text.value,
            "created_at": datetime.utcnow()
            # No guardamos user_id para mantener anonimato real
        })
        
        await interaction.followup.send(
            f"✅ Tu confesión #{confession_number} ha sido enviada anónimamente.",
            ephemeral=True
        )


class ConfessionView(discord.ui.View):
    """Vista con botón para crear confesión"""
    
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(
        label="📝 Confesar",
        style=discord.ButtonStyle.primary,
        custom_id="confession:create"
    )
    async def create_confession(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ConfessionModal()
        await interaction.response.send_modal(modal)


class Confessions(commands.Cog):
    """📝 Sistema de Confesiones"""
    
    emoji = "📝"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def cog_load(self):
        """Registrar vistas persistentes"""
        self.bot.add_view(ConfessionView())
    
    @commands.group(
        name="confessions",
        aliases=["confession", "confess"],
        brief="Sistema de confesiones anónimas",
        invoke_without_command=True
    )
    async def confessions(self, ctx: commands.Context):
        """Sistema de confesiones anónimas"""
        embed = discord.Embed(
            title="📝 Sistema de Confesiones",
            description="Permite a los usuarios enviar confesiones anónimas.",
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(
            name="Comandos",
            value=f"`{ctx.prefix}confessions setup <canal>` - Configurar sistema\n"
                  f"`{ctx.prefix}confessions panel` - Enviar panel para confesar\n"
                  f"`{ctx.prefix}confessions send` - Enviar confesión (DM)\n"
                  f"`{ctx.prefix}confessions disable` - Desactivar sistema",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @confessions.command(name="setup", aliases=["set", "channel"])
    @commands.has_permissions(administrator=True)
    async def confessions_setup(self, ctx: commands.Context, channel: discord.TextChannel):
        """Configurar canal de confesiones"""
        await database.confession_settings.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {
                    "guild_id": ctx.guild.id,
                    "channel_id": channel.id,
                    "enabled": True
                }
            },
            upsert=True
        )
        
        await ctx.send(embed=success_embed(
            f"Canal de confesiones: {channel.mention}\n\n"
            f"Usa `{ctx.prefix}confessions panel` para enviar el panel."
        ))
    
    @confessions.command(name="panel", aliases=["embed", "button"])
    @commands.has_permissions(manage_guild=True)
    async def confessions_panel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Enviar panel para crear confesiones"""
        channel = channel or ctx.channel
        
        settings = await database.confession_settings.find_one({
            "guild_id": ctx.guild.id
        })
        
        if not settings or not settings.get("channel_id"):
            return await ctx.send(embed=error_embed(
                f"Primero configura el sistema con `{ctx.prefix}confessions setup <canal>`"
            ))
        
        embed = discord.Embed(
            title="📝 Confesiones Anónimas",
            description="Haz clic en el botón para enviar una confesión anónima.\n\n"
                       "⚠️ **Reglas:**\n"
                       "• No revelar información personal de otros\n"
                       "• No contenido ilegal o extremadamente ofensivo\n"
                       "• Las confesiones son anónimas pero moderadas",
            color=config.BLURPLE_COLOR
        )
        
        embed.set_footer(text=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        
        view = ConfessionView()
        await channel.send(embed=embed, view=view)
        
        if channel != ctx.channel:
            await ctx.send(embed=success_embed(f"Panel enviado a {channel.mention}"))
    
    @confessions.command(name="send")
    async def confessions_send(self, ctx: commands.Context, *, text: Optional[str] = None):
        """Enviar una confesión directamente"""
        settings = await database.confession_settings.find_one({
            "guild_id": ctx.guild.id
        })
        
        if not settings or not settings.get("channel_id"):
            return await ctx.send(embed=error_embed("El sistema de confesiones no está configurado"))
        
        if not text:
            # Abrir modal si es slash command o enviar instrucciones
            if ctx.interaction:
                modal = ConfessionModal()
                await ctx.interaction.response.send_modal(modal)
                return
            else:
                return await ctx.send(embed=error_embed(
                    f"Uso: `{ctx.prefix}confessions send <tu confesión>`\n"
                    f"O usa el panel de confesiones."
                ))
        
        # Eliminar mensaje del usuario por privacidad
        try:
            await ctx.message.delete()
        except:
            pass
        
        channel = ctx.guild.get_channel(settings["channel_id"])
        if not channel:
            return await ctx.send(embed=error_embed("El canal de confesiones no existe"), delete_after=5)
        
        # Obtener número de confesión
        count = await database.confessions.count_documents({
            "guild_id": ctx.guild.id
        })
        confession_number = count + 1
        
        # Crear embed
        embed = discord.Embed(
            title=f"📝 Confesión #{confession_number}",
            description=text,
            color=config.BLURPLE_COLOR,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Confesión anónima")
        
        msg = await channel.send(embed=embed)
        
        # Guardar
        await database.confessions.insert_one({
            "guild_id": ctx.guild.id,
            "message_id": msg.id,
            "number": confession_number,
            "content": text,
            "created_at": datetime.utcnow()
        })
        
        # Notificar al usuario
        try:
            await ctx.author.send(embed=success_embed(
                f"Tu confesión #{confession_number} ha sido enviada anónimamente."
            ))
        except:
            pass
    
    @confessions.command(name="disable", aliases=["off"])
    @commands.has_permissions(administrator=True)
    async def confessions_disable(self, ctx: commands.Context):
        """Desactivar sistema de confesiones"""
        await database.confession_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"enabled": False, "channel_id": None}}
        )
        
        await ctx.send(embed=success_embed("Sistema de confesiones desactivado"))
    
    @confessions.command(name="stats")
    async def confessions_stats(self, ctx: commands.Context):
        """Ver estadísticas de confesiones"""
        total = await database.confessions.count_documents({
            "guild_id": ctx.guild.id
        })
        
        if total == 0:
            return await ctx.send(embed=warning_embed("No hay confesiones en este servidor"))
        
        # Última confesión
        last = await database.confessions.find_one(
            {"guild_id": ctx.guild.id},
            sort=[("number", -1)]
        )
        
        embed = discord.Embed(
            title="📊 Estadísticas de Confesiones",
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(name="Total", value=str(total), inline=True)
        embed.add_field(name="Última", value=f"#{last['number']}", inline=True)
        
        if last.get("created_at"):
            embed.add_field(
                name="Última Confesión",
                value=f"<t:{int(last['created_at'].timestamp())}:R>",
                inline=True
            )
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Confessions(bot))
