"""
港版 iOS 下单+司机端接口接单流转 —— 参数化基类
==============================================================================
所有车型+支付方式的组合用例继承本基类，只需设置类属性：
  CAR_TYPE  : 车型（"meter"=打錶的士 / "charter"=包車價的士）
  PAYMENT   : 支付方式（"cash" / "epayment" / "alipay" / "bankcard"）

流程：
  阶段 0（UI）  ：预清理 —— 取消遗留的进行中订单 / 处理未支付订单
  阶段 1（接口）：司机端 API 登录 → 出车上线 → Socket → 清理缓存
  阶段 2（UI）  ：拉起 App → 配置起终点 → 选择车型 → 选择支付方式
               → 确认呼叫 → 检测登录态 → 未登录则登录后重新下单 → 等待下单成功
  阶段 3（接口）：轮询订单获取 order_no → 接单 → 状态流转
               → 确认账单 → 确认收款 → 收车下线

注意：
  1. 不使用乘客端 API 登录查询 order_no（会互踢 App UI 登录态）。
  2. 先启动司机端（登录+出车+Socket），再 UI 下单，确保下单时司机已在线。
  3. 登录成功后不重启 App，避免杀死 App 导致已选路线丢失。
==============================================================================
"""

import os
import sys
import time

import pytest
import wda

# 添加 UI 框架根路径（本用例所在目录的上级 = JRYG_Passenger_UI_HK-ios）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 添加项目根路径（JRYG_PassengerIUi），用于导入 JRYG_Passenger_API_HK
PROJECT_ROOT = os.path.dirname(BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from jryg_hk_ios.JRYG_config import SETTINGS
from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_ios_ui_base import iOSBase
from jryg_hk_ios import JRYG_ios_ui_elements as E

# 导入 API 层客户端
from JRYG_Passenger_API_HK.cases.JRYG_test_hk_driver_api import (
    HKDriverApiClient, DRIVER_LATITUDE, DRIVER_LONGITUDE,
)
from JRYG_Passenger_API_HK.common.jryg_socket_client import JRYGSocketClient
from JRYG_Passenger_API_HK.common.redis_cache_cleaner import clean_driver_cache
from JRYG_Passenger_API_HK.common.hk_config import config as api_config


# ==================== 车型/支付方式映射 ====================
CAR_TYPE_LABELS = {
    "meter": "打錶的士",
    "charter": "包車價的士",
}

PAYMENT_LABELS = {
    "cash": "現金",
    "epayment": "電子支付",
    "alipay": "Alipay HK",
    "bankcard": "信用卡/扣帳卡",
}


class TestOrderBase(iOSBase):
    """参数化下单+司机端接口接单流转基类。

    子类只需设置类属性 CAR_TYPE 和 PAYMENT，无需重写任何方法。
    本基类不直接执行（__test__ = False），由子类继承后设置参数。
    """

    __test__ = False  # pytest 不收集基类本身

    # ==================== 子类必须覆盖的类属性 ====================
    CAR_TYPE = ""   # "meter" 或 "charter"
    PAYMENT = ""    # "cash" / "epayment" / "alipay" / "bankcard"

    @classmethod
    def setup_class(cls):
        """类级 setup：创建司机端 API 客户端与 Socket 客户端。"""
        super().setup_class()
        cls.driver_api = HKDriverApiClient()
        cls.socket_client = None

    @classmethod
    def teardown_class(cls):
        """类级 teardown：断开 Socket、收车下线。"""
        if cls.socket_client:
            try:
                cls.socket_client.disconnect()
            except Exception:
                pass
            cls.socket_client = None
        if cls.driver_api and cls.driver_api.access_token:
            try:
                cls.driver_api.handle_work_status(
                    handle_status=0, trace_id=f"d_offline_teardown_{int(time.time())}")
                logger.info("【teardown】司机端收车下线")
            except Exception as e:
                logger.warning(f"【teardown】收车失败: {e}")
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
        # 阶段 1：司机端 API 登录 → 出车 → Socket
        # ============================================================
        logger.info("=" * 60)
        logger.info("【阶段 1】司机端：登录→出车→Socket")
        logger.info("=" * 60)

        self._driver_api_login_and_go_online(tag)
        self._driver_api_start_socket(tag)
        self._driver_api_clean_cache(tag)

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

        logger.info(f"【{tag} 步骤 7】选择{pay_label}支付方式...")
        self._ios_select_payment(tag, payment=self.PAYMENT)

        ordered = self._click_call_and_check_login_then_retry(tag)

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
        logger.info(f"【{tag} 全流程完成】订单号: {order_no}")
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

    # ==================== UI 下单辅助方法 ====================

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
        go_poco = self.poco(textMatches=".*去完成.*|.*去處理.*")
        if go_poco.exists():
            go_poco.click()
            go_clicked = True
            time.sleep(2)

        if not go_clicked:
            go_wda = self.client(textContains="去完成")
            if go_wda.exists:
                go_wda.click()
                go_clicked = True
                time.sleep(2)

        if not go_clicked:
            self.client.click(259, 482)
            go_clicked = True
            time.sleep(2)

        if not go_clicked:
            later_btn = self.poco(textMatches=".*稍後.*|.*稍后.*")
            if later_btn.exists():
                later_btn.click()
                time.sleep(2)
            else:
                try:
                    self.client(textContains="稍後").click()
                except Exception:
                    pass
                time.sleep(2)
            return

        time.sleep(3)
        texts = self._ios_get_all_texts(self.client)
        logger.info(f"【{tag}】点击'去完成'后页面文本: {texts[:200]}")

        # 情况 A：等待接单页 → 取消订单
        if any("取消訂單" in t for t in texts):
            logger.info(f"【{tag}】跳转到进行中订单页，取消订单...")
            cancel_el = self.poco(text="取消訂單")
            if cancel_el.exists():
                cancel_el.click()
                time.sleep(3)
            else:
                cancel_wda = self.client(text="取消訂單")
                if cancel_wda.exists:
                    cancel_wda.click()
                    time.sleep(3)

            confirm_texts = self._ios_get_all_texts(self.client)
            for confirm_kw in ["確認取消", "确认取消", "確定", "确定"]:
                if any(confirm_kw in t for t in confirm_texts):
                    btn = self.poco(textMatches=f".*{confirm_kw}.*")
                    if btn.exists():
                        btn.click()
                        time.sleep(3)
                        break
                    btn_wda = self.client(textContains=confirm_kw)
                    if btn_wda.exists:
                        btn_wda.click()
                        time.sleep(3)
                        break
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

        流程：
        1. 点击"確認支付"按钮 → 跳转 Safari Alipay HK 支付页面
        2. 关闭"Safari浏览器打不开该网页"弹窗
        3. 点击 simulation-wallet 中的"Pay Now"
        4. 等待支付成功（SUCCESS）
        5. 点击 Return to Merchant → 处理"打开"弹窗 → 返回 App
        6. 从评价页返回首页
        """
        # 步骤 1：点击确认支付
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

        # 步骤 2：关闭 Safari 弹窗
        logger.info(f"【{tag}】支付步骤 2：关闭 Safari 弹窗...")
        texts = self._ios_get_all_texts(self.client)
        if any("打不开" in t or "网址无效" in t for t in texts):
            ok_btn = self.client(text="好")
            if ok_btn.exists:
                ok_btn.click()
            else:
                self.client.click(338, 392)
            time.sleep(3)

        # 步骤 3：点击 Pay Now
        logger.info(f"【{tag}】支付步骤 3：点击 Pay Now...")
        pay_now = self.client(text="Pay Now")
        if pay_now.exists:
            pay_now.click()
        else:
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
            time.sleep(2)

        if not pay_success:
            logger.warning(f"【{tag}】支付未确认成功，尝试继续...")
        else:
            # 步骤 5：返回 App
            logger.info(f"【{tag}】支付步骤 5：返回 App...")
            time.sleep(2)
            return_btn = self.client(textContains="Return to Merchant")
            if return_btn.exists:
                return_btn.click()
                time.sleep(3)

            texts = self._ios_get_all_texts(self.client)
            if any("打開" in t or "打开" in t for t in texts):
                open_btn = self.client(text="打開")
                if not open_btn.exists:
                    open_btn = self.client(text="打开")
                if open_btn.exists:
                    open_btn.click()
                    time.sleep(5)

        # 步骤 6：从评价/行程结束页返回首页
        logger.info(f"【{tag}】支付步骤 6：返回首页...")
        self._ios_back_to_home(tag)

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
        """UI 方式取消遗留的进行中订单，并在需要时执行 UI 登录。"""
        self.client.home()
        time.sleep(2)
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
            cancel_el = self.poco(text="取消訂單")
            if cancel_el.exists():
                cancel_el.click()
                time.sleep(3)
            else:
                cancel_wda = self.client(text="取消訂單")
                if cancel_wda.exists:
                    cancel_wda.click()
                    time.sleep(3)

            confirm_texts = self._ios_get_all_texts(self.client)
            for confirm_kw in ["確認取消", "确认取消", "確定", "确定"]:
                if any(confirm_kw in t for t in confirm_texts):
                    btn = self.poco(textMatches=f".*{confirm_kw}.*")
                    if btn.exists():
                        btn.click()
                        time.sleep(3)
                        break
                    btn_wda = self.client(textContains=confirm_kw)
                    if btn_wda.exists:
                        btn_wda.click()
                        time.sleep(3)
                        break

            time.sleep(3)
            self._ios_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_00_cleanup.png")
            logger.info(f"【{tag}】预清理: 订单取消完成")
        else:
            logger.info(f"【{tag}】预清理: 不在等待接单页")

        # 情况 1b：检测"未完成訂單"提示弹窗
        page_texts = self._ios_get_all_texts(self.client)
        if any(("未完成" in t and "訂單" in t) or ("未完成" in t and "订单" in t)
               for t in page_texts):
            logger.info(f"【{tag}】预清理: 检测到'未完成訂單'提示弹窗")
            go_btn = self.poco(textMatches=".*去完成.*|.*去處理.*")
            if go_btn.exists():
                go_btn.click()
                time.sleep(5)
                texts2 = self._ios_get_all_texts(self.client)
                if any("取消訂單" in t for t in texts2):
                    logger.info(f"【{tag}】预清理: 跳转到进行中订单页，取消订单...")
                    cancel_el = self.poco(text="取消訂單")
                    if cancel_el.exists():
                        cancel_el.click()
                        time.sleep(3)
                    for confirm_kw in ["確認取消", "确认取消", "確定", "确定"]:
                        btn = self.poco(textMatches=f".*{confirm_kw}.*")
                        if btn.exists():
                            btn.click()
                            time.sleep(3)
                            break
                time.sleep(3)
            else:
                later_btn = self.poco(textMatches=".*稍後.*|.*稍后.*|.*關閉.*|.*关闭.*")
                if later_btn.exists():
                    later_btn.click()
                    time.sleep(2)

        # 情况 2：检测登录页
        self._ios_ensure_logged_in(tag=tag)

        self.client.home()
        time.sleep(2)

    # ==================== 司机端 API 辅助方法 ====================

    def _driver_api_login_and_go_online(self, tag):
        """司机端 API 登录并出车上线（含重试机制）。"""
        max_retry = 3
        for attempt in range(max_retry):
            try:
                self.driver_api.login_scene_check(trace_id=f"d_check_{int(time.time())}")
                time.sleep(0.3)

                self.driver_api.send_auth_code(trace_id=f"d_sms_{int(time.time())}")
                time.sleep(0.5)

                status, resp = self.driver_api.login(trace_id=f"d_login_{int(time.time())}")
                assert status == 200, f"司机端 API 登录 HTTP 状态码预期 200，实际 {status}"
                assert resp.get("code") == 10000, f"司机端 API 登录失败: {resp}"
                self.driver_api.access_token = resp["data"]["sign_info"]["access_token"]
                logger.info(f"【{tag}】司机端 API 登录成功 (尝试 {attempt+1}/{max_retry})")

                s0, r0 = self.driver_api.get_out_car_status(
                    trace_id=f"d_status_{int(time.time())}")
                is_online = r0.get("data", {}).get("is_online", 0) if r0.get("code") == 10000 else 0
                if is_online == 1:
                    logger.info(f"【{tag}】司机端已在线，无需出车")
                else:
                    s, resp = self.driver_api.handle_work_status(
                        handle_status=1, trace_id=f"d_online_{int(time.time())}")
                    assert resp.get("code") == 10000, f"司机端出车失败: {resp}"
                    logger.info(f"【{tag}】司机端出车上线成功")
                return  # 登录+出车成功，退出重试循环

            except AssertionError:
                raise  # 断言失败直接抛出
            except Exception as e:
                logger.warning(f"【{tag}】司机端登录异常(尝试 {attempt+1}/{max_retry}): {e}")
                if attempt >= max_retry - 1:
                    raise AssertionError(f"司机端 API 登录重试 {max_retry} 次仍失败: {e}")
                time.sleep(3)

    def _driver_api_start_socket(self, tag):
        """启动 Socket 长连接（心跳 + 位置上报）。"""
        self.socket_client = JRYGSocketClient(
            self.driver_api.access_token, lat=DRIVER_LATITUDE, lng=DRIVER_LONGITUDE)
        connected = self.socket_client.connect()
        assert connected, "Socket 长连接建立失败，无法接收订单派发"
        logger.info(f"【{tag}】Socket 长连接已建立，等待位置上报稳定...")
        time.sleep(api_config.SOCKET_STABILIZE_WAIT)

    def _driver_api_clean_cache(self, tag):
        """清理 Redis 司机派单缓存。"""
        try:
            deleted = clean_driver_cache()
            logger.info(f"【{tag}】Redis 司机缓存清理完成，删除 {deleted} 个 key")
        except Exception as e:
            logger.warning(f"【{tag}】Redis 缓存清理失败: {e}（继续测试）")

    def _driver_api_polling_order(self, tag):
        """通过司机端 polling 接口轮询获取派发给当前司机的订单号。"""
        POLLING_TIMEOUT = api_config.POLLING_TIMEOUT
        POLLING_INTERVAL = api_config.POLLING_INTERVAL
        deadline = time.monotonic() + POLLING_TIMEOUT
        last_code = None

        logger.info(f"【{tag}】开始轮询订单（超时 {POLLING_TIMEOUT}s）...")
        while time.monotonic() < deadline:
            s, resp = self.driver_api.polling_order(
                trace_id=f"d_poll_{int(time.time())}")
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
                        if order_list:
                            order_no = order_list[0].get("order_no")
                    if not order_no and code != last_code:
                        logger.info(f"【{tag}】code=10000 但无 order_no, data keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}, data={str(data)[:300]}")
                if order_no:
                    logger.info(f"【{tag}】轮询获取到订单号: {order_no}")
                    return order_no

            time.sleep(POLLING_INTERVAL)

        raise AssertionError(
            f"轮询订单超时（{POLLING_TIMEOUT}s），未获取到派发订单。"
            f"最后返回 code={last_code}")

    def _driver_api_grab_and_flow(self, tag, order_no):
        """司机端接口：接单 → 状态流转 → 结束行程 → 确认账单 → 确认收款。"""
        STATUS_WAIT = api_config.STATUS_WAIT
        MOVE_STEPS = api_config.MOVE_STEPS
        MOVE_INTERVAL = api_config.MOVE_INTERVAL

        # ---- 接单 ----
        logger.info(f"【{tag}】司机端接单: {order_no}")
        s, resp = self.driver_api.grab_order(
            order_no, trace_id=f"d_grab_{int(time.time())}")
        code = resp.get("code")
        if code == 10000:
            logger.info(f"【{tag}】接单成功")
        elif code == 10011:
            logger.info(f"【{tag}】订单已被自己接走，继续")
        elif code == 23000:
            logger.info(f"【{tag}】指派模式: 订单已派发，grab 不可用，跳过")
        else:
            logger.warning(f"【{tag}】接单返回 code={code}: {resp.get('message')}")
        time.sleep(STATUS_WAIT + 3)

        # ---- 状态 1: 已出发 ----
        s, resp = self.driver_api.service_change(
            order_no, service_status=1,
            latitude=DRIVER_LATITUDE, longitude=DRIVER_LONGITUDE,
            trace_id=f"d_sc1_{int(time.time())}")
        logger.info(f"【{tag}】状态变更 1(已出发): code={resp.get('code')}")
        time.sleep(STATUS_WAIT)

        # ---- 状态 2: 到达上车地点 ----
        s, resp = self.driver_api.service_change(
            order_no, service_status=2,
            latitude=DRIVER_LATITUDE, longitude=DRIVER_LONGITUDE,
            trace_id=f"d_sc2_{int(time.time())}")
        logger.info(f"【{tag}】状态变更 2(到达): code={resp.get('code')}")
        time.sleep(STATUS_WAIT)

        # ---- 状态 3: 开始行程 ----
        s, resp = self.driver_api.service_change(
            order_no, service_status=3,
            latitude=DRIVER_LATITUDE, longitude=DRIVER_LONGITUDE,
            trace_id=f"d_sc3_{int(time.time())}")
        logger.info(f"【{tag}】状态变更 3(开始行程): code={resp.get('code')}")
        time.sleep(STATUS_WAIT)

        # ---- 模拟行驶到终点 ----
        begin_lat = float(DRIVER_LATITUDE)
        begin_lng = float(DRIVER_LONGITUDE)
        end_lat = begin_lat + 0.01
        end_lng = begin_lng + 0.01
        logger.info(f"【{tag}】模拟行驶: ({begin_lat},{begin_lng}) → ({end_lat},{end_lng})")
        for i in range(MOVE_STEPS + 1):
            t = i / MOVE_STEPS
            if self.socket_client:
                self.socket_client.lat = begin_lat + (end_lat - begin_lat) * t
                self.socket_client.lng = begin_lng + (end_lng - begin_lng) * t
            time.sleep(MOVE_INTERVAL)
        logger.info(f"【{tag}】已到达终点附近")

        # ---- 状态 4: 结束行程 ----
        time.sleep(3)
        s, resp = self.driver_api.service_change(
            order_no, service_status=4,
            latitude=end_lat, longitude=end_lng,
            trace_id=f"d_sc4_{int(time.time())}")
        code = resp.get("code")
        logger.info(f"【{tag}】状态变更 4(结束行程): code={code}, "
                    f"msg={resp.get('message')}")
        if code != 10000:
            if code == 20156:
                logger.info(f"【{tag}】服务端要求继续行驶，再移动 10 步...")
                for i in range(10):
                    if self.socket_client:
                        self.socket_client.lat = end_lat
                        self.socket_client.lng = end_lng
                    time.sleep(MOVE_INTERVAL)
                s, resp = self.driver_api.service_change(
                    order_no, service_status=4,
                    latitude=end_lat, longitude=end_lng,
                    trace_id=f"d_sc4_retry_{int(time.time())}")
                logger.info(f"【{tag}】结束行程(重试): code={resp.get('code')}")
            else:
                time.sleep(3)
                s, resp = self.driver_api.service_change(
                    order_no, service_status=4,
                    latitude=end_lat, longitude=end_lng,
                    trace_id=f"d_sc4_retry2_{int(time.time())}")
                logger.info(f"【{tag}】结束行程(重试2): code={resp.get('code')}")
        time.sleep(STATUS_WAIT)

        # ---- 确认账单/填写金额 ----
        s, resp = self.driver_api.confirm_bill(
            order_no, order_amount=api_config.ORDER_AMOUNT,
            other_amount=api_config.OTHER_AMOUNT,
            trace_id=f"d_bill_{int(time.time())}")
        assert resp.get("code") == 10000, f"确认账单失败: {resp}"
        logger.info(f"【{tag}】确认账单成功，金额={api_config.ORDER_AMOUNT}")
        time.sleep(STATUS_WAIT)

        # ---- 状态 5: 确认收款 ----
        s, resp = self.driver_api.service_change(
            order_no, service_status=5,
            latitude=end_lat, longitude=end_lng,
            trace_id=f"d_sc5_{int(time.time())}")
        logger.info(f"【{tag}】状态变更 5(确认收款): code={resp.get('code')}")
        time.sleep(STATUS_WAIT)

        # ---- 查询行程详情确认完成 ----
        s, resp = self.driver_api.get_trip_detail(
            order_no, trace_id=f"d_trip_{int(time.time())}")
        if resp.get("code") == 10000:
            order = resp.get("data", {}).get("order", {})
            fee = resp.get("data", {}).get("fee", {})
            logger.info(f"【{tag}】行程详情: "
                        f"order_status_name={order.get('order_status_name')}, "
                        f"pay_status_name={order.get('pay_status_name')}")
            if fee:
                logger.info(f"【{tag}】订单费用: {fee.get('order_fee')} {fee.get('unit')}")
