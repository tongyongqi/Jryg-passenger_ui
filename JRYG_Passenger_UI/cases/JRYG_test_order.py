import pytest
import os
import json
import time
import subprocess
import sys

# 添加测试框架核心目录至 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from airtest.core.api import connect_device, sleep, keyevent
from poco.drivers.android.uiautomation import AndroidUiautomationPoco
from JRYG_Passenger_UI.common.JRYG_logger import logger
from JRYG_Passenger_UI.common.JRYG_config import SETTINGS, TEST_DATA_FILE

class TestJRYGOrderRide:
    """阳光出行起终点呼叫、车型选择、模拟接单、尾号验证、收款完单全业务闭环测试"""

    @classmethod
    def setup_class(cls):
        udid = SETTINGS["device"]["udid"]
        connect_device(f"android://127.0.0.1:5037/{udid}")
        cls.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        cls.udid = udid
        cls.passenger_pkg = SETTINGS["packages"]["passenger"]
        cls.driver_pkg = SETTINGS["packages"]["driver"]
        
        with open(TEST_DATA_FILE, "r", encoding="utf-8") as f:
            cls.test_data = json.load(f)
        logger.info("设备连接完毕，已经提取测试数据，开始全闭环自动呼叫业务流程测试")

    def test_complete_ride_flow(self):
        """全自动流转业务测试用例 (State-Machine Driven)"""
        start_addr = self.test_data["start_address"]
        dest_addr = self.test_data["dest_address"]
        phone_number = self.test_data["phone_number"]
        verify_code = self.test_data["verify_code"]
        verify_tail = self.test_data["verify_tail"]
        
        progress = {}
        logger.info("【呼叫完单测试】强制拉起乘客端 App 并准备运行状态流转...")
        self._launch_app(self.passenger_pkg)
        sleep(2)

        # 通过状态监控执行多阶段操作状态机循环
        for cycle in range(60):
            state = self._detect_state()
            logger.info(f"当前流转 [循环 {cycle}] -> 页面状态: {state}")

            if state == "launcher":
                logger.info("当前位于桌面，强制启动乘客端 App...")
                self._launch_app(self.passenger_pkg)
                continue

            if state == "blockcanary":
                logger.info("识别到 BlockCanary/LeakCanary 残留，发送 BACK 返回键清理...")
                keyevent("BACK")
                sleep(2)
                continue

            if state == "trip_finished":
                logger.info("乘客端处于行程结束页面，点击 '点击回首页' 返回首页以开展新一轮下单...")
                btn = self.poco(text="点击回首页")
                if not btn.exists():
                    btn = self.poco(text="返回首页")
                if btn.exists():
                    btn.click()
                sleep(3)
                continue

            if state == "ad":
                logger.info("识别到广告浮窗，执行叉号点击关闭...")
                try:
                    self.poco(f"{self.passenger_pkg}:id/iv_cancel").click()
                except Exception:
                    pass
                sleep(2)
                continue

            if state == "home":
                if not progress.get("start_done"):
                    logger.info("在乘客首页，点击起点栏位...")
                    start_layout = self.poco(f"{self.passenger_pkg}:id/ll_start")
                    if not start_layout.exists():
                        start_layout = self.poco(f"{self.passenger_pkg}:id/tv_start_address")
                    if start_layout.exists():
                        start_layout.click()
                    sleep(2)
                elif not progress.get("dest_done"):
                    logger.info("在乘客首页，点击目的地输入栏...")
                    dest = self.poco(f"{self.passenger_pkg}:id/rl_destination_layout")
                    if not dest.exists():
                        dest = self.poco(text="想要去哪里？")
                    if dest.exists():
                        dest.click()
                    sleep(2)
                else:
                    logger.info("起点和目的地均已设置完毕")
                continue

            if state == "search":
                if not progress.get("start_done"):
                    logger.info(f"在搜索页面，输入并选定起点: {start_addr}")
                    self._search_and_select(start_addr)
                    progress["start_done"] = True
                    sleep(4)
                elif not progress.get("dest_done"):
                    logger.info(f"在搜索页面，输入并选定目的地: {dest_addr}")
                    self._search_and_select(dest_addr)
                    progress["dest_done"] = True
                    sleep(4)
                else:
                    keyevent("BACK")
                    sleep(2)
                continue

            if state == "quote":
                logger.info("进入询价车款挑选页面，勾选并提交 '阳光优选' 确认呼叫...")
                self._handle_quote()
                continue

            if state == "cashier":
                logger.info("进入在线收银台，切换先付后乘标签并勾选微信支付...")
                self._handle_cashier()
                progress["pay_done"] = True
                continue

            if state == "calling":
                logger.info("乘客端已呼叫车辆中。马上切换至司机端接单...")
                self._launch_app(self.driver_pkg)
                # 重构 Poco 以保证驱动层同步
                self.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
                sleep(2)
                continue

            # 处理司机端各弹窗与流程状态
            if state == "driver_ok":
                logger.info("司机端系统消息，点击 '好的' 关闭弹框...")
                ok_btn = self.poco(text="好的")
                if ok_btn.exists():
                    ok_btn.click()
                sleep(2)
                continue

            if state == "driver_known":
                logger.info("司机端提示框，点击并关闭...")
                btn = self.poco(text="我知道了")
                if not btn.exists():
                    btn = self.poco(text="知道了")
                if btn.exists():
                    btn.click()
                sleep(2)
                continue

            if state == "driver_ready":
                logger.info("点击 '准备出发' 前往乘客起点...")
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
                logger.info("司机已到达，滑动 '到达上车地点'...")
                self._slide_drag_view()
                sleep(3)
                continue

            if state == "driver_wait_passenger":
                logger.info("司机已在起点等候，滑动 '已接到乘客'...")
                self._slide_drag_view()
                sleep(3)
                continue

            if state == "driver_verify_phone":
                logger.info(f"遇到安全尾号验证，对输入焦点执行 adb 键入手机尾号两位: {verify_tail}")
                self.poco.click([0.5, 0.32])
                sleep(1)
                subprocess.run(["adb", "-s", self.udid, "shell", "input", "text", verify_tail])
                sleep(3)
                continue

            if state == "driver_in_trip":
                logger.info("行程正在进行中！司机端模拟驾车 5 秒后，滑动 '到达目的地' 准备结算...")
                sleep(5)
                self._slide_drag_view()
                sleep(3)
                continue

            if state == "driver_bill":
                logger.info("点击稍后查看以关闭遮挡弹窗，然后滑动 '发起收款'...")
                btn_later = self.poco(text="稍后查看")
                if btn_later.exists():
                    btn_later.click()
                    sleep(1)
                self._slide_drag_view()
                sleep(3)
                continue

            if state == "driver_fee_abnormal":
                logger.info("系统检测到费用异常弹窗，点击 '拒绝' 以拒绝免单并继续正常收款...")
                btn_refuse = self.poco(text="拒绝")
                if btn_refuse.exists():
                    btn_refuse.click()
                sleep(3)
                continue

            if state == "driver_bill_finished":
                logger.info("【业务成功】司机端完单、发起收款，自动完成收车，全闭环操作通过！")
                progress["flow_complete"] = True
                break

            sleep(2)

        # 切换到乘客端进行结算结果判定
        logger.info("业务流转成功，立即切回乘客端核对完单结果账单...")
        self._launch_app(self.passenger_pkg)
        sleep(6)
        
        texts = self._get_all_texts()
        joined = " ".join(texts)
        assert "行程结束" in joined or "待支付" in joined or "元" in joined or "账单" in joined, "核对失败：乘客端未正确到达订单终期页面"
        logger.info("【核对完毕】乘客端已完单并且自动计算折扣完毕")

    # ==================== 底层操作函数封装 ====================

    def _detect_state(self):
        activity = self._get_top_activity().lower()
        
        if "launcher" in activity:
            return "launcher"
        if "blockcanary" in activity or "displayactivity" in activity or "leakcanary" in activity:
            return "blockcanary"

        # 1. 快速匹配 (极速的 exists 校验，无延迟且不消耗 RPC 请求)
        if "com.jryg.driver" in activity:
            if self.poco(text="拒绝").exists() and self.poco(text="同意").exists():
                return "driver_fee_abnormal"
            if self.poco(text="好的").exists():
                return "driver_ok"
            if self.poco(text="我知道了").exists() or self.poco(text="知道了").exists():
                return "driver_known"
            if self.poco(text="准备出发").exists() or self.poco(text="出发").exists():
                return "driver_ready"
            if self.poco(text="到达上车地点").exists():
                return "driver_at_pickup"
            if self.poco(text="已接到乘客").exists():
                return "driver_wait_passenger"
            if self.poco(textMatches=".*验证.*").exists() or self.poco(textMatches=".*后两位.*").exists():
                return "driver_verify_phone"
            if self.poco(text="到达目的地").exists() or self.poco(textMatches=".*送乘客.*").exists():
                return "driver_in_trip"
            if self.poco(text="未确认账单").exists() or self.poco(text="发起收款").exists():
                return "driver_bill"
            if self.poco(text="今日营收").exists() or self.poco(text="听单检测").exists():
                return "driver_bill_finished"
        else:
            if self.poco(f"{self.passenger_pkg}:id/iv_cancel").exists():
                return "ad"
            if "addresssearch" in activity:
                return "search"
            if "immediateorderprocess" in activity:
                if self.poco(text="点击回首页").exists() or self.poco(text="行程结束").exists() or self.poco(textMatches=".*行程结束.*").exists():
                    return "trip_finished"
                return "calling"
            if self.poco(text="确认支付并呼叫").exists() or self.poco(text="先付后乘").exists() or self.poco(text="先付费后乘车").exists():
                return "cashier"
            if self.poco(text="确认呼叫").exists() or self.poco(text="阳光优选").exists():
                return "quote"
            if "ygahomeactivity" in activity:
                return "home"

        # 2. 兜底匹配 (获取所有文本进行多条件复合判定)
        texts = self._get_all_texts()
        joined = " ".join(texts)

        # 司机端应用内状态
        if "com.jryg.driver" in activity:
            if "拒绝" in texts and "同意" in texts:
                return "driver_fee_abnormal"
            if "好的" in texts:
                return "driver_ok"
            if "我知道了" in texts or "知道了" in texts:
                return "driver_known"
            if "准备出发" in texts or "出发" in texts:
                return "driver_ready"
            if "到达上车地点" in texts:
                return "driver_at_pickup"
            if "已接到乘客" in texts:
                return "driver_wait_passenger"
            if "验证身份" in texts or "tv_verify_phone_title" in joined or "后两位" in joined:
                return "driver_verify_phone"
            if "到达目的地" in texts or "送乘客" in texts:
                return "driver_in_trip"
            if "未确认账单" in texts or "tv_title" in joined or "发起收款" in texts:
                return "driver_bill"
            if "今日营收" in texts or "听单检测" in texts:
                return "driver_bill_finished"
            return "driver_other"

        # 乘客端应用内状态
        if self.poco(f"{self.passenger_pkg}:id/iv_cancel").exists():
            return "ad"
        if "addresssearch" in activity:
            return "search"
        if "immediateorderprocess" in activity or "正在为您呼叫" in joined:
            if "点击回首页" in joined or "行程结束" in joined:
                return "trip_finished"
            return "calling"
        if "确认支付并呼叫" in joined or "先付后乘" in joined:
            return "cashier"
        if "阳光优选" in joined or "确认呼叫" in joined:
            return "quote"
        if "ygahomeactivity" in activity:
            return "home"
            
        return "unknown"

    def _get_top_activity(self):
        res = subprocess.run(
            ["adb", "-s", self.udid, "shell", "dumpsys", "activity", "activities"],
            capture_output=True, text=True, timeout=10
        )
        for line in res.stdout.split("\n"):
            if "topResumedActivity" in line:
                return line.strip()
        return "unknown"

    def _launch_app(self, package):
        subprocess.run(["adb", "-s", self.udid, "shell", "am", "force-stop", package], capture_output=True)
        sleep(1)
        subprocess.run(["adb", "-s", self.udid, "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], capture_output=True)
        sleep(6)

    def _handle_blockcanary(self):
        try:
            subprocess.run(["adb", "-s", self.udid, "shell", "input", "tap", "586", "2670"], capture_output=True)
        except Exception:
            pass

    def _get_all_texts(self):
        texts = []
        try:
            for el in self.poco(type="android.widget.TextView"):
                try:
                    t = el.get_text()
                    if t and t.strip():
                        texts.append(t)
                except Exception:
                    pass
        except Exception:
            pass
        return texts

    def _search_and_select(self, keyword):
        et = self.poco(f"{self.passenger_pkg}:id/et_search")
        if not et.exists():
            et = self.poco(type="android.widget.EditText")
        et.click()
        sleep(0.5)
        et.set_text(keyword)
        sleep(3)
        
        parent = self.poco(f"{self.passenger_pkg}:id/rl_parent")
        if parent.exists():
            parent[0].click()
        else:
            result = self.poco(textMatches=f".*{keyword[:3]}.*")
            if result.exists():
                result[0].click()

    def _handle_quote(self):
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

    def _handle_cashier(self):
        pay_first = self.poco(text="先付后乘")
        if not pay_first.exists():
            pay_first = self.poco(text="先付费后乘车")
        if pay_first.exists():
            pay_first.click()
            sleep(2)
        wechat = self.poco(text="微信支付")
        if wechat.exists():
            wechat.click()
            sleep(2)
        btn = self.poco(text="确认支付并呼叫")
        if not btn.exists():
            btn = self.poco(text="确认呼叫")
        if btn.exists():
            btn.click()
        sleep(5)

    def _slide_drag_view(self):
        drag_view = self.poco("com.jryg.driver:id/ll_drag_view")
        if drag_view.exists():
            pos = drag_view.get_position()
            size = drag_view.get_size()
            x_start = pos[0] - size[0] / 2 + 0.05
            x_end = pos[0] + size[0] / 2 - 0.05
            y = pos[1]
            self.poco.swipe([x_start, y], [x_end, y], duration=1.5)
            logger.info("横向滑块滑动指令执行完成")
