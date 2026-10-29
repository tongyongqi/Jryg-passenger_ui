"""
港版阳光出行 Android 乘客端 —— 公共基础方法（Base Class）
==============================================================================
所有 Android 测试用例继承此类，共享设备连接、地址搜索、车型选择、截图等公共操作。

模块结构说明：
    - setup_class        ：类级初始化，建立 ADB / Poco 连接并缓存设备信息。
    - ADB 操作段         ：设备状态、屏幕尺寸、当前 Activity、坐标点击、截图等底层能力。
    - App 启动与登录段   ：权限授予、App 冷启动、弹窗关闭、登录态检测与一键登录。
    - 地址搜索段         ：起点/目的地的输入与候选结果选择。
    - 底层辅助段         ：基于 uiautomator dump 的文本/控件坐标点击。

坐标说明：
    文件中出现的绝对坐标（如 661,477 / 617,821 / 586,1042 / 586,865）均为
    兜底坐标，对应 1080x2700 分辨率下的控件中心点，仅在 Poco 控件树定位
    失败时启用，因此与元素常量的相对比例定位相比优先级更低。
==============================================================================
"""

import os
import re
import sys
import time
import subprocess

import pytest
from airtest.core.api import connect_device, text as airtest_text
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

# 项目根目录（JRYG_Passenger_UI_HK-android），用于定位 screenshots 等资源目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 将项目根加入模块搜索路径，保证 `jryg_hk_android` 包可被导入
sys.path.append(BASE_DIR)

from jryg_hk_android.JRYG_config import SETTINGS
from jryg_hk_android.JRYG_logger import logger
from jryg_hk_android import JRYG_android_elements as E


class AndroidBase:
    """Android 自动化测试公共基类，提供设备连接与通用操作封装。

    子类通过继承获得以下能力：
        - setup_class 中建立的 ``udid`` / ``package`` / ``activity`` /
          ``width`` / ``height`` / ``poco`` 类属性；
        - ADB 设备查询与坐标点击、截图能力；
        - App 冷启动、登录态保障、地址搜索等业务级操作。

    设计要点：
        所有界面操作均优先使用 Poco 控件树定位；只有在控件树不可用时
        才回退到 ADB 坐标点击或 uiautomator dump 文本匹配，保证在控件
        ID 缺失或多语言场景下仍能推进流程。
    """

    @classmethod
    def setup_class(cls):
        """初始化 ADB 连接、Poco 控件树驱动。

        执行顺序：校验设备在线 → 读取分辨率 → 建立 Airtest 设备连接 →
        创建 Poco 控件树驱动。

        :raises pytest.fail.Exception: 设备未就绪（adb get-state 非 device）时直接失败。
        :raises AssertionError: 无法解析屏幕尺寸时抛出。
        """
        # 设备唯一标识、乘客端包名与启动 Activity，均来自 JRYG_settings.yaml
        cls.udid = SETTINGS["device"]["udid"]
        cls.package = SETTINGS["packages"]["passenger_hk"]
        cls.activity = SETTINGS["packages"]["passenger_hk_activity"]
        # 设备必须处于 device 状态（online/unauthorized 均视为不可用）
        cls._ensure_device_online()
        # 缓存分辨率，供相对比例坐标换算使用
        cls.width, cls.height = cls._screen_size()
        # 通过 Airtest 建立设备连接（127.0.0.1:5037 为 adb server 默认端口）
        connect_device(f"android://127.0.0.1:5037/{cls.udid}")
        # 使用 UiAutomation2 驱动获取控件树；关闭每步截图以提升执行速度
        cls.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        logger.info(f"【初始化】Android 设备已连接，分辨率: {cls.width}x{cls.height}")

    # ==================== ADB 操作 ====================

    @classmethod
    def _adb(cls, *args, timeout=30, check=True):
        """执行 ADB 命令并返回标准输出。

        :param args: ADB 子命令及参数，例如 ``("shell", "wm", "size")``。
        :param timeout: 命令超时时间（秒），默认 30。
        :param check: 为 True 时，命令返回码非 0 立即抛错；为 False 时忽略失败。
        :return: 命令的标准输出文本。
        :raises RuntimeError: check 为 True 且命令执行失败时抛出，错误信息含命令与 stderr。
        :raises subprocess.TimeoutExpired: 命令执行超时时由 subprocess 抛出。
        """
        # 固定附加 -s <udid>，保证操作的是目标设备而非默认设备
        command = ["adb", "-s", cls.udid, *args]
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if check and result.returncode != 0:
            raise RuntimeError(f"ADB 命令失败: {' '.join(command)}\n{result.stderr}")
        return result.stdout

    @classmethod
    def _ensure_device_online(cls):
        """确认目标设备处于可用状态。

        :raises pytest.fail.Exception: 设备状态不是 device 时直接终止用例。
        """
        state = cls._adb("get-state").strip()
        if state != "device":
            pytest.fail(f"Android 设备未就绪: {cls.udid}, state={state}")

    @classmethod
    def _screen_size(cls):
        """读取设备物理分辨率。

        :return: (宽, 高) 的整数元组。
        :raises AssertionError: 输出中无法解析出 "宽x高" 格式时抛出。
        """
        # `wm size` 输出形如 "Physical size: 1080x2700"
        output = cls._adb("shell", "wm", "size")
        matches = re.findall(r"(\d+)x(\d+)", output)
        if not matches:
            raise AssertionError(f"无法读取屏幕尺寸: {output}")
        # 取最后一个匹配项，规避输出中同时存在 Override size 的情况
        width, height = matches[-1]
        return int(width), int(height)

    @classmethod
    def _current_activity(cls):
        """获取当前前台 Activity 名称。

        :return: mFocusedApp 行内容（包含包名与 Activity 名）；无前台信息时返回空字符串。
        """
        output = cls._adb("shell", "dumpsys", "window", timeout=15)
        focused = [line.strip() for line in output.splitlines() if "mFocusedApp=" in line]
        # 正常情况下仅有一行，取最后一行兼容多窗口场景
        return focused[-1] if focused else ""

    def _wait_activity(self, keyword, timeout=15):
        """等待前台 Activity 包含指定关键字。

        :param keyword: 期望出现在 Activity 名中的关键字。
        :param timeout: 最长等待时间（秒），默认 15。
        :return: 命中的 Activity 文本；超时则返回最后一次读取的 Activity。
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            activity = self._current_activity()
            if keyword in activity:
                return activity
            time.sleep(1)
        # 超时后返回当前 Activity，由调用方判断是否失败
        return self._current_activity()

    def _tap_ratio(self, x_ratio, y_ratio, name=""):
        """按屏幕比例换算坐标并点击。

        使用比例而非绝对坐标，可在不同分辨率设备上复用同一套脚本。

        :param x_ratio: 横坐标比例，取值 0~1。
        :param y_ratio: 纵坐标比例，取值 0~1。
        :param name: 目标控件名称，仅用于日志输出。
        """
        x = int(self.width * x_ratio)
        y = int(self.height * y_ratio)
        self._adb("shell", "input", "tap", str(x), str(y))
        logger.info(f"  >> 已点击{name}: ({x}, {y})")

    def _screenshot(self, filename):
        """截取当前屏幕并保存到 screenshots 目录。

        :param filename: 保存文件名（不含目录）。
        :return: 截图文件的绝对路径。
        :raises AssertionError: ADB 返回码非 0 或文件过小（<1KB，说明截图为空）时抛出。
        """
        path = os.path.join(BASE_DIR, "screenshots", filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # exec-out 直接将二进制图片流输出到文件，避免 pull 过程的中转开销
        with open(path, "wb") as image_file:
            result = subprocess.run(
                ["adb", "-s", self.udid, "exec-out", "screencap", "-p"],
                stdout=image_file, stderr=subprocess.PIPE, timeout=30,
            )
        # 文件过小通常意味着截图内容为空（如设备息屏），同样视为失败
        if result.returncode != 0 or os.path.getsize(path) < 1024:
            raise AssertionError(f"截图失败: {path}")
        logger.info(f"  >> 截图已保存: {path}")
        return path

    # ==================== App 启动与登录 ====================

    def _grant_permissions(self):
        """授予位置与通知权限，避免启动后被系统权限弹窗打断流程。

        使用 check=False 授予：部分设备或系统版本上重复授予会返回非 0，
        该情况属于预期，不应中断流程。
        """
        permissions = (
            "android.permission.ACCESS_FINE_LOCATION",     # 精确定位：下单与行程定位必需
            "android.permission.ACCESS_COARSE_LOCATION",   # 粗略定位：定位兜底
            "android.permission.POST_NOTIFICATIONS",       # 通知权限：接单/派单提醒
        )
        for perm in permissions:
            self._adb("shell", "pm", "grant", self.package, perm, check=False)

    def _launch_app(self):
        """冷启动乘客端 App 并等待其进入前台。

        流程：授予权限 → force-stop 结束旧进程 → am start 启动 →
        轮询前台 Activity → 重建 Poco 控件树。

        :raises AssertionError: 超时后前台 Activity 仍不属于目标包时抛出。
        """
        self._grant_permissions()
        # 先结束旧进程，保证每次都是冷启动，状态可控
        self._adb("shell", "am", "force-stop", self.package)
        # -W 参数等待启动完成，便于判断启动是否成功
        self._adb("shell", "am", "start", "-W", "-n", f"{self.package}/{self.activity}")
        for _ in range(15):
            activity = self._current_activity()
            if self.package in activity:
                logger.info(f"  >> App 已启动: {activity}")
                time.sleep(3)
                # 冷启动后旧的控件树句柄失效，需重建 Poco 实例
                self.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
                # 等待首页数据加载完成
                time.sleep(5)
                return
            time.sleep(1)
        activity = self._current_activity()
        if self.package not in activity:
            raise AssertionError(f"App 启动失败: {activity}")
        self.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        time.sleep(5)

    def _close_activity_popup(self):
        """关闭首页可能出现的活动营销弹框。

        通过 dumpsys window 检测 PopupWindow 存在，再点击固定比例位置的关闭按钮。
        """
        output = self._adb("shell", "dumpsys", "window", timeout=15)
        if "PopupWindow" in output:
            # 0.50/0.747 为弹框右上角关闭按钮在 1080x2700 下的相对位置
            self._tap_ratio(0.50, 0.747, "活动弹框关闭按钮")
            time.sleep(2)

    def _detect_current_state(self):
        """检测当前登录/业务状态。

        判定分两层：
            第一层按控件文本精确匹配（快，覆盖常见弹窗与登录页）；
            第二层遍历全部 TextView 拼接成文本再匹配（慢，覆盖控件树
            结构异常、文本被拆分到子节点的情况）。

        :return: 状态字符串，取值范围：
            launcher / privacy_agreement / permission_dialog /
            system_location_permission / login_code_input /
            login_phone_input / mine_unlogged / home_logged /
            home_unlogged / unknown。
        """
        activity = self._current_activity().lower()
        # 不在乘客端前台，说明 App 未启动
        if self.package not in activity:
            return "launcher"

        # 第一层：精确匹配关键控件文本
        # 隐私协议弹窗：同时存在"同意"与"不同意"才判定，避免误伤普通页面
        if self.poco(text=E.TEXT_AGREE).exists() and self.poco(text=E.TEXT_DISAGREE).exists():
            return "privacy_agreement"
        # 应用内权限引导弹窗
        if self.poco(text=E.TEXT_GO_AUTH).exists() and self.poco(text=E.TEXT_CANCEL).exists():
            return "permission_dialog"
        # 系统级定位权限弹窗
        if self.poco(text=E.TEXT_ALLOW_LOCATION).exists() or self.poco(text=E.TEXT_ALLOW_LOCATION_ALT).exists():
            return "system_location_permission"
        # 验证码输入页
        if self.poco(text=E.TEXT_INPUT_CODE).exists() or self.poco(textMatches=E.TEXT_REGET_CODE_REGEX).exists():
            return "login_code_input"
        # 手机号输入页
        if self.poco(text=E.TEXT_INPUT_PHONE).exists() or self.poco(text=E.TEXT_GET_CODE).exists():
            return "login_phone_input"
        # "我的"页未登录（存在登录/注册入口）
        if self.poco(text=E.TEXT_LOGIN_REGISTER).exists():
            return "mine_unlogged"

        # 第二层：遍历 TextView 拼接文本后做包含匹配（兜底）
        texts = []
        try:
            for el in self.poco(type="android.widget.TextView"):
                t = el.get_text()
                if t:
                    texts.append(t.strip())
        except Exception:
            # 遍历控件树异常时忽略，走后续文本兜底判断
            pass
        joined = " ".join(texts)

        if "歡迎登錄" in joined or E.TEXT_INPUT_PHONE in joined:
            return "login_phone_input"
        if E.TEXT_INPUT_CODE in joined:
            return "login_code_input"
        if E.TEXT_LOGIN_REGISTER in joined:
            return "mine_unlogged"
        if "想要去哪裡？" in joined:
            # 首页占位文案存在时，用手机号尾号或掩码判断登录态
            if "1727" in joined or "****" in joined:
                return "home_logged"
            return "home_unlogged"
        return "unknown"

    def _ensure_logged_in(self):
        """保障登录：检查登录态，未登录则执行一键登录，最后切回首页。

        登录步骤依次为：进入"我的"页 → 点击登录/注册 → 输入手机号 →
        勾选隐私协议 → 获取验证码 → 输入验证码（默认验证码 123456）。

        :return: None。流程异常会通过 AssertionError / RuntimeError 中断。
        """
        logger.info(f"【登录校验】预备手机号: {E.LOGIN_PHONE_NUMBER}")
        self._close_activity_popup()

        # 进入"我的"页，登录入口在该页
        btn_mine = self.poco(text="我的")
        if btn_mine.exists():
            btn_mine.click()
        else:
            self._tap_by_text("我的")
        time.sleep(5)

        # 轮询判断当前是否已登录：出现"登录/注册"即为未登录，
        # 出现手机号尾号/掩码/会员等文案即为已登录
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

            if E.TEXT_LOGIN_REGISTER in joined:
                logged_in = False
                break
            elif "1727" in joined or "****" in joined or "會員" in joined or "会员" in joined or "我的行程" in joined:
                logged_in = True
                break
            time.sleep(1)

        if not logged_in:
            logger.info("  >> 未登录，执行登录流程...")
            # 点击"登录/注册"按钮；控件树未命中时回退到固定坐标
            btn_login = self.poco(text=E.TEXT_LOGIN_REGISTER)
            if not btn_login.exists():
                btn_login = self.poco(E.MINE_NAME_ID)
            if btn_login.exists():
                btn_login.click()
            else:
                # 兜底坐标：1080x2700 下"登录/注册"入口中心
                self._adb("shell", "input", "tap", "661", "477")
            time.sleep(4)

            # 输入手机号：优先通过控件树 set_text（可正确处理中文输入法），
            # 否则用 ADB 坐标聚焦 + input text 兜底
            et_phone = self.poco(E.PHONE_INPUT_ID)
            if et_phone.exists():
                et_phone.click()
                time.sleep(0.5)
                et_phone.set_text(E.LOGIN_PHONE_NUMBER)
            else:
                # 兜底坐标：手机号输入框中心
                self._adb("shell", "input", "tap", "617", "821")
                time.sleep(0.5)
                self._adb("shell", "input", "text", E.LOGIN_PHONE_NUMBER)
            time.sleep(1.5)

            # 勾选隐私协议复选框，否则无法获取验证码
            self._tap_checkbox()
            time.sleep(1)

            # 点击"获取验证码"
            btn_code = self.poco(E.GET_CODE_BTN_ID)
            if btn_code.exists():
                btn_code.click()
            else:
                # 兜底坐标："取得驗證碼"按钮中心
                self._adb("shell", "input", "tap", "586", "1042")
            time.sleep(4)

            # 输入验证码，港版测试环境固定验证码为 123456
            et_code = self.poco(E.VERIFY_CODE_INPUT_ID)
            if et_code.exists():
                et_code.click()
                time.sleep(0.5)
                et_code.set_text(E.LOGIN_VERIFY_CODE)
            else:
                # 兜底坐标：验证码输入框中心
                self._adb("shell", "input", "tap", "586", "865")
                time.sleep(0.5)
                self._adb("shell", "input", "text", E.LOGIN_VERIFY_CODE)
            time.sleep(6)
        else:
            logger.info("  >> 已登录，跳过")

        # 切回首页：底部 Tab 的"首页"入口，最多尝试 3 次
        for i in range(3):
            btn_home = self.poco(E.TAB_HOME_ID)
            if btn_home.exists():
                btn_home[0].click()
            else:
                self._adb("shell", "input", "tap", str(E.HOME_TAB_COORD[0]), str(E.HOME_TAB_COORD[1]))
            time.sleep(4)
            # 出现起点栏或目的地文案即认为已回到首页
            if self.poco(E.START_ADDRESS_ID).exists() or self.poco(text=E.DEST_TEXT).exists():
                break
        # 切页后控件树句柄需重建
        self.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        time.sleep(2)

    # ==================== 地址搜索 ====================

    def _input_text(self, value):
        """在地址搜索框中输入关键词。

        先按已知控件 ID 定位输入框；若控件树未就绪则按 EditText 类型匹配；
        两者均失败时回退到点击搜索栏后使用 Airtest 文本输入。

        :param value: 待输入的地址关键词。
        :return: None
        """
        et_search = None
        # 最多等待 15 秒搜索框出现（页面切换较慢时需要重试）
        for i in range(15):
            el = self.poco(E.SEARCH_INPUT_ID)
            if el.exists():
                et_search = el
                break
            # 兜底：按控件类型匹配任意 EditText
            el_type = self.poco(typeMatches=".*EditText.*")
            if el_type.exists():
                et_search = el_type
                break
            time.sleep(1)

        if et_search:
            et_search.set_text(value)
            logger.info(f"  >> 已输入: {value}")
        else:
            # 最终兜底：点击搜索栏位置后用 Airtest 键盘输入
            self._tap_ratio(0.50, 0.15, "搜索栏")
            time.sleep(2)
            airtest_text(value, enter=False)
        time.sleep(5)

    def _select_first_search_result(self, fallback_x, fallback_y, name):
        """选择搜索结果列表中的第一项。

        :param fallback_x: 控件树定位失败时使用的横坐标比例。
        :param fallback_y: 控件树定位失败时使用的纵坐标比例。
        :param name: 目标地址名称，仅用于日志输出。
        :return: None
        """
        first_item = None
        # 等待搜索结果渲染，最多 10 秒
        for _ in range(10):
            el = self.poco(E.SEARCH_RESULT_TITLE_ID)
            if el.exists():
                first_item = el
                break
            time.sleep(1)

        if first_item:
            try:
                # 多数情况下返回的是列表代理对象，需取第 0 项
                first_item[0].click()
            except Exception:
                # 单元素场景直接点击
                first_item.click()
            logger.info(f"  >> 选中: {name}")
        else:
            # 兜底：按比例坐标点击第一条结果
            self._tap_ratio(fallback_x, fallback_y, name)

    def _set_origin(self):
        """设置行程起点为默认出发地址（铜锣湾地铁站）。"""
        logger.info("点击起点栏位...")
        tv_start = self.poco(E.START_ADDRESS_ID)
        if tv_start.exists():
            tv_start.click()
        else:
            # 兜底坐标：首页起点栏位中心
            self._tap_ratio(0.50, 0.742, "出发地址")
        time.sleep(3)
        self._input_text(E.DEFAULT_START_ADDRESS)
        # 留存搜索结果截图，便于失败时核对候选列表
        self._screenshot("JRYG_android_02_origin_results.png")
        self._select_first_search_result(0.50, 0.149, "铜锣湾地铁站")
        time.sleep(6)
        self._close_activity_popup()

    def _set_destination(self):
        """设置行程目的地为默认到达地址（香港大学）。"""
        logger.info("点击目的地栏位...")
        # 目的地栏位可能以文案、ID 或外层容器三种形式出现，依次尝试
        tv_dest = self.poco(text=E.DEST_TEXT)
        if not tv_dest.exists():
            tv_dest = self.poco(E.DEST_ID)
        if not tv_dest.exists():
            tv_dest = self.poco(E.DEST_LAYOUT_ID)

        if tv_dest.exists():
            tv_dest.click()
        else:
            # 兜底坐标：首页目的地栏位中心
            self._tap_ratio(0.50, 0.812, "目的地")
        time.sleep(3)
        self._input_text(E.DEFAULT_END_ADDRESS)
        self._screenshot("JRYG_android_03_destination_results.png")
        self._select_first_search_result(0.34, 0.153, "香港大学")
        # 目的地选择后需等待路线规划与价格计算，留出更长等待
        time.sleep(10)

    # ==================== 底层辅助 ====================

    def _tap_by_text(self, target_text):
        """通过 adb dump 查找文本并点击其中心坐标。

        用于 Poco 控件树无法定位的场景（如自定义 View 未暴露文本节点）。

        :param target_text: 目标控件显示文本。
        :return: 命中并点击返回 True；未找到返回 False。
        """
        # dump 当前界面层级到设备临时文件
        self._adb("shell", "uiautomator", "dump", "/sdcard/_temp.xml", check=False)
        path = os.path.join(BASE_DIR, "screenshots", "_temp.xml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # 将层级文件拉取到本地
        with open(path, "wb") as f:
            subprocess.run(["adb", "-s", self.udid, "exec-out", "cat", "/sdcard/_temp.xml"], stdout=f)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            # 匹配同时含目标 text 与 bounds 的节点，取 bounds 中心点
            pattern = r'text="' + re.escape(target_text) + r'"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            match = re.search(pattern, content)
            if match:
                x1, y1, x2, y2 = map(int, match.groups())
                self._adb("shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2))
                return True
        return False

    def _tap_checkbox(self):
        """点击隐私条款 CheckBox。

        复选框本身通常无可见文本，需借助相邻的协议文案节点的 bounds，
        向左偏移 35 像素落到复选框上。
        """
        self._adb("shell", "uiautomator", "dump", "/sdcard/_temp.xml", check=False)
        path = os.path.join(BASE_DIR, "screenshots", "_temp.xml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            subprocess.run(["adb", "-s", self.udid, "exec-out", "cat", "/sdcard/_temp.xml"], stdout=f)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            # 匹配协议文案节点（正则前缀用于容纳尾部"我已閱讀並同意"等变体）
            pattern = r'text="' + re.escape(E.AGREE_CHECKBOX_TEXT) + r'[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            match = re.search(pattern, content)
            if match:
                x1, y1, x2, y2 = map(int, match.groups())
                # 复选框位于文案左侧，横坐标左移 35 像素
                self._adb("shell", "input", "tap", str(x1 - 35), str((y1+y2)//2))
