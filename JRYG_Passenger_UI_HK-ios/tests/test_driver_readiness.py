"""司机派单就绪条件与乘客提交前检查的离线回归测试。

HTTP 接口和多数 Socket 交互均由 Mock 替代；最后一个测试使用本地
socketpair 模拟网关收发，不访问真实司机服务，也不连接手机。
覆盖心跳/定位回执、连接失效、出车状态确认、提交拦截和线程清理。
"""

# 按文件路径加载下单基类，避免目录名称包含连字符时无法直接导入。
import importlib.util
from pathlib import Path
# 本地套接字及超时异常，用于模拟断连、半包和网关收发。
import socket
# 编解码 Socket 协议中大端整数格式的长度、消息类型和序列号。
import struct
import sys
import threading
from unittest.mock import Mock

import pytest

# 项目根目录包含 API 层和 iOS UI 层，跨目录导入需要加入模块搜索路径。
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from JRYG_Passenger_API_HK.cases.JRYG_test_hk_driver_api import HKDriverApiClient
from JRYG_Passenger_API_HK.common.jryg_socket_client import JRYGSocketClient

# 使用独立模块名加载测试基类，只调用被测方法，不运行真机 setup_class。
spec = importlib.util.spec_from_file_location(
    "driver_readiness_order_base",
    ROOT / "JRYG_Passenger_UI_HK-ios/cases/JRYG_test_ios_order_base.py",
)
order_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(order_module)
OrderBase = order_module.TestOrderBase


@pytest.fixture
def client():
    """提供已连接但尚无回执的模拟 Socket 客户端，用例结束后断开连接。"""
    instance = JRYGSocketClient("test-token")
    # 替代网络传输，并模拟登录成功及三个后台线程存活的状态。
    instance.sock = Mock()
    instance.connected = instance.logged_in = instance._running = True
    instance._recv_thread = Mock(is_alive=Mock(return_value=True))
    instance._heart_thread = Mock(is_alive=Mock(return_value=True))
    instance._location_thread = Mock(is_alive=Mock(return_value=True))
    yield instance
    # 清理停止标记及连接资源，避免不同测试共享运行状态。
    instance.disconnect()


def acknowledge(client, msg_type):
    """发送心跳或定位消息并模拟同类型、同序列号的回执，返回发送序列号。"""
    builder = (client._build_heart_message if msg_type == client.MSG_HEART
               else client._build_location_message)
    seq = client._send_message(builder())
    # 先发送再登记回执，保证回执对应真实的待确认请求。
    client._record_ack(msg_type, seq)
    return seq


def make_ready(client):
    """构造一个心跳回执及两个定位回执，满足基础就绪条件。"""
    acknowledge(client, client.MSG_HEART)
    acknowledge(client, client.MSG_LOCATION)
    acknowledge(client, client.MSG_LOCATION)


def test_out_car_status_uses_get():
    """出车状态查询必须使用 GET，并透传 trace_id，不得误发 POST。"""
    api = HKDriverApiClient()
    api.get = Mock(return_value=(200, {"code": 10000, "data": {"is_online": 1}}))
    api.post = Mock()
    api.get_out_car_status(trace_id="test-trace")
    api.get.assert_called_once_with("/driverApi/home/outCarStatus", trace_id="test-trace")
    api.post.assert_not_called()


def test_sent_locations_without_ack_are_not_ready(client):
    """发送定位消息不等于网关已接收，没有定位回执时不能判为就绪。"""
    acknowledge(client, client.MSG_HEART)
    # 故意仅发送定位，不调用 _record_ack 模拟网关确认。
    client._send_message(client._build_location_message())
    assert not client.wait_until_ready(timeout=0)
    assert client.readiness_status()["location_ack_count"] == 0


def test_two_location_acks_and_heartbeat_are_required(client):
    """只有心跳确认和两个定位确认全部具备时，客户端才可就绪。"""
    acknowledge(client, client.MSG_LOCATION)
    assert not client.wait_until_ready(timeout=0)
    acknowledge(client, client.MSG_HEART)
    assert not client.wait_until_ready(timeout=0)
    # 第二个定位回执补齐数量门槛，此时才应通过。
    acknowledge(client, client.MSG_LOCATION)
    assert client.wait_until_ready(timeout=0)


def test_unsolicited_wrong_type_and_duplicate_acks_are_ignored(client):
    """无对应请求、类型不匹配和重复回执不能增加有效定位确认数。"""
    # 序列号 999 没有对应请求；随后用定位请求序列号伪造心跳回执。
    client._record_ack(client.MSG_LOCATION, 999)
    seq = client._send_message(client._build_location_message())
    client._record_ack(client.MSG_HEART, seq)
    assert client.readiness_status()["location_ack_count"] == 0
    # 同一个合法回执重复到达，只允许计数一次。
    client._record_ack(client.MSG_LOCATION, seq)
    client._record_ack(client.MSG_LOCATION, seq)
    assert client.readiness_status()["location_ack_count"] == 1


# 将不同消息回执的时间戳回拨，分别验证回执过期后的拦截逻辑。
@pytest.mark.parametrize("msg_type,age", [(1017, 11), (1022, 46)])
def test_stale_acks_do_not_pass_preflight(client, msg_type, age):
    """历史回执即使数量充足，一旦过期也不能通过就绪检查。"""
    make_ready(client)
    client._ack_times[msg_type] -= age
    assert not client.wait_until_ready(timeout=0)


def test_dead_location_worker_blocks_preflight(client):
    """定位上传线程已退出时，历史回执不能掩盖客户端异常。"""
    make_ready(client)
    client._location_thread.is_alive.return_value = False
    assert not client.wait_until_ready(timeout=0)


def test_old_coordinate_ack_does_not_confirm_new_location(client):
    """坐标改变后，旧坐标的定位回执不能证明当前位置已上报。"""
    make_ready(client)
    # 只改变客户端纬度，不为新坐标补发确认回执。
    client.lat += 0.01
    assert not client.wait_until_ready(timeout=0)


def test_preflight_requires_fresh_request_ack(client):
    """提交前定位刷新必须获得本次请求的回执，不能只复用历史就绪状态。"""
    make_ready(client)
    assert not client.confirm_location(timeout=0)


def test_preflight_accepts_matched_fresh_acks(client):
    """网关即时返回与新请求匹配的回执时，提交前定位刷新通过。"""
    make_ready(client)

    def reply(message):
        """跳过四字节长度头，提取消息类型及序列号并模拟匹配回执。"""
        msg_type, seq = struct.unpack(">ii", message[4:12])
        client._record_ack(msg_type, seq)

    # 每次发送都同步触发模拟回包，无需启动真实接收线程。
    client.sock.sendall.side_effect = reply
    assert client.confirm_location(timeout=0)


def test_eof_clears_online_socket_state(client):
    """接收空字节表示对端关闭，必须清除连接、登录和运行状态。"""
    make_ready(client)
    client.sock.recv.return_value = b""
    client._recv_loop()
    # EOF 后应广播停止标记，历史回执也不能继续通过就绪检查。
    assert not client.connected
    assert not client.logged_in
    assert not client._running
    assert client._stop.is_set()
    assert not client.wait_until_ready(timeout=0)


def test_send_failure_stops_uploading(client):
    """定位刷新发送失败时应断开连接并通知后台线程停止。"""
    client.sock.sendall.side_effect = OSError("connection lost")
    assert not client.confirm_location(timeout=0)
    assert not client.connected
    assert client._stop.is_set()


def test_partial_frame_survives_read_timeout(client):
    """半包读取遭遇一次超时后应保留已收字节，继续拼接完整帧。"""
    # 首字节已到达，中间超时，后续两字节仍需拼接成 abc。
    client.sock.recv.side_effect = [b"a", socket.timeout(), b"bc"]
    assert client._recv_all(3) == b"abc"


@pytest.fixture
def order(monkeypatch):
    """提供不连接手机的下单基类实例，默认模拟司机在线且没有服务中订单。"""
    class Harness(OrderBase):
        """仅用于直接调用被测方法，不让 pytest 收集继承的真机测试。"""
        __test__ = False
        # 每次夹具创建独立子类，隔离类级 Socket 状态。
        socket_client = None
        driver_api_socket_enabled = True

    instance = Harness()
    instance.driver_api = Mock()
    instance.driver_api.access_token = "test-token"
    # HTTP 状态 200 与业务码 10000 共同表示成功，在线标志为 1。
    instance.driver_api.get_out_car_status.return_value = (
        200, {"code": 10000, "data": {"is_online": 1}})
    instance.driver_api.get_serving_order.return_value = (
        200, {"code": 10000, "data": {"has_serving_order": False}})
    instance.driver_api.handle_work_status.return_value = (200, {"code": 10000})
    # 去掉被测方法中的固定等待；monkeypatch 在用例结束后自动还原。
    monkeypatch.setattr(order_module.time, "sleep", lambda seconds: None)
    return instance


def test_online_driver_does_not_repeat_go_online(order):
    """已确认在线的司机无需重复调用出车接口。"""
    order._driver_api_ensure_online("test")
    order.driver_api.handle_work_status.assert_not_called()


def test_offline_driver_requires_app_go_online(order):
    """司机离线时阻止继续下单，不再调用出车接口。"""
    order.driver_api.get_out_car_status.return_value = (
        200, {"code": 10000, "data": {"is_online": 0}})
    with pytest.raises(AssertionError, match="App 点击出车"):
        order._driver_api_ensure_online("test")
    order.driver_api.handle_work_status.assert_not_called()


# 分别覆盖 HTTP 失败、业务失败和响应缺少在线标志。
@pytest.mark.parametrize("response", [
    (404, {}),
    (200, {"code": 10003}),
    (200, {"code": 10000, "data": {}}),
])
def test_unknown_online_status_blocks_order(order, response):
    """在线状态不可确认时停止下单，不根据未知状态盲目请求出车。"""
    order.driver_api.get_out_car_status.return_value = response
    with pytest.raises(AssertionError):
        order._driver_api_require_ready("test")
    order.driver_api.handle_work_status.assert_not_called()


def test_offline_preflight_never_uses_api_go_online(order):
    """下单前司机掉线时停止，不通过接口重新出车。"""
    order.driver_api.get_out_car_status.return_value = (
        200, {"code": 10000, "data": {"is_online": 0}})
    with pytest.raises(AssertionError, match="司机未在线"):
        order._driver_api_require_ready("test")
    order.driver_api.handle_work_status.assert_not_called()


def test_busy_driver_cannot_submit_order(order):
    """司机已有服务中订单时，即使在线也不能进行新的乘客下单。"""
    order.driver_api.get_serving_order.return_value = (
        200, {"code": 10000, "data": {"has_serving_order": True}})
    with pytest.raises(AssertionError, match="服务中订单"):
        order._driver_api_require_ready("test")


# 呼叫和预付确认两个入口均必须执行相同的司机就绪门禁。
@pytest.mark.parametrize("method", ["_ios_click_confirm_call", "_ios_click_confirm_pay"])
def test_submission_is_blocked_when_preflight_fails(order, monkeypatch, method):
    """提交前检查失败时向上传递断言，不能触发父类的 UI 点击方法。"""
    order._driver_api_require_ready = Mock(side_effect=AssertionError("not ready"))
    click = Mock()
    # 替代底层点击方法，确保测试不会触碰手机且能检测误提交。
    monkeypatch.setattr(order_module.iOSBase, method, click)
    with pytest.raises(AssertionError, match="not ready"):
        getattr(order, method)("test")
    click.assert_not_called()


def test_socket_is_owned_by_class_for_teardown(order, monkeypatch):
    """Socket 必须保存在类属性中，确保类级 teardown 能访问并断开连接。"""
    connection = Mock()
    connection.connect.return_value = True
    connection.wait_until_ready.return_value = True
    monkeypatch.setattr(order_module, "JRYGSocketClient", Mock(return_value=connection))
    order._driver_api_start_socket("test")
    assert type(order).socket_client is connection
    # 实例同名属性会遮蔽类属性，影响连接归属和统一清理。
    assert "socket_client" not in order.__dict__


def test_failed_initial_location_ack_blocks_order(order, monkeypatch):
    """Socket 登录成功但首次定位确认未完成时，禁止进入乘客下单流程。"""
    connection = Mock()
    connection.connect.return_value = True
    connection.wait_until_ready.return_value = False
    monkeypatch.setattr(order_module, "JRYGSocketClient", Mock(return_value=connection))
    with pytest.raises(AssertionError, match="定位回执"):
        order._driver_api_start_socket("test")


def test_preflight_recovers_dead_connection_and_refreshes_location(order):
    """提交前发现连接失效时重建 Socket，并用新连接刷新定位。"""
    connection = Mock()
    connection.readiness_status.return_value = {
        "connected": False, "logged_in": False, "running": False, "workers_alive": False}
    type(order).socket_client = connection
    replacement = Mock(confirm_location=Mock(return_value=True))
    # 重连操作替换类级连接，后续确认必须调用 replacement 而非旧连接。
    order._driver_api_start_socket = Mock(
        side_effect=lambda tag: setattr(type(order), "socket_client", replacement))
    order._driver_api_require_ready("test")
    order._driver_api_start_socket.assert_called_once_with("test")
    replacement.confirm_location.assert_called_once()


@pytest.mark.parametrize("method", ["_ios_click_confirm_call", "_ios_click_confirm_pay"])
def test_preflight_runs_before_submission(order, monkeypatch, method):
    """两个提交入口均应先确认司机就绪，再执行实际提交点击。"""
    # 用动作列表记录执行顺序，避免仅检查两次调用存在却忽略先后关系。
    actions = []
    order._driver_api_require_ready = Mock(side_effect=lambda tag: actions.append("ready"))
    monkeypatch.setattr(order_module.iOSBase, method,
                        lambda self, tag: actions.append("submit"))
    getattr(order, method)("test")
    assert actions == ["ready", "submit"]


def test_waiting_for_dispatch_stops_when_location_upload_fails(order):
    """轮询等待派单期间定位失效，应立即失败而非继续等待订单超时。"""
    connection = Mock(wait_until_ready=Mock(return_value=False))
    type(order).socket_client = connection
    # polling 返回成功但无订单号，随后应检测连接健康并终止本轮等待。
    order.driver_api.polling_order.return_value = (200, {"code": 10000, "data": {"order_no": ""}})
    with pytest.raises(AssertionError, match="定位上报失效"):
        order._driver_api_polling_order("test")
    assert order.driver_api.polling_order.call_count == 1


def test_preflight_blocks_when_refresh_ack_is_missing(order):
    """连接和线程看似正常，但本次定位刷新缺少回执时仍禁止下单。"""
    connection = Mock(confirm_location=Mock(return_value=False))
    connection.readiness_status.return_value = {
        "connected": True, "logged_in": True, "running": True, "workers_alive": True}
    type(order).socket_client = connection
    with pytest.raises(AssertionError, match="禁止乘客下单"):
        order._driver_api_require_ready("test")


def test_connection_with_gateway_replies_stops_all_workers(monkeypatch):
    """本地模拟网关确认登录、心跳和定位，断开后所有收发线程必须退出。"""
    # 使用本地套接字对替代远端 TCP 连接，保留真实字节收发和线程行为。
    local, remote = socket.socketpair()
    transport = Mock(wraps=local)
    # socketpair 不支持 TCP 专用选项，仅将该选项调用替换为模拟操作。
    transport.setsockopt = Mock()
    monkeypatch.setattr(socket, "create_connection", Mock(return_value=transport))
    client = JRYGSocketClient("test-token")

    def receive_exact(count):
        """从网关端累计读取指定字节数；对端关闭时返回 None。"""
        packet = b""
        while len(packet) < count:
            chunk = remote.recv(count - len(packet))
            if not chunk:
                return None
            packet += chunk
        return packet

    def gateway():
        """读取长度前缀帧，并将消息类型和序列号回显为最小确认帧。"""
        try:
            while True:
                # 四字节大端整数表示随后需要读取的消息体长度。
                header = receive_exact(4)
                if header is None:
                    break
                body = receive_exact(struct.unpack(">i", header)[0])
                if body is None:
                    break
                # 回包体仅含类型和序列号，共八字节；长度头与消息体分开编码。
                remote.sendall(struct.pack(">i", 8) + body[:8])
        except OSError:
            # 客户端断开时读写可能报错，网关模拟线程应正常结束。
            pass
        finally:
            remote.close()

    # 网关线程持续回应客户端真实后台线程发送的登录、心跳和定位消息。
    worker = threading.Thread(target=gateway, daemon=True)
    worker.start()
    try:
        assert client.connect()
        assert client.wait_until_ready(timeout=5)
        assert client.confirm_location(timeout=2)
    finally:
        # 即使断言失败也断开客户端，并有界等待网关线程退出。
        client.disconnect()
        worker.join(timeout=2)
    # 不仅检查连接标志，还确认网关及三个客户端后台线程都已停止。
    assert not worker.is_alive()
    assert not any(t.is_alive() for t in
                   (client._recv_thread, client._heart_thread, client._location_thread))
    assert not client.logged_in
