"""
港版 iOS 双端全 UI 下单与司机订单流转 —— 参数化基类
==============================================================================
所有车型+支付方式的组合用例继承本基类，只需设置类属性：
  CAR_TYPE  : 车型（"meter"=打錶的士 / "charter"=包車價的士）
  PAYMENT   : 支付方式（"cash" / "epayment" / "alipay" / "bankcard"）

流程：
  阶段 0（UI）  ：打开已登录司机 App → 点击出车，不检查司机接口 token
  阶段 1（UI）  ：乘客端预清理 —— 取消遗留的进行中订单 / 处理未支付订单
  阶段 2（UI）  ：拉起乘客 App → 配置起终点 → 选择车型 → 选择支付方式
               → 确认呼叫 → 检测登录态 → 未登录则登录后重新下单 → 等待下单成功
  阶段 3（UI）  ：切回司机 App → 接单 → 滑动到达/接载/结束 → 填写并确认账单
  阶段 4（UI）  ：切乘客 App 实际支付 → 切司机 App 核验完成且已支付

注意：
  1. 不调用司机业务接口，不读取 token，不创建 Socket 或模拟行驶轨迹。
  2. 默认同设备顺序切换；双设备可配置 HK_DRIVER_WDA_URL，派单与定位由司机 App 维护。
  3. 测试车费/附加费在 driver 配置中指定，尾号校验及现金收款需显式确认。
==============================================================================
"""

import os
import re
import sys
import time

import pytest
import wda

# 公共订单编排集中在ui_framework，cases只定义场景参数；上一级为项目根。
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 导入港版 iOS 自动化配置（设备信息、目录路径等）
from ui_framework.JRYG_config import SETTINGS
# 导入统一日志记录器，全流程日志输出
from ui_framework.JRYG_logger import logger
# 导入 iOS 自动化公共基类，提供设备连接、地址搜索、车型选择、支付等通用操作
from ui_framework.JRYG_ios_ui_base import iOSBase
# 导入 UI 元素定位常量（XPath、关键词、坐标、测试数据）
from ui_framework import JRYG_ios_ui_elements as E
from ui_framework.JRYG_driver_runtime import resolve_runtime
from ui_framework.JRYG_driver_ui import DriverUIFlow, parser as driver_parser


# ==================== 车型/支付方式映射 ====================
# 车型标识 → 中文标签映射，用于日志输出
CAR_TYPE_LABELS = {
    "meter": "打錶的士",       # 按表计费
    "charter": "包車價的士",   # 固定一口价，先付後乘
}

# 支付方式标识 → 中文标签映射，用于日志输出
PAYMENT_LABELS = {
    "cash": "現金",            # 司机端确认收款后无需 App 端支付
    "epayment": "電子支付",    # 订单结束后走信用卡/扣帳卡支付流程
    "alipay": "Alipay HK",    # 订单结束后走 Safari AlipayHK 支付流程
    "bankcard": "信用卡/扣帳卡", # 银行卡表单 + 3DS OTP 验证流程
}


class TestOrderBase(iOSBase):
    """参数化乘客下单与司机全 UI 接单流转基类。

    子类设置 CAR_TYPE 和 PAYMENT；电子支付后付可用 FINAL_PAYMENT 选择渠道，无需重写流程。
    本基类不直接执行（__test__ = False），由子类继承后设置参数。
    """

    __test__ = False  # pytest 不收集基类本身，由子类继承后设置参数执行

    # ==================== 子类必须覆盖的类属性 ====================
    CAR_TYPE = ""   # 车型标识："meter"=打錶的士 / "charter"=包車價的士
    PAYMENT = ""    # 下单方式："cash" / "epayment" / "alipay" / "bankcard"
    FINAL_PAYMENT = ""  # 可选后付渠道："bankcard" / "alipay"；留空保持原用例行为。

    @property
    def order_settings(self):
        return SETTINGS

    def _resolve_driver_runtime(self):
        return resolve_runtime(self.order_settings)

    def _driver_parser(self):
        return driver_parser()

    def _create_driver_flow(self, args):
        return DriverUIFlow(args)

    @property
    def final_payment(self):
        """解析后付渠道但不改下单PAYMENT；非法配置在任何UI订单动作前拒绝。"""
        if self.FINAL_PAYMENT:
            if self.CAR_TYPE != "meter" or self.PAYMENT != "epayment" or self.FINAL_PAYMENT not in ("bankcard", "alipay"):
                raise ValueError("FINAL_PAYMENT 仅支持打錶的士電子支付后付的 bankcard 或 alipay 渠道")
            return self.FINAL_PAYMENT
        return "bankcard" if self.PAYMENT == "epayment" else self.PAYMENT

    @classmethod
    def teardown_class(cls):
        """仅释放设备连接，保留司机 App 状态，不自动收车或取消订单。"""
        logger.info("【teardown】保留司机 App 出车状态，不自动收车")
        super().teardown_class()

    # ==================== 主测试方法 ====================

    def test_order_flow(self):
        """乘客 UI 下单 → 司机 UI 接单与滑动 → UI 确认账单与支付。"""
        car_label = CAR_TYPE_LABELS.get(self.CAR_TYPE, self.CAR_TYPE)
        pay_label = PAYMENT_LABELS.get(self.PAYMENT, self.PAYMENT)
        tag = f"{car_label}+{pay_label}"
        channel = self.final_payment
        if self.FINAL_PAYMENT:
            tag += f"+后付{PAYMENT_LABELS[channel]}"

        assert self.CAR_TYPE, f"{tag}: 未设置 CAR_TYPE 类属性"
        assert self.PAYMENT, f"{tag}: 未设置 PAYMENT 类属性"
        stop_after = os.environ.get("HK_DRIVER_UI_STOP_AFTER", "submitted")
        assert stop_after in ("accepted", "submitted"), "HK_DRIVER_UI_STOP_AFTER 只能为 accepted 或 submitted"

        # ============================================================
        # 阶段 0：司机 UI 打开与出车，不读取或检查司机接口 token
        # ============================================================
        logger.info("=" * 60)
        logger.info("【阶段 0】司机端：打开 App→UI 出车，不检查接口会话")
        logger.info("=" * 60)
        self._driver_ui_go_online(tag)

        # ============================================================
        # 阶段 1：乘客端预清理
        # ============================================================
        logger.info("=" * 60)
        logger.info("【阶段 1】乘客端：处理遗留订单")
        logger.info("=" * 60)
        self._ui_cleanup_ongoing_order(tag)

        # ============================================================
        # 阶段 2：UI 下单
        # ============================================================
        logger.info("=" * 60)
        logger.info(f"【阶段 2】UI 下单：{car_label} + {pay_label}")
        logger.info("=" * 60)

        self._ios_launch_setup_and_addresses(
            tag, E.DEFAULT_START_ADDRESS, E.DEFAULT_END_ADDRESS)
        self._ios_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_01_car_select.png")

        self._ios_select_car_type(tag, car_type=self.CAR_TYPE)
        self._ios_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_02_selected.png")

        # 支付方式选择流程因车型不同：
        # - 打錶的士：选车型 → 在"可選服務"区域选支付方式 → 確認呼叫
        # - 包車價的士：选车型 → 確認呼叫 → 弹出预付页面 → 选支付方式 → 確認支付並呼叫
        if self.CAR_TYPE == "meter":
            logger.info(f"【{tag} 步骤 7】选择{pay_label}支付方式...")
            self._ios_select_payment(tag, payment=self.PAYMENT)
            ordered = self._click_call_and_check_login_then_retry(tag)
        else:
            # 包車價的士：先点击确认呼叫，弹出预付页面后选择支付方式
            ordered = self._charter_click_call_and_select_payment(tag)

        assert ordered, f"{tag} UI 下单失败"
        logger.info(f"【{tag}】UI 下单成功")
        self._ios_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_03_order_success.png")

        # ============================================================
        # 阶段 3：切司机 App → UI 接单 → 滑动状态 → 填写与确认账单
        # ============================================================
        logger.info("=" * 60)
        logger.info("【阶段 3】司机 UI：接单→到达上车点→接载→到达目的地→确认账单")
        logger.info("=" * 60)
        self._driver_ui_grab_and_flow(tag)
        if stop_after == "accepted":
            # 本次只验证下单与接单，保留司机订单页面，不推进行程或支付。
            self.driver_ui.snapshot("accepted_order")
            logger.info(f"【{tag} 接单调试完成】司机已接单；未滑动后续状态、未提交账单、未支付")
            return
        logger.info(f"【{tag}】司机 UI 账单已提交，切回乘客 App 处理支付")
        self.client.app_activate(E.PASSENGER_BUNDLE_ID)

        # ============================================================
        # 阶段 4：App 端订单完成后返回首页
        # ============================================================
        logger.info("=" * 60)
        logger.info("【阶段 4】App 端：订单完成后返回首页")
        logger.info("=" * 60)

        # 等待 App 收到订单完成推送
        time.sleep(5)

        if self.CAR_TYPE == "meter" and self.PAYMENT != "cash":
            # 打表在线支付必须等到真实费用页，不能因推送稍慢跳过付款。
            self._ios_wait_current_payment(tag)
            self._ios_complete_payment(tag)
        else:
            page_texts = self._ios_get_all_texts(self.client)
            if any("確認支付" in t or "确认支付" in t for t in page_texts):
                self._ios_complete_payment(tag)
            else:
                self._ios_back_to_home(tag)

        # 真机顺序：乘客完成支付并回首页 → 切司机 → 返回首页 → 到账详情核验同单。
        try:
            self.driver_ui.wait_completed()
        except Exception:
            self.driver_ui.snapshot("payment_verification_failed")
            raise
        logger.info(f"【{tag} 全 UI 流程完成】订单 {self.driver_ui.order_no} 已完成且已支付")

    # ==================== UI 下单辅助方法 ====================

    def _ios_wait_current_payment(self, tag):
        """等待真实乘客费用页，并核对付款金额等于司机刚提交的车费加附加费。"""
        from decimal import Decimal
        settings = self.order_settings.get("driver") or {}
        expected = Decimal(str(os.environ.get("HK_ORDER_AMOUNT", settings.get("fare", "5")))) + Decimal(
            str(os.environ.get("HK_OTHER_AMOUNT", settings.get("surcharge", "0"))))
        timeout = (self.order_settings.get("order_validation") or {}).get("completion_timeout", 90)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            texts = self._ios_get_all_texts(self.client)
            if any(kw in t for t in texts for kw in ("支付失敗", "支付失败", "訂單已取消", "订单已取消")):
                raise RuntimeError(f"{tag}: 乘客订单支付失败或取消，停止操作")
            for text in texts:
                match = re.search(r"(?:確認支付|确认支付)\s*([0-9]+(?:\.[0-9]+)?)\s*HKD", text)
                if match:
                    assert Decimal(match.group(1)) == expected, f"{tag}: 付款金额与司机账单不一致，禁止提交"
                    self._ios_screenshot("epayment_current_before_payment.png")
                    logger.info("【%s】已确认乘客付款金额 %s HKD", tag, expected)
                    return
            time.sleep(1)
        raise TimeoutError(f"{tag}: 未等到带金额的确认支付页面，不跳过支付")

    def _ios_click_confirm_call(self, tag):
        """乘客确认呼叫只执行乘客 UI，不读取或验证司机 App token。"""
        return super()._ios_click_confirm_call(tag)

    def _ios_click_confirm_pay(self, tag):
        """乘客确认支付不以司机接口会话为前置，司机接单在下单成功之后。"""
        return super()._ios_click_confirm_pay(tag)

    def _charter_click_call_and_select_payment(self, tag):
        """包車價的士下单流程：点击确认呼叫 → 预付页面选支付方式 → 确认支付并呼叫。

        包車價的士点击"確認呼叫"后弹出预付车费页面（收银台），
        在该页面选择支付方式（Alipay HK / 信用卡或扣帳卡）后，
        点击"確認支付並呼叫"完成下单。

        :param tag: 日志标签。
        :return: True 表示下单成功，False 表示下单失败。
        """
        # 步骤 7：点击确认呼叫（触发预付页面弹出）
        logger.info(f"【{tag} 步骤 7】点击确认呼叫，等待预付页面弹出...")
        self._ios_click_confirm_call(tag)
        time.sleep(3)

        # 检测是否弹出预付页面（收银台）
        page_texts = self._ios_get_all_texts(self.client)
        if not any(kw in t for t in page_texts for kw in E.CASHIER_PAGE_KEYWORDS):
            # 未弹出预付页面，可能直接下单或跳到登录页
            logger.info(f"【{tag}】未检测到预付页面，按常规流程处理...")
            # 回退到标准流程的等待下单结果
            result = self._ios_wait_order_result(tag, max_checks=15)
            if result == "success":
                return True
            logger.warning(f"【{tag}】未弹出预付页面且下单未成功")
            return False

        # 步骤 8：在预付页面选择支付方式
        pay_label = PAYMENT_LABELS.get(self.PAYMENT, self.PAYMENT)
        logger.info(f"【{tag} 步骤 8】预付页面选择{pay_label}支付方式...")
        self._ios_select_payment(tag, payment=self.PAYMENT)
        self._ios_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_03_payment_selected.png")

        # 步骤 9：点击"確認支付並呼叫"
        logger.info(f"【{tag} 步骤 9】点击确认支付并呼叫...")
        self._ios_click_confirm_pay(tag)

        # 已确认的预付先完成渠道支付，再等待下单；不得重复确认或提前回首页。
        if self.PAYMENT == "bankcard":
            filled = self._ios_pay(tag, payment="bankcard", stage="submitted")
            if filled:
                logger.info(f"【{tag} 步骤 10】已填写银行卡信息并提交支付")
            else:
                logger.info(f"【{tag} 步骤 10】未检测到银行卡填写页面，继续等待下单结果")
        elif self.PAYMENT == "alipay":
            self._ios_pay(tag, payment="alipay", stage="submitted")
            logger.info(f"【{tag} 步骤 10】Alipay HK预付已确认SUCCESS并返回App")

        # 等待下单结果
        if self._ios_is_login_page():
            logger.warning(f"【{tag}】确认支付后跳到登录页，登录态可能失效")
            return False

        logger.info(f"【{tag}】确认支付后等待下单结果...")
        result = self._ios_wait_order_result(tag, max_checks=15)
        if result == "success":
            return True

        logger.warning(f"【{tag}】确认支付后下单未成功: {result}")
        return False

    def _click_call_and_check_login_then_retry(self, tag):
        """点击确认呼叫后检测登录态，未登录则登录后重新下单。

        - 检测"距离太近"提示 → 自动切换备选终点重试
        - 检测登录态失效 → UI 登录后重试
        - 检测"未完成訂單"弹窗 → 处理遗留订单后重试

        :param tag: 日志标签。
        :return: True 表示下单成功，False 表示下单失败。
        """
        max_retry = 3
        # 备选终点列表（距离太近时依次切换）
        fallback_ends = list(E.FALLBACK_END_ADDRESSES)
        fallback_idx = 0  # 当前使用的备选终点索引
        current_end = E.DEFAULT_END_ADDRESS

        for attempt in range(max_retry):
            attempt_label = "首次" if attempt == 0 else f"重试({attempt})"
            logger.info(f"【{tag} 步骤 8】{attempt_label}点击确认呼叫（终点={current_end}）...")
            self._ios_click_confirm_call(tag)
            time.sleep(8)

            if self._ios_is_login_page():
                logger.warning(
                    f"【{tag}】{attempt_label}点击确认呼叫后跳到登录页，"
                    f"App 登录态已失效，执行 UI 登录...")
                self._ios_screenshot(
                    f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_login_page_{attempt}.png")
                login_ok = self._ios_ui_login(tag=tag)

                if not login_ok:
                    logger.error(f"【{tag}】UI 登录失败")
                    if attempt >= max_retry - 1:
                        return False
                    continue

                if attempt < max_retry - 1:
                    logger.info(f"【{tag}】登录成功，从当前页面重新走下单流程...")
                    self._ios_re_setup_from_current_page(
                        tag, E.DEFAULT_START_ADDRESS, current_end)
                    continue
                else:
                    logger.error(f"【{tag}】已达最大重试次数，仍跳到登录页")
                    return False
            else:
                logger.info(f"【{tag}】点击确认呼叫后未跳到登录页，等待下单结果...")
                result = self._ios_wait_order_result(tag, max_checks=15)

                if result == "success":
                    return True

                # 遗留未完成订单 → 处理后重新下单
                if result == "ongoing_order":
                    logger.warning(f"【{tag}】检测到'未完成訂單'弹窗，处理遗留订单...")
                    self._ios_handle_unfinished_order_popup(tag)
                    if attempt < max_retry - 1:
                        self._ios_re_setup_from_current_page(
                            tag, E.DEFAULT_START_ADDRESS, current_end)
                        continue

                # 距离太近 → 切换备选终点重试
                if result == "too_close":
                    if fallback_idx < len(fallback_ends):
                        current_end = fallback_ends[fallback_idx]
                        fallback_idx += 1
                        logger.warning(
                            f"【{tag}】距离太近，切换终点为: {current_end}")
                        self._ios_re_setup_from_current_page(
                            tag, E.DEFAULT_START_ADDRESS, current_end)
                        continue
                    else:
                        logger.error(
                            f"【{tag}】所有备选终点均距离太近，无法下单")
                        return False

                # 检测"未完成訂單"弹窗
                page_texts = self._ios_get_all_texts(self.client)
                if any(("未完成" in t and ("訂單" in t or "订单" in t))
                       for t in page_texts):
                    logger.warning(f"【{tag}】检测到'未完成訂單'弹窗，处理遗留订单...")
                    self._ios_handle_unfinished_order_popup(tag)
                    if attempt < max_retry - 1:
                        self._ios_re_setup_from_current_page(
                            tag, E.DEFAULT_START_ADDRESS, current_end)
                        continue

                if self._ios_is_login_page() and attempt < max_retry - 1:
                    logger.warning(
                        f"【{tag}】下单失败且页面在登录页，执行 UI 登录后重试...")
                    self._ios_ui_login(tag=tag)
                    time.sleep(3)
                    self._ios_re_setup_from_current_page(
                        tag, E.DEFAULT_START_ADDRESS, current_end)
                    continue

                # 超时无结果 → 尝试切换终点重试一次
                if result == "timeout" and attempt < max_retry - 1:
                    if fallback_idx < len(fallback_ends):
                        current_end = fallback_ends[fallback_idx]
                        fallback_idx += 1
                        logger.warning(
                            f"【{tag}】下单超时无结果，切换终点为: {current_end} 重试")
                        self._ios_re_setup_from_current_page(
                            tag, E.DEFAULT_START_ADDRESS, current_end)
                        continue

                page_texts = self._ios_get_all_texts(self.client)
                logger.warning(f"【{tag}】下单失败({result})，页面文本: {page_texts[:300]}")
                return False

        logger.error(f"【{tag}】达到最大重试次数 {max_retry}，下单失败")
        return False

    def _ios_handle_unfinished_order_popup(self, tag):
        """处理"您還有未完成的訂單"提示弹窗。

        - 点击"去完成" → 跳转到订单页面
        - 等待接单页 → 取消订单
        - 行程结束/支付页 → 完成支付 → 返回首页
        """
        go_clicked = False
        # 点击"去完成"/"去處理"按钮
        go_clicked = self._ios_click_dialog_button(
            ["去完成", "去處理", "去处理"], tag=tag, fallback_coord=(259, 482), wait_after=2)

        if not go_clicked:
            # 点击"稍後"/"關閉"关闭弹窗
            if self._ios_click_dialog_button(
                    ["稍後", "稍后", "關閉", "关闭"], tag=tag, wait_after=2):
                return
            go_clicked = True  # 坐标已点击，继续

        # 等待页面加载完成（最多 10 秒），检测页面类型
        texts = []
        for load_wait in range(10):
            time.sleep(1)
            texts = self._ios_get_all_texts(self.client)
            # 页面加载完成标志：出现关键词或文本数量 > 3
            if any(kw in t for t in texts for kw in
                   ["取消訂單", "行程結束", "行程结束", "確認支付", "費用明細",
                    "訂單編號", "想去哪裡", "主頁"]) or len(texts) > 3:
                break
        logger.info(f"【{tag}】点击'去完成'后页面文本: {texts[:200]}")

        # 情况 A：等待接单页 → 取消订单
        if any("取消訂單" in t for t in texts):
            logger.info(f"【{tag}】跳转到进行中订单页，取消订单...")
            # 点击"取消訂單"
            self._ios_click_dialog_button(
                ["取消訂單", "取消订单"], tag=tag, wait_after=3)
            # 点击取消确认按钮
            self._ios_click_dialog_button(
                self.CANCEL_CONFIRM_KEYWORDS, tag=tag, wait_after=3)
            time.sleep(3)
            logger.info(f"【{tag}】遗留订单取消完成")

        # 情况 B：行程结束/支付页 → 完成支付 → 返回首页
        elif any("行程結束" in t or "行程结束" in t or
                 "確認支付" in t or "費用明細" in t or "訂單編號" in t
                 for t in texts):
            logger.info(f"【{tag}】跳转到行程结束/支付页，开始支付流程...")
            self._ios_complete_payment(tag)

        else:
            logger.warning(f"【{tag}】点击'去完成'后未识别页面类型")

    def _ios_complete_payment(self, tag):
        """正常后付及遗留订单均委托公共支付入口；现金保持原返回首页行为。"""
        if self.final_payment == "cash":
            return self._ios_back_to_home(tag)
        return self._ios_pay(tag, payment=self.final_payment)

    def _ios_re_setup_from_current_page(self, tag, start_addr, end_addr):
        """登录成功后从当前页面重新配置起终点、选车型、选支付。"""
        monitor = self._ios_ensure_monitor()
        state = monitor.inspect().state
        logger.info(f"【{tag}】登录后当前页面状态: {state}，不重启 App，直接配置起终点")

        if state == "activity_popup":
            monitor.dismiss_activity_popup(self.client)
            time.sleep(2)
            state = monitor.inspect().state

        if state == "privacy_agreement":
            monitor.click_text(self.client, "同意")
            time.sleep(3)
            state = monitor.inspect().state

        if state in ("home_unlogged", "home_logged"):
            search_entry = self.poco(textMatches=".*想去哪.*|.*您從哪裡出發.*|.*搜索.*")
            if search_entry.exists():
                search_entry.click()
                time.sleep(3)
            else:
                self.client.click(196, 120)
                time.sleep(3)

        self._ios_configure_addresses(tag, start_addr, end_addr)
        time.sleep(7)

        self._ios_select_car_type(tag, car_type=self.CAR_TYPE)
        self._ios_select_payment(tag, payment=self.PAYMENT)

    def _ui_cleanup_ongoing_order(self, tag):
        """UI 方式取消遗留的进行中订单，并在需要时执行 UI 登录。

        拉起 App 后依次处理：
        1. 系统弹窗 + 隐私协议 + 引导页 + 广告弹窗
        2. 情况 1：在等待接单页 → 点击取消訂單 → 确认取消 → 回首页
        3. 情况 1b：检测到"未完成訂單"弹窗 → 去完成/取消/关闭
        4. 情况 2：检测到登录页 → 执行 UI 登录
        """
        # 共用启动遮挡清理，遗留订单取消和登录判断仍留在本编排中。
        self._ios_prepare_passenger_app(tag, launch_wait=8, alert_wait=1)

        page_texts = self._ios_get_all_texts(self.client)
        logger.info(f"【{tag}】预清理: 当前页面文本: {page_texts[:200]}")

        # 情况 1：等待接单页 → 取消订单
        if any("取消訂單" in t for t in page_texts):
            logger.info(f"【{tag}】预清理: 检测到进行中订单，正在取消...")
            # 点击"取消訂單"按钮
            if not self._ios_click_dialog_button(
                    ["取消訂單", "取消订单"], tag=tag, log_prefix="预清理", wait_after=3):
                logger.warning(f"【{tag}】预清理: 未找到取消订单按钮")

            confirm_texts = self._ios_get_all_texts(self.client)
            logger.info(f"【{tag}】预清理: 取消后弹窗文本: {confirm_texts[:200]}")

            # 点击取消确认按钮（不用車了/確認取消/確定 等）
            confirmed = self._ios_click_dialog_button(
                self.CANCEL_CONFIRM_KEYWORDS, tag=tag, log_prefix="预清理", wait_after=3)
            if not confirmed:
                logger.warning(f"【{tag}】预清理: 未找到取消确认按钮，可能已直接取消")

            time.sleep(3)
            self._ios_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_00_cleanup.png")
            logger.info(f"【{tag}】预清理: 订单取消完成")

            # 取消后关闭可能连续弹出的确认弹窗
            self._ios_dismiss_dialogs(
                ["確定", "确定", "好", "OK", "我知道了"], tag=tag, max_rounds=3, wait_after=1)

            # 强制回首页
            self.client.home()
            time.sleep(1)
            self.client.session(E.PASSENGER_BUNDLE_ID)
            time.sleep(3)

            # 验证已返回首页
            for back_wait in range(10):
                page_texts = self._ios_get_all_texts(self.client)
                if any(kw in t for t in page_texts for kw in ["想去哪裡", "想去哪里", "主頁"]):
                    logger.info(f"【{tag}】预清理: 取消后已返回首页 ({back_wait+1}s)")
                    break
                # 再尝试关闭弹窗
                self._ios_click_dialog_button(
                    ["確定", "确定", "好", "OK"], tag=tag, wait_after=1)
                time.sleep(1)
        else:
            logger.info(f"【{tag}】预清理: 不在等待接单页")

        # 情况 1b：检测"未完成訂單"提示弹窗
        page_texts = self._ios_get_all_texts(self.client)
        if any(("未完成" in t and "訂單" in t) or ("未完成" in t and "订单" in t)
               for t in page_texts):
            logger.info(f"【{tag}】预清理: 检测到'未完成訂單'提示弹窗")
            # 点击"去完成"/"去處理"
            if self._ios_click_dialog_button(
                    ["去完成", "去處理", "去处理"], tag=tag, wait_after=5):
                texts2 = self._ios_get_all_texts(self.client)
                if any("取消訂單" in t for t in texts2):
                    logger.info(f"【{tag}】预清理: 跳转到进行中订单页，取消订单...")
                    self._ios_click_dialog_button(
                        ["取消訂單", "取消订单"], tag=tag, wait_after=3)
                    self._ios_click_dialog_button(
                        self.CANCEL_CONFIRM_KEYWORDS, tag=tag, wait_after=3)
                time.sleep(3)
            else:
                # 点击"稍後"/"關閉"关闭弹窗
                self._ios_click_dialog_button(
                    ["稍後", "稍后", "關閉", "关闭"], tag=tag, wait_after=2)

        # 情况 2：检测登录页
        self._ios_ensure_logged_in(tag=tag)

        self.client.home()
        time.sleep(2)

    # ==================== 司机端 UI 辅助方法 ====================

    def _driver_ui_go_online(self, tag):
        """先打开司机 App 出车；之后顺序切换乘客下单，全部通过 WDA 页面操作。"""
        self.driver_runtime = self._resolve_driver_runtime()
        args = self._driver_parser().parse_args(["--wda-url", self.driver_runtime.wda_url, "--stop-after", "online"])
        self.driver_ui = self._create_driver_flow(args)
        self.driver_ui.ensure_online()
        logger.info(f"【{tag}】司机 UI 已确认听单，继续乘客下单")

    def _driver_ui_grab_and_flow(self, tag):
        """乘客下单后切回司机，UI 接单、滑动状态并提交测试账单，不请求业务 API。"""
        settings = self.order_settings.get("driver") or {}
        stop_after = os.environ.get("HK_DRIVER_UI_STOP_AFTER", "submitted")
        limits = self.order_settings.get("order_validation") or {}
        args = ["--wda-url", self.driver_runtime.wda_url, "--stop-after", stop_after,
                "--timeout", str(limits.get("total_timeout", 900)),
                "--step-timeout", str(limits.get("state_timeout", 30)),
                "--dispatch-timeout", str(limits.get("dispatch_timeout", 90)),
                "--payment-timeout", str(limits.get("completion_timeout", 90)),
                "--fare", str(os.environ.get("HK_ORDER_AMOUNT", settings.get("fare", "5"))),
                "--surcharge", str(os.environ.get("HK_OTHER_AMOUNT", settings.get("surcharge", "0"))),
                "--payment", "cash" if self.PAYMENT == "cash" else "online"]
        tail = os.environ.get("HK_DRIVER_PASSENGER_TAIL") or settings.get("passenger_tail")
        if tail:
            if not str(tail).isdigit() or len(str(tail)) != 4:
                raise RuntimeError("请配置四位乘客测试尾号")
            args.extend(["--tail", str(tail)])
        if self.PAYMENT == "cash" and os.environ.get("HK_DRIVER_CASH_COLLECTED") == "1":
            args.append("--cash-collected")
        self.driver_ui = self._create_driver_flow(self._driver_parser().parse_args(args))
        try:
            self.driver_ui.run()
        except Exception:
            self.driver_ui.snapshot("failed_order_flow")
            raise
        expected = ("departure", "pickup") if stop_after == "accepted" else ("unpaid", "complete")
        assert self.driver_ui.last_phase in expected, f"{tag}: 司机 UI 未确认接单或账单提交成功"
