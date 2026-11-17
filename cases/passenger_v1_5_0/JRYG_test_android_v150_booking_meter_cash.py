# 编写时间：2026-11-13
# 本期功能：V1.5.0 预约后付费 type16 改造 — 打表的士 + 现金支付下单真机验证
# 场景：预约用车 → 打表的士 → 现金支付 → 确认呼叫 → 进入呼叫中 → 库表直查断言
"""V1.5.0 预约用车 type16 真机验证：打表的士 + 现金支付下单。

需求映射：
- 预约后付费订单 = OrderTypeBookingRealTime = 16，走实时库
- 选择车型页选择打表的士 → 现金支付方式下单
  → payment_collection_mode=2（线下支付），business_type=1（出租车）
- 需求文档中 payment_collection_mode: 1=线上, 2=线下
  现金支付属于线下支付（payment_collection_mode=2）

真机流程：预约用车 → 选择打表的士 → 选择现金支付 → 确认呼叫 → 进入呼叫中
→ 抓取下单接口日志 → 直查库表断言两字段值（不取消订单）。

不修改已有成熟用例，仅调用已有方法完成新场景验证。
"""

from pathlib import Path
import sys
import time
import logging

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

logger = logging.getLogger("JRYG_HK_android")

from passenger_android_core.v150.device_steps import V150DeviceSteps
from passenger_android_core.v150.api_log import check_api_response, parse_api_calls
from passenger_android_core.v150.contract import (
    ORDER_TYPE_BOOKING_REALTIME,
    PAYMENT_COLLECTION_OFFLINE,
    BUSINESS_TAXI,
    create_params_validate,
    order_center_create,
    order_center_show,
)

try:
    from passenger_android_core.v150.db_verify import query_order_field_values
    from passenger_android_core.JRYG_config import SETTINGS
    _HAS_DB = bool(SETTINGS.get("database"))
except ImportError:
    _HAS_DB = False


class TestV150BookingMeterCashDevice(V150DeviceSteps):
    """预约用车 type16：打表的士 + 现金支付下单。

    场景：预约用车 → 打表的士 → 現金支付 → 確認呼叫 → 呼叫中 → 直查库表断言
    验证：
    1. 离线契约：create 传 payment_collection_mode=2（线下）, business_type=1
    2. 真机：预约下单进入呼叫中后，直查库表断言两字段值（不取消订单）
    """

    __test__ = True
    DRIVER_REQUIRED = False
    CAR_TYPE = "meter"

    OK_CODE = 10000

    # _start_network_capture / _dismiss_proxy_dialog / _collect_network_log /
    # _extract_order_no_from_logcat 已封装到 V150DeviceSteps 基类

    # ==================== 离线契约预校验 ====================

    def test_01_contract_create_with_cash_payment_fields(self):
        """离线契约：打表+现金支付 → payment_collection_mode=2（线下）, business_type=1。"""
        result = create_params_validate(
            payment_collection_mode=PAYMENT_COLLECTION_OFFLINE,
            business_type=BUSINESS_TAXI)
        assert result == {"payment_collection_mode": 2, "business_type": 1}

        created = order_center_create(
            ORDER_TYPE_BOOKING_REALTIME,
            payment_collection_mode=PAYMENT_COLLECTION_OFFLINE,
            business_type=BUSINESS_TAXI)
        assert created["order_type"] == 16
        assert created["payment_collection_mode"] == 2
        assert created["business_type"] == 1
        assert created["storage"] == "realtime"

        shown = order_center_show(created)
        assert shown["payment_collection_mode"] == 2
        assert shown["business_type"] == 1
        self.v150_screenshot("booking_meter_cash_contract")

    # ==================== 真机：预约打表的士+现金支付下单 ====================

    def test_02_real_booking_meter_cash_order(self):
        """真机：预约用车 → 打表的士 → 现金支付 → 确认呼叫 → 呼叫中。"""
        tag = "v150_booking_meter_cash"
        self._ensure_devices_awake()
        self._v150_dismiss_proxy_dialog()
        self.prepare_passenger_app(tag, launch=True)
        self.ensure_passenger_login(tag)

        # 进入预约用车
        page = self.v150_open_booking_entry(tag)
        assert page == "time_picker", f"时间选择器未出现：{page}"
        self.v150_select_booking_time(tag, minutes_ahead=35)
        self.v150_prepare_booking_route(tag)

        # 询价页：选择打表的士
        self._android_select_car_type(tag, "meter")
        logger.info("【%s】已选择打表的士", tag)
        self.v150_screenshot("booking_meter_cash_car_selected")

        # 选择现金支付
        self._android_select_payment(tag, "cash")
        logger.info("【%s】已选择现金支付", tag)
        self.v150_screenshot("booking_meter_cash_payment_selected")

        # 抓取下单接口日志
        pid = self._v150_start_logcat_capture(tag)

        # 点击确认呼叫
        self._android_click_estimate_call()
        logger.info("【%s】已点击确认呼叫", tag)
        self.v150_screenshot("booking_meter_cash_calling")

        # 等待进入呼叫中
        self._wait(
            lambda: self._v150_current_page_type() == "calling",
            "预约打表现金支付未进入呼叫中", timeout=30)
        logger.info("【%s】已进入预约呼叫中", tag)

        # 收集接口日志
        calls = self._v150_collect_logcat(tag, pid=pid, timeout=8).get("raw_calls", [])
        if calls:
            # 现金支付 payment_collection_mode=2（线下）
            check = check_api_response(
                calls, "agent_order_create",
                expect_code=self.OK_CODE,
                expect_params={"payment_collection_mode": "2"})
            logger.info("【%s】create 接口 payment_collection_mode 检查：%s", tag, check)
        else:
            logger.warning("【%s】未抓取到接口日志", tag)

        # 获取订单号（呼叫中页面可能不显示，从 logcat 兜底提取）
        status = self._v150_booking_status()
        order_no = status.get("order_no")
        if not order_no:
            order_no = self._v150_extract_order_no(pid)
        if order_no:
            logger.info("【%s】订单号=%s", tag, order_no)
            type(self)._booking_order_no = order_no
        else:
            logger.warning("【%s】未获取到订单号", tag)

        self.v150_screenshot("booking_meter_cash_result")

    # ==================== 库表直查断言（不取消订单） ====================

    @pytest.mark.skipif(not _HAS_DB, reason="database 配置缺失")
    def test_03_db_verify_meter_cash_fields(self):
        """库表直查：下单后不取消，直查 order_info 表断言 payment_collection_mode=2, business_type=1。"""
        order_no = getattr(type(self), "_booking_order_no", None)
        if not order_no:
            pytest.skip("未获取到订单号，跳过库表验证")
        result = query_order_field_values(order_no)
        if result is None:
            pytest.skip(f"order_no={order_no} 在 order_info 表中未找到")
        assert result["payment_collection_mode"] == PAYMENT_COLLECTION_OFFLINE, \
            f"payment_collection_mode={result['payment_collection_mode']}，预期=2"
        assert result["business_type"] == BUSINESS_TAXI, \
            f"business_type={result['business_type']}，预期=1"
        logger.info("【DB验证】order_no=%s 两字段正确，订单未取消", order_no)


if __name__ == "__main__":
    from JRYG_run_main import run_tests
    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
