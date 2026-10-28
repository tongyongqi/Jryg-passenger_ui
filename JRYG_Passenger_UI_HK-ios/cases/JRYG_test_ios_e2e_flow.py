"""
港版阳光出行 iOS 乘客端 E2E 全流程自动化用例
==============================================================================
完整流程：
  打开App → 登录 → 下单(打錶的士/現金) → 切司机端流转订单
  (接单→到达上车点→接载乘客→到达目的地→输入车费→确认收款)
  → 切回乘客端查看订单状态 → 返回首页
==============================================================================
使用前置：
1. WDA 已在手机上运行 (Automation Running)
2. tidevice/iproxy 已转发 8100 端口
3. 司机端 App 已登录且处于出车状态
4. 在本目录运行: python -m pytest cases/JRYG_test_ios_e2e_flow.py -s
   或直接在 PyCharm 中右键 Run
==============================================================================
"""

import os
import sys
import time

import pytest
import wda

# 添加框架根路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_config import SETTINGS, REPORT_DIR
from jryg_hk_ios.JRYG_page_monitor import IOSPageMonitor


class TestJRYGE2EFlow:
    """阳光出行港版 iOS E2E 全流程：乘客下单 + 司机流转 + 订单完成验证"""

    # ---- 测试常量 ----
    PASSENGER_BUNDLE = "com.sunlightmobility.client"
    DRIVER_BUNDLE = "com.sunlightmobility.driver"
    WDA_URL = SETTINGS.get("device", {}).get("wda_url", "http://127.0.0.1:8100")
    PHONE_NUMBER = "11001727"
    VERIFY_CODE = "123456"
    START_ADDRESS = "北角地鐵站"
    DEST_ADDRESS = "香港大學"
    FARE_AMOUNT = "5"

    @classmethod
    def setup_class(cls):
        """初始化 WDA 客户端和页面监控器"""
        cls.output_dir = os.path.join(REPORT_DIR, "e2e_flow")
        os.makedirs(cls.output_dir, exist_ok=True)

        logger.info(f"【E2E】正在连接 WDA: {cls.WDA_URL}")
        wda.HTTP_TIMEOUT = 20
        try:
            cls.client = wda.Client(cls.WDA_URL)
            cls.client.status()
            logger.info("【E2E】WDA 连接成功")
        except Exception as e:
            logger.error(f"【E2E】WDA 连接失败: {e}")
            pytest.skip("WDA 物理通道未就绪")

        cls.monitor = IOSPageMonitor(cls.WDA_URL, cls.output_dir)

    @classmethod
    def teardown_class(cls):
        cls.monitor.close()
        logger.info("【E2E】测试结束，资源已释放")

    # ---- 通用工具方法 ----

    def _screenshot(self, name):
        """截图并保存"""
        path = os.path.join(self.output_dir, f"{int(time.time())}_{name}.png")
        try:
            self.client.screenshot(path)
            logger.info(f"  >> 截图: {path}")
        except Exception as e:
            logger.warning(f"  >> 截图失败: {e}")

    def _capture(self, reason):
        """页面树 + 截图卡点"""
        self.monitor.capture(reason)

    def _click_text(self, text):
        """点击可见文本控件"""
        return self.monitor.click_text(self.client, text)

    def _wait_state(self, description, states, timeout=30):
        """等待页面进入指定状态之一"""
        if isinstance(states, str):
            states = (states,)
        return self.monitor.wait_for(
            description,
            lambda page: page.state in states,
            timeout=timeout,
        )

    def _swipe_slider(self, x_start=46, y=795, x_end=380, duration=3.0):
        """滑动底部状态确认滑块（通用坐标）"""
        self.client.swipe(x_start, y, x_end, y, duration=duration)

    def _activate_app(self, bundle_id, wait=3):
        """激活指定 App"""
        self.client.app_activate(bundle_id)
        time.sleep(wait)

    # ---- 乘客端：打开 App + 登录 ----

    def _passenger_open_and_login(self):
        """步骤 1-2：打开乘客端 App 并完成登录"""
        logger.info("=" * 60)
        logger.info("【阶段 1】打开乘客端 App 并登录")
        logger.info("=" * 60)

        # 1. 拉起乘客端
        self._activate_app(self.PASSENGER_BUNDLE, wait=5)
        self._capture("01_passenger_launch")

        # 2. 状态机驱动登录流程
        deadline = time.monotonic() + 120
        for cycle in range(30):
            page = self.monitor.inspect()
            state = page.state
            logger.info(f"  [循环 {cycle}] 状态: {state}")
            assert time.monotonic() < deadline, f"登录流程超时，当前状态={state}"

            # 活动弹窗
            if state == "activity_popup":
                self.monitor.dismiss_activity_popup(self.client)
                continue

            # 隐私协议
            if state == "privacy_agreement":
                self._click_text("同意")
                time.sleep(3)
                continue

            # 权限弹窗
            if state == "permission_dialog":
                if not self._click_text("去授權"):
                    self._click_text("去授权")
                time.sleep(1)
                try:
                    self.client.alert.accept()
                except Exception:
                    pass
                time.sleep(3)
                continue

            # 首页未登录 → 点击"我的"
            if state == "home_unlogged":
                self._click_text("我的")
                self._wait_state("进入个人中心", ("mine_unlogged", "mine_logged", "login_phone_input"), timeout=15)
                continue

            # 个人中心未登录 → 点击登录
            if state == "mine_unlogged":
                if not self._click_text("登錄/註冊"):
                    self._click_text("登录/注册")
                time.sleep(4)
                continue

            # 手机号输入页
            if state == "login_phone_input":
                tf = self.client(className="XCUIElementTypeTextField", index=0)
                assert tf.exists, "手机号输入框不存在"
                tf.click()
                tf.clear_text()
                self.client.send_keys(self.PHONE_NUMBER)
                time.sleep(0.5)
                if not self._click_text("取得驗證碼"):
                    self._click_text("获取验证码")
                self._wait_state("进入验证码页", ("login_code_input",), timeout=15)
                continue

            # 验证码输入页
            if state == "login_code_input":
                tf = self.client(className="XCUIElementTypeTextField", index=0)
                assert tf.exists, "验证码输入框不存在"
                tf.click()
                self.client.send_keys(self.VERIFY_CODE)
                self._wait_state("登录成功", ("mine_logged", "home_unlogged", "activity_popup"), timeout=20)
                continue

            # 已登录
            if state == "mine_logged":
                assert self.monitor.last_page.matches_account(self.PHONE_NUMBER), "登录账号不匹配"
                logger.info(f"【登录成功】账号: {self.PHONE_NUMBER}")
                self._capture("02_login_success")
                return

            time.sleep(2)

        raise AssertionError("登录流程未在预期时间内完成")

    # ---- 乘客端：下单 ----

    def _passenger_place_order(self):
        """步骤 3：乘客端下单（打錶的士 + 现金）"""
        logger.info("=" * 60)
        logger.info("【阶段 2】乘客端下单")
        logger.info("=" * 60)

        # 切到首页
        self._click_text("主頁")
        time.sleep(2)
        self._capture("03_home_ready")

        # 选择起点
        logger.info(f"  输入起点: {self.START_ADDRESS}")
        start_el = self.client(xpath='//*[contains(@label,"想去") or contains(@value,"想去") or contains(@label,"哪裡") or contains(@value,"哪裡")]')
        if start_el.exists:
            start_el.click()
        else:
            self.client.click(0.5, 0.76)  # 起点区域坐标
        time.sleep(2)

        # 输入起点搜索
        search_tf = self.client(className="XCUIElementTypeTextField", index=0)
        if search_tf.exists:
            search_tf.click()
            self.client.send_keys(self.START_ADDRESS)
            time.sleep(3)
            # 点击第一个搜索结果
            first_cell = self.client(type="Cell", index=0)
            if first_cell.exists:
                first_cell.click()
            else:
                self.client.click(0.5, 0.25)
            time.sleep(3)

        # 输入终点
        logger.info(f"  输入终点: {self.DEST_ADDRESS}")
        dest_el = self.client(xpath='//*[contains(@label,"想去") or contains(@value,"想去") or contains(@label,"哪裡") or contains(@value,"哪裡")]')
        if dest_el.exists:
            dest_el.click()
        else:
            self.client.click(0.5, 0.68)
        time.sleep(2)

        search_tf = self.client(className="XCUIElementTypeTextField", index=0)
        if search_tf.exists:
            search_tf.click()
            self.client.send_keys(self.DEST_ADDRESS)
            time.sleep(3)
            first_cell = self.client(type="Cell", index=0)
            if first_cell.exists:
                first_cell.click()
            else:
                self.client.click(0.5, 0.25)
            time.sleep(5)

        self._capture("04_route_selected")

        # 选择车型：打錶的士
        logger.info("  选择车型: 打錶的士")
        meter_btn = self.client(xpath='//*[contains(@label,"打錶") or contains(@value,"打錶") or contains(@label,"打表") or contains(@value,"打表")]')
        if meter_btn.exists:
            meter_btn.click()
            time.sleep(2)
            logger.info("  >> 已选择打錶的士")

        # 选择支付方式：现金
        logger.info("  选择支付方式: 現金")
        cash_btn = self.client(xpath='//*[contains(@label,"現金") or contains(@value,"現金") or contains(@label,"现金") or contains(@value,"现金")]')
        if cash_btn.exists:
            cash_btn.click()
            time.sleep(2)
            logger.info("  >> 已选择现金支付")

        self._capture("05_before_call")

        # 点击确认呼叫
        logger.info("  点击确认呼叫")
        call_btn = self.client(xpath='//*[contains(@label,"確認呼叫") or contains(@value,"確認呼叫") or contains(@label,"确认呼叫") or contains(@value,"确认呼叫")]')
        if call_btn.exists:
            call_btn.click()
        else:
            self.client.click(0.5, 0.95)
        time.sleep(5)

        self._capture("06_order_placed")
        logger.info("【下单完成】订单已提交，等待司机接单")

    # ---- 司机端：接单 + 流转订单 ----

    def _driver_process_order(self):
        """步骤 4-8：切到司机端，接单并走完订单流程"""
        logger.info("=" * 60)
        logger.info("【阶段 3】司机端流转订单")
        logger.info("=" * 60)

        # 切到司机端
        self._activate_app(self.DRIVER_BUNDLE, wait=3)
        self._capture("07_driver_app")

        # 等待接单（检测订单页面出现"接乘客"或"到達上車地點"）
        logger.info("  等待司机端进入接单状态...")
        order_page = self.monitor.wait_for(
            "司机端接单",
            lambda page: page.has("接乘客", "到達上車地點", "等乘客"),
            timeout=60,
        )
        logger.info(f"  >> 司机端已接单，状态: {order_page.texts[:200]}")
        self._capture("08_driver_accepted")

        # 步骤 4: 滑动 → 到达上车点
        logger.info("  [步骤 4] 滑动确认到达上车点")
        self._swipe_slider()
        time.sleep(5)
        self._capture("09_arrived_pickup")

        arrived = self.monitor.inspect()
        assert arrived.has("等乘客", "已接載乘客"), f"到达上车点失败，当前文本: {arrived.texts[:200]}"
        logger.info("  >> 已到达上车点")

        # 步骤 5: 滑动 → 接载乘客
        logger.info("  [步骤 5] 滑动确认接载乘客")
        self._swipe_slider()
        time.sleep(5)
        self._capture("10_passenger_onboard")

        onboard = self.monitor.inspect()
        assert onboard.has("送乘客", "到達目的地"), f"接载乘客失败，当前文本: {onboard.texts[:200]}"
        logger.info("  >> 已接载乘客，行程开始")

        # 步骤 6: 滑动 → 到达目的地
        logger.info("  [步骤 6] 滑动确认到达目的地")
        self._swipe_slider()
        time.sleep(5)

        # 检查是否进入账单页面（可能需要重试滑动）
        page = self.monitor.inspect()
        if not page.has("確認賬單", "確認收款", "車費", "請輸入車費"):
            logger.info("  >> 第一次滑动未触发，重试...")
            self._swipe_slider()
            time.sleep(5)
            page = self.monitor.inspect()

        assert page.has("確認賬單", "確認收款", "車費"), f"到达目的地失败，当前文本: {page.texts[:200]}"
        self._capture("11_arrived_dest")
        logger.info("  >> 已到达目的地，进入确认账单页面")

        # 步骤 7: 输入车费
        logger.info(f"  [步骤 7] 输入车费: {self.FARE_AMOUNT} HKD")
        fare_tf = self.client(className="XCUIElementTypeTextField", index=0)
        if fare_tf.exists:
            fare_tf.click()
            time.sleep(0.5)
            fare_tf.set_text(self.FARE_AMOUNT)
            time.sleep(1)
            # 关闭键盘
            self.client.click(196, 69)
            time.sleep(1)
        else:
            logger.warning("  >> 未找到车费输入框")

        # 验证输入
        page = self.monitor.inspect()
        for node in page.nodes:
            if node.tag == "XCUIElementTypeTextField" and node.get("visible") == "true":
                val = node.get("value", "")
                if val and val != "請輸入附加費":
                    logger.info(f"  >> 车费输入框值: {val}")
                    break

        self._capture("12_fare_entered")

        # 步骤 8: 滑动确认收款
        logger.info("  [步骤 8] 滑动确认收款")
        self._swipe_slider()
        time.sleep(8)

        page = self.monitor.inspect()
        assert page.has("已完成", "已支付", "服務完成時間"), f"确认收款失败，当前文本: {page.texts[:300]}"
        self._capture("13_payment_confirmed")
        logger.info("  >> 收款确认成功，账单已完成")

        # 提取订单号
        order_no = None
        for text in page.texts:
            if len(text) >= 10 and text.isalnum():
                order_no = text
                break
        if order_no:
            logger.info(f"  >> 订单号: {order_no}")
        return order_no

    # ---- 司机端返回首页 ----

    def _driver_return_home(self):
        """步骤 9：司机端点击返回首页"""
        logger.info("=" * 60)
        logger.info("【阶段 4】司机端返回首页")
        logger.info("=" * 60)

        self._click_text("返回首頁")
        time.sleep(3)
        self._capture("14_driver_home")

        page = self.monitor.inspect()
        assert page.has("今日營收", "完單數", "接單中"), f"司机端返回首页失败，当前文本: {page.texts[:200]}"
        logger.info("  >> 司机端已返回首页")

    # ---- 乘客端：查看订单状态 + 返回首页 ----

    def _passenger_check_order(self):
        """步骤 10-11：切回乘客端查看订单状态，返回首页"""
        logger.info("=" * 60)
        logger.info("【阶段 5】乘客端查看订单状态")
        logger.info("=" * 60)

        # 切回乘客端
        self._activate_app(self.PASSENGER_BUNDLE, wait=3)
        self._capture("15_passenger_check")

        page = self.monitor.inspect()
        logger.info(f"  乘客端页面文本: {page.texts[:500]}")

        # 验证订单已完成
        assert page.has("行程結束", "已完成", "費用明細"), \
            f"乘客端未显示订单完成状态，当前文本: {page.texts[:300]}"

        # 提取订单信息
        order_info = {}
        for text in page.texts:
            if "訂單編號" in text or "订单编号" in text:
                # 订单号通常在下一个文本
                continue
            if len(text) >= 10 and text.isalnum() and "HKD" not in text:
                order_info["order_no"] = text
            if "HKD" in text:
                order_info["fare"] = text
            if "公里" in text:
                order_info["distance"] = text

        logger.info(f"  >> 订单信息: {order_info}")
        self._capture("16_passenger_order_detail")
        logger.info("  >> 乘客端确认订单已完成")

        # 返回首页
        logger.info("  点击返回箭头回到首页")
        arrow = self.client(xpath='//XCUIElementTypeImage[contains(@name,"arrow_left") or contains(@label,"arrow_left")]')
        if arrow.exists:
            arrow.click()
        else:
            self.client.click(20, 100)
        time.sleep(3)

        page = self.monitor.inspect()
        assert page.state == "home_unlogged" or page.has("想去哪", "主頁"), \
            f"乘客端返回首页失败，当前状态: {page.state}"
        self._capture("17_passenger_home")
        logger.info("  >> 乘客端已返回首页")

    # ---- 主测试入口 ----

    def test_e2e_full_flow(self):
        """E2E 全流程：乘客下单 → 司机流转 → 订单完成 → 乘客确认"""
        try:
            # 阶段 1: 乘客端打开 + 登录
            self._passenger_open_and_login()

            # 阶段 2: 乘客端下单
            self._passenger_place_order()

            # 阶段 3: 司机端接单 + 流转订单
            self._driver_process_order()

            # 阶段 4: 司机端返回首页
            self._driver_return_home()

            # 阶段 5: 乘客端查看订单 + 返回首页
            self._passenger_check_order()

            logger.info("=" * 60)
            logger.info("【E2E 全流程完成】所有步骤均已成功执行")
            logger.info("=" * 60)

        except Exception as e:
            self._capture("99_error")
            logger.error(f"【E2E 流程失败】{e}")
            raise
