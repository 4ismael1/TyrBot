"""
Cog Owner - Comandos exclusivos del dueño del bot
"""

from __future__ import annotations

import discord
from discord.ext import commands
import asyncio
import sys
import io
import textwrap
import traceback
from contextlib import redirect_stdout

from config import config
from core import database, cache
from utils import success_embed, error_embed, warning_embed, paginate


class Owner(commands.Cog):
    """👑 Comandos del dueño"""
    
    emoji = "👑"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_result = None
    
    async def cog_check(self, ctx: commands.Context) -> bool:
        """Solo el dueño puede usar estos comandos"""
        return await self.bot.is_owner(ctx.author)
    
    def cleanup_code(self, content: str) -> str:
        """Limpiar código de bloques de código"""
        if content.startswith("```") and content.endswith("```"):
            return "\n".join(content.split("\n")[1:-1])
        return content.strip("` \n")

    @commands.command(
        name="ownerhelp",
        aliases=["ohelp"],
        extras={"hidden": True}
    )
    async def owner_help(self, ctx: commands.Context):
        """Ayuda exclusiva para el owner"""
        p = ctx.clean_prefix

        def is_owner_check(cmd: commands.Command) -> bool:
            for check in getattr(cmd, "checks", []):
                qualname = getattr(check, "__qualname__", "")
                if "is_owner.<locals>.predicate" in qualname:
                    return True
            return False

        def is_owner_only(cmd: commands.Command) -> bool:
            # Comandos dentro del cog Owner siempre son owner-only
            if cmd.cog and cmd.cog.qualified_name == "Owner":
                return True

            extras = getattr(cmd, "extras", {}) or {}
            if extras.get("owner_only"):
                return True

            if is_owner_check(cmd):
                return True

            parent = getattr(cmd, "parent", None)
            while parent:
                if is_owner_check(parent):
                    return True
                parent_extras = getattr(parent, "extras", {}) or {}
                if parent_extras.get("owner_only"):
                    return True
                parent = getattr(parent, "parent", None)

            return False

        def format_cmd(cmd: commands.Command) -> str:
            desc = cmd.brief or cmd.short_doc or cmd.help or "Sin descripción"
            desc = desc.strip().splitlines()[0]
            alias_text = ""
            if cmd.aliases:
                alias_text = f" (alias: {', '.join(cmd.aliases)})"
            return f"`{p}{cmd.qualified_name}`{alias_text} — {desc}"

        def chunk_lines(lines: list[str], max_len: int = 1024) -> list[str]:
            chunks: list[str] = []
            current: list[str] = []
            current_len = 0
            for line in lines:
                extra = len(line) + (1 if current else 0)
                if current and current_len + extra > max_len:
                    chunks.append("\n".join(current))
                    current = [line]
                    current_len = len(line)
                else:
                    current.append(line)
                    current_len += extra
            if current:
                chunks.append("\n".join(current))
            return chunks

        owner_cmds = {}
        unique = {}
        for cmd in self.bot.walk_commands():
            unique[cmd.qualified_name] = cmd
        for cmd in unique.values():
            if not is_owner_only(cmd):
                continue
            cog_name = cmd.cog.qualified_name if cmd.cog else "Otros"
            owner_cmds.setdefault(cog_name, []).append(cmd)

        if not owner_cmds:
            return await ctx.send(embed=warning_embed("No se encontraron comandos de owner."))

        embeds: list[discord.Embed] = []
        for cog_name in sorted(owner_cmds.keys()):
            commands_list = sorted(owner_cmds[cog_name], key=lambda c: c.qualified_name)
            lines = [format_cmd(c) for c in commands_list]
            chunks = chunk_lines(lines)
            for i, chunk in enumerate(chunks):
                title = f"🔐 Owner Help — {cog_name}"
                embed = discord.Embed(
                    title=title,
                    description="Comandos exclusivos del owner. Úsalos con cuidado.",
                    color=config.BLURPLE_COLOR
                )
                field_name = "Comandos" if i == 0 else "Continuación"
                embed.add_field(name=field_name, value=chunk, inline=False)
                embeds.append(embed)

        await paginate(ctx, embeds)
    
    @commands.command(name="eval", aliases=["ev", "exec"])
    async def _eval(self, ctx: commands.Context, *, code: str):
        """
        Evaluar código Python.
        
        Variables disponibles:
        - bot, ctx, channel, author, guild, message
        - database, cache, config
        """
        env = {
            "bot": self.bot,
            "ctx": ctx,
            "channel": ctx.channel,
            "author": ctx.author,
            "guild": ctx.guild,
            "message": ctx.message,
            "database": database,
            "cache": cache,
            "config": config,
            "_": self._last_result,
            "discord": discord,
            "commands": commands,
            "asyncio": asyncio
        }
        
        env.update(globals())
        
        code = self.cleanup_code(code)
        stdout = io.StringIO()
        
        to_compile = f'async def func():\n{textwrap.indent(code, "  ")}'
        
        try:
            exec(to_compile, env)
        except Exception as e:
            return await ctx.send(f"```py\n{e.__class__.__name__}: {e}\n```")
        
        func = env["func"]
        
        try:
            with redirect_stdout(stdout):
                ret = await func()
        except Exception:
            value = stdout.getvalue()
            await ctx.send(f"```py\n{value}{traceback.format_exc()}\n```")
        else:
            value = stdout.getvalue()
            
            try:
                await ctx.message.add_reaction("✅")
            except:
                pass
            
            if ret is None:
                if value:
                    await ctx.send(f"```py\n{value}\n```")
            else:
                self._last_result = ret
                await ctx.send(f"```py\n{value}{ret}\n```")
    
    @commands.command(name="reload", aliases=["rl"])
    async def reload(self, ctx: commands.Context, *, extension: str = None):
        """Recargar una extensión o todas"""
        if extension:
            try:
                await self.bot.reload_extension(f"cogs.{extension}")
                await ctx.send(embed=success_embed(f"Extensión `{extension}` recargada"))
            except Exception as e:
                await ctx.send(embed=error_embed(f"Error: {e}"))
        else:
            # Recargar todas
            reloaded = []
            failed = []
            
            for ext in list(self.bot.extensions.keys()):
                try:
                    await self.bot.reload_extension(ext)
                    reloaded.append(ext)
                except Exception as e:
                    failed.append(f"{ext}: {e}")
            
            msg = f"✅ Recargadas: {len(reloaded)}"
            if failed:
                msg += f"\n❌ Fallidas:\n" + "\n".join(failed)
            
            await ctx.send(msg)
    
    @commands.command(name="load", aliases=["ld"])
    async def load(self, ctx: commands.Context, *, extension: str):
        """Cargar una extensión"""
        try:
            await self.bot.load_extension(f"cogs.{extension}")
            await ctx.send(embed=success_embed(f"Extensión `{extension}` cargada"))
        except Exception as e:
            await ctx.send(embed=error_embed(f"Error: {e}"))
    
    @commands.command(name="unload", aliases=["ul"])
    async def unload(self, ctx: commands.Context, *, extension: str):
        """Descargar una extensión"""
        try:
            await self.bot.unload_extension(f"cogs.{extension}")
            await ctx.send(embed=success_embed(f"Extensión `{extension}` descargada"))
        except Exception as e:
            await ctx.send(embed=error_embed(f"Error: {e}"))
    
    @commands.command(name="sync")
    async def sync(self, ctx: commands.Context, option: str = None):
        """
        Sincronizar comandos slash.
        
        **Opciones:**
        - Sin argumentos: Sincroniza globalmente
        - `guild` o `~`: Sincroniza solo en este servidor
        - `clear`: Limpia comandos globales y sincroniza
        - `clearguild`: Limpia comandos de este servidor
        """
        msg = await ctx.send(embed=warning_embed("⏳ Sincronizando comandos slash..."))
        
        try:
            if option == "clear":
                # Limpiar comandos globales
                self.bot.tree.clear_commands(guild=None)
                synced = await self.bot.tree.sync()
                await msg.edit(embed=success_embed(f"✅ Limpiados y sincronizados {len(synced)} comandos globales"))
                
            elif option == "clearguild":
                # Limpiar comandos del servidor actual
                self.bot.tree.clear_commands(guild=ctx.guild)
                synced = await self.bot.tree.sync(guild=ctx.guild)
                await msg.edit(embed=success_embed(f"✅ Limpiados comandos del servidor. {len(synced)} comandos sincronizados"))
                
            elif option in ("guild", "~"):
                # Sincronizar solo en este servidor
                self.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await self.bot.tree.sync(guild=ctx.guild)
                await msg.edit(embed=success_embed(f"✅ Sincronizados {len(synced)} comandos en este servidor"))
                
            else:
                # Sincronizar globalmente
                synced = await self.bot.tree.sync()
                await msg.edit(embed=success_embed(f"✅ Sincronizados {len(synced)} comandos globalmente"))
                
        except Exception as e:
            await msg.edit(embed=error_embed(f"Error: {e}"))
    
    @commands.command(name="shutdown", aliases=["off", "die"])
    async def shutdown(self, ctx: commands.Context):
        """Apagar el bot"""
        await ctx.send(embed=success_embed("Apagando bot..."))
        await self.bot.close()
    
    @commands.command(name="restart", aliases=["reboot"])
    async def restart(self, ctx: commands.Context):
        """Reiniciar el bot"""
        await ctx.send(embed=success_embed("Reiniciando bot..."))
        # El proceso debería ser reiniciado por un supervisor
        sys.exit(0)
    
    @commands.command(name="guilds", aliases=["servers"])
    async def guilds(self, ctx: commands.Context):
        """Ver lista de servidores"""
        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)
        
        description = ""
        for i, guild in enumerate(guilds[:20], 1):
            description += f"**{i}.** {guild.name} ({guild.member_count} miembros)\n"
        
        embed = discord.Embed(
            title=f"🏠 Servidores ({len(self.bot.guilds)})",
            description=description,
            color=config.BLURPLE_COLOR
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name="leave")
    async def leave(self, ctx: commands.Context, guild_id: int):
        """Salir de un servidor"""
        guild = self.bot.get_guild(guild_id)
        
        if not guild:
            return await ctx.send(embed=error_embed("Servidor no encontrado"))
        
        await guild.leave()
        await ctx.send(embed=success_embed(f"Salí de **{guild.name}**"))
    
    @commands.command(name="blacklist")
    async def blacklist(self, ctx: commands.Context, user: discord.User):
        """Añadir/quitar usuario de la blacklist"""
        doc = await database.blacklist.find_one({"user_id": user.id})
        
        if doc:
            await database.blacklist.delete_one({"user_id": user.id})
            # Remover de Redis
            await cache.remove_from_blacklist(user.id)
            await ctx.send(embed=success_embed(f"{user} removido de la blacklist"))
        else:
            await database.blacklist.insert_one({
                "user_id": user.id,
                "added_by": ctx.author.id,
                "added_at": discord.utils.utcnow()
            })
            # Añadir a Redis
            await cache.add_to_blacklist(user.id)
            await ctx.send(embed=success_embed(f"{user} añadido a la blacklist"))
    
    @commands.command(name="blacklisted")
    async def blacklisted(self, ctx: commands.Context):
        """Ver lista de usuarios en la blacklist"""
        users = await database.blacklist.find().to_list(length=None)
        
        if not users:
            return await ctx.send(embed=error_embed("La blacklist está vacía"))
        
        description = ""
        for i, doc in enumerate(users[:20], 1):
            user = self.bot.get_user(doc["user_id"])
            name = str(user) if user else f"ID: {doc['user_id']}"
            description += f"**{i}.** {name}\n"
        
        embed = discord.Embed(
            title=f"🚫 Blacklist ({len(users)})",
            description=description,
            color=config.ERROR_COLOR
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name="dm")
    async def dm(self, ctx: commands.Context, user: discord.User, *, message: str):
        """Enviar DM a un usuario"""
        try:
            await user.send(message)
            await ctx.send(embed=success_embed(f"Mensaje enviado a {user}"))
        except discord.HTTPException as e:
            await ctx.send(embed=error_embed(f"No se pudo enviar: {e}"))
    
    @commands.command(name="say")
    async def say(self, ctx: commands.Context, channel: discord.TextChannel, *, message: str):
        """Enviar mensaje a un canal"""
        try:
            await channel.send(message)
            await ctx.send(embed=success_embed(f"Mensaje enviado a {channel.mention}"))
        except discord.HTTPException as e:
            await ctx.send(embed=error_embed(f"Error: {e}"))
    
    @commands.command(name="status")
    async def status(self, ctx: commands.Context, status_type: str, *, text: str = None):
        """
        Cambiar el estado del bot.
        
        Tipos: playing, watching, listening, streaming, competing
        """
        activity_types = {
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "streaming": discord.ActivityType.streaming,
            "competing": discord.ActivityType.competing
        }
        
        if status_type.lower() == "clear":
            await self.bot.change_presence(activity=None)
            return await ctx.send(embed=success_embed("Estado limpiado"))
        
        if status_type.lower() not in activity_types:
            return await ctx.send(embed=error_embed(f"Tipo inválido. Usa: {', '.join(activity_types.keys())}"))
        
        if not text:
            return await ctx.send(embed=error_embed("Necesitas especificar un texto"))
        
        activity = discord.Activity(
            type=activity_types[status_type.lower()],
            name=text
        )
        
        await self.bot.change_presence(activity=activity)
        await ctx.send(embed=success_embed(f"Estado cambiado a: {status_type} {text}"))
    
    @commands.command(name="sql")
    async def sql(self, ctx: commands.Context, *, query: str):
        """Ejecutar consulta en MongoDB (find)"""
        query = self.cleanup_code(query)
        
        try:
            # Parsear query simple: collection.find({...})
            parts = query.split(".", 1)
            collection = getattr(database, parts[0])
            
            if "find(" in parts[1]:
                # Extract filter
                import ast
                filter_str = parts[1].replace("find(", "").rstrip(")")
                filter_dict = ast.literal_eval(filter_str) if filter_str else {}
                
                results = await collection.find(filter_dict).limit(10).to_list(10)
                
                output = "\n".join(str(r) for r in results)
                if len(output) > 1900:
                    output = output[:1900] + "..."
                
                await ctx.send(f"```json\n{output}\n```")
            else:
                await ctx.send(embed=error_embed("Solo se soporta find()"))
        except Exception as e:
            await ctx.send(embed=error_embed(f"Error: {e}"))
    
    @commands.command(name="clearcache")
    async def clearcache(self, ctx: commands.Context, pattern: str = None):
        """
        Limpiar caché de Redis.
        
        Uso: ;clearcache [patrón]
        Ejemplo: ;clearcache prefix:* (limpia todos los prefijos)
        Sin patrón limpia toda la caché
        """
        if not cache.is_connected:
            return await ctx.send(embed=error_embed("Redis no está conectado"))
        
        try:
            if pattern:
                # Limpiar patrón específico
                keys = await cache._client.keys(pattern)
                if keys:
                    await cache._client.delete(*keys)
                    await ctx.send(embed=success_embed(f"Se eliminaron {len(keys)} claves con patrón `{pattern}`"))
                else:
                    await ctx.send(embed=warning_embed(f"No se encontraron claves con patrón `{pattern}`"))
            else:
                # Limpiar toda la caché del bot
                keys = await cache._client.keys("bot:*")
                if keys:
                    await cache._client.delete(*keys)
                await ctx.send(embed=success_embed(f"Caché limpiada ({len(keys) if keys else 0} claves)"))
        except Exception as e:
            await ctx.send(embed=error_embed(f"Error limpiando caché: {e}"))
    
    @commands.command(name="cacheinfo")
    async def cacheinfo(self, ctx: commands.Context):
        """Ver información del caché de Redis"""
        if not cache.is_connected:
            return await ctx.send(embed=error_embed("Redis no está conectado"))
        
        try:
            info = await cache._client.info()
            keys = await cache._client.dbsize()
            
            embed = discord.Embed(
                title="📊 Redis Cache Info",
                color=config.BLURPLE_COLOR
            )
            
            embed.add_field(
                name="📈 Estadísticas",
                value=f"**Claves:** {keys}\n"
                      f"**Memoria usada:** {info.get('used_memory_human', 'N/A')}\n"
                      f"**Clientes conectados:** {info.get('connected_clients', 'N/A')}",
                inline=True
            )
            
            embed.add_field(
                name="⚡ Rendimiento",
                value=f"**Hits:** {info.get('keyspace_hits', 0):,}\n"
                      f"**Misses:** {info.get('keyspace_misses', 0):,}\n"
                      f"**Uptime:** {info.get('uptime_in_days', 0)} días",
                inline=True
            )
            
            # Contar claves por prefijo
            guild_count = await cache.get_guild_count()
            user_count = await cache.get_user_count()
            
            embed.add_field(
                name="📌 Estadísticas del Bot",
                value=f"**Guilds (cached):** {guild_count or 'N/A'}\n"
                      f"**Users (cached):** {user_count or 'N/A'}",
                inline=False
            )
            
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed(f"Error: {e}"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Owner(bot))
