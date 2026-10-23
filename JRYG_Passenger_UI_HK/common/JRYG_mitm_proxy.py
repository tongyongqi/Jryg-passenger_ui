"""mitmproxy 插件：捕获地图搜索及支付方式相关接口请求与响应。

拦截接口：
  1. /map-service/v1/a_map/poi          — POI 关键词搜索
  2. /map-service/v2/place              — 地点搜索（含周围搜索 place_type=1）
  3. /v3/place/around                    — 高德周围搜索下游接口
  4. /passenger/payment/mode            — 支付方式接口

使用方式（终端启动）：
    mitmdump -s JRYG_Passenger_UI_HK/common/JRYG_mitm_proxy.py -p 8080

或通过 run_hk.sh 自动启动（见 JRYG_run_hk.sh 中 mitmdump 集成段）。

捕获结果写入：
    JRYG_Passenger_UI_HK/logs/JRYG_poi_capture.json       — POI 接口
    JRYG_Passenger_UI_HK/logs/JRYG_place_capture.json    — v2/place 接口
    JRYG_Passenger_UI_HK/logs/JRYG_around_capture.json    — 高德 /v3/place/around 接口
    JRYG_Passenger_UI_HK/logs/JRYG_payment_mode_capture.json — 支付方式接口
"""

import json
import os
import time
from mitmproxy import http

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 各接口的捕获文件路径
POI_CAPTURE_FILE = os.path.join(BASE_DIR, "JRYG_Passenger_UI_HK", "logs", "JRYG_poi_capture.json")
PLACE_CAPTURE_FILE = os.path.join(BASE_DIR, "JRYG_Passenger_UI_HK", "logs", "JRYG_place_capture.json")
AROUND_CAPTURE_FILE = os.path.join(BASE_DIR, "JRYG_Passenger_UI_HK", "logs", "JRYG_around_capture.json")
PAYMENT_MODE_CAPTURE_FILE = os.path.join(BASE_DIR, "JRYG_Passenger_UI_HK", "logs", "JRYG_payment_mode_capture.json")

# 目标接口路径关键字
POI_TARGET_PATH = "/map-service/v1/a_map/poi"
PLACE_TARGET_PATH = "/map-service/v2/place"
AROUND_TARGET_PATH = "/v3/place/around"
PAYMENT_MODE_TARGET_PATH = "/passenger/payment/mode"

# 兼容旧代码引用
CAPTURE_FILE = POI_CAPTURE_FILE
TARGET_PATH = POI_TARGET_PATH

# 全局捕获列表（同一 mitmdump 进程生命周期内有效）
_captured_requests = []        # POI 接口
_place_captured_requests = []  # v2/place 接口
_around_captured_requests = [] # 高德 around 接口
_payment_mode_captured_requests = []  # 支付方式接口


def request(flow: http.HTTPFlow):
    """拦截请求"""
    url = flow.request.pretty_url

    if POI_TARGET_PATH in url:
        _handle_request(flow, _captured_requests, POI_CAPTURE_FILE)
    elif PLACE_TARGET_PATH in url:
        _handle_request(flow, _place_captured_requests, PLACE_CAPTURE_FILE)
    elif AROUND_TARGET_PATH in url:
        _handle_request(flow, _around_captured_requests, AROUND_CAPTURE_FILE)
    elif PAYMENT_MODE_TARGET_PATH in url:
        _handle_request(flow, _payment_mode_captured_requests, PAYMENT_MODE_CAPTURE_FILE)


def response(flow: http.HTTPFlow):
    """拦截响应"""
    url = flow.request.pretty_url

    if POI_TARGET_PATH in url:
        _handle_response(flow, _captured_requests, POI_CAPTURE_FILE)
    elif PLACE_TARGET_PATH in url:
        _handle_response(flow, _place_captured_requests, PLACE_CAPTURE_FILE)
    elif AROUND_TARGET_PATH in url:
        _handle_response(flow, _around_captured_requests, AROUND_CAPTURE_FILE)
    elif PAYMENT_MODE_TARGET_PATH in url:
        _handle_response(flow, _payment_mode_captured_requests, PAYMENT_MODE_CAPTURE_FILE)


def _handle_request(flow, capture_list, capture_file):
    """通用请求拦截处理"""
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "url": flow.request.pretty_url,
        "method": flow.request.method,
        "headers": dict(flow.request.headers),
        "query_params": dict(flow.request.query) if flow.request.query else {},
        "body": flow.request.get_text() or "",
        "response": None,
    }
    capture_list.append(entry)
    _flush_to(capture_list, capture_file)


def _handle_response(flow, capture_list, capture_file):
    """通用响应拦截处理"""
    for entry in reversed(capture_list):
        if entry["url"] == flow.request.pretty_url and entry["response"] is None:
            entry["response"] = {
                "status_code": flow.response.status_code,
                "headers": dict(flow.response.headers),
                "body": flow.response.get_text() or "",
            }
            break
    _flush_to(capture_list, capture_file)


def _flush_to(capture_list, capture_file):
    """将捕获结果写入指定文件"""
    os.makedirs(os.path.dirname(capture_file), exist_ok=True)
    with open(capture_file, "w", encoding="utf-8") as f:
        json.dump(capture_list, f, ensure_ascii=False, indent=2)
