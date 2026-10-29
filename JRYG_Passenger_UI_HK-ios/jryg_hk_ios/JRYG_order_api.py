"""测试环境订单校验通道；复用签名，禁止自动登录、全量清单或记录凭据。

关键约束：
  - 只允许访问测试环境域名，禁止访问生产地址。
  - 乘客端 token 与 App 登录互踢，乘客端不可用时降级用司机端接口核实。
  - 写操作失败一律抛错，禁止盲目重试造成重复下单。
"""

import json
import logging
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlparse

import requests

from jryg_hk_ios.JRYG_order_guard import OrderValidationError, number, require

logger = logging.getLogger("JRYG_HK_ios")


class HKOrderAPI:
    """乘客端 + 司机端订单接口封装（仅测试环境）。"""

    # 允许访问的测试环境主机白名单
    ALLOWED_HOSTS = {"app-client-test.sunlightmobility.hk", "driver-test.sunlightmobility.hk",
                     "localhost", "127.0.0.1"}

    def __init__(self, passenger, driver, passenger_sign, driver_sign, driver_id):
        """绑定乘客端/司机端客户端与签名函数，并校验目标环境与司机身份。"""
        # 乘客端/司机端 HTTP 客户端
        self.passenger, self.driver = passenger, driver
        # 两侧各自的签名函数
        self.passenger_sign, self.driver_sign = passenger_sign, driver_sign
        # 目标司机 ID（11000005）
        self.driver_id = str(driver_id)
        for client in (passenger, driver):
            parsed = urlparse(client.base_url)
            # 必须命中白名单且不得在 URL 中携带用户名密码
            require(parsed.scheme in ("http", "https") and parsed.hostname in self.ALLOWED_HOSTS
                    and not parsed.username and not parsed.password,
                    "订单自动重试仅允许已确认的测试环境地址")
        # 乘客端 token 可选（与 App 登录互踢，改用司机端降级）
        require(bool(driver.access_token), "缺少司机端会话token，禁止创建订单")
        self.http = requests.Session()

    @classmethod
    def from_environment(cls):
        """需司机会话文件；乘客端 token 可选（与 App 登录互踢，改用司机端降级）。"""
        # 乘客端 token 允许为空
        token = os.environ.get("HK_PASSENGER_ACCESS_TOKEN", "")
        # 司机会话文件路径是硬性前提
        session_path = os.environ.get("HK_DRIVER_SESSION_FILE")
        require(bool(session_path),
                "需要 HK_DRIVER_SESSION_FILE（11000005成功登录的JSON回包）；缺少时直接失败，不下单")
        try:
            session = json.loads(Path(session_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise OrderValidationError("无法读取司机会话JSON文件") from None
        # 先校验会话确属 11000005，再使用其中的 token
        identity, driver_token = cls.validate_driver_session(session)
        root = str(Path(__file__).resolve().parents[2])
        if root not in sys.path:
            # 让 API 用例目录可被导入，复用既有签名实现
            sys.path.insert(0, root)
        from JRYG_Passenger_API_HK.cases.JRYG_test_hk_api import HKApiClient, _generate_sign
        from JRYG_Passenger_API_HK.cases.JRYG_test_hk_driver_api import (
            HKDriverApiClient, _generate_driver_sign,
        )
        passenger, driver = HKApiClient(), HKDriverApiClient()
        passenger.access_token, driver.access_token = token, driver_token
        return cls(passenger, driver, _generate_sign, _generate_driver_sign, identity)

    @staticmethod
    def validate_driver_session(session):
        """校验司机会话文件格式与身份，返回 (driver_id, access_token)。

        必须是 11000005 的成功登录回包，否则拒绝运行。
        """
        require(isinstance(session, dict) and session.get("code") == 10000,
                "司机会话文件不是成功登录回包")
        data = session.get("data", {})
        require(isinstance(data, dict), "司机登录data格式错误")
        info, sign = data.get("driver_info", {}), data.get("sign_info", {})
        require(isinstance(info, dict) and isinstance(sign, dict), "司机登录缺少身份字段")
        # 去掉空格与横线后比较，避免格式差异导致误判
        phone = str(info.get("driver_phone", "")).replace(" ", "").replace("-", "")
        mobile = str(sign.get("mobile", "")).replace(" ", "").replace("-", "")
        accepted = {"11000005", "+85211000005", "85211000005"}
        require(phone in accepted and mobile in accepted, "司机会话不属于11000005，停止运行")
        driver_id = number(info.get("driver_id"), "driver_info.driver_id")
        require(driver_id > 0 and bool(sign.get("access_token")), "司机会话缺少ID或token")
        return str(driver_id), sign["access_token"]

    def request(self, side, method, uri, params):
        """发起一次已签名的接口请求并返回 data 对象。

        乘客端 token 失效（10301）时抛出带 10301 的错误，由调用方决定降级；
        其它失败一律抛错，禁止盲目重试写操作。
        """
        client = self.passenger if side == "passenger" else self.driver
        signer = self.passenger_sign if side == "passenger" else self.driver_sign
        # 乘客端 token 为空（与 App 登录互踢，不使用），直接抛 10301 触发降级
        if side == "passenger" and not client.access_token:
            raise OrderValidationError(f"{uri} 10301 乘客端 token 为空，降级用司机端接口")
        # nonce 使用毫秒时间戳防止重放
        values = dict(params, nonce=str(int(time.time() * 1000)))
        headers = client._build_headers(sign=signer(values))
        # GET 用 query，其它方法用 body
        kwargs = {"params" if method == "GET" else "data": values}
        try:
            response = self.http.request(method, client.base_url + uri, headers=headers,
                                         timeout=(3, 12), allow_redirects=False, **kwargs)
            require(response.status_code == 200, f"{uri} HTTP失败: {response.status_code}")
            body = response.json()
        except (requests.RequestException, ValueError):
            # 网络异常或非 JSON 响应：写操作结果未知，不自动重试
            raise OrderValidationError(f"{uri} 请求失败或响应不是JSON，禁止盲目重试写操作") from None
        # 乘客端 token 被 App 登录挤掉时返回 10301，由调用方决定降级处理
        code = body.get("code") if isinstance(body, dict) else None
        msg = body.get("message", "") if isinstance(body, dict) else ""
        if code == 10301 or "登入已過期" in str(msg):
            raise OrderValidationError(f"{uri} 10301 {msg}")
        require(isinstance(body, dict) and code == 10000,
                f"{uri} 业务失败，不能当作操作成功")
        data = body.get("data")
        require(isinstance(data, dict), f"{uri} 缺少data对象")
        return data

    def unfinished(self):
        """查询乘客端未完成订单。

        如果乘客端 token 被 App 登录挤掉（10301），降级为司机端 servingOrder：
        若 11000005 无在途订单则视为乘客端也无未完成订单，避免 token 互踢死循环。
        """
        try:
            return self.request("passenger", "POST", "/passenger/order/unfinishList", {}).get("list")
        except OrderValidationError as e:
            # 只有 token 失效才降级，其它错误直接上抛
            if "10301" not in str(e) and "登入已過期" not in str(e):
                raise
            logger.warning("乘客端 token 失效，降级用司机端 servingOrder 核实无在途订单")
            serving = self.request("driver", "GET", "/driverApi/order/servingOrder",
                                   {"gaode_imei": "##amapf210603d-ef00-4912-b3af-47b776a426ef"})
            # servingOrder 返回 data 为 None 或空表示无在途订单
            if serving is None or not serving:
                return []
            # 如果司机端有在途订单，需要返回与乘客端格式兼容的列表
            if isinstance(serving, dict) and serving.get("order_no"):
                return [serving]
            if isinstance(serving, list):
                return serving
            return []

    def status(self, no):
        """查询乘客端订单状态。token 失效时降级用司机端 tripDetail。"""
        try:
            return self.request("passenger", "GET", "/passenger/order/status", {"order_no": no})
        except OrderValidationError as e:
            if "10301" not in str(e) and "登入已過期" not in str(e):
                raise
            logger.warning("乘客端 token 失效，降级用司机端 tripDetail 查询订单状态")
            detail = self.trip_detail(no)
            order = detail.get("order", {})
            # 组装成与乘客端 status 相同的结构返回
            return {
                "order_no": no,
                "order_status": order.get("order_status"),
                "driver_id": order.get("driver_id"),
            }

    def prepare_cancel(self, no):
        """取消前置校验：存在取消费用或未知提示时禁止自动取消。"""
        data = self.request("passenger", "POST", "/passenger/order/prepareCancel", {"order_no": no})
        require(data.get("cancel_type") == 0 and data.get("alert_type") == 0 and
                not data.get("limit_cancel_notice") and
                data.get("buyout_cancel_tip", "") in ("", "馬上為您找到司機了，您確定不再等等嗎？"),
                "取消存在限制、费用或未知提示，停止自动取消")
        return data

    def cancel(self, no):
        """取消指定订单。"""
        return self.request("passenger", "POST", "/passenger/order/cancel", {"order_no": no})

    def trip_detail(self, no):
        """查询司机端行程详情。"""
        return self.request("driver", "GET", "/driverApi/order/tripDetail", {"order_no": no})

    def service_detail(self, no):
        """查询司机端服务详情，并校验确属当前订单且未取消。"""
        data = self.request("driver", "GET", "/driverApi/order/serviceDetail", {"order_no": no})
        # 订单号必须一致，防止拿到其它订单数据
        require(data.get("order_no") == no, "司机服务详情不是当前绑定订单")
        require(isinstance(data.get("order"), dict) and isinstance(data.get("service"), dict),
                "司机服务详情缺少order/service")
        require(number(data["order"].get("order_status"), "driver.order_status") != 9,
                "司机服务详情显示订单已取消")
        return data

    def service_change(self, no, status, latitude, longitude):
        """更新司机端服务状态（如接驾、到达等）并上报坐标。"""
        return self.request("driver", "POST", "/driverApi/order/serviceChange", {
            "order_no": no, "service_status": str(status),
            "latitude": str(latitude), "longitude": str(longitude),
        })

    def confirm_bill(self, no, amount):
        """确认账单金额（现金场景使用）。"""
        return self.request("driver", "POST", "/driverApi/order/confirmBill", {
            "order_no": no, "order_amount": str(amount), "other_amount": "0",
        })

    def close(self):
        """关闭底层 HTTP 连接。"""
        self.http.close()
