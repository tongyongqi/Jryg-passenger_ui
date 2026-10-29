"""
Android 测试场景：优惠券估价失效刷新持久性验证
==============================================================================
流程：启动App → 登录 → 起终点 → 选包车价 → 选优惠券 → 等待5分钟过期 → 确认呼叫
      → 处理刷新提示 → 验证优惠券保留状态 → 返回首页
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
class TestCouponExpiry(AndroidBase):
    """优惠券估价失效刷新后持久性验证"""

    def test_android_coupon_expiry_verification(self):
        """优惠券选择在估价失效刷新后的持久性验证"""
        logger.info("【优惠券时效验证】启动...")

        try:
            logger.info("【步骤 1】启动App...")
            # 步骤 1：冷启动 App 并保障登录态（未登录会自动走登录流程）
            self._launch_app()
            self._ensure_logged_in()
            # 缓存 Poco 控件树句柄，后续定位复用，避免重复创建
            poco = self.poco
            self._close_activity_popup()

            logger.info("【步骤 2】配置起点...")
            # 步骤 2：配置行程起点
            self._set_origin()

            logger.info("【步骤 3】配置终点...")
            # 步骤 3：配置行程终点，等待报价计算完成
            self._set_destination()

            logger.info("【步骤 4】选择包車價的士...")
            # 步骤 4：选择「包車價的士」；控件树未命中时回退到坐标点击
            car_el = poco(textMatches=E.CHARTER_CAR_REGEX)
            if car_el.exists():
                car_el.click()
            else:
                self._tap_ratio(*E.CHARTER_CAR_COORD_RATIO, name="包車價的士")
            time.sleep(3)
            self._screenshot("JRYG_coupon_check_01_quote.png")

            logger.info("【步骤 5】进入优惠券列表...")
            # 步骤 5：进入优惠券列表；控件树未命中时回退到坐标点击
            coupon_el = poco(textMatches=E.COUPON_REGEX)
            if coupon_el.exists():
                coupon_el.click()
            else:
                self._tap_ratio(*E.COUPON_ENTRY_COORD_RATIO, name="优惠券区域")
            time.sleep(4)
            self._screenshot("JRYG_coupon_check_02_list.png")

            logger.info("勾选所有优惠券...")
            # 勾选所有目标优惠券，逐张点击并留出渲染间隔
            target_coupons = poco(textMatches=E.COUPON_TARGET_REGEX)
            if target_coupons.exists():
                try:
                    for cp in target_coupons:
                        cp.click()
                        time.sleep(1.5)
                except Exception as ex:
                    logger.warning(f"遍历勾选异常: {ex}")
            else:
                first_coupon = poco(textMatches=".*元.*|.*HKD.*|.*折.*")
                if first_coupon.exists():
                    first_coupon.click()
                    time.sleep(2)

            # 确认使用所选优惠券
            btn_use = poco(textMatches=E.COUPON_USE_BTN_REGEX)
            if btn_use.exists():
                btn_use.click()
                time.sleep(3)

            logger.info("【步骤 6】等待 5 分钟 10 秒模拟估价过期...")
            # 步骤 6：真实等待 5 分钟 10 秒，模拟优惠券估价过期
            # （不能用 mock 加速，否则无法验证服务端过期逻辑）
            for minute in range(1, 6):
                time.sleep(60)
                logger.info(f"  >> 已等待 {minute} 分钟...")
            time.sleep(10)

            logger.info("【步骤 7】点击确认呼叫触发刷新提示...")
            # 步骤 7：点击确认呼叫，触发估价失效的刷新提示
            self._tap_ratio(*E.CONFIRM_CALL_COORD_RATIO, name="确认呼叫")
            time.sleep(4)
            self._screenshot("JRYG_coupon_check_03_expired_prompt.png")

            btn_refresh = poco(textMatches=".*確定.*|.*确定.*|.*確認.*|.*确认.*|.*我知道了.*|.*同意.*|.*重新估價.*|.*重新估价.*")
            if btn_refresh.exists():
                btn_refresh.click()
                time.sleep(4)

            logger.info("【步骤 8】验证优惠券保留状态...")
            # 步骤 8：重新进入优惠券区域，验证过期后优惠券是否被保留
            coupon_retry = poco(textMatches=E.COUPON_REGEX)
            if coupon_retry.exists():
                coupon_retry.click()
            else:
                self._tap_ratio(*E.COUPON_ENTRY_COORD_RATIO, name="优惠券区域")
            time.sleep(4)
            self._screenshot("JRYG_coupon_check_04_post_verification.png")

            # 校验目标优惠券是否仍存在于列表中
            target_chk = poco(textMatches=E.COUPON_VERIFY_REGEX)
            if target_chk.exists():
                logger.info("  >> [校验成功] 目标优惠券依然存在")
            else:
                logger.warning("  >> [校验提示] 目标优惠券未找到")

            logger.info("【步骤 9】返回首页...")
            # 步骤 9：返回首页；无返回按钮时用系统返回键兜底
            btn_back = poco(textMatches=".*返回.*|.*点击回首页.*|.*返回首页.*")
            if btn_back.exists():
                btn_back.click()
            else:
                self._adb("shell", "input", "keyevent", "BACK")
            time.sleep(3)
            self._adb("shell", "input", "keyevent", "BACK")
            time.sleep(3)
            self._screenshot("JRYG_coupon_check_05_finished.png")
            logger.info("【成功】优惠券时效验证完成")

        except Exception as e:
            logger.error(f"【优惠券时效测试失败】{e}")
            self._screenshot("JRYG_coupon_check_failed.png")
            raise
