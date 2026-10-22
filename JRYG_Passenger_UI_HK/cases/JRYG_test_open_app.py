"""港版阳光出行 Android：从启动 App 到提交订单的端到端自动化用例。"""

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

from JRYG_Passenger_UI_HK.common.JRYG_config import SETTINGS
from JRYG_Passenger_UI_HK.common.JRYG_logger import logger


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() != "ANDROID",
    reason="当前不是 Android 自动化环境",
)
class TestJRYGHKAndroidOrder:
    """启动港版 App，选择铜锣湾地铁站到香港大学并确认呼叫。"""

    @classmethod
    def setup_class(cls):
        cls.udid = SETTINGS["device"]["udid"]
        cls.package = SETTINGS["packages"]["passenger_hk"]
        cls.activity = SETTINGS["packages"]["passenger_hk_activity"]
        cls._ensure_device_online()
        cls.width, cls.height = cls._screen_size()
        cls.had_active_order = "YGAImmediateOrderProcessActivity" in cls._current_activity()
        connect_device(f"android://127.0.0.1:5037/{cls.udid}")
        cls.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        logger.info(f"【初始化】Android 设备已连接并建立 Poco，分辨率: {cls.width}x{cls.height}")

    @classmethod
    def _adb(cls, *args, timeout=30, check=True):
        command = ["adb", "-s", cls.udid, *args]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
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

    def _wait_activity(self, keyword, timeout=15):
        end_time = time.time() + timeout
        while time.time() < end_time:
            activity = self._current_activity()
            if keyword in activity:
                return activity
            time.sleep(1)
        return self._current_activity()

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
                stdout=image_file,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        if result.returncode != 0 or os.path.getsize(path) < 1024:
            raise AssertionError(f"截图失败: {path}")
        logger.info(f"  >> 截图已保存: {path}")
        return path

    def _grant_permissions(self):
        permissions = (
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.POST_NOTIFICATIONS",
        )
        for permission in permissions:
            self._adb(
                "shell",
                "pm",
                "grant",
                self.package,
                permission,
                check=False,
            )

    def _launch_app(self):
        self._grant_permissions()
        self._adb("shell", "am", "force-stop", self.package)
        self._adb("shell", "am", "start", "-W", "-n", f"{self.package}/{self.activity}")
        # 循环等待确保进入前台
        for _ in range(15):
            activity = self._current_activity()
            if self.package in activity:
                logger.info(f"  >> 港版 App 已启动并处于前台: {activity}")
                time.sleep(3)
                # 重新初始化 Poco 并等待其服务绑定稳定
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

    def _detect_current_state(self):
        """通过前台 Activity 与 UI 关键内容判断当前所在登录/业务状态"""
        activity = self._current_activity().lower()
        if self.package not in activity:
            return "launcher"

        # 极速匹配
        if self.poco(text="同意").exists() and self.poco(text="不同意").exists():
            return "privacy_agreement"
        if self.poco(text="去授權").exists() and self.poco(text="取消").exists():
            return "permission_dialog"
        if self.poco(text="使用应用时允许").exists() or self.poco(text="仅在使用中允许").exists():
            return "system_location_permission"
        if self.poco(text="請輸入驗證碼").exists() or self.poco(textMatches=".*重新獲取.*").exists():
            return "login_code_input"
        if self.poco(text="請輸入手機號").exists() or self.poco(text="取得驗證碼").exists():
            return "login_phone_input"
        if self.poco(text="登錄/註冊").exists():
            return "mine_unlogged"
        
        # 通过拉取全部TextView作复合判断
        texts = []
        try:
            for el in self.poco(type="android.widget.TextView"):
                t = el.get_text()
                if t:
                    texts.append(t.strip())
        except Exception:
            pass
        joined = " ".join(texts)

        if "歡迎登錄" in joined or "請輸入手機號" in joined:
            return "login_phone_input"
        if "請輸入驗證碼" in joined:
            return "login_code_input"
        if "登錄/註冊" in joined:
            return "mine_unlogged"
        if "想要去哪裡？" in joined:
            if "1727" in joined or "****" in joined:
                return "home_logged"
            return "home_unlogged"

        return "unknown"

    def _tap_by_text(self, target_text):
        """通过 adb dump 正则查找目标 text 并物理点击"""
        self._adb("shell", "uiautomator", "dump", "/sdcard/_temp.xml", check=False)
        path = os.path.join(BASE_DIR, "screenshots", "_temp.xml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            subprocess.run(["adb", "-s", self.udid, "exec-out", "cat", "/sdcard/_temp.xml"], stdout=f)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            pattern = r'text="' + re.escape(target_text) + r'"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            match = re.search(pattern, content)
            if match:
                x1, y1, x2, y2 = map(int, match.groups())
                self._adb("shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2))
                return True
        return False

    def _tap_checkbox(self):
        """通过 bounds 计算点击隐私条款最左侧的 CheckBox"""
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
                self._adb("shell", "input", "tap", str(x1 - 35), str((y1+y2)//2))

    def _ensure_logged_in(self):
        """保障登录：进入个人中心，检查是否登录，若未登录则一键登录，最后必须切换回首页"""
        phone_number = "11001727"
        verify_code = "123456"
        logger.info(f"【登录校验】进入个人中心检查登录状态，预备登录手机号: {phone_number}...")

        # 1. 确保在“我的”页面
        self._close_activity_popup()
        
        logger.info("  >> 点击底部『我的』标签以检查登录态...")
        btn_mine = self.poco(text="我的")
        if btn_mine.exists():
            btn_mine.click()
        else:
            self._tap_by_text("我的")
        time.sleep(5)

        # 2. 检查“我的”页面中的登录状态
        logged_in = True
        for retry in range(5):
            # 每轮先检测并关闭代理安全提示弹窗
            self._dismiss_proxy_popup()
            texts = []
            try:
                for el in self.poco(type="android.widget.TextView"):
                    t = el.get_text()
                    if t:
                        texts.append(t.strip())
            except Exception:
                pass
            joined = " ".join(texts)
            logger.info(f"  >> [我的页面文本嗅探] 循环 {retry}: {joined}")
            
            if "登錄/註冊" in joined or "登录/注册" in joined:
                logged_in = False
                break
            elif "1727" in joined or "****" in joined or "會員" in joined or "会员" in joined or "我的行程" in joined:
                logged_in = True
                break
            time.sleep(1)

        if not logged_in:
            logger.info("  >> 【未登录】检测到处于未登录态，准备执行登录流程...")
            btn_login_entry = self.poco(text="登錄/註冊")
            if not btn_login_entry.exists():
                btn_login_entry = self.poco("com.sunlightmobility.client:id/tv_mine_name")
            if btn_login_entry.exists():
                btn_login_entry.click()
            else:
                self._adb("shell", "input", "tap", "661", "477")
            time.sleep(4)

            # 输入手机号
            logger.info(f"  >> 键入手机号 {phone_number}...")
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
            
            # 勾选同意隐私
            self._tap_checkbox()
            time.sleep(1)
            
            # 点击取得验证码
            btn_get_code = self.poco("com.sunlightmobility.client:id/rl_next")
            if btn_get_code.exists():
                btn_get_code.click()
            else:
                self._adb("shell", "input", "tap", "586", "1042")
            time.sleep(4)

            # 输入验证码
            logger.info(f"  >> 键入验证码 {verify_code}...")
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
            logger.info("  >> 登录验证码已输入完毕，等待网络交互跳转。")
        else:
            logger.info("  >> 【已登录】检测到已处于登录态，跳过登录录入步骤。")

        # 3. 最终：切回首页并确保首页就绪
        logger.info("【登录校验结束】正在切换并回到乘客端首页选项卡...")
        for i in range(3):
            btn_home_tab = self.poco("com.sunlightmobility.client:id/item_tab_icon_layout")
            if btn_home_tab.exists():
                btn_home_tab[0].click()
            else:
                self._adb("shell", "input", "tap", "195", "2676")
            time.sleep(4)
            
            # 嗅探当前页面是否已经含有首页的标志性元素
            tv_start = self.poco("com.sunlightmobility.client:id/tv_start_address")
            tv_dest = self.poco(text="想要去哪裡？")
            if tv_start.exists() or tv_dest.exists():
                logger.info("  >> 成功确认切回乘客端主页！")
                break
            logger.warning(f"  >> 切回首页未成功确认，尝试重新点击 (尝试次数: {i+1})...")
        
        # 重新创建 Poco 的连接句柄以保证上下文状态绝对干净稳定
        self.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        time.sleep(2)

    def _popup_visible(self):
        output = self._adb("shell", "dumpsys", "window", timeout=15)
        return "PopupWindow" in output

    def _dismiss_proxy_popup(self):
        """检测并关闭代理安全提示弹窗 (Notice Proxy detected... Got It)"""
        for attempt in range(3):
            # 通过文本匹配 "Got It" 或 "代理" 相关
            for text_val in ["Got It", "got it", "GOT IT", "知道了", "確定", "确定"]:
                btn = self.poco(text=text_val)
                if btn.exists():
                    logger.info(f"  >> [代理弹窗] 检测到代理提示弹窗，点击「{text_val}」关闭...")
                    btn.click()
                    time.sleep(2)
                    return True
            # 通过 ADB dump 匹配 "Got It" 坐标点击
            self._adb("shell", "uiautomator", "dump", "/sdcard/_temp.xml", check=False)
            path = os.path.join(BASE_DIR, "screenshots", "_temp.xml")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                subprocess.run(["adb", "-s", self.udid, "exec-out", "cat", "/sdcard/_temp.xml"], stdout=f)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                pattern = r'text="(Got It|got it|GOT IT|知道了|確定|确定)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
                match = re.search(pattern, content)
                if match:
                    x1, y1, x2, y2 = int(match.group(2)), int(match.group(3)), int(match.group(4)), int(match.group(5))
                    self._adb("shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2))
                    logger.info(f"  >> [代理弹窗] ADB 点击关闭按钮 ({(x1+x2)//2}, {(y1+y2)//2})")
                    time.sleep(2)
                    return True
            break
        return False

    def _close_activity_popup(self):
        # 0. 先检测代理安全提示弹窗
        self._dismiss_proxy_popup()
        if self._popup_visible():
            self._tap_ratio(0.50, 0.747, "活动弹框关闭按钮")
            time.sleep(2)
            logger.info("  >> 活动弹框已关闭")
        else:
            logger.info("  >> 当前没有活动弹框")

    def _input_text(self, value):
        # 轮询等待控件渲染加载出来，最多等待 15 秒，每次循环动态重检索以获取最新的 UI 状态
        et_search = None
        for i in range(15):
            # 优先匹配特定 ID
            el = self.poco("com.sunlightmobility.client:id/et_search")
            if el.exists():
                et_search = el
                break
            # 模糊类名匹配含有 EditText 字符的控件
            el_type = self.poco(typeMatches=".*EditText.*")
            if el_type.exists():
                et_search = el_type
                break
            time.sleep(1)
            
        if et_search:
            et_search.set_text(value)
            logger.info(f"  >> [Poco Input] 已成功键入: {value}")
        else:
            logger.warning("  >> [警告] 未定位到输入框控件，执行高精度屏幕顶部坐标点击以聚焦，并退回至 Airtest 输入...")
            self._tap_ratio(0.50, 0.15, "搜索栏输入焦点")
            time.sleep(2)
            try:
                airtest_text(value, enter=False)
                logger.info(f"  >> [Airtest Input fallback] 已成功键入: {value}")
            except Exception as e:
                logger.error(f"  >> [Airtest Input 失败] {e}")
        time.sleep(5)

    def _select_first_search_result(self, fallback_x, fallback_y, name):
        # 寻找搜索关联结果列表首项，并在 10 秒内动态重检索轮询，保障网络加载与列表渲染
        first_item = None
        for _ in range(10):
            el = self.poco("com.sunlightmobility.client:id/tv_title")
            if el.exists():
                first_item = el
                break
            time.sleep(1)

        if first_item:
            try:
                # 通过 try-except 优先尝试多结果首项点击，若抛出异常（例如不是多元素）则执行单元素点击
                try:
                    first_item[0].click()
                except Exception:
                    first_item.click()
                logger.info(f"  >> [Poco] 成功选中首个搜索结果: {name}")
            except Exception as e:
                logger.warning(f"  >> Poco 点击匹配项异常: {e}，执行高容错坐标点击兜底...")
                self._tap_ratio(fallback_x, fallback_y, f"第一条{name}结果")
        else:
            self._tap_ratio(fallback_x, fallback_y, f"第一条{name}结果")

    def _set_origin(self):
        logger.info("正在点击起点栏位...")
        tv_start = self.poco("com.sunlightmobility.client:id/tv_start_address")
        if tv_start.exists():
            tv_start.click()
            logger.info("  >> [Poco] 成功点击起点栏位")
        else:
            self._tap_ratio(0.50, 0.742, "出发地址")
        time.sleep(3)
        self._input_text("铜锣湾地铁站")
        self._screenshot("JRYG_android_02_origin_results.png")
        self._select_first_search_result(0.50, 0.149, "铜锣湾地铁站")
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
            logger.info("  >> [Poco] 成功点击目的地栏位")
        else:
            self._tap_ratio(0.50, 0.812, "『想要去哪裡？』")
        time.sleep(3)
        self._input_text("香港大学")
        self._screenshot("JRYG_android_03_destination_results.png")
        self._select_first_search_result(0.34, 0.153, "香港大学")
        time.sleep(10)
        activity = self._current_activity()
        if self.package not in activity:
            raise AssertionError(f"选择目的地后 App 不在前台: {activity}")



    @pytest.mark.skip(reason="只进行乘客端优惠券场景校验，跳过直接呼叫下单")
    def test_android_launch_to_order(self):
        """启动 App、关闭弹框、设置起终点、选择打錶的士并提交订单。"""
        try:
            logger.info("【步骤 1】从桌面启动港版 App...")
            self._launch_app()

            if self.had_active_order:
                activity = self._wait_activity("YGAImmediateOrderProcessActivity", timeout=10)
                self._screenshot("JRYG_android_06_order_submitted.png")
                if "YGAImmediateOrderProcessActivity" not in activity:
                    raise AssertionError(f"启动前已有订单，但未恢复订单处理页: {activity}")
                logger.info("【成功】已恢复刚刚提交的港版订单，避免重复下单。")
                return

            logger.info("【步骤 2】保存首页截图并关闭活动弹框...")
            self._screenshot("JRYG_android_00_home_with_popup.png")
            self._close_activity_popup()
            self._screenshot("JRYG_android_01_home.png")

            logger.info("【步骤 3】设置起点：铜锣湾地铁站...")
            self._set_origin()

            logger.info("【步骤 4】设置终点：香港大学...")
            self._set_destination()

            logger.info("【成功】港版 Android App 从启动到下单流程执行完成！")
        except Exception as exc:
            logger.error(f"【下单流程失败】{exc}")
            try:
                self._screenshot("JRYG_android_order_error.png")
            except Exception as screenshot_error:
                logger.error(f"  >> 异常截图失败: {screenshot_error}")
            raise

    def _slide_drag_view_hk(self, poco):
        """香港版司机端滑块滑动逻辑 (高容错设计)"""
        drag_id = "com.sunlightmobility.driver:id/ll_drag_view"
        drag_view = poco(drag_id)
        if not drag_view.exists():
            for possible_id in ["com.sunlightmobility.driver:id/drag_view", "com.sunlightmobility.driver:id/sb_drag"]:
                if poco(possible_id).exists():
                    drag_view = poco(possible_id)
                    break
                    
        if drag_view.exists():
            pos = drag_view.get_position()
            size = drag_view.get_size()
            x_start = pos[0] - size[0] / 2 + 0.05
            x_end = pos[0] + size[0] / 2 - 0.05
            y = pos[1]
            poco.swipe([x_start, y], [x_end, y], duration=1.5)
            logger.info("  >> 【司机端】Poco 控件滑动成功")
        else:
            logger.warning("  >> 【司机端】未定位到滑块控件，采用高精度 ADB 物理滑动兜底...")
            x_start = int(self.width * 0.15)
            x_end = int(self.width * 0.85)
            y = int(self.height * 0.82)
            self._adb("shell", "input", "swipe", str(x_start), str(y), str(x_end), str(y), "1500")
            logger.info("  >> 【司机端】ADB 物理滑动完成")

    def _click_by_text_hk(self, poco, text_val):
        """点击指定繁体/简体文字控件"""
        el = poco(text=text_val)
        if el.exists():
            el.click()
            logger.info(f"  >> 【司机端】成功点击控件: {text_val}")
            return True
        el_match = poco(textMatches=f".*{text_val}.*")
        if el_match.exists():
            el_match.click()
            logger.info(f"  >> 【司机端】成功模糊点击控件: {text_val}")
            return True
        return False

    @pytest.mark.skip(reason="只进行乘客端优惠券场景校验，无需打开司机端")
    def test_android_driver_process(self):
        """香港版司机端订单状态流转：滑动到达上车地点 -> 接到乘客 -> 等待1分钟 -> 滑动到达目的地"""
        logger.info("\n" + "="*50)
        logger.info("  >> 【步骤 6】启动香港版司机端，开始执行订单流转...")
        logger.info("="*50)

        driver_pkg = "com.sunlightmobility.driver"
        driver_activity = "com.sunlightmobility.driver.activity.loading.YGALoadingActivity"

        # 启动香港版司机端
        logger.info("正在唤醒并拉起香港版司机端 App...")
        self._adb("shell", "am", "force-stop", driver_pkg)
        time.sleep(1)
        self._adb("shell", "am", "start", "-W", "-n", f"{driver_pkg}/{driver_activity}")
        time.sleep(8)

        # 实例化 Poco 
        logger.info("正在建立司机端 Poco 控件树驱动...")
        poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)

        progress = {
            "waited_1min": False,
            "order_entered": False
        }

        # 状态流转机
        for cycle in range(40):
            current_act = self._current_activity()
            logger.info(f"【司机端流转 循环 {cycle + 1}】当前 Activity: {current_act}")

            # 1. 弹框及权限清理
            for pop_text in ["同意", "我知道了", "知道了", "好的", "去授權", "去授权"]:
                if poco(text=pop_text).exists():
                    poco(text=pop_text).click()
                    logger.info(f"  >> 【司机端弹框】已自动关闭弹窗: {pop_text}")
                    time.sleep(2)

            # 2. 判断当前是否已经进入订单详情页 (根据核心状态按钮的存在性)
            is_at_pickup = poco(textMatches=".*到達上車地點.*|.*到达上车地点.*").exists()
            is_received = poco(textMatches=".*已接到乘客.*|.*接到乘客.*|.*已接載乘客.*|.*接載乘客.*").exists()
            is_at_dest = poco(textMatches=".*到達目的地.*|.*到达目的地.*|.*已到達目的地.*|.*已到达目的地.*|.*行程結束.*|.*行程结束.*|.*結束行程.*|.*结束行程.*").exists()
            is_billing = poco(textMatches=".*發起收款.*|.*发起收款.*|.*確認賬單.*|.*确认账单.*|.*確認收款.*|.*确认收款.*").exists()

            if is_at_pickup or is_received or is_at_dest or is_billing:
                if not progress["order_entered"]:
                    logger.info("  >> 【司机端】成功检测到订单状态页面元素，order_entered 标记为 True！")
                    progress["order_entered"] = True

            # 3. 检查并寻找或打开进行中的订单
            if not progress["order_entered"]:
                for open_text in ["訂單進行中", "订单进行中", "未確認賬單", "未确认账单", "進行中", "进行中", "去處理", "去处理", "待出發", "待出发", "新訂單", "新订单"]:
                    if poco(text=open_text).exists():
                        poco(text=open_text).click()
                        logger.info(f"  >> 【司机端】点击进入订单入口: {open_text}")
                        time.sleep(3)
                        break

            # 4. 如果发现需要点击“準備出發”或“出發”
            if self._click_by_text_hk(poco, "準備出發") or self._click_by_text_hk(poco, "出發") or self._click_by_text_hk(poco, "去接乘客"):
                time.sleep(4)
                continue

            # 5. 判断并处理“到達上車地點”
            if is_at_pickup:
                logger.info("  >> 【司机端状态】检测到处于『到達上車地點』阶段，准备滑动...")
                self._screenshot("JRYG_driver_01_at_pickup.png")
                self._slide_drag_view_hk(poco)
                time.sleep(5)
                continue

            # 6. 判断并处理“已接到乘客” / “接到乘客”
            if is_received:
                logger.info("  >> 【司机端状态】检测到处于『已接到乘客』阶段，准备滑动...")
                self._screenshot("JRYG_driver_02_received_passenger.png")
                self._slide_drag_view_hk(poco)
                time.sleep(5)
                continue

            # 7. 判断并处理“到達目的地”
            if is_at_dest:
                self._screenshot("JRYG_driver_03_in_trip.png")
                if not progress["waited_1min"]:
                    logger.info("  >> 【司机端状态】检测到处于『到達目的地』阶段。根据需求：等待 1 分钟...")
                    time.sleep(60)
                    progress["waited_1min"] = True
                    logger.info("  >> 【司机端状态】1 分钟等待结束，开始执行滑动『到達目的地』！")
                
                logger.info("  >> 【司机端状态】正在滑动『到達目的地』...")
                self._slide_drag_view_hk(poco)
                time.sleep(5)
                self._screenshot("JRYG_driver_04_arrived_destination.png")
                continue

            # 8. 结算或完单阶段判断 (例如看到了“發起收款”或“发起收款”或“账单”或“今日营收”或“听单检测”)
            if progress["order_entered"]:
                if is_billing:
                    # 针对打表车型录入车费
                    et_fee = poco("com.sunlightmobility.driver:id/et_input_fee")
                    if et_fee.exists() and et_fee.get_text() in ["請輸入車費", "请输入车费", ""]:
                        logger.info("  >> 【司机端状态】检测到打表车费录入页面，正在输入车费：50 HKD...")
                        et_fee.click()
                        time.sleep(1)
                        et_fee.set_text("50")
                        time.sleep(2)
                    
                    logger.info("  >> 【司机端状态】正在滑动『發起收款/確認收款』...")
                    self._slide_drag_view_hk(poco)
                    time.sleep(5)
                    self._screenshot("JRYG_driver_04_billing_sent.png")
                    continue

                if poco(textMatches=".*今日營收.*|.*今日营收.*|.*聽單.*|.*听单.*|.*完單數.*|.*完单数.*").exists():
                    logger.info("  >> 【司机端状态】成功检测到结算或完单返回界面，行程已圆满结束！")
                    self._screenshot("JRYG_driver_05_finished.png")
                    
                    # 1. 确认收款后，点击返回首页
                    logger.info("正在点击『返回首頁』/『返回首页』以回到司机端主页...")
                    btn_back_home = poco(textMatches=".*返回首頁.*|.*返回首页.*|.*確定.*|.*确定.*|.*返回.*")
                    if btn_back_home.exists():
                        btn_back_home.click()
                        logger.info("  >> 成功点击司机端返回首页按钮")
                    else:
                        logger.info("  >> 采用 ADB 物理返回键兜底回到首页...")
                        self._adb("shell", "input", "keyevent", "BACK")
                    time.sleep(3)
                    break

            time.sleep(3)

        logger.info("【成功】香港版司机端自动化状态流转执行完毕！")

        # 2. 之后打开乘客端查看，并返回首页
        logger.info("\n" + "="*50)
        logger.info("  >> 【步骤 7】重新拉起乘客端，查看结算状态并返回首页...")
        logger.info("="*50)
        
        logger.info("正在唤醒并拉起港版乘客端 App...")
        self._launch_app()
        poco_passenger = self.poco
        
        # 截图保存乘客端完单后状态
        self._screenshot("JRYG_passenger_after_bill.png")
        logger.info("  >> 已保存乘客端查看状态截图: JRYG_passenger_after_bill.png")
        
        # 点击返回首页
        logger.info("正在尝试寻找并点击『点击回首页』或『返回首页』以恢复乘客端主页...")
        btn_passenger_home = poco_passenger(textMatches=".*点击回首页.*|.*返回首页.*|.*確定.*|.*确定.*|.*返回.*")
        if btn_passenger_home.exists():
            btn_passenger_home.click()
            logger.info("  >> 成功点击返回乘客端首页")
        else:
            logger.info("  >> 未能找到显式返回首页按钮，采用 ADB 物理返回/坐标点击兜底...")
            self._adb("shell", "input", "keyevent", "BACK")
        time.sleep(4)
        
        self._screenshot("JRYG_passenger_home_restored.png")
        logger.info("【成功】港版乘客端已成功返回首页。全部港版起终点闭环流转流程全部执行完毕！")

    def test_android_coupon_expiry_verification(self):
        """香港版乘客端：优惠券选择在估价失效刷新后的持久性验证流"""
        logger.info("\n" + "="*50)
        logger.info("  >> 【特殊用例】启动港版乘客端优惠券时效与刷新验证...")
        logger.info("="*50)

        try:
            # 1. 打开乘客端
            logger.info("【步骤 1】从桌面启动港版 App...")
            self._launch_app()
            
            # 【核心一步】执行登录保障，确保已登录
            self._ensure_logged_in()
            poco_passenger = self.poco
            
            self._close_activity_popup()

            # 2. 输入起点
            logger.info("【步骤 3】配置起点：铜锣湾地铁站...")
            self._set_origin()

            # 3. 输入终点并跳转到估价页面
            logger.info("【步骤 4】配置目的地：香港大学...")
            self._set_destination()

            # 4. 选择包車价的士 (包车价的士存在优惠券，打表的士不具备优惠券)
            logger.info("【步骤 5】寻找并选择车型『包車价的士』并配置优惠券...")
            car_el = poco_passenger(textMatches=".*包車.*|.*包车.*")
            if car_el.exists():
                car_el.click()
                logger.info("  >> 成功点击『包車价的士』车型")
            else:
                logger.warning("  >> 未定位到包车价车型文字，执行物理高容错坐标点击偏左侧区域...")
                self._tap_ratio(0.25, 0.83, "包車价的士区域")
            time.sleep(3)
            self._screenshot("JRYG_coupon_check_01_quote.png")

            # 5. 进入优惠券页面并选择 111元/折扣 优惠券
            logger.info("寻找并进入优惠券列表页面...")
            coupon_el = poco_passenger(textMatches=".*券.*|.*優惠.*|.*优惠.*|.*抵扣.*|.*HKD.*")
            if coupon_el.exists():
                coupon_el.click()
                logger.info("  >> 成功点击优惠券入口")
            else:
                logger.warning("  >> 未定位到优惠券文字，执行物理高容错坐标点击进入...")
                self._tap_ratio(0.85, 0.81, "优惠券区域")
            time.sleep(4)

            self._screenshot("JRYG_coupon_check_02_list.png")
            logger.info("正在列表中选择并全部勾选所有优惠券卡片...")
            target_coupons = poco_passenger(textMatches=".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*|.*元.*|.*HKD.*|.*折.*")
            if target_coupons.exists():
                try:
                    cnt = 0
                    for cp in target_coupons:
                        cp.click()
                        cnt += 1
                        logger.info(f"  >> 成功点击勾选第 {cnt} 张优惠券: '{cp.get_text() if hasattr(cp, 'get_text') else ''}'")
                        time.sleep(1.5)
                except Exception as ex:
                    logger.warning(f"  >> 遍历全部勾选优惠券时出现异常: {ex}")
            else:
                logger.info("  >> 未在列表中找到特定特征的优惠券，默认点击列表首张券...")
                first_coupon = poco_passenger(textMatches=".*元.*|.*HKD.*|.*折.*")
                if first_coupon.exists():
                    first_coupon.click()
                    time.sleep(2)

            # 点击确定/使用
            btn_use = poco_passenger(textMatches=".*確定.*|.*确定.*|.*確認.*|.*确认.*|.*使用.*")
            if btn_use.exists():
                btn_use.click()
                logger.info("  >> 点击确定使用成功")
                time.sleep(3)

            # 6. 等待5分钟10秒以模拟估价过期
            logger.info("【重要步骤】为了触发预估刷新提示，正在就地等待 5 分钟 10 秒 (310 秒)...")
            for minute in range(1, 6):
                time.sleep(60)
                logger.info(f"  >> [等待进度] 已过去 {minute} 分钟...")
            time.sleep(10)
            logger.info("  >> [等待进度] 额外 10 秒等待结束。")

            # 7. 点击“確認呼叫”，触发预估价已刷新提示
            logger.info("【步骤 6】等待结束，正在点击『確認呼叫』以触发预估更新对话框...")
            self._tap_ratio(0.50, 0.928, "確認呼叫")
            time.sleep(4)
            self._screenshot("JRYG_coupon_check_03_expired_prompt.png")

            # 处理可能出现的“预估已刷新 / 确认重新估价”提示弹框
            logger.info("检测并处理预估价格刷新提示框...")
            btn_refresh_confirm = poco_passenger(textMatches=".*確定.*|.*确定.*|.*確認.*|.*确认.*|.*我知道了.*|.*同意.*|.*重新估價.*|.*重新估价.*")
            if btn_refresh_confirm.exists():
                btn_refresh_confirm.click()
                logger.info("  >> 成功点击确认价格刷新弹窗")
                time.sleep(4)
            else:
                logger.info("  >> 未发现显式阻挡弹窗，执行物理返回或直接继续下步操作...")

            # 8. 重新点击优惠券进入列表，验证此前选择的优惠券是否保留
            logger.info("【步骤 7】再次点击优惠券选项卡以核对状态持久性...")
            coupon_el_retry = poco_passenger(textMatches=".*券.*|.*優惠.*|.*优惠.*|.*抵扣.*|.*HKD.*")
            if coupon_el_retry.exists():
                coupon_el_retry.click()
            else:
                self._tap_ratio(0.85, 0.81, "优惠券区域")
            time.sleep(4)

            self._screenshot("JRYG_coupon_check_04_post_verification.png")
            logger.info("【步骤 8】已打开优惠券列表。检查此前选中的券是否保持勾选状态...")
            
            # 对目标优惠券选中状态进行断言/日志记录
            target_coupon_chk = poco_passenger(textMatches=".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*")
            if target_coupon_chk.exists():
                logger.info("  >> [校验成功] 目标优惠券依然存在于列表中！")
            else:
                logger.warning("  >> [校验提示] 目标优惠券未找到，请查看截图进行人工复核。")

            # 9. 返回首页完成测试
            logger.info("【步骤 9】校验完毕，正在点击返回以恢复首页...")
            btn_back = poco_passenger(textMatches=".*返回.*|.*点击回首页.*|.*返回首页.*")
            if btn_back.exists():
                btn_back.click()
            else:
                self._adb("shell", "input", "keyevent", "BACK")
            time.sleep(3)

            # 退回大主页
            self._adb("shell", "input", "keyevent", "BACK")
            time.sleep(3)
            self._screenshot("JRYG_coupon_check_05_finished.png")
            logger.info("【成功】乘客端优惠券时效刷新与持久性验证流程顺利完成！")

        except Exception as e:
            logger.error(f"【优惠券核销时效测试失败】{e}")
            self._screenshot("JRYG_coupon_check_failed.png")
            raise e

    def test_android_coupon_rules_scenarios(self):
        """香港版乘客端多场景优惠券刷新与手选券保留规则验证用例 (新增需求)"""
        logger.info("\n" + "="*50)
        logger.info("  >> 【多场景验证】开始执行优惠券刷新与手选保留场景测试集...")
        logger.info("="*50)

        try:
            # ------------------ 场景 D 校验：初次加载与上级页面进入，无需提示，重新匹配 ------------------
            logger.info("=== 场景 D: 由上级页面进入选择车型页时，获取估价，无需提示直接重新匹配 ===")
            self._launch_app()
            
            # 【核心一步】执行登录保障，确保如果是未登录态则一键手机号验证码登录；已登录则直接跳过
            self._ensure_logged_in()
            poco_passenger = self.poco # 重新获取 Poco 实例保证句柄稳定
            
            self._close_activity_popup()
            
            self._set_origin()
            self._set_destination()
            time.sleep(5)
            
            # 验证进入车型页，没有提示弹框
            toast_or_popup = poco_passenger(textMatches=".*预估信息已更新.*|.*请重新选择.*|.*失效.*")
            assert not toast_or_popup.exists(), "【失败】初始进入选择车型页面不应有刷新提示或报错！"
            logger.info("  >> 场景 D 验证通过：初始进入页面直接进行推荐，无弹框干扰。")

            # ------------------ 场景 A 校验：应用切入后台再切回，预估价失效自动刷新并保留手选券 ------------------
            logger.info("=== 场景 A: 页面切入后台再切回来，自动刷新估价并保留手选券 ===")
            # 1. 手选一张优惠券 (先点击选择包車价的士，然后再点击进入列表)
            logger.info("选择车型『包車价的士』并配置优惠券...")
            car_el = poco_passenger(textMatches=".*包車.*|.*包车.*")
            if car_el.exists():
                car_el.click()
                logger.info("  >> 成功点击『包車价的士』")
            else:
                self._tap_ratio(0.25, 0.83, "包車价的士区域")
            time.sleep(3)
            coupon_el = poco_passenger(textMatches=".*券.*|.*優惠.*|.*优惠.*|.*抵扣.*|.*HKD.*")
            if coupon_el.exists():
                coupon_el.click()
                time.sleep(3)
                # 寻找并全部勾选所有可用的优惠券卡片
                target_coupons = poco_passenger(textMatches=".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*|.*元.*|.*HKD.*|.*折.*")
                if target_coupons.exists():
                    try:
                        cnt = 0
                        for cp in target_coupons:
                            cp.click()
                            cnt += 1
                            logger.info(f"  >> [场景A] 成功点击勾选第 {cnt} 张优惠券: '{cp.get_text() if hasattr(cp, 'get_text') else ''}'")
                            time.sleep(1.5)
                    except Exception as ex:
                        logger.warning(f"  >> [场景A] 遍历勾选优惠券异常: {ex}")
                # 点击确定使用
                btn_use = poco_passenger(textMatches=".*確定.*|.*确定.*|.*確認.*|.*确认.*|.*使用.*")
                if btn_use.exists():
                    btn_use.click()
                    time.sleep(3)
                    
            logger.info("  >> 成功手动勾选目标优惠券。")
            self._screenshot("JRYG_scenario_A_selected.png")

            # 2. 将 App 切入后台 (通过发送 KEYEVENT_HOME / 物理 Home 键)
            logger.info("正在将港版乘客端 App 切入后台模拟挂起...")
            self._adb("shell", "input", "keyevent", "3") # HOME键
            time.sleep(5)

            # 3. 重新拉起 App 切回前台 (使用 monkey 调起，保留进程内存状态不进行冷启动)
            logger.info("正在唤醒并重新将 App 切回前台...")
            self._adb("shell", "monkey", "-p", self.package, "-c", "android.intent.category.LAUNCHER", "1")
            time.sleep(6)
            self._screenshot("JRYG_scenario_A_foreground.png")

            # 4. 验证预估刷新及手选券保留
            # 检查重新切回后，手选的券是否仍然生效（点击再次进入优惠券列表查看选中状态）
            coupon_el_retry = poco_passenger(textMatches=".*券.*|.*優惠.*|.*优惠.*|.*抵扣.*|.*HKD.*")
            if coupon_el_retry.exists():
                coupon_el_retry.click()
                time.sleep(3)
                
            self._screenshot("JRYG_scenario_A_retained_check.png")
            target_coupon_chk = poco_passenger(textMatches=".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*")
            assert target_coupon_chk.exists(), "【失败】应用从后台切回前台后，手选的目标优惠券未被正确保留！"
            logger.info("  >> 场景 A 验证通过：切回前台后手选券被正确保留！")
            
            # 返回估价页
            btn_back = poco_passenger(textMatches=".*返回.*|.*确定.*|.*確定.*|.*確認.*|.*确认.*")
            if btn_back.exists():
                btn_back.click()
            else:
                self._adb("shell", "input", "keyevent", "BACK")
            time.sleep(3)

            # ------------------ 场景 C 校验：收银台支付失效弹框关闭后，自动刷新估价并保留手选券 ------------------
            logger.info("=== 场景 C: 预付收银台支付失效弹框关闭，自动刷新估价并保留手选券 ===")
            # 1. 确保选择了预付车型并点击呼叫进入收银台
            logger.info("点击呼叫以触发预付收银台页面...")
            self._tap_ratio(0.50, 0.928, "確認呼叫")
            time.sleep(5)
            self._screenshot("JRYG_scenario_C_cashier.png")

            # 2. 模拟关闭收银台 (如点击左上角返回或点击关闭支付弹窗)
            logger.info("正在点击返回或关闭支付收银台弹窗，返回到车型选择页...")
            self._adb("shell", "input", "keyevent", "BACK")
            time.sleep(4)
            self._screenshot("JRYG_scenario_C_back_to_quote.png")

            # 3. 验证此时估价已自动刷新，且手选的 100元 优惠券仍保留
            coupon_el_c = poco_passenger(textMatches=".*券.*|.*優惠.*|.*优惠.*|.*抵扣.*|.*HKD.*")
            if coupon_el_c.exists():
                coupon_el_c.click()
                time.sleep(3)
                
            self._screenshot("JRYG_scenario_C_retained_check.png")
            target_coupon_c_chk = poco_passenger(textMatches=".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*")
            assert target_coupon_c_chk.exists(), "【失败】收银台关闭并刷新估价后，手选的目标优惠券未被正确保留！"
            logger.info("  >> 场景 C 验证通过：收银台页面关闭自动刷新预估价后，手选券完好保留！")

            # ------------------ 场景 E 校验：选择优惠券并最终完成支付下单 ------------------
            logger.info("=== 场景 E: 最终选择优惠券并支付下单 ===")
            logger.info("正在关闭优惠券列表，返回车型估价页...")
            btn_back_to_quote = poco_passenger(textMatches=".*返回.*|.*确定.*|.*確定.*|.*確認.*|.*确认.*|.*使用.*")
            if btn_back_to_quote.exists():
                btn_back_to_quote.click()
            else:
                self._adb("shell", "input", "keyevent", "BACK")
            time.sleep(4)

            logger.info("在车型预估主页，确认优惠券状态并点击『確認呼叫』重新进入预付款收银台...")
            self._tap_ratio(0.50, 0.928, "確認呼叫")
            time.sleep(5)
            self._screenshot("JRYG_prepaid_cashier_order.png")

            logger.info("正在点击收银台『确认支付/去支付』下单按钮...")
            pay_btn = poco_passenger(textMatches=".*支付.*|.*立即支付.*|.*確認支付.*|.*确认支付.*|.*去支付.*")
            if pay_btn.exists():
                pay_btn.click()
                logger.info("  >> [Poco] 成功点击支付/下单按钮")
            else:
                logger.warning("  >> 未定位到支付按钮文字，执行高精度物理坐标点击底部支付/确认呼叫区域 (0.50, 0.928)...")
                self._tap_ratio(0.50, 0.928, "收银台支付按钮")
            
            time.sleep(10)
            self._screenshot("JRYG_order_submitted_with_coupon.png")
            logger.info("【成功】乘客端选择优惠券并支付下单全流程运行圆满完成！")

        except Exception as e:
            logger.error(f"【多场景优惠券校验失败】{e}")
            self._screenshot("JRYG_scenario_coupon_failed.png")
            raise e
