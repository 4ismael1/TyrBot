"""
Cog Games - Juegos y diversión
"""

from __future__ import annotations

import discord
from discord.ext import commands
from datetime import datetime
import random
import asyncio
from typing import Optional

from config import config
from utils import error_embed


# Tablero de TicTacToe
class TicTacToeButton(discord.ui.Button["TicTacToeView"]):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=y)
        self.x = x
        self.y = y
    
    async def callback(self, interaction: discord.Interaction):
        view = self.view
        
        if view.current_player != interaction.user:
            return await interaction.response.send_message(
                "No es tu turno!", ephemeral=True
            )
        
        # Marcar celda
        self.style = discord.ButtonStyle.danger if view.turn == "X" else discord.ButtonStyle.success
        self.label = view.turn
        self.disabled = True
        view.board[self.y][self.x] = view.turn
        
        # Verificar ganador
        winner = view.check_winner()
        
        if winner:
            for child in view.children:
                child.disabled = True
            
            if winner == "Tie":
                content = "🎮 ¡Empate!"
            else:
                win_user = view.player1 if winner == "X" else view.player2
                content = f"🎉 ¡{win_user.mention} gana!"
            
            await interaction.response.edit_message(content=content, view=view)
            view.stop()
        else:
            # Cambiar turno
            view.turn = "O" if view.turn == "X" else "X"
            view.current_player = view.player2 if view.turn == "O" else view.player1
            
            content = f"🎮 TicTacToe\n{view.current_player.mention} (:{view.turn}:) - Tu turno"
            await interaction.response.edit_message(content=content, view=view)


class TicTacToeView(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member):
        super().__init__(timeout=120)
        self.player1 = player1
        self.player2 = player2
        self.current_player = player1
        self.turn = "X"
        self.board = [
            [None, None, None],
            [None, None, None],
            [None, None, None]
        ]
        
        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))
    
    def check_winner(self) -> Optional[str]:
        # Filas
        for row in self.board:
            if row[0] == row[1] == row[2] and row[0]:
                return row[0]
        
        # Columnas
        for col in range(3):
            if self.board[0][col] == self.board[1][col] == self.board[2][col] and self.board[0][col]:
                return self.board[0][col]
        
        # Diagonales
        if self.board[0][0] == self.board[1][1] == self.board[2][2] and self.board[0][0]:
            return self.board[0][0]
        if self.board[0][2] == self.board[1][1] == self.board[2][0] and self.board[0][2]:
            return self.board[0][2]
        
        # Empate
        if all(cell for row in self.board for cell in row):
            return "Tie"
        
        return None
    
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# Connect 4
class Connect4Button(discord.ui.Button["Connect4View"]):
    def __init__(self, column: int):
        super().__init__(style=discord.ButtonStyle.secondary, label=str(column + 1))
        self.column = column
    
    async def callback(self, interaction: discord.Interaction):
        view = self.view
        
        if view.current_player != interaction.user:
            return await interaction.response.send_message(
                "No es tu turno!", ephemeral=True
            )
        
        # Encontrar fila disponible
        row = None
        for r in range(5, -1, -1):
            if view.board[r][self.column] is None:
                row = r
                break
        
        if row is None:
            return await interaction.response.send_message(
                "Esta columna está llena!", ephemeral=True
            )
        
        # Colocar ficha
        view.board[row][self.column] = view.turn
        
        # Verificar ganador
        winner = view.check_winner()
        
        if winner:
            for child in view.children:
                child.disabled = True
            
            if winner == "Tie":
                content = f"{view.render_board()}\n\n🎮 ¡Empate!"
            else:
                win_user = view.player1 if winner == "🔴" else view.player2
                content = f"{view.render_board()}\n\n🎉 ¡{win_user.mention} gana!"
            
            await interaction.response.edit_message(content=content, view=view)
            view.stop()
        else:
            # Verificar si columna está llena
            if view.board[0][self.column] is not None:
                self.disabled = True
            
            # Cambiar turno
            view.turn = "🟡" if view.turn == "🔴" else "🔴"
            view.current_player = view.player2 if view.current_player == view.player1 else view.player1
            
            content = f"{view.render_board()}\n\n{view.current_player.mention} ({view.turn}) - Tu turno"
            await interaction.response.edit_message(content=content, view=view)


class Connect4View(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member):
        super().__init__(timeout=300)
        self.player1 = player1
        self.player2 = player2
        self.current_player = player1
        self.turn = "🔴"
        self.board = [[None] * 7 for _ in range(6)]
        
        for col in range(7):
            self.add_item(Connect4Button(col))
    
    def render_board(self) -> str:
        board_str = ""
        for row in self.board:
            board_str += "".join(cell or "⚫" for cell in row) + "\n"
        board_str += "1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣"
        return board_str
    
    def check_winner(self) -> Optional[str]:
        # Horizontal
        for row in range(6):
            for col in range(4):
                if self.board[row][col] and all(self.board[row][col+i] == self.board[row][col] for i in range(4)):
                    return self.board[row][col]
        
        # Vertical
        for row in range(3):
            for col in range(7):
                if self.board[row][col] and all(self.board[row+i][col] == self.board[row][col] for i in range(4)):
                    return self.board[row][col]
        
        # Diagonal (descendente)
        for row in range(3):
            for col in range(4):
                if self.board[row][col] and all(self.board[row+i][col+i] == self.board[row][col] for i in range(4)):
                    return self.board[row][col]
        
        # Diagonal (ascendente)
        for row in range(3, 6):
            for col in range(4):
                if self.board[row][col] and all(self.board[row-i][col+i] == self.board[row][col] for i in range(4)):
                    return self.board[row][col]
        
        # Empate
        if all(self.board[0][col] is not None for col in range(7)):
            return "Tie"
        
        return None
    
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# RPS (Piedra, Papel, Tijeras)
class RPSButton(discord.ui.Button["RPSView"]):
    def __init__(self, choice: str, emoji: str):
        super().__init__(style=discord.ButtonStyle.secondary, emoji=emoji)
        self.choice = choice
    
    async def callback(self, interaction: discord.Interaction):
        view = self.view
        
        if interaction.user not in [view.player1, view.player2]:
            return await interaction.response.send_message(
                "No estás en este juego!", ephemeral=True
            )
        
        if interaction.user == view.player1:
            if view.choice1:
                return await interaction.response.send_message(
                    "Ya elegiste!", ephemeral=True
                )
            view.choice1 = self.choice
            await interaction.response.send_message(
                f"Elegiste {self.choice}!", ephemeral=True
            )
        else:
            if view.choice2:
                return await interaction.response.send_message(
                    "Ya elegiste!", ephemeral=True
                )
            view.choice2 = self.choice
            await interaction.response.send_message(
                f"Elegiste {self.choice}!", ephemeral=True
            )
        
        # Si ambos eligieron
        if view.choice1 and view.choice2:
            winner = view.determine_winner()
            
            for child in view.children:
                child.disabled = True
            
            if winner == "Tie":
                result = f"🎮 ¡Empate!\nAmbos eligieron {view.choice1}"
            elif winner == 1:
                result = f"🎉 ¡{view.player1.mention} gana!\n{view.choice1} vs {view.choice2}"
            else:
                result = f"🎉 ¡{view.player2.mention} gana!\n{view.choice1} vs {view.choice2}"
            
            await interaction.message.edit(content=result, view=view)
            view.stop()


class RPSView(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member):
        super().__init__(timeout=60)
        self.player1 = player1
        self.player2 = player2
        self.choice1 = None
        self.choice2 = None
        
        self.add_item(RPSButton("🪨 Piedra", "🪨"))
        self.add_item(RPSButton("📄 Papel", "📄"))
        self.add_item(RPSButton("✂️ Tijeras", "✂️"))
    
    def determine_winner(self) -> str:
        if self.choice1 == self.choice2:
            return "Tie"
        
        wins = {
            "🪨 Piedra": "✂️ Tijeras",
            "📄 Papel": "🪨 Piedra",
            "✂️ Tijeras": "📄 Papel"
        }
        
        if wins.get(self.choice1) == self.choice2:
            return 1
        return 2
    
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class Games(commands.Cog):
    """🎮 Juegos y diversión"""
    
    emoji = "🎮"
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.hybrid_command(
        name="tictactoe",
        aliases=["ttt", "gato", "tateti"],
        brief="Jugar TicTacToe"
    )
    async def tictactoe(self, ctx: commands.Context, opponent: discord.Member):
        """
        Jugar TicTacToe contra otro usuario.
        
        **Uso:** ;tictactoe @usuario
        """
        if opponent.bot:
            return await ctx.send(embed=error_embed("No puedes jugar contra un bot"))
        
        if opponent == ctx.author:
            return await ctx.send(embed=error_embed("No puedes jugar contra ti mismo"))
        
        view = TicTacToeView(ctx.author, opponent)
        await ctx.send(
            f"🎮 TicTacToe\n{ctx.author.mention} (❌) vs {opponent.mention} (⭕)\n\n{ctx.author.mention} - Tu turno",
            view=view
        )
    
    @commands.hybrid_command(
        name="connect4",
        aliases=["c4", "4enraya", "cuatroenlinea"],
        brief="Jugar Connect 4"
    )
    async def connect4(self, ctx: commands.Context, opponent: discord.Member):
        """
        Jugar Connect 4 contra otro usuario.
        
        **Uso:** ;connect4 @usuario
        """
        if opponent.bot:
            return await ctx.send(embed=error_embed("No puedes jugar contra un bot"))
        
        if opponent == ctx.author:
            return await ctx.send(embed=error_embed("No puedes jugar contra ti mismo"))
        
        view = Connect4View(ctx.author, opponent)
        await ctx.send(
            f"{view.render_board()}\n\n{ctx.author.mention} (🔴) vs {opponent.mention} (🟡)\n{ctx.author.mention} - Tu turno",
            view=view
        )
    
    @commands.hybrid_command(
        name="rps",
        aliases=["ppt", "piedrapapeltijeras"],
        brief="Piedra, Papel, Tijeras"
    )
    async def rps(self, ctx: commands.Context, opponent: discord.Member):
        """
        Jugar Piedra, Papel, Tijeras contra otro usuario.
        
        **Uso:** ;rps @usuario
        """
        if opponent.bot:
            return await ctx.send(embed=error_embed("No puedes jugar contra un bot"))
        
        if opponent == ctx.author:
            return await ctx.send(embed=error_embed("No puedes jugar contra ti mismo"))
        
        view = RPSView(ctx.author, opponent)
        await ctx.send(
            f"🎮 Piedra, Papel, Tijeras\n{ctx.author.mention} vs {opponent.mention}\n\n¡Elijan su opción!",
            view=view
        )
    
    @commands.hybrid_command(
        name="8ball",
        aliases=["8b", "bola8", "pregunta"],
        brief="Pregunta a la bola 8"
    )
    async def eightball(self, ctx: commands.Context, *, question: str):
        """
        Pregunta a la bola mágica 8.
        
        **Uso:** ;8ball <pregunta>
        """
        responses = [
            "🎱 Sí, definitivamente.",
            "🎱 Sin duda.",
            "🎱 Sí.",
            "🎱 Probablemente sí.",
            "🎱 Las señales apuntan a que sí.",
            "🎱 Pregunta de nuevo más tarde.",
            "🎱 Mejor no te lo digo ahora.",
            "🎱 No puedo predecirlo ahora.",
            "🎱 Concéntrate y pregunta de nuevo.",
            "🎱 No cuentes con ello.",
            "🎱 Mi respuesta es no.",
            "🎱 Mis fuentes dicen que no.",
            "🎱 Las perspectivas no son buenas.",
            "🎱 Muy dudoso.",
            "🎱 Definitivamente no."
        ]
        
        embed = discord.Embed(color=config.BLURPLE_COLOR)
        embed.add_field(name="❓ Pregunta", value=question, inline=False)
        embed.add_field(name="🎱 Respuesta", value=random.choice(responses), inline=False)
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="coinflip",
        aliases=["cf", "moneda", "flip"],
        brief="Lanzar una moneda"
    )
    async def coinflip(self, ctx: commands.Context):
        """
        Lanzar una moneda.
        """
        result = random.choice(["🪙 Cara", "🪙 Cruz"])
        await ctx.send(f"{result}")
    
    @commands.hybrid_command(
        name="roll",
        aliases=["dice", "dado"],
        brief="Tirar un dado"
    )
    async def roll(self, ctx: commands.Context, sides: int = 6):
        """
        Tirar un dado.
        
        **Uso:** ;roll [caras]
        **Ejemplo:** ;roll 20
        """
        if sides < 2:
            return await ctx.send(embed=error_embed("El dado necesita al menos 2 caras"))
        
        if sides > 1000:
            return await ctx.send(embed=error_embed("Máximo 1000 caras"))
        
        result = random.randint(1, sides)
        await ctx.send(f"🎲 Tiraste un d{sides} y obtuviste: **{result}**")
    
    @commands.hybrid_command(
        name="choose",
        aliases=["pick", "elegir"],
        brief="Elegir entre opciones"
    )
    async def choose(self, ctx: commands.Context, *, options: str):
        """
        Elegir entre varias opciones separadas por comas.
        
        **Uso:** ;choose opcion1, opcion2, opcion3
        """
        choices = [c.strip() for c in options.split(",") if c.strip()]
        
        if len(choices) < 2:
            return await ctx.send(embed=error_embed("Necesitas al menos 2 opciones separadas por comas"))
        
        choice = random.choice(choices)
        await ctx.send(f"🤔 Elijo: **{choice}**")
    
    @commands.hybrid_command(
        name="rate",
        aliases=["puntuar", "calificar"],
        brief="Calificar algo"
    )
    async def rate(self, ctx: commands.Context, *, thing: str):
        """
        Calificar algo del 0 al 10.
        
        **Uso:** ;rate <cosa>
        """
        rating = random.randint(0, 10)
        
        embed = discord.Embed(
            description=f"Califico **{thing}** con un **{rating}/10**",
            color=config.BLURPLE_COLOR
        )
        
        # Emoji basado en rating
        if rating <= 3:
            embed.description += " 😔"
        elif rating <= 6:
            embed.description += " 😐"
        elif rating <= 8:
            embed.description += " 😊"
        else:
            embed.description += " 🤩"
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="ship",
        aliases=["love", "amor"],
        brief="Calcular compatibilidad"
    )
    async def ship(self, ctx: commands.Context, user1: discord.Member, user2: discord.Member = None):
        """
        Calcular la compatibilidad entre dos usuarios.
        
        **Uso:** ;ship @user1 [@user2]
        """
        if user2 is None:
            user2 = ctx.author
        
        # Generar porcentaje basado en IDs para consistencia
        seed = user1.id + user2.id
        random.seed(seed)
        percentage = random.randint(0, 100)
        random.seed()  # Reset seed
        
        # Barra de progreso
        filled = percentage // 10
        bar = "❤️" * filled + "🖤" * (10 - filled)
        
        # Mensaje basado en porcentaje
        if percentage <= 20:
            message = "😢 No es lo tuyo..."
        elif percentage <= 40:
            message = "😕 Podrían ser amigos"
        elif percentage <= 60:
            message = "😊 ¡Hay potencial!"
        elif percentage <= 80:
            message = "😍 ¡Gran compatibilidad!"
        else:
            message = "💕 ¡AMOR VERDADERO!"
        
        embed = discord.Embed(
            title="💘 Love Calculator",
            description=f"**{user1.display_name}** x **{user2.display_name}**\n\n"
                        f"{bar}\n**{percentage}%**\n\n{message}",
            color=discord.Color.from_rgb(255, 105, 180)
        )
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(
        name="slots",
        aliases=["tragamonedas"],
        brief="Jugar tragamonedas"
    )
    async def slots(self, ctx: commands.Context):
        """
        Jugar a las tragamonedas.
        """
        emojis = ["🍎", "🍊", "🍋", "🍇", "🍒", "⭐", "💎", "7️⃣"]
        
        # Spinning animation
        msg = await ctx.send("🎰 **| Girando...**")
        await asyncio.sleep(1)
        
        result = [random.choice(emojis) for _ in range(3)]
        
        # Determinar ganancia
        if result[0] == result[1] == result[2]:
            if result[0] == "💎":
                outcome = "🎉 ¡¡¡JACKPOT!!! 💎💎💎"
            elif result[0] == "7️⃣":
                outcome = "🎉 ¡¡¡TRIPLE SIETES!!! 7️⃣7️⃣7️⃣"
            else:
                outcome = "🎉 ¡GANASTE! Tres iguales"
        elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
            outcome = "😊 ¡Dos iguales!"
        else:
            outcome = "😔 Sigue intentando..."
        
        await msg.edit(content=f"🎰 **| {result[0]} | {result[1]} | {result[2]} |**\n{outcome}")
    
    @commands.hybrid_command(
        name="reverse",
        aliases=["invertir"],
        brief="Invertir texto"
    )
    async def reverse(self, ctx: commands.Context, *, text: str):
        """
        Invertir un texto.
        """
        await ctx.send(text[::-1])
    
    @commands.hybrid_command(
        name="emojify",
        brief="Convertir texto a emojis"
    )
    async def emojify(self, ctx: commands.Context, *, text: str):
        """
        Convertir texto a emojis de letras.
        """
        emoji_map = {
            "a": "🇦", "b": "🇧", "c": "🇨", "d": "🇩", "e": "🇪",
            "f": "🇫", "g": "🇬", "h": "🇭", "i": "🇮", "j": "🇯",
            "k": "🇰", "l": "🇱", "m": "🇲", "n": "🇳", "o": "🇴",
            "p": "🇵", "q": "🇶", "r": "🇷", "s": "🇸", "t": "🇹",
            "u": "🇺", "v": "🇻", "w": "🇼", "x": "🇽", "y": "🇾",
            "z": "🇿", " ": "  ", "0": "0️⃣", "1": "1️⃣", "2": "2️⃣",
            "3": "3️⃣", "4": "4️⃣", "5": "5️⃣", "6": "6️⃣", "7": "7️⃣",
            "8": "8️⃣", "9": "9️⃣", "?": "❓", "!": "❗"
        }
        
        result = " ".join(emoji_map.get(c.lower(), c) for c in text)
        
        if len(result) > 2000:
            return await ctx.send(embed=error_embed("Resultado muy largo"))
        
        await ctx.send(result)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Games(bot))
