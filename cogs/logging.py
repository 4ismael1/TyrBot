"""
Cog Logging - Sistema de logs del servidor con panel interactivo
"""

from __future__ import annotations

import discord
from discord.ext import commands
from discord import ui
from datetime import datetime
from typing import Optional

from config import config
from core import database, cache
from utils import success_embed, error_embed, warning_embed


# Eventos de logs disponibles (granulares)
LOG_EVENTS = {
    # Mensajes
    "message_delete": {"emoji": "🗑️", "name": "Mensaje eliminado", "category": "Mensajes"},
    "message_edit": {"emoji": "✏️", "name": "Mensaje editado", "category": "Mensajes"},
    "message_bulk_delete": {"emoji": "🧹", "name": "Purge/Eliminación masiva", "category": "Mensajes"},
    
    # Miembros
    "member_join": {"emoji": "📥", "name": "Miembro entra", "category": "Miembros"},
    "member_leave": {"emoji": "📤", "name": "Miembro sale", "category": "Miembros"},
    "member_nick": {"emoji": "📝", "name": "Cambio de apodo", "category": "Miembros"},
    "member_roles": {"emoji": "🎭", "name": "Cambio de roles", "category": "Miembros"},
    "member_avatar": {"emoji": "🖼️", "name": "Cambio de avatar", "category": "Miembros"},
    
    # Servidor
    "channel_create": {"emoji": "📁", "name": "Canal creado", "category": "Servidor"},
    "channel_delete": {"emoji": "🗑️", "name": "Canal eliminado", "category": "Servidor"},
    "channel_update": {"emoji": "⚙️", "name": "Canal modificado", "category": "Servidor"},
    "role_create": {"emoji": "🎨", "name": "Rol creado", "category": "Servidor"},
    "role_delete": {"emoji": "🗑️", "name": "Rol eliminado", "category": "Servidor"},
    "role_update": {"emoji": "⚙️", "name": "Rol modificado", "category": "Servidor"},
    "emoji_update": {"emoji": "😀", "name": "Emojis actualizados", "category": "Servidor"},
    "invite_create": {"emoji": "🔗", "name": "Invitación creada", "category": "Servidor"},
    "invite_delete": {"emoji": "🔗", "name": "Invitación eliminada", "category": "Servidor"},
    
    # Voz
    "voice_join": {"emoji": "🔊", "name": "Entra a voz", "category": "Voz"},
    "voice_leave": {"emoji": "🔇", "name": "Sale de voz", "category": "Voz"},
    "voice_move": {"emoji": "🔀", "name": "Cambio de canal", "category": "Voz"},
    "voice_mute": {"emoji": "🎙️", "name": "Mute/Unmute", "category": "Voz"},
    "voice_deafen": {"emoji": "🎧", "name": "Deafen/Undeafen", "category": "Voz"},
    
    # Moderación
    "mod_warn": {"emoji": "⚠️", "name": "Warn", "category": "Moderación"},
    "mod_kick": {"emoji": "👢", "name": "Kick", "category": "Moderación"},
    "mod_ban": {"emoji": "🔨", "name": "Ban", "category": "Moderación"},
    "mod_unban": {"emoji": "✅", "name": "Unban", "category": "Moderación"},
    "mod_timeout": {"emoji": "🔇", "name": "Timeout", "category": "Moderación"},
    "mod_untimeout": {"emoji": "🔊", "name": "Untimeout", "category": "Moderación"},
    "mod_quarantine": {"emoji": "🔒", "name": "Cuarentena", "category": "Moderación"},
    "mod_unquarantine": {"emoji": "🔓", "name": "Fin Cuarentena", "category": "Moderación"},
}

# Categorías
CATEGORIES = {
    "Mensajes": {"emoji": "💬", "color": 0x5865F2},
    "Miembros": {"emoji": "👤", "color": 0x57F287},
    "Servidor": {"emoji": "🏠", "color": 0xFEE75C},
    "Voz": {"emoji": "🔊", "color": 0xEB459E},
    "Moderación": {"emoji": "🔨", "color": 0xED4245},
}


class LogChannelModal(ui.Modal):
    """Modal para configurar el canal de logs"""
    
    def __init__(self):
        super().__init__(title="Configurar Canal de Logs")
    
    channel_id = ui.TextInput(
        label="ID del Canal",
        placeholder="Pega el ID del canal aquí...",
        required=True,
        min_length=17,
        max_length=20
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel = interaction.guild.get_channel(int(self.channel_id.value))
            if not channel:
                return await interaction.response.send_message(
                    embed=error_embed("Canal no encontrado"),
                    ephemeral=True
                )
            
            await database.logging.update_one(
                {"guild_id": interaction.guild.id},
                {"$set": {"channel": channel.id}},
                upsert=True
            )
            
            cog = interaction.client.get_cog("Logging")
            if cog:
                await cog.invalidate_cache(interaction.guild.id)
            
            await interaction.response.send_message(
                embed=success_embed(f"✅ Canal de logs configurado: {channel.mention}"),
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                embed=error_embed("ID inválido"),
                ephemeral=True
            )


class CategoryChannelSelect(ui.Select):
    """Select para elegir categoría a configurar"""
    
    def __init__(self, view_ref):
        self.view_ref = view_ref
        options = [
            discord.SelectOption(
                label=cat_name,
                emoji=cat_info["emoji"],
                description=f"Canal para logs de {cat_name.lower()}",
                value=cat_name
            )
            for cat_name, cat_info in CATEGORIES.items()
        ]
        super().__init__(
            placeholder="Selecciona una categoría...",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        
        # Crear view con selector de canal
        channel_view = ui.View(timeout=60)
        channel_select = ui.ChannelSelect(
            placeholder=f"Selecciona canal para {category}...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )
        
        async def channel_callback(channel_interaction: discord.Interaction):
            channel = channel_select.values[0]
            
            # Guardar canal para esta categoría
            await database.logging.update_one(
                {"guild_id": interaction.guild.id},
                {"$set": {f"category_channels.{category}": channel.id}},
                upsert=True
            )
            
            cog = interaction.client.get_cog("Logging")
            if cog:
                await cog.invalidate_cache(interaction.guild.id)
            
            # Actualizar config_data del view padre
            if "category_channels" not in self.view_ref.config_data:
                self.view_ref.config_data["category_channels"] = {}
            self.view_ref.config_data["category_channels"][category] = channel.id
            
            await channel_interaction.response.send_message(
                embed=success_embed(f"✅ Canal de **{category}**: {channel.mention}"),
                ephemeral=True
            )
        
        channel_select.callback = channel_callback
        channel_view.add_item(channel_select)
        
        # Añadir botón para quitar canal de categoría
        remove_btn = ui.Button(
            label="Quitar canal",
            emoji="🗑️",
            style=discord.ButtonStyle.danger
        )
        
        async def remove_callback(remove_interaction: discord.Interaction):
            await database.logging.update_one(
                {"guild_id": interaction.guild.id},
                {"$unset": {f"category_channels.{category}": ""}}
            )
            
            cog = interaction.client.get_cog("Logging")
            if cog:
                await cog.invalidate_cache(interaction.guild.id)
            
            if "category_channels" in self.view_ref.config_data:
                self.view_ref.config_data["category_channels"].pop(category, None)
            
            await remove_interaction.response.send_message(
                embed=success_embed(f"✅ Canal de **{category}** eliminado (usará canal general)"),
                ephemeral=True
            )
        
        remove_btn.callback = remove_callback
        channel_view.add_item(remove_btn)
        
        await interaction.response.send_message(
            f"**{CATEGORIES[category]['emoji']} {category}**\nSelecciona el canal para esta categoría:",
            view=channel_view,
            ephemeral=True
        )


class LoggingView(ui.View):
    """Vista principal del panel de logs"""
    
    def __init__(self, bot: commands.Bot, guild_id: int, config_data: dict):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.config_data = config_data
    
    def get_embed(self, guild: discord.Guild) -> discord.Embed:
        """Generar embed del panel"""
        channel_id = self.config_data.get("channel")
        enabled_events = self.config_data.get("events", [])
        category_channels = self.config_data.get("category_channels", {})
        
        embed = discord.Embed(
            title="📋 Sistema de Logs",
            color=config.BLURPLE_COLOR
        )
        
        # Estado del canal general
        if channel_id:
            channel = guild.get_channel(channel_id)
            channel_status = f"✅ {channel.mention}" if channel else "⚠️ Canal no encontrado"
        else:
            channel_status = "❌ No configurado"
        
        embed.add_field(
            name="📍 Canal General",
            value=channel_status,
            inline=False
        )
        
        # Mostrar canales por categoría si hay alguno configurado
        if category_channels:
            cat_lines = []
            for cat_name, cat_channel_id in category_channels.items():
                cat_channel = guild.get_channel(cat_channel_id)
                if cat_channel:
                    cat_emoji = CATEGORIES.get(cat_name, {}).get("emoji", "📁")
                    cat_lines.append(f"{cat_emoji} **{cat_name}:** {cat_channel.mention}")
            
            if cat_lines:
                embed.add_field(
                    name="📂 Canales por Categoría",
                    value="\n".join(cat_lines),
                    inline=False
                )
        
        # Mostrar eventos por categoría
        for cat_name, cat_info in CATEGORIES.items():
            events_in_cat = [e for e, info in LOG_EVENTS.items() if info["category"] == cat_name]
            
            lines = []
            for event in events_in_cat:
                info = LOG_EVENTS[event]
                status = "✅" if event in enabled_events else "❌"
                lines.append(f"{status} {info['emoji']} {info['name']}")
            
            embed.add_field(
                name=f"{cat_info['emoji']} {cat_name}",
                value="\n".join(lines) if lines else "Sin eventos",
                inline=True
            )
        
        # Contador
        total = len(LOG_EVENTS)
        active = len([e for e in enabled_events if e in LOG_EVENTS])
        embed.set_footer(text=f"📊 {active}/{total} eventos activos • Usa los botones para configurar")
        
        return embed
    
    async def toggle_category(self, interaction: discord.Interaction, category: str):
        """Toggle todos los eventos de una categoría"""
        events_in_cat = [e for e, info in LOG_EVENTS.items() if info["category"] == category]
        enabled_events = set(self.config_data.get("events", []))
        
        # Si todos están activos, desactivar todos. Si no, activar todos.
        all_active = all(e in enabled_events for e in events_in_cat)
        
        if all_active:
            # Desactivar todos
            for event in events_in_cat:
                enabled_events.discard(event)
        else:
            # Activar todos
            for event in events_in_cat:
                enabled_events.add(event)
        
        self.config_data["events"] = list(enabled_events)
        
        await database.logging.update_one(
            {"guild_id": self.guild_id},
            {"$set": {"events": list(enabled_events)}},
            upsert=True
        )
        
        cog = self.bot.get_cog("Logging")
        if cog:
            await cog.invalidate_cache(self.guild_id)
        
        embed = self.get_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)
    
    @ui.button(label="Mensajes", emoji="💬", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_messages(self, interaction: discord.Interaction, button: ui.Button):
        await self.toggle_category(interaction, "Mensajes")
    
    @ui.button(label="Miembros", emoji="👤", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_members(self, interaction: discord.Interaction, button: ui.Button):
        await self.toggle_category(interaction, "Miembros")
    
    @ui.button(label="Servidor", emoji="🏠", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_server(self, interaction: discord.Interaction, button: ui.Button):
        await self.toggle_category(interaction, "Servidor")
    
    @ui.button(label="Voz", emoji="🔊", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_voice(self, interaction: discord.Interaction, button: ui.Button):
        await self.toggle_category(interaction, "Voz")
    
    @ui.button(label="Moderación", emoji="🔨", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_moderation(self, interaction: discord.Interaction, button: ui.Button):
        await self.toggle_category(interaction, "Moderación")
    
    @ui.button(label="Canal", emoji="📍", style=discord.ButtonStyle.primary, row=1)
    async def set_channel(self, interaction: discord.Interaction, button: ui.Button):
        """Configurar canal de logs general"""
        view = ui.View(timeout=60)
        
        select = ui.ChannelSelect(
            placeholder="Selecciona el canal de logs general...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )
        
        async def select_callback(select_interaction: discord.Interaction):
            channel = select.values[0]
            self.config_data["channel"] = channel.id
            
            await database.logging.update_one(
                {"guild_id": self.guild_id},
                {"$set": {"channel": channel.id}},
                upsert=True
            )
            
            cog = self.bot.get_cog("Logging")
            if cog:
                await cog.invalidate_cache(self.guild_id)
            
            # Actualizar el embed del panel
            embed = self.get_embed(select_interaction.guild)
            await interaction.message.edit(embed=embed, view=self)
            
            await select_interaction.response.send_message(
                embed=success_embed(f"✅ Canal general de logs: {channel.mention}"),
                ephemeral=True
            )
        
        select.callback = select_callback
        view.add_item(select)
        
        # Botón para quitar canal general
        remove_btn = ui.Button(
            label="Quitar canal general",
            emoji="🗑️",
            style=discord.ButtonStyle.danger
        )
        
        async def remove_callback(remove_interaction: discord.Interaction):
            self.config_data.pop("channel", None)
            
            await database.logging.update_one(
                {"guild_id": self.guild_id},
                {"$unset": {"channel": ""}}
            )
            
            cog = self.bot.get_cog("Logging")
            if cog:
                await cog.invalidate_cache(self.guild_id)
            
            # Actualizar el embed del panel
            embed = self.get_embed(remove_interaction.guild)
            await interaction.message.edit(embed=embed, view=self)
            
            await remove_interaction.response.send_message(
                embed=success_embed("✅ Canal general de logs eliminado"),
                ephemeral=True
            )
        
        remove_btn.callback = remove_callback
        view.add_item(remove_btn)
        
        await interaction.response.send_message(
            "**📍 Canal General**\nSelecciona el canal donde se enviarán los logs (por defecto para todas las categorías):\n\n*El canal general es opcional si tienes canales por categoría configurados.*",
            view=view,
            ephemeral=True
        )
    
    @ui.button(label="Por Categoría", emoji="📂", style=discord.ButtonStyle.primary, row=1)
    async def set_category_channels(self, interaction: discord.Interaction, button: ui.Button):
        """Configurar canales por categoría"""
        view = ui.View(timeout=120)
        view.add_item(CategoryChannelSelect(self))
        
        # Mostrar configuración actual
        category_channels = self.config_data.get("category_channels", {})
        current_config = []
        for cat_name, cat_channel_id in category_channels.items():
            cat_channel = interaction.guild.get_channel(cat_channel_id)
            if cat_channel:
                cat_emoji = CATEGORIES.get(cat_name, {}).get("emoji", "📁")
                current_config.append(f"{cat_emoji} **{cat_name}:** {cat_channel.mention}")
        
        desc = "**Configuración actual:**\n" + ("\n".join(current_config) if current_config else "*Sin canales por categoría*")
        desc += "\n\n*Las categorías sin canal usarán el canal general.*"
        
        await interaction.response.send_message(
            f"**📂 Canales por Categoría**\n{desc}\n\nSelecciona una categoría para configurar:",
            view=view,
            ephemeral=True
        )
    
    @ui.button(label="Todo ON", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def enable_all(self, interaction: discord.Interaction, button: ui.Button):
        """Activar todos los eventos"""
        all_events = list(LOG_EVENTS.keys())
        self.config_data["events"] = all_events
        
        await database.logging.update_one(
            {"guild_id": self.guild_id},
            {"$set": {"events": all_events}},
            upsert=True
        )
        
        cog = self.bot.get_cog("Logging")
        if cog:
            await cog.invalidate_cache(self.guild_id)
        
        embed = self.get_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)
    
    @ui.button(label="Todo OFF", emoji="❌", style=discord.ButtonStyle.danger, row=1)
    async def disable_all(self, interaction: discord.Interaction, button: ui.Button):
        """Desactivar todos los eventos"""
        self.config_data["events"] = []
        
        await database.logging.update_one(
            {"guild_id": self.guild_id},
            {"$set": {"events": []}},
            upsert=True
        )
        
        cog = self.bot.get_cog("Logging")
        if cog:
            await cog.invalidate_cache(self.guild_id)
        
        embed = self.get_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)
    
    @ui.button(label="Test", emoji="🧪", style=discord.ButtonStyle.secondary, row=1)
    async def test_logs(self, interaction: discord.Interaction, button: ui.Button):
        """Enviar log de prueba a todos los canales configurados"""
        channel_id = self.config_data.get("channel")
        category_channels = self.config_data.get("category_channels", {})
        
        if not channel_id and not category_channels:
            return await interaction.response.send_message(
                embed=error_embed("Primero configura un canal de logs"),
                ephemeral=True
            )
        
        embed = discord.Embed(
            title="🧪 Log de Prueba",
            description="Si ves este mensaje, los logs están funcionando correctamente.",
            color=config.SUCCESS_COLOR,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"Probado por {interaction.user}")
        
        sent_to = []
        errors = []
        
        # Enviar al canal general
        if channel_id:
            channel = interaction.guild.get_channel(channel_id)
            if channel:
                try:
                    test_embed = embed.copy()
                    test_embed.title = "🧪 Log de Prueba (Canal General)"
                    await channel.send(embed=test_embed)
                    sent_to.append(f"📍 General: {channel.mention}")
                except discord.HTTPException as e:
                    errors.append(f"📍 General: {e}")
            else:
                errors.append("📍 General: Canal no encontrado")
        
        # Enviar a canales por categoría
        for cat_name, cat_channel_id in category_channels.items():
            cat_channel = interaction.guild.get_channel(cat_channel_id)
            if cat_channel:
                try:
                    test_embed = embed.copy()
                    test_embed.title = f"🧪 Log de Prueba ({cat_name})"
                    await cat_channel.send(embed=test_embed)
                    sent_to.append(f"{CATEGORIES[cat_name]['emoji']} {cat_name}: {cat_channel.mention}")
                except discord.HTTPException as e:
                    errors.append(f"{CATEGORIES[cat_name]['emoji']} {cat_name}: {e}")
            else:
                errors.append(f"{CATEGORIES[cat_name]['emoji']} {cat_name}: Canal no encontrado")
        
        # Crear respuesta
        response_lines = []
        if sent_to:
            response_lines.append("**✅ Enviados:**\n" + "\n".join(sent_to))
        if errors:
            response_lines.append("**❌ Errores:**\n" + "\n".join(errors))
        
        await interaction.response.send_message(
            "\n\n".join(response_lines) if response_lines else "No hay canales configurados",
            ephemeral=True
        )


class Logging(commands.Cog):
    """📋 Sistema de logs del servidor"""
    
    emoji = "📋"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._log_channels: dict[int, dict] = {}  # guild_id -> config
    
    async def invalidate_cache(self, guild_id: int):
        """Invalidar caché de logging"""
        if guild_id in self._log_channels:
            del self._log_channels[guild_id]
        await cache.invalidate_logging(guild_id)
    
    async def get_log_config(self, guild_id: int) -> dict:
        """Obtener configuración de logs de un servidor con caché Redis"""
        # Primero cache local
        if guild_id in self._log_channels:
            return self._log_channels[guild_id]
        
        # Luego Redis
        cached = await cache.get_logging_config(guild_id)
        if cached:
            self._log_channels[guild_id] = cached
            return cached
        
        # Finalmente base de datos
        doc = await database.logging.find_one({"guild_id": guild_id})
        
        if doc:
            self._log_channels[guild_id] = doc
            # Guardar en Redis (sin _id)
            cache_doc = {k: v for k, v in doc.items() if k != "_id"}
            await cache.set_logging_config(guild_id, cache_doc)
        else:
            self._log_channels[guild_id] = {}
        
        return self._log_channels[guild_id]
    
    async def is_event_enabled(self, guild_id: int, event: str) -> bool:
        """Verificar si un evento está habilitado"""
        config_data = await self.get_log_config(guild_id)
        events = config_data.get("events", [])
        return event in events
    
    async def get_log_channel(self, guild: discord.Guild, event: str = None) -> Optional[discord.TextChannel]:
        """
        Obtener el canal de logs para un evento.
        
        Si el evento tiene una categoría con canal específico, usa ese.
        De lo contrario, usa el canal general.
        """
        config_data = await self.get_log_config(guild.id)
        
        # Si hay evento, buscar si la categoría tiene canal específico
        if event and event in LOG_EVENTS:
            category = LOG_EVENTS[event]["category"]
            category_channels = config_data.get("category_channels", {})
            
            if category in category_channels:
                channel_id = category_channels[category]
                channel = guild.get_channel(channel_id)
                if channel:
                    return channel
        
        # Fallback al canal general
        channel_id = config_data.get("channel")
        if channel_id:
            return guild.get_channel(channel_id)
        return None
    
    async def send_log(self, guild: discord.Guild, event: str, embed: discord.Embed):
        """Enviar un log si el evento está habilitado"""
        if not await self.is_event_enabled(guild.id, event):
            return
        
        channel = await self.get_log_channel(guild, event)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass
    
    # === LISTENERS DE MENSAJES ===
    
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Log de mensajes eliminados"""
        if message.author.bot or not message.guild:
            return
        
        embed = discord.Embed(
            title="🗑️ Mensaje Eliminado",
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="Canal", value=message.channel.mention, inline=True)
        embed.add_field(name="Autor", value=message.author.mention, inline=True)
        
        if message.content:
            embed.add_field(name="Contenido", value=message.content[:1024], inline=False)
        
        if message.attachments:
            files = "\n".join(f"• {a.filename}" for a in message.attachments[:5])
            embed.add_field(name="📎 Archivos", value=files, inline=False)
        
        embed.set_footer(text=f"Mensaje ID: {message.id} • Usuario ID: {message.author.id}")
        
        await self.send_log(message.guild, "message_delete", embed)
    
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Log de mensajes editados"""
        if before.author.bot or not before.guild:
            return
        
        if before.content == after.content:
            return
        
        embed = discord.Embed(
            title="✏️ Mensaje Editado",
            color=0xFEE75C,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
        embed.add_field(name="Canal", value=before.channel.mention, inline=True)
        embed.add_field(name="Autor", value=before.author.mention, inline=True)
        embed.add_field(name="Link", value=f"[Ir al mensaje]({after.jump_url})", inline=True)
        embed.add_field(name="📝 Antes", value=before.content[:500] or "*Vacío*", inline=False)
        embed.add_field(name="📝 Después", value=after.content[:500] or "*Vacío*", inline=False)
        embed.set_footer(text=f"Usuario ID: {before.author.id}")
        
        await self.send_log(before.guild, "message_edit", embed)
    
    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        """Log de eliminación masiva"""
        if not messages:
            return
        
        guild = messages[0].guild
        channel = messages[0].channel
        
        embed = discord.Embed(
            title="🧹 Eliminación Masiva",
            description=f"**{len(messages)}** mensajes eliminados en {channel.mention}",
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        
        authors = set(m.author for m in messages if m.author)
        if authors:
            embed.add_field(
                name="Autores afectados",
                value=", ".join(str(a) for a in list(authors)[:10]),
                inline=False
            )
        
        await self.send_log(guild, "message_bulk_delete", embed)
    
    # === LISTENERS DE MIEMBROS ===
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Log de miembro que se une"""
        embed = discord.Embed(
            title="📥 Miembro Entró",
            color=0x57F287,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="Cuenta creada", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
        embed.add_field(name="Miembro #", value=f"`{member.guild.member_count}`", inline=True)
        
        account_age = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
        if account_age < 7:
            embed.add_field(name="⚠️ Cuenta Nueva", value=f"Creada hace **{account_age}** días", inline=False)
            embed.color = 0xFEE75C
        
        await self.send_log(member.guild, "member_join", embed)
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Log de miembro que sale"""
        embed = discord.Embed(
            title="📤 Miembro Salió",
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(
            name="Se unió",
            value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Desconocido",
            inline=True
        )
        embed.add_field(name="Miembros", value=f"`{member.guild.member_count}`", inline=True)
        
        roles = [r.mention for r in member.roles[1:]]
        if roles:
            embed.add_field(name="Roles", value=", ".join(roles[:10]), inline=False)
        
        await self.send_log(member.guild, "member_leave", embed)
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Log de actualizaciones de miembro"""
        # Cambio de nickname
        if before.nick != after.nick:
            embed = discord.Embed(
                title="📝 Apodo Cambiado",
                color=0x5865F2,
                timestamp=datetime.utcnow()
            )
            embed.set_author(name=str(after), icon_url=after.display_avatar.url)
            embed.add_field(name="Usuario", value=after.mention, inline=True)
            embed.add_field(name="Antes", value=f"`{before.nick or 'Sin apodo'}`", inline=True)
            embed.add_field(name="Después", value=f"`{after.nick or 'Sin apodo'}`", inline=True)
            embed.set_footer(text=f"ID: {after.id}")
            
            await self.send_log(after.guild, "member_nick", embed)
        
        # Cambio de roles
        if before.roles != after.roles:
            added = set(after.roles) - set(before.roles)
            removed = set(before.roles) - set(after.roles)
            
            if added or removed:
                embed = discord.Embed(
                    title="🎭 Roles Actualizados",
                    color=0x5865F2,
                    timestamp=datetime.utcnow()
                )
                embed.set_author(name=str(after), icon_url=after.display_avatar.url)
                embed.add_field(name="Usuario", value=after.mention, inline=False)
                
                if added:
                    embed.add_field(name="➕ Añadidos", value=", ".join(r.mention for r in added), inline=True)
                if removed:
                    embed.add_field(name="➖ Removidos", value=", ".join(r.mention for r in removed), inline=True)
                
                embed.set_footer(text=f"ID: {after.id}")
                
                await self.send_log(after.guild, "member_roles", embed)
        
        # Cambio de avatar de servidor
        if before.guild_avatar != after.guild_avatar:
            embed = discord.Embed(
                title="🖼️ Avatar del Servidor Cambiado",
                color=0x5865F2,
                timestamp=datetime.utcnow()
            )
            embed.set_author(name=str(after), icon_url=after.display_avatar.url)
            embed.add_field(name="Usuario", value=after.mention, inline=True)
            
            if after.guild_avatar:
                embed.set_thumbnail(url=after.guild_avatar.url)
            
            embed.set_footer(text=f"ID: {after.id}")
            
            await self.send_log(after.guild, "member_avatar", embed)
    
    # === LISTENERS DEL SERVIDOR ===
    
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        """Log de canal creado"""
        embed = discord.Embed(
            title="📁 Canal Creado",
            color=0x57F287,
            timestamp=datetime.utcnow()
        )
        
        type_names = {
            discord.ChannelType.text: "📝 Texto",
            discord.ChannelType.voice: "🔊 Voz",
            discord.ChannelType.category: "📂 Categoría",
            discord.ChannelType.stage_voice: "🎤 Escenario",
            discord.ChannelType.forum: "💬 Foro"
        }
        
        embed.add_field(name="Canal", value=getattr(channel, 'mention', channel.name), inline=True)
        embed.add_field(name="Tipo", value=type_names.get(channel.type, str(channel.type)), inline=True)
        embed.add_field(name="ID", value=f"`{channel.id}`", inline=True)
        
        try:
            async for entry in channel.guild.audit_logs(action=discord.AuditLogAction.channel_create, limit=1):
                if entry.target.id == channel.id:
                    embed.add_field(name="Creado por", value=entry.user.mention, inline=True)
                    break
        except:
            pass
        
        await self.send_log(channel.guild, "channel_create", embed)
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        """Log de canal eliminado y limpieza de configuración"""
        # Limpiar configuración si el canal eliminado era un canal de logs
        config_data = await self.get_log_config(channel.guild.id)
        updates = {}
        
        # Verificar si era el canal general
        if config_data.get("channel") == channel.id:
            updates["channel"] = ""
        
        # Verificar si era un canal de categoría
        category_channels = config_data.get("category_channels", {})
        for cat_name, cat_channel_id in list(category_channels.items()):
            if cat_channel_id == channel.id:
                updates[f"category_channels.{cat_name}"] = ""
        
        # Aplicar cambios si hay algo que limpiar
        if updates:
            await database.logging.update_one(
                {"guild_id": channel.guild.id},
                {"$unset": updates}
            )
            await self.invalidate_cache(channel.guild.id)
        
        # Enviar log del canal eliminado
        embed = discord.Embed(
            title="🗑️ Canal Eliminado",
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        
        type_names = {
            discord.ChannelType.text: "📝 Texto",
            discord.ChannelType.voice: "🔊 Voz",
            discord.ChannelType.category: "📂 Categoría",
            discord.ChannelType.stage_voice: "🎤 Escenario",
            discord.ChannelType.forum: "💬 Foro"
        }
        
        embed.add_field(name="Nombre", value=f"`{channel.name}`", inline=True)
        embed.add_field(name="Tipo", value=type_names.get(channel.type, str(channel.type)), inline=True)
        embed.add_field(name="ID", value=f"`{channel.id}`", inline=True)
        
        try:
            async for entry in channel.guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=1):
                if entry.target.id == channel.id:
                    embed.add_field(name="Eliminado por", value=entry.user.mention, inline=True)
                    break
        except:
            pass
        
        await self.send_log(channel.guild, "channel_delete", embed)
    
    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        """Log de canal modificado"""
        changes = []
        
        if before.name != after.name:
            changes.append(f"**Nombre:** `{before.name}` → `{after.name}`")
        
        if hasattr(before, 'topic') and hasattr(after, 'topic'):
            if before.topic != after.topic:
                changes.append(f"**Tema:** `{before.topic or 'Sin tema'}` → `{after.topic or 'Sin tema'}`")
        
        if hasattr(before, 'slowmode_delay') and hasattr(after, 'slowmode_delay'):
            if before.slowmode_delay != after.slowmode_delay:
                changes.append(f"**Slowmode:** `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")
        
        if not changes:
            return
        
        embed = discord.Embed(
            title="⚙️ Canal Modificado",
            description=getattr(after, 'mention', after.name),
            color=0xFEE75C,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Cambios", value="\n".join(changes), inline=False)
        
        try:
            async for entry in after.guild.audit_logs(action=discord.AuditLogAction.channel_update, limit=1):
                if entry.target.id == after.id:
                    embed.add_field(name="Modificado por", value=entry.user.mention, inline=True)
                    break
        except:
            pass
        
        await self.send_log(after.guild, "channel_update", embed)
    
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        """Log de rol creado"""
        embed = discord.Embed(
            title="🎨 Rol Creado",
            color=role.color if role.color.value else 0x57F287,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Rol", value=role.mention, inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="ID", value=f"`{role.id}`", inline=True)
        
        try:
            async for entry in role.guild.audit_logs(action=discord.AuditLogAction.role_create, limit=1):
                if entry.target.id == role.id:
                    embed.add_field(name="Creado por", value=entry.user.mention, inline=True)
                    break
        except:
            pass
        
        await self.send_log(role.guild, "role_create", embed)
    
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        """Log de rol eliminado"""
        embed = discord.Embed(
            title="🗑️ Rol Eliminado",
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Nombre", value=f"`{role.name}`", inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="ID", value=f"`{role.id}`", inline=True)
        
        try:
            async for entry in role.guild.audit_logs(action=discord.AuditLogAction.role_delete, limit=1):
                if entry.target.id == role.id:
                    embed.add_field(name="Eliminado por", value=entry.user.mention, inline=True)
                    break
        except:
            pass
        
        await self.send_log(role.guild, "role_delete", embed)
    
    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        """Log de rol modificado"""
        changes = []
        
        if before.name != after.name:
            changes.append(f"**Nombre:** `{before.name}` → `{after.name}`")
        if before.color != after.color:
            changes.append(f"**Color:** `{before.color}` → `{after.color}`")
        if before.hoist != after.hoist:
            changes.append(f"**Separado:** `{before.hoist}` → `{after.hoist}`")
        if before.mentionable != after.mentionable:
            changes.append(f"**Mencionable:** `{before.mentionable}` → `{after.mentionable}`")
        
        if not changes:
            return
        
        embed = discord.Embed(
            title="⚙️ Rol Modificado",
            description=after.mention,
            color=after.color if after.color.value else 0xFEE75C,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Cambios", value="\n".join(changes), inline=False)
        
        try:
            async for entry in after.guild.audit_logs(action=discord.AuditLogAction.role_update, limit=1):
                if entry.target.id == after.id:
                    embed.add_field(name="Modificado por", value=entry.user.mention, inline=True)
                    break
        except:
            pass
        
        await self.send_log(after.guild, "role_update", embed)
    
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: list, after: list):
        """Log de emojis actualizados"""
        added = set(after) - set(before)
        removed = set(before) - set(after)
        
        if not added and not removed:
            return
        
        embed = discord.Embed(
            title="😀 Emojis Actualizados",
            color=0xFEE75C,
            timestamp=datetime.utcnow()
        )
        
        if added:
            embed.add_field(
                name="➕ Añadidos",
                value=" ".join(str(e) for e in list(added)[:10]) or "Ninguno",
                inline=False
            )
        if removed:
            embed.add_field(
                name="➖ Eliminados",
                value=", ".join(f"`:{e.name}:`" for e in list(removed)[:10]) or "Ninguno",
                inline=False
            )
        
        await self.send_log(guild, "emoji_update", embed)
    
    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        """Log de invitación creada"""
        embed = discord.Embed(
            title="🔗 Invitación Creada",
            color=0x57F287,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Código", value=f"`{invite.code}`", inline=True)
        embed.add_field(name="Canal", value=invite.channel.mention, inline=True)
        embed.add_field(name="Creador", value=invite.inviter.mention if invite.inviter else "Desconocido", inline=True)
        
        if invite.max_uses:
            embed.add_field(name="Usos máximos", value=str(invite.max_uses), inline=True)
        if invite.max_age:
            hours = invite.max_age // 3600
            embed.add_field(name="Expira en", value=f"{hours}h" if hours else "Nunca", inline=True)
        
        await self.send_log(invite.guild, "invite_create", embed)
    
    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        """Log de invitación eliminada"""
        embed = discord.Embed(
            title="🔗 Invitación Eliminada",
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Código", value=f"`{invite.code}`", inline=True)
        embed.add_field(name="Canal", value=invite.channel.mention if invite.channel else "Desconocido", inline=True)
        
        await self.send_log(invite.guild, "invite_delete", embed)
    
    # === LISTENERS DE VOZ ===
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Log de actividad de voz"""
        
        # Cambio de canal
        if before.channel != after.channel:
            if before.channel is None:
                # Entró a voz
                embed = discord.Embed(
                    title="🔊 Entró a Voz",
                    color=0x57F287,
                    timestamp=datetime.utcnow()
                )
                embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                embed.add_field(name="Usuario", value=member.mention, inline=True)
                embed.add_field(name="Canal", value=after.channel.mention, inline=True)
                embed.set_footer(text=f"ID: {member.id}")
                
                await self.send_log(member.guild, "voice_join", embed)
            
            elif after.channel is None:
                # Salió de voz
                embed = discord.Embed(
                    title="🔇 Salió de Voz",
                    color=0xED4245,
                    timestamp=datetime.utcnow()
                )
                embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                embed.add_field(name="Usuario", value=member.mention, inline=True)
                embed.add_field(name="Canal", value=before.channel.mention, inline=True)
                embed.set_footer(text=f"ID: {member.id}")
                
                await self.send_log(member.guild, "voice_leave", embed)
            
            else:
                # Cambió de canal
                embed = discord.Embed(
                    title="🔀 Cambió de Canal",
                    color=0x5865F2,
                    timestamp=datetime.utcnow()
                )
                embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                embed.add_field(name="Usuario", value=member.mention, inline=True)
                embed.add_field(name="De", value=before.channel.mention, inline=True)
                embed.add_field(name="A", value=after.channel.mention, inline=True)
                embed.set_footer(text=f"ID: {member.id}")
                
                await self.send_log(member.guild, "voice_move", embed)
        
        # Mute/Unmute
        if before.self_mute != after.self_mute or before.mute != after.mute:
            is_muted = after.self_mute or after.mute
            embed = discord.Embed(
                title=f"🎙️ {'Muteado' if is_muted else 'Desmuteado'}",
                color=0xED4245 if is_muted else 0x57F287,
                timestamp=datetime.utcnow()
            )
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            embed.add_field(name="Usuario", value=member.mention, inline=True)
            if after.channel:
                embed.add_field(name="Canal", value=after.channel.mention, inline=True)
            embed.set_footer(text=f"ID: {member.id}")
            
            await self.send_log(member.guild, "voice_mute", embed)
        
        # Deafen/Undeafen
        if before.self_deaf != after.self_deaf or before.deaf != after.deaf:
            is_deaf = after.self_deaf or after.deaf
            embed = discord.Embed(
                title=f"🎧 {'Ensordecido' if is_deaf else 'Desensordecido'}",
                color=0xED4245 if is_deaf else 0x57F287,
                timestamp=datetime.utcnow()
            )
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            embed.add_field(name="Usuario", value=member.mention, inline=True)
            if after.channel:
                embed.add_field(name="Canal", value=after.channel.mention, inline=True)
            embed.set_footer(text=f"ID: {member.id}")
            
            await self.send_log(member.guild, "voice_deafen", embed)
    
    # === LISTENERS DE MODERACIÓN (eventos de Discord) ===
    
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        """Log de ban (evento de Discord)"""
        embed = discord.Embed(
            title="🔨 Usuario Baneado",
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{user.mention}\n`{user.id}`", inline=True)
        
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
                if entry.target.id == user.id:
                    embed.add_field(name="Moderador", value=entry.user.mention, inline=True)
                    if entry.reason:
                        embed.add_field(name="Razón", value=entry.reason, inline=False)
                    break
        except:
            pass
        
        await self.send_log(guild, "mod_ban", embed)
    
    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        """Log de unban (evento de Discord)"""
        embed = discord.Embed(
            title="✅ Usuario Desbaneado",
            color=0x57F287,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{user.mention}\n`{user.id}`", inline=True)
        
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=1):
                if entry.target.id == user.id:
                    embed.add_field(name="Moderador", value=entry.user.mention, inline=True)
                    break
        except:
            pass
        
        await self.send_log(guild, "mod_unban", embed)
    
    # === COMANDOS ===
    
    @commands.group(
        name="logs",
        aliases=["log", "logging"],
        brief="Configurar logs del servidor",
        invoke_without_command=True
    )
    @commands.has_permissions(administrator=True)
    async def logs(self, ctx: commands.Context):
        """
        Configurar el sistema de logs del servidor.
        
        Abre un panel interactivo para activar/desactivar eventos específicos.
        """
        config_data = await self.get_log_config(ctx.guild.id)
        view = LoggingView(self.bot, ctx.guild.id, config_data)
        embed = view.get_embed(ctx.guild)
        
        await ctx.send(embed=embed, view=view)
    
    @logs.command(name="channel", aliases=["canal", "set"])
    @commands.has_permissions(administrator=True)
    async def logs_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """
        Configurar el canal de logs general.
        
        **Uso:** 
        ;logs channel #canal - Configurar canal
        ;logs channel - Ver canal actual
        """
        if channel is None:
            # Mostrar canal actual
            config_data = await self.get_log_config(ctx.guild.id)
            channel_id = config_data.get("channel")
            
            if channel_id:
                ch = ctx.guild.get_channel(channel_id)
                if ch:
                    return await ctx.send(embed=success_embed(f"📍 Canal de logs general: {ch.mention}"))
                else:
                    return await ctx.send(embed=warning_embed("⚠️ El canal configurado ya no existe"))
            else:
                return await ctx.send(embed=warning_embed(f"No hay canal general configurado.\nUsa `{ctx.clean_prefix}logs channel #canal` para configurar"))
        
        await database.logging.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"channel": channel.id}},
            upsert=True
        )
        
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed(f"✅ Canal de logs: {channel.mention}"))
    
    @logs.command(name="channel_remove", aliases=["canal_remove", "unset"])
    @commands.has_permissions(administrator=True)
    async def logs_channel_remove(self, ctx: commands.Context):
        """
        Quitar el canal de logs general.
        
        Las categorías con canales específicos seguirán funcionando.
        
        **Uso:** ;logs channel_remove
        """
        await database.logging.update_one(
            {"guild_id": ctx.guild.id},
            {"$unset": {"channel": ""}}
        )
        
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed("✅ Canal de logs general eliminado"))
    
    @logs.command(name="enable", aliases=["on", "activar"])
    @commands.has_permissions(administrator=True)
    async def logs_enable(self, ctx: commands.Context, *, events: str = None):
        """
        Activar eventos de logs.
        
        **Uso:** 
        ;logs enable - Activa todos
        ;logs enable message_delete member_join - Activa específicos
        """
        if events:
            event_list = events.lower().split()
            valid_events = [e for e in event_list if e in LOG_EVENTS]
            
            if not valid_events:
                return await ctx.send(embed=error_embed("Ningún evento válido especificado"))
            
            await database.logging.update_one(
                {"guild_id": ctx.guild.id},
                {"$addToSet": {"events": {"$each": valid_events}}},
                upsert=True
            )
            
            msg = f"✅ Eventos activados: `{', '.join(valid_events)}`"
        else:
            all_events = list(LOG_EVENTS.keys())
            await database.logging.update_one(
                {"guild_id": ctx.guild.id},
                {"$set": {"events": all_events}},
                upsert=True
            )
            msg = "✅ **Todos los eventos** activados"
        
        await self.invalidate_cache(ctx.guild.id)
        await ctx.send(embed=success_embed(msg))
    
    @logs.command(name="disable", aliases=["off", "desactivar"])
    @commands.has_permissions(administrator=True)
    async def logs_disable(self, ctx: commands.Context, *, events: str = None):
        """
        Desactivar eventos de logs.
        
        **Uso:** 
        ;logs disable - Desactiva todos
        ;logs disable message_delete - Desactiva específico
        """
        if events:
            event_list = events.lower().split()
            valid_events = [e for e in event_list if e in LOG_EVENTS]
            
            if not valid_events:
                return await ctx.send(embed=error_embed("Ningún evento válido especificado"))
            
            await database.logging.update_one(
                {"guild_id": ctx.guild.id},
                {"$pull": {"events": {"$in": valid_events}}}
            )
            
            msg = f"❌ Eventos desactivados: `{', '.join(valid_events)}`"
        else:
            await database.logging.update_one(
                {"guild_id": ctx.guild.id},
                {"$set": {"events": []}}
            )
            msg = "❌ **Todos los eventos** desactivados"
        
        await self.invalidate_cache(ctx.guild.id)
        await ctx.send(embed=success_embed(msg))
    
    @logs.command(name="events", aliases=["list", "lista"])
    @commands.has_permissions(administrator=True)
    async def logs_events(self, ctx: commands.Context):
        """Ver lista de eventos disponibles."""
        embed = discord.Embed(
            title="📋 Eventos de Logs Disponibles",
            color=config.BLURPLE_COLOR
        )
        
        for cat_name, cat_info in CATEGORIES.items():
            events_in_cat = [e for e, info in LOG_EVENTS.items() if info["category"] == cat_name]
            lines = [f"`{e}` - {LOG_EVENTS[e]['name']}" for e in events_in_cat]
            embed.add_field(
                name=f"{cat_info['emoji']} {cat_name}",
                value="\n".join(lines),
                inline=False
            )
        
        await ctx.send(embed=embed)
    
    @logs.command(name="category", aliases=["categoria", "cat"])
    @commands.has_permissions(administrator=True)
    async def logs_category(self, ctx: commands.Context, category: str = None, channel: discord.TextChannel = None):
        """
        Configurar canal por categoría de logs.
        
        **Categorías:** Mensajes, Miembros, Servidor, Voz, Moderación
        
        **Uso:**
        ;logs category - Ver configuración actual
        ;logs category Mensajes #canal - Configurar canal para mensajes
        ;logs category Mensajes off - Quitar canal de categoría
        
        **Ejemplo:**
        ;logs category Moderación #mod-logs
        ;logs category Voz #voice-logs
        """
        config_data = await self.get_log_config(ctx.guild.id)
        category_channels = config_data.get("category_channels", {})
        
        if not category:
            # Mostrar configuración actual
            embed = discord.Embed(
                title="📂 Canales por Categoría",
                color=config.BLURPLE_COLOR
            )
            
            general_channel = config_data.get("channel")
            if general_channel:
                ch = ctx.guild.get_channel(general_channel)
                embed.add_field(
                    name="📍 Canal General",
                    value=ch.mention if ch else "⚠️ No encontrado",
                    inline=False
                )
            
            lines = []
            for cat_name, cat_info in CATEGORIES.items():
                if cat_name in category_channels:
                    cat_ch = ctx.guild.get_channel(category_channels[cat_name])
                    status = cat_ch.mention if cat_ch else "⚠️ No encontrado"
                else:
                    status = "*Canal general*"
                lines.append(f"{cat_info['emoji']} **{cat_name}:** {status}")
            
            embed.add_field(
                name="📂 Categorías",
                value="\n".join(lines),
                inline=False
            )
            
            embed.set_footer(text=f"Usa {ctx.clean_prefix}logs category <nombre> #canal para configurar")
            return await ctx.send(embed=embed)
        
        # Normalizar nombre de categoría
        category_normalized = category.title()
        if category_normalized not in CATEGORIES:
            return await ctx.send(embed=error_embed(
                f"Categoría inválida. Usa: `{', '.join(CATEGORIES.keys())}`"
            ))
        
        if channel is None:
            # Si no hay canal, mostrar estado de esa categoría
            if category_normalized in category_channels:
                cat_ch = ctx.guild.get_channel(category_channels[category_normalized])
                if cat_ch:
                    return await ctx.send(embed=success_embed(
                        f"{CATEGORIES[category_normalized]['emoji']} **{category_normalized}**: {cat_ch.mention}"
                    ))
            
            return await ctx.send(embed=warning_embed(
                f"{CATEGORIES[category_normalized]['emoji']} **{category_normalized}**: Usa canal general\n"
                f"Usa `{ctx.clean_prefix}logs category {category_normalized} #canal` para configurar"
            ))
        
        # Actualizar canal de categoría
        await database.logging.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {f"category_channels.{category_normalized}": channel.id}},
            upsert=True
        )
        
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed(
            f"✅ Canal de **{category_normalized}**: {channel.mention}"
        ))
    
    @logs.command(name="category_remove", aliases=["cat_remove", "catremove"])
    @commands.has_permissions(administrator=True)
    async def logs_category_remove(self, ctx: commands.Context, category: str):
        """
        Quitar canal específico de una categoría.
        
        La categoría volverá a usar el canal general.
        
        **Uso:** ;logs category_remove Mensajes
        """
        category_normalized = category.title()
        if category_normalized not in CATEGORIES:
            return await ctx.send(embed=error_embed(
                f"Categoría inválida. Usa: `{', '.join(CATEGORIES.keys())}`"
            ))
        
        await database.logging.update_one(
            {"guild_id": ctx.guild.id},
            {"$unset": {f"category_channels.{category_normalized}": ""}}
        )
        
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed(
            f"✅ **{category_normalized}** ahora usa el canal general"
        ))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Logging(bot))
