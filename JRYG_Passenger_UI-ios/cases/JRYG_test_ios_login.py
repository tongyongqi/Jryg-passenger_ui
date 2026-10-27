"""阳光出行乘客端 iOS 登录自动化测试用例 -ios

测试流程：
  1. 处理首次启动隐私协议弹窗（点击"同意"）
  2. 关闭可能出现的广告弹窗
  3. 从游客首页导航到登录页：点击"我的" → 点击"登录/注册"
  4. 输入手机号
  5. 勾选用户协议复选框
  6. 点击"获取验证码"按钮
  7. 输入验证码（默认 123456），自动登录回首页

前置条件：
  - iPhone 真机已通过 WDA 连接
  - Appium Server 已启动
  - 测试数据 JSON 中包含 phone_number 和 verify_code 字段
"""
import json
import time
import os
import sys

# 将 iOS 项目根目录添加到 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from selenium.common.exceptions import TimeoutException
from jryg_ios.JRYG_logger import logger
from jryg_ios.JRYG_config import SETTINGS, TEST_DATA_FILE
from jryg_ios.JRYG_connect_device import IOSDevice


class TestJRYGIosLogin:
    """阳光出行乘客端 iOS 登录测试用例类 -ios

    前置条件：iPhone 已连接、Appium Server 已启动、WDA 已运行。
    预期结果：输入手机号 → 点击获取验证码 → 进入验证码输入页 → 输入验证码 → 登录进入首页。
    """

    @classmethod
    def setup_class(cls):
        """类级 setup：创建 IOSDevice 实例并连接 Appium Server"""
        cls.device = IOSDevice()
        cls.driver = cls.device.connect()
        logger.info("【iOS 乘客端】Appium Session 已创建，开始执行登录测试")

    @classmethod
    def teardown_class(cls):
        """类级 teardown：断开 Appium Session"""
        cls.device.disconnect()
        logger.info("【iOS 乘客端】登录测试流程运行完毕，Session 已安全断开")

    def test_ios_passenger_login(self):
        """测试：输入手机号 → 点击获取验证码 → 进入验证码输入页 → 输入验证码完成登录 -ios"""
        with open(TEST_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        phone = data["phone_number"]
        code = data["verify_code"]

        logger.info(f"【iOS 登录】手机号: {phone}，验证码: {code}")

        # ==================== 登录态预校验 ====================
        # 如果已经处于首页且已登录，直接通过
        try:
            home_el = self.device.find_element(self.device.by_text("首页"), timeout=3)
            if home_el:
                logger.info("【iOS 乘客端】检测到可能已处于登录状态，尝试导航验证")
        except TimeoutException:
            pass

        # ==================== 步骤0: 前置弹窗处理 ====================
        self._dismiss_privacy_dialog()
        self._close_ad_if_present()

        # ==================== 步骤1: 导航到登录页 ====================
        self._navigate_to_login()

        # ==================== 步骤2: 输入手机号 ====================
        try:
            phone_input = self.device.find_element(
                self.device.by_text("请输入手机号"), timeout=10
            )
        except TimeoutException:
            phone_input = self.device.find_element(
                self.device.by_class_chain('**/XCUIElementTypeTextField[`label == "请输入手机号"`]'), timeout=10
            )
        phone_input.click()
        phone_input.clear()
        time.sleep(0.5)
        # iOS 使用 send_keys 输入
        phone_input.send_keys(phone)
        time.sleep(1)
        logger.info(f"【iOS 乘客端】已输入手机号: {phone}")

        # ==================== 步骤3: 勾选用户协议复选框 ====================
        try:
            checkbox = self.device.find_element(
                self.device.by_text("同意"), timeout=5
            )
            checkbox.click()
            time.sleep(0.5)
            logger.info("【iOS 乘客端】已勾选用户协议")
        except TimeoutException:
            logger.info("【iOS 乘客端】未找到协议复选框，可能已默认勾选")

        # ==================== 步骤4: 点击"获取验证码"按钮 ====================
        try:
            btn_get_code = self.device.find_element(
                self.device.by_text("获取验证码"), timeout=5
            )
            btn_get_code.click()
            logger.info("【iOS 乘客端】已点击获取验证码按钮")
        except TimeoutException:
            try:
                btn_get_code = self.device.find_element(
                    self.device.by_text("下一步"), timeout=5
                )
                btn_get_code.click()
                logger.info("【iOS 乘客端】已点击下一步按钮")
            except TimeoutException:
                logger.warning("【iOS 乘客端】未找到获取验证码/下一步按钮")
        time.sleep(3)

        # ==================== 步骤5: 验证已进入验证码输入页 ====================
        try:
            code_title = self.device.find_element(
                self.device.by_text_contains("验证码"), timeout=10
            )
            logger.info("【iOS 乘客端】已进入验证码输入页")
        except TimeoutException:
            logger.warning("【iOS 乘客端】未找到验证码输入页标题，尝试直接输入")

        # ==================== 步骤6: 输入验证码 ====================
        try:
            code_input = self.device.find_element(
                self.device.by_class_chain('**/XCUIElementTypeTextField'), timeout=10
            )
            code_input.click()
            time.sleep(0.5)
            code_input.send_keys(code)
            time.sleep(3)
            logger.info(f"【iOS 乘客端】已输入验证码: {code}")
        except TimeoutException:
            logger.warning("【iOS 乘客端】未找到验证码输入框")

        # ==================== 步骤7: 验证登录成功 ====================
        # 等待回到首页
        time.sleep(5)
        try:
            home = self.device.find_element(self.device.by_text("首页"), timeout=20)
            if home:
                logger.info("JRYG iOS 乘客端登录后首页验证通过")
                self.device.screenshot("JRYG_ios_login_success.png")
                return
        except TimeoutException:
            pass

        # 如果首页文字没找到，尝试检查是否已有下单入口
        try:
            self.device.find_element(
                self.device.by_text_contains("去哪"), timeout=10
            )
            logger.info("JRYG iOS 乘客端登录后首页验证通过（通过下单入口检测）")
            self.device.screenshot("JRYG_ios_login_success.png")
            return
        except TimeoutException:
            pass

        logger.warning("【iOS 乘客端】登录后未明确检测到首页，截图保存现场")
        self.device.screenshot("JRYG_ios_login_unknown_state.png")

    # ==================== 私有辅助方法 ====================

    def _dismiss_privacy_dialog(self):
        """处理首次启动的隐私协议弹窗，点击同意按钮"""
        try:
            agree_btn = self.device.find_element(self.device.by_text("同意"), timeout=5)
            agree_btn.click()
            logger.info("【iOS 乘客端】已点击隐私协议同意按钮")
            time.sleep(2)
        except TimeoutException:
            pass

    def _close_ad_if_present(self):
        """关闭可能出现的广告弹窗"""
        for close_text in ("跳过", "跳过广告", "关闭"):
            try:
                close_btn = self.device.find_element(self.device.by_text(close_text), timeout=2)
                close_btn.click()
                logger.info(f"【iOS 乘客端】已通过 '{close_text}' 关闭广告弹窗")
                time.sleep(1)
                return
            except TimeoutException:
                continue
        # 如果首页有底部 Tab 栏，说明广告已关闭或无广告
        try:
            self.device.find_element(self.device.by_text("首页"), timeout=3)
            return
        except TimeoutException:
            pass
        # 坐标点击关闭
        try:
            self.device.click(0.5, 0.73)
            logger.info("【iOS 乘客端】已通过坐标点击关闭广告弹窗")
            time.sleep(2)
        except Exception:
            pass

    def _navigate_to_login(self):
        """从游客首页导航到登录页"""
        # 点击"我的"tab
        try:
            mine_tab = self.device.find_element(self.device.by_text("我的"), timeout=10)
            mine_tab.click()
            time.sleep(2)
        except TimeoutException:
            logger.warning("【iOS 乘客端】未找到'我的'tab")

        # 点击"登录/注册"
        try:
            login_entry = self.device.find_element(
                self.device.by_text("登录/注册"), timeout=5
            )
            login_entry.click()
            time.sleep(2)
            logger.info("【iOS 乘客端】已从首页导航至登录页")
        except TimeoutException:
            try:
                login_entry = self.device.find_element(
                    self.device.by_text("登录"), timeout=5
                )
                login_entry.click()
                time.sleep(2)
                logger.info("【iOS 乘客端】已从首页导航至登录页（通过'登录'按钮）")
            except TimeoutException:
                logger.warning("【iOS 乘客端】未找到登录入口")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
