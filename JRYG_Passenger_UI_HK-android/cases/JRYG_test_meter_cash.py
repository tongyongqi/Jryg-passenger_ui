"""
Android 测试场景：打表的士现金支付下单
==============================================================================
流程：登录 → 首页 → 起终点 → 优惠券 → 确认呼叫 → 完成下单
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
class TestMeterCashFlow(AndroidBase):
    """打表的士现金支付下单测试"""

    def test_passenger_hk_booking_flow(self):
        """登录后下单：起终点 + 优惠券 + 确认呼叫"""
        logger.info("【港版下单】打錶的士+现金支付")

        # 确保首页
        btn_home = self.poco(E.TAB_HOME_ID)
        if btn_home.exists():
            btn_home[0].click()
        else:
            self._adb("shell", "input", "tap", str(E.HOME_TAB_COORD[0]), str(E.HOME_TAB_COORD[1]))
        time.sleep(3)

        # 关闭弹窗
        self._close_activity_popup()

        # 起点
        logger.info("配置起点...")
        tv_start = self.poco(E.START_ADDRESS_ID)
        if tv_start.exists():
            tv_start.click()
            time.sleep(3)
            et_search = self.poco(E.SEARCH_INPUT_ID)
            if not et_search.exists():
                et_search = self.poco(type="android.widget.EditText")
            if et_search.exists():
                et_search.click()
                time.sleep(0.5)
                et_search.set_text("铜锣湾地铁")
                time.sleep(4)
                self._select_first_search_result_adb("铜锣湾地铁站")
                time.sleep(3)

        # 终点
        logger.info("配置终点...")
        tv_dest = self.poco(text=E.DEST_TEXT)
        if not tv_dest.exists():
            tv_dest = self.poco(E.DEST_ID)
        if not tv_dest.exists():
            tv_dest = self.poco(E.DEST_LAYOUT_ID)
        if tv_dest.exists():
            tv_dest.click()
            time.sleep(3)
            et_search = self.poco(E.SEARCH_INPUT_ID)
            if not et_search.exists():
                et_search = self.poco(type="android.widget.EditText")
            if et_search.exists():
                et_search.click()
                time.sleep(0.5)
                et_search.set_text("香港大学")
                time.sleep(4)
                self._select_first_search_result_adb("香港大学")
                time.sleep(6)

        # 优惠券
        logger.info("选择优惠券...")
        for text_to_try in ["優惠券", "优惠券", "优惠", "優惠", "100"]:
            if self._tap_by_text(text_to_try):
                time.sleep(3)
                break
        else:
            el_coupon = self.poco(textMatches=E.COUPON_REGEX)
            if el_coupon.exists():
                el_coupon.click()
                time.sleep(3)

        for target in ["100元优惠卷", "100元优惠券", "100", "100元"]:
            if self._tap_by_text(target):
                time.sleep(3)
                break
        else:
            first_card = self.poco(textMatches=".*元.*")
            if first_card.exists():
                first_card.click()
                time.sleep(3)

        # 确认呼叫
        logger.info("点击确认呼叫...")
        btn_call = self.poco(E.CALL_BTN_ID)
        if btn_call.exists():
            btn_call.click()
        else:
            self._adb("shell", "input", "tap", str(E.CALL_BTN_COORD[0]), str(E.CALL_BTN_COORD[1]))
        time.sleep(5)
        logger.info("【港版下单流程】执行完毕")

    def _select_first_search_result_adb(self, name):
        """选择第一个搜索结果（ADB dump方式）"""
        self._adb("shell", "uiautomator", "dump", "/sdcard/_temp.xml", check=False)
        path = os.path.join(BASE_DIR, "screenshots", "_temp.xml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import subprocess
        with open(path, "wb") as f:
            subprocess.run(["adb", "-s", self.udid, "exec-out", "cat", "/sdcard/_temp.xml"], stdout=f)
        if os.path.exists(path):
            import re
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            pattern = r'resource-id="' + re.escape(E.SEARCH_RESULT_TITLE_ID) + r'"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            import re as re_mod
            matches = re_mod.findall(pattern, content)
            if matches:
                x1, y1, x2, y2 = map(int, matches[0])
                self._adb("shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2))
                return
        self._adb("shell", "input", "tap", "500", "420")
