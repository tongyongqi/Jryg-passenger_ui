"""
港版 iOS 测试场景：包車價的士 + 八達通支付
==============================================================================
车型：包車價的士（charter）—— 固定一口价，先付後乘
支付：八達通（octopus）—— 通过八達通卡完成支付
备注：八達通支付暂不执行，仅展示用例结构，待后续八達通 SDK 接入后启用
==============================================================================
"""

import os
import sys
import pytest

# 获取 UI 框架根路径（本文件所在目录的上级 = JRYG_Passenger_UI_HK-ios）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 将框架根路径加入 sys.path，确保能 import jryg_hk_ios 包
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 导入港版 iOS 自动化配置（设备信息、平台等）
from jryg_hk_ios.JRYG_config import SETTINGS
# 导入参数化下单基类，子类只需设置 CAR_TYPE 和 PAYMENT 即可自动执行全流程
from cases.JRYG_test_ios_order_base import TestOrderBase


# 当设备配置为 Android 时跳过此 iOS 测试用例，避免跨平台误执行
@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() == "ANDROID",
    reason="当前配置为 Android 自动化环境，跳过 iOS 测试"
)
# 八達通支付暂不执行（SDK 未接入），仅保留用例结构以便后续启用
@pytest.mark.skip(reason="八達通支付暂不执行，仅展示用例结构")
class TestCharterOctopus(TestOrderBase):
    """包車價的士 + 八達通支付（暂不执行）

    继承 TestOrderBase，待八達通 SDK 接入后启用：
    UI 下单（包車價的士 + 八達通，先付後乘）→ 司机端接口接单 → 订单流转
    → 结束行程 → 订单结束后通过八達通卡完成支付 → 支付成功 → 返回首页
    """

    __test__ = True            # 标记为可被 pytest 收集的测试类（基类中 __test__ = False）
    CAR_TYPE = "charter"       # 车型：包車價的士（固定一口价，先付後乘）
    PAYMENT = "octopus"        # 支付方式：八達通（暂不执行，待 SDK 接入）


if __name__ == "__main__":
    # 支持直接运行此文件：pytest 执行本文件，-v 显示详细输出，-s 不捕获 print
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
