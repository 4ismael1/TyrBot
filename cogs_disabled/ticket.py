"""
Cog Tickets - Sistema de tickets de soporte
"""

from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional
from datetime import datetime
import io

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed


class TicketCloseView(discord.ui.View):
    """Vista para cerrar ticket"""
    
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
    
    @discord.ui.button(
        label="🔒 Cerrar Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:close"
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cerrar el ticket"""
        ticket = await database.tickets.find_one({
            "channel_id": interaction.channel.id
        })
        
        if not ticket:
            return await interaction.response.send_message(
                "Este no es un canal de ticket.",
                ephemeral=True
            )
        
        # Verificar permisos
        has_perm = (
            interaction.user.guild_permissions.manage_channels or
            interaction.user.id == ticket["user_id"]
        )
        
        if not has_perm:
            return await interaction.response.send_message(
                "No tienes permisos para cerrar este ticket.",
                ephemeral=True
            )
        
        await interaction.response.send_message("🔒 Cerrando ticket en 5 segundos...")
        
        # Guardar transcripción
        messages = []
        async for msg in interaction.channel.history(limit=500, oldest_first=True):
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            content = msg.content or "[Embed/Archivo]"
            messages.append(f"[{timestamp}] {msg.author}: {content}")
        
        transcript = "\n".join(messages)
        
        # Actualizar DB
        await database.tickets.update_one(
            {"channel_id": interaction.channel.id},
            {
                "$set": {
                    "closed": True,
                    "closed_at": datetime.utcnow(),
                    "closed_by": interaction.user.id
                }
            }
        )
        
        # Enviar transcripción al usuario si es posible
        try:
            user = interaction.guild.get_member(ticket["user_id"])
            if user:
                file = discord.File(
                    io.BytesIO(transcript.encode()),
                    filename=f"ticket-{ticket['ticket_number']}.txt"
                )
                embed = discord.Embed(
                    title="🎫 Ticket Cerrado",
                    description=f"Tu ticket #{ticket['ticket_number']} ha sido cerrado.",
                    color=discord.Color.red()
                )
                await user.send(embed=embed, file=file)
        except:
            pass
        
        # Borrar canal
        import asyncio
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket cerrado por {interaction.user}")


class TicketCreateView(discord.ui.View):
    """Vista para crear ticket"""
    
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
    
    @discord.ui.button(
        label="📩 Crear Ticket",
        style=discord.ButtonStyle.green,
        custom_id="ticket:create"
    )
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Crear un nuevo ticket"""
        # Obtener configuración
        settings = await database.ticket_settings.find_one({
            "guild_id": interaction.guild.id
        })
        
        if not settings:
            return await interaction.response.send_message(
                "El sistema de tickets no está configurado.",
                ephemeral=True
            )
        
        # Verificar límite de tickets abiertos
        open_tickets = await database.tickets.count_documents({
            "guild_id": interaction.guild.id,
            "user_id": interaction.user.id,
            "closed": False
        })
        
        if open_tickets >= 3:
            return await interaction.response.send_message(
                "Ya tienes 3 tickets abiertos. Cierra uno antes de crear otro.",
                ephemeral=True
            )
        
        # Obtener categoría
        category = interaction.guild.get_channel(settings.get("category_id"))
        if not category or not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message(
                "La categoría de tickets no existe. Contacta a un administrador.",
                ephemeral=True
            )
        
        # Obtener número de ticket
        last_ticket = await database.tickets.find_one(
            {"guild_id": interaction.guild.id},
            sort=[("ticket_number", -1)]
        )
        ticket_number = (last_ticket["ticket_number"] + 1) if last_ticket else 1
        
        # Crear canal
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True
            )
        }
        
        # Agregar rol de soporte
        if settings.get("support_role"):
            support_role = interaction.guild.get_role(settings["support_role"])
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True
                )
        
        try:
            channel = await category.create_text_channel(
                name=f"ticket-{ticket_number}",
                overwrites=overwrites,
                reason=f"Ticket creado por {interaction.user}"
            )
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                f"Error al crear ticket: {e}",
                ephemeral=True
            )
        
        # Guardar en DB
        await database.tickets.insert_one({
            "guild_id": interaction.guild.id,
            "channel_id": channel.id,
            "user_id": interaction.user.id,
            "ticket_number": ticket_number,
            "created_at": datetime.utcnow(),
            "closed": False,
            "closed_at": None,
            "closed_by": None
        })
        
        # Mensaje inicial
        embed = discord.Embed(
            title=f"🎫 Ticket #{ticket_number}",
            description=settings.get("welcome_message", 
                "Gracias por crear un ticket. Un miembro del equipo te atenderá pronto.\n\n"
                "Por favor, describe tu problema o consulta."),
            color=config.BLURPLE_COLOR
        )
        embed.set_footer(text=f"Creado por {interaction.user}")
        embed.timestamp = datetime.utcnow()
        
        view = TicketCloseView(self.bot)
        await channel.send(content=interaction.user.mention, embed=embed, view=view)
        
        await interaction.response.send_message(
            f"✅ Ticket creado: {channel.mention}",
            ephemeral=True
        )


class Tickets(commands.Cog):
    """🎫 Sistema de Tickets"""
    
    emoji = "🎫"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def cog_load(self):
        """Registrar vistas persistentes"""
        self.bot.add_view(TicketCreateView(self.bot))
        self.bot.add_view(TicketCloseView(self.bot))
    
    @commands.group(
        name="ticket",
        aliases=["tickets", "soporte"],
        brief="Sistema de tickets",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_guild=True)
    async def ticket(self, ctx: commands.Context):
        """Sistema de tickets de soporte"""
        embed = discord.Embed(
            title="🎫 Sistema de Tickets",
            description="Configura un sistema de soporte mediante tickets.",
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(
            name="Comandos",
            value=f"`{ctx.prefix}ticket setup` - Configurar sistema\n"
                  f"`{ctx.prefix}ticket panel [canal]` - Enviar panel de tickets\n"
                  f"`{ctx.prefix}ticket role <rol>` - Establecer rol de soporte\n"
                  f"`{ctx.prefix}ticket category <categoría>` - Establecer categoría\n"
                  f"`{ctx.prefix}ticket message <mensaje>` - Mensaje de bienvenida\n"
                  f"`{ctx.prefix}ticket close` - Cerrar ticket actual\n"
                  f"`{ctx.prefix}ticket add <usuario>` - Añadir usuario a ticket\n"
                  f"`{ctx.prefix}ticket remove <usuario>` - Quitar usuario de ticket",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @ticket.command(name="setup", aliases=["configure", "config"])
    @commands.has_permissions(administrator=True)
    async def ticket_setup(self, ctx: commands.Context):
        """Configuración inicial del sistema de tickets"""
        # Crear categoría si no existe
        settings = await database.ticket_settings.find_one({
            "guild_id": ctx.guild.id
        })
        
        if settings and settings.get("category_id"):
            category = ctx.guild.get_channel(settings["category_id"])
            if category:
                return await ctx.send(embed=warning_embed(
                    f"El sistema ya está configurado. Categoría: {category.mention}"
                ))
        
        # Crear categoría
        category = await ctx.guild.create_category(
            name="🎫 Tickets",
            reason="Setup de sistema de tickets"
        )
        
        # Guardar configuración
        await database.ticket_settings.update_one(
            {"guild_id": ctx.guild.id},
            {
                "$set": {
                    "guild_id": ctx.guild.id,
                    "category_id": category.id,
                    "support_role": None,
                    "welcome_message": "Gracias por crear un ticket. Un miembro del equipo te atenderá pronto.\n\nPor favor, describe tu problema o consulta."
                }
            },
            upsert=True
        )
        
        embed = success_embed(
            f"Sistema de tickets configurado!\n\n"
            f"**Categoría:** {category.mention}\n\n"
            f"Usa `{ctx.prefix}ticket panel` para enviar el panel de tickets."
        )
        
        await ctx.send(embed=embed)
    
    @ticket.command(name="panel", aliases=["embed", "send"])
    @commands.has_permissions(manage_guild=True)
    async def ticket_panel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Enviar panel de tickets a un canal"""
        channel = channel or ctx.channel
        
        settings = await database.ticket_settings.find_one({
            "guild_id": ctx.guild.id
        })
        
        if not settings:
            return await ctx.send(embed=error_embed(
                f"Primero configura el sistema con `{ctx.prefix}ticket setup`"
            ))
        
        embed = discord.Embed(
            title="🎫 Centro de Soporte",
            description="¿Necesitas ayuda? Haz clic en el botón de abajo para crear un ticket.\n\n"
                       "Un miembro del equipo te atenderá lo antes posible.",
            color=config.BLURPLE_COLOR
        )
        embed.set_footer(text=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        
        view = TicketCreateView(self.bot)
        await channel.send(embed=embed, view=view)
        
        if channel != ctx.channel:
            await ctx.send(embed=success_embed(f"Panel enviado a {channel.mention}"))
    
    @ticket.command(name="role", aliases=["supportrole"])
    @commands.has_permissions(administrator=True)
    async def ticket_role(self, ctx: commands.Context, role: discord.Role):
        """Establecer rol de soporte"""
        await database.ticket_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"support_role": role.id}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(
            f"Rol de soporte establecido: {role.mention}"
        ))
    
    @ticket.command(name="category", aliases=["cat"])
    @commands.has_permissions(administrator=True)
    async def ticket_category(self, ctx: commands.Context, category: discord.CategoryChannel):
        """Establecer categoría para tickets"""
        await database.ticket_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"category_id": category.id}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(
            f"Categoría establecida: {category.mention}"
        ))
    
    @ticket.command(name="message", aliases=["welcomemsg", "msg"])
    @commands.has_permissions(administrator=True)
    async def ticket_message(self, ctx: commands.Context, *, message: str):
        """Establecer mensaje de bienvenida"""
        if len(message) > 1000:
            return await ctx.send(embed=error_embed("El mensaje no puede tener más de 1000 caracteres"))
        
        await database.ticket_settings.update_one(
            {"guild_id": ctx.guild.id},
            {"$set": {"welcome_message": message}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed("Mensaje de bienvenida actualizado"))
    
    @ticket.command(name="close", aliases=["cerrar"])
    async def ticket_close(self, ctx: commands.Context):
        """Cerrar el ticket actual"""
        ticket = await database.tickets.find_one({
            "channel_id": ctx.channel.id,
            "closed": False
        })
        
        if not ticket:
            return await ctx.send(embed=error_embed("Este no es un canal de ticket"))
        
        # Verificar permisos
        has_perm = (
            ctx.author.guild_permissions.manage_channels or
            ctx.author.id == ticket["user_id"]
        )
        
        if not has_perm:
            return await ctx.send(embed=error_embed(
                "No tienes permisos para cerrar este ticket"
            ))
        
        await ctx.send("🔒 Cerrando ticket en 5 segundos...")
        
        # Guardar transcripción
        messages = []
        async for msg in ctx.channel.history(limit=500, oldest_first=True):
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            content = msg.content or "[Embed/Archivo]"
            messages.append(f"[{timestamp}] {msg.author}: {content}")
        
        transcript = "\n".join(messages)
        
        # Actualizar DB
        await database.tickets.update_one(
            {"channel_id": ctx.channel.id},
            {
                "$set": {
                    "closed": True,
                    "closed_at": datetime.utcnow(),
                    "closed_by": ctx.author.id
                }
            }
        )
        
        # Enviar transcripción
        try:
            user = ctx.guild.get_member(ticket["user_id"])
            if user:
                file = discord.File(
                    io.BytesIO(transcript.encode()),
                    filename=f"ticket-{ticket['ticket_number']}.txt"
                )
                embed = discord.Embed(
                    title="🎫 Ticket Cerrado",
                    description=f"Tu ticket #{ticket['ticket_number']} ha sido cerrado.",
                    color=discord.Color.red()
                )
                await user.send(embed=embed, file=file)
        except:
            pass
        
        import asyncio
        await asyncio.sleep(5)
        await ctx.channel.delete(reason=f"Ticket cerrado por {ctx.author}")
    
    @ticket.command(name="add", aliases=["adduser"])
    async def ticket_add(self, ctx: commands.Context, user: discord.Member):
        """Añadir usuario a un ticket"""
        ticket = await database.tickets.find_one({
            "channel_id": ctx.channel.id,
            "closed": False
        })
        
        if not ticket:
            return await ctx.send(embed=error_embed("Este no es un canal de ticket"))
        
        await ctx.channel.set_permissions(
            user,
            view_channel=True,
            send_messages=True,
            attach_files=True,
            embed_links=True
        )
        
        await ctx.send(embed=success_embed(f"{user.mention} añadido al ticket"))
    
    @ticket.command(name="remove", aliases=["removeuser"])
    async def ticket_remove(self, ctx: commands.Context, user: discord.Member):
        """Quitar usuario de un ticket"""
        ticket = await database.tickets.find_one({
            "channel_id": ctx.channel.id,
            "closed": False
        })
        
        if not ticket:
            return await ctx.send(embed=error_embed("Este no es un canal de ticket"))
        
        if user.id == ticket["user_id"]:
            return await ctx.send(embed=error_embed("No puedes quitar al creador del ticket"))
        
        await ctx.channel.set_permissions(user, overwrite=None)
        
        await ctx.send(embed=success_embed(f"{user.mention} quitado del ticket"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
