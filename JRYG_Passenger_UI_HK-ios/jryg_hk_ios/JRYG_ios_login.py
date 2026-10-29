"""
JRYG 港版 iOS 自动化 —— 登录模块
==============================================================================
功能：
  智能登录乘客端。如果当前 App 已登录，则跳过登录直接返回。
  如果未登录，执行完整登录流程：进入个人中心 → 输入手机号 → 获取验证码 →
  输入验证码 → 确认登录成功。

设计原则：
  - 不退出已登录的账号，避免重复登录
  - 依赖 open_passenger_app() 先确保 App 已打开
==============================================================================
"""

import time

from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_ios_base import IOSBase


class IOSLogin(IOSBase):
    """iOS 登录操作模块"""

    def login_passenger(self):
        """
        登录乘客端（智能判断）
        - 如果已登录，直接返回 True
        - 如果未登录，执行完整登录流程
        - 返回: True 表示已登录就绪，False 表示登录失败
        """
        logger.info("=" * 60)
        logger.info("【阶段】乘客端登录")
        logger.info("=" * 60)

        # 1. 先确保 App 在前台
        if not self._is_app_running(self.PASSENGER_BUNDLE):
            logger.info("  >> App 不在前台，先激活 App")
            self._activate_app(self.PASSENGER_BUNDLE, wait=3)

        # 2. 检查是否已登录
        if self._is_logged_in():
            logger.info(f"  >> 当前已登录（账号: {self.PHONE_NUMBER}），无需重复登录")
            self._capture("03_already_logged_in")
            # 此时 App 已在个人中心（_is_logged_in 内部跳转），不跳回首页
            # _verify_passenger_account 会核实账号后统一跳回首页
            return True

        logger.info("  >> 当前未登录，开始执行登录流程...")

        # 3. 状态机驱动登录流程
        deadline = time.monotonic() + 120
        for cycle in range(30):
            page = self.monitor.inspect()
            state = page.state
            logger.info(f"  [登录循环 {cycle}] 状态: {state}")
            # 超时直接失败，不允许盲点后续按钮
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
                self._wait_state("进入个人中心", ("mine_unlogged", "mine_logged", "login_phone_input"),
                                 timeout=20, recover=self._recover_blocking_popup)
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
                # 先清空再输入，避免残留旧号码
                tf.clear_text()
                self.client.send_keys(self.PHONE_NUMBER)
                time.sleep(0.5)
                if not self._click_text("取得驗證碼"):
                    self._click_text("获取验证码")
                self._wait_state("进入验证码页", ("login_code_input",), timeout=15,
                                 recover=self._recover_blocking_popup)
                continue

            # 验证码输入页
            if state == "login_code_input":
                tf = self.client(className="XCUIElementTypeTextField", index=0)
                assert tf.exists, "验证码输入框不存在"
                tf.click()
                self.client.send_keys(self.VERIFY_CODE)
                self._wait_state("登录成功", ("mine_logged", "home_unlogged", "activity_popup"),
                                 timeout=20, recover=self._recover_blocking_popup)
                continue

            # 已登录
            if state == "mine_logged":
                # 必须确认是目标测试账号
                assert self.monitor.last_page.matches_account(self.PHONE_NUMBER), "登录账号不匹配"
                logger.info(f"【登录成功】账号: {self.PHONE_NUMBER}")
                self._capture("04_login_success")
                # 此时已在个人中心，不跳回首页
                # _verify_passenger_account 会核实账号后统一跳回首页
                return True

            if state in ("route_selected", "order_complete", "order_active", "order_cancelled"):
                # 已存在订单页时，登录态通过个人中心核实
                if self._is_logged_in():
                    self._capture("04_already_logged_in")
                    return True
                continue

            time.sleep(2)

        # 最终检查：可能已登录但状态检测有延迟
        if self._is_logged_in():
            logger.info("  >> 登录流程结束后检测到已登录")
            return True

        logger.error("  >> 登录流程未在预期时间内完成")
        return False
