"""司机端完整流程单独调试入口。

从隐私协议→登录→验证码→出车→听单，全流程独立运行，
不依赖乘客端下单。用于快速验证司机端登录出车链路是否正常。

使用方式：直接运行 python JRYG_debug_driver_login.py
返回：True=流程完成（已出车听单），False=流程未完成
"""
import os
import json
import sys

# 添加项目根目录至 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from airtest.core.api import connect_device, sleep, keyevent
from poco.drivers.android.uiautomation import AndroidUiautomationPoco
from JRYG_Passenger_UI.common.JRYG_logger import logger
from JRYG_Passenger_UI.common.JRYG_config import SETTINGS, TEST_DATA_FILE
from JRYG_Passenger_UI.common.JRYG_adb_tools import JRYG_ADBTools
from JRYG_Passenger_UI.common.JRYG_driver_flow import DriverFlowMixin


class DebugDriverFlow(DriverFlowMixin):
    """司机端完整流程单独调试：隐私协议→登录→验证码→出车。

    继承 DriverFlowMixin 获取司机端状态检测、登录、验证码输入、出车等通用能力。
    与 TestJRYGOrderRide 不同，该类不需要乘客端下单，纯粹验证司机端链路。
    """

    def __init__(self):
        """初始化设备连接、Poco 实例、司机/乘客包名、测试数据。"""
        udid = SETTINGS["device"]["udid"]
        connect_device(f"android://127.0.0.1:5037/{udid}")
        self.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        self.udid = udid
        self.adb = JRYG_ADBTools(udid)
        self.driver_pkg = SETTINGS["packages"]["driver"]
        self.passenger_pkg = SETTINGS["packages"]["passenger"]
        self.driver_activity = SETTINGS["packages"]["driver_activity"]

        with open(TEST_DATA_FILE, "r", encoding="utf-8") as f:
            self.test_data = json.load(f)

        self.verify_code = "123456"
        self.driver_phone = self.test_data.get("driver_phone", "11070893898")
        self.logged_in = False
        self.drived_out = False

    # ==================== 底层操作函数 ====================

    def _launch_driver(self):
        """启动司机端 App。"""
        self.adb.start_app(self.driver_pkg, self.driver_activity)

    def _force_stop_driver(self):
        """强制停止司机端 App。"""
        self.adb.force_stop(self.driver_pkg)

    def _force_stop_passenger(self):
        """强制停止乘客端 App，避免双端互相干扰。"""
        self.adb.force_stop(self.passenger_pkg)

    # ==================== 状态检测 ====================

    def _detect_state(self):
        """检测司机端当前页面状态，综合系统弹窗和司机端业务状态。

        检测顺序：
          1. 系统级状态：launcher、blockcanary、permission_dialog
          2. 司机端业务状态：通过 _driver_state 检测（继承自 DriverFlowMixin）
          3. 未知状态：返回 "unknown"
        """
        activity = self._get_top_activity_full().lower()
        if "launcher" in activity:
            return "launcher"
        if any(name in activity for name in ("blockcanary", "displayactivity", "leakcanary")):
            return "blockcanary"
        if "permissioncontroller" in activity or "grantpermissions" in activity:
            return "permission_dialog"
        texts, names = self._page_content(self.driver_pkg)
        return self._driver_state(activity, texts, names) or "unknown"

    # ==================== 调试主流程 ====================

    def run(self):
        """调试主流程：从干净状态启动司机端，循环检测状态并驱动至听单。

        流程：
          1. 强制停止两端 App，确保干净状态
          2. 启动司机端 App
          3. 状态机循环（最多 60 次）：
             - privacy_agreement → 勾选协议 + 点击同意
             - permission_dialog → 点击允许
             - driver_tourist_home → 点击登录/注册
             - driver_login → 输入手机号登录
             - driver_verify_code → 输入验证码
             - driver_home → 点击出车
             - driver_listening → 出车成功，返回 True
          4. 遇到已有订单状态（accept_order/in_trip 等）则返回 False

        :return: True=出车听单成功，False=流程未完成
        """
        logger.info("=" * 60)
        logger.info("【司机端完整流程调试】手机号: %s, 验证码: %s", self.driver_phone, self.verify_code)
        logger.info("=" * 60)

        # 先强制停止两端，从干净状态启动
        logger.info("强制停止乘客端和司机端...")
        self._force_stop_passenger()
        self._force_stop_driver()
        sleep(2)

        # 启动司机端
        logger.info("启动司机端App...")
        self._launch_driver()
        sleep(5)

        for cycle in range(60):
            state = self._detect_state()
            self._check_stall(state)
            logger.info("[循环 %d] 状态: %s", cycle, state)

            # ── 隐私协议 ──
            if state == "privacy_agreement":
                logger.info("【隐私协议】勾选复选框并点击同意...")
                # 先勾选复选框
                check_box = self.poco(f"{self.driver_pkg}:id/tv_btn_check")
                if check_box.exists():
                    logger.info("勾选司机端隐私协议复选框...")
                    self.poco(f"{self.driver_pkg}:id/ll_content_tips").click()
                    sleep(1)
                # 点击同意
                agree_btn = self.poco(f"{self.driver_pkg}:id/tv_privacy_yes")
                if not agree_btn.exists():
                    agree_btn = self.poco(text="同意")
                if agree_btn.exists():
                    agree_btn.click()
                sleep(3)
                continue

            # ── 系统权限弹窗 ──
            if state == "permission_dialog":
                logger.info("【系统权限】点击允许...")
                allow_btn = self.poco(text="使用应用时允许")
                if not allow_btn.exists():
                    allow_btn = self.poco(text="允许")
                if allow_btn.exists():
                    allow_btn.click()
                sleep(3)
                continue

            # ── 司机端游客首页 ──
            if state == "driver_tourist_home":
                logger.info("【游客首页】点击登录/注册进入登录页...")
                btn = self.poco(text="登录/注册")
                if not btn.exists():
                    btn = self.poco(text="登录")
                if btn.exists():
                    btn.click()
                sleep(3)
                continue

            if state == "driver_login":
                self._driver_login()
                continue

            if state == "driver_verify_code":
                self._input_driver_code()
                continue

            if state == "driver_home":
                self.logged_in = True
                if not self._request_drive_out():
                    sleep(2)
                continue

            if state == "driver_listening":
                self.logged_in = True
                self.drived_out = True
                logger.info("【听单中】已确认司机出车成功")
                return True

            if state == "driver_popup":
                self._click_first(ids=(f"{self.driver_pkg}:id/iv_cancel",))
                sleep(2)
                continue

            if state in ("driver_accept_order", "driver_ready", "driver_at_pickup",
                         "driver_wait_passenger", "driver_in_trip", "driver_bill",
                         "driver_fee_abnormal", "driver_verify_phone"):
                logger.error("当前已有订单或订单弹窗，登录出车调试不处理订单: %s", state)
                return False

            # ── 司机端弹窗类（好的/知道了）──
            if state == "driver_ok":
                logger.info("【弹窗】点击 '好的'...")
                self.poco(text="好的").click()
                sleep(2)
                continue

            if state == "driver_known":
                logger.info("【弹窗】点击 '我知道了'...")
                btn = self.poco(text="我知道了")
                if not btn.exists():
                    btn = self.poco(text="知道了")
                if btn.exists():
                    btn.click()
                sleep(2)
                continue

            if state == "blockcanary":
                keyevent("BACK")
                sleep(2)
                continue

            # ── 桌面 ──
            if state == "launcher":
                logger.info("【桌面】重新启动司机端...")
                self._launch_driver()
                sleep(5)
                continue

            # ── 未知状态 ──
            logger.info("未知状态，等待2秒...")
            sleep(2)

        logger.info("【结束】调试完成，共循环60次")
        logger.info("登录状态: %s, 出车状态: %s", self.logged_in, self.drived_out)
        return False


if __name__ == "__main__":
    result = DebugDriverFlow().run()
    print("司机端登录出车流程通过" if result else "司机端流程未完成")
    sys.exit(0 if result else 1)
