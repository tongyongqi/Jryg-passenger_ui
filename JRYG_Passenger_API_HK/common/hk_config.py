"""香港接口自动化统一配置管理。

所有硬编码参数集中到此文件，支持通过环境变量覆盖。
敏感信息（密钥、密码、内网IP）优先从环境变量读取。

使用方式：
    from JRYG_Passenger_API_HK.common.hk_config import config

    # 读取配置
    mobile = config.PASSENGER_MOBILE
    sign_key = config.SIGN_KEY

环境变量一览（优先级高于配置文件默认值）：
    # 乘客端
    HK_API_BASE_URL          乘客端 API 基地址
    HK_PASSENGER_MOBILE      乘客端测试手机号
    HK_PASSENGER_CAPTCHA     乘客端测试验证码

    # 司机端
    HK_DRIVER_API_BASE_URL   司机端 API 基地址
    HK_DRIVER_MOBILE         司机端测试手机号
    HK_DRIVER_CAPTCHA        司机端测试验证码
    HK_DRIVER_LATITUDE       司机端定位纬度
    HK_DRIVER_LONGITUDE      司机端定位经度

    # 搜索/路线
    HK_BEGIN_SEARCH_KEYWORD  起点搜索关键词
    HK_END_SEARCH_KEYWORD    终点搜索关键词
    HK_SEARCH_LATITUDE       搜索定位纬度
    HK_SEARCH_LONGITUDE      搜索定位经度

    # 账单
    HK_ORDER_AMOUNT          订单金额
    HK_OTHER_AMOUNT          其他金额

    # 安全/密钥
    HK_SIGN_KEY              签名密钥
    HK_REDIS_HOST            Redis 主机
    HK_REDIS_PORT            Redis 端口
    HK_REDIS_PASSWORD        Redis 密码
    HK_REDIS_DB              Redis 数据库
    HK_SOCKET_GATEWAY_HOST   Socket 网关 IP
    HK_SOCKET_GATEWAY_PORT   Socket 网关端口

    # 通用
    HK_AREA_CODE             区号（默认 +852）
    HK_CITY_ID               城市 ID
    HK_REQUEST_TIMEOUT       请求超时（秒）
"""

import os


class HKConfig:
    """香港接口自动化统一配置（单例模式，全局共享）。"""

    # ==================== 乘客端配置 ====================

    # 乘客端 API 基地址
    PASSENGER_BASE_URL = os.environ.get(
        "HK_API_BASE_URL",
        "http://app-client-test.sunlightmobility.hk",
    )

    # 乘客端测试手机号（与 iOS App 登录账号一致：11001727）
    PASSENGER_MOBILE = os.environ.get("HK_PASSENGER_MOBILE", "11001727")

    # 乘客端测试验证码（测试环境固定值）
    PASSENGER_CAPTCHA = os.environ.get("HK_PASSENGER_CAPTCHA", "123456")

    # 乘客端 App 版本信息
    PASSENGER_APP_VERSION = "1.4.0"
    PASSENGER_APP_TERMINAL = "Android"
    PASSENGER_OS_VERSION = "Android16"
    PASSENGER_DEVICE_MODEL = "SM-S9280"
    PASSENGER_CHANNEL = "guanwang"

    # 乘客端设备标识（接口签名所需固定标识）
    PASSENGER_DEVICE_NO = (
        "cdf56abe2fb0aba6-3E697AB8C454206BC0EEC57C7E3B17D876F7FCFF"
    )

    # ==================== 司机端配置 ====================

    # 司机端 API 基地址
    DRIVER_BASE_URL = os.environ.get(
        "HK_DRIVER_API_BASE_URL",
        "http://driver-test.sunlightmobility.hk",
    )

    # 司机端测试手机号（司机ID=31, name=T師傅）
    DRIVER_MOBILE = os.environ.get("HK_DRIVER_MOBILE", "11000005")

    # 司机端测试验证码
    DRIVER_CAPTCHA = os.environ.get("HK_DRIVER_CAPTCHA", "123456")

    # 司机端 App 版本信息
    DRIVER_APP_VERSION = "1.2.2"
    DRIVER_APP_TERMINAL = "Android"
    DRIVER_OS_VERSION = "Android14"
    DRIVER_DEVICE_MODEL = "Pixel 8"
    DRIVER_CHANNEL = "guangwang"

    # 司机端设备标识
    DRIVER_DEVICE_NO = (
        "82870dca777fcd5b-7D6F0B63B272F42F8DBBFD3644226913A8DA66D2"
    )

    # 高德 IMEI（servingOrder 接口需要）
    DRIVER_GAODE_IMEI = "##amapf210603d-ef00-4912-b3af-47b776a426ef"

    # 司机端定位坐标（模拟司机位置）
    DRIVER_LATITUDE = os.environ.get("HK_DRIVER_LATITUDE", "22.277409")
    DRIVER_LONGITUDE = os.environ.get("HK_DRIVER_LONGITUDE", "114.188752")

    # ==================== 搜索/路线配置 ====================

    # 起终点搜索关键词
    BEGIN_SEARCH_KEYWORD = os.environ.get("HK_BEGIN_SEARCH_KEYWORD", "銅鑼灣")
    END_SEARCH_KEYWORD = os.environ.get("HK_END_SEARCH_KEYWORD", "香港")

    # 搜索定位坐标（用于 searchAddress 接口）
    SEARCH_LATITUDE = os.environ.get("HK_SEARCH_LATITUDE", "22.278893")
    SEARCH_LONGITUDE = os.environ.get("HK_SEARCH_LONGITUDE", "114.180418")

    # ==================== 账单配置 ====================

    # 司机端确认账单金额（两文件原不一致: "5" vs "88"，统一为 "5"）
    ORDER_AMOUNT = os.environ.get("HK_ORDER_AMOUNT", "5")
    OTHER_AMOUNT = os.environ.get("HK_OTHER_AMOUNT", "0")

    # ==================== 安全/密钥配置 ====================

    # 签名密钥（乘客端和司机端共用）
    SIGN_KEY = os.environ.get(
        "HK_SIGN_KEY", "RCY9H4c9Cc9z6KaKrunTToWsjCERRexY"
    )

    # Redis 连接配置
    REDIS_HOST = os.environ.get("HK_REDIS_HOST", "172.31.104.4")
    REDIS_PORT = int(os.environ.get("HK_REDIS_PORT", "6379"))
    REDIS_PASSWORD = os.environ.get(
        "HK_REDIS_PASSWORD", "ygcx_test2@wqBEUSwzxmDv8hpO"
    )
    REDIS_DB = int(os.environ.get("HK_REDIS_DB", "8"))

    # Socket 网关配置
    SOCKET_GATEWAY_HOST = os.environ.get(
        "HK_SOCKET_GATEWAY_HOST", "43.128.0.173"
    )
    SOCKET_GATEWAY_PORT = int(os.environ.get("HK_SOCKET_GATEWAY_PORT", "9527"))

    # ==================== 通用配置 ====================

    # 香港区号
    AREA_CODE = os.environ.get("HK_AREA_CODE", "+852")

    # 城市 ID
    CITY_ID = os.environ.get("HK_CITY_ID", "514")

    # 请求超时（秒）
    REQUEST_TIMEOUT = int(os.environ.get("HK_REQUEST_TIMEOUT", "15"))

    # 登录方式: 0 表示验证码登录
    LOGIN_METHOD = "0"

    # 验证码场景值: 100 表示登录验证码
    SMS_SCENE = "100"

    # ==================== 流程控制参数（等待时间） ====================

    # 状态变更间隔（秒）
    STATUS_WAIT = 2

    # Socket 位置上报稳定等待（秒）
    SOCKET_STABILIZE_WAIT = 10

    # 轮询订单超时（秒）
    POLLING_TIMEOUT = 120

    # 轮询间隔（秒）
    POLLING_INTERVAL = 3

    # 模拟行驶步数（结束行程前需沿导航移动足够距离）
    MOVE_STEPS = 30

    # 行驶间隔（秒）
    MOVE_INTERVAL = 2

    # 接单后等待（秒）
    GRAB_WAIT = 5


# 全局单例
config = HKConfig()
