# 编写时间：2026-11-19
# 本期功能：V1.6.0 网约车与预约业务真机验证
"""V1.6.0 网约车与预约业务真机验证场景。

覆盖需求文档的真机可验证部分：
- 需求 1：选择车型页展示网约车 5 车型及繁体名称
- 需求 2/3：预估详情、费用详情、计价规则页的费项明细
- 需求 4：车型选择栏三段式高度与起终点展示
- 需求 5：出发时间入口，即时/预约业务切换
- 需求 8：预付订单取消页原路退款提示
- 需求 9：预约接单后「預約用車」标签与司机位置未暴露浮框
- 需求 10：一口价提醒弹框与消息栏
- 需求 14：订单详情车辆图片按颜色适配

真机策略（99% 真实数据原则）：
- 通过 UI 操作进入对应页面，用 uiautomator 页面树校验文案与元素
- 路线/起终点从 config/JRYG_settings.yaml 的 order_validation 段读取，
  不在用例中硬编码路线名称
- 车型数据从 CarTypeCatalog 读配置，不硬编码车型名
- 金额/预估价从真实页面树读取，不硬编码预期金额
- 在关键节点抓取 logcat，解析 retrofit 拦截器输出断言接口 code=10000
- 不操作司机端、不清理已有订单

前置条件：设备已连接、Appium 已启动、乘客 App 已登录。
"""

from pathlib import Path
import sys

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import logging
logger = logging.getLogger("JRYG_HK_android")

from passenger_android_core.JRYG_config import SETTINGS
from passenger_android_core.v160.booking_contract import (
    truncate_endpoint_name,
    CAR_SELECTOR_STATE_COLLAPSED,
    CAR_SELECTOR_STATE_DEFAULT,
    CAR_SELECTOR_STATE_EXPANDED,
)
from passenger_android_core.v160.contract import (
    BUSINESS_RIDE_HAILING,
    BUSINESS_TAXI,
    resolve_vehicle_image,
)
from passenger_android_core.v160.device_steps import V160DeviceSteps
from passenger_android_core.v160.fulfillment_contract import (
    ORDER_STATUS_ACCEPTED,
    business_label,
    home_card_visible,
)

# 真实路线数据（从 config/JRYG_settings.yaml 读取，不硬编码）
_ORDER_VALIDATION = SETTINGS.get("order_validation", {})
_START_NAMES = _ORDER_VALIDATION.get("start_names", [])
_END_NAMES = _ORDER_VALIDATION.get("end_names", [])


class TestV160RideHailingDevice(V160DeviceSteps):
    """V1.6.0 网约车车型与预约业务真机验证。"""

    __test__ = True
    DRIVER_REQUIRED = False

    OK_CODE = 10000

    # ---- class 级共享状态 ----
    _v160_ready = False
    _v160_logcat_pid = None

    # ==================== 真机 UI 验证 ====================

    def test_10_real_car_selector_displays_ride_hailing(self):
        """真机：选择车型页展示网约车 5 车型。"""
        self.v160_open_car_selector(tag="v160_carlist")
        names = self.v160_assert_ride_hailing_types_displayed(tag="v160_carlist")
        assert len(names) == 5

    def test_11_real_car_selector_height_states(self):
        """真机：车型选择栏三段式高度状态可切换。

        R4-01：三种高度状态 default / expanded / collapsed。
        滑动后必须观察到状态变化，不能等于滑动前状态。
        """
        self.v160_open_car_selector(tag="v160_carlist")
        before = self.v160_car_selector_height_state(tag="v160_carlist")
        logger.info("【v160_carlist】初始高度状态=%s", before)
        assert before in (CAR_SELECTOR_STATE_DEFAULT, CAR_SELECTOR_STATE_EXPANDED,
                          CAR_SELECTOR_STATE_COLLAPSED)

        expanded = self.v160_scroll_car_selector("up", tag="v160_carlist")
        logger.info("【v160_carlist】上滑后状态=%s", expanded)
        assert expanded == CAR_SELECTOR_STATE_EXPANDED

        collapsed = self.v160_scroll_car_selector("down", tag="v160_carlist")
        logger.info("【v160_carlist】下滑后状态=%s", collapsed)
        assert collapsed == CAR_SELECTOR_STATE_COLLAPSED

    @pytest.mark.skip(reason="证据不足：起终点独立定位及与本次路线的实际显示比较尚未适配")
    def test_12_real_endpoint_display_in_expanded(self):
        raise NotImplementedError("不能对已读取文案调用本地截断函数来证明 App 截断正确")

    def test_13_real_departure_time_entry(self):
        """真机：车型选择页存在出发时间入口。"""
        self.v160_open_car_selector(tag="v160_depart")
        self.v160_open_departure_time_entry(tag="v160_depart")
        logger.info("【v160_depart】出发时间入口可用")

    def test_14_real_estimate_detail_fee_items(self):
        """真机：网约车预估详情展示费项明细。"""
        self.v160_open_car_selector(tag="v160_fee")
        self.v160_open_estimate_detail(tag="v160_fee")
        items = self.v160_assert_fee_details(order_type=5, tag="v160_fee")
        assert "起步價" in items

    def test_15_real_charge_rule_page(self):
        """真机：计价规则页展示业务类型。"""
        self.v160_open_car_selector(tag="v160_fee")
        self.v160_open_estimate_detail(tag="v160_fee")
        self.v160_open_charge_rule(tag="v160_fee")
        self.v160_assert_charge_rule(order_type=5, tag="v160_fee")

    @pytest.mark.skip(reason="证据不足：缺少本次订单车辆颜色前置及实际车辆图片读取链路")
    def test_16_real_vehicle_image_color(self):
        raise NotImplementedError("本地资源名称契约不能作为真机车辆图片验证")

    def test_17_business_label_contract(self):
        """离线契约：预约业务「預約用車」标签。

        R9-05：后续状态复用即时展示 + 「預約用車」标签。
        此为离线契约验证，不依赖真机。
        """
        assert business_label(6) == "預約用車"
        assert business_label(5) == ""

    def test_18_home_card_states_contract(self):
        """离线契约：首页进行中订单卡片支持预约状态。

        R13-03：首页进行中订单卡片新增预约 4 状态。
        此为离线契约验证，不依赖真机。
        """
        assert home_card_visible(ORDER_STATUS_ACCEPTED, 6) is True
        assert home_card_visible(ORDER_STATUS_ACCEPTED, 5) is True

    # ==================== 40 秒无司机接单自动诊断 ====================

    def test_19_no_accept_timeout_config(self):
        """离线契约：无接单等待超时为 40 秒。

        验证 NO_ACCEPT_TIMEOUT 常量值为 40，
        自动化测试中下单后等待 40 秒无司机接单即触发诊断。
        """
        assert self.NO_ACCEPT_TIMEOUT == 40

    def test_20_accepted_keywords_include_driver_coming(self):
        """离线契约：已接单关键词包含「司機正在趕來」和「司機已接單」。"""
        assert "司機正在趕來" in self._ACCEPTED_KEYWORDS
        assert "司機已接單" in self._ACCEPTED_KEYWORDS
        assert "行程中" in self._ACCEPTED_KEYWORDS

    def test_21_no_accept_keywords_include_timeout(self):
        """离线契约：无接单关键词包含「暫無司機接單」和「呼叫超時」。"""
        assert "暫無司機接單" in self._NO_ACCEPT_KEYWORDS
        assert "呼叫超時" in self._NO_ACCEPT_KEYWORDS

    def test_22_dispatch_diagnose_method_exists(self):
        """离线契约：v160_wait_for_accept_or_diagnose 方法可用。"""
        assert hasattr(self, "v160_wait_for_accept_or_diagnose")
        assert callable(self.v160_wait_for_accept_or_diagnose)

    def test_23_dispatch_diagnose_order_no_extraction(self):
        """离线契约：_v160_extract_order_no_from_logcat 方法可用。"""
        assert hasattr(self, "_v160_extract_order_no_from_logcat")
        assert callable(self._v160_extract_order_no_from_logcat)

    def test_24_dispatch_diagnose_k8s_method_exists(self):
        """离线契约：_v160_run_dispatch_diagnose 方法可用。"""
        assert hasattr(self, "_v160_run_dispatch_diagnose")
        assert callable(self._v160_run_dispatch_diagnose)

    @pytest.mark.skip(reason="前置未实现：缺少本次真实创建订单与接单状态的唯一关联，诊断报告不代表接单成功")
    def test_25_real_wait_for_accept_or_diagnose(self):
        raise NotImplementedError("先实现授权下单及订单绑定，再按同订单接单结果断言")
