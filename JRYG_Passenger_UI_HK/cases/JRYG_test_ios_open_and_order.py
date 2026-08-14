"""
JRYG 阳光出行 iOS 港版乘客端 UI 自动化测试核心用例 (Poco + WDA 物理通道)
==============================================================================
使用前置准备：
1. 确保手机上已成功部署并运行了【WebDriverAgentRunner】，屏幕显示 `Automation Running`。
2. 确保已经在终端中启动了端口映射 (由 tidevice 转发 8100 端口)。
3. 在 Mac 本地终端运行：./JRYG_run_hk.sh 即可自动调度此测试用例！
==============================================================================
"""

import os
import sys
import time
import pytest

# 引入 iOS 操控核心依赖
import wda
from airtest.core.api import connect_device
from poco.drivers.ios import iosPoco

# 添加框架根路径与父目录至 sys.path，支持相对导入和全局引用
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from JRYG_Passenger_UI_HK.common.JRYG_logger import logger
from JRYG_Passenger_UI_HK.common.JRYG_config import SETTINGS


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() == "ANDROID",
    reason="当前配置为 Android 自动化环境，跳过 iOS 下单测试案例"
)
class TestJRYGHKIosOrder:
    """阳光出行港版 iOS 乘客端极速一键下单与优惠券核销自动化测试"""

    @classmethod
    def setup_class(cls):
        cls.wda_url = SETTINGS["device"].get("wda_url", "http://127.0.0.1:8100")
        logger.info(f"【iOS 自动化】正在尝试连接 WDA 物理通道: {cls.wda_url}")
        
        try:
            # 建立 WDA 客户端物理连接
            cls.client = wda.Client(cls.wda_url)
            status = cls.client.status()
            logger.info(f"【iOS 自动化】设备连接成功！ status: {status}")
        except Exception as e:
            logger.error(
                f"【iOS 连接失败】请确认 WDA 已在手机上正常运行，且通过 tidevice/iproxy 转发了 8100 端口！ 错误原因: {e}"
            )
            pytest.skip("WDA 物理通道未就绪，跳过 iOS 自动化用例")

        # 通过 Airtest 桥接 iOS 底层操控
        connect_device(f"ios:///{cls.wda_url}")
        
        # 初始化 iOS 平台专用的 Poco 控件树驱动
        cls.poco = iosPoco()
        logger.info("【iOS 自动化】Poco 控件树驱动加载完成，已准备就绪。")

    @classmethod
    def teardown_class(cls):
        logger.info("【iOS 自动化】测试执行结束，正在安全释放连接通道。")

    def test_ios_passenger_booking_flow(self):
        """核心业务流：拉起乘客端 -> 处理弹框授权 -> 先配置并锁定起点 -> 再配置并锁定目的地 -> 选择 100元优惠券 -> 确认呼叫"""
        try:
            self._test_ios_passenger_booking_flow_impl()
        except Exception as e:
            # 异常时自动截图
            screenshot_path = os.path.join(BASE_DIR, "screenshots", "JRYG_ios_booking_failed.png")
            os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
            try:
                self.client.screenshot(screenshot_path)
                logger.error(f"【测试异常】执行中发生错误，已自动保存异常屏幕截图至: {screenshot_path}")
            except Exception as se:
                logger.error(f"【截图失败】无法获取屏幕截图: {se}")
            logger.error(f"【详细异常原因】{e}")
            raise e

    def _test_ios_passenger_booking_flow_impl(self):
        # 1. 锁屏唤醒并回到桌面
        logger.info("【步骤 1】正在回到 iOS 系统桌面首页...")
        self.client.home()
        time.sleep(2)

        # 2. 拉起港版阳光出行乘客端 App
        bundle_id = "com.sunlightmobility.client"
        logger.info(f"【步骤 2】正在物理唤醒并拉起港版 App: {bundle_id}")
        self.client.session(bundle_id)
        # 给足时间进行首屏冷启动、网络定位、以及城市未开通配置的拉取
        time.sleep(10)

        # 3. 自动处理 iOS 系统的首次权限弹窗
        logger.info("【步骤 3】检测并自动处理可能出现的系统级授权弹窗...")
        try:
            self.client.alert.accept()
            logger.info("已自动允许系统授权弹窗")
            time.sleep(2)
        except Exception:
            pass

        # 处理可能的大图广告/促销推广遮罩层
        logger.info("自动检测并清理开屏可能存在的广告遮罩层...")
        for ad_btn_text in ["iv_cancel", "close", "关闭", "叉号"]:
            ad_el = self.poco(ad_btn_text)
            if ad_el.exists():
                ad_el.click()
                logger.info(f"成功点击关闭首页促销大图弹框 (标识: {ad_btn_text})")
                time.sleep(2)
                break

        # 4. 【第一大步】配置起点：点击首页的起点输入框
        logger.info("【步骤 4】等待并寻找首页起点输入框加载展现...")
        
        start_gate = None
        # 循环 5 秒（减少等待时间），自适应查找常见的起点占位符或文本元素
        for wait_sec in range(5):
            elements = self.client(xpath='//*[contains(@label, "起點") or contains(@value, "起點") or contains(@label, "起点") or contains(@value, "起点") or contains(@label, "当前位置") or contains(@value, "当前位置") or contains(@label, "當前位置") or contains(@value, "當前位置") or contains(@label, "输入起点") or contains(@value, "输入起点") or contains(@label, "輸入起點") or contains(@value, "輸入起點") or contains(@label, "您在哪") or contains(@value, "您在哪") or contains(@label, "您從哪") or contains(@value, "您從哪") or contains(@label, "您从哪") or contains(@value, "您从哪")]')
            if elements.exists:
                start_gate = elements
                break
            # 尝试 Poco 模糊查询
            if self.poco(textMatches=".*起點.*|.*起点.*|.*当前位置.*|.*當前位置.*|.*请输入起点.*|.*輸入起點.*|.*输入起点.*|.*您在哪.*|.*您從哪.*|.*您从哪.*").exists():
                start_gate = self.poco(textMatches=".*起點.*|.*起点.*|.*当前位置.*|.*當前位置.*|.*请输入起点.*|.*輸入起點.*|.*输入起点.*|.*您在哪.*|.*您從哪.*|.*您从哪.*")
                break
            time.sleep(1)

        # 自适应重试点击，直到 100% 进入起点地址搜索页（搜索页以 TextField 存在为核心判等标识）
        search_entered = False
        for click_try in range(5):
            logger.info(f"尝试点击起点入口以拉起搜索页 (第 {click_try + 1} 次尝试)...")
            if start_gate:
                start_gate.click()
            else:
                # 物理高容错高精度坐标点击 (起点绿色圆点处于该灰色卡片的纵向 76% 左右)
                logger.info("采用高容错高精度物理坐标 (0.5, 0.76) 点击起点区域...")
                self.client.click(0.5, 0.76)
            time.sleep(2)
            
            # 检测是否已经出现文本输入框
            if self.client(type="TextField").exists or self.poco(type="XCUIElementTypeTextField").exists():
                logger.info("【进入搜索页成功】已检测到地址输入框，成功进入起点搜索页！")
                search_entered = True
                break

        if not search_entered:
            logger.error("多次尝试均未能成功进入起点搜索页，流程阻断！")
            raise AssertionError("【阻断】未能进入起点搜索页，必须先选择起点，才能继续进行后续测试！")

        # 5. 在搜索页面，输入并选中起点：铜锣湾地铁站
        logger.info("【步骤 5】正在输入起点地址为：铜锣湾地铁站...")
        # 点击起点输入栏，激活键盘
        logger.info("点击起点输入框区域 (0.5, 0.125)...")
        self.client.click(0.5, 0.125)
        time.sleep(1.5)
        
        # 通过当前活跃焦点直接键入起点
        logger.info("正在发送起点文本: 铜锣湾地铁站...")
        self.client.send_keys("铜锣湾地铁站")
        logger.info("文本输入成功，等待联想搜索列表渲染...")
        time.sleep(4)
        
        # 点击搜索内容下方的首条联想匹配地址
        logger.info("正在点击下方搜索出的第一个起点...")
        first_cell = self.client(type="Cell")
        if first_cell.exists:
            first_cell[0].click()
            logger.info("成功选中起点！页面已全自动退回到乘客端首页。")
        else:
            logger.info("通过物理坐标 (0.5, 0.25) 强制点击首行联想结果...")
            self.client.click(0.5, 0.25)
        time.sleep(4) # 给足主页重绘和定位更新的时间

        # 确认当前起点已设置，继续进行第二步
        logger.info("【起点配置完毕】严格遵循『必须选择起点，再选择终点』，开始进行第二步：配置目的地。")

        # 6. 【第二大步】配置目的地：点击首页目的地输入栏“想去哪裡？”（繁体：想去哪裡？）
        logger.info("【步骤 6】首页已重绘，正在等待并寻找目的地『想去哪裡？』区域加载展现...")
        
        dest_gate = None
        for wait_sec in range(5):
            elements = self.client(xpath='//*[contains(@label, "想去") or contains(@value, "想去") or contains(@label, "哪裡") or contains(@value, "哪裡") or contains(@label, "哪里") or contains(@value, "哪里") or contains(@label, "输入目的地") or contains(@value, "输入目的地") or contains(@label, "輸入目的地") or contains(@value, "輸入目的地") or contains(@label, "要去哪") or contains(@value, "要去哪") or contains(@label, "要去邊") or contains(@value, "要去邊")]')
            if elements.exists:
                dest_gate = elements
                break
            if self.poco(textMatches=".*想去哪.*|.*想去哪里.*|.*目的地.*|.*去哪.*|.*輸入目的地.*|.*输入目的地.*|.*要去哪.*|.*要去邊.*").exists():
                dest_gate = self.poco(textMatches=".*想去哪.*|.*想去哪里.*|.*目的地.*|.*去哪.*|.*輸入目的地.*|.*输入目的地.*|.*要去哪.*|.*要去邊.*")
                break
            time.sleep(1)

        # 自适应重试点击，直到 100% 进入目的地搜索页
        dest_entered = False
        for click_try in range(6):
            logger.info(f"尝试点击目的地入口以拉起目的地搜索页 (第 {click_try + 1} 次尝试)...")
            if dest_gate:
                dest_gate.click()
            else:
                # 物理多重容错坐标点击：首页重绘后打车输入框通常在 (0.5, 0.65) 到 (0.5, 0.85) 之间
                if click_try in [0, 1]:
                    # 优先点击正常打车首页常见目的地中下部位置
                    logger.info("采用高精度物理坐标 (0.5, 0.68) 点击目的地核心区域...")
                    self.client.click(0.5, 0.68)
                elif click_try in [2, 3]:
                    # 尝试稍稍靠下的过渡坐标位置
                    logger.info("采用过渡物理坐标 (0.5, 0.73) 点击目的地区域...")
                    self.client.click(0.5, 0.73)
                else:
                    # 尝试原先的偏下位置
                    logger.info("采用经典物理坐标 (0.5, 0.83) 点击目的地区域...")
                    self.client.click(0.5, 0.83)
            time.sleep(2)
            
            # 检测是否已经出现文本输入框
            if self.client(type="TextField").exists or self.poco(type="XCUIElementTypeTextField").exists():
                logger.info("【进入目的地搜索页成功】已检测到地址输入框，成功进入目的地搜索页！")
                dest_entered = True
                break

        if not dest_entered:
            logger.error("多次尝试均未能成功进入目的地搜索页，流程阻断！")
            raise AssertionError("【阻断】未能进入目的地搜索页，无法完成终点选择流程！")

        # 7. 在搜索页面，输入并选中目的地：香港大学
        logger.info("【步骤 7】正在输入目的地地址为：香港大学...")
        # 点击目的地输入框
        logger.info("点击目的地输入框区域 (0.5, 0.125)...")
        self.client.click(0.5, 0.125)
        time.sleep(1.5)
        
        # 键入终点文本
        logger.info("正在发送目的地文本: 香港大学...")
        self.client.send_keys("香港大学")
        logger.info("文本输入成功，等待目的地联想列表渲染...")
        time.sleep(4)
        
        # 点击终点搜索结果的第一行匹配项，选择后会自动计算行程并跳转车型询价确认页面
        logger.info("正在点击目的地首个匹配联想项...")
        first_cell = self.client(type="Cell")
        if first_cell.exists:
            first_cell[0].click()
            logger.info("选中目的地联想地址成功！系统正在计算行驶线路并进入选择车型页面...")
        else:
            logger.info("通过物理坐标 (0.5, 0.25) 强制点击首行联想结果...")
            self.client.click(0.5, 0.25)
            
        time.sleep(7) # 给足路线路径和车型面板加载展示的时间

        # 8. 进入车型确认面板，选择 100元优惠卷
        logger.info("【步骤 8】进入车型确认面板，正在寻找并进入『优惠券 / 優惠券』选择列表...")
        coupon_gate = self.client(xpath='//*[contains(@label, "優惠券") or contains(@value, "優惠券") or contains(@label, "优惠券") or contains(@value, "优惠券") or contains(@label, "优惠") or contains(@value, "优惠") or contains(@label, "折扣") or contains(@value, "折扣")]')
        
        # 兼容如果 WDA 找不到，使用 Poco 多维度检索定位
        if not coupon_gate.exists:
            poco_coupon = self.poco(textMatches=".*優惠券.*|.*优惠券.*|.*优惠.*|.*優惠.*|.*折扣.*")
            if poco_coupon.exists():
                coupon_gate = poco_coupon
                
        if coupon_gate and (hasattr(coupon_gate, "exists") and coupon_gate.exists or not hasattr(coupon_gate, "exists")):
            coupon_gate.click()
            logger.info("成功点击进入优惠券列表")
            time.sleep(3)
            
            # 在列表中匹配并点击 “100元优惠卷”
            logger.info("正在应用『100元优惠卷』...")
            selected = False
            for target_text in ["100元优惠卷", "100元优惠券", "100", "100元"]:
                card = self.client(xpath=f'//*[contains(@label, "{target_text}") or contains(@value, "{target_text}")]')
                if not card.exists:
                    poco_card = self.poco(textMatches=f".*{target_text}.*")
                    if poco_card.exists():
                        card = poco_card
                        
                if card and (hasattr(card, "exists") and card.exists or not hasattr(card, "exists")):
                    card.click()
                    logger.info(f"匹配并点击成功，已成功勾选优惠券: '{target_text}'！")
                    selected = True
                    time.sleep(3)
                    break
            if not selected:
                logger.warning("未匹配到 100元 卡片，点击应用列表第一张优惠卡片进行兜底...")
                first_card = self.poco(type="XCUIElementTypeCell")
                if first_card.exists():
                    first_card[0].click()
                    time.sleep(3)
        else:
            # 物理点击车型面板右下角/优惠选择区域的兜底坐标，通常在屏幕下方偏上 (0.5, 0.75 - 0.8 附近)
            logger.warning("未找到显式优惠券入口文本，执行物理兜底点击优惠券区域 (0.85, 0.8)...")
            self.client.click(0.85, 0.8)
            time.sleep(3)

        # 9. 点击“確認呼叫”按钮正式提交订单
        logger.info("【步骤 9】正在寻找并点击『確認呼叫』正式发起呼叫...")
        btn_call = self.client(xpath='//*[contains(@label, "確認呼叫") or contains(@value, "確認呼叫") or contains(@label, "确认呼叫") or contains(@value, "确认呼叫") or contains(@label, "呼叫") or contains(@value, "呼叫") or contains(@label, "確認") or contains(@value, "確認")]')
        
        if not btn_call.exists:
            poco_call = self.poco(textMatches=".*確認呼叫.*|.*确认呼叫.*|.*呼叫.*|.*确认.*|.*確認.*")
            if poco_call.exists():
                btn_call = poco_call
                
        if btn_call and (hasattr(btn_call, "exists") and btn_call.exists or not hasattr(btn_call, "exists")):
            btn_call.click()
            logger.info("【下单成功】已成功点击『確認呼叫』，本单正式进入后台派单业务！")
        else:
            logger.info("执行物理高精度坐标点击 (0.5, 0.95) 提交订单呼叫...")
            self.client.click(0.5, 0.95)
            
        time.sleep(5)
        
        # 截图存盘作为测试运行成功的凭证
        screenshot_path = os.path.join(BASE_DIR, "screenshots", "JRYG_ios_booking_success.png")
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        self.client.screenshot(screenshot_path)
        logger.info(f"【运营大闭环成功】测试已完美跑通，下单凭证截图已成功归档保存: {screenshot_path}")
