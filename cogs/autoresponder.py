"""
Cog AutoResponder - Sistema de respuestas automáticas
"""

from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional
import re

from config import config
from core import database, cache
from utils import success_embed, error_embed, warning_embed, paginate


class TriggerModal(discord.ui.Modal, title="Crear Auto-Respuesta"):
    """Modal para crear una auto-respuesta"""
    
    trigger = discord.ui.TextInput(
        label="Trigger (palabra/frase)",
        placeholder="Ej: hola, buenos días",
        max_length=100
    )
    
    response = discord.ui.TextInput(
        label="Respuesta",
        placeholder="Ej: ¡Hola {user}! Bienvenido a {server}",
        style=discord.TextStyle.paragraph,
        max_length=2000
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        self.interaction = interaction
        self.stop()


class AutoResponder(commands.Cog):
    """💬 Sistema de respuestas automáticas"""
    
    emoji = "💬"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache local de triggers por servidor (backup)
        self._triggers: dict[int, list[dict]] = {}
    
    async def load_triggers(self, guild_id: int) -> list[dict]:
        """Cargar triggers de un servidor (Redis primero, luego DB)"""
        # Intentar cache local
        if guild_id in self._triggers:
            return self._triggers[guild_id]
        
        # Intentar Redis
        cached = await cache.get_autoresponder_triggers(guild_id)
        if cached:
            self._triggers[guild_id] = cached
            return cached
        
        # Cargar de DB
        triggers = await database.autoresponder.find({
            "guild_id": guild_id,
            "enabled": True
        }).to_list(length=None)
        
        # Convertir ObjectId a string para serialización
        for t in triggers:
            t["_id"] = str(t["_id"])
        
        # Guardar en Redis y cache local
        if triggers:
            await cache.set_autoresponder_triggers(guild_id, triggers)
        self._triggers[guild_id] = triggers
        
        return triggers
    
    async def invalidate_cache(self, guild_id: int) -> None:
        """Invalidar caché de un servidor"""
        self._triggers.pop(guild_id, None)
        await cache.invalidate_autoresponder(guild_id)
    
    def parse_variables(self, text: str, message: discord.Message) -> str:
        """Reemplazar variables en el texto"""
        variables = {
            "{user}": message.author.mention,
            "{user.name}": message.author.name,
            "{user.display}": message.author.display_name,
            "{user.id}": str(message.author.id),
            "{server}": message.guild.name,
            "{server.id}": str(message.guild.id),
            "{channel}": message.channel.mention,
            "{channel.name}": message.channel.name,
        }
        
        for var, value in variables.items():
            text = text.replace(var, value)
        
        return text
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Detectar triggers y responder"""
        if message.author.bot or not message.guild:
            return
        
        triggers = await self.load_triggers(message.guild.id)
        
        if not triggers:
            return
        
        content = message.content.lower()
        
        for trigger in triggers:
            trigger_text = trigger["trigger"].lower()
            match_type = trigger.get("match_type", "contains")
            
            matched = False
            
            if match_type == "exact":
                matched = content == trigger_text
            elif match_type == "startswith":
                matched = content.startswith(trigger_text)
            elif match_type == "endswith":
                matched = content.endswith(trigger_text)
            elif match_type == "regex":
                try:
                    matched = bool(re.search(trigger["trigger"], message.content, re.IGNORECASE))
                except re.error:
                    pass
            else:  # contains
                matched = trigger_text in content
            
            if matched:
                response = self.parse_variables(trigger["response"], message)
                
                try:
                    if trigger.get("reply", True):
                        await message.reply(response, mention_author=False)
                    else:
                        await message.channel.send(response)
                except discord.HTTPException:
                    pass
                
                # Incrementar contador
                await database.autoresponder.update_one(
                    {"_id": trigger["_id"]},
                    {"$inc": {"uses": 1}}
                )
                
                # Solo responder al primer trigger que coincida
                break
    
    @commands.group(
        name="autoresponder",
        aliases=["ar", "autoresponse", "autoreply"],
        brief="Sistema de respuestas automáticas",
        invoke_without_command=True
    )
    @commands.has_permissions(manage_guild=True)
    async def autoresponder(self, ctx: commands.Context):
        """
        Configurar respuestas automáticas del servidor.
        
        Las respuestas automáticas permiten que el bot responda
        automáticamente cuando alguien escribe cierta palabra o frase.
        
        **Variables disponibles:**
        `{user}` - Mención del usuario
        `{user.name}` - Nombre del usuario
        `{user.display}` - Nombre visible del usuario
        `{server}` - Nombre del servidor
        `{channel}` - Mención del canal
        """
        await ctx.send_help(ctx.command)
    
    @autoresponder.command(name="add", aliases=["create", "new", "crear"])
    @commands.has_permissions(manage_guild=True)
    async def ar_add(self, ctx: commands.Context, trigger: str = None, *, response: str = None):
        """
        Añadir una auto-respuesta al servidor.
        
        Cuando alguien escriba el trigger, el bot responderá automáticamente.
        
        **Variables disponibles:**
        `{user}` - Mención del usuario
        `{user.name}` - Nombre del usuario  
        `{server}` - Nombre del servidor
        `{channel}` - Mención del canal
        
        **Ejemplos:**
        ;ar add hola ¡Hola {user}! Bienvenido
        ;ar add ayuda Usa ;help para ver comandos
        ;ar add tienda Visita nuestra tienda en discord.gg/ejemplo
        """
        if not trigger or not response:
            # Usar modal
            modal = TriggerModal()
            await ctx.send("Abriendo formulario... (si no aparece, usa ;ar add <trigger> <respuesta>)")
            
            # Para comandos híbridos necesitamos manejar esto diferente
            # Por ahora usamos el método tradicional
            return await ctx.send(embed=error_embed("Uso: `;ar add <trigger> <respuesta>`"))
        
        trigger = trigger.lower()
        
        # Verificar si existe
        existing = await database.autoresponder.find_one({
            "guild_id": ctx.guild.id,
            "trigger": trigger
        })
        
        if existing:
            return await ctx.send(embed=error_embed(f"Ya existe un trigger para `{trigger}`"))
        
        # Verificar límite (máx 50 por servidor)
        count = await database.autoresponder.count_documents({"guild_id": ctx.guild.id})
        if count >= 50:
            return await ctx.send(embed=error_embed("Has alcanzado el límite de 50 auto-respuestas"))
        
        await database.autoresponder.insert_one({
            "guild_id": ctx.guild.id,
            "trigger": trigger,
            "response": response,
            "match_type": "contains",
            "enabled": True,
            "reply": True,
            "uses": 0,
            "created_by": ctx.author.id,
            "created_at": discord.utils.utcnow()
        })
        
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed(f"Auto-respuesta creada para `{trigger}`"))
    
    @autoresponder.command(name="remove", aliases=["delete", "del", "eliminar"])
    @commands.has_permissions(manage_guild=True)
    async def ar_remove(self, ctx: commands.Context, *, trigger: str):
        """
        Eliminar una auto-respuesta existente.
        
        **Ejemplos:**
        ;ar remove hola
        ;ar delete ayuda
        """
        trigger = trigger.lower()
        
        result = await database.autoresponder.delete_one({
            "guild_id": ctx.guild.id,
            "trigger": trigger
        })
        
        if result.deleted_count == 0:
            return await ctx.send(embed=error_embed(f"No existe trigger para `{trigger}`"))
        
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed(f"Auto-respuesta `{trigger}` eliminada"))
    
    @autoresponder.command(name="edit", aliases=["editar", "modify"])
    @commands.has_permissions(manage_guild=True)
    async def ar_edit(self, ctx: commands.Context, trigger: str, *, response: str):
        """
        Editar la respuesta de un trigger existente.
        
        **Ejemplos:**
        ;ar edit hola Nueva respuesta de hola
        ;ar edit ayuda Nuevo mensaje de ayuda {user}
        """
        trigger = trigger.lower()
        
        result = await database.autoresponder.update_one(
            {"guild_id": ctx.guild.id, "trigger": trigger},
            {"$set": {"response": response}}
        )
        
        if result.matched_count == 0:
            return await ctx.send(embed=error_embed(f"No existe trigger para `{trigger}`"))
        
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed(f"Auto-respuesta `{trigger}` actualizada"))
    
    @autoresponder.command(name="list", aliases=["all", "lista"])
    @commands.has_permissions(manage_guild=True)
    async def ar_list(self, ctx: commands.Context):
        """
        Ver todas las auto-respuestas del servidor.
        
        Muestra el estado (✅/❌) y usos de cada trigger.
        """
        triggers = await database.autoresponder.find({
            "guild_id": ctx.guild.id
        }).sort("uses", -1).to_list(length=None)
        
        if not triggers:
            return await ctx.send(embed=warning_embed("No hay auto-respuestas configuradas"))
        
        embeds = []
        for i in range(0, len(triggers), 10):
            chunk = triggers[i:i+10]
            
            description = ""
            for t in chunk:
                status = "✅" if t["enabled"] else "❌"
                description += f"{status} `{t['trigger']}` - {t['uses']} usos\n"
            
            embed = discord.Embed(
                title="💬 Auto-Respuestas",
                description=description,
                color=config.BLURPLE_COLOR
            )
            embed.set_footer(text=f"Total: {len(triggers)} | Usa ;ar info <trigger> para más detalles")
            embeds.append(embed)
        
        await paginate(ctx, embeds)
    
    @autoresponder.command(name="info", aliases=["details"])
    @commands.has_permissions(manage_guild=True)
    async def ar_info(self, ctx: commands.Context, *, trigger: str):
        """
        Ver información detallada de un trigger.
        
        Muestra: respuesta, tipo, usos, estado y creador.
        
        **Ejemplos:**
        ;ar info hola
        ;ar info ayuda
        """
        trigger_data = await database.autoresponder.find_one({
            "guild_id": ctx.guild.id,
            "trigger": trigger.lower()
        })
        
        if not trigger_data:
            return await ctx.send(embed=error_embed(f"No existe trigger para `{trigger}`"))
        
        creator = self.bot.get_user(trigger_data["created_by"])
        
        embed = discord.Embed(
            title=f"💬 Auto-Respuesta: {trigger_data['trigger']}",
            color=config.BLURPLE_COLOR
        )
        embed.add_field(name="Respuesta", value=trigger_data["response"][:1024], inline=False)
        embed.add_field(name="Tipo", value=trigger_data.get("match_type", "contains"), inline=True)
        embed.add_field(name="Usos", value=str(trigger_data["uses"]), inline=True)
        embed.add_field(name="Estado", value="✅ Activo" if trigger_data["enabled"] else "❌ Desactivado", inline=True)
        embed.add_field(name="Responde", value="Responder al mensaje" if trigger_data.get("reply", True) else "Mensaje normal", inline=True)
        embed.add_field(name="Creado por", value=str(creator) if creator else f"ID: {trigger_data['created_by']}", inline=True)
        
        await ctx.send(embed=embed)
    
    @autoresponder.command(name="toggle", aliases=["enable", "disable"])
    @commands.has_permissions(manage_guild=True)
    async def ar_toggle(self, ctx: commands.Context, *, trigger: str):
        """
        Activar o desactivar un trigger sin eliminarlo.
        
        **Ejemplos:**
        ;ar toggle hola
        ;ar disable ayuda
        """
        trigger = trigger.lower()
        
        trigger_data = await database.autoresponder.find_one({
            "guild_id": ctx.guild.id,
            "trigger": trigger
        })
        
        if not trigger_data:
            return await ctx.send(embed=error_embed(f"No existe trigger para `{trigger}`"))
        
        new_state = not trigger_data["enabled"]
        
        await database.autoresponder.update_one(
            {"_id": trigger_data["_id"]},
            {"$set": {"enabled": new_state}}
        )
        
        await self.invalidate_cache(ctx.guild.id)
        
        status = "activada" if new_state else "desactivada"
        await ctx.send(embed=success_embed(f"Auto-respuesta `{trigger}` {status}"))
    
    @autoresponder.command(name="type", aliases=["matchtype", "match"])
    @commands.has_permissions(manage_guild=True)
    async def ar_type(self, ctx: commands.Context, trigger: str, match_type: str):
        """
        Cambiar cómo el bot detecta el trigger.
        
        **Tipos disponibles:**
        • `contains` — Detecta si el mensaje contiene la palabra (por defecto)
        • `exact` — Solo si el mensaje es exactamente igual al trigger
        • `startswith` — Solo si el mensaje empieza con el trigger
        • `endswith` — Solo si el mensaje termina con el trigger
        • `regex` — Usa expresiones regulares (avanzado)
        
        **Ejemplos:**
        ;ar type hola exact
        ;ar type link contains
        ;ar type saludo startswith
        """
        trigger = trigger.lower()
        match_type = match_type.lower()
        
        valid_types = ["contains", "exact", "startswith", "endswith", "regex"]
        
        if match_type not in valid_types:
            return await ctx.send(embed=error_embed(f"Tipo inválido. Usa: {', '.join(valid_types)}"))
        
        result = await database.autoresponder.update_one(
            {"guild_id": ctx.guild.id, "trigger": trigger},
            {"$set": {"match_type": match_type}}
        )
        
        if result.matched_count == 0:
            return await ctx.send(embed=error_embed(f"No existe trigger para `{trigger}`"))
        
        await self.invalidate_cache(ctx.guild.id)
        
        await ctx.send(embed=success_embed(f"Tipo de coincidencia cambiado a `{match_type}`"))
    
    @autoresponder.command(name="clear", aliases=["reset", "limpiar"])
    @commands.has_permissions(administrator=True)
    async def ar_clear(self, ctx: commands.Context):
        """
        Eliminar TODAS las auto-respuestas del servidor.
        
        ⚠️ Esta acción no se puede deshacer.
        Requiere permisos de Administrador.
        """
        # Confirmación
        embed = discord.Embed(
            title="⚠️ Confirmar eliminación",
            description="¿Estás seguro de eliminar TODAS las auto-respuestas?",
            color=config.WARNING_COLOR
        )
        
        view = discord.ui.View(timeout=30)
        
        async def confirm_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("No eres el autor del comando", ephemeral=True)
            
            result = await database.autoresponder.delete_many({"guild_id": ctx.guild.id})
            await self.invalidate_cache(ctx.guild.id)
            
            await interaction.response.edit_message(
                embed=success_embed(f"Se eliminaron {result.deleted_count} auto-respuestas"),
                view=None
            )
        
        async def cancel_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("No eres el autor del comando", ephemeral=True)
            
            await interaction.response.edit_message(
                embed=warning_embed("Operación cancelada"),
                view=None
            )
        
        confirm_btn = discord.ui.Button(label="Confirmar", style=discord.ButtonStyle.danger)
        confirm_btn.callback = confirm_callback
        
        cancel_btn = discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.secondary)
        cancel_btn.callback = cancel_callback
        
        view.add_item(confirm_btn)
        view.add_item(cancel_btn)
        
        await ctx.send(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoResponder(bot))
