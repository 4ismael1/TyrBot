"""
Cog Lookup - Búsquedas de perfiles externos
"""

from __future__ import annotations

import discord
from discord.ext import commands
import aiohttp
from typing import Optional

from config import config
from utils import error_embed


class Lookup(commands.Cog):
    """🔍 Búsquedas"""
    
    emoji = "🔍"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.command(
        name="minecraft",
        aliases=["mcu", "mcuser"],
        brief="Buscar perfil de Minecraft"
    )
    async def minecraft(self, ctx: commands.Context, username: str):
        """Buscar información de un usuario de Minecraft"""
        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    # Obtener UUID
                    async with session.get(f"https://api.mojang.com/users/profiles/minecraft/{username}") as resp:
                        if resp.status == 204 or resp.status == 404:
                            return await ctx.send(embed=error_embed(f"Usuario `{username}` no encontrado"))
                        if resp.status != 200:
                            return await ctx.send(embed=error_embed("Error al conectar con Mojang API"))
                        
                        data = await resp.json()
                    
                    uuid = data["id"]
                    name = data["name"]
                    
                    # Formatear UUID
                    uuid_formatted = f"{uuid[:8]}-{uuid[8:12]}-{uuid[12:16]}-{uuid[16:20]}-{uuid[20:]}"
                
                embed = discord.Embed(
                    title=f"⛏️ {name}",
                    color=0x62B47A  # Verde Minecraft
                )
                
                # Skins
                skin_url = f"https://mc-heads.net/body/{uuid}/128"
                avatar_url = f"https://mc-heads.net/avatar/{uuid}/128"
                head_url = f"https://mc-heads.net/head/{uuid}/128"
                
                embed.set_thumbnail(url=avatar_url)
                embed.set_image(url=skin_url)
                
                embed.add_field(name="UUID", value=f"`{uuid_formatted}`", inline=False)
                embed.add_field(name="Nombre", value=f"`{name}`", inline=True)
                
                embed.add_field(
                    name="Enlaces",
                    value=f"[NameMC](https://namemc.com/profile/{uuid})\n"
                          f"[Descargar Skin](https://mc-heads.net/download/{uuid})",
                    inline=True
                )
                
                await ctx.send(embed=embed)
            
            except Exception as e:
                await ctx.send(embed=error_embed(f"Error: {str(e)[:100]}"))
    
    @commands.command(
        name="github",
        aliases=["gh", "ghuser"],
        brief="Buscar perfil de GitHub"
    )
    async def github(self, ctx: commands.Context, username: str):
        """Buscar información de un usuario de GitHub"""
        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"https://api.github.com/users/{username}") as resp:
                        if resp.status == 404:
                            return await ctx.send(embed=error_embed(f"Usuario `{username}` no encontrado"))
                        if resp.status != 200:
                            return await ctx.send(embed=error_embed("Error al conectar con GitHub API"))
                        
                        data = await resp.json()
                
                embed = discord.Embed(
                    title=f"🐙 {data['login']}",
                    url=data["html_url"],
                    color=0x171515  # Negro GitHub
                )
                
                if data.get("avatar_url"):
                    embed.set_thumbnail(url=data["avatar_url"])
                
                if data.get("bio"):
                    embed.description = data["bio"]
                
                embed.add_field(name="Nombre", value=data.get("name") or "N/A", inline=True)
                embed.add_field(name="Empresa", value=data.get("company") or "N/A", inline=True)
                embed.add_field(name="Ubicación", value=data.get("location") or "N/A", inline=True)
                
                embed.add_field(name="Repos Públicos", value=str(data.get("public_repos", 0)), inline=True)
                embed.add_field(name="Gists", value=str(data.get("public_gists", 0)), inline=True)
                embed.add_field(name="Seguidores", value=str(data.get("followers", 0)), inline=True)
                
                if data.get("created_at"):
                    from datetime import datetime
                    created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
                    embed.add_field(name="Creada", value=f"<t:{int(created.timestamp())}:R>", inline=True)
                
                if data.get("blog"):
                    embed.add_field(name="Web", value=data["blog"], inline=True)
                
                await ctx.send(embed=embed)
            
            except Exception as e:
                await ctx.send(embed=error_embed(f"Error: {str(e)[:100]}"))
    
    @commands.command(
        name="weather",
        aliases=["clima", "tiempo"],
        brief="Ver el clima de una ciudad"
    )
    async def weather(self, ctx: commands.Context, *, city: str):
        """Ver el clima actual de una ciudad"""
        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    # Usar wttr.in que no requiere API key
                    url = f"https://wttr.in/{city}?format=j1"
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return await ctx.send(embed=error_embed("Ciudad no encontrada"))
                        
                        data = await resp.json()
                
                current = data["current_condition"][0]
                location = data["nearest_area"][0]
                
                temp_c = current["temp_C"]
                temp_f = current["temp_F"]
                feels_c = current["FeelsLikeC"]
                humidity = current["humidity"]
                wind_kmph = current["windspeedKmph"]
                description = current["weatherDesc"][0]["value"]
                
                city_name = location["areaName"][0]["value"]
                country = location["country"][0]["value"]
                
                # Emojis según condición
                weather_emojis = {
                    "clear": "☀️", "sunny": "☀️",
                    "partly cloudy": "⛅", "cloudy": "☁️",
                    "rain": "🌧️", "light rain": "🌦️",
                    "thunder": "⛈️", "snow": "🌨️",
                    "fog": "🌫️", "mist": "🌫️"
                }
                
                emoji = "🌡️"
                for key, em in weather_emojis.items():
                    if key in description.lower():
                        emoji = em
                        break
                
                embed = discord.Embed(
                    title=f"{emoji} Clima en {city_name}, {country}",
                    color=config.BLURPLE_COLOR
                )
                
                embed.add_field(name="🌡️ Temperatura", value=f"{temp_c}°C / {temp_f}°F", inline=True)
                embed.add_field(name="🤒 Sensación", value=f"{feels_c}°C", inline=True)
                embed.add_field(name="💧 Humedad", value=f"{humidity}%", inline=True)
                embed.add_field(name="💨 Viento", value=f"{wind_kmph} km/h", inline=True)
                embed.add_field(name="📝 Condición", value=description, inline=True)
                
                await ctx.send(embed=embed)
            
            except Exception as e:
                await ctx.send(embed=error_embed(f"Error: {str(e)[:100]}"))
    
    @commands.command(
        name="npm",
        aliases=["npmpackage"],
        brief="Buscar paquete de NPM"
    )
    async def npm(self, ctx: commands.Context, package: str):
        """Buscar información de un paquete de NPM"""
        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"https://registry.npmjs.org/{package}") as resp:
                        if resp.status == 404:
                            return await ctx.send(embed=error_embed(f"Paquete `{package}` no encontrado"))
                        if resp.status != 200:
                            return await ctx.send(embed=error_embed("Error al conectar con NPM"))
                        
                        data = await resp.json()
                
                latest = data.get("dist-tags", {}).get("latest", "N/A")
                name = data.get("name", package)
                description = data.get("description", "Sin descripción")
                
                embed = discord.Embed(
                    title=f"📦 {name}",
                    url=f"https://www.npmjs.com/package/{name}",
                    description=description[:200],
                    color=0xCB3837  # Rojo NPM
                )
                
                embed.add_field(name="Versión", value=f"`{latest}`", inline=True)
                
                if data.get("license"):
                    embed.add_field(name="Licencia", value=data["license"], inline=True)
                
                if data.get("repository", {}).get("url"):
                    repo_url = data["repository"]["url"].replace("git+", "").replace(".git", "")
                    embed.add_field(name="Repositorio", value=f"[GitHub]({repo_url})", inline=True)
                
                if data.get("keywords"):
                    keywords = ", ".join(data["keywords"][:5])
                    embed.add_field(name="Keywords", value=keywords, inline=False)
                
                embed.add_field(
                    name="Instalar",
                    value=f"```npm install {name}```",
                    inline=False
                )
                
                await ctx.send(embed=embed)
            
            except Exception as e:
                await ctx.send(embed=error_embed(f"Error: {str(e)[:100]}"))
    
    @commands.command(
        name="pypi",
        aliases=["pip", "python"],
        brief="Buscar paquete de PyPI"
    )
    async def pypi(self, ctx: commands.Context, package: str):
        """Buscar información de un paquete de PyPI"""
        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"https://pypi.org/pypi/{package}/json") as resp:
                        if resp.status == 404:
                            return await ctx.send(embed=error_embed(f"Paquete `{package}` no encontrado"))
                        if resp.status != 200:
                            return await ctx.send(embed=error_embed("Error al conectar con PyPI"))
                        
                        data = await resp.json()
                
                info = data.get("info", {})
                
                embed = discord.Embed(
                    title=f"🐍 {info.get('name', package)}",
                    url=info.get("package_url"),
                    description=info.get("summary", "Sin descripción")[:200],
                    color=0x3776AB  # Azul Python
                )
                
                embed.add_field(name="Versión", value=f"`{info.get('version', 'N/A')}`", inline=True)
                embed.add_field(name="Autor", value=info.get("author", "N/A")[:50], inline=True)
                
                if info.get("license"):
                    embed.add_field(name="Licencia", value=info["license"][:50], inline=True)
                
                if info.get("requires_python"):
                    embed.add_field(name="Python", value=info["requires_python"], inline=True)
                
                embed.add_field(
                    name="Instalar",
                    value=f"```pip install {info.get('name', package)}```",
                    inline=False
                )
                
                await ctx.send(embed=embed)
            
            except Exception as e:
                await ctx.send(embed=error_embed(f"Error: {str(e)[:100]}"))
    
    @commands.command(
        name="urban",
        aliases=["ud", "urbandictionary"],
        brief="Buscar en Urban Dictionary"
    )
    async def urban(self, ctx: commands.Context, *, term: str):
        """Buscar definición en Urban Dictionary"""
        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"https://api.urbandictionary.com/v0/define?term={term}"
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return await ctx.send(embed=error_embed("Error al conectar con Urban Dictionary"))
                        
                        data = await resp.json()
                
                results = data.get("list", [])
                if not results:
                    return await ctx.send(embed=error_embed(f"No se encontraron definiciones para `{term}`"))
                
                result = results[0]
                
                definition = result["definition"].replace("[", "").replace("]", "")
                if len(definition) > 1000:
                    definition = definition[:1000] + "..."
                
                example = result.get("example", "").replace("[", "").replace("]", "")
                if len(example) > 500:
                    example = example[:500] + "..."
                
                embed = discord.Embed(
                    title=f"📖 {result['word']}",
                    url=result["permalink"],
                    description=definition,
                    color=config.BLURPLE_COLOR
                )
                
                if example:
                    embed.add_field(name="Ejemplo", value=f"*{example}*", inline=False)
                
                embed.add_field(name="👍", value=str(result.get("thumbs_up", 0)), inline=True)
                embed.add_field(name="👎", value=str(result.get("thumbs_down", 0)), inline=True)
                embed.set_footer(text=f"Por {result.get('author', 'Anónimo')}")
                
                await ctx.send(embed=embed)
            
            except Exception as e:
                await ctx.send(embed=error_embed(f"Error: {str(e)[:100]}"))
    
    @commands.command(
        name="anime",
        aliases=["animesearch"],
        brief="Buscar anime"
    )
    async def anime(self, ctx: commands.Context, *, name: str):
        """Buscar información de un anime"""
        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    query = """
                    query ($search: String) {
                        Media(search: $search, type: ANIME) {
                            id
                            title { romaji english native }
                            description(asHtml: false)
                            episodes
                            status
                            averageScore
                            coverImage { large }
                            genres
                            studios { nodes { name } }
                            startDate { year month day }
                            endDate { year month day }
                        }
                    }
                    """
                    
                    url = "https://graphql.anilist.co"
                    async with session.post(url, json={"query": query, "variables": {"search": name}}) as resp:
                        if resp.status != 200:
                            return await ctx.send(embed=error_embed("Error al conectar con AniList"))
                        
                        data = await resp.json()
                
                if not data.get("data", {}).get("Media"):
                    return await ctx.send(embed=error_embed(f"Anime `{name}` no encontrado"))
                
                anime = data["data"]["Media"]
                
                title = anime["title"]["english"] or anime["title"]["romaji"]
                
                embed = discord.Embed(
                    title=f"🎬 {title}",
                    url=f"https://anilist.co/anime/{anime['id']}",
                    color=0x02A9FF  # Azul AniList
                )
                
                if anime.get("coverImage", {}).get("large"):
                    embed.set_thumbnail(url=anime["coverImage"]["large"])
                
                if anime.get("description"):
                    # Limpiar HTML
                    import re
                    desc = re.sub(r'<[^>]+>', '', anime["description"])
                    if len(desc) > 300:
                        desc = desc[:300] + "..."
                    embed.description = desc
                
                embed.add_field(name="Episodios", value=str(anime.get("episodes", "??")), inline=True)
                embed.add_field(name="Estado", value=anime.get("status", "N/A").title(), inline=True)
                embed.add_field(name="Score", value=f"{anime.get('averageScore', 0)}/100", inline=True)
                
                if anime.get("genres"):
                    embed.add_field(name="Géneros", value=", ".join(anime["genres"][:5]), inline=False)
                
                if anime.get("studios", {}).get("nodes"):
                    studios = ", ".join([s["name"] for s in anime["studios"]["nodes"][:3]])
                    embed.add_field(name="Estudio", value=studios, inline=True)
                
                await ctx.send(embed=embed)
            
            except Exception as e:
                await ctx.send(embed=error_embed(f"Error: {str(e)[:100]}"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Lookup(bot))
