"""POI 接口验证模块：读取 mitmproxy 捕获的 /map-service/v1/a_map/poi 请求并校验。"""

import json
import os
import time

from JRYG_Passenger_UI_HK.common.JRYG_config import LOGS_DIR
from JRYG_Passenger_UI_HK.common.JRYG_logger import logger

CAPTURE_FILE = os.path.join(LOGS_DIR, "JRYG_poi_capture.json")

TARGET_PATH = "/map-service/v1/a_map/poi"


def load_captures():
    """加载 mitmproxy 捕获文件，返回捕获列表。"""
    if not os.path.exists(CAPTURE_FILE):
        return []
    try:
        with open(CAPTURE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"读取 POI 捕获文件失败: {e}")
        return []


def clear_captures():
    """清空捕获文件，在测试开始前调用。"""
    if os.path.exists(CAPTURE_FILE):
        os.remove(CAPTURE_FILE)
        logger.info("已清空旧的 POI 接口捕获记录。")


def wait_for_poi_request(timeout=30, keyword=None, min_count=1):
    """轮询等待 POI 接口被调用。

    Args:
        timeout: 最大等待秒数。
        keyword: 可选，在请求 URL query 或 body 中搜索的关键字
                 （如搜索关键词 "铜锣湾" 或 "香港大学"）。
        min_count: 期望的最少匹配条数。

    Returns:
        list: 匹配的捕获条目列表。

    Raises:
        AssertionError: 如果超时仍未捕获到足够的请求。
    """
    end_time = time.time() + timeout
    while time.time() < end_time:
        captures = load_captures()
        matched = []
        for entry in captures:
            if keyword:
                # 在 query_params、body 中搜索关键字
                search_space = json.dumps(entry, ensure_ascii=False)
                if keyword not in search_space:
                    continue
            matched.append(entry)
        if len(matched) >= min_count:
            logger.info(f"成功捕获 {len(matched)} 条 POI 接口请求（关键字: {keyword}）。")
            return matched
        time.sleep(1)

    # 超时，输出详细诊断信息
    total = load_captures()
    logger.error(
        f"POI 接口验证超时（{timeout}s），期望 {min_count} 条"
        f"（关键字: {keyword}），实际捕获 {len(total)} 条。"
    )
    raise AssertionError(
        f"未能在 {timeout}s 内捕获到足够的 {TARGET_PATH} 请求"
        f"（期望 {min_count} 条，关键字: {keyword}）"
    )


def verify_poi_response(captures):
    """校验 POI 接口响应状态码和返回体。

    Args:
        captures: wait_for_poi_request 返回的捕获列表。

    Raises:
        AssertionError: 如果任意一条响应非 200 或 body 为空。
    """
    for i, entry in enumerate(captures):
        resp = entry.get("response")
        if resp is None:
            raise AssertionError(f"第 {i+1} 条 POI 请求缺少响应数据（可能 mitmproxy 未捕获到响应）。")
        status = resp.get("status_code")
        body = resp.get("body", "")
        if status != 200:
            raise AssertionError(f"第 {i+1} 条 POI 接口响应状态码异常: {status}")
        if not body:
            raise AssertionError(f"第 {i+1} 条 POI 接口响应 body 为空。")
        # 尝试解析 JSON 并检查是否包含 POI 列表
        try:
            data = json.loads(body)
            logger.info(f"第 {i+1} 条 POI 响应解析成功，顶层键: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
        except json.JSONDecodeError:
            logger.warning(f"第 {i+1} 条 POI 响应非 JSON 格式，body 前 200 字符: {body[:200]}")

    logger.info(f"全部 {len(captures)} 条 POI 接口响应校验通过。")
