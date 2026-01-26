<div align="center">

# ⚔️ Tyr Bot

### Bot de Discord multipropósito para moderación y administración de servidores

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Discord.py](https://img.shields.io/badge/discord.py-2.0+-5865F2.svg?style=for-the-badge&logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![MongoDB](https://img.shields.io/badge/MongoDB-4.4+-47A248.svg?style=for-the-badge&logo=mongodb&logoColor=white)](https://mongodb.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)

</div>

---

## 📋 Características

### 🛡️ Seguridad
- **AntiNuke** - Protección contra ataques de nuke (bans masivos, eliminación de canales/roles)
- **AntiRaid** - Detección y bloqueo automático de raids
- **Sistema de Cuarentena** - Aislar usuarios sospechosos automáticamente

### ⚖️ Moderación
- **Sistema de Casos** - Historial completo de sanciones editables
- **Comandos completos** - Ban, kick, mute, timeout, warn, softban
- **Logs de Moderación** - Registro detallado de todas las acciones

### 🎤 VoiceMaster
- Canales de voz temporales personalizables
- Panel interactivo con botones
- Control total para el dueño del canal

### 🔧 Utilidades
- **Tags** - Snippets de texto reutilizables
- **Recordatorios** - Sistema de reminders
- **AFK** - Estado de ausencia automático
- **Snipe** - Recuperar mensajes eliminados
- **Starboard** - Destacar mensajes populares

### ⚙️ Configuración
- **AutoRole** - Roles automáticos al unirse
- **AutoResponder** - Respuestas automáticas personalizadas
- **JoinDM** - Mensajes de bienvenida por DM
- **FakePerms** - Permisos virtuales para roles
- **ForceNick** - Forzar apodos a usuarios

### 🎉 Comunidad
- **Giveaways** - Sistema de sorteos
- **Confesiones** - Canal de confesiones anónimas
- **Reaction Roles** - Roles por reacción

---

## 🚀 Instalación

### Requisitos Previos

- Python 3.10 o superior
- MongoDB (local o Atlas)
- Redis (opcional, mejora el rendimiento)
- Git

### Paso 1: Clonar el repositorio

```bash
git clone https://github.com/4ismael1/TyrBot.git
cd TyrBot
```

### Paso 2: Crear entorno virtual

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux/Mac
python3 -m venv .venv
source .venv/bin/activate
```

### Paso 3: Instalar dependencias

```bash
pip install -r requirements.txt
```

### Paso 4: Configurar variables de entorno

Copia el archivo de ejemplo y edítalo con tus credenciales:

```bash
cp .env.example .env
```

Edita `.env` con tus valores:

```env
# Bot
DISCORD_TOKEN=tu_token_aqui
OWNER_IDS=tu_id_de_discord

# MongoDB
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=Tyr

# Redis (opcional)
REDIS_URL=redis://localhost:6379
REDIS_PASSWORD=
```

### Paso 5: Ejecutar el bot

```bash
python main.py
```

---

## ⚙️ Configuración de MongoDB

### Opción A: MongoDB Atlas (Recomendado para producción)

1. Crea una cuenta en [MongoDB Atlas](https://www.mongodb.com/atlas)
2. Crea un cluster gratuito (M0)
3. Crea un usuario de base de datos
4. Obtén la URI de conexión y ponla en `MONGO_URI`

### Opción B: MongoDB Local

```bash
# Instalar MongoDB Community Edition
# https://www.mongodb.com/try/download/community

# Iniciar el servicio
mongod --dbpath /path/to/data
```

---

## 🔧 Configuración de Redis (Opcional)

Redis es opcional pero mejora significativamente el rendimiento del bot al cachear datos frecuentes.

### Opción A: Upstash (Recomendado - Gratis)

1. Crea una cuenta en [Upstash](https://upstash.com/)
2. Crea una base de datos Redis
3. Copia la URL y password a tu `.env`

### Opción B: Redis Local

```bash
# Windows (usando WSL o Docker)
docker run -d -p 6379:6379 redis

# Linux
sudo apt install redis-server
sudo systemctl start redis
```

**Nota:** El bot funciona perfectamente sin Redis, solo será un poco más lento en algunas operaciones.

---

## 📁 Estructura del Proyecto

```
TyrBot/
├── main.py              # Entrada principal del bot
├── config.py            # Configuración y constantes
├── requirements.txt     # Dependencias
├── .env.example         # Plantilla de variables de entorno
│
├── cogs/                # Módulos del bot
│   ├── moderation.py    # Sistema de moderación y casos
│   ├── antinuke.py      # Protección anti-nuke
│   ├── antiraid.py      # Protección anti-raid
│   ├── voicemaster.py   # Canales de voz temporales
│   ├── logging.py       # Sistema de logs
│   ├── help.py          # Comando de ayuda personalizado
│   └── ...              # Otros módulos
│
├── core/                # Núcleo del bot
│   ├── database.py      # Conexión a MongoDB
│   └── cache.py         # Sistema de caché Redis
│
├── utils/               # Utilidades
│   ├── helpers.py       # Funciones auxiliares
│   └── paginator.py     # Sistema de paginación
│
└── cogs_disabled/       # Módulos desactivados
```

---

## 🎮 Comandos Principales

| Comando | Descripción |
|---------|-------------|
| `;help` | Menú de ayuda interactivo |
| `;prefix set <prefijo>` | Cambiar prefijo del servidor |
| `;ban <usuario> [razón]` | Banear usuario |
| `;kick <usuario> [razón]` | Expulsar usuario |
| `;warn <usuario> [razón]` | Advertir usuario |
| `;case <id>` | Ver detalles de un caso |
| `;case list [@usuario]` | Listar casos |
| `;vm setup` | Configurar VoiceMaster |
| `;antinuke enable` | Activar protección anti-nuke |
| `;giveaway start <tiempo> <premio>` | Iniciar sorteo |

---

## 🔐 Permisos Requeridos

El bot necesita los siguientes permisos para funcionar correctamente:

- `Administrator` (recomendado) o:
  - Manage Server
  - Manage Roles
  - Manage Channels
  - Kick Members
  - Ban Members
  - Moderate Members
  - Manage Messages
  - View Audit Log
  - Send Messages
  - Embed Links
  - Read Message History
  - Add Reactions

---

## 🤝 Contribuir

Las contribuciones son bienvenidas. Por favor:

1. Fork el repositorio
2. Crea una rama para tu feature (`git checkout -b feature/NuevaCaracteristica`)
3. Commit tus cambios (`git commit -m 'Añadir nueva característica'`)
4. Push a la rama (`git push origin feature/NuevaCaracteristica`)
5. Abre un Pull Request

---

## 📝 Licencia

Este proyecto está bajo la licencia MIT. Ver el archivo [LICENSE](LICENSE) para más detalles.

---

## 💬 Soporte

Si tienes problemas o preguntas:
- Abre un [Issue](https://github.com/4ismael1/TyrBot/issues)

---

<div align="center">

**Hecho con ❤️ usando discord.py**

</div>
