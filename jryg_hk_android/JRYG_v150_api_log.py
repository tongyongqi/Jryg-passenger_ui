"""V1.5.0 乘客端接口日志解析。

依据需求文档提供的接口清单，从 Android logcat 中还原 App 实际发出的
网络请求及其服务端响应，用于用例断言「服务端是否按预期处理」。

覆盖接口（V1.5.0 需求接口清单）：
- 用户信息保存      POST /passenger/user/save
- 联系人列表        GET  /passenger/contact/list
- 联系人保存        POST /passenger/contact/save
- 联系人删除        POST /passenger/contact/delete
- 联系人分享设置    POST /passenger/contact/share
- 紧急报警          POST /passenger/emergency/alarm
- 订单行程信息发送  POST /passenger/order/tripSend
- 用户信息          GET  /passenger/user/getInfo

日志来源为 App 内 retrofit 拦截器输出：
- ``Sending request <url>``      请求发出
- ``order_no=..&email=..``       表单请求体
- ``result={...}``               服务端响应体
- ``url=<url>``                  响应所属接口
"""
import json
import re

# 需求接口清单：逻辑名 -> 接口路径片段
API_PATHS = {
    "user_save": "/passenger/user/save",
    "contact_list": "/passenger/contact/list",
    "contact_save": "/passenger/contact/save",
    "contact_delete": "/passenger/contact/delete",
    "contact_share": "/passenger/contact/share",
    "emergency_alarm": "/passenger/emergency/alarm",
    "trip_send": "/passenger/order/tripSend",
    "user_info": "/passenger/user/getInfo",
    "order_detail": "/passenger/order/detail",
    "order_list": "/passenger/order/list",
}

# 接口路径 -> 逻辑名（路径片段互不包含，按最长优先匹配）
_PATH_TO_NAME = sorted(
    ((name, path) for name, path in API_PATHS.items()),
    key=lambda item: len(item[1]),
    reverse=True,
)

_SENDING_RE = re.compile(r"Sending request\s+(\S+)")
_URL_RE = re.compile(r"\burl=(\S+)")
# 服务端响应行：result={"code":...}；需排除Flutter事件里的 result={response={...}}
_RESULT_RE = re.compile(r"result=(?P<body>\{.*\})\s*$")
# Flutter 网络事件行，其中的 result 不是接口响应体
_FLUTTER_EVENT_RE = re.compile(r"__@app_network_response__|__@app_network_request__")
_BODY_RE = re.compile(r"(?:^|[\s:])(?P<body>(?:order_no|email|area_code|name|phone|auto_share|"
                      r"contact_id|longitude|latitude)=(?:[^\s&]+)?"
                      r"(?:\s*&\s*[a-zA-Z0-9_\-]+=(?:[^\s&]+)?)*)\s*$")
_GETPARAMS_RE = re.compile(r"getParams\s*:\s*\{([^}]*)\}")
_SORTPARAMS_RE = re.compile(r"getSortParams\s*:\s*(.*)$")


def _normalize(path):
    """去掉查询串与结尾斜杠，便于按接口路径匹配。"""
    if not path:
        return ""
    return path.split("?", 1)[0].rstrip("/")


def api_name_for_url(url):
    """按接口路径返回逻辑名，未知接口返回空字符串。"""
    path = _normalize(url)
    for name, expected in _PATH_TO_NAME:
        if path.endswith(expected) or path == expected:
            return name
    return ""


def _unquote(value):
    """解码URL编码的表单值，非编码原样返回。"""
    if "%" not in value:
        return value
    from urllib.parse import unquote
    return unquote(value)


# 签名/防重放参数，不属于业务请求参数
_SIGNING_PARAMS = ("nonce", "key", "timestamp", "sign")


def _parse_form_body(text):
    """解析 ``a=1&b=2`` 形式的请求体，返回字典（值做URL解码，剔除签名参数）。"""
    params = {}
    for item in re.split(r"[&,\s]+", text or ""):
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        key = key.strip()
        if not key or key in _SIGNING_PARAMS:
            continue
        params[key] = _unquote(value.strip())
    return params


def _merge_params(target, incoming):
    """合并请求参数：已有明文值不被URL编码值覆盖。"""
    for key, value in incoming.items():
        if key in target and "%" in str(target[key]) and "%" not in str(value):
            continue
        target[key] = value


def parse_api_calls(lines):
    """从 logcat 行中还原接口调用序列。

    返回列表，每项包含：api（逻辑名）、url、method_hint、params、response、code、message。
    """
    calls = []
    current = None
    pending_params = {}

    def flush():
        nonlocal current
        if current is None:
            return
        if current.get("response") and current.get("code") is None:
            parsed = parse_response(current["response"])
            if parsed:
                current.update(parsed)
        current.setdefault("data", None)
        calls.append(current)
        current = None

    for raw in lines or []:
        line = raw.strip()
        if not line:
            continue

        match = _SENDING_RE.search(line)
        if match:
            flush()
            url = match.group(1)
            current = {
                "api": api_name_for_url(url),
                "url": url,
                "method_hint": "POST" if "Content-Type" in line else "",
                "params": dict(pending_params),
                "response": "",
                "code": None,
                "message": "",
                "data": None,
            }
            pending_params = {}
            continue

        match = _GETPARAMS_RE.search(line)
        if match:
            params = _parse_form_body(match.group(1))
            if current is None:
                pending_params.update(params)
            else:
                _merge_params(current["params"], params)
            continue

        if current is None:
            continue

        match = _URL_RE.search(line)
        if match:
            url = match.group(1)
            name = api_name_for_url(url)
            if name:
                current["api"] = name
                current["url"] = url
            continue

        match = _RESULT_RE.search(line)
        if match and not _FLUTTER_EVENT_RE.search(line):
            if not current["response"]:
                current["response"] = match.group("body")
            continue

        match = _BODY_RE.search(line)
        if match:
            _merge_params(current["params"], _parse_form_body(match.group("body")))
            continue

        match = _SORTPARAMS_RE.search(line)
        if match:
            _merge_params(current["params"], _parse_form_body(match.group(1)))

    flush()
    return calls


def parse_response(payload):
    """解析服务端响应体，返回 code/message/data；无法解析时返回空字典。"""
    if not payload:
        return {}
    try:
        body = json.loads(payload)
    except (ValueError, TypeError):
        return {}
    if not isinstance(body, dict):
        return {}
    return {
        "code": body.get("code"),
        "message": body.get("message", ""),
        "data": body.get("data"),
    }


def _as_calls(calls_or_lines):
    """兼容传入日志行或已解析的调用列表。"""
    if not calls_or_lines:
        return []
    if isinstance(calls_or_lines, dict):
        return [calls_or_lines]
    first = calls_or_lines[0]
    if isinstance(first, dict):
        return list(calls_or_lines)
    return parse_api_calls(calls_or_lines)


def find_api_calls(calls_or_lines, api_name):
    """返回指定逻辑接口的全部调用记录，可传日志行或已解析列表。"""
    return [call for call in _as_calls(calls_or_lines) if call["api"] == api_name]


def summarize_calls(calls):
    """把接口调用序列压缩为可写入报告的结构。"""
    summary = []
    for call in calls:
        item = {
            "api": call["api"],
            "url": call.get("url", ""),
            "params": call.get("params", {}),
            "code": call.get("code"),
            "message": call.get("message", ""),
        }
        data = call.get("data")
        if isinstance(data, dict):
            item["data_keys"] = sorted(data.keys())
        summary.append(item)
    return summary


def check_api_response(calls, api_name, *, expect_code=10000, expect_params=None,
                       forbidden_params=None, expect_data_contains=None):
    """按接口层断言服务端响应。

    返回字典：matched（是否命中该接口）、passed（是否符合预期）、
    reason（不通过原因）、code、message、params。
    """
    calls = _as_calls(calls)
    matched = find_api_calls(calls, api_name)
    if not matched:
        return {
            "matched": False, "passed": False,
            "reason": f"本次操作未观察到接口 {api_name} 调用",
            "code": None, "message": "", "params": {},
        }

    last = matched[-1]
    code = last.get("code")
    result = {
        "matched": True,
        "passed": True,
        "reason": "",
        "code": code,
        "message": last.get("message", ""),
        "params": last.get("params", {}),
        "calls": len(matched),
    }

    if expect_code is not None and code != expect_code:
        result["passed"] = False
        result["reason"] = f"接口 {api_name} 返回 code={code}，期望 {expect_code}（{last.get('message','')}）"

    if expect_params:
        for key, expected in expect_params.items():
            actual = result["params"].get(key)
            if actual is None:
                result["passed"] = False
                result["reason"] = result["reason"] or f"接口 {api_name} 请求缺少参数 {key}"
            elif expected is not None and str(actual) != str(expected):
                result["passed"] = False
                result["reason"] = result["reason"] or (
                    f"接口 {api_name} 参数 {key}={actual}，期望 {expected}")

    if forbidden_params:
        for key in forbidden_params:
            if key in result["params"]:
                result["passed"] = False
                result["reason"] = result["reason"] or (
                    f"接口 {api_name} 不应携带参数 {key}")

    if expect_data_contains:
        data = last.get("data")
        if not isinstance(data, dict):
            result["passed"] = False
            result["reason"] = result["reason"] or f"接口 {api_name} 响应 data 结构不符"
        else:
            for key, expected in expect_data_contains.items():
                if key not in data:
                    result["passed"] = False
                    result["reason"] = result["reason"] or (
                        f"接口 {api_name} 响应缺少字段 {key}")
                elif expected is not None and str(data[key]) != str(expected):
                    result["passed"] = False
                    result["reason"] = result["reason"] or (
                        f"接口 {api_name} 响应 {key}={data[key]}，期望 {expected}")
    return result
