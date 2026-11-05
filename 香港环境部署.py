#!/usr/bin/env python3
"""香港环境部署：通过香港 Jenkins API 将 k8s 服务部署到指定环境和分支。

与国内环境部署逻辑完全一致，仅以下配置不同：
  - Jenkins 地址：http://jk-test.sunlightmobility.hk
  - Jenkins 账号：dongyongqi
  - 可选环境：dev / test / test1~test7 / pre
  - 密码环境变量：HK_JENKINS_PASSWORD（国内为 JRYG_JENKINS_PASSWORD）

工作流程：
  1. 选择部署环境
  2. 加载该环境支持的服务列表（从 Jenkins 自动发现）
  3. 交互式选择服务（支持关键词搜索、编号多选、范围选择）
  4. 选择共同分支（自动取所有已选服务的分支交集）
  5. 预览部署计划，确认后触发 Jenkins 构建
  6. 并行等待所有构建完成，显示实时进度条

运行模式：
  - 不带参数：终端交互模式（默认）
  - --gui：打开 Tkinter 窗口选择
  - --env / --branch / --services：命令行参数模式（默认仅预检，加 --execute 才部署）

安全说明：
  - 密码只从环境变量 HK_JENKINS_PASSWORD 或交互输入读取，不写入代码
  - 不写入日志、不输出到命令行
"""

import argparse
import os
import sys
from typing import Dict, List, Optional, Sequence

# 导入国内部署模块的全部功能
import 国内环境部署 as base
from 国内环境部署 import (
    JenkinsError, JenkinsJob, SelectionCancelled,
    add_crumb, build_session, common_job_branches, confirm,
    deployment_parameters, discover_jobs, execute_plan,
    login_password as _original_login_password, print_plan,
    select_in_terminal, select_services_in_terminal,
)

# ── 覆盖香港 Jenkins 配置 ──────────────────────────────────
# 香港 Jenkins 地址
base.DEFAULT_URL = "http://jk-test.sunlightmobility.hk"
# 默认 Jenkins 账号
base.DEFAULT_USERNAME = "dongyongqi"
# 默认部署分支和版本号
base.DEFAULT_BRANCH = "origin/master"
base.DEFAULT_VERSION = "master"
# 香港可选的部署环境列表（从香港 Jenkins 实际配置中获取）
base.ENV_CHOICES = (
    "dev", "test", "test1", "test2", "test3",
    "test4", "test5", "test6", "test7", "pre",
)


# ── 覆盖密码读取逻辑 ──────────────────────────────────────
def _hk_login_password(base_url: str, username: str, explicit=None):
    """获取香港 Jenkins 密码。

    优先级：参数传入 > 环境变量 HK_JENKINS_PASSWORD > 钥匙串 > 交互输入。
    """
    password = explicit or os.getenv("HK_JENKINS_PASSWORD")
    if not password:
        # 回退到国内部署的密码读取（钥匙串等）
        password = base.saved_password(base_url, username)
    if not password:
        import getpass
        password = getpass.getpass("Jenkins密码（隐藏输入）：")
    if not password:
        raise JenkinsError("Jenkins密码不能为空")
    return password


# 替换国内部署模块的密码读取函数
base.login_password = _hk_login_password


def _hk_run_terminal(args: argparse.Namespace) -> int:
    """香港终端交互模式入口：选环境→加载服务→选服务→选分支→确认→部署。

    与国内部署 run_terminal 逻辑完全一致，仅标题不同。
    """
    print("香港环境部署 · 终端选择（不会打开窗口）")
    environment = args.env or select_in_terminal("选择部署环境", base.ENV_CHOICES)[0]
    username = args.username
    base_url = args.url.rstrip("/")
    password = _hk_login_password(base_url, username, args.password)
    print(f"使用Jenkins账号：{username}（更换账号可使用 --username）")
    with build_session(base_url, username, password) as session:
        print(f"\n正在加载支持 {environment} 的服务…", flush=True)

        def progress(text: str) -> None:
            print("\r" + text.ljust(110), end="", flush=True)

        errors: List[str] = []
        # 香港 Jenkins 同样以 k8s_ 开头命名服务
        include = r"^(k8s_|test_h5_dcms$)" if args.include == r"^k8s_" else args.include
        jobs = discover_jobs(session, base_url, include, args.exclude, args.limit,
                             progress=progress, on_error=errors.append)
        print()
        available: Dict[str, JenkinsJob] = {}
        for job in jobs:
            try:
                deployment_parameters(job, environment, base.DEFAULT_BRANCH, args.version)
            except JenkinsError:
                continue
            available[job.name] = job
        print(f"已加载 {len(available)} 个支持 {environment} 的服务")
        for reason in errors:
            print("未加载：" + reason)
        names: List[str] = []
        while True:
            names = select_services_in_terminal(tuple(available), names)
            selected_jobs = [available[name] for name in names]
            add_crumb(session, base_url)
            try:
                branches = common_job_branches(session, selected_jobs, print)
            except JenkinsError as exc:
                print(f"无法选择共同分支：{exc}；请重新选择服务")
                continue
            break
        branch = select_in_terminal("选择全部已选服务的共同分支", branches, kind="branch")[0]
        plan = [(job, deployment_parameters(job, environment, branch, args.version))
                for job in selected_jobs]
        print("\n部署计划（尚未触发部署）：")
        print_plan(plan)
        if not confirm(environment, branch, len(plan)):
            print("预检结束，未触发任何部署。")
            return 0
        return execute_plan(session, base_url, plan, args.delay, args.wait)


# 替换 run_terminal
base.run_terminal = _hk_run_terminal


def _hk_parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """香港版参数解析：覆盖默认 URL、账号、环境列表、密码环境变量。"""
    parser = argparse.ArgumentParser(description="香港环境部署（无参数默认终端选择；参数模式默认只预检）")
    parser.add_argument("--url", default=base.DEFAULT_URL, help="Jenkins 地址")
    parser.add_argument("--username", default=os.getenv("HK_JENKINS_USER", base.DEFAULT_USERNAME))
    parser.add_argument("--password", default=os.getenv("HK_JENKINS_PASSWORD"),
                        help="不建议直接传入；优先使用 HK_JENKINS_PASSWORD")
    parser.add_argument("--env", choices=base.ENV_CHOICES, help="目标部署环境；交互模式可在终端选择")
    parser.add_argument("--branch", default=base.DEFAULT_BRANCH,
                        help="目标Git分支，如 master、release/x 或 origin/release/x")
    parser.add_argument("--version", default=base.DEFAULT_VERSION,
                        help="部署版本VER；非多版本部署通常保持master")
    parser.add_argument("--include", default=r"^k8s_",
                        help="服务名包含规则（正则）；可用于只部署特定服务")
    parser.add_argument("--exclude", help="服务名排除规则（正则）")
    parser.add_argument("--limit", type=int, help="仅处理前 N 个服务，用于调试")
    parser.add_argument("--delay", type=float, default=0.5, help="触发服务之间的间隔秒数")
    parser.add_argument("--wait", action="store_true", default=True,
                        help="触发后等待每个Jenkins构建完成并显示进度（默认开启）")
    parser.add_argument("--no-wait", dest="wait", action="store_false",
                        help="仅触发部署，不等待构建结果")
    parser.add_argument("--execute", action="store_true", help="真正触发部署；缺省仅预检")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认，适用于受控 CI")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--gui", action="store_true", help="显式打开图形界面")
    modes.add_argument("--interactive", action="store_true", help="在终端选择环境、多个服务和共同分支")
    return parser.parse_args(argv)


# 替换 parse_args
base.parse_args = _hk_parse_args


def main(argv: Optional[Sequence[str]] = None) -> int:
    """程序入口：调用国内部署的 main，使用覆盖后的香港配置。"""
    return base.main(argv)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SelectionCancelled, KeyboardInterrupt, EOFError):
        print("\n已退出终端选择；已触发的构建不会自动撤销。")
        sys.exit(0)
    except (JenkinsError, Exception) as exc:
        import traceback
        traceback.print_exc()
        sys.exit(1)
