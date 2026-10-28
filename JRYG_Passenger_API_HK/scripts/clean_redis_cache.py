"""清空 Redis 司机派单缓存 — 独立可执行脚本（支持香港 / 大陆多环境）。

功能：清理 dispatcher:driver 下的 agent 和 phone 缓存，避免上次测试的派单缓存干扰调度。
  - agent:repeat:*   → 司机重复派单限制缓存
  - phone:repeat:*   → 司机手机号重复派单限制缓存

说明：只清理 agent 和 phone 两类缓存，不清空 grab（抢单活动）和 publish（派发轮次）。

支持的环境：
  - 香港-test    香港测试环境
  - 大陆-test6   大陆测试6环境
  - 大陆-pre     大陆 pre 预发布环境

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
    resolve_env,
    ENVIRONMENTS,
    DEFAULT_ENV,
)


def prompt_env():
    """交互式选择 Redis 环境。

    打印环境列表，等待用户输入序号，返回选中的环境标识。
    """
    env_keys = list(ENVIRONMENTS.keys())
    print("=" * 50)
    print("  请选择要清理的 Redis 环境")
    print("=" * 50)
    for i, key in enumerate(env_keys, 1):
        conf = ENVIRONMENTS[key]
        print(f"  {i}. {key:<12} {conf['name']}  "
              f"({conf['host']}:{conf['port']} db={conf['db']})")
    print("=" * 50)

    while True:
        try:
            raw = input(f"请输入序号 (1-{len(env_keys)})，回车默认 [{DEFAULT_ENV}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            sys.exit(0)

        if raw == "":
            selected = DEFAULT_ENV
            break

        # 支持输入序号或环境标识
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(env_keys):
                selected = env_keys[idx - 1]
                break
        elif raw in ENVIRONMENTS:
            selected = raw
            break

        print(f"  ✗ 无效输入 '{raw}'，请重新选择")

    return selected


def main():
    """命令行入口。"""
    env_choices = list(ENVIRONMENTS.keys())
    env_help = "\n".join(
        f"  {key:<12} {ENVIRONMENTS[key]['name']}  "
        f"({ENVIRONMENTS[key]['host']}:{ENVIRONMENTS[key]['port']} db={ENVIRONMENTS[key]['db']})"
        for key in env_choices
    )

    parser = argparse.ArgumentParser(
        description="清空 Redis 司机派单缓存（支持香港/大陆多环境，可独立执行）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
可用环境:
{env_help}

示例:
  %(prog)s                      # 交互式选择环境后清理
  %(prog)s --env 大陆-test6      # 直接清理大陆测试6环境缓存
  %(prog)s --env 大陆-pre        # 直接清理大陆 pre 环境缓存
  %(prog)s --list               # 只查看缓存，不删除
  %(prog)s --driver-id 31       # 只清理指定司机的缓存
  %(prog)s --quiet              # 安静模式，不打印每个 key
""",
    )
    parser.add_argument(
        "--env",
        default=None,
        choices=env_choices,
        help="Redis 环境标识（不传则交互式选择）",
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

    # 如果未指定 --env，进入交互式选择
    if args.env is None:
        selected_env = prompt_env()
    else:
        selected_env = args.env

    # 解析环境并打印连接信息
    conf = resolve_env(selected_env)
    print()
    print(f"环境: {selected_env} ({conf['name']})")
    print(f"Redis: {conf['host']}:{conf['port']} (db={conf['db']})")
    print()

    if args.list:
        # 只查看模式
        try:
            list_driver_cache(env=selected_env)
        except Exception as e:
            print(f"✗ 查询失败: {e}")
            sys.exit(1)
        return

    # 清理模式
    verbose = not args.quiet
    driver_id = args.driver_id

    if driver_id:
        print(f"清理司机 {driver_id} 的 Redis 缓存...")
    else:
        print("清理全部 driver Redis 缓存...")

    try:
        deleted = clean_driver_cache(driver_id=driver_id, verbose=verbose, env=selected_env)
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
