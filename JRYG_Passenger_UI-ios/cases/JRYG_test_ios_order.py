"""阳光出行乘客端 iOS 下单全流程自动化测试用例 -ios

完整业务流程：登录 → 设置起点/目的地 → 搜索选择地址 → 询价选车型 → 收银台支付 → 呼叫

设计模式：
  - 状态机循环：通过 _detect_state 检测当前页面状态，路由到对应处理逻辑
  - 卡顿检测：_check_stall 当页面状态持续超时未推进时抛出断言

前置条件：
  - iPhone 真机已通过 WDA 连接
  - Appium Server 已启动
  - 测试数据 JSON 中包含 start_address、dest_address、phone_number、verify_code
"""
import pytest
import os
import json
import time
import sys

# 将 iOS 项目根目录添加到 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from jryg_ios.JRYG_logger import logger
from jryg_ios.JRYG_config import SETTINGS, TEST_DATA_FILE, SCREENSHOTS_DIR
from jryg_ios.JRYG_connect_device import IOSDevice

from selenium.common.exceptions import TimeoutException


class TestJRYGIosOrder:
    """阳光出行 iOS 乘客端下单全流程测试 -ios

    通过状态机循环驱动 App 完成从登录到下单的完整流程。
    """

    @classmethod
    def setup_class(cls):
        """类级 setup：创建 IOSDevice 实例并连接 Appium Server"""
        cls.device = IOSDevice()
        cls.driver = cls.device.connect()
        cls.passenger_bundle = SETTINGS["packages"]["passenger"]

        with open(TEST_DATA_FILE, "r", encoding="utf-8") as f:
            cls.test_data = json.load(f)

        logger.info("【iOS 下单测试】设备连接完毕，开始执行下单流程")

    @classmethod
    def teardown_class(cls):
        """类级 teardown：断开 Appium Session"""
        cls.device.disconnect()
        logger.info("【iOS 下单测试】流程结束，Session 已安全断开")

    def test_ios_complete_order_flow(self):
        """乘客端下单全流程：登录 → 设置起终点 → 询价 → 收银台 → 呼叫 -ios"""
        start_addr = self.test_data["start_address"]
        dest_addr = self.test_data["dest_address"]
        phone = self.test_data["phone_number"]
        code = self.test_data["verify_code"]
        progress = {}
        state = "not_started"
        self._last_state = None
        self._state_since = time.monotonic()

        # ==================== 状态机循环 ====================
        for cycle in range(60):
            state = self._detect_state()
            logger.info(f"【iOS 下单】循环 {cycle} -> 状态: {state}")

            self._check_stall(state, timeout=60)

            # ── 隐私协议 ──
            if state == "privacy_agreement":
                self._handle_privacy()
                continue

            # ── 登录 ──
            if state == "login":
                self._handle_login(phone, code)
                continue

            # ── 广告弹窗 ──
            if state == "ad":
                self._close_ad()
                continue

            # ── 首页 ──
            if state == "home":
                if not progress.get("start_done"):
                    self._click_start()
                elif not progress.get("dest_done"):
                    self._click_dest()
                else:
                    logger.info("【iOS 下单】起点和目的地均已设置完毕")
                continue

            # ── 搜索页 ──
            if state == "search":
                if not progress.get("start_done"):
                    if self._search_and_select(start_addr):
                        progress["start_done"] = True
                    time.sleep(4)
                elif not progress.get("dest_done"):
                    if self._search_and_select(dest_addr):
                        progress["dest_done"] = True
                    time.sleep(4)
                else:
                    self.driver.navigate().back()
                    time.sleep(2)
                continue

            # ── 询价页 ──
            if state == "quote":
                self._handle_quote()
                continue

            # ── 收银台 ──
            if state == "cashier":
                try:
                    self._handle_cashier()
                except Exception as e:
                    logger.error(f"【iOS 收银台失败】{e}")
                    self.device.screenshot("JRYG_ios_cashier_failed.png")
                    raise
                progress["order_started"] = True
                logger.info("【iOS 下单】已提交呼叫，流程完成！")
                self.device.screenshot("JRYG_ios_order_submitted.png")
                break

            # ── 呼叫中 ──
            if state == "calling":
                progress["order_started"] = True
                logger.info("【iOS 下单】正在呼叫中，流程完成！")
                self.device.screenshot("JRYG_ios_calling.png")
                break

            # ── 订单失败 ──
            if state == "order_failed":
                pytest.fail(f"【iOS 下单】呼叫失败或订单被取消: {self._get_page_texts()}")

            time.sleep(2)

        assert progress.get("order_started"), (
            f"【iOS 下单】流程未完成，最后状态: {state}，进度: {progress}"
        )
        logger.info("【iOS 下单】乘客端下单全流程运行圆满完成！")

    # ==================== 状态检测 ====================

    def _detect_state(self):
        """检测当前页面状态，返回状态字符串"""
        try:
            # 隐私协议
            if self._has_text("同意") and self._has_text("不同意"):
                return "privacy_agreement"

            # 广告弹窗
            if self._has_text("跳过") or self._has_text("跳过广告"):
                return "ad"

            # 登录页
            if self._has_text("请输入手机号") or self._has_text("登录/注册") or self._has_text("欢迎登录"):
                return "login"

            # 收银台
            if self._has_text("确认支付并呼叫") or self._has_text("先付后乘"):
                return "cashier"

            # 询价页
            if self._has_text("确认呼叫") or self._has_text("阳光优选"):
                return "quote"

            # 呼叫中
            if self._has_text("正在为您呼叫") or self._has_text("呼叫中"):
                return "calling"

            # 订单失败
            if self._has_text("呼叫超时") or self._has_text("已自动取消"):
                return "order_failed"

            # 首页
            if self._has_text("首页") and self._has_text("我的"):
                return "home"

            # 搜索页
            if self._has_text("搜索") and (self._has_text("目的地") or self._has_text("起点")):
                return "search"

        except Exception as e:
            logger.warning(f"【iOS 状态检测】异常: {e}")

        return "unknown"

    def _has_text(self, text):
        """检查当前页面是否包含指定文本"""
        try:
            return self.device.is_element_present(self.device.by_text(text), timeout=1)
        except Exception:
            return False

    def _get_page_texts(self):
        """获取当前页面的关键文本（用于日志输出）"""
        texts = []
        for keyword in ("首页", "我的", "登录", "验证码", "搜索", "确认呼叫", "确认支付并呼叫",
                        "阳光优选", "呼叫中", "跳过", "同意", "不同意", "请输入手机号"):
            if self._has_text(keyword):
                texts.append(keyword)
        return texts

    # ==================== 状态处理方法 ====================

    def _handle_privacy(self):
        """处理隐私协议弹窗"""
        logger.info("【iOS 隐私协议】点击同意")
        try:
            agree = self.device.find_element(self.device.by_text("同意"), timeout=5)
            agree.click()
            time.sleep(3)
        except TimeoutException:
            pass

    def _handle_login(self, phone, code):
        """处理登录流程"""
        logger.info("【iOS 登录】执行登录流程")
        # 输入手机号
        try:
            phone_input = self.device.find_element(
                self.device.by_text("请输入手机号"), timeout=5
            )
            phone_input.click()
            phone_input.clear()
            time.sleep(0.5)
            phone_input.send_keys(phone)
            time.sleep(1)
            logger.info(f"【iOS 登录】已输入手机号: {phone}")
        except TimeoutException:
            logger.warning("【iOS 登录】未找到手机号输入框")

        # 勾选协议
        try:
            checkbox = self.device.find_element(self.device.by_text("同意"), timeout=3)
            checkbox.click()
            time.sleep(0.5)
        except TimeoutException:
            pass

        # 点击获取验证码/下一步
        for btn_text in ("获取验证码", "下一步"):
            try:
                btn = self.device.find_element(self.device.by_text(btn_text), timeout=3)
                btn.click()
                logger.info(f"【iOS 登录】已点击 {btn_text}")
                time.sleep(3)
                break
            except TimeoutException:
                continue

        # 输入验证码
        time.sleep(2)
        try:
            code_input = self.device.find_element(
                self.device.by_class_chain('**/XCUIElementTypeTextField'), timeout=10
            )
            code_input.click()
            time.sleep(0.5)
            code_input.send_keys(code)
            time.sleep(3)
            logger.info(f"【iOS 登录】已输入验证码: {code}")
        except TimeoutException:
            logger.warning("【iOS 登录】未找到验证码输入框")

    def _close_ad(self):
        """关闭广告弹窗"""
        for close_text in ("跳过", "跳过广告", "关闭"):
            try:
                close_btn = self.device.find_element(self.device.by_text(close_text), timeout=2)
                close_btn.click()
                logger.info(f"【iOS 广告】已点击 {close_text}")
                time.sleep(2)
                return
            except TimeoutException:
                continue
        # 坐标点击
        self.device.click(0.5, 0.73)
        time.sleep(2)

    def _click_start(self):
        """点击起点栏位"""
        logger.info("【iOS 下单】点击起点栏位")
        for text in ("起点", "从哪里出发"):
            try:
                el = self.device.find_element(self.device.by_text(text), timeout=5)
                el.click()
                time.sleep(2)
                return
            except TimeoutException:
                continue
        # 坐标点击起点区域
        self.device.click(0.5, 0.35)
        time.sleep(2)

    def _click_dest(self):
        """点击目的地输入栏"""
        logger.info("【iOS 下单】点击目的地输入栏")
        for text in ("想要去哪里？", "目的地", "去哪"):
            try:
                el = self.device.find_element(self.device.by_text(text), timeout=5)
                el.click()
                time.sleep(2)
                return
            except TimeoutException:
                continue
        # 坐标点击目的地区域
        self.device.click(0.5, 0.45)
        time.sleep(2)

    def _search_and_select(self, keyword):
        """在搜索页输入关键词并选择第一条结果"""
        logger.info(f"【iOS 搜索】输入并选定: {keyword}")
        try:
            search_input = self.device.find_element(
                self.device.by_class_chain('**/XCUIElementTypeTextField'), timeout=5
            )
            search_input.click()
            search_input.clear()
            time.sleep(0.5)
            search_input.send_keys(keyword)
            time.sleep(3)
        except TimeoutException:
            logger.warning(f"【iOS 搜索】未找到搜索输入框")
            return False

        # 选择第一条搜索结果
        try:
            result = self.device.find_element(
                self.device.by_text_contains(keyword[:3]), timeout=10
            )
            result.click()
            time.sleep(3)
            return True
        except TimeoutException:
            # 尝试点击列表第一项
            try:
                first_item = self.device.find_element(
                    self.device.by_class_chain('**/XCUIElementTypeCell[1]'), timeout=5
                )
                first_item.click()
                time.sleep(3)
                return True
            except TimeoutException:
                logger.warning(f"【iOS 搜索】未找到匹配结果: {keyword}")
                return False

    def _handle_quote(self):
        """在询价页选择车型并点击确认呼叫"""
        logger.info("【iOS 询价】选择车型并确认呼叫")
        # 尝试选择"阳光优选"
        try:
            car = self.device.find_element(self.device.by_text("阳光优选"), timeout=5)
            car.click()
            time.sleep(2)
        except TimeoutException:
            logger.info("【iOS 询价】未找到阳光优选，尝试其他车型")
            for car_name in ("阳光快车", "阳光舒享", "六座专车"):
                try:
                    car = self.device.find_element(self.device.by_text(car_name), timeout=2)
                    car.click()
                    time.sleep(1)
                    break
                except TimeoutException:
                    continue

        # 点击确认呼叫
        for btn_text in ("确认呼叫", "呼叫"):
            try:
                btn = self.device.find_element(self.device.by_text(btn_text), timeout=5)
                btn.click()
                logger.info(f"【iOS 询价】已点击 {btn_text}")
                time.sleep(4)
                return
            except TimeoutException:
                continue
        logger.warning("【iOS 询价】未找到确认呼叫按钮")

    def _handle_cashier(self):
        """处理收银台支付流程"""
        logger.info("【iOS 收银台】处理支付流程")
        # 勾选微信支付
        try:
            wechat = self.device.find_element(self.device.by_text("微信支付"), timeout=5)
            wechat.click()
            time.sleep(1)
            logger.info("【iOS 收银台】已选择微信支付")
        except TimeoutException:
            logger.info("【iOS 收银台】未找到微信支付选项，尝试直接提交")

        # 点击确认支付并呼叫
        try:
            btn = self.device.find_element(self.device.by_text("确认支付并呼叫"), timeout=10)
            btn.click()
            logger.info("【iOS 收银台】已点击确认支付并呼叫")
            time.sleep(5)
        except TimeoutException:
            logger.warning("【iOS 收银台】未找到确认支付按钮")

    def _check_stall(self, state, timeout=60):
        """卡顿检测：当页面状态持续 timeout 秒未推进时抛出断言"""
        now = time.monotonic()
        if getattr(self, "_last_state", None) != state:
            self._last_state = state
            self._state_since = now
        elapsed = now - self._state_since
        if elapsed >= timeout:
            raise AssertionError(
                f"【iOS 下单】页面状态 {state} 已持续 {elapsed:.0f} 秒未推进"
            )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
