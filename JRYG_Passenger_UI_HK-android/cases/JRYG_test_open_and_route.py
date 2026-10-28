"""港版阳光出行 Android：打开 App，选择起点铜锣湾、终点香港大学的 UI 自动化用例。"""

import os
import re
import subprocess
import sys
import time

import pytest
from airtest.core.api import connect_device, text as airtest_text
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from jryg_hk_android.JRYG_config import SETTINGS
from jryg_hk_android.JRYG_logger import logger


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() != "ANDROID",
    reason="当前不是 Android 自动化环境",
)
class TestJRYGHKOpenAndRoute:
    """启动港版 App，选择起点铜锣湾、终点香港大学。"""

    @classmethod
    def setup_class(cls):
        cls.udid = cls._resolve_udid(SETTINGS["device"].get("udid", ""))
        cls.package = SETTINGS["packages"]["passenger_hk"]
        cls.activity = SETTINGS["packages"]["passenger_hk_activity"]
        cls._ensure_device_online()
        cls.width, cls.height = cls._screen_size()
        connect_device(f"android://127.0.0.1:5037/{cls.udid}")
        cls.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        logger.info(f"【初始化】Android 设备已连接并建立 Poco，分辨率: {cls.width}x{cls.height}")

    # ==================== 设备与 ADB 工具方法 ====================

    @staticmethod
    def _online_udids():
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            raise RuntimeError(f"读取 ADB 设备列表失败: {result.stderr.strip()}")
        return [
            line.split()[0]
            for line in result.stdout.splitlines()[1:]
            if len(line.split()) >= 2 and line.split()[1] == "device"
        ]

    @classmethod
    def _resolve_udid(cls, configured_udid):
        online_udids = cls._online_udids()
        if configured_udid in online_udids:
            return configured_udid
        if len(online_udids) == 1:
            detected_udid = online_udids[0]
            logger.warning(f"配置 UDID '{configured_udid}' 不在线，自动使用唯一在线设备: {detected_udid}")
            return detected_udid
        if not online_udids:
            pytest.fail("未检测到在线 Android 设备，请连接设备并确认 adb devices 状态为 device")
        pytest.fail(f"配置 UDID '{configured_udid}' 不在线，且检测到多台设备: {', '.join(online_udids)}；请更新配置")

    @classmethod
    def _adb(cls, *args, timeout=30, check=True):
        command = ["adb", "-s", cls.udid, *args]
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if check and result.returncode != 0:
            raise RuntimeError(f"ADB 命令失败: {' '.join(command)}\n{result.stderr}")
        return result.stdout

    @classmethod
    def _ensure_device_online(cls):
        state = cls._adb("get-state").strip()
        if state != "device":
            pytest.fail(f"Android 设备未就绪: {cls.udid}, state={state}")

    @classmethod
    def _screen_size(cls):
        output = cls._adb("shell", "wm", "size")
        matches = re.findall(r"(\d+)x(\d+)", output)
        if not matches:
            raise AssertionError(f"无法读取 Android 屏幕尺寸: {output}")
        width, height = matches[-1]
        return int(width), int(height)

    @classmethod
    def _current_activity(cls):
        output = cls._adb("shell", "dumpsys", "window", timeout=15)
        focused = [line.strip() for line in output.splitlines() if "mFocusedApp=" in line]
        return focused[-1] if focused else ""

    # ==================== 通用操作封装 ====================

    def _tap_ratio(self, x_ratio, y_ratio, name):
        x = int(self.width * x_ratio)
        y = int(self.height * y_ratio)
        self._adb("shell", "input", "tap", str(x), str(y))
        logger.info(f"  >> 已点击{name}: ({x}, {y})")

    def _screenshot(self, filename):
        path = os.path.join(BASE_DIR, "screenshots", filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as image_file:
            result = subprocess.run(
                ["adb", "-s", self.udid, "exec-out", "screencap", "-p"],
                stdout=image_file, stderr=subprocess.PIPE, timeout=30,
            )
        if result.returncode != 0 or os.path.getsize(path) < 1024:
            raise AssertionError(f"截图失败: {path}")
        logger.info(f"  >> 截图已保存: {path}")
        return path

    def _grant_permissions(self):
        for permission in (
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.POST_NOTIFICATIONS",
        ):
            self._adb("shell", "pm", "grant", self.package, permission, check=False)

    def _launch_app(self):
        self._grant_permissions()
        self._adb("shell", "am", "force-stop", self.package)
        self._adb("shell", "am", "start", "-W", "-n", f"{self.package}/{self.activity}")
        for _ in range(15):
            activity = self._current_activity()
            if self.package in activity:
                logger.info(f"  >> 港版 App 已启动并处于前台: {activity}")
                time.sleep(3)
                self.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
                time.sleep(5)
                return
            time.sleep(1)
        activity = self._current_activity()
        if self.package not in activity:
            raise AssertionError(f"港版 App 启动失败，当前前台页面: {activity}")
        logger.info(f"  >> 港版 App 已启动: {activity}")
        self.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        time.sleep(5)

    def _close_proxy_warning(self):
        """关闭代理检测提示框（Proxy detected → Got It）"""
        for _ in range(5):
            got_it = self.poco("com.sunlightmobility.client:id/positive")
            if got_it.exists():
                got_it.click()
                logger.info("  >> 已关闭代理检测提示框 (Got It)")
                time.sleep(2)
                return
            # 也尝试通过文本匹配
            got_it_text = self.poco(text="Got It")
            if got_it_text.exists():
                got_it_text.click()
                logger.info("  >> 已关闭代理检测提示框 (Got It)")
                time.sleep(2)
                return
            time.sleep(1)
        logger.info("  >> 未检测到代理检测提示框，继续执行")

    def _close_activity_popup(self):
        # 先关闭代理检测提示框
        self._close_proxy_warning()

        output = self._adb("shell", "dumpsys", "window", timeout=15)
        if "PopupWindow" in output:
            self._tap_ratio(0.50, 0.747, "活动弹框关闭按钮")
            time.sleep(2)
            logger.info("  >> 活动弹框已关闭")
        else:
            logger.info("  >> 当前没有活动弹框")

    def _input_text(self, value):
        et_search = None
        for _ in range(15):
            el = self.poco("com.sunlightmobility.client:id/et_search")
            if el.exists():
                et_search = el
                break
            el_type = self.poco(typeMatches=".*EditText.*")
            if el_type.exists():
                et_search = el_type
                break
            time.sleep(1)

        if et_search:
            et_search.set_text(value)
            logger.info(f"  >> 已成功键入: {value}")
        else:
            logger.warning("  >> 未定位到输入框控件，执行坐标点击并退回 Airtest 输入...")
            self._tap_ratio(0.50, 0.15, "搜索栏输入焦点")
            time.sleep(2)
            try:
                airtest_text(value, enter=False)
                logger.info(f"  >> [Airtest Input] 已成功键入: {value}")
            except Exception as e:
                logger.error(f"  >> [Airtest Input 失败] {e}")
        time.sleep(5)

    def _select_first_search_result(self, fallback_x, fallback_y, name):
        first_item = None
        for _ in range(10):
            el = self.poco("com.sunlightmobility.client:id/tv_title")
            if el.exists():
                first_item = el
                break
            time.sleep(1)

        if first_item:
            try:
                try:
                    first_item[0].click()
                except Exception:
                    first_item.click()
                logger.info(f"  >> 成功选中首个搜索结果: {name}")
            except Exception as e:
                logger.warning(f"  >> Poco 点击异常: {e}，执行坐标点击兜底...")
                self._tap_ratio(fallback_x, fallback_y, f"第一条{name}结果")
        else:
            self._tap_ratio(fallback_x, fallback_y, f"第一条{name}结果")

    # ==================== 登录保障 ====================

    def _ensure_logged_in(self):
        phone_number = "11001727"
        verify_code = "123456"
        logger.info(f"【登录校验】进入个人中心检查登录状态，预备手机号: {phone_number}...")

        self._close_activity_popup()

        btn_mine = self.poco(text="我的")
        if btn_mine.exists():
            btn_mine.click()
        else:
            self._adb("shell", "input", "tap", "195", "2676")
        time.sleep(5)

        logged_in = True
        for retry in range(5):
            texts = []
            try:
                for el in self.poco(type="android.widget.TextView"):
                    t = el.get_text()
                    if t:
                        texts.append(t.strip())
            except Exception:
                pass
            joined = " ".join(texts)
            logger.info(f"  >> [我的页面文本嗅探] 循环 {retry}: {joined[:200]}")

            if "登錄/註冊" in joined or "登录/注册" in joined:
                logged_in = False
                break
            elif "1727" in joined or "****" in joined or "會員" in joined or "会员" in joined or "我的行程" in joined:
                logged_in = True
                break
            time.sleep(1)

        if not logged_in:
            logger.info("  >> 【未登录】执行登录流程...")
            btn_login_entry = self.poco(text="登錄/註冊")
            if not btn_login_entry.exists():
                btn_login_entry = self.poco("com.sunlightmobility.client:id/tv_mine_name")
            if btn_login_entry.exists():
                btn_login_entry.click()
            else:
                self._adb("shell", "input", "tap", "661", "477")
            time.sleep(4)

            # 输入手机号
            et_phone = self.poco("com.sunlightmobility.client:id/phone_num")
            if et_phone.exists():
                et_phone.click()
                time.sleep(0.5)
                et_phone.set_text(phone_number)
            else:
                self._adb("shell", "input", "tap", "617", "821")
                time.sleep(0.5)
                self._adb("shell", "input", "text", phone_number)
            time.sleep(1.5)

            # 勾选隐私
            self._tap_checkbox()
            time.sleep(1)

            # 获取验证码
            btn_get_code = self.poco("com.sunlightmobility.client:id/rl_next")
            if btn_get_code.exists():
                btn_get_code.click()
            else:
                self._adb("shell", "input", "tap", "586", "1042")
            time.sleep(4)

            # 输入验证码
            et_code = self.poco("com.sunlightmobility.client:id/verify_code")
            if et_code.exists():
                et_code.click()
                time.sleep(0.5)
                et_code.set_text(verify_code)
            else:
                self._adb("shell", "input", "tap", "586", "865")
                time.sleep(0.5)
                self._adb("shell", "input", "text", verify_code)
            time.sleep(6)
            logger.info("  >> 登录验证码已输入完毕，等待跳转。")
        else:
            logger.info("  >> 【已登录】跳过登录步骤。")

        # 切回首页
        for i in range(3):
            btn_home_tab = self.poco("com.sunlightmobility.client:id/item_tab_icon_layout")
            if btn_home_tab.exists():
                btn_home_tab[0].click()
            else:
                self._adb("shell", "input", "tap", "195", "2676")
            time.sleep(4)

            tv_start = self.poco("com.sunlightmobility.client:id/tv_start_address")
            tv_dest = self.poco(text="想要去哪裡？")
            if tv_start.exists() or tv_dest.exists():
                logger.info("  >> 成功确认切回乘客端主页！")
                break
            logger.warning(f"  >> 切回首页未确认，重试 ({i+1})...")

        self.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        time.sleep(2)

    def _tap_checkbox(self):
        self._adb("shell", "uiautomator", "dump", "/sdcard/_temp.xml", check=False)
        path = os.path.join(BASE_DIR, "screenshots", "_temp.xml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            subprocess.run(["adb", "-s", self.udid, "exec-out", "cat", "/sdcard/_temp.xml"], stdout=f)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            pattern = r'text="已閱讀並同意[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            match = re.search(pattern, content)
            if match:
                x1, y1, x2, y2 = map(int, match.groups())
                self._adb("shell", "input", "tap", str(x1 - 35), str((y1 + y2) // 2))

    # ==================== 起终点设置 ====================

    def _set_origin(self):
        logger.info("正在点击起点栏位...")
        tv_start = self.poco("com.sunlightmobility.client:id/tv_start_address")
        if tv_start.exists():
            tv_start.click()
            logger.info("  >> 成功点击起点栏位")
        else:
            self._tap_ratio(0.50, 0.742, "出发地址")
        time.sleep(3)
        self._input_text("铜锣湾")
        self._screenshot("JRYG_route_01_origin_results.png")
        self._select_first_search_result(0.50, 0.149, "铜锣湾")
        time.sleep(6)
        self._close_activity_popup()

    def _set_destination(self):
        logger.info("正在点击目的地栏位...")
        tv_dest = self.poco(text="想要去哪裡？")
        if not tv_dest.exists():
            tv_dest = self.poco("com.sunlightmobility.client:id/tv_destination")
        if not tv_dest.exists():
            tv_dest = self.poco("com.sunlightmobility.client:id/rl_destination_layout")

        if tv_dest.exists():
            tv_dest.click()
            logger.info("  >> 成功点击目的地栏位")
        else:
            self._tap_ratio(0.50, 0.812, "目的地")
        time.sleep(3)
        self._input_text("香港大学")
        self._screenshot("JRYG_route_02_destination_results.png")
        self._select_first_search_result(0.34, 0.153, "香港大学")
        time.sleep(10)
        activity = self._current_activity()
        if self.package not in activity:
            raise AssertionError(f"选择目的地后 App 不在前台: {activity}")

    # ==================== 测试用例 ====================

    def test_open_app_and_select_route(self):
        """启动港版 App，选择起点铜锣湾、终点香港大学。"""
        try:
            logger.info("【步骤 1】从桌面启动港版 App...")
            self._launch_app()

            logger.info("【步骤 2】关闭活动弹框...")
            self._screenshot("JRYG_route_00_home.png")
            self._close_activity_popup()

            logger.info("【步骤 3】保障登录状态...")
            self._ensure_logged_in()
            self._close_activity_popup()

            logger.info("【步骤 4】设置起点：铜锣湾...")
            self._set_origin()

            logger.info("【步骤 5】设置终点：香港大学...")
            self._set_destination()

            self._screenshot("JRYG_route_03_route_selected.png")
            logger.info("【成功】港版 App 已启动并完成起点铜锣湾、终点香港大学的选择！")
        except Exception as exc:
            logger.error(f"【流程失败】{exc}")
            try:
                self._screenshot("JRYG_route_error.png")
            except Exception as screenshot_error:
                logger.error(f"  >> 异常截图失败: {screenshot_error}")
            raise
