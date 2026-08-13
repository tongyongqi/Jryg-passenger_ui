import pytest
import time
import os
import sys

# 添加测试框架根目录及原脚本目录到 sys.path，保证 Appium 辅助类能被正常调用
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(BASE_DIR)
sys.path.append(BASE_DIR)
sys.path.append(PARENT_DIR)

from JRYG_Passenger_UI.common.JRYG_logger import logger
from JRYG_Passenger_UI.common.JRYG_config import SETTINGS
from JRYG_Passenger_UI.common.JRYG_connect_device import AndroidDevice

class TestJRYGLogin:
    """阳光出行乘客端登录相关测试用例类"""
    
    @classmethod
    def setup_class(cls):
        cls.device = AndroidDevice()
        cls.driver = cls.device.connect()
        logger.info("【乘客端】Appium Session 已创建，开始执行登录测试")

    @classmethod
    def teardown_class(cls):
        cls.device.disconnect()
        logger.info("【乘客端】登录测试流程运行完毕，Session 已安全断开")

    def test_passenger_login(self):
        """测试：验证输入手机号、获取验证码并完成自动登录流程"""
        from JRYG_Passenger_UI.common.JRYG_config import TEST_DATA_FILE
        import json
        
        with open(TEST_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        phone = data["phone_number"]
        code = data["verify_code"]
        
        logger.info(f"正在进行登录，加载测试数据手机号: {phone}")
        pkg = SETTINGS['packages']['passenger']
        
        # 增加登录态预校验：如果已经处于首页，直接通过测试
        if self.device.is_element_present(self.device.by_id(f"{pkg}:id/ll_start")) or \
           self.device.is_element_present(self.device.by_text("想要去哪里？")):
            logger.info("【乘客端】检测到已处于登录状态（首页），跳过登录输入步骤，登录验证通过！")
            return
            
        # 1. 查找并点击手机号输入框并输入手机号
        phone_input = self.device.find_element(self.device.by_id(f"{pkg}:id/et_phone"))
        phone_input.click()
        phone_input.clear()
        phone_input.send_keys(phone)
        time.sleep(1)
        
        # 2. 点击“下一步”跳转验证码输入界面
        btn_next = self.device.find_element(self.device.by_text("下一步"))
        btn_next.click()
        time.sleep(2)
        
        # 3. 处理可能会遮挡的用户协议同意弹窗
        try:
            agree_btn = self.device.find_element(self.device.by_text("同意并继续"), timeout=3)
            agree_btn.click()
            time.sleep(1)
        except Exception:
            pass
            
        # 4. 寻找并输入 6 位快捷登录短信验证码
        code_input = self.device.find_element(self.device.by_id(f"{pkg}:id/et_code"))
        code_input.click()
        code_input.clear()
        code_input.send_keys(code)
        time.sleep(2)
        
        # 5. 点击提交“登录”
        btn_login = self.device.find_element(self.device.by_text("登录"))
        btn_login.click()
        time.sleep(5)
        
        logger.info("JRYG 乘客端登录流程步骤执行全部通过")
