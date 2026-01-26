"""
Sistema de ayuda personalizado mejorado
"""

from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional, List, Mapping, Any

from config import config
from utils import PaginatorView


# Organizar cogs por categorías temáticas
COG_CATEGORIES = {
    "🛡️ Seguridad": ["Antinuke", "Antiraid", "Filter", "Verification"],
    "⚔️ Moderación": ["Moderation", "ForceNick", "Logging"],
    "🎭 Roles": ["Autorole", "ReactionRoles", "FakePerms"],
    "🎙️ Voz": ["VoiceMaster", "VoiceMasterAdvanced"],
    "💬 Comunicación": ["AutoResponder", "Welcome", "JoinDM", "Confessions", "Tickets"],
    "🎵 Entretenimiento": ["Games", "LastFM", "Giveaway"],
    "📊 Utilidades": ["Utility", "Levels", "Reminder", "Snipe", "Starboard", "Tags", "Sticky", "Lookup"],
    "💎 Extras": ["Booster", "Emoji", "AFK"],
    "👑 Sistema": ["Owner", "Help", "ConfigSync"],
}

# Comandos destacados para la página principal
FEATURED_COMMANDS = {
    "📋 Casos": [";case", ";case edit", ";case delete", ";case list", ";history"],
    "🛡️ Antinuke": [";antinuke", ";antinuke whitelist", ";antinuke trusted", ";antinuke punishment", ";antinuke setroles", ";antinuke alertrole"],
    "🚨 Antiraid": [";antiraid", ";antiraid penalty", ";antiraid massjoin", ";antiraid age", ";antiraid noavatar"],
    "⚔️ Moderación": [";kick", ";ban", ";timeout", ";warn", ";purge", ";quarantine", ";unquarantine"],
    "📝 Logs": [";logs", ";logs channel", ";logs channel remove", ";logs category", ";logs ignore"],
    "🎭 FakePerms": [";fp grant", ";fp edit", ";fp check", ";fp revoke"],
    "🎙️ Voz": [";voicemaster", ";vm setup", ";vm claim", ";vm lock"],
}


def get_cog_category(cog_name: str) -> str:
    """Obtener la categoría de un cog"""
    for category, cogs in COG_CATEGORIES.items():
        if cog_name in cogs:
            return category
    return "📁 Otros"


class HelpCategorySelect(discord.ui.Select):
    """Menú para seleccionar categoría temática"""
    
    def __init__(self, help_command: 'CustomHelp', categories: dict[str, list]):
        self.help_command = help_command
        self.categories_data = categories
        
        options = [
            discord.SelectOption(
                label="🏠 Inicio",
                description="Página principal de ayuda",
                emoji="🏠",
                value="home"
            )
        ]
        
        for category_name, cogs_list in categories.items():
            if cogs_list:  # Solo si hay cogs en la categoría
                emoji = category_name.split()[0]  # Primer caracter es el emoji
                label = category_name.split(" ", 1)[1] if " " in category_name else category_name
                options.append(
                    discord.SelectOption(
                        label=label,
                        description=f"{len(cogs_list)} módulos",
                        emoji=emoji,
                        value=category_name
                    )
                )
        
        super().__init__(
            placeholder="📂 Selecciona una categoría...",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=0
        )
    
    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "home":
            embed = self.help_command.get_home_embed()
            # Actualizar el segundo select si existe
            view = self.view
            if hasattr(view, 'cog_select') and view.cog_select:
                view.remove_item(view.cog_select)
                view.cog_select = None
        else:
            category = self.values[0]
            embed = self.help_command.get_category_embed(category, self.categories_data[category])
            
            # Actualizar el select de cogs
            view = self.view
            if hasattr(view, 'cog_select') and view.cog_select:
                view.remove_item(view.cog_select)
            
            view.cog_select = HelpCogSelect(self.help_command, self.categories_data[category])
            view.add_item(view.cog_select)
        
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpCogSelect(discord.ui.Select):
    """Menú para seleccionar un cog específico"""
    
    def __init__(self, help_command: 'CustomHelp', cogs_list: list):
        self.help_command = help_command
        
        options = []
        for cog in cogs_list:
            emoji = getattr(cog, "emoji", "📁")
            cmds = [c for c in cog.get_commands() if not c.hidden]
            options.append(
                discord.SelectOption(
                    label=cog.qualified_name,
                    description=f"{len(cmds)} comandos" if cmds else "Sin comandos",
                    emoji=emoji,
                    value=cog.qualified_name
                )
            )
        
        super().__init__(
            placeholder="📜 Selecciona un módulo...",
            min_values=1,
            max_values=1,
            options=options[:25] if options else [
                discord.SelectOption(label="Sin módulos", value="none")
            ],
            row=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.defer()
        
        cog = self.help_command.context.bot.get_cog(self.values[0])
        if cog:
            embed = self.help_command.get_cog_embed(cog)
            await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    """Vista del sistema de ayuda mejorada"""
    
    def __init__(
        self, 
        help_command: 'CustomHelp', 
        categories: dict[str, list],
        author_id: int
    ):
        super().__init__(timeout=180)
        self.help_command = help_command
        self.author_id = author_id
        self.message: Optional[discord.Message] = None
        self.cog_select: Optional[HelpCogSelect] = None
        
        # Agregar select de categorías
        self.add_item(HelpCategorySelect(help_command, categories))
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Solo el autor puede usar este menú.",
                ephemeral=True
            )
            return False
        return True
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class CustomHelp(commands.HelpCommand):
    """Sistema de ayuda personalizado"""
    
    def _organize_cogs_by_category(self) -> dict[str, list]:
        """Organizar cogs del bot por categorías temáticas"""
        bot = self.context.bot
        categories = {}
        used_cogs = set()
        
        # Primero, organizar por las categorías predefinidas
        for category_name, cog_names in COG_CATEGORIES.items():
            cogs_in_category = []
            for cog_name in cog_names:
                cog = bot.get_cog(cog_name)
                if cog:
                    cmds = [c for c in cog.get_commands() if not c.hidden]
                    if cmds:  # Solo si tiene comandos visibles
                        cogs_in_category.append(cog)
                        used_cogs.add(cog_name)
            
            if cogs_in_category:
                categories[category_name] = sorted(cogs_in_category, key=lambda c: c.qualified_name)
        
        # Agregar cogs no categorizados a "Otros"
        otros = []
        for cog_name, cog in bot.cogs.items():
            if cog_name not in used_cogs:
                cmds = [c for c in cog.get_commands() if not c.hidden]
                if cmds:
                    otros.append(cog)
        
        if otros:
            categories["📁 Otros"] = sorted(otros, key=lambda c: c.qualified_name)
        
        return categories
    
    def get_home_embed(self) -> discord.Embed:
        """Obtener embed de la página principal"""
        ctx = self.context
        bot = ctx.bot
        
        # Contar comandos
        total_commands = len(set(bot.walk_commands()))
        total_cogs = len([c for c in bot.cogs.values() if any(not cmd.hidden for cmd in c.get_commands())])
        
        embed = discord.Embed(
            title="📚 Centro de Ayuda",
            description=(
                f"¡Hola **{ctx.author.display_name}**! Soy **{bot.user.name}**, "
                f"un bot multipropósito para Discord.\n\n"
                f"**Prefijo actual:** `{ctx.clean_prefix}`\n"
                f"**Comandos:** {total_commands}\n"
                f"**Módulos:** {total_cogs}\n\n"
                f"**Navegación:**\n"
                f"• Usa el menú de categorías abajo\n"
                f"• `{ctx.clean_prefix}help <comando>` - Info de un comando\n"
                f"• `{ctx.clean_prefix}help <módulo>` - Info de un módulo"
            ),
            color=config.BLURPLE_COLOR
        )
        
        # Comandos destacados/nuevos
        embed.add_field(
            name="⭐ Comandos Destacados",
            value=(
                f"**📋 Casos:** `{ctx.clean_prefix}case` `{ctx.clean_prefix}case edit` `{ctx.clean_prefix}history`\n"
                f"**⚔️ Mod:** `{ctx.clean_prefix}kick` `{ctx.clean_prefix}ban` `{ctx.clean_prefix}warn` `{ctx.clean_prefix}massban`\n"
                f"**🎭 FakePerms:** `{ctx.clean_prefix}fp grant` `{ctx.clean_prefix}fp edit` `{ctx.clean_prefix}fp check`\n"
                f"**📝 Logs:** `{ctx.clean_prefix}logs` `{ctx.clean_prefix}logs category`"
            ),
            inline=False
        )
        
        # Organizar por categorías
        categories = self._organize_cogs_by_category()
        
        # Mostrar resumen de categorías
        category_lines = []
        for category_name, cogs_list in categories.items():
            total_cmds = sum(len([c for c in cog.get_commands() if not c.hidden]) for cog in cogs_list)
            category_lines.append(f"{category_name} — {len(cogs_list)} módulos, {total_cmds} comandos")
        
        embed.add_field(
            name="📂 Categorías Disponibles",
            value="\n".join(category_lines) if category_lines else "Sin categorías",
            inline=False
        )
        
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.set_footer(
            text=f"Solicitado por {ctx.author} • Usa el menú para navegar",
            icon_url=ctx.author.display_avatar.url
        )
        
        return embed
    
    def get_category_embed(self, category_name: str, cogs_list: list) -> discord.Embed:
        """Obtener embed de una categoría temática"""
        ctx = self.context
        
        embed = discord.Embed(
            title=f"{category_name}",
            description=f"Selecciona un módulo del menú de abajo para ver sus comandos.",
            color=config.BLURPLE_COLOR
        )
        
        # Listar módulos de esta categoría
        for cog in cogs_list:
            emoji = getattr(cog, "emoji", "📁")
            cmds = [c for c in cog.get_commands() if not c.hidden]
            
            # Mostrar algunos comandos de ejemplo
            cmd_names = [f"`{c.name}`" for c in cmds[:5]]
            cmd_text = ", ".join(cmd_names)
            if len(cmds) > 5:
                cmd_text += f" y {len(cmds) - 5} más..."
            
            embed.add_field(
                name=f"{emoji} {cog.qualified_name}",
                value=f"{cog.description or 'Sin descripción'}\n**Comandos:** {cmd_text}",
                inline=False
            )
        
        total_cmds = sum(len([c for c in cog.get_commands() if not c.hidden]) for cog in cogs_list)
        embed.set_footer(
            text=f"{len(cogs_list)} módulos, {total_cmds} comandos en esta categoría"
        )
        
        return embed
    
    def get_cog_embed(self, cog: commands.Cog) -> discord.Embed:
        """Obtener embed de un módulo específico"""
        ctx = self.context
        
        emoji = getattr(cog, "emoji", "📁")
        embed = discord.Embed(
            title=f"{emoji} {cog.qualified_name}",
            description=cog.description or "Sin descripción",
            color=config.BLURPLE_COLOR
        )
        
        # Separar comandos principales de grupos
        main_commands = []
        group_commands = []
        
        for cmd in sorted(cog.get_commands(), key=lambda c: c.name):
            if cmd.hidden:
                continue
            
            brief = cmd.brief or cmd.short_doc or "Sin descripción"
            
            if isinstance(cmd, commands.Group):
                subcmds = [c.name for c in cmd.commands if not c.hidden]
                if subcmds:
                    subcmd_text = ", ".join(f"`{s}`" for s in subcmds[:5])
                    if len(subcmds) > 5:
                        subcmd_text += f" +{len(subcmds) - 5}"
                    group_commands.append(
                        f"**`{ctx.clean_prefix}{cmd.name}`** — {brief[:35]}\n"
                        f"  ↳ {subcmd_text}"
                    )
                else:
                    main_commands.append(f"`{ctx.clean_prefix}{cmd.name}` — {brief[:45]}")
            else:
                main_commands.append(f"`{ctx.clean_prefix}{cmd.name}` — {brief[:45]}")
        
        # Mostrar grupos primero (comandos con subcomandos)
        if group_commands:
            group_text = "\n".join(group_commands[:6])
            if len(group_commands) > 6:
                group_text += f"\n*... y {len(group_commands) - 6} más*"
            embed.add_field(
                name=f"📂 Grupos de Comandos ({len(group_commands)})",
                value=group_text,
                inline=False
            )
        
        # Luego comandos simples
        if main_commands:
            # Mostrar todos los comandos, no truncar
            cmd_text = "\n".join(main_commands)
            
            # Si es muy largo, dividir en campos
            if len(cmd_text) > 1024:
                # Dividir en chunks que quepan
                chunks = []
                current_chunk = []
                current_len = 0
                
                for cmd in main_commands:
                    if current_len + len(cmd) + 1 > 1000:
                        chunks.append("\n".join(current_chunk))
                        current_chunk = [cmd]
                        current_len = len(cmd)
                    else:
                        current_chunk.append(cmd)
                        current_len += len(cmd) + 1
                
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                
                for i, chunk in enumerate(chunks):
                    field_name = f"📜 Comandos ({len(main_commands)})" if i == 0 else "📜 Continuación..."
                    embed.add_field(
                        name=field_name,
                        value=chunk,
                        inline=False
                    )
            else:
                embed.add_field(
                    name=f"📜 Comandos ({len(main_commands)})",
                    value=cmd_text,
                    inline=False
                )
        
        total_cmds = len(main_commands) + len(group_commands)
        embed.set_footer(
            text=f"Total: {total_cmds} comandos | {ctx.clean_prefix}help <comando> para más info"
        )
        
        return embed
    
    def get_command_embed(self, command: commands.Command) -> discord.Embed:
        """Obtener embed de un comando específico"""
        ctx = self.context
        
        # Extraer descripción y ejemplos del docstring
        help_text = command.help or command.brief or "Sin descripción"
        description_lines = []
        examples = []
        
        for line in help_text.split("\n"):
            line_stripped = line.strip()
            if line_stripped.startswith("**Ejemplo"):
                continue  # Skip ejemplo headers
            elif line_stripped.startswith("**Uso:**"):
                continue
            elif line_stripped.startswith(";") or line_stripped.startswith(ctx.clean_prefix):
                examples.append(line_stripped)
            elif not line_stripped.startswith("**") or "Variables" in line_stripped or "Tipos" in line_stripped:
                description_lines.append(line)
        
        clean_description = "\n".join(description_lines).strip()
        if not clean_description:
            clean_description = command.brief or "Sin descripción"
        
        # Obtener el cog y su emoji
        cog_emoji = "📖"
        if command.cog:
            cog_emoji = getattr(command.cog, "emoji", "📖")
        
        embed = discord.Embed(
            title=f"{cog_emoji} {ctx.clean_prefix}{command.qualified_name}",
            description=clean_description,
            color=config.BLURPLE_COLOR
        )
        
        # Uso con sintaxis clara
        signature = self.get_command_signature(command)
        embed.add_field(
            name="📝 Sintaxis",
            value=f"```{signature}```",
            inline=False
        )
        
        # Explicar parámetros
        params_explanation = []
        for param_name, param in command.params.items():
            if param_name in ("self", "ctx"):
                continue
            
            # Determinar si es opcional
            is_optional = param.default is not param.empty
            param_type = "opcional" if is_optional else "requerido"
            
            # Obtener tipo si está disponible
            type_hint = ""
            if param.annotation is not param.empty:
                if hasattr(param.annotation, "__name__"):
                    type_hint = f" ({param.annotation.__name__})"
                elif hasattr(param.annotation, "__class__"):
                    type_hint = f" ({param.annotation.__class__.__name__})"
            
            params_explanation.append(f"• `{param_name}`{type_hint} — {param_type}")
        
        if params_explanation:
            embed.add_field(
                name="📋 Parámetros",
                value="\n".join(params_explanation),
                inline=False
            )
        
        # Ejemplos (extraídos o generados)
        if examples:
            embed.add_field(
                name="💡 Ejemplos",
                value="```\n" + "\n".join(examples[:5]) + "```",
                inline=False
            )
        else:
            # Generar ejemplo básico
            example = f"{ctx.clean_prefix}{command.qualified_name}"
            for param_name, param in command.params.items():
                if param_name in ("self", "ctx"):
                    continue
                if param.default is param.empty:
                    example += f" <{param_name}>"
            embed.add_field(
                name="💡 Ejemplo",
                value=f"```{example}```",
                inline=False
            )
        
        # Aliases
        if command.aliases:
            aliases = ", ".join(f"`{ctx.clean_prefix}{a}`" for a in command.aliases)
            embed.add_field(
                name="🔀 Aliases",
                value=aliases,
                inline=True
            )
        
        # Cooldown
        if command.cooldown:
            cd = command.cooldown
            embed.add_field(
                name="⏱️ Cooldown",
                value=f"{cd.rate} uso(s) cada {cd.per:.0f}s",
                inline=True
            )
        
        # Permisos requeridos
        if hasattr(command, "checks") and command.checks:
            perms = []
            for check in command.checks:
                if hasattr(check, "__qualname__"):
                    name = check.__qualname__
                    if "has_permissions" in name:
                        perms.append("📛 Permisos especiales")
                    elif "is_owner" in name:
                        perms.append("👑 Dueño del bot")
                    elif "trusted" in name.lower():
                        perms.append("🛡️ Usuario de confianza")
            if perms:
                embed.add_field(
                    name="🔒 Requiere",
                    value="\n".join(set(perms)),
                    inline=True
                )
        
        # Mostrar módulo al que pertenece
        if command.cog:
            embed.add_field(
                name="📂 Módulo",
                value=f"`{command.cog.qualified_name}`",
                inline=True
            )
        
        # Subcomandos
        if isinstance(command, commands.Group):
            subcommands = []
            for c in sorted(command.commands, key=lambda x: x.name):
                if c.hidden:
                    continue
                brief = c.brief or c.short_doc or ""
                if brief:
                    subcommands.append(f"`{c.name}` — {brief[:35]}")
                else:
                    subcommands.append(f"`{c.name}`")
            
            if subcommands:
                sub_text = "\n".join(subcommands[:10])
                if len(subcommands) > 10:
                    sub_text += f"\n*... y {len(subcommands) - 10} más*"
                embed.add_field(
                    name=f"📁 Subcomandos ({len(subcommands)})",
                    value=sub_text,
                    inline=False
                )
        
        embed.set_footer(text="<> = Requerido | [] = Opcional")
        
        return embed
    
    async def send_bot_help(self, mapping: Mapping[Optional[commands.Cog], List[commands.Command]]) -> None:
        """Enviar ayuda general del bot"""
        categories = self._organize_cogs_by_category()
        embed = self.get_home_embed()
        view = HelpView(self, categories, self.context.author.id)
        
        message = await self.get_destination().send(embed=embed, view=view)
        view.message = message
    
    async def send_cog_help(self, cog: commands.Cog) -> None:
        """Enviar ayuda de un módulo"""
        embed = self.get_cog_embed(cog)
        await self.get_destination().send(embed=embed)
    
    async def send_command_help(self, command: commands.Command) -> None:
        """Enviar ayuda de un comando"""
        embed = self.get_command_embed(command)
        await self.get_destination().send(embed=embed)
    
    async def send_group_help(self, group: commands.Group) -> None:
        """Enviar ayuda de un grupo de comandos"""
        embed = self.get_command_embed(group)
        await self.get_destination().send(embed=embed)
    
    async def send_error_message(self, error: str) -> None:
        """Enviar mensaje de error"""
        embed = discord.Embed(
            description=f"❌ {error}",
            color=config.ERROR_COLOR
        )
        await self.get_destination().send(embed=embed)


class Help(commands.Cog):
    """Sistema de ayuda del bot"""
    
    emoji = "❓"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._original_help_command = bot.help_command
        bot.help_command = CustomHelp()
        bot.help_command.cog = self
    
    def cog_unload(self):
        self.bot.help_command = self._original_help_command
    
    @commands.command(name="setup", aliases=["configurar", "guia"])
    async def setup_guide(self, ctx: commands.Context, module: Optional[str] = None):
        """
        Guías de configuración rápida.
        
        **Uso:** ;setup [módulo]
        **Módulos:** antinuke, antiraid, quarantine, logs, fakeperms
        """
        guides = {
            "antinuke": {
                "title": "🛡️ Configuración de Antinuke",
                "steps": [
                    "**1. Habilitar:** `;antinuke enable`",
                    "**2. Agregar whitelist (inmunidad total):** `;antinuke whitelist add @user`",
                    "**3. Agregar trusted (puede configurar):** `;antinuke trusted add @user`",
                    "**4. Configurar castigo:** `;antinuke punishment <ban/kick/quarantine>`",
                    "**5. Configurar rol de cuarentena:** `;antinuke setroles quarantine @rol`",
                    "**6. Configurar rol de alerta:** `;antinuke alertrole @rol`",
                    "**7. Ver estado:** `;antinuke`"
                ]
            },
            "antiraid": {
                "title": "🚨 Configuración de Antiraid",
                "steps": [
                    "**1. Habilitar:** `;antiraid enable`",
                    "**2. Configurar penalización:** `;antiraid penalty <ban/kick/quarantine>`",
                    "**3. Activar mass join:** `;antiraid massjoin on 10 10` (10 joins en 10s)",
                    "**4. Activar filtro por edad:** `;antiraid age on 7` (mínimo 7 días)",
                    "**5. Activar filtro sin avatar:** `;antiraid noavatar on`",
                    "**6. Ver estado:** `;antiraid`"
                ]
            },
            "quarantine": {
                "title": "🔒 Configuración de Cuarentena",
                "steps": [
                    "**Setup Automático (recomendado):**",
                    "`;antinuke setroles quarantine`",
                    "",
                    "Esto automáticamente:",
                    "• Crea el rol 🔒 Cuarentena",
                    "• Lo configura sin permisos en TODOS los canales",
                    "• Crea canal #cuarentena donde pueden apelar",
                    "• Mueve el rol arriba para poder quitar otros",
                    "",
                    "**Comandos:**",
                    "`;quarantine @user razón` — Poner en cuarentena",
                    "`;unquarantine @user razón` — Quitar (restaura roles)"
                ]
            },
            "logs": {
                "title": "📝 Configuración de Logs",
                "steps": [
                    "**1. Habilitar y configurar canal general:** `;logs channel #canal`",
                    "**2. Activar eventos:** `;logs toggle message_delete on`",
                    "**3. Canal por categoría:** `;logs category messages #canal`",
                    "**4. Ignorar canales:** `;logs ignore #canal`",
                    "**5. Ver estado:** `;logs`",
                    "",
                    "📂 **Categorías:** `messages`, `members`, `moderation`, `server`, `voice`"
                ]
            },
            "fakeperms": {
                "title": "🎭 Configuración de FakePerms",
                "steps": [
                    "**1. Dar permisos a rol:** `;fp grant @rol kick_members`",
                    "**2. Editar permisos:** `;fp edit @rol`",
                    "**3. Ver permisos de usuario:** `;fp check @user`",
                    "**4. Quitar permisos:** `;fp revoke @rol kick_members`",
                    "",
                    "⚡ **Permisos comunes:** `kick_members`, `ban_members`, `moderate_members`, `manage_messages`"
                ]
            }
        }
        
        if module and module.lower() in guides:
            guide = guides[module.lower()]
            embed = discord.Embed(
                title=guide["title"],
                description="\n".join(guide["steps"]),
                color=config.BLURPLE_COLOR
            )
        else:
            # Mostrar lista de guías disponibles
            embed = discord.Embed(
                title="📚 Guías de Configuración",
                description=(
                    "Usa `;setup <módulo>` para ver la guía específica.\n\n"
                    "**Módulos disponibles:**\n"
                    "🛡️ `antinuke` — Protección contra ataques\n"
                    "🚨 `antiraid` — Protección contra raids\n"
                    "🔒 `quarantine` — Sistema de cuarentena\n"
                    "📝 `logs` — Sistema de logs\n"
                    "🎭 `fakeperms` — Permisos falsos\n\n"
                    "**Ejemplo:** `;setup quarantine`"
                ),
                color=config.BLURPLE_COLOR
            )
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
