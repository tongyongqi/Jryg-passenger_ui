"""复用司机 App 会话的订单接口流程，不登录、不出车、不自动收车。"""

import json
import math
import os
from pathlib import Path
import time

from JRYG_Passenger_API_HK.common.hk_config import config


def load_app_session(api, session_file=None):
    token = os.environ.get("HK_DRIVER_ACCESS_TOKEN")
    filename = session_file or os.environ.get("HK_DRIVER_SESSION_FILE")
    if not token and filename:
        try:
            session = json.loads(Path(filename).expanduser().read_text(encoding="utf-8"))
            data = session.get("data", session)
            token = data.get("access_token") or data.get("sign_info", {}).get("access_token")
        except (OSError, ValueError, AttributeError, TypeError):
            raise RuntimeError("司机 App 会话文件无法读取或格式错误") from None
    if not isinstance(token, str) or not token.strip() or any(c.isspace() for c in token) or ";" in token:
        raise RuntimeError(
            "请配置当前司机 App 的 HK_DRIVER_ACCESS_TOKEN 或 HK_DRIVER_SESSION_FILE；"
            "不会自动接口登录，请勿使用重新 API 登录生成的会话覆盖 App 登录态")
    api.access_token = token


class DriverOrderAPI:
    """司机订单仅通过 HTTP 接口推进，不依赖 UI 驱动或 Socket 模拟行驶。"""

    def __init__(self, api, logger):
        self.api = api
        self.logger = logger

    @staticmethod
    def check(result, action):
        status, resp = result
        if status != 200 or resp.get("code") != 10000:
            raise AssertionError(f"{action}失败：HTTP={status}, code={resp.get('code')}")
        return resp.get("data") or {}

    def require_online(self):
        data = self.check(self.api.get_out_car_status(), "查询司机出车状态")
        assert data.get("is_online") == 1, "司机未在线，请在 App 点击出车；不会调用出车接口"

    def require_idle(self):
        data = self.check(self.api.get_serving_order(), "查询司机服务中订单")
        assert data.get("has_serving_order") is False, "司机存在服务中订单或状态未知，停止新订单流程"

    def poll(self, timeout, interval, expected_order_no=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.require_online()
            data = self.check(self.api.polling_order(), "轮询派单")
            candidates = [data] if data.get("order_no") else data.get("list", [])
            orders = [item.get("order_no") for item in candidates if isinstance(item, dict) and item.get("order_no")]
            if expected_order_no:
                if expected_order_no in orders:
                    return expected_order_no
            elif len(set(orders)) == 1:
                return orders[0]
            elif orders:
                raise AssertionError("存在多个派单，请指定 --order-no，避免接错订单")
            time.sleep(interval)
        raise TimeoutError("司机派单轮询超时；请检查 App 长连接及定位，不会直接抢接未派发订单")

    def coordinates(self, order_no):
        data = self.check(self.api.get_service_detail(order_no), "查询订单起终点")
        order = data.get("order") or {}
        try:
            values = tuple(float(order[key]) for key in ("start_lat", "start_lng", "end_lat", "end_lng"))
        except (KeyError, TypeError, ValueError):
            raise AssertionError("订单起终点坐标缺失，停止流转，不猜测终点") from None
        assert all(math.isfinite(v) for v in values), "订单坐标不是有限数值"
        assert all(abs(v) <= limit for v, limit in zip(values, (90, 180, 90, 180))), "订单坐标超出范围"
        return values

    def change(self, order_no, status, lat, lng):
        """POST /driverApi/order/serviceChange；状态 1～4 分别对应出发、到达、开始、结束。"""
        # HTTP=200 且业务 code=10000 才继续；失败直接抛出，不改用 UI 或 Socket 操作。
        self.check(self.api.service_change(
            order_no, service_status=status, latitude=lat, longitude=lng), f"订单状态 {status} 变更")
        self.logger.info("司机接口状态已推进：%s，service_status=%s", order_no, status)
        # 等待服务端同步状态，仅等待，不调用任何设备操作。
        time.sleep(config.STATUS_WAIT)

    def advance(self, order_no, stop_after="bill", fare=None, surcharge=0,
                payment="online", cash_collected=False):
        """仅用 HTTP 完成接单及行程推进；complete 模式还调用确认账单接口。

        调用前需由 App 完成登录和出车；本方法不调用 UI、Poco、Airtest 或 Socket。
        bill 模式不提交金额，complete 模式必须指定 fare；现金收款另需明确确认。
        """
        if stop_after == "complete":
            assert fare is not None, "提交账单必须指定金额"
            assert payment != "cash" or cash_collected, "现金收款需明确确认已收款"
        self.require_online()
        start_lat, start_lng, end_lat, end_lng = self.coordinates(order_no)
        status, resp = self.api.grab_order(order_no)
        code = resp.get("code")
        assert status == 200 and code in (10000, 10011, 23000), (
            f"接单失败：HTTP={status}, code={code}")
        if code == 10011:
            serving = self.check(self.api.get_serving_order(), "核对已接订单")
            active = serving.get("order_no") or (serving.get("order") or {}).get("order_no")
            assert active == order_no, "已接订单不属于当前司机，停止流转"
        time.sleep(config.GRAB_WAIT)
        # 已出发：POST serviceChange，service_status=1，使用订单上车点坐标。
        self.change(order_no, 1, start_lat, start_lng)
        if stop_after == "pickup":
            return
        # 到达上车点：POST serviceChange，service_status=2，不滑动司机页面。
        self.change(order_no, 2, start_lat, start_lng)
        if stop_after == "onboard":
            return
        # 开始行程：POST serviceChange，service_status=3，不点击接载或填写 UI 尾号。
        self.change(order_no, 3, start_lat, start_lng)
        if stop_after == "destination":
            return
        # 结束行程：POST serviceChange，service_status=4，使用接口返回的真实终点。
        # 不模拟 Socket 轨迹；若服务端拒绝结束（如 code=20156），停止而非绕过校验。
        self.change(order_no, 4, end_lat, end_lng)
        if stop_after == "bill":
            # bill 只到达待确认账单阶段；提交账单需 complete 模式及明确金额。
            return
        # 确认账单：POST /driverApi/order/confirmBill，车费和附加费均通过请求体提交。
        self.check(self.api.confirm_bill(order_no, order_amount=fare, other_amount=surcharge), "确认账单")
        time.sleep(config.STATUS_WAIT)
        if payment == "cash":
            # 状态 5 是确认现金收款，不是确认账单；仅明确已收款时调用该接口。
            self.change(order_no, 5, end_lat, end_lng)
        self.logger.info("司机接口已完成行程及账单；在线支付等待乘客实际支付")

    def wait_completed(self, order_no, timeout, interval=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self.check(self.api.get_trip_detail(order_no), "查询行程完成状态")
            order = data.get("order") or {}
            if order.get("order_status") == 8 and order.get("pay_status") == 1:
                self.logger.info("订单已完成且已支付：%s", order_no)
                return
            time.sleep(interval)
        raise TimeoutError("订单未确认完成且已支付；不会将未支付订单标记成功")
