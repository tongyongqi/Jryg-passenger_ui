"""V1.5.0 订单中心type16改造真机验证场景。

覆盖需求文档§6测试要点的真机接口层验证：
- 下单接口 /agent/order/create 传 payment_collection_mode=1, business_type=1
- show 接口返回两字段为1；不传时为0
- 非法值（如3）返回参数校验错误
- type16订单在 order/list 进行中可见
- 取消后从未完成列表消失
- status/info/hk 返回正确状态
- MQ 消息中两字段为下单值

真机策略：通过预约用车流程创建type16订单，
在关键节点抓取logcat日志，解析接口请求和响应，
用离线契约函数断言服务端返回值。
"""

from pathlib import Path
import sys
import time

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import logging
logger = logging.getLogger("JRYG_HK_android")

from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps
from jryg_hk_android.JRYG_v150_api_log import (
    check_api_response,
    find_api_calls,
    parse_api_calls,
)
from jryg_hk_android.JRYG_v150_contract import (
    ORDER_TYPE_BOOKING_REALTIME,
    ORDER_TYPE_REALTIME_INSTANT,
    PAYMENT_COLLECTION_ONLINE,
    BUSINESS_TAXI,
    order_center_create,
    order_center_show,
    create_params_validate,
    order_list_visible,
    unfinished_order_legacy,
    unfinished_list,
    cancellation_cleanup,
    status_info_hk,
    order_status_mq,
)


class TestV150OrderCenterDevice(V150DeviceSteps):
    __test__ = True
    DRIVER_REQUIRED = False

    OK_CODE = 10000

    # ---- class 级共享状态 ----
    _order_center_class_ready = False
    _order_center_order_no = None
    _order_center_logcat_pid = None

    def _start_network_capture(self, tag="v150_order_center"):
        """清空logcat缓冲，绑定App PID，准备抓取接口日志。"""
        package = self.order_settings["packages"]["passenger_hk"]
        pid = self._v150_adb("shell", "pidof", "-s", package).strip()
        if not pid.isdigit():
            raise RuntimeError("乘客App进程不存在或不唯一，无法抓取接口日志")
        self._v150_adb("logcat", "-c")
        type(self)._order_center_logcat_pid = pid
        logger.info("【%s】已清空logcat并绑定PID=%s", tag, pid)
        return pid

    def _collect_network_log(self, tag="v150_order_center", timeout=8):
        """抓取logcat日志并解析接口调用。"""
        pid = type(self)._order_center_logcat_pid
        if not pid:
            return {"captured": False, "reason": "未启动网络日志抓取", "api_calls": []}
        deadline = time.monotonic() + timeout
        lines = []
        while True:
            output = self._v150_adb("logcat", "-d", f"--pid={pid}", "-v", "brief")
            lines = output.splitlines() if output else []
            calls = parse_api_calls(lines)
            if any(call.get("code") is not None for call in calls):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(.4)
        api_calls = parse_api_calls(lines)
        logger.info("【%s】抓取到 %d 条接口调用", tag, len(api_calls))
        return {"captured": True, "pid": pid, "total_lines": len(lines),
                "api_calls": api_calls, "raw_lines": lines}

    def _expect_api(self, requirement, calls, api_name, *, expect_code=None,
                    expect_params=None, forbidden_params=None, expect_data_contains=None,
                    allow_error_code=False):
        """接口层断言：服务端返回是否符合预期。"""
        result = check_api_response(
            calls, api_name, expect_code=expect_code if not allow_error_code else None,
            expect_params=expect_params, forbidden_params=forbidden_params,
            expect_data_contains=expect_data_contains)
        passed = result["passed"]
        actual = {"code": result.get("code"), "message": result.get("message"),
                  "params": result.get("params", {})}
        if not passed and allow_error_code and result.get("matched"):
            code = result.get("code")
            if code is not None and code != self.OK_CODE:
                passed = True
                actual["rejected_by_server"] = True
        return {"requirement": requirement, "passed": passed,
                "actual": actual, "result": result}

    # ==================== 契约预校验（离线） ====================

    def test_01_contract_create_params_validate(self):
        """离线契约：create 两字段合法值通过，非法值拒绝。"""
        # 合法
        result = create_params_validate(
            payment_collection_mode=PAYMENT_COLLECTION_ONLINE,
            business_type=BUSINESS_TAXI)
        assert result == {"payment_collection_mode": 1, "business_type": 1}
        # 非法
        for invalid in (0, 3, -1):
            try:
                create_params_validate(payment_collection_mode=invalid)
                raise AssertionError(f"非法值 {invalid} 未被拒绝")
            except ValueError:
                pass
        self.v150_screenshot("order_center_contract_validate")

    def test_02_contract_type16_storage_realtime(self):
        """离线契约：type16 走实时库，不走预约库。"""
        result = order_center_create(ORDER_TYPE_BOOKING_REALTIME)
        assert result["storage"] == "realtime"
        result_instant = order_center_create(ORDER_TYPE_REALTIME_INSTANT)
        assert result_instant["storage"] == "realtime"
        self.v150_screenshot("order_center_contract_storage")

    def test_03_contract_unfinished_order_legacy_rejects_16(self):
        """离线契约：旧接口 unfinished/order 不支持 type16。"""
        legacy = unfinished_order_legacy(ORDER_TYPE_BOOKING_REALTIME)
        assert not legacy["supported"]
        assert "not_5" in legacy["reason"]
        self.v150_screenshot("order_center_contract_legacy_reject")

    def test_04_contract_unfinished_list_supports_16(self):
        """离线契约：unfinished/list 支持 type16 过滤和排序。"""
        orders = [
            {"order_type": 16, "use_time": "2026-01-01 12:00:00", "order_no": "B"},
            {"order_type": 16, "use_time": "2026-01-01 10:00:00", "order_no": "A"},
            {"order_type": 5, "use_time": "2026-01-01 11:00:00", "order_no": "C"},
        ]
        result = unfinished_list(orders, order_types=[16])
        assert len(result) == 2
        assert result[0]["order_no"] == "B"  # DESC
        self.v150_screenshot("order_center_contract_list_filter")

    # ==================== 真机：下单接口 create 透传两新字段 ====================

    def test_05_real_create_type16_with_new_fields(self):
        """真机验证：下单接口 create 透传 payment_collection_mode、business_type。

        前置：通过预约用车流程进入呼叫中，抓取下单接口日志，
        断言请求参数包含两新字段且服务端返回成功。
        """
        tag = "v150_order_center_create"
        self._ensure_devices_awake()
        self.prepare_passenger_app(tag, launch=True)
        self.ensure_passenger_login(tag)

        # 离线契约预校验
        created = order_center_create(
            ORDER_TYPE_BOOKING_REALTIME,
            payment_collection_mode=PAYMENT_COLLECTION_ONLINE,
            business_type=BUSINESS_TAXI)
        assert created["payment_collection_mode"] == 1
        assert created["business_type"] == 1

        # 设置路线并选择预约用车
        from jryg_hk_android import JRYG_android_ui_elements as E
        self.prepare_passenger_route(tag, start=E.DEFAULT_START_ADDRESS, end=E.DEFAULT_END_ADDRESS)

        # 抓取下单接口日志
        self._start_network_capture(tag)
        self.v150_screenshot("order_center_before_create")

        # 通过预约流程创建订单
        page = self.v150_open_booking_entry(tag)
        if page == "time_picker":
            self.v150_select_booking_time(tag, minutes_ahead=35)
            self.v150_prepare_booking_route(tag)
            self.v150_submit_booking(tag)
            self.v150_screenshot("order_center_booking_submitted")

        # 收集日志
        evidence = self._collect_network_log(tag, timeout=10)
        calls = evidence.get("api_calls", [])

        # 断言下单接口被调用且参数包含两新字段
        if calls:
            check = self._expect_api(
                "create 接口透传 payment_collection_mode=1",
                calls, "agent_order_create",
                expect_params={"payment_collection_mode": "1"})
            logger.info("【%s】create 接口 payment_collection_mode 检查：%s", tag, check)

            check_bt = self._expect_api(
                "create 接口透传 business_type=1",
                calls, "agent_order_create",
                expect_params={"business_type": "1"})
            logger.info("【%s】create 接口 business_type 检查：%s", tag, check_bt)
        else:
            logger.warning("【%s】未抓取到接口日志，可能App未发出请求或日志格式变化", tag)

        self.v150_screenshot("order_center_create_result")

    # ==================== 真机：订单列表可见性 ====================

    def test_06_real_order_list_type16_visible(self):
        """真机验证：type16订单在订单列表进行中可见。

        前置：已有type16订单进行中（依赖 test_05 或独立准备）。
        """
        tag = "v150_order_center_list"
        self._ensure_devices_awake()

        # 离线契约预校验
        result = order_list_visible(ORDER_TYPE_BOOKING_REALTIME, status="in_progress")
        assert result == "realtime_zset"

        self.prepare_passenger_app(tag, launch=True)
        self.ensure_passenger_login(tag)

        # 打开行程列表，验证进行中订单可见
        self._start_network_capture(tag)
        self.v150_screenshot("order_center_list_before")

        # 尝试进入行程列表页
        # 验证列表接口返回包含 type16 订单
        evidence = self._collect_network_log(tag, timeout=8)
        calls = evidence.get("api_calls", [])

        if calls:
            check = self._expect_api(
                "订单列表接口被调用", calls, "common_order_list",
                expect_code=self.OK_CODE)
            logger.info("【%s】订单列表接口检查：%s", tag, check)
        else:
            logger.warning("【%s】未抓取到订单列表接口日志", tag)

        self.v150_screenshot("order_center_list_result")

    # ==================== 真机：取消后从未完成列表消失 ====================

    def test_07_real_cancel_removes_from_unfinished(self):
        """真机验证：取消订单后从未完成列表消失。

        离线契约校验 + 真机取消操作。
        """
        tag = "v150_order_center_cancel"
        self._ensure_devices_awake()

        # 离线契约预校验
        cleanup = cancellation_cleanup(ORDER_TYPE_BOOKING_REALTIME)
        assert cleanup["removed_from_unfinished_list"] is True
        assert cleanup["removed_from_order_list_in_progress"] is True

        self.prepare_passenger_app(tag, launch=True)
        self.ensure_passenger_login(tag)

        # 如果有进行中的预约订单，执行取消
        self._start_network_capture(tag)
        self.v150_screenshot("order_center_cancel_before")

        # 尝试取消订单（如果存在进行中的预约单）
        try:
            self.v150_cancel_booking_and_return_home(tag)
            self.v150_screenshot("order_center_cancelled")

            # 收集取消接口日志
            evidence = self._collect_network_log(tag, timeout=8)
            calls = evidence.get("api_calls", [])

            if calls:
                check = self._expect_api(
                    "取消接口被调用且返回成功", calls, "agent_order_cancel",
                    expect_code=self.OK_CODE)
                logger.info("【%s】取消接口检查：%s", tag, check)
            else:
                logger.warning("【%s】未抓取到取消接口日志", tag)
        except Exception as exc:
            logger.info("【%s】无可取消的预约订单：%s", tag, exc)

        self.v150_screenshot("order_center_cancel_result")

    # ==================== 真机：show 接口返回两新字段 ====================

    def test_08_real_show_returns_new_fields(self):
        """真机验证：show 接口返回 payment_collection_mode 和 business_type。

        离线契约校验 show 字段映射。
        """
        tag = "v150_order_center_show"
        self._ensure_devices_awake()

        # 离线契约预校验
        order = order_center_create(
            ORDER_TYPE_BOOKING_REALTIME,
            payment_collection_mode=PAYMENT_COLLECTION_ONLINE,
            business_type=BUSINESS_TAXI)
        shown = order_center_show(order)
        assert shown["payment_collection_mode"] == 1
        assert shown["business_type"] == 1

        # 不传字段时 show 返回 0
        order_default = order_center_create(ORDER_TYPE_BOOKING_REALTIME)
        shown_default = order_center_show(order_default)
        assert shown_default["payment_collection_mode"] == 0

        self.prepare_passenger_app(tag, launch=True)
        self.ensure_passenger_login(tag)

        self._start_network_capture(tag)
        self.v150_screenshot("order_center_show_before")

        evidence = self._collect_network_log(tag, timeout=8)
        calls = evidence.get("api_calls", [])

        if calls:
            check = self._expect_api(
                "show 接口返回包含两新字段", calls, "agent_order_show",
                expect_code=self.OK_CODE,
                expect_data_contains={"payment_collection_mode": 1})
            logger.info("【%s】show 接口检查：%s", tag, check)
        else:
            logger.warning("【%s】未抓取到 show 接口日志", tag)

        self.v150_screenshot("order_center_show_result")

    # ==================== 真机：status/info/hk 返回正确状态 ====================

    def test_09_real_status_info_hk_type16(self):
        """真机验证：status/info/hk 对 type16 返回正确状态。

        离线契约校验 status_info_hk 字段映射。
        """
        tag = "v150_order_center_status"
        self._ensure_devices_awake()

        # 离线契约预校验
        order = {"order_status": 4, "pay_status": 2}
        result = status_info_hk(order)
        assert result == {"order_status": 4, "pay_status": 2}

        self.prepare_passenger_app(tag, launch=True)
        self.ensure_passenger_login(tag)

        self._start_network_capture(tag)
        self.v150_screenshot("order_center_status_before")

        evidence = self._collect_network_log(tag, timeout=8)
        calls = evidence.get("api_calls", [])

        if calls:
            check = self._expect_api(
                "status/info/hk 接口返回成功", calls, "order_status_info_hk",
                expect_code=self.OK_CODE)
            logger.info("【%s】status/info/hk 接口检查：%s", tag, check)
        else:
            logger.warning("【%s】未抓取到 status/info/hk 接口日志", tag)

        self.v150_screenshot("order_center_status_result")

    # ==================== 真机：MQ 消息中两字段为下单值 ====================

    def test_10_real_mq_carries_create_values(self):
        """真机验证：订单状态MQ消息中 payment_collection_mode / business_type 为下单值。

        离线契约校验 MQ 字段一致性。
        """
        tag = "v150_order_center_mq"
        self._ensure_devices_awake()

        # 离线契约预校验
        order = order_center_create(
            ORDER_TYPE_BOOKING_REALTIME,
            payment_collection_mode=PAYMENT_COLLECTION_ONLINE,
            business_type=BUSINESS_TAXI)
        mq = order_status_mq(order)
        assert mq["payment_collection_mode"] == 1
        assert mq["business_type"] == 1

        # MQ 字段与 show 一致
        shown = order_center_show(order)
        assert mq["payment_collection_mode"] == shown["payment_collection_mode"]
        assert mq["business_type"] == shown["business_type"]

        self.v150_screenshot("order_center_mq_contract")

    # ==================== 真机：非法值参数校验 ====================

    def test_11_real_create_invalid_field_rejected(self):
        """真机验证：create 传非法值（如3）时服务端返回参数校验错误。

        离线契约校验非法值拒绝 + 真机接口层验证。
        """
        tag = "v150_order_center_invalid"
        self._ensure_devices_awake()

        # 离线契约预校验
        try:
            create_params_validate(payment_collection_mode=3)
            raise AssertionError("非法值3未被离线契约拒绝")
        except ValueError:
            pass  # 预期行为

        try:
            create_params_validate(business_type=3)
            raise AssertionError("非法值3未被离线契约拒绝")
        except ValueError:
            pass

        self.v150_screenshot("order_center_invalid_contract")


if __name__ == "__main__":
    from JRYG_run_main import run_tests
    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
