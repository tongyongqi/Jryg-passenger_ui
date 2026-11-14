# 编写时间：2026-11-12
# 本期功能：V1.5.0 接口日志解析与接口层断言的离线回归
"""V1.5.0 接口日志解析与接口层断言的离线回归。"""
import json
from pathlib import Path

import pytest

from jryg_hk_android.JRYG_v150_api_log import (
    API_PATHS,
    api_name_for_url,
    check_api_response,
    find_api_calls,
    parse_api_calls,
    parse_response,
    summarize_calls,
)


TRIP_SEND_LOG = [
    "E/encrypt (21450): getParams : {order_no=26B6PIEWECNW, email=v150_receipt@example.com}",
    "E/retrofit(21450): Sending request http://app-client-test.sunlightmobility.hk/passenger/order/tripSend",
    "E/retrofit(21450): order_no=26B6PIEWECNW&email=v150_receipt%40example.com",
    "E/retrofit(21450): url=http://app-client-test.sunlightmobility.hk/passenger/order/tripSend",
    'E/retrofit(21450): result={"code":10000,"data":null,"message":"成功"}',
    "E/retrofit(21450): Sending request http://app-client-test.sunlightmobility.hk/passenger/user/getInfo",
    'E/retrofit(21450): result={"code":10000,"data":{"email":"v150_receipt@example.com","user_id":301025},"message":"成功"}',
]

USER_SAVE_LOG = [
    "E/encrypt (21450): getParams : {email=v150_trim@example.com}",
    "E/retrofit(21450): Sending request http://app-client-test.sunlightmobility.hk/passenger/user/save",
    'E/retrofit(21450): result={"code":10000,"data":null,"message":"成功"}',
]


def test_api_paths_cover_requirement_interfaces():
    """需求接口清单必须全部登记在解析表中。"""
    expected = {
        "/passenger/user/save",
        "/passenger/contact/list",
        "/passenger/contact/save",
        "/passenger/contact/delete",
        "/passenger/contact/share",
        "/passenger/emergency/alarm",
        "/passenger/order/tripSend",
        "/passenger/user/getInfo",
    }
    assert expected <= set(API_PATHS.values())


def test_api_name_for_url_matches_requirement_paths():
    """接口路径必须映射到正确的逻辑名。"""
    assert api_name_for_url("http://h/passenger/order/tripSend") == "trip_send"
    assert api_name_for_url("http://h/passenger/user/save") == "user_save"
    assert api_name_for_url("http://h/passenger/user/getInfo") == "user_info"
    assert api_name_for_url("http://h/passenger/contact/list") == "contact_list"
    assert api_name_for_url("http://h/passenger/contact/save") == "contact_save"
    assert api_name_for_url("http://h/passenger/contact/delete") == "contact_delete"
    assert api_name_for_url("http://h/passenger/contact/share") == "contact_share"
    assert api_name_for_url("http://h/passenger/emergency/alarm") == "emergency_alarm"
    assert api_name_for_url("http://h/passenger/unknown/api") == ""


def test_parse_api_calls_extracts_url_params_and_response():
    """从logcat还原接口调用：URL、请求参数与响应码。"""
    calls = parse_api_calls(TRIP_SEND_LOG)
    trip = [call for call in calls if call["api"] == "trip_send"]
    assert len(trip) == 1
    call = trip[0]
    assert call["url"].endswith("/passenger/order/tripSend")
    assert call["params"]["order_no"] == "26B6PIEWECNW"
    assert call["params"]["email"] == "v150_receipt@example.com"
    assert call["code"] == 10000
    assert call["message"] == "成功"

    user_info = [call for call in calls if call["api"] == "user_info"]
    assert len(user_info) == 1
    assert user_info[0]["code"] == 10000
    assert user_info[0]["data"]["email"] == "v150_receipt@example.com"


def test_parse_response_handles_invalid_payload():
    """非JSON响应体不应抛异常，直接返回空结果。"""
    assert parse_response("not json") == {}
    assert parse_response("") == {}
    assert parse_response('{"code":10000,"message":"成功"}')["code"] == 10000


def test_flutter_network_event_does_not_override_response():
    """Flutter网络事件行的 result={response={...}} 不得覆盖真正的接口响应体。"""
    log = [
        "E/retrofit(21450): Sending request http://h/passenger/user/save",
        "E/retrofit(21450): email=demo@example.com",
        'E/retrofit(21450): result={"code":10000,"data":null,"message":"成功"}',
        "I/flutter native(21450): sendEvent event:__@app_network_response__ 2} "
        '{event_key=__@app_network_response__, event_arguments={identity=NetworkPost10235, '
        'result={response={"code":10000,"data":null,"message":"成功"}}}',
    ]
    calls = parse_api_calls(log)
    assert len(calls) == 1
    assert calls[0]["code"] == 10000
    assert calls[0]["message"] == "成功"
    assert calls[0]["params"]["email"] == "demo@example.com"


def test_signing_params_excluded_from_business_params():
    """nonce 等签名参数不计入业务请求参数。"""
    log = [
        "E/encrypt (21450): getSortParams : nonce=1794465927333",
        "E/retrofit(21450): Sending request http://h/passenger/user/save",
        "E/retrofit(21450): email=",
        'E/retrofit(21450): result={"code":10000,"data":null,"message":"成功"}',
    ]
    calls = parse_api_calls(log)
    assert calls[0]["params"] == {"email": ""}
    assert "nonce" not in calls[0]["params"]


def test_empty_email_param_is_captured():
    """空值参数也要被记录，便于断言清空邮箱场景。"""
    log = [
        "E/retrofit(21450): Sending request http://h/passenger/user/save",
        "E/retrofit(21450): email=",
        'E/retrofit(21450): result={"code":10000,"data":null,"message":"成功"}',
    ]
    calls = parse_api_calls(log)
    assert calls[0]["params"]["email"] == ""
    result = check_api_response(calls, "user_save", expect_code=10000,
                                expect_params={"email": ""})
    assert result["passed"] is True


def test_check_api_response_passes_on_success_code():
    """成功响应：接口层判定通过。"""
    calls = parse_api_calls(TRIP_SEND_LOG)
    result = check_api_response(calls, "trip_send", expect_code=10000,
                                 expect_params={"order_no": "26B6PIEWECNW"})
    assert result["matched"] is True
    assert result["passed"] is True
    assert result["code"] == 10000


def test_check_api_response_fails_when_api_not_called():
    """未观察到接口调用：判定为未命中，不能当作通过。"""
    calls = parse_api_calls(TRIP_SEND_LOG)
    result = check_api_response(calls, "user_save", expect_code=10000)
    assert result["matched"] is False
    assert result["passed"] is False
    assert "未观察到接口" in result["reason"]


def test_check_api_response_detects_wrong_code():
    """服务端返回错误码：判定不通过并给出错误信息。"""
    log = [
        "E/retrofit(21450): Sending request http://h/passenger/order/tripSend",
        'E/retrofit(21450): result={"code":40001,"data":null,"message":"发送过于频繁"}',
    ]
    calls = parse_api_calls(log)
    result = check_api_response(calls, "trip_send", expect_code=10000)
    assert result["matched"] is True
    assert result["passed"] is False
    assert result["code"] == 40001
    assert "频繁" in result["reason"]


def test_check_api_response_detects_param_mismatch():
    """请求参数与期望不符：判定不通过。"""
    calls = parse_api_calls(TRIP_SEND_LOG)
    result = check_api_response(calls, "trip_send", expect_code=10000,
                                expect_params={"email": "other@example.com"})
    assert result["passed"] is False
    assert "email" in result["reason"]


def test_check_api_response_detects_missing_param():
    """缺少请求参数：判定不通过。"""
    calls = parse_api_calls(TRIP_SEND_LOG)
    result = check_api_response(calls, "trip_send", expect_code=10000,
                                expect_params={"order_no": "OTHER"})
    assert result["passed"] is False
    assert "order_no" in result["reason"]


def test_forbidden_params_detected():
    """不应携带的参数存在时判定不通过。"""
    log = [
        "E/retrofit(21450): Sending request http://h/passenger/order/tripSend",
        "E/retrofit(21450): order_no=26B6PIEWECNW&auto_share=true",
        'E/retrofit(21450): result={"code":10000,"data":null,"message":"成功"}',
    ]
    calls = parse_api_calls(log)
    result = check_api_response(calls, "trip_send", expect_code=10000,
                                forbidden_params=["auto_share"])
    assert result["passed"] is False
    assert "auto_share" in result["reason"]


def test_forbidden_params_absent_passes():
    """不应携带的参数确实不存在时判定通过。"""
    calls = parse_api_calls(TRIP_SEND_LOG)
    result = check_api_response(calls, "trip_send", expect_code=10000,
                                forbidden_params=["auto_share"])
    assert result["passed"] is True


def test_expect_data_contains_validates_response_fields():
    """响应字段校验：缺失或值不符时判定不通过。"""
    calls = parse_api_calls(TRIP_SEND_LOG)
    ok = check_api_response(calls, "user_info", expect_code=10000,
                            expect_data_contains={"email": "v150_receipt@example.com"})
    assert ok["passed"] is True
    bad = check_api_response(calls, "user_info", expect_code=10000,
                             expect_data_contains={"email": "none@example.com"})
    assert bad["passed"] is False
    missing = check_api_response(calls, "user_info", expect_code=10000,
                                 expect_data_contains={"nick_name": "x"})
    assert missing["passed"] is False
    assert "nick_name" in missing["reason"]


def test_user_save_log_parsed():
    """用户信息保存接口解析。"""
    calls = parse_api_calls(USER_SAVE_LOG)
    result = check_api_response(calls, "user_save", expect_code=10000,
                                expect_params={"email": "v150_trim@example.com"})
    assert result["passed"] is True
    assert result["code"] == 10000


def test_summarize_calls_keeps_code_and_params():
    """摘要结构保留接口名、参数与响应码。"""
    calls = parse_api_calls(TRIP_SEND_LOG)
    summary = summarize_calls(calls)
    trip = [item for item in summary if item["api"] == "trip_send"][0]
    assert trip["code"] == 10000
    assert trip["params"]["order_no"] == "26B6PIEWECNW"


def test_find_api_calls_filters_by_name():
    """按逻辑名筛选接口调用。"""
    calls = parse_api_calls(TRIP_SEND_LOG)
    assert len(find_api_calls(calls, "trip_send")) == 1
    assert len(find_api_calls(calls, "user_info")) == 1
    assert find_api_calls(calls, "contact_save") == []


def test_device_steps_capture_records_api_calls(tmp_path, monkeypatch):
    """设备步骤抓取日志后应写入结构化接口调用。"""
    from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps

    case = V150DeviceSteps()
    case.android_settings = {"packages": {"passenger_hk": "com.test.app"},
                             "device": {"udid": "fake-udid"}}
    case._receipt_case_directory = tmp_path
    case._receipt_record = {"evidence": []}
    monkeypatch.setattr(case, "_v150_adb", Mock_log(TRIP_SEND_LOG))
    case._receipt_logcat_pid = "12345"
    evidence = case.v150_receipt_collect_network_log("test", order_no="26B6PIEWECNW")
    assert evidence["captured"] is True
    assert "trip_send" in evidence["api_names"]
    assert "user_info" in evidence["api_names"]
    assert case._receipt_record["network_log_summary"]["api_names"]
    saved = list(tmp_path.glob("*_network_log.json"))
    assert len(saved) == 1
    body = json.loads(saved[0].read_text(encoding="utf-8"))
    assert body["api_calls"][0]["api"] == "trip_send"


def test_email_capture_records_user_save(tmp_path, monkeypatch):
    """邮箱保存抓取应识别 user/save 接口。"""
    from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps

    case = V150DeviceSteps()
    case.android_settings = {"packages": {"passenger_hk": "com.test.app"},
                             "device": {"udid": "fake-udid"}}
    case._receipt_case_directory = tmp_path
    monkeypatch.setattr(case, "_v150_adb", Mock_log(USER_SAVE_LOG))
    case._email_logcat_pid = "12345"
    evidence = case._v150_email_collect_api_log("test")
    assert evidence["captured"] is True
    assert "user_save" in evidence["api_names"]
    assert getattr(case, "_last_email_api_calls")[0]["code"] == 10000


class Mock_log:
    """模拟 _v150_adb 返回固定日志。"""

    def __init__(self, lines):
        """初始化实例。"""
        self.lines = lines

    def __call__(self, *args):
        """__call__方法。"""
        return "\n".join(self.lines)


@pytest.mark.parametrize("payload,expected_code", [
    ('{"code":10000,"message":"成功"}', 10000),
    ('{"code":40001,"message":"发送过于频繁"}', 40001),
])
def test_parse_response_codes(payload, expected_code):
    """响应码解析按服务端返回原样取值。"""
    assert parse_response(payload)["code"] == expected_code
