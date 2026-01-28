"""
Sistema de caché Redis para operaciones rápidas
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, Union
from datetime import datetime

import redis.asyncio as redis

from config import config

logger = logging.getLogger(__name__)


def json_serializer(obj):
    """Serializador personalizado para JSON"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, '__str__'):  # ObjectId y otros
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class RedisCache:
    """Sistema de caché con Redis"""
    
    _instance: Optional[RedisCache] = None
    _client: Optional[redis.Redis] = None
    
    # Prefijos para las keys
    PREFIX_GUILD = "guild:"
    PREFIX_PREFIX = "prefix:"
    PREFIX_AFK = "afk:"
    PREFIX_ANTINUKE = "antinuke:"
    PREFIX_COOLDOWN = "cooldown:"
    PREFIX_VOICEMASTER = "vm:"
    PREFIX_WELCOME = "welcome:"
    PREFIX_LICENSE = "license:"
    
    # TTL por defecto (en segundos)
    DEFAULT_TTL = 3600  # 1 hora
    PREFIX_TTL = 86400  # 24 horas
    AFK_TTL = 604800  # 7 días
    COOLDOWN_TTL = 60  # 1 minuto
    LICENSE_TTL = 1800  # 30 minutos
    
    def __new__(cls) -> RedisCache:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def connect(self) -> None:
        """Conectar a Redis"""
        if self._client is not None:
            return
        
        try:
            self._client = redis.Redis.from_url(
                config.REDIS_URL,
                password=config.REDIS_PASSWORD,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
            # Verificar conexión
            await self._client.ping()
            logger.info("✅ Conectado a Redis")
            
        except Exception as e:
            logger.error(f"❌ Error conectando a Redis: {e}")
            # Redis es opcional, continuar sin él
            self._client = None
    
    async def disconnect(self) -> None:
        """Desconectar de Redis"""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("🔌 Desconectado de Redis")
    
    @property
    def client(self) -> Optional[redis.Redis]:
        return self._client
    
    @property
    def is_connected(self) -> bool:
        return self._client is not None
    
    # ========== Operaciones básicas ==========
    
    async def get(self, key: str) -> Optional[str]:
        """Obtener valor de una key"""
        if not self.is_connected:
            return None
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.error(f"Error en Redis GET: {e}")
            return None
    
    async def set(
        self, 
        key: str, 
        value: Union[str, int, float], 
        ttl: Optional[int] = None
    ) -> bool:
        """Establecer valor con TTL opcional"""
        if not self.is_connected:
            return False
        try:
            if ttl:
                await self._client.setex(key, ttl, value)
            else:
                await self._client.set(key, value)
            return True
        except Exception as e:
            logger.error(f"Error en Redis SET: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Eliminar una key"""
        if not self.is_connected:
            return False
        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error en Redis DELETE: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Verificar si existe una key"""
        if not self.is_connected:
            return False
        try:
            return await self._client.exists(key) > 0
        except Exception as e:
            logger.error(f"Error en Redis EXISTS: {e}")
            return False
    
    async def get_json(self, key: str) -> Optional[Any]:
        """Obtener valor JSON deserializado"""
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None
    
    async def set_json(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None
    ) -> bool:
        """Establecer valor como JSON serializado"""
        try:
            json_value = json.dumps(value, default=json_serializer)
            return await self.set(key, json_value, ttl)
        except (TypeError, ValueError) as e:
            logger.error(f"Error serializando JSON: {e}")
            return False
    
    # ========== Operaciones de prefijo ==========
    
    async def get_prefix(self, guild_id: int) -> Optional[str]:
        """Obtener prefijo de un servidor"""
        key = f"{self.PREFIX_PREFIX}{guild_id}"
        return await self.get(key)
    
    async def set_prefix(self, guild_id: int, prefix: str) -> bool:
        """Establecer prefijo de un servidor"""
        key = f"{self.PREFIX_PREFIX}{guild_id}"
        return await self.set(key, prefix, self.PREFIX_TTL)
    
    async def delete_prefix(self, guild_id: int) -> bool:
        """Eliminar prefijo de un servidor"""
        key = f"{self.PREFIX_PREFIX}{guild_id}"
        return await self.delete(key)
    
    # ========== Operaciones de AFK ==========
    
    async def get_afk(self, guild_id: int, user_id: int) -> Optional[dict]:
        """Obtener estado AFK de un usuario"""
        key = f"{self.PREFIX_AFK}{guild_id}:{user_id}"
        return await self.get_json(key)
    
    async def set_afk(
        self, 
        guild_id: int, 
        user_id: int, 
        reason: str, 
        timestamp: int
    ) -> bool:
        """Establecer estado AFK de un usuario"""
        key = f"{self.PREFIX_AFK}{guild_id}:{user_id}"
        data = {"reason": reason, "timestamp": timestamp}
        return await self.set_json(key, data, self.AFK_TTL)
    
    async def delete_afk(self, guild_id: int, user_id: int) -> bool:
        """Eliminar estado AFK de un usuario"""
        key = f"{self.PREFIX_AFK}{guild_id}:{user_id}"
        return await self.delete(key)
    
    # ========== Operaciones de Antinuke ==========
    
    async def get_antinuke_settings(self, guild_id: int) -> Optional[dict]:
        """Obtener configuración antinuke de un servidor"""
        key = f"{self.PREFIX_ANTINUKE}settings:{guild_id}"
        return await self.get_json(key)
    
    async def set_antinuke_settings(self, guild_id: int, settings: dict) -> bool:
        """Establecer configuración antinuke"""
        key = f"{self.PREFIX_ANTINUKE}settings:{guild_id}"
        return await self.set_json(key, settings, self.DEFAULT_TTL)
    
    async def get_antinuke_whitelist(self, guild_id: int) -> Optional[dict]:
        """Obtener whitelist antinuke de un servidor (usuarios y roles)"""
        key = f"{self.PREFIX_ANTINUKE}whitelist:{guild_id}"
        return await self.get_json(key)
    
    async def set_antinuke_whitelist(self, guild_id: int, whitelist: dict) -> bool:
        """Establecer whitelist antinuke (usuarios y roles)"""
        key = f"{self.PREFIX_ANTINUKE}whitelist:{guild_id}"
        return await self.set_json(key, whitelist, self.DEFAULT_TTL)

    # ========== Operaciones de Licencias ==========

    async def get_license_status(self, guild_id: int) -> Optional[bool]:
        """Obtener estado de licencia de un servidor"""
        key = f"{self.PREFIX_LICENSE}{guild_id}"
        value = await self.get(key)
        if value is None:
            return None
        if value in ("1", "true", "True", "yes"):
            return True
        if value in ("0", "false", "False", "no"):
            return False
        return None

    async def set_license_status(self, guild_id: int, status: bool, ttl: Optional[int] = None) -> bool:
        """Establecer estado de licencia de un servidor"""
        key = f"{self.PREFIX_LICENSE}{guild_id}"
        value = "1" if status else "0"
        return await self.set(key, value, ttl or self.LICENSE_TTL)

    async def delete_license_status(self, guild_id: int) -> bool:
        """Eliminar estado de licencia de un servidor"""
        key = f"{self.PREFIX_LICENSE}{guild_id}"
        return await self.delete(key)
    
    async def increment_action_count(
        self, 
        guild_id: int, 
        user_id: int, 
        action: str
    ) -> int:
        """Incrementar contador de acciones (para rate limiting antinuke)"""
        if not self.is_connected:
            return 0
        
        key = f"{self.PREFIX_ANTINUKE}count:{guild_id}:{user_id}:{action}"
        try:
            count = await self._client.incr(key)
            # Establecer TTL de 30 segundos si es nueva key
            if count == 1:
                await self._client.expire(key, 30)
            return count
        except Exception as e:
            logger.error(f"Error incrementando contador: {e}")
            return 0
    
    # ========== Operaciones de VoiceMaster ==========
    
    async def get_voicemaster_channel(self, channel_id: int) -> Optional[dict]:
        """Obtener información de canal VoiceMaster"""
        key = f"{self.PREFIX_VOICEMASTER}channel:{channel_id}"
        return await self.get_json(key)
    
    async def set_voicemaster_channel(
        self, 
        channel_id: int, 
        owner_id: int, 
        guild_id: int
    ) -> bool:
        """Establecer información de canal VoiceMaster"""
        key = f"{self.PREFIX_VOICEMASTER}channel:{channel_id}"
        data = {"owner_id": owner_id, "guild_id": guild_id}
        return await self.set_json(key, data, self.DEFAULT_TTL)
    
    async def delete_voicemaster_channel(self, channel_id: int) -> bool:
        """Eliminar información de canal VoiceMaster"""
        key = f"{self.PREFIX_VOICEMASTER}channel:{channel_id}"
        return await self.delete(key)
    
    # ========== Operaciones de Welcome ==========
    
    async def get_welcome_config(self, guild_id: int) -> Optional[dict]:
        """Obtener configuración de bienvenida"""
        key = f"{self.PREFIX_WELCOME}{guild_id}"
        return await self.get_json(key)
    
    async def set_welcome_config(self, guild_id: int, config: dict) -> bool:
        """Establecer configuración de bienvenida"""
        key = f"{self.PREFIX_WELCOME}{guild_id}"
        return await self.set_json(key, config, self.DEFAULT_TTL)
    
    async def invalidate_welcome_config(self, guild_id: int) -> bool:
        """Invalidar caché de configuración de bienvenida"""
        key = f"{self.PREFIX_WELCOME}{guild_id}"
        return await self.delete(key)
    
    # ========== Cooldown ==========
    
    async def check_cooldown(
        self, 
        user_id: int, 
        command: str, 
        cooldown_seconds: int
    ) -> tuple[bool, int]:
        """
        Verificar cooldown de un comando
        Retorna (está_en_cooldown, segundos_restantes)
        """
        if not self.is_connected:
            return False, 0
        
        key = f"{self.PREFIX_COOLDOWN}{user_id}:{command}"
        try:
            ttl = await self._client.ttl(key)
            if ttl > 0:
                return True, ttl
            
            await self._client.setex(key, cooldown_seconds, "1")
            return False, 0
        except Exception as e:
            logger.error(f"Error verificando cooldown: {e}")
            return False, 0
    
    # ========== Last Seen ==========
    
    async def set_last_seen(self, user_id: int, guild_id: int = None) -> bool:
        """Registrar última vez que un usuario fue visto"""
        if not self.is_connected:
            return False
        key = f"lastseen:{user_id}"
        try:
            import time
            data = {
                "timestamp": time.time(),
                "guild_id": guild_id
            }
            await self._client.set(key, json.dumps(data, default=json_serializer), ex=604800)  # 7 días
            return True
        except Exception as e:
            logger.error(f"Error guardando lastseen: {e}")
            return False
    
    async def get_last_seen(self, user_id: int) -> Optional[dict]:
        """Obtener última vez que un usuario fue visto"""
        if not self.is_connected:
            return None
        key = f"lastseen:{user_id}"
        try:
            value = await self._client.get(key)
            if value:
                data = json.loads(value)
                # Convertir timestamp a ISO format para compatibilidad
                from datetime import datetime
                data["timestamp"] = datetime.fromtimestamp(data["timestamp"]).isoformat()
                return data
            return None
        except Exception as e:
            logger.error(f"Error obteniendo lastseen: {e}")
            return None
    
    # ========== Autoresponder ==========
    
    async def get_autoresponder_triggers(self, guild_id: int) -> Optional[list]:
        """Obtener triggers de autoresponder de un servidor"""
        key = f"ar:triggers:{guild_id}"
        return await self.get_json(key)
    
    async def set_autoresponder_triggers(self, guild_id: int, triggers: list) -> bool:
        """Establecer triggers de autoresponder"""
        key = f"ar:triggers:{guild_id}"
        return await self.set_json(key, triggers, 1800)  # 30 minutos
    
    async def invalidate_autoresponder(self, guild_id: int) -> bool:
        """Invalidar caché de autoresponder"""
        key = f"ar:triggers:{guild_id}"
        return await self.delete(key)
    
    # ========== Snipe (mensajes eliminados/editados) ==========
    
    async def add_deleted_message(
        self,
        channel_id: int,
        author_id: int,
        author_name: str,
        content: str,
        timestamp: int
    ) -> bool:
        """Añadir mensaje eliminado al caché"""
        if not self.is_connected:
            return False
        
        key = f"snipe:deleted:{channel_id}"
        data = {
            "author_id": author_id,
            "author_name": author_name,
            "content": content,
            "timestamp": timestamp
        }
        try:
            # Usar lista, mantener máximo 10
            await self._client.lpush(key, json.dumps(data, default=json_serializer))
            await self._client.ltrim(key, 0, 9)
            await self._client.expire(key, 3600)  # 1 hora
            return True
        except Exception as e:
            logger.error(f"Error guardando snipe: {e}")
            return False
    
    async def get_deleted_messages(self, channel_id: int) -> list:
        """Obtener mensajes eliminados de un canal"""
        if not self.is_connected:
            return []
        
        key = f"snipe:deleted:{channel_id}"
        try:
            messages = await self._client.lrange(key, 0, -1)
            return [json.loads(m) for m in messages]
        except Exception as e:
            logger.error(f"Error obteniendo snipes: {e}")
            return []
    
    async def add_edited_message(
        self,
        channel_id: int,
        author_id: int,
        author_name: str,
        before: str,
        after: str,
        timestamp: int,
        jump_url: str
    ) -> bool:
        """Añadir mensaje editado al caché"""
        if not self.is_connected:
            return False
        
        key = f"snipe:edited:{channel_id}"
        data = {
            "author_id": author_id,
            "author_name": author_name,
            "before": before,
            "after": after,
            "timestamp": timestamp,
            "jump_url": jump_url
        }
        try:
            await self._client.lpush(key, json.dumps(data, default=json_serializer))
            await self._client.ltrim(key, 0, 9)
            await self._client.expire(key, 3600)
            return True
        except Exception as e:
            logger.error(f"Error guardando editsnipe: {e}")
            return False
    
    async def get_edited_messages(self, channel_id: int) -> list:
        """Obtener mensajes editados de un canal"""
        if not self.is_connected:
            return []
        
        key = f"snipe:edited:{channel_id}"
        try:
            messages = await self._client.lrange(key, 0, -1)
            return [json.loads(m) for m in messages]
        except Exception as e:
            logger.error(f"Error obteniendo editsnipes: {e}")
            return []
    
    async def clear_snipe_cache(self, channel_id: int) -> bool:
        """Limpiar caché de snipes de un canal"""
        if not self.is_connected:
            return False
        try:
            await self._client.delete(f"snipe:deleted:{channel_id}")
            await self._client.delete(f"snipe:edited:{channel_id}")
            return True
        except Exception as e:
            logger.error(f"Error limpiando snipes: {e}")
            return False
    
    # ========== Bot Stats ==========
    
    async def update_guild_count(self, count: int) -> bool:
        """Actualizar conteo de servidores"""
        if not self.is_connected:
            return False
        try:
            await self._client.set("stats:guilds", str(count))
            return True
        except Exception as e:
            logger.error(f"Error actualizando guild count: {e}")
            return False
    
    async def get_guild_count(self) -> Optional[int]:
        """Obtener conteo de servidores"""
        if not self.is_connected:
            return None
        try:
            value = await self._client.get("stats:guilds")
            return int(value) if value else None
        except:
            return None
    
    async def update_user_count(self, count: int) -> bool:
        """Actualizar conteo de usuarios"""
        if not self.is_connected:
            return False
        try:
            await self._client.set("stats:users", str(count))
            return True
        except Exception as e:
            logger.error(f"Error actualizando user count: {e}")
            return False
    
    async def get_user_count(self) -> Optional[int]:
        """Obtener conteo de usuarios"""
        if not self.is_connected:
            return None
        try:
            value = await self._client.get("stats:users")
            return int(value) if value else None
        except:
            return None
    
    # ========== Tags Cache ==========
    
    async def get_tag(self, guild_id: int, name: str) -> Optional[dict]:
        """Obtener tag del caché"""
        key = f"tag:{guild_id}:{name.lower()}"
        return await self.get_json(key)
    
    async def set_tag(self, guild_id: int, name: str, data: dict) -> bool:
        """Guardar tag en caché"""
        key = f"tag:{guild_id}:{name.lower()}"
        return await self.set_json(key, data, 3600)  # 1 hora
    
    async def invalidate_tag(self, guild_id: int, name: str) -> bool:
        """Invalidar tag del caché"""
        key = f"tag:{guild_id}:{name.lower()}"
        return await self.delete(key)
    
    # ========== Blacklist ==========
    
    async def is_blacklisted(self, user_id: int) -> bool:
        """Verificar si un usuario está en blacklist"""
        if not self.is_connected:
            return False
        try:
            return await self._client.sismember("blacklist", str(user_id))
        except:
            return False
    
    async def add_to_blacklist(self, user_id: int) -> bool:
        """Añadir usuario a blacklist"""
        if not self.is_connected:
            return False
        try:
            await self._client.sadd("blacklist", str(user_id))
            return True
        except:
            return False
    
    async def remove_from_blacklist(self, user_id: int) -> bool:
        """Remover usuario de blacklist"""
        if not self.is_connected:
            return False
        try:
            await self._client.srem("blacklist", str(user_id))
            return True
        except:
            return False
    
    async def load_blacklist(self, user_ids: list[int]) -> bool:
        """Cargar lista de blacklist en Redis"""
        if not self.is_connected:
            return False
        try:
            if user_ids:
                await self._client.sadd("blacklist", *[str(uid) for uid in user_ids])
            return True
        except:
            return False
    
    # ========== Pub/Sub para invalidación de cache ==========
    
    CHANNEL_CONFIG_UPDATE = "config_update"
    
    async def publish_config_update(self, guild_id: int, config_type: str) -> bool:
        """Publicar actualización de configuración para invalidar caches"""
        if not self.is_connected:
            return False
        try:
            message = json.dumps({
                "guild_id": guild_id,
                "type": config_type
            }, default=json_serializer)
            await self._client.publish(self.CHANNEL_CONFIG_UPDATE, message)
            logger.debug(f"📢 Config update published: {config_type} for guild {guild_id}")
            return True
        except Exception as e:
            logger.error(f"Error publishing config update: {e}")
            return False
    
    async def subscribe_config_updates(self):
        """Suscribirse a actualizaciones de configuración"""
        if not self.is_connected:
            return None
        try:
            pubsub = self._client.pubsub()
            await pubsub.subscribe(self.CHANNEL_CONFIG_UPDATE)
            return pubsub
        except Exception as e:
            logger.error(f"Error subscribing to config updates: {e}")
            return None
    
    # ========== Invalidación de cache por tipo ==========
    
    async def invalidate_guild_config(self, guild_id: int, config_type: str) -> bool:
        """Invalidar cache de configuración específica de un guild"""
        if not self.is_connected:
            return False
        
        patterns = {
            "prefix": [f"{self.PREFIX_PREFIX}{guild_id}"],
            "antinuke": [
                f"{self.PREFIX_ANTINUKE}settings:{guild_id}",
                f"{self.PREFIX_ANTINUKE}whitelist:{guild_id}"
            ],
            "welcome": [f"{self.PREFIX_WELCOME}{guild_id}"],
            "antiraid": [f"antiraid:{guild_id}"],
            "logging": [f"logging:{guild_id}"],
            "levels": [f"levels:settings:{guild_id}"],
            "starboard": [f"starboard:{guild_id}"],
            "filter": [f"filter:{guild_id}"],
            "autoroles": [f"autoroles:{guild_id}"],
        }
        
        keys_to_delete = patterns.get(config_type, [])
        
        try:
            for key in keys_to_delete:
                await self.delete(key)
            logger.debug(f"🗑️ Cache invalidated: {config_type} for guild {guild_id}")
            return True
        except Exception as e:
            logger.error(f"Error invalidating cache: {e}")
            return False
    
    # ========== Operaciones de Antiraid ==========
    
    async def antiraid_add_join(self, guild_id: int, member_id: int) -> int:
        """
        Registrar un join en el tracker de antiraid.
        Usa Redis ZADD con timestamp como score para ordenamiento automático.
        Retorna el número total de joins recientes.
        """
        if not self.is_connected:
            return 0
        
        import time
        key = f"antiraid:joins:{guild_id}"
        now = time.time()
        
        try:
            # Agregar el join con timestamp actual como score
            await self._client.zadd(key, {str(member_id): now})
            # Establecer TTL de 60 segundos
            await self._client.expire(key, 60)
            # Retornar cantidad de elementos
            return await self._client.zcard(key)
        except Exception as e:
            logger.error(f"Error en antiraid_add_join: {e}")
            return 0
    
    async def antiraid_get_recent_joins(self, guild_id: int, timeframe: int) -> list[int]:
        """
        Obtener lista de member_ids que se unieron en los últimos X segundos.
        """
        if not self.is_connected:
            return []
        
        import time
        key = f"antiraid:joins:{guild_id}"
        min_score = time.time() - timeframe
        
        try:
            # Obtener miembros con score (timestamp) mayor al mínimo
            members = await self._client.zrangebyscore(key, min_score, "+inf")
            return [int(m) for m in members]
        except Exception as e:
            logger.error(f"Error en antiraid_get_recent_joins: {e}")
            return []
    
    async def antiraid_clear_joins(self, guild_id: int) -> bool:
        """Limpiar el tracker de joins después de un raid"""
        if not self.is_connected:
            return False
        
        key = f"antiraid:joins:{guild_id}"
        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error en antiraid_clear_joins: {e}")
            return False
    
    async def antiraid_set_raid_mode(self, guild_id: int, duration: int = 60) -> bool:
        """Activar raid mode para un servidor (dura X segundos)"""
        if not self.is_connected:
            return False
        
        key = f"antiraid:raidmode:{guild_id}"
        try:
            await self._client.setex(key, duration, "1")
            return True
        except Exception as e:
            logger.error(f"Error en antiraid_set_raid_mode: {e}")
            return False
    
    async def antiraid_is_raid_mode(self, guild_id: int) -> bool:
        """Verificar si un servidor está en raid mode"""
        if not self.is_connected:
            return False
        
        key = f"antiraid:raidmode:{guild_id}"
        try:
            return await self._client.exists(key) > 0
        except Exception as e:
            logger.error(f"Error en antiraid_is_raid_mode: {e}")
            return False
    
    async def antiraid_get_settings(self, guild_id: int) -> Optional[dict]:
        """Obtener configuración de antiraid"""
        key = f"antiraid:settings:{guild_id}"
        return await self.get_json(key)
    
    async def antiraid_set_settings(self, guild_id: int, settings: dict) -> bool:
        """Establecer configuración de antiraid"""
        key = f"antiraid:settings:{guild_id}"
        return await self.set_json(key, settings, self.DEFAULT_TTL)
    
    async def antiraid_invalidate(self, guild_id: int) -> bool:
        """Invalidar caché de antiraid"""
        key = f"antiraid:settings:{guild_id}"
        return await self.delete(key)
    
    # ========== FakePerms Cache ==========
    
    async def get_fakeperms(self, guild_id: int) -> Optional[dict]:
        """Obtener configuración de fakeperms de un servidor"""
        key = f"fakeperms:{guild_id}"
        return await self.get_json(key)
    
    async def set_fakeperms(self, guild_id: int, data: dict) -> bool:
        """Establecer configuración de fakeperms"""
        key = f"fakeperms:{guild_id}"
        return await self.set_json(key, data, self.DEFAULT_TTL)
    
    async def invalidate_fakeperms(self, guild_id: int) -> bool:
        """Invalidar caché de fakeperms"""
        key = f"fakeperms:{guild_id}"
        return await self.delete(key)
    
    # ========== Filter Cache ==========
    
    async def get_filter_settings(self, guild_id: int) -> Optional[dict]:
        """Obtener configuración de filtros"""
        key = f"filter:{guild_id}"
        return await self.get_json(key)
    
    async def set_filter_settings(self, guild_id: int, settings: dict) -> bool:
        """Establecer configuración de filtros"""
        key = f"filter:{guild_id}"
        return await self.set_json(key, settings, 1800)  # 30 minutos
    
    async def invalidate_filter(self, guild_id: int) -> bool:
        """Invalidar caché de filtros"""
        key = f"filter:{guild_id}"
        return await self.delete(key)
    
    # ========== Logging Cache ==========
    
    async def get_logging_config(self, guild_id: int) -> Optional[dict]:
        """Obtener configuración de logging"""
        key = f"logging:{guild_id}"
        return await self.get_json(key)
    
    async def set_logging_config(self, guild_id: int, config: dict) -> bool:
        """Establecer configuración de logging"""
        key = f"logging:{guild_id}"
        return await self.set_json(key, config, self.DEFAULT_TTL)
    
    async def invalidate_logging(self, guild_id: int) -> bool:
        """Invalidar caché de logging"""
        key = f"logging:{guild_id}"
        return await self.delete(key)
    
    # ========== Autorole Cache ==========
    
    async def get_autorole(self, guild_id: int) -> Optional[dict]:
        """Obtener configuración de autorole"""
        key = f"autorole:{guild_id}"
        return await self.get_json(key)
    
    async def set_autorole(self, guild_id: int, data: dict) -> bool:
        """Establecer configuración de autorole"""
        key = f"autorole:{guild_id}"
        return await self.set_json(key, data, self.DEFAULT_TTL)
    
    async def invalidate_autorole(self, guild_id: int) -> bool:
        """Invalidar caché de autorole"""
        key = f"autorole:{guild_id}"
        return await self.delete(key)
    
    # ========== JoinDM Cache ==========
    
    async def get_joindm(self, guild_id: int) -> Optional[dict]:
        """Obtener configuración de joindm"""
        key = f"joindm:{guild_id}"
        return await self.get_json(key)
    
    async def set_joindm(self, guild_id: int, data: dict) -> bool:
        """Establecer configuración de joindm"""
        key = f"joindm:{guild_id}"
        return await self.set_json(key, data, self.DEFAULT_TTL)
    
    async def invalidate_joindm(self, guild_id: int) -> bool:
        """Invalidar caché de joindm"""
        key = f"joindm:{guild_id}"
        return await self.delete(key)
    
    # ========== Levels Cache ==========
    
    async def get_user_level(self, guild_id: int, user_id: int) -> Optional[dict]:
        """Obtener nivel de usuario"""
        key = f"levels:{guild_id}:{user_id}"
        return await self.get_json(key)
    
    async def set_user_level(self, guild_id: int, user_id: int, data: dict) -> bool:
        """Establecer nivel de usuario"""
        key = f"levels:{guild_id}:{user_id}"
        return await self.set_json(key, data, 300)  # 5 minutos
    
    async def invalidate_user_level(self, guild_id: int, user_id: int) -> bool:
        """Invalidar caché de nivel"""
        key = f"levels:{guild_id}:{user_id}"
        return await self.delete(key)


# Instancia global
cache = RedisCache()
