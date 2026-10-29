"""
Android 测试场景：一键登录
==============================================================================
流程：拉起App → 隐私协议 → 定位权限 → 个人中心 → 手机号输入 → 验证码 → 登录成功
==============================================================================
"""

import os
import sys
import time
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from jryg_hk_android.JRYG_config import SETTINGS
from jryg_hk_android.JRYG_logger import logger
from jryg_hk_android.JRYG_android_base import AndroidBase
from jryg_hk_android import JRYG_android_elements as E


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() != "ANDROID",
    reason="当前不是 Android 自动化环境"
)
class TestLoginFlow(AndroidBase):
    """一键打开并自动登录测试"""

    def test_passenger_hk_login_flow(self):
        """执行一键打开并自动登录完整闭环"""
        logger.info(f"【港版一键登录】预备手机号: {E.LOGIN_PHONE_NUMBER}")

        # 一键登录采用状态机循环：每轮识别当前页面状态并针对性处理，
        # 最多重试 30 轮以覆盖隐私协议、权限弹窗、输入框等各类拦截
        for cycle in range(30):
            # 识别当前页面状态（协议/权限/登录页/首页已登录等）
            state = self._detect_current_state()
            logger.info(f"[循环 {cycle}] 状态: {state}")

            if state == "privacy_agreement":
                btn = self.poco(text=E.TEXT_AGREE)
                if btn.exists():
                    btn.click()
                else:
                    self._tap_by_text(E.TEXT_AGREE)
                time.sleep(3)
                continue

            if state == "permission_dialog":
                btn = self.poco(text=E.TEXT_GO_AUTH)
                if btn.exists():
                    btn.click()
                else:
                    self._tap_by_text(E.TEXT_GO_AUTH)
                time.sleep(3)
                continue

            if state == "system_location_permission":
                btn = self.poco(text=E.TEXT_ALLOW_LOCATION)
                if not btn.exists():
                    btn = self.poco(text=E.TEXT_ALLOW_LOCATION_ALT)
                if btn.exists():
                    btn.click()
                else:
                    self._adb("shell", "input", "tap", "586", "2178")
                time.sleep(4)
                continue

            if state == "home_unlogged":
                btn = self.poco(text="我的")
                if btn.exists():
                    btn.click()
                else:
                    self._tap_by_text("我的")
                time.sleep(3)
                continue

            if state == "mine_unlogged":
                btn = self.poco(text=E.TEXT_LOGIN_REGISTER)
                if not btn.exists():
                    btn = self.poco(E.MINE_NAME_ID)
                if btn.exists():
                    btn.click()
                else:
                    self._adb("shell", "input", "tap", "661", "477")
                time.sleep(4)
                continue

            if state == "login_phone_input":
                et_phone = self.poco(E.PHONE_INPUT_ID)
                if et_phone.exists():
                    et_phone.click()
                    time.sleep(0.5)
                    et_phone.set_text(E.LOGIN_PHONE_NUMBER)
                else:
                    self._adb("shell", "input", "tap", "617", "821")
                    time.sleep(0.5)
                    self._adb("shell", "input", "text", E.LOGIN_PHONE_NUMBER)
                time.sleep(1.5)
                self._tap_checkbox()
                time.sleep(1)
                btn_code = self.poco(E.GET_CODE_BTN_ID)
                if btn_code.exists():
                    btn_code.click()
                else:
                    self._adb("shell", "input", "tap", "586", "1042")
                time.sleep(4)
                continue

            if state == "login_code_input":
                et_code = self.poco(E.VERIFY_CODE_INPUT_ID)
                if et_code.exists():
                    et_code.click()
                    time.sleep(0.5)
                    et_code.set_text(E.LOGIN_VERIFY_CODE)
                else:
                    self._adb("shell", "input", "tap", "586", "865")
                    time.sleep(0.5)
                    self._adb("shell", "input", "text", E.LOGIN_VERIFY_CODE)
                time.sleep(5)
                continue

            if state == "home_logged":
                logger.info("【成功】一键登录完成")
                break

            time.sleep(2)
