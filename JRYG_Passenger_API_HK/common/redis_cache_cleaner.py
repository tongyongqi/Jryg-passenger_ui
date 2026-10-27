"""香港 Redis 缓存清理工具。

每次执行接口自动化测试前，清理 dispatcher:driver 下的 agent 和 phone 缓存：
  - agent:repeat:*  → 司机重复派单限制缓存
  - phone:repeat:*  → 司机手机号重复派单限制缓存

用法：
    from JRYG_Passenger_API_HK.common.redis_cache_cleaner import clean_driver_cache
    clean_driver_cache()          # 清理 agent + phone 缓存
    clean_driver_cache(driver_id=311451)  # 只清理指定司机的缓存
"""

import redis

from JRYG_Passenger_API_HK.common.hk_config import config

# 香港 Redis 连接配置（从统一配置读取，支持环境变量覆盖）
REDIS_HOST = config.REDIS_HOST
REDIS_PORT = config.REDIS_PORT
REDIS_PASSWORD = config.REDIS_PASSWORD
REDIS_DB = config.REDIS_DB

# 需要清理的 key 模式（只清理 agent 和 phone，不清空 grab/publish）
DRIVER_CACHE_PATTERNS = [
    "dispatcher:driver:agent:*",    # agent 缓存（司机重复派单限制）
    "dispatcher:driver:phone:*",    # phone 缓存（手机号重复派单限制）
]


def get_redis_client():
    """获取 Redis 连接。"""
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        db=REDIS_DB,
        decode_responses=True,
    )


def clean_driver_cache(driver_id=None, verbose=True):
    """清理 driver 相关的 Redis 缓存。

    :param driver_id: 如果指定，只清理该司机的缓存；否则清理全部
    :param verbose: 是否打印清理详情
    :return: 清理的 key 数量
    """
    r = get_redis_client()
    r.ping()

    total_deleted = 0

    for pattern in DRIVER_CACHE_PATTERNS:
        keys = r.keys(pattern)
        if driver_id:
            # 只清理指定司机的 key
            keys = [k for k in keys if str(driver_id) in k]

        if keys:
            deleted = r.delete(*keys)
            total_deleted += deleted
            if verbose:
                for k in keys:
                    print(f"  [Redis] 删除 {k}")
                print(f"  [Redis] {pattern} → 清理 {deleted} 个 key")

    if verbose:
        print(f"  [Redis] 共清理 {total_deleted} 个 driver 缓存 key")

    return total_deleted


def list_driver_cache():
    """列出当前所有 driver 缓存 key（不删除）。"""
    r = get_redis_client()
    r.ping()

    print("=== 当前 driver Redis 缓存 ===")
    for pattern in DRIVER_CACHE_PATTERNS:
        keys = r.keys(pattern)
        print(f"\n{pattern} ({len(keys)} 个):")
        for k in keys:
            t = r.type(k)
            if t == "string":
                v = r.get(k)
            elif t == "hash":
                v = r.hgetall(k)
            elif t == "set":
                v = r.smembers(k)
            elif t == "zset":
                v = r.zrange(k, 0, -1)
            else:
                v = ""
            print(f"  {k} ({t}) = {v}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        list_driver_cache()
    else:
        print("清理 driver Redis 缓存...")
        clean_driver_cache()
        print("清理完成。")
