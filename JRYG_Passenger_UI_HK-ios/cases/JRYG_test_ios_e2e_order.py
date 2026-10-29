"""
港版阳光出行 iOS 乘客端 E2E 自动化用例（重构版）
==============================================================================
执行顺序：
  1. 打开App（如已打开则跳过）
  2. 登录（如已登录则跳过）
  3. 下单：
     3.1 包车价的士（支付方式: Alipay HK → 银行卡支付）
     3.2 打表的士：
         - 先选择后付方式下单，订单完成后
         - 再选择现金方式下单完成订单

设计原则：
  - 打开App和登录各自独立为模块，支持智能跳过
  - 下单按顺序执行：先包车价，再打表（后付→现金）
==============================================================================
使用前置：
1. WDA 已在手机上运行 (Automation Running)
2. tidevice/iproxy 已转发 8100 端口
3. 司机端 App 已登录且处于出车状态
4. 运行: python -m pytest cases/JRYG_test_ios_e2e_order.py -s
==============================================================================
"""

import os
import sys

import pytest

# 添加框架根路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_ios_open_app import IOSOpenApp
from jryg_hk_ios.JRYG_ios_login import IOSLogin
from jryg_hk_ios.JRYG_ios_order_charter import IOSOrderCharter
from jryg_hk_ios.JRYG_ios_order_meter import IOSOrderMeter


class TestJRYGE2EOrder(IOSOpenApp, IOSLogin, IOSOrderCharter, IOSOrderMeter):
    """
    E2E 全流程测试：
    打开App → 登录 → 包车价下单 → 打表下单（后付→现金）
    通过多继承组合各模块的能力
    """

    @classmethod
    def setup_class(cls):
        """初始化 WDA 客户端和页面监控器"""
        if not cls.init_wda(output_subdir="e2e_order"):
            pytest.fail("WDA 物理通道未就绪，未执行订单流程，不得判为通过", pytrace=False)

    @classmethod
    def teardown_class(cls):
        """类级清理：释放设备连接与相关资源。

        :return: None。"""
        cls.cleanup_wda()
        logger.info("【E2E】测试结束，资源已释放")

    def test_e2e_full_flow(self):
        """E2E 全流程：打开App → 登录 → 包车价下单 → 打表下单（后付→现金）"""
        self.order_guard = None
        self.e2e_verified = False
        try:
            scenarios = self._order_scenarios()
            assert self.open_passenger_app(), "打开 App 失败"
            assert self.login_passenger(), "App UI登录失败"
            self._verify_passenger_account()
            guard = self._ensure_order_guard()
            for scenario in scenarios:
                if scenario == "charter":
                    self.order_charter_taxi()
                else:
                    self.order_meter_taxi(payment_method=scenario)
            guard.assert_all_completed(len(scenarios))
            self.e2e_verified = True
            logger.info("【E2E 已验证完成】所有订单均由11000005接单、已完成且已支付，无未完成订单")
        except Exception as e:
            self._capture("99_error")
            logger.error("【E2E 流程失败】%s", e)
            raise
        finally:
            if self.order_guard is not None:
                self.order_guard.api.close()
