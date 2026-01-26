"""
Cog Verification - Sistema de verificación de usuarios
"""

from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional, Dict
from datetime import datetime
import random
import string

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed


class CaptchaModal(discord.ui.Modal, title="Verificación"):
    """Modal para resolver captcha"""
    
    def __init__(self, code: str):
        super().__init__()
        self.correct_code = code
        
        self.code = discord.ui.TextInput(
            label=f"Escribe el código: {code}",
            placeholder="Escribe el código exactamente como lo ves",
            min_length=len(code),
            max_length=len(code),
            required=True
        )
        self.add_item(self.code)
    
    async def on_submit(self, interaction: discord.Interaction):
        if self.code.value.upper() == self.correct_code:
            # Verificación exitosa
            settings = await database.verification_settings.find_one({
                "guild_id": interaction.guild.id
            })
            
            if settings and settings.get("verified_role"):
                role = interaction.guild.get_role(settings["verified_role"])
                if role:
                    try:
                        await interaction.user.add_roles(role, reason="Verificación completada")
                    except discord.HTTPException:
                        pass
            
            # Quitar rol de no verificado si existe
            if settings and settings.get("unverified_role"):
                unv_role = interaction.guild.get_role(settings["unverified_role"])
                if unv_role and unv_role in interaction.user.roles:
                    try:
                        await interaction.user.remove_roles(unv_role, reason="Verificación completada")
                    except:
                        pass
            
            await interaction.response.send_message(
                "✅ ¡Verificación completada! Bienvenido al servidor.",
                ephemeral=True
            )
            
            # Log de verificación
            if settings and settings.get("log_channel"):
                log_channel = interaction.guild.get_channel(settings["log_channel"])
                if log_channel:
                    embed = discord.Embed(
                        title="✅ Usuario Verificado",
                        description=f"{interaction.user.mention} ({interaction.user}) completó la verificación",
                        color=discord.Color.green(),
                        timestamp=datetime.utcnow()
                    )
                    embed.set_thumbnail(url=interaction.user.display_avatar.url)
                    await log_channel.send(embed=embed)
        else:
            await interaction.response.send_message(
                "❌ Código incorrecto. Inténtalo de nuevo.",
                ephemeral=True
            )


class VerificationView(discord.ui.View):
    """Vista para iniciar verificación"""
    
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
    
    def generate_code(self) -> str:
        """Generar código alfanumérico"""
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    
    @discord.ui.button(
        label="✅ Verificarme",
        style=discord.ButtonStyle.success,
        custom_id="verify:start"
    )
    async def start_verification(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Iniciar proceso de verificación"""
        settings = await database.verification_settings.find_one({
            "guild_id": interaction.guild.id
        })
        
        if not settings:
            return await interaction.response.send_message(
                "❌ El sistema de verificación no está configurado.",
                ephemeral=True
            )
        
        # Verificar si ya está verificado
        if settings.get("verified_role"):
            verified_role = interaction.guild.get_role(settings["verified_role"])
            if verified_role and verified_role in interaction.user.roles:
                return await interaction.response.send_message(
                    "✅ Ya estás verificado.",
                    ephemeral=True
                )
        
        verify_type = settings.get("type", "button")
        
        if verify_type == "button":
            # Verificación simple con botón
            if settings.get("verified_role"):
                role = interaction.guild.get_role(settings["verified_role"])
                if role:
                    await interaction.user.add_roles(role, reason="Verificación por botón")
            
            # Quitar rol de no verificado
            if settings.get("unverified_role"):
                unv_role = interaction.guild.get_role(settings["unverified_role"])
                if unv_role:
                    await interaction.user.remove_roles(unv_role, reason="Verificación completada")
            
            await interaction.response.send_message(
                "✅ ¡Verificado! Bienvenido al servidor.",
                ephemeral=True
            )
        
        elif verify_type == "captcha":
            # Verificación con captcha
            code = self.generate_code()
            modal = CaptchaModal(code)
            await interaction.response.send_modal(modal)


class Verification(commands.Cog):
    """✅ Sistema de Verificación"""
    
    emoji = "✅"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def cog_load(self):
        """Registrar vistas persistentes"""
        self.bot.add_view(VerificationView(self.bot))
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Dar rol de no verificado al unirse"""
        settings = await database.verification_settings.find_one({
            "guild_id": member.guild.id
        })
        
        if not settings or not settings.get("enabled"):
            return
        
        # Dar rol de no verificado
        if settings.get("unverified_role"):
            role = member.guild.get_role(settings["unverified_role"])
            if role:
                try:
                    await member.add_roles(role, reason="Nuevo miembro - pendiente verificación")
                except:
                    pass
    
    @commands.group(
        name="verification",
        aliases=["verify", "verificacion"],
        brief="Sistema de verificación",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_guild=True)
    async def verification(self, ctx: commands.Context):
        """Sistema de verificación de usuarios"""
        embed = discord.Embed(
            title="✅ Sistema de Verificación",
            description="Protege tu servidor requiriendo verificación a nuevos miembros.",
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(
            name="Comandos",
            value=f"`{ctx.prefix}verification setup <tipo>` - Configurar (button/captcha)\n"
                  f"`{ctx.prefix}verification role <rol>` - Rol de verificado\n"
                  f"`{ctx.prefix}verification unverified <rol>` - Rol de no verificado\n"
                  f"`{ctx.prefix}verification panel [canal]` - Enviar panel\n"
                  f"`{ctx.prefix}verification log <canal>` - Canal de logs\n"
                  f"`{ctx.prefix}verification disable` - Desactivar\n"
                  f"`{ctx.prefix}verification settings` - Ver configuración",
            inline=False
        )
        
        embed.add_field(
            name="Tipos de Verificación",
            value="• `button` - Solo click en botón (básico)\n"
                  "• `captcha` - Resolver código captcha (más seguro)",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @verification.command(name="setup")
    @commands.has_permissions(administrator=True)
    async def verify_setup(self, ctx: commands.Context, verify_type: str = "button"):
        """Configurar sistema de verificación"""
        verify_type = verify_type.lower()
        
        if verify_type not in ["button", "captcha"]:
            return await ctx.send(embed=error_embed(
                "Tipo inválido. Usa `button` o `captcha`"
            ))
        
        await database.verification_settings.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {
                    "guild_id": ctx.guild.id,
                    "enabled": True,
                    "type": verify_type
                }
            },
            upsert=True
        )
        
        await ctx.send(embed=success_embed(
            f"Sistema de verificación configurado: **{verify_type}**\n\n"
            f"Usa `{ctx.prefix}verification role <rol>` para establecer el rol de verificado."
        ))
    
    @verification.command(name="role", aliases=["verifiedrole"])
    @commands.has_permissions(administrator=True)
    async def verify_role(self, ctx: commands.Context, role: discord.Role):
        """Establecer rol de verificado"""
        await database.verification_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"verified_role": role.id}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(f"Rol de verificado: {role.mention}"))
    
    @verification.command(name="unverified", aliases=["unverifiedrole"])
    @commands.has_permissions(administrator=True)
    async def verify_unverified(self, ctx: commands.Context, role: discord.Role):
        """Establecer rol de no verificado (se da al unirse)"""
        await database.verification_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"unverified_role": role.id}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(
            f"Rol de no verificado: {role.mention}\n"
            f"Este rol se dará automáticamente a nuevos miembros."
        ))
    
    @verification.command(name="panel", aliases=["embed", "send"])
    @commands.has_permissions(manage_guild=True)
    async def verify_panel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Enviar panel de verificación"""
        channel = channel or ctx.channel
        
        settings = await database.verification_settings.find_one({
            "guild_id": ctx.guild.id
        })
        
        if not settings:
            return await ctx.send(embed=error_embed(
                f"Primero configura el sistema con `{ctx.prefix}verification setup`"
            ))
        
        verify_type = settings.get("type", "button")
        
        embed = discord.Embed(
            title="✅ Verificación",
            color=config.BLURPLE_COLOR
        )
        
        if verify_type == "button":
            embed.description = (
                "Bienvenido al servidor!\n\n"
                "Haz clic en el botón de abajo para verificarte y obtener acceso completo."
            )
        else:
            embed.description = (
                "Bienvenido al servidor!\n\n"
                "Para verificarte, haz clic en el botón y escribe el código que aparece.\n"
                "Esto nos ayuda a prevenir bots y spam."
            )
        
        embed.set_footer(text=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        
        view = VerificationView(self.bot)
        await channel.send(embed=embed, view=view)
        
        if channel != ctx.channel:
            await ctx.send(embed=success_embed(f"Panel enviado a {channel.mention}"))
    
    @verification.command(name="log", aliases=["logs"])
    @commands.has_permissions(administrator=True)
    async def verify_log(self, ctx: commands.Context, channel: discord.TextChannel):
        """Establecer canal de logs de verificación"""
        await database.verification_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"log_channel": channel.id}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(f"Logs de verificación: {channel.mention}"))
    
    @verification.command(name="disable", aliases=["off"])
    @commands.has_permissions(administrator=True)
    async def verify_disable(self, ctx: commands.Context):
        """Desactivar sistema de verificación"""
        await database.verification_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"enabled": False}}
        )
        
        await ctx.send(embed=success_embed("Sistema de verificación desactivado"))
    
    @verification.command(name="settings", aliases=["config"])
    @commands.has_permissions(manage_guild=True)
    async def verify_settings(self, ctx: commands.Context):
        """Ver configuración actual"""
        settings = await database.verification_settings.find_one({
            "guild_id": ctx.guild.id
        })
        
        if not settings:
            return await ctx.send(embed=warning_embed("El sistema no está configurado"))
        
        embed = discord.Embed(
            title="✅ Configuración de Verificación",
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(
            name="Estado",
            value="✅ Activado" if settings.get("enabled") else "❌ Desactivado",
            inline=True
        )
        embed.add_field(name="Tipo", value=settings.get("type", "button").title(), inline=True)
        
        verified_role = ctx.guild.get_role(settings.get("verified_role"))
        embed.add_field(
            name="Rol Verificado",
            value=verified_role.mention if verified_role else "No configurado",
            inline=True
        )
        
        unverified_role = ctx.guild.get_role(settings.get("unverified_role"))
        embed.add_field(
            name="Rol No Verificado",
            value=unverified_role.mention if unverified_role else "No configurado",
            inline=True
        )
        
        log_channel = ctx.guild.get_channel(settings.get("log_channel"))
        embed.add_field(
            name="Canal de Logs",
            value=log_channel.mention if log_channel else "No configurado",
            inline=True
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name="unverify")
    @commands.has_permissions(manage_roles=True)
    async def unverify(self, ctx: commands.Context, member: discord.Member):
        """Quitar verificación a un usuario"""
        settings = await database.verification_settings.find_one({
            "guild_id": ctx.guild.id
        })
        
        if not settings:
            return await ctx.send(embed=error_embed("El sistema no está configurado"))
        
        # Quitar rol de verificado
        if settings.get("verified_role"):
            role = ctx.guild.get_role(settings["verified_role"])
            if role and role in member.roles:
                await member.remove_roles(role, reason=f"No verificado por {ctx.author}")
        
        # Dar rol de no verificado
        if settings.get("unverified_role"):
            role = ctx.guild.get_role(settings["unverified_role"])
            if role:
                await member.add_roles(role, reason=f"No verificado por {ctx.author}")
        
        await ctx.send(embed=success_embed(f"{member.mention} ha sido marcado como no verificado"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Verification(bot))
