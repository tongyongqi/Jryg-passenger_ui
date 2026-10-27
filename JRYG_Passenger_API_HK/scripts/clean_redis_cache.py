"""清空 Redis 司机派单缓存 — 独立可执行脚本。

功能：清理 dispatcher:driver 下的 agent 和 phone 缓存，避免上次测试的派单缓存干扰调度。
  - agent:repeat:*   → 司机重复派单限制缓存
  - phone:repeat:*   → 司机手机号重复派单限制缓存

说明：只清理 agent 和 phone 两类缓存，不清空 grab（抢单活动）和 publish（派发轮次）。

单独执行方式：
    # 方式1：直接运行（清理全部 driver 缓存）
    python JRYG_Passenger_API_HK/scripts/clean_redis_cache.py

    # 方式2：只查看不删除
    python JRYG_Passenger_API_HK/scripts/clean_redis_cache.py --list

    # 方式3：只清理指定司机的缓存
    python JRYG_Passenger_API_HK/scripts/clean_redis_cache.py --driver-id 31

    # 方式4：安静模式（不打印每个 key）
    python JRYG_Passenger_API_HK/scripts/clean_redis_cache.py --quiet

说明：
    - 本脚本可独立运行，不依赖 pytest
    - 接口自动化测试每次执行时仍会自动调用 clean_driver_cache()
      （在 test_e2e_full_flow.py 和 JRYG_test_hk_dual_end_flow.py 的 setup 中）
    - 本脚本仅作为手动清理工具，方便在测试前/后单独执行
"""

import sys
import os
import argparse

# 将项目根目录添加到 sys.path，确保 common 模块可被正确导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from JRYG_Passenger_API_HK.common.redis_cache_cleaner import (
    clean_driver_cache,
    list_driver_cache,
)
from JRYG_Passenger_API_HK.common.hk_config import config


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="清空香港 Redis 司机派单缓存（可独立执行）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                      # 清理全部 driver 缓存
  %(prog)s --list               # 只查看缓存，不删除
  %(prog)s --driver-id 31       # 只清理指定司机的缓存
  %(prog)s --quiet              # 安静模式，不打印每个 key
""",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="只查看当前缓存，不删除",
    )
    parser.add_argument(
        "--driver-id",
        type=int,
        default=None,
        help="只清理指定司机的缓存（传入 driver_id）",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="安静模式，不逐个打印删除的 key",
    )
    args = parser.parse_args()

    # 打印连接信息
    print(f"Redis: {config.REDIS_HOST}:{config.REDIS_PORT} (db={config.REDIS_DB})")
    print()

    if args.list:
        # 只查看模式
        list_driver_cache()
        return

    # 清理模式
    verbose = not args.quiet
    driver_id = args.driver_id

    if driver_id:
        print(f"清理司机 {driver_id} 的 Redis 缓存...")
    else:
        print("清理全部 driver Redis 缓存...")

    try:
        deleted = clean_driver_cache(driver_id=driver_id, verbose=verbose)
        print()
        if deleted > 0:
            print(f"✓ 清理完成，共删除 {deleted} 个 key")
        else:
            print("✓ 清理完成，无缓存需要清理")
    except Exception as e:
        print(f"✗ 清理失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
