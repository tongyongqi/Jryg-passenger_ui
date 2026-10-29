"""香港 iOS 用例的请求超时和失败现场。"""

from pathlib import Path

import pytest
import wda

from jryg_hk_ios.JRYG_config import SETTINGS
from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_page_monitor import IOSPageMonitor


@pytest.fixture(scope="session", autouse=True)
def bounded_wda_requests():
    """bounded_wda_requests —— pytest 夹具函数，在用例执行前后准备或清理测试环境。

        :return: None（yield 之前为前置处理，之后为后置处理）。"""
    previous = wda.HTTP_TIMEOUT
    wda.HTTP_TIMEOUT = 20
    yield
    wda.HTTP_TIMEOUT = previous


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """pytest_runtest_makereport —— pytest 钩子函数，在报告生成阶段补充断言、
        标记结果或收集失败现场信息。

        :param item: 当前执行的用例对象。
        :param call: 本次调用阶段的执行结果。
        :return: None"""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.passed and item.path.name == "JRYG_test_ios_e2e_order.py":
        if getattr(item.instance, "e2e_verified", False) is not True:
            report.outcome = "failed"
            report.longrepr = "未完成真实订单、目标司机和支付终态校验，禁止E2E通过"
        else:
            report.user_properties.append(("order_verified", True))
    setattr(item, "rep_" + report.when, report)


@pytest.fixture(autouse=True)
def ios_page_diagnostics(request):
    """ios_page_diagnostics —— pytest 夹具函数，在用例执行前后准备或清理测试环境。

        :return: None（yield 之前为前置处理，之后为后置处理）。"""
    instance = request.instance
    if instance is None or not hasattr(instance, "client"):
        yield
        return
    monitor = IOSPageMonitor(
        SETTINGS["device"]["wda_url"],
        Path(__file__).resolve().parents[1] / "report" / "diagnostics",
    )
    instance.monitor = monitor
    yield
    try:
        report = getattr(request.node, "rep_call", None)
        if report is not None and report.failed:
            try:
                monitor.inspect(timeout=5)
            except Exception as exc:
                logger.warning("失败后页面读取不可用: %s", exc)
            monitor.capture(request.node.name)
    except Exception as exc:
        logger.warning("失败现场保存异常，不覆盖用例错误: %s", exc)
    finally:
        monitor.close()
