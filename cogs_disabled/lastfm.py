"""
Cog LastFM - Integración con Last.fm
"""

from __future__ import annotations

import discord
from discord.ext import commands
from datetime import datetime
import aiohttp
from typing import Optional

from config import config
from core import database
from utils import success_embed, error_embed, warning_embed, paginate


class LastFM(commands.Cog):
    """🎵 Integración con Last.fm"""
    
    emoji = "🎵"
    BASE_URL = "http://ws.audioscrobbler.com/2.0/"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def cog_load(self):
        self.session = aiohttp.ClientSession()
    
    async def cog_unload(self):
        if self.session:
            await self.session.close()
    
    async def lastfm_request(self, method: str, **params) -> dict:
        """Hacer una petición a la API de Last.fm"""
        params.update({
            "method": method,
            "api_key": config.LASTFM_API_KEY,
            "format": "json"
        })
        
        async with self.session.get(self.BASE_URL, params=params) as response:
            if response.status != 200:
                raise Exception(f"Error de API: {response.status}")
            return await response.json()
    
    async def get_user(self, user_id: int) -> Optional[str]:
        """Obtener nombre de Last.fm vinculado"""
        doc = await database.lastfm.find_one({"user_id": user_id})
        return doc["username"] if doc else None
    
    @commands.group(
        name="lastfm",
        aliases=["fm", "lfm"],
        brief="Comandos de Last.fm",
        invoke_without_command=True
    )
    async def lastfm(self, ctx: commands.Context, member: discord.Member = None):
        """
        Ver lo que escuchas en Last.fm.
        
        **Uso:** ;fm [usuario]
        """
        member = member or ctx.author
        
        username = await self.get_user(member.id)
        if not username:
            if member == ctx.author:
                return await ctx.send(embed=error_embed(
                    f"No tienes cuenta vinculada. Usa `{ctx.prefix}fm set <usuario>`"
                ))
            return await ctx.send(embed=error_embed(
                f"{member.display_name} no tiene cuenta de Last.fm vinculada"
            ))
        
        try:
            data = await self.lastfm_request(
                "user.getrecenttracks",
                user=username,
                limit=1
            )
        except Exception as e:
            return await ctx.send(embed=error_embed(f"Error al conectar con Last.fm: {e}"))
        
        tracks = data.get("recenttracks", {}).get("track", [])
        
        if not tracks:
            return await ctx.send(embed=warning_embed(f"{username} no ha escuchado nada recientemente"))
        
        track = tracks[0]
        artist = track["artist"]["#text"]
        name = track["name"]
        album = track.get("album", {}).get("#text", "Desconocido")
        image = track.get("image", [{}])[-1].get("#text", "")
        
        # Verificar si está escuchando ahora
        now_playing = track.get("@attr", {}).get("nowplaying") == "true"
        
        embed = discord.Embed(color=0xD51007)  # Color de Last.fm
        embed.set_author(
            name=f"{'🎵 Escuchando ahora' if now_playing else '🎵 Última reproducción'} - {username}",
            icon_url=member.display_avatar.url,
            url=f"https://last.fm/user/{username}"
        )
        
        embed.description = f"**[{name}]({track.get('url', '')})**\npor **{artist}**"
        
        if album:
            embed.description += f"\nen **{album}**"
        
        if image:
            embed.set_thumbnail(url=image)
        
        # Obtener total de scrobbles
        try:
            user_info = await self.lastfm_request("user.getinfo", user=username)
            playcount = user_info.get("user", {}).get("playcount", "?")
            embed.set_footer(text=f"Scrobbles totales: {int(playcount):,}")
        except:
            pass
        
        await ctx.send(embed=embed)
    
    @lastfm.command(name="set", aliases=["link", "vincular", "connect"])
    async def fm_set(self, ctx: commands.Context, *, username: str):
        """
        Vincular tu cuenta de Last.fm.
        
        **Uso:** ;fm set <usuario>
        """
        # Verificar que el usuario existe
        try:
            data = await self.lastfm_request("user.getinfo", user=username)
            if "error" in data:
                return await ctx.send(embed=error_embed("Usuario de Last.fm no encontrado"))
        except Exception as e:
            return await ctx.send(embed=error_embed(f"Error al verificar usuario: {e}"))
        
        # Guardar en DB
        await database.lastfm.update_one(
            {"user_id": ctx.author.id},
            {"$set": {"username": username, "linked_at": datetime.utcnow()}},
            upsert=True
        )
        
        await ctx.send(embed=success_embed(f"Cuenta vinculada: **{username}**"))
    
    @lastfm.command(name="unset", aliases=["unlink", "desvincular", "disconnect"])
    async def fm_unset(self, ctx: commands.Context):
        """Desvincular tu cuenta de Last.fm"""
        result = await database.lastfm.delete_one({"user_id": ctx.author.id})
        
        if result.deleted_count == 0:
            return await ctx.send(embed=error_embed("No tienes cuenta vinculada"))
        
        await ctx.send(embed=success_embed("Cuenta desvinculada"))
    
    @lastfm.command(name="topartists", aliases=["ta", "artists", "artistas"])
    async def fm_topartists(self, ctx: commands.Context, period: str = "overall", member: discord.Member = None):
        """
        Ver tus artistas más escuchados.
        
        **Periodos:** overall, 7day, 1month, 3month, 6month, 12month
        """
        member = member or ctx.author
        username = await self.get_user(member.id)
        
        if not username:
            return await ctx.send(embed=error_embed("No hay cuenta vinculada"))
        
        valid_periods = ["overall", "7day", "1month", "3month", "6month", "12month"]
        if period not in valid_periods:
            return await ctx.send(embed=error_embed(f"Periodo inválido. Usa: {', '.join(valid_periods)}"))
        
        try:
            data = await self.lastfm_request(
                "user.gettopartists",
                user=username,
                period=period,
                limit=10
            )
        except Exception as e:
            return await ctx.send(embed=error_embed(f"Error: {e}"))
        
        artists = data.get("topartists", {}).get("artist", [])
        
        if not artists:
            return await ctx.send(embed=warning_embed("No hay datos suficientes"))
        
        period_names = {
            "overall": "Todo el tiempo",
            "7day": "Última semana",
            "1month": "Último mes",
            "3month": "Últimos 3 meses",
            "6month": "Últimos 6 meses",
            "12month": "Último año"
        }
        
        description = ""
        for i, artist in enumerate(artists, 1):
            plays = int(artist["playcount"])
            description += f"**{i}.** [{artist['name']}]({artist['url']}) - {plays:,} plays\n"
        
        embed = discord.Embed(
            title=f"🎤 Top Artistas - {period_names.get(period, period)}",
            description=description,
            color=0xD51007
        )
        embed.set_author(name=username, icon_url=member.display_avatar.url)
        
        await ctx.send(embed=embed)
    
    @lastfm.command(name="topalbums", aliases=["tab", "albums", "albumes"])
    async def fm_topalbums(self, ctx: commands.Context, period: str = "overall", member: discord.Member = None):
        """Ver tus álbumes más escuchados"""
        member = member or ctx.author
        username = await self.get_user(member.id)
        
        if not username:
            return await ctx.send(embed=error_embed("No hay cuenta vinculada"))
        
        valid_periods = ["overall", "7day", "1month", "3month", "6month", "12month"]
        if period not in valid_periods:
            return await ctx.send(embed=error_embed(f"Periodo inválido. Usa: {', '.join(valid_periods)}"))
        
        try:
            data = await self.lastfm_request(
                "user.gettopalbums",
                user=username,
                period=period,
                limit=10
            )
        except Exception as e:
            return await ctx.send(embed=error_embed(f"Error: {e}"))
        
        albums = data.get("topalbums", {}).get("album", [])
        
        if not albums:
            return await ctx.send(embed=warning_embed("No hay datos suficientes"))
        
        period_names = {
            "overall": "Todo el tiempo",
            "7day": "Última semana",
            "1month": "Último mes",
            "3month": "Últimos 3 meses",
            "6month": "Últimos 6 meses",
            "12month": "Último año"
        }
        
        description = ""
        for i, album in enumerate(albums, 1):
            plays = int(album["playcount"])
            description += f"**{i}.** [{album['name']}]({album['url']}) - {album['artist']['name']} ({plays:,})\n"
        
        embed = discord.Embed(
            title=f"💿 Top Álbumes - {period_names.get(period, period)}",
            description=description,
            color=0xD51007
        )
        embed.set_author(name=username, icon_url=member.display_avatar.url)
        
        if albums and albums[0].get("image"):
            embed.set_thumbnail(url=albums[0]["image"][-1]["#text"])
        
        await ctx.send(embed=embed)
    
    @lastfm.command(name="toptracks", aliases=["tt", "tracks", "canciones"])
    async def fm_toptracks(self, ctx: commands.Context, period: str = "overall", member: discord.Member = None):
        """Ver tus canciones más escuchadas"""
        member = member or ctx.author
        username = await self.get_user(member.id)
        
        if not username:
            return await ctx.send(embed=error_embed("No hay cuenta vinculada"))
        
        valid_periods = ["overall", "7day", "1month", "3month", "6month", "12month"]
        if period not in valid_periods:
            return await ctx.send(embed=error_embed(f"Periodo inválido. Usa: {', '.join(valid_periods)}"))
        
        try:
            data = await self.lastfm_request(
                "user.gettoptracks",
                user=username,
                period=period,
                limit=10
            )
        except Exception as e:
            return await ctx.send(embed=error_embed(f"Error: {e}"))
        
        tracks = data.get("toptracks", {}).get("track", [])
        
        if not tracks:
            return await ctx.send(embed=warning_embed("No hay datos suficientes"))
        
        period_names = {
            "overall": "Todo el tiempo",
            "7day": "Última semana",
            "1month": "Último mes",
            "3month": "Últimos 3 meses",
            "6month": "Últimos 6 meses",
            "12month": "Último año"
        }
        
        description = ""
        for i, track in enumerate(tracks, 1):
            plays = int(track["playcount"])
            description += f"**{i}.** [{track['name']}]({track['url']}) - {track['artist']['name']} ({plays:,})\n"
        
        embed = discord.Embed(
            title=f"🎵 Top Canciones - {period_names.get(period, period)}",
            description=description,
            color=0xD51007
        )
        embed.set_author(name=username, icon_url=member.display_avatar.url)
        
        await ctx.send(embed=embed)
    
    @lastfm.command(name="recent", aliases=["recents", "reciente"])
    async def fm_recent(self, ctx: commands.Context, member: discord.Member = None):
        """Ver reproducciones recientes"""
        member = member or ctx.author
        username = await self.get_user(member.id)
        
        if not username:
            return await ctx.send(embed=error_embed("No hay cuenta vinculada"))
        
        try:
            data = await self.lastfm_request(
                "user.getrecenttracks",
                user=username,
                limit=10
            )
        except Exception as e:
            return await ctx.send(embed=error_embed(f"Error: {e}"))
        
        tracks = data.get("recenttracks", {}).get("track", [])
        
        if not tracks:
            return await ctx.send(embed=warning_embed("No hay reproducciones recientes"))
        
        description = ""
        for i, track in enumerate(tracks, 1):
            now = "🎵 " if track.get("@attr", {}).get("nowplaying") else ""
            description += f"{now}**{i}.** [{track['name']}]({track.get('url', '')}) - {track['artist']['#text']}\n"
        
        embed = discord.Embed(
            title="🎧 Reproducciones Recientes",
            description=description,
            color=0xD51007
        )
        embed.set_author(name=username, icon_url=member.display_avatar.url)
        
        await ctx.send(embed=embed)
    
    @lastfm.command(name="profile", aliases=["perfil", "user", "info"])
    async def fm_profile(self, ctx: commands.Context, member: discord.Member = None):
        """Ver perfil de Last.fm"""
        member = member or ctx.author
        username = await self.get_user(member.id)
        
        if not username:
            return await ctx.send(embed=error_embed("No hay cuenta vinculada"))
        
        try:
            data = await self.lastfm_request("user.getinfo", user=username)
        except Exception as e:
            return await ctx.send(embed=error_embed(f"Error: {e}"))
        
        user = data.get("user", {})
        
        embed = discord.Embed(
            title=f"👤 {user.get('realname') or username}",
            url=user.get("url"),
            color=0xD51007
        )
        
        if user.get("image"):
            embed.set_thumbnail(url=user["image"][-1]["#text"])
        
        embed.add_field(name="Usuario", value=username, inline=True)
        embed.add_field(name="Scrobbles", value=f"{int(user.get('playcount', 0)):,}", inline=True)
        embed.add_field(name="Artistas", value=f"{int(user.get('artist_count', 0)):,}", inline=True)
        embed.add_field(name="Álbumes", value=f"{int(user.get('album_count', 0)):,}", inline=True)
        embed.add_field(name="Canciones", value=f"{int(user.get('track_count', 0)):,}", inline=True)
        embed.add_field(name="País", value=user.get("country") or "No especificado", inline=True)
        
        # Fecha de registro
        if user.get("registered"):
            registered = datetime.fromtimestamp(int(user["registered"]["unixtime"]))
            embed.add_field(name="Registrado", value=discord.utils.format_dt(registered, "D"), inline=True)
        
        await ctx.send(embed=embed)
    
    @lastfm.command(name="whoknows", aliases=["wk", "quienconoce"])
    async def fm_whoknows(self, ctx: commands.Context, *, artist: str):
        """Ver quién en el servidor conoce a un artista"""
        # Obtener todos los usuarios vinculados del servidor
        users = await database.lastfm.find({}).to_list(length=None)
        
        # Filtrar solo usuarios del servidor
        server_users = []
        for user_doc in users:
            member = ctx.guild.get_member(user_doc["user_id"])
            if member:
                server_users.append((member, user_doc["username"]))
        
        if not server_users:
            return await ctx.send(embed=warning_embed("Nadie en el servidor tiene Last.fm vinculado"))
        
        # Obtener plays de cada usuario
        results = []
        
        async with ctx.typing():
            for member, username in server_users:
                try:
                    data = await self.lastfm_request(
                        "artist.getinfo",
                        artist=artist,
                        username=username
                    )
                    
                    if "artist" in data:
                        plays = int(data["artist"].get("stats", {}).get("userplaycount", 0))
                        if plays > 0:
                            results.append((member, plays))
                except:
                    continue
        
        if not results:
            return await ctx.send(embed=warning_embed(f"Nadie en el servidor ha escuchado a **{artist}**"))
        
        # Ordenar por plays
        results.sort(key=lambda x: x[1], reverse=True)
        
        description = ""
        for i, (member, plays) in enumerate(results[:15], 1):
            crown = "👑 " if i == 1 else ""
            description += f"{crown}**{i}.** {member.mention} - {plays:,} plays\n"
        
        embed = discord.Embed(
            title=f"🎤 Quién conoce a {artist}",
            description=description,
            color=0xD51007
        )
        embed.set_footer(text=f"{len(results)} personas en el servidor")
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LastFM(bot))
