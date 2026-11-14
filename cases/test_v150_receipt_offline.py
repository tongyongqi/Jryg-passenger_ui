# 编写时间：2026-11-10
# 本期功能：V1.5.0 收据 UI 解析和提交保护离线回归
"""收据UI解析和提交保护离线回归；不连接设备、不发送邮件。"""

from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from jryg_hk_android.JRYG_android_ui import normalized_tree
from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps


PACKAGE = "com.sunlightmobility.client"


def node(parent, rid, text="", cls="android.widget.TextView", **attrs):
    """在 parent 下创建一个带 resource-id 的 UI 节点，用于构造测试用 UI 树。"""
    return ET.SubElement(parent, cls, {"resource-id": f"{PACKAGE}:id/{rid}",
        "class": cls, "text": text, "displayed": "true", "enabled": "true",
        "bounds": "[20,50][1100,220]", **attrs})


def dialog(email="", saved=False, enabled=False):
    """构造一个模拟收据弹框的 UI 树，支持空输入、已保存邮箱、发送按钮启用状态。"""
    root = ET.Element("hierarchy")
    content = node(root, "dialog_content", cls="android.widget.LinearLayout")
    node(content, "tv_title", "發送行程收據")
    node(content, "tv_subtitle", "行程收據將發送至您的電子郵箱")
    if saved:
        node(content, "email_value", email)
        node(content, "edit", "修改")
    else:
        node(content, "et_email", email or "請輸入電子郵箱", "android.widget.EditText",
             hint="請輸入電子郵箱", focused="true")
    node(content, "btn_send", "發送", "android.widget.Button", enabled=str(enabled).lower())
    node(content, "iv_close", cls="android.widget.ImageView")
    return root


def parse(root, keyboard=False):
    """将 UI 树序列化后调用 _v150_receipt_parse_dialog 解析弹框状态。"""
    return V150DeviceSteps._v150_receipt_parse_dialog(ET.tostring(root, encoding="unicode"), keyboard)


def test_empty_dialog_hint_and_disabled_state():
    """空弹框：输入框展示 placeholder、键盘弹出、发送按钮禁用、标题/副标题正确。"""
    state = parse(dialog(), keyboard=True)
    assert state["present"] and state["email_input"] and state["keyboard"]
    assert state["email"] == ""
    assert state["email_placeholder"] == "請輸入電子郵箱"
    assert state["send_text"] == "發送" and not state["send_enabled"]
    assert state["title"] == "發送行程收據"
    assert state["subtitle"] == "行程收據將發送至您的電子郵箱"
    assert state["close"] and not state["modify"]


@pytest.mark.parametrize("value", ["user@example.com", "  user@example.com  ", "invalid", "a@b@c.com"])
def test_dialog_preserves_input_exactly(value):
    """弹框中原样保留输入值不做 trim 或校验，发送按钮启用。"""
    state = parse(dialog(value, enabled=True))
    assert state["email"] == value
    assert state["send_enabled"]


def test_saved_dialog_reads_static_email_and_modify():
    """已保存邮箱的弹框：展示静态邮箱文案和「修改」按钮，无输入框。"""
    state = parse(dialog("user@example.com", saved=True, enabled=True))
    assert not state["email_input"]
    assert state["email"] == "user@example.com"
    assert state["modify_text"] == "修改"


def test_no_dialog_does_not_match_email_settings_input():
    """非收据弹框的邮箱设置页输入框不会被误识别为弹框。"""
    root = ET.Element("hierarchy")
    node(root, "et_email", "", "android.widget.EditText")
    assert not parse(root)["present"]
    assert parse(root)["email"] is None


def test_hidden_send_button_is_not_accepted():
    """发送按钮 displayed=false 时不会被当作可用按钮。"""
    root = dialog()
    button = next(n for n in root.iter() if n.get("resource-id", "").endswith("/btn_send"))
    button.set("displayed", "false")
    assert not parse(root)["send_button"]


def test_different_dialog_title_is_not_normalized():
    """简体标题「发送行程收据」不被归一化为繁体，保留实际文案。"""
    root = dialog()
    title = next(n for n in root.iter() if n.get("resource-id", "").endswith("/tv_title"))
    title.set("text", "发送行程收据")
    assert parse(root)["title"] == "发送行程收据"
    assert parse(root)["title"] != "發送行程收據"


@pytest.mark.parametrize("status,kind,eligible", [
    ("已完成", "即時用車", True), ("已完成", "預約用車", False),
    ("待支付", "即時用車", False), ("已取消", "即時用車", False),
])
def test_only_same_card_completed_instant_is_selected(status, kind, eligible):
    """仅「已完成 + 即時用車」的订单卡片被收据功能选中，其他组合不选。"""
    root = ET.Element("hierarchy")
    card = node(root, "rl_order_item_layout", cls="android.widget.LinearLayout")
    node(card, "tv_type_order", status)
    node(card, "tv_type_scheduling", kind)
    node(card, "tv_guid_date", "2026-11-10 12:00:00")
    normalized = normalized_tree(ET.tostring(root, encoding="unicode"), PACKAGE)
    assert bool(V150DeviceSteps._v150_receipt_instant_cards(normalized)) is eligible


def test_completed_detail_is_not_home_due_to_shared_safe_icon():
    """订单详情页含安全中心图标但 page_type=order_detail 而非 home。"""
    root = ET.Element("hierarchy")
    node(root, "tv_safe", "安全中心")
    node(root, "tv_order_no", "訂單編號 26TEST000001")
    node(root, "tv_status_name", "打錶的士行程結束")
    case = V150DeviceSteps()
    case._passenger_root = Mock(return_value=normalized_tree(ET.tostring(root, encoding="unicode"), PACKAGE))
    assert case._v150_current_page_type() == "order_detail"


def test_receipt_hint_uses_actual_native_hint_without_trimming():
    """邮箱读取使用实际 hint 判断空值，不 trim 原始文案。"""
    case = V150DeviceSteps()
    element = Mock()
    element.text = "請輸入電子郵箱"
    element.get_attribute.side_effect = {"resource-id": f"{PACKAGE}:id/et_email", "hint": "請輸入電子郵箱"}.get
    assert case._v150_native_email_value(element) == ""
    element.text = "  user@example.com  "
    assert case._v150_native_email_value(element) == "  user@example.com  "


@pytest.mark.parametrize("present,enabled", [(False, False), (True, False)])
def test_missing_or_disabled_send_never_submits(present, enabled):
    """弹框不存在或发送按钮禁用时点击发送抛 AssertionError 且不执行点击。"""
    case = V150DeviceSteps()
    case._v150_receipt_dialog_state = Mock(return_value={"present": present, "send_button": True, "send_enabled": enabled})
    case._v150_receipt_element = Mock()
    with pytest.raises(AssertionError):
        case.v150_receipt_click_send()
    case._v150_receipt_element.assert_not_called()


def test_send_submits_exactly_once():
    """弹框存在且发送按钮启用时点击发送执行一次且仅一次。"""
    case = V150DeviceSteps()
    case._v150_receipt_dialog_state = Mock(return_value={"present": True, "send_button": True, "send_enabled": True})
    element = Mock()
    case._v150_receipt_element = Mock(return_value=element)
    assert case.v150_receipt_click_send()
    case._v150_receipt_element.assert_called_once_with("btn_send")
    element.click.assert_called_once_with()


def test_close_uses_real_close_control_not_back():
    """关闭弹框用实际 iv_close 控件而非 driver.back。"""
    case = V150DeviceSteps()
    case.client = Mock()
    case._v150_receipt_dialog_ready = Mock(side_effect=[True, False])
    case._v150_receipt_element = Mock()
    case._wait = lambda predicate, message, timeout: predicate() or pytest.fail(message)
    assert case.v150_receipt_close_dialog()
    case._v150_receipt_element.assert_called_once_with("iv_close")
    case.client.driver.back.assert_not_called()


def test_read_missing_email_is_not_treated_as_empty():
    """弹框中邮箱读为 None 时抛 RuntimeError 而非当作空字符串。"""
    case = V150DeviceSteps()
    case._v150_receipt_dialog_state = Mock(return_value={"present": True, "email": None})
    with pytest.raises(RuntimeError, match="不能当作未设置"):
        case.v150_receipt_read_saved_email()


def test_close_button_can_be_dialog_content_sibling():
    """关闭按钮作为 dialog_content 的兄弟节点时仍能被识别。"""
    root = dialog()
    content = next(n for n in root.iter() if n.get("resource-id", "").endswith("/dialog_content"))
    close = next(n for n in content if n.get("resource-id", "").endswith("/iv_close"))
    content.remove(close)
    root.append(close)
    assert parse(root)["close"]


def test_receipt_prepare_respects_email_keyword_only_signature():
    """_prepare 方法仅接受 email 关键字参数，不混用位置参数。"""
    from unittest.mock import create_autospec
    from cases.JRYG_test_android_v150_receipt import TestV150ReceiptDevice as ReceiptCase
    case = ReceiptCase()
    case.v150_email_read_current = Mock(return_value="")
    case.v150_email_save = create_autospec(case.v150_email_save, return_value=case.RECEIPT_EMAIL)
    case.v150_open_completed_order_detail = Mock()
    case.v150_open_email_settings = Mock()
    case._v150_current_page_type = Mock(return_value="order_detail")
    case._capture = Mock()
    # 重置 class 缓存以模拟首次进入
    ReceiptCase._receipt_current_email = None
    ReceiptCase._receipt_order_binding = None
    ReceiptCase._receipt_order_no_cached = None
    case._prepare(case.RECEIPT_EMAIL)
    case.v150_email_save.assert_called_once_with("receipt_precondition", email=case.RECEIPT_EMAIL)
    assert case._receipt_phase == "measurement"
    # 恢复类属性默认值
    ReceiptCase._receipt_current_email = None
    ReceiptCase._receipt_order_binding = None
    ReceiptCase._receipt_order_no_cached = None


def test_requirement_mismatch_records_actual_then_continues(tmp_path):
    """期望与实际不符时记录差异并生成 product_bug 证据，后续检查继续执行。"""
    from cases.JRYG_test_android_v150_receipt import TestV150ReceiptDevice as ReceiptCase
    case = ReceiptCase()
    case._receipt_case_directory = tmp_path
    case._receipt_request = Mock()
    case._receipt_request.node.nodeid = "receipt-check"
    case._receipt_record = {"checks": [], "evidence": []}
    case._capture = Mock()
    assert not case._expect("精确提示", "發送過於頻繁", "发送过于频繁")
    assert case._expect("后续检查", "ok", "ok")
    assert (tmp_path / "product_bug_1.json").is_file()
    assert len(case._receipt_record["checks"]) == 2
    with pytest.raises(AssertionError, match="精确提示"):
        case._finish_checks()


def test_missing_toast_capture_is_not_confirmed_product_bug(tmp_path):
    """toast 未抓到时归类为 observation_gap 而非 product_bug，不生成 product_bug 文件。"""
    from cases.JRYG_test_android_v150_receipt import TestV150ReceiptDevice as ReceiptCase
    case = ReceiptCase()
    case._receipt_case_directory = tmp_path
    case._receipt_request = Mock()
    case._receipt_request.node.nodeid = "toast-evidence"
    case._receipt_record = {"checks": [], "evidence": []}
    case._capture = Mock()
    assert not case._expect("发送成功提示", [], [case.SUCCESS])
    assert case._receipt_record["checks"][0]["category"] == "observation_gap"
    assert not (tmp_path / "product_bug_1.json").exists()
    assert (tmp_path / "observation_gap_1.json").exists()


def _receipt_case_for_prompt():
    """构造一个带空检查记录和 Mock _capture 的收据用例实例。"""
    from cases.JRYG_test_android_v150_receipt import TestV150ReceiptDevice as ReceiptCase
    case = ReceiptCase()
    case._receipt_record = {"checks": [], "evidence": []}
    case._capture = Mock()
    return case


def test_saved_email_hides_prompt_and_set_and_send():
    """已设置邮箱：行程结束上方提示栏与「設置並發送」不展示，发送入口仍存在。"""
    case = _receipt_case_for_prompt()
    case.v150_receipt_prompt_present = Mock(return_value={
        "prompt": False, "prompt_text": "", "set_and_send": False, "set_text": "",
        "send_button": True, "send_text": "發送行程收據"})
    case._prepare = Mock()
    case.test_receipt_saved_email_entry_sends_directly_without_dialog()
    requirements = [check["requirement"] for check in case._receipt_record["checks"]]
    assert "已设置邮箱时行程结束上方提示栏不展示" in requirements
    assert "已设置邮箱时设置并发送按钮不展示" in requirements
    assert "已设置邮箱时发送行程收据入口仍存在" in requirements
    assert all(check["passed"] for check in case._receipt_record["checks"])


def test_unset_email_shows_prompt_and_set_and_send():
    """未设置邮箱：行程结束上方提示栏与「設置並發送」都展示，且入口可弹出弹框。"""
    case = _receipt_case_for_prompt()
    case.v150_receipt_prompt_present = Mock(return_value={
        "prompt": True, "prompt_text": case.PROMPT, "set_and_send": True,
        "set_text": "設置並發送", "send_button": True, "send_text": "發送行程收據"})
    case._prepare = Mock()
    case._open = Mock(return_value={
        "present": True, "title": case.TITLE, "subtitle": case.SUBTITLE, "email_input": True,
        "email": "", "send_enabled": False, "keyboard": True})
    case.test_receipt_unset_email_entry_shows_set_and_send_dialog()
    requirements = [check["requirement"] for check in case._receipt_record["checks"]]
    assert "未设置邮箱时展示行程结束上方提示栏" in requirements
    assert "未设置邮箱时展示设置并发送按钮" in requirements
    assert "设置并发送入口弹出弹框" in requirements
    assert all(check["passed"] for check in case._receipt_record["checks"])


def test_empty_email_save_restores_set_and_send_entry():
    """设置页保存空邮箱成功后，回到行程详情应重新展示提示栏与「設置並發送」。"""
    case = _receipt_case_for_prompt()
    case._prepare = Mock()
    case.v150_open_email_settings = Mock()
    case.v150_email_read_current = Mock(return_value=case.RECEIPT_EMAIL)
    case.v150_email_save = Mock(return_value="")
    case.v150_open_completed_order_detail = Mock()
    case.v150_receipt_prompt_present = Mock(return_value={
        "prompt": True, "prompt_text": case.PROMPT, "set_and_send": True,
        "set_text": "設置並發送", "send_button": True, "send_text": "發送行程收據"})
    case._open = Mock(return_value={
        "present": True, "title": case.TITLE, "subtitle": case.SUBTITLE, "email_input": True,
        "email": "", "send_enabled": False, "keyboard": True})
    try:
        case.test_receipt_empty_email_save_restores_set_and_send_entry()
    finally:
        from cases.JRYG_test_android_v150_receipt import TestV150ReceiptDevice as ReceiptCase
        ReceiptCase._receipt_current_email = None
    case.v150_email_save.assert_called_once_with("receipt_empty_save", email="")
    requirements = [check["requirement"] for check in case._receipt_record["checks"]]
    assert "设置页保存空邮箱后回读为空" in requirements
    assert "保存空邮箱后行程结束上方提示栏重新展示" in requirements
    assert "保存空邮箱后设置并发送按钮重新展示" in requirements
    assert all(check["passed"] for check in case._receipt_record["checks"])


def test_direct_send_capture_starts_before_entry_click():
    """已设置邮箱时入口即发送：接口抓取必须在点击入口之前开启。"""
    from cases.JRYG_test_android_v150_receipt import TestV150ReceiptDevice as ReceiptCase
    case = ReceiptCase()
    case._receipt_record = {"checks": [], "evidence": []}
    case._capture = Mock()
    order = []
    case.v150_receipt_start_network_capture = Mock(side_effect=lambda tag: order.append("capture"))
    case.v150_receipt_collect_network_log = Mock(
        side_effect=lambda tag, order_no=None: (order.append("collect"), {"api_calls": []})[1])
    case.v150_receipt_observe_toasts = Mock(return_value=[])
    case.v150_receipt_prompt_present = Mock(return_value={
        "prompt": False, "prompt_text": "", "set_and_send": False, "set_text": "",
        "send_button": True, "send_text": "發送行程收據"})
    case._record_action = lambda name: __import__("contextlib").nullcontext()
    case.v150_open_receipt_dialog = Mock(
        side_effect=lambda tag="v150_receipt", entry="send": (order.append("click"), {"present": False})[1])
    case._send_and_observe_direct()
    assert order == ["capture", "click", "collect"]


@pytest.mark.parametrize("text", ["已發送，稍後查看", "郵箱格式不正確", "未列入预期的实际错误"])
def test_visual_toast_reads_actual_not_expected_filter(tmp_path, monkeypatch, text):
    """视觉 toast 读取实际 OCR 文案而非按预期列表过滤，保留截图证据。"""
    import cv2
    import numpy as np
    from jryg_hk_android import JRYG_android_route_ocr
    image = np.full((1000, 500, 3), 240, dtype=np.uint8)
    cv2.rectangle(image, (120, 480), (380, 530), (40, 40, 40), -1)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    case = V150DeviceSteps()
    case.client = Mock()
    case.client.driver.get_screenshot_as_png.return_value = encoded.tobytes()
    case._receipt_case_directory = tmp_path
    case._receipt_record = {"evidence": []}
    monkeypatch.setattr(JRYG_android_route_ocr, "recognize_map", Mock(return_value=[
        {"text": text, "confidence": 1, "x": .1, "y": .2}]))
    assert case._v150_receipt_visual_toasts() == {text}
    assert len(list(tmp_path.glob("*.png"))) == 1


def test_visual_toast_does_not_treat_white_background_as_toast():
    """纯白背景不被误判为 toast 区域。"""
    import numpy as np
    image = np.full((1000, 500, 3), 240, dtype=np.uint8)
    assert V150DeviceSteps._v150_receipt_toast_regions(image) == []


def test_action_video_is_stopped_and_preserved_on_failure(tmp_path):
    """操作录像在失败时停止并保存为证据文件。"""
    import base64
    from cases.JRYG_test_android_v150_receipt import TestV150ReceiptDevice as ReceiptCase
    case = ReceiptCase()
    case.client = Mock()
    case.client.driver.stop_recording_screen.return_value = base64.b64encode(b"video-evidence").decode()
    case._receipt_case_directory = tmp_path
    case._receipt_record = {"evidence": []}
    with pytest.raises(RuntimeError, match="action failed"):
        with case._record_action("action"):
            raise RuntimeError("action failed")
    case.client.driver.stop_recording_screen.assert_called_once_with()
    assert len(case._receipt_record["evidence"]) == 1
    assert next(tmp_path.glob("*.mp4")).read_bytes() == b"video-evidence"


def test_network_log_capture_extracts_relevant_lines(tmp_path, monkeypatch):
    """网络日志抓取：过滤出 retrofit 和 flutter 相关行，解析接口调用和响应码。"""
    case = V150DeviceSteps()
    case.android_settings = {"packages": {"passenger_hk": "com.test.app"},
                             "device": {"udid": "fake-udid"}}
    case._receipt_case_directory = tmp_path
    case._receipt_record = {"evidence": []}
    log = ('E/retrofit(12345): Sending request http://h/passenger/order/tripSend\n'
           'E/retrofit(12345): result={"code":10000,"data":{"order_no":"ABC123"},"message":"成功"}\n'
           'W/flutter(12345): email sent\n'
           'I/other(12345): irrelevant line\n')
    monkeypatch.setattr(case, "_v150_adb", Mock(side_effect=["12345", "", log, log]))
    pid = case.v150_receipt_start_network_capture("test")
    assert pid == "12345"
    evidence = case.v150_receipt_collect_network_log("test", order_no="ABC123")
    assert evidence["captured"] is True
    assert evidence["pid"] == "12345"
    assert evidence["relevant_lines"] == 3
    assert any("tripSend" in line for line in evidence["log"])
    assert any("email sent" in line for line in evidence["log"])
    assert evidence["order_no"] == "ABC123"
    assert "trip_send" in evidence["api_names"]
    assert any(e.get("phase") == "network_log" for e in case._receipt_record["evidence"])
    assert case._receipt_record["network_log_summary"]["relevant_lines"] == 3
    assert case._receipt_record["api_calls"][0]["code"] == 10000


def test_network_log_capture_returns_not_started_when_pid_missing(tmp_path):
    """未启动网络抓取（pid 缺失）时返回 captured=False 并说明原因。"""
    case = V150DeviceSteps()
    case._receipt_case_directory = tmp_path
    case._receipt_record = {"evidence": []}
    evidence = case.v150_receipt_collect_network_log("test")
    assert evidence["captured"] is False
    assert "未启动" in evidence["reason"]
