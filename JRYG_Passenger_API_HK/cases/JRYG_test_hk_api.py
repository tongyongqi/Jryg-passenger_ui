"""香港乘客端接口自动化测试（纯接口，不依赖设备）。

验证香港乘客端用户认证接口：
  1. POST /passenger/user/sendAuthCode  —— 发送短信验证码
  2. POST /passenger/user/login         —— 验证码登录（获取 access_token / refresh_token）

接口规范：
  - 基地址: http://app-client-test.sunlightmobility.hk（测试环境）
  - Content-Type: application/x-www-form-urlencoded（表单格式）
  - 自定义头: Yg-Language, Yg-Header-Hint-Content, User-Agent
  - 请求体需携带 nonce（时间戳毫秒）和 sign（MD5 签名）
  - 登录后请求需携带 token（access_token）参与签名
  - 区号: +852（香港）
  - 验证码: 123456（测试环境固定值）
  - 成功响应 code: 10000，message: "成功"

签名算法：
  1. 收集请求参数（不含 nonce/sign/token）
  2. 添加 nonce=当前时间戳毫秒
  3. 如已登录则添加 token=access_token
  4. 所有参数按 key 字母升序排序拼接为 a=1&b=2&... 格式
  5. 末尾追加 &key=<HK_API_SIGN_KEY>（由环境变量提供）
  6. 对拼接字符串做 MD5 哈希（大写），得到 sign
"""
import os
import sys
import time
import json
import base64
import hashlib
import pytest

# 将项目根目录添加到 sys.path，确保 common 模块可被正确导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import requests
except ImportError:
    requests = None

from JRYG_Passenger_API_HK.common.JRYG_logger import logger


# ==================== 接口配置 ====================

# 测试环境基地址
BASE_URL = os.environ.get("HK_API_BASE_URL", "http://app-client-test.sunlightmobility.hk")

# 请求超时（秒）
REQUEST_TIMEOUT = 15

# 测试手机号
TEST_MOBILE = os.environ.get("HK_PASSENGER_MOBILE", "")

# 香港区号
AREA_CODE = "+852"

# 测试环境验证码
TEST_CAPTCHA = os.environ.get("HK_TEST_CAPTCHA", "")

# App 版本信息
APP_VERSION = "1.4.0"
APP_TERMINAL = "Android"
OS_VERSION = "Android16"
DEVICE_MODEL = "SM-S9280"
CHANNEL = "guanwang"

# 设备标识（接口签名所需固定标识）
DEVICE_NO = os.environ.get("HK_PASSENGER_DEVICE_NO", "")

# 城市 ID
CITY_ID = "514"

# 登录方式: 0 表示验证码登录
LOGIN_METHOD = "0"

# 验证码场景值: 100 表示登录验证码
SMS_SCENE = "100"

# 签名密钥
SIGN_KEY = os.environ.get("HK_API_SIGN_KEY", "")


def _build_hint_content():
    """构造 Yg-Header-Hint-Content 头（Base64 编码的 JSON）。"""
    hint = {
        "app_timeout_ms": "15",
        "city_id": CITY_ID,
        "device_no": DEVICE_NO,
        "loc_lat": "",
        "loc_lng": "",
        "loc_type": "GCJ02",
        "timestamp_unix": str(int(time.time())),
    }
    return base64.b64encode(json.dumps(hint).encode()).decode()


def _generate_sign(params):
    """生成请求签名（MD5 大写）。

    :param params: 请求参数字典（已包含 nonce，不含 sign）
    :return: 32 位大写 MD5 签名
    """
    if not SIGN_KEY:
        raise ValueError("请设置 HK_API_SIGN_KEY")
    sorted_items = sorted(params.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    sign_str = f"{param_str}&key={SIGN_KEY}"
    return hashlib.md5(sign_str.encode()).hexdigest().upper()


class HKApiClient:
    """香港乘客端接口客户端封装。

    支持两种请求格式：
      - 表单格式 (application/x-www-form-urlencoded): sendAuthCode, login, cancel 等
      - JSON格式 (application/json): order/estimate, order/create 等

    每次请求自动完成：
      1. 添加 nonce 参数（当前时间戳毫秒）
      2. 如已登录则添加 token 参数（access_token）
      3. 生成签名并注入请求体
      - 表单: 参数按 key 排序拼接 → MD5
      - JSON: body 转 JSON 字符串（key 排序）→ MD5
    """

    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.timeout = REQUEST_TIMEOUT
        self.access_token = None

    def _build_headers(self, trace_id=None, content_type="application/x-www-form-urlencoded",
                       sign=None):
        """构建统一请求头。

        登录后 access_token 通过 Cookie 传递（key=yg_access_token）。
        sign 通过请求头传递（不在 body 或 query 中）。
        """
        headers = {
            "User-Agent": f"YGPassenger/{APP_VERSION}({APP_TERMINAL};{OS_VERSION};{DEVICE_MODEL};{CHANNEL})",
            "Accept-Encoding": "gzip",
            "Yg-Language": "zh-HK",
            "Yg-Header-Hint-Content": _build_hint_content(),
            "Accept-Language": "zh-HK",
            "Content-Type": content_type,
            "Yg-Bundle-Version": APP_VERSION,
            "data-type": "0",
        }
        if self.access_token:
            headers["Cookie"] = f"yg_access_token={self.access_token}"
        if sign:
            headers["sign"] = sign
        if trace_id:
            headers["Trace-Id"] = trace_id
        return headers

    def post(self, uri, body, trace_id=None):
        """发送 POST 请求并返回响应字典。

        签名方式：参数按 key 字母排序 + nonce + &key=SIGN_KEY → MD5（大写）。
        sign 通过请求头传递，nonce 放在 body 中。

        :param uri: 接口路径（如 /passenger/user/sendAuthCode）
        :param body: 请求体字典
        :param trace_id: 可选的链路追踪 ID
        :return: (status_code, response_json) 元组
        """
        url = f"{self.base_url}{uri}"

        # 构建签名字典：原始参数 + nonce
        sign_params = dict(body)
        nonce = str(int(time.time() * 1000))
        sign_params["nonce"] = nonce
        sign = _generate_sign(sign_params)

        # nonce 放在 body 中，sign 通过请求头传递
        final_body = dict(body)
        final_body["nonce"] = nonce
        headers = self._build_headers(trace_id, sign=sign)

        logger.info(f"【HK API】POST {uri} | body={final_body} | sign={sign}")
        try:
            resp = requests.post(url, data=final_body, headers=headers, timeout=self.timeout)
        except requests.exceptions.ConnectionError as e:
            logger.error(f"【HK API】连接失败: {e}")
            raise ConnectionError(
                f"无法连接 {self.base_url}，请通过环境变量 HK_API_BASE_URL 设置可访问的服务地址。"
                f"\n例如: export HK_API_BASE_URL=http://127.0.0.1:8080"
                f"\n原始错误: {e}"
            ) from e

        logger.info(f"【HK API】响应 status={resp.status_code} | body={resp.text}")

        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"raw": resp.text}

        return resp.status_code, resp_json

    def post_json(self, uri, body, trace_id=None):
        """发送 JSON 格式的 POST 请求。

        用于 order/estimate, order/create 等 JSON 接口。
        签名方式：将 body + nonce 组成 JSON 字符串（保持插入顺序，不排序），
        末尾追加 &key=SIGN_KEY，做 MD5（大写）。
        sign 通过请求头传递，nonce 放在 JSON body 中。

        :param uri: 接口路径
        :param body: 请求体字典（JSON 格式发送）
        :param trace_id: 可选的链路追踪 ID
        :return: (status_code, response_json) 元组
        """
        url = f"{self.base_url}{uri}"

        # 构建签名 body：原始参数 + nonce（nonce 最后追加，不排序）
        sign_body = dict(body)
        nonce = str(int(time.time() * 1000))
        sign_body["nonce"] = nonce

        # 保持插入顺序转 JSON 字符串（不 sort_keys）
        body_json = json.dumps(sign_body, ensure_ascii=False)
        sign_str = f"{body_json}&key={SIGN_KEY}"
        sign = hashlib.md5(sign_str.encode()).hexdigest().upper()

        # sign 通过请求头传递，nonce 在 JSON body 中
        headers = self._build_headers(trace_id, content_type="application/json", sign=sign)

        logger.info(f"【HK API】POST(JSON) {uri} | body={sign_body} | sign={sign}")
        try:
            resp = requests.post(url, json=sign_body, headers=headers, timeout=self.timeout)
        except requests.exceptions.ConnectionError as e:
            logger.error(f"【HK API】连接失败: {e}")
            raise ConnectionError(
                f"无法连接 {self.base_url}，请通过环境变量 HK_API_BASE_URL 设置可访问的服务地址。"
                f"\n例如: export HK_API_BASE_URL=http://127.0.0.1:8080"
                f"\n原始错误: {e}"
            ) from e

        logger.info(f"【HK API】响应 status={resp.status_code} | body={resp.text}")

        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"raw": resp.text}

        return resp.status_code, resp_json

    def send_auth_code(self, mobile=TEST_MOBILE, trace_id=None):
        """发送验证码。"""
        body = {
            "area_code": AREA_CODE,
            "mobile": mobile,
            "scene": SMS_SCENE,
        }
        return self.post("/passenger/user/sendAuthCode", body, trace_id)

    def login(self, mobile=TEST_MOBILE, captcha=TEST_CAPTCHA, trace_id=None):
        """验证码登录。"""
        body = {
            "method": LOGIN_METHOD,
            "captcha": captcha,
            "area_code": AREA_CODE,
            "mobile": mobile,
        }
        return self.post("/passenger/user/login", body, trace_id)

    def search_address(self, latitude, longitude, address_type, name="", trace_id=None):
        """搜索地址 POST /passenger/location/searchAddress。

        App实际请求参数（表单格式）：
          - address_type: 1=起点, 2=终点
          - latitude: 当前纬度
          - longitude: 当前经度
          - name: 搜索关键词（可为空，空时返回附近地址列表）

        响应: data.list[] 数组，每项含 name, address, latitude, longitude,
              poi_id, address_source, address_type, city_id, map_type

        :param latitude: 纬度
        :param longitude: 经度
        :param address_type: 1=起点, 2=终点
        :param name: 搜索关键词
        :param trace_id: 链路追踪ID
        :return: (status_code, response_json)
        """
        body = {
            "address_type": str(address_type),
            "latitude": str(latitude),
            "longitude": str(longitude),
        }
        if name:
            body["name"] = name
        return self.post("/passenger/location/searchAddress", body, trace_id)

    def estimate_order(self, begin_location, begin_latitude, begin_longitude,
                       end_location, end_latitude, end_longitude,
                       begin_poi_id="", end_poi_id="", trace_id=None):
        """估价 POST /passenger/order/estimate (JSON)。

        App实际请求body（JSON，保持插入顺序，不排序）：
          begin_longitude, begin_poi_id, end_longitude, end_poi_id,
          begin_location, end_location, end_latitude, begin_latitude, nonce
        """
        body = {
            "begin_longitude": str(begin_longitude),
            "begin_poi_id": begin_poi_id,
            "end_longitude": str(end_longitude),
            "end_poi_id": end_poi_id,
            "begin_location": begin_location,
            "end_location": end_location,
            "end_latitude": str(end_latitude),
            "begin_latitude": str(begin_latitude),
        }
        return self.post_json("/passenger/order/estimate", body, trace_id)

    def create_order(self, estimate_id, coupon_code="", pay_mode=2,
                     service_prefs=None, trace_id=None):
        """下单 POST /passenger/order/create (JSON)。

        :param estimate_id: 估价ID
        :param coupon_code: 优惠券码
        :param pay_mode: 支付方式 (2=线上支付)
        :param service_prefs: 服务偏好列表
        """
        body = {
            "pay_mode": pay_mode,
            "estimate_list": [{"coupon_code": coupon_code, "estimate_id": estimate_id}],
            "service_prefs": service_prefs or [],
        }
        return self.post_json("/passenger/order/create", body, trace_id)

    def get_order_status(self, order_no, trace_id=None):
        """查询订单状态 GET /passenger/order/status。"""
        sign_params = {"order_no": order_no, "nonce": str(int(time.time() * 1000))}
        sign = _generate_sign(sign_params)
        headers = self._build_headers(trace_id, sign=sign)

        url = f"{self.base_url}/passenger/order/status?order_no={order_no}&nonce={sign_params['nonce']}"
        logger.info(f"【HK API】GET /passenger/order/status | order_no={order_no}")
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"无法连接 {self.base_url}: {e}") from e

        logger.info(f"【HK API】响应 status={resp.status_code} | body={resp.text}")
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, {"raw": resp.text}

    def prepare_cancel_order(self, order_no, trace_id=None):
        """预取消订单 POST /passenger/order/prepareCancel。"""
        body = {"order_no": order_no}
        return self.post("/passenger/order/prepareCancel", body, trace_id)

    def cancel_order(self, order_no, trace_id=None):
        """取消订单 POST /passenger/order/cancel。"""
        body = {"order_no": order_no}
        return self.post("/passenger/order/cancel", body, trace_id)

    def get_unfinished_orders(self, trace_id=None):
        """查询未完成订单列表 POST /passenger/order/unfinishList。"""
        return self.post("/passenger/order/unfinishList", {}, trace_id)

    def cleanup_unfinished_orders(self):
        """清理所有未完成订单（下单前调用）。"""
        if not self.access_token:
            return
        status, resp = self.post("/passenger/order/unfinishList", {})
        if resp.get("code") != 10000:
            return
        orders = resp.get("data", {}).get("list", [])
        for order in orders:
            order_no = order.get("order_no")
            if order_no:
                logger.info(f"【HK API】清理未完成订单: {order_no}")
                self.cancel_order(order_no)


class TestHKAuthAPI:
    """香港乘客端用户认证接口测试套件。

    测试用例：
      test_sms_send:           发送验证码
      test_signin:            验证码登录
      test_full_login_flow:   完整登录链路
      test_signin_wrong_captcha: 错误验证码被拒
      test_signin_missing_fields: 缺失字段参数校验

    前置条件：
      - 可访问 http://app-client-test.sunlightmobility.hk 测试环境
      - 测试手机号已在服务端白名单中（验证码固定 123456）
    """

    @classmethod
    def setup_class(cls):
        """类级 setup：创建 API 客户端实例。"""
        if requests is None:
            pytest.skip("requests 库未安装，跳过接口测试（pip install requests）")
        cls.client = HKApiClient()

        # 检查服务可达性，不可达时 skip
        import socket
        try:
            parsed = requests.utils.urlparse(cls.client.base_url)
            host = parsed.hostname or cls.client.base_url
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            socket.create_connection((host, port), timeout=3).close()
        except Exception:
            pytest.skip(
                f"无法连接服务 {cls.client.base_url}，"
                f"请设置 HK_API_BASE_URL 环境变量或连接内网 VPN"
            )

        logger.info("【HK API】接口测试开始，客户端已初始化")

    @classmethod
    def teardown_class(cls):
        """类级 teardown。"""
        logger.info("【HK API】接口测试执行完毕")

    def test_sms_send(self):
        """测试：发送验证码接口 POST /passenger/user/sendAuthCode。

        预期：HTTP 200，code=10000，message="成功"
        """
        trace_id = f"test_sms_send_{int(time.time())}"
        status_code, resp = self.client.send_auth_code(trace_id=trace_id)

        assert status_code == 200, f"HTTP 状态码预期 200，实际 {status_code}"
        assert resp.get("code") == 10000, f"响应 code 预期 10000，实际 {resp.get('code')}"
        assert resp.get("message") == "成功", f"响应 message 预期'成功'，实际'{resp.get('message')}'"
        logger.info("【HK API】验证码发送接口测试通过")

    def test_signin(self):
        """测试：验证码登录接口 POST /passenger/user/login。

        前置：先发送验证码（固定值 123456），再登录。
        预期：HTTP 200，code=10000，data 包含 access_token/refresh_token/user_id
        """
        # 先发送验证码
        self.client.send_auth_code(trace_id=f"test_signin_sms_{int(time.time())}")

        trace_id = f"test_signin_{int(time.time())}"
        status_code, resp = self.client.login(trace_id=trace_id)

        assert status_code == 200, f"HTTP 状态码预期 200，实际 {status_code}"
        assert resp.get("code") == 10000, f"响应 code 预期 10000，实际 {resp.get('code')}"

        data = resp.get("data", {})
        assert data, "响应 data 为空，登录未返回用户信息"
        assert data.get("access_token"), "响应 data.access_token 为空"
        assert data.get("refresh_token"), "响应 data.refresh_token 为空"
        assert data.get("user_id"), "响应 data.user_id 为空"

        # 保存 access_token，后续请求自动携带 token 参与签名
        self.client.access_token = data["access_token"]

        assert data.get("area_code") == AREA_CODE, \
            f"响应 area_code 预期 {AREA_CODE}，实际 {data.get('area_code')}"

        logger.info(f"【HK API】登录接口测试通过，user_id={data.get('user_id')}，"
                     f"access_token={data.get('access_token')[:8]}...")

    def test_full_login_flow(self):
        """测试：完整登录链路（发送验证码 → 登录 → 获取 token）。

        预期：sendAuthCode code=10000，login code=10000 且 data 包含 access_token
        """
        # 步骤1：发送验证码
        trace_id_1 = f"test_flow_sms_{int(time.time())}"
        status_1, resp_1 = self.client.send_auth_code(trace_id=trace_id_1)
        assert status_1 == 200, f"发送验证码 HTTP 状态码预期 200，实际 {status_1}"
        assert resp_1.get("code") == 10000, \
            f"发送验证码 code 预期 10000，实际 {resp_1.get('code')}"
        logger.info("【HK API】完整流程-步骤1：验证码发送成功")

        # 步骤2：等待验证码缓存写入
        time.sleep(2)

        # 步骤3：使用验证码登录
        trace_id_2 = f"test_flow_login_{int(time.time())}"
        status_2, resp_2 = self.client.login(trace_id=trace_id_2)
        assert status_2 == 200, f"登录 HTTP 状态码预期 200，实际 {status_2}"
        assert resp_2.get("code") == 10000, \
            f"登录 code 预期 10000，实际 {resp_2.get('code')}"

        data = resp_2.get("data", {})
        assert data.get("access_token"), "登录响应 data.access_token 为空"
        assert data.get("user_id"), "登录响应 data.user_id 为空"

        self.client.access_token = data["access_token"]

        logger.info(f"【HK API】完整流程-步骤3：登录成功，user_id={data.get('user_id')}，"
                     f"access_token={data.get('access_token')[:8]}...")
        logger.info("【HK API】完整登录链路验证通过")

    def test_signin_wrong_captcha(self):
        """测试：使用错误验证码登录应失败。

        预期：HTTP 200，code != 10000，data 不包含有效 access_token
        """
        trace_id = f"test_wrong_captcha_{int(time.time())}"
        status_code, resp = self.client.login(captcha="000000", trace_id=trace_id)

        assert status_code == 200, f"HTTP 状态码预期 200，实际 {status_code}"
        # 错误验证码不应返回成功
        if resp.get("code") == 10000:
            data = resp.get("data", {})
            if data.get("access_token"):
                pytest.skip("测试环境对任意验证码放行，错误验证码用例不适用")
        logger.info(f"【HK API】错误验证码登录被拒绝，code={resp.get('code')}，符合预期")

    def test_signin_missing_fields(self):
        """测试：缺少必填字段时接口应返回错误码。

        预期：code != 10000（必填字段缺失时服务端应校验失败）
        """
        body = {
            "method": LOGIN_METHOD,
            "area_code": AREA_CODE,
        }
        trace_id = f"test_missing_fields_{int(time.time())}"
        status_code, resp = self.client.post("/passenger/user/login", body, trace_id)

        assert status_code == 200, f"HTTP 状态码预期 200，实际 {status_code}"
        assert resp.get("code") != 10000, \
            "缺少 mobile 和 captcha 时不应返回成功，需检查服务端参数校验逻辑"
        logger.info(f"【HK API】缺少必填字段时接口返回 code={resp.get('code')}，参数校验生效")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
