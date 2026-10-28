"""香港 iOS 用例的请求超时和失败现场。"""

from pathlib import Path

import pytest
import wda

from jryg_hk_ios.JRYG_config import SETTINGS
from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_page_monitor import IOSPageMonitor


@pytest.fixture(scope="session", autouse=True)
def bounded_wda_requests():
    previous = wda.HTTP_TIMEOUT
    wda.HTTP_TIMEOUT = 20
    yield
    wda.HTTP_TIMEOUT = previous


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, "rep_" + report.when, report)


@pytest.fixture(autouse=True)
def ios_page_diagnostics(request):
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
