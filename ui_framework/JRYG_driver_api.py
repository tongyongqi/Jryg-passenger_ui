"""司机端接口操作模块：通过 HTTP API 完成出车、接单、订单流转和确认账单。

本模块替代司机端 UI 操作，通过接口完成全部司机端流程：
  1. 登录（手机号+验证码 → 获取 token）
  2. 出车（handleWorkStatus → online）+ 启动 Socket 位置上报
  3. 接单（polling 等待派单 → grab）
  4. 订单流转（serviceChange: arrival / onboard / destination）
  5. 确认账单（confirmBill）

关键：出车后必须通过 Socket 长连接（gateway:9527）持续上报位置，
否则调度引擎圈选司机时判定"坐标点上传时间不通过"，不会派单。

签名算法（与乘客端不同）：
  1. 收集请求参数 + nonce（时间戳毫秒）
  2. 参数按 key 字母升序排序拼接为 a=1&b=2&...&nonce=xxx
  3. 末尾追加 &key=RCY9H4c9Cc9z6KaKrunTToWsjCERRexY&yg_bundle_version=1.2.2
  4. 对拼接字符串做 MD5 哈希（大写），得到 sign
  5. sign 通过请求头 Sign 传递，nonce 在 body/query 中

token 传递方式：
  - 登录后通过 Cookie: yg_access_token=access-token.xxx 传递
  - access_token 从 smsCodeLogin 响应的 data.sign_info.access_token 获取

本模块不操作手机，不启动 WDA，不依赖 UI 控件树。
全部请求通过 requests 库发送，带超时和重试。
"""

import base64
import hashlib
import json
import logging
import os
import sys
import time

import requests

from ui_framework.JRYG_config import SETTINGS
from ui_framework.JRYG_logger import get_logger

logger = get_logger("JRYG_driver_api")

# 尝试导入已验证的 JRYGSocketClient（来自 JRYG_Passenger_API_HK 项目）
_JRYGSocketClient = None
try:
    _codebuddy_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _codebuddy_root not in sys.path:
        sys.path.insert(0, _codebuddy_root)
    from JRYG_Passenger_API_HK.common.jryg_socket_client import JRYGSocketClient as _JRYGSocketClient
    logger.debug("JRYGSocketClient 已从 JRYG_Passenger_API_HK 加载")
except ImportError as _e:
    logger.debug("JRYGSocketClient 加载失败: %s", _e)

# ==================== 接口路径常量 ====================
# 从真实 App 流量和 JRYG_test_hk_driver_api.py 采集到的司机端 API 路径
PATH_LOGIN_SCENE_CHECK = "/driverApi/passport/loginSceneCheck"  # 登录场景检查
PATH_SEND_CODE = "/driverApi/passport/sendCode"           # 发送验证码
PATH_SMS_CODE_LOGIN = "/driverApi/passport/smsCodeLogin"  # 验证码登录
PATH_HANDLE_WORK_STATUS = "/driverApi/home/v1/handleWorkStatus"  # 出车/收车（注意 v1）
PATH_OUT_CAR_STATUS = "/driverApi/home/outCarStatus"         # 出车状态
PATH_ORDER_GRAB = "/driverApi/order/grab"                    # 接单
PATH_SERVICE_CHANGE = "/driverApi/order/serviceChange"       # 状态流转
PATH_SERVING_ORDER = "/driverApi/order/servingOrder"         # 当前服务订单
PATH_CONFIRM_BILL = "/driverApi/order/confirmBill"           # 确认账单
PATH_ORDER_NEW_DETAIL = "/driverApi/order/newDetail"         # 订单详情
PATH_TRIP_DETAIL = "/driverApi/order/tripDetail"             # 行程详情
PATH_POLLING = "/driverApi/order/polling"                    # 派单轮询
PATH_SERVICE_DETAIL = "/driverApi/order/serviceDetail"       # 服务详情

# ==================== 签名配置 ====================
SIGN_KEY = "RCY9H4c9Cc9z6KaKrunTToWsjCERRexY"
APP_VERSION = "1.2.2"  # 签名中的 yg_bundle_version 值

# ==================== 状态码常量（serviceChange 的 service_status 参数）====================
# 司机端订单状态流转链
STATUS_DEPARTURE = "1"    # 已出发（前往接乘客）
STATUS_ARRIVAL = "2"      # 到达上车地点
STATUS_ONBOARD = "3"      # 开始行程（接载乘客）
STATUS_DESTINATION = "4"  # 结束行程（到达目的地）
STATUS_CONFIRM = "5"      # 确认收款

# 出车/收车
HANDLE_ONLINE = "1"   # 出车上线
HANDLE_OFFLINE = "0"  # 收车下线

# 香港区号
AREA_CODE = "+852"

# 默认超时（秒）
DEFAULT_TIMEOUT = 15
# 派单轮询间隔（秒）
POLLING_INTERVAL = 2
# 派单轮询最大等待（秒），与 order_validation.dispatch_timeout 对齐
POLLING_MAX_WAIT = 90

# 司机定位坐标（香港铜锣湾地铁站）
# 铜锣湾地铁站：22.2839N, 114.1919E
DRIVER_LATITUDE = "22.2839"
DRIVER_LONGITUDE = "114.1919"
# 目的地坐标（大谭郊野公园，用于 arrive_destination 时更新位置）
DEST_LATITUDE = "22.2544"
DEST_LONGITUDE = "114.2097"
# 城市 ID（香港=514）
CITY_ID = "514"
# 设备标识（模拟）
DEVICE_NO = "159f07ea083a69ee-54AFF1ADC15564C60857CF74BE01F08A2A5C926D"
# 定位类型（2=GPS）
LOC_TYPE = "2"

# Socket 网关地址（港版测试环境）
SOCKET_GATEWAY_HOST = "gateway-test.sunlightmobility.hk"
SOCKET_GATEWAY_PORT = 9527


def _generate_sign(params):
    """生成司机端请求签名（MD5 大写）。

    规则：
    1. 参数按 key 字母升序排序拼接为 a=1&b=2&...&nonce=xxx
    2. 末尾追加 &key=SIGN_KEY&yg_bundle_version=APP_VERSION
    3. MD5 哈希并转大写

    :param params: 请求参数字典（已包含 nonce，不含 sign）
    :return: 32 位大写 MD5 签名
    """
    sorted_items = sorted(params.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    sign_str = f"{param_str}&key={SIGN_KEY}&yg_bundle_version={APP_VERSION}"
    return hashlib.md5(sign_str.encode()).hexdigest().upper()


def _resolve_base_url():
    """从配置或环境变量推导 API 域名。"""
    driver_api_config = SETTINGS.get("driver_api") or {}
    if driver_api_config.get("base_url"):
        return driver_api_config["base_url"].rstrip("/")
    env_url = os.environ.get("HK_DRIVER_API_BASE_URL")
    if env_url:
        return env_url.rstrip("/")
    namespace = "test"
    api_catalog = SETTINGS.get("api_catalog") or {}
    if api_catalog.get("namespace"):
        namespace = api_catalog["namespace"]
    inferred = f"http://driver-{namespace}.sunlightmobility.hk"
    logger.warning("driver_api.base_url 未配置，推导为 %s", inferred)
    return inferred


class DriverAPI:
    """司机端接口操作客户端。

    使用方式：
        api = DriverAPI()
        api.login()              # 登录获取 token
        api.go_online()          # 出车
        order = api.wait_for_dispatch()  # 等待派单
        api.accept_order(order)  # 接单
        api.arrive_pickup()      # 到达上车点
        api.pickup_passenger()   # 接载乘客
        api.arrive_destination() # 到达目的地
        api.confirm_bill(fare="5", surcharge="0")  # 确认账单
    """

    def __init__(self, base_url=None, mobile=None, code=None):
        """初始化接口客户端。

        :param base_url: API 域名；留空自动推导。
        :param mobile: 司机手机号；留空从 config 读取。
        :param code: 验证码；留空从 config 读取。
        """
        self.base_url = base_url or _resolve_base_url()
        driver_config = SETTINGS.get("driver") or {}
        self.mobile = mobile or os.environ.get("HK_DRIVER_MOBILE") or driver_config.get("mobile")
        self.code = code or os.environ.get("HK_DRIVER_UI_CODE") or driver_config.get("code")
        self.token = None
        self.order_no = None
        self.session = requests.Session()
        self._socket = None  # Socket 位置上报客户端
        logger.info("【司机接口】base_url=%s, mobile=%s", self.base_url, self.mobile)

    # ==================== 内部方法 ====================

    def _build_hint_content(self):
        """构造 Yg-Header-Hint-Content 头（Base64 编码的 JSON）。

        包含定位信息（loc_lat/loc_lng/loc_type）和城市 ID，
        确保后端识别司机当前城市为香港（city_id=514）。
        """
        hint = {
            "app_timeout_ms": "15",
            "city_id": CITY_ID,
            "device_no": DEVICE_NO,
            "loc_lat": DRIVER_LATITUDE,
            "loc_lng": DRIVER_LONGITUDE,
            "loc_type": LOC_TYPE,
            "timestamp_unix": str(int(time.time())),
        }
        return base64.b64encode(json.dumps(hint).encode()).decode()

    def _build_headers(self, sign=None, content_type="application/x-www-form-urlencoded"):
        """构建统一请求头。"""
        headers = {
            "User-Agent": f"YGDriver/{APP_VERSION}(Android;Android15;V2303A;guangwang)",
            "Accept-Encoding": "gzip",
            "Yg-Language": "zh-HK",
            "Yg-Header-Hint-Content": self._build_hint_content(),
            "Accept-Language": "zh-HK",
            "Content-Type": content_type,
            "Yg-Bundle-Version": APP_VERSION,
        }
        if self.token:
            # token 从 smsCodeLogin 响应获取，格式已为 access-token.xxx
            headers["Cookie"] = f"yg_access_token={self.token}"
        if sign:
            headers["Sign"] = sign
        return headers

    def _post(self, uri, body, timeout=DEFAULT_TIMEOUT):
        """发送 POST 表单请求。

        自动添加 nonce、生成签名、发送请求、解析响应。
        """
        url = f"{self.base_url}{uri}"
        sign_params = dict(body)
        nonce = str(int(time.time() * 1000))
        sign_params["nonce"] = nonce
        sign = _generate_sign(sign_params)

        final_body = dict(body)
        final_body["nonce"] = nonce
        headers = self._build_headers(sign=sign)

        logger.info("【司机接口】POST %s | body=%s | sign=%s", uri, final_body, sign)
        try:
            resp = self.session.post(url, data=final_body, headers=headers, timeout=timeout)
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f"无法连接 {self.base_url}: {e}") from e

        logger.info("【司机接口】响应 status=%d | body=%s", resp.status_code, resp.text[:200])
        return self._parse_response(resp)

    def _get(self, uri, query_params=None, timeout=DEFAULT_TIMEOUT):
        """发送 GET 请求。

        自动添加 nonce、生成签名、发送请求、解析响应。
        """
        url = f"{self.base_url}{uri}"
        sign_params = dict(query_params or {})
        nonce = str(int(time.time() * 1000))
        sign_params["nonce"] = nonce
        sign = _generate_sign(sign_params)

        send_params = dict(query_params or {})
        send_params["nonce"] = nonce
        headers = self._build_headers(sign=sign)

        logger.info("【司机接口】GET %s | params=%s | sign=%s", uri, query_params, sign)
        try:
            resp = self.session.get(url, params=send_params, headers=headers, timeout=timeout)
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f"无法连接 {self.base_url}: {e}") from e

        logger.info("【司机接口】响应 status=%d | body=%s", resp.status_code, resp.text[:200])
        return self._parse_response(resp)

    def _parse_response(self, resp):
        """解析 HTTP 响应为 JSON 并校验业务码。"""
        text = resp.text.strip()
        if not text:
            data = {"code": 10000, "data": {}, "message": ""}
        else:
            try:
                data = resp.json()
            except ValueError:
                logger.error("【司机接口】响应非JSON: %s", text[:200])
                raise RuntimeError(f"响应解析失败: {text[:200]}")

        code_val = data.get("code")
        # 港版接口 code=10000 表示成功
        # 20156="請按照導航繼續送乘客" 是业务提示，不阻断流程
        # 20150="订单状态不正确" 在复用旧订单时可能出现，不阻断
        # 23000="服務暫時出現問題" 在已自动派单时grab会返回，已在前置逻辑跳过
        if code_val not in (10000, 0, 200, None, 20156, 20150):
            msg = data.get("message") or data.get("msg") or "未知错误"
            logger.error("【司机接口】业务失败: code=%s, msg=%s", code_val, msg)
            raise RuntimeError(f"司机接口业务失败: code={code_val}, msg={msg}")

        return data

    # ==================== 登录 ====================

    def login(self):
        """司机登录获取 token。

        流程：
        1. POST /driverApi/passport/sendCode 发送验证码
        2. POST /driverApi/passport/smsCodeLogin 验证码登录，返回 token

        :return: token 字符串
        :raises: RuntimeError 当手机号/验证码未配置或登录失败时
        """
        if not self.mobile:
            raise RuntimeError("司机手机号未配置，请在 config/JRYG_settings.yaml driver.mobile 设置")
        if not self.code:
            raise RuntimeError("司机验证码未配置，请在 config/JRYG_settings.yaml driver.code 设置")

        logger.info("【司机接口】登录: mobile=%s", self.mobile)

        # 步骤1：发送验证码
        try:
            self._post(PATH_SEND_CODE, {
                "country_code": AREA_CODE,
                "business_type": "driver_login_code",
                "mobile": self.mobile,
            })
        except RuntimeError:
            logger.warning("【司机接口】发送验证码失败，测试环境可能使用固定验证码，继续验证")

        # 步骤2：验证码登录
        data = self._post(PATH_SMS_CODE_LOGIN, {
            "country_code": AREA_CODE,
            "code": self.code,
            "codeType": "0",
            "mobile": self.mobile,
        })

        # token 在 data.sign_info.access_token
        sign_info = (data.get("data") or {}).get("sign_info") or {}
        token = sign_info.get("access_token")
        if not token:
            raise RuntimeError(f"司机登录成功但未获取 token，响应 keys={list(data.keys())}")

        self.token = token
        logger.info("【司机接口】登录成功，token 已获取")
        return token

    # ==================== 出车 ====================

    def go_online(self):
        """出车（上线听单）。

        POST /driverApi/home/v1/handleWorkStatus
        参数：car_id=0&event_source=1&lat=xxx&lng=xxx&nonce=xxx&status=1
        """
        logger.info("【司机接口】出车（上线听单），定位：铜锣湾地铁站(%s, %s)", DRIVER_LATITUDE, DRIVER_LONGITUDE)
        data = self._post(PATH_HANDLE_WORK_STATUS, {
            "car_id": "0",
            "event_source": "1",
            "lat": DRIVER_LATITUDE,
            "lng": DRIVER_LONGITUDE,
            "status": HANDLE_ONLINE,
        })
        logger.info("【司机接口】已出车")

        # 出车后启动 Socket 位置上报（调度引擎依赖位置上报圈选司机）
        self._start_socket_location()

        return data

    def go_offline(self):
        """收车（下线）。

        POST /driverApi/home/v1/handleWorkStatus
        参数：car_id=0&event_source=1&lat=xxx&lng=xxx&nonce=xxx&status=0
        """
        logger.info("【司机接口】收车（下线）")
        # 停止 Socket 位置上报
        self._stop_socket_location()
        data = self._post(PATH_HANDLE_WORK_STATUS, {
            "car_id": "0",
            "event_source": "1",
            "lat": DRIVER_LATITUDE,
            "lng": DRIVER_LONGITUDE,
            "status": HANDLE_OFFLINE,
        })
        logger.info("【司机接口】已收车")
        return data

    def _start_socket_location(self):
        """启动 Socket 长连接位置上报（复用 JRYG_Passenger_API_HK 的 JRYGSocketClient）。"""
        if not self.token:
            logger.warning("【司机Socket】未登录，跳过位置上报")
            return
        if self._socket and getattr(self._socket, "connected", False):
            logger.info("【司机Socket】已在运行中，跳过")
            return
        if _JRYGSocketClient is None:
            logger.warning("【司机Socket】JRYGSocketClient 未加载，跳过位置上报；"
                           "调度引擎可能因坐标时效不通过而不派单")
            return
        self._socket = _JRYGSocketClient(
            self.token,
            lat=DRIVER_LATITUDE,
            lng=DRIVER_LONGITUDE,
        )
        if not self._socket.connect():
            logger.warning("【司机Socket】连接失败，调度引擎可能无法派单")
        else:
            logger.info("【司机Socket】位置上报已启动（lat=%s, lng=%s）",
                        DRIVER_LATITUDE, DRIVER_LONGITUDE)

    def _stop_socket_location(self):
        """停止 Socket 位置上报。"""
        if self._socket:
            try:
                self._socket.disconnect()
            except Exception:
                pass
            self._socket = None

    # ==================== 等待派单 ====================

    def wait_for_dispatch(self, max_wait=None):
        """轮询等待派单。

        GET /driverApi/order/polling
        当返回有订单信息时，解析订单号并返回。

        :param max_wait: 最大等待秒数；留空使用 POLLING_MAX_WAIT
        :return: 订单号字符串
        :raises: RuntimeError 当超时无派单时
        """
        max_wait = max_wait or POLLING_MAX_WAIT
        logger.info("【司机接口】等待派单，最多 %d 秒", max_wait)

        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            data = self._get(PATH_POLLING, query_params={"order_type": "0"})
            order_data = data.get("data") or {}
            # 派单数据可能在 data.order 或 data.list 中
            order_no = (
                order_data.get("order_no")
                or order_data.get("orderNo")
                or order_data.get("orderCode")
            )
            if order_no:
                self.order_no = order_no
                # 记录订单状态，用于判断是否需要 grab
                self._dispatched_order_status = order_data.get("order_status", 0)
                self._dispatched_service_status = order_data.get("order_service_status", 0)
                logger.info("【司机接口】收到派单: orderNo=%s, order_status=%s, service_status=%s",
                            order_no, self._dispatched_order_status, self._dispatched_service_status)
                return order_no
            time.sleep(POLLING_INTERVAL)

        raise RuntimeError(f"等待派单超时（{max_wait}秒），未收到订单")

    # ==================== 接单 ====================

    def accept_order(self, order_no=None):
        """接单。

        POST /driverApi/order/grab

        如果 polling 返回的 order_status 已经是 3（已自动派单+接单），
        则跳过 grab，直接返回。

        :param order_no: 订单号；留空使用 wait_for_dispatch 获取的
        """
        order_no = order_no or self.order_no
        if not order_no:
            raise RuntimeError("接单需要订单号，请先调用 wait_for_dispatch 或传入 order_no")

        # order_status=3 且 service_status>=1 表示系统已自动派单，无需手动 grab
        dispatched_status = getattr(self, "_dispatched_order_status", 0)
        if dispatched_status >= 3:
            logger.info("【司机接口】订单 %s 已自动派单(status=%s)，跳过 grab",
                        order_no, dispatched_status)
            self.order_no = order_no
            return {"code": 10000, "data": {}, "message": "auto-dispatched"}

        logger.info("【司机接口】接单: orderNo=%s", order_no)
        data = self._post(PATH_ORDER_GRAB, {"order_no": order_no})
        self.order_no = order_no
        logger.info("【司机接口】已接单")
        return data

    # ==================== 订单流转 ====================

    # 非行程中状态流转间隔（秒）
    FLOW_INTERVAL_NORMAL = 3
    # 行程中状态后等待间隔（秒）——给乘客端足够时间展示行程过程
    FLOW_INTERVAL_ONBOARD = 30

    def depart(self):
        """出发接乘客。

        POST /driverApi/order/serviceChange → service_status=1
        """
        logger.info("【司机接口】出发接乘客")
        data = self._post(PATH_SERVICE_CHANGE, {
            "order_no": self.order_no,
            "service_status": STATUS_DEPARTURE,
            "latitude": DRIVER_LATITUDE,
            "longitude": DRIVER_LONGITUDE,
        })
        logger.info("【司机接口】已出发")
        return data

    def arrive_pickup(self):
        """到达上车点。

        POST /driverApi/order/serviceChange → service_status=2
        """
        logger.info("【司机接口】到达上车点")
        data = self._post(PATH_SERVICE_CHANGE, {
            "order_no": self.order_no,
            "service_status": STATUS_ARRIVAL,
            "latitude": DRIVER_LATITUDE,
            "longitude": DRIVER_LONGITUDE,
        })
        logger.info("【司机接口】已到达上车点")
        return data

    def pickup_passenger(self):
        """接载乘客（已上车，行程中）。

        POST /driverApi/order/serviceChange → service_status=3
        """
        logger.info("【司机接口】接载乘客（行程中）")
        data = self._post(PATH_SERVICE_CHANGE, {
            "order_no": self.order_no,
            "service_status": STATUS_ONBOARD,
            "latitude": DRIVER_LATITUDE,
            "longitude": DRIVER_LONGITUDE,
        })
        logger.info("【司机接口】已接载乘客，等待 %d 秒后继续到达目的地", self.FLOW_INTERVAL_ONBOARD)
        return data

    def arrive_destination(self, dest_lat=None, dest_lng=None):
        """到达目的地。

        POST /driverApi/order/serviceChange → service_status=4

        :param dest_lat: 目的地纬度；留空用默认目的地坐标
        :param dest_lng: 目的地经度；留空用默认目的地坐标
        """
        dest_lat = dest_lat or DEST_LATITUDE
        dest_lng = dest_lng or DEST_LONGITUDE
        logger.info("【司机接口】到达目的地 (%s, %s)", dest_lat, dest_lng)

        # 先更新 Socket 位置到目的地附近
        if self._socket:
            try:
                self._socket.lat = float(dest_lat)
                self._socket.lng = float(dest_lng)
                # 等待位置上报生效（行程中状态后需等待30秒让乘客端展示行程过程）
                logger.info("【司机接口】位置已更新到目的地附近，等待 %d 秒后结束行程",
                            self.FLOW_INTERVAL_ONBOARD)
                time.sleep(self.FLOW_INTERVAL_ONBOARD)
            except Exception:
                pass

        data = self._post(PATH_SERVICE_CHANGE, {
            "order_no": self.order_no,
            "service_status": STATUS_DESTINATION,
            "latitude": dest_lat,
            "longitude": dest_lng,
        })
        logger.info("【司机接口】已到达目的地")
        return data

    # ==================== 确认账单 ====================

    def confirm_bill(self, fare=None, surcharge=None):
        """确认账单。

        POST /driverApi/order/confirmBill

        包车（charter）：不传金额，直接确认。
        打表（meter）：传入车费和附加费。

        :param fare: 车费（打表必传，如 "5"）
        :param surcharge: 附加费（可选，如 "0"）
        """
        body = {"order_no": self.order_no}
        if fare is not None:
            body["order_amount"] = fare
        if surcharge is not None:
            body["other_amount"] = surcharge

        logger.info("【司机接口】确认账单: orderNo=%s, fare=%s, surcharge=%s",
                    self.order_no, fare, surcharge)
        data = self._post(PATH_CONFIRM_BILL, body)
        logger.info("【司机接口】账单已确认")
        return data

    # ==================== 查询方法 ====================

    def get_serving_order(self):
        """获取当前服务订单。

        GET /driverApi/order/servingOrder
        """
        data = self._get(PATH_SERVING_ORDER, query_params={"gaode_imei": "##amap4a0898c0-4419-4a7d-8e4c-6c9b152780ef"})
        order_data = data.get("data") or {}
        order_no = order_data.get("order_no") or order_data.get("orderNo")
        if order_no and not self.order_no:
            self.order_no = order_no
        return data

    def get_order_detail(self, order_no=None):
        """获取订单详情。

        GET /driverApi/order/newDetail
        """
        order_no = order_no or self.order_no
        data = self._get(PATH_ORDER_NEW_DETAIL, query_params={"order_no": order_no})
        return data

    def get_out_car_status(self):
        """获取出车状态。

        GET /driverApi/home/outCarStatus
        """
        data = self._get(PATH_OUT_CAR_STATUS)
        return data

    # ==================== 一键流程 ====================

    def run_full_flow(self, car_type="meter", fare=None, surcharge=None):
        """执行完整司机端接口流程（出车→接单→流转→账单）。

        :param car_type: 车型 "meter"（打表）或 "charter"（包车）
        :param fare: 车费（打表必传）
        :param surcharge: 附加费（可选）
        :return: 订单号
        """
        if not self.token:
            self.login()

        self.go_online()
        order_no = self.wait_for_dispatch()
        self.accept_order(order_no)
        self.depart()
        self.arrive_pickup()
        self.pickup_passenger()
        self.arrive_destination()

        if car_type == "meter":
            self.confirm_bill(fare=fare or "5", surcharge=surcharge or "0")
        else:
            self.confirm_bill()

        logger.info("【司机接口】全流程完成: orderNo=%s", order_no)
        return order_no
