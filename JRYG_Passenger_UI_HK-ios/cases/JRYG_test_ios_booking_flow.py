"""
iOS 测试场景：极速一键下单流程（优惠券场景）
==============================================================================
流程：拉起App → 处理弹窗授权 → 配置起点(铜锣湾地铁站) → 配置终点(香港大学)
     → 选择100元优惠券 → 确认呼叫 → 截图存档
==============================================================================
"""

import os
import sys
import time
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from jryg_hk_ios.JRYG_config import SETTINGS
from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_ios_ui_base import iOSBase
from jryg_hk_ios import JRYG_ios_ui_elements as E


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() == "ANDROID",
    reason="当前配置为 Android 自动化环境，跳过 iOS 测试"
)
class TestBookingFlow(iOSBase):
    """极速一键下单测试：配置起终点 → 选优惠券 → 确认呼叫"""

    def test_ios_passenger_booking_flow(self):
        """核心业务流：拉起乘客端 -> 配置起终点 -> 选择100元优惠券 -> 确认呼叫"""
        tag = "极速下单"
        try:
            self._test_impl()
        except Exception as e:
            self._ios_screenshot("JRYG_ios_booking_failed.png")
            logger.error(f"【{tag} 异常】{e}")
            raise

    def _test_impl(self):
        """TestBookingFlow._test_impl —— 内部辅助方法：test impl。

        :return: None"""
        tag = "极速下单"

        # 步骤 1-5：拉起App + 弹窗 + 起终点
        self._ios_launch_setup_and_addresses(
            tag, E.BOOKING_START_ADDRESS, E.BOOKING_END_ADDRESS
        )

        # 步骤 6：进入优惠券列表
        logger.info(f"【{tag} 步骤 6】寻找并进入优惠券选择列表...")
        self._open_coupon_list()

        # 步骤 7：选择100元优惠券
        logger.info(f"【{tag} 步骤 7】选择100元优惠券...")
        self._select_coupon()

        # 步骤 8：点击确认呼叫
        logger.info(f"【{tag} 步骤 8】点击『確認呼叫』发起呼叫...")
        self._ios_click_confirm_call(tag)
        time.sleep(5)

        # 截图存档
        self._ios_screenshot("JRYG_ios_booking_success.png")
        logger.info(f"【{tag} 流程完毕】下单凭证截图已归档")

    def _open_coupon_list(self):
        """点击优惠券入口进入优惠券列表"""
        coupon_gate = self.client(xpath=E.COUPON_XPATH)

        if not coupon_gate.exists:
            poco_coupon = self.poco(textMatches=E.COUPON_POCO_REGEX)
            if poco_coupon.exists():
                coupon_gate = poco_coupon

        if coupon_gate and (
            hasattr(coupon_gate, "exists") and coupon_gate.exists
            or not hasattr(coupon_gate, "exists")
        ):
            coupon_gate.click()
            logger.info("  >> 成功点击进入优惠券列表")
            time.sleep(3)
        else:
            logger.warning(f"  >> 未找到优惠券入口，物理兜底点击 {E.COUPON_FALLBACK_COORD}")
            self.client.click(*E.COUPON_FALLBACK_COORD)
            time.sleep(3)

    def _select_coupon(self):
        """在优惠券列表中匹配并选择目标优惠券"""
        selected = False
        for target_text in E.COUPON_TARGET_TEXTS:
            card = self.client(
                xpath=f'//*[contains(@label, "{target_text}") or contains(@value, "{target_text}")]'
            )
            if not card.exists:
                poco_card = self.poco(textMatches=f".*{target_text}.*")
                if poco_card.exists():
                    card = poco_card

            if card and (
                hasattr(card, "exists") and card.exists
                or not hasattr(card, "exists")
            ):
                card.click()
                logger.info(f"  >> 匹配并点击优惠券: '{target_text}'")
                selected = True
                time.sleep(3)
                break

        if not selected:
            logger.warning("  >> 未匹配到目标优惠券，点击列表第一张兜底...")
            first_card = self.poco(type="XCUIElementTypeCell")
            if first_card.exists():
                first_card[0].click()
                time.sleep(3)
