"""
Cog VoiceMaster - Sistema de canales de voz temporales
"""

from __future__ import annotations

import asyncio
import discord
from discord.ext import commands
from discord import ui
from typing import Optional

from config import config
from core import database, cache
from utils import success_embed, error_embed, warning_embed


class VoiceMasterModal(ui.Modal):
    """Modal base para VoiceMaster"""
    
    def __init__(self, bot: commands.Bot, title: str):
        super().__init__(title=title)
        self.bot = bot


class RenameModal(VoiceMasterModal):
    """Modal para renombrar canal"""
    
    name = ui.TextInput(
        label="Nuevo nombre",
        placeholder="Escribe el nuevo nombre del canal...",
        max_length=100,
        required=True
    )
    
    def __init__(self, bot: commands.Bot, channel: discord.VoiceChannel):
        super().__init__(bot, "Renombrar canal")
        self.channel = channel
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.channel.edit(name=str(self.name))
            embed = success_embed(f"Canal renombrado a **{self.name}**")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException as e:
            embed = error_embed(f"Error al renombrar: {e}")
            await interaction.response.send_message(embed=embed, ephemeral=True)


class LimitModal(VoiceMasterModal):
    """Modal para establecer límite de usuarios"""
    
    limit = ui.TextInput(
        label="Límite de usuarios",
        placeholder="Número de 0 a 99 (0 = sin límite)",
        max_length=2,
        required=True
    )
    
    def __init__(self, bot: commands.Bot, channel: discord.VoiceChannel):
        super().__init__(bot, "Establecer límite")
        self.channel = channel
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit_value = int(str(self.limit))
            if limit_value < 0 or limit_value > 99:
                raise ValueError()
        except ValueError:
            embed = error_embed("El límite debe ser un número entre 0 y 99")
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        try:
            await self.channel.edit(user_limit=limit_value)
            text = f"Límite establecido en **{limit_value}**" if limit_value > 0 else "Límite removido"
            embed = success_embed(text)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException as e:
            embed = error_embed(f"Error: {e}")
            await interaction.response.send_message(embed=embed, ephemeral=True)


class VoiceMasterView(ui.View):
    """Vista persistente del panel de control de VoiceMaster - Diseño simétrico"""
    
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
    
    async def get_user_channel(self, user_id: int, guild_id: int) -> Optional[dict]:
        """Obtener información del canal del usuario"""
        # Intentar Redis primero
        cached = await cache.get_voicemaster_channel(user_id)
        if cached and cached.get("guild_id") == guild_id:
            return cached
        
        # Buscar en MongoDB
        data = await database.voicemaster_channels.find_one({
            "owner_id": user_id,
            "guild_id": guild_id
        })
        
        return data
    
    async def verify_ownership(
        self, 
        interaction: discord.Interaction
    ) -> tuple[bool, Optional[discord.VoiceChannel]]:
        """Verificar que el usuario sea dueño de un canal VoiceMaster"""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                embed=error_embed("Debes estar en un canal de voz"),
                ephemeral=True
            )
            return False, None
        
        channel = interaction.user.voice.channel
        data = await self.get_user_channel(interaction.user.id, interaction.guild.id)
        
        if not data or data.get("channel_id") != channel.id:
            await interaction.response.send_message(
                embed=error_embed("No eres el dueño de este canal"),
                ephemeral=True
            )
            return False, None
        
        return True, channel
    
    async def verify_in_voicemaster(
        self, 
        interaction: discord.Interaction
    ) -> tuple[bool, Optional[discord.VoiceChannel], Optional[dict]]:
        """Verificar que el usuario esté en un canal VoiceMaster"""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                embed=error_embed("Debes estar en un canal de voz"),
                ephemeral=True
            )
            return False, None, None
        
        channel = interaction.user.voice.channel
        data = await database.voicemaster_channels.find_one({
            "channel_id": channel.id,
            "guild_id": interaction.guild.id
        })
        
        if not data:
            await interaction.response.send_message(
                embed=error_embed("Este no es un canal VoiceMaster"),
                ephemeral=True
            )
            return False, None, None
        
        return True, channel, data
    
    # ========== Fila 0: Lock, Unlock, Ghost, Reveal, Claim ==========
    
    @ui.button(emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="vm:lock", row=0)
    async def lock_button(self, interaction: discord.Interaction, button: ui.Button):
        """Bloquear el canal"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        overwrites = channel.overwrites_for(interaction.guild.default_role)
        overwrites.connect = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
        
        embed = success_embed("🔒 Canal **bloqueado** — nadie más puede unirse")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @ui.button(emoji="🔓", style=discord.ButtonStyle.secondary, custom_id="vm:unlock", row=0)
    async def unlock_button(self, interaction: discord.Interaction, button: ui.Button):
        """Desbloquear el canal"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        overwrites = channel.overwrites_for(interaction.guild.default_role)
        overwrites.connect = True
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
        
        embed = success_embed("🔓 Canal **desbloqueado** — todos pueden unirse")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @ui.button(emoji="👻", style=discord.ButtonStyle.secondary, custom_id="vm:ghost", row=0)
    async def ghost_button(self, interaction: discord.Interaction, button: ui.Button):
        """Ocultar el canal (Ghost)"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        overwrites = channel.overwrites_for(interaction.guild.default_role)
        overwrites.view_channel = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
        
        embed = success_embed("👻 Canal **oculto** — invisible para otros")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @ui.button(emoji="👁️", style=discord.ButtonStyle.secondary, custom_id="vm:reveal", row=0)
    async def reveal_button(self, interaction: discord.Interaction, button: ui.Button):
        """Mostrar el canal (Reveal)"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        overwrites = channel.overwrites_for(interaction.guild.default_role)
        overwrites.view_channel = True
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
        
        embed = success_embed("👁️ Canal **visible** — todos pueden verlo")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @ui.button(emoji="🎤", style=discord.ButtonStyle.secondary, custom_id="vm:claim", row=0)
    async def claim_button(self, interaction: discord.Interaction, button: ui.Button):
        """Reclamar un canal abandonado"""
        valid, channel, data = await self.verify_in_voicemaster(interaction)
        if not valid:
            return
        
        # Verificar si el dueño actual está en el canal
        current_owner = interaction.guild.get_member(data["owner_id"])
        if current_owner and current_owner in channel.members:
            return await interaction.response.send_message(
                embed=error_embed("El dueño actual aún está en el canal"),
                ephemeral=True
            )
        
        # Transferir propiedad
        await database.voicemaster_channels.update_one(
            {"channel_id": channel.id},
            {"$set": {"owner_id": interaction.user.id}}
        )
        
        # Actualizar caché
        await cache.set_voicemaster_channel(channel.id, interaction.user.id, interaction.guild.id)
        
        # Renombrar canal
        try:
            await channel.edit(name=f"Canal de {interaction.user.display_name}")
        except discord.HTTPException:
            pass
        
        embed = success_embed(f"🎤 Ahora eres el **dueño** de este canal")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # ========== Fila 1: Disconnect, Activity, Info, Increase, Decrease ==========
    
    @ui.button(emoji="🚫", style=discord.ButtonStyle.secondary, custom_id="vm:disconnect", row=1)
    async def disconnect_button(self, interaction: discord.Interaction, button: ui.Button):
        """Desconectar un usuario del canal"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        # Crear select para elegir usuario
        if len(channel.members) <= 1:
            return await interaction.response.send_message(
                embed=error_embed("No hay otros usuarios en el canal"),
                ephemeral=True
            )
        
        options = []
        for member in channel.members:
            if member.id != interaction.user.id:
                options.append(
                    discord.SelectOption(
                        label=member.display_name,
                        value=str(member.id),
                        emoji="👤"
                    )
                )
        
        select = discord.ui.Select(
            placeholder="Selecciona un usuario para desconectar...",
            options=options[:25]
        )
        
        async def select_callback(select_interaction: discord.Interaction):
            member_id = int(select.values[0])
            member = interaction.guild.get_member(member_id)
            if member and member.voice:
                await member.move_to(None)
                await select_interaction.response.send_message(
                    embed=success_embed(f"🚫 **{member.display_name}** desconectado"),
                    ephemeral=True
                )
            else:
                await select_interaction.response.send_message(
                    embed=error_embed("El usuario ya no está en el canal"),
                    ephemeral=True
                )
        
        select.callback = select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        
        await interaction.response.send_message(
            "Selecciona un usuario para desconectar:",
            view=view,
            ephemeral=True
        )
    
    @ui.button(emoji="🎮", style=discord.ButtonStyle.secondary, custom_id="vm:activity", row=1)
    async def activity_button(self, interaction: discord.Interaction, button: ui.Button):
        """Iniciar una actividad de Discord"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        # Actividades populares
        activities = {
            "Watch Together": 880218394199220334,
            "Poker Night": 755827207812677713,
            "Chess": 832012774040141894,
            "Checkers": 832013003968348200,
            "Sketch Heads": 902271654783242291,
            "Letter League": 879863686565621790,
            "Word Snacks": 879863976006127627,
            "SpellCast": 852509694341283871,
        }
        
        options = [
            discord.SelectOption(label=name, value=str(app_id), emoji="🎮")
            for name, app_id in activities.items()
        ]
        
        select = discord.ui.Select(
            placeholder="Selecciona una actividad...",
            options=options
        )
        
        async def select_callback(select_interaction: discord.Interaction):
            app_id = int(select.values[0])
            try:
                invite = await channel.create_invite(
                    max_age=3600,
                    target_type=discord.InviteTarget.embedded_application,
                    target_application_id=app_id
                )
                embed = discord.Embed(
                    title="🎮 Actividad Iniciada",
                    description=f"[Click aquí para unirte]({invite.url})",
                    color=config.SUCCESS_COLOR
                )
                await select_interaction.response.send_message(embed=embed, ephemeral=True)
            except Exception as e:
                await select_interaction.response.send_message(
                    embed=error_embed(f"Error al crear actividad: {e}"),
                    ephemeral=True
                )
        
        select.callback = select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        
        await interaction.response.send_message(
            "Selecciona una actividad para iniciar:",
            view=view,
            ephemeral=True
        )
    
    @ui.button(emoji="ℹ️", style=discord.ButtonStyle.secondary, custom_id="vm:info", row=1)
    async def info_button(self, interaction: discord.Interaction, button: ui.Button):
        """Ver información del canal"""
        valid, channel, data = await self.verify_in_voicemaster(interaction)
        if not valid:
            return
        
        owner = interaction.guild.get_member(data["owner_id"])
        
        # Estado del canal
        default_perms = channel.overwrites_for(interaction.guild.default_role)
        is_locked = default_perms.connect is False
        is_hidden = default_perms.view_channel is False
        
        status = []
        if is_locked:
            status.append("🔒 Bloqueado")
        else:
            status.append("🔓 Desbloqueado")
        if is_hidden:
            status.append("👻 Oculto")
        else:
            status.append("👁️ Visible")
        
        embed = discord.Embed(
            title=f"ℹ️ Información del Canal",
            color=config.BLURPLE_COLOR
        )
        embed.add_field(name="📛 Nombre", value=channel.name, inline=True)
        embed.add_field(name="👑 Dueño", value=owner.mention if owner else "Desconocido", inline=True)
        embed.add_field(name="👥 Usuarios", value=f"{len(channel.members)}/{channel.user_limit or '∞'}", inline=True)
        embed.add_field(name="🎚️ Bitrate", value=f"{channel.bitrate // 1000}kbps", inline=True)
        embed.add_field(name="📊 Estado", value=" • ".join(status), inline=True)
        embed.add_field(name="📅 Creado", value=discord.utils.format_dt(channel.created_at, style="R"), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @ui.button(emoji="➕", style=discord.ButtonStyle.success, custom_id="vm:increase", row=1)
    async def increase_button(self, interaction: discord.Interaction, button: ui.Button):
        """Aumentar límite de usuarios"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        current = channel.user_limit or 0
        new_limit = min(current + 1, 99)
        
        if new_limit == current and current == 99:
            return await interaction.response.send_message(
                embed=error_embed("El límite máximo es 99 usuarios"),
                ephemeral=True
            )
        
        await channel.edit(user_limit=new_limit)
        embed = success_embed(f"➕ Límite aumentado a **{new_limit}** usuarios")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @ui.button(emoji="➖", style=discord.ButtonStyle.danger, custom_id="vm:decrease", row=1)
    async def decrease_button(self, interaction: discord.Interaction, button: ui.Button):
        """Disminuir límite de usuarios"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        current = channel.user_limit or 0
        
        if current <= 0:
            return await interaction.response.send_message(
                embed=error_embed("El canal ya no tiene límite"),
                ephemeral=True
            )
        
        new_limit = max(current - 1, 0)
        await channel.edit(user_limit=new_limit if new_limit > 0 else 0)
        
        if new_limit == 0:
            embed = success_embed("➖ Límite de usuarios **removido**")
        else:
            embed = success_embed(f"➖ Límite reducido a **{new_limit}** usuarios")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # ========== Fila 2: Rename, Permit, Reject, Transfer, Bitrate ==========
    
    @ui.button(emoji="✏️", style=discord.ButtonStyle.primary, custom_id="vm:rename", row=2)
    async def rename_button(self, interaction: discord.Interaction, button: ui.Button):
        """Renombrar el canal"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        modal = RenameModal(self.bot, channel)
        await interaction.response.send_modal(modal)
    
    @ui.button(emoji="✅", style=discord.ButtonStyle.success, custom_id="vm:permit", row=2)
    async def permit_button(self, interaction: discord.Interaction, button: ui.Button):
        """Permitir acceso a un usuario"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        # Modal para ingresar usuario
        class PermitModal(ui.Modal, title="Permitir Usuario"):
            user_input = ui.TextInput(
                label="Usuario (ID o mención)",
                placeholder="Escribe el ID o @usuario",
                required=True
            )
            
            def __init__(modal_self, channel: discord.VoiceChannel):
                super().__init__()
                modal_self.channel = channel
            
            async def on_submit(modal_self, modal_interaction: discord.Interaction):
                # Intentar obtener usuario
                user_str = str(modal_self.user_input).strip()
                # Limpiar mención
                user_str = user_str.replace("<@", "").replace(">", "").replace("!", "")
                
                try:
                    user_id = int(user_str)
                    member = interaction.guild.get_member(user_id)
                except ValueError:
                    # Buscar por nombre
                    member = discord.utils.find(
                        lambda m: m.name.lower() == user_str.lower() or m.display_name.lower() == user_str.lower(),
                        interaction.guild.members
                    )
                
                if not member:
                    return await modal_interaction.response.send_message(
                        embed=error_embed("Usuario no encontrado"),
                        ephemeral=True
                    )
                
                overwrites = modal_self.channel.overwrites_for(member)
                overwrites.connect = True
                overwrites.view_channel = True
                await modal_self.channel.set_permissions(member, overwrite=overwrites)
                
                await modal_interaction.response.send_message(
                    embed=success_embed(f"✅ **{member.display_name}** puede acceder al canal"),
                    ephemeral=True
                )
        
        await interaction.response.send_modal(PermitModal(channel))
    
    @ui.button(emoji="❌", style=discord.ButtonStyle.danger, custom_id="vm:reject", row=2)
    async def reject_button(self, interaction: discord.Interaction, button: ui.Button):
        """Denegar acceso a un usuario"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        # Modal para ingresar usuario
        class RejectModal(ui.Modal, title="Denegar Usuario"):
            user_input = ui.TextInput(
                label="Usuario (ID o mención)",
                placeholder="Escribe el ID o @usuario",
                required=True
            )
            
            def __init__(modal_self, channel: discord.VoiceChannel):
                super().__init__()
                modal_self.channel = channel
            
            async def on_submit(modal_self, modal_interaction: discord.Interaction):
                user_str = str(modal_self.user_input).strip()
                user_str = user_str.replace("<@", "").replace(">", "").replace("!", "")
                
                try:
                    user_id = int(user_str)
                    member = interaction.guild.get_member(user_id)
                except ValueError:
                    member = discord.utils.find(
                        lambda m: m.name.lower() == user_str.lower() or m.display_name.lower() == user_str.lower(),
                        interaction.guild.members
                    )
                
                if not member:
                    return await modal_interaction.response.send_message(
                        embed=error_embed("Usuario no encontrado"),
                        ephemeral=True
                    )
                
                if member.id == interaction.user.id:
                    return await modal_interaction.response.send_message(
                        embed=error_embed("No puedes bloquearte a ti mismo"),
                        ephemeral=True
                    )
                
                overwrites = modal_self.channel.overwrites_for(member)
                overwrites.connect = False
                overwrites.view_channel = False
                await modal_self.channel.set_permissions(member, overwrite=overwrites)
                
                # Desconectar si está en el canal
                if member.voice and member.voice.channel == modal_self.channel:
                    await member.move_to(None)
                
                await modal_interaction.response.send_message(
                    embed=success_embed(f"❌ **{member.display_name}** ya no puede acceder al canal"),
                    ephemeral=True
                )
        
        await interaction.response.send_modal(RejectModal(channel))
    
    @ui.button(emoji="👑", style=discord.ButtonStyle.primary, custom_id="vm:transfer", row=2)
    async def transfer_button(self, interaction: discord.Interaction, button: ui.Button):
        """Transferir propiedad del canal"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        if len(channel.members) <= 1:
            return await interaction.response.send_message(
                embed=error_embed("No hay otros usuarios en el canal"),
                ephemeral=True
            )
        
        options = []
        for member in channel.members:
            if member.id != interaction.user.id:
                options.append(
                    discord.SelectOption(
                        label=member.display_name,
                        value=str(member.id),
                        emoji="👤"
                    )
                )
        
        select = discord.ui.Select(
            placeholder="Selecciona el nuevo dueño...",
            options=options[:25]
        )
        
        async def select_callback(select_interaction: discord.Interaction):
            member_id = int(select.values[0])
            member = interaction.guild.get_member(member_id)
            
            if not member:
                return await select_interaction.response.send_message(
                    embed=error_embed("Usuario no encontrado"),
                    ephemeral=True
                )
            
            # Transferir propiedad
            await database.voicemaster_channels.update_one(
                {"channel_id": channel.id},
                {"$set": {"owner_id": member.id}}
            )
            
            await cache.set_voicemaster_channel(channel.id, member.id, interaction.guild.id)
            
            try:
                await channel.edit(name=f"Canal de {member.display_name}")
            except discord.HTTPException:
                pass
            
            await select_interaction.response.send_message(
                embed=success_embed(f"👑 **{member.display_name}** es el nuevo dueño del canal"),
                ephemeral=True
            )
        
        select.callback = select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        
        await interaction.response.send_message(
            "Selecciona el nuevo dueño del canal:",
            view=view,
            ephemeral=True
        )
    
    @ui.button(emoji="🎚️", style=discord.ButtonStyle.secondary, custom_id="vm:bitrate", row=2)
    async def bitrate_button(self, interaction: discord.Interaction, button: ui.Button):
        """Cambiar bitrate del canal"""
        valid, channel = await self.verify_ownership(interaction)
        if not valid:
            return
        
        class BitrateModal(ui.Modal, title="Cambiar Bitrate"):
            bitrate_input = ui.TextInput(
                label="Bitrate (8-96 kbps)",
                placeholder="Ejemplo: 64",
                max_length=2,
                required=True
            )
            
            def __init__(modal_self, channel: discord.VoiceChannel):
                super().__init__()
                modal_self.channel = channel
            
            async def on_submit(modal_self, modal_interaction: discord.Interaction):
                try:
                    bitrate = int(str(modal_self.bitrate_input))
                    if bitrate < 8 or bitrate > 96:
                        raise ValueError()
                except ValueError:
                    return await modal_interaction.response.send_message(
                        embed=error_embed("El bitrate debe ser entre 8 y 96"),
                        ephemeral=True
                    )
                
                await modal_self.channel.edit(bitrate=bitrate * 1000)
                await modal_interaction.response.send_message(
                    embed=success_embed(f"🎚️ Bitrate cambiado a **{bitrate}kbps**"),
                    ephemeral=True
                )
        
        await interaction.response.send_modal(BitrateModal(channel))


class VoiceMaster(commands.Cog):
    """🎙️ Sistema de canales de voz temporales"""
    
    emoji = "🎙️"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Registrar vista persistente
        self.bot.add_view(VoiceMasterView(bot))
    
    # ========== Event Listeners ==========
    
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        """Manejar entrada/salida de canales de voz"""
        guild = member.guild
        
        # Usuario entró a un canal
        if after.channel:
            await self.handle_join(member, after.channel)
        
        # Usuario salió de un canal
        if before.channel:
            await self.handle_leave(member, before.channel)
    
    async def handle_join(self, member: discord.Member, channel: discord.VoiceChannel):
        """Manejar cuando un usuario entra a un canal"""
        # Verificar si es el canal generador
        config_data = await database.voicemaster_guilds.find_one({
            "guild_id": member.guild.id
        })
        
        if not config_data:
            return
        
        generator_id = config_data.get("generator_channel_id")
        category_id = config_data.get("category_id")
        
        if channel.id != generator_id:
            return
        
        # Crear canal temporal
        category = member.guild.get_channel(category_id)
        if not category:
            return
        
        try:
            # Crear el canal
            new_channel = await member.guild.create_voice_channel(
                name=f"Canal de {member.display_name}",
                category=category,
                reason="VoiceMaster: Canal temporal"
            )
            
            # Dar permisos al dueño
            await new_channel.set_permissions(
                member,
                connect=True,
                manage_channels=True,
                manage_permissions=True,
                mute_members=True,
                deafen_members=True,
                move_members=True
            )
            
            # Mover al usuario
            await member.move_to(new_channel)
            
            # Guardar en base de datos
            await database.voicemaster_channels.insert_one({
                "guild_id": member.guild.id,
                "channel_id": new_channel.id,
                "owner_id": member.id,
                "created_at": discord.utils.utcnow()
            })
            
            # Guardar en Redis para acceso rápido
            await cache.set_voicemaster_channel(
                new_channel.id, 
                member.id, 
                member.guild.id
            )
            
        except discord.HTTPException as e:
            print(f"Error creando canal VoiceMaster: {e}")
    
    async def handle_leave(self, member: discord.Member, channel: discord.VoiceChannel):
        """Manejar cuando un usuario sale de un canal"""
        # Verificar si el canal está vacío y es un canal VoiceMaster
        if len(channel.members) > 0:
            return
        
        # Verificar si es un canal VoiceMaster
        data = await database.voicemaster_channels.find_one({
            "channel_id": channel.id
        })
        
        if not data:
            return
        
        # Eliminar canal
        try:
            await channel.delete(reason="VoiceMaster: Canal vacío")
        except discord.HTTPException:
            pass
        
        # Limpiar base de datos
        await database.voicemaster_channels.delete_one({"channel_id": channel.id})
        await cache.delete_voicemaster_channel(channel.id)
    
    # ========== Commands ==========
    
    @commands.group(
        name="voicemaster",
        aliases=["vm", "vc"],
        brief="Sistema de canales de voz temporales",
        invoke_without_command=True
    )
    async def voicemaster(self, ctx: commands.Context):
        """
        Sistema de canales de voz temporales.
        Permite a los usuarios crear y gestionar sus propios canales de voz.
        """
        embed = discord.Embed(
            title="🎙️ VoiceMaster",
            description=(
                "Sistema de canales de voz temporales.\n\n"
                "Cuando entras al canal generador, se crea automáticamente "
                "tu propio canal de voz que puedes personalizar.\n\n"
                "**Comandos disponibles:**"
            ),
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(
            name="⚙️ Configuración",
            value=(
                f"`{ctx.clean_prefix}vm setup` - Configurar VoiceMaster\n"
                f"`{ctx.clean_prefix}vm interface` - Panel de control\n"
                f"`{ctx.clean_prefix}vm disable` - Desactivar"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🎛️ Control de canal",
            value=(
                f"`{ctx.clean_prefix}vm lock` - Bloquear canal\n"
                f"`{ctx.clean_prefix}vm unlock` - Desbloquear\n"
                f"`{ctx.clean_prefix}vm rename <nombre>` - Renombrar\n"
                f"`{ctx.clean_prefix}vm limit <número>` - Límite de usuarios\n"
                f"`{ctx.clean_prefix}vm permit @usuario` - Permitir acceso\n"
                f"`{ctx.clean_prefix}vm reject @usuario` - Denegar acceso\n"
                f"`{ctx.clean_prefix}vm claim` - Reclamar canal"
            ),
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @voicemaster.command(name="setup", aliases=["configurar"])
    @commands.has_permissions(administrator=True)
    async def vm_setup(
        self, 
        ctx: commands.Context, 
        category: Optional[discord.CategoryChannel] = None
    ):
        """
        Configurar VoiceMaster en el servidor.
        
        **Uso:** ;vm setup [categoría]
        Si no se especifica categoría, se creará una nueva.
        """
        # Verificar si ya está configurado
        existing = await database.voicemaster_guilds.find_one({"guild_id": ctx.guild.id})
        if existing:
            return await ctx.send(embed=warning_embed(
                f"VoiceMaster ya está configurado. Usa `{ctx.clean_prefix}vm disable` para reiniciar."
            ))
        
        # Crear o usar categoría
        if not category:
            category = await ctx.guild.create_category(
                "🎙️ VoiceMaster",
                reason="VoiceMaster setup"
            )
        
        # Crear canal generador
        generator = await ctx.guild.create_voice_channel(
            "➕ Crear Canal",
            category=category,
            reason="VoiceMaster generator"
        )
        
        # Guardar configuración
        await database.voicemaster_guilds.insert_one({
            "guild_id": ctx.guild.id,
            "category_id": category.id,
            "generator_channel_id": generator.id,
            "interface_channel_id": None,
            "interface_message_id": None,
            "created_at": discord.utils.utcnow()
        })
        
        embed = success_embed(
            f"✅ VoiceMaster configurado!\n\n"
            f"**Categoría:** {category.name}\n"
            f"**Canal generador:** {generator.mention}\n\n"
            f"Los usuarios pueden unirse a {generator.mention} para crear su canal.",
            ctx.author
        )
        await ctx.send(embed=embed)
    
    @voicemaster.command(name="interface", aliases=["panel"])
    @commands.has_permissions(administrator=True)
    async def vm_interface(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """
        Crear el panel de control de VoiceMaster.
        
        **Uso:** ;vm interface [canal]
        """
        config_data = await database.voicemaster_guilds.find_one({"guild_id": ctx.guild.id})
        if not config_data:
            return await ctx.send(embed=error_embed(
                f"VoiceMaster no está configurado. Usa `{ctx.clean_prefix}vm setup`"
            ))
        
        channel = channel or ctx.channel
        
        embed = discord.Embed(
            title="🎙️ VoiceMaster",
            description="Usa los botones de abajo para controlar tu canal de voz.",
            color=config.BLURPLE_COLOR
        )
        
        # Descripción de botones organizada
        embed.add_field(
            name="📋 Controles",
            value=(
                "🔒 — **Bloquear** el canal de voz\n"
                "🔓 — **Desbloquear** el canal de voz\n"
                "👻 — **Ocultar** el canal de voz\n"
                "👁️ — **Revelar** el canal de voz\n"
                "🎤 — **Reclamar** el canal de voz\n"
                "🚫 — **Desconectar** a un miembro\n"
                "🎮 — **Iniciar** una actividad\n"
                "ℹ️ — **Ver** información del canal\n"
                "➕ — **Aumentar** el límite de usuarios\n"
                "➖ — **Reducir** el límite de usuarios\n"
                "✏️ — **Renombrar** el canal de voz\n"
                "✅ — **Permitir** a un miembro\n"
                "❌ — **Rechazar** a un miembro\n"
                "👑 — **Transferir** propiedad\n"
                "🎚️ — **Ajustar** bitrate"
            ),
            inline=False
        )
        
        # Agregar thumbnail del servidor o un logo
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        
        view = VoiceMasterView(self.bot)
        message = await channel.send(embed=embed, view=view)
        
        # Guardar referencia
        await database.voicemaster_guilds.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {
                    "interface_channel_id": channel.id,
                    "interface_message_id": message.id
                }
            }
        )
        
        if channel != ctx.channel:
            await ctx.send(embed=success_embed(f"Panel creado en {channel.mention}"))
    
    @voicemaster.command(name="disable", aliases=["desactivar"])
    @commands.has_permissions(administrator=True)
    async def vm_disable(self, ctx: commands.Context):
        """Desactivar VoiceMaster"""
        result = await database.voicemaster_guilds.delete_one({"guild_id": ctx.guild.id})
        
        if result.deleted_count == 0:
            return await ctx.send(embed=error_embed("VoiceMaster no está configurado"))
        
        # Limpiar canales temporales
        await database.voicemaster_channels.delete_many({"guild_id": ctx.guild.id})
        
        embed = success_embed("VoiceMaster desactivado", ctx.author)
        await ctx.send(embed=embed)
    
    # ========== User Commands ==========
    
    async def get_user_channel_ctx(self, ctx: commands.Context) -> Optional[discord.VoiceChannel]:
        """Helper para obtener el canal del usuario"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send(embed=error_embed("Debes estar en un canal de voz"))
            return None
        
        channel = ctx.author.voice.channel
        data = await database.voicemaster_channels.find_one({
            "channel_id": channel.id,
            "owner_id": ctx.author.id
        })
        
        if not data:
            await ctx.send(embed=error_embed("No eres el dueño de este canal"))
            return None
        
        return channel
    
    @voicemaster.command(name="lock", aliases=["bloquear"])
    async def vm_lock(self, ctx: commands.Context):
        """Bloquear tu canal de voz"""
        channel = await self.get_user_channel_ctx(ctx)
        if not channel:
            return
        
        overwrites = channel.overwrites_for(ctx.guild.default_role)
        overwrites.connect = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrites)
        
        await ctx.send(embed=success_embed("🔒 Canal bloqueado"))
    
    @voicemaster.command(name="unlock", aliases=["desbloquear"])
    async def vm_unlock(self, ctx: commands.Context):
        """Desbloquear tu canal de voz"""
        channel = await self.get_user_channel_ctx(ctx)
        if not channel:
            return
        
        overwrites = channel.overwrites_for(ctx.guild.default_role)
        overwrites.connect = True
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrites)
        
        await ctx.send(embed=success_embed("🔓 Canal desbloqueado"))
    
    @voicemaster.command(name="rename", aliases=["renombrar"])
    async def vm_rename(self, ctx: commands.Context, *, name: str):
        """Renombrar tu canal de voz"""
        channel = await self.get_user_channel_ctx(ctx)
        if not channel:
            return
        
        if len(name) > 100:
            return await ctx.send(embed=error_embed("El nombre es muy largo (máx. 100)"))
        
        await channel.edit(name=name)
        await ctx.send(embed=success_embed(f"Canal renombrado a **{name}**"))
    
    @voicemaster.command(name="limit", aliases=["limite"])
    async def vm_limit(self, ctx: commands.Context, limit: int):
        """Establecer límite de usuarios (0 = sin límite)"""
        channel = await self.get_user_channel_ctx(ctx)
        if not channel:
            return
        
        if limit < 0 or limit > 99:
            return await ctx.send(embed=error_embed("El límite debe estar entre 0 y 99"))
        
        await channel.edit(user_limit=limit)
        
        if limit == 0:
            await ctx.send(embed=success_embed("Límite removido"))
        else:
            await ctx.send(embed=success_embed(f"Límite establecido en **{limit}**"))
    
    @voicemaster.command(name="permit", aliases=["permitir", "allow"])
    async def vm_permit(self, ctx: commands.Context, member: discord.Member):
        """Permitir a un usuario unirse a tu canal"""
        channel = await self.get_user_channel_ctx(ctx)
        if not channel:
            return
        
        await channel.set_permissions(member, connect=True, view_channel=True)
        await ctx.send(embed=success_embed(f"**{member}** puede unirse al canal"))
    
    @voicemaster.command(name="reject", aliases=["rechazar", "deny"])
    async def vm_reject(self, ctx: commands.Context, member: discord.Member):
        """Denegar acceso a un usuario"""
        channel = await self.get_user_channel_ctx(ctx)
        if not channel:
            return
        
        await channel.set_permissions(member, connect=False)
        
        # Si está en el canal, desconectarlo
        if member in channel.members:
            await member.move_to(None)
        
        await ctx.send(embed=success_embed(f"**{member}** no puede unirse al canal"))
    
    @voicemaster.command(name="claim", aliases=["reclamar"])
    async def vm_claim(self, ctx: commands.Context):
        """Reclamar un canal abandonado"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send(embed=error_embed("Debes estar en un canal de voz"))
        
        channel = ctx.author.voice.channel
        
        data = await database.voicemaster_channels.find_one({
            "channel_id": channel.id,
            "guild_id": ctx.guild.id
        })
        
        if not data:
            return await ctx.send(embed=error_embed("Este no es un canal VoiceMaster"))
        
        owner = ctx.guild.get_member(data["owner_id"])
        if owner and owner in channel.members:
            return await ctx.send(embed=error_embed("El dueño aún está en el canal"))
        
        # Transferir propiedad
        await database.voicemaster_channels.update_one(
            {"channel_id": channel.id},
            {"$set": {"owner_id": ctx.author.id}}
        )
        
        await cache.set_voicemaster_channel(channel.id, ctx.author.id, ctx.guild.id)
        
        try:
            await channel.edit(name=f"Canal de {ctx.author.display_name}")
        except discord.HTTPException:
            pass
        
        await ctx.send(embed=success_embed("👑 Ahora eres el dueño del canal"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceMaster(bot))
