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
        for ad_btn_text in ["iv_cancel", "close", "关闭", "叉號", "叉号"]:
            ad_el = self.poco(ad_btn_text)
            if ad_el.exists():
                ad_el.click()
                logger.info(f"  >> 成功关闭首页促销大图弹框 (标识: {ad_btn_text})")
                time.sleep(2)
                return
        # 尝试通过坐标关闭弹框
        close_xpath = self.client(xpath='//*[contains(@label, "close") or contains(@label, "關閉") or contains(@label, "关闭") or contains(@label, "叉")]')
        if close_xpath.exists:
            close_xpath.click()
            logger.info("  >> [WDA] 成功关闭弹框")
            time.sleep(2)
        else:
            logger.info("  >> 当前没有活动弹框")

    def _click_search_and_input(self, value):
        """点击搜索框并输入文本"""
        logger.info(f"正在输入: {value}...")
        # 检测 TextField 出现
        for wait_sec in range(10):
            tf = self.client(type="TextField")
            if tf.exists:
                tf.click()
                time.sleep(0.5)
                break
            # Poco 兜底
            if self.poco(type="XCUIElementTypeTextField").exists():
                self.poco(type="XCUIElementTypeTextField").click()
                time.sleep(0.5)
                break
            time.sleep(1)

        self.client.send_keys(value)
        logger.info(f"  >> [WDA] 已成功键入: {value}")
        time.sleep(5)

    def _select_first_search_result(self, fallback_x, fallback_y, name):
        """选择搜索结果列表首项"""
        first_cell = self.client(type="Cell")
        if first_cell.exists:
            first_cell[0].click()
            logger.info(f"  >> [WDA] 成功选中首个搜索结果: {name}")
        else:
            # Poco 兜底
            first_item = self.poco(type="XCUIElementTypeCell")
            if first_item.exists():
                first_item[0].click()
                logger.info(f"  >> [Poco] 成功选中首个搜索结果: {name}")
            else:
                logger.info(f"  >> 通过物理坐标 ({fallback_x}, {fallback_y}) 强制点击首行{name}结果...")
                self.client.click(fallback_x, fallback_y)

    # ==================== 登录保障 ====================

    def _ensure_logged_in(self):
        phone_number = "11001727"
        verify_code = "123456"
        logger.info(f"【登录校验 -ios】进入个人中心检查登录状态，预备手机号: {phone_number}...")

        self._close_activity_popup()

        # 点击底部『我的』标签
        btn_mine = self.poco(textMatches=".*我的.*|.*Me.*|.*個人.*|.*个人.*")
        if btn_mine.exists():
            btn_mine.click()
            logger.info("  >> [Poco] 成功点击『我的』标签")
        else:
            mine_xpath = self.client(xpath='//*[contains(@label, "我的") or contains(@value, "我的")]')
            if mine_xpath.exists:
                mine_xpath.click()
                logger.info("  >> [WDA] 成功点击『我的』标签")
            else:
                logger.info("  >> 采用物理坐标 (0.83, 0.97) 点击底部『我的』标签...")
                self.client.click(0.83, 0.97)
        time.sleep(5)

        # 检查登录状态
        logged_in = True
        for retry in range(5):
            texts = []
            try:
                for el in self.poco(type="XCUIElementTypeStaticText"):
                    t = el.get_text()
                    if t:
                        texts.append(t.strip())
            except Exception:
                pass
            joined = " ".join(texts)
            logger.info(f"  >> [iOS 我的页面文本嗅探] 循环 {retry}: {joined[:200]}")

            if "登錄/註冊" in joined or "登录/注册" in joined:
                logged_in = False
                break
            elif "1727" in joined or "****" in joined or "會員" in joined or "会员" in joined or "我的行程" in joined:
                logged_in = True
                break
            time.sleep(1)

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
            time.sleep(4)

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
        for i in range(3):
            # 点击底部首页标签
            self.client.click(0.15, 0.97)
            time.sleep(4)

            # 嗅探当前页面是否已经含有首页的标志性元素
            tv_start = self.poco(textMatches=".*起點.*|.*起点.*|.*当前位置.*|.*當前位置.*|.*您在哪.*")
            tv_dest = self.poco(textMatches=".*想去哪.*|.*目的地.*|.*去哪.*")
            if tv_start.exists() or tv_dest.exists():
                logger.info("  >> 成功确认切回乘客端主页！")
                break
            logger.warning(f"  >> 切回首页未成功确认，尝试重新点击 (尝试次数: {i+1})...")

        time.sleep(2)

    # ==================== 起终点设置 ====================

    def _set_origin(self):
        """设置起点：铜锣湾"""
        logger.info("正在点击起点栏位...")
        start_el = self.poco(textMatches=".*起點.*|.*起点.*|.*当前位置.*|.*當前位置.*|.*请输入起点.*|.*輸入起點.*|.*输入起点.*|.*您在哪.*|.*您從哪.*|.*您从哪.*")
        if start_el.exists():
            start_el.click()
            logger.info("  >> [Poco] 成功点击起点栏位")
        else:
            start_xpath = self.client(xpath='//*[contains(@label, "起點") or contains(@value, "起點") or contains(@label, "起点") or contains(@value, "起点") or contains(@label, "当前位置") or contains(@value, "当前位置") or contains(@label, "當前位置") or contains(@value, "當前位置") or contains(@label, "您在哪") or contains(@value, "您在哪")]')
            if start_xpath.exists:
                start_xpath.click()
                logger.info("  >> [WDA] 成功点击起点栏位")
            else:
                logger.info("  >> 采用物理坐标 (0.5, 0.76) 点击起点区域...")
                self.client.click(0.5, 0.76)

        time.sleep(3)
        self._click_search_and_input("铜锣湾")
        self._screenshot("JRYG_ios_route_01_origin_results.png")
        self._select_first_search_result(0.50, 0.25, "铜锣湾")
        time.sleep(6)
        self._close_activity_popup()

    def _set_destination(self):
        """设置终点：香港大学"""
        logger.info("正在点击目的地栏位...")
        dest_el = self.poco(textMatches=".*想去哪.*|.*想去哪里.*|.*目的地.*|.*去哪.*|.*輸入目的地.*|.*输入目的地.*|.*要去哪.*|.*要去邊.*")
        if dest_el.exists():
            dest_el.click()
            logger.info("  >> [Poco] 成功点击目的地栏位")
        else:
            dest_xpath = self.client(xpath='//*[contains(@label, "想去") or contains(@value, "想去") or contains(@label, "哪裡") or contains(@value, "哪裡") or contains(@label, "哪里") or contains(@value, "哪里") or contains(@label, "输入目的地") or contains(@value, "输入目的地") or contains(@label, "輸入目的地") or contains(@value, "輸入目的地")]')
            if dest_xpath.exists:
                dest_xpath.click()
                logger.info("  >> [WDA] 成功点击目的地栏位")
            else:
                logger.info("  >> 采用物理坐标 (0.5, 0.68) 点击目的地区域...")
                self.client.click(0.5, 0.68)

        time.sleep(3)
        self._click_search_and_input("香港大学")
        self._screenshot("JRYG_ios_route_02_destination_results.png")
        self._select_first_search_result(0.50, 0.25, "香港大学")
        time.sleep(10)

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
