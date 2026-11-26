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
from ui_framework.JRYG_driver_ui import DriverUIFlow, PHASE_NAMES, parser as driver_parser

# 司机端接口操作模块（条件启用，与 UI 模式互斥，不影响现有 UI 流程）
def _driver_api_enabled():
    """检查是否启用司机接口模式。

    优先级：
    1. 环境变量 HK_DRIVER_API_ENABLED=1/true
    2. config/JRYG_settings.yaml → driver_api.enabled
    默认 False，保持现有 UI 流程不受影响。
    """
    env_val = os.environ.get("HK_DRIVER_API_ENABLED", "").strip().lower()
    if env_val in ("1", "true", "yes", "on"):
        return True
    if env_val in ("0", "false", "no", "off"):
        return False
    api_config = SETTINGS.get("driver_api") or {}
    return bool(api_config.get("enabled"))


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
        """提供本平台订单配置；Android子类覆盖以复用同一业务编排。"""
        return SETTINGS

    def _resolve_driver_runtime(self):
        """根据订单配置解析司机设备模式，不连接设备或读取司机接口会话。"""
        return resolve_runtime(self.order_settings)

    def _driver_parser(self):
        """提供司机参数解析器供统一校验费用及时限，平台子类可替换默认值。"""
        return driver_parser()

    def _create_driver_flow(self, args):
        """以已解析参数创建司机UI状态机，平台子类可复用既有Android客户端。"""
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
        self.completed_order_no = None
        self.retry_safe = False
        self._app_crashes = []  # 记录流转过程中的崩溃事件
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

        try:
            self._run_order_flow(tag, stop_after, car_label, pay_label)
        except (RuntimeError, TimeoutError, AssertionError, OSError) as exc:
            # 记录崩溃/异常现场
            self._ios_screenshot(
                f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_exception.png")
            crash_count = len(getattr(self, "_app_crashes", []))
            if crash_count > 0:
                logger.error(f"【{tag}】流程异常（{type(exc).__name__}: {exc}），"
                             f"且流转过程中记录了 {crash_count} 次崩溃事件")
            else:
                logger.error(f"【{tag}】流程异常（{type(exc).__name__}: {exc}）")
            raise

    def _run_order_flow(self, tag, stop_after, car_label="", pay_label=""):
        """实际订单流程实现，由 test_order_flow 包裹异常处理后调用。"""

        # ============================================================
        # 阶段 0：司机端出车（接口模式或 UI 模式）
        # ============================================================
        use_driver_api = _driver_api_enabled()
        if use_driver_api:
            logger.info("=" * 60)
            logger.info("【阶段 0】司机端：接口出车（登录→出车），不操作手机")
            logger.info("=" * 60)
            self._driver_api_go_online(tag)
        else:
            logger.info("=" * 60)
            logger.info("【阶段 0】司机端：打开 App→UI 出车，不检查接口会话")
            logger.info("=" * 60)
            self._driver_ui_go_online(tag)

        if self.resuming_order:
            logger.info("【%s】接续当前订单，不重设起终点、不确认呼叫、不重新预付", tag)
            if stop_after == "accepted":
                if not use_driver_api:
                    self.driver_ui.snapshot("existing_order_accepted")
                logger.info("【%s】已有订单已接单；仅接单模式保留当前阶段，不推进行程或付款", tag)
                return
        else:
            self.retry_safe = True
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

            self._ios_configure_addresses(
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
                self.retry_safe = False
                ordered = self._click_call_and_check_login_then_retry(tag)
            else:
                # 包車價的士：先点击确认呼叫，弹出预付页面后选择支付方式
                self.retry_safe = False
                ordered = self._charter_click_call_and_select_payment(tag)

            assert ordered, f"{tag} UI 下单失败"
            logger.info(f"【{tag}】UI 下单成功")
            self._ios_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_03_order_success.png")

        # ============================================================
        # 阶段 3：司机端接单与订单流转（接口模式或 UI 模式）
        # ============================================================
        if use_driver_api:
            logger.info("=" * 60)
            if stop_after == "accepted":
                logger.info("【阶段 3】司机接口：接单（停在接单，不推进流转）")
            else:
                logger.info("【阶段 3】司机接口：接单→到达上车点→接载→到达目的地→确认账单")
            logger.info("=" * 60)
            self._driver_api_grab_and_flow(tag, stop_after=stop_after)
        else:
            logger.info("=" * 60)
            logger.info("【阶段 3】司机 UI：接单→到达上车点→接载→到达目的地→确认账单")
            logger.info("=" * 60)
            self._driver_ui_grab_and_flow(tag)
        if stop_after == "accepted" and not use_driver_api:
            # 本次只验证下单与接单，保留司机订单页面，不推进行程或支付。
            self.driver_ui.snapshot("accepted_order")
            logger.info(f"【{tag} 接单调试完成】司机已接单；未滑动后续状态、未提交账单、未支付")
            return
        if stop_after == "accepted" and use_driver_api:
            logger.info(f"【{tag} 接口接单完成】司机已接单；未推进后续状态、未提交账单、未支付")
            return
        logger.info(f"【{tag}】司机账单已提交，切回乘客 App 处理支付")
        self.client.app_activate(E.PASSENGER_BUNDLE_ID)

        # ============================================================
        # 阶段 4：App 端订单完成后返回首页
        # ============================================================
        logger.info("=" * 60)
        logger.info("【阶段 4】App 端：订单完成后返回首页")
        logger.info("=" * 60)

        # 等待 App 收到订单完成推送
        time.sleep(5)

        if use_driver_api:
            # 接口模式：司机端状态由接口维护，现金已完成支付，在线支付需乘客付款
            if self.CAR_TYPE == "meter" and self.PAYMENT != "cash":
                self._ios_wait_current_payment(tag)
                self._ios_complete_payment(tag)
            else:
                logger.info("【%s】包车预付或现金订单不重复发起渠道付款", tag)
                self._ios_back_to_home(tag)
            self.completed_order_no = self.driver_api.order_no
            logger.info(f"【{tag} 接口流程完成】订单 {self.driver_api.order_no} 已完成且已支付")
        else:
            if self.driver_ui.last_phase == "complete":
                logger.info("【%s】司机当前订单已支付，只返回首页并核验同订单，不重复付款", tag)
                self._ios_back_to_home(tag)
            elif self.CAR_TYPE == "meter" and self.PAYMENT != "cash":
                # 打表在线支付必须等到真实费用页，不能因推送稍慢跳过付款。
                self._ios_wait_current_payment(tag)
                self._ios_complete_payment(tag)
            else:
                logger.info("【%s】包车预付或现金订单不重复发起渠道付款，继续同订单到账核验", tag)
                self._ios_back_to_home(tag)

            # 真机顺序：乘客完成支付并回首页 → 切司机 → 返回首页 → 到账详情核验同单。
            try:
                self.driver_ui.wait_completed()
            except Exception:
                self.driver_ui.snapshot("payment_verification_failed")
                raise
            self.completed_order_no = self.driver_ui.order_no
            mode = "已有订单续跑完成" if self.resuming_order else "全 UI 流程完成"
            logger.info(f"【{tag} {mode}】订单 {self.driver_ui.order_no} 已完成且已支付")

    # ==================== UI 下单辅助方法 ====================

    def _ios_wait_current_payment(self, tag):
        """等待真实乘客费用页，不判断金额是多少。

        打表后付（线上支付：alipay hk 和银行卡）不需判断金额是多少，
        只需等待带"確認支付"的页面出现后继续，不校验金额与司机账单是否一致。
        """
        timeout = (self.order_settings.get("order_validation") or {}).get("completion_timeout", 90)
        deadline = time.monotonic() + timeout
        monitor = self._ios_ensure_monitor()
        while time.monotonic() < deadline:
            try:
                page = monitor.inspect(timeout=max(0.1, deadline - time.monotonic()))
            except Exception:
                monitor.capture("current_payment_page_read_failed")
                raise
            if page.root.get("bundleId") != E.PASSENGER_BUNDLE_ID:
                monitor.capture("current_payment_not_foreground")
                raise RuntimeError(f"{tag}: 费用页核验时乘客App不在前台，未发起付款")
            texts = page.texts
            failures = tuple(kw for kw in ("支付失敗", "支付失败", "訂單已取消", "订单已取消")
                             if any(kw in text for text in texts))
            if failures:
                driver_order = getattr(getattr(self, "driver_ui", None), "order_no", None) or "未取得"
                target = monitor.capture("current_payment_failed_or_cancelled")
                logger.error("【%s】费用页命中=%s；司机订单=%s；现场=%s；未发起渠道付款",
                             tag, failures, driver_order, target)
                raise RuntimeError(
                    f"{tag}: 乘客订单支付失败或取消，命中={failures}；司机订单={driver_order}；"
                    "停止操作，未发起渠道付款，请核对现场及两端订单")
            for text in texts:
                if re.search(r"(?:確認支付|确认支付)", text):
                    self._ios_screenshot("epayment_current_before_payment.png")
                    logger.info("【%s】已检测到确认支付页，不判断金额，继续支付", tag)
                    return
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        monitor.capture("current_payment_page_timeout")
        raise TimeoutError(f"{tag}: 未等到确认支付页面，不跳过支付")

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
        点击"確認支付並呼叫"后先调用submitted阶段的公共渠道支付，再等待下单结果。
        银行卡保留表单未出现的兼容行为；Alipay需确认SUCCESS并返回App，均不提前回首页。
        下单成功不等于司机行程已完成或同订单最终到账。

        :param tag: 日志标签。
        :return: True 表示下单成功，False 表示下单失败。
        """
        for attempt in range(E.ESTIMATE_CALL_MAX_ATTEMPTS):
            logger.info("【%s 步骤 7】确认呼叫（%s/%s），等待预付页面", tag, attempt + 1, E.ESTIMATE_CALL_MAX_ATTEMPTS)
            if attempt == 0:
                self._ios_click_confirm_call(tag)
            else:
                self._ios_click_refreshed_estimate_call(tag, self.CAR_TYPE)
            time.sleep(3)
            page_texts = self._ios_get_all_texts(self.client)
            if any(kw in text for text in page_texts for kw in E.CASHIER_PAGE_KEYWORDS):
                break
            if any(kw in text for text in page_texts for kw in E.ESTIMATE_UPDATED_KEYWORDS):
                result = "estimate_updated"
            else:
                result = self._ios_wait_order_result(tag, max_checks=15)
            if result == "success":
                return True
            if result == "cashier":
                break
            # 检测到"未完成訂單"弹窗 → 处理遗留订单后重试呼叫
            if result == "ongoing_order":
                logger.warning(f"【{tag}】检测到'未完成訂單'弹窗，处理遗留订单...")
                self._ios_handle_unfinished_order_popup(tag)
                if attempt + 1 < E.ESTIMATE_CALL_MAX_ATTEMPTS:
                    # 回首页重新配置起终点、选车型
                    self.client.home()
                    time.sleep(1)
                    self.client.session(E.PASSENGER_BUNDLE_ID)
                    time.sleep(2)
                    self._ios_re_setup_from_current_page(
                        tag, E.DEFAULT_START_ADDRESS, E.DEFAULT_END_ADDRESS)
                    continue
                logger.error("【%s】'未完成訂單'处理后呼叫已达%d次上限，未重复支付", tag, E.ESTIMATE_CALL_MAX_ATTEMPTS)
                return False
            if result != "estimate_updated":
                logger.warning("【%s】未进入预付页面，下单结果：%s；不盲目重试呼叫", tag, result)
                return False
            if attempt + 1 >= E.ESTIMATE_CALL_MAX_ATTEMPTS:
                self._ios_screenshot("JRYG_ios_estimate_retry_exhausted.png")
                logger.error("【%s】预估重复更新，呼叫已达3次上限，未重复支付", tag)
                return False
            state = self._ios_reselect_refreshed_estimate(tag, self.CAR_TYPE)
            if state == "success":
                return True
            if state == "cashier":
                break

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

        # 确认支付后仍出现"未完成訂單"弹窗 → 处理后返回失败，由上层决定是否重试
        if result == "ongoing_order":
            logger.warning(f"【{tag}】确认支付后仍检测到'未完成訂單'弹窗，处理遗留订单...")
            self._ios_handle_unfinished_order_popup(tag)
            return False

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
        max_retry = E.ESTIMATE_CALL_MAX_ATTEMPTS
        # 备选终点列表（距离太近时依次切换）
        fallback_ends = list(E.FALLBACK_END_ADDRESSES)
        fallback_idx = 0  # 当前使用的备选终点索引
        current_end = E.DEFAULT_END_ADDRESS
        refreshed_estimate = False

        for attempt in range(max_retry):
            attempt_label = "首次" if attempt == 0 else f"重试({attempt})"
            logger.info(f"【{tag} 步骤 8】{attempt_label}点击确认呼叫（终点={current_end}）...")
            if refreshed_estimate:
                self._ios_click_refreshed_estimate_call(tag, self.CAR_TYPE)
                refreshed_estimate = False
            else:
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
                    logger.error(f"【{tag}】UI 登录失败，停止，不重复呼叫或发送验证码")
                    return False

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
                if result == "estimate_updated":
                    if attempt + 1 >= max_retry:
                        self._ios_screenshot("JRYG_ios_estimate_retry_exhausted.png")
                        logger.error("【%s】预估重复更新，已达呼叫上限，不切换终点或重复支付", tag)
                        return False
                    state = self._ios_reselect_refreshed_estimate(tag, self.CAR_TYPE)
                    if state == "success":
                        return True
                    if state != "ready":
                        return False
                    self._ios_select_payment(tag, payment=self.PAYMENT)
                    refreshed_estimate = True
                    continue
                if result == "cashier":
                    logger.error("【%s】打表下单意外进入收银台，停止，不重新呼叫", tag)
                    return False

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
                    if not self._ios_ui_login(tag=tag):
                        return False
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
        self._guard_existing_order_retry()
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
        start_addr = self._ios_start_address(start_addr)
        monitor = self._ios_ensure_monitor()
        state = monitor.inspect().state
        logger.info(f"【{tag}】登录后当前页面状态: {state}，不重启 App，直接配置起终点")

        if state == "activity_popup":
            monitor.dismiss_activity_popup(self.client)
            time.sleep(1)
            state = monitor.inspect().state

        if state == "privacy_agreement":
            monitor.click_text(self.client, "同意")
            time.sleep(1)
            state = monitor.inspect().state

        if state in ("home_unlogged", "home_logged"):
            search_entry = self.poco(textMatches=".*想去哪.*|.*您從哪裡出發.*|.*搜索.*")
            if search_entry.exists():
                search_entry.click()
                time.sleep(1)
            else:
                self.client.click(196, 120)
                time.sleep(1)

        self._ios_configure_addresses(tag, start_addr, end_addr)
        time.sleep(1)

        self._ios_select_car_type(tag, car_type=self.CAR_TYPE)
        self._ios_select_payment(tag, payment=self.PAYMENT)

    def _guard_existing_order_retry(self):
        """发现遗留订单后关闭整例重试；重试轮不自动取消或支付已有订单。"""
        self.retry_safe = False
        if getattr(self, "batch_retry", False):
            raise RuntimeError("重试检测到遗留订单，停止当前用例，不自动取消、接续或重复付款")

    def _ui_cleanup_ongoing_order(self, tag):
        """UI 方式取消遗留的进行中订单，并在需要时执行 UI 登录。

        拉起 App 后依次处理：
        1. 系统弹窗 + 隐私协议 + 引导页 + 广告弹窗
        2. 情况 1：在等待接单页 → 点击取消訂單 → 确认取消 → 回首页
        3. 情况 1b：检测到"未完成訂單"弹窗 → 去完成/取消/关闭
        4. 情况 2：检测到登录页 → 执行 UI 登录
        """
        # 共用启动遮挡清理，遗留订单取消和登录判断仍留在本编排中。
        if getattr(self, "batch_retry", False):
            logger.info("【%s】失败重试：WDA已就绪，重新打开乘客App后执行当前用例", tag)
        self._ios_prepare_passenger_app(tag, launch_wait=8, alert_wait=1)
        if not self._ios_ensure_logged_in(tag=tag):
            raise RuntimeError("乘客自动登录失败，停止遗留订单处理和下单")

        page_texts = self._ios_get_all_texts(self.client)
        logger.info(f"【{tag}】预清理: 当前页面文本: {page_texts[:200]}")
        if any(text.strip() in ("確認支付", "确认支付", "費用明細", "费用明细", "行程結束", "行程结束")
               for text in page_texts):
            self._guard_existing_order_retry()

        # 情况 1：等待接单页 → 取消订单
        if any("取消訂單" in t for t in page_texts):
            self._guard_existing_order_retry()
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

            time.sleep(2)
            self._ios_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_00_cleanup.png")
            logger.info(f"【{tag}】预清理: 订单取消完成")

            # 取消后关闭可能连续弹出的确认弹窗
            self._ios_dismiss_dialogs(
                ["確定", "确定", "好", "OK", "我知道了"], tag=tag, max_rounds=3, wait_after=1)

            # 强制回首页
            self.client.home()
            time.sleep(1)
            self.client.session(E.PASSENGER_BUNDLE_ID)
            time.sleep(1)

            # 验证已返回首页
            for back_wait in range(10):
                page_texts = self._ios_get_all_texts(self.client)
                if any(kw in t for t in page_texts for kw in ["想去哪裡", "想去哪里", "主頁"]):
                    logger.info(f"【{tag}】预清理: 取消后已返回首页 ({back_wait*0.5+0.5:.0f}s)")
                    break
                # 再尝试关闭弹窗
                self._ios_click_dialog_button(
                    ["確定", "确定", "好", "OK"], tag=tag, wait_after=0.5)
                time.sleep(0.5)
        else:
            logger.info(f"【{tag}】预清理: 不在等待接单页")

        # 情况 1b：检测"未完成訂單"提示弹窗 → 点"去完成"处理遗留订单
        page_texts = self._ios_get_all_texts(self.client)
        if any(("未完成" in t and "訂單" in t) or ("未完成" in t and "订单" in t)
               for t in page_texts):
            self._guard_existing_order_retry()
            logger.info(f"【{tag}】预清理: 检测到'未完成訂單'提示弹窗，调用统一处理")
            self._ios_handle_unfinished_order_popup(tag)
            time.sleep(2)

        logger.info("【%s】预清理完成，保持乘客App前台，继续起终点配置", tag)

    # ==================== 司机端接口辅助方法 ====================

    def _driver_api_go_online(self, tag):
        """接口模式阶段 0：登录→出车，不操作手机。

        先检查是否有未完成订单（servingOrder），有则续跑，无则出车听单。
        """
        from ui_framework.JRYG_driver_api import DriverAPI
        self.driver_api = DriverAPI()
        self.driver_api.login()

        # 检查是否有未完成订单
        self.resuming_order = False
        try:
            serving = self.driver_api.get_serving_order()
            order_data = (serving.get("data") or {})
            existing_no = order_data.get("orderNo") or order_data.get("order_no")
            if existing_no:
                self.driver_api.order_no = existing_no
                self.resuming_order = True
                logger.info("【%s】接口检测到未完成订单：%s；跳过乘客清理和重复下单", tag, existing_no)
                return
        except RuntimeError:
            logger.info("【%s】接口查询当前订单无返回，继续出车听单", tag)

        self.driver_api.go_online()
        logger.info(f"【{tag}】司机接口已出车（听单），继续乘客下单")

    def _driver_api_grab_and_flow(self, tag, stop_after="submitted"):
        """接口模式阶段 3：接单→流转→确认账单，不操作手机。

        乘客下单成功后，通过接口完成司机端全部订单流转。
        stop_after="accepted" 时只接单不流转，不提交账单。

        状态流转节奏：
        - 非行程中状态（出发/到达上车点/到达目的地/确认账单）：间隔 3 秒
        - 行程中状态（接载乘客）后：等待 30 秒再执行到达目的地

        每个状态流转后切换到乘客端，核验订单详情页状态是否符合预期。
        """
        settings = self.order_settings.get("driver") or {}
        limits = self.order_settings.get("order_validation") or {}

        # 续跑已有订单时不再重新接单
        if not self.resuming_order:
            # 等待派单
            max_wait = limits.get("dispatch_timeout", 90)
            order_no = self.driver_api.wait_for_dispatch(max_wait=max_wait)

            # 接单
            self.driver_api.accept_order(order_no)
        else:
            order_no = self.driver_api.order_no
            logger.info("【%s】接口续跑已有订单：%s，跳过接单", tag, order_no)

        if stop_after == "accepted":
            logger.info(f"【{tag}】接口 stop_after=accepted，已接单不推进流转")
            return

        # 乘客端保持在订单详情页，司机端每个状态流转后核验页面
        flow_interval = self.driver_api.FLOW_INTERVAL_NORMAL  # 3秒
        onboard_wait = self.driver_api.FLOW_INTERVAL_ONBOARD  # 30秒

        # === 出发接乘客 ===
        logger.info(f"【{tag}】司机出发接乘客...")
        self.driver_api.depart()
        time.sleep(flow_interval)
        self._ios_verify_passenger_order_page(tag, "出发接乘客", order_no)

        # === 到达上车点 ===
        logger.info(f"【{tag}】司机到达上车点...")
        self.driver_api.arrive_pickup()
        time.sleep(flow_interval)
        self._ios_verify_passenger_order_page(tag, "到达上车点", order_no)

        # === 接载乘客（行程中）===
        logger.info(f"【{tag}】司机接载乘客，行程开始...")
        self.driver_api.pickup_passenger()
        # 行程中状态后等待30秒，让乘客端展示行程过程
        logger.info(f"【{tag}】行程中，等待 {onboard_wait} 秒后继续到达目的地...")
        time.sleep(onboard_wait)
        self._ios_verify_passenger_order_page(tag, "行程中", order_no)

        # === 到达目的地 ===
        logger.info(f"【{tag}】司机到达目的地...")
        self.driver_api.arrive_destination()
        time.sleep(flow_interval)
        self._ios_verify_passenger_order_page(tag, "到达目的地", order_no)

        # === 确认账单 ===
        if self.CAR_TYPE == "meter":
            fare = str(os.environ.get("HK_ORDER_AMOUNT", settings.get("fare", "5")))
            surcharge = "0" if self.PAYMENT == "cash" else str(os.environ.get("HK_OTHER_AMOUNT", settings.get("surcharge", "0")))
            self.driver_api.confirm_bill(fare=fare, surcharge=surcharge)
        else:
            self.driver_api.confirm_bill()
        time.sleep(flow_interval)
        self._ios_verify_passenger_order_page(tag, "确认账单", order_no)

        logger.info(f"【{tag}】司机接口账单已提交，订单={order_no}")

    def _ios_verify_passenger_order_page(self, tag, phase, order_no):
        """切换到乘客端核验订单详情页状态是否符合预期。

        在司机接口流转的每个阶段后调用，检查乘客端页面是否正确反映了
        司机当前的服务状态，是否存在错误提示或异常页面。

        特殊场景处理：
        - 出现弹窗（系统弹窗/广告/活动弹窗）→ 自动关闭后重新核验
        - App 崩溃（前台不是乘客 App）→ 记录并重新拉起
        - 服务端错误提示 → 记录并标记

        :param tag: 用例标签
        :param phase: 当前流转阶段名称（如"出发接乘客"）
        :param order_no: 订单号
        """
        # 切换到乘客端
        try:
            self.client.app_activate(E.PASSENGER_BUNDLE_ID)
            time.sleep(2)  # 等待 App 切换和页面刷新
        except Exception as exc:
            logger.warning(f"【{tag}】切换乘客端失败（{phase}）: {exc}")
            return

        # === 崩溃检测：检查乘客 App 是否在前台 ===
        try:
            app_info = self.client.http.get("/wda/activeAppInfo", timeout=5).value
            current_bundle = app_info.get("bundleId") if isinstance(app_info, dict) else None
            if current_bundle != E.PASSENGER_BUNDLE_ID:
                logger.error(f"【{tag}】[{phase}] 乘客App不在前台（当前: {current_bundle}），"
                             f"可能已崩溃或被系统杀死，尝试重新拉起")
                self._ios_screenshot(
                    f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_{phase}_crash.png")
                # 记录崩溃事件
                self._record_app_crash(tag, phase, order_no,
                                       f"乘客App不在前台，当前bundle={current_bundle}")
                # 重新拉起 App
                try:
                    self.client.app_activate(E.PASSENGER_BUNDLE_ID)
                    time.sleep(3)
                except Exception:
                    logger.error(f"【{tag}】[{phase}] 重新拉起乘客App失败")
                    return
        except Exception:
            pass  # activeAppInfo 不可用时不阻断

        # === 弹窗检测与关闭 ===
        self._ios_dismiss_popups_during_flow(tag, phase)

        # 读取乘客端当前页面文本和状态
        page_texts = self._ios_get_all_texts(self.client)
        from ui_framework.JRYG_page_monitor import IOSPage
        try:
            source = self.client.source(format="xml")
            page = IOSPage(source)
            page_state = page.state
        except Exception:
            page_state = "unknown"

        logger.info(f"【{tag}】[{phase}] 乘客端页面状态: {page_state}")
        logger.info(f"【{tag}】[{phase}] 页面文本: {page_texts[:300]}")

        # 截图记录当前页面状态
        self._ios_screenshot(
            f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_{phase}.png")

        # 核验页面状态是否符合预期
        expected_states = (
            "order_active",      # 订单进行中（司机正在赶来/已到达/行程中）
            "order_complete",    # 行程结束
            "payment_failed",    # 支付失败（后付场景可能出现）
            "route_selected",    # 路线选择页（确认账单后可能短暂出现）
            "home_unlogged",     # 订单完成后回到首页
        )

        if page_state == "unknown":
            logger.warning(f"【{tag}】[{phase}] 乘客端页面状态未知，"
                          f"可能页面正在加载或存在异常，请检查截图")
        elif page_state == "order_cancelled":
            logger.error(f"【{tag}】[{phase}] 乘客端显示订单已取消！"
                         f"订单 {order_no} 可能在流转过程中被取消")
        elif page_state not in expected_states:
            logger.warning(f"【{tag}】[{phase}] 乘客端页面状态 {page_state} "
                          f"不在预期范围内 {expected_states}")

        # 检查页面文本中是否有错误提示关键词
        error_keywords = ["系統錯誤", "系统错误", "網絡異常", "网络异常",
                         "請重試", "请重试", "加載失敗", "加载失败",
                         "訂單不存在", "订单不存在", "無法獲取", "无法获取"]
        for text in page_texts:
            for kw in error_keywords:
                if kw in text:
                    logger.error(f"【{tag}】[{phase}] 乘客端页面检测到错误提示: "
                                 f"'{kw}' (完整文本: '{text}')")
                    break

    def _ios_dismiss_popups_during_flow(self, tag, phase):
        """在订单流转过程中检测并关闭弹窗。

        处理订单详情页可能出现的各种弹窗：
        - 系统权限弹窗（Alert）
        - 活动弹窗/广告弹窗
        - 网络异常提示弹窗
        - 其他非业务弹窗

        :param tag: 用例标签
        :param phase: 当前流转阶段名称
        """
        # 1. 系统权限弹窗
        try:
            self.client.alert.accept()
        except Exception:
            pass

        # 2. 隐私协议弹窗
        try:
            self._ios_dismiss_privacy_agreement()
        except Exception:
            pass

        # 3. 活动弹窗/广告弹窗（最多3轮）
        try:
            monitor = self._ios_ensure_monitor()
            for _ in range(3):
                page = monitor.inspect()
                if page.state != "activity_popup":
                    break
                logger.info(f"【{tag}】[{phase}] 检测到活动弹窗，尝试关闭...")
                monitor.dismiss_activity_popup(self.client)
                time.sleep(1)
        except Exception:
            pass

        # 4. 通用弹窗关闭（確定/好/OK/知道了/關閉/关闭 等）
        dismiss_keywords = ["確定", "确定", "好", "OK", "知道了", "我知道了",
                           "關閉", "关闭", "知道了", "明白了", "知道了"]
        try:
            self._ios_dismiss_dialogs(
                dismiss_keywords, tag=tag, max_rounds=2, wait_after=1)
        except Exception:
            pass

    def _record_app_crash(self, tag, phase, order_no, detail):
        """记录 App 崩溃事件到实例属性，供批次结果收集时使用。

        :param tag: 用例标签
        :param phase: 当前流转阶段名称
        :param order_no: 订单号
        :param detail: 崩溃详情描述
        """
        crashes = getattr(self, "_app_crashes", [])
        crashes.append({
            "tag": tag,
            "phase": phase,
            "order_no": order_no,
            "detail": detail,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        self._app_crashes = crashes
        # 标记为非安全重试（崩溃后不应整例重试，避免重复下单）
        self.retry_safe = False

    # ==================== 司机端 UI 辅助方法 ====================

    def _driver_ui_go_online(self, tag):
        """仅未完成订单续跑；启动前已完成订单退回听单后新下单，不能冒充本次结果。"""
        self.driver_runtime = self._resolve_driver_runtime()
        args = self._driver_parser().parse_args(["--wda-url", self.driver_runtime.wda_url, "--stop-after", "online"])
        self.driver_ui = self._create_driver_flow(args)
        self.resuming_order = self.driver_ui.ensure_online(resume_existing=not getattr(self, "batch_new_order_only", False))
        if self.resuming_order:
            logger.info("【%s】检测到已有订单，当前阶段：%s；跳过乘客清理和重复下单", tag,
                        PHASE_NAMES[self.driver_ui.last_phase])
        else:
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
                "--car-type", self.CAR_TYPE,
                "--surcharge", "0" if self.PAYMENT == "cash" else str(os.environ.get("HK_OTHER_AMOUNT", settings.get("surcharge", "0"))),
                "--payment", "cash" if self.PAYMENT == "cash" else "online"]
        if self.CAR_TYPE == "meter":
            # 打表：司机输入车费5元，附加费0元
            fare = "5" if self.PAYMENT == "cash" else str(os.environ.get("HK_ORDER_AMOUNT", settings.get("fare", "5")))
            args.extend(["--fare", fare])
        # 包车：不传 --fare，不输入金额，不校验金额
        tail = os.environ.get("HK_DRIVER_PASSENGER_TAIL") or settings.get("passenger_tail")
        if tail:
            if not str(tail).isdigit() or len(str(tail)) != 4:
                raise RuntimeError("请配置四位乘客测试尾号")
            args.extend(["--tail", str(tail)])
        if self.PAYMENT == "cash":
            args.append("--cash-collected")
            logger.info("【%s】现金测试用例：车费5 HKD、附加费0 HKD；回读核对后滑动确认收款，无需额外环境开关", tag)
        self.driver_ui.args = self._driver_parser().parse_args(args)
        try:
            self.driver_ui.run()
        except Exception:
            self.driver_ui.snapshot("failed_order_flow")
            raise
        expected = ("departure", "pickup") if stop_after == "accepted" else ("unpaid", "complete")
        assert self.driver_ui.last_phase in expected, f"{tag}: 司机 UI 未确认接单或账单提交成功"
        if self.driver_ui.last_phase == "unpaid":
            logger.info("【%s】司机已提交账单，订单=%s；保留未支付现场后交还乘客，不重提账单",
                        tag, self.driver_ui.order_no)
            self.driver_ui.snapshot("bill_submitted_unpaid_before_passenger_payment")
