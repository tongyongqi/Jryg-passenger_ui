"""测试场景：上划/下划基础手势校验

验证 AndroidDevice 的 swipe_up 和 swipe_down 方法是否正常工作。
  上划：从屏幕底部 80% 滑至顶部 20%
  下划：从屏幕顶部 20% 滑至底部 80%
"""

import pytest
import os
import sys

# 将项目根目录添加到 sys.path，确保 jryg_android 模块可被正确导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from jryg_android.JRYG_connect_device import AndroidDevice


class TestJRYGSwipe:
    """上划与下划基础动作模拟用例类"""

    @classmethod
    def setup_class(cls):
        """类级 setup：创建 AndroidDevice 并连接 Appium Server。"""
        cls.device = AndroidDevice()
        cls.driver = cls.device.connect()

    @classmethod
    def teardown_class(cls):
        """类级 teardown：断开 Appium Session。"""
        cls.device.disconnect()

    def test_swipe(self):
        """测试：上划与下划基础动作模拟"""
        self.device.swipe_up()
        self.device.swipe_down()


if __name__ == "__main__":
    # 支持直接运行：python -m pytest JRYG_test_swipe.py -v -s
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
