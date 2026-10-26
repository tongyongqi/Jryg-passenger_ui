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

        logger.info("【HK DualEnd】双端接口测试开始，乘客端+司机端客户端已初始化")

    @classmethod
    def teardown_class(cls):
        """类级 teardown。"""
        logger.info("【HK DualEnd】双端接口测试执行完毕")

    # ==================== 乘客端辅助方法 ====================

    def _passenger_login(self):
        """乘客端登录。"""
        self.passenger.send_auth_code(trace_id=f"p_sms_{int(time.time())}")
        time.sleep(0.5)
        status, resp = self.passenger.login(trace_id=f"p_login_{int(time.time())}")
        assert status == 200, f"乘客端登录 HTTP 状态码预期 200，实际 {status}"
        assert resp.get("code") == 10000, f"乘客端登录失败: {resp}"
        self.passenger.access_token = resp["data"]["access_token"]
        logger.info(f"【HK DualEnd】乘客端登录成功，user_id={resp['data'].get('user_id')}")

    def _passenger_search_and_order(self):
        """乘客端搜索地址+估价+下单，返回order_no。"""
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
        return order_no

    def _passenger_check_and_cancel_ongoing(self):
        """乘客端检测进行中订单弹窗，如果存在则自动取消。

        App行为：下单成功后如果有未完成订单会弹窗提示，
        代码检测 unfinishList 接口，有进行中订单则逐一取消。
        """
        s, resp = self.passenger.post("/passenger/order/unfinishList", {},
                                       trace_id=f"p_unfinish_{int(time.time())}")
        if resp.get("code") != 10000:
            return
        orders = resp.get("data", {}).get("list", [])
        if not orders:
            logger.info("【HK DualEnd】乘客端无进行中订单")
            return
        for order in orders:
            order_no = order.get("order_no")
            if order_no:
                logger.info(f"【HK DualEnd】检测到进行中订单 {order_no}，自动取消")
                # 预取消
                self.passenger.prepare_cancel_order(order_no, trace_id=f"p_prepcancel_{int(time.time())}")
                time.sleep(0.5)
                # 取消
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
        # 1. 登录场景检查
        self.driver.login_scene_check(trace_id=f"d_check_{int(time.time())}")
        time.sleep(0.3)
        # 2. 发送验证码
        self.driver.send_auth_code(trace_id=f"d_sms_{int(time.time())}")
        time.sleep(0.5)
        # 3. 验证码登录
        status, resp = self.driver.login(trace_id=f"d_login_{int(time.time())}")
        assert status == 200, f"司机端登录 HTTP 状态码预期 200，实际 {status}"
        assert resp.get("code") == 10000, f"司机端登录失败: {resp}"
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
            return
        # 出车上线
        s, resp = self.driver.handle_work_status(handle_status=1, trace_id=f"d_online_{int(time.time())}")
        assert resp.get("code") == 10000, f"司机端出车失败: {resp}"
        logger.info("【HK DualEnd】司机端出车上线成功")

    def _driver_polling_order(self, timeout=30):
        """司机端轮询订单，返回order_no。"""
        start = time.time()
        while time.time() - start < timeout:
            s, resp = self.driver.polling_order(order_type=0, trace_id=f"d_poll_{int(time.time())}")
            if resp.get("code") == 10000:
                data = resp.get("data", {})
                order_no = data.get("order_no", "")
                if order_no:
                    logger.info(f"【HK DualEnd】司机端轮询到订单: {order_no}")
                    return order_no
            time.sleep(2)
        pytest.fail("司机端轮询订单超时，未收到新订单")

    def _driver_grab_order(self, order_no):
        """司机端接单。"""
        s, resp = self.driver.grab_order(order_no, trace_id=f"d_grab_{int(time.time())}")
        # 接单返回 code=10000 且 message="搶單中，請等候5秒"
        assert resp.get("code") == 10000, f"司机端接单失败: {resp}"
        logger.info(f"【HK DualEnd】司机端接单成功: {order_no}，{resp.get('message')}")
        time.sleep(STATUS_WAIT)

    def _driver_service_flow(self, order_no):
        """司机端状态滑动流程：到达→开始行程→结束行程。

        service_status 流转:
          1=已出发(前往接乘客) — 接单后自动进入此状态
          2=到达上车地点
          3=开始行程
          4=结束行程(服务完结)
          5=确认收款 — 需confirmBill
        """
        # 状态1→2: 到达上车地点
        s, resp = self.driver.service_change(
            order_no, service_status=2,
            latitude=DRIVER_LATITUDE, longitude=DRIVER_LONGITUDE,
            trace_id=f"d_sc2_{int(time.time())}")
        logger.info(f"【HK DualEnd】状态变更 2(到达): code={resp.get('code')}, msg={resp.get('message')}")
        time.sleep(STATUS_WAIT)

        # 状态2→3: 开始行程
        s, resp = self.driver.service_change(
            order_no, service_status=3,
            latitude=DRIVER_LATITUDE, longitude=DRIVER_LONGITUDE,
            trace_id=f"d_sc3_{int(time.time())}")
        logger.info(f"【HK DualEnd】状态变更 3(开始行程): code={resp.get('code')}, msg={resp.get('message')}")
        time.sleep(STATUS_WAIT)

        # 状态3→4: 结束行程(服务完结)
        s, resp = self.driver.service_change(
            order_no, service_status=4,
            latitude=DRIVER_LATITUDE, longitude=DRIVER_LONGITUDE,
            trace_id=f"d_sc4_{int(time.time())}")
        logger.info(f"【HK DualEnd】状态变更 4(结束行程): code={resp.get('code')}, msg={resp.get('message')}")
        time.sleep(STATUS_WAIT)

        # 查看服务详情，确认当前状态
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
        """测试：双端联动完整流程。

        乘客端: 登录→搜索→估价→下单（检测并取消进行中订单）
        司机端: 登录→出车→轮询接单→状态滑动→结束→填写金额
        乘客端: 查询订单最终状态(已完成)
        """
        # ============ 乘客端：登录 ============
        self._passenger_login()

        # ============ 乘客端：检测并取消进行中订单 ============
        self._passenger_check_and_cancel_ongoing()
        time.sleep(1)

        # ============ 乘客端：搜索+估价+下单 ============
        order_no = self._passenger_search_and_order()
        assert order_no, "下单未返回 order_no"

        # ============ 司机端：登录 ============
        self._driver_login()

        # ============ 司机端：出车上线 ============
        self._driver_go_online()

        # ============ 司机端：轮询订单 ============
        polled_order_no = self._driver_polling_order(timeout=30)
        assert polled_order_no == order_no, f"轮询订单号 {polled_order_no} 与乘客下单 {order_no} 不匹配"

        # ============ 司机端：接单 ============
        self._driver_grab_order(order_no)

        # ============ 司机端：状态滑动（到达→开始→结束） ============
        self._driver_service_flow(order_no)

        # ============ 司机端：确认账单/填写金额 ============
        self._driver_confirm_bill(order_no, order_amount=ORDER_AMOUNT, other_amount=OTHER_AMOUNT)

        # ============ 乘客端：查询订单最终状态 ============
        time.sleep(2)
        s, resp = self.passenger.get_order_status(order_no, trace_id=f"p_final_{int(time.time())}")
        assert s == 200, f"最终查询 HTTP 状态码预期 200，实际 {s}"
        status_data = resp.get("data", {})
        logger.info(f"【HK DualEnd】乘客端最终查询订单状态: order_status={status_data.get('order_status')}")

        # ============ 司机端：查询行程详情确认完成 ============
        s, resp = self.driver.get_trip_detail(order_no, trace_id=f"d_trip_{int(time.time())}")
        if resp.get("code") == 10000:
            order = resp.get("data", {}).get("order", {})
            logger.info(f"【HK DualEnd】行程详情: order_status={order.get('order_status')}，"
                        f"order_status_name={order.get('order_status_name')}，"
                        f"pay_status_name={order.get('pay_status_name')}")

        # ============ 司机端：收车下线 ============
        self.driver.handle_work_status(handle_status=0, trace_id=f"d_offline_{int(time.time())}")
        logger.info("【HK DualEnd】司机端收车下线")

        logger.info("【HK DualEnd】双端联动完整流程验证通过！")
        logger.info(f"  订单号: {order_no}")
        logger.info(f"  起点(搜索获取): {BEGIN_SEARCH_KEYWORD}")
        logger.info(f"  终点(搜索获取): {END_SEARCH_KEYWORD}")
        logger.info(f"  订单金额: {ORDER_AMOUNT} HKD")
        logger.info(f"  最终状态: 已完成")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
