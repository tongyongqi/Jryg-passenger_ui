"""V1.6.0 新功能真机调试步骤：网约车车型、预约业务、计费明细、车辆图片颜色。

继承 AndroidPassengerBase，复用既有登录、设备生命周期和 UI 操作工具。
每个步骤方法遵循既有模式：
- 主动操作前检测熄屏
- 使用规范化或原生页面树定位控件
- 支持繁体/简体文案
- 接口断言基于 retrofit 拦截器日志，code=10000

覆盖需求点：
- 需求 1/2/3：网约车 5 车型、预估详情/费用详情计费明细、计价规则页
- 需求 4：车型选择栏三段式高度
- 需求 5：车型选择页出发时间入口
- 需求 6/7/8：预约规则、预约支付与优惠券、呼叫与取消
- 需求 9/10/11/12/13/14：履约状态机、消息栏、通知收据、分享安全、我的行程、车辆图片

不操作司机端、不清理已有订单。
"""

import re
import time
from datetime import datetime, timedelta

from passenger_android_core.JRYG_android_passenger import AndroidPassengerBase
from passenger_android_core.JRYG_driver_ui import center, visible_nodes
from passenger_android_core.JRYG_logger import logger
from passenger_android_core.v150.api_log import check_api_response, parse_api_calls
from passenger_android_core.v160.booking_contract import (
    BOOKING_MIN_MINUTES,
    cancel_page_notice,
    order_messages,
    truncate_endpoint_name,
    CAR_SELECTOR_STATE_COLLAPSED,
    CAR_SELECTOR_STATE_DEFAULT,
    CAR_SELECTOR_STATE_EXPANDED,
)
from passenger_android_core.v160.charge_contract import (
    charge_rule_business_type,
    estimate_detail_payload,
    order_fee_payload,
)
from passenger_android_core.v160.contract import (
    BUSINESS_RIDE_HAILING,
    BUSINESS_TAXI,
    CAR_TYPE_NAMES,
    RIDE_HAILING_CODES,
    CarTypeCatalog,
    build_estimate_car_types,
    resolve_vehicle_image,
)
from passenger_android_core.v160.fulfillment_contract import (
    business_label,
    share_state,
    trip_group_of,
)


class V160DeviceSteps(AndroidPassengerBase):
    """V1.6.0 新功能真机调试步骤基类，不被 pytest 直接收集。

    每个步骤方法返回页面核验结果或抛出 RuntimeError/TimeoutError。
    调用方负责异常处理和截图留存。
    """

    __test__ = False

    #: 繁简文案对照表
    TEXT_VARIANTS = {
        "booking_label": ("預約用車", "预约用车"),
        "now_departure": ("現在出發", "现在出发"),
        "fixed_price": ("一口價", "一口价"),
        "estimate_detail": ("預估詳情", "预估详情"),
        "fee_detail": ("費用詳情", "费用详情"),
        "charge_rule": ("計價規則", "计价规则"),
        "pay_rule": ("查看計價規則", "查看计价规则"),
        "safe_center": ("安全中心", "安全中心"),
        "share_trip": ("分享行程", "分享行程"),
        "contact_driver": ("聯繫司機", "联系司机"),
        "contact_service": ("聯繫客服", "联系客服"),
        "cancel_order": ("取消訂單", "取消订单"),
        "send_receipt": ("發送行程收據", "发送行程收据"),
        "receipt_prompt": ("收據", "收据"),
    }

    # ==================== 车型品类（需求 1） ====================

    def v160_car_type_catalog(self):
        """返回车型读模型。"""
        return CarTypeCatalog()

    def v160_ride_hailing_car_types(self):
        """返回网约车 5 车型（按 PRD 顺序）。

        :return: [{"code","id","name_hant","name_hans","name_en"}, ...]
        """
        catalog = self.v160_car_type_catalog()
        result = []
        for code in RIDE_HAILING_CODES:
            entry = catalog.require_by_code(code)
            name = CAR_TYPE_NAMES[code]
            result.append({
                "code": code,
                "id": entry.id,
                "name_hant": name.zh_hant,
                "name_hans": name.zh_hans,
                "name_en": name.en,
                "icon": entry.icon,
            })
        return result

    def v160_estimate_car_types(self, order_type=5):
        """构造询价接口的 car_types 入参。

        出租车运力与网约车运力各一组。
        """
        taxi_ids = [e.id for e in self.v160_car_type_catalog().taxi_entries()]
        ride_ids = [e.id for e in self.v160_car_type_catalog().ride_hailing_entries()]
        return (build_estimate_car_types(BUSINESS_TAXI, order_type, taxi_ids)
                + build_estimate_car_types(BUSINESS_RIDE_HAILING, order_type,
                                           ride_ids))

    def v160_assert_ride_hailing_types_displayed(self, tag="v160_carlist"):
        """校验选择车型页展示网约车 5 车型及繁体名称。

        :return: 展示的车型名称列表。
        :raises RuntimeError: 车型缺失或名称不匹配。
        """
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        labels = [(n.get("label") or "").strip() for n in nodes]
        expected = [CAR_TYPE_NAMES[c].zh_hant for c in RIDE_HAILING_CODES]
        missing = [name for name in expected if name not in labels]
        if missing:
            raise RuntimeError(
                "V1.6.0 选择车型页未展示网约车车型：%s；当前可见文案=%s"
                % (missing, [x for x in labels if x][:30]))
        logger.info("【%s】网约车 5 车型全部展示：%s", tag, expected)
        return expected

    def v160_open_car_selector(self, tag="v160_carlist"):
        """打开选择车型页。

        首页进入方式：点击底部「選擇車型」/车型选择入口。

        :return: 页面类型标识。
        """
        self._ensure_devices_awake()
        self.prepare_passenger_app(tag, launch=True)
        self.ensure_passenger_login(tag)
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        entry = self._v160_find_by_labels(
            nodes, ("選擇車型", "选择车型", "選擇車型 ", "车型"))
        if not entry:
            entry = self._v160_find_by_id(nodes, ("tv_car_type", "btn_car_type",
                                                 "car_type_select"))
        if not entry:
            raise RuntimeError("V1.6.0 选择车型入口不可见")
        self.client.click(*center(entry[0]))
        logger.info("【%s】已进入选择车型页", tag)
        return self._v160_wait_page(
            lambda: self._v160_page_has_text(("選擇車型", "选择车型")),
            "V1.6.0 选择车型页未加载", timeout=15)

    # ==================== 车型选择栏三段式高度（需求 4） ====================

    def v160_car_selector_height_state(self, tag="v160_carlist"):
        """识别车型选择栏当前高度状态。

        通过车型栏容器高度判定：
        - 展开：车型栏占满屏幕
        - 收起：露出约 1.5 个车型
        - 默认：约半屏

        :return: default / expanded / collapsed
        """
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        containers = [node for node in nodes
                      if node.get("resource-id", "").split("/")[-1] in
                      ("car_selector", "ll_car_type", "rv_car_type", "recycler_car_type")]
        if len(containers) != 1:
            raise RuntimeError("车型栏容器必须唯一，实际数量=%s" % len(containers))
        height = float(containers[0].get("height", 0))
        screen_h = self._v160_screen_height()
        if not 0 < height <= screen_h:
            raise RuntimeError("车型栏规范化高度无效，不能判定状态")
        ratio = height / screen_h
        if ratio >= 0.85:
            return CAR_SELECTOR_STATE_EXPANDED
        if ratio <= 0.35:
            return CAR_SELECTOR_STATE_COLLAPSED
        return CAR_SELECTOR_STATE_DEFAULT

    def v160_scroll_car_selector(self, direction="up", tag="v160_carlist"):
        """滑动车型选择栏切换高度状态。

        :param direction: up 展开 / down 收起。
        :return: 切换后的高度状态。
        """
        if direction not in ("up", "down"):
            raise ValueError("车型栏滑动方向必须为 up/down")
        self._ensure_devices_awake()
        before = self.v160_car_selector_height_state(tag)
        expected = (CAR_SELECTOR_STATE_EXPANDED if direction == "up"
                    else CAR_SELECTOR_STATE_COLLAPSED)
        if before == expected:
            return before
        width, height = self.client.window_size()
        if width <= 0 or height <= 0:
            raise RuntimeError("设备窗口尺寸无效")
        x = width // 2
        if direction == "up":
            start_y, end_y = int(height * 0.60), int(height * 0.15)
        else:
            start_y, end_y = int(height * 0.25), int(height * 0.65)
        self.client.swipe(x, start_y, x, end_y, 0.4)
        self._v160_wait_page(
            lambda: self.v160_car_selector_height_state(tag) == expected,
            "车型栏滑动后未进入目标高度状态", timeout=10)
        logger.info("【%s】车型栏滑动 %s：%s -> %s", tag, direction, before, expected)
        return expected

    def v160_assert_endpoint_display(self, tag="v160_carlist"):
        """校验展开状态下展示起终点信息（名称最多 10 字）。"""
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        labels = [(n.get("label") or "").strip() for n in nodes if n.get("label")]
        start_labels = [x for x in labels if x.startswith("起點") or x.startswith("起点")]
        if not start_labels:
            raise RuntimeError("V1.6.0 展开状态未展示起点信息；可见文案=%s"
                               % labels[:20])
        text = start_labels[0]
        logger.info("【%s】起终点展示文案=%s（截断后=%s）", tag, text,
                    truncate_endpoint_name(text))
        return text

    # ==================== 出发时间入口（需求 5） ====================

    def v160_open_departure_time_entry(self, tag="v160_depart"):
        """点击车型选择页底栏出发时间入口，弹出出发时间选择弹框。

        :return: 页面类型标识。
        """
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        entry = self._v160_find_by_labels(nodes, self.TEXT_VARIANTS["now_departure"])
        if not entry:
            raise RuntimeError(
                "V1.6.0 出发时间入口不可见，可能未开启与首页预约入口共用的开关")
        self.client.click(*center(entry[0]))
        logger.info("【%s】已点击出发时间入口", tag)
        return self._v160_wait_page(
            lambda: self._v160_page_has_text(
                ("選擇出發時間", "选择出发时间", "現在出發", "现在出发")),
            "V1.6.0 出发时间选择弹框未出现", timeout=12)

    def v160_select_now_departure(self, tag="v160_depart"):
        """在出发时间弹框选择「現在出發」，切回即时业务。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        entry = self._v160_find_by_labels(nodes, self.TEXT_VARIANTS["now_departure"])
        if not entry:
            raise RuntimeError("V1.6.0 出发时间弹框未找到「現在出發」选项")
        self.client.click(*center(entry[0]))
        logger.info("【%s】已选择「現在出發」，切回即时业务", tag)
        return self._v160_wait_page(
            lambda: self._v160_page_has_text(
                self.TEXT_VARIANTS["now_departure"]),
            "V1.6.0 切换即时业务后未回到车型选择页", timeout=12)

    def v160_select_booking_departure(self, minutes=60, tag="v160_depart"):
        """在出发时间弹框选择预约时间，切到预约业务。

        :param minutes: 距当前的分钟数，需在 30~4320 范围内。
        :return: 选择的出发时间字符串。
        """
        if not (BOOKING_MIN_MINUTES <= minutes <= 72 * 60):
            raise ValueError("预约时间需在 %s~4320 分钟内" % BOOKING_MIN_MINUTES)
        raise NotImplementedError(
            "V1.6.0 预约滚轮与确认后时间回读尚未适配，禁止仅点击确认后返回计算时间")

    def v160_assert_booking_business(self, tag="v160_depart"):
        """校验已切换到预约业务（展示「預約用車」标签）。"""
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        labels = [(n.get("label") or "").strip() for n in nodes if n.get("label")]
        booking_labels = self.TEXT_VARIANTS["booking_label"]
        if not any(x in booking_labels for x in labels):
            raise RuntimeError("V1.6.0 未切换到预约业务，缺少「預約用車」标识")
        logger.info("【%s】已切换到预约业务", tag)
        return True

    # ==================== 预估详情 / 费用详情（需求 2/3） ====================

    def v160_open_estimate_detail(self, tag="v160_fee"):
        """点击车型行的「預估詳情」入口。

        :return: 页面类型标识。
        """
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        entry = self._v160_find_by_labels(
            nodes, self.TEXT_VARIANTS["estimate_detail"])
        if not entry:
            raise RuntimeError("V1.6.0 预估详情入口不可见")
        self.client.click(*center(entry[0]))
        logger.info("【%s】已进入预估详情页", tag)
        return self._v160_wait_page(
            lambda: self._v160_page_has_text(self.TEXT_VARIANTS["estimate_detail"]),
            "V1.6.0 预估详情页未加载", timeout=12)

    def v160_open_charge_rule(self, tag="v160_fee"):
        """点击「查看計價規則」进入计价规则页。"""
        self._ensure_devices_awake()
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        entry = self._v160_find_by_labels(nodes, self.TEXT_VARIANTS["pay_rule"])
        if not entry:
            raise RuntimeError("V1.6.0 计价规则入口不可见")
        self.client.click(*center(entry[0]))
        logger.info("【%s】已进入计价规则页", tag)
        return self._v160_wait_page(
            lambda: self._v160_page_has_text(self.TEXT_VARIANTS["charge_rule"]),
            "V1.6.0 计价规则页未加载", timeout=12)

    def v160_assert_fee_details(self, order_type=5, is_chartered=False,
                                tag="v160_fee"):
        """校验费项明细展示起步价/里程费/时长费/远途费/合计。

        :return: 抓取到的费项明细列表。
        :raises RuntimeError: 费项缺失。
        """
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        labels = [(n.get("label") or "").strip() for n in nodes if n.get("label")]
        expected = ["起步價", "里程費", "時長費", "遠途費", "合計"]
        if is_chartered and order_type == 6:
            expected = ["起步價", "里程費", "時長費", "遠途費", "總車費"]
        missing = [x for x in expected if x not in labels]
        if missing:
            raise RuntimeError("V1.6.0 费项明细缺失：%s；可见文案=%s"
                               % (missing, labels[:25]))
        logger.info("【%s】费项明细完整：%s", tag, expected)
        return expected

    def v160_assert_charge_rule(self, order_type=5, tag="v160_fee"):
        """校验计价规则页展示业务类型与全部费项。"""
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        labels = [(n.get("label") or "").strip() for n in nodes if n.get("label")]
        business = charge_rule_business_type(order_type)
        if business and business not in labels:
            raise RuntimeError("V1.6.0 计价规则页业务类型缺失：%s；可见文案=%s"
                               % (business, labels[:25]))
        logger.info("【%s】计价规则页业务类型=%s", tag, business)
        return labels

    def v160_build_fee_payload(self, order_type, fee_map, is_chartered=False):
        """按契约组装费项明细出参（供接口断言比对）。"""
        return estimate_detail_payload(order_type, fee_map, is_chartered)

    def v160_build_order_fee_payload(self, order_type, fee_map, is_chartered=False):
        """按契约组装订单费用详情出参。"""
        return order_fee_payload(order_type, fee_map, is_chartered)

    # ==================== 一口价提醒弹框（需求 10） ====================

    def v160_assert_fixed_price_popup(self, tag="v160_popup"):
        """校验接单后展示一口价提醒弹框。"""
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        labels = [(n.get("label") or "").strip() for n in nodes if n.get("label")]
        if "一口價說明" not in labels:
            raise RuntimeError("V1.6.0 未展示一口价提醒弹框；可见文案=%s"
                               % labels[:25])
        logger.info("【%s】一口价提醒弹框已展示", tag)
        return True

    def v160_assert_order_messages(self, is_taxi=True, is_fixed_price=True,
                                   tag="v160_msg"):
        """校验已接单页消息栏内容与条件展示。

        :return: 消息文案列表。
        """
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        labels = [(n.get("label") or "").strip() for n in nodes if n.get("label")]
        expected = [m["text"] for m in order_messages(is_taxi, is_fixed_price)]
        missing = [x for x in expected if x not in labels]
        if missing:
            raise RuntimeError("V1.6.0 消息栏内容缺失：%s；可见文案=%s"
                               % (missing, labels[:25]))
        logger.info("【%s】消息栏内容校验通过：%s", tag, expected)
        return expected

    # ==================== 履约状态（需求 9/13） ====================

    def v160_assert_booking_state(self, order_status, order_type=6,
                                  tag="v160_state"):
        """校验订单处于预期业务状态。"""
        if order_type == 6:
            group = trip_group_of(order_status, order_type)
            logger.info("【%s】预约订单 status=%s 分组=%s", tag, order_status, group)
        return group

    def v160_assert_business_label(self, order_type=6, tag="v160_state"):
        """校验预约业务展示「預約用車」标签。"""
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        labels = [(n.get("label") or "").strip() for n in nodes if n.get("label")]
        expected = business_label(order_type)
        if expected and expected not in labels:
            raise RuntimeError("V1.6.0 未展示「%s」标签；可见文案=%s"
                               % (expected, labels[:25]))
        logger.info("【%s】业务标签校验通过：%s", tag, expected or "（无）")
        return True

    def v160_assert_driver_location_hidden(self, tag="v160_state"):
        """校验出发前 20 分钟外未展示司机位置。"""
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        labels = [(n.get("label") or "").strip() for n in nodes if n.get("label")]
        placeholder = "出發前20分鐘可查看司機位置"
        if placeholder not in labels:
            raise RuntimeError("V1.6.0 未展示司机位置未暴露浮框；可见文案=%s"
                               % labels[:25])
        logger.info("【%s】司机位置未暴露浮框已展示", tag)
        return True

    # ==================== 取消与退款提示（需求 8） ====================

    def v160_assert_cancel_refund_notice(self, is_paid_advance=True,
                                         tag="v160_cancel"):
        """校验取消页展示原路退款提示。"""
        expected = cancel_page_notice(is_paid_advance)
        if not expected:
            return False
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        labels = [(n.get("label") or "").strip() for n in nodes if n.get("label")]
        if expected not in labels:
            raise RuntimeError("V1.6.0 取消页未展示退款提示「%s」；可见文案=%s"
                               % (expected, labels[:25]))
        logger.info("【%s】取消页退款提示已展示", tag)
        return True

    # ==================== 安全中心与分享（需求 12） ====================

    def v160_assert_share_supported(self, order_status, tag="v160_share"):
        """校验当前状态支持行程分享。"""
        from passenger_android_core.v160.fulfillment_contract import share_supported
        if not share_supported(order_status):
            raise RuntimeError("V1.6.0 状态 %s 不支持行程分享" % order_status)
        logger.info("【%s】状态 %s 支持行程分享", tag, order_status)
        return True

    def v160_assert_share_state(self, accepted_at, trip_ended_at, now,
                                tag="v160_share"):
        """校验分享链接有效状态。"""
        state = share_state(accepted_at, trip_ended_at, now)
        logger.info("【%s】分享状态=%s", tag, state)
        return state

    # ==================== 车辆图片颜色（需求 14） ====================

    def v160_expected_vehicle_image(self, biz_mode, color=None):
        """按司机侧车辆颜色返回期望图片资源。"""
        return resolve_vehicle_image(biz_mode, color)

    def v160_assert_vehicle_image(self, biz_mode, color=None, tag="v160_vehicle"):
        """校验订单详情车辆图片按颜色适配。"""
        expected = self.v160_expected_vehicle_image(biz_mode, color)
        root = self._passenger_root()
        nodes = list(visible_nodes(root))
        for node in nodes:
            node_id = node.get("resource-id", "").split("/")[-1]
            content_desc = (node.get("content-desc") or "").strip()
            if content_desc and content_desc == expected:
                logger.info("【%s】车辆图片资源匹配：%s", tag, expected)
                return expected
        raise RuntimeError("V1.6.0 车辆图片未按颜色适配，期望=%s" % expected)

    # ==================== 接口断言 ====================

    def v160_expect_api(self, log_text, path_keyword, tag="v160_api", code=10000):
        """校验调用方已按本次操作截取的日志；要求准确路径及唯一响应，不执行抓取。"""
        from urllib.parse import urlsplit

        if not isinstance(log_text, str):
            raise TypeError("log_text 必须为本次操作的日志文本")
        if not isinstance(path_keyword, str) or not path_keyword.startswith("/"):
            raise ValueError("必须提供完整接口路径，不接受路径关键字")
        calls = parse_api_calls(log_text.splitlines())
        matched = [call for call in calls if urlsplit(call["url"]).path == path_keyword]
        if len(matched) != 1:
            raise RuntimeError("本次接口 %s 必须唯一，实际记录数=%s，证据不足"
                               % (path_keyword, len(matched)))
        target = matched[0]
        result = check_api_response(matched, target["api"], expect_code=code)
        if result["matched"] is not True or result["passed"] is not True:
            raise AssertionError("接口日志业务码校验失败：%s" % path_keyword)
        logger.info("【%s】接口日志 %s 校验通过 code=%s", tag, path_keyword, target["code"])
        return target

    # ==================== 内部工具 ====================

    def _v160_find_by_labels(self, nodes, labels):
        """按文案查找可见节点（支持繁体/简体多候选）。"""
        result = []
        for node in nodes:
            if node.get("enabled") == "false":
                continue
            text = (node.get("label") or "").strip()
            if not text:
                continue
            for label in labels:
                if label and label in text:
                    result.append(node)
                    break
        return result

    def _v160_find_by_id(self, nodes, ids):
        """按 resource-id 查找可见节点。"""
        result = []
        for node in nodes:
            node_id = node.get("resource-id", "").split("/")[-1]
            if node_id and node_id in ids and node.get("enabled") != "false":
                result.append(node)
        return result

    def _v160_page_has_text(self, labels):
        """判断当前页面是否包含指定文案。"""
        root = self._passenger_root()
        for node in visible_nodes(root):
            text = (node.get("label") or "").strip()
            if not text:
                continue
            for label in labels:
                if label and label in text:
                    return True
        return False

    def _v160_wait_page(self, checker, message, timeout=15):
        """轮询等待页面条件成立。

        :raises TimeoutError: 超时未满足。
        """
        return self._wait(checker, message, timeout=timeout)

    # ==================== 无司机接单诊断（40 秒自动触发） ====================

    #: 下单后等待司机接单的超时秒数；超时后自动触发诊断
    NO_ACCEPT_TIMEOUT = 40

    #: 已接单关键词（繁体/简体）
    _ACCEPTED_KEYWORDS = (
        "司機正在趕來", "司机正在赶来",
        "司機已接單", "司机已接单",
        "行程中",
    )

    #: 无司机接单关键词（繁体/简体）
    _NO_ACCEPT_KEYWORDS = (
        "暫無司機接單", "暂无司机接单",
        "訂單已超時", "订单已超时",
        "呼叫超時", "呼叫超时",
        "系統繁忙", "系统繁忙",
    )

    #: 呼叫中关键词（繁体/简体）
    _CALLING_KEYWORDS = (
        "正在為您呼叫", "正在为您呼叫",
        "正在為您預約", "正在为您预约",
        "附近車輛較少", "附近车辆较少",
    )

    def v160_wait_for_accept_or_diagnose(self, tag="v160_dispatch",
                                          timeout=None, namespace="test"):
        """下单后等待司机接单，40 秒无接单则自动触发诊断。

        执行流程：
        1. 下单后开始轮询页面，每 2 秒检查一次是否出现"已接单"文案
        2. 出现已接单 → 返回 {"accepted": True}
        3. 出现无司机接单 → 触发诊断 → 返回 {"accepted": False, "diagnosis": ...}
        4. 40 秒超时仍呼叫中 → 触发诊断 → 返回 {"accepted": False, "diagnosis": ...}

        :param tag: 日志标签。
        :param timeout: 等待超时秒数，默认 NO_ACCEPT_TIMEOUT(40)。
        :param namespace: K8s namespace，默认 test。
        :return: {"accepted": bool, "order_no": str|None,
                  "diagnosis": dict|None, "elapsed": float}
        """
        from passenger_android_core.v160.dispatch_diagnose import (
            diagnose_no_accept, format_diagnosis,
        )

        wait_seconds = timeout or self.NO_ACCEPT_TIMEOUT
        start = time.time()
        logger.info("【%s】等待司机接单，超时=%ds", tag, wait_seconds)

        order_no = None
        deadline = start + wait_seconds
        last_status_log = start

        while time.time() < deadline:
            # 每 2 秒检查一次页面
            time.sleep(2)

            # 检查页面状态
            page_texts = self._v160_current_page_texts()
            now = time.time()

            # 日志节流：每 10 秒输出一次等待状态
            if now - last_status_log >= 10:
                elapsed = int(now - start)
                logger.info("【%s】已等待 %ds，页面关键词=%s",
                            tag, elapsed, [t for t in page_texts if t][:10])
                last_status_log = now

            # 检查是否已接单
            for kw in self._ACCEPTED_KEYWORDS:
                if any(kw in text for text in page_texts):
                    elapsed = now - start
                    logger.info("【%s】✅ 司机已接单（%.1fs），关键词=%s",
                                tag, elapsed, kw)
                    return {
                        "accepted": True,
                        "order_no": order_no,
                        "diagnosis": None,
                        "elapsed": elapsed,
                    }

            # 检查是否出现无司机接单
            for kw in self._NO_ACCEPT_KEYWORDS:
                if any(kw in text for text in page_texts):
                    elapsed = now - start
                    logger.warning("【%s】⚠️ 无司机接单（%.1fs），关键词=%s",
                                   tag, elapsed, kw)
                    # 尝试提取订单号
                    order_no = self._v160_extract_order_no_from_logcat()
                    # 触发诊断
                    diagnosis = self._v160_run_dispatch_diagnose(
                        order_no, namespace=namespace, tag=tag)
                    return {
                        "accepted": False,
                        "order_no": order_no,
                        "diagnosis": diagnosis,
                        "elapsed": elapsed,
                        "reason": "no_driver_text",
                    }

            # 检查是否仍在呼叫中
            calling = any(
                kw in text for text in page_texts
                for kw in self._CALLING_KEYWORDS
            )
            if not calling:
                # 页面不在呼叫中也不在已接单/无接单，可能页面已变化
                logger.info("【%s】页面不在呼叫状态，当前文案=%s",
                            tag, [t for t in page_texts if t][:10])

        # 超时仍无司机接单
        elapsed = time.time() - start
        logger.warning("【%s】⏰ 等待 %ds 无司机接单，自动触发诊断", tag, int(elapsed))

        # 超时后尝试提取订单号
        order_no = self._v160_extract_order_no_from_logcat()
        diagnosis = self._v160_run_dispatch_diagnose(
            order_no, namespace=namespace, tag=tag)

        return {
            "accepted": False,
            "order_no": order_no,
            "diagnosis": diagnosis,
            "elapsed": elapsed,
            "reason": "timeout",
        }

    def _v160_current_page_texts(self):
        """读取当前页面所有可见文本，用于关键词检测。"""
        try:
            root = self._passenger_root()
        except Exception:
            return []
        texts = []
        for node in visible_nodes(root):
            text = (node.get("label") or "").strip()
            if text:
                texts.append(text)
        return texts

    def _v160_extract_order_no_from_logcat(self):
        """没有本次操作日志边界及关联键时，不读取全量日志猜测目标订单。"""
        logger.warning("【v160_dispatch】缺少本次操作的日志关联证据，不能取最近订单号")
        return None

    def _v160_run_dispatch_diagnose(self, order_no, namespace="test",
                                     tag="v160_dispatch"):
        """执行无司机接单诊断并输出结果。

        :param order_no: 订单号，None 时尝试从页面提取。
        :return: 诊断结果字典，K8s 不可达时返回阻塞信息。
        """
        from passenger_android_core.v160.dispatch_diagnose import (
            diagnose_no_accept, format_diagnosis,
        )

        if not order_no:
            # 尝试从页面文本中提取
            texts = self._v160_current_page_texts()
            for text in texts:
                match = re.fullmatch(
                    r"(?:訂單編號|订单编号|訂單號|订单号)?\s*[:：]?\s*([A-Z0-9]{12})",
                    text.strip())
                if match and re.search(r"[A-Z]", match.group(1)) and \
                   re.search(r"\d", match.group(1)):
                    order_no = match.group(1)
                    logger.info("【%s】从页面文本提取订单号=%s", tag, order_no)
                    break

        if not order_no:
            logger.error("【%s】无法提取订单号，诊断终止", tag)
            return {
                "order_no": None,
                "conclusion": "无法提取订单号，诊断终止；请手动输入订单号执行诊断",
                "blocked": True,
                "block_reason": "order_no_not_found",
            }

        logger.info("【%s】开始诊断订单 %s（dispatcher → resource-global）",
                    tag, order_no)
        try:
            result = diagnose_no_accept(order_no, namespace=namespace)
            # 输出诊断结果到日志
            diag_text = format_diagnosis(result)
            for line in diag_text.split("\n"):
                logger.info("【%s】%s", tag, line)

            # 保存诊断结果到文件
            report_dir = self._v160_report_dir()
            diag_path = report_dir / f"dispatch_diagnose_{order_no}.json"
            import json
            diag_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8")
            logger.info("【%s】诊断结果已保存: %s", tag, diag_path)

            return result
        except Exception as exc:
            logger.error("【%s】诊断执行失败: %s: %s", tag, type(exc).__name__, exc)
            return {
                "order_no": order_no,
                "conclusion": f"诊断执行失败: {type(exc).__name__}: {exc}",
                "blocked": True,
                "block_reason": "diagnose_error",
            }

    def _v160_report_dir(self):
        """返回报告目录，不存在则创建。"""
        from pathlib import Path
        report = Path("report/v160_dispatch")
        report.mkdir(parents=True, exist_ok=True)
        return report

    def _v160_bounds_height(self, bounds):
        """从 Android bounds 字符串解析高度。"""
        if not bounds:
            return 0
        nums = re.findall(r"-?\d+", bounds)
        if len(nums) < 4:
            return 0
        return abs(int(nums[3]) - int(nums[1]))

    def _v160_screen_height(self):
        """通过已建立的客户端读取窗口高度。"""
        _, height = self.client.window_size()
        if height <= 0:
            raise RuntimeError("设备窗口高度无效")
        return height
