"""
JRYG 港版 iOS 自动化 —— 基础模块
==============================================================================
提供 WDA 连接、页面监控、通用工具方法，供打开App/登录/下单各模块复用。
==============================================================================
"""

import os
import time

import wda

from jryg_hk_ios.JRYG_logger import logger
from jryg_hk_ios.JRYG_config import SETTINGS, REPORT_DIR
from jryg_hk_ios.JRYG_page_monitor import IOSPageMonitor
from jryg_hk_ios.JRYG_verified_order_flow import VerifiedOrderFlow


class IOSBase(VerifiedOrderFlow):
    """iOS 自动化基础类，封装 WDA 连接与通用操作工具"""

    # ---- 测试常量 ----
    PASSENGER_BUNDLE = "com.sunlightmobility.client"  # 乘客端 App 包名
    DRIVER_BUNDLE = "com.sunlightmobility.driver"      # 司机端 App 包名
    WDA_URL = SETTINGS.get("device", {}).get("wda_url", "http://127.0.0.1:8100")  # WDA 地址
    PHONE_NUMBER = "11001727"   # 测试账号手机号
    VERIFY_CODE = "123456"      # 测试验证码
    START_ADDRESS = "北角地鐵站"  # 起点地址（需在首页起点输入框输入并确认）
    DEST_ADDRESS = "香港大學"    # 终点地址（在“想去哪裡？”输入框输入）
    FARE_AMOUNT = "5"           # 测试车费金额，用于确认收款

    @classmethod
    def init_wda(cls, output_subdir="e2e_flow"):
        """初始化 WDA 客户端和页面监控器。

        返回 True 表示连接成功，False 表示连接失败（由调用方决定是否继续）。
        """
        # 卡点文件输出子目录
        cls.output_dir = os.path.join(REPORT_DIR, output_subdir)
        os.makedirs(cls.output_dir, exist_ok=True)

        logger.info(f"【iOS】正在连接 WDA: {cls.WDA_URL}")
        # 放宽 WDA 请求超时，避免慢响应被误判为失败
        wda.HTTP_TIMEOUT = 20
        try:
            cls.client = wda.Client(cls.WDA_URL)
            # 主动探活，确认通道真的可用
            cls.client.status()
            logger.info("【iOS】WDA 连接成功")
        except Exception as e:
            logger.error(f"【iOS】WDA 连接失败: {e}")
            return False

        cls.monitor = IOSPageMonitor(cls.WDA_URL, cls.output_dir)
        return True

    @classmethod
    def cleanup_wda(cls):
        """释放 WDA 资源"""
        if hasattr(cls, "monitor") and cls.monitor:
            cls.monitor.close()
        logger.info("【iOS】资源已释放")

    # ---- 通用工具方法 ----

    def _screenshot(self, name):
        """截图并保存"""
        # 文件名带时间戳，避免同名覆盖
        path = os.path.join(self.output_dir, f"{int(time.time())}_{name}.png")
        try:
            self.client.screenshot(path)
            logger.info(f"  >> 截图: {path}")
        except Exception as e:
            # 截图失败不掩盖原始错误
            logger.warning(f"  >> 截图失败: {e}")

    def _capture(self, reason):
        """页面树 + 截图卡点"""
        self.monitor.capture(reason)

    def _click_text(self, text):
        """点击可见文本控件"""
        return self.monitor.click_text(self.client, text)

    def _wait_state(self, description, states, timeout=30, recover=None):
        """等待页面进入指定状态之一"""
        # 允许传入单个状态字符串
        if isinstance(states, str):
            states = (states,)
        return self.monitor.wait_for(
            description,
            lambda page: page.state in states,
            timeout=timeout,
            recover=recover,
        )

    def _goto_home_and_dismiss_popups(self):
        """登录成功后回到首页，关闭城市弹框/活动弹框。

        每次进入首页或输入起点（其他城市）后都可能弹出城市切换弹框和活动弹框，
        需要逐一关闭后才可继续操作。
        """
        logger.info("  >> 登录成功，点击首页回到首页")
        # 点击底部「主頁」标签
        if not self._click_text("主頁"):
            self._click_text("主页")
        time.sleep(2)
        self._dismiss_home_popups()

    def _dismiss_home_popups(self):
        """关闭首页上可能出现的城市弹框和活动弹框，循环处理直到清空。"""
        # 最多处理 5 轮，避免弹框不断弹出导致死循环
        for _ in range(5):
            page = self.monitor.inspect()
            state = page.state
            if state == "activity_popup":
                logger.info("  >> 首页检测到活动弹框，关闭")
                self.monitor.dismiss_activity_popup(self.client)
                time.sleep(1)
                continue
            if state == "privacy_agreement":
                logger.info("  >> 首页检测到隐私协议，同意")
                self._click_text("同意")
                time.sleep(2)
                continue
            if state == "permission_dialog":
                logger.info("  >> 首页检测到权限弹窗，授权")
                if not self._click_text("去授權"):
                    self._click_text("去授权")
                time.sleep(1)
                try:
                    self.client.alert.accept()
                except Exception:
                    pass
                time.sleep(2)
                continue
            # 城市弹框：含「取消」/「確認」且非订单/登录页
            if page.has("取消", "取消") and page.has("確認", "确认", "确定") and \
               not page.has("確認呼叫", "确认呼叫"):
                logger.info("  >> 首页检测到城市弹框，点击确认")
                if not self._click_text("確認"):
                    self._click_text("确认")
                time.sleep(2)
                continue
            logger.info("  >> 首页弹框已清空，当前状态: %s", state)
            self._capture("home_popups_dismissed")
            return

    def _swipe_slider(self, x_start=46, y=795, x_end=380, duration=3.0):
        """滑动底部状态确认滑块（通用坐标）"""
        self.client.swipe(x_start, y, x_end, y, duration=duration)

    def _activate_app(self, bundle_id, wait=3):
        """激活指定 App"""
        self.client.app_activate(bundle_id)
        time.sleep(wait)

    def _get_current_state(self):
        """获取当前页面状态"""
        return self.monitor.inspect().state

    def _is_app_running(self, bundle_id):
        """
        判断指定 App 是否在前台运行。
        通过 WDA 获取当前活跃 App 的 bundleId 进行比对。
        """
        try:
            active = self.client.app_current()
            # WDA 返回可能是 dict，也可能是纯字符串
            active_bundle = active.get("bundleId", "") if isinstance(active, dict) else str(active)
            logger.info(f"  >> 当前前台 App: {active_bundle}")
            return active_bundle == bundle_id
        except Exception as e:
            # 拿不到前台信息时按“未运行”处理，让调用方走激活流程
            logger.warning(f"  >> 获取当前App失败: {e}")
            return False

    def _is_logged_in(self):
        """以乘客App个人中心账号匹配判断已登录。

        如果当前在首页等非个人中心页面，先跳到个人中心确认，
        再跳回首页，避免来回切换。
        """
        from jryg_hk_ios.JRYG_order_guard import require
        page = self._passenger_account_page()
        if page.state == "mine_logged":
            # 已是目标测试账号才认为登录可用，不自动退出或换号
            require(page.matches_account(self.PHONE_NUMBER), "当前已登录其他账号，不自动退出或换号")
            logger.info("  >> 已在App个人中心核实测试账号登录态")
            return True
        # 非个人中心（首页、路线页等），跳到个人中心确认
        if page.state in ("home_unlogged", "route_selected", "order_active",
                          "order_complete", "order_cancelled"):
            logger.info("  >> 当前在首页/订单页，跳到个人中心核实登录态")
            self._click_text("我的")
            page = self._order_wait("个人中心", lambda p: p.state in ("mine_logged", "mine_unlogged"),
                                   timeout=15)
            if page.state == "mine_logged":
                require(page.matches_account(self.PHONE_NUMBER), "当前已登录其他账号，不自动退出或换号")
                logger.info("  >> 已在App个人中心核实测试账号登录态")
                return True
        return False
