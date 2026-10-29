"""港版阳光出行 iOS：打开 App，选择起点铜锣湾、终点香港大学的 UI 自动化用例 -ios

对标安卓版 JRYG_test_open_and_route.py，逻辑与业务流程完全一致。
使用 WDA (WebDriverAgent) + facebook-wda + iosPoco 物理通道驱动 iOS 真机。
"""

import os
import sys
import time

import pytest
import wda
from airtest.core.api import connect_device
from poco.drivers.ios import iosPoco

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from jryg_hk_ios.JRYG_config import SETTINGS
from jryg_hk_ios.JRYG_logger import logger


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() != "IOS",
    reason="当前不是 iOS 自动化环境",
)
class TestJRYGHKIosOpenAndRoute:
    """启动港版 iOS App，选择起点铜锣湾、终点香港大学 -ios。"""

    @classmethod
    def setup_class(cls):
        """类级初始化：建立设备连接、缓存设备信息并创建 Poco 控件树驱动。

        :return: None。"""
        cls.wda_url = SETTINGS["device"].get("wda_url", "http://127.0.0.1:8100")
        cls.bundle_id = SETTINGS["packages"].get("passenger_hk", "com.sunlightmobility.client")
        logger.info(f"【iOS 路线 -ios】正在尝试连接 WDA 物理通道: {cls.wda_url}")

        try:
            cls.client = wda.Client(cls.wda_url)
            status = cls.client.status()
            logger.info(f"【iOS 路线 -ios】设备连接成功！ status: {status}")
        except Exception as e:
            logger.error(
                f"【iOS 连接失败 -ios】请确认 WDA 已在手机上正常运行，且通过 iproxy 转发了 8100 端口！ 错误原因: {e}"
            )
            pytest.skip("WDA 物理通道未就绪，跳过 iOS 路线选择用例")

        connect_device(f"ios:///{cls.wda_url}")
        cls.poco = iosPoco()
        logger.info("【iOS 路线 -ios】Poco 控件树驱动加载完成，已准备就绪。")

    @classmethod
    def teardown_class(cls):
        """类级清理：释放设备连接与相关资源。

        :return: None。"""
        logger.info("【iOS 路线 -ios】自动化运行结束。")

    # ==================== 通用操作封装 ====================

    def _screenshot(self, filename):
        """通过 WDA 截图并保存到 screenshots 目录"""
        path = os.path.join(BASE_DIR, "screenshots", filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.client.screenshot(path)
        logger.info(f"  >> 截图已保存: {path}")
        return path

    def _launch_app(self):
        """拉起港版乘客端 App"""
        logger.info(f"【iOS -ios】正在拉起港版 App: {self.bundle_id}")
        self.client.home()
        time.sleep(1)
        self.client.session(self.bundle_id)
        time.sleep(8)

    def _accept_alert(self):
        """自动接受 iOS 系统弹窗"""
        try:
            self.client.alert.accept()
            logger.info("  >> 已自动允许系统授权弹窗")
            time.sleep(2)
        except Exception:
            pass

    def _close_activity_popup(self):
        """关闭首页可能出现的广告/促销弹框"""
        self._accept_alert()
        self.monitor.dismiss_activity_popup(self.client)

    def _click_search_and_input(self, value):
        """点击搜索框并输入文本"""
        logger.info(f"正在输入: {value}...")
        self.monitor.wait_for("进入地址搜索页", lambda page: page.state == "address_search")
        tf = self.client(type="TextField")
        assert tf.exists, "地址搜索输入框不存在"
        tf.click()
        tf.clear_text()
        self.client.send_keys(value)
        logger.info(f"  >> [WDA] 已成功键入: {value}")
        time.sleep(5)

    def _select_first_search_result(self, name):
        """等待真实地址结果，按可见单元格选择匹配项。"""
        translation = str.maketrans("銅鑼灣學", "铜锣湾学")

        def matching_cells(page):
            """TestJRYGHKIosOpenAndRoute.matching_cells —— 公开方法：matching cells。

        :return: None"""
            return [node for node in page.nodes if node.tag.endswith("Cell")
                    and name in " ".join(
                        child.get("label", "") + child.get("value", "")
                        for child in node.iter()).translate(translation)]

        page = self.monitor.wait_for(f"搜索结果: {name}", lambda current: bool(matching_cells(current)))
        cell = matching_cells(page)[0]
        self.client.click(int(float(cell.get("x")) + float(cell.get("width")) / 2),
                          int(float(cell.get("y")) + float(cell.get("height")) / 2))
        logger.info(f"已选择匹配的搜索结果: {name}")

    # ==================== 登录保障 ====================

    def _ensure_logged_in(self):
        """保障登录：检查登录态，未登录则执行登录流程，最后切回首页。

        :return: None。流程异常通过 AssertionError / RuntimeError 中断。"""
        phone_number = "11001727"
        verify_code = "123456"
        logger.info(f"【登录校验 -ios】进入个人中心检查登录状态，预备手机号: {phone_number}...")

        self._close_activity_popup()

        assert self.monitor.click_text(self.client, "我的"), "未找到可见的我的标签"

        page = self.monitor.wait_for(
            "进入个人中心并识别登录态",
            lambda current: current.state in ("mine_unlogged", "mine_logged"),
        )
        logged_in = page.state == "mine_logged"

        if not logged_in:
            logger.info("  >> 【未登录 -ios】检测到处于未登录态，准备执行登录流程...")
            btn_login_entry = self.poco(textMatches=".*登錄/註冊.*|.*登录/注册.*")
            if btn_login_entry.exists():
                btn_login_entry.click()
            else:
                login_xpath = self.client(xpath='//*[contains(@label, "登錄/註冊") or contains(@value, "登錄/註冊") or contains(@label, "登录/注册") or contains(@value, "登录/注册")]')
                if login_xpath.exists:
                    login_xpath.click()
                else:
                    self.client.click(0.5, 0.25)
            time.sleep(4)

            # 输入手机号
            logger.info(f"  >> 键入手机号 {phone_number}...")
            phone_field = self.client(type="TextField")
            if phone_field.exists:
                phone_field.click()
                time.sleep(0.5)
                self.client.send_keys(phone_number)
            else:
                self.client.click(0.5, 0.25)
                time.sleep(1)
                self.client.send_keys(phone_number)
            time.sleep(1.5)

            # 勾选隐私协议
            agree_text = self.poco(textMatches=".*已閱讀並同意.*|.*已阅读并同意.*|.*同意.*")
            if agree_text.exists():
                try:
                    pos = agree_text.get_position()
                    size = agree_text.get_size()
                    x = pos[0] - size[0] / 2 + 0.03
                    y = pos[1]
                    self.client.click(x, y)
                    logger.info("  >> 成功勾选隐私协议复选框")
                except Exception:
                    agree_text.click()
                time.sleep(1)

            # 点击取得验证码
            btn_get_code = self.poco(textMatches=".*取得驗證碼.*|.*获取验证码.*")
            if btn_get_code.exists():
                btn_get_code.click()
            else:
                code_xpath = self.client(xpath='//*[contains(@label, "取得驗證碼") or contains(@value, "取得驗證碼") or contains(@label, "获取验证码") or contains(@value, "获取验证码")]')
                if code_xpath.exists:
                    code_xpath.click()
                else:
                    self.client.click(0.5, 0.55)
            self.monitor.wait_for("进入验证码页", lambda page: page.state == "login_code_input")

            # 输入验证码
            logger.info(f"  >> 键入验证码 {verify_code}...")
            code_field = self.client(type="TextField")
            if code_field.exists:
                code_field.click()
                time.sleep(0.5)
                self.client.send_keys(verify_code)
            else:
                self.client.click(0.5, 0.25)
                time.sleep(1)
                self.client.send_keys(verify_code)
            time.sleep(6)
            logger.info("  >> 登录验证码已输入完毕，等待网络交互跳转。")
        else:
            logger.info("  >> 【已登录 -ios】检测到已处于登录态，跳过登录录入步骤。")

        # 切回首页
        logger.info("【登录校验结束 -ios】正在切换并回到乘客端首页选项卡...")
        assert self.monitor.click_text(self.client, "主頁", "首页"), "未找到可见的首页标签"

        self._close_activity_popup()
        self.monitor.wait_for(
            "返回乘客首页", lambda page: page.state == "home_unlogged",
            recover=lambda page: self.monitor.dismiss_activity_popup(self.client)
            if page.state == "activity_popup" else None,
        )

    # ==================== 起终点设置 ====================

    def _set_origin(self):
        """设置起点：铜锣湾"""
        logger.info("正在点击起点栏位...")
        page = self.monitor.inspect()
        assert page.state == "home_unlogged", f"设置起点前不是首页: {page.state}"
        origin_buttons = [
            node for node in page.root.findall(".//XCUIElementTypeScrollView//XCUIElementTypeButton")
            if node.get("visible") == "true" and not node.get("label")
            and not node.get("name") and float(node.get("width", 0)) > 100
        ]
        assert len(origin_buttons) == 1, "无法唯一识别首页起点按钮，停止坐标兜底"
        origin = origin_buttons[0]
        self.client.click(int(float(origin.get("x")) + float(origin.get("width")) / 2),
                          int(float(origin.get("y")) + float(origin.get("height")) / 2))

        time.sleep(3)
        self._click_search_and_input("铜锣湾")
        self._screenshot("JRYG_ios_route_01_origin_results.png")
        self._select_first_search_result("铜锣湾")
        time.sleep(6)
        self._close_activity_popup()

    def _set_destination(self):
        """设置终点：香港大学"""
        logger.info("正在点击目的地栏位...")
        assert self.monitor.click_text(
            self.client, "想去哪裡？", "想去哪裡", "輸入目的地", "slm_icon_main_end_address_border"
        ), "未找到可见的目的地入口"

        time.sleep(3)
        self._click_search_and_input("香港大学")
        self._screenshot("JRYG_ios_route_02_destination_results.png")
        self._select_first_search_result("香港大学")
        self.monitor.wait_for(
            "确认起终点及路线报价页",
            lambda page: page.state == "route_selected"
            and page.has("銅鑼灣", "铜锣湾") and page.has("香港大學", "香港大学"),
        )

    # ==================== 测试用例 ====================

    def test_ios_open_app_and_select_route(self):
        """启动港版 iOS App，选择起点铜锣湾、终点香港大学 -ios。"""
        try:
            logger.info("【步骤 1 -ios】从桌面启动港版 App...")
            self._launch_app()

            logger.info("【步骤 2 -ios】关闭活动弹框...")
            self._screenshot("JRYG_ios_route_00_home.png")
            self._close_activity_popup()

            logger.info("【步骤 3 -ios】保障登录状态...")
            self._ensure_logged_in()
            self._close_activity_popup()

            logger.info("【步骤 4 -ios】设置起点：铜锣湾...")
            self._set_origin()

            logger.info("【步骤 5 -ios】设置终点：香港大学...")
            self._set_destination()

            self._screenshot("JRYG_ios_route_03_route_selected.png")
            logger.info("【成功 -ios】港版 iOS App 已启动并完成起点铜锣湾、终点香港大学的选择！")
        except Exception as exc:
            logger.error(f"【流程失败 -ios】{exc}")
            try:
                self._screenshot("JRYG_ios_route_error.png")
            except Exception as screenshot_error:
                logger.error(f"  >> 异常截图失败: {screenshot_error}")
            raise
