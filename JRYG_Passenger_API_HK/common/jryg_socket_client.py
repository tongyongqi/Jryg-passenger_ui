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

import socket
import struct
import threading
import time
import math


class JRYGSocketClient:
    """司机端 Socket 长连接客户端。"""

    GATEWAY_HOST = "43.128.0.173"  # gateway-test.sunlightmobility.hk 真实IP
    GATEWAY_PORT = 9527

    MSG_LOGIN = 1026
    MSG_HEART = 1022
    MSG_LOCATION = 1017

    def __init__(self, access_token, lat=22.277409, lng=114.188752):
        """
        :param access_token: HTTP 登录返回的 access_token（作为 Socket openToken）
        :param lat: 纬度
        :param lng: 经度
        """
        self.access_token = access_token
        self.lat = float(lat)
        self.lng = float(lng)
        self.sock = None
        self.sequence = 1
        self.connected = False
        self.logged_in = False
        self._recv_thread = None
        self._heart_thread = None
        self._location_thread = None
        self._running = False
        self._lock = threading.Lock()

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
        app_version_bytes = b"1.2.2"
        device_type_bytes = b"Pixel 8"
        system_version_bytes = b"14"

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

    def _recv_all(self, n):
        """精确读取 n 个字节"""
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    def _parse_response(self, data):
        """解析服务端返回消息"""
        if len(data) < 12:
            return None
        # 跳过4字节总长度，读messageType和sequence
        msg_type = struct.unpack(">i", data[4:8])[0]
        sequence = struct.unpack(">i", data[8:12])[0]
        return msg_type, sequence

    def _recv_loop(self):
        """接收线程：读取服务端消息"""
        while self._running:
            try:
                # 先读4字节长度
                len_bytes = self._recv_all(4)
                if not len_bytes:
                    print("[Socket] 连接断开")
                    self.connected = False
                    break
                total_len = struct.unpack(">i", len_bytes)[0]
                if total_len <= 0 or total_len > 65536:
                    print(f"[Socket] 异常长度: {total_len}")
                    continue
                # 读取消息体
                body = self._recv_all(total_len)
                if not body:
                    print("[Socket] 连接断开(读取消息体)")
                    self.connected = False
                    break
                result = self._parse_response(len_bytes + body)
                if result:
                    msg_type, seq = result
                    if msg_type == self.MSG_LOGIN:
                        print(f"[Socket] 登录成功! sequence={seq}")
                        self.logged_in = True
                    elif msg_type == self.MSG_HEART:
                        print(f"[Socket] 心跳返回成功 sequence={seq}")
                    elif msg_type == self.MSG_LOCATION:
                        print(f"[Socket] 位置上报成功 sequence={seq}")
                    else:
                        # 可能是新订单推送等消息
                        print(f"[Socket] 收到消息 type={msg_type} sequence={seq} len={total_len}")
                        # 尝试提取JSON（新订单推送）
                        if total_len > 16:
                            try:
                                json_data = body[8:].decode("utf-8", errors="ignore")
                                if "{" in json_data:
                                    start = json_data.index("{")
                                    print(f"[Socket] 推送内容: {json_data[start:]}")
                            except Exception:
                                pass
            except Exception as e:
                print(f"[Socket] 接收异常: {e}")
                self.connected = False
                break

    def _heart_loop(self):
        """心跳线程：每30秒发送一次"""
        while self._running and self.logged_in:
            try:
                msg = self._build_heart_message()
                self.sock.sendall(msg)
                print("[Socket] 发送心跳")
            except Exception as e:
                print(f"[Socket] 心跳发送异常: {e}")
                break
            time.sleep(30)

    def _location_loop(self):
        """位置上报线程：每3秒发送一次"""
        while self._running and self.logged_in:
            try:
                msg = self._build_location_message()
                self.sock.sendall(msg)
                print(f"[Socket] 发送位置 lat={self.lat} lng={self.lng}")
            except Exception as e:
                print(f"[Socket] 位置上报异常: {e}")
                break
            time.sleep(3)

    def connect(self):
        """建立 TCP 连接"""
        print(f"[Socket] 连接 {self.GATEWAY_HOST}:{self.GATEWAY_PORT}...")
        self.sock = socket.create_connection((self.GATEWAY_HOST, self.GATEWAY_PORT), timeout=10)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.connected = True
        self._running = True
        print("[Socket] TCP 连接成功")

        # 启动接收线程
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        # 发送登录消息
        login_msg = self._build_login_message()
        self.sock.sendall(login_msg)
        print(f"[Socket] 已发送登录消息 (token={self.access_token[:20]}...)")

        # 等待登录成功
        for _ in range(50):
            if self.logged_in:
                break
            time.sleep(0.1)

        if not self.logged_in:
            print("[Socket] 登录超时!")
            return False

        # 发送心跳
        heart_msg = self._build_heart_message()
        self.sock.sendall(heart_msg)

        # 发送位置数据
        loc_msg = self._build_location_message()
        self.sock.sendall(loc_msg)

        # 启动心跳线程
        self._heart_thread = threading.Thread(target=self._heart_loop, daemon=True)
        self._heart_thread.start()

        # 启动位置上报线程
        self._location_thread = threading.Thread(target=self._location_loop, daemon=True)
        self._location_thread.start()

        print("[Socket] 长连接登录成功，心跳+位置上报已启动")
        return True

    def disconnect(self):
        """断开连接"""
        self._running = False
        self.logged_in = False
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        print("[Socket] 已断开连接")

    def wait_for_order(self, timeout=120):
        """等待接收新订单推送"""
        print(f"[Socket] 等待订单推送（最长 {timeout} 秒）...")
        start = time.time()
        while time.time() - start < timeout:
            if not self._running:
                break
            time.sleep(1)
        print("[Socket] 等待结束")
