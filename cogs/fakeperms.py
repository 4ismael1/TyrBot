"""
Cog FakePerms - Permisos falsos para roles y usuarios
"""

from __future__ import annotations

import discord
from discord.ext import commands, tasks
from discord import ui
from typing import Optional, Dict, List, Union

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed, paginate


# Lista de permisos válidos organizados por categoría
PERM_CATEGORIES = {
    "⚔️ Moderación": [
        "administrator", "moderate_members", "kick_members", "ban_members", 
        "manage_nicknames", "mute_members", "deafen_members", "move_members"
    ],
    "🛠️ Gestión": [
        "manage_guild", "manage_roles", "manage_channels", "manage_webhooks",
        "manage_emojis", "manage_expressions", "view_audit_log"
    ],
    "💬 Mensajes": [
        "manage_messages", "mention_everyone", "send_messages", 
        "embed_links", "attach_files", "add_reactions", "use_external_emojis"
    ]
}

# Lista plana de permisos válidos
VALID_PERMS = [perm for perms in PERM_CATEGORIES.values() for perm in perms]


class PermissionSelect(ui.Select):
    """Select para elegir permisos"""
    
    def __init__(self, category: str, perms: list, target_id: int, current_perms: list):
        self.target_id = target_id
        options = []
        
        for perm in perms:
            has_perm = perm in current_perms
            options.append(discord.SelectOption(
                label=perm.replace("_", " ").title(),
                value=perm,
                emoji="✅" if has_perm else "❌",
                default=has_perm
            ))
        
        super().__init__(
            placeholder=category,
            min_values=0,
            max_values=len(options),
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        # Obtener todos los selects y sus valores
        view: PermissionsView = self.view
        all_selected = set()
        
        for child in view.children:
            if isinstance(child, PermissionSelect):
                if child == self:
                    all_selected.update(self.values)
                else:
                    # Obtener valores actuales de otros selects
                    all_selected.update([opt.value for opt in child.options if opt.default])
        
        # Actualizar en DB
        if all_selected:
            await database.fakeperms.update_one(
                {"guild_id": interaction.guild.id, "target_id": self.target_id},
                {"$set": {"permissions": list(all_selected)}},
                upsert=True
            )
        else:
            await database.fakeperms.delete_one({
                "guild_id": interaction.guild.id,
                "target_id": self.target_id
            })
        
        # Actualizar cache del cog
        cog = interaction.client.get_cog("FakePerms")
        if cog:
            if interaction.guild.id not in cog.perms_cache:
                cog.perms_cache[interaction.guild.id] = {}
            cog.perms_cache[interaction.guild.id][self.target_id] = list(all_selected)
        
        await interaction.response.send_message(
            embed=success_embed(f"✅ Permisos actualizados ({len(all_selected)} seleccionados)"),
            ephemeral=True
        )


class PermissionsView(ui.View):
    """Vista con selects para cada categoría de permisos"""
    
    def __init__(self, target: Union[discord.Role, discord.Member], current_perms: list):
        super().__init__(timeout=180)
        self.target = target
        
        for category, perms in PERM_CATEGORIES.items():
            self.add_item(PermissionSelect(category, perms, target.id, current_perms))


class FakePerms(commands.Cog):
    """🎭 Permisos Falsos"""
    
    emoji = "🎭"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache: {guild_id: {role_id: [perms], user_id: [perms]}}
        self.perms_cache: Dict[int, Dict[int, List[str]]] = {}
        self.cache_sync.start()
    
    def cog_unload(self):
        self.cache_sync.cancel()
    
    @tasks.loop(minutes=5)
    async def cache_sync(self):
        """Sincronizar cache con DB"""
        self.perms_cache.clear()
        async for doc in database.fakeperms.find():
            guild_id = doc["guild_id"]
            target_id = doc["target_id"]
            perms = doc["permissions"]
            
            if guild_id not in self.perms_cache:
                self.perms_cache[guild_id] = {}
            self.perms_cache[guild_id][target_id] = perms
    
    @cache_sync.before_loop
    async def before_cache_sync(self):
        await self.bot.wait_until_ready()
    
    async def has_fakeperm(self, guild: discord.Guild, member: discord.Member, permission: str) -> bool:
        """Verificar si un miembro tiene un permiso falso"""
        guild_data = self.perms_cache.get(guild.id, {})
        
        # Verificar permisos del usuario
        if member.id in guild_data:
            if permission in guild_data[member.id] or "administrator" in guild_data[member.id]:
                return True
        
        # Verificar permisos de sus roles
        for role in member.roles:
            if role.id in guild_data:
                if permission in guild_data[role.id] or "administrator" in guild_data[role.id]:
                    return True
        
        return False
    
    async def get_all_fakeperms(self, guild: discord.Guild, member: discord.Member) -> List[str]:
        """Obtener todos los permisos falsos de un miembro"""
        perms = set()
        guild_data = self.perms_cache.get(guild.id, {})
        
        # Permisos del usuario
        if member.id in guild_data:
            perms.update(guild_data[member.id])
        
        # Permisos de sus roles
        for role in member.roles:
            if role.id in guild_data:
                perms.update(guild_data[role.id])
        
        return list(perms)
    
    def perm_to_display(self, perm: str) -> str:
        """Convertir permiso a formato legible"""
        return perm.replace("_", " ").title()
    
    @commands.group(
        name="fakeperms",
        aliases=["fakeperm", "fp"],
        brief="Sistema de permisos falsos",
        invoke_without_command=True
    )
    @commands.has_permissions(administrator=True)
    async def fakeperms(self, ctx: commands.Context):
        """
        Sistema de permisos falsos para roles y usuarios.
        Los permisos falsos solo funcionan con comandos del bot.
        
        **Uso:** ;fakeperms
        **Ejemplo:** ;fp grant @Mods ban_members
        """
        embed = discord.Embed(
            title="🎭 Fake Permissions",
            description=(
                "Asigna permisos falsos a roles o usuarios.\n"
                "Estos permisos **solo funcionan con comandos del bot**, "
                "no afectan los permisos reales de Discord."
            ),
            color=config.BLURPLE_COLOR
        )
        
        embed.add_field(
            name="📋 Comandos",
            value=(
                f"`{ctx.prefix}fp grant <rol/usuario> <permiso>` - Otorgar\n"
                f"`{ctx.prefix}fp revoke <rol/usuario> <permiso>` - Revocar\n"
                f"`{ctx.prefix}fp edit <rol/usuario>` - Panel interactivo\n"
                f"`{ctx.prefix}fp list [rol/usuario]` - Ver permisos\n"
                f"`{ctx.prefix}fp check <usuario>` - Ver permisos efectivos\n"
                f"`{ctx.prefix}fp clear <rol/usuario>` - Limpiar todo"
            ),
            inline=False
        )
        
        # Lista de permisos con los comandos que desbloquean
        embed.add_field(
            name="⚔️ Permisos y Comandos que Desbloquean",
            value=(
                "`ban_members` → ;ban, ;unban, ;massban\n"
                "`kick_members` → ;kick\n"
                "`moderate_members` → ;timeout, ;untimeout, ;warn\n"
                "`manage_messages` → ;purge, ;clear, ;snipe\n"
                "`manage_nicknames` → ;nick, ;forcenick\n"
                "`manage_roles` → ;role, ;autorole\n"
                "`manage_channels` → ;lock, ;unlock, ;slowmode\n"
                "`manage_guild` → ;antinuke, ;antiraid, ;logs"
            ),
            inline=False
        )
        
        embed.add_field(
            name="💡 Ejemplo de Uso",
            value=(
                f"`{ctx.prefix}fp grant @Moderadores kick_members`\n"
                f"→ Ahora @Moderadores puede usar `;kick` aunque no tenga el permiso real"
            ),
            inline=False
        )
        
        # Mostrar estadísticas
        doc_count = await database.fakeperms.count_documents({"guild_id": ctx.guild.id})
        embed.set_footer(text=f"Configuraciones activas: {doc_count}")
        
        await ctx.send(embed=embed)
    
    @fakeperms.command(name="permissions", aliases=["perms", "available"])
    async def fakeperms_permissions(self, ctx: commands.Context):
        """Ver lista de permisos disponibles organizados por categoría."""
        embed = discord.Embed(
            title="🎭 Permisos Disponibles",
            description="Lista de permisos que puedes asignar:",
            color=config.BLURPLE_COLOR
        )
        
        for category, perms in PERM_CATEGORIES.items():
            perms_text = "\n".join([f"• `{p}`" for p in perms])
            embed.add_field(name=category, value=perms_text, inline=True)
        
        await ctx.send(embed=embed)
    
    @fakeperms.command(name="edit", aliases=["panel", "configure"])
    @commands.has_permissions(administrator=True)
    async def fakeperms_edit(self, ctx: commands.Context, target: Union[discord.Role, discord.Member]):
        """
        Abrir panel interactivo para editar permisos.
        
        **Uso:** ;fp edit <rol/usuario>
        """
        doc = await database.fakeperms.find_one({
            "guild_id": ctx.guild.id,
            "target_id": target.id
        })
        
        current_perms = doc.get("permissions", []) if doc else []
        
        embed = discord.Embed(
            title=f"🎭 Editar Permisos: {target.name}",
            description=(
                "Selecciona los permisos que quieres otorgar.\n"
                "✅ = Activo | ❌ = Inactivo"
            ),
            color=target.color if isinstance(target, discord.Role) else config.BLURPLE_COLOR
        )
        
        if current_perms:
            embed.add_field(
                name="Permisos Actuales",
                value=", ".join([f"`{p}`" for p in current_perms[:10]]) + 
                      (f" +{len(current_perms)-10} más" if len(current_perms) > 10 else ""),
                inline=False
            )
        
        view = PermissionsView(target, current_perms)
        await ctx.send(embed=embed, view=view)
    
    @fakeperms.command(name="grant", aliases=["add", "give"])
    @commands.has_permissions(administrator=True)
    async def fakeperms_grant(
        self, 
        ctx: commands.Context, 
        target: Union[discord.Role, discord.Member],
        permission: str
    ):
        """
        Otorgar un permiso falso a un rol o usuario.
        
        **Uso:** ;fp grant <rol/usuario> <permiso>
        **Ejemplo:** ;fp grant @Mods ban_members
        """
        permission = permission.lower().replace(" ", "_")
        
        if permission not in VALID_PERMS:
            return await ctx.send(embed=error_embed(
                f"Permiso no válido. Usa `{ctx.prefix}fp permissions` para ver la lista."
            ))
        
        doc = await database.fakeperms.find_one({
            "guild_id": ctx.guild.id,
            "target_id": target.id
        })
        
        if doc:
            if permission in doc["permissions"]:
                return await ctx.send(embed=warning_embed(
                    f"{target.mention} ya tiene el permiso `{permission}`"
                ))
            
            await database.fakeperms.update_one(
                {"guild_id": ctx.guild.id, "target_id": target.id},
                {"$push": {"permissions": permission}}
            )
        else:
            await database.fakeperms.insert_one({
                "guild_id": ctx.guild.id,
                "target_id": target.id,
                "target_type": "role" if isinstance(target, discord.Role) else "user",
                "permissions": [permission]
            })
        
        # Actualizar cache
        if ctx.guild.id not in self.perms_cache:
            self.perms_cache[ctx.guild.id] = {}
        if target.id not in self.perms_cache[ctx.guild.id]:
            self.perms_cache[ctx.guild.id][target.id] = []
        self.perms_cache[ctx.guild.id][target.id].append(permission)
        
        await ctx.send(embed=success_embed(
            f"✅ Permiso `{self.perm_to_display(permission)}` otorgado a {target.mention}"
        ))
    
    @fakeperms.command(name="revoke", aliases=["remove", "del"])
    @commands.has_permissions(administrator=True)
    async def fakeperms_revoke(
        self, 
        ctx: commands.Context, 
        target: Union[discord.Role, discord.Member],
        permission: str
    ):
        """
        Revocar un permiso falso de un rol o usuario.
        
        **Uso:** ;fp revoke <rol/usuario> <permiso>
        """
        permission = permission.lower().replace(" ", "_")
        
        doc = await database.fakeperms.find_one({
            "guild_id": ctx.guild.id,
            "target_id": target.id
        })
        
        if not doc or permission not in doc.get("permissions", []):
            return await ctx.send(embed=error_embed(
                f"{target.mention} no tiene el permiso `{permission}`"
            ))
        
        new_perms = [p for p in doc["permissions"] if p != permission]
        
        if new_perms:
            await database.fakeperms.update_one(
                {"guild_id": ctx.guild.id, "target_id": target.id},
                {"$set": {"permissions": new_perms}}
            )
        else:
            await database.fakeperms.delete_one({
                "guild_id": ctx.guild.id,
                "target_id": target.id
            })
        
        # Actualizar cache
        if ctx.guild.id in self.perms_cache and target.id in self.perms_cache[ctx.guild.id]:
            self.perms_cache[ctx.guild.id][target.id] = new_perms
        
        await ctx.send(embed=success_embed(
            f"✅ Permiso `{self.perm_to_display(permission)}` revocado de {target.mention}"
        ))
    
    @fakeperms.command(name="check", aliases=["effective"])
    @commands.has_permissions(manage_guild=True)
    async def fakeperms_check(self, ctx: commands.Context, member: discord.Member):
        """
        Ver los permisos efectivos de un usuario (incluyendo los de sus roles).
        
        **Uso:** ;fp check <usuario>
        """
        all_perms = await self.get_all_fakeperms(ctx.guild, member)
        
        if not all_perms:
            return await ctx.send(embed=warning_embed(
                f"{member.mention} no tiene permisos falsos efectivos"
            ))
        
        embed = discord.Embed(
            title=f"🎭 Permisos Efectivos de {member}",
            description="Incluye permisos directos y de sus roles",
            color=member.color
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        
        # Organizar por categoría
        for category, category_perms in PERM_CATEGORIES.items():
            user_perms = [p for p in all_perms if p in category_perms]
            if user_perms:
                embed.add_field(
                    name=category,
                    value="\n".join([f"✅ `{p}`" for p in user_perms]),
                    inline=True
                )
        
        # Mostrar de dónde vienen
        guild_data = self.perms_cache.get(ctx.guild.id, {})
        sources = []
        
        if member.id in guild_data:
            sources.append(f"👤 **Directo:** {len(guild_data[member.id])} permisos")
        
        for role in member.roles:
            if role.id in guild_data:
                sources.append(f"🏷️ **{role.name}:** {len(guild_data[role.id])} permisos")
        
        if sources:
            embed.add_field(name="📍 Fuentes", value="\n".join(sources), inline=False)
        
        await ctx.send(embed=embed)
    
    @fakeperms.command(name="list", aliases=["view", "show"])
    @commands.has_permissions(manage_guild=True)
    async def fakeperms_list(
        self, 
        ctx: commands.Context, 
        target: Optional[Union[discord.Role, discord.Member]] = None
    ):
        """
        Ver permisos falsos de un rol, usuario o del servidor.
        
        **Uso:** ;fp list [rol/usuario]
        """
        if target:
            doc = await database.fakeperms.find_one({
                "guild_id": ctx.guild.id,
                "target_id": target.id
            })
            
            if not doc or not doc.get("permissions"):
                return await ctx.send(embed=warning_embed(
                    f"{target.mention} no tiene permisos falsos"
                ))
            
            embed = discord.Embed(
                title=f"🎭 Permisos de {target.name}",
                color=target.color if isinstance(target, discord.Role) else config.BLURPLE_COLOR
            )
            
            # Organizar por categoría
            for category, category_perms in PERM_CATEGORIES.items():
                user_perms = [p for p in doc["permissions"] if p in category_perms]
                if user_perms:
                    embed.add_field(
                        name=category,
                        value="\n".join([f"• `{p}`" for p in user_perms]),
                        inline=True
                    )
        else:
            docs = await database.fakeperms.find(
                {"guild_id": ctx.guild.id}
            ).to_list(length=None)
            
            if not docs:
                return await ctx.send(embed=warning_embed("No hay permisos falsos configurados"))
            
            embed = discord.Embed(
                title="🎭 Permisos Falsos del Servidor",
                color=config.BLURPLE_COLOR
            )
            
            roles_lines = []
            users_lines = []
            
            for doc in docs:
                perms_count = len(doc["permissions"])
                perms_preview = ", ".join([f"`{p}`" for p in doc["permissions"][:2]])
                if perms_count > 2:
                    perms_preview += f" +{perms_count - 2}"
                
                if doc["target_type"] == "role":
                    role = ctx.guild.get_role(doc["target_id"])
                    name = role.mention if role else f"~~Rol eliminado~~"
                    roles_lines.append(f"{name}: {perms_preview}")
                else:
                    member = ctx.guild.get_member(doc["target_id"])
                    name = member.mention if member else f"~~Usuario salió~~"
                    users_lines.append(f"{name}: {perms_preview}")
            
            if roles_lines:
                embed.add_field(name="🏷️ Roles", value="\n".join(roles_lines[:10]), inline=False)
            if users_lines:
                embed.add_field(name="👤 Usuarios", value="\n".join(users_lines[:10]), inline=False)
            
            embed.set_footer(text=f"Total: {len(docs)} configuraciones")
        
        await ctx.send(embed=embed)
    
    @fakeperms.command(name="clear", aliases=["reset"])
    @commands.has_permissions(administrator=True)
    async def fakeperms_clear(self, ctx: commands.Context, target: Union[discord.Role, discord.Member]):
        """
        Limpiar todos los permisos falsos de un rol o usuario.
        
        **Uso:** ;fp clear <rol/usuario>
        """
        result = await database.fakeperms.delete_one({
            "guild_id": ctx.guild.id,
            "target_id": target.id
        })
        
        if result.deleted_count == 0:
            return await ctx.send(embed=warning_embed(
                f"{target.mention} no tiene permisos falsos"
            ))
        
        # Actualizar cache
        if ctx.guild.id in self.perms_cache:
            self.perms_cache[ctx.guild.id].pop(target.id, None)
        
        await ctx.send(embed=success_embed(
            f"🗑️ Permisos falsos de {target.mention} eliminados"
        ))
    
    @fakeperms.command(name="clearall", aliases=["resetall"])
    @commands.has_permissions(administrator=True)
    async def fakeperms_clearall(self, ctx: commands.Context):
        """Limpiar TODOS los permisos falsos del servidor."""
        from utils import confirm
        
        count = await database.fakeperms.count_documents({"guild_id": ctx.guild.id})
        
        if count == 0:
            return await ctx.send(embed=warning_embed("No hay permisos falsos configurados"))
        
        confirmed = await confirm(
            ctx,
            f"⚠️ ¿Eliminar **{count}** configuraciones de permisos falsos?\n"
            "Esta acción no se puede deshacer."
        )
        
        if not confirmed:
            return await ctx.send(embed=warning_embed("Cancelado"))
        
        await database.fakeperms.delete_many({"guild_id": ctx.guild.id})
        
        # Limpiar cache
        if ctx.guild.id in self.perms_cache:
            del self.perms_cache[ctx.guild.id]
        
        await ctx.send(embed=success_embed(f"🗑️ Se eliminaron **{count}** configuraciones"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FakePerms(bot))
