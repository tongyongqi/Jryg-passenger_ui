"""阳光出行乘客端 iOS 设置页面功能验证测试用例 -ios

验证设置页面各功能入口可正常打开和返回。
对应安卓端 JRYG_test_settings.py 的简化版本。

前置条件：
  - iPhone 真机已连接
  - 乘客端 App 已登录
"""
import time
import os
import sys

import pytest

# 将 iOS 项目根目录添加到 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from jryg_ios.JRYG_logger import logger
from jryg_ios.JRYG_config import SETTINGS
from jryg_ios.JRYG_connect_device import IOSDevice

from selenium.common.exceptions import TimeoutException


class TestJRYGIosSettings:
    """阳光出行 iOS 设置页面功能验证 -ios"""

    @classmethod
    def setup_class(cls):
        """类级初始化：连接设备并导航至设置页面"""
        cls.device = IOSDevice()
        cls.driver = cls.device.connect()
        cls.flow_errors = []
        logger.info("【iOS 设置测试】设备连接完毕")

    @classmethod
    def teardown_class(cls):
        """类级 teardown"""
        cls.device.disconnect()
        logger.info("【iOS 设置测试】流程结束")

    def test_ios_settings_navigation(self):
        """验证设置页面可正常进入和返回 -ios

        流程：首页 → 我的 → 齿轮 → 设置页面 → 逐个验证功能入口
        """
        steps = [
            ("隐私中心入口", self._check_privacy_entry),
            ("常用地址入口", self._check_address_entry),
            ("支付方式入口", self._check_payment_entry),
            ("版本信息", self._check_version),
            ("清除缓存", self._check_cache),
        ]

        # 先导航到设置页面
        self._navigate_to_settings()

        errors = []
        for label, method in steps:
            error = None
            try:
                self._return_to_settings()
                method()
                logger.info(f"【iOS 设置测试】{label} 通过")
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                self.device.screenshot(f"JRYG_ios_settings_{label}_failed.png")
                logger.error(f"【iOS 设置测试】{label} 失败: {error}")
            if error:
                errors.append(f"{label}: {error}")

            # 返回设置主页
            try:
                self._return_to_settings()
            except Exception:
                pass

        if errors:
            pytest.fail(f"{len(errors)}/{len(steps)} 项失败:\n" + "\n".join(errors))

    def _navigate_to_settings(self):
        """从 App 首页导航至设置页面：首页 → 我的 → 齿轮 → 设置"""
        logger.info("【iOS 设置导航】开始导航至设置页面")

        # 关闭广告弹窗
        for close_text in ("跳过", "跳过广告", "关闭", "我知道了"):
            try:
                close_btn = self.device.find_element(self.device.by_text(close_text), timeout=3)
                close_btn.click()
                time.sleep(1)
                break
            except TimeoutException:
                continue

        # 点击"我的"
        try:
            mine_tab = self.device.find_element(self.device.by_text("我的"), timeout=10)
            mine_tab.click()
            time.sleep(2)
        except TimeoutException:
            logger.warning("【iOS 设置导航】未找到'我的'tab")

        # 点击齿轮/设置图标
        for label in ("设置", "齿轮"):
            try:
                setting_btn = self.device.find_element(self.device.by_text(label), timeout=5)
                setting_btn.click()
                time.sleep(2)
                logger.info(f"【iOS 设置导航】已点击 {label}")
                return
            except TimeoutException:
                continue

        # 尝试通过 accessibility id
        try:
            setting_btn = self.device.find_element(
                self.device.by_id("setting"), timeout=5
            )
            setting_btn.click()
            time.sleep(2)
            logger.info("【iOS 设置导航】已通过 accessibility id 点击设置")
            return
        except TimeoutException:
            pass

        logger.warning("【iOS 设置导航】未找到设置入口，尝试直接验证当前页面")

    def _return_to_settings(self):
        """返回设置主页"""
        for _ in range(5):
            if self._is_settings_page():
                return
            # 尝试点击设置标签
            try:
                setting = self.device.find_element(self.device.by_text("设置"), timeout=3)
                setting.click()
                time.sleep(1)
                continue
            except TimeoutException:
                pass
            # 返回键
            self.driver.navigate().back()
            time.sleep(1)

    def _is_settings_page(self):
        """判断当前是否在设置页面"""
        return self._has_text("设置") and (
            self._has_text("隐私中心") or
            self._has_text("常用地址") or
            self._has_text("清除缓存")
        )

    def _has_text(self, text):
        """检查页面是否包含指定文本"""
        try:
            return self.device.is_element_present(self.device.by_text(text), timeout=2)
        except Exception:
            return False

    def _check_privacy_entry(self):
        """验证隐私中心入口"""
        for text in ("隐私中心", "隐私"):
            try:
                el = self.device.find_element(self.device.by_text(text), timeout=5)
                el.click()
                time.sleep(2)
                logger.info(f"【iOS 设置】已进入 {text}")
                return
            except TimeoutException:
                continue
        pytest.fail("未找到隐私中心入口")

    def _check_address_entry(self):
        """验证常用地址入口"""
        for text in ("常用地址", "地址管理"):
            try:
                el = self.device.find_element(self.device.by_text(text), timeout=5)
                el.click()
                time.sleep(2)
                logger.info(f"【iOS 设置】已进入 {text}")
                return
            except TimeoutException:
                continue
        pytest.fail("未找到常用地址入口")

    def _check_payment_entry(self):
        """验证支付方式入口"""
        for text in ("支付方式", "支付管理"):
            try:
                el = self.device.find_element(self.device.by_text(text), timeout=5)
                el.click()
                time.sleep(2)
                logger.info(f"【iOS 设置】已进入 {text}")
                return
            except TimeoutException:
                continue
        pytest.fail("未找到支付方式入口")

    def _check_version(self):
        """验证版本信息"""
        for text in ("版本信息", "版本", "关于"):
            try:
                el = self.device.find_element(self.device.by_text(text), timeout=5)
                el.click()
                time.sleep(2)
                logger.info(f"【iOS 设置】已进入 {text}")
                return
            except TimeoutException:
                continue
        pytest.fail("未找到版本信息入口")

    def _check_cache(self):
        """验证清除缓存入口（仅验证入口存在，不执行清除）"""
        for text in ("清除缓存", "清理缓存"):
            try:
                el = self.device.find_element(self.device.by_text(text), timeout=5)
                logger.info(f"【iOS 设置】已定位到 {text} 入口（不执行清除）")
                return
            except TimeoutException:
                continue
        pytest.fail("未找到清除缓存入口")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
