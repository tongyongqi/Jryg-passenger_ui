"""
JRYG 阳光出行 iOS 乘客端 UI 自动化测试用例 (自适应 WDA 物理通道)
==============================================================================
使用前置准备：
1. 确保 Mac 上连接了 iPhone，且 iPhone 已开启【开发者模式】。
2. 确保 iPhone 上已成功通过 Xcode 部署并运行了【WebDriverAgentRunner】。
3. 确保已经在终端中运行了端口转发：iproxy 8100 8100
4. 在 PyCharm 中直接点击右键运行此测试，或运行：./JRYG_run.sh
==============================================================================
"""

import os
import sys
import time
import pytest

# 引入 iOS 操控核心依赖
import wda
from airtest.core.api import connect_device, sleep
from poco.drivers.ios import iosPoco

# 添加框架根路径与父目录至 sys.path，支持相对导入和全局引用
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from JRYG_auto_project.common.JRYG_logger import logger
from JRYG_auto_project.common.JRYG_config import SETTINGS, TEST_DATA_FILE


class TestJRYGIosOrder:
    """阳光出行 iOS 乘客端自动化下单业务验证"""

    @classmethod
    def setup_class(cls):
        # 1. 连接本地已做 iproxy 转发的 iOS 设备物理通道
        cls.wda_url = "http://127.0.0.1:8100"
        logger.info(f"【iOS 自动化】正在尝试连接 WDA 物理通道: {cls.wda_url}")
        
        try:
            # 建立底层 WDA 物理连接客户端
            cls.client = wda.Client(cls.wda_url)
            # 验证连接状态，如果手机未锁屏且 WDA 运行正常，此处可成功获取 status
            status = cls.client.status()
            logger.info(f"【iOS 自动化】设备连接成功！ status: {status}")
        except Exception as e:
            logger.error(
                f"【iOS 连接失败】请确认已在终端执行了 'iproxy 8100 8100'，且手机上 WDA 已成功启动！ 错误原因: {e}"
            )
            pytest.skip("WDA 物理通道未就绪，跳过 iOS 自动化用例")

        # 2. 通过 Airtest 连接 iOS
        connect_device(f"ios:///{cls.wda_url}")
        
        # 3. 初始化 iOS 平台专用的 Poco 控件树驱动
        cls.poco = iosPoco()
        logger.info("【iOS 自动化】Poco 控件树驱动加载完成，准备执行交互...")

    @classmethod
    def teardown_class(cls):
        logger.info("【iOS 自动化】测试执行结束，正在释放连接...")

    def test_ios_passenger_order_flow(self):
        """测试：iOS 乘客端打开App、处理权限/广告、输入起终点并跳转询价页面"""
        # 1. 锁屏唤醒并回到 iPhone 桌面主页
        logger.info("回到 iOS 系统主页...")
        self.client.home()
        time.sleep(2)

        # 2. 拉起阳光出行 iOS 客户端 (通过其 Bundle ID)
        bundle_id = "com.jryg.client"  # 阳光出行 iOS 包名
        logger.info(f"拉起 iOS 阳光出行 App: {bundle_id}")
        self.client.session(bundle_id)
        time.sleep(6)

        # 3. 自动检测并同意 iOS 系统弹框权限（如：定位权限、通知权限、无线网络权限）
        logger.info("检测系统系统授权弹窗...")
        try:
            # 自动点击系统弹窗中的“允许”、“使用App期间允许”或“无线局域网与蜂窝网络”
            self.client.alert.accept()
            logger.info("已自动允许系统权限弹窗")
            time.sleep(2)
        except Exception:
            pass

        # 4. 自动处理乘客端开屏广告或弹窗
        logger.info("处理首页开屏广告及促销弹窗...")
        ad_close_btn = self.poco("iv_cancel")  # 或者是 iOS 上的特定 Accessibility 标识
        if ad_close_btn.exists():
            ad_close_btn.click()
            logger.info("已点击关闭首页广告弹窗")
            time.sleep(2)

        # 5. 点击“想要去哪里？”输入框
        logger.info("点击目的地输入栏...")
        dest_input = self.poco("想要去哪里？")
        if not dest_input.exists():
            # 兼容：如果 iOS 控件树上显示的是 placeholder 或者其他文字标识
            dest_input = self.poco(text="您要去哪儿")
            
        if dest_input.exists():
            dest_input.click()
            time.sleep(2)
            
            # 输入目的地 (这里会拉起 iOS 软键盘并执行高速键入)
            dest_address = "蓟门桥地铁A口"
            logger.info(f"正在键入目的地: {dest_address}")
            dest_input.set_text(dest_address)
            time.sleep(3)
            
            # 点击搜索出的第一条匹配地址列表项
            # 在 iOS 上，列表项通常是 XCUIElementTypeCell 类型
            first_result = self.poco(type="XCUIElementTypeCell")
            if first_result.exists():
                first_result[0].click()
                logger.info("已在地址列表中选中第一个目的地匹配项")
                time.sleep(4)
                
        # 6. 截图保存运行结果
        screenshot_path = os.path.join(BASE_DIR, "screenshots", "JRYG_ios_order_quote.png")
        self.client.screenshot(screenshot_path)
        logger.info(f"【iOS 运行成功】询价页面截图已保存至: {screenshot_path}")
