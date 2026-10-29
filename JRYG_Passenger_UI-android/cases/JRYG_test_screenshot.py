"""测试场景：屏幕截图功能校验

调用 device.screenshot 截取当前屏幕，断言截图文件存在。
截图默认保存至 screenshots 目录。
"""

import pytest
import os
import sys

# 将项目根目录添加到 sys.path，确保 jryg_android 模块可被正确导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from jryg_android.JRYG_connect_device import AndroidDevice


class TestJRYGScreenshot:
    """屏幕截图机制校验用例类"""

    @classmethod
    def setup_class(cls):
        """类级 setup：创建 AndroidDevice 并连接 Appium Server。"""
        cls.device = AndroidDevice()
        cls.driver = cls.device.connect()

    @classmethod
    def teardown_class(cls):
        """类级 teardown：断开 Appium Session。"""
        cls.device.disconnect()

    def test_screenshot(self):
        """测试：Appium 屏幕截图机制

        调用 device.screenshot 截取当前屏幕，断言截图文件存在。
        """
        filename = self.device.screenshot("test_screen.png")
        assert os.path.exists(filename), "截图文件未能正确输出"


if __name__ == "__main__":
    # 支持直接运行：python -m pytest JRYG_test_screenshot.py -v -s
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
