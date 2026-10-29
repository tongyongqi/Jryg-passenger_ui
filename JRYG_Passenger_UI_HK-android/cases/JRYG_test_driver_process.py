"""
Android 测试场景：司机端订单状态流转
==============================================================================
流程：启动司机端 → 接单 → 到达上车点 → 接到乘客 → 到达目的地 → 发起收款 → 完单
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
from poco.drivers.android.uiautomation import AndroidUiautomationPoco


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() != "ANDROID",
    reason="当前不是 Android 自动化环境"
)
class TestDriverProcess(AndroidBase):
    """司机端订单状态流转测试"""

    @pytest.mark.skip(reason="只进行乘客端优惠券场景校验，无需打开司机端")
    def test_android_driver_process(self):
        """司机端订单状态流转全流程"""
        logger.info("启动香港版司机端...")

        self._adb("shell", "am", "force-stop", E.DRIVER_PACKAGE)
        time.sleep(1)
        self._adb("shell", "am", "start", "-W", "-n", f"{E.DRIVER_PACKAGE}/{E.DRIVER_ACTIVITY}")
        time.sleep(8)

        poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        progress = {"waited_1min": False, "order_entered": False}

        for cycle in range(40):
            current_act = self._current_activity()
            logger.info(f"【司机端 循环 {cycle + 1}】Activity: {current_act}")

            for pop_text in E.DRIVER_POPUP_TEXTS:
                if poco(text=pop_text).exists():
                    poco(text=pop_text).click()
                    logger.info(f"  >> 关闭弹窗: {pop_text}")
                    time.sleep(2)

            is_at_pickup = poco(textMatches=E.DRIVER_STATE_PICKUP_REGEX).exists()
            is_received = poco(textMatches=E.DRIVER_STATE_RECEIVED_REGEX).exists()
            is_at_dest = poco(textMatches=E.DRIVER_STATE_DEST_REGEX).exists()
            is_billing = poco(textMatches=E.DRIVER_STATE_BILLING_REGEX).exists()

            if is_at_pickup or is_received or is_at_dest or is_billing:
                progress["order_entered"] = True

            if not progress["order_entered"]:
                for open_text in E.DRIVER_ORDER_ENTRY_TEXTS:
                    if poco(text=open_text).exists():
                        poco(text=open_text).click()
                        time.sleep(3)
                        break

            if is_at_pickup:
                self._screenshot("JRYG_driver_01_at_pickup.png")
                self._slide_drag(poco)
                time.sleep(5)
                continue

            if is_received:
                self._screenshot("JRYG_driver_02_received.png")
                self._slide_drag(poco)
                time.sleep(5)
                continue

            if is_at_dest:
                self._screenshot("JRYG_driver_03_in_trip.png")
                if not progress["waited_1min"]:
                    logger.info("等待 1 分钟...")
                    time.sleep(60)
                    progress["waited_1min"] = True
                self._slide_drag(poco)
                time.sleep(5)
                self._screenshot("JRYG_driver_04_arrived.png")
                continue

            if progress["order_entered"]:
                if is_billing:
                    et_fee = poco(E.DRIVER_FEE_INPUT_ID)
                    if et_fee.exists() and et_fee.get_text() in ["請輸入車費", "请输入车费", ""]:
                        logger.info("输入车费: 50 HKD")
                        et_fee.click()
                        time.sleep(1)
                        et_fee.set_text("50")
                        time.sleep(2)
                    self._slide_drag(poco)
                    time.sleep(5)
                    self._screenshot("JRYG_driver_04_billing.png")
                    continue

                if poco(textMatches=E.DRIVER_FINISHED_REGEX).exists():
                    logger.info("行程结束")
                    self._screenshot("JRYG_driver_05_finished.png")
                    btn_back = poco(textMatches=E.DRIVER_BACK_HOME_REGEX)
                    if btn_back.exists():
                        btn_back.click()
                    else:
                        self._adb("shell", "input", "keyevent", "BACK")
                    time.sleep(3)
                    break

            time.sleep(3)

        logger.info("【成功】司机端流转完毕")

        # 回到乘客端
        logger.info("重新拉起乘客端...")
        # 步骤 1：冷启动司机端 App
        self._launch_app()
        self._screenshot("JRYG_passenger_after_bill.png")
        btn_home = self.poco(textMatches=".*点击回首页.*|.*返回首页.*|.*確定.*|.*确定.*|.*返回.*")
        if btn_home.exists():
            btn_home.click()
        else:
            self._adb("shell", "input", "keyevent", "BACK")
        time.sleep(4)
        self._screenshot("JRYG_passenger_home_restored.png")

    def _slide_drag(self, poco):
        """滑动按钮到最右端"""
        try:
            drag_view = poco(textMatches=".*到達.*|.*到达.*|.*接到.*|.*發起.*|.*发起.*|.*確認.*|.*确认.*")
            if drag_view.exists():
                el = drag_view
                try:
                    el = el[0]
                except Exception:
                    pass
                bounds = el.get_bounds()
                x1 = (bounds["right"] - bounds["left"]) * 0.2 + bounds["left"]
                y1 = (bounds["bottom"] - bounds["top"]) * 0.5 + bounds["top"]
                from airtest.core.api import swipe
                swipe((x1, y1), (x1 + 300, y1))
                logger.info("  >> 滑动成功")
        except Exception as e:
            logger.warning(f"  >> 滑动异常: {e}")
