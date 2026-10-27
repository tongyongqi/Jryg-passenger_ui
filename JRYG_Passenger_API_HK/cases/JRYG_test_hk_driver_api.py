"""香港司机端接口自动化测试（纯接口，不依赖设备）。

完整流程：登录 → 出车上线 → 轮询接单 → 状态滑动(到达→开始行程→结束) → 确认账单(填写金额)

接口清单：
  1. GET  /driverApi/passport/loginSceneCheck    登录场景检查（GET, query: country_code+mobile）
  2. POST /driverApi/passport/sendCode           发送验证码（表单: country_code+business_type+mobile）
  3. POST /driverApi/passport/smsCodeLogin       验证码登录（表单: country_code+code+codeType+mobile）
  4. POST /driverApi/home/handleWorkStatus       出车/收车（表单, handle_status: 1=出车, 0=收车）
  5. GET  /driverApi/home/outCarStatus           查询出车状态
  6. POST /driverApi/order/grab                  接单（表单, order_no）
  7. GET  /driverApi/order/servingOrder          查询服务中订单（GET, query: gaode_imei）
  8. POST /driverApi/order/serviceChange         状态变更（表单, order_no+service_status+lat+lng）
  9. POST /driverApi/order/confirmBill           确认账单/填写金额（表单, order_no+order_amount+other_amount）
  10. GET  /driverApi/order/newDetail             订单详情（GET, query: order_no）
  11. GET  /driverApi/order/tripDetail            行程详情（GET, query: order_no）
  12. GET  /driverApi/order/polling               轮询订单（GET, query: order_type）

重要说明：
  - 新订单派发通过 Socket 长连接（gateway-test.sunlightmobility.hk:9527），
    纯 HTTP API 的 polling 只能获取已派发给当前司机的订单（含待接单和服务中）。
  - 纯接口测试时，需先用乘客端API创建订单并确保系统调度引擎将订单派发给目标司机，
    或通过 App 接单后用 API 完成后续状态流转。
  - loginSceneCheck 在登录前调用（secretType=1），签名方式与登录后接口略有不同，
    可能返回"簽名有誤"，但不影响后续 sendCode + smsCodeLogin 流程。

签名算法（与乘客端不同）：
  1. 收集请求参数 + nonce（时间戳毫秒）
  2. 参数按 key 字母升序排序拼接为 a=1&b=2&...&nonce=xxx
  3. 末尾追加 &key=RCY9H4c9Cc9z6KaKrunTToWsjCERRexY&yg_bundle_version=1.2.2
  4. 对拼接字符串做 MD5 哈希（大写），得到 sign
  5. sign 通过请求头传递，nonce 在 body/query 中

token 传递方式：
  - 登录后通过 Cookie: yg_access_token=<access_token> 传递（与乘客端一致）
  - access_token 从 smsCodeLogin 响应的 data.sign_info.access_token 获取

司机端与乘客端签名区别：
  - 司机端签名末尾多加 &yg_bundle_version=1.2.2
  - 乘客端签名末尾只有 &key=SECRET_KEY

service_status 状态流转：
  1 = 已出发（前往接乘客）
  2 = 到达上车地点
  3 = 开始行程
  4 = 结束行程（服务完结）
  5 = 确认收款（需confirmBill填写金额）
"""
import os
import sys
import time
import json
import base64
import hashlib
import pytest

# 将项目根目录添加到 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import requests
except ImportError:
    requests = None

from JRYG_Passenger_API_HK.common.JRYG_logger import logger
from JRYG_Passenger_API_HK.common.hk_config import config


# ==================== 司机端接口配置（从统一配置读取） ====================

# 司机端测试环境基地址
DRIVER_BASE_URL = config.DRIVER_BASE_URL

# 请求超时（秒）
REQUEST_TIMEOUT = config.REQUEST_TIMEOUT

# 司机测试手机号（从App日志获取，司机ID=31, name=T師傅）
DRIVER_MOBILE = config.DRIVER_MOBILE

# 香港区号
AREA_CODE = config.AREA_CODE

# 测试环境固定验证码
TEST_CAPTCHA = config.DRIVER_CAPTCHA

# App 版本信息
APP_VERSION = config.DRIVER_APP_VERSION
APP_TERMINAL = config.DRIVER_APP_TERMINAL
OS_VERSION = config.DRIVER_OS_VERSION
DEVICE_MODEL = config.DRIVER_DEVICE_MODEL
CHANNEL = config.DRIVER_CHANNEL

# 设备标识（从App日志获取）
DEVICE_NO = config.DRIVER_DEVICE_NO

# 高德IMEI（servingOrder接口需要）
GAODE_IMEI = config.DRIVER_GAODE_IMEI

# 城市 ID
CITY_ID = config.CITY_ID

# 登录方式
LOGIN_METHOD = config.LOGIN_METHOD

# 验证码场景值
SMS_SCENE = config.SMS_SCENE

# 签名密钥
SIGN_KEY = config.SIGN_KEY

# 定位坐标（模拟司机位置）
DRIVER_LATITUDE = config.DRIVER_LATITUDE
DRIVER_LONGITUDE = config.DRIVER_LONGITUDE


def _build_driver_hint_content():
    """构造司机端 Yg-Header-Hint-Content 头（Base64 编码的 JSON）。"""
    hint = {
        "app_timeout_ms": "15",
        "city_id": CITY_ID,
        "device_no": DEVICE_NO,
        "loc_lat": DRIVER_LATITUDE,
        "loc_lng": DRIVER_LONGITUDE,
        "loc_type": "12",
        "timestamp_unix": str(int(time.time())),
    }
    return base64.b64encode(json.dumps(hint).encode()).decode()


def _generate_driver_sign(params):
    """生成司机端请求签名（MD5 大写）。

    与乘客端区别：末尾追加 &yg_bundle_version=1.2.2

    :param params: 请求参数字典（已包含 nonce，不含 sign）
    :return: 32 位大写 MD5 签名
    """
    # 第1步：参数按 key 字母升序排序拼接为 a=1&b=2&...&nonce=xxx
    sorted_items = sorted(params.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    # 第2步：末尾追加 &key=SIGN_KEY&yg_bundle_version=1.2.2（司机端特有）
    sign_str = f"{param_str}&key={SIGN_KEY}&yg_bundle_version={APP_VERSION}"
    # 第3步：MD5 哈希并转大写
    return hashlib.md5(sign_str.encode()).hexdigest().upper()


class HKDriverApiClient:
    """香港司机端接口客户端封装。

    签名方式：参数按字母排序 + nonce + &key=SECRET_KEY&yg_bundle_version=1.2.2 → MD5大写
    sign通过请求头传递，nonce在body/query中。
    """

    def __init__(self, base_url=DRIVER_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.timeout = REQUEST_TIMEOUT
        self.access_token = None

    def _build_headers(self, trace_id=None, content_type="application/x-www-form-urlencoded",
                       sign=None):
        """构建统一请求头。"""
        headers = {
            "User-Agent": f"YGDriver/{APP_VERSION}({APP_TERMINAL};{OS_VERSION};{DEVICE_MODEL};{CHANNEL})",
            "Accept-Encoding": "gzip",
            "Yg-Language": "zh-HK",
            "Yg-Header-Hint-Content": _build_driver_hint_content(),
            "Accept-Language": "zh-HK",
            "Content-Type": content_type,
            "Yg-Bundle-Version": APP_VERSION,
        }
        if self.access_token:
            headers["Cookie"] = f"yg_access_token={self.access_token}"
        if sign:
            headers["sign"] = sign
        if trace_id:
            headers["Trace-Id"] = trace_id
        return headers

    def post(self, uri, body, trace_id=None):
        """发送 POST 表单请求并返回响应字典。"""
        url = f"{self.base_url}{uri}"

        # 第1步：构建签名字典（原始参数 + nonce 时间戳毫秒）
        sign_params = dict(body)
        nonce = str(int(time.time() * 1000))
        sign_params["nonce"] = nonce
        # 第2步：生成司机端签名（参数排序 + &key=SIGN_KEY&yg_bundle_version=1.2.2 → MD5）
        sign = _generate_driver_sign(sign_params)

        # 第3步：组装最终请求体（nonce 放在 body 中，sign 通过请求头传递）
        final_body = dict(body)
        final_body["nonce"] = nonce
        headers = self._build_headers(trace_id, sign=sign)

        logger.info(f"【HK Driver API】POST {uri} | body={final_body} | sign={sign}")
        try:
            # 第4步：发送请求（表单格式）
            resp = requests.post(url, data=final_body, headers=headers, timeout=self.timeout)
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(
                f"无法连接 {self.base_url}，请设置 HK_DRIVER_API_BASE_URL 环境变量。\n错误: {e}"
            ) from e

        logger.info(f"【HK Driver API】响应 status={resp.status_code} | body={resp.text}")

        # 第5步：解析响应 JSON
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"raw": resp.text}

        return resp.status_code, resp_json

    def get(self, uri, query_params=None, trace_id=None):
        """发送 GET 请求并返回响应字典。

        nonce 同时放在 URL params 中（供服务端验证签名）。
        使用 requests params 自动 URL 编码（如 +852 → %2B852）。
        """
        url = f"{self.base_url}{uri}"

        # 第1步：构建签名字典（query 参数 + nonce）
        sign_params = dict(query_params or {})
        nonce = str(int(time.time() * 1000))
        sign_params["nonce"] = nonce
        # 第2步：生成签名（与 POST 相同的签名算法）
        sign = _generate_driver_sign(sign_params)

        # 第3步：组装实际发送的 URL 参数（包含 nonce）
        send_params = dict(query_params or {})
        send_params["nonce"] = nonce

        headers = self._build_headers(trace_id, sign=sign)

        logger.info(f"【HK Driver API】GET {uri} | params={query_params} | sign={sign}")
        try:
            # 第4步：发送请求（参数通过 query string 传递）
            resp = requests.get(url, params=send_params, headers=headers, timeout=self.timeout)
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"无法连接 {self.base_url}: {e}") from e

        logger.info(f"【HK Driver API】响应 status={resp.status_code} | body={resp.text}")

        # 第5步：解析响应 JSON
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"raw": resp.text}

        return resp.status_code, resp_json

    # ==================== 接口方法 ====================

    def login_scene_check(self, mobile=DRIVER_MOBILE, trace_id=None):
        """登录场景检查 GET /driverApi/passport/loginSceneCheck。

        App实际请求参数（query string）：
          country_code=+852&mobile=11000005
        """
        return self.get("/driverApi/passport/loginSceneCheck",
                        query_params={"country_code": AREA_CODE, "mobile": mobile},
                        trace_id=trace_id)

    def send_auth_code(self, mobile=DRIVER_MOBILE, trace_id=None):
        """发送验证码 POST /driverApi/passport/sendCode。

        App实际请求body（表单）：
          country_code=+852&business_type=driver_login_code&mobile=11000005
        """
        body = {
            "country_code": AREA_CODE,
            "business_type": "driver_login_code",
            "mobile": mobile,
        }
        return self.post("/driverApi/passport/sendCode", body, trace_id)

    def login(self, mobile=DRIVER_MOBILE, captcha=TEST_CAPTCHA, trace_id=None):
        """验证码登录 POST /driverApi/passport/smsCodeLogin。

        App实际请求body（表单）：
          country_code=+852&code=123456&codeType=0&mobile=11000005

        响应中 data.sign_info.access_token 为登录令牌。
        """
        body = {
            "country_code": AREA_CODE,
            "code": captcha,
            "codeType": "0",
            "mobile": mobile,
        }
        return self.post("/driverApi/passport/smsCodeLogin", body, trace_id)

    def handle_work_status(self, handle_status, event_source=1, trace_id=None):
        """出车/收车 POST /driverApi/home/handleWorkStatus。

        :param handle_status: 1=出车上线, 0=收车下线
        :param event_source: 1=手动操作
        """
        body = {
            "event_source": str(event_source),
            "handle_status": str(handle_status),
        }
        return self.post("/driverApi/home/handleWorkStatus", body, trace_id)

    def get_out_car_status(self, trace_id=None):
        """查询出车状态 POST /driverApi/home/outCarStatus。"""
        return self.post("/driverApi/home/outCarStatus", {}, trace_id)

    def grab_order(self, order_no, trace_id=None):
        """接单 POST /driverApi/order/grab。"""
        body = {"order_no": order_no}
        return self.post("/driverApi/order/grab", body, trace_id)

    def get_serving_order(self, trace_id=None):
        """查询服务中订单 GET /driverApi/order/servingOrder。"""
        return self.get("/driverApi/order/servingOrder",
                        query_params={"gaode_imei": GAODE_IMEI}, trace_id=trace_id)

    def service_change(self, order_no, service_status, latitude=DRIVER_LATITUDE,
                       longitude=DRIVER_LONGITUDE, trace_id=None):
        """状态变更 POST /driverApi/order/serviceChange。

        service_status 流转:
          1=已出发(前往接乘客)
          2=到达上车地点
          3=开始行程
          4=结束行程(服务完结)
          5=确认收款
        """
        body = {
            "order_no": order_no,
            "latitude": str(latitude),
            "service_status": str(service_status),
            "longitude": str(longitude),
        }
        return self.post("/driverApi/order/serviceChange", body, trace_id)

    def confirm_bill(self, order_no, order_amount, other_amount=0, trace_id=None):
        """确认账单/填写金额 POST /driverApi/order/confirmBill。

        :param order_no: 订单号
        :param order_amount: 订单金额
        :param other_amount: 附加费金额
        """
        body = {
            "order_no": order_no,
            "order_amount": str(order_amount),
            "other_amount": str(other_amount),
        }
        return self.post("/driverApi/order/confirmBill", body, trace_id)

    def get_order_new_detail(self, order_no, trace_id=None):
        """订单详情 GET /driverApi/order/newDetail。"""
        return self.get("/driverApi/order/newDetail",
                        query_params={"order_no": order_no}, trace_id=trace_id)

    def get_trip_detail(self, order_no, trace_id=None):
        """行程详情 GET /driverApi/order/tripDetail。"""
        return self.get("/driverApi/order/tripDetail",
                        query_params={"order_no": order_no}, trace_id=trace_id)

    def polling_order(self, order_type=0, trace_id=None):
        """轮询订单 GET /driverApi/order/polling。"""
        return self.get("/driverApi/order/polling",
                        query_params={"order_type": str(order_type)}, trace_id=trace_id)

    def get_service_detail(self, order_no, trace_id=None):
        """服务详情 GET /driverApi/order/serviceDetail。"""
        return self.get("/driverApi/order/serviceDetail",
                        query_params={"order_no": order_no}, trace_id=trace_id)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
