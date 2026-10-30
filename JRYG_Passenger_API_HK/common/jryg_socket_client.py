"""司机端 Socket 长连接客户端（Python 实现）。

通过反编译司机端 APK 分析出的二进制协议：
  1. TCP 连接 gateway-test.sunlightmobility.hk:9527
  2. 发送登录消息 messageId=1026（openToken = HTTP 登录的 access_token）
  3. 收到 1026 回执 → 长连接登录成功
  4. 循环发送心跳 messageId=1022
  5. 循环发送位置数据 messageId=1017

协议格式（大端序 Big-Endian）：
  消息 = [4字节总长度(不含自身)] + [消息体]
  消息体 = [4字节messageId] + [4字节sequence] + [各消息特定字段...]

ByteUtil 方法对应：
  d(int) → 4字节大端 int
  e(int) → 4字节大端 int (同 d，但用 >>>)
  f(int) → 1字节
  c(double) → 8字节大端 double
  b(byte[]...) → 拼接
"""

import logging
import socket
import struct
import threading
import time
import math

from JRYG_Passenger_API_HK.common.hk_config import config


class JRYGSocketClient:
    """司机端 Socket 长连接客户端。"""

    GATEWAY_HOST = config.SOCKET_GATEWAY_HOST  # gateway-test.sunlightmobility.hk 真实IP
    GATEWAY_PORT = config.SOCKET_GATEWAY_PORT

    MSG_LOGIN = 1026
    MSG_HEART = 1022
    MSG_LOCATION = 1017

    def __init__(self, access_token, lat=None, lng=None, logger=None):
        """
        :param access_token: HTTP 登录返回的 access_token（作为 Socket openToken）
        :param lat: 纬度（默认用配置中的司机定位纬度）
        :param lng: 经度（默认用配置中的司机定位经度）
        """
        self.access_token = access_token
        # 默认使用配置中的司机定位坐标
        self.lat = float(lat if lat is not None else config.DRIVER_LATITUDE)
        self.lng = float(lng if lng is not None else config.DRIVER_LONGITUDE)
        self.sock = None
        self.sequence = 1
        self.connected = False
        self.logged_in = False
        self._recv_thread = None
        self._heart_thread = None
        self._location_thread = None
        self._running = False
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._state = threading.Condition()
        self._stop = threading.Event()
        self._pending = {}
        self._ack_sequences = {}
        self._ack_times = {}
        self._location_ack_count = 0
        self._last_location = None
        self.last_error = ""
        self.logger = logger or logging.getLogger(__name__)

    def _next_seq(self):
        with self._lock:
            seq = self.sequence
            self.sequence += 1
            return seq

    @staticmethod
    def _int4_be(val):
        """ByteUtil.d(int) → 4字节大端 int"""
        return struct.pack(">i", val)

    @staticmethod
    def _uint4_be(val):
        """ByteUtil.e(int) → 4字节大端 unsigned int"""
        return struct.pack(">I", val & 0xFFFFFFFF)

    @staticmethod
    def _byte1(val):
        """ByteUtil.f(int) → 1字节"""
        return struct.pack("B", val & 0xFF)

    @staticmethod
    def _double8_be(val):
        """ByteUtil.c(double) → 8字节大端 double"""
        return struct.pack(">d", val)

    @staticmethod
    def _float4_be(val):
        """Float.floatToIntBits → 4字节大端"""
        return struct.pack(">f", val)

    @staticmethod
    def _short2_be(val):
        """2字节大端 short"""
        return struct.pack(">H", val & 0xFFFF)

    @staticmethod
    def _concat(*arrays):
        """ByteUtil.b(byte[]...) → 拼接"""
        return b"".join(arrays)

    def _wrap_message(self, body_bytes):
        """在消息体前加4字节总长度"""
        total_len = len(body_bytes)
        return self._int4_be(total_len) + body_bytes

    def _build_login_message(self):
        """构建登录消息 messageId=1026"""
        seq = self._next_seq()
        token_bytes = self.access_token.encode()
        # 设备参数从统一配置读取（与 driver_api 引用同一来源，避免不一致）
        app_version_bytes = config.DRIVER_APP_VERSION.encode()
        device_type_bytes = config.DRIVER_DEVICE_MODEL.encode()
        system_version_bytes = config.DRIVER_OS_VERSION.replace("Android", "").encode()

        body = self._concat(
            self._int4_be(self.MSG_LOGIN),          # messageId
            self._int4_be(seq),                      # sequence
            self._int4_be(len(token_bytes)),        # openToken.length
            token_bytes,                             # openToken
            self._int4_be(1),                        # userType=1 (司机端)
            self._int4_be(2),                        # 固定值=2
            self._byte1(len(app_version_bytes)),    # app_version.length
            app_version_bytes,                        # app_version
            self._byte1(len(device_type_bytes)),    # deviceType.length
            device_type_bytes,                        # deviceType
            self._byte1(len(system_version_bytes)), # systemVersion.length
            system_version_bytes,                    # systemVersion
            self._byte1(2),                          # 固定=2 (非调试模式)
            self._int4_be(0),                        # killAppTime
            self._int4_be(int(time.time())),         # SocketFirstConnectTime (首次连接时间)
        )
        return self._wrap_message(body)

    def _build_heart_message(self):
        """构建心跳消息 messageId=1022"""
        seq = self._next_seq()
        now = int(time.time())
        body = self._concat(
            self._int4_be(self.MSG_HEART),  # messageId
            self._int4_be(seq),              # sequence
            self._int4_be(now),              # 当前时间戳
        )
        return self._wrap_message(body)

    def _build_location_message(self):
        """构建位置列表消息 messageId=1017

        YGMSendLocationListMessage.getMessageByte() 格式：
          [4字节总长度] [4字节id=1017] [4字节seq] [4字节locationCount] [4字节sendTime]
          + 每个位置:
            [8字节lng double] [8字节lat double] [4字节speed float] [4字节bearing float]
            [4字节altitude float] [4字节createTime int] [4字节sdkLocationTime int]
            [1字节locType] [2字节accuracy short] [1字节gaode_location_type]
            [1字节trusted_level] [1字节result_code] [1字节tmc_status]
            [1字节service_status] [4字节fake_reason] [4字节fake_probability float]
            [4字节mock_gps] [4字节provider.length] [provider bytes] [1字节map_type]
        """
        seq = self._next_seq()
        now = int(time.time())

        # 构建单个位置数据
        provider = "gps"
        provider_bytes = provider.encode()

        loc = self._concat(
            self._double8_be(self.lng),              # lng
            self._double8_be(self.lat),              # lat
            self._float4_be(0.0),                    # speed
            self._float4_be(0.0),                    # bearing
            self._float4_be(62.39),                  # altitude
            self._uint4_be(now),                     # createTime
            self._uint4_be(now),                     # sdkLocationTime
            self._byte1(0),                          # locType
            self._short2_be(int(16.643)),            # accuracy (2字节short)
            self._byte1(12),                         # gaode_location_type
            self._byte1(2),                          # trusted_level
            self._byte1(0),                          # result_code
            self._byte1(0),                          # tmc_status
            self._byte1(100),                        # service_status
            self._uint4_be(0),                       # fake_reason
            self._float4_be(0.0),                    # fake_probability
            self._uint4_be(0),                       # mock_gps
            self._uint4_be(len(provider_bytes)),    # provider.length
            provider_bytes,                          # provider
            self._byte1(1),                          # map_type
        )

        # 位置列表消息体
        body = self._concat(
            self._int4_be(self.MSG_LOCATION),  # messageId
            self._int4_be(seq),                 # sequence
            self._int4_be(1),                   # locationCount=1
            self._uint4_be(now),               # sendTime
            loc,                                # 位置数据
        )
        return self._wrap_message(body)

    def _send_message(self, message):
        msg_type, seq = struct.unpack(">ii", message[4:12])
        location = struct.unpack(">dd", message[20:36]) if msg_type == self.MSG_LOCATION else None
        try:
            with self._send_lock:
                with self._state:
                    if not self.connected or not self._running:
                        raise ConnectionError("司机长连接已断开")
                    self._pending[seq] = (msg_type, location)
                    while len(self._pending) > 100:
                        self._pending.pop(next(iter(self._pending)))
                self.sock.sendall(message)
            return seq
        except Exception as exc:
            self._mark_disconnected(f"发送失败: {exc}")
            raise

    def _record_ack(self, msg_type, seq):
        with self._state:
            pending = self._pending.get(seq)
            if not self._running or not self.connected or not pending or pending[0] != msg_type:
                return
            self._pending.pop(seq)
            if msg_type == self.MSG_LOGIN:
                self.logged_in = True
            if msg_type == self.MSG_LOCATION:
                self._location_ack_count += 1
            if seq > self._ack_sequences.get(msg_type, 0):
                self._ack_sequences[msg_type] = seq
                self._ack_times[msg_type] = time.monotonic()
                if msg_type == self.MSG_LOCATION:
                    self._last_location = pending[1]
            self._state.notify_all()
        self.logger.info("[Socket] 收到回执 type=%s sequence=%s location=%s",
                         msg_type, seq, pending[1])

    def _mark_disconnected(self, reason):
        with self._state:
            self.connected = False
            self.logged_in = False
            self._running = False
            self.last_error = reason
            self._pending.clear()
            self._stop.set()
            self._state.notify_all()
        transport = self.sock
        if transport is not None:
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                transport.close()
            except OSError:
                pass
        self.logger.info("[Socket] 连接停止: %s", reason)

    def readiness_status(self):
        """返回连接、上报线程及定位回执的新鲜度，不包含登录凭证。"""
        with self._state:
            now = time.monotonic()
            location_at = self._ack_times.get(self.MSG_LOCATION)
            heart_at = self._ack_times.get(self.MSG_HEART)
            return {
                "connected": self.connected,
                "logged_in": self.logged_in,
                "running": self._running,
                "workers_alive": all(t is not None and t.is_alive() for t in
                                     (self._recv_thread, self._heart_thread, self._location_thread)),
                "location_ack_count": self._location_ack_count,
                "location_ack_sequence": self._ack_sequences.get(self.MSG_LOCATION, 0),
                "heart_ack_sequence": self._ack_sequences.get(self.MSG_HEART, 0),
                "location_age": None if location_at is None else now - location_at,
                "heart_age": None if heart_at is None else now - heart_at,
                "location": self._last_location,
                "last_error": self.last_error,
            }

    def wait_until_ready(self, timeout=20, max_location_age=10, min_location_acks=2,
                         location_sequence=0, heart_sequence=0):
        """等待相关定位和心跳回执，同时确认后台上报线程仍存活。"""
        deadline = time.monotonic() + timeout
        with self._state:
            while True:
                state = self.readiness_status()
                if not all(state[key] for key in ("connected", "logged_in", "running", "workers_alive")):
                    return False
                if (state["location_ack_count"] >= min_location_acks
                        and state["location_ack_sequence"] >= location_sequence
                        and state["heart_ack_sequence"] >= heart_sequence
                        and state["location_age"] is not None
                        and state["location_age"] <= max_location_age
                        and state["heart_age"] is not None and state["heart_age"] <= 45
                        and state["location"] == (self.lng, self.lat)):
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._state.wait(min(remaining, 0.2))

    def confirm_location(self, timeout=20, max_location_age=10, min_location_acks=2):
        """下单前主动刷新心跳和定位，等待本次或更新序列的匹配回执。"""
        try:
            heart_seq = self._send_message(self._build_heart_message())
            loc_seq = self._send_message(self._build_location_message())
        except (OSError, ConnectionError):
            return False
        return self.wait_until_ready(timeout, max_location_age, min_location_acks,
                                     location_sequence=loc_seq, heart_sequence=heart_seq)

    def _recv_all(self, n):
        """精确读取 n 个字节，读超时不丢弃已接收的半包。"""
        data = b""
        while self._running and len(data) < n:
            try:
                chunk = self.sock.recv(n - len(data))
            except socket.timeout:
                continue
            if not chunk:
                return None
            data += chunk
        return data if len(data) == n else None

    def _parse_response(self, data):
        """解析服务端返回消息"""
        if len(data) < 12:
            return None
        # 跳过4字节总长度，读messageType和sequence
        msg_type = struct.unpack(">i", data[4:8])[0]
        sequence = struct.unpack(">i", data[8:12])[0]
        return msg_type, sequence

    def _recv_loop(self):
        """接收线程：读取服务端消息。"""
        while self._running:
            try:
                len_bytes = self._recv_all(4)
                if not len_bytes:
                    if self._running:
                        self._mark_disconnected("接收连接断开")
                    break
                total_len = struct.unpack(">i", len_bytes)[0]
                if total_len < 8 or total_len > 65536:
                    self._mark_disconnected(f"异常报文长度: {total_len}")
                    break
                body = self._recv_all(total_len)
                if not body:
                    if self._running:
                        self._mark_disconnected("读取消息体时断开")
                    break
                result = self._parse_response(len_bytes + body)
                if result:
                    msg_type, seq = result
                    if msg_type in (self.MSG_LOGIN, self.MSG_HEART, self.MSG_LOCATION):
                        self._record_ack(msg_type, seq)
                    else:
                        self.logger.info("[Socket] 收到推送 type=%s sequence=%s len=%s",
                                         msg_type, seq, total_len)
                        if total_len > 16:
                            json_data = body[8:].decode("utf-8", errors="ignore")
                            if "{" in json_data:
                                self.logger.debug("[Socket] 推送内容: %s",
                                                  json_data[json_data.index("{"):])
            except Exception as exc:
                if self._running:
                    self._mark_disconnected(f"接收异常: {exc}")
                break

    def _heart_loop(self):
        """心跳线程：每30秒发送一次。"""
        while self._running and self.logged_in:
            try:
                self._send_message(self._build_heart_message())
            except Exception as exc:
                self._mark_disconnected(f"心跳发送异常: {exc}")
                break
            if self._stop.wait(30):
                break

    def _location_loop(self):
        """位置上报线程：每3秒发送一次。"""
        while self._running and self.logged_in:
            try:
                seq = self._send_message(self._build_location_message())
                self.logger.info("[Socket] 发送位置 sequence=%s lat=%s lng=%s",
                                 seq, self.lat, self.lng)
            except Exception as exc:
                self._mark_disconnected(f"位置上报异常: {exc}")
                break
            if self._stop.wait(3):
                break

    def connect(self):
        """建立连接并启动持续心跳、位置上报，失败时清理线程。"""
        self.disconnect()
        with self._state:
            self._pending.clear()
            self._ack_sequences.clear()
            self._ack_times.clear()
            self._location_ack_count = 0
            self._last_location = None
            self.last_error = ""
            self._stop.clear()
        try:
            self.sock = socket.create_connection((self.GATEWAY_HOST, self.GATEWAY_PORT), timeout=10)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            self.sock.settimeout(1)
            self.connected = True
            self._running = True
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()
            self._send_message(self._build_login_message())
            with self._state:
                self._state.wait_for(lambda: self.logged_in or not self.connected, timeout=5)
            if not self.logged_in or not self.connected:
                self._mark_disconnected("Socket 登录回执超时或连接中断")
                self.disconnect()
                return False
            self._heart_thread = threading.Thread(target=self._heart_loop, daemon=True)
            self._location_thread = threading.Thread(target=self._location_loop, daemon=True)
            self._heart_thread.start()
            self._location_thread.start()
            self.logger.info("[Socket] 登录确认，心跳和定位上报已启动")
            return True
        except Exception as exc:
            self._mark_disconnected(f"连接失败: {exc}")
            self.disconnect()
            return False

    def disconnect(self):
        """停止后台上报并关闭连接，避免测试结束后留下上传线程。"""
        self._mark_disconnected(self.last_error or "主动断开")
        for worker in (self._recv_thread, self._heart_thread, self._location_thread):
            if worker is not None and worker is not threading.current_thread():
                worker.join(timeout=2)
        self.sock = None

    def wait_for_order(self, timeout=120):
        """等待接收新订单推送"""
        print(f"[Socket] 等待订单推送（最长 {timeout} 秒）...")
        start = time.time()
        while time.time() - start < timeout:
            if not self._running:
                break
            time.sleep(1)
        print("[Socket] 等待结束")
