"""
港版 iOS 测试场景：打錶的士 + 電子支付
==============================================================================
车型：打錶的士（meter）—— 按表计费，行程结束后按表金额电子支付
支付：電子支付（epayment）—— 订单结束后走信用卡/扣帳卡支付流程（银行卡表单 + OTP）

注意：epayment 与 bankcard 在订单结束后的支付流程中走相同的信用卡路径，
      区别在于 epayment 在下单时选择"電子支付"选项，而 bankcard 选择"信用卡/扣帳卡"。

完整流程：
  阶段 0（UI）  ：预清理 —— 取消遗留的进行中订单 / 处理未支付订单
  阶段 1（接口）：司机端 API 登录 → 出车上线 → Socket → 清理缓存
  阶段 2（UI）  ：拉起 App → 配置起终点 → 选择打錶的士 → 选择電子支付方式
               → 確認呼叫 → 检测登录态 → 未登录则登录后重新下单 → 等待下单成功
  阶段 3（接口）：轮询订单获取 order_no → 接单 → 状态流转
               → 确认账单 → 确认收款 → 收车下线
  阶段 4（UI）  ：订单结束后检测到支付页面 → 选择信用卡/扣帳卡 → 確認支付
               → 银行卡表单填写（卡号/有效期/CVV/持卡人）→ 請支付
               → 3D Secure OTP 验证页 → 输入验证码 → Verify → 返回 App → 返回首页
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
class TestMeterEpayment(TestOrderBase):
    """打錶的士 + 電子支付

    继承 TestOrderBase，自动执行：
    UI 下单（打錶的士 + 電子支付）→ 司机端接口接单 → 订单流转 → 结束行程
    → 订单结束后支付页面选择信用卡/扣帳卡 → 確認支付
    → 银行卡表单填写 → 3D Secure OTP 验证 → 支付成功 → 返回首页
    """

    __test__ = True            # 标记为可被 pytest 收集的测试类（基类中 __test__ = False）
    CAR_TYPE = "meter"         # 车型：打錶的士（按表计费）
    PAYMENT = "epayment"       # 支付方式：電子支付（订单结束后走信用卡/扣帳卡支付流程）


if __name__ == "__main__":
    # 支持直接运行此文件：pytest 执行本文件，-v 显示详细输出，-s 不捕获 print
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
