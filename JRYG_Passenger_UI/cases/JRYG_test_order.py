"""阳光出行乘客端+司机端全链路订单自动化测试。

完整业务闭环：乘客下单 → 司机接单 → 到达 → 接乘客 → 行程 → 收款完单

流程概述：
  阶段1: 打开乘客端 App
  阶段2: 授权（隐私协议 + 系统权限弹窗）
  阶段3: 登录（手机号 + 验证码）
  阶段4: 下单（设置起点/目的地 → 搜索选择地址 → 询价选车型 → 收银台支付 → 呼叫）
  阶段4.5: 司机端登录（如未登录则先登录）+ 出车听单
  阶段5: 司机端接单流程（接单 → 准备出发 → 到达 → 接乘客 → 验证尾号 → 行程 → 收款完单）
  收尾: 切回乘客端返回首页

设计模式：
  - 状态机循环：通过 _detect_state 检测当前页面状态，路由到对应处理逻辑
  - DriverFlowMixin：提供司机端状态检测、登录、验证码输入、出车、卡顿检测等通用能力
  - progress 字典：跨阶段传递已完成步骤标记（start_done/dest_done/order_started 等）
  - 卡顿检测：_check_stall 当页面状态持续超时未推进时抛出断言

前置条件：
  - 设备已连接、Appium Server 已启动
  - 测试数据 JSON 中包含 start_address、dest_address、phone_number、verify_code、verify_tail
  - 司机端 App 已安装
"""
import pytest
import os
import json
import time
import subprocess
import sys

# 将项目根目录添加到 sys.path，确保 common 模块可被正确导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from airtest.core.api import connect_device, sleep, keyevent
from poco.drivers.android.uiautomation import AndroidUiautomationPoco
from JRYG_Passenger_UI.common.JRYG_logger import logger
from JRYG_Passenger_UI.common.JRYG_config import SETTINGS, TEST_DATA_FILE
from JRYG_Passenger_UI.common.JRYG_adb_tools import JRYG_ADBTools
from JRYG_Passenger_UI.common.JRYG_driver_flow import DriverFlowMixin

class TestJRYGOrderRide(DriverFlowMixin):
    """阳光出行起终点呼叫、车型选择、模拟接单、尾号验证、收款完单全业务闭环测试

    继承 DriverFlowMixin 获取司机端状态检测、登录、验证码输入、出车等通用能力。
    通过状态机循环驱动双端 App 完成从下单到完单的全流程。
    """

    @classmethod
    def setup_class(cls):
        """类级 setup：连接设备、创建 Poco 实例、加载测试数据。

        使用 airtest connect_device 连接 Android 设备，
        AndroidUiautomationPoco 创建 Poco 实例用于 UI 操作，
        JRYG_ADBTools 封装 ADB 命令用于 App 启动/停止等操作。
        """
        udid = SETTINGS["device"]["udid"]
        connect_device(f"android://127.0.0.1:5037/{udid}")
        cls.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        cls.udid = udid
        cls.adb = JRYG_ADBTools(udid)
        cls.passenger_pkg = SETTINGS["packages"]["passenger"]  # 乘客端包名
        cls.driver_pkg = SETTINGS["packages"]["driver"]        # 司机端包名

        # 加载测试数据：起终点地址、手机号、验证码、手机尾号
        with open(TEST_DATA_FILE, "r", encoding="utf-8") as f:
            cls.test_data = json.load(f)

        logger.info("设备连接完毕，应用进程由用例启动阶段统一处理，保留应用数据")

    def test_complete_ride_flow(self):
        """乘客下单、司机接单完单、乘客返回首页。"""
        logger.info("【呼叫完单测试】强制拉起乘客端 App 并准备运行状态流转...")
        self._launch_app(self.passenger_pkg)
        sleep(2)
        self._run_ride_flow()

    def _run_ride_flow(self, progress=None):
        """执行完整行程流程的状态机循环。

        核心机制：通过 _detect_state 检测当前页面状态，路由到对应处理逻辑，
        直到行程完成或订单失败时退出循环。最多循环 60 次。

        状态流程：
          阶段1: launcher/blockcanary → 启动 App
          阶段2: privacy_agreement/permission_dialog → 授权弹窗处理
          阶段3: login → 手机号+验证码登录
          阶段4: ad/home/search/quote/cashier/calling → 乘客下单
          阶段4.5: driver_tourist_home/driver_login/driver_verify_code → 司机端登录
          阶段5: driver_accept_order → driver_ready → driver_at_pickup →
                  driver_wait_passenger → driver_verify_phone → driver_in_trip →
                  driver_bill → driver_finished → 切回乘客端

        :param progress: 可选的进度字典，用于跨阶段传递已完成步骤标记
                         （start_done/dest_done/order_started/trip_started/collection_submitted）
        """
        start_addr = self.test_data["start_address"]
        dest_addr = self.test_data["dest_address"]
        verify_tail = self.test_data["verify_tail"]
        progress = dict(progress or {})
        state = "not_started"
        self._last_state = None

        # ==================== 状态机循环 ====================
        # 流程顺序：打开app → 授权 → 登录 → 下单 → 下单后续操作
        for cycle in range(60):
            state = self._detect_state()
            logger.info(f"当前流转 [循环 {cycle}] -> 页面状态: {state}")

            self._check_stall(state, timeout=120 if state == "driver_listening" else 60)
            if state == "order_failed":
                pytest.fail(f"乘客呼叫失败或订单被取消，停止流程: {self._get_all_texts()}")
            if all(progress.get(key) for key in (
                "order_started", "trip_started", "collection_submitted"
            )) and state in ("driver_home", "driver_listening", "driver_finished"):
                progress["flow_complete"] = True
                logger.info("【司机端完单】已确认收款后的结束状态，准备切回乘客端")
                break

            # ── 阶段1: 打开app ──
            if state == "launcher":
                logger.info("【阶段1-打开app】当前位于桌面，强制启动乘客端 App...")
                self._launch_app(self.passenger_pkg)
                continue

            if state == "blockcanary":
                logger.info("【阶段1-打开app】识别到 BlockCanary/LeakCanary 残留，发送 BACK 返回键清理...")
                keyevent("BACK")
                sleep(2)
                continue

            # ── 阶段2: 授权（隐私协议 + 系统权限） ──
            if state == "privacy_agreement":
                logger.info("【阶段2-授权】识别到隐私协议弹窗，勾选复选框并点击 '同意'...")
                # 司机端需要先勾选"我已仔细阅读"复选框
                check_box = self.poco(f"{self.driver_pkg}:id/tv_btn_check")
                if check_box.exists():
                    logger.info("勾选司机端隐私协议复选框...")
                    self.poco(f"{self.driver_pkg}:id/ll_content_tips").click()
                    sleep(1)
                # 点击同意按钮（乘客端/司机端通用）
                agree_btn = self.poco(text="同意")
                if not agree_btn.exists():
                    agree_btn = self.poco(f"{self.passenger_pkg}:id/tv_button_agree")
                if not agree_btn.exists():
                    agree_btn = self.poco(f"{self.driver_pkg}:id/tv_privacy_yes")
                if agree_btn.exists():
                    agree_btn.click()
                else:
                    subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "770", "2590"])
                sleep(3)
                continue

            if state == "permission_dialog":
                logger.info("【阶段2-授权】识别到系统权限弹窗，点击 '使用应用时允许' 授权...")
                allow_btn = self.poco(text="使用应用时允许")
                if not allow_btn.exists():
                    allow_btn = self.poco(text="允许")
                if allow_btn.exists():
                    allow_btn.click()
                else:
                    subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "586", "2178"])
                sleep(3)
                continue

            # ── 阶段3: 登录 ──
            if state == "login":
                logger.info("【阶段3-登录】识别到登录页面，执行登录流程...")

                # 先检查是否有协议二次确认弹窗（不同意/同意）
                agree_dialog = self.poco(text="同意")
                disagree_dialog = self.poco(text="不同意")
                if agree_dialog.exists() and disagree_dialog.exists():
                    logger.info("检测到服务协议二次确认弹窗，点击 '同意'...")
                    agree_dialog.click()
                    sleep(2)

                phone_input = self.poco(f"{self.passenger_pkg}:id/et_phone_num")
                if not phone_input.exists():
                    phone_input = self.poco(type="android.widget.EditText")
                if phone_input.exists():
                    # 检查是否已在验证码输入阶段
                    code_label = self.poco(textMatches=".*验证码.*")
                    if code_label.exists():
                        logger.info("已在验证码输入阶段，直接输入验证码...")
                        code_input = self.poco(type="android.widget.EditText")
                        if code_input.exists():
                            code_input.click()
                            sleep(0.5)
                            code_input.set_text(self.test_data["verify_code"])
                            sleep(1)
                            confirm_btn = self.poco(text="确认")
                            if not confirm_btn.exists():
                                confirm_btn = self.poco(text="登录")
                            if not confirm_btn.exists():
                                confirm_btn = self.poco(textMatches=".*确认|登录.*")
                            if confirm_btn.exists():
                                confirm_btn.click()
                            sleep(5)
                        continue

                    # 手机号输入阶段
                    phone_input.click()
                    sleep(0.5)
                    phone_input.set_text(self.test_data["phone_number"])
                    sleep(1)

                    # 勾选协议
                    checkbox = self.poco(f"{self.passenger_pkg}:id/cb_agree")
                    if not checkbox.exists():
                        checkbox = self.poco(type="android.widget.CheckBox")
                    if checkbox.exists():
                        try:
                            if not checkbox.attr("checked"):
                                checkbox.click()
                                sleep(0.5)
                        except Exception:
                            checkbox.click()
                            sleep(0.5)

                    # 点击下一步
                    next_btn = self.poco(text="下一步")
                    if not next_btn.exists():
                        next_btn = self.poco(textMatches=".*下一步.*")
                    if next_btn.exists():
                        next_btn.click()
                    sleep(2)

                    # 处理可能出现的协议二次确认弹窗
                    agree_dialog2 = self.poco(text="同意")
                    disagree_dialog2 = self.poco(text="不同意")
                    if agree_dialog2.exists() and disagree_dialog2.exists():
                        logger.info("点击下一步后弹出协议二次确认，点击 '同意'...")
                        agree_dialog2.click()
                        sleep(3)

                    # 输入验证码
                    code_input = self.poco(f"{self.passenger_pkg}:id/et_code")
                    if not code_input.exists():
                        code_input = self.poco(type="android.widget.EditText")
                    if code_input.exists():
                        code_input.click()
                        sleep(0.5)
                        code_input.set_text(self.test_data["verify_code"])
                        sleep(1)

                        # 点击确认/登录
                        confirm_btn = self.poco(text="确认")
                        if not confirm_btn.exists():
                            confirm_btn = self.poco(text="登录")
                        if not confirm_btn.exists():
                            confirm_btn = self.poco(textMatches=".*确认|登录.*")
                        if confirm_btn.exists():
                            confirm_btn.click()
                        sleep(5)
                else:
                    logger.warning("登录页面未找到手机号输入框")
                    keyevent("BACK")
                    sleep(2)
                continue

            # ── 阶段4: 下单（设置起终点 → 询价 → 收银台 → 呼叫） ──
            if state == "ad":
                logger.info("【阶段4-下单】识别到广告浮窗，执行叉号点击关闭...")
                try:
                    self.poco(f"{self.passenger_pkg}:id/iv_cancel").click()
                except Exception:
                    pass
                sleep(2)
                continue

            if state == "home":
                if not progress.get("start_done"):
                    logger.info("【阶段4-下单】在乘客首页，点击起点栏位...")
                    start_layout = self.poco(f"{self.passenger_pkg}:id/ll_start")
                    if not start_layout.exists():
                        start_layout = self.poco(f"{self.passenger_pkg}:id/tv_start_address")
                    if start_layout.exists():
                        start_layout.click()
                    sleep(2)
                elif not progress.get("dest_done"):
                    logger.info("【阶段4-下单】在乘客首页，点击目的地输入栏...")
                    dest = self.poco(f"{self.passenger_pkg}:id/rl_destination_layout")
                    if not dest.exists():
                        dest = self.poco(text="想要去哪里？")
                    if dest.exists():
                        dest.click()
                    sleep(2)
                else:
                    # 验证目的地是否真正设置成功
                    dest_text = self.poco(f"{self.passenger_pkg}:id/tv_destination")
                    if dest_text.exists():
                        try:
                            actual_dest = dest_text.get_text()
                        except Exception:
                            actual_dest = ""
                        if actual_dest and actual_dest != "想要去哪里？" and actual_dest.strip():
                            logger.info(f"【阶段4-下单】起点和目的地均已设置完毕，目的地: {actual_dest}")
                        else:
                            logger.warning(f"【阶段4-下单】目的地实际为空('{actual_dest}')，重置 dest_done 以重新设置目的地...")
                            progress["dest_done"] = False
                    else:
                        logger.info("【阶段4-下单】起点和目的地均已设置完毕")
                continue

            if state == "search":
                if not progress.get("start_done"):
                    logger.info(f"【阶段4-下单】在搜索页面，输入并选定起点: {start_addr}")
                    if self._search_and_select(start_addr):
                        progress["start_done"] = True
                    sleep(4)
                elif not progress.get("dest_done"):
                    logger.info(f"【阶段4-下单】在搜索页面，输入并选定目的地: {dest_addr}")
                    if self._search_and_select(dest_addr):
                        progress["dest_done"] = True
                    sleep(4)
                else:
                    keyevent("BACK")
                    sleep(2)
                continue

            if state == "quote":
                logger.info("【阶段4-下单】进入询价车款挑选页面，勾选并提交 '阳光优选' 确认呼叫...")
                self._handle_quote()
                continue

            if state == "cashier":
                logger.info("【阶段4-下单】进入在线收银台，校验微信支付并提交呼叫...")
                try:
                    self._handle_cashier()
                except Exception:
                    logger.exception("【收银台失败】已尝试提交=%s", getattr(self, "_cashier_submitted", False))
                    raise
                progress["order_started"] = True
                self._switch_to_driver()
                continue

            if state == "calling":
                progress["order_started"] = True
                self._switch_to_driver()
                continue

            if state == "trip_finished":
                if progress.get("order_started"):
                    pytest.fail("本次乘客订单已结束，但尚未确认司机端收款完成，停止重复下单")
                logger.info("【阶段4-下单】关闭旧订单结束页，返回乘客首页")
                self._click_first(texts=("点击回首页", "返回首页", "回到首页"), package=self.passenger_pkg)
                sleep(3)
                continue

            # ── 阶段4.5: 司机端登录（如未登录则先登录） ──
            if state == "driver_tourist_home":
                logger.info("【司机端登录】司机端未登录，在游客首页，点击 '登录/注册' 进入登录页...")
                login_btn = self.poco(f"{self.driver_pkg}:id/btn_login")
                if login_btn.exists():
                    login_btn.click()
                else:
                    login_btn = self.poco(text="登录/注册")
                    if login_btn.exists():
                        login_btn.click()
                sleep(3)
                continue

            if state == "driver_login":
                self._driver_login()
                continue

            if state == "driver_verify_code":
                self._input_driver_code()
                continue

            if state == "driver_home":
                if not self._request_drive_out():
                    sleep(3)
                continue

            if state == "driver_popup":
                self._click_first(ids=(f"{self.driver_pkg}:id/iv_cancel",))
                sleep(2)
                continue

            # ── 司机端听单中 ──
            if state == "driver_listening":
                logger.info("【司机端听单】司机端正在听单，等待乘客下单...")
                sleep(3)
                continue

            # ── 司机端接单弹窗 ──
            if state == "driver_accept_order":
                logger.info("【司机端接单】检测到接单弹窗，点击抢单/接单...")
                btn = self.poco(text="抢单")
                if not btn.exists():
                    btn = self.poco(text="接单")
                if btn.exists():
                    btn.click()
                    logger.info("已点击抢单/接单")
                sleep(3)
                continue

            # ── 阶段5: 下单后续操作（司机端接单 → 到达 → 接乘客 → 行程 → 完单） ──
            if state == "driver_ok":
                logger.info("【阶段5-后续操作】司机端系统消息，点击 '好的' 关闭弹框...")
                ok_btn = self.poco(text="好的")
                if ok_btn.exists():
                    ok_btn.click()
                sleep(2)
                continue

            if state == "driver_known":
                logger.info("【阶段5-后续操作】司机端提示框，点击并关闭...")
                btn = self.poco(text="我知道了")
                if not btn.exists():
                    btn = self.poco(text="知道了")
                if btn.exists():
                    btn.click()
                sleep(2)
                continue

            if state == "driver_ready":
                logger.info("【阶段5-后续操作】点击 '准备出发' 前往乘客起点...")
                btn = self.poco(text="准备出发")
                if not btn.exists():
                    btn = self.poco(text="到达上车地点")
                if not btn.exists():
                    btn = self.poco(text="出发")
                if btn.exists():
                    btn.click()
                sleep(2)
                continue

            if state == "driver_at_pickup":
                logger.info("【阶段5-后续操作】司机已到达，滑动 '到达上车地点'...")
                self._slide_drag_view()
                sleep(3)
                continue

            if state == "driver_wait_passenger":
                logger.info("【阶段5-后续操作】司机已在起点等候，滑动 '已接到乘客'...")
                self._slide_drag_view()
                sleep(3)
                continue

            if state == "driver_verify_phone":
                logger.info(f"【阶段5-后续操作】遇到安全尾号验证，键入手机尾号两位: {verify_tail}")
                self.poco.click([0.5, 0.32])
                sleep(1)
                subprocess.run(["adb", "-s", self.udid, "shell", "input", "text", verify_tail])
                sleep(3)
                continue

            if state == "driver_in_trip":
                progress["trip_started"] = True
                logger.info("【阶段5-后续操作】行程进行中！模拟驾车 5 秒后，滑动 '到达目的地' 准备结算...")
                sleep(5)
                self._slide_drag_view()
                sleep(3)
                continue

            if state == "driver_bill":
                logger.info("【阶段5-后续操作】点击稍后查看关闭遮挡弹窗，然后滑动 '发起收款'...")
                btn_later = self.poco(text="稍后查看")
                if btn_later.exists():
                    btn_later.click()
                    sleep(1)
                if self._slide_drag_view():
                    progress["collection_submitted"] = True
                sleep(3)
                continue

            if state == "driver_fee_abnormal":
                logger.info("【阶段5-后续操作】费用异常弹窗，点击 '拒绝' 继续正常收款...")
                btn_refuse = self.poco(text="拒绝")
                if btn_refuse.exists():
                    btn_refuse.click()
                sleep(3)
                continue

            if state == "driver_in_service":
                logger.info("【司机端服务中】检测到司机端有进行中订单（出发去接乘客），等待状态推进...")
                sleep(3)
                continue

            if state == "driver_other":
                logger.warning("未识别司机页面，等待刷新，不重启正在进行的订单")

            sleep(2)

        assert progress.get("flow_complete"), (
            f"司机端订单流程未结束，最后状态: {state}，进度: {progress}，"
            f"页面: {self._get_top_activity_full()}，文本: {self._get_all_texts()}"
        )
        self._return_to_passenger_home()
        logger.info("【流程完成】司机端订单已结束，乘客端已返回首页")

    # ==================== 底层操作函数封装 ====================

    def _switch_to_driver(self):
        """双端衔接：从乘客端切换到司机端 App。

        乘客端下单进入呼叫页面后，通过 ADB 启动司机端 App。
        等待司机端进入前台（最多 15 秒），同时处理可能出现的系统权限弹窗。
        """
        logger.info("【双端衔接】乘客已进入呼叫页面，打开司机端接单，不停止乘客端")
        self.adb.start_app(self.driver_pkg, SETTINGS["packages"]["driver_activity"])
        for _ in range(15):
            activity = self._get_top_activity_full().lower()
            if self.driver_pkg in activity:
                logger.info("【双端衔接】司机端已在前台，继续接单和各状态滑动")
                return
            if "permissioncontroller" in activity or "grantpermissions" in activity:
                return
            sleep(1)
        raise RuntimeError(f"切换司机端失败，当前页面: {self._get_top_activity_full()}")

    def _return_to_passenger_home(self):
        """司机端完单后切回乘客端，返回首页。

        通过 ADB am start 启动乘客端 App，最多等待 60 秒确认回到首页。
        处理可能遇到的：卡顿监控页、广告弹窗、行程结束页（点击回首页/返回键）。
        """
        logger.info("【乘客端收尾】切回乘客端，返回首页")
        launch_command = [
            "adb", "-s", self.udid, "shell", "am", "start", "-n",
            f"{self.passenger_pkg}/{SETTINGS['packages']['passenger_activity']}"
        ]
        subprocess.run(launch_command, capture_output=True, text=True, timeout=15, check=True)
        deadline = time.monotonic() + 60
        back_attempts = 0
        foreground_attempts = 0
        while time.monotonic() < deadline:
            activity = self._get_top_activity_full().lower()
            if any(name in activity for name in ("blockcanary", "leakcanary", "displayactivity")):
                logger.info("【乘客端收尾】关闭卡顿监控页面")
                keyevent("BACK")
                sleep(2)
                continue
            if self.passenger_pkg not in activity:
                if foreground_attempts < 2:
                    logger.info("【乘客端收尾】返回键后离开乘客端，重新唤起乘客端")
                    subprocess.run(launch_command, capture_output=True, text=True, timeout=15, check=True)
                    foreground_attempts += 1
                sleep(2)
                continue

            cancel_btn = self.poco(f"{self.passenger_pkg}:id/iv_cancel")
            if cancel_btn.exists():
                cancel_btn.click()
                sleep(2)
                continue

            for text in ("点击回首页", "返回首页", "回到首页"):
                button = self.poco(text=text, package=self.passenger_pkg)
                if not button.exists():
                    button = self.poco(desc=text, package=self.passenger_pkg)
                if button.exists():
                    logger.info("【乘客端收尾】点击 '%s'", text)
                    button.click()
                    sleep(2)
                    break
            else:
                home_visible = (
                    self.poco(f"{self.passenger_pkg}:id/ll_start").exists()
                    or self.poco(f"{self.passenger_pkg}:id/rl_destination_layout").exists()
                )
                if "ygahomeactivity" in activity and home_visible:
                    logger.info("【乘客端收尾】已确认乘客首页显示")
                    return
                texts = " ".join(self._get_all_texts())
                if back_attempts < 3 and any(
                    text in texts for text in ("行程结束", "订单已完成", "待支付", "评价本次行程")
                ):
                    logger.info("【乘客端收尾】结束页无回首页按钮，按返回键")
                    keyevent("BACK")
                    back_attempts += 1
                sleep(2)

        pytest.fail(
            f"司机端已完单，但乘客端60秒内未返回首页；"
            f"页面: {self._get_top_activity_full()}，文本: {self._get_all_texts()}"
        )

    def _detect_state(self):
        """检测当前页面状态，返回状态字符串。

        检测顺序（优先级从高到低）：
          1. 系统级状态：launcher（桌面）、blockcanary（卡顿监控）、permission_dialog（权限弹窗）
          2. 隐私协议：privacy_agreement
          3. 司机端状态：通过 _driver_state 检测司机端各业务阶段
          4. 乘客端状态：login、cashier、ad、search、order_failed、trip_finished、calling、quote、home

        返回值：状态字符串，如 launcher/privacy_agreement/login/home/search/quote/cashier/calling/
                driver_login/driver_verify_code/driver_home/driver_listening/driver_accept_order/
                driver_ready/driver_at_pickup/driver_wait_passenger/driver_verify_phone/
                driver_in_trip/driver_bill/driver_finished 等
        """
        activity = self._get_top_activity_full().lower()
        if "launcher" in activity:
            return "launcher"
        if any(name in activity for name in ("blockcanary", "displayactivity", "leakcanary")):
            return "blockcanary"
        if "permissioncontroller" in activity or "grantpermissions" in activity:
            return "permission_dialog"

        package = self.driver_pkg if self.driver_pkg in activity else self.passenger_pkg
        texts, names = self._page_content(package)
        joined = " ".join(texts)
        if "同意" in texts and ("ygaloadingactivity" in activity or (
            "不同意" in texts and any(text in joined for text in ("隐私", "协议", "个人信息"))
        )):
            return "privacy_agreement"
        driver_state = self._driver_state(activity, texts, names)
        if driver_state:
            return driver_state
        if self.passenger_pkg not in activity:
            return "unknown"
        if "login" in activity:
            return "login"
        cashier_ids = {f"{self.passenger_pkg}:id/cashier_title", f"{self.passenger_pkg}:id/btn_confirm"}
        if cashier_ids <= names or texts & {"确认支付并呼叫", "先付后乘", "先付费后乘车"}:
            return "cashier"
        if f"{self.passenger_pkg}:id/iv_cancel" in names:
            return "ad"
        if "addresssearch" in activity:
            return "search"
        if any(text in joined for text in ("呼叫超时", "已自动取消订单", "订单已取消")):
            return "order_failed"
        if texts & {"点击回首页", "返回首页", "回到首页", "行程结束", "订单已完成"}:
            return "trip_finished"
        if "immediateorderprocess" in activity or "正在为您呼叫" in joined:
            return "calling"
        if texts & {"确认呼叫", "阳光优选"}:
            return "quote"
        if "ygahomeactivity" in activity:
            return "home"
        return "unknown"

    def _launch_app(self, package, force_stop_other=True):
        """启动指定 App，可选先强杀另一端 App 以避免干扰。"""
        if force_stop_other:
            other = self.driver_pkg if package == self.passenger_pkg else self.passenger_pkg
            self.adb.force_stop(other)
        self.adb.force_stop(package)
        activity = SETTINGS["packages"]["passenger_activity"] if package == self.passenger_pkg \
            else SETTINGS["packages"]["driver_activity"]
        self.adb.start_app(package, activity)
        sleep(6)

    def _search_and_select(self, keyword):
        """在地址搜索页输入关键词并选中第一条搜索结果。

        定位策略（按优先级降级）：
          方式1: 通过 rl_parent 容器点击第一条结果
          方式2: 通过文本模糊匹配（前 3 个字符）点击结果
          方式3: 通过 RecyclerView 容器的第一个子项点击

        :param keyword: 搜索关键词（如起终点地址）
        :return: True 选中成功，False 选中失败
        """
        et = self.poco(f"{self.passenger_pkg}:id/et_search")
        if not et.exists():
            et = self.poco(type="android.widget.EditText")
        et.click()
        sleep(0.5)
        et.set_text(keyword)
        sleep(3)

        # 尝试多种方式选中搜索结果
        # 方式1: 通过 rl_parent 容器点击第一条结果
        parent = self.poco(f"{self.passenger_pkg}:id/rl_parent")
        if parent.exists():
            parent[0].click()
            return True

        # 方式2: 通过文本模糊匹配
        result = self.poco(textMatches=f".*{keyword[:3]}.*")
        if result.exists():
            result[0].click()
            return True

        # 方式3: 通过 rv/list 容器的第一个子项点击
        for rid in ["rv_search_result", "rv_address", "list_view", "recyclerView"]:
            container = self.poco(f"{self.passenger_pkg}:id/{rid}")
            if container.exists():
                try:
                    container.offspring(type="android.widget.RelativeLayout")[0].click()
                    return True
                except Exception:
                    pass

        logger.warning(f"搜索结果选中失败，关键词: {keyword}")
        return False

    def _handle_quote(self):
        """在报价页选择"阳光优选"车型并点击确认呼叫。

        流程：遍历车型列表 → 找到"阳光优选"并点击 → 点击确认呼叫按钮 → 等待跳转
        """
        car_names = self.poco(f"{self.passenger_pkg}:id/tv_car_type_name")
        if car_names.exists():
            for i in range(len(car_names)):
                try:
                    if car_names[i].get_text() == "阳光优选":
                        car_names[i].click()
                        break
                except Exception:
                    pass
        sleep(2)
        btn = self.poco(f"{self.passenger_pkg}:id/btn_call")
        if not btn.exists():
            btn = self.poco(text="确认呼叫")
        if btn.exists():
            btn.click()
        sleep(4)

    def _wechat_payment_controls(self):
        """定位收银台微信支付选项的容器行和勾选框。

        结构：pay_title(微信支付) → parent → parent(pay_root 行容器) → offspring(pay_cb 勾选框)
        返回 (row, checkbox) 两个 Poco 控件对象，供 _handle_cashier 使用。
        如果结构不匹配或缺少勾选框，抛出 RuntimeError 停止支付操作。
        """
        wechat = self.poco(f"{self.passenger_pkg}:id/pay_title", text="微信支付")
        if not wechat.exists():
            raise RuntimeError("收银台未找到微信支付选项")
        row = wechat.parent().parent()
        if row.attr("name") != f"{self.passenger_pkg}:id/pay_root":
            raise RuntimeError("微信支付选项的容器结构不匹配，停止支付操作")
        checkbox = row.offspring(f"{self.passenger_pkg}:id/pay_cb")
        if not checkbox.exists():
            raise RuntimeError("微信支付选项未找到对应勾选框")
        return row, checkbox

    def _handle_cashier(self):
        """处理收银台支付流程：勾选微信支付 → 点击确认支付并呼叫 → 等待进入呼叫页面。

        安全机制：
          - _cashier_submitted 标志位防止重复提交
          - 勾选后重新校验 checked 状态（最多 10 次刷新）
          - 确认按钮必须 enabled 才允许点击
          - 点击后等待 15 秒确认进入呼叫页面，超时则报错
          - 如果跳转微信支付页面则报错（外部支付未完成）
        """
        if getattr(self, "_cashier_submitted", False):
            raise RuntimeError("已点击确认支付并呼叫，禁止重复提交，请检查支付结果")
        if self._detect_state() != "cashier":
            raise RuntimeError("当前不是乘客收银台，停止支付操作")

        wechat = self.poco(f"{self.passenger_pkg}:id/pay_title", text="微信支付")
        if not wechat.exists():
            self._click_first(texts=("先付后乘",))
            for _ in range(10):
                if wechat.exists():
                    break
                sleep(1)
        if not wechat.exists():
            raise RuntimeError(f"收银台未找到微信支付选项: {self._get_all_texts()}")

        row, checkbox = self._wechat_payment_controls()
        selected = checkbox.attr("checked") is True
        if not selected:
            logger.info("【收银台】点击微信支付所在行，勾选微信支付")
            row.parent().click()
            for attempt in range(10):
                sleep(1)
                _, checkbox = self._wechat_payment_controls()
                selected = checkbox.attr("checked") is True
                logger.info("【收银台】重新定位微信支付，第%d次校验 checked=%s", attempt + 1, selected)
                if selected:
                    break
        if not selected:
            logger.error("【收银台】刷新节点后微信支付仍未勾选，未点击确认支付并呼叫")
            raise RuntimeError("点击后微信支付仍未勾选，禁止提交支付")
        logger.info("【收银台】已确认微信支付勾选状态: checked=True")

        button = self.poco(f"{self.passenger_pkg}:id/btn_confirm", text="确认支付并呼叫")
        if not button.exists():
            raise RuntimeError("收银台未找到确认支付并呼叫按钮")
        if not button.attr("enabled"):
            raise RuntimeError("确认支付并呼叫按钮不可用，停止提交")
        self._cashier_submitted = True
        button.click()
        logger.info("【收银台】已点击确认支付并呼叫，等待呼叫结果")
        for _ in range(15):
            sleep(1)
            state = self._detect_state()
            if state == "calling":
                logger.info("【收银台】确认支付并呼叫后已进入乘客呼叫页面")
                return True
            if state == "order_failed":
                raise RuntimeError(f"提交后呼叫失败: {self._get_all_texts()}")
            activity = self._get_top_activity_full()
            if "com.tencent.mm/" in activity:
                raise RuntimeError("已提交并跳转微信支付，尚未完成外部支付，不重复点击或切换司机端")
        raise RuntimeError(
            f"确认支付并呼叫后15秒内未进入呼叫页面，不重复提交；"
            f"Activity: {self._get_top_activity_full()}；文本: {self._get_all_texts()}"
        )

    def _slide_drag_view(self):
        """在司机端执行横向滑块滑动操作，返回是否成功。

        定位 ll_drag_view 滑块控件，从左端滑至右端模拟滑动确认。
        用于"到达上车地点"、"已接到乘客"、"到达目的地"、"发起收款"等操作。
        """
        drag_view = self.poco("com.jryg.driver:id/ll_drag_view")
        if drag_view.exists():
            pos = drag_view.get_position()
            size = drag_view.get_size()
            x_start = pos[0] - size[0] / 2 + 0.05
            x_end = pos[0] + size[0] / 2 - 0.05
            y = pos[1]
            self.poco.swipe([x_start, y], [x_end, y], duration=1.5)
            logger.info("横向滑块滑动指令执行完成")
            return True
        logger.warning("当前页面未找到司机端滑块，未执行滑动")
        return False
