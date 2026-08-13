"""
示例测试用例：Android 真机 App 启动与核心操作功能验证（已迁入 JRYG_Passenger_UI 结构）
"""

import pytest
import os
import sys

# 添加必要的工作目录到 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from JRYG_Passenger_UI.common.JRYG_connect_device import AndroidDevice


class TestJRYGDemo:
    """Android App 真机连接性与基础手势测试用例类"""

    @classmethod
    def setup_class(cls):
        cls.device = AndroidDevice()
        cls.driver = cls.device.connect()

    @classmethod
    def teardown_class(cls):
        cls.device.disconnect()

    def test_app_launch(self):
        """测试：验证 App Session 是否能正确生成与唤起"""
        assert self.driver.session_id is not None, "Appium Session 未正常创建"
        print("App 成功拉起且 Session 正常")

    def test_screenshot(self):
        """测试：Appium 屏幕截图机制"""
        filename = self.device.screenshot("test_screen.png")
        assert os.path.exists(filename), "截图文件未能正确输出"

    def test_swipe(self):
        """测试：上划与下划基础动作模拟"""
        self.device.swipe_up()
        self.device.swipe_down()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
