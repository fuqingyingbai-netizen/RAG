# 导入json模块：用于把 Python 对象 转成 JSON字符串，也能把JSON字符串转回Python对象
import json

# 导入os模块：用于读取操作系统里的环境变量（比如Redis地址、密码等）
import os

# 导入类型提示工具：Any表示任意类型，Optional表示可以是None或指定类型
from typing import Any, Optional

# 导入redis库：用来连接和操作Redis缓存数据库
import redis


# 定义一个Redis缓存工具类，所有缓存操作都通过这个类来做
class RedisCache:
    # 构造函数：创建RedisCache对象时自动执行，做初始化配置
    def __init__(self):
        # 从环境变量读取Redis连接地址，没有就用默认本地地址：redis://localhost:6379/0
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        # 从环境变量读取key前缀，没有就用默认"supermew"
        # 作用：防止不同项目的key重名，所有key都会变成 supermew:xxx
        self.key_prefix = os.getenv("REDIS_KEY_PREFIX", "supermew")

        # 从环境变量读取默认缓存过期时间，没有就用300秒（5分钟）
        self.default_ttl = int(os.getenv("REDIS_CACHE_TTL_SECONDS", "300"))

        # 初始化客户端连接为None，延迟加载（用到时才真正连接，不浪费资源）
        self._client = None

    # 内部工具方法：获取Redis客户端连接（单例模式，只连一次）
    def _get_client(self):
        # 如果还没有创建连接
        if self._client is None:
            # 创建Redis连接，decode_responses=True 表示自动把bytes转成字符串
            self._client = redis.Redis.from_url(self.redis_url, decode_responses=True)
        # 返回已经建好的连接 
        return self._client

    # 内部工具方法：给key加前缀，避免key冲突
    def _key(self, key: str) -> str:
        # 比如传入"user1"，返回 "supermew:user1"
        return f"{self.key_prefix}:{key}"

    # 对外方法：从Redis获取JSON数据，并自动转回Python对象（dict/list等）
    def get_json(self, key: str) -> Optional[Any]:
        try:
            # 1. 从Redis获取带前缀的key对应的值
            value = self._get_client().get(self._key(key))

            # 2. 如果值不存在，返回None
            if not value:
                return None

            # 3. 把JSON字符串 → 转回Python对象（dict/list）
            return json.loads(value)

        # 如果出现任何异常（连不上、解析失败），直接返回None
        except Exception:
            return None

    # 对外方法：把Python对象（dict/list）存到Redis，自动转JSON，支持设置过期时间
    def set_json(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        try:
            # 1. 把Python对象 → 转成JSON字符串
            payload = json.dumps(value, ensure_ascii=False)

            # 2. 存入Redis，使用 setex（带过期时间）
            # ttl 不传就用默认300秒
            self._get_client().setex(self._key(key), ttl or self.default_ttl, payload)

        # 出错不崩溃，安静返回
        except Exception:
            return

    # 对外方法：删除指定key
    def delete(self, key: str) -> None:
        try:
            self._get_client().delete(self._key(key))
        except Exception:
            return

    # 对外方法：按通配符批量删除key 例如 delete_pattern("user:*")
    def delete_pattern(self, pattern: str) -> None:
        try:
            # 拼接成带前缀的pattern
            full_pattern = self._key(pattern)

            # 查找所有匹配的key
            keys = self._get_client().keys(full_pattern)

            # 如果有匹配的key，就批量删除
            if keys:
                self._get_client().delete(*keys)
        except Exception:
            return


# 创建一个全局可用的缓存实例，整个项目都用这一个连接
cache = RedisCache()