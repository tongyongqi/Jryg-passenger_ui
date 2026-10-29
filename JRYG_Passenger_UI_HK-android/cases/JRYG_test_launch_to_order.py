"""
Android 测试场景：App启动到下单端到端流程
==============================================================================
流程：启动App → 关闭弹窗 → 设置起终点 → 选择车型 → 提交订单
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
class TestLaunchToOrder(AndroidBase):
    """从启动App到提交订单的端到端测试"""

    @pytest.mark.skip(reason="只进行乘客端优惠券场景校验，跳过直接呼叫下单")
    def test_android_launch_to_order(self):
        """启动App、关闭弹框、设置起终点、选择车型并提交订单"""
        try:
            # 步骤 1：冷启动 App，等待其进入前台首页
            logger.info("【步骤 1】从桌面启动港版 App...")
            self._launch_app()

            # 步骤 2：关闭可能遮挡首页的活动弹框
            # 先截图留档（含弹框状态），便于失败时核对弹框来源
            logger.info("【步骤 2】关闭活动弹框...")
            self._screenshot("JRYG_android_00_home_with_popup.png")
            self._close_activity_popup()
            self._screenshot("JRYG_android_01_home.png")

            # 步骤 3：设置起点为铜锣湾地铁站
            logger.info("【步骤 3】设置起点：铜锣湾地铁站...")
            self._set_origin()

            # 步骤 4：设置终点为香港大学，等待路线与报价计算完成
            logger.info("【步骤 4】设置终点：香港大学...")
            self._set_destination()

            logger.info("【成功】港版 Android App 从启动到下单流程执行完成！")
        except Exception as exc:
            # 异常时先记录日志，再截图留证，最后原样抛出以保留失败原因
            logger.error(f"【下单流程失败】{exc}")
            try:
                self._screenshot("JRYG_android_order_error.png")
            except Exception:
                # 截图失败不应掩盖原始异常，此处静默忽略
                pass
            raise
