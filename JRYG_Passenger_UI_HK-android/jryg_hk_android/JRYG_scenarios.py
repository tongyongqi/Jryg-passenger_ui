"""安卓六个独立订单场景清单，顺序与已验证iOS默认清单一致。"""

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
OPTIONAL_SCENARIOS = (
    ("JRYG_test_android_meter_epayment_target_order.py", "TestMeterEpaymentTargetOrderAndroid"),
)


def scenario_nodes(*, include_optional=False):
    nodes = []
    scenarios = SCENARIOS + OPTIONAL_SCENARIOS if include_optional else SCENARIOS
    for filename, class_name in scenarios:
        path = BASE_DIR / "cases" / filename
        if not path.is_file():
            raise RuntimeError(f"安卓独立订单场景缺失：{filename}")
        nodes.append(f"{path}::{class_name}::test_order_flow")
    return nodes


def android_scenarios():
    for filename, class_name in SCENARIOS:
        path = BASE_DIR / "cases" / filename
        spec = importlib.util.spec_from_file_location("hk_android_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield getattr(module, class_name)
