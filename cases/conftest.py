"""Android UI 失败留存现场；不重复下单、支付或取消订单。"""

from pathlib import Path
import time

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """失败阶段保存现有设备XML和截图；取证异常不覆盖原始失败报告。"""
    outcome = yield
    report = outcome.get_result()
    if not report.failed:
        return
    instance = getattr(item, "instance", None)
    clients = getattr(instance, "clients", {}) if instance is not None else {}
    directory = Path(__file__).resolve().parents[1] / "report/diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    for index, client in enumerate(clients.values()):
        prefix = directory / f"{time.time_ns()}_{item.name}_{index}"
        try:
            prefix.with_suffix(".xml").write_text(client.driver.page_source, encoding="utf-8")
            client.screenshot(str(prefix.with_suffix(".png")))
        except Exception:
            pass
