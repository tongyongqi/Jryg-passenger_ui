"""司机 UI 仅打开/出车、订单全部接口操作的离线回归。"""

import json
from pathlib import Path
import sys
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "JRYG_Passenger_UI_HK-ios"))

import JRYG_run_driver_flow as ui
from jryg_hk_ios import JRYG_driver_order_api as backend
from test_driver_readiness import OrderBase, order_module


def response(data=None, code=10000, status=200):
    return status, {"code": code, "data": data or {}}


@pytest.fixture
def api():
    client = Mock()
    client.get_out_car_status.return_value = response({"is_online": 1})
    client.get_serving_order.return_value = response({"has_serving_order": False})
    client.get_service_detail.return_value = response({"order": {
        "start_lat": "22.3", "start_lng": "114.1", "end_lat": "22.4", "end_lng": "114.2"}})
    client.grab_order.return_value = response()
    client.service_change.return_value = response()
    client.confirm_bill.return_value = response()
    client.polling_order.return_value = response({"order_no": "test-order"})
    return client


@pytest.fixture
def flow(api, monkeypatch):
    monkeypatch.setattr(backend.time, "sleep", lambda seconds: None)
    return backend.DriverOrderAPI(api, Mock())


@pytest.fixture
def driver(monkeypatch):
    client = Mock()
    monkeypatch.setattr(ui.wda, "Client", Mock(return_value=client))
    args = ui.parser().parse_args([])
    instance = ui.DriverUIFlow(args)
    instance.wait_for = Mock(return_value=(ET.Element("root"), "offline"))
    instance.act = Mock()
    instance.root = Mock(return_value=ET.Element("root"))
    return instance


def test_default_is_ui_online_only(driver):
    driver.wait_for.side_effect = [(ET.Element("root"), "offline"), (ET.Element("root"), "online")]
    driver.run()
    driver.client.app_activate.assert_called_once_with(ui.BUNDLE_ID)
    driver.act.assert_called_once()
    assert driver.act.call_args.args[1] == ui.ACTION_LABELS["offline"]
    driver.client.swipe.assert_not_called()
    assert driver.last_phase == "online"


@pytest.mark.parametrize("phase", ["online", "offer"])
def test_online_ui_never_accepts_or_slides(driver, phase):
    driver.wait_for.return_value = ET.Element("root"), phase
    driver.run()
    driver.act.assert_not_called()
    driver.client.swipe.assert_not_called()


@pytest.mark.parametrize("phase", ["login", "code", "pickup", "onboard", "tail", "destination", "bill"])
def test_ui_rejects_login_or_existing_trip(driver, phase):
    driver.wait_for.return_value = ET.Element("root"), phase
    with pytest.raises(RuntimeError):
        driver.run()
    driver.act.assert_not_called()
    driver.client.send_keys.assert_not_called()


def test_inspect_never_goes_online(driver):
    driver.args.inspect = True
    driver.run()
    driver.act.assert_not_called()


@pytest.mark.parametrize("stop,states", [
    ("pickup", [1]), ("onboard", [1, 2]), ("destination", [1, 2, 3]), ("bill", [1, 2, 3, 4]),
])
def test_api_replaces_order_sliders(flow, api, stop, states):
    flow.advance("test-order", stop_after=stop)
    assert [call.kwargs["service_status"] for call in api.service_change.call_args_list] == states
    api.grab_order.assert_called_once_with("test-order")
    api.login.assert_not_called()
    api.handle_work_status.assert_not_called()
    api.confirm_bill.assert_not_called()
    if stop == "bill":
        assert api.service_change.call_args.kwargs["latitude"] == 22.4
        assert api.service_change.call_args.kwargs["longitude"] == 114.2


def test_online_payment_does_not_confirm_cash(flow, api):
    flow.advance("test-order", stop_after="complete", fare="5", payment="online")
    assert [call.kwargs["service_status"] for call in api.service_change.call_args_list] == [1, 2, 3, 4]
    api.confirm_bill.assert_called_once_with("test-order", order_amount="5", other_amount=0)


def test_cash_collection_uses_status_five(flow, api):
    flow.advance("test-order", stop_after="complete", fare="5", payment="cash", cash_collected=True)
    assert [call.kwargs["service_status"] for call in api.service_change.call_args_list] == [1, 2, 3, 4, 5]


def test_unconfirmed_cash_stops_before_grab(flow, api):
    with pytest.raises(AssertionError, match="明确确认"):
        flow.advance("test-order", stop_after="complete", fare="5", payment="cash")
    api.grab_order.assert_not_called()


@pytest.mark.parametrize("failed_status", [1, 2, 3, 4])
def test_failed_status_never_advances_or_submits_bill(flow, api, failed_status):
    api.service_change.side_effect = [response()] * (failed_status - 1) + [response(code=20156)]
    with pytest.raises(AssertionError, match=f"状态 {failed_status} 变更"):
        flow.advance("test-order", stop_after="complete", fare="5")
    assert api.service_change.call_count == failed_status
    api.confirm_bill.assert_not_called()


@pytest.mark.parametrize("status,code", [(500, 10000), (200, 99999)])
def test_grab_failure_stops_state_changes(flow, api, status, code):
    api.grab_order.return_value = response(status=status, code=code)
    with pytest.raises(AssertionError, match="接单失败"):
        flow.advance("test-order")
    api.service_change.assert_not_called()


def test_duplicate_grab_requires_matching_driver_order(flow, api):
    api.grab_order.return_value = response(code=10011)
    api.get_serving_order.return_value = response({"order_no": "another-order"})
    with pytest.raises(AssertionError, match="当前司机"):
        flow.advance("test-order")
    api.service_change.assert_not_called()


@pytest.mark.parametrize("coords", [{}, {"start_lat": "nan", "start_lng": 114, "end_lat": 22, "end_lng": 114}])
def test_invalid_coordinates_are_not_guessed(flow, api, coords):
    api.get_service_detail.return_value = response({"order": coords})
    with pytest.raises(AssertionError, match="坐标"):
        flow.advance("test-order")
    api.service_change.assert_not_called()


def test_poll_uses_dispatched_order(flow, api):
    assert flow.poll(1, 0) == "test-order"
    api.grab_order.assert_not_called()


def test_poll_rejects_ambiguous_orders(flow, api):
    api.polling_order.return_value = response({"list": [{"order_no": "first"}, {"order_no": "second"}]})
    with pytest.raises(AssertionError, match="多个派单"):
        flow.poll(1, 0)
    assert flow.poll(1, 0, expected_order_no="second") == "second"


def test_injected_app_token_never_logs_in(api, monkeypatch):
    monkeypatch.setenv("HK_DRIVER_ACCESS_TOKEN", "current-app-token")
    backend.load_app_session(api)
    assert api.access_token == "current-app-token"
    api.login.assert_not_called()
    api.send_auth_code.assert_not_called()


def test_app_session_file_is_loaded_without_login(api, tmp_path, monkeypatch):
    monkeypatch.delenv("HK_DRIVER_ACCESS_TOKEN", raising=False)
    filename = tmp_path / "driver_session.json"
    filename.write_text(json.dumps({"data": {"sign_info": {"access_token": "app-token"}}}))
    backend.load_app_session(api, filename)
    assert api.access_token == "app-token"
    api.login.assert_not_called()


def test_missing_app_session_is_explicit_failure(api, monkeypatch):
    monkeypatch.delenv("HK_DRIVER_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("HK_DRIVER_SESSION_FILE", raising=False)
    with pytest.raises(RuntimeError, match="不会自动接口登录"):
        backend.load_app_session(api)
    api.login.assert_not_called()


@pytest.mark.parametrize("token", ["", "bad\ntoken", "bad;cookie"])
def test_invalid_app_tokens_are_rejected(api, monkeypatch, token):
    monkeypatch.setenv("HK_DRIVER_ACCESS_TOKEN", token)
    monkeypatch.delenv("HK_DRIVER_SESSION_FILE", raising=False)
    with pytest.raises(RuntimeError):
        backend.load_app_session(api)


def test_paid_completion_is_verified(flow, api):
    api.get_trip_detail.return_value = response({"order": {"order_status": 8, "pay_status": 1}})
    flow.wait_completed("test-order", 1)


def test_unpaid_order_is_not_success(flow, api, monkeypatch):
    api.get_trip_detail.return_value = response({"order": {"order_status": 8, "pay_status": 0}})
    monkeypatch.setattr(backend.time, "monotonic", Mock(side_effect=[0, 0, 2]))
    with pytest.raises(TimeoutError, match="未支付"):
        flow.wait_completed("test-order", 1)


def test_app_mode_does_not_create_a_second_socket(api, monkeypatch):
    monkeypatch.delenv("HK_DRIVER_USE_API_SOCKET", raising=False)
    instance = OrderBase()
    instance.driver_api = api
    instance.driver_ui = Mock(last_phase="online")
    instance._driver_api_start_socket = Mock()
    instance._driver_api_require_ready("test")
    instance._driver_api_start_socket.assert_not_called()
    api.handle_work_status.assert_not_called()


def test_passenger_flow_uses_ui_go_online_and_existing_session(api, monkeypatch):
    monkeypatch.setenv("HK_DRIVER_ACCESS_TOKEN", "app-token")
    monkeypatch.setenv("HK_DRIVER_WDA_URL", "http://127.0.0.1:8200")
    monkeypatch.setattr(order_module, "SETTINGS", {"device": {"wda_url": "http://127.0.0.1:8100"}})
    driver = Mock()
    monkeypatch.setattr(order_module, "DriverUIFlow", Mock(return_value=driver))
    instance = OrderBase()
    instance.driver_api = api
    instance._driver_ui_go_online("test")
    driver.ensure_online.assert_called_once()
    assert api.access_token == "app-token"
    api.login.assert_not_called()
    api.handle_work_status.assert_not_called()


def test_passenger_and_driver_cannot_share_wda(api, monkeypatch):
    monkeypatch.setenv("HK_DRIVER_ACCESS_TOKEN", "app-token")
    monkeypatch.setenv("HK_DRIVER_WDA_URL", "http://127.0.0.1:8100")
    monkeypatch.setattr(order_module, "SETTINGS", {"device": {"wda_url": "http://127.0.0.1:8100"}})
    instance = OrderBase()
    instance.driver_api = api
    with pytest.raises(AssertionError, match="同一 WDA"):
        instance._driver_ui_go_online("test")


def test_driver_entry_hands_order_steps_to_api_only(driver, monkeypatch):
    from JRYG_Passenger_API_HK.cases import JRYG_test_hk_driver_api as clients
    api = Mock()
    orders = Mock()
    orders.poll.return_value = "test-order"
    monkeypatch.setattr(clients, "HKDriverApiClient", Mock(return_value=api))
    loader = Mock()
    monkeypatch.setattr(backend, "load_app_session", loader)
    monkeypatch.setattr(backend, "DriverOrderAPI", Mock(return_value=orders))
    driver.args.stop_after = "bill"
    driver.ensure_online = Mock()
    driver.run()
    driver.ensure_online.assert_called_once()
    loader.assert_called_once_with(api, driver.args.session_file)
    orders.advance.assert_called_once_with("test-order", stop_after="bill", fare=None,
                                           surcharge=0, payment="online", cash_collected=False)
    driver.act.assert_not_called()
    driver.client.swipe.assert_not_called()


def test_cached_online_state_is_not_used_after_driver_leaves_listening(driver):
    driver.last_phase = "online"
    driver.root.return_value = ET.fromstring('<root><node visible="true" label="點擊出車" /></root>')
    with pytest.raises(RuntimeError, match="离开听单"):
        driver.check_online()
    driver.act.assert_not_called()


def test_app_preflight_reads_current_ui_state(api, monkeypatch):
    monkeypatch.delenv("HK_DRIVER_USE_API_SOCKET", raising=False)
    instance = OrderBase()
    instance.driver_api = api
    instance.driver_ui = Mock()
    instance.driver_ui.check_online.side_effect = RuntimeError("司机 App 离开听单")
    with pytest.raises(RuntimeError, match="离开听单"):
        instance._driver_api_require_ready("test")
    instance.driver_ui.check_online.assert_called_once()
    api.handle_work_status.assert_not_called()


def test_five_order_stages_send_only_http_requests(monkeypatch):
    """保留真实 HTTP 客户端封装，用 Mock 网络验证四次状态 POST 和一次账单 POST。"""
    from JRYG_Passenger_API_HK.cases import JRYG_test_hk_driver_api as clients

    data = {"is_online": 1, "order": {
        "start_lat": "22.3", "start_lng": "114.1", "end_lat": "22.4", "end_lng": "114.2"}}
    reply = Mock(status_code=200, text="mock-response")
    reply.json.return_value = {"code": 10000, "data": data}
    get = Mock(return_value=reply)
    post = Mock(return_value=reply)
    monkeypatch.setattr(clients.requests, "get", get)
    monkeypatch.setattr(clients.requests, "post", post)
    monkeypatch.setattr(backend.time, "sleep", lambda seconds: None)
    client = clients.HKDriverApiClient(base_url="https://driver.test")
    client.access_token = "app-token"
    flow = backend.DriverOrderAPI(client, Mock())

    flow.advance("test-order", stop_after="complete", fare="5", surcharge="1", payment="online")

    urls = [call.args[0] for call in post.call_args_list]
    assert urls == ["https://driver.test/driverApi/order/grab"] + [
        "https://driver.test/driverApi/order/serviceChange"] * 4 + [
        "https://driver.test/driverApi/order/confirmBill"]
    state_calls = post.call_args_list[1:5]
    assert [call.kwargs["data"]["service_status"] for call in state_calls] == ["1", "2", "3", "4"]
    assert all(call.kwargs["data"]["order_no"] == "test-order" for call in post.call_args_list)
    assert post.call_args.kwargs["data"]["order_amount"] == "5"
    assert post.call_args.kwargs["data"]["other_amount"] == "1"
    assert "socket_client" not in vars(flow)


def test_order_base_does_not_pass_ui_or_socket_to_order_flow(api, monkeypatch):
    """即使基类存在设备及派单连接，订单推进层也只接收 HTTP 客户端。"""
    instance = OrderBase()
    instance.driver_api = api
    instance.driver_ui = Mock()
    instance.socket_client = Mock()
    instance.PAYMENT = "online"
    flow = Mock()
    factory = Mock(return_value=flow)
    monkeypatch.setattr(order_module, "DriverOrderAPI", factory)

    instance._driver_api_grab_and_flow("test", "test-order")

    factory.assert_called_once_with(api, order_module.logger)
    flow.advance.assert_called_once()
    instance.driver_ui.assert_not_called()
    assert not instance.driver_ui.mock_calls
    assert not instance.socket_client.mock_calls
