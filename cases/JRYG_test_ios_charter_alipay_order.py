"""
港版 iOS 测试场景：包車價的士 + Alipay HK 支付
==============================================================================
车型：包車價的士（charter）—— 固定一口价，先付後乘
支付：Alipay HK（alipay）—— 下单时通过 Safari AlipayHK 预付，结束后不重复付款
公共调用：启动/登录/地址由iOSBase处理；预付收银台由OrderBase编排，渠道支付委托_ios_pay。

完整流程：
  阶段 0（UI）  ：打开司机 App → 点击出车并确认听单
  阶段 1（UI）  ：打开乘客 App → 处理权限弹框（无则忽略）→ 核验一次登录态并缓存
               → 按现有规则处理遗留订单，保持乘客 App 前台
  阶段 2（UI）  ：输入起点铜锣湾 → 输入终点大谭郊野公园 → 选择包車價的士
               → 確認呼叫 → 预付页面选择 Alipay HK → 確認支付並呼叫
               → Safari Pay Now → SUCCESS → 返回 App → 等待下单成功
  阶段 3（UI）  ：切司机 App → UI 接单 → 滑动到达/接载/结束 → 填写并确认账单
               提交后切回乘客，不调用业务接口、不自动收车
  阶段 4（UI）  ：乘客返回首页 → 司机核验同一订单已完成且已支付，不重复预付
  登录缓存仅限本次用例；明确登录失效时清除缓存，付款结果不确定时不重下单。
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

    继承 TestOrderBase：一次启动与登录核验 → 铜锣湾到大谭郊野公园
    → 包車價的士 → 確認呼叫 → Alipay HK预付 → 司机UI接单及行程流转
    → 结束行程 → 乘客返回首页 → 同订单完成及到账核验。
    """

    __test__ = True            # 标记为可被 pytest 收集的测试类（基类中 __test__ = False）
    CAR_TYPE = "charter"       # 车型：包車價的士（固定一口价，先付後乘）
    PAYMENT = "alipay"         # 支付方式：Alipay HK 预付


if __name__ == "__main__":
    from runners.JRYG_run_case_ios import run_case

    sys.exit(run_case(__file__))
