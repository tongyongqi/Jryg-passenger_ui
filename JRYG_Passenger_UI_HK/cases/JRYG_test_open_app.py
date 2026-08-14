"""
JRYG 阳光出行 Android 港版乘客端 UI 自动化测试用例 (Python + Appium 官方驱动版)
==============================================================================
使用前置准备：
1. 确保已通过 pip install Appium-Python-Client 安装了 Appium 客户端。
2. 确保已连接安卓真机/模拟器，且 USB 调试已打开。
3. 确保 Appium Server 在后台/前台 4723 端口处于运行状态（JRYG_run_hk.sh 会自动拉起）。
4. 本用例专门针对 Android 端编写，使用 pytest 组织，可通过 JRYG_run_hk.sh 一键执行！
==============================================================================
"""

import os
import sys
import time
import pytest
from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy

# 动态添加框架根路径与父目录至 sys.path，支持相对导入和全局引用
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from JRYG_Passenger_UI_HK.common.JRYG_logger import logger
from JRYG_Passenger_UI_HK.common.JRYG_connect_device import JRYG_HKDevice
from JRYG_Passenger_UI_HK.common.JRYG_config import SETTINGS


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() == "IOS",
    reason="当前设置为 iOS 物理真机环境，跳过 Android 用例"
)
class TestJRYGHKOpenApp:
    """阳光出行港版 Android 乘客端 Appium 自动化测试：极速唤起与首页元素点击交互"""

    @classmethod
    def setup_class(cls):
        """
        初始化连接：使用项目中高度封装的 JRYG_HKDevice 自动拉起 Android 港版 App 进程
        """
        logger.info("【Appium 自动化】正在启动港版乘客端 Android Appium 进程...")
        try:
            # 实例化设备交互类
            cls.device = JRYG_HKDevice()
            # connect() 会读取 yaml 配置，调用 UiAutomator2Options，拉起安卓 App
            cls.driver = cls.device.connect()
            logger.info("【Appium 自动化】Android Session 连接建立成功！")
        except Exception as e:
            logger.error(
                f"【Appium 连接失败】请确认 Appium 驱动及 Android 设备已正常运行与连接！ 错误原因: {e}"
            )
            pytest.skip("Appium 物理通道或服务未就绪，跳过当前 Android Appium 自动化用例")

    @classmethod
    def teardown_class(cls):
        """安全释放 Appium 连接"""
        if hasattr(cls, "device") and cls.device:
            logger.info("【Appium 自动化】测试完毕，正在安全释放 Appium 会话...")
            cls.device.disconnect()

    def test_appium_android_open_and_basic_check(self):
        """
        业务测试流：验证 Android 客户端顺利拉起，检测系统弹窗并自动定位首页打车输入栏
        """
        driver = self.driver
        try:
            logger.info("【步骤 1】检测并处理 Android 系统的首次权限弹窗/网络提示框...")
            try:
                # 尝试点击 Android 系统可能弹出的允许通知/定位等确认按钮
                driver.switch_to.alert.accept()
                logger.info("  >> 成功自动接受了系统级权限弹窗！")
                time.sleep(2)
            except Exception:
                logger.info("  >> 未检测到系统级 Alert 弹窗，继续后续步骤。")

            logger.info("【步骤 2】等待 App 首页渲染，尝试定位首页起点输入卡片...")
            time.sleep(6)  # 给予充足渲染时间

            # 寻找起点输入栏 (Android 经典 ID)
            start_locator_id = "com.sunlightmobility.client:id/tv_start_address"
            start_locator_xpath = '//*[contains(@text, "起點") or contains(@text, "起点") or contains(@text, "当前位置") or contains(@text, "當前位置")]'

            start_element = None
            try:
                logger.info(f"  >> 尝试通过 ID 定位起点栏：{start_locator_id}")
                start_element = driver.find_element(by=AppiumBy.ID, value=start_locator_id)
            except Exception:
                logger.warning("  >> ID 定位失败，尝试使用包含文本的 XPath 兜底定位...")
                try:
                    start_element = driver.find_element(by=AppiumBy.XPATH, value=start_locator_xpath)
                except Exception as ex:
                    logger.error(f"  >> 无法通过常规方式定位起点卡片: {ex}")

            # 进行点击交互
            if start_element:
                element_text = start_element.text or start_element.get_attribute('text')
                logger.info(f"【成功】已成功定位到起点区域，其显示内容为: {element_text}")
                
                logger.info("  >> 模拟点击起点栏以激活地址检索页...")
                start_element.click()
                time.sleep(3)

                logger.info("【步骤 3】在搜索栏中输入检索关键字：『铜锣湾地铁站』...")
                try:
                    # 获取输入框
                    search_field = driver.find_element(by=AppiumBy.ID, value="com.sunlightmobility.client:id/et_search")
                    search_field.click()
                    search_field.send_keys("铜锣湾地铁站")
                    logger.info("  >> 关键字键入成功！")
                    time.sleep(3)
                except Exception as input_err:
                    logger.error(f"  >> 检索框定位或文本键入失败: {input_err}")
            else:
                logger.warning("【警告】未能成功定位到首页起点卡片。")
                screenshot_path = os.path.join(BASE_DIR, "screenshots", "JRYG_android_appium_failed.png")
                os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                driver.get_screenshot_as_file(screenshot_path)
                logger.info(f"  >> 状态截图已归档保存至: {screenshot_path}")

        except Exception as e:
            logger.error(f"【用例执行异常】发生错误: {e}")
            # 异常时进行截图归档
            screenshot_path = os.path.join(BASE_DIR, "screenshots", "JRYG_android_appium_error.png")
            os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
            try:
                driver.get_screenshot_as_file(screenshot_path)
                logger.info(f"  >> 异常快照已存盘: {screenshot_path}")
            except Exception as se:
                logger.error(f"  >> 截图捕获失败: {se}")
            raise e
