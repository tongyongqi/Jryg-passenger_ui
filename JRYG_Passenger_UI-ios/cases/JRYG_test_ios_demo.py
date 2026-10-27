"""阳光出行 iOS 真机基础连接性验证测试用例 -ios

验证 Appium 连接、截图、滑动等基础能力，不涉及具体业务功能。
对应安卓端 JRYG_test_demo.py。
"""
import os
import sys

import pytest

# 将 iOS 项目根目录添加到 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from jryg_ios.JRYG_connect_device import IOSDevice


class TestJRYGIosDemo:
    """iOS 真机连接性与基础手势测试用例类 -ios"""

    @classmethod
    def setup_class(cls):
        """类级 setup：创建 IOSDevice 并连接 Appium Server"""
        cls.device = IOSDevice()
        cls.driver = cls.device.connect()

    @classmethod
    def teardown_class(cls):
        """类级 teardown：断开 Appium Session"""
        cls.device.disconnect()

    def test_ios_app_launch(self):
        """测试：验证 iOS App Session 是否能正确生成与唤起 -ios"""
        assert self.driver.session_id is not None, "Appium Session 未正常创建"
        print("iOS App 成功拉起且 Session 正常")

    def test_ios_screenshot(self):
        """测试：Appium 屏幕截图机制 -ios"""
        filename = self.device.screenshot("JRYG_ios_test_screen.png")
        assert os.path.exists(filename), "截图文件未能正确输出"

    def test_ios_swipe(self):
        """测试：上划与下划基础动作模拟 -ios"""
        self.device.swipe_up()
        self.device.swipe_down()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
