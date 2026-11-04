"""港版 iOS 测试用例 conftest —— pytest 夹具与钩子配置。

本文件定义 session 级和 function 级的 pytest 夹具（fixture），
仅负责测试生命周期、请求时限与失败取证，不自动重下单、重付或收车。
在用例执行前后自动准备/清理测试环境：

  1. bounded_wda_requests  ：session 级，限制 WDA HTTP 超时为 20s，避免卡死
  2. pytest_runtest_makereport ：钩子，在用例执行后将报告挂到 item 上供后续判断
  3. ios_page_diagnostics  ：function 级，注入 IOSPageMonitor 到用例实例，
                             用例失败时自动保存卡点现场（页面树 XML + 截图 PNG）
"""

from pathlib import Path

import pytest
import wda

# 导入自动化配置，获取 WDA 地址等设备信息
from ui_framework.JRYG_config import SETTINGS
# 导入统一日志记录器，夹具中使用 logger 记录警告信息
from ui_framework.JRYG_logger import logger
# 导入页面监控器，用于失败时保存卡点现场
from ui_framework.JRYG_page_monitor import IOSPageMonitor

# 旧电子支付银行卡文件保留显式运行入口；目录扫描只收集新的独立银行卡场景。
collect_ignore = ["JRYG_test_ios_meter_epayment_order.py"]


@pytest.fixture(scope="session", autouse=True)
def bounded_wda_requests():
    """bounded_wda_requests —— session 级夹具，限制 WDA HTTP 请求超时。

    在整个测试 session 开始前将 wda.HTTP_TIMEOUT 设为 20 秒，
    防止页面卡死时单个请求无限等待导致整个用例挂起。
    session 结束后恢复原始超时值。

    :return: None（yield 之前为前置处理，之后为后置处理）。
    """
    # 保存原始超时值，session 结束后恢复
    previous = wda.HTTP_TIMEOUT
    # 限制 WDA HTTP 超时为 20 秒，避免页面卡死时无限等待
    wda.HTTP_TIMEOUT = 20
    yield
    # 恢复原始超时配置
    wda.HTTP_TIMEOUT = previous


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """pytest_runtest_makereport —— pytest 钩子函数，在报告生成阶段补充信息。

    将用例的 setup/call/teardown 阶段报告挂载到 item 对象上
    （如 item.rep_call），供后续夹具判断用例是否失败。

    :param item: 当前执行的用例对象。
    :param call: 本次调用阶段的执行结果。
    :return: None
    """
    outcome = yield
    # 获取本次阶段的测试报告
    report = outcome.get_result()
    # 将报告挂载到 item 上（属性名为 rep_setup / rep_call / rep_teardown）
    setattr(item, "rep_" + report.when, report)


@pytest.fixture(autouse=True)
def ios_page_diagnostics(request):
    """ios_page_diagnostics —— function 级夹具，注入页面监控器并处理失败现场。

    在每个用例执行前：
    - 检测用例实例是否有 client 属性（已连接 WDA 的用例）
    - 有则创建 IOSPageMonitor 并注入到 instance.monitor
    在每个用例执行后：
    - 检测用例是否失败（rep_call.failed）
    - 失败则自动调用 monitor.inspect() + monitor.capture() 保存卡点现场
    - 无论成功失败都关闭 monitor 的 HTTP 连接

    :return: None（yield 之前为前置处理，之后为后置处理）。
    """
    # 获取当前用例的类实例
    instance = request.instance
    # 无实例或未连接 WDA 的用例（如纯 API 用例），跳过页面监控
    if instance is None or not hasattr(instance, "client"):
        yield
        return

    # 创建页面监控器，卡点文件输出到 report/diagnostics 目录
    monitor = IOSPageMonitor(
        SETTINGS["device"]["wda_url"],
        Path(__file__).resolve().parents[1] / "report" / "diagnostics",
    )
    # 将监控器注入到用例实例，供用例内部使用
    instance.monitor = monitor

    yield

    # ---- 用例执行完毕的后置处理 ----
    try:
        # 获取 call 阶段的测试报告
        report = getattr(request.node, "rep_call", None)
        if report is not None and report.failed:
            # 用例失败时保存卡点现场：先读取页面树，再截图
            try:
                monitor.inspect(timeout=5)
            except Exception as exc:
                logger.warning("失败后页面读取不可用: %s", exc)
            # 保存页面树 XML + 截图 PNG 到 diagnostics 目录
            monitor.capture(request.node.name)
    except Exception as exc:
        # 卡点保存失败不影响原始错误信息
        logger.warning("失败现场保存异常，不覆盖用例错误: %s", exc)
    finally:
        # 关闭监控器的 HTTP 连接
        monitor.close()
