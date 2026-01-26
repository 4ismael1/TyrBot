"""
Sistema de paginación con botones
"""

from __future__ import annotations

import discord
from typing import TYPE_CHECKING, List, Optional, Union
import asyncio

if TYPE_CHECKING:
    from discord.ext import commands


class PaginatorView(discord.ui.View):
    """Vista de paginación con botones"""
    
    def __init__(
        self,
        embeds: List[discord.Embed],
        author_id: int,
        timeout: float = 180.0
    ):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.author_id = author_id
        self.current_page = 0
        self.message: Optional[discord.Message] = None
        
        # Actualizar estado de botones
        self._update_buttons()
    
    def _update_buttons(self) -> None:
        """Actualizar estado de los botones según la página actual"""
        self.first_page.disabled = self.current_page == 0
        self.prev_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page == len(self.embeds) - 1
        self.last_page.disabled = self.current_page == len(self.embeds) - 1
        
        # Actualizar label del contador
        self.page_counter.label = f"{self.current_page + 1}/{len(self.embeds)}"
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Verificar que solo el autor pueda usar los botones"""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Solo el autor del comando puede usar estos botones.",
                ephemeral=True
            )
            return False
        return True
    
    async def on_timeout(self) -> None:
        """Deshabilitar botones cuando expire el timeout"""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
    
    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Ir a la primera página"""
        self.current_page = 0
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Página anterior"""
        self.current_page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def page_counter(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Contador de páginas (no interactivo)"""
        pass
    
    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Siguiente página"""
        self.current_page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Ir a la última página"""
        self.current_page = len(self.embeds) - 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)


class ConfirmView(discord.ui.View):
    """Vista de confirmación con botones Sí/No"""
    
    def __init__(
        self,
        author_id: int,
        timeout: float = 60.0
    ):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: Optional[bool] = None
        self.message: Optional[discord.Message] = None
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Solo el autor del comando puede confirmar.",
                ephemeral=True
            )
            return False
        return True
    
    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
    
    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.edit_message(view=None)
    
    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.edit_message(view=None)


class SelectMenuView(discord.ui.View):
    """Vista con menú de selección"""
    
    def __init__(
        self,
        options: List[discord.SelectOption],
        author_id: int,
        placeholder: str = "Selecciona una opción...",
        min_values: int = 1,
        max_values: int = 1,
        timeout: float = 180.0
    ):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: Optional[List[str]] = None
        self.message: Optional[discord.Message] = None
        
        # Crear el select menu
        self.select = discord.ui.Select(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            options=options
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Solo el autor del comando puede seleccionar.",
                ephemeral=True
            )
            return False
        return True
    
    async def select_callback(self, interaction: discord.Interaction):
        self.value = self.select.values
        self.stop()
        await interaction.response.defer()


async def paginate(
    ctx: commands.Context,
    embeds: List[discord.Embed],
    timeout: float = 180.0
) -> Optional[discord.Message]:
    """
    Función helper para paginar embeds
    
    Si solo hay un embed, lo envía sin paginación
    """
    if not embeds:
        return None
    
    if len(embeds) == 1:
        return await ctx.send(embed=embeds[0])
    
    # Añadir footer con número de página
    for i, embed in enumerate(embeds):
        if not embed.footer:
            embed.set_footer(text=f"Página {i + 1}/{len(embeds)}")
    
    view = PaginatorView(embeds, ctx.author.id, timeout)
    message = await ctx.send(embed=embeds[0], view=view)
    view.message = message
    
    return message


async def confirm(
    ctx: commands.Context,
    message: str,
    timeout: float = 60.0,
    embed: Optional[discord.Embed] = None
) -> Optional[bool]:
    """
    Función helper para confirmar una acción
    
    Retorna True si confirma, False si cancela, None si expira
    """
    if embed is None:
        embed = discord.Embed(
            description=f"⚠️ {message}",
            color=0xF3DD6C
        )
    
    view = ConfirmView(ctx.author.id, timeout)
    msg = await ctx.send(embed=embed, view=view)
    view.message = msg
    
    await view.wait()
    return view.value
