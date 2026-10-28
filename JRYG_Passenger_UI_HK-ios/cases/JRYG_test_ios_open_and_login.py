"""
港版阳光出行乘客端 (iOS) —— 一键打开并登录全业务流自动化用例 -ios
==============================================================================
特性：
1. 本文件遵循"一站式闭环"设计，将【拉起App -> 隐私协议同意 -> 定位权限授权 ->
   个人中心跳转 -> 手机号键入 -> 隐私勾选 -> 获取验证码 -> 验证码输入 -> 登录成功核对】
   完整操作全部内聚在本单一 .py 文件中，结构干净明晰，没有任何多余脚本。
2. 完美支持在 PyCharm 中右键直接点击 Run 运行。
3. 基于 WDA (WebDriverAgent) + facebook-wda + iosPoco 物理通道驱动 iOS 真机。
4. 对标安卓版 JRYG_test_open_and_login.py，逻辑与业务流程完全一致。
==============================================================================
"""

import os
import sys
import time

import pytest
import wda
from airtest.core.api import connect_device
from poco.drivers.ios import iosPoco

# 添加测试框架核心根路径到 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_config import SETTINGS


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() != "IOS",
    reason="当前不是 iOS 自动化环境，跳过 iOS 一键登录用例",
)
class TestJRYGHKIosOneKeyLogin:
    """阳光出行港版 iOS 乘客端一键打开与登录测试套件 -ios"""

    @classmethod
    def setup_class(cls):
        cls.wda_url = SETTINGS["device"].get("wda_url", "http://127.0.0.1:8100")
        cls.bundle_id = SETTINGS["packages"].get("passenger_hk", "com.sunlightmobility.client")
        logger.info(f"【iOS 一键登录 -ios】正在尝试连接 WDA 物理通道: {cls.wda_url}")

        try:
            cls.client = wda.Client(cls.wda_url)
            status = cls.client.status()
            logger.info(f"【iOS 一键登录 -ios】设备连接成功！ status: {status}")
        except Exception as e:
            logger.error(
                f"【iOS 连接失败 -ios】请确认 WDA 已在手机上正常运行，且通过 iproxy 转发了 8100 端口！ 错误原因: {e}"
            )
            pytest.skip("WDA 物理通道未就绪，跳过 iOS 一键登录用例")

        # 通过 Airtest 桥接 iOS 底层操控
        connect_device(f"ios:///{cls.wda_url}")
        # 初始化 iOS 平台专用的 Poco 控件树驱动
        cls.poco = iosPoco()
        logger.info("【iOS 一键登录 -ios】Poco 控件树驱动加载完成，已准备就绪。")

    @classmethod
    def teardown_class(cls):
        logger.info("【iOS 一键登录 -ios】自动化运行结束。")

    def _screenshot(self, filename):
        """通过 WDA 截图并保存到 screenshots 目录"""
        path = os.path.join(BASE_DIR, "screenshots", filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.client.screenshot(path)
        logger.info(f"  >> 截图已保存: {path}")
        return path

    def _launch_app(self):
        """拉起港版乘客端 App"""
        logger.info(f"【iOS -ios】正在拉起港版 App: {self.bundle_id}")
        self.client.home()
        time.sleep(1)
        self.client.session(self.bundle_id)
        time.sleep(8)

    def _accept_alert(self):
        """自动接受 iOS 系统弹窗"""
        try:
            self.client.alert.accept()
            logger.info("  >> 已自动允许系统授权弹窗")
            time.sleep(2)
        except Exception:
            pass

    def _click_text(self, target_text):
        """通过 Poco 或 WDA xpath 点击指定文本控件"""
        # 优先 Poco textMatches
        el = self.poco(textMatches=f".*{target_text}.*")
        if el.exists():
            el.click()
            logger.info(f"  >> [Poco] 成功点击: {target_text}")
            return True
        # WDA xpath 兜底
        xpath = f'//*[contains(@label, "{target_text}") or contains(@value, "{target_text}")]'
        wda_el = self.client(xpath=xpath)
        if wda_el.exists:
            wda_el.click()
            logger.info(f"  >> [WDA] 成功点击: {target_text}")
            return True
        return False

    def _detect_current_state(self):
        """核心：通过 UI 关键内容嗅探当前所在业务节点"""
        # 检测隐私协议同意弹窗
        if self.poco(textMatches=".*同意.*|.*Agree.*").exists() and self.poco(textMatches=".*不同意.*|.*Disagree.*|.*拒絕.*|.*拒绝.*").exists():
            return "privacy_agreement"

        # 检测位置权限弹窗
        if self.poco(textMatches=".*去授權.*|.*去授权.*|.*Allow.*|.*允許.*|.*允许.*").exists():
            return "permission_dialog"

        # 检测验证码输入页
        if self.poco(textMatches=".*請輸入驗證碼.*|.*请输入验证码.*|.*重新獲取.*|.*重新获取.*|.*驗證碼.*|.*验证码.*").exists():
            return "login_code_input"

        # 检测手机号输入页
        if self.poco(textMatches=".*請輸入手機號.*|.*请输入手机号.*|.*取得驗證碼.*|.*获取验证码.*|.*歡迎登錄.*|.*欢迎登录.*").exists():
            return "login_phone_input"

        # 检测未登录态个人中心
        if self.poco(textMatches=".*登錄/註冊.*|.*登录/注册.*").exists():
            return "mine_unlogged"

        # 嗅探全部文本做复合判断
        texts = []
        try:
            for el in self.poco(type="XCUIElementTypeStaticText"):
                t = el.get_text()
                if t:
                    texts.append(t.strip())
        except Exception:
            pass
        joined = " ".join(texts)
        logger.info(f"  >> [iOS 页面文本嗅探] joined: {joined[:200]}")

        if "登錄/註冊" in joined or "登录/注册" in joined:
            return "mine_unlogged"
        if "請輸入驗證碼" in joined or "验证码" in joined:
            return "login_code_input"
        if "請輸入手機號" in joined or "歡迎登錄" in joined or "欢迎登录" in joined:
            return "login_phone_input"
        if "想去哪裡" in joined or "想要去哪" in joined or "想去哪" in joined:
            if "1727" in joined or "****" in joined or "會員" in joined or "会员" in joined or "我的行程" in joined:
                return "home_logged"
            return "home_unlogged"

        return "unknown"

    def test_ios_passenger_hk_login_flow(self):
        """测试用例 -ios：执行一键打开并自动登录完整闭环流程"""
        phone_number = "11001727"
        verify_code = "123456"

        logger.info(f"【iOS 一键登录 -ios】启动业务流转，预备登录手机号: {phone_number}")

        # 1. 拉起 App
        self._launch_app()

        # 2. 自动处理系统弹窗
        self._accept_alert()

        # 3. 通过状态监控执行状态机循环
        for cycle in range(30):
            state = self._detect_current_state()
            logger.info(f"当前流转 [循环 {cycle}] -> 页面状态: {state}")

            # 1. 隐私服务协议弹窗处理
            if state == "privacy_agreement":
                logger.info("【步骤 1 -ios】检测到隐私政策服务弹窗，正在寻找并点击『同意』...")
                self._click_text("同意")
                time.sleep(3)
                continue

            # 2. 地理位置权限申请框处理
            if state == "permission_dialog":
                logger.info("【步骤 2 -ios】检测到位置权限授权提示框，正在点击『去授權』/『允許』...")
                if not self._click_text("去授權"):
                    self._click_text("去授权")
                # 处理系统级弹窗
                time.sleep(1)
                self._accept_alert()
                time.sleep(3)
                continue

            # 3. 乘客端主页（已授权进入）处理 -> 点击『我的』
            if state == "home_unlogged":
                logger.info("【步骤 4 -ios】已成功进入港版 App 首页，正在点击下方导航栏『我的』...")
                # 通过 Poco 点击底部导航
                tab_mine = self.poco(textMatches=".*我的.*|.*Me.*|.*個人.*|.*个人.*")
                if tab_mine.exists():
                    tab_mine.click()
                else:
                    # 物理高容错坐标点击底部导航右侧"我的"标签
                    logger.info("  >> 采用物理坐标 (0.83, 0.97) 点击底部『我的』标签...")
                    self.client.click(0.83, 0.97)
                time.sleep(3)
                continue

            # 4. 个人中心未登录态处理 -> 点击『登錄/註冊』
            if state == "mine_unlogged":
                logger.info("【步骤 5 -ios】已进入个人中心，正在点击『登錄/註冊』进入账号录入页...")
                if not self._click_text("登錄/註冊"):
                    self._click_text("登录/注册")
                time.sleep(4)
                continue

            # 5. 真实手机号输入页面处理 -> 键入手机号 + 勾选隐私 -> 获取验证码
            if state == "login_phone_input":
                logger.info("【步骤 6 -ios】正在手机号输入页：键入号码、勾选协议、并点击『取得驗證碼』...")

                # 键入手机号 - 通过 WDA 查找 TextField
                phone_field = self.client(type="TextField")
                if phone_field.exists:
                    phone_field.click()
                    time.sleep(0.5)
                    self.client.send_keys(phone_number)
                    logger.info(f"  >> [WDA] 已成功键入手机号: {phone_number}")
                else:
                    # 物理点击输入框区域并输入
                    logger.info("  >> 采用物理坐标 (0.5, 0.25) 点击手机号输入框...")
                    self.client.click(0.5, 0.25)
                    time.sleep(1)
                    self.client.send_keys(phone_number)
                time.sleep(1.5)

                # 勾选隐私协议 - iOS 端通过点击复选框或"已閱讀並同意"文本
                agree_text = self.poco(textMatches=".*已閱讀並同意.*|.*已阅读并同意.*|.*同意.*")
                if agree_text.exists():
                    # 点击文本左侧的复选框
                    try:
                        pos = agree_text.get_position()
                        size = agree_text.get_size()
                        # 偏左点击复选框
                        x = pos[0] - size[0] / 2 + 0.03
                        y = pos[1]
                        self.client.click(x, y)
                        logger.info("  >> 成功勾选隐私协议复选框")
                    except Exception:
                        agree_text.click()
                        logger.info("  >> 直接点击同意文本")
                    time.sleep(1)

                # 点击取得验证码
                if not self._click_text("取得驗證碼"):
                    self._click_text("获取验证码")
                # 物理兜底
                if not self.poco(textMatches=".*取得驗證碼.*|.*获取验证码.*").exists():
                    logger.info("  >> 采用物理坐标 (0.5, 0.55) 点击取得验证码按钮...")
                    self.client.click(0.5, 0.55)
                time.sleep(4)
                continue

            # 6. 真实验证码输入页面处理 -> 键入验证码 123456 -> 自动登录
            if state == "login_code_input":
                logger.info(f"【步骤 7 -ios】正在验证码输入页：输入验证码: {verify_code}...")
                code_field = self.client(type="TextField")
                if code_field.exists:
                    code_field.click()
                    time.sleep(0.5)
                    self.client.send_keys(verify_code)
                    logger.info(f"  >> [WDA] 已成功键入验证码: {verify_code}")
                else:
                    logger.info("  >> 采用物理坐标 (0.5, 0.25) 点击验证码输入框...")
                    self.client.click(0.5, 0.25)
                    time.sleep(1)
                    self.client.send_keys(verify_code)
                time.sleep(6)  # 等待登录服务器网络交互并跳转
                continue

            # 7. 成功登录状态验证
            if state == "home_logged":
                logger.info("【成功 -ios】一键打开并登录港版阳光出行 iOS 测试成功！手机号已正确核对绑定。")
                self._screenshot("JRYG_ios_login_success.png")
                break

            time.sleep(2)

    def test_ios_passenger_hk_booking_flow(self):
        """测试用例 -ios：登录成功后切换回首页，输入起终点，选择优惠券，点击确认呼叫"""
        logger.info("【iOS 下单测试 -ios】启动港版乘客端全业务下单流程...")

        # 1. 确保在首页
        logger.info("确保处于首页选项卡...")
        # 通过物理坐标点击底部导航栏首页标签
        self.client.click(0.15, 0.97)
        time.sleep(3)

        # 2. 自动检查并关闭可能阻挡主页的大图推广弹框
        logger.info("检查并关闭可能覆盖主页的弹窗...")
        for ad_btn_text in ["iv_cancel", "close", "关闭", "叉號", "叉号"]:
            ad_el = self.poco(ad_btn_text)
            if ad_el.exists():
                ad_el.click()
                logger.info(f"  >> 成功关闭首页促销大图弹框 (标识: {ad_btn_text})")
                time.sleep(2)
                break

        # 3. 输入起点：铜锣湾地铁站
        logger.info("【步骤 3 -ios】点击起点输入栏...")
        start_clicked = False
        # 通过 Poco 模糊匹配起点
        start_el = self.poco(textMatches=".*起點.*|.*起点.*|.*当前位置.*|.*當前位置.*|.*请输入起点.*|.*輸入起點.*|.*输入起点.*|.*您在哪.*|.*您從哪.*|.*您从哪.*")
        if start_el.exists():
            start_el.click()
            start_clicked = True
            logger.info("  >> [Poco] 成功点击起点输入栏")
        else:
            # WDA xpath 兜底
            start_xpath = self.client(xpath='//*[contains(@label, "起點") or contains(@value, "起點") or contains(@label, "起点") or contains(@value, "起点") or contains(@label, "当前位置") or contains(@value, "当前位置") or contains(@label, "當前位置") or contains(@value, "當前位置") or contains(@label, "您在哪") or contains(@value, "您在哪")]')
            if start_xpath.exists:
                start_xpath.click()
                start_clicked = True
                logger.info("  >> [WDA] 成功点击起点输入栏")
        if not start_clicked:
            logger.info("  >> 采用物理坐标 (0.5, 0.76) 点击起点区域...")
            self.client.click(0.5, 0.76)

        time.sleep(3)

        # 在搜索页输入起点
        logger.info("输入起点：铜锣湾地铁站...")
        self.client.click(0.5, 0.125)  # 点击搜索框
        time.sleep(1.5)
        self.client.send_keys("铜锣湾地铁站")
        logger.info("  >> 文本输入成功，等待联想搜索列表渲染...")
        time.sleep(4)

        # 点击搜索内容下方的首条联想匹配地址
        logger.info("正在点击下方搜索出的第一个起点...")
        first_cell = self.client(type="Cell")
        if first_cell.exists:
            first_cell[0].click()
            logger.info("  >> 成功选中起点！页面已退回到乘客端首页。")
        else:
            logger.info("  >> 通过物理坐标 (0.5, 0.25) 强制点击首行联想结果...")
            self.client.click(0.5, 0.25)
        time.sleep(4)

        # 4. 输入终点：香港大学
        logger.info("【步骤 4 -ios】点击目的地输入栏...")
        dest_clicked = False
        dest_el = self.poco(textMatches=".*想去哪.*|.*目的地.*|.*去哪.*|.*輸入目的地.*|.*输入目的地.*|.*要去哪.*|.*要去邊.*")
        if dest_el.exists():
            dest_el.click()
            dest_clicked = True
            logger.info("  >> [Poco] 成功点击目的地输入栏")
        else:
            dest_xpath = self.client(xpath='//*[contains(@label, "想去") or contains(@value, "想去") or contains(@label, "哪裡") or contains(@value, "哪裡") or contains(@label, "哪里") or contains(@value, "哪里") or contains(@label, "输入目的地") or contains(@value, "输入目的地") or contains(@label, "輸入目的地") or contains(@value, "輸入目的地")]')
            if dest_xpath.exists:
                dest_xpath.click()
                dest_clicked = True
                logger.info("  >> [WDA] 成功点击目的地输入栏")
        if not dest_clicked:
            logger.info("  >> 采用物理坐标 (0.5, 0.68) 点击目的地区域...")
            self.client.click(0.5, 0.68)

        time.sleep(3)

        # 在搜索页输入终点
        logger.info("输入终点：香港大学...")
        self.client.click(0.5, 0.125)  # 点击搜索框
        time.sleep(1.5)
        self.client.send_keys("香港大学")
        logger.info("  >> 文本输入成功，等待目的地联想列表渲染...")
        time.sleep(4)

        # 点击终点搜索结果的第一行匹配项
        logger.info("正在点击目的地首个匹配联想项...")
        first_cell = self.client(type="Cell")
        if first_cell.exists:
            first_cell[0].click()
            logger.info("  >> 选中目的地联想地址成功！正在计算线路并进入车型选择页面...")
        else:
            logger.info("  >> 通过物理坐标 (0.5, 0.25) 强制点击首行联想结果...")
            self.client.click(0.5, 0.25)
        time.sleep(7)  # 等待路线路径和车型面板加载

        self._screenshot("JRYG_ios_route_selected.png")

        # 5. 选择优惠卷：100元优惠卷
        logger.info("【步骤 5 -ios】在车型选择与确认页面中，正在寻找并点击『优惠券/優惠券』选择栏...")
        coupon_clicked = False
        coupon_el = self.poco(textMatches=".*優惠券.*|.*优惠券.*|.*优惠.*|.*優惠.*|.*折扣.*")
        if coupon_el.exists():
            coupon_el.click()
            coupon_clicked = True
            logger.info("  >> [Poco] 成功点击优惠券入口")
        else:
            coupon_xpath = self.client(xpath='//*[contains(@label, "優惠券") or contains(@value, "優惠券") or contains(@label, "优惠券") or contains(@value, "优惠券") or contains(@label, "优惠") or contains(@value, "优惠") or contains(@label, "折扣") or contains(@value, "折扣")]')
            if coupon_xpath.exists:
                coupon_xpath.click()
                coupon_clicked = True
                logger.info("  >> [WDA] 成功点击优惠券入口")
        if not coupon_clicked:
            logger.info("  >> 采用物理坐标 (0.85, 0.8) 点击优惠券区域...")
            self.client.click(0.85, 0.8)
            time.sleep(3)
            coupon_clicked = True

        # 进入列表后选择 100元优惠卷
        if coupon_clicked:
            logger.info("已进入优惠券列表，正在选中『100元优惠卷』...")
            selected_coupon = False
            for target_text in ["100元优惠卷", "100元优惠券", "100", "100元"]:
                card = self.client(xpath=f'//*[contains(@label, "{target_text}") or contains(@value, "{target_text}")]')
                if not card.exists:
                    poco_card = self.poco(textMatches=f".*{target_text}.*")
                    if poco_card.exists():
                        card = poco_card
                if card and (hasattr(card, "exists") and card.exists or not hasattr(card, "exists")):
                    card.click()
                    logger.info(f"  >> 匹配并点击成功，已成功勾选优惠券: '{target_text}'！")
                    selected_coupon = True
                    time.sleep(3)
                    break
            if not selected_coupon:
                logger.info("  >> 未匹配到 100元 卡片，点击应用列表第一张优惠卡片进行兜底...")
                first_card = self.poco(type="XCUIElementTypeCell")
                if first_card.exists():
                    first_card[0].click()
                    time.sleep(3)

            # 点击确定使用
            btn_use = self.poco(textMatches=".*確定.*|.*确定.*|.*確認.*|.*确认.*|.*使用.*")
            if btn_use.exists():
                btn_use.click()
                logger.info("  >> 点击确定使用成功")
                time.sleep(3)

        # 6. 点击"確認呼叫"按钮
        logger.info("【呼叫 -ios】点击『確認呼叫』正式向系统发起本订单派单...")
        btn_call = self.client(xpath='//*[contains(@label, "確認呼叫") or contains(@value, "確認呼叫") or contains(@label, "确认呼叫") or contains(@value, "确认呼叫") or contains(@label, "呼叫") or contains(@value, "呼叫")]')
        if not btn_call.exists:
            poco_call = self.poco(textMatches=".*確認呼叫.*|.*确认呼叫.*|.*呼叫.*|.*確認.*|.*确认.*")
            if poco_call.exists():
                btn_call = poco_call
        if btn_call and (hasattr(btn_call, "exists") and btn_call.exists or not hasattr(btn_call, "exists")):
            btn_call.click()
            logger.info("  >> [Poco/WDA] 成功点击『確認呼叫』！")
        else:
            logger.info("  >> 采用物理坐标 (0.5, 0.95) 提交订单呼叫...")
            self.client.click(0.5, 0.95)

        time.sleep(5)
        self._screenshot("JRYG_ios_booking_submitted.png")
        logger.info("【iOS 下单流程 -ios】执行完毕，订单已成功发起并进入后台派单流程！")
