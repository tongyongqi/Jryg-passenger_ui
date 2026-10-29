"""
JRYG 港版 iOS 自动化 —— 包车的士下单模块
==============================================================================
功能：
  包车价的士下单流程：
  1. 选择起点和终点
  2. 选择车型：包车价的士
  3. 选择支付方式：Alipay HK
  4. 选择银行卡支付方式
  5. 确认呼叫提交订单

设计原则：
  - 依赖 open_passenger_app() 和 login_passenger() 先确保 App 已打开并登录
  - 独立完成包车价下单的全流程
==============================================================================
"""

import time

from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_ios_base import IOSBase


class IOSOrderCharter(IOSBase):
    """iOS 包车的士下单模块"""

    def order_charter_taxi(self):
        """包车价同样需要目标司机和完整终态，不允许仅提交呼叫就进入下一场景。"""
        return self._run_verified_order(self._place_verified_charter)

    def _go_to_home(self):
        """切到首页（处理可能存在的订单完成页面）"""
        logger.info("  >> 切换到首页")

        # 检查是否在订单完成/重新下单页面
        page = self.monitor.inspect()
        state = page.state
        if state == "order_complete":
            logger.info("  >> 检测到订单完成页面，点击'重新下單'回到首页")
            if not self._click_text("重新下單"):
                self._click_text("重新下单")
            time.sleep(3)

        # 点击底部「主頁」标签
        self._click_text("主頁")
        time.sleep(2)

        # 关闭可能存在的广告弹窗
        for ad_text in ["iv_cancel", "close", "关闭", "叉號", "叉号"]:
            # 按文案模糊匹配广告关闭按钮
            ad_el = self.client(xpath=f'//*[contains(@label,"{ad_text}") or contains(@name,"{ad_text}")]')
            if ad_el.exists:
                ad_el.click()
                time.sleep(2)
                break

        self._capture("05_home_ready")

    def _input_route(self):
        """输入起点和终点"""
        # 输入起点
        logger.info(f"  >> 输入起点: {self.START_ADDRESS}")
        # 兼容多种“想去/哪裡/起點/起点”文案定位起点输入框
        start_el = self.client(xpath='//*[contains(@label,"想去") or contains(@value,"想去") or contains(@label,"哪裡") or contains(@value,"哪裡") or contains(@label,"起點") or contains(@value,"起點") or contains(@label,"起点") or contains(@value,"起点")]')
        if start_el.exists:
            start_el.click()
        else:
            # 兜底：按屏幕比例点击起点栏位置
            self.client.click(0.5, 0.76)
        time.sleep(2)

        # 定位搜索输入框并输入起点
        search_tf = self.client(className="XCUIElementTypeTextField", index=0)
        if search_tf.exists:
            search_tf.click()
            self.client.send_keys(self.START_ADDRESS)
            time.sleep(3)
            # 选择第一条联想结果
            first_cell = self.client(type="Cell", index=0)
            if first_cell.exists:
                first_cell.click()
            else:
                # 兜底：点击结果列表区域
                self.client.click(0.5, 0.25)
            time.sleep(3)

        # 输入终点
        logger.info(f"  >> 输入终点: {self.DEST_ADDRESS}")
        # 终点输入框使用“想去/哪裡”文案定位
        dest_el = self.client(xpath='//*[contains(@label,"想去") or contains(@value,"想去") or contains(@label,"哪裡") or contains(@value,"哪裡")]')
        if dest_el.exists:
            dest_el.click()
        else:
            # 兜底：按屏幕比例点击终点栏位置
            self.client.click(0.5, 0.68)
        time.sleep(2)

        # 定位搜索输入框并输入终点
        search_tf = self.client(className="XCUIElementTypeTextField", index=0)
        if search_tf.exists:
            search_tf.click()
            self.client.send_keys(self.DEST_ADDRESS)
            time.sleep(3)
            # 选择第一条联想结果
            first_cell = self.client(type="Cell", index=0)
            if first_cell.exists:
                first_cell.click()
            else:
                # 兜底：点击结果列表区域
                self.client.click(0.5, 0.25)
            time.sleep(5)

        self._capture("06_route_selected")

    def _select_charter_taxi(self):
        """选择车型：包车价的士"""
        logger.info("  >> 选择车型: 包车价的士")

        # 尝试多种文本匹配包车价的士
        charter_btn = self.client(xpath='//*[contains(@label,"包車") or contains(@value,"包車") or contains(@label,"包车") or contains(@value,"包车") or contains(@label,"包車價") or contains(@value,"包車價") or contains(@label,"包车价") or contains(@value,"包车价")]')
        if charter_btn.exists:
            charter_btn.click()
            time.sleep(2)
            logger.info("  >> 已选择包车价的士")
        else:
            logger.warning("  >> 未找到包车价的士按钮，尝试兜底坐标点击")
            # 兜底：按屏幕比例点击车型区域
            self.client.click(0.3, 0.55)
            time.sleep(2)

        self._capture("07_charter_taxi_selected")

    def _select_alipay_bank_card(self):
        """选择支付方式：Alipay HK → 银行卡"""
        logger.info("  >> 选择支付方式: Alipay HK")

        # 点击支付方式入口
        pay_btn = self.client(xpath='//*[contains(@label,"Alipay") or contains(@value,"Alipay") or contains(@label,"支付") or contains(@value,"支付") or contains(@label,"付款") or contains(@value,"付款")]')
        if pay_btn.exists:
            pay_btn.click()
            time.sleep(2)

        # 选择 Alipay HK
        alipay_btn = self.client(xpath='//*[contains(@label,"AlipayHK") or contains(@value,"AlipayHK") or contains(@label,"Alipay HK") or contains(@value,"Alipay HK") or contains(@label,"支付寶HK") or contains(@value,"支付寶HK") or contains(@label,"支付宝HK") or contains(@value,"支付宝HK")]')
        if alipay_btn.exists:
            alipay_btn.click()
            time.sleep(2)
            logger.info("  >> 已选择 Alipay HK")

        # 选择银行卡支付方式
        logger.info("  >> 选择银行卡支付方式")
        bank_card_btn = self.client(xpath='//*[contains(@label,"銀行卡") or contains(@value,"銀行卡") or contains(@label,"银行卡") or contains(@value,"银行卡") or contains(@label,"信用卡") or contains(@value,"信用卡") or contains(@label," debit") or contains(@value,"debit")]')
        if bank_card_btn.exists:
            bank_card_btn.click()
            time.sleep(2)
            logger.info("  >> 已选择银行卡支付")
        else:
            logger.warning("  >> 未找到银行卡选项，可能需要手动选择")

        self._capture("08_payment_selected")

    def _confirm_call(self):
        """点击确认呼叫"""
        logger.info("  >> 点击确认呼叫")

        # 兼容“確認呼叫/确认呼叫/立即呼叫”三种文案
        call_btn = self.client(xpath='//*[contains(@label,"確認呼叫") or contains(@value,"確認呼叫") or contains(@label,"确认呼叫") or contains(@value,"确认呼叫") or contains(@label,"立即呼叫") or contains(@value,"立即呼叫")]')
        if call_btn.exists:
            call_btn.click()
        else:
            # 兜底：按屏幕比例点击底部呼叫按钮
            self.client.click(0.5, 0.95)

        time.sleep(5)
        self._capture("09_order_placed")

        logger.info("【包车价下单完成】订单已提交")
        return True
