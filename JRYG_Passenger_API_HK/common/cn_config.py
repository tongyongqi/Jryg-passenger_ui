"""大陆接口自动化统一配置管理。

与香港的 hk_config.py 平行，存放大陆环境配置，同样支持通过环境变量覆盖。

使用方式：
    from JRYG_Passenger_API_HK.common.cn_config import config

    # 读取配置
    redis_host = config.REDIS_HOST

环境变量一览（优先级高于配置文件默认值）：
    # Redis 连接
    CN_REDIS_HOST            Redis 主机
    CN_REDIS_PORT            Redis 端口
    CN_REDIS_PASSWORD        Redis 密码
    CN_REDIS_DB              Redis 数据库
    CN_REDIS_ENV             Redis 环境标识（test6 / pre）

    # 通用
    CN_REQUEST_TIMEOUT       请求超时（秒）
"""

import os


class CNConfig:
    """大陆接口自动化统一配置（单例模式，全局共享）。"""

    # ==================== Redis 连接配置 ====================

    # Redis 环境标识：test6（测试6）/ pre（预发布）
    # 用于区分多套 Redis 实例，默认测试6
    REDIS_ENV = os.environ.get("CN_REDIS_ENV", "test6")

    # 各环境的 Redis 连接信息
    # 格式: {环境标识: {"host":..., "port":..., "password":..., "db":...}}
    REDIS_ENVIRONMENTS = {
        # 测试6环境（域名需 VPN 内网 DNS；也可直连 IP 172.19.96.101 / 172.19.19.204）
        "test6": {
            "host": os.environ.get("CN_REDIS_HOST", "redis.tx-test6.jryghq.cn"),
            "port": int(os.environ.get("CN_REDIS_PORT", "6379")),
            "password": os.environ.get("CN_REDIS_PASSWORD", "jryg_tx_dev@nPYT90uU1pkJTmEN"),
            "db": int(os.environ.get("CN_REDIS_DB", "8")),
        },
        # pre 预发布环境（内网地址，密码含数字0非字母O）
        "pre": {
            "host": os.environ.get("CN_PRE_REDIS_HOST", "192.168.22.2"),
            "port": int(os.environ.get("CN_PRE_REDIS_PORT", "6379")),
            "password": os.environ.get("CN_PRE_REDIS_PASSWORD", "RC0WQhkWxU"),
            "db": int(os.environ.get("CN_PRE_REDIS_DB", "8")),
        },
    }

    # 当前生效的 Redis 连接信息
    REDIS_HOST = REDIS_ENVIRONMENTS[REDIS_ENV]["host"]
    REDIS_PORT = REDIS_ENVIRONMENTS[REDIS_ENV]["port"]
    REDIS_PASSWORD = REDIS_ENVIRONMENTS[REDIS_ENV]["password"]
    REDIS_DB = REDIS_ENVIRONMENTS[REDIS_ENV]["db"]

    # ==================== 通用配置 ====================

    # 请求超时（秒）
    REQUEST_TIMEOUT = int(os.environ.get("CN_REQUEST_TIMEOUT", "15"))


# 全局单例
config = CNConfig()
