"""
港版 iOS 测试场景：打錶的士 + 現金支付
==============================================================================
车型：打錶的士（meter）—— 按表计费，行程结束后按表金额现金结算
支付：現金（cash）—— 司机端确认收款后无需 App 端支付，直接返回首页
公共调用：继承TestOrderBase的启动、地址及双端编排；现金不进入_ios_pay线上渠道。

完整流程：
  阶段 0（UI）  ：打开司机 App → 点击出车并确认听单
  阶段 1（UI）  ：切乘客 App 处理遗留订单，不调用司机业务接口
  阶段 2（UI）  ：拉起 App → 配置起终点 → 选择打錶的士 → 选择現金支付方式
               → 確認呼叫 → 检测登录态 → 未登录则登录后重新下单 → 等待下单成功
  阶段 3（UI）  ：切司机 App → 接单 → 滑动到达/接载/结束 → 填写并确认账单
               现金收款需显式确认实际已收款，不自动收车
  阶段 4（UI）  ：订单结束后无支付页面，直接返回首页
==============================================================================
"""

import os
import sys
import pytest

# 获取 UI 框架根路径（本文件所在目录的上级 = JRYG_Passenger_UI_HK-ios）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 将框架根路径加入 sys.path，确保能 import ui_framework 包
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 导入港版 iOS 自动化配置（设备信息、平台等）
from ui_framework.JRYG_config import SETTINGS
# 导入参数化下单基类，子类只需设置 CAR_TYPE 和 PAYMENT 即可自动执行全流程
from ui_framework.JRYG_order_flow import TestOrderBase


# 当设备配置为 Android 时跳过此 iOS 测试用例，避免跨平台误执行
@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() == "ANDROID",
    reason="当前配置为 Android 自动化环境，跳过 iOS 测试"
)
class TestMeterCash(TestOrderBase):
    """打錶的士 + 現金支付

    继承 TestOrderBase，自动执行：
    UI 下单（打錶的士 + 現金）→ 司机端接口接单 → 订单流转 → 结束行程
    → 确认账单 → 确认收款 → 无需 App 端支付，直接返回首页
    """

    __test__ = True            # 标记为可被 pytest 收集的测试类（基类中 __test__ = False）
    CAR_TYPE = "meter"         # 车型：打錶的士（按表计费）
    PAYMENT = "cash"           # 支付方式：現金（司机端确认收款后无需 App 端支付）


if __name__ == "__main__":
    # 支持直接运行此文件：pytest 执行本文件，-v 显示详细输出，-s 不捕获 print
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
