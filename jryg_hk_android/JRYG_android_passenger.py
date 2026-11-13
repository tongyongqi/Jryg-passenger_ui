"""Android 乘客公共步骤：启动、弹窗、登录、起终点及车型/支付选择。"""

import re
import time
import warnings
from decimal import Decimal
import xml.etree.ElementTree as ET

from .JRYG_android_base import AndroidUIBase
from .JRYG_android_login import AndroidLoginMixin
from .JRYG_driver_ui import center, rect, visible_nodes
from . import JRYG_ios_ui_elements as E
from .JRYG_ios_ui_base import iOSBase
from .JRYG_logger import logger


class AndroidPassengerMixin(AndroidLoginMixin):
    """提供共享订单接口对应的Android乘客操作，_ios前缀仅用于接口兼容。"""

    LOGIN_PHONE = iOSBase.LOGIN_PHONE
    LOGIN_CODE = iOSBase.LOGIN_CODE

    def _passenger_root(self):
        self._assert_passenger_foreground()
        root = ET.fromstring(self.client.source(format="xml"))
        if root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
            raise AssertionError("Android 页面树不是乘客App，停止操作")
        return root

    @staticmethod
    def _native_address_result(root, expected_names, north_point=False, expected_details=()):
        nodes = list(visible_nodes(root))
        title_ids = ("tv_title", "tv_address_name")
        titles = [node for node in nodes if node.get("resource-id", "").split("/")[-1] in title_ids
                  and node.get("label", "").strip() in expected_names]
        parents = {child: parent for parent in root.iter() for child in parent}
        if expected_details:
            matched = []
            for title in titles:
                container = parents.get(title)
                while container is not None and container is not root:
                    contents = list(visible_nodes(container))
                    row_titles = [node for node in contents if node.get("resource-id", "").split("/")[-1] in title_ids]
                    if len(row_titles) != 1:
                        break
                    details = [node.get("label", "").strip() for node in contents
                               if node.get("resource-id", "").endswith("/tv_address_detail_name")]
                    if len(details) == 1 and details[0] in expected_details:
                        matched.append(title)
                        break
                    if container.get("resource-id", "").endswith("/rl_parent"):
                        break
                    container = parents.get(container)
            titles = matched
        if len(titles) > 1:
            raise AssertionError("Android 目标地址不唯一，禁止选第一条结果")
        if not titles:
            return None
        if not north_point:
            return titles[0]
        parents = {child: parent for parent in root.iter() for child in parent}
        container = parents.get(titles[0])
        while container is not None and container is not root:
            labels = {node.get("label", "").strip() for node in visible_nodes(container)}
            row_titles = [node for node in visible_nodes(container)
                          if node.get("resource-id", "").split("/")[-1] in title_ids]
            if len(row_titles) != 1:
                break
            if E.NORTH_POINT_DISTRICT in labels:
                exits = [node for node in visible_nodes(container)
                         if node.get("label", "").strip() == E.NORTH_POINT_EXIT and node.get("enabled") == "true"]
                if len(exits) > 1:
                    raise AssertionError("北角地铁站出口不唯一，禁止选址")
                if exits:
                    return exits[0]
            if container.get("resource-id", "").endswith("/rl_parent"):
                break
            container = parents.get(container)
        return None

    def _search_address(self, entry_ids, keywords, address, expected_names):
        """搜索阶段临时关闭空闲等待，页面读取、唯一选址后恢复设置。"""
        driver = self.client.driver
        settings = driver.get_settings()
        if "waitForIdleTimeout" not in settings:
            raise RuntimeError("Android搜索空闲等待设置未确认，未选址")
        try:
            driver.update_settings({"waitForIdleTimeout": 0})
            return self._search_address_ready(entry_ids, keywords, address, expected_names)
        finally:
            try:
                driver.update_settings({"waitForIdleTimeout": settings["waitForIdleTimeout"]})
            except Exception:
                warnings.warn("Android搜索后空闲等待恢复失败，请检查Appium会话", RuntimeWarning)

    def _search_address_ready(self, entry_ids, keywords, address, expected_names):
        """回读搜索词并唯一选址；北角必须匹配东区站点内A1出口，不模糊降级。"""
        self._assert_passenger_foreground()
        north_point = bool({"tv_start_address", "reservation_origin"}.intersection(entry_ids)) and address.strip() in (
            *E.NORTH_POINT_STATION_NAMES, E.NORTH_POINT_SEARCH_TEXT)
        for name in entry_ids:
            entry = self.client(resourceId=E.PASSENGER_BUNDLE_ID + ":id/" + name)
            if entry.exists:
                entry.click()
                break
        else:
            if north_point:
                raise AssertionError("Android 起点入口未唯一定位，禁止误改落车点")
            self._click_text(keywords)
        field = self._wait(lambda: self.client(resourceId=E.PASSENGER_BUNDLE_ID + ":id/et_search").find_elements(),
                           "Android 地址搜索框未出现")
        if len(field) != 1:
            raise RuntimeError("Android 地址搜索框不唯一")
        search_text = E.NORTH_POINT_SEARCH_TEXT if north_point else address
        self._login_replace_text(field[0].native, search_text)
        self._check_address_query(self._passenger_root(), search_text)
        self.client.driver.execute_script("mobile: performEditorAction", {"action": "search"})

        def select_result():
            root = self._passenger_root()
            self._check_address_query(root, search_text)
            details = self.order_settings["order_validation"].get("end_details", ()) if (
                not north_point and address == E.DEFAULT_END_ADDRESS) else ()
            return self._native_address_result(root, expected_names, north_point, details)

        logger.info("Android等待唯一地址结果：%s，北角A1校验=%s", address, north_point)
        self._wait(lambda: select_result() is not None, f"搜索结果未匹配目标地址及出口：{address}")
        result = select_result()
        if result is None:
            raise AssertionError("Android 地址结果已变化，禁止点击旧坐标")
        logger.info("Android地址及出口已确认，单次选择：%s", result.get("label", "").strip())
        self.client.click(*center(result))
        self._wait(lambda: not self.client(resourceId=E.PASSENGER_BUNDLE_ID + ":id/et_search").exists,
                   "Android 选址后未离开搜索页，停止下单", timeout=10)
        self._assert_passenger_foreground()
        logger.info("Android已离开搜索页，选址完成：%s", address)

    @staticmethod
    def _check_address_query(root, expected):
        fields = [node for node in visible_nodes(root)
                  if node.get("resource-id", "").endswith("/et_search")]
        if len(fields) != 1 or fields[0].get("value") != expected:
            raise AssertionError("Android 搜索词回读不一致或输入框已变化，禁止选址")

    def _ios_configure_addresses(self, tag, start, end):
        """按起点→终点设置路线，使用默认/预约地名别名并等待确认呼叫页。"""
        limits = self.order_settings["order_validation"]
        booking_names = {"铜锣湾": ["銅鑼灣", "铜锣湾"], E.BOOKING_START_ADDRESS: ["銅鑼灣(地鐵站)", "銅鑼灣地鐵站", "铜锣湾地铁站"]}
        start_names = limits["start_names"] if start == E.DEFAULT_START_ADDRESS else booking_names.get(start, [start])
        end_names = limits["end_names"] if end == E.DEFAULT_END_ADDRESS else [end]
        self._search_address(["tv_start_address"], ["起點", "您從哪"], start, start_names)
        self._search_address(["tv_destination", "rl_destination_layout"], ["想要去哪", "想去哪"], end, end_names)
        self._wait(lambda: self.client(textContains="確認呼叫").exists, "Android 路线页未就绪")
        route = self._ios_estimate_route_identity(self._passenger_root())
        accepted = set(start_names) | {f"{name} {E.NORTH_POINT_EXIT}" for name in start_names}
        if route is not None and route[0] in accepted and route[1] in end_names:
            self._ios_call_route_key = route
        elif route is not None:
            raise AssertionError(f"Android 路线实际起终点不一致或无法唯一识别：{route}，未确认呼叫")
        self._ios_retry_estimate_quote = None

    def _ios_estimate_route_identity(self, root):
        def address(resource_names):
            values = [node.get("label", "").strip() for node in visible_nodes(root)
                      if node.get("resource-id", "").split("/")[-1] in resource_names]
            return values[0] if len(values) == 1 and values[0] else None
        start = address(("tv_start_address",))
        end = address(("tv_destination",))
        if start and end:
            return start, end
        nodes = list(visible_nodes(root))
        if any(node.get("resource-id", "").split("/")[-1] in ("tv_start_address", "tv_destination") for node in nodes):
            return None
        if root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
            return None
        calls = [node for node in nodes if node.get("label") in ("確認呼叫", "确认呼叫") and node.get("enabled") == "true"]
        cars = [node for node in nodes if node.get("resource-id", "").endswith("/tv_car_type_name")]
        if len(calls) != 1 or not cars or any(node.tag == "XCUIElementTypeAlert" for node in nodes):
            return None
        _, height = self.client.window_size()
        map_bottom = min(rect(node)[1] for node in cars) / height
        if not 0.2 < map_bottom < 0.9:
            return None
        from .JRYG_android_route_ocr import current_map_route
        route = current_map_route(self.client, map_bottom)
        logger.info("Android实时地图OCR路线核验：%s", route)
        return route

    def _ios_estimate_quote(self, root, car_type):
        if root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
            return None
        nodes = list(visible_nodes(root))
        blocked = (*E.ESTIMATE_UPDATED_KEYWORDS, *E.CASHIER_PAGE_KEYWORDS,
                   *E.ORDER_SUCCESS_KEYWORDS, *E.ORDER_PROCESSING_KEYWORDS, *E.ORDER_FAIL_KEYWORDS)
        if any(node.tag == "XCUIElementTypeAlert" or any(
                keyword in node.get("label", "") for keyword in blocked) for node in nodes):
            return None
        calls = [node for node in nodes if node.get("label") in ("確認呼叫", "确认呼叫")
                 and node.get("enabled") == "true"]
        label = E.CHARTER_CAR_LABEL if car_type == "charter" else E.METER_CAR_LABEL
        cars = [node for node in nodes if node.get("label") == label and node.get("enabled") == "true"]
        if len(calls) != 1 or len(cars) != 1:
            return None
        parents = {child: parent for parent in root.iter() for child in parent}
        container = parents.get(cars[0])
        quote = None
        while container is not None and container is not root:
            texts = {node.get("label", "").strip() for node in visible_nodes(container)}
            if (E.CHARTER_CAR_LABEL in texts and E.METER_CAR_LABEL in texts):
                break
            if car_type == "charter":
                prices = [match.group(1) for text in texts for match in
                          [re.fullmatch(r"包車價\s*([0-9]+(?:\.[0-9]{1,2})?)\s*HKD", text)] if match]
                if len(prices) == 1 and Decimal(prices[0]) > 0:
                    quote = format(Decimal(prices[0]).normalize(), "f")
            elif "打錶計價" in texts:
                quote = "打錶計價"
            if quote is not None:
                break
            container = parents.get(container)
        route = self._ios_estimate_route_identity(root)
        return (route, quote) if route is not None and quote is not None else None

    _ios_reselect_refreshed_estimate = iOSBase._ios_reselect_refreshed_estimate
    _ios_click_refreshed_estimate_call = iOSBase._ios_click_refreshed_estimate_call

    def _ios_click_estimate_car(self, car_type):
        self._assert_passenger_foreground()
        self._ios_select_car_type("estimate_refresh", car_type)

    def _ios_click_estimate_call(self):
        self._assert_passenger_foreground()
        self._click_text(["確認呼叫", "确认呼叫"], exact=True)

    def prepare_passenger_route(self, tag="passenger", start=None, end=None, *, verify_login=False):
        """统一启动登录后准备路线；verify_login保留兼容，所有入口均核验登录态。"""
        if not self.ensure_passenger_login(tag):
            raise RuntimeError("安卓登录未核验，未继续设置路线")
        self._ios_configure_addresses(tag, start or E.DEFAULT_START_ADDRESS, end or E.DEFAULT_END_ADDRESS)

    def _ios_launch_setup_and_addresses(self, tag, start, end):
        """共享订单入口委托统一路线准备，避免在订单类复制Android启动步骤。"""
        self.prepare_passenger_route(tag, start, end, verify_login=True)

    def _ios_re_setup_from_current_page(self, tag, start, end):
        """从当前页面重新设置路线、车型和下单支付方式，不重启设备会话。"""
        self._ios_configure_addresses(tag, start, end)
        self._ios_select_car_type(tag, self.CAR_TYPE)
        self._ios_select_payment(tag, self.PAYMENT)

    def _ios_select_car_type(self, tag, car_type):
        """精确选择打表或包车车型，场景标识合法性由上层用例配置负责。"""
        self._click_text([E.METER_CAR_LABEL if car_type == "meter" else E.CHARTER_CAR_LABEL], exact=True)

    def _android_select_meter_payment(self, tag, payment):
        """打表下单仅选择现金/电子支付，Alipay和银行卡仍在行程后按final_payment选择。"""
        if payment not in ("cash", "epayment", "alipay", "bankcard"):
            raise ValueError("Android打表下单支付方式不支持")
        prefix = E.PASSENGER_BUNDLE_ID + ":id/"
        mode = "cash" if payment == "cash" else "epayment"
        labels = ("現金支付", "現金") if mode == "cash" else ("電子支付",)

        def selected():
            nodes = [n for n in visible_nodes(self._passenger_root())
                     if n.get("resource-id") == prefix + "tv_pay_mode"]
            if len(nodes) > 1:
                raise RuntimeError("Android打表下单支付方式说明不唯一，禁止呼叫")
            return bool(nodes) and any("已選擇" + label in nodes[0].get("label", "") for label in labels)

        if selected():
            logger.info("【%s】Android打表本次已选择%s，后付渠道=%s；不重复点击", tag, labels[0], payment)
            return
        entries = self.client(resourceId=prefix + "tv_pay_mode").find_elements()
        if len(entries) != 1:
            raise RuntimeError("Android打表支付方式入口缺失或不唯一，禁止呼叫")
        entries[0].click()
        self._wait(lambda: self.client(text="請選擇本單支付方式").exists,
                   "Android打表支付方式面板未就绪，未呼叫", timeout=10)
        options = self.client(resourceId=prefix + "tv_payment_name").find_elements()
        targets = [option for option in options if option.label in labels]
        if len(targets) != 1:
            raise RuntimeError("Android打表现金/电子支付选项缺失或不唯一，禁止选择渠道描述或呼叫")
        targets[0].click()
        confirm = self.client(resourceId=prefix + "btn_confirm").find_elements()
        if len(confirm) != 1 or confirm[0].label != "確認選擇":
            raise RuntimeError("Android打表支付方式确认按钮不唯一或不符，禁止呼叫")
        confirm[0].click()
        self._wait(selected, "Android打表支付方式确认后未回读到本次已选择，禁止呼叫", timeout=10)
        logger.info("【%s】Android打表下单%s已回读确认，行程后支付渠道=%s", tag, labels[0], payment)

    def _ios_select_payment(self, tag, payment):
        """选择下单付款方式，已选中不重复点击；打开可选服务后须确认选择。

        电子支付下单与行程结束后的银行卡/Alipay渠道选择是不同步骤。
        """
        if getattr(self, "CAR_TYPE", None) == "meter":
            return self._android_select_meter_payment(tag, payment)
        keywords = {"cash": E.CASH_KEYWORDS, "epayment": E.EPAYMENT_KEYWORDS,
                    "bankcard": E.BANKCARD_KEYWORDS, "alipay": E.ALIPAY_KEYWORDS}[payment]
        opened = self._click_text(["可選服務"], required=False)
        texts = self._ios_get_all_texts(self.client)
        if not any("已選擇" in text and any(keyword in text for keyword in keywords) for text in texts):
            self._click_text(keywords)
        if opened:
            self._wait(lambda: self.client(text="確認選擇").exists, "Android 支付面板缺少確認選擇")
            self._click_text(["確認選擇"], exact=True)

    def _ios_click_confirm_call(self, tag):
        """只点击一次确认呼叫，后续登录、预付或下单结果由订单编排处理。"""
        self._click_text(["確認呼叫"], exact=True)

    def _ios_click_confirm_pay(self, tag):
        """预付收银台只点击一次确认支付并呼叫，不等同于行程结束后付款。"""
        self._click_text(["確認支付並呼叫"])

    _ios_wait_order_result = iOSBase._ios_wait_order_result

    def _ios_back_to_home(self, tag):
        """激活乘客App并最多五轮返回首页，以起点控件确认；不在此核验到账。"""
        self.client.app_activate(E.PASSENGER_BUNDLE_ID)
        for _ in range(5):
            if self.client(resourceId=E.PASSENGER_BUNDLE_ID + ":id/tv_start_address").exists:
                return True
            if not self._click_text(["返回首頁", "主頁", "首页"], exact=True, required=False):
                tabs = self.client(resourceId=E.PASSENGER_BUNDLE_ID + ":id/item_tab_icon_layout").find_elements()
                if tabs:
                    tabs[0].click()
                else:
                    self.client.back()
            time.sleep(2)
        raise TimeoutError("Android 乘客未返回首页")


class AndroidPassengerBase(AndroidPassengerMixin, AndroidUIBase):
    """独立乘客用例复用同一套平台操作，无需声明订单支付场景。"""
