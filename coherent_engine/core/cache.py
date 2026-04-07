# core/cache.py 
import json 
from typing import Dict, Any, Optional 
import redis.asyncio as redis 

class LockPointCache: 
    """锁点缓存（加速）""" 
    def __init__(self, redis_url: str = "redis://localhost:6379"): 
        self.redis_url = redis_url
        self.redis = None
        self.local_cache = {}  # 内存降级缓存
        self.default_ttl = 3600  # 1小时 

    async def _ensure_redis(self):
        if self.redis is None:
            try:
                self.redis = redis.from_url(self.redis_url, decode_responses=True)
                await self.redis.ping()
            except Exception:
                self.redis = False # 标记为不可用
                print("Redis unavailable, using local memory cache.")

    async def get(self, key: str) -> Optional[Dict[str, Any]]: 
        await self._ensure_redis()
        if self.redis:
            try:
                data = await self.redis.get(f"lockpoint:{key}") 
                return json.loads(data) if data else None
            except Exception:
                pass
        return self.local_cache.get(key)

    async def set(self, key: str, value: Dict[str, Any], ttl: int = None): 
        await self._ensure_redis()
        if self.redis:
            try:
                await self.redis.setex( 
                    f"lockpoint:{key}", 
                    ttl or self.default_ttl, 
                    json.dumps(value) 
                )
                return
            except Exception:
                pass
        self.local_cache[key] = value

    async def close(self): 
        if self.redis:
            await self.redis.close() 
