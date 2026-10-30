"""
港版 iOS 测试场景：包車價的士 + Alipay HK 支付
==============================================================================
车型：包車價的士（charter）—— 固定一口价，先付後乘
支付：Alipay HK（alipay）—— 订单结束后通过 Safari AlipayHK 完成支付
公共调用：启动/地址由iOSBase处理；下单预付收银台由OrderBase编排，后续付款
委托_ios_pay，不把预付确认并呼叫与后付确认支付合并为同一次点击。

完整流程：
  阶段 0（UI）  ：打开司机 App → 点击出车并确认听单
  阶段 1（UI）  ：切乘客 App 处理遗留订单，不调用司机业务接口
  阶段 2（UI）  ：拉起 App → 配置起终点 → 选择包車價的士 → 確認呼叫
               → 预付页面弹出 → 选择 Alipay HK 支付方式 → 確認支付並呼叫
               → 检测登录态 → 未登录则登录后重新下单 → 等待下单成功
  阶段 3（UI）  ：切司机 App → 接单 → 滑动到达/接载/结束 → 填写并确认账单
               提交后切回乘客，不调用业务接口、不自动收车
  阶段 4（UI）  ：订单结束后检测到支付页面 → 选择 Alipay HK → 確認支付
               → Safari 支付页 Pay Now → SUCCESS → 返回 App → 返回首页
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
class TestCharterAlipay(TestOrderBase):
    """包車價的士 + Alipay HK 支付

    继承 TestOrderBase，自动执行：
    UI 下单（包車價的士 + Alipay HK，先付後乘）→ 司机端接口接单 → 订单流转
    → 结束行程 → 订单结束后支付页面选择 Alipay HK → Safari 支付 → 支付成功 → 返回首页
    """

    __test__ = True            # 标记为可被 pytest 收集的测试类（基类中 __test__ = False）
    CAR_TYPE = "charter"       # 车型：包車價的士（固定一口价，先付後乘）
    PAYMENT = "alipay"         # 支付方式：Alipay HK（订单结束后走 Safari 支付流程）


if __name__ == "__main__":
    # 支持直接运行此文件：pytest 执行本文件，-v 显示详细输出，-s 不捕获 print
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
