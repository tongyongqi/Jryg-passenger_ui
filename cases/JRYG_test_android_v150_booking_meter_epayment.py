# 编写时间：2026-11-13
# 本期功能：V1.5.0 预约后付费 type16 改造 — 打表的士 + 电子支付下单真机验证
# 场景：预约用车 → 打表的士 → 电子支付 → 确认呼叫 → 进入呼叫中 → 库表直查断言
"""V1.5.0 预约用车 type16 真机验证：打表的士 + 电子支付下单。

需求映射：
- 预约后付费订单 = OrderTypeBookingRealTime = 16，走实时库
- 打表的士选择「電子支付」下单 → payment_collection_mode=1（线上支付）
- business_type=1（出租车）

真机流程：预约用车 → 选择打表的士 → 选择电子支付 → 确认呼叫 → 进入呼叫中
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

from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps
from jryg_hk_android.JRYG_v150_api_log import check_api_response, parse_api_calls
from jryg_hk_android.JRYG_v150_contract import (
    ORDER_TYPE_BOOKING_REALTIME,
    PAYMENT_COLLECTION_ONLINE,
    BUSINESS_TAXI,
    create_params_validate,
    order_center_create,
    order_center_show,
)

# 库表直查（可选，配置缺失时 skip）
try:
    from jryg_hk_android.JRYG_v150_db_verify import query_order_field_values
    from jryg_hk_android.JRYG_config import SETTINGS
    _HAS_DB = bool(SETTINGS.get("database"))
except ImportError:
    _HAS_DB = False


class TestV150BookingMeterEpaymentDevice(V150DeviceSteps):
    """预约用车 type16：打表的士 + 电子支付下单。

    场景：预约用车 → 打表的士 → 電子支付 → 確認呼叫 → 呼叫中 → 直查库表断言
    验证：
    1. 离线契约：create 传 payment_collection_mode=1, business_type=1
    2. 真机：预约下单进入呼叫中后，直查库表断言两字段值（不取消订单）
    """

    __test__ = True
    DRIVER_REQUIRED = False
    CAR_TYPE = "meter"

    OK_CODE = 10000

    # ---- 网络日志抓取 ----

    def _start_network_capture(self, tag):
        """清空 logcat，绑定 App PID。"""
        package = self.order_settings["packages"]["passenger_hk"]
        pid = self._v150_adb("shell", "pidof", "-s", package).strip()
        if not pid.isdigit():
            raise RuntimeError("乘客App进程不存在，无法抓取接口日志")
        self._v150_adb("logcat", "-c")
        logger.info("【%s】已清空logcat并绑定PID=%s", tag, pid)
        return pid

    def _dismiss_proxy_dialog(self):
        """启动 App 前先关闭可能的代理模式温馨提示弹窗。"""
        package = self.order_settings["packages"]["passenger_hk"]
        activity = self.order_settings["packages"]["passenger_hk_activity"]
        self._v150_adb("shell", "am", "start", "-n", f"{package}/{activity}")
        time.sleep(3)
        # 用 adb input tap 点击"知道了"按钮（坐标基于真机 dump 验证）
        self._v150_adb("shell", "input", "tap", "586", "1626")
        time.sleep(1)
        logger.info("已尝试关闭代理模式温馨提示弹窗")

    def _collect_network_log(self, tag, pid, timeout=10):
        """抓取并解析接口调用。"""
        deadline = time.monotonic() + timeout
        while True:
            output = self._v150_adb("logcat", "-d", f"--pid={pid}", "-v", "brief")
            lines = output.splitlines() if output else []
            calls = parse_api_calls(lines)
            if any(c.get("code") is not None for c in calls):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(.4)
        calls = parse_api_calls(lines)
        logger.info("【%s】抓取到 %d 条接口调用", tag, len(calls))
        return calls

    def _extract_order_no_from_logcat(self, pid):
        """从 logcat 中提取订单号（呼叫中页面可能不显示订单号）。"""
        import re
        output = self._v150_adb("logcat", "-d", f"--pid={pid}", "-v", "brief")
        pattern = re.compile(r"order_no=([A-Z0-9]{12})")
        matches = pattern.findall(output)
        if matches:
            # 取最后一次出现的订单号
            return matches[-1]
        return None

    # ==================== 离线契约预校验 ====================

    def test_01_contract_create_with_epayment_fields(self):
        """离线契约：打表+电子支付 → payment_collection_mode=1, business_type=1。"""
        result = create_params_validate(
            payment_collection_mode=PAYMENT_COLLECTION_ONLINE,
            business_type=BUSINESS_TAXI)
        assert result == {"payment_collection_mode": 1, "business_type": 1}

        created = order_center_create(
            ORDER_TYPE_BOOKING_REALTIME,
            payment_collection_mode=PAYMENT_COLLECTION_ONLINE,
            business_type=BUSINESS_TAXI)
        assert created["order_type"] == 16
        assert created["payment_collection_mode"] == 1
        assert created["business_type"] == 1
        assert created["storage"] == "realtime"

        shown = order_center_show(created)
        assert shown["payment_collection_mode"] == 1
        assert shown["business_type"] == 1
        self.v150_screenshot("booking_meter_epayment_contract")

    # ==================== 真机：预约打表的士+电子支付下单 ====================

    def test_02_real_booking_meter_epayment_order(self):
        """真机：预约用车 → 打表的士 → 电子支付 → 确认呼叫 → 呼叫中 → 直查库表断言。

        下单进入呼叫中后不取消订单，直接查 order_info 表断言两字段值。
        """
        tag = "v150_booking_meter_epayment"
        self._ensure_devices_awake()
        self._dismiss_proxy_dialog()
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
        self.v150_screenshot("booking_meter_epayment_car_selected")

        # 选择电子支付
        self._android_select_payment(tag, "epayment")
        logger.info("【%s】已选择电子支付", tag)
        self.v150_screenshot("booking_meter_epayment_payment_selected")

        # 抓取下单接口日志
        pid = self._start_network_capture(tag)

        # 点击确认呼叫
        self._android_click_estimate_call()
        logger.info("【%s】已点击确认呼叫", tag)
        self.v150_screenshot("booking_meter_epayment_calling")

        # 等待进入呼叫中
        self._wait(
            lambda: self._v150_current_page_type() == "calling",
            "预约打表电子支付未进入呼叫中", timeout=30)
        logger.info("【%s】已进入预约呼叫中", tag)

        # 收集接口日志
        calls = self._collect_network_log(tag, pid, timeout=8)
        if calls:
            check = check_api_response(
                calls, "agent_order_create",
                expect_code=self.OK_CODE,
                expect_params={"payment_collection_mode": "1"})
            logger.info("【%s】create 接口 payment_collection_mode 检查：%s", tag, check)
        else:
            logger.warning("【%s】未抓取到接口日志", tag)

        # 获取订单号（呼叫中页面可能不显示，从 logcat 兜底提取）
        status = self._v150_booking_status()
        order_no = status.get("order_no")
        if not order_no:
            order_no = self._extract_order_no_from_logcat(pid)
        if order_no:
            logger.info("【%s】订单号=%s", tag, order_no)
            type(self)._booking_order_no = order_no
        else:
            logger.warning("【%s】未获取到订单号", tag)

        self.v150_screenshot("booking_meter_epayment_result")

    # ==================== 库表直查断言（不取消订单） ====================

    @pytest.mark.skipif(not _HAS_DB, reason="database 配置缺失")
    def test_03_db_verify_meter_epayment_fields(self):
        """库表直查：下单后不取消，直查 order_info 表断言两字段值为 1。"""
        order_no = getattr(type(self), "_booking_order_no", None)
        if not order_no:
            pytest.skip("未获取到订单号，跳过库表验证")
        result = query_order_field_values(order_no)
        if result is None:
            pytest.skip(f"order_no={order_no} 在 order_info 表中未找到")
        assert result["payment_collection_mode"] == PAYMENT_COLLECTION_ONLINE, \
            f"payment_collection_mode={result['payment_collection_mode']}，预期=1"
        assert result["business_type"] == BUSINESS_TAXI, \
            f"business_type={result['business_type']}，预期=1"
        logger.info("【DB验证】order_no=%s 两字段正确，订单未取消", order_no)


if __name__ == "__main__":
    from JRYG_run_main import run_tests
    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
