"""验证器：/map-service/v2/place 周围搜索接口。

验证维度：
  1. place_type=1 时走周围搜索逻辑
  2. language 透传至高德 /v3/place/around
  3. place_type 非法或缺失时路由逻辑
  4. 返回字段（name/pname/cityname/adname/address）语言正确性
  5. pname/adname 保持高德原始返回值
  6. 周围搜索默认简体中文

依赖 HK_CAPTURE_DIR 目录下的 JRYG_place_capture.json 和
JRYG_around_capture.json；默认目录为接口项目 data/captures。
"""

import json
import os
import re

from JRYG_Passenger_API_HK.common.JRYG_config import CAPTURE_DIR

PLACE_CAPTURE_FILE = os.path.join(CAPTURE_DIR, "JRYG_place_capture.json")
AROUND_CAPTURE_FILE = os.path.join(CAPTURE_DIR, "JRYG_around_capture.json")

# 繁体中文 Unicode 范围（基本区 + 扩展区）
TRADITIONAL_PATTERN = re.compile(
    r'[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df\U0002a700-\U0002b73f]'
)

# 简体中文常见范围的子集（排除部分繁体专用字）
# 注意：简繁字集有大量重叠，这里用「仅繁体使用」的字来判断
TRADITIONAL_ONLY_CHARS = set(
    chr(c) for c in range(0x4e00, 0x9fff + 1)
    if chr(c) in '萬禮國會學東長點電時來發機場區車後義動離開關員術業產經營運現場說實體計計畫藝術誌認證論壇網際網路資訊處理週末假期節目錄製過程簡單問題車輛動態調整討論區議員質詢財政預算審議條例'
)


def load_place_captures():
    """加载 /map-service/v2/place 捕获数据"""
    if not os.path.exists(PLACE_CAPTURE_FILE):
        return []
    with open(PLACE_CAPTURE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_around_captures():
    """加载高德 /v3/place/around 捕获数据"""
    if not os.path.exists(AROUND_CAPTURE_FILE):
        return []
    with open(AROUND_CAPTURE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_response_body(entry):
    """解析响应 body（JSON 字符串 → dict）"""
    resp = entry.get("response")
    if not resp:
        return None
    body = resp.get("body", "")
    if not body:
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None


def _get_first_place_entry():
    """获取第一条 place 捕获记录"""
    entries = load_place_captures()
    if not entries:
        return None
    return entries[-1]


def _get_around_entry_for_language(language):
    """获取指定 language 参数的 around 捕获记录"""
    entries = load_around_captures()
    for entry in entries:
        params = entry.get("query_params", {})
        if params.get("language") == language:
            return entry
    # 如果找不到精确匹配，返回最后一条
    return entries[-1] if entries else None


def _is_traditional_chinese(text):
    """判断文本是否为繁体中文（包含繁体专用字）"""
    if not text:
        return False
    # 如果文本中有「仅繁体使用」的字，认为是繁体
    for char in text:
        if char in TRADITIONAL_ONLY_CHARS:
            return True
    # 如果没有繁体专用字，但全是 CJK 字符，也检查常见繁体字
    common_traditional = '臺灣臺北車站廣場東區門號碼區員長點電時來發機場車後義動離開關員術業產經營運現場說實體計畫藝術誌認證論壇網際網路資訊處理週末假期節目錄製過程'
    for char in text:
        if char in common_traditional:
            return True
    return False


def _is_english(text):
    """判断文本是否主要为英文"""
    if not text:
        return False
    # 去除空格、数字、标点后，如果剩余字符主要是 ASCII 字母
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    ascii_letters = [c for c in letters if ord(c) < 128]
    return len(ascii_letters) / len(letters) > 0.7


# ============ 验证方法 ============

def verify_place_type_around():
    """TC1: place_type=1 时走周围搜索逻辑

    预期：上游请求 place_type=1 时，下游高德 /v3/place/around 被调用
    """
    place_entry = _get_first_place_entry()
    around_entries = load_around_captures()

    errors = []

    if not place_entry:
        errors.append("未捕获到 /map-service/v2/place 请求")
        return errors

    place_params = place_entry.get("query_params", {})
    place_type = place_params.get("place_type")

    if place_type != "1":
        errors.append(f"place_type 预期为 1，实际为 {place_type}")

    if not around_entries:
        errors.append("place_type=1 但未捕获到高德 /v3/place/around 下游请求，周围搜索逻辑未触发")

    return errors


def verify_language_passthrough(language="trd"):
    """TC2: language 透传至高德 /v3/place/around

    预期：上游 language 参数值出现在下游 /v3/place/around 请求参数中
    """
    place_entry = _get_first_place_entry()
    errors = []

    if not place_entry:
        errors.append("未捕获到 /map-service/v2/place 请求")
        return errors

    place_params = place_entry.get("query_params", {})
    upstream_lang = place_params.get("language")

    if upstream_lang != language:
        errors.append(f"上游 language 参数预期为 {language}，实际为 {upstream_lang}")

    around_entry = _get_around_entry_for_language(language)
    if not around_entry:
        errors.append(f"未捕获到高德 /v3/place/around 请求（language={language}）")
        return errors

    around_params = around_entry.get("query_params", {})
    downstream_lang = around_params.get("language")

    if downstream_lang != language:
        errors.append(
            f"下游 /v3/place/around language 参数预期为 {language}，实际为 {downstream_lang}"
        )

    return errors


def verify_place_type_routing():
    """TC3: [质检] place_type 非法或缺失时路由逻辑

    预期：place_type 非法或缺失时，按接口文档路由到关键词或周围搜索逻辑
    注意：此用例标记为 [待确认]，仅做信息收集不做断言
    """
    errors = []
    place_entry = _get_first_place_entry()

    if not place_entry:
        errors.append("未捕获到 /map-service/v2/place 请求")
        return errors

    place_params = place_entry.get("query_params", {})
    place_type = place_params.get("place_type")

    # [待确认] 仅记录信息，不做严格断言
    if place_type is None:
        errors.append("[待确认] place_type 缺失，需人工确认路由逻辑是否符合接口文档")
    elif place_type not in ("0", "1"):
        errors.append(f"[待确认] place_type={place_type} 非法，需人工确认路由逻辑是否符合接口文档")

    return errors


def verify_around_language_trd():
    """TC4: /v3/place/around 请求参数 language=trd

    预期：下游请求包含 language=trd
    """
    errors = []
    around_entry = _get_around_entry_for_language("trd")

    if not around_entry:
        errors.append("未捕获到高德 /v3/place/around 请求")
        return errors

    around_params = around_entry.get("query_params", {})
    lang = around_params.get("language")

    if lang != "trd":
        errors.append(f"下游 /v3/place/around language 预期为 trd，实际为 {lang}")

    return errors


def verify_around_response_traditional():
    """TC5: 返回结果 name、pname、cityname、adname、address 为繁体中文

    预期：language=trd 时，这些字段内容为繁体中文
    """
    errors = []
    around_entry = _get_around_entry_for_language("trd")

    if not around_entry:
        errors.append("未捕获到高德 /v3/place/around 响应")
        return errors

    resp_data = _parse_response_body(around_entry)
    if not resp_data:
        errors.append("高德 /v3/place/around 响应体解析失败")
        return errors

    pois = resp_data.get("pois", []) if isinstance(resp_data, dict) else []
    if not pois:
        errors.append("高德 /v3/place/around 响应中未找到 pois 数据")
        return errors

    first_poi = pois[0]
    fields = ["name", "pname", "cityname", "adname", "address"]

    for field in fields:
        value = first_poi.get(field, "")
        if not value:
            errors.append(f"字段 {field} 值为空")
        elif not _is_traditional_chinese(value):
            errors.append(f"字段 {field} 预期为繁体中文，实际为: {value}")

    return errors


def verify_around_response_matches_amap_trd():
    """TC6: 返回文案与高德 /v3/place/around language=trd 对应字段一致

    预期：上游 /map-service/v2/place 返回字段与高德原始返回无差异
    """
    errors = []
    place_entry = _get_first_place_entry()
    around_entry = _get_around_entry_for_language("trd")

    if not place_entry:
        errors.append("未捕获到 /map-service/v2/place 响应")
        return errors
    if not around_entry:
        errors.append("未捕获到高德 /v3/place/around 响应")
        return errors

    place_resp = _parse_response_body(place_entry)
    around_resp = _parse_response_body(around_entry)

    if not place_resp:
        errors.append("/map-service/v2/place 响应体解析失败")
        return errors
    if not around_resp:
        errors.append("高德 /v3/place/around 响应体解析失败")
        return errors

    # 获取上游与下游的 pois 列表
    place_pois = place_resp.get("pois", []) or place_resp.get("data", {}).get("pois", []) if isinstance(place_resp, dict) else []
    around_pois = around_resp.get("pois", []) if isinstance(around_resp, dict) else []

    if not place_pois:
        errors.append("/map-service/v2/place 响应中未找到 pois 数据")
        return errors
    if not around_pois:
        errors.append("高德 /v3/place/around 响应中未找到 pois 数据")
        return errors

    # 比较第一条 POI 的关键字段
    fields = ["name", "pname", "cityname", "adname", "address"]
    place_poi = place_pois[0]
    around_poi = around_pois[0]

    for field in fields:
        place_val = place_poi.get(field, "")
        around_val = around_poi.get(field, "")
        if place_val != around_val:
            errors.append(
                f"字段 {field} 上游与高德不一致: 上游='{place_val}', 高德='{around_val}'"
            )

    return errors


def verify_around_language_en():
    """TC7: /v3/place/around 请求参数 language=en

    预期：下游请求包含 language=en
    """
    errors = []
    around_entry = _get_around_entry_for_language("en")

    if not around_entry:
        errors.append("未捕获到高德 /v3/place/around 请求（language=en）")
        return errors

    around_params = around_entry.get("query_params", {})
    lang = around_params.get("language")

    if lang != "en":
        errors.append(f"下游 /v3/place/around language 预期为 en，实际为 {lang}")

    return errors


def verify_around_response_english():
    """TC8: 返回结果 name、cityname、address 为英文

    预期：language=en 时，这些字段内容为英文
    """
    errors = []
    around_entry = _get_around_entry_for_language("en")

    if not around_entry:
        errors.append("未捕获到高德 /v3/place/around 响应（language=en）")
        return errors

    resp_data = _parse_response_body(around_entry)
    if not resp_data:
        errors.append("高德 /v3/place/around 响应体解析失败")
        return errors

    pois = resp_data.get("pois", []) if isinstance(resp_data, dict) else []
    if not pois:
        errors.append("高德 /v3/place/around 响应中未找到 pois 数据")
        return errors

    first_poi = pois[0]
    fields = ["name", "cityname", "address"]

    for field in fields:
        value = first_poi.get(field, "")
        if not value:
            errors.append(f"字段 {field} 值为空")
        elif not _is_english(value):
            errors.append(f"字段 {field} 预期为英文，实际为: {value}")

    return errors


def verify_pname_adname_not_converted():
    """TC9: [质检] pname、adname 保持高德原始返回值

    预期：language=en 时，pname 和 adname 不进行英文转换，保持高德原始返回值
    """
    errors = []
    place_entry = _get_first_place_entry()
    around_entry = _get_around_entry_for_language("en")

    if not place_entry:
        errors.append("未捕获到 /map-service/v2/place 响应")
        return errors
    if not around_entry:
        errors.append("未捕获到高德 /v3/place/around 响应（language=en）")
        return errors

    place_resp = _parse_response_body(place_entry)
    around_resp = _parse_response_body(around_entry)

    if not place_resp or not around_resp:
        errors.append("响应体解析失败")
        return errors

    place_pois = place_resp.get("pois", []) or place_resp.get("data", {}).get("pois", []) if isinstance(place_resp, dict) else []
    around_pois = around_resp.get("pois", []) if isinstance(around_resp, dict) else []

    if not place_pois or not around_pois:
        errors.append("未找到 pois 数据")
        return errors

    place_poi = place_pois[0]
    around_poi = around_pois[0]

    for field in ["pname", "adname"]:
        place_val = place_poi.get(field, "")
        around_val = around_poi.get(field, "")
        if place_val != around_val:
            errors.append(
                f"[质检] {field} 上游值 '{place_val}' 与高德原始值 '{around_val}' 不一致，"
                f"可能被错误转换"
            )

    return errors


def verify_around_default_simplified():
    """TC10: 周围搜索保持默认简体中文

    预期：不传 language 或传默认值时，返回字段为简体中文
    """
    errors = []
    place_entry = _get_first_place_entry()

    if not place_entry:
        errors.append("未捕获到 /map-service/v2/place 请求")
        return errors

    place_params = place_entry.get("query_params", {})
    language = place_params.get("language")

    # 检查上游是否未传 language 或传了默认值
    if language not in (None, "", "zh-CN", "zh", "zh-cn"):
        errors.append(
            f"本用例验证默认简体中文场景，但上游 language={language}，"
            f"请确认是否为默认场景"
        )

    # 检查响应是否为简体中文
    resp_data = _parse_response_body(place_entry)
    if not resp_data:
        errors.append("/map-service/v2/place 响应体解析失败")
        return errors

    pois = resp_data.get("pois", []) or resp_data.get("data", {}).get("pois", []) if isinstance(resp_data, dict) else []
    if not pois:
        errors.append("/map-service/v2/place 响应中未找到 pois 数据")
        return errors

    first_poi = pois[0]
    fields = ["name", "pname", "cityname", "adname", "address"]

    for field in fields:
        value = first_poi.get(field, "")
        if not value:
            errors.append(f"字段 {field} 值为空")
        elif _is_traditional_chinese(value):
            errors.append(f"字段 {field} 预期为简体中文，但检测为繁体: {value}")
        elif _is_english(value):
            errors.append(f"字段 {field} 预期为简体中文，但检测为英文: {value}")

    return errors


def run_all_verifications():
    """运行所有验证，返回汇总结果"""
    results = {}

    test_cases = [
        ("TC1_place_type_around", verify_place_type_around),
        ("TC2_language_passthrough_trd", lambda: verify_language_passthrough("trd")),
        ("TC3_place_type_routing", verify_place_type_routing),
        ("TC4_around_language_trd", verify_around_language_trd),
        ("TC5_around_response_traditional", verify_around_response_traditional),
        ("TC6_around_response_matches_amap", verify_around_response_matches_amap_trd),
        ("TC7_around_language_en", verify_around_language_en),
        ("TC8_around_response_english", verify_around_response_english),
        ("TC9_pname_adname_not_converted", verify_pname_adname_not_converted),
        ("TC10_around_default_simplified", verify_around_default_simplified),
    ]

    for name, func in test_cases:
        try:
            errors = func()
            results[name] = {
                "passed": len(errors) == 0,
                "errors": errors,
            }
        except Exception as e:
            results[name] = {
                "passed": False,
                "errors": [f"验证异常: {str(e)}"],
            }

    return results


def print_verification_report(results=None):
    """打印验证报告"""
    if results is None:
        results = run_all_verifications()

    print("\n" + "=" * 70)
    print("  /map-service/v2/place 周围搜索接口验证报告")
    print("=" * 70)

    passed = sum(1 for r in results.values() if r["passed"])
    failed = len(results) - passed

    for name, result in results.items():
        status = "PASS" if result["passed"] else "FAIL"
        print(f"\n  [{status}] {name}")
        if not result["passed"]:
            for err in result["errors"]:
                print(f"         - {err}")

    print("\n" + "-" * 70)
    print(f"  总计: {len(results)} 项 | 通过: {passed} | 失败: {failed}")
    print("=" * 70 + "\n")

    return results
