"""
mitmproxy 插件：手动操作 App 触发请求后，抓包并篡改服务端返回参数。

核心功能：
  1. 抓取所有 HTTP/HTTPS 请求和响应，打印到终端
  2. 通过 CONFIG 字典配置需要篡改的接口及修改规则
  3. 支持多种篡改方式：置空字段、替换值、删除字段、自定义函数

使用方式（WireGuard 模式，解决 Flutter App 不走代理问题）：
    # 1. 用 python3.12 启动 mitmproxy WireGuard 模式
    python3.12 -m mitmproxy wireguard -s JRYG_Passenger_UI_HK/common/JRYG_intercept_rewrite.py

    # 2. 或者用 mitmdump WireGuard 模式（终端输出更清晰）
    python3.12 -m mitmdump wireguard -s JRYG_Passenger_UI_HK/common/JRYG_intercept_rewrite.py

    # 3. 启动后终端会显示二维码和连接信息
    #    在手机上扫码连接 WireGuard VPN（或通过 adb reverse 自动连接）

    # 4. 手动操作 App（如：输入地址、询价、点击确认支付等）
    #    所有接口请求会被拦截，命中的接口会被篡改返回参数

配置说明：
    修改下方 CONFIG 字典，添加需要篡改的接口路径和修改规则。
    每个接口的配置格式：
        "接口路径关键字": {
            "description": "描述",
            "actions": [
                {
                    "type": "set_empty",          # 将指定字段置为空数组/空值
                    "path": ["data", "mode"]       # JSON 路径，如 data.mode
                },
                {
                    "type": "set_value",
                    "path": ["data", "status"],
                    "value": "disabled"
                },
                {
                    "type": "remove_field",
                    "path": ["data", "language"]
                }
            ]
        }
"""

import json
import time
import copy
from mitmproxy import http, ctx


# ============================================================================
# 配置区：在这里添加你要篡改的接口和修改规则
# ============================================================================
CONFIG = {
    # 示例1：支付方式接口 — 将 mode 列表置空
    "/passenger/payment/mode": {
        "description": "支付方式接口 — 将 mode/modes 列表置空",
        "actions": [
            {"type": "set_empty", "path": ["data", "mode"]},
            {"type": "set_empty", "path": ["data", "modes"]},
            {"type": "set_empty", "path": ["data", "payment_mode"]},
            {"type": "set_empty", "path": ["data", "payment_modes"]},
            {"type": "set_empty", "path": ["data", "list"]},
        ]
    },

    # 示例2：POI 搜索接口 — 移除 language 字段
    "/map-service/v1/a_map/poi": {
        "description": "POI 搜索接口 — 递归移除 language 字段",
        "actions": [
            {"type": "remove_recursive", "path": ["language"]},
        ]
    },

    # 示例3：v2/place 接口 — 将搜索结果置空
    # "/map-service/v2/place": {
    #     "description": "地点搜索 — 置空搜索结果",
    #     "actions": [
    #         {"type": "set_empty", "path": ["data", "pois"]},
    #         {"type": "set_empty", "path": ["data", "suggestions"]},
    #     ]
    # },
}

# 是否打印所有请求（调试用，设为 True 会打印所有流量）
PRINT_ALL_REQUESTS = True

# 是否只打印命中的请求（PRINT_ALL_REQUESTS=False 时生效）
PRINT_ONLY_MATCHED = True


# ============================================================================
# 核心逻辑：不需要修改以下代码，只需修改上方 CONFIG
# ============================================================================

def _get_by_path(data, path_list):
    """按路径列表获取嵌套 JSON 中的值，如 ["data", "mode"]"""
    current = data
    for key in path_list:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            return None, False
    return current, True


def _set_by_path(data, path_list, value):
    """按路径列表设置嵌套 JSON 中的值"""
    current = data
    for i, key in enumerate(path_list[:-1]):
        if isinstance(current, dict):
            if key not in current:
                current[key] = {}
            current = current[key]
        elif isinstance(current, list) and key.isdigit():
            idx = int(key)
            while len(current) <= idx:
                current.append({})
            current = current[idx]
        else:
            return False
    last_key = path_list[-1]
    if isinstance(current, dict):
        current[last_key] = value
        return True
    elif isinstance(current, list) and last_key.isdigit():
        current[int(last_key)] = value
        return True
    return False


def _remove_recursive(data, field_name):
    """递归移除所有层级的指定字段"""
    if isinstance(data, dict):
        data.pop(field_name, None)
        for v in data.values():
            _remove_recursive(v, field_name)
    elif isinstance(data, list):
        for item in data:
            _remove_recursive(item, field_name)


def _apply_action(resp_data, action):
    """执行单个篡改动作"""
    atype = action.get("type")
    path = action.get("path", [])

    if atype == "set_empty":
        # 置空：如果原值是 list 设为 []，如果是 str 设为 ""，否则设为 None
        original, found = _get_by_path(resp_data, path)
        if found:
            if isinstance(original, list):
                _set_by_path(resp_data, path, [])
            elif isinstance(original, str):
                _set_by_path(resp_data, path, "")
            elif isinstance(original, dict):
                _set_by_path(resp_data, path, {})
            else:
                _set_by_path(resp_data, path, None)
            return True
        return False

    elif atype == "set_value":
        return _set_by_path(resp_data, path, action.get("value"))

    elif atype == "remove_field":
        # 删除指定路径的字段
        if len(path) == 1:
            if isinstance(resp_data, dict):
                resp_data.pop(path[0], None)
                return True
        else:
            parent, found = _get_by_path(resp_data, path[:-1])
            if found and isinstance(parent, dict):
                parent.pop(path[-1], None)
                return True
        return False

    elif atype == "remove_recursive":
        _remove_recursive(resp_data, path[0] if path else "")
        return True

    elif atype == "custom":
        # 自定义函数处理
        func = action.get("func")
        if callable(func):
            func(resp_data)
            return True
        return False

    return False


def request(flow: http.HTTPFlow) -> None:
    """拦截请求阶段：打印请求信息"""
    url = flow.request.pretty_url
    path = flow.request.path

    # 检查是否命中配置中的接口
    matched_key = None
    for key in CONFIG:
        if key in path:
            matched_key = key
            break

    if PRINT_ALL_REQUESTS or (PRINT_ONLY_MATCHED and matched_key):
        print(f"\n{'─'*60}")
        print(f"[请求] {flow.request.method} {url}")
        if matched_key:
            print(f"[命中规则] {matched_key} — {CONFIG[matched_key].get('description', '')}")
        print(f"[时间] {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"[Host] {flow.request.pretty_host}")
        print(f"[Query] {dict(flow.request.query)}")
        req_body = flow.request.get_text() or ""
        if req_body:
            print(f"[请求体] {req_body[:500]}")
        print(f"{'─'*60}")


def response(flow: http.HTTPFlow) -> None:
    """拦截响应阶段：打印并篡改"""
    url = flow.request.pretty_url
    path = flow.request.path

    # 检查是否命中配置中的接口
    matched_key = None
    for key in CONFIG:
        if key in path:
            matched_key = key
            break

    if not matched_key:
        if PRINT_ALL_REQUESTS:
            print(f"\n[响应透传] {flow.response.status_code} {url}")
        return

    # 命中的接口：打印 + 篡改
    rule = CONFIG[matched_key]
    raw = flow.response.get_text() or ""

    print(f"\n{'='*60}")
    print(f"[命中拦截] {matched_key}")
    print(f"[描述] {rule.get('description', '')}")
    print(f"[URL] {url}")
    print(f"[状态码] {flow.response.status_code}")
    print(f"[原始响应体] {raw[:2000]}")
    print(f"[时间] {time.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        resp_data = json.loads(raw)
        original_data = copy.deepcopy(resp_data)  # 保留原始数据用于对比

        # 执行所有篡改动作
        changes = []
        for action in rule.get("actions", []):
            atype = action.get("type")
            path_keys = action.get("path", [])
            path_str = ".".join(path_keys) if path_keys else "(root)"

            original_val, found = _get_by_path(resp_data, path_keys) if path_keys else (None, False)
            success = _apply_action(resp_data, action)

            if success:
                if atype == "set_empty":
                    print(f"[篡改] {path_str}: {original_val} → [] (置空)")
                elif atype == "set_value":
                    print(f"[篡改] {path_str}: {original_val} → {action.get('value')}")
                elif atype == "remove_field":
                    print(f"[篡改] 删除字段 {path_str}: 原值={original_val}")
                elif atype == "remove_recursive":
                    print(f"[篡改] 递归移除字段 {path_str}")
                changes.append(path_str)
            else:
                # 静默跳过未找到的字段
                pass

        if changes:
            modified_json = json.dumps(resp_data, ensure_ascii=False).encode("utf-8")
            flow.response.headers["Content-Type"] = "application/json; charset=utf-8"
            flow.response.content = modified_json
            print(f"[篡改完成] 修改了 {len(changes)} 个字段: {', '.join(changes)}")
            print(f"[新响应体] {modified_json.decode('utf-8')[:2000]}")
        else:
            # 如果没有字段被命中，尝试通用兜底：把 data 下的所有 list 置空
            if isinstance(resp_data, dict) and isinstance(resp_data.get("data"), dict):
                data = resp_data["data"]
                changed_any = False
                for k, v in list(data.items()):
                    if isinstance(v, list) and v:
                        print(f"[兜底置空] data.{k}: {v} → []")
                        data[k] = []
                        changed_any = True
                if changed_any:
                    modified_json = json.dumps(resp_data, ensure_ascii=False).encode("utf-8")
                    flow.response.headers["Content-Type"] = "application/json; charset=utf-8"
                    flow.response.content = modified_json
                    print(f"[兜底篡改完成]")
                    print(f"[新响应体] {modified_json.decode('utf-8')[:2000]}")
                else:
                    print(f"[无篡改] 配置中的字段均未命中，且 data 下无 list 字段")
            else:
                print(f"[无篡改] 配置中的字段均未命中")

    except json.JSONDecodeError as e:
        print(f"[JSON解析失败] {e}，响应原样返回")
    except Exception as e:
        print(f"[处理异常] {e}，响应原样返回")

    print(f"{'='*60}\n")
