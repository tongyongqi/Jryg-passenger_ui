"""
港版阳光出行 iOS 乘客端 —— 公共基础方法（Base Class）
==============================================================================
所有 iOS 测试用例继承此类，共享设备连接、地址搜索、车型选择、截图等公共操作。
==============================================================================
"""

import os
import sys
import time
import pytest
import xml.etree.ElementTree as ET

import wda
from airtest.core.api import connect_device
from poco.drivers.ios import iosPoco

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from jryg_hk_ios.JRYG_config import SETTINGS
from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios import JRYG_ios_ui_elements as E


class iOSBase:
    """iOS 自动化测试公共基类，提供设备连接与通用操作封装"""

    @classmethod
    def setup_class(cls):
        """连接 WDA 物理通道，初始化 Poco 控件树驱动"""
        cls.wda_url = SETTINGS["device"].get("wda_url", "http://127.0.0.1:8100")
        logger.info(f"【iOS 自动化】正在尝试连接 WDA 物理通道: {cls.wda_url}")

        try:
            cls.client = wda.Client(cls.wda_url)
            status = cls.client.status()
            logger.info(f"【iOS 自动化】设备连接成功！ status: {status}")
        except Exception as e:
            logger.error(
                f"【iOS 连接失败】请确认 WDA 已在手机上正常运行，且通过 tidevice/iproxy 转发了 8100 端口！ 错误原因: {e}"
            )
            pytest.skip("WDA 物理通道未就绪，跳过 iOS 自动化用例")

        connect_device(f"ios:///{cls.wda_url}")
        cls.poco = iosPoco()
        logger.info("【iOS 自动化】Poco 控件树驱动加载完成，已准备就绪。")

    @classmethod
    def teardown_class(cls):
        """类级清理：释放设备连接与相关资源。

        :return: None。"""
        logger.info("【iOS 自动化】测试执行结束，正在安全释放连接通道。")

    # ==================== 通用操作 ====================

    @staticmethod
    def _ios_get_all_texts(client):
        """获取当前页面所有可见文本"""
        import requests
        try:
            r = requests.get("http://127.0.0.1:8100/source?format=xml", timeout=12)
            root = ET.fromstring(r.json()["value"])
            texts = []
            for node in root.iter():
                if node.get("visible", "true") == "false":
                    continue
                for key in ("label", "name", "value"):
                    val = node.get(key, "")
                    if val.strip():
                        texts.append(val.strip())
            return list(dict.fromkeys(texts))
        except Exception as e:
            logger.warning(f"获取页面文本失败: {e}")
            return []

    @staticmethod
    def _ios_get_textfields():
        """获取当前页面所有 TextField 的坐标和值"""
        import requests
        try:
            r = requests.get("http://127.0.0.1:8100/source?format=xml", timeout=12)
            root = ET.fromstring(r.json()["value"])
            out = []
            for n in root.iter():
                if "TextField" not in n.tag:
                    continue
                if n.get("visible", "true") == "false":
                    continue
                x, y = int(n.get("x", "0")), int(n.get("y", "0"))
                w, h = int(n.get("width", "0")), int(n.get("height", "0"))
                out.append(dict(value=n.get("value", ""), cx=x + w // 2, cy=y + h // 2))
            return out
        except Exception as e:
            logger.warning(f"  >> 获取TextField列表失败: {e}")
            return []

    def _ios_screenshot(self, filename):
        """截图并保存到 screenshots 目录"""
        path = os.path.join(BASE_DIR, "screenshots", filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            self.client.screenshot(path)
            logger.info(f"  >> 截图已保存: {path}")
        except Exception as e:
            logger.warning(f"  >> 截图失败: {e}")

    def _ios_dismiss_keyboard(self):
        """关闭 iOS 键盘"""
        done_btn = self.client(xpath=E.KEYBOARD_DONE_XPATH)
        if done_btn.exists:
            done_btn.click()
            time.sleep(1)
            logger.info("  >> 已点击'完成'关闭键盘")
            return
        self.client.click(196, 128)
        time.sleep(1)
        logger.info("  >> 已点击空白区域关闭键盘")

    # ==================== 登录流程 ====================

    # 港版测试账号（手机号 8 位，区号 +852，验证码固定 123456）
    LOGIN_PHONE = "11001727"
    LOGIN_CODE = "123456"

    def _ios_ensure_monitor(self):
        """确保 self.monitor 已初始化。

        conftest.py 的 ios_page_diagnostics fixture 会自动注入 monitor，
        但在 setup_class 或非 pytest 入口调用时可能不存在，此处兜底创建。

        :return: IOSPageMonitor 实例。
        """
        if not hasattr(self, "monitor") or self.monitor is None:
            from jryg_hk_ios.JRYG_page_monitor import IOSPageMonitor
            output_dir = os.path.join(BASE_DIR, "report", "diagnostics")
            self.monitor = IOSPageMonitor(self.wda_url, output_dir)
        return self.monitor

    def _ios_is_login_page(self):
        """检测当前页面是否为登录页（手机号输入页或验证码输入页）。

        :return: True 表示当前在登录页，False 表示不在。
        """
        monitor = self._ios_ensure_monitor()
        state = monitor.inspect().state
        return state in ("login_phone_input", "login_code_input")

    def _ios_dismiss_privacy_agreement(self):
        """检测并处理隐私协议弹框（点击"同意"）。

        使用 IOSPageMonitor 状态机检测，当页面状态为 privacy_agreement 时
        点击"同意"按钮。使用 monitor.click_text 精确匹配，避免误点"不同意"。
        """
        monitor = self._ios_ensure_monitor()
        for _ in range(3):
            page = monitor.inspect()
            if page.state != "privacy_agreement":
                return
            logger.info("  >> 检测到隐私协议弹框，点击'同意'...")
            if not monitor.click_text(self.client, "同意"):
                # 兜底：坐标点击"同意"按钮（通常在屏幕下方右侧）
                self.client.click(int(0.75 * 393), int(0.85 * 852))
            time.sleep(3)

    def _ios_ui_login(self, phone=None, code=None, tag="登录"):
        """执行完整的 UI 登录流程（手机号 + 验证码），基于 IOSPageMonitor 状态机。

        与单独运行登录用例（JRYG_test_ios_open_and_login.py）使用完全相同的
        状态机方式：每轮检测当前页面状态，根据状态执行对应操作，确保：
        - 协议复选框用 monitor.click_text 精确匹配（不误点"不同意"）
        - 验证码页用 monitor.wait_for 等待页面切换完成（键盘保持打开）
        - 验证码输入先尝试 TextField，失败则逐个键盘按键

        :param phone: 登录手机号，默认使用 LOGIN_PHONE。
        :param code: 短信验证码，默认使用 LOGIN_CODE（测试环境固定 123456）。
        :param tag: 日志标签。
        :return: True 表示登录成功并进入首页，False 表示登录失败。
        """
        phone = phone or self.LOGIN_PHONE
        code = code or self.LOGIN_CODE
        client = self.client
        monitor = self._ios_ensure_monitor()

        deadline = time.monotonic() + 120
        last_state = None
        state_since = time.monotonic()

        for cycle in range(30):
            state = monitor.inspect().state
            now = time.monotonic()
            if state != last_state:
                last_state, state_since = state, now
            # 单个状态停滞超过 40 秒视为卡死
            if now > deadline or now - state_since > 40:
                logger.warning(f"【{tag}】登录流程停滞，当前页面={state}")
                self._ios_screenshot(f"JRYG_ios_login_stuck_{state}.png")
                return False
            logger.info(f"【{tag}】登录流转 [循环 {cycle}] -> 页面状态: {state}")

            # ---- 隐私协议弹框 ----
            if state == "privacy_agreement":
                logger.info(f"【{tag}】检测到隐私协议弹框，点击'同意'...")
                monitor.click_text(client, "同意")
                time.sleep(3)
                continue

            # ---- 系统权限弹框 ----
            if state == "permission_dialog":
                logger.info(f"【{tag}】检测到权限弹框，点击'去授權'...")
                if not monitor.click_text(client, "去授權"):
                    monitor.click_text(client, "去授权")
                time.sleep(1)
                try:
                    client.alert.accept()
                except Exception:
                    pass
                time.sleep(3)
                continue

            # ---- 活动弹窗 ----
            if state == "activity_popup":
                monitor.dismiss_activity_popup(client)
                continue

            # ---- 手机号输入页 ----
            if state == "login_phone_input":
                logger.info(f"【{tag}】在手机号输入页：输入手机号、获取验证码...")
                # 输入手机号
                phone_field = client(type="TextField")
                if phone_field.exists:
                    phone_field.click()
                    phone_field.clear_text()
                    client.send_keys(phone)
                    time.sleep(1)

                # 勾选协议（精确匹配，避免误点"不同意"）
                # 手机号输入页的协议复选框通常含"已閱讀"文字
                agree_el = self.poco(textMatches=".*已閱讀.*|.*已阅读.*")
                if agree_el.exists():
                    agree_el.click()
                    time.sleep(1)

                # 点击"取得驗證碼"
                if not monitor.click_text(client, "取得驗證碼"):
                    monitor.click_text(client, "获取验证码")

                # 等待进入验证码页或隐私协议页
                try:
                    monitor.wait_for(
                        "进入验证码页或协议确认页",
                        lambda page: page.state in ("login_code_input", "privacy_agreement"),
                        timeout=15,
                    )
                except AssertionError:
                    logger.warning(f"【{tag}】点击'取得驗證碼'后未进入验证码页")
                continue

            # ---- 验证码输入页 ----
            if state == "login_code_input":
                logger.info(f"【{tag}】在验证码输入页：输入验证码 {code}...")
                # 先尝试标准 TextField（焦点连续时有效）
                code_field = client(type="TextField")
                if code_field.exists:
                    code_field.click()
                    code_field.clear_text()
                    client.send_keys(code)
                else:
                    # 无 TextField（自定义 OTP 控件），逐个键盘按键输入
                    # 键盘在进入验证码页时已弹出，直接按键
                    logger.info(f"【{tag}】无 TextField，通过键盘逐个输入验证码...")
                    for digit in code:
                        key_el = client(xpath=f'//XCUIElementTypeKey[@label="{digit}"]')
                        if key_el.exists:
                            key_el.tap()
                        time.sleep(0.3)

                # 等待登录完成（进入首页/个人中心/活动弹窗）
                try:
                    monitor.wait_for(
                        "验证码提交后登录成功",
                        lambda page: page.state in (
                            "mine_logged", "home_unlogged", "activity_popup",
                            "privacy_agreement", "permission_dialog",
                            "route_selected", "order_active",
                        ),
                        timeout=15,
                    )
                except AssertionError:
                    logger.warning(f"【{tag}】验证码提交后未离开验证码页")
                continue

            # ---- 已登录状态（个人中心） ----
            if state == "mine_logged":
                logger.info(f"【{tag}】登录成功，已在个人中心确认登录态")
                self._ios_screenshot("JRYG_ios_login_success.png")
                return True

            # ---- 首页（已登录或未登录） ----
            if state == "home_unlogged":
                # 首页说明已登录成功（跳转回来了）
                logger.info(f"【{tag}】登录成功，已进入首页")
                self._ios_screenshot("JRYG_ios_login_success.png")
                return True

            # ---- 路线选择页（登录后直接回到下单流程） ----
            if state == "route_selected":
                logger.info(f"【{tag}】登录成功，已回到下单页面")
                self._ios_screenshot("JRYG_ios_login_success.png")
                return True

            # ---- 订单进行中（登录后回到进行中订单页） ----
            if state == "order_active":
                logger.info(f"【{tag}】登录成功，当前有进行中订单")
                self._ios_screenshot("JRYG_ios_login_success.png")
                return True

            # ---- 订单完成页（行程结束/评价页） ----
            if state == "order_complete":
                logger.info(f"【{tag}】在订单完成页，点击返回按钮回首页...")
                back_wda = client(
                    xpath='//XCUIElementTypeImage[contains(@name,"navi_arrow_left")]')
                if back_wda.exists:
                    back_wda.click()
                else:
                    client.click(34, 82)
                time.sleep(3)
                continue

            time.sleep(2)

        logger.warning(f"【{tag}】登录状态机重试耗尽，最后页面={last_state}")
        self._ios_screenshot("JRYG_ios_login_timeout.png")
        return False

    def _ios_ensure_logged_in(self, tag="登录"):
        """确保 App 处于已登录状态，未登录则执行 UI 登录。

        检测当前页面：
        - 在登录页 → 执行 UI 登录流程
        - 不在登录页 → 认为已登录，直接返回

        :param tag: 日志标签。
        :return: True 表示已登录或登录成功，False 表示登录失败。
        """
        if self._ios_is_login_page():
            logger.info(f"【{tag}】检测到未登录（当前在登录页），执行 UI 登录...")
            return self._ios_ui_login(tag=tag)
        logger.info(f"【{tag}】已处于登录状态，无需登录")
        return True

    # ==================== 地址搜索 ====================

    def _ios_search_address(self, is_start=True, address=""):
        """通用地址搜索：点击入口 → 输入地址 → 选择搜索结果

        :raises AssertionError: 未能进入搜索页或未能选中地址时抛出。
        """
        client = self.client
        poco = self.poco
        addr_type = "起点" if is_start else "终点"

        if is_start:
            logger.info(f"  输入起点: {address}")
            gate = client(xpath=E.START_GATE_XPATH)
            if not gate.exists:
                gate = poco(textMatches=E.START_GATE_POCO_REGEX)
            fallback_coord = E.START_GATE_FALLBACK_COORD
        else:
            logger.info(f"  输入终点: {address}")
            gate = client(xpath=E.DEST_GATE_XPATH)
            if not gate.exists:
                gate = poco(textMatches=E.DEST_GATE_POCO_REGEX)
            fallback_coord = E.DEST_GATE_FALLBACK_COORD

        entered = False
        for attempt in range(5):
            if gate and (hasattr(gate, "exists") and gate.exists or not hasattr(gate, "exists")):
                try:
                    gate.click()
                except Exception:
                    gate.tap()
            else:
                if attempt % 2 == 0:
                    client.click(*fallback_coord)
                else:
                    client.tap(*fallback_coord)
            time.sleep(2)
            if client(type="TextField").exists or poco(type=E.SEARCH_TEXTFIELD_TYPE).exists():
                entered = True
                break

        if not entered:
            raise AssertionError(f"未能进入{addr_type}搜索页")

        target_text = address.replace("地鐵站", "").replace("地铁站", "").strip()
        hist_el = client(xpath=f'//XCUIElementTypeStaticText[@label="{address}" or @value="{address}"]')
        if not hist_el.exists and target_text != address:
            hist_el = client(xpath=f'//XCUIElementTypeStaticText[@label="{target_text}" or @value="{target_text}"]')
        if hist_el.exists:
            hist_el.tap()
            logger.info(f"  >> 从历史记录选中{addr_type}: {address}")
            time.sleep(4 if is_start else 7)
            return

        tf = client(className=E.SEARCH_TEXTFIELD_TYPE)
        if tf.exists:
            tf.click()
            time.sleep(1)
        client.send_keys(address)
        time.sleep(4)

        done = client(xpath=E.KEYBOARD_DONE_XPATH)
        if done.exists:
            done.tap()
            time.sleep(2)

        first_cell = client(type="Cell")
        if first_cell.exists:
            first_cell[0].click()
            logger.info(f"  >> 选中{addr_type}: {address}")
        else:
            result = client(xpath=f'//XCUIElementTypeStaticText[contains(@label,"{target_text}") or contains(@value,"{target_text}")]')
            if result.exists:
                result.tap()
                logger.info(f"  >> 文本匹配选中{addr_type}: {address}")
            else:
                client.click(*E.SEARCH_FIRST_RESULT_COORD)
                logger.info(f"  >> 物理坐标选中{addr_type}")
        time.sleep(4 if is_start else 7)

    # ==================== 公共流程步骤 ====================

    def _ios_launch_setup_and_addresses(self, tag, start_addr="", end_addr=""):
        """公共步骤：拉起App → 处理弹窗 → 跳过引导页 → 关闭广告 → 配置起点 → 配置终点"""
        logger.info(f"【{tag} 步骤 1】正在回到桌面...")
        self.client.home()
        time.sleep(2)

        logger.info(f"【{tag} 步骤 2】正在拉起 App: {E.PASSENGER_BUNDLE_ID}")
        self.client.session(E.PASSENGER_BUNDLE_ID)
        time.sleep(10)

        logger.info(f"【{tag} 步骤 3】处理系统弹窗...")
        try:
            self.client.alert.accept()
            time.sleep(2)
        except Exception:
            pass

        # 处理隐私协议弹框（登录后或首次进入时可能弹出）
        self._ios_dismiss_privacy_agreement()

        for i in range(5):
            guide_btn = self.client(xpath=E.GUIDE_SKIP_XPATH)
            if guide_btn.exists:
                guide_btn.tap()
                logger.info(f"  >> 跳过引导页 ({i + 1}/5)")
                time.sleep(3)
            else:
                break

        for ad_btn_text in E.AD_CLOSE_IDENTIFIERS:
            ad_el = self.poco(ad_btn_text)
            if ad_el.exists():
                ad_el.click()
                logger.info(f"成功关闭广告弹框 (标识: {ad_btn_text})")
                time.sleep(2)
                break

        logger.info(f"【{tag} 步骤 4】配置起点: {start_addr}")
        self._ios_search_address(is_start=True, address=start_addr)

        logger.info(f"【{tag} 步骤 5】配置终点: {end_addr}")
        self._ios_search_address(is_start=False, address=end_addr)
        time.sleep(7)

    def _ios_select_car_type(self, tag, car_type="charter"):
        """选择车型：charter=包車價的士, meter=打錶的士"""
        if car_type == "charter":
            xpath_exact = E.CHARTER_CAR_XPATH_EXACT
            xpath_contains = E.CHARTER_CAR_XPATH_CONTAINS
            poco_regex = E.CHARTER_CAR_POCO_REGEX
            fallback_coord = E.CHARTER_CAR_FALLBACK_COORD
            car_name = E.CHARTER_CAR_LABEL
        else:
            xpath_exact = E.METER_CAR_XPATH_EXACT
            xpath_contains = E.METER_CAR_XPATH_CONTAINS
            poco_regex = E.METER_CAR_POCO_REGEX
            fallback_coord = E.METER_CAR_FALLBACK_COORD
            car_name = E.METER_CAR_LABEL

        logger.info(f"【{tag} 步骤 6】选择『{car_name}』车型...")
        car_selected = False

        car_el = self.client(xpath=xpath_exact)
        if car_el.exists:
            car_el.click()
            car_selected = True
            logger.info(f"  >> [WDA] 精确匹配并点击『{car_name}』")

        if not car_selected:
            poco_car = self.poco(textMatches=poco_regex)
            if poco_car.exists():
                poco_car.click()
                car_selected = True
                logger.info(f"  >> [Poco] 模糊匹配并点击{car_name}")

        if not car_selected:
            car_el = self.client(xpath=xpath_contains)
            if car_el.exists:
                car_el.click()
                car_selected = True
                logger.info(f"  >> [WDA] contains 匹配并点击{car_name}")

        if not car_selected:
            logger.warning(f"  >> 未匹配到{car_name}，物理坐标点击...")
            self.client.click(*fallback_coord)
            time.sleep(2)

        time.sleep(3)

    def _ios_click_confirm_call(self, tag):
        """点击『確認呼叫』按钮（含重试机制）"""
        for attempt in range(3):
            btn = self.client(xpath=E.CONFIRM_CALL_XPATH)
            if not btn.exists:
                poco_btn = self.poco(textMatches=E.CONFIRM_CALL_POCO_REGEX)
                if poco_btn.exists():
                    btn = poco_btn

            if btn and (hasattr(btn, "exists") and btn.exists or not hasattr(btn, "exists")):
                try:
                    btn.click()
                    logger.info(f"  >> [{tag}] 已点击确认呼叫 (尝试 {attempt+1}/3)")
                    time.sleep(5)
                    return
                except Exception as e:
                    logger.warning(f"  >> [{tag}] 点击确认呼叫异常: {e}，重试...")
                    time.sleep(2)
            else:
                logger.warning(f"  >> [{tag}] 未找到确认呼叫按钮，物理坐标点击 (尝试 {attempt+1}/3)")
                self.client.click(*E.CONFIRM_CALL_FALLBACK_COORD)
                time.sleep(5)
                return

        logger.error(f"  >> [{tag}] 确认呼叫按钮点击失败，已达最大重试次数")
        self._ios_screenshot(f"JRYG_ios_{tag}_confirm_call_failed.png")

    def _ios_click_confirm_pay(self, tag):
        """点击『確認支付並呼叫』按钮"""
        btn = self.client(xpath=E.CONFIRM_PAY_XPATH)
        if not btn.exists:
            poco_btn = self.poco(textMatches=E.CONFIRM_PAY_POCO_REGEX)
            if poco_btn.exists():
                btn = poco_btn

        if btn and (hasattr(btn, "exists") and btn.exists or not hasattr(btn, "exists")):
            btn.click()
            logger.info(f"  >> [{tag}] 已点击确认支付并呼叫")
        else:
            self.client.click(*E.CONFIRM_PAY_FALLBACK_COORD)
            logger.info(f"  >> [{tag}] 物理坐标点击确认支付并呼叫")
        time.sleep(5)

    def _ios_select_payment(self, tag, payment="cash"):
        """选择支付方式。

        支持两种交互模式：
        1. 直接点击：页面上的支付方式选项（包車價的士等）
        2. 弹出面板：先点击"可選服務"区域弹出支付方式选择面板，
           在面板中选择后点击"確認選擇"（打錶的士等）

        :param tag: 日志标签。
        :param payment: 支付方式标识（cash/epayment/alipay/bankcard）。
        :raises AssertionError: 未找到支付方式选项时抛出。
        """
        keywords_map = {
            "cash": E.CASH_KEYWORDS,
            "epayment": E.EPAYMENT_KEYWORDS,
            "alipay": E.ALIPAY_KEYWORDS,
            "bankcard": E.BANKCARD_KEYWORDS,
        }
        keywords = keywords_map.get(payment, [payment])
        selected = False

        # ---- 模式 1：直接搜索页面上的支付方式选项 ----
        for kw in keywords:
            pay_el = self.client(xpath=f'//*[contains(@label, "{kw}") or contains(@value, "{kw}")]')
            if pay_el.exists:
                pay_el.click()
                selected = True
                logger.info(f"  >> [WDA] 直接点击支付方式『{kw}』")
                break

        if not selected:
            poco_regex = ".*" + ".*|.*".join(keywords) + ".*"
            poco_pay = self.poco(textMatches=poco_regex)
            if poco_pay.exists():
                poco_pay.click()
                selected = True
                logger.info(f"  >> [Poco] 直接点击支付方式")

        # ---- 模式 2：通过支付方式选择面板 ----
        if not selected:
            logger.info(f"  >> [{tag}] 未直接找到支付方式，尝试弹出支付方式选择面板...")
            # 点击"可選服務"文案区域弹出面板
            service_el = self.client(
                xpath='//*[contains(@label,"可選服務") or contains(@value,"可選服務")]')
            if service_el.exists:
                service_el.click()
                time.sleep(2)
                logger.info(f"  >> [{tag}] 已点击'可選服務'区域，等待面板弹出")
            else:
                # 尝试 Poco 匹配
                service_poco = self.poco(textMatches=".*可選服務.*")
                if service_poco.exists():
                    service_poco.click()
                    time.sleep(2)

            # 在面板中选择目标支付方式
            for kw in keywords:
                pay_el = self.client(
                    xpath=f'//*[contains(@label,"{kw}") or contains(@value,"{kw}")]')
                if pay_el.exists:
                    pay_el.click()
                    selected = True
                    logger.info(f"  >> [WDA] 面板中选择支付方式『{kw}』")
                    break

            if not selected:
                poco_regex = ".*" + ".*|.*".join(keywords) + ".*"
                poco_pay = self.poco(textMatches=poco_regex)
                if poco_pay.exists():
                    poco_pay.click()
                    selected = True
                    logger.info(f"  >> [Poco] 面板中选择支付方式")

            # 点击"確認選擇"按钮确认选择
            if selected:
                confirm_btn = self.client(
                    textMatches="確認選擇|确认选择")
                if confirm_btn.exists:
                    confirm_btn.click()
                    logger.info(f"  >> [{tag}] 已点击'確認選擇'按钮")
                    time.sleep(2)
                else:
                    confirm_poco = self.poco(textMatches=".*確認選擇.*|.*确认选择.*")
                    if confirm_poco.exists():
                        confirm_poco.click()
                        logger.info(f"  >> [{tag}] 已点击'確認選擇'按钮")
                        time.sleep(2)
                    else:
                        logger.warning(f"  >> [{tag}] 未找到'確認選擇'按钮")

        if not selected:
            self._ios_screenshot(f"JRYG_ios_{tag}_payment_notfound.png")
            raise AssertionError(f"未匹配到支付方式({payment})，页面无对应选项")

        time.sleep(2)

    def _ios_wait_order_result(self, tag, max_checks=15):
        """轮询等待下单结果。

        :return: "success"=下单成功, "too_close"=距离太近需切换终点,
                 "fail"=下单失败, "timeout"=超时无结果。
        """
        logger.info(f"  >> [{tag}] 等待下单结果...")
        result = "timeout"
        for wait_sec in range(max_checks):
            time.sleep(2)
            page_texts = self._ios_get_all_texts(self.client)
            logger.info(f"  [{tag} {wait_sec*2}s] 页面文本: {page_texts[:200]}")

            if any(kw in t for t in page_texts for kw in E.ORDER_SUCCESS_KEYWORDS):
                logger.info(f"  [{tag} {wait_sec*2}s] 【下单成功】")
                result = "success"
                break

            if any(kw in t for t in page_texts for kw in E.ORDER_FAIL_KEYWORDS):
                logger.warning(f"  [{tag} {wait_sec*2}s] 下单失败")
                result = "fail"
                break

            # 检测"距离太近"提示
            if any(kw in t for t in page_texts
                   for kw in E.DISTANCE_TOO_CLOSE_KEYWORDS):
                logger.warning(f"  [{tag} {wait_sec*2}s] 起终点距离太近，需切换终点")
                result = "too_close"
                # 尝试点击提示上的"確定"/"好"按钮关闭弹窗
                for btn_kw in ["確定", "确定", "好", "OK", "知道了"]:
                    btn = self.client(textContains=btn_kw)
                    if btn.exists:
                        btn.click()
                        time.sleep(1)
                        break
                break

            if any(kw in t for t in page_texts for kw in E.ORDER_PROCESSING_KEYWORDS):
                logger.info(f"  [{tag} {wait_sec*2}s] 处理中...")

        return result

    def _ios_fill_bank_field(self, field_index, text, label):
        """通过坐标聚焦并填写银行卡表单字段"""
        fields = self._ios_get_textfields()
        if field_index >= len(fields):
            raise AssertionError(f"未找到第{field_index + 1}个TextField（{label}），当前仅有{len(fields)}个字段")

        cx, cy = fields[field_index]["cx"], fields[field_index]["cy"]
        self.client.click(cx, cy)
        time.sleep(1.5)
        self.client.send_keys(text)
        time.sleep(1.5)

        fields_after = self._ios_get_textfields()
        if field_index < len(fields_after):
            actual = fields_after[field_index]["value"]
            logger.info(f"  >> {label}输入完成: '{actual}'")

        self._ios_dismiss_keyboard()
