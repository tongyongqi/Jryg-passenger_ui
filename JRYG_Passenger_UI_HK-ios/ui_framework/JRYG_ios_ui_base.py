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

import os
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


class iOSBase(HKIOSPaymentMixin):
    """iOS 自动化测试公共基类，提供设备连接与通用操作封装"""

    @classmethod
    def setup_class(cls):
        """连接WDA后初始化Poco；设备依赖仅在执行阶段加载，不干扰pytest收集。

        Poco内置旧six导入器不支持find_spec，不能在pytest加载conftest前注册。
        Airtest也只在此处加载，避免离线导入或仅收集时探测设备依赖。
        """
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

        from airtest.core.api import connect_device
        from poco.drivers.ios import iosPoco

        connect_device(f"ios:///{cls.wda_url}")
        cls.poco = iosPoco()
        logger.info("【iOS 自动化】Poco 控件树驱动加载完成，已准备就绪。")

    @classmethod
    def teardown_class(cls):
        """类级清理：释放设备连接与相关资源。

        :return: None。"""
        logger.info("【iOS 自动化】测试执行结束，正在安全释放连接通道。")

    # ==================== 通用操作 ====================

    def _ios_get_source_xml(self):
        """从当前乘客WDA客户端获取页面XML，不固定8100端口。

        用于需要按元素属性（label/name/rect）精确定位并自行计算坐标的场景
        （例如 Safari WebView 内的元素必须坐标点击，element uuid 点击无效）。

        :return: XML 字符串，失败返回空字符串。
        """
        try:
            return self.client.source(format="xml") or ""
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
        try:
            return list(IOSPage(client.source(format="xml")).texts)
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

        使用状态机方式：每轮检测当前页面状态，根据状态执行对应操作，确保：
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

    # 取消订单确认弹框的关键词（简繁体）
    CANCEL_CONFIRM_KEYWORDS = ["不用車了", "不用车了", "確認取消", "确认取消", "確定", "确定", "好"]

    def _ios_select_search_result(self, is_start, address, target_text, tag=""):
        """通用地址搜索结果选择：文本匹配 → 父Cell → 第一个Cell → 坐标 → 验证跳转。

        从搜索结果列表中选中地址并验证页面跳转：
        - 起点：选中后验证返回首页（检测"想去哪裡"等关键词）
        - 终点：选中后验证进入路线选择页（检测"確認呼叫"/"打錶"等关键词）

        选择策略（依次尝试）：
        1. 点击包含关键词的 StaticText 的父 Cell（最稳定）
        2. 直接点击包含关键词的 StaticText
        3. 点击第一个 Cell（带重试，避免 stale element）
        4. 物理坐标兜底

        :param is_start: True=起点, False=终点。
        :param address: 原始地址文本。
        :param target_text: 去除"地铁站/地鐵站"后的简体地址。
        :param tag: 日志标签。
        :raises AssertionError: 选中后 10s 内未离开搜索页。
        """
        client = self.client
        addr_type = "起点" if is_start else "终点"

        # 简繁体关键词列表
        search_kws = [target_text, address.replace("地铁站", "地鐵站").replace("地铁", "地鐵")]
        found = False

        for kw in search_kws:
            try:
                # 策略 1：点击包含关键词的 StaticText 的父 Cell
                parent_cell = client(
                    xpath=f'//XCUIElementTypeCell[.//XCUIElementTypeStaticText'
                          f'[contains(@label,"{kw}") or contains(@value,"{kw}")]]')
                if parent_cell.exists:
                    parent_cell.click()
                    found = True
                    logger.info(f"  >> 文本匹配选中{addr_type}（父Cell）: {address} (kw={kw})")
                    break
                # 策略 2：直接点击 StaticText
                result = client(
                    xpath=f'//XCUIElementTypeStaticText[contains(@label,"{kw}") or contains(@value,"{kw}")]')
                if result.exists:
                    result.tap()
                    found = True
                    logger.info(f"  >> 文本匹配选中{addr_type}: {address} (kw={kw})")
                    break
            except Exception as e:
                logger.warning(f"  >> 文本匹配『{kw}』异常: {e}")

        # 文本匹配点击后验证是否跳转，未跳转则尝试其他方式
        if found:
            time.sleep(2)
            if not client(type="TextField").exists:
                logger.info(f"  >> {addr_type}文本匹配点击后已离开搜索页")
            else:
                logger.info(f"  >> {addr_type}文本匹配点击后仍在搜索页，尝试 Cell 方式")
                found = False

        # 策略 3：点击第一个 Cell（带重试，避免 stale element）
        if not found:
            for retry in range(3):
                try:
                    first_cell = client(xpath="(//XCUIElementTypeCell)[1]")
                    if first_cell.exists:
                        first_cell.click()
                        found = True
                        logger.info(f"  >> 选中{addr_type}第一个 Cell (重试 {retry+1}/3)")
                        break
                except Exception as e:
                    logger.warning(f"  >> 点击 Cell 异常 (重试 {retry+1}/3): {e}")
                    time.sleep(1)

        # 策略 4：物理坐标兜底
        if not found:
            client.click(*E.SEARCH_FIRST_RESULT_COORD)
            logger.info(f"  >> 物理坐标选中{addr_type}")

        # ---- 验证页面已跳转离开搜索页 ----
        jump_ok = False
        for wait_idx in range(10):
            time.sleep(1)
            if not client(type="TextField").exists:
                jump_ok = True
                logger.info(f"  >> {addr_type}选中后已离开搜索页 ({wait_idx+1}s)")
                break

        if not jump_ok:
            self._ios_screenshot(f"JRYG_ios_search_{addr_type}_jump_fail.png")
            page_texts = self._ios_get_all_texts(client)
            logger.error(f"  >> {addr_type}选中后未跳转，仍在搜索页，页面文本: {page_texts[:150]}")
            raise AssertionError(f"{addr_type}选中后未离开搜索页(10s)")

        # 起点验证返回首页；终点验证进入路线选择页
        if is_start:
            home_keywords = ["想去哪裡", "想去哪里", "目的地", "起點", "起点"]
            home_ok = False
            for wait_idx in range(10):
                time.sleep(1)
                page_texts = self._ios_get_all_texts(client)
                if any(kw in t for t in page_texts for kw in home_keywords):
                    home_ok = True
                    logger.info(f"  >> 起点设置完成，已返回首页 ({wait_idx+1}s)")
                    break
            if not home_ok:
                self._ios_screenshot("JRYG_ios_search_start_not_home.png")
                logger.warning(f"  >> 起点选中后未检测到首页关键词，页面文本: {page_texts[:150]}")
        else:
            route_keywords = ["確認呼叫", "确认呼叫", "包車價", "打錶", "可選服務"]
            route_ok = False
            for wait_idx in range(10):
                time.sleep(1)
                page_texts = self._ios_get_all_texts(client)
                if any(kw in t for t in page_texts for kw in route_keywords):
                    route_ok = True
                    logger.info(f"  >> 终点设置完成，已进入路线选择页 ({wait_idx+1}s)")
                    break
            if not route_ok:
                self._ios_screenshot("JRYG_ios_search_end_not_route.png")
                logger.warning(f"  >> 终点选中后未检测到路线页关键词，页面文本: {page_texts[:150]}")

        time.sleep(2)

    def _ios_search_address(self, is_start=True, address=""):
        """通用地址搜索：点击入口 → 输入地址 → 等待搜索结果出现 → 选择结果 → 验证页面跳转

        - 起点：选中后验证返回首页（检测"想去哪裡"等首页关键词）
        - 终点：选中后验证进入路线选择页（检测车型选择或"確認呼叫"）

        :raises AssertionError: 未能进入搜索页、搜索结果未出现、未能选中地址、
                                 或选中后未正确跳转时抛出。
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

        # ---- 步骤 A：进入搜索页 ----
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
            self._ios_screenshot(f"JRYG_ios_search_{addr_type}_enter_fail.png")
            raise AssertionError(f"未能进入{addr_type}搜索页")

        # ---- 步骤 B：检查历史记录（直接命中免输入） ----
        target_text = address.replace("地鐵站", "").replace("地铁站", "").strip()
        hist_el = client(xpath=f'//XCUIElementTypeStaticText[@label="{address}" or @value="{address}"]')
        if not hist_el.exists and target_text != address:
            hist_el = client(xpath=f'//XCUIElementTypeStaticText[@label="{target_text}" or @value="{target_text}"]')
        if hist_el.exists:
            hist_el.tap()
            logger.info(f"  >> 从历史记录选中{addr_type}: {address}")
            # 历史记录选中后验证页面已跳转（搜索输入框消失）
            addr_label = "起点" if is_start else "终点"
            for wait_idx in range(10):
                time.sleep(1)
                if not client(type="TextField").exists:
                    logger.info(f"  >> {addr_label}历史记录选中后已离开搜索页 ({wait_idx+1}s)")
                    break
            else:
                self._ios_screenshot(f"JRYG_ios_search_{addr_label}_hist_jump_fail.png")
                raise AssertionError(f"{addr_label}历史记录选中后未离开搜索页(10s)")
            time.sleep(2)
        else:
            # ---- 步骤 C：输入地址文本 ----
            tf = client(className=E.SEARCH_TEXTFIELD_TYPE)
            if tf.exists:
                tf.click()
                time.sleep(1)
            client.send_keys(address)
            logger.info(f"  >> 已输入{addr_type}文本: {address}")

            # ---- 步骤 D：等待搜索结果出现（轮询最多 15 秒） ----
            # iOS 搜索在输入过程中实时出结果，不需要点 Done
            search_result_found = False
            for wait_idx in range(15):
                time.sleep(1)
                # 检测搜索结果：Cell 元素或包含地址关键词的 StaticText
                cells = client(type="Cell")
                cell_count = cells.count() if callable(getattr(cells, "count", None)) else 0
                if cells.exists and cell_count > 0:
                    search_result_found = True
                    logger.info(f"  >> 搜索结果已出现 ({wait_idx+1}s)，Cell 数量: {cell_count}")
                    break

                # 备选：文本匹配（同时匹配简体和繁体关键词）
                search_kws = [target_text, address.replace("地铁站", "地鐵站").replace("地铁", "地鐵")]
                for kw in search_kws:
                    result = client(
                        xpath=f'//XCUIElementTypeStaticText[contains(@label,"{kw}") or contains(@value,"{kw}")]')
                    if result.exists:
                        search_result_found = True
                        logger.info(f"  >> 搜索结果已出现 ({wait_idx+1}s)，文本匹配『{kw}』")
                        break
                if search_result_found:
                    break

                time.sleep(1)

            if not search_result_found:
                self._ios_screenshot(f"JRYG_ios_search_{addr_type}_no_result.png")
                page_texts = self._ios_get_all_texts(client)
                logger.error(f"  >> 等待{addr_type}搜索结果超时，页面文本: {page_texts[:150]}")
                raise AssertionError(f"等待{addr_type}搜索结果超时(15s)，未出现结果")

            # ---- 步骤 E+F：选择搜索结果并验证跳转（调用通用封装方法） ----
            self._ios_select_search_result(is_start, address, target_text)

    # ==================== 公共流程步骤 ====================

    def _ios_launch_setup_and_addresses(self, tag, start_addr="", end_addr=""):
        """初始下单：启动清理后配置起终点；当前页重选不得调用此启动入口。"""
        self._ios_prepare_passenger_app(tag)
        self._ios_configure_addresses(tag, start_addr, end_addr)

    def _ios_prepare_passenger_app(self, tag, *, launch_wait=10, alert_wait=2):
        """共用启动步骤：桌面→乘客App→系统权限→隐私→引导→广告。

        正常下单保留10秒启动/2秒权限等待；预清理传8秒/1秒。
        仅清理启动遮挡，不取消订单、不登录、不支付，也不重置司机状态。
        """
        # 步骤 1：回到桌面
        logger.info(f"【{tag} 步骤 1】正在回到桌面...")
        self.client.home()
        time.sleep(2)

        # 步骤 2：拉起乘客端 App
        logger.info(f"【{tag} 步骤 2】正在拉起 App: {E.PASSENGER_BUNDLE_ID}")
        self.client.session(E.PASSENGER_BUNDLE_ID)
        time.sleep(launch_wait)

        # 系统权限不存在时继续检查应用内遮挡；真实控件失败由后续流程判断。
        logger.info(f"【{tag} 步骤 3】处理系统弹窗...")
        try:
            self.client.alert.accept()
            time.sleep(alert_wait)
        except Exception:
            pass

        # 处理隐私协议弹框（登录后或首次进入时可能弹出）
        self._ios_dismiss_privacy_agreement()

        # 跳过引导页（最多 5 次，每次点击跳过按钮后等待 3 秒）
        for i in range(5):
            guide_btn = self.client(xpath=E.GUIDE_SKIP_XPATH)
            if guide_btn.exists:
                guide_btn.tap()
                logger.info(f"  >> 跳过引导页 ({i + 1}/5)")
                time.sleep(3)
            else:
                break

        # 关闭广告弹窗（依次尝试广告关闭按钮标识）
        for ad_btn_text in E.AD_CLOSE_IDENTIFIERS:
            ad_el = self.poco(ad_btn_text)
            if ad_el.exists():
                ad_el.click()
                logger.info(f"成功关闭广告弹框 (标识: {ad_btn_text})")
                time.sleep(2)
                break

    def _ios_configure_addresses(self, tag, start_addr, end_addr):
        """依次搜索起点和终点；只处理地址，不启动App、不选择车型或付款。

        初次下单和登录后重选共用本方法。起点搜索抛错时不继续终点或后续步骤。
        """
        logger.info(f"【{tag} 步骤 4】配置起点: {start_addr}")
        self._ios_search_address(is_start=True, address=start_addr)

        # 步骤 5：配置终点
        logger.info(f"【{tag} 步骤 5】配置终点: {end_addr}")
        self._ios_search_address(is_start=False, address=end_addr)

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
            time.sleep(2)

        time.sleep(3)

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
                    time.sleep(5)
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
        time.sleep(5)

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
            filled = False
            # CVV/持卡人姓名：占位文字方式不可靠（StaticText 遮挡 TextField），直接用坐标
            use_placeholder = label not in ("CVV", "持卡人姓名")

            # 方式 1：点击占位文字对应的元素（StaticText 或 TextField）
            if use_placeholder:
                for ph in placeholders:
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
                    except Exception as e:
                        logger.warning(f"  >> [{tag}] 填写{label}(ph={ph})异常: {e}")

            # 方式 2：通过 WDA XML 获取 TextField 坐标直接点击
            if not filled:
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
                except Exception as e:
                    logger.warning(f"  >> [{tag}] 坐标填写{label}异常: {e}")

            if not filled:
                raise RuntimeError(f"{tag}: {label}未填写，停止提交支付")

        self._ios_screenshot(f"JRYG_ios_{tag}_bank_form_filled.png")
        time.sleep(1)

        # 点击"請支付"按钮提交
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

    def _ios_handle_otp_page(self, tag):
        """检测并处理 3D Secure OTP 验证页。

        点击"請支付"后可能跳转到银行 3DS 验证页面（Sandbox 测试环境），
        需要输入 OTP 验证码并点击 Verify & Proceed。

        注意（WebView 3DS 弹层踩坑）：
        1. WDA source 中 TextField 的 value 永远是占位符"e.g. 123456"，
           读不到真实输入值，不能据此判断是否已输入。
        2. 坐标 tap 对该 WebView 内的按钮无效，必须用 element uuid 点击
           （self.client(xpath=...).click() 内部走的就是 uuid 点击）。
        3. 输入框若残留旧字符会导致校验失败，需先退格清空再输入。

        :param tag: 日志标签。
        """
        page_texts = self._ios_get_all_texts(self.client)
        if not any(kw in t for t in page_texts for kw in E.OTP_PAGE_KEYWORDS):
            return  # 不是 OTP 页面

        logger.info(f"  >> [{tag}] 检测到 3D Secure OTP 验证页，填写 OTP...")
        self._ios_screenshot(f"JRYG_ios_{tag}_otp_page.png")
        time.sleep(2)

        otp_code = E.OTP_DEFAULT_CODE

        # ---- 步骤 1：定位 OTP 输入框 ----
        tf = None
        try:
            tf = self.client(type="TextField")
        except Exception as e:
            logger.warning(f"  >> [{tag}] 查找 OTP 输入框异常: {e}")

        # ---- 步骤 2：聚焦输入框（element uuid 点击，坐标 tap 对 WebView 无效） ----
        try:
            if not self._ios_click_element_by_label("", "XCUIElementTypeTextField"):
                # 兜底：坐标点击输入框（实测 393x852 下中心约 196,539）
                self.client.click(*E.OTP_FALLBACK_COORD)
            logger.info(f"  >> [{tag}] 已聚焦 OTP 输入框")
            time.sleep(1.5)
        except Exception as e:
            raise RuntimeError(f"{tag}: 聚焦OTP失败，停止验证") from e

        # ---- 步骤 3：退格清空残留内容 ----
        try:
            for _ in range(E.OTP_CLEAR_TIMES):
                self.client.send_keys("\b")
                time.sleep(0.2)
            logger.info(f"  >> [{tag}] 已清空输入框")
            time.sleep(0.5)
        except Exception as e:
            raise RuntimeError(f"{tag}: 清空OTP失败，停止验证") from e

        # ---- 步骤 4：输入 OTP ----
        try:
            self.client.send_keys(otp_code)
            logger.info(f"  >> [{tag}] 已输入 OTP（内容不记录）")
            time.sleep(1)
        except Exception as e:
            raise RuntimeError(f"{tag}: 输入OTP失败，停止验证") from e

        # ---- 步骤 5：点击 Verify & Proceed（element uuid 点击，坐标 tap 无效） ----
        clicked = self._ios_click_element_by_label("Verify")
        if clicked:
            logger.info(f"  >> [{tag}] 已点击 Verify & Proceed")
        else:
            try:
                verify_poco = self.poco(textMatches=".*Verify.*|.*验证.*|.*Proceed.*")
                if verify_poco.exists():
                    verify_poco.click()
                    clicked = True
                    logger.info(f"  >> [{tag}] Poco 点击 Verify")
            except Exception as e:
                logger.warning(f"  >> [{tag}] Poco 点击 Verify 异常: {e}")

        if not clicked:
            # 兜底：坐标点击（WDA source 坐标：Verify 中心约 196,611）
            self.client.click(*E.OTP_VERIFY_FALLBACK_COORD)
            logger.info(f"  >> [{tag}] 物理坐标点击 Verify")

        time.sleep(5)

        # ---- 步骤 6：等待 3DS 弹层关闭（成功页或返回 App） ----
        logger.info(f"  >> [{tag}] 等待 3DS 验证结果...")
        otp_done = False
        for i in range(15):
            cur_texts = self._ios_get_all_texts(self.client)
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

    def _ios_select_payment(self, tag, payment="cash"):
        """选择支付方式。

        统一面板流程（打錶的士/包車價的士均适用）：
        1. 点击"可選服務"区域 → 弹出支付方式选择面板
        2. 在面板中选择目标支付方式（如已默认选中则跳过）
        3. 点击"確認選擇"按钮 → 回到路线页
        后续由调用方点击"確認呼叫"继续流程。

        车型与支付方式选择时机：
        - 打錶的士：选车型 → 选支付方式（面板）→ 確認選擇 → 確認呼叫
        - 包車價的士：选车型 → 確認呼叫 → 预付页面选支付方式 → 確認支付並呼叫

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

        # ---- 步骤 1：点击"可選服務"区域，弹出支付方式选择面板 ----
        logger.info(f"  >> [{tag}] 点击'可選服務'区域，弹出支付方式选择面板...")
        panel_opened = False
        service_el = self.client(
            xpath='//*[contains(@label,"可選服務") or contains(@value,"可選服務")]')
        if service_el.exists:
            service_el.click()
            panel_opened = True
            time.sleep(2)
            logger.info(f"  >> [{tag}] 已点击'可選服務'区域，等待面板弹出")
        else:
            service_poco = self.poco(textMatches=".*可選服務.*")
            if service_poco.exists():
                service_poco.click()
                panel_opened = True
                time.sleep(2)
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
                        time.sleep(3)
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
