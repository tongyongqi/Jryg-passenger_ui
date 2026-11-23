"""香港乘客端 V1.6.0 独立 HTTP 接口测试（连接真实测试环境）。

编写时间：2026-11-19
数据来源：真实测试环境 app-client-test.sunlightmobility.hk，不发 mock 请求。

覆盖接口（V1.6.0 需求文档明确给出的接口）：
- POST /passenger/order/estimate    询价
- GET  /passenger/order/status      订单状态
- GET  /passenger/order/detail      订单详情
- GET  /passenger/charge/rule       计价规则

测试原则（99% 真实）：
1. 所有请求发往真实测试环境 app-client-test.sunlightmobility.hk。
2. 认证 token 从环境变量 V160_AUTH_TOKEN 获取（真实登录后获取的 token），
   未提供时 skip 并标注「需真实登录后传入 token」，不伪造 token。
3. 询价用真实路线坐标（北角地铁站 → 香港大学，来自 config/JRYG_settings.yaml）。
4. 订单状态/详情/计价规则需要真实订单号（V160_REAL_ORDER_NO），
   未提供时 skip，不伪造订单号。
5. 不对创建订单、支付、取消等变更操作自动重试。
6. TLS 证书验证保持开启（verify=True）。

前置条件：
- 测试环境可达（app-client-test.sunlightmobility.hk）
- 已获取真实 auth token（V160_AUTH_TOKEN）
- 已有真实订单号（V160_REAL_ORDER_NO，用于查询类接口）

运行：
  V160_AUTH_TOKEN=xxx V160_REAL_ORDER_NO=THXXXXXXX \
  pytest cases/passenger_v1_6_0/test_v160_http_api_real.py -v
"""

import os
import sys

import pytest
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ---------------------------------------------------------------------------
# 真实环境配置（从环境变量获取，不硬编码凭据）
# ---------------------------------------------------------------------------
_BASE_URL = os.environ.get(
    "V160_API_BASE_URL",
    "http://app-client-test.sunlightmobility.hk"
).rstrip("/")

_AUTH_TOKEN = os.environ.get("V160_AUTH_TOKEN", "").strip()
_REAL_ORDER_NO = os.environ.get("V160_REAL_ORDER_NO", "").strip()

# 真实路线坐标（北角地铁站 → 香港大学，来自 config/JRYG_settings.yaml）
# 不硬编码金额或预估结果，只提供路线坐标让真实接口返回真实报价
_ORIGIN = {"lat": 22.2856, "lng": 114.1568, "name": "北角(地鐵站)"}
_DESTINATION = {"lat": 22.2835, "lng": 114.1400, "name": "香港大學"}

# HTTP 超时（连接 + 读取），不等于接口 SLA
_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 30


@pytest.fixture(scope="module")
def http_session():
    """共享 requests.Session，复用 TCP 连接。"""
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    if _AUTH_TOKEN:
        s.headers["Authorization"] = _AUTH_TOKEN
    yield s
    s.close()


@pytest.fixture(scope="module", autouse=True)
def env_available():
    """校验测试环境和认证凭据可用，缺失时跳过整个模块。"""
    if not _AUTH_TOKEN:
        pytest.skip(
            "未提供真实 auth token（V160_AUTH_TOKEN），"
            "独立接口测试需真实登录后传入 token，不伪造凭据"
        )
    # 探活：尝试连接 base URL
    try:
        requests.head(_BASE_URL, timeout=_CONNECT_TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        pytest.skip(f"测试环境不可达 {_BASE_URL}：{exc}")


def _need_real_order():
    """未提供真实订单号时 skip。"""
    if not _REAL_ORDER_NO:
        pytest.skip(
            "未提供真实订单号（V160_REAL_ORDER_NO），"
            "查询类接口需真实订单号，不伪造"
        )


def _post(session, path, body=None, params=None):
    """发送 POST 请求到真实环境，返回 Response 对象。"""
    url = f"{_BASE_URL}{path}"
    resp = session.post(url, json=body, params=params,
                        timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))
    return resp


def _get(session, path, params=None):
    """发送 GET 请求到真实环境，返回 Response 对象。"""
    url = f"{_BASE_URL}{path}"
    resp = session.get(url, params=params,
                       timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))
    return resp


class TestV160EstimateApi:
    """POST /passenger/order/estimate 询价接口。"""

    def test_estimate_returns_200_and_business_code(self, http_session):
        """询价接口返回 HTTP 200 且业务码 code=10000。

        使用真实路线坐标（北角 → 香港大学），不硬编码预估金额。
        """
        body = {
            "origin": _ORIGIN,
            "destination": _DESTINATION,
            "order_type": 5,
            "car_types": [
                {"business_type": 2, "order_type": 5,
                 "car_type_id": [1, 9, 2, 3, 4]},
            ],
        }
        resp = _post(http_session, "/passenger/order/estimate", body=body)
        assert resp.status_code == 200, \
            f"HTTP {resp.status_code}，响应={resp.text[:500]}"
        data = resp.json()
        assert data.get("code") == 10000, \
            f"业务码 code={data.get('code')}，message={data.get('message')}"

    @pytest.mark.skip(reason="需求未明确：缺少 passenger/order/estimate 响应数组的准确字段路径")
    def test_estimate_response_contains_car_types(self):
        raise NotImplementedError("取得当前询价响应契约后实现，不猜测 car_types/list")

    @pytest.mark.skip(reason="需求未明确：缺少询价返回车型数量及过滤规则，展示五车型不等于必返五条")
    def test_estimate_ride_hailing_has_five_types(self):
        raise NotImplementedError("取得当前询价数量契约后实现，不以至少一条替代五条")

    @pytest.mark.skip(reason="需求未明确：缺少询价金额的准确字段、类型、单位和空值规则")
    def test_estimate_response_amount_is_numeric(self):
        raise NotImplementedError("取得当前金额契约后实现，不猜字段或跳过缺失字段断言")

    def test_estimate_timeout_is_not_sla(self, http_session):
        """记录询价接口响应耗时，不作为性能 SLA 断言。"""
        import time
        body = {
            "origin": _ORIGIN,
            "destination": _DESTINATION,
            "order_type": 5,
            "car_types": [
                {"business_type": 2, "order_type": 5,
                 "car_type_id": [1, 9, 2, 3, 4]},
            ],
        }
        start = time.monotonic()
        resp = _post(http_session, "/passenger/order/estimate", body=body)
        elapsed = time.monotonic() - start
        assert resp.status_code == 200
        # 仅记录耗时，不作为 SLA 断言（需求未定义性能阈值）
        print(f"\n[询价耗时] {elapsed:.3f}s")


class TestV160OrderStatusApi:
    """GET /passenger/order/status 订单状态接口。"""

    def test_status_returns_200(self, http_session):
        """真实订单状态查询返回 HTTP 200。"""
        _need_real_order()
        resp = _get(http_session, "/passenger/order/status",
                    params={"order_no": _REAL_ORDER_NO})
        assert resp.status_code == 200, \
            f"HTTP {resp.status_code}，响应={resp.text[:500]}"

    def test_status_returns_business_code(self, http_session):
        """真实订单状态查询返回业务码 code=10000。"""
        _need_real_order()
        resp = _get(http_session, "/passenger/order/status",
                    params={"order_no": _REAL_ORDER_NO})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("code") == 10000, \
            f"业务码 code={data.get('code')}，message={data.get('message')}"

    def test_status_response_has_order_status(self, http_session):
        """真实订单状态响应包含 order_status 字段。"""
        _need_real_order()
        resp = _get(http_session, "/passenger/order/status",
                    params={"order_no": _REAL_ORDER_NO})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("code") == 10000
        payload = data.get("data", {})
        assert "order_status" in payload, \
            f"响应 data 中未找到 order_status：{payload}"

    def test_status_nonexistent_order(self, http_session):
        """不存在的订单号返回非 10000 业务码或空 data。"""
        resp = _get(http_session, "/passenger/order/status",
                    params={"order_no": "TH_NOT_EXIST_99999999"})
        assert resp.status_code == 200
        data = resp.json()
        # 不存在的订单不应返回 code=10000 且 order_status 有值
        assert not (data.get("code") == 10000
                    and data.get("data", {}).get("order_status") is not None), \
            f"不存在的订单返回了有效状态：{data}"


class TestV160OrderDetailApi:
    """GET /passenger/order/detail 订单详情接口。

    接口文档：http://yapi.sunlightmobility.hk/project/776/interface/api/52851
    """

    def test_detail_returns_200(self, http_session):
        """真实订单详情查询返回 HTTP 200。"""
        _need_real_order()
        resp = _get(http_session, "/passenger/order/detail",
                    params={"order_no": _REAL_ORDER_NO})
        assert resp.status_code == 200

    def test_detail_returns_business_code(self, http_session):
        """真实订单详情查询返回业务码 code=10000。"""
        _need_real_order()
        resp = _get(http_session, "/passenger/order/detail",
                    params={"order_no": _REAL_ORDER_NO})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("code") == 10000, \
            f"业务码 code={data.get('code')}，message={data.get('message')}"

    def test_detail_response_has_order_no(self, http_session):
        """真实订单详情响应包含 order_no 字段且与查询一致。"""
        _need_real_order()
        resp = _get(http_session, "/passenger/order/detail",
                    params={"order_no": _REAL_ORDER_NO})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("code") == 10000
        payload = data.get("data", {})
        assert payload.get("order_no") == _REAL_ORDER_NO, \
            f"响应 order_no={payload.get('order_no')}，查询={_REAL_ORDER_NO}"

    def test_detail_response_has_order_type(self, http_session):
        """真实订单详情响应包含 order_type 字段且值为 5 或 6。"""
        _need_real_order()
        resp = _get(http_session, "/passenger/order/detail",
                    params={"order_no": _REAL_ORDER_NO})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("code") == 10000
        payload = data.get("data", {})
        assert payload.get("order_type") in (5, 6), \
            f"order_type={payload.get('order_type')}，期望 5 或 6"


class TestV160ChargeRuleApi:
    """GET /passenger/charge/rule 计价规则接口。

    接口文档：http://yapi.sunlightmobility.hk/project/776/interface/api/58526
    """

    def test_rule_by_order_no_returns_200(self, http_session):
        """按真实订单号查询计价规则返回 HTTP 200。"""
        _need_real_order()
        resp = _get(http_session, "/passenger/charge/rule",
                    params={"order_no": _REAL_ORDER_NO})
        assert resp.status_code == 200

    def test_rule_by_order_no_returns_business_code(self, http_session):
        """按真实订单号查询计价规则返回业务码 code=10000。"""
        _need_real_order()
        resp = _get(http_session, "/passenger/charge/rule",
                    params={"order_no": _REAL_ORDER_NO})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("code") == 10000, \
            f"业务码 code={data.get('code')}，message={data.get('message')}"

    def test_rule_response_has_rules(self, http_session):
        """计价规则响应包含 rules 字段且为非空数组。"""
        _need_real_order()
        resp = _get(http_session, "/passenger/charge/rule",
                    params={"order_no": _REAL_ORDER_NO})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("code") == 10000
        payload = data.get("data", {})
        rules = payload.get("rules")
        assert rules is not None, f"响应 data 中未找到 rules：{payload}"
        assert isinstance(rules, list), \
            f"rules 类型={type(rules)}，期望 list"
        assert len(rules) >= 1, f"rules 为空数组：{payload}"

    def test_rule_response_has_car_type_name(self, http_session):
        """计价规则响应包含 car_type_name 字段。"""
        _need_real_order()
        resp = _get(http_session, "/passenger/charge/rule",
                    params={"order_no": _REAL_ORDER_NO})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("code") == 10000
        payload = data.get("data", {})
        assert "car_type_name" in payload, \
            f"响应 data 中未找到 car_type_name：{payload}"


class TestV160HttpSafety:
    """HTTP 接口安全与健壮性验证。"""

    def test_no_auth_returns_error(self):
        """无 auth token 请求受保护接口返回非 10000 业务码。"""
        resp = requests.get(
            f"{_BASE_URL}/passenger/order/detail",
            params={"order_no": "TH26B6PIEWECN"},
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
        )
        # 无 token 时应返回错误业务码（401/403 或 code != 10000）
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("code") != 10000, \
                "无 auth token 请求受保护接口不应返回 code=10000"
        else:
            assert resp.status_code in (401, 403), \
                f"无 token 时 HTTP {resp.status_code}，期望 401/403 或非 10000"

    def test_invalid_order_no_returns_error(self, http_session):
        """格式非法的订单号返回非 10000 业务码。"""
        resp = _get(http_session, "/passenger/order/detail",
                    params={"order_no": "INVALID###"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("code") != 10000, \
            f"非法订单号不应返回 code=10000：{data}"
