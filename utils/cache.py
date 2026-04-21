"""
Simple in-memory caching con TTL
Uso: cache.set("key", valor, ttl_segundos=300)
     valor = cache.get("key")
"""
import time
import threading
from typing import Any, Optional

class SimpleCache:
    def __init__(self):
        self.data = {}
        self.lock = threading.Lock()

    def set(self, key: str, value: Any, ttl_segundos: int = 300):
        """Guardar valor con TTL (time to live en segundos)"""
        with self.lock:
            self.data[key] = {
                "value": value,
                "expires_at": time.time() + ttl_segundos
            }

    def get(self, key: str) -> Optional[Any]:
        """Obtener valor, retorna None si expiró o no existe"""
        with self.lock:
            if key not in self.data:
                return None

            entry = self.data[key]
            if time.time() > entry["expires_at"]:
                # Expiró
                del self.data[key]
                return None

            return entry["value"]

    def invalidate(self, pattern: str = None):
        """Invalidar caché
        Si pattern=None: limpiar todo
        Si pattern="operario_*": limpiar keys que coincidan
        """
        with self.lock:
            if pattern is None:
                self.data.clear()
            else:
                # Simple pattern matching (prefix)
                keys_to_delete = [k for k in self.data.keys() if k.startswith(pattern)]
                for k in keys_to_delete:
                    del self.data[k]

    def cleanup_expired(self):
        """Eliminar entries expirados"""
        with self.lock:
            now = time.time()
            expired_keys = [
                k for k, v in self.data.items()
                if now > v["expires_at"]
            ]
            for k in expired_keys:
                del self.data[k]

# Instancia global
_cache = SimpleCache()

def set_cache(key: str, value: Any, ttl_segundos: int = 300):
    """API global para guardar en caché"""
    _cache.set(key, value, ttl_segundos)

def get_cache(key: str) -> Optional[Any]:
    """API global para obtener del caché"""
    return _cache.get(key)

def invalidate_cache(pattern: str = None):
    """API global para invalidar caché"""
    _cache.invalidate(pattern)

def cleanup_cache():
    """API global para limpiar expirados"""
    _cache.cleanup_expired()
