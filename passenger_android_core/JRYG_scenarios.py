"""HK Android main-flow six-scenario registry."""

import importlib.util
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SCENARIOS = (
    ("JRYG_test_android_meter_cash_order.py", "TestMeterCashAndroid"),
    ("JRYG_test_android_meter_epayment_bankcard_order.py", "TestMeterEpaymentBankcardAndroid"),
    ("JRYG_test_android_meter_epayment_alipay_order.py", "TestMeterEpaymentAlipayAndroid"),
    ("JRYG_test_android_meter_alipay_order.py", "TestMeterAlipayAndroid"),
    ("JRYG_test_android_charter_alipay_order.py", "TestCharterAlipayAndroid"),
    ("JRYG_test_android_charter_bankcard_order.py", "TestCharterBankcardAndroid"),
)


def scenario_nodes():
    """Return registered main-flow test nodes."""
    nodes = []
    main_dir = BASE_DIR / "cases" / "main_flow_cases"
    for filename, class_name in SCENARIOS:
        path = main_dir / filename
        if not path.is_file():
            raise RuntimeError(f"Main-flow scenario file missing: {filename}")
        nodes.append(f"{path}::{class_name}::test_order_flow")
    return nodes


def android_scenarios():
    """Yield Android scenario classes."""
    for filename, class_name in SCENARIOS:
        path = BASE_DIR / "cases" / "main_flow_cases" / filename
        spec = importlib.util.spec_from_file_location("hk_android_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield getattr(module, class_name)
