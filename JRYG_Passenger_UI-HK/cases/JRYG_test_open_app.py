"""
港版阳光出行乘客端 UI 自动化 —— 验证打开 App 并成功加载测试用例
"""

import pytest
import os
import sys
import time

# 添加测试框架核心根路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from JRYG_Passenger_UI-HK.common.JRYG_logger import logger
from JRYG_Passenger_UI-HK.common.JRYG_config import SETTINGS
from JRYG_Passenger_UI-HK.common.JRYG_connect_device import JRYG_HKDevice


class TestJRYGOpenAppHK:
    """港版阳光出行乘客端基础启动测试类"""

    @classmethod
    def setup_class(cls):
        cls.device = JRYG_HKDevice()
        logger.info("【港版测试】准备连接设备通道...")
        cls.driver = cls.device.connect()

    @classmethod
    def teardown_class(cls):
        cls.device.disconnect()
        logger.info("【港版测试】设备连接已释放，测试流正常结束")

    def test_passenger_hk_launch(self):
        """测试用例：验证港版阳光出行客户端是否能被正确拉起，并处于活动 Session 状态"""
        logger.info("正在执行：[港版 App 启动检测]")
        
        # 1. 验证 SessionID
        assert self.driver.session_id is not None, "错误：Appium 无法生成活动 Session，App 启动失败！"
        logger.info(f"【启动成功】成功拉起 App，当前 Session 标识: {self.driver.session_id}")
        
        # 2. 处理可能出现的权限或通知确认弹窗
        # 在 iOS 上利用底层 Accept 机制一键自动跳过任何可能阻挡的系统对话框
        if SETTINGS.get("device", {}).get("platform_name", "iOS").upper() == "IOS":
            try:
                self.driver.execute_script("mobile: alert", {"action": "accept"})
                logger.info("【系统权限】自动同意了 iOS 首次拉起的定位/通知弹窗")
            except Exception:
                pass
                
        # 3. 页面完全加载等待并截图记录
        time.sleep(5)
        screenshot_dir = os.path.join(BASE_DIR, "screenshots")
        if not os.path.exists(screenshot_dir):
            os.makedirs(screenshot_dir)
            
        screenshot_file = os.path.join(screenshot_dir, "JRYG_hk_passenger_home.png")
        self.driver.save_screenshot(screenshot_file)
        logger.info(f"【界面截图】首屏截图已输出并保存至: {screenshot_file}")
