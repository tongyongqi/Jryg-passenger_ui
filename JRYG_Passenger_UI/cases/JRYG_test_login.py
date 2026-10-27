"""阳光出行香港乘客端登录自动化测试用例。

测试流程：
  1. 处理首次启动隐私协议弹窗（清除数据后出现，点击"同意"）
  2. 处理系统权限授权弹窗（点击"取消"跳过，不影响后续登录）
  3. 关闭可能出现的广告弹窗（多种方式兼容：resource_id / 坐标点击）
  4. 从游客首页导航到登录页：点击底部"我的"tab → 点击"登錄/註冊"
  5. 输入手机号（8 位香港号码，区号 +852）
  6. 勾选用户协议复选框
  7. 点击"取得驗證碼"按钮，进入验证码输入页
  8. 输入验证码（默认 123456），输入后自动登录回首页

前置条件：
  - 设备已通过 ADB 连接
  - Appium Server 已启动（默认 127.0.0.1:4723）
  - 测试数据 JSON 中包含 phone_number 和 verify_code 字段
  - 当前 App 版本为繁体中文香港版（包名 com.sunlightmobility.client）

预期结果：
  - 验证码输入后自动登录，回到乘客首页（YGAHomeActivity）
  - 首页元素 ll_start 可见，"我的"区域显示脱敏手机号

注意：
  - 该版本 App 使用繁体中文，按钮文字与大陆版不同
  - 验证码输入框无 resource_id，需通过容器定位 + ADB input text 输入
  - 登录态预校验：如果已在首页且已登录，直接跳过登录步骤
"""
import json
import time
import os
import sys
import subprocess

# 将项目根目录添加到 sys.path，确保 common 模块可被正确导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from selenium.common.exceptions import TimeoutException
from JRYG_Passenger_UI.common.JRYG_logger import logger
from JRYG_Passenger_UI.common.JRYG_config import SETTINGS, TEST_DATA_FILE
from JRYG_Passenger_UI.common.JRYG_connect_device import AndroidDevice


class TestJRYGLogin:
    """阳光出行乘客端登录相关测试用例类。

    前置条件：设备已连接、Appium Server 已启动、测试数据 JSON 中包含 phone_number 和 verify_code。
    预期结果：输入手机号 → 点击获取验证码 → 进入验证码输入页 → 输入验证码（默认123456） → 登录进入首页。
    """

    @classmethod
    def setup_class(cls):
        """类级 setup：创建 AndroidDevice 实例并连接 Appium Server。

        AndroidDevice 封装了 Appium WebDriver 的创建、ADB 启动 App、
        广告弹窗关闭等初始化逻辑，返回已就绪的 driver 实例。
        """
        cls.device = AndroidDevice()
        cls.driver = cls.device.connect()
        logger.info("【乘客端】Appium Session 已创建，开始执行登录测试")

    @classmethod
    def teardown_class(cls):
        """类级 teardown：断开 Appium Session，释放设备连接资源。"""
        cls.device.disconnect()
        logger.info("【乘客端】登录测试流程运行完毕，Session 已安全断开")

    def test_passenger_login(self):
        """测试：输入手机号 → 点击获取验证码 → 进入验证码输入页 → 输入验证码完成登录

        完整流程：
          隐私协议同意 → 权限弹窗跳过 → 关闭广告 → 导航至登录页 →
          输入手机号 → 勾选协议 → 点击取得验证码 → 输入验证码 → 自动登录回首页
        """
        # 从测试数据 JSON 加载手机号和验证码
        with open(TEST_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        phone = data["phone_number"]   # 香港号码 8 位，如 "56789012"
        code = data["verify_code"]     # 验证码默认 "123456"

        logger.info(f"正在进行登录，加载测试数据手机号: {phone}，验证码: {code}")
        pkg = SETTINGS['packages']['passenger']  # com.sunlightmobility.client

        # ==================== 登录态预校验 ====================
        # 如果已经处于首页且已登录（tv_mine_name 显示脱敏手机号含 *），直接通过测试
        # 避免重复登录操作，适用于已登录设备快速回归验证
        if self.device.is_element_present(self.device.by_id(f"{pkg}:id/ll_start")):
            mine_name = self.device.find_element(
                self.device.by_id(f"{pkg}:id/tv_mine_name"), timeout=2
            )
            if mine_name and "*" in mine_name.text:
                logger.info("【乘客端】检测到已处于登录状态（首页），跳过登录输入步骤，登录验证通过！")
                return

        # ==================== 步骤0: 前置弹窗处理 ====================
        # 0.1 处理首次启动隐私协议弹窗（清除数据后出现，按钮 ID=tv_button_agree）
        self._dismiss_privacy_dialog(pkg)

        # 0.2 处理系统权限授权弹窗（地理位置权限等，点击取消跳过）
        self._dismiss_permission_dialog(pkg)

        # 0.3 关闭可能出现的广告弹窗（广告关闭按钮可能无 resource_id，需坐标兼容）
        self._close_ad_if_present(pkg)

        # ==================== 步骤1: 导航到登录页 ====================
        # 从游客首页导航：点击底部"我的"tab → 侧边栏点击"登錄/註冊" → 进入登录页
        self._navigate_to_login(pkg)

        # ==================== 步骤2: 输入手机号 ====================
        # 手机号输入框 ID=phone_num，占位文字"請輸入手機號"
        phone_input = self.device.find_element(
            self.device.by_id(f"{pkg}:id/phone_num"), timeout=10
        )
        phone_input.click()
        phone_input.clear()
        time.sleep(0.5)
        # 使用 ADB input text 输入手机号（避免 Appium send_keys 的自动格式化问题，
        # 如自动插入空格 "5678 9012" 导致验证码按钮无法激活）
        self.device.driver.press_keycode(67)  # KEYCODE_DEL：删除可能残留的字符
        subprocess.run(
            ["adb", "-s", SETTINGS["device"]["udid"], "shell", "input", "text", phone],
            capture_output=True, timeout=10
        )
        time.sleep(1)
        logger.info(f"【乘客端】已输入手机号: {phone}")

        # ==================== 步骤3: 勾选用户协议复选框 ====================
        # 协议复选框 ID=agree_img，不勾选则"取得驗證碼"按钮不可用
        agree_checkbox = self.device.find_element(
            self.device.by_id(f"{pkg}:id/agree_img"), timeout=5
        )
        agree_checkbox.click()
        time.sleep(0.5)
        logger.info("【乘客端】已勾选用户协议")

        # ==================== 步骤4: 点击"取得驗證碼"按钮 ====================
        # 按钮在 rl_next 布局中，文字为"取得驗證碼"（繁体）
        btn_get_code = self.device.find_element(
            self.device.by_id(f"{pkg}:id/rl_next"), timeout=5
        )
        btn_get_code.click()
        logger.info("【乘客端】已点击获取验证码按钮")
        time.sleep(3)  # 等待页面跳转至验证码输入页

        # ==================== 步骤5: 验证已进入验证码输入页 ====================
        # 验证码页 Activity=YGUVerificationCodeActivity，标题文字"請輸入驗證碼"
        code_title = self.device.find_element(
            self.device.by_text("請輸入驗證碼"), timeout=10
        )
        logger.info("【乘客端】已进入验证码输入页，开始输入验证码")

        # ==================== 步骤6: 输入验证码 ====================
        # 验证码输入框在 verify_code RelativeLayout 内，是一个无 resource_id 的 EditText
        # 先点击验证码输入区域激活焦点，再通过 ADB input text 输入
        verify_container = self.device.find_element(
            self.device.by_id(f"{pkg}:id/verify_code"), timeout=5
        )
        verify_container.click()
        time.sleep(0.5)
        subprocess.run(
            ["adb", "-s", SETTINGS["device"]["udid"], "shell", "input", "text", code],
            capture_output=True, timeout=10
        )
        time.sleep(3)  # 等待验证码提交和页面跳转
        logger.info(f"【乘客端】已输入验证码: {code}")

        # ==================== 步骤7: 验证登录成功 ====================
        # 该版本验证码输入后自动登录，无需点击"登录"按钮
        # 断言回到首页（ll_start 元素可见）
        assert self.device.is_element_present(
            self.device.by_id(f"{pkg}:id/ll_start"), timeout=20
        ), "输入验证码后未自动登录进入乘客首页"
        logger.info("JRYG 乘客端登录后首页验证通过")

    # ==================== 私有辅助方法 ====================

    def _dismiss_privacy_dialog(self, pkg):
        """处理首次启动的隐私协议弹窗，点击同意按钮。

        清除 App 数据后首次启动会出现隐私协议弹窗（繁体"使用者協議與私隱政策"），
        按钮文本为"同意"，resource_id 为 tv_button_agree。
        如果不是首次启动（无弹窗），方法静默跳过。
        """
        try:
            agree_btn = self.device.find_element(
                self.device.by_id(f"{pkg}:id/tv_button_agree"), timeout=5
            )
            agree_btn.click()
            logger.info("【乘客端】已点击隐私协议同意按钮")
            time.sleep(2)
        except TimeoutException:
            pass  # 无弹窗，正常情况

    def _dismiss_permission_dialog(self, pkg):
        """处理系统权限授权弹窗，点击取消跳过。

        隐私协议同意后可能出现地理位置权限弹窗（繁体"地理位置權限"），
        点击"取消"按钮（tv_cancel）跳过授权，不影响后续登录流程。
        如果无弹窗则静默跳过。
        """
        try:
            cancel_btn = self.device.find_element(
                self.device.by_id(f"{pkg}:id/tv_cancel"), timeout=5
            )
            cancel_btn.click()
            logger.info("【乘客端】已跳过权限授权弹窗")
            time.sleep(2)
        except TimeoutException:
            pass  # 无权限弹窗

    def _close_ad_if_present(self, pkg):
        """关闭可能出现的广告弹窗（多种关闭方式兼容）。

        广告弹窗的关闭按钮在不同版本中 resource_id 可能不同，
        甚至可能没有 resource_id（仅 ImageView），因此采用三级降级策略：

        方式1：尝试通过已知的 resource_id 列表（iv_close / iv_cancel / close）定位关闭按钮
        方式2：检查底部"我的"tab 是否存在，存在则说明广告已关闭或无广告
        方式3：坐标点击广告关闭按钮（底部居中 ImageView，约屏幕高度 73% 处）
        """
        # 方式1：尝试通过 resource_id 关闭
        for close_id in ("iv_close", "iv_cancel", "close"):
            try:
                close_btn = self.device.find_element(
                    self.device.by_id(f"{pkg}:id/{close_id}"), timeout=2
                )
                close_btn.click()
                logger.info(f"【乘客端】已通过 {close_id} 关闭广告弹窗")
                time.sleep(1)
                return
            except TimeoutException:
                continue

        # 方式2：如果首页有底部 Tab 栏，说明广告已关闭或无广告，无需操作
        try:
            mine_tab = self.device.find_element(self.device.by_text("我的"), timeout=3)
            if mine_tab:
                return  # 底部 Tab 存在，无需关闭广告
        except TimeoutException:
            pass

        # 方式3：坐标点击广告关闭按钮（底部居中 ImageView，无 resource_id）
        try:
            size = self.device.driver.get_window_size()
            adb_udid = SETTINGS["device"]["udid"]
            subprocess.run(
                ["adb", "-s", adb_udid, "shell", "input", "tap",
                 str(size["width"] // 2), str(int(size["height"] * 0.73))],
                capture_output=True, timeout=5
            )
            logger.info("【乘客端】已通过坐标点击关闭广告弹窗")
            time.sleep(2)
        except Exception:
            pass  # 广告关闭失败不中断流程，后续导航步骤会再次尝试

    def _navigate_to_login(self, pkg):
        """从游客首页导航到登录页。

        该版本 App 的首页布局：
          - 底部 Tab 栏：首頁 / 優惠券 / 我的
          - 点击"我的"展开侧边抽屉栏
          - 抽屉栏顶部显示"登錄/註冊"（tv_mine_name），点击进入登录页

        登录页 Activity=YGULoginNewActivity，标题"歡迎登錄陽光出行"
        """
        # 点击底部"我的"tab，展开侧边抽屉栏
        mine_tab = self.device.find_element(self.device.by_text("我的"), timeout=10)
        mine_tab.click()
        time.sleep(2)

        # 点击"登錄/註冊"（tv_mine_name），进入登录页
        login_entry = self.device.find_element(
            self.device.by_id(f"{pkg}:id/tv_mine_name"), timeout=5
        )
        login_entry.click()
        time.sleep(2)
        logger.info("【乘客端】已从首页导航至登录页")


if __name__ == "__main__":
    # 支持直接运行：python -m pytest JRYG_test_login.py -v -s
    import pytest
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
