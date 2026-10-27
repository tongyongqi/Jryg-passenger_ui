"""Redis 缓存清理工具（支持香港 / 大陆多环境）。

每次执行接口自动化测试前，清理 dispatcher:driver 下的 agent 和 phone 缓存：
  - agent:repeat:*  → 司机重复派单限制缓存
  - phone:repeat:*  → 司机手机号重复派单限制缓存

支持的 Redis 环境：
  - 香港-test    香港测试环境（172.31.104.4:6379 db=8）
  - 大陆-test6   大陆测试6环境（redis.tx-test6.jryghq.cn:6379 db=8）
  - 大陆-pre     大陆 pre 预发布环境（192.168.22.2:6379 db=8）

用法：
    from JRYG_Passenger_API_HK.common.redis_cache_cleaner import clean_driver_cache

    clean_driver_cache()                              # 默认香港-test 环境
    clean_driver_cache(env="大陆-test6")              # 大陆测试6环境
    clean_driver_cache(env="大陆-pre")                # 大陆 pre 环境
    clean_driver_cache(driver_id=31)                  # 只清理指定司机
"""

import redis

from JRYG_Passenger_API_HK.common.hk_config import config as hk_config
from JRYG_Passenger_API_HK.common.cn_config import config as cn_config

# 支持的环境标识 -> Redis 连接参数
ENVIRONMENTS = {
    # 香港测试环境
    "香港-test": {
        "name": "香港测试环境",
        "host": hk_config.REDIS_HOST,
        "port": hk_config.REDIS_PORT,
        "password": hk_config.REDIS_PASSWORD,
        "db": hk_config.REDIS_DB,
    },
    # 大陆测试6环境
    "大陆-test6": {
        "name": "大陆测试6环境",
        "host": cn_config.REDIS_ENVIRONMENTS["test6"]["host"],
        "port": cn_config.REDIS_ENVIRONMENTS["test6"]["port"],
        "password": cn_config.REDIS_ENVIRONMENTS["test6"]["password"],
        "db": cn_config.REDIS_ENVIRONMENTS["test6"]["db"],
    },
    # 大陆 pre 预发布环境
    "大陆-pre": {
        "name": "大陆pre预发布环境",
        "host": cn_config.REDIS_ENVIRONMENTS["pre"]["host"],
        "port": cn_config.REDIS_ENVIRONMENTS["pre"]["port"],
        "password": cn_config.REDIS_ENVIRONMENTS["pre"]["password"],
        "db": cn_config.REDIS_ENVIRONMENTS["pre"]["db"],
    },
}

# 默认环境
DEFAULT_ENV = "香港-test"

# 需要清理的 key 模式（只清理 agent 和 phone，不清空 grab/publish）
DRIVER_CACHE_PATTERNS = [
    "dispatcher:driver:agent:*",    # agent 缓存（司机重复派单限制）
    "dispatcher:driver:phone:*",    # phone 缓存（手机号重复派单限制）
]


def resolve_env(env=None):
    """解析环境标识，返回对应的 Redis 连接参数。

    :param env: 环境标识，如 "香港-test" / "大陆-test6" / "大陆-pre"；None 表示默认环境
    :return: 包含 host/port/password/db/name 的 dict
    :raises ValueError: 环境标识不存在时抛出
    """
    env = env or DEFAULT_ENV
    if env not in ENVIRONMENTS:
        supported = ", ".join(ENVIRONMENTS.keys())
        raise ValueError(f"未知环境标识 '{env}'，可选值: {supported}")
    return ENVIRONMENTS[env]


def get_redis_client(env=None):
    """获取指定环境的 Redis 连接。"""
    conf = resolve_env(env)
    return redis.Redis(
        host=conf["host"],
        port=conf["port"],
        password=conf["password"],
        db=conf["db"],
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=10,
    )


def _ping_or_raise(r, conf):
    """执行 PING，连接失败时抛出带提示信息的异常。"""
    try:
        r.ping()
    except redis.exceptions.ConnectionError as e:
        raise ConnectionError(
            f"无法连接 Redis（{conf['name']} {conf['host']}:{conf['port']}）。"
            f"请检查网络/VPN 是否已连接目标环境。\n原始错误: {e}"
        ) from e
    except redis.exceptions.AuthenticationError as e:
        raise ConnectionError(
            f"Redis 认证失败（{conf['name']}）。请检查密码配置是否正确。\n原始错误: {e}"
        ) from e


def clean_driver_cache(driver_id=None, verbose=True, env=None):
    """清理 driver 相关的 Redis 缓存。

    :param driver_id: 如果指定，只清理该司机的缓存；否则清理全部
    :param verbose: 是否打印清理详情
    :param env: 环境标识，如 "香港-test" / "大陆-test6" / "大陆-pre"；None 表示默认环境
    :return: 清理的 key 数量
    """
    conf = resolve_env(env)
    r = get_redis_client(env)
    _ping_or_raise(r, conf)

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


def list_driver_cache(env=None):
    """列出指定环境当前所有 driver 缓存 key（不删除）。"""
    conf = resolve_env(env)
    r = get_redis_client(env)
    _ping_or_raise(r, conf)

    print(f"=== 当前 driver Redis 缓存（{conf['name']}） ===")
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

    # 命令行：python redis_cache_cleaner.py [环境] [list]
    _env = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "list" else None
    if len(sys.argv) > 1 and sys.argv[-1] == "list":
        list_driver_cache(env=_env)
    else:
        print(f"清理 driver Redis 缓存（{resolve_env(_env)['name']}）...")
        clean_driver_cache(env=_env)
        print("清理完成。")
