"""测试场景：App 启动与 Session 校验

验证 Appium Session 是否正确创建、App 是否成功唤起。
属于环境连通性检查用例，不依赖业务数据。
"""

import pytest
import os
import sys

# 将项目根目录添加到 sys.path，确保 jryg_android 模块可被正确导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from jryg_android.JRYG_connect_device import AndroidDevice


class TestJRYGAppLaunch:
    """Android App 启动与 Session 生成校验用例类"""

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


if __name__ == "__main__":
    # 支持直接运行：python -m pytest JRYG_test_app_launch.py -v -s
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
