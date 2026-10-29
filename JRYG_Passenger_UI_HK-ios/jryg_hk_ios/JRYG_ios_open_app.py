"""
JRYG 港版 iOS 自动化 —— 打开 App 模块
==============================================================================
功能：
  智能打开乘客端 App。如果 App 已在前台运行，则跳过打开操作直接返回。
  如果 App 未打开，则拉起 App 并处理启动过程中的弹窗（隐私协议、权限请求等）。

设计原则：
  - 不关闭已打开的 App，避免重复操作
  - 可被登录模块和下单模块复用
==============================================================================
"""

import time

from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_ios_base import IOSBase


class IOSOpenApp(IOSBase):
    """iOS 打开 App 操作模块"""

    def open_passenger_app(self):
        """
        打开乘客端 App（智能判断）
        - 如果 App 已在前台，直接返回 True
        - 如果 App 不在前台，拉起 App 并处理启动弹窗
        - 返回: True 表示 App 已就绪，False 表示打开失败
        """
        logger.info("=" * 60)
        logger.info("【阶段】打开乘客端 App")
        logger.info("=" * 60)

        # 1. 检查 App 是否已在前台运行
        if self._is_app_running(self.PASSENGER_BUNDLE):
            logger.info("  >> 乘客端 App 已在前台运行，无需重新打开")
            self._capture("00_app_already_open")
            return True

        logger.info("  >> 乘客端 App 未在前台，正在拉起...")

        # 2. 拉起乘客端 App
        self._activate_app(self.PASSENGER_BUNDLE, wait=5)
        self._capture("01_passenger_launch")

        # 3. 处理启动过程中的弹窗（最多等待 60 秒）
        deadline = time.monotonic() + 60
        for cycle in range(20):
            page = self.monitor.inspect()
            state = page.state
            logger.info(f"  [启动循环 {cycle}] 状态: {state}")
            # 启动超时直接失败，避免带着未知状态继续下单
            assert time.monotonic() < deadline, f"App 启动流程超时，当前状态={state}"

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

            # 首页（无论是否登录）都表示 App 已成功打开
            if state in ("home_unlogged", "home_logged", "mine_logged", "mine_unlogged",
                         "route_selected", "order_complete", "order_active", "order_cancelled",
                         "login_phone_input", "login_code_input", "payment_failed"):
                logger.info(f"  >> App 启动成功，当前状态: {state}")
                self._capture("02_app_ready")
                # 关闭首页可能弹出的城市弹框/活动弹框
                self._dismiss_home_popups()
                return True

            time.sleep(2)

        # 超时检查：如果 App 在前台就认为成功
        if self._is_app_running(self.PASSENGER_BUNDLE):
            logger.info("  >> App 已在前台运行（状态检测超时但App已就绪）")
            return True

        logger.error("  >> App 打开失败，未在预期时间内进入可用状态")
        return False
