"""
Android 测试场景：多场景优惠券刷新与手选券保留规则验证
==============================================================================
场景D：初次进入车型页无提示
场景A：切后台再切回，估价刷新并保留手选券
场景C：收银台关闭后估价刷新并保留手选券
场景E：最终选择优惠券并支付下单
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
class TestCouponRulesScenarios(AndroidBase):
    """多场景优惠券刷新与手选券保留规则验证"""

    def test_android_coupon_rules_scenarios(self):
        """多场景优惠券验证：D→A→C→E"""
        logger.info("【多场景验证】开始...")

        try:
            # 场景D：初次进入
            logger.info("=== 场景D：初次进入车型页，无提示 ===")
            # 步骤 1：冷启动 App 并保障登录态
            self._launch_app()
            self._ensure_logged_in()
            poco = self.poco
            self._close_activity_popup()
            # 步骤 2：配置行程起点
            self._set_origin()
            # 步骤 3：配置行程终点，等待报价计算完成
            self._set_destination()
            time.sleep(5)

            toast = poco(textMatches=".*预估信息已更新.*|.*请重新选择.*|.*失效.*")
            assert not toast.exists(), "场景D失败：初始进入不应有刷新提示"
            logger.info("  >> 场景D验证通过")

            # 场景A：切后台再切回
            logger.info("=== 场景A：切后台再切回，估价刷新并保留手选券 ===")
            car_el = poco(textMatches=E.CHARTER_CAR_REGEX)
            if car_el.exists():
                car_el.click()
            else:
                self._tap_ratio(*E.CHARTER_CAR_COORD_RATIO, name="包車價的士")
            time.sleep(3)

            # 进入优惠券列表；控件树未命中时回退到坐标点击
            coupon_el = poco(textMatches=E.COUPON_REGEX)
            if coupon_el.exists():
                coupon_el.click()
                time.sleep(3)
                target_coupons = poco(textMatches=E.COUPON_TARGET_REGEX)
                if target_coupons.exists():
                    try:
                        for cp in target_coupons:
                            cp.click()
                            time.sleep(1.5)
                    except Exception as ex:
                        logger.warning(f"场景A勾选异常: {ex}")
                btn_use = poco(textMatches=E.COUPON_USE_BTN_REGEX)
                if btn_use.exists():
                    btn_use.click()
                    time.sleep(3)

            self._screenshot("JRYG_scenario_A_selected.png")

            logger.info("切后台...")
            self._adb("shell", "input", "keyevent", "3")
            time.sleep(5)
            logger.info("切回前台...")
            self._adb("shell", "monkey", "-p", self.package, "-c", "android.intent.category.LAUNCHER", "1")
            time.sleep(6)
            self._screenshot("JRYG_scenario_A_foreground.png")

            coupon_retry = poco(textMatches=E.COUPON_REGEX)
            if coupon_retry.exists():
                coupon_retry.click()
                time.sleep(3)
            self._screenshot("JRYG_scenario_A_retained_check.png")

            target_chk = poco(textMatches=E.COUPON_VERIFY_REGEX)
            assert target_chk.exists(), "场景A失败：切回后手选券未保留"
            logger.info("  >> 场景A验证通过")

            btn_back = poco(textMatches=".*返回.*|.*确定.*|.*確定.*|.*確認.*|.*确认.*")
            if btn_back.exists():
                btn_back.click()
            else:
                self._adb("shell", "input", "keyevent", "BACK")
            time.sleep(3)

            # 场景C：收银台关闭后刷新
            logger.info("=== 场景C：收银台关闭后刷新估价并保留手选券 ===")
            self._tap_ratio(*E.CONFIRM_CALL_COORD_RATIO, name="确认呼叫")
            time.sleep(5)
            self._screenshot("JRYG_scenario_C_cashier.png")

            self._adb("shell", "input", "keyevent", "BACK")
            time.sleep(4)
            self._screenshot("JRYG_scenario_C_back_to_quote.png")

            coupon_c = poco(textMatches=E.COUPON_REGEX)
            if coupon_c.exists():
                coupon_c.click()
                time.sleep(3)
            self._screenshot("JRYG_scenario_C_retained_check.png")

            target_c = poco(textMatches=E.COUPON_VERIFY_REGEX)
            assert target_c.exists(), "场景C失败：收银台关闭后手选券未保留"
            logger.info("  >> 场景C验证通过")

            # 场景E：最终下单
            logger.info("=== 场景E：选择优惠券并支付下单 ===")
            btn_back_quote = poco(textMatches=".*返回.*|.*确定.*|.*確定.*|.*確認.*|.*确认.*|.*使用.*")
            if btn_back_quote.exists():
                btn_back_quote.click()
            else:
                self._adb("shell", "input", "keyevent", "BACK")
            time.sleep(4)

            self._tap_ratio(*E.CONFIRM_CALL_COORD_RATIO, name="确认呼叫")
            time.sleep(5)
            self._screenshot("JRYG_prepaid_cashier_order.png")

            pay_btn = poco(textMatches=".*支付.*|.*立即支付.*|.*確認支付.*|.*确认支付.*|.*去支付.*")
            if pay_btn.exists():
                pay_btn.click()
            else:
                self._tap_ratio(*E.CONFIRM_CALL_COORD_RATIO, name="支付按钮")
            time.sleep(10)
            self._screenshot("JRYG_order_submitted_with_coupon.png")
            logger.info("【成功】多场景优惠券验证完成")

        except Exception as e:
            logger.error(f"【多场景优惠券校验失败】{e}")
            self._screenshot("JRYG_scenario_coupon_failed.png")
            raise
