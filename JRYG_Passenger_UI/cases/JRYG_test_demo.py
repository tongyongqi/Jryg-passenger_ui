"""示例测试用例：Android 真机 App 启动与核心操作功能验证。

该文件为入门级示例，验证 Appium 连接、截图、滑动等基础能力，
不涉及具体业务功能。用于验证测试环境是否搭建正确。

测试内容：
  - test_app_launch: 验证 Appium Session 是否正确创建
  - test_screenshot: 验证截图功能是否正常工作
  - test_swipe: 验证上划和下划手势操作
"""

import pytest
import os
import sys

# 将项目根目录添加到 sys.path，确保 common 模块可被正确导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from JRYG_Passenger_UI.common.JRYG_connect_device import AndroidDevice


class TestJRYGDemo:
    """Android App 真机连接性与基础手势测试用例类

    用于验证测试环境（Appium Server、ADB、设备连接）是否正常工作。
    不依赖任何业务数据，适合作为环境检查用例。
    """

    @classmethod
    def setup_class(cls):
        """类级 setup：创建 AndroidDevice 并连接 Appium Server。"""
        cls.device = AndroidDevice()
        cls.driver = cls.device.connect()

    @classmethod
    def teardown_class(cls):
        """类级 teardown：断开 Appium Session。"""
        cls.device.disconnect()

    def test_app_launch(self):
        """测试：验证 App Session 是否能正确生成与唤起

        断言 Appium session_id 不为空，说明 Session 已成功创建。
        """
        assert self.driver.session_id is not None, "Appium Session 未正常创建"
        print("App 成功拉起且 Session 正常")

    def test_screenshot(self):
        """测试：Appium 屏幕截图机制

        调用 device.screenshot 截取当前屏幕，断言截图文件存在。
        截图默认保存至 screenshots 目录。
        """
        filename = self.device.screenshot("test_screen.png")
        assert os.path.exists(filename), "截图文件未能正确输出"

    def test_swipe(self):
        """测试：上划与下划基础动作模拟

        验证 AndroidDevice 的 swipe_up 和 swipe_down 方法是否正常工作。
        上划：从屏幕底部 80% 滑至顶部 20%
        下划：从屏幕顶部 20% 滑至底部 80%
        """
        self.device.swipe_up()
        self.device.swipe_down()


if __name__ == "__main__":
    # 支持直接运行：python -m pytest JRYG_test_demo.py -v -s
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
