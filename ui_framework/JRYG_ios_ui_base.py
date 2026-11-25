"""
港版阳光出行 iOS 乘客端 —— 公共基础方法（Base Class）
==============================================================================
所有 iOS 测试用例继承此类，共享设备连接、地址搜索、车型选择、截图等公共操作。
公共启动由_ios_prepare_passenger_app处理遮挡，_ios_configure_addresses只设置地址；
页面文本委托IOSPage解析，支付继承HKIOSPaymentMixin，订单顺序不在工具层重排。

本类提供以下功能模块：
  1. 设备连接：setup_class 连接 WDA + Poco，teardown_class 释放连接
  2. 通用操作：获取页面 XML/文本/TextField、截图、关闭键盘
  3. 通用弹框处理：按钮点击（Poco→WDA→坐标三级降级）、循环关闭弹框
  4. 登录流程：隐私协议处理、UI 登录（手机号+验证码状态机）、登录态检测
  5. 地址搜索：点击入口→输入地址→等待结果→选择结果→验证跳转
  6. 公共流程步骤：拉起App→配置起终点→选车型→确认呼叫→确认支付→银行卡表单→OTP
  7. 支付方式选择：统一面板流程（可選服務→选支付方式→確認選擇）
  8. 下单结果等待：轮询页面文本判断成功/失败/距离太近/超时
==============================================================================
"""

from decimal import Decimal
import os
import re
import sys
import time
import pytest
import xml.etree.ElementTree as ET

# WDA（WebDriverAgent）iOS 自动化驱动
import wda

# 框架根路径（JRYG_Passenger_UI_HK-ios），加入 sys.path 供跨目录导入
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# 导入港版 iOS 自动化配置（设备信息、目录路径等）
from ui_framework.JRYG_config import SETTINGS
# 导入统一日志记录器
from ui_framework.JRYG_logger import logger
# 导入 UI 元素定位常量（XPath、关键词、坐标、测试数据）
from ui_framework import JRYG_ios_ui_elements as E
from ui_framework.JRYG_ios_payment import HKIOSPaymentMixin
from ui_framework.JRYG_device_guard import DeviceUnlockError, ensure_unlocked, remember_foreground
from ui_framework.JRYG_device_guard import ensure_mac_awake, mac_stop_prevent_sleep


class iOSBase(HKIOSPaymentMixin):
    """iOS 自动化测试公共基类，提供设备连接与通用操作封装"""

    def setup_method(self):
        """登录核验结果只在单次用例内复用，不跨用例或运行持久化。"""
        self._passenger_verified_phone = None

    @classmethod
    def setup_class(cls):
        """连接WDA后初始化Poco；设备依赖仅在执行阶段加载，不干扰pytest收集。

        Poco内置旧six导入器不支持find_spec，不能在pytest加载conftest前注册。
        Airtest也只在此处加载，避免离线导入或仅收集时探测设备依赖。
        不管执行到哪个阶段，如果 Mac 或 iPhone 熄屏，唤醒后继续执行，不中断测试。
        """
        # Mac 防休眠：不管执行到哪个阶段都检测并唤醒
        ensure_mac_awake()

        cls.wda_url = SETTINGS["device"].get("wda_url", "http://127.0.0.1:8100")
        logger.info(f"【iOS 自动化】正在尝试连接 WDA 物理通道: {cls.wda_url}")

        try:
            cls.client = wda.Client(cls.wda_url)
            status = cls.client.status()
            logger.info(f"【iOS 自动化】设备连接成功！ status: {status}")
            ensure_unlocked(cls.client)
        except DeviceUnlockError:
            raise
        except Exception as e:
            logger.error(
                f"【iOS 连接失败】请确认 WDA 已在手机上正常运行，且通过 tidevice/iproxy 转发了 8100 端口！ 错误原因: {e}"
            )
            pytest.skip("WDA 物理通道未就绪，跳过 iOS 自动化用例")

        from airtest.core.api import connect_device
        from poco.drivers.ios import iosPoco

        connect_device(f"ios:///{cls.wda_url}")
        cls.poco = iosPoco()
        logger.info("【iOS 自动化】Poco 控件树驱动加载完成，已准备就绪。")

    @classmethod
    def teardown_class(cls):
        """类级清理：释放设备连接与 Mac 防休眠进程。

        :return: None。"""
        logger.info("【iOS 自动化】测试执行结束，正在安全释放连接通道。")
        mac_stop_prevent_sleep()

    # ==================== 通用操作 ====================

    def _ios_get_source_xml(self):
        """从当前乘客WDA客户端获取页面XML，不固定8100端口。

        用于需要按元素属性（label/name/rect）精确定位并自行计算坐标的场景
        （例如 Safari WebView 内的元素必须坐标点击，element uuid 点击无效）。

        :return: XML 字符串，普通读取失败返回空字符串；解锁失败直接停止。
        """
        ensure_unlocked(self.client)
        try:
            source = self.client.source(format="xml") or ""
            if source:
                remember_foreground(self.client, ET.fromstring(source))
            return source
        except Exception as e:
            logger.warning(f"获取页面源码失败: {e}")
            return ""

    @staticmethod
    def _ios_get_all_texts(client):
        """获取当前页面所有可见文本。

        使用传入客户端读取页面树，委托 IOSPage 的可见性及去重保序规则。
        不固定8100端口，双设备时始终读取调用方的设备；读取超时由WDA客户端管理。

        :param client: 当前乘客页面所属的 WDA 客户端。
        :return: 文本列表（去重保序），读取或解析失败返回空列表。
        """
        from ui_framework.JRYG_page_monitor import IOSPage
        ensure_unlocked(client)
        try:
            page = IOSPage(client.source(format="xml"))
            remember_foreground(client, page.root)
            return list(page.texts)
        except Exception as e:
            logger.warning(f"获取页面文本失败: {e}")
            return []

    @staticmethod
    def _ios_get_textfields():
        """获取当前页面所有 TextField 的坐标和值。

        请求 WDA 页面树 XML，提取所有可见 TextField 的中心坐标 (cx, cy) 和当前值。
        用于银行卡表单等 WebView 场景下的字段定位（元素 uuid 不可靠时用坐标点击）。

        :return: 字典列表，每个字典含 value/cx/cy 三个键，失败返回空列表。
        """
        import requests
        try:
            r = requests.get("http://127.0.0.1:8100/source?format=xml", timeout=12)
            root = ET.fromstring(r.json()["value"])
            out = []
            for n in root.iter():
                # 只处理 TextField 类型节点
                if "TextField" not in n.tag:
                    continue
                # 跳过不可见的 TextField
                if n.get("visible", "true") == "false":
                    continue
                # 计算中心坐标
                x, y = int(n.get("x", "0")), int(n.get("y", "0"))
                w, h = int(n.get("width", "0")), int(n.get("height", "0"))
                out.append(dict(value=n.get("value", ""), cx=x + w // 2, cy=y + h // 2))
            return out
        except Exception as e:
            logger.warning(f"  >> 获取TextField列表失败: {e}")
            return []

    def _ios_screenshot(self, filename):
        """截图并保存到 screenshots 目录。

        :param filename: 截图文件名（含 .png 后缀）。
        """
        # 截图输出路径：screenshots/ 目录下
        path = os.path.join(BASE_DIR, "screenshots", filename)
        # 确保目录存在
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            # 调用 WDA 截图接口
            self.client.screenshot(path)
            logger.info(f"  >> 截图已保存: {path}")
        except Exception as e:
            logger.warning(f"  >> 截图失败: {e}")

    def _ios_dismiss_keyboard(self):
        """关闭 iOS 键盘。

        优先点击键盘上的"完成/Done"按钮，找不到则点击空白区域收起键盘。
        """
        # 方式 1：点击键盘上的"完成/Done"按钮
        done_btn = self.client(xpath=E.KEYBOARD_DONE_XPATH)
        if done_btn.exists:
            done_btn.click()
            time.sleep(1)
            logger.info("  >> 已点击'完成'关闭键盘")
            return
        # 方式 2：点击空白区域收起键盘（坐标 196,128 为屏幕上方空白区）
        self.client.click(196, 128)
        time.sleep(1)
        logger.info("  >> 已点击空白区域关闭键盘")

    # ==================== 通用弹框处理 ====================

    def _ios_click_dialog_button(self, keywords, tag="", fallback_coord=None,
                                  wait_after=2, log_prefix=""):
        """通用弹框按钮点击：Poco精确 → Poco模糊 → WDA → 坐标 fallback。

        统一封装弹框确认按钮的点击逻辑，支持简繁体关键词列表，
        依次尝试 Poco 精确匹配、Poco 模糊匹配、WDA textContains、
        物理坐标兜底，命中任一即点击并返回 True。

        :param keywords: 按钮关键词列表（如 ["不用車了", "不用车了", "確認取消"]）。
        :param tag: 日志标签。
        :param fallback_coord: 兜底坐标 (x, y)，None 则不使用坐标兜底。
        :param wait_after: 点击后等待秒数。
        :param log_prefix: 日志前缀（如 "预清理"）。
        :return: True 表示点击成功，False 表示未找到按钮。
        """
        prefix = f"【{tag}】{log_prefix}" if log_prefix else f"【{tag}】" if tag else ""
        for kw in keywords:
            # 1. Poco 精确匹配
            btn = self.poco(text=kw)
            if btn.exists():
                btn.click()
                logger.info(f"{prefix}Poco 点击 '{kw}'")
                time.sleep(wait_after)
                return True
            # 2. Poco 模糊匹配
            btn = self.poco(textMatches=f".*{kw}.*")
            if btn.exists():
                btn.click()
                logger.info(f"{prefix}Poco 模糊匹配点击 '{kw}'")
                time.sleep(wait_after)
                return True
            # 3. WDA textContains
            btn_wda = self.client(textContains=kw)
            if btn_wda.exists:
                btn_wda.click()
                logger.info(f"{prefix}WDA 点击 '{kw}'")
                time.sleep(wait_after)
                return True

        # 4. 坐标兜底
        if fallback_coord:
            self.client.click(*fallback_coord)
            logger.info(f"{prefix}物理坐标点击 {fallback_coord}")
            time.sleep(wait_after)
            return True

        return False

    def _ios_dismiss_dialogs(self, keywords_list, tag="", max_rounds=3, wait_after=1):
        """循环检测并关闭多个弹框。

        每轮扫描页面，依次尝试关键词列表中的按钮，命中则点击并继续下一轮，
        直到无弹框或达到最大轮数。适用于取消订单后可能连续弹出多个确认框的场景。

        :param keywords_list: 每组关键词列表（如 ["確定", "确定", "好", "OK"]）。
        :param tag: 日志标签。
        :param max_rounds: 最大检测轮数。
        :param wait_after: 每次点击后等待秒数。
        """
        for _ in range(max_rounds):
            clicked = self._ios_click_dialog_button(
                keywords_list, tag=tag, wait_after=wait_after)
            if not clicked:
                break

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
            from ui_framework.JRYG_page_monitor import IOSPageMonitor
            output_dir = os.path.join(BASE_DIR, "report", "diagnostics")
            self.monitor = IOSPageMonitor(self.wda_url, output_dir)
        return self.monitor

    def _ios_is_login_page(self):
        """检测当前页面是否为登录页（手机号输入页或验证码输入页）。

        :return: True 表示当前在登录页，False 表示不在。
        """
        monitor = self._ios_ensure_monitor()
        state = monitor.inspect().state
        unlogged = state in ("mine_unlogged", "login_phone_input", "login_code_input")
        if unlogged:
            self._passenger_verified_phone = None
        return unlogged

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
            time.sleep(1)

    def _ios_assert_passenger_foreground(self):
        ensure_unlocked(self.client, resume_bundle=E.PASSENGER_BUNDLE_ID)
        current = self.client.http.get("/wda/activeAppInfo", timeout=5).value
        if not isinstance(current, dict) or current.get("bundleId") != E.PASSENGER_BUNDLE_ID:
            raise RuntimeError("乘客App不在前台，停止登录，不向其他App输入凭据")

    def _ios_login_page(self, monitor):
        self._ios_assert_passenger_foreground()
        return monitor.inspect()

    def _ios_verify_passenger_account(self, page, phone, tag):
        self._passenger_verified_phone = None
        if page.state != "mine_logged":
            raise RuntimeError("乘客未登录，停止下单")
        monitor = self._ios_ensure_monitor()
        if not monitor.click_text(self.client, "主頁", "首頁", "首页", "主頁，標籤頁", "首頁，標籤頁"):
            raise RuntimeError("乘客已登录，但未找到返回首页入口，停止下单")
        monitor.wait_for("登录核验后返回首页", lambda item: item.state == "home_unlogged", timeout=15)
        self._passenger_verified_phone = phone
        logger.info("【%s】已记录本次用例登录态，不比对账号，后续不再进入个人中心核验", tag)
        return True

    def _ios_ui_login(self, phone=None, code=None, tag="登录"):
        """执行完整的 UI 登录流程（手机号 + 验证码），基于 IOSPageMonitor 状态机。

        使用状态机方式：每轮检测当前页面状态，根据状态执行对应操作，确保：
        - 协议复选框用 monitor.click_text 精确匹配（不误点"不同意"）
        - 验证码页用 monitor.wait_for 等待页面切换完成（键盘保持打开）
        - 验证码输入先尝试 TextField，失败则逐个键盘按键

        :param phone: 登录手机号，默认使用 LOGIN_PHONE。
        :param code: 短信验证码，默认使用 LOGIN_CODE（测试环境固定 123456）。
        :param tag: 日志标签。
        :return: True 表示登录成功并进入首页，False 表示登录失败。
        """
        phone = phone or os.environ.get("HK_PASSENGER_MOBILE") or self.LOGIN_PHONE
        code = code or os.environ.get("HK_PASSENGER_UI_CODE") or self.LOGIN_CODE
        if not re.fullmatch(r"[0-9]{8}", phone) or not re.fullmatch(r"[0-9]{6}", code):
            raise RuntimeError("乘客自动登录需要8位测试手机号和6位测试验证码")
        client = self.client
        monitor = self._ios_ensure_monitor()
        phone_submitted = code_submitted = entry_opened = mine_opened = False

        deadline = time.monotonic() + 120
        last_state = None
        state_since = time.monotonic()

        for cycle in range(30):
            page = self._ios_login_page(monitor)
            state = page.state
            if state in ("mine_unlogged", "login_phone_input", "login_code_input"):
                self._passenger_verified_phone = None
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
                time.sleep(1)
                continue

            # ---- 系统权限弹框 ----
            if state == "permission_dialog":
                logger.info(f"【{tag}】检测到权限弹框，点击'去授權'...")
                if not monitor.click_text(client, "去授權"):
                    monitor.click_text(client, "去授权")
                time.sleep(0.5)
                try:
                    client.alert.accept()
                except Exception:
                    pass
                time.sleep(1)
                continue

            # ---- 活动弹窗 ----
            if state == "activity_popup":
                monitor.dismiss_activity_popup(client)
                continue

            if state == "mine_unlogged":
                if entry_opened:
                    return False
                entry_opened = True
                if not monitor.click_text(client, "登錄/註冊", "登录/注册", "登入/註冊"):
                    return False
                monitor.wait_for("打开乘客登录输入页", lambda item: item.state in (
                    "login_phone_input", "login_code_input"), timeout=15)
                continue

            # ---- 手机号输入页 ----
            if state == "login_phone_input":
                if phone_submitted:
                    logger.warning("【%s】手机号已提交但页面未完成切换，停止，不重复发送短信", tag)
                    return False
                logger.info(f"【{tag}】在手机号输入页：输入手机号、获取验证码...")
                # 输入手机号
                phone_field = client(type="TextField")
                if phone_field.exists:
                    phone_field.click()
                    phone_field.clear_text()
                    client.send_keys(phone)
                    time.sleep(1)
                else:
                    return False

                # 勾选协议（精确匹配，避免误点"不同意"）
                # 手机号输入页的协议复选框通常含"已閱讀"文字
                agree_el = self.poco(textMatches=".*已閱讀.*|.*已阅读.*")
                if agree_el.exists():
                    agree_el.click()
                    time.sleep(1)

                # 点击"取得驗證碼"
                phone_submitted = True
                if not monitor.click_text(client, "取得驗證碼", "获取验证码", "獲取驗證碼"):
                    return False

                # 等待进入验证码页或隐私协议页
                try:
                    monitor.wait_for(
                        "进入验证码页或协议确认页",
                        lambda page: page.state in ("login_code_input", "privacy_agreement"),
                        timeout=15,
                    )
                except AssertionError:
                    logger.warning(f"【{tag}】点击'取得驗證碼'后未进入验证码页")
                    return False
                continue

            # ---- 验证码输入页 ----
            if state == "login_code_input":
                if code_submitted:
                    logger.warning("【%s】验证码已提交但未完成登录，停止，不重复输入", tag)
                    return False
                code_submitted = True
                logger.info(f"【{tag}】在验证码输入页：输入测试验证码...")
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
                        if not key_el.exists:
                            return False
                        key_el.tap()
                        time.sleep(0.3)

                # 等待登录完成（进入首页/个人中心/活动弹窗）
                try:
                    result = monitor.wait_for(
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
                    return False
                # wait_for 返回最终页面，若已登录直接核验返回，不再回到循环顶部
                if result is not None and result.state == "mine_logged":
                    return self._ios_verify_passenger_account(result, phone, tag)
                mine_opened = False
                continue

            # ---- 已登录状态（个人中心） ----
            if state == "mine_logged":
                return self._ios_verify_passenger_account(page, phone, tag)

            if state in ("home_unlogged", "route_selected"):
                if getattr(self, "_passenger_verified_phone", None):
                    return True
                if mine_opened:
                    logger.warning("【%s】个人中心登录核验未完成，停止下单", tag)
                    return False
                mine_opened = True
                if not monitor.click_text(client, "我的", "個人中心", "个人中心", "我的，標籤頁"):
                    return False
                monitor.wait_for("打开乘客个人中心核验登录", lambda item: item.state in (
                    "mine_logged", "mine_unlogged", "login_phone_input", "login_code_input"), timeout=15)
                continue

            # ---- 订单进行中（登录后回到进行中订单页） ----
            if state == "order_active":
                self._passenger_verified_phone = phone
                logger.info(f"【{tag}】已记录登录态，当前有进行中订单")
                self._ios_screenshot("JRYG_ios_login_success.png")
                return True
            time.sleep(2)

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
        """本次用例只主动核验一次；明确登录失效时由登录页检测清除缓存。"""
        if getattr(self, "_passenger_verified_phone", None):
            self._ios_assert_passenger_foreground()
            logger.info("【%s】复用本次用例登录态，跳过重复登录核验", tag)
            return True
        phone = os.environ.get("HK_PASSENGER_MOBILE") or self.LOGIN_PHONE
        monitor = self._ios_ensure_monitor()
        page = self._ios_login_page(monitor)
        if page.state == "mine_logged":
            return self._ios_verify_passenger_account(page, phone, tag)
        if page.state == "order_active":
            self._passenger_verified_phone = phone
            logger.info("【%s】乘客已有进行中订单，记录登录态并保留页面，不重新登录或下单", tag)
            return True
        if page.state in ("address_search", "unknown"):
            # App 可能停在搜索页或其他无法识别的中间态（如上次测试遗留），
            # 尝试点击左上角返回箭头回到首页后再判断登录态
            logger.info("【%s】页面状态 %s，尝试返回首页后重新判断登录态", tag, page.state)
            for back_attempt in range(3):
                # 优先点击左上角返回箭头（路线页/搜索页通用）
                try:
                    back_btn = self.client(name="slm_icon_navi_arrow_left")
                    if back_btn.exists:
                        back_btn.click()
                        time.sleep(1.5)
                        page = self._ios_login_page(monitor)
                        if page.state not in ("address_search", "unknown"):
                            break
                        continue
                except Exception:
                    pass
                # 无返回箭头时重启 App 回首页
                try:
                    self.client.session(E.PASSENGER_BUNDLE_ID)
                    time.sleep(3)
                except Exception:
                    pass
                page = self._ios_login_page(monitor)
                if page.state not in ("address_search", "unknown"):
                    break
            if page.state == "mine_logged":
                return self._ios_verify_passenger_account(page, phone, tag)
            if page.state == "home_unlogged":
                logger.info("【%s】已返回首页，继续核验登录态", tag)
            elif page.state in ("address_search", "unknown"):
                logger.error("【%s】无法确认乘客登录态，停止下单", tag)
                return False
        logger.info("【%s】核验乘客登录态，需要时调用现有UI登录方法", tag)
        return self._ios_ui_login(tag=tag)

    # ==================== 地址搜索 ====================

    # 取消订单确认弹框的关键词（简繁体）
    CANCEL_CONFIRM_KEYWORDS = ["不用車了", "不用车了", "確認取消", "确认取消", "確定", "确定", "好"]

    def _ios_address_search_page(self, is_start, expected_value=None):
        """只接受乘客前台、正确起终点占位及唯一可用输入框。"""
        root = ET.fromstring(self._ios_get_source_xml())
        if root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
            raise AssertionError("地址搜索时乘客App不在前台，停止选址")
        if any(node.get("visible") == "true" for node in root.iter("XCUIElementTypeAlert")):
            raise AssertionError("地址搜索存在弹窗，停止输入或选择")
        placeholders = ("您從哪裡出發", "您从哪里出发") if is_start else ("請輸入落車點", "请输入落车点")
        fields = [node for node in root.iter("XCUIElementTypeTextField") if node.get("visible") == "true"]
        if (len(fields) != 1 or fields[0].get("enabled") == "false"
                or fields[0].get("placeholderValue") not in placeholders):
            raise AssertionError("不是唯一可用的起点搜索框" if is_start else "不是唯一可用的终点搜索框")
        if expected_value is not None:
            value = fields[0].get("value") or ""
            if expected_value == "":
                valid = value in ("", fields[0].get("placeholderValue"))
            else:
                valid = value == expected_value
            if not valid:
                raise AssertionError("地址输入回读不一致，禁止点击搜索或结果")
        return root, fields[0]

    @staticmethod
    def _ios_address_node_xpath(root, node):
        parents = {child: parent for parent in root.iter() for child in parent}
        parts = []
        while node is not root:
            parent = parents[node]
            siblings = [child for child in parent if child.tag == node.tag]
            parts.append(f"{node.tag}[{siblings.index(node) + 1}]")
            node = parent
        return f"//{root.tag}[1]/" + "/".join(reversed(parts))

    def _ios_click_address_node(self, root, node):
        elements = self.client(xpath=self._ios_address_node_xpath(root, node)).find_elements()
        if len(elements) != 1 or not elements[0].displayed or not elements[0].enabled:
            raise AssertionError("地址控件不再唯一可用，停止，不改点第一条或固定坐标")
        expected = node.get("label") or node.get("name") or node.get("value") or ""
        label, name, value = elements[0].label, elements[0].name, elements[0].value
        actual = label or name or value or ""
        if not expected and not label and not value and name in (None, "", node.tag):
            bounds = elements[0].bounds
            try:
                same_bounds = all(abs(float(node.get(key)) - float(getattr(bounds, key))) <= 1
                                  for key in ("x", "y", "width", "height"))
            except (TypeError, ValueError, AttributeError):
                same_bounds = False
            if not same_bounds:
                raise AssertionError("无文字起点按钮边界已变化，停止点击")
            actual = ""
        if elements[0].className != node.tag or actual != expected:
            raise AssertionError("地址控件身份已变化，停止，不点击旧结果")
        elements[0].tap()

    @staticmethod
    def _ios_start_address(address):
        if not isinstance(address, str) or address.strip() not in E.START_ADDRESS_NAMES:
            raise AssertionError("起点仅允许铜锣湾，禁止使用其他地址或站点出口")
        return E.DEFAULT_START_ADDRESS

    def _ios_enter_address_query(self, is_start, address):
        """清空并回读后输入地址，单次点击键盘搜索；历史记录不免输入。"""
        if is_start:
            address = self._ios_start_address(address)
        if not isinstance(address, str) or not address.strip():
            raise AssertionError("地址不能为空，未输入或搜索")
        root, node = self._ios_address_search_page(is_start)
        elements = self.client(xpath=self._ios_address_node_xpath(root, node)).find_elements()
        if len(elements) != 1 or not elements[0].displayed or not elements[0].enabled:
            raise AssertionError("地址输入框不可用，停止输入")
        field = elements[0]
        field.click()
        self._ios_address_search_page(is_start)
        field.clear_text()
        self._ios_address_search_page(is_start, "")
        field.set_text(address)
        for _ in range(10):
            root, node = self._ios_address_search_page(is_start)
            if node.get("value") == address:
                break
            time.sleep(0.5)
        else:
            raise AssertionError("地址输入未正确回读，未提交键盘搜索")
        for _ in range(10):
            root, _field = self._ios_address_search_page(is_start, address)
            buttons = []
            for keyboard in root.iter("XCUIElementTypeKeyboard"):
                if keyboard.get("visible") != "true":
                    continue
                buttons.extend(node for node in keyboard.iter()
                               if node.tag in ("XCUIElementTypeButton", "XCUIElementTypeKey")
                               and node.get("visible") == "true" and node.get("enabled") != "false"
                               and (node.get("label") or node.get("name") or "").casefold() in ("搜索", "搜尋", "search"))
            if len(buttons) > 1:
                raise AssertionError("键盘搜索按钮不唯一，未提交搜索")
            if buttons:
                self._ios_click_address_node(root, buttons[0])
                logger.info("  >> 已清空并输入%s：%s；已单次点击键盘搜索", "起点" if is_start else "终点", address)
                return
            time.sleep(0.5)
        raise AssertionError("未找到可用的键盘搜索按钮，未把历史列表当作查询结果")

    @staticmethod
    def _ios_address_text_key(text):
        traditional = str.maketrans({"铜": "銅", "锣": "鑼", "湾": "灣", "谭": "潭", "譚": "潭",
                                    "园": "園", "铁": "鐵", "学": "學", "车": "車", "场": "場",
                                    "门": "門", "岛": "島", "东": "東", "区": "區", "头": "頭"})
        text = re.sub(r"[\s()（）]+", "", (text or "").translate(traditional))
        return text.replace("出口", "出入口")

    @staticmethod
    def _ios_address_result_node(root, address, *, is_start=False):
        """匹配可见结果Cell内精确地址标题，同名时取App排序的第一个。

        真机搜索"铜锣湾"返回多个标题为"銅鑼灣"的Cell，第一个是铜锣湾地铁站区域
        （副标题"香港特別行政區灣仔區Wan Chai District"），App会把它解析成该地铁站的
        出入口并作为实际起点；后续带门牌号的Cell是同一区域内的其他POI，不是同一个地址。
        因此同名时取App排序的第一个，与App对输入地址的解析保持一致。
        站点扩展Cell（如"銅鑼灣(地鐵站)"含出入口按钮）标题不精确匹配。
        """
        if is_start:
            iOSBase._ios_start_address(address)
        key = iOSBase._ios_address_text_key(address)
        keyboard_nodes = {node for keyboard in root.iter("XCUIElementTypeKeyboard") for node in keyboard.iter()}
        matches = []
        for cell in root.iter("XCUIElementTypeCell"):
            if cell in keyboard_nodes or cell.get("visible") != "true" or cell.get("enabled") == "false":
                continue
            for node in cell.iter("XCUIElementTypeStaticText"):
                if node in keyboard_nodes or node.get("visible") != "true" or node.get("enabled") == "false":
                    continue
                text = node.get("label") or node.get("name") or node.get("value") or ""
                matched = text.strip() in E.START_ADDRESS_NAMES if is_start else iOSBase._ios_address_text_key(text) == key
                if matched:
                    matches.append((cell, node))
        matches = list(dict.fromkeys(matches))
        if not matches:
            return None
        matches.sort(key=lambda pair: float(pair[0].get("y", "9999")))
        return matches[0][1]

    def _ios_select_search_result(self, is_start, address, target_text, tag=""):
        """等待当前查询的精确结果，只点击一次，再核验地址页及目标页面。"""
        if is_start:
            address = self._ios_start_address(address)
        addr_type = "起点" if is_start else "终点"
        previous = None
        for _ in range(60):
            root, _field = self._ios_address_search_page(is_start, address)
            node = self._ios_address_result_node(root, address, is_start=is_start)
            signature = None if node is None else (self._ios_address_node_xpath(root, node),
                                                  node.get("label"), node.get("name"), node.get("value"))
            if signature is not None and signature == previous:
                self._ios_click_address_node(root, node)
                logger.info("  >> 已精确选择%s：%s", addr_type, address)
                break
            previous = signature
            time.sleep(0.5)
        else:
            self._ios_screenshot(f"JRYG_ios_search_{addr_type}_no_result.png")
            raise AssertionError(f"未找到唯一匹配的{addr_type}结果，未选历史首项或固定坐标")

        keywords = ("想去哪裡", "想去哪里", "目的地", "起點", "起点", "確認呼叫", "确认呼叫") if is_start else (
            "確認呼叫", "确认呼叫", "包車價", "打錶", "可選服務")
        for _ in range(20):
            root = ET.fromstring(self._ios_get_source_xml())
            if root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
                raise AssertionError("选址后乘客App已离开前台，停止下单")
            if any(node.get("visible") == "true" for node in root.iter("XCUIElementTypeAlert")):
                raise AssertionError("选址后出现弹窗，停止下单")
            fields = [node for node in root.iter("XCUIElementTypeTextField") if node.get("visible") == "true"]
            texts = [(node.get("label") or node.get("name") or node.get("value") or "")
                     for node in root.iter("XCUIElementTypeStaticText") if node.get("visible") == "true"]
            buttons = [(node.get("label") or node.get("name") or "")
                       for node in root.iter("XCUIElementTypeButton") if node.get("visible") == "true"]
            if not fields and any(keyword in text for text in texts + buttons for keyword in keywords):
                logger.info("  >> %s设置完成并已核验目标页面", addr_type)
                return
            time.sleep(0.5)
        self._ios_screenshot(f"JRYG_ios_search_{addr_type}_jump_fail.png")
        raise AssertionError(f"{addr_type}选中后页面未正确跳转，停止，不重复选址")

    @staticmethod
    def _ios_page_contains(source_xml, *texts):
        """在原始页面树中查找任意文本，不依赖 WDA 的 visible 属性。

        部分 UI 文案（如首页"当前城市暂未开通服务"）被 WDA 标记为 visible=false，
        但实际在屏显示，因此需要基于原始 XML 做兜底识别。
        """
        if not source_xml:
            return False
        try:
            root = ET.fromstring(source_xml)
        except Exception:
            return False
        all_text = " ".join(
            (node.get("label") or "") + " " + (node.get("name") or "") + " " + (node.get("value") or "")
            for node in root.iter()
        )
        return any(text in all_text for text in texts)

    @staticmethod
    def _ios_start_entry_node(root):
        """通过起点文案定位同一行真实按钮；隐藏文案不等于整行不可点击。"""
        parents = {child: parent for parent in root.iter() for child in parent}
        excluded = {node for item in root.iter()
                    if item.tag in ("XCUIElementTypeKeyboard", "XCUIElementTypeCell") for node in item.iter()}
        matches = []
        for node in root.iter():
            if node in excluded or node.tag not in ("XCUIElementTypeStaticText", "XCUIElementTypeButton") or node.get("enabled") == "false":
                continue
            text = (node.get("label") or node.get("name") or node.get("value") or "").strip()
            failure_prompt = (any(message in text for message in E.LOCATION_UNAVAILABLE_TEXTS)
                              and any(prompt in text for prompt in ("請輸入起點", "请输入起点")))
            if text not in E.START_GATE_TEXTS + E.START_ADDRESS_NAMES and not failure_prompt:
                continue
            parent = parents.get(node)
            if parent is None or parent.get("visible") != "true" or parent.get("enabled") == "false":
                continue
            buttons = [child for child in parent if child.tag == "XCUIElementTypeButton"
                       and child.get("visible") == "true" and child.get("enabled") != "false"]
            if len(buttons) > 1:
                raise AssertionError("起点行内可点击按钮不唯一，停止，不点击隐藏文案或固定坐标")
            if buttons:
                matches.extend(buttons)
            elif node.get("visible") == "true":
                matches.append(node)
        matches = list(dict.fromkeys(matches))
        if len(matches) > 1:
            raise AssertionError("起点入口不唯一，停止，不改点第一项")
        return matches[0] if matches else None

    def _ios_open_start_search(self):
        """只打开起点搜索；不等待定位、不输入地址、不点击终点或业务按钮。"""
        def read_page():
            root = ET.fromstring(self._ios_get_source_xml())
            if root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
                raise AssertionError("打开起点搜索时乘客App不在前台")
            if any(node.get("visible") == "true" for node in root.iter("XCUIElementTypeAlert")):
                raise AssertionError("打开起点搜索时存在弹窗，停止点击")
            return root

        def is_start_search(root):
            fields = [node for node in root.iter("XCUIElementTypeTextField") if node.get("visible") == "true"]
            if not fields:
                return False
            if (len(fields) != 1 or fields[0].get("enabled") == "false"
                    or fields[0].get("placeholderValue") not in ("您從哪裡出發", "您从哪里出发")):
                raise AssertionError("当前不是唯一可用的起点搜索框，停止，不切换或输入终点")
            return True

        for _ in range(20):
            root = read_page()
            if is_start_search(root):
                return
            target = self._ios_start_entry_node(root)
            if target is not None:
                fresh = read_page()
                if is_start_search(fresh):
                    return
                current = self._ios_start_entry_node(fresh)
                if current is None or self._ios_address_node_xpath(fresh, current) != self._ios_address_node_xpath(root, target):
                    raise AssertionError("起点行控件已变化，停止点击")
                self._ios_click_address_node(fresh, current)
                logger.info("  >> 已单次点击起点行可用按钮；定位失败提示不阻断手动输入")
                break
            time.sleep(0.5)
        else:
            raise AssertionError("未找到唯一可用的起点入口，未触发重新定位或固定坐标")
        for _ in range(20):
            if is_start_search(read_page()):
                logger.info("  >> 已核验进入起点搜索页面")
                return
            time.sleep(0.5)
        self._ios_screenshot("JRYG_ios_start_entry_jump_fail.png")
        raise AssertionError("起点行点击后未进入起点搜索页，停止，不重复点击")

    def _ios_open_route_address_row(self, is_start=True):
        """在路线页点击起点/终点地址栏行，进入地址搜索页。

        路线页地址栏由「起点文字(上) + 终点文字(下)」组成，
        起点行旁通常有 ``slm_icon_anno_start`` 图标，
        终点行无固定标记图标，但按 y 坐标排在起点下方。
        本方法不依赖固定 marker 名称，按地址栏布局特征定位行：

        1. 收集所有地址栏候选文字行（排除车型/价格等非地址文案）；
        2. 按 y 坐标排序，起点取第一行，终点取第二行；
        3. 优先点击文字行，标记图标作为兜底。

        :return: True 表示已进入搜索页（存在 TextField）。
        """
        client = self.client

        # 非地址文案关键词，用于过滤
        _NON_ADDR_KEYWORDS = (
            "確認呼叫", "确认呼叫", "服務偏好", "服务偏好",
            "全程", "約行駛", "约行驶", "包車價", "打錶", "打表",
            "安全中心", "以實際", "HKD", "券", "預約", "预约",
        )

        def _has_textfield():
            return client(type=E.SEARCH_TEXTFIELD_TYPE).exists

        for attempt in range(3):
            try:
                source = client.source(format="xml")
            except Exception:
                source = ""
            if not source:
                return False
            try:
                root = ET.fromstring(source)
            except Exception:
                return False

            # 收集地址栏候选文字行
            text_nodes = []
            for node in root.iter():
                if node.tag != "XCUIElementTypeStaticText":
                    continue
                try:
                    y = float(node.get("y", 0)); h = float(node.get("height", 0))
                    w = float(node.get("width", 0))
                except (TypeError, ValueError):
                    continue
                if w <= 0 or h <= 0:
                    continue
                text = (node.get("label") or node.get("value") or node.get("name") or "").strip()
                if not text:
                    continue
                if any(k in text for k in _NON_ADDR_KEYWORDS):
                    continue
                text_nodes.append((node, y))

            # 按 y 排序，起点取第一行，终点取第二行
            text_nodes.sort(key=lambda item: item[1])
            if not text_nodes:
                return False

            if is_start:
                candidates = [text_nodes[0][0]]
            elif len(text_nodes) >= 2:
                candidates = [text_nodes[1][0]]
            else:
                candidates = []

            # 兜底：用 marker 图标
            marker = "slm_icon_anno_start" if is_start else "slm_icon_anno_end"
            marker_nodes = []
            for node in root.iter():
                name = node.get("name") or ""
                if name == marker:
                    marker_nodes.append(node)

            for tnode in candidates:
                try:
                    x = float(tnode.get("x", 0)); y = float(tnode.get("y", 0))
                    w = float(tnode.get("width", 0)); h = float(tnode.get("height", 0))
                except (TypeError, ValueError):
                    continue
                if w <= 0 or h <= 0:
                    continue
                try:
                    client.click(int(x + w / 2), int(y + h / 2))
                except Exception:
                    continue
                time.sleep(2)
                if _has_textfield():
                    return True

            # 文字行无效时退回点击标记图标
            for mnode in marker_nodes:
                try:
                    x = float(mnode.get("x", 0)); y = float(mnode.get("y", 0))
                    w = float(mnode.get("width", 0)); h = float(mnode.get("height", 0))
                except (TypeError, ValueError):
                    continue
                if w <= 0 or h <= 0:
                    continue
                try:
                    client.click(int(x + w / 2), int(y + h / 2))
                except Exception:
                    continue
                time.sleep(2)
                if _has_textfield():
                    return True

            if not candidates and not marker_nodes:
                return False
        return _has_textfield()

    def _ios_search_address(self, is_start=True, address=""):
        """通用地址搜索：点击入口 → 输入地址 → 等待搜索结果出现 → 选择结果 → 验证页面跳转

        - 起点：选中后验证返回首页（检测"想去哪裡"等首页关键词）
        - 终点：选中后验证进入路线选择页（检测车型选择或"確認呼叫"）

        :raises AssertionError: 未能进入搜索页、搜索结果未出现、未能选中地址、
                                 或选中后未正确跳转时抛出。
        """
        if is_start:
            address = self._ios_start_address(address)
            logger.info("  输入起点: %s", address)
            self._ios_open_start_search()
            self._ios_enter_address_query(True, address)
            self._ios_select_search_result(True, address, address)
            return

        client = self.client
        poco = self.poco
        logger.info("  输入终点: %s", address)
        gate = client(xpath=E.DEST_GATE_XPATH)
        if not gate.exists:
            gate = poco(textMatches=E.DEST_GATE_POCO_REGEX)
        entered = False
        for attempt in range(5):
            if gate and (hasattr(gate, "exists") and gate.exists or not hasattr(gate, "exists")):
                try:
                    gate.click()
                except Exception:
                    gate.tap()
            else:
                client.click(*E.DEST_GATE_FALLBACK_COORD)
            if self._ios_wait_for_page(
                    lambda: client(type="TextField").exists or poco(type=E.SEARCH_TEXTFIELD_TYPE).exists(),
                    timeout=4, interval=0.5):
                entered = True
                break
        if not entered:
            entered = self._ios_open_route_address_row(is_start=False)
        if not entered:
            self._ios_screenshot("JRYG_ios_search_终点_enter_fail.png")
            raise AssertionError("未能进入终点搜索页")
        self._ios_enter_address_query(False, address)
        self._ios_select_search_result(False, address, address)

    # ==================== 公共流程步骤 ====================

    def _ios_launch_setup_and_addresses(self, tag, start_addr=E.DEFAULT_START_ADDRESS, end_addr=""):
        """初始下单：启动清理后配置起终点；当前页重选不得调用此启动入口。"""
        start_addr = self._ios_start_address(start_addr)
        self._ios_prepare_passenger_app(tag)
        if not self._ios_ensure_logged_in(tag=tag):
            raise RuntimeError("乘客自动登录失败，停止配置地址和下单")
        self._ios_configure_addresses(tag, start_addr, end_addr)

    def _ios_wait_for_page(self, check_fn, timeout=10, interval=0.5):
        """轮询等待页面条件满足，替代固定 sleep；命中即返回，不空等。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if check_fn():
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False

    def _ios_prepare_passenger_app(self, tag, *, launch_wait=10, alert_wait=2):
        """共用启动步骤：桌面→乘客App→系统权限→隐私→引导→广告。

        正常下单保留10秒启动/2秒权限等待；预清理传8秒/1秒。
        仅清理启动遮挡，不取消订单、不登录、不支付，也不重置司机状态。
        """
        ensure_unlocked(self.client)
        # 步骤 1：回到桌面
        logger.info(f"【{tag} 步骤 1】正在回到桌面...")
        self.client.home()
        time.sleep(1)

        # 步骤 2：拉起乘客端 App
        logger.info(f"【{tag} 步骤 2】正在拉起 App: {E.PASSENGER_BUNDLE_ID}")
        self.client.session(E.PASSENGER_BUNDLE_ID)
        # 用轮询替代固定 launch_wait：App 前台就绪即继续
        self._ios_wait_for_page(
            lambda: self._ios_active_bundle() == E.PASSENGER_BUNDLE_ID,
            timeout=launch_wait, interval=1)

        # 系统权限不存在时继续检查应用内遮挡；真实控件失败由后续流程判断。
        logger.info(f"【{tag} 步骤 3】处理系统弹窗...")
        try:
            self.client.alert.accept()
            time.sleep(alert_wait)
        except Exception:
            pass

        # 处理隐私协议弹框（登录后或首次进入时可能弹出）
        self._ios_dismiss_privacy_agreement()

        # 跳过引导页（最多 5 次，每次点击跳过按钮后等待 1 秒）
        for i in range(5):
            guide_btn = self.client(xpath=E.GUIDE_SKIP_XPATH)
            if guide_btn.exists:
                guide_btn.tap()
                logger.info(f"  >> 跳过引导页 ({i + 1}/5)")
                time.sleep(1)
            else:
                break

        # 关闭广告弹窗（依次尝试广告关闭按钮标识）
        for ad_btn_text in E.AD_CLOSE_IDENTIFIERS:
            ad_el = self.poco(ad_btn_text)
            if ad_el.exists():
                ad_el.click()
                logger.info(f"成功关闭广告弹框 (标识: {ad_btn_text})")
                time.sleep(1)
                break

    def _ios_active_bundle(self):
        """读取当前前台 App bundleId，失败返回空字符串。"""
        try:
            current = self.client.http.get("/wda/activeAppInfo", timeout=3).value
            if isinstance(current, dict):
                return current.get("bundleId") or ""
        except Exception:
            pass
        return ""

    @staticmethod
    def _ios_route_start_texts(root):
        """读取起点地图标记所属容器的名称，不能用终点或历史搜索文本证明起点。"""
        parents = {child: parent for parent in root.iter() for child in parent}
        texts = []
        for node in root.iter("XCUIElementTypeImage"):
            if node.get("visible") != "true" or (node.get("name") or node.get("label")) != "slm_icon_anno_start":
                continue
            parent = parents.get(node)
            if parent is not None:
                texts.extend((child.get("label") or child.get("name") or child.get("value") or "").strip()
                             for child in parent.iter("XCUIElementTypeStaticText") if child.get("visible") == "true")
        return texts

    def _ios_configure_addresses(self, tag, start_addr, end_addr):
        """依次搜索起点和终点；只处理地址，不启动App、不选择车型或付款。

        初次下单和登录后重选共用本方法。起点搜索抛错时不继续终点或后续步骤。
        """
        start_addr = self._ios_start_address(start_addr)
        logger.info(f"【{tag} 步骤 4】配置起点: {start_addr}")
        self._ios_search_address(is_start=True, address=start_addr)

        # 步骤 5：配置终点
        logger.info(f"【{tag} 步骤 5】配置终点: {end_addr}")
        self._ios_search_address(is_start=False, address=end_addr)
        for _ in range(30):
            root = ET.fromstring(self._ios_get_source_xml())
            if root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
                raise AssertionError("路线核验时乘客App已离开前台，未确认呼叫")
            actual_route = self._ios_estimate_route_identity(root)
            start_ok = actual_route is not None and (
                actual_route[0] in E.START_ADDRESS_NAMES
                or any(actual_route[0].startswith(prefix) for prefix in E.START_ROUTE_PREFIXES))
            if start_ok and self._ios_address_text_key(actual_route[1]) == self._ios_address_text_key(end_addr):
                self._ios_call_route_key = actual_route
                self._ios_retry_estimate_quote = None
                logger.info("【%s】实际起终点与请求一致，允许继续选择车型", tag)
                return
            time.sleep(0.5)
        self._ios_screenshot("JRYG_ios_route_address_mismatch.png")
        raise AssertionError("实际起终点未匹配请求，未选择车型或确认呼叫")

    @staticmethod
    def _ios_estimate_route_identity(root):
        """仅按起终点地图标记读取原路线，隐藏历史地址不参与重试核验。"""
        starts = iOSBase._ios_route_start_texts(root)
        parents = {child: parent for parent in root.iter() for child in parent}
        ends = []
        for node in root.iter("XCUIElementTypeImage"):
            if node.get("visible") != "true" or node.get("name") != "slm_icon_anno_end":
                continue
            parent = parents.get(node)
            if parent is not None:
                ends.extend((child.get("label") or child.get("name") or child.get("value") or "").strip()
                            for child in parent.iter("XCUIElementTypeStaticText") if child.get("visible") == "true")
        return (starts[0], ends[0]) if len(starts) == len(ends) == 1 and starts[0] and ends[0] else None

    @staticmethod
    def _ios_estimate_quote(root, car_type):
        """只有同一可见车型Cell与可用呼叫按钮就绪时才返回报价，不以隐藏收银台证明刷新。"""
        if root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
            return None
        visible = [node for node in root.iter() if node.get("visible") == "true"]
        texts = [(node.get("label") or node.get("name") or node.get("value") or "").strip() for node in visible]
        blocked = (*E.ESTIMATE_UPDATED_KEYWORDS, *E.CASHIER_PAGE_KEYWORDS,
                   *E.ORDER_SUCCESS_KEYWORDS, *E.ORDER_PROCESSING_KEYWORDS, *E.ORDER_FAIL_KEYWORDS)
        if any(keyword in text for text in texts for keyword in blocked) or any(node.tag == "XCUIElementTypeAlert" for node in visible):
            return None
        calls = [node for node in visible if node.tag == "XCUIElementTypeButton"
                 and (node.get("label") or node.get("name")) in ("確認呼叫", "确认呼叫")
                 and node.get("enabled") == "true"]
        if len(calls) != 1:
            return None
        label = E.CHARTER_CAR_LABEL if car_type == "charter" else E.METER_CAR_LABEL
        candidates = []
        for cell in root.iter("XCUIElementTypeCell"):
            if cell.get("visible") != "true" or cell.get("enabled") != "true":
                continue
            cell_texts = {(node.get("label") or node.get("name") or node.get("value") or "").strip()
                          for node in cell.iter("XCUIElementTypeStaticText") if node.get("visible") == "true"}
            if label not in cell_texts:
                continue
            if car_type == "charter":
                prices = [match.group(1) for text in cell_texts
                          for match in [re.fullmatch(r"包車價\s*([0-9]+(?:\.[0-9]{1,2})?)\s*HKD", text)] if match]
                if len(prices) != 1 or Decimal(prices[0]) <= 0:
                    continue
                quote = format(Decimal(prices[0]).normalize(), "f")
            else:
                if "打錶計價" not in cell_texts:
                    continue
                quote = "打錶計價"
            candidates.append(quote)
        route = iOSBase._ios_estimate_route_identity(root)
        return (route, candidates[0]) if route is not None and len(candidates) == 1 else None

    def _ios_reselect_refreshed_estimate(self, tag, car_type):
        """收到明确更新提示后，连续两次回读稳定报价，再精确重选同路线车型；不点击支付。"""
        original = getattr(self, "_ios_call_route_key", None)
        self._ios_retry_estimate_quote = None
        if original is None:
            raise AssertionError("缺少原路线凭据，禁止因预估更新重新呼叫")
        logger.info("【%s】预估已更新，等待报价刷新稳定，保留原起终点：%s", tag, original)
        previous = None
        deadline = time.monotonic() + E.ESTIMATE_REFRESH_TIMEOUT
        while time.monotonic() < deadline:
            root = ET.fromstring(self.client.source(format="xml"))
            if root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
                raise AssertionError("预估刷新时乘客App已离开前台，禁止重试呼叫")
            texts = [(node.get("label") or node.get("name") or node.get("value") or "")
                     for node in root.iter() if node.get("visible") == "true"]
            if any(keyword in text for text in texts for keyword in E.ORDER_FAIL_KEYWORDS):
                raise AssertionError("预估刷新时已出现订单或支付失败，禁止重试呼叫")
            if any(keyword in text for text in texts for keyword in E.CASHIER_PAGE_KEYWORDS):
                return "cashier"
            if any(keyword in text for text in texts for keyword in E.ORDER_SUCCESS_KEYWORDS):
                return "success"
            route = self._ios_estimate_route_identity(root)
            if route is not None and route != original:
                raise AssertionError(f"预估刷新后起终点已变化：{route}，禁止重试呼叫")
            quote = self._ios_estimate_quote(root, car_type)
            if quote is not None and quote == previous:
                label = E.CHARTER_CAR_LABEL if car_type == "charter" else E.METER_CAR_LABEL
                self._ios_click_estimate_car(car_type)
                time.sleep(1)
                current = self._ios_estimate_quote(ET.fromstring(self.client.source(format="xml")), car_type)
                if current == quote:
                    self._ios_retry_estimate_quote = quote
                    logger.info("【%s】已精确重选%s，原路线及新报价回读一致：%s；尚未呼叫", tag, label, quote[1])
                    return "ready"
                previous = None
            else:
                previous = quote
            time.sleep(1)
        self._ios_screenshot("JRYG_ios_estimate_refresh_timeout.png")
        raise AssertionError("预估刷新30秒内未稳定，未重试呼叫、未支付")

    def _ios_click_refreshed_estimate_call(self, tag, car_type):
        """再次核对刷新凭据后仅点击一次真实呼叫Button，不执行模糊或坐标兜底。"""
        expected = getattr(self, "_ios_retry_estimate_quote", None)
        current = self._ios_estimate_quote(ET.fromstring(self.client.source(format="xml")), car_type)
        if expected is None or current != expected or current[0] != self._ios_call_route_key:
            raise AssertionError("重试呼叫前路线或报价再次变化，停止，不重复提交")
        self._ios_retry_estimate_quote = None
        self._ios_click_estimate_call()
        logger.info("【%s】预估刷新后已单次重试呼叫，继续等待收银台或订单结果", tag)
        time.sleep(2)

    def _ios_click_estimate_car(self, car_type):
        label = E.CHARTER_CAR_LABEL if car_type == "charter" else E.METER_CAR_LABEL
        xpath = (f'//XCUIElementTypeCell[@visible="true" and @enabled="true"'
                 f' and .//XCUIElementTypeStaticText[@visible="true" and @label="{label}"]]')
        self.client(xpath=xpath).click()

    def _ios_click_estimate_call(self):
        self.client(xpath='//XCUIElementTypeButton[@visible="true" and @enabled="true" and (@label="確認呼叫" or @label="确认呼叫")]').click()

    def _ios_select_car_type(self, tag, car_type="charter"):
        """选择车型：charter=包車價的士, meter=打錶的士

        选择策略（依次降级）：
        1. WDA 精确 XPath 匹配
        2. Poco 模糊 textMatches 匹配
        3. WDA contains XPath 匹配
        4. 物理坐标兜底

        :param tag: 日志标签。
        :param car_type: 车型标识，"charter"=包車價的士 / "meter"=打錶的士。
        """
        # 根据车型选择对应的定位策略
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

        # 策略 1：WDA 精确 XPath 匹配
        car_el = self.client(xpath=xpath_exact)
        if car_el.exists:
            car_el.click()
            car_selected = True
            logger.info(f"  >> [WDA] 精确匹配并点击『{car_name}』")

        # 策略 2：Poco 模糊 textMatches 匹配
        if not car_selected:
            poco_car = self.poco(textMatches=poco_regex)
            if poco_car.exists():
                poco_car.click()
                car_selected = True
                logger.info(f"  >> [Poco] 模糊匹配并点击{car_name}")

        # 策略 3：WDA contains XPath 匹配
        if not car_selected:
            car_el = self.client(xpath=xpath_contains)
            if car_el.exists:
                car_el.click()
                car_selected = True
                logger.info(f"  >> [WDA] contains 匹配并点击{car_name}")

        # 策略 4：物理坐标兜底
        if not car_selected:
            logger.warning(f"  >> 未匹配到{car_name}，物理坐标点击...")
            self.client.click(*fallback_coord)
            time.sleep(1)

        time.sleep(1)

    def _ios_click_confirm_call(self, tag):
        """点击『確認呼叫』按钮（含 3 次重试机制）。

        尝试顺序：WDA XPath → Poco textMatches → 物理坐标兜底。
        每次尝试失败后等待 2 秒重试，最多 3 次。

        :param tag: 日志标签。
        """
        for attempt in range(3):
            # 先尝试 WDA XPath 匹配
            btn = self.client(xpath=E.CONFIRM_CALL_XPATH)
            if not btn.exists:
                # WDA 找不到则尝试 Poco textMatches
                poco_btn = self.poco(textMatches=E.CONFIRM_CALL_POCO_REGEX)
                if poco_btn.exists():
                    btn = poco_btn

            # 按钮存在则点击（WDA 和 Poco 的 exists 判断方式不同）
            if btn and (hasattr(btn, "exists") and btn.exists or not hasattr(btn, "exists")):
                try:
                    btn.click()
                    logger.info(f"  >> [{tag}] 已点击确认呼叫 (尝试 {attempt+1}/3)")
                    time.sleep(2)
                    return
                except Exception as e:
                    logger.warning(f"  >> [{tag}] 点击确认呼叫异常: {e}，重试...")
                    time.sleep(2)
            else:
                # 按钮未找到，物理坐标兜底
                logger.warning(f"  >> [{tag}] 未找到确认呼叫按钮，物理坐标点击 (尝试 {attempt+1}/3)")
                self.client.click(*E.CONFIRM_CALL_FALLBACK_COORD)
                time.sleep(5)
                return

        # 3 次重试均失败
        logger.error(f"  >> [{tag}] 确认呼叫按钮点击失败，已达最大重试次数")
        self._ios_screenshot(f"JRYG_ios_{tag}_confirm_call_failed.png")

    def _ios_click_confirm_pay(self, tag):
        """点击『確認支付並呼叫』按钮（包車價的士预付页面）。

        尝试顺序：WDA XPath → Poco textMatches → 物理坐标兜底。

        :param tag: 日志标签。
        """
        # 先尝试 WDA XPath 匹配
        btn = self.client(xpath=E.CONFIRM_PAY_XPATH)
        if not btn.exists:
            # WDA 找不到则尝试 Poco textMatches
            poco_btn = self.poco(textMatches=E.CONFIRM_PAY_POCO_REGEX)
            if poco_btn.exists():
                btn = poco_btn

        # 按钮存在则点击
        if btn and (hasattr(btn, "exists") and btn.exists or not hasattr(btn, "exists")):
            btn.click()
            logger.info(f"  >> [{tag}] 已点击确认支付并呼叫")
        else:
            # 物理坐标兜底
            self.client.click(*E.CONFIRM_PAY_FALLBACK_COORD)
            logger.info(f"  >> [{tag}] 物理坐标点击确认支付并呼叫")
        time.sleep(2)

    def _ios_fill_bank_card_form(self, tag):
        """填写银行卡信息并提交支付。

        点击"確認支付並呼叫"后，如果选择了信用卡/扣帳卡支付方式，
        会跳转到银行卡信息填写页面（WebView 表单），需要依次填写：
        卡号 → 月/年 → CVV碼 → 持卡人姓名 → 点击"請支付"按钮。

        :param tag: 日志标签。
        :return: True 表示已填写并提交，False 表示未检测到银行卡页面。
        """
        # 轮询等待银行卡页面加载（最多 15 秒）
        bank_page_found = False
        for wait_idx in range(15):
            page_texts = self._ios_get_all_texts(self.client)
            if any(kw in t for t in page_texts for kw in E.BANK_PAGE_KEYWORDS):
                bank_page_found = True
                logger.info(f"  >> [{tag}] 检测到银行卡填写页面 ({wait_idx+1}s)")
                break
            time.sleep(1)

        if not bank_page_found:
            logger.info(f"  >> [{tag}] 未检测到银行卡填写页面(15s)")
            return False

        self._ios_screenshot(f"JRYG_ios_{tag}_bank_form_before.png")
        time.sleep(2)

        # WebView 表单：只有当前聚焦的 TextField 可见，需逐个点击占位文字激活
        # 占位文案 → 要填入的值
        card_fields = [
            (["卡號", "卡号", "Card Number"], E.TEST_CARD_NUMBER, "卡号"),
            (["月 / 年", "月/年", "MM/YY", "Expiry", "有效期"], E.TEST_CARD_EXPIRY, "月/年"),
            (["CVV", "CVV 碼", "CVV码"], E.TEST_CARD_CVV, "CVV"),
            (["持卡人姓名", "Name"], E.TEST_CARD_HOLDER, "持卡人姓名"),
        ]

        for field_idx, (placeholders, value, label) in enumerate(card_fields):
            ensure_unlocked(self.client)
            filled = False
            # CVV/持卡人姓名：占位文字方式不可靠（StaticText 遮挡 TextField），直接用坐标
            use_placeholder = label not in ("CVV", "持卡人姓名")

            # 方式 1：点击占位文字对应的元素（StaticText 或 TextField）
            if use_placeholder:
                for ph in placeholders:
                    ensure_unlocked(self.client)
                    try:
                        el = self.client(
                            xpath=f'//*[contains(@label, "{ph}") or contains(@value, "{ph}")]')
                        if el.exists:
                            el.click()
                            time.sleep(0.5)
                            self.client.send_keys(value)
                            time.sleep(1)
                            logger.info(f"  >> [{tag}] 已填写{label} (placeholder={ph}，内容不记录)")
                            filled = True
                            break
                    except DeviceUnlockError:
                        raise
                    except Exception as e:
                        logger.warning(f"  >> [{tag}] 填写{label}(ph={ph})异常: {e}")

            # 方式 2：通过 WDA XML 获取 TextField 坐标直接点击
            if not filled:
                ensure_unlocked(self.client)
                try:
                    root = ET.fromstring(self.client.source(format="xml"))
                    target_tf = None
                    for node in root.iter():
                        if "TextField" not in node.tag:
                            continue
                        if node.get("visible", "true") == "false":
                            continue
                        val = node.get("value", "")
                        # 优先匹配占位文字（说明该字段未填写）
                        if any(ph in val for ph in placeholders):
                            x = int(node.get("x", "0"))
                            y = int(node.get("y", "0"))
                            w = int(node.get("width", "0"))
                            h = int(node.get("height", "0"))
                            target_tf = (x + w // 2, y + h // 2)
                            break
                    # 备选：按 y 排序取第 field_idx 个
                    if not target_tf:
                        visible_tfs = []
                        for node in root.iter():
                            if "TextField" not in node.tag:
                                continue
                            if node.get("visible", "true") == "false":
                                continue
                            x = int(node.get("x", "0"))
                            y = int(node.get("y", "0"))
                            w = int(node.get("width", "0"))
                            h = int(node.get("height", "0"))
                            visible_tfs.append((x + w // 2, y + h // 2))
                        visible_tfs.sort(key=lambda t: t[1])
                        if field_idx < len(visible_tfs):
                            target_tf = visible_tfs[field_idx]

                    if target_tf:
                        cx, cy = target_tf
                        self.client.click(cx, cy)
                        time.sleep(0.5)
                        self.client.send_keys(value)
                        time.sleep(1)
                        logger.info(f"  >> [{tag}] 坐标填写{label} ({cx},{cy}，内容不记录)")
                        filled = True
                except DeviceUnlockError:
                    raise
                except Exception as e:
                    logger.warning(f"  >> [{tag}] 坐标填写{label}异常: {e}")

            if not filled:
                raise RuntimeError(f"{tag}: {label}未填写，停止提交支付")

        self._ios_screenshot(f"JRYG_ios_{tag}_bank_form_filled.png")
        time.sleep(1)

        # 点击"請支付"按钮提交
        ensure_unlocked(self.client)
        logger.info(f"  >> [{tag}] 点击請支付按钮提交支付...")
        pay_btn = self.client(xpath=E.FINAL_PAY_XPATH)
        if not pay_btn.exists:
            poco_btn = self.poco(textMatches=E.FINAL_PAY_POCO_REGEX)
            if poco_btn.exists():
                pay_btn = poco_btn

        if pay_btn and (hasattr(pay_btn, "exists") and pay_btn.exists or not hasattr(pay_btn, "exists")):
            pay_btn.click()
            logger.info(f"  >> [{tag}] 已点击請支付按钮")
        else:
            self.client.click(*E.FINAL_PAY_FALLBACK_COORD)
            logger.info(f"  >> [{tag}] 物理坐标点击請支付")
        time.sleep(5)

        # 检测是否跳转到 3D Secure OTP 验证页
        self._ios_handle_otp_page(tag)
        return True

    def _ios_click_element_by_label(self, label_kw, class_name="XCUIElementTypeButton"):
        """通过元素 uuid 点击控件（WebView 内元素唯一可靠的方式）。

        WDA 坐标 tap（wda.Client.click → /wda/tap）对 WebView 内的
        DOM 元素无效，必须走 POST /wda/element/{uuid}/click。

        :param label_kw: 控件 label 关键词。
        :param class_name: 元素类型（Button/TextField/StaticText 等）。
        :return: True 表示点击成功。
        """
        try:
            for el in self.client(className=class_name).find_elements():
                try:
                    if label_kw in (el.label or ""):
                        el.click()
                        return True
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"  >> element 点击({label_kw}) 异常: {e}")
        return False

    @staticmethod
    def _ios_otp_form(root):
        """限定沙箱OTP标题所属表单及唯一可输入框，返回精确控件XPath。"""
        if root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
            raise RuntimeError("OTP核验时乘客App不在前台，禁止输入或提交")
        visible = [node for node in root.iter() if node.get("visible") == "true"]
        if any(node.tag == "XCUIElementTypeAlert" for node in visible):
            raise RuntimeError("OTP页面存在弹窗，禁止输入或提交")
        fields = [node for node in visible
                  if node.tag in ("XCUIElementTypeTextField", "XCUIElementTypeSecureTextField")]
        placeholder = "e.g. 123456"
        if (len(fields) != 1 or fields[0].tag != "XCUIElementTypeTextField"
                or fields[0].get("enabled") != "true"
                or fields[0].get("placeholderValue") != placeholder):
            raise RuntimeError("OTP输入框缺失、不唯一、不可输入或标识不符，禁止提交")
        parents = {child: parent for parent in root.iter() for child in parent}
        parent = parents.get(fields[0])
        if parent is None or parent.tag != "XCUIElementTypeOther":
            raise RuntimeError("OTP输入框不在已确认表单内，禁止提交")
        texts = {(node.get("label") or node.get("name") or "") for node in parent.iter()
                 if node.tag == "XCUIElementTypeStaticText"}
        buttons = [node for node in parent if node.tag == "XCUIElementTypeButton"
                   and node.get("visible") == "true" and node.get("label") == "Verify & Proceed"]
        if not {"Sandbox Test Page", "One-Time Password (OTP)"}.issubset(texts) or len(buttons) != 1:
            raise RuntimeError("OTP沙箱标题或同表单验证按钮不符，禁止提交")
        form_xpath = ('//XCUIElementTypeOther[.//XCUIElementTypeStaticText[@label="Sandbox Test Page"]'
                      ' and .//XCUIElementTypeStaticText[@label="One-Time Password (OTP)"]'
                      ' and ./XCUIElementTypeTextField[@visible="true" and @enabled="true" and @placeholderValue="e.g. 123456"]]')
        field_xpath = form_xpath + '/XCUIElementTypeTextField[@visible="true" and @enabled="true" and @placeholderValue="e.g. 123456"]'
        verify_xpath = form_xpath + '/XCUIElementTypeButton[@visible="true" and @enabled="true" and @label="Verify & Proceed"]'
        return field_xpath, verify_xpath, placeholder

    @staticmethod
    def _ios_otp_value_confirmed(value, expected, placeholder):
        """仅精确实际值算确认；空值、占位符、掩码或长度相同均不能证明输入成功。"""
        return (isinstance(value, str) and isinstance(expected, str) and bool(expected)
                and value not in ("", placeholder) and expected != placeholder and value == expected)

    def _ios_wait_otp_value(self, field, expected, tag, *, clearing=False):
        """仅回读同一元素，最多5秒，不重发输入；异常及日志均不包含验证码。"""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                _, _, placeholder = self._ios_otp_form(ET.fromstring(self.client.source(format="xml")))
                if not field.displayed or not field.enabled:
                    raise RuntimeError("OTP目标输入框已不可用")
                value = field.value
            except Exception:
                raise RuntimeError(f"{tag}: OTP目标控件或回读异常，停止，不提交验证") from None
            if clearing:
                if value in ("", placeholder):
                    return
            elif self._ios_otp_value_confirmed(value, expected, placeholder):
                return
            time.sleep(0.5)
        action = "清空" if clearing else "输入"
        raise RuntimeError(f"{tag}: OTP{action}未通过回读核验，停止，不提交验证")

    @staticmethod
    def _ios_otp_readiness(root):
        """加载中表单返回None；离开乘客App、系统弹窗或明确支付失败立即阻断。"""
        if root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
            raise RuntimeError("等待OTP时乘客App不在前台，停止，不输入或提交")
        visible = [node for node in root.iter() if node.get("visible") == "true"]
        if any(node.tag == "XCUIElementTypeAlert" for node in visible):
            raise RuntimeError("等待OTP时存在系统弹窗，停止，不输入或提交")
        texts = [(node.get("label") or node.get("name") or "") for node in visible
                 if node.tag in ("XCUIElementTypeStaticText", "XCUIElementTypeTextView")]
        failures = ("Payment Failed", "Authentication Failed", "Incorrect OTP", "支付失敗", "支付失败", "驗證失敗", "验证失败")
        if any(keyword in text for text in texts for keyword in failures):
            raise RuntimeError("等待OTP时出现支付或验证失败，停止，不输入或提交")
        try:
            return iOSBase._ios_otp_form(root)
        except RuntimeError:
            return None

    @staticmethod
    def _ios_otp_loading_reason(root):
        visible = [node for node in root.iter() if node.get("visible") == "true"]
        texts = {(node.get("label") or node.get("name") or "") for node in visible
                 if node.tag in ("XCUIElementTypeStaticText", "XCUIElementTypeTextView")}
        has_field = any(node.tag in ("XCUIElementTypeTextField", "XCUIElementTypeSecureTextField")
                        for node in visible)
        if (texts & {"安全結帳", "安全结账"} and not has_field
                and not texts & {"Sandbox Test Page", "One-Time Password (OTP)"}):
            return "安全結帳内容未加载（未出现OTP标题或输入框）"
        if not has_field:
            return "OTP输入框未出现"
        return "OTP表单标识、输入框唯一性或可用性未通过核验"

    def _ios_wait_otp_ready(self, tag, wait_seconds=90):
        """只读等待同表单唯一可用OTP元素；白屏不点击、刷新或重付。"""
        if not isinstance(wait_seconds, (int, float)) or not 0 < wait_seconds <= 180:
            raise ValueError("OTP只读等待时限必须在0到180秒之间")
        deadline = time.monotonic() + wait_seconds
        next_log = time.monotonic()
        reason = "尚未取得支付页面"
        logger.info("【%s】等待OTP表单及输入框就绪，最多%s秒，期间不输入或提交", tag, wait_seconds)
        while time.monotonic() < deadline:
            ensure_unlocked(self.client, deadline=deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                xml = self.client.http.get("/source?format=xml", timeout=min(5, remaining)).value
                root = ET.fromstring(xml)
            except ET.ParseError:
                root = None
                reason = "支付页面控件树尚不完整"
            except Exception as exc:
                root = None
                reason = f"WDA页面读取失败（{type(exc).__name__}）"
            if root is not None:
                remember_foreground(self.client, root)
                form = self._ios_otp_readiness(root)
                reason = self._ios_otp_loading_reason(root)
                if form is not None and time.monotonic() < deadline:
                    field_xpath, verify_xpath, placeholder = form
                    try:
                        fields = self.client(xpath=field_xpath).find_elements()
                        ready = len(fields) == 1 and fields[0].displayed and fields[0].enabled
                    except Exception:
                        ready = False
                        reason = "WDA目标OTP元素读取失败"
                    else:
                        reason = "WDA目标OTP元素尚不唯一、可见或启用"
                    if ready and time.monotonic() < deadline:
                        return fields[0], verify_xpath, placeholder
            if time.monotonic() >= next_log:
                logger.info("【%s】%s；仅等待，剩余%.0f秒", tag, reason, max(0, deadline - time.monotonic()))
                next_log = time.monotonic() + 5
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        raise TimeoutError(
            f"{tag}: {reason}，{wait_seconds}秒内OTP未就绪；未清空、输入或提交验证。"
            "支付请求已发出但结果未确认，请先核对当前交易状态，不要直接重付")

    def _ios_handle_otp_page(self, tag):
        """有界等待沙箱OTP框就绪，元素级清空输入并回读确认后，仅提交一次验证。"""
        field, verify_xpath, placeholder = self._ios_wait_otp_ready(tag)
        otp_code = E.OTP_DEFAULT_CODE
        if not isinstance(otp_code, str) or not otp_code.strip() or otp_code == placeholder:
            raise RuntimeError(f"{tag}: OTP配置无效，未输入或提交")
        try:
            field.tap()
            self._ios_otp_form(ET.fromstring(self.client.source(format="xml")))
        except Exception:
            raise RuntimeError(f"{tag}: OTP就绪后聚焦或表单核验失败，未提交验证") from None
        logger.info("【%s】OTP目标输入框唯一且可用，使用同一元素输入", tag)
        try:
            field.clear_text()
        except Exception:
            raise RuntimeError(f"{tag}: OTP元素清空失败，未输入或提交验证") from None
        self._ios_wait_otp_value(field, None, tag, clearing=True)
        logger.info("【%s】OTP清空回读通过（内容不记录）", tag)
        try:
            field.set_text(otp_code)
        except Exception:
            raise RuntimeError(f"{tag}: OTP元素输入响应异常，停止，不重复输入或提交") from None
        self._ios_wait_otp_value(field, otp_code, tag)
        logger.info("【%s】OTP实际值回读一致，输入核验通过（内容不记录）", tag)
        try:
            self._ios_otp_form(ET.fromstring(self.client.source(format="xml")))
            buttons = self.client(xpath=verify_xpath).find_elements()
            if (len(buttons) != 1 or not buttons[0].displayed or not buttons[0].enabled
                    or not field.displayed or not field.enabled
                    or not self._ios_otp_value_confirmed(field.value, otp_code, placeholder)):
                raise RuntimeError("OTP输入再次变化或验证按钮不可用")
        except Exception:
            raise RuntimeError(f"{tag}: OTP提交前核验失败，停止，不提交验证") from None
        try:
            buttons[0].tap()
        except Exception:
            raise RuntimeError(f"{tag}: 验证点击已发出但响应未确认，停止，不重复提交") from None
        logger.info("【%s】OTP提交前核验通过，已单次点击Verify & Proceed", tag)

        time.sleep(5)

        # ---- 步骤 6：等待 3DS 弹层关闭（成功页或返回 App） ----
        logger.info(f"  >> [{tag}] 等待 3DS 验证结果...")
        otp_done = False
        for i in range(15):
            try:
                current = ET.fromstring(self.client.source(format="xml"))
                cur_texts = [(node.get("label") or node.get("name") or "")
                             for node in current.iter() if node.get("visible") == "true"
                             and node.tag in ("XCUIElementTypeStaticText", "XCUIElementTypeButton", "XCUIElementTypeTextView")]
            except Exception:
                logger.warning("【%s】3DS结果页面暂不可读取，仅等待，不重复提交", tag)
                time.sleep(2)
                continue
            if not any(cur_texts):
                time.sleep(2)
                continue
            if current.get("bundleId") not in (E.PASSENGER_BUNDLE_ID, "com.apple.mobilesafari"):
                raise RuntimeError(f"{tag}: 3DS结果核验时已离开支付App，停止，不重复提交")
            if any(kw in t for t in cur_texts for kw in ("Payment Failed", "Authentication Failed", "Incorrect OTP", "支付失敗", "支付失败", "驗證失敗", "验证失败")):
                raise RuntimeError(f"{tag}: 3DS支付验证失败")
            if any(kw in t for t in cur_texts for kw in E.OTP_SUCCESS_KEYWORDS):
                logger.info(f"  >> [{tag}] 3DS 验证成功")
                otp_done = True
                break
            # 已离开 OTP 弹层（回到 App 支付结果页或首页）
            if not any(kw in t for t in cur_texts for kw in E.OTP_PAGE_KEYWORDS):
                logger.info(f"  >> [{tag}] 3DS 弹层已关闭")
                otp_done = True
                break
            time.sleep(2)

        if not otp_done:
            self._ios_screenshot(f"JRYG_ios_{tag}_otp_failed.png")
            raise TimeoutError(f"{tag}: 3DS弹层未关闭，停止后续流程")

        # ---- 步骤 7：处理"打開/打开"弹窗返回 App ----
        if otp_done:
            time.sleep(2)
            cur_texts = self._ios_get_all_texts(self.client)
            if any(kw in t for t in cur_texts for kw in E.OTP_RETURN_APP_KEYWORDS):
                open_btn = self.client(text="打開")
                if not open_btn.exists:
                    open_btn = self.client(text="打开")
                if open_btn.exists:
                    open_btn.click()
                    logger.info(f"  >> [{tag}] 已点击'打開'返回 App")
                    time.sleep(5)

        # 此处仅完成3DS输入、提交及页面退出；到账由司机同订单详情最终核验。
        # 不重复等待/点击 Verify，避免把同一次付款重提。
        logger.info(f"  >> [{tag}] 3DS步骤已结束，待司机同订单支付状态核验")

    def _ios_wait_payment_state(self, tag, description, predicate):
        """在原页面等待支付控件就绪，超时保存XML及截图，不重发业务动作。"""
        monitor = self._ios_ensure_monitor()
        deadline = time.monotonic() + E.ROUTE_PAYMENT_WAIT_TIMEOUT
        while time.monotonic() < deadline:
            page = monitor.inspect(timeout=max(0.1, deadline - time.monotonic()))
            if page.root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
                monitor.capture("payment_app_not_foreground")
                raise RuntimeError(f"{tag}: 乘客App不在前台，停止支付方式操作")
            if predicate(page):
                return page
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        monitor.capture(f"payment_{description}_timeout")
        raise AssertionError(f"{tag}: {description}未就绪，未继续呼叫或支付")

    def _ios_click_payment_text(self, page, labels):
        """只点击可见可用的完整选项文案，不将渠道说明文字当作选项。"""
        for node in page.nodes:
            if node.tag not in ("XCUIElementTypeButton", "XCUIElementTypeStaticText", "XCUIElementTypeCell"):
                continue
            if node.get("enabled", "true") == "false":
                continue
            for attr in ("label", "name", "value"):
                text = node.get(attr)
                if text not in labels:
                    continue
                xpath = (f'(//{node.tag}[@visible="true" and @enabled!="false"'
                         f' and @{attr}="{text}"])[1]')
                self.client(xpath=xpath).click()
                return True
        return False

    def _ios_select_meter_payment(self, tag, payment):
        """打表原顺序：打开支付方式面板、选指定方式、确认选择、回到路线页。"""
        def panel_ready(page):
            return page.has(*E.ROUTE_PAYMENT_PANEL_TITLES) and page.has(*E.ROUTE_PAYMENT_CONFIRM_TEXTS)

        page = self._ios_wait_payment_state(
            tag, "打表支付入口",
            lambda item: panel_ready(item) or any(
                text.startswith(E.ROUTE_PAYMENT_ENTRY_TEXTS) for text in item.texts))
        if not panel_ready(page):
            service = self.client(xpath=E.ROUTE_PAYMENT_ENTRY_XPATH)
            if service.exists:
                service.click()
            else:
                service = self.poco(textMatches=E.ROUTE_PAYMENT_ENTRY_POCO_REGEX)
                if not service.exists():
                    self._ios_ensure_monitor().capture("meter_payment_entry_missing")
                    raise AssertionError(f"{tag}: 未找到可点击的支付方式入口，支付面板未打开")
                service.click()
            logger.info("【%s】已点击支付方式入口，等待选择面板，不重复点击", tag)
            page = self._ios_wait_payment_state(tag, "支付方式面板", panel_ready)

        labels = {
            "cash": (*E.CASH_KEYWORDS, "現金支付", "现金支付"),
            "epayment": E.EPAYMENT_KEYWORDS,
            "alipay": E.ALIPAY_KEYWORDS,
            "bankcard": (*E.BANKCARD_KEYWORDS, "信用卡或扣帳卡", "信用卡/扣帳卡"),
        }.get(payment, (payment,))
        selected = self._ios_click_payment_text(page, labels)
        if not selected and payment in ("alipay", "bankcard") and not any(text in labels for text in page.texts):
            for cell in page.root.iter("XCUIElementTypeCell"):
                if cell not in page.nodes or cell.get("enabled", "true") == "false":
                    continue
                texts = {node.get(attr, "").strip() for node in cell.iter()
                         if node in page.nodes and node.get("enabled", "true") != "false"
                         for attr in ("label", "name", "value")}
                supports_channel = any(
                    text.startswith(("支持", "支援", "Supports", "supports"))
                    and not any(word in text for word in ("不支持", "不支援"))
                    and any(label in text for label in labels) for text in texts)
                if not texts.intersection(E.EPAYMENT_KEYWORDS) or not supports_channel:
                    continue
                group_page = type(page)(ET.tostring(cell, encoding="unicode"))
                selected = self._ios_click_payment_text(group_page, E.EPAYMENT_KEYWORDS)
                if selected:
                    labels = E.EPAYMENT_KEYWORDS
                    logger.info("【%s】下单面板按電子支付分组，已确认支持%s；最终渠道仍为%s，行程结束后选择并支付",
                                tag, payment, payment)
                    break
        if not selected:
            self._ios_ensure_monitor().capture(f"meter_payment_{payment}_option_missing")
            raise AssertionError(
                f"{tag}: 支付面板无可用支付选项({payment})或支持该渠道的電子支付分组；"
                f"可见文案={page.texts}；未呼叫，不更换最终支付渠道")
        page = self._ios_wait_payment_state(tag, "支付方式确认按钮", panel_ready)
        if not self._ios_click_payment_text(page, E.ROUTE_PAYMENT_CONFIRM_TEXTS):
            self._ios_ensure_monitor().capture("meter_payment_confirm_missing")
            raise AssertionError(f"{tag}: 支付方式确认按钮不可用，未呼叫")
        self._ios_wait_payment_state(
            tag, "支付选择后返回路线页",
            lambda item: not item.has(*E.ROUTE_PAYMENT_PANEL_TITLES)
            and item.has("確認呼叫", "确认呼叫")
            and any(text.startswith(E.ROUTE_PAYMENT_ENTRY_TEXTS)
                    and ("已選擇" in text or "已选择" in text)
                    and any(label in text for label in labels) for text in item.texts))
        logger.info("【%s】打表支付方式已选择并回读，后续仍按原流程呼叫及行程结束后支付", tag)

    def _ios_select_payment(self, tag, payment="cash"):
        """选择支付方式。

        打表兼容"支付方式"/"可選服務"入口，优先直选渠道，也支持明确包含该渠道的電子支付分组。
        包车保持预付收银台直接选择渠道；这里不呼叫、不执行渠道付款。

        车型与支付方式选择时机：
        - 打錶的士：选车型 → 选支付方式（面板）→ 確認選擇 → 確認呼叫
        - 包車價的士：选车型 → 確認呼叫 → 预付页面选支付方式 → 確認支付並呼叫

        :param tag: 日志标签。
        :param payment: 支付方式标识（cash/epayment/alipay/bankcard）。
        :raises AssertionError: 未找到支付方式选项时抛出。
        """
        if getattr(self, "CAR_TYPE", "") == "meter":
            return self._ios_select_meter_payment(tag, payment)
        keywords_map = {
            "cash": E.CASH_KEYWORDS,
            "epayment": E.EPAYMENT_KEYWORDS,
            "alipay": E.ALIPAY_KEYWORDS,
            "bankcard": E.BANKCARD_KEYWORDS,
        }
        keywords = keywords_map.get(payment, [payment])

        # ---- 步骤 1：点击"可選服務"区域，弹出支付方式选择面板 ----
        logger.info(f"  >> [{tag}] 点击'可選服務'区域，弹出支付方式选择面板...")
        panel_opened = False
        service_el = self.client(
            xpath='//*[contains(@label,"可選服務") or contains(@value,"可選服務")]')
        if service_el.exists:
            service_el.click()
            panel_opened = True
            time.sleep(1)
            logger.info(f"  >> [{tag}] 已点击'可選服務'区域，等待面板弹出")
        else:
            service_poco = self.poco(textMatches=".*可選服務.*")
            if service_poco.exists():
                service_poco.click()
                panel_opened = True
                time.sleep(1)
                logger.info(f"  >> [{tag}] Poco 点击'可選服務'区域")

        if not panel_opened:
            logger.warning(f"  >> [{tag}] 未找到'可選服務'区域，尝试直接选择支付方式")

        # ---- 步骤 2：在面板中选择目标支付方式（如已默认选中则跳过） ----
        # 检测是否已默认选中目标支付方式（页面有"已選擇"+目标关键词的提示文案）
        already_selected = False
        page_texts = self._ios_get_all_texts(self.client)
        for kw in keywords:
            for t in page_texts:
                if ("已選擇" in t or "已选择" in t) and kw in t:
                    already_selected = True
                    logger.info(f"  >> [{tag}] 支付方式『{kw}』已默认选中，跳过选择")
                    break
            if already_selected:
                break

        if not already_selected:
            for kw in keywords:
                pay_el = self.client(
                    xpath=f'//*[contains(@label,"{kw}") or contains(@value,"{kw}")]')
                if pay_el.exists:
                    pay_el.click()
                    logger.info(f"  >> [WDA] 面板中选择支付方式『{kw}』")
                    time.sleep(1)
                    break
            else:
                poco_regex = ".*" + ".*|.*".join(keywords) + ".*"
                poco_pay = self.poco(textMatches=poco_regex)
                if poco_pay.exists():
                    poco_pay.click()
                    logger.info(f"  >> [Poco] 面板中选择支付方式")
                    time.sleep(1)
                else:
                    self._ios_screenshot(f"JRYG_ios_{tag}_payment_notfound.png")
                    raise AssertionError(f"未匹配到支付方式({payment})，面板无对应选项")

        # ---- 步骤 3：点击"確認選擇"按钮，回到路线页 ----
        logger.info(f"  >> [{tag}] 点击'確認選擇'按钮...")
        confirm_clicked = False
        confirm_btn = self.client(textMatches="確認選擇|确认选择")
        if confirm_btn.exists:
            confirm_btn.click()
            confirm_clicked = True
            logger.info(f"  >> [{tag}] 已点击'確認選擇'按钮")
            time.sleep(2)
        else:
            confirm_poco = self.poco(textMatches=".*確認選擇.*|.*确认选择.*")
            if confirm_poco.exists():
                confirm_poco.click()
                confirm_clicked = True
                logger.info(f"  >> [{tag}] Poco 点击'確認選擇'按钮")
                time.sleep(2)

        if not confirm_clicked:
            logger.info(f"  >> [{tag}] 未找到'確認選擇'按钮（可能无需确认，已回到路线页）")

        time.sleep(2)

    def _ios_wait_order_result(self, tag, max_checks=15):
        """轮询等待下单结果。

        :return: "success"=下单成功, "too_close"=距离太近需切换终点,
                 "cashier"=已进入收银台, "estimate_updated"=预估更新需同路线重选,
                 "fail"=下单失败, "timeout"=超时无结果。
        """
        logger.info(f"  >> [{tag}] 等待下单结果...")
        result = "timeout"
        for wait_sec in range(max_checks):
            time.sleep(1)
            page_texts = self._ios_get_all_texts(self.client)
            logger.info(f"  [{tag} {wait_sec}s] 页面文本: {page_texts[:200]}")

            if any(kw in t for t in page_texts for kw in E.ORDER_FAIL_KEYWORDS):
                logger.warning(f"  [{tag} {wait_sec*2}s] 下单失败")
                result = "fail"
                break

            if any(kw in text for text in page_texts for kw in E.CASHIER_PAGE_KEYWORDS):
                logger.info("【%s】已进入收银台，不再重试确认呼叫", tag)
                return "cashier"
            if any(kw in t for t in page_texts for kw in E.ORDER_SUCCESS_KEYWORDS):
                logger.info(f"  [{tag} {wait_sec*2}s] 【下单成功】")
                result = "success"
                break
            if any(kw in text for text in page_texts for kw in E.ESTIMATE_UPDATED_KEYWORDS):
                logger.warning("【%s】检测到预估更新提示，返回同路线重选流程", tag)
                return "estimate_updated"

            # 检测"未完成訂單"弹窗 → 返回让调用方处理
            if any(("未完成" in t and ("訂單" in t or "订单" in t))
                   for t in page_texts):
                logger.warning(f"  [{tag} {wait_sec*2}s] 检测到'未完成訂單'弹窗")
                result = "ongoing_order"
                break

            # 检测包車價的士温馨提示页，点击"我知道了，準備出發"
            if any(kw in t for t in page_texts for kw in ["溫馨提示", "温馨提示", "我知道了", "準備出發", "准备出发"]):
                logger.info(f"  [{tag} {wait_sec*2}s] 检测到温馨提示页，点击确认...")
                for btn_kw in ["我知道了", "準備出發", "准备出发", "我知道"]:
                    btn = self.client(textContains=btn_kw)
                    if btn.exists:
                        btn.click()
                        logger.info(f"  >> 已点击'{btn_kw}'")
                        time.sleep(1)
                        break
                continue  # 继续等待下单成功

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
        """通过坐标聚焦并填写银行卡表单字段。

        WebView 表单中只有当前聚焦的 TextField 可见，
        需通过坐标点击激活后再输入文本，输入完成后关闭键盘。

        :param field_index: 字段索引（0=卡号, 1=月/年, 2=CVV, 3=持卡人姓名）。
        :param text: 要输入的文本值。
        :param label: 字段标签（用于日志）。
        :raises AssertionError: 指定索引的 TextField 不存在时抛出。
        """
        # 获取当前页面所有 TextField
        fields = self._ios_get_textfields()
        if field_index >= len(fields):
            raise AssertionError(f"未找到第{field_index + 1}个TextField（{label}），当前仅有{len(fields)}个字段")

        # 点击 TextField 中心坐标聚焦
        cx, cy = fields[field_index]["cx"], fields[field_index]["cy"]
        self.client.click(cx, cy)
        time.sleep(1.5)
        # 输入文本
        self.client.send_keys(text)
        time.sleep(1.5)

        # 验证输入是否成功（重新获取 TextField 列表检查值）
        fields_after = self._ios_get_textfields()
        if field_index < len(fields_after):
            actual = fields_after[field_index]["value"]
            logger.info(f"  >> {label}输入完成: '{actual}'")

        # 输入完成后关闭键盘
        self._ios_dismiss_keyboard()
