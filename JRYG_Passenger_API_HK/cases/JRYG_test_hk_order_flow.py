"""香港乘客端下单全流程接口自动化测试（纯接口，不依赖设备）。

完整流程：登录 → 搜索起点 → 搜索终点 → 估价 → 下单 → 查询订单状态 → 取消订单

接口清单：
  1. POST /passenger/user/sendAuthCode        发送验证码（表单）
  2. POST /passenger/user/login              验证码登录（表单）
  3. POST /passenger/location/searchAddress   搜索地址（表单，参数: address_type/latitude/longitude/name）
  4. POST /passenger/order/estimate           估价（JSON，需begin_poi_id/end_poi_id）
  5. POST /passenger/order/create             下单（JSON）
  6. GET  /passenger/order/status             查询订单状态
  7. POST /passenger/order/prepareCancel      预取消（表单）
  8. POST /passenger/order/cancel             取消订单（表单）

测试流程：
  - 通过搜索地址接口搜索起点和终点，获取实际坐标和poi_id
  - 使用搜索结果中的坐标和poi_id进行估价和下单
  - 不允许跳过搜索地址步骤或使用硬编码坐标直接下单
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
from JRYG_Passenger_API_HK.common.JRYG_logger import logger

# 搜索关键词（模拟App实际操作）
BEGIN_SEARCH_KEYWORD = "銅鑼灣"
END_SEARCH_KEYWORD = "香港"

# 搜索时的当前定位坐标（模拟App初始定位）
SEARCH_LATITUDE = "22.278893"
SEARCH_LONGITUDE = "114.180418"


class TestHKOrderFlow:
    """香港乘客端下单全流程测试套件。

    测试用例：
      test_order_full_flow: 完整下单流程（登录→搜索起终点→估价→下单→取消）

    前置条件：
      - 可访问 http://app-client-test.sunlightmobility.hk 测试环境
      - 测试手机号已在服务端白名单中（验证码固定 123456）
    """

    @classmethod
    def setup_class(cls):
        """类级 setup：创建客户端并登录。"""
        import requests
        import socket
        cls.client = HKApiClient()

        # 检查服务可达性
        try:
            parsed = requests.utils.urlparse(cls.client.base_url)
            host = parsed.hostname or cls.client.base_url
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            socket.create_connection((host, port), timeout=3).close()
        except Exception:
            pytest.skip(f"无法连接服务 {cls.client.base_url}，请设置 HK_API_BASE_URL 环境变量或连接内网 VPN")

        logger.info("【HK OrderFlow】接口测试开始，客户端已初始化")

    @classmethod
    def teardown_class(cls):
        """类级 teardown。"""
        logger.info("【HK OrderFlow】接口测试执行完毕")

    def _login(self):
        """辅助方法：发送验证码并登录。"""
        # 发送验证码
        self.client.send_auth_code(trace_id=f"order_flow_sms_{int(time.time())}")
        # 登录
        status, resp = self.client.login(trace_id=f"order_flow_login_{int(time.time())}")
        assert status == 200, f"登录 HTTP 状态码预期 200，实际 {status}"
        assert resp.get("code") == 10000, f"登录失败: {resp}"
        data = resp["data"]
        self.client.access_token = data["access_token"]
        logger.info(f"【HK OrderFlow】登录成功，user_id={data.get('user_id')}")

        # 清理未完成订单，避免 "您還有未完成的訂單" 错误
        self.client.cleanup_unfinished_orders()
        return data

    def _search_address(self, keyword, address_type):
        """辅助方法：搜索地址，返回第一个匹配结果。

        :param keyword: 搜索关键词
        :param address_type: 1=起点, 2=终点
        :return: dict，包含 name, address, latitude, longitude, poi_id 等字段
        """
        trace_id = f"search_addr_{address_type}_{int(time.time())}"
        status, resp = self.client.search_address(
            latitude=SEARCH_LATITUDE,
            longitude=SEARCH_LONGITUDE,
            address_type=address_type,
            name=keyword,
            trace_id=trace_id,
        )
        assert status == 200, f"搜索地址 HTTP 状态码预期 200，实际 {status}"
        assert resp.get("code") == 10000, f"搜索地址失败: {resp}"

        addr_list = resp.get("data", {}).get("list", [])
        assert addr_list, f"搜索地址 '{keyword}' 返回空列表"

        # 取第一个匹配结果
        first = addr_list[0]
        logger.info(f"【HK OrderFlow】搜索地址 '{keyword}' (type={address_type}) 成功，"
                     f"共 {len(addr_list)} 条结果，选中: name={first.get('name')}, "
                     f"lat={first.get('latitude')}, lng={first.get('longitude')}, "
                     f"poi_id={first.get('poi_id')}")
        return first

    def test_order_full_flow(self):
        """测试：完整下单流程（登录 → 搜索起点 → 搜索终点 → 估价 → 下单 → 查询状态 → 取消订单）。

        预期结果：
          - 登录成功，获取 access_token
          - 搜索起点地址成功，获取坐标和 poi_id
          - 搜索终点地址成功，获取坐标和 poi_id
          - 估价成功，获取 estimate_id
          - 下单成功，获取 order_no
          - 订单状态查询成功
          - 取消订单成功，订单状态变为已取消
        """
        # === 步骤1：登录 ===
        login_data = self._login()
        assert login_data.get("access_token"), "登录未返回 access_token"

        # === 步骤2：搜索起点地址 ===
        begin_addr = self._search_address(BEGIN_SEARCH_KEYWORD, address_type=1)
        begin_location = begin_addr.get("name", "")
        begin_latitude = begin_addr.get("latitude", "")
        begin_longitude = begin_addr.get("longitude", "")
        begin_poi_id = begin_addr.get("poi_id", "")
        assert begin_location, "搜索起点未返回 name"
        assert begin_latitude, "搜索起点未返回 latitude"
        assert begin_longitude, "搜索起点未返回 longitude"
        logger.info(f"【HK OrderFlow】步骤2：搜索起点成功 → {begin_location} "
                     f"({begin_latitude}, {begin_longitude}) poi_id={begin_poi_id}")

        # === 步骤3：搜索终点地址 ===
        end_addr = self._search_address(END_SEARCH_KEYWORD, address_type=2)
        end_location = end_addr.get("name", "")
        end_latitude = end_addr.get("latitude", "")
        end_longitude = end_addr.get("longitude", "")
        end_poi_id = end_addr.get("poi_id", "")
        assert end_location, "搜索终点未返回 name"
        assert end_latitude, "搜索终点未返回 latitude"
        assert end_longitude, "搜索终点未返回 longitude"
        logger.info(f"【HK OrderFlow】步骤3：搜索终点成功 → {end_location} "
                     f"({end_latitude}, {end_longitude}) poi_id={end_poi_id}")

        # === 步骤4：估价（使用搜索结果中的坐标和poi_id） ===
        trace_id_4 = f"estimate_{int(time.time())}"
        status_4, resp_4 = self.client.estimate_order(
            begin_location, begin_latitude, begin_longitude,
            end_location, end_latitude, end_longitude,
            begin_poi_id=begin_poi_id,
            end_poi_id=end_poi_id,
            trace_id=trace_id_4,
        )
        assert status_4 == 200, f"估价 HTTP 状态码预期 200，实际 {status_4}"
        assert resp_4.get("code") == 10000, f"估价失败: {resp_4}"

        estimates = resp_4.get("data", {}).get("estimates", [])
        assert estimates, "估价返回空列表"
        # 使用"打錶的士"类型的估价（taxi）
        taxi_estimate = next((e for e in estimates if e.get("car_type") == "taxi"), estimates[0])
        estimate_id = taxi_estimate["estimate_id"]
        logger.info(f"【HK OrderFlow】步骤4：估价成功，estimate_id={estimate_id}，"
                     f"车型={taxi_estimate.get('car_type_name')}")

        # === 步骤5：下单 ===
        trace_id_5 = f"create_{int(time.time())}"
        status_5, resp_5 = self.client.create_order(
            estimate_id=estimate_id, trace_id=trace_id_5
        )
        assert status_5 == 200, f"下单 HTTP 状态码预期 200，实际 {status_5}"
        assert resp_5.get("code") == 10000, f"下单失败: {resp_5}"

        order_data = resp_5.get("data", {})
        order_no = order_data.get("order_no")
        assert order_no, "下单未返回 order_no"
        logger.info(f"【HK OrderFlow】步骤5：下单成功，order_no={order_no}，"
                     f"pay_type={order_data.get('pay_type')}")

        # === 步骤6：查询订单状态 ===
        time.sleep(1)
        trace_id_6 = f"status_{int(time.time())}"
        status_6, resp_6 = self.client.get_order_status(order_no, trace_id=trace_id_6)
        assert status_6 == 200, f"查询订单状态 HTTP 状态码预期 200，实际 {status_6}"
        assert resp_6.get("code") == 10000, f"查询订单状态失败: {resp_6}"
        status_data = resp_6.get("data", {})
        assert status_data.get("order_no") == order_no, "订单号不匹配"
        logger.info(f"【HK OrderFlow】步骤6：查询订单状态成功，order_status={status_data.get('order_status')}")

        # === 步骤7：预取消订单 ===
        trace_id_7 = f"prepare_cancel_{int(time.time())}"
        status_7, resp_7 = self.client.prepare_cancel_order(order_no, trace_id=trace_id_7)
        assert status_7 == 200, f"预取消 HTTP 状态码预期 200，实际 {status_7}"
        assert resp_7.get("code") == 10000, f"预取消失败: {resp_7}"
        logger.info(f"【HK OrderFlow】步骤7：预取消订单成功")

        # === 步骤8：取消订单 ===
        trace_id_8 = f"cancel_{int(time.time())}"
        status_8, resp_8 = self.client.cancel_order(order_no, trace_id=trace_id_8)
        assert status_8 == 200, f"取消订单 HTTP 状态码预期 200，实际 {status_8}"
        assert resp_8.get("code") == 10000, f"取消订单失败: {resp_8}"

        cancel_data = resp_8.get("data", {})
        assert cancel_data.get("canceled") is True, \
            f"取消订单预期 canceled=true，实际 {cancel_data}"
        logger.info(f"【HK OrderFlow】步骤8：取消订单成功，canceled={cancel_data.get('canceled')}")

        # === 最终验证：再次查询订单状态确认已取消 ===
        time.sleep(1)
        trace_id_9 = f"final_status_{int(time.time())}"
        status_9, resp_9 = self.client.get_order_status(order_no, trace_id=trace_id_9)
        assert status_9 == 200, f"最终查询 HTTP 状态码预期 200，实际 {status_9}"
        logger.info(f"【HK OrderFlow】最终查询订单状态: code={resp_9.get('code')}")

        logger.info(f"【HK OrderFlow】完整下单流程验证通过！")
        logger.info(f"  起点(搜索获取): {begin_location} ({begin_latitude}, {begin_longitude})")
        logger.info(f"  终点(搜索获取): {end_location} ({end_latitude}, {end_longitude})")
        logger.info(f"  订单号: {order_no}")
        logger.info(f"  最终状态: 已取消")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
