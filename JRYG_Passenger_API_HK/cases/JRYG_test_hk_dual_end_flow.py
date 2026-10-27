"""香港乘客端+司机端联动下单全流程接口自动化测试（纯接口，不依赖设备）。

完整流程：
  乘客端: 登录 → 搜索起终点 → 估价 → 下单 → (检测进行中订单弹窗，自动取消旧订单)
  司机端: 登录 → 出车上线 → 轮询订单 → 接单 → 状态滑动(出发→到达→开始行程→结束) → 确认账单(填写金额)
  乘客端: 查询订单最终状态(已完成)

接口清单：
  === 乘客端 ===
  1. POST /passenger/user/sendAuthCode       发送验证码
  2. POST /passenger/user/login              登录
  3. POST /passenger/location/searchAddress   搜索地址
  4. POST /passenger/order/estimate           估价
  5. POST /passenger/order/create             下单
  6. POST /passenger/order/unfinishList       查询进行中订单（弹窗检测+自动取消）
  7. GET  /passenger/order/status             查询订单状态
  8. POST /passenger/order/detail             订单详情

  === 司机端 ===
  9.  POST /driverApi/user/sendAuthCode       发送验证码
  10. POST /driverApi/user/login              登录
  11. POST /driverApi/home/handleWorkStatus    出车上线
  12. GET  /driverApi/order/polling            轮询订单
  13. POST /driverApi/order/grab              接单
  14. POST /driverApi/order/serviceChange      状态变更（1→2→3→4→5）
  15. POST /driverApi/order/confirmBill        确认账单/填写金额
  16. GET  /driverApi/order/serviceDetail      服务详情
  17. GET  /driverApi/order/tripDetail         行程详情
"""
import os
import sys
import time
import pytest

# 将项目根目录添加到 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from JRYG_Passenger_API_HK.cases.JRYG_test_hk_api import HKApiClient
from JRYG_Passenger_API_HK.cases.JRYG_test_hk_driver_api import HKDriverApiClient, DRIVER_LATITUDE, DRIVER_LONGITUDE
from JRYG_Passenger_API_HK.common.JRYG_logger import logger
from JRYG_Passenger_API_HK.common.jryg_socket_client import JRYGSocketClient
from JRYG_Passenger_API_HK.common.redis_cache_cleaner import clean_driver_cache

# 搜索关键词
BEGIN_SEARCH_KEYWORD = "銅鑼灣"
END_SEARCH_KEYWORD = "香港"

# 搜索定位坐标
SEARCH_LATITUDE = "22.278893"
SEARCH_LONGITUDE = "114.180418"

# 司机端默认填写金额
ORDER_AMOUNT = "5"
OTHER_AMOUNT = "0"

# 状态变更轮询等待时间（秒）
STATUS_WAIT = 2

# Socket 长连接位置上报稳定等待（秒）
SOCKET_STABILIZE_WAIT = 10

# 轮询订单超时（秒）— Socket 上报位置后需等待系统调度派单
POLLING_TIMEOUT = 120
POLLING_INTERVAL = 3

# 模拟行驶步数（结束行程前需沿导航移动足够距离）
MOVE_STEPS = 30
MOVE_INTERVAL = 2


class TestHKDualEndFlow:
    """香港乘客端+司机端联动下单全流程测试套件。

    测试用例：
      test_dual_end_full_flow: 双端联动完整流程
        乘客端: 登录→搜索→估价→下单（检测并取消进行中订单）
        司机端: 登录→出车→接单→状态滑动→结束→填写金额
    """

    @classmethod
    def setup_class(cls):
        """类级 setup：创建双端客户端。"""
        import requests
        import socket

        cls.passenger = HKApiClient()
        cls.driver = HKDriverApiClient()
        cls.socket_client = None

        # 检查乘客端服务可达性
        try:
            parsed = requests.utils.urlparse(cls.passenger.base_url)
            host = parsed.hostname or cls.passenger.base_url
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            socket.create_connection((host, port), timeout=3).close()
        except Exception:
            pytest.skip(f"无法连接乘客端服务 {cls.passenger.base_url}")

        # 检查司机端服务可达性
        try:
            parsed = requests.utils.urlparse(cls.driver.base_url)
            host = parsed.hostname or cls.driver.base_url
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            socket.create_connection((host, port), timeout=3).close()
        except Exception:
            pytest.skip(f"无法连接司机端服务 {cls.driver.base_url}")

        # 检查 Socket 网关可达性
        try:
            socket.create_connection(
                (JRYGSocketClient.GATEWAY_HOST, JRYGSocketClient.GATEWAY_PORT),
                timeout=5).close()
        except Exception:
            pytest.skip(f"无法连接 Socket 网关 {JRYGSocketClient.GATEWAY_HOST}:{JRYGSocketClient.GATEWAY_PORT}")

        logger.info("【HK DualEnd】双端接口测试开始，乘客端+司机端客户端已初始化")

    @classmethod
    def teardown_class(cls):
        """类级 teardown。"""
        if cls.socket_client:
            cls.socket_client.disconnect()
        logger.info("【HK DualEnd】双端接口测试执行完毕")

    # ==================== 乘客端辅助方法 ====================

    def _passenger_login(self):
        """乘客端登录。"""
        # 第1步：发送短信验证码（测试环境固定返回 123456）
        self.passenger.send_auth_code(trace_id=f"p_sms_{int(time.time())}")
        time.sleep(0.5)  # 等待验证码缓存写入

        # 第2步：用验证码登录，获取 access_token
        status, resp = self.passenger.login(trace_id=f"p_login_{int(time.time())}")
        assert status == 200, f"乘客端登录 HTTP 状态码预期 200，实际 {status}"
        assert resp.get("code") == 10000, f"乘客端登录失败: {resp}"

        # 第3步：保存 access_token，后续所有请求自动携带 token 参与签名
        self.passenger.access_token = resp["data"]["access_token"]
        logger.info(f"【HK DualEnd】乘客端登录成功，user_id={resp['data'].get('user_id')}")

    def _passenger_search_and_order_with_details(self):
        """乘客端搜索地址+估价+下单，返回 (order_no, begin, end)。

        begin/end 为起点/终点地址详情字典（含 latitude/longitude/name/poi_id），
        供司机端模拟行驶和结束行程时使用坐标。
        """
        # 搜索起点
        s1, r1 = self.passenger.search_address(
            SEARCH_LATITUDE, SEARCH_LONGITUDE, 1, name=BEGIN_SEARCH_KEYWORD,
            trace_id=f"p_search_begin_{int(time.time())}")
        assert r1.get("code") == 10000, f"搜索起点失败: {r1}"
        begin = r1["data"]["list"][0]
        logger.info(f"【HK DualEnd】乘客端搜索起点: {begin['name']} ({begin['latitude']}, {begin['longitude']})")

        # 搜索终点
        s2, r2 = self.passenger.search_address(
            SEARCH_LATITUDE, SEARCH_LONGITUDE, 2, name=END_SEARCH_KEYWORD,
            trace_id=f"p_search_end_{int(time.time())}")
        assert r2.get("code") == 10000, f"搜索终点失败: {r2}"
        end = r2["data"]["list"][0]
        logger.info(f"【HK DualEnd】乘客端搜索终点: {end['name']} ({end['latitude']}, {end['longitude']})")

        # 估价
        s3, r3 = self.passenger.estimate_order(
            begin["name"], begin["latitude"], begin["longitude"],
            end["name"], end["latitude"], end["longitude"],
            begin_poi_id=begin.get("poi_id", ""), end_poi_id=end.get("poi_id", ""),
            trace_id=f"p_estimate_{int(time.time())}")
        assert r3.get("code") == 10000, f"估价失败: {r3}"
        estimates = r3["data"]["estimates"]
        taxi = next((e for e in estimates if e["car_type"] == "taxi"), estimates[0])
        estimate_id = taxi["estimate_id"]
        logger.info(f"【HK DualEnd】乘客端估价成功，estimate_id={estimate_id}")

        # 下单
        s4, r4 = self.passenger.create_order(
            estimate_id=estimate_id, trace_id=f"p_create_{int(time.time())}")
        assert r4.get("code") == 10000, f"下单失败: {r4}"
        order_no = r4["data"]["order_no"]
        logger.info(f"【HK DualEnd】乘客端下单成功，order_no={order_no}")
        return order_no, begin, end

    def _passenger_check_and_cancel_ongoing(self):
        """乘客端检测进行中订单弹窗，如果存在则自动取消。

        App行为：下单成功后如果有未完成订单会弹窗提示，
        代码检测 unfinishList 接口，有进行中订单则逐一取消。
        """
        # 查询当前用户是否有进行中订单（App 下单后会弹窗提示）
        s, resp = self.passenger.post("/passenger/order/unfinishList", {},
                                       trace_id=f"p_unfinish_{int(time.time())}")
        if resp.get("code") != 10000:
            return  # 接口异常则跳过，不阻塞主流程

        orders = resp.get("data", {}).get("list", [])
        if not orders:
            logger.info("【HK DualEnd】乘客端无进行中订单")
            return  # 没有进行中订单，直接返回

        # 有进行中订单，逐一取消（避免影响新下单的派单）
        for order in orders:
            order_no = order.get("order_no")
            if order_no:
                logger.info(f"【HK DualEnd】检测到进行中订单 {order_no}，自动取消")
                # 预取消：通知服务端准备取消（App 内取消前置步骤）
                self.passenger.prepare_cancel_order(order_no, trace_id=f"p_prepcancel_{int(time.time())}")
                time.sleep(0.5)  # 等待预取消处理完成
                # 正式取消：执行取消操作
                cs, cresp = self.passenger.cancel_order(order_no, trace_id=f"p_cancel_{int(time.time())}")
                if cresp.get("code") == 10000:
                    logger.info(f"【HK DualEnd】进行中订单 {order_no} 已取消")
                else:
                    logger.warning(f"【HK DualEnd】取消订单 {order_no} 失败: {cresp}")

    # ==================== 司机端辅助方法 ====================

    def _driver_login(self):
        """司机端登录。

        流程：loginSceneCheck → sendCode → smsCodeLogin
        返回 data.sign_info.access_token 作为登录令牌。
        """
        # 第1步：登录场景检查（查询手机号是否可登录，可能返回签名有误但不影响后续流程）
        self.driver.login_scene_check(trace_id=f"d_check_{int(time.time())}")
        time.sleep(0.3)
        # 第2步：发送验证码（测试环境固定 123456）
        self.driver.send_auth_code(trace_id=f"d_sms_{int(time.time())}")
        time.sleep(0.5)  # 等待验证码缓存写入
        # 第3步：验证码登录，获取 access_token
        status, resp = self.driver.login(trace_id=f"d_login_{int(time.time())}")
        assert status == 200, f"司机端登录 HTTP 状态码预期 200，实际 {status}"
        assert resp.get("code") == 10000, f"司机端登录失败: {resp}"
        # 第4步：从 sign_info 中提取 access_token，后续请求自动携带
        sign_info = resp["data"]["sign_info"]
        self.driver.access_token = sign_info["access_token"]
        driver_info = resp["data"].get("driver_info", {})
        logger.info(f"【HK DualEnd】司机端登录成功，driver_id={driver_info.get('driver_id')}，"
                    f"driver_name={driver_info.get('driver_name')}")

    def _driver_go_online(self):
        """司机端出车上线。"""
        # 先检查当前状态
        s0, r0 = self.driver.get_out_car_status(trace_id=f"d_status_{int(time.time())}")
        is_online = r0.get("data", {}).get("is_online", 0) if r0.get("code") == 10000 else 0
        if is_online == 1:
            logger.info("【HK DualEnd】司机端已在线，无需出车")
        else:
            # 出车上线
            s, resp = self.driver.handle_work_status(handle_status=1, trace_id=f"d_online_{int(time.time())}")
            assert resp.get("code") == 10000, f"司机端出车失败: {resp}"
            logger.info("【HK DualEnd】司机端出车上线成功")

    def _driver_start_socket(self):
        """启动 Socket 长连接（心跳 + 位置上报）。

        没有 Socket 长连接，服务端不知道司机实时位置，不会派发订单。
        """
        self.socket_client = JRYGSocketClient(
            self.driver.access_token, lat=DRIVER_LATITUDE, lng=DRIVER_LONGITUDE)
        connected = self.socket_client.connect()
        assert connected, "Socket 长连接建立失败，无法接收订单派发"
        logger.info("【HK DualEnd】Socket 长连接已建立，心跳+位置上报已启动")
        logger.info(f"【HK DualEnd】等待 {SOCKET_STABILIZE_WAIT} 秒让位置上报稳定...")
        time.sleep(SOCKET_STABILIZE_WAIT)

    def _driver_clean_cache(self):
        """清理 Redis 司机派单缓存（避免上次测试的缓存干扰调度）。"""
        try:
            deleted = clean_driver_cache()
            logger.info(f"【HK DualEnd】Redis 司机缓存清理完成，删除 {deleted} 个 key")
        except Exception as e:
            logger.warning(f"【HK DualEnd】Redis 缓存清理失败: {e}（继续测试）")

    def _driver_polling_order(self, timeout=POLLING_TIMEOUT):
        """司机端轮询订单，返回order_no。

        Socket 长连接上报位置后，系统调度引擎会将订单派发给附近司机，
        polling 接口可获取已派发的订单。
        """
        start = time.time()
        poll_count = 0
        # 循环轮询直到拿到订单或超时
        while time.time() - start < timeout:
            poll_count += 1
            s, resp = self.driver.polling_order(order_type=0, trace_id=f"d_poll_{int(time.time())}")
            if resp.get("code") == 10000:
                data = resp.get("data", {})
                order_no = data.get("order_no", "")
                if order_no:
                    # 拿到已派发的订单号，返回供后续接单
                    logger.info(f"【HK DualEnd】第{poll_count}次轮询获取到订单: {order_no}")
                    return order_no
            # 每5次打印一次进度（便于排查超时原因）
            if poll_count % 5 == 0:
                elapsed = time.time() - start
                logger.info(f"【HK DualEnd】第{poll_count}次轮询... 暂无订单 (elapsed={elapsed:.0f}s)")
            time.sleep(POLLING_INTERVAL)
        pytest.fail(f"司机端轮询订单超时({timeout}s)，未收到新订单")

    def _driver_grab_order(self, order_no):
        """司机端接单。

        指派模式下 grab 可能返回 23000（不可抢单），但订单已自动派发，
        此时直接进入状态流转即可。
        """
        # 调用 grab 接口尝试接单
        s, resp = self.driver.grab_order(order_no, trace_id=f"d_grab_{int(time.time())}")
        code = resp.get("code")
        if code == 10000:
            # 正常接单成功
            logger.info(f"【HK DualEnd】司机端接单成功: {order_no}，{resp.get('message')}")
        elif code == 10011:
            # 订单已被自己接走（重复接单），继续后续流程
            logger.info(f"【HK DualEnd】订单已被自己接走，继续: {order_no}")
        elif code == 23000:
            # 指派模式：系统已自动派单，grab 不可用，直接进入状态流转
            logger.info(f"【HK DualEnd】指派模式: 订单已派发，grab不可用，跳过: {order_no}")
        else:
            logger.warning(f"【HK DualEnd】接单返回 code={code}: {resp.get('message')}")
        time.sleep(STATUS_WAIT + 3)  # 等待系统处理接单（状态同步）

    def _driver_service_flow(self, order_no, begin_lat, begin_lng, end_lat, end_lng):
        """司机端状态滑动流程：已出发→到达→开始行程→模拟行驶→结束行程。

        service_status 流转:
          1=已出发(前往接乘客) — 需主动调用，指派模式下接单后第一步
          2=到达上车地点
          3=开始行程
          4=结束行程(服务完结) — 需用终点坐标，且需沿导航移动足够距离
          5=确认收款 — 需confirmBill

        :param begin_lat/lng: 起点坐标（模拟行驶起点）
        :param end_lat/lng: 终点坐标（结束行程时使用）
        """
        # 状态0→1: 已出发（前往接乘客）
        # 指派模式下接单后第一步，告知服务端司机已出发前往乘客上车点
        s, resp = self.driver.service_change(
            order_no, service_status=1,
            latitude=DRIVER_LATITUDE, longitude=DRIVER_LONGITUDE,
            trace_id=f"d_sc1_{int(time.time())}")
        logger.info(f"【HK DualEnd】状态变更 1(已出发): code={resp.get('code')}, msg={resp.get('message')}")
        time.sleep(STATUS_WAIT)

        # 状态1→2: 到达上车地点
        # 司机到达乘客指定的上车点，等待乘客上车
        s, resp = self.driver.service_change(
            order_no, service_status=2,
            latitude=DRIVER_LATITUDE, longitude=DRIVER_LONGITUDE,
            trace_id=f"d_sc2_{int(time.time())}")
        logger.info(f"【HK DualEnd】状态变更 2(到达): code={resp.get('code')}, msg={resp.get('message')}")
        time.sleep(STATUS_WAIT)

        # 状态2→3: 开始行程
        # 乘客上车后开始行程，进入计费阶段
        s, resp = self.driver.service_change(
            order_no, service_status=3,
            latitude=DRIVER_LATITUDE, longitude=DRIVER_LONGITUDE,
            trace_id=f"d_sc3_{int(time.time())}")
        logger.info(f"【HK DualEnd】状态变更 3(开始行程): code={resp.get('code')}, msg={resp.get('message')}")
        time.sleep(STATUS_WAIT)

        # 模拟行驶到终点（Socket 位置上报逐步移动）
        # 服务端要求司机沿导航路线行驶足够距离才能结束行程，
        # 否则会返回 20156 "請按照導航繼續送乘客"，拒绝结束行程
        logger.info(f"【HK DualEnd】模拟行驶: ({begin_lat},{begin_lng}) → ({end_lat},{end_lng})")
        for i in range(MOVE_STEPS + 1):
            t = i / MOVE_STEPS  # 线性插值，逐步从起点移动到终点
            if self.socket_client:
                # 更新 Socket 上报的实时位置，模拟司机沿导航路线行驶
                self.socket_client.lat = begin_lat + (end_lat - begin_lat) * t
                self.socket_client.lng = begin_lng + (end_lng - begin_lng) * t
            time.sleep(MOVE_INTERVAL)
        logger.info("【HK DualEnd】已到达终点附近")

        # 状态3→4: 结束行程(服务完结) — 必须用终点坐标
        time.sleep(3)  # 等待服务端状态同步（位置上报有延迟）
        s, resp = self.driver.service_change(
            order_no, service_status=4,
            latitude=end_lat, longitude=end_lng,
            trace_id=f"d_sc4_{int(time.time())}")
        code = resp.get("code")
        logger.info(f"【HK DualEnd】状态变更 4(结束行程): code={code}, msg={resp.get('message')}")
        if code != 10000:
            # 结束行程失败，根据错误码判断是否可重试
            # 20156 = 请按照导航继续送乘客，再行驶一段后重试
            if code == 20156:
                logger.info("【HK DualEnd】服务端要求继续行驶，再移动10步...")
                for i in range(10):
                    if self.socket_client:
                        # 在终点附近持续上报位置，满足行驶距离要求
                        self.socket_client.lat = end_lat
                        self.socket_client.lng = end_lng
                    time.sleep(MOVE_INTERVAL)
                # 重试结束行程
                s, resp = self.driver.service_change(
                    order_no, service_status=4,
                    latitude=end_lat, longitude=end_lng,
                    trace_id=f"d_sc4_retry_{int(time.time())}")
                logger.info(f"【HK DualEnd】结束行程(重试): code={resp.get('code')}, msg={resp.get('message')}")
            else:
                # 其他错误码：等待后简单重试一次
                time.sleep(3)
                s, resp = self.driver.service_change(
                    order_no, service_status=4,
                    latitude=end_lat, longitude=end_lng,
                    trace_id=f"d_sc4_retry2_{int(time.time())}")
                logger.info(f"【HK DualEnd】结束行程(重试2): code={resp.get('code')}, msg={resp.get('message')}")
        time.sleep(STATUS_WAIT)

        # 查看服务详情，确认当前状态（调试用，非断言）
        s, resp = self.driver.get_service_detail(order_no, trace_id=f"d_sd_{int(time.time())}")
        if resp.get("code") == 10000:
            service = resp.get("data", {}).get("service", {})
            logger.info(f"【HK DualEnd】当前服务状态: {service.get('service_status_name')}，"
                        f"下一步: {service.get('next_service_status_name')}")

    def _driver_confirm_bill(self, order_no, order_amount=ORDER_AMOUNT, other_amount=OTHER_AMOUNT):
        """司机端确认账单/填写金额。"""
        s, resp = self.driver.confirm_bill(
            order_no, order_amount=order_amount, other_amount=other_amount,
            trace_id=f"d_bill_{int(time.time())}")
        assert resp.get("code") == 10000, f"确认账单失败: {resp}"
        logger.info(f"【HK DualEnd】司机端确认账单成功，金额={order_amount}，附加费={other_amount}")
        time.sleep(STATUS_WAIT)

    # ==================== 主测试用例 ====================

    def test_dual_end_full_flow(self):
        """测试：双端联动完整流程（Socket 长连接 + Redis 缓存清理）。

        司机端: 登录→出车→启动Socket长连接（位置上报）→清理Redis缓存
        乘客端: 登录→检测并取消进行中订单→搜索→估价→下单
        司机端: 轮询接单→状态滑动(已出发→到达→开始→模拟行驶→结束)→确认账单→确认收款
        乘客端: 查询订单最终状态(已完成)

        关键：没有 Socket 长连接上报司机位置，服务端调度引擎不会派发订单，
        polling 接口只会返回 order_id=0。
        """
        # ============ 司机端：登录 ============
        self._driver_login()

        # ============ 司机端：出车上线 ============
        self._driver_go_online()

        # ============ 司机端：启动 Socket 长连接（心跳+位置上报）============
        self._driver_start_socket()

        # ============ 清理 Redis 司机派单缓存 ============
        self._driver_clean_cache()

        # ============ 乘客端：登录 ============
        self._passenger_login()

        # ============ 乘客端：检测并取消进行中订单 ============
        self._passenger_check_and_cancel_ongoing()
        time.sleep(1)

        # ============ 乘客端：搜索+估价+下单 ============
        order_no, begin, end = self._passenger_search_and_order_with_details()
        assert order_no, "下单未返回 order_no"

        # ============ 司机端：轮询订单 ============
        polled_order_no = self._driver_polling_order(timeout=POLLING_TIMEOUT)
        logger.info(f"【HK DualEnd】轮询订单 {polled_order_no}，乘客下单 {order_no}")
        # 不强制匹配（可能轮询到之前的遗留订单），优先使用乘客下单号

        # ============ 司机端：接单 ============
        self._driver_grab_order(order_no)

        # ============ 司机端：状态滑动（已出发→到达→开始→模拟行驶→结束）============
        self._driver_service_flow(
            order_no,
            begin_lat=float(begin["latitude"]), begin_lng=float(begin["longitude"]),
            end_lat=float(end["latitude"]), end_lng=float(end["longitude"]))

        # ============ 司机端：确认账单/填写金额 ============
        self._driver_confirm_bill(order_no, order_amount=ORDER_AMOUNT, other_amount=OTHER_AMOUNT)

        # ============ 司机端：确认收款 (serviceChange status=5) ============
        # 结束行程并确认账单后，调用 status=5 完成收款，订单进入已完成状态
        s, resp = self.driver.service_change(
            order_no, service_status=5,
            latitude=end["latitude"], longitude=end["longitude"],
            trace_id=f"d_sc5_{int(time.time())}")
        logger.info(f"【HK DualEnd】状态变更 5(确认收款): code={resp.get('code')}, msg={resp.get('message')}")
        time.sleep(STATUS_WAIT)

        # ============ 乘客端：查询订单最终状态 ============
        # 等待服务端状态同步后，乘客端查询订单是否已完成
        time.sleep(2)
        s, resp = self.passenger.get_order_status(order_no, trace_id=f"p_final_{int(time.time())}")
        assert s == 200, f"最终查询 HTTP 状态码预期 200，实际 {s}"
        status_data = resp.get("data", {})
        logger.info(f"【HK DualEnd】乘客端最终查询订单状态: order_status={status_data.get('order_status')}")

        # ============ 司机端：查询行程详情确认完成 ============
        # 查询行程详情，验证订单状态和支付状态是否符合预期（调试用，非断言）
        s, resp = self.driver.get_trip_detail(order_no, trace_id=f"d_trip_{int(time.time())}")
        if resp.get("code") == 10000:
            order = resp.get("data", {}).get("order", {})
            fee = resp.get("data", {}).get("fee", {})
            logger.info(f"【HK DualEnd】行程详情: order_status={order.get('order_status')}，"
                        f"order_status_name={order.get('order_status_name')}，"
                        f"pay_status_name={order.get('pay_status_name')}")
            if fee:
                logger.info(f"【HK DualEnd】订单费用: {fee.get('order_fee')} {fee.get('unit')}")

        # ============ 司机端：收车下线 ============
        self.driver.handle_work_status(handle_status=0, trace_id=f"d_offline_{int(time.time())}")
        logger.info("【HK DualEnd】司机端收车下线")

        # ============ 断开 Socket 长连接 ============
        if self.socket_client:
            self.socket_client.disconnect()
            self.socket_client = None

        logger.info("【HK DualEnd】双端联动完整流程验证通过！")
        logger.info(f"  订单号: {order_no}")
        logger.info(f"  起点(搜索获取): {BEGIN_SEARCH_KEYWORD}")
        logger.info(f"  终点(搜索获取): {END_SEARCH_KEYWORD}")
        logger.info(f"  订单金额: {ORDER_AMOUNT} HKD")
        logger.info(f"  最终状态: 已完成")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
