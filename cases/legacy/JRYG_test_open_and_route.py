"""香港 Android 独立路线用例，启动、登录和地址操作统一委托公共步骤。"""

import pytest

from jryg_hk_android.JRYG_config import SETTINGS
from jryg_hk_android.JRYG_android_passenger import AndroidPassengerBase


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() != "ANDROID",
    reason="当前不是 Android 自动化环境",
)
class TestJRYGHKOpenAndRoute(AndroidPassengerBase):
    """只验证登录和起终点路线准备，不点击确认呼叫或付款。"""

    def test_open_app_and_select_route(self):
        """配置起终点后核验车型路线页出现确认呼叫，截图留证。"""
        self.prepare_passenger_route("route", start="铜锣湾", verify_login=True)
        self._assert_passenger_foreground()
        assert self.client(textContains="確認呼叫").exists, "选择起终点后未进入车型路线页"
        self._android_screenshot("JRYG_route_03_route_selected.png")
