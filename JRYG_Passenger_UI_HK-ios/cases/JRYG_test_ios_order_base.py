"""
港版 iOS 下单+司机端接口接单流转 —— 参数化基类
==============================================================================
所有车型+支付方式的组合用例继承本基类，只需设置类属性：
  CAR_TYPE  : 车型（"meter"=打錶的士 / "charter"=包車價的士）
  PAYMENT   : 支付方式（"cash" / "epayment" / "alipay" / "bankcard"）

流程：
  阶段 0（UI）  ：预清理 —— 取消遗留的进行中订单 / 处理未支付订单
  阶段 1（UI）  ：打开已登录司机 App → 点击出车 → 复用当前 App 会话
  阶段 2（UI）  ：拉起乘客 App → 配置起终点 → 选择车型 → 选择支付方式
               → 确认呼叫 → 检测登录态 → 未登录则登录后重新下单 → 等待下单成功
  阶段 3（接口）：轮询派单 → 接单 → 状态流转 → 确认账单
  阶段 4（UI）  ：乘客实际支付 → 接口验证完成与支付状态

注意：
  1. 不使用双端 API 重新登录，司机会话通过 HK_DRIVER_ACCESS_TOKEN/SESSION_FILE 注入。
  2. 司机需要独立设备的 HK_DRIVER_WDA_URL；默认由司机 App 维护派单长连接。
  3. HK_DRIVER_USE_API_SOCKET=1 可显式使用接口定位上报，需确认不会与 App 连接冲突。
==============================================================================
"""

import os
import re
import sys
import time

import pytest
import wda

# 添加 UI 框架根路径（本用例所在目录的上级 = JRYG_Passenger_UI_HK-ios）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 添加项目根路径（JRYG_PassengerIUi），用于导入 JRYG_Passenger_API_HK 跨项目 API 层
PROJECT_ROOT = os.path.dirname(BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 导入港版 iOS 自动化配置（设备信息、目录路径等）
from jryg_hk_ios.JRYG_config import SETTINGS
# 导入统一日志记录器，全流程日志输出
from jryg_hk_ios.JRYG_logger import logger
# 导入 iOS 自动化公共基类，提供设备连接、地址搜索、车型选择、支付等通用操作
from jryg_hk_ios.JRYG_ios_ui_base import iOSBase
# 导入 UI 元素定位常量（XPath、关键词、坐标、测试数据）
from jryg_hk_ios import JRYG_ios_ui_elements as E
from jryg_hk_ios.JRYG_driver_order_api import DriverOrderAPI, load_app_session
from JRYG_run_driver_flow import DriverUIFlow, parser as driver_parser

# 导入 API 层客户端 —— 司机端接口操作（登录、接单、状态流转等）
from JRYG_Passenger_API_HK.cases.JRYG_test_hk_driver_api import (
    HKDriverApiClient, DRIVER_LATITUDE, DRIVER_LONGITUDE,
)
# 导入 Socket 长连接客户端 —— 接收订单派发推送 + 位置上报
from JRYG_Passenger_API_HK.common.jryg_socket_client import JRYGSocketClient
# 导入 Redis 缓存清理工具 —— 清理司机派单缓存，确保测试环境干净
from JRYG_Passenger_API_HK.common.redis_cache_cleaner import clean_driver_cache
# 导入港版 API 配置 —— 轮询超时、状态等待、订单金额、Socket 配置等
from JRYG_Passenger_API_HK.common.hk_config import config as api_config


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
    "octopus": "八達通",       # 八達通卡支付（暂不执行）
}


class TestOrderBase(iOSBase):
    """参数化下单+司机端接口接单流转基类。

    子类只需设置类属性 CAR_TYPE 和 PAYMENT，无需重写任何方法。
    本基类不直接执行（__test__ = False），由子类继承后设置参数。
    """

    __test__ = False  # pytest 不收集基类本身，由子类继承后设置参数执行

    # ==================== 子类必须覆盖的类属性 ====================
    CAR_TYPE = ""   # 车型标识："meter"=打錶的士 / "charter"=包車價的士
    PAYMENT = ""    # 支付方式标识："cash" / "epayment" / "alipay" / "bankcard" / "octopus"

    @classmethod
    def setup_class(cls):
        """类级 setup：连接 WDA 设备 + 创建司机端 API 客户端与 Socket 客户端。

        调用父类 setup_class 完成 WDA 连接和 Poco 初始化，
        然后创建司机端 API 客户端实例（后续登录、接单等操作使用）。
        Socket 客户端在阶段 1 中创建。
        """
        # 先调用父类完成 iOS 设备连接（WDA + Poco）
        super().setup_class()
        # 创建司机端 API 客户端（登录、出车、接单、状态流转等接口操作）
        cls.driver_api = HKDriverApiClient()
        # Socket 客户端占位，在阶段 1 中实际创建
        cls.socket_client = None

    @classmethod
    def teardown_class(cls):
        """释放测试创建的 Socket，保留司机 App 在线状态。"""
        # 先断开 Socket 长连接，停止位置上报和心跳
        if cls.socket_client:
            try:
                cls.socket_client.disconnect()
            except Exception:
                pass
            cls.socket_client = None
        logger.info("【teardown】保留司机 App 出车状态，不自动收车")
        # 调用父类 teardown 释放设备连接
        super().teardown_class()

    # ==================== 主测试方法 ====================

    def test_order_flow(self):
        """UI 下单（指定车型+支付方式） → 司机端接口接单 → 订单流转 → 结束"""
        car_label = CAR_TYPE_LABELS.get(self.CAR_TYPE, self.CAR_TYPE)
        pay_label = PAYMENT_LABELS.get(self.PAYMENT, self.PAYMENT)
        tag = f"{car_label}+{pay_label}"

        assert self.CAR_TYPE, f"{tag}: 未设置 CAR_TYPE 类属性"
        assert self.PAYMENT, f"{tag}: 未设置 PAYMENT 类属性"

        # ============================================================
        # 阶段 0：预清理
        # ============================================================
        logger.info("=" * 60)
        logger.info("【阶段 0】预清理：取消遗留的进行中订单")
        logger.info("=" * 60)
        self._ui_cleanup_ongoing_order(tag)

        # ============================================================
        # 阶段 1：司机 App 打开与出车，复用 App 会话
        # ============================================================
        logger.info("=" * 60)
        logger.info("【阶段 1】司机端：打开 App→UI 出车→复用会话")
        logger.info("=" * 60)

        self._driver_ui_go_online(tag)
        if self.driver_api_socket_enabled:
            self._driver_api_start_socket(tag)

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
        # 阶段 3：轮询订单获取 order_no → 接单 → 流转 → 结束
        # ============================================================
        logger.info("=" * 60)
        logger.info("【阶段 3】司机端：轮询订单→接单→流转→结束")
        logger.info("=" * 60)

        order_no = self._driver_api_polling_order(tag)
        logger.info(f"【{tag}】获取到订单号: {order_no}")
        self._driver_api_grab_and_flow(tag, order_no)

        logger.info("=" * 60)
        logger.info(f"【{tag} 司机接口流转完成】订单号: {order_no}，待核验支付")
        logger.info("=" * 60)

        # ============================================================
        # 阶段 4：App 端订单完成后返回首页
        # ============================================================
        logger.info("=" * 60)
        logger.info("【阶段 4】App 端：订单完成后返回首页")
        logger.info("=" * 60)

        # 等待 App 收到订单完成推送
        time.sleep(5)

        # 检测 App 当前页面：如果需要支付则先完成支付，再返回首页
        page_texts = self._ios_get_all_texts(self.client)
        if any("確認支付" in t or "确认支付" in t for t in page_texts):
            logger.info(f"【{tag}】订单完成后检测到支付页面，执行支付流程...")
            self._ios_complete_payment(tag)
        else:
            logger.info(f"【{tag}】订单完成后无支付页面，直接返回首页...")
            self._ios_back_to_home(tag)

        DriverOrderAPI(self.driver_api, logger).wait_completed(
            order_no, timeout=api_config.POLLING_TIMEOUT)
        logger.info(f"【{tag} 全流程完成且已支付】订单号: {order_no}")

    # ==================== UI 下单辅助方法 ====================

    def _ios_click_confirm_call(self, tag):
        self._driver_api_require_ready(tag)
        return super()._ios_click_confirm_call(tag)

    def _ios_click_confirm_pay(self, tag):
        self._driver_api_require_ready(tag)
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

        # 步骤 10：检测是否跳转到银行卡填写页面（bankcard 支付方式）
        if self.PAYMENT == "bankcard":
            filled = self._ios_fill_bank_card_form(tag)
            if filled:
                logger.info(f"【{tag} 步骤 10】已填写银行卡信息并提交支付")
            else:
                logger.info(f"【{tag} 步骤 10】未检测到银行卡填写页面，继续等待下单结果")

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
        """在行程结束/支付页完成支付并返回首页。

        流程因支付方式不同：
        - bankcard/epayment：选"信用卡或扣帳卡" → 確認支付 → 银行卡表单 → OTP → 返回
        - alipay：选"Alipay HK"（或默认已选）→ 確認支付 → Safari Pay Now → SUCCESS → 返回
        - cash/无支付页：直接返回首页
        """
        # ---- 步骤 0：行程结束支付页，选择支付方式 ----
        # 页面有多个支付方式选项（Alipay HK / 信用卡或扣帳卡），需先选中目标方式
        page_texts = self._ios_get_all_texts(self.client)
        has_payment_options = any(
            "信用卡或扣帳卡" in t or "Alipay HK" in t for t in page_texts)

        if has_payment_options:
            if self.PAYMENT in ("bankcard", "epayment"):
                # 选"信用卡或扣帳卡"
                logger.info(f"【{tag}】支付步骤 0：选择'信用卡或扣帳卡'支付方式...")
                pay_opt = self.client(textContains="信用卡或扣帳卡")
                if not pay_opt.exists:
                    pay_opt = self.poco(textMatches=".*信用卡.*|.*扣帳卡.*")
                if pay_opt.exists if hasattr(pay_opt, "exists") else pay_opt.exists():
                    try:
                        pay_opt.click()
                    except Exception:
                        pay_opt.tap() if hasattr(pay_opt, "tap") else pay_opt.click()
                    logger.info(f"【{tag}】已选择'信用卡或扣帳卡'")
                    time.sleep(2)
            else:
                # epayment/alipay 默认选中 Alipay HK，如未选中则点击
                logger.info(f"【{tag}】支付步骤 0：确认'Alipay HK'支付方式...")
                alipay_opt = self.poco(textMatches=".*Alipay.*")
                if alipay_opt.exists():
                    # 检测是否已选中（有 selected 标识），未选中则点击
                    alipay_opt.click()
                    logger.info(f"【{tag}】已确认选择'Alipay HK'")
                    time.sleep(2)

        # ---- 步骤 1：点击确认支付 ----
        logger.info(f"【{tag}】支付步骤 1：点击确认支付按钮...")
        pay_btn = self.poco(textMatches=".*確認支付.*|.*确认支付.*")
        if pay_btn.exists():
            pay_btn.click()
        else:
            pay_wda = self.client(textContains="確認支付")
            if pay_wda.exists:
                pay_wda.click()
            else:
                self.client.click(196, 789)
        time.sleep(5)

        # ---- 步骤 2：bankcard/epayment → 银行卡表单 + OTP ----
        if self.PAYMENT in ("bankcard", "epayment"):
            logger.info(f"【{tag}】支付步骤 2：填写银行卡信息...")
            filled = self._ios_fill_bank_card_form(tag)
            if filled:
                logger.info(f"【{tag}】银行卡支付完成")
            else:
                logger.warning(f"【{tag}】未检测到银行卡页面，尝试继续...")
            # 步骤 6：返回首页
            logger.info(f"【{tag}】支付步骤 6：返回首页...")
            self._ios_back_to_home(tag)
            return

        # ---- epayment/alipay → Safari 支付流程 ----
        # 注意：Safari 内的元素（含系统弹窗）只能用【坐标点击】，
        #      element uuid 点击（wda Selector.click）对 Safari WebView 无效。
        # 步骤 2：等待并关闭 Safari 弹窗（弹窗在页面加载后才出现，需轮询等待）
        logger.info(f"【{tag}】支付步骤 2：等待并关闭 Safari 弹窗...")
        self._ios_wait_and_close_safari_alert(tag)

        # 步骤 3：点击 Pay Now（Safari 内元素 → 坐标点击）
        logger.info(f"【{tag}】支付步骤 3：点击 Pay Now...")
        # 点击前再确认一次弹窗已关闭（否则弹窗会吞掉点击）
        self._ios_wait_and_close_safari_alert(tag)
        if not self._ios_safari_click_by_text("Pay Now", 196, 460):
            self.client.click(196, 460)
        time.sleep(5)

        # 步骤 4：等待支付成功
        logger.info(f"【{tag}】支付步骤 4：等待支付成功...")
        pay_success = False
        for i in range(15):
            texts = self._ios_get_all_texts(self.client)
            if any("SUCCESS" in t for t in texts):
                logger.info(f"【{tag}】支付成功！")
                pay_success = True
                break
            # 支付页跳转过程中可能再弹出"网址无效"，需先关掉
            self._ios_wait_and_close_safari_alert(tag)
            time.sleep(2)

        if not pay_success:
            logger.warning(f"【{tag}】支付未确认成功，尝试继续...")
        else:
            # 步骤 5：返回 App
            logger.info(f"【{tag}】支付步骤 5：返回 App...")
            time.sleep(2)
            # Pay Now 成功后会弹出"在XX中打开此页?"，需点"打开"回到 App
            for _ in range(3):
                texts = self._ios_get_all_texts(self.client)
                if not any("打開" in t or "打开" in t for t in texts):
                    break
                # "打开"按钮坐标随弹窗高度变化，按 XML 动态定位
                if not self._ios_safari_click_by_text("打开", 336, 429, exact=True):
                    self.client.click(336, 429)
                logger.info(f"【{tag}】已点击'打开'返回 App")
                time.sleep(3)

            # 兜底：Safari 仍停留在成功页时，点 Return to Merchant
            texts = self._ios_get_all_texts(self.client)
            if any("Return to Merchant" in t for t in texts):
                self._ios_safari_click_by_text("Return to Merchant", 196, 385)
                time.sleep(3)
                texts = self._ios_get_all_texts(self.client)
                if any("打開" in t or "打开" in t for t in texts):
                    if not self._ios_safari_click_by_text("打开", 336, 429, exact=True):
                        self.client.click(336, 429)
                    time.sleep(5)

        # 步骤 6：从评价/行程结束页返回首页
        logger.info(f"【{tag}】支付步骤 6：返回首页...")
        self._ios_back_to_home(tag)

    def _ios_wait_and_close_safari_alert(self, tag, wait_seconds=12):
        """等待并关闭 Safari 的"网址无效"系统弹窗。

        Safari 打开第三方支付页时会出现「Safari浏览器打不开该网页，因为网址无效。」
        的系统弹窗，它会遮挡页面导致后续所有点击失效。
        该弹窗是在页面加载完成后才出现的，因此需要轮询等待其出现后再关闭。

        注意：Safari 系统弹窗必须用【坐标点击】关闭，
        element uuid 点击（wda Selector.click）对其无效。

        :param tag: 日志标签。
        :param wait_seconds: 最长等待秒数。
        :return: True 表示检测到并关闭了弹窗。
        """
        alert_kw = ("打不开", "网址无效", "無法連接", "Safari浏览器打不开")
        deadline = time.time() + wait_seconds
        closed = False
        while time.time() < deadline:
            texts = self._ios_get_all_texts(self.client)
            if any(any(k in t for k in alert_kw) for t in texts):
                # 弹窗"好"按钮坐标随弹窗高度变化（(338,392) / (338,440)），
                # 必须按 XML 动态定位，exact=True 精确匹配避免误命中其他文本
                if not self._ios_safari_click_by_text("好", 338, 440, exact=True):
                    self.client.click(338, 440)
                logger.info(f"【{tag}】已坐标点击 Safari 弹窗'好'")
                closed = True
                time.sleep(2)
                # 确认弹窗已消失
                texts = self._ios_get_all_texts(self.client)
                if not any(any(k in t for k in alert_kw) for t in texts):
                    break
            else:
                time.sleep(1.5)
        return closed

    def _ios_safari_click_by_text(self, text_kw, fallback_x, fallback_y, exact=False):
        """在 Safari 页面内按文本定位并【坐标点击】。

        Safari（含其 WebView 与系统弹窗）内的元素，WDA 的 element uuid 点击
        （wda Selector.click → /wda/element/{uuid}/click）不生效，
        必须读取元素 rect 后用坐标点击（/session/{sid}/wda/tap）。

        :param text_kw: 目标文本关键词。
        :param fallback_x: 未找到元素时的兜底 x 坐标。
        :param fallback_y: 未找到元素时的兜底 y 坐标。
        :param exact: True 时要求 label 与 text_kw 完全相等（避免误匹配）。
        :return: True 表示定位到元素并点击成功。
        """
        try:
            src = self._ios_get_source_xml()
            for m in re.finditer(r'<XCUIElementType\w+[^>]*>', src):
                s = m.group(0)
                lab = re.search(r'label="([^"]*)"', s)
                if not lab:
                    continue
                label = lab.group(1)
                if (label != text_kw) if exact else (text_kw not in label):
                    continue
                vis = re.search(r'visible="(\w+)"', s)
                if vis and vis.group(1) != "true":
                    continue
                # 注意：不能用 r'x="(\d+)"'，会误匹配 index="9" 中的 x="9"
                ex = re.search(r'\bx="(\d+)"', s)
                ey = re.search(r'\by="(\d+)"', s)
                ew = re.search(r'\bwidth="(\d+)"', s)
                eh = re.search(r'\bheight="(\d+)"', s)
                if not (ex and ey and ew and eh):
                    continue
                cx = int(ex.group(1)) + int(ew.group(1)) // 2
                cy = int(ey.group(1)) + int(eh.group(1)) // 2
                try:
                    self.client.click(cx, cy)
                    logger.info(f"  >> Safari 坐标点击 '{text_kw}' @ ({cx},{cy})")
                    return True
                except Exception as ce:
                    logger.warning(f"  >> Safari 坐标点击 '{text_kw}' 点击异常: {ce}")
                    continue
        except Exception as e:
            logger.warning(f"  >> Safari 坐标点击 '{text_kw}' 异常: {e}")
        # 兜底坐标
        logger.info(f"  >> Safari 未定位到 '{text_kw}'，使用兜底坐标 ({fallback_x},{fallback_y})")
        try:
            self.client.click(fallback_x, fallback_y)
        except Exception as e:
            logger.warning(f"  >> Safari 兜底坐标点击失败: {e}")
        return False

    def _ios_back_to_home(self, tag):
        """从评价/行程结束/路线选择等页面返回首页。

        循环点击左上角返回按钮，直到检测到首页元素或达到最大重试次数。
        """
        for _ in range(5):
            texts = self._ios_get_all_texts(self.client)
            if any("想去哪裡" in t or "主頁" in t for t in texts):
                logger.info(f"【{tag}】已返回首页")
                return True
            back_wda = self.client(
                xpath='//XCUIElementTypeImage[contains(@name,"navi_arrow_left")]')
            if back_wda.exists:
                back_wda.click()
                time.sleep(3)
            else:
                self.client.click(34, 82)
                time.sleep(3)
        logger.warning(f"【{tag}】未能返回首页（重试 5 次仍非首页）")
        self._ios_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_back_home_fail.png")
        return False

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

        logger.info(f"【{tag} 步骤 4】配置起点: {start_addr}")
        self._ios_search_address(is_start=True, address=start_addr)
        logger.info(f"【{tag} 步骤 5】配置终点: {end_addr}")
        self._ios_search_address(is_start=False, address=end_addr)
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
        # 回到桌面再拉起 App，确保从干净状态开始
        self.client.home()
        time.sleep(2)
        # 拉起乘客端 App
        self.client.session(E.PASSENGER_BUNDLE_ID)
        time.sleep(8)

        try:
            self.client.alert.accept()
            time.sleep(1)
        except Exception:
            pass

        self._ios_dismiss_privacy_agreement()

        for i in range(5):
            guide_btn = self.client(xpath=E.GUIDE_SKIP_XPATH)
            if guide_btn.exists:
                guide_btn.tap()
                time.sleep(3)
            else:
                break

        for ad_btn_text in E.AD_CLOSE_IDENTIFIERS:
            ad_el = self.poco(ad_btn_text)
            if ad_el.exists():
                ad_el.click()
                time.sleep(2)
                break

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

    # ==================== 司机端 API 辅助方法 ====================

    @property
    def driver_api_socket_enabled(self):
        return os.environ.get("HK_DRIVER_USE_API_SOCKET") == "1"

    def _driver_ui_go_online(self, tag):
        """复用 App 会话，司机 UI 仅打开与出车。"""
        load_app_session(self.driver_api)
        driver_url = os.environ.get("HK_DRIVER_WDA_URL")
        passenger_url = SETTINGS["device"].get("wda_url", "http://127.0.0.1:8100")
        assert driver_url and driver_url.rstrip("/") != passenger_url.rstrip("/"), (
            "请配置独立司机设备的 HK_DRIVER_WDA_URL，不能与乘客争用同一 WDA")
        args = driver_parser().parse_args(["--wda-url", driver_url, "--stop-after", "online"])
        self.driver_ui = DriverUIFlow(args)
        self.driver_ui.ensure_online()
        for _ in range(10):
            status, resp = self.driver_api.get_out_car_status()
            assert status == 200 and resp.get("code") == 10000, f"{tag}: 司机 App 会话失效或出车状态查询失败"
            if (resp.get("data") or {}).get("is_online") == 1:
                logger.info(f"【{tag}】司机 UI 出车已生效，后续仅接口操作")
                return
            time.sleep(0.5)
        raise AssertionError(f"{tag}: UI 出车后司机仍未在线，停止乘客下单")

    def _driver_api_ensure_online(self, tag):
        """只读查询司机在线状态，不在接口层出车。"""
        DriverOrderAPI(self.driver_api, logger).require_online()

    def _driver_api_start_socket(self, tag):
        """启动持续上报，并等待网关确认心跳及至少两个定位点。"""
        cls = type(self)
        if cls.socket_client is not None:
            cls.socket_client.disconnect()
        cls.socket_client = JRYGSocketClient(
            self.driver_api.access_token, lat=DRIVER_LATITUDE, lng=DRIVER_LONGITUDE,
            logger=logger)
        assert cls.socket_client.connect(), f"{tag}: 司机 Socket 登录失败，停止乘客下单"
        ready = cls.socket_client.wait_until_ready(
            timeout=api_config.DRIVER_READY_TIMEOUT,
            max_location_age=api_config.DRIVER_LOCATION_MAX_AGE,
            min_location_acks=api_config.DRIVER_LOCATION_MIN_ACKS)
        state = cls.socket_client.readiness_status()
        logger.info(f"【{tag}】司机初始定位上报确认: {state}")
        assert ready, f"{tag}: 未收到有效心跳和定位回执，停止乘客下单。状态={state}"

    def _driver_api_require_ready(self, tag):
        """乘客提交订单前检查出车、空闲、连接及本次定位回执。"""
        self._driver_api_ensure_online(tag)
        status, resp = self.driver_api.get_serving_order()
        assert status == 200 and resp.get("code") == 10000, (
            f"{tag}: 查询司机服务中订单失败，停止乘客下单")
        assert (resp.get("data") or {}).get("has_serving_order") is False, (
            f"{tag}: 司机存在服务中订单或状态未知，停止乘客下单")
        if not self.driver_api_socket_enabled:
            assert getattr(self, "driver_ui", None), "司机 App 尚未完成 UI 出车"
            self.driver_ui.check_online()
            return
        socket_client = self.socket_client
        connection_state = socket_client.readiness_status() if socket_client is not None else {}
        if not all(connection_state.get(key, False)
                   for key in ("connected", "logged_in", "running", "workers_alive")):
            logger.warning(f"【{tag}】下单前司机连接不可用，重新连接并上传定位")
            self._driver_api_start_socket(tag)
            socket_client = self.socket_client
        ready = socket_client.confirm_location(
            timeout=api_config.DRIVER_READY_TIMEOUT,
            max_location_age=api_config.DRIVER_LOCATION_MAX_AGE,
            min_location_acks=api_config.DRIVER_LOCATION_MIN_ACKS)
        state = socket_client.readiness_status()
        logger.info(f"【{tag}】下单前司机就绪检查: {state}")
        assert ready, f"{tag}: 司机定位刷新未确认，禁止乘客下单。状态={state}"

    def _driver_api_clean_cache(self, tag):
        """清理 Redis 司机派单缓存。

        清理司机在 Redis 中的派单缓存 key，确保下单时订单能正确派发给当前司机。
        清理失败不中断测试，仅记录警告。
        """
        try:
            # 调用 Redis 清理工具删除司机派单相关缓存 key
            deleted = clean_driver_cache()
            logger.info(f"【{tag}】Redis 司机缓存清理完成，删除 {deleted} 个 key")
        except Exception as e:
            # 清理失败不中断测试，继续执行
            logger.warning(f"【{tag}】Redis 缓存清理失败: {e}（继续测试）")

    def _driver_api_polling_order(self, tag):
        """通过司机端 polling 接口轮询获取派发给当前司机的订单号。

        轮询期间同时检测乘客端 App 页面：
        - 如果乘客端订单已被取消（超时/手动取消），立即停止轮询。
        - 轮询超时为 330s，略长于乘客端呼叫超时(300s)。
        """
        POLLING_TIMEOUT = api_config.POLLING_TIMEOUT
        POLLING_INTERVAL = api_config.POLLING_INTERVAL
        deadline = time.monotonic() + POLLING_TIMEOUT
        last_code = None
        last_data_log = 0  # 上次打印 data 详情的时间戳

        logger.info(f"【{tag}】开始轮询订单（超时 {POLLING_TIMEOUT}s）...")
        while time.monotonic() < deadline:
            s, resp = self.driver_api.polling_order(
                trace_id=f"d_poll_{int(time.time())}")
            DriverOrderAPI.check((s, resp), "轮询司机派单")
            code = resp.get("code")
            if code != last_code:
                logger.info(f"【{tag}】轮询返回 code={code}, msg={resp.get('message')}")
                last_code = code

            if code == 10000:
                data = resp.get("data", {})
                order_no = None
                if isinstance(data, dict):
                    order_no = data.get("order_no")
                    if not order_no:
                        order_list = data.get("list", [])
                        orders = {item.get("order_no") for item in order_list
                                  if isinstance(item, dict) and item.get("order_no")}
                        assert len(orders) <= 1, f"{tag}: 发现多个派单，停止自动接单"
                        if orders:
                            order_no = orders.pop()
                    # 每 30 秒打印一次 data 详情，避免日志刷屏
                    if not order_no and time.monotonic() - last_data_log > 30:
                        logger.info(f"【{tag}】code=10000 但无 order_no, "
                                    f"data keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}, "
                                    f"data={str(data)[:300]}")
                        last_data_log = time.monotonic()
                if order_no:
                    logger.info(f"【{tag}】轮询获取到订单号: {order_no}")
                    return order_no

            self._driver_api_ensure_online(tag)
            if self.driver_api_socket_enabled:
                socket_client = self.socket_client
                healthy = socket_client is not None and socket_client.wait_until_ready(
                    timeout=0, max_location_age=api_config.DRIVER_LOCATION_MAX_AGE,
                    min_location_acks=api_config.DRIVER_LOCATION_MIN_ACKS)
                assert healthy, (
                    f"{tag}: 等待派单时司机长连接或定位上报失效。"
                    f"状态={socket_client.readiness_status() if socket_client else '未连接'}")

            # 检测乘客端 App 是否仍在等待接单
            try:
                page_texts = self._ios_get_all_texts(self.client)
                if any(kw in t for t in page_texts
                       for kw in E.ORDER_FAIL_KEYWORDS):
                    logger.warning(f"【{tag}】乘客端检测到订单取消/失败，停止轮询")
                    raise AssertionError(
                        f"乘客端订单已被取消/失败，停止司机端轮询。"
                        f"页面文本: {page_texts[:200]}")
                # 仍在等待接单则继续
                if any("取消訂單" in t for t in page_texts):
                    pass  # 正常等待中
                elif any("想去哪裡" in t or "主頁" in t for t in page_texts):
                    logger.warning(f"【{tag}】乘客端已回到首页，订单可能已超时取消，停止轮询")
                    raise AssertionError(
                        "乘客端已回到首页，订单可能已超时取消")
            except AssertionError:
                raise
            except Exception as e:
                logger.debug(f"【{tag}】乘客端页面检测异常（忽略）: {e}")

            time.sleep(POLLING_INTERVAL)

        raise AssertionError(
            f"轮询订单超时（{POLLING_TIMEOUT}s），未获取到派发订单。"
            f"最后返回 code={last_code}")

    def _driver_api_grab_and_flow(self, tag, order_no):
        """接单调用 grab，状态 1～4 调用 serviceChange，账单调用 confirmBill，不操作司机 UI。"""
        # 订单接口层不接收 UI/Socket 客户端，禁止以点击、滑动或模拟行驶兜底。
        flow = DriverOrderAPI(self.driver_api, logger)
        flow.advance(order_no, stop_after="complete", fare=api_config.ORDER_AMOUNT,
                     surcharge=api_config.OTHER_AMOUNT,
                     payment="cash" if self.PAYMENT == "cash" else "online",
                     cash_collected=self.PAYMENT == "cash")
