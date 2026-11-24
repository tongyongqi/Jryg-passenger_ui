"""Android UI failure evidence capture; no repeated orders, payments or cancellations."""

from pathlib import Path
import time

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Save device XML and screenshot on failure; evidence errors do not mask the original report."""
    outcome = yield
    report = outcome.get_result()
    instance = getattr(item, "instance", None)
    receipt_recorder = getattr(instance, "_receipt_report_phase", None)
    if callable(receipt_recorder):
        try:
            record = receipt_recorder(report)
            if record is not None:
                from pytest_html import extras
                report.extras = [*getattr(report, "extras", []),
                                 extras.json(record, name="requirement_and_defect_evidence")]
        except Exception as exc:
            report.sections.append(("receipt_record_error", f"{type(exc).__name__}: {exc}"))
    if not report.failed:
        return
    clients = getattr(instance, "clients", {}) if instance is not None else {}
    if not clients:
        return
    directory = Path(__file__).resolve().parents[1] / "report/diagnostics"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        report.sections.append(("evidence_dir_error", type(exc).__name__))
        return
    for index, client in enumerate(clients.values()):
        prefix = directory / f"{time.time_ns()}_{index}"
        try:
            prefix.with_suffix(".xml").write_text(client.driver.page_source, encoding="utf-8")
        except Exception as exc:
            report.sections.append((f"device_{index}_xml_error", type(exc).__name__))
        try:
            client.screenshot(str(prefix.with_suffix(".png")))
        except Exception as exc:
            report.sections.append((f"device_{index}_screenshot_error", type(exc).__name__))
        report.sections.append((f"device_{index}_evidence_prefix", str(prefix)))
