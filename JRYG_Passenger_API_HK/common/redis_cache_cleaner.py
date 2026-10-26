"""香港 Redis 缓存清理工具。

每次执行接口自动化测试前，清理 dispatcher:driver 下的缓存：
  - agent:repeat:*  → 司机重复派单限制缓存
  - phone:repeat:*  → 司机手机号重复派单限制缓存
  - grab:activity:* → 抢单活动缓存
  - publish:rounds:* → 派发轮次缓存

用法：
    from JRYG_Passenger_API_HK.common.redis_cache_cleaner import clean_driver_cache
    clean_driver_cache()          # 清理所有 driver 缓存
    clean_driver_cache(driver_id=311451)  # 只清理指定司机的缓存
"""

import os

import redis

# 香港 Redis 连接配置
REDIS_HOST = os.environ.get("HK_REDIS_HOST", "")
REDIS_PORT = int(os.environ.get("HK_REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("HK_REDIS_PASSWORD", "")
REDIS_DB = int(os.environ.get("HK_REDIS_DB", "8"))

# 需要清理的 key 模式
DRIVER_CACHE_PATTERNS = [
    "dispatcher:driver:agent:*",    # agent 缓存
    "dispatcher:driver:phone:*",    # phone 缓存
    "dispatcher:driver:grab:*",     # 抢单活动缓存
    "dispatcher:driver:publish:*",  # 派发轮次缓存
]


def get_redis_client():
    """获取 Redis 连接。"""
    if not REDIS_HOST or not REDIS_PASSWORD:
        raise ValueError("请设置 HK_REDIS_HOST 和 HK_REDIS_PASSWORD")
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
