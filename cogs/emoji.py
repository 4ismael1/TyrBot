"""
Cog Emoji - Gestión de emojis del servidor
"""

from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional, Union
import re
import io
import aiohttp

from config import config
from utils import success_embed, error_embed, warning_embed


class Emoji(commands.Cog):
    """😎 Gestión de Emojis"""
    
    emoji = "😎"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    def parse_emoji(self, emoji_str: str) -> Optional[dict]:
        """Parsear string de emoji a información útil"""
        # Emoji animado: <a:name:id>
        # Emoji estático: <:name:id>
        match = re.match(r'<(a?):(\w+):(\d+)>', emoji_str)
        if match:
            animated = bool(match.group(1))
            name = match.group(2)
            emoji_id = int(match.group(3))
            ext = "gif" if animated else "png"
            url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=128"
            return {
                "name": name,
                "id": emoji_id,
                "animated": animated,
                "url": url
            }
        return None
    
    @commands.command(
        name="steal",
        aliases=["stealemoji", "addemoji", "emojiadd"],
        brief="Robar emoji de otro servidor"
    )
    @commands.has_permissions(manage_emojis=True)
    @commands.bot_has_permissions(manage_emojis=True)
    async def steal(self, ctx: commands.Context, emojis: commands.Greedy[discord.PartialEmoji], *, name: Optional[str] = None):
        """Robar uno o más emojis de otro servidor"""
        if not emojis:
            return await ctx.send(embed=error_embed(
                f"Proporciona al menos un emoji\n"
                f"Uso: `{ctx.prefix}steal <emoji> [nombre]`"
            ))
        
        added = []
        failed = []
        
        for emoji in emojis:
            try:
                emoji_name = name if name and len(emojis) == 1 else emoji.name
                emoji_bytes = await emoji.read()
                
                new_emoji = await ctx.guild.create_custom_emoji(
                    name=emoji_name,
                    image=emoji_bytes,
                    reason=f"Robado por {ctx.author}"
                )
                added.append(str(new_emoji))
            except discord.HTTPException as e:
                failed.append(f"{emoji.name}: {str(e)[:50]}")
        
        if added:
            embed = success_embed(f"Emoji(s) añadido(s): {' '.join(added)}")
            if failed:
                embed.add_field(name="Fallidos", value="\n".join(failed[:5]), inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=error_embed(f"No se pudo añadir ningún emoji\n" + "\n".join(failed[:5])))
    
    @commands.command(
        name="stealsticker",
        aliases=["addsticker"],
        brief="Robar sticker de otro servidor"
    )
    @commands.has_permissions(manage_emojis=True)
    @commands.bot_has_permissions(manage_emojis=True)
    async def stealsticker(self, ctx: commands.Context, *, name: Optional[str] = None):
        """Robar un sticker de un mensaje referenciado"""
        ref = ctx.message.reference
        if not ref or not ref.resolved:
            return await ctx.send(embed=error_embed(
                "Responde a un mensaje que contenga un sticker"
            ))
        
        msg = ref.resolved
        if not msg.stickers:
            return await ctx.send(embed=error_embed(
                "El mensaje no tiene stickers"
            ))
        
        sticker = msg.stickers[0]
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(sticker.url) as resp:
                    if resp.status != 200:
                        return await ctx.send(embed=error_embed("Error descargando sticker"))
                    data = await resp.read()
            
            sticker_name = name or sticker.name
            file = discord.File(io.BytesIO(data), filename=f"{sticker_name}.png")
            
            new_sticker = await ctx.guild.create_sticker(
                name=sticker_name,
                description=f"Robado de otro servidor",
                emoji="😀",
                file=file,
                reason=f"Robado por {ctx.author}"
            )
            
            await ctx.send(embed=success_embed(f"Sticker **{new_sticker.name}** añadido"))
        except discord.HTTPException as e:
            await ctx.send(embed=error_embed(f"Error: {e}"))
    
    @commands.command(
        name="enlarge",
        aliases=["jumbo", "bigemoji", "e"],
        brief="Agrandar un emoji"
    )
    async def enlarge(self, ctx: commands.Context, emoji: discord.PartialEmoji):
        """Ver un emoji en tamaño grande"""
        ext = "gif" if emoji.animated else "png"
        url = f"https://cdn.discordapp.com/emojis/{emoji.id}.{ext}?size=512"
        
        embed = discord.Embed(color=config.BLURPLE_COLOR)
        embed.set_image(url=url)
        embed.set_footer(text=f":{emoji.name}: • ID: {emoji.id}")
        
        await ctx.send(embed=embed)
    
    @commands.command(
        name="emojiinfo",
        aliases=["ei", "emojistats"],
        brief="Información de un emoji"
    )
    async def emojiinfo(self, ctx: commands.Context, emoji: discord.PartialEmoji):
        """Ver información detallada de un emoji"""
        ext = "gif" if emoji.animated else "png"
        url = f"https://cdn.discordapp.com/emojis/{emoji.id}.{ext}?size=128"
        
        embed = discord.Embed(
            title=f":{emoji.name}:",
            color=config.BLURPLE_COLOR
        )
        embed.set_thumbnail(url=url)
        
        embed.add_field(name="ID", value=f"`{emoji.id}`", inline=True)
        embed.add_field(name="Animado", value="Sí" if emoji.animated else "No", inline=True)
        embed.add_field(name="URL", value=f"[Descargar]({url})", inline=True)
        
        created_at = discord.utils.snowflake_time(emoji.id)
        embed.add_field(name="Creado", value=f"<t:{int(created_at.timestamp())}:R>", inline=True)
        
        await ctx.send(embed=embed)
    
    @commands.command(
        name="emojis",
        aliases=["emojilist", "serveremojis", "listemojis"],
        brief="Listar emojis del servidor"
    )
    async def emojis(self, ctx: commands.Context):
        """Ver todos los emojis del servidor"""
        emojis = ctx.guild.emojis
        
        if not emojis:
            return await ctx.send(embed=warning_embed("Este servidor no tiene emojis personalizados"))
        
        static = [e for e in emojis if not e.animated]
        animated = [e for e in emojis if e.animated]
        
        embed = discord.Embed(
            title=f"😎 Emojis de {ctx.guild.name}",
            color=config.BLURPLE_COLOR
        )
        
        # Límites
        emoji_limit = ctx.guild.emoji_limit
        embed.description = f"**Estáticos:** {len(static)}/{emoji_limit} • **Animados:** {len(animated)}/{emoji_limit}"
        
        # Mostrar emojis (límite para no exceder embed)
        if static:
            static_text = " ".join([str(e) for e in static[:50]])
            if len(static) > 50:
                static_text += f"\n... y {len(static) - 50} más"
            embed.add_field(name=f"Estáticos ({len(static)})", value=static_text[:1024], inline=False)
        
        if animated:
            animated_text = " ".join([str(e) for e in animated[:50]])
            if len(animated) > 50:
                animated_text += f"\n... y {len(animated) - 50} más"
            embed.add_field(name=f"Animados ({len(animated)})", value=animated_text[:1024], inline=False)
        
        await ctx.send(embed=embed)
    
    @commands.command(
        name="stickers",
        aliases=["stickerlist", "serverstickers"],
        brief="Listar stickers del servidor"
    )
    async def stickers(self, ctx: commands.Context):
        """Ver todos los stickers del servidor"""
        stickers = ctx.guild.stickers
        
        if not stickers:
            return await ctx.send(embed=warning_embed("Este servidor no tiene stickers"))
        
        embed = discord.Embed(
            title=f"🏷️ Stickers de {ctx.guild.name}",
            description=f"**Total:** {len(stickers)}/{ctx.guild.sticker_limit}",
            color=config.BLURPLE_COLOR
        )
        
        sticker_list = "\n".join([f"• `{s.name}` (:{s.emoji}:)" for s in stickers[:15]])
        if len(stickers) > 15:
            sticker_list += f"\n... y {len(stickers) - 15} más"
        
        embed.add_field(name="Stickers", value=sticker_list, inline=False)
        
        await ctx.send(embed=embed)
    
    @commands.command(
        name="deleteemoji",
        aliases=["removeemoji", "delemoji"],
        brief="Eliminar un emoji del servidor"
    )
    @commands.has_permissions(manage_emojis=True)
    @commands.bot_has_permissions(manage_emojis=True)
    async def deleteemoji(self, ctx: commands.Context, emoji: discord.Emoji):
        """Eliminar un emoji del servidor"""
        if emoji.guild_id != ctx.guild.id:
            return await ctx.send(embed=error_embed("Ese emoji no es de este servidor"))
        
        name = emoji.name
        await emoji.delete(reason=f"Eliminado por {ctx.author}")
        
        await ctx.send(embed=success_embed(f"Emoji **:{name}:** eliminado"))
    
    @commands.command(
        name="renameemoji",
        aliases=["emojirename"],
        brief="Renombrar un emoji"
    )
    @commands.has_permissions(manage_emojis=True)
    @commands.bot_has_permissions(manage_emojis=True)
    async def renameemoji(self, ctx: commands.Context, emoji: discord.Emoji, *, new_name: str):
        """Renombrar un emoji del servidor"""
        if emoji.guild_id != ctx.guild.id:
            return await ctx.send(embed=error_embed("Ese emoji no es de este servidor"))
        
        new_name = new_name.replace(" ", "_")[:32]
        old_name = emoji.name
        
        await emoji.edit(name=new_name, reason=f"Renombrado por {ctx.author}")
        
        await ctx.send(embed=success_embed(f"Emoji renombrado: :{old_name}: → :{new_name}:"))
    
    @commands.command(
        name="addemojifromurl",
        aliases=["addemojiurl", "emojiurl"],
        brief="Añadir emoji desde URL"
    )
    @commands.has_permissions(manage_emojis=True)
    @commands.bot_has_permissions(manage_emojis=True)
    async def addemojifromurl(self, ctx: commands.Context, url: str, *, name: str):
        """Añadir un emoji desde una URL de imagen"""
        name = name.replace(" ", "_")[:32]
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return await ctx.send(embed=error_embed("No se pudo descargar la imagen"))
                    
                    content_type = resp.headers.get("Content-Type", "")
                    if not content_type.startswith("image/"):
                        return await ctx.send(embed=error_embed("La URL no es una imagen válida"))
                    
                    data = await resp.read()
            
            new_emoji = await ctx.guild.create_custom_emoji(
                name=name,
                image=data,
                reason=f"Añadido por {ctx.author}"
            )
            
            await ctx.send(embed=success_embed(f"Emoji {new_emoji} añadido"))
        except discord.HTTPException as e:
            await ctx.send(embed=error_embed(f"Error: {e}"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Emoji(bot))
