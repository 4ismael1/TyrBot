"""
Sistema simple de licencias por servidor
"""

from __future__ import annotations

import secrets
import string
import time
from datetime import datetime
from typing import Optional

from pymongo.errors import DuplicateKeyError

from core.database import database
from core.cache import cache


class LicenseManager:
    """Gestor de licencias con cache local + Redis"""

    DEFAULT_TTL = 1800  # 30 minutos

    def __init__(self, db=database, cache_client=cache):
        self.db = db
        self.cache = cache_client
        self._local_cache: dict[int, tuple[bool, float]] = {}
        self._ttl = self.DEFAULT_TTL

    def _get_local(self, guild_id: int) -> Optional[bool]:
        data = self._local_cache.get(guild_id)
        if not data:
            return None
        status, expires_at = data
        if time.time() > expires_at:
            self._local_cache.pop(guild_id, None)
            return None
        return status

    def _set_local(self, guild_id: int, status: bool) -> None:
        self._local_cache[guild_id] = (status, time.time() + self._ttl)

    async def invalidate(self, guild_id: int) -> None:
        """Invalidar cache local y Redis para un servidor"""
        self._local_cache.pop(guild_id, None)
        try:
            await self.cache.delete_license_status(guild_id)
        except Exception:
            pass

    async def is_licensed(self, guild_id: int) -> bool:
        """Verificar si un servidor tiene licencia activa"""
        local = self._get_local(guild_id)
        if local is not None:
            return local

        cached = await self.cache.get_license_status(guild_id)
        if cached is not None:
            self._set_local(guild_id, cached)
            return cached

        doc = await self.db.licenses.find_one({
            "guild_id": guild_id,
            "status": "active"
        })
        status = doc is not None
        await self.cache.set_license_status(guild_id, status, ttl=self._ttl)
        self._set_local(guild_id, status)
        return status

    def normalize_key(self, key: str) -> str:
        return key.strip().upper()

    def _generate_key(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
        return f"TYR-{parts[0]}-{parts[1]}-{parts[2]}"

    async def generate_keys(self, count: int, created_by: int) -> list[str]:
        """Generar licencias nuevas"""
        keys: list[str] = []
        for _ in range(count):
            for _ in range(10):
                key = self._generate_key()
                doc = {
                    "key": key,
                    "status": "active",
                    "created_at": datetime.utcnow(),
                    "created_by": created_by,
                }
                try:
                    await self.db.licenses.insert_one(doc)
                    keys.append(key)
                    break
                except DuplicateKeyError:
                    continue
            else:
                raise RuntimeError("No se pudo generar una licencia única")
        return keys

    async def redeem(self, key: str, guild_id: int, user_id: int) -> tuple[bool, str]:
        """Canjear licencia para un servidor"""
        normalized = self.normalize_key(key)
        doc = await self.db.licenses.find_one({"key": normalized})
        if not doc:
            return False, "invalid"
        if doc.get("status") != "active":
            return False, "revoked"
        if doc.get("guild_id") and doc.get("guild_id") != guild_id:
            return False, "used_other"
        if doc.get("guild_id") == guild_id:
            return True, "already"

        await self.db.licenses.update_one(
            {"key": normalized},
            {"$set": {
                "guild_id": guild_id,
                "redeemed_by": user_id,
                "redeemed_at": datetime.utcnow()
            }}
        )
        await self.invalidate(guild_id)
        return True, "ok"

    async def revoke(self, key: str, revoked_by: int) -> tuple[bool, Optional[dict]]:
        """Revocar licencia"""
        normalized = self.normalize_key(key)
        doc = await self.db.licenses.find_one({"key": normalized})
        if not doc:
            return False, None

        await self.db.licenses.update_one(
            {"key": normalized},
            {"$set": {
                "status": "revoked",
                "revoked_by": revoked_by,
                "revoked_at": datetime.utcnow()
            }}
        )
        if doc.get("guild_id"):
            await self.invalidate(doc["guild_id"])
        return True, doc

    async def get_license(self, key: str) -> Optional[dict]:
        normalized = self.normalize_key(key)
        return await self.db.licenses.find_one({"key": normalized})

    async def get_guild_license(self, guild_id: int) -> Optional[dict]:
        return await self.db.licenses.find_one({"guild_id": guild_id, "status": "active"})

    async def list_licenses(self, status: str | None = None, limit: int = 100) -> list[dict]:
        query: dict = {}
        if status == "active":
            query = {"status": "active", "guild_id": {"$exists": True}}
        elif status == "unused":
            query = {
                "status": "active",
                "$or": [{"guild_id": {"$exists": False}}, {"guild_id": None}]
            }
        elif status == "revoked":
            query = {"status": "revoked"}

        cursor = self.db.licenses.find(query).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=None)


license_manager = LicenseManager()

