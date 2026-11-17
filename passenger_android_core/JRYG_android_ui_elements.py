"""港版阳光出行 Android 乘客端 —— 全局 UI 元素常量定义。

Android 用 resource-id 和文本定位，不使用 Android XPath/Poco。
常量名与 Android 版本保持一致以减少下游代码改动，但定位方式改为 Android 原生。
"""

# ==================== App 基本信息 ====================
PASSENGER_BUNDLE_ID = "com.sunlightmobility.client"

# ==================== 首页元素 ====================
START_GATE_XPATH = ""  # Android 不使用 XPath
START_GATE_POCO_REGEX = ".*起點.*|.*起点.*|.*您從哪.*|.*您从哪.*"
START_GATE_FALLBACK_COORD = (0.5, 0.72)

DEST_GATE_XPATH = ""
DEST_GATE_POCO_REGEX = ".*想去哪.*|.*目的地.*|.*去哪.*"
DEST_GATE_FALLBACK_COORD = (0.5, 0.68)

SEARCH_TEXTFIELD_TYPE = "android.widget.EditText"
SEARCH_INPUT_COORD = (0.5, 0.125)
SEARCH_FIRST_RESULT_COORD = (0.5, 0.25)

KEYBOARD_DONE_XPATH = ""
GUIDE_SKIP_XPATH = ""
AD_CLOSE_IDENTIFIERS = ["iv_cancel", "close", "关闭", "叉号"]

# ==================== 车型选择 ====================
CHARTER_CAR_LABEL = "包車價的士"
CHARTER_CAR_XPATH_EXACT = ""
CHARTER_CAR_XPATH_CONTAINS = ""
CHARTER_CAR_POCO_REGEX = ".*包車價.*|.*包车价.*"
CHARTER_CAR_FALLBACK_COORD = (0.25, 0.72)

METER_CAR_LABEL = "打錶的士"
METER_CAR_XPATH_EXACT = ""
METER_CAR_XPATH_CONTAINS = ""
METER_CAR_POCO_REGEX = ".*打錶.*|.*打表.*"
METER_CAR_FALLBACK_COORD = (0.75, 0.72)

# ==================== 确认呼叫按钮 ====================
CONFIRM_CALL_XPATH = ""
CONFIRM_CALL_POCO_REGEX = ".*確認呼叫.*|.*确认呼叫.*|.*呼叫.*"
CONFIRM_CALL_FALLBACK_COORD = (0.5, 0.95)
ESTIMATE_UPDATED_KEYWORDS = ("預估資訊已更新，請重新選擇", "预估信息已更新，请重新选择")
ESTIMATE_REFRESH_TIMEOUT = 30
ESTIMATE_CALL_MAX_ATTEMPTS = 3

# ==================== 收银台（先付後乘） ====================
CASHIER_PAGE_KEYWORDS = ["預付車費", "先付後乘", "確認支付並呼叫"]
CONFIRM_PAY_XPATH = ""
CONFIRM_PAY_POCO_REGEX = ".*確認支付.*|.*确认支付.*|.*支付並呼叫.*|.*支付并呼叫.*"
CONFIRM_PAY_FALLBACK_COORD = (0.5, 0.92)

# ==================== 支付方式选项 ====================
ALIPAY_KEYWORDS = ["Alipay HK", "Alipay", "支付寶HK", "支付寶"]
ALIPAY_POCO_REGEX = ".*Alipay.*|.*支付寶.*|.*支付宝.*"

BANKCARD_KEYWORDS = ["信用卡", "扣帳卡", "扣帐卡"]
BANKCARD_POCO_REGEX = ".*信用卡.*|.*扣帳卡.*|.*扣帐卡.*"

CASH_KEYWORDS = ["現金", "现金", "Cash"]

EPAYMENT_KEYWORDS = ["電子支付", "电子支付", "Electronic", "e-payment", "E-Payment"]

# ==================== 银行卡填写页 ====================
BANK_PAGE_KEYWORDS = ["銀行卡", "卡號", "需付總額"]
FINAL_PAY_XPATH = ""
FINAL_PAY_POCO_REGEX = ".*請支付.*|.*请支付.*|.*支付.*"
FINAL_PAY_FALLBACK_COORD = (0.5, 0.92)

# OTP / 3D Secure 验证页
OTP_PAGE_KEYWORDS = ["安全結帳", "One-Time Password", "OTP"]
OTP_VERIFY_XPATH = ""
OTP_VERIFY_FALLBACK_COORD = (0.5, 0.717)
OTP_DEFAULT_CODE = "123456"
OTP_FALLBACK_COORD = (196, 539)
OTP_CLEAR_TIMES = 12
OTP_SUCCESS_KEYWORDS = ["SUCCESS", "成功", "Payment Successful", "交易成功"]
OTP_RETURN_APP_KEYWORDS = ["打開", "打开"]

# ==================== Alipay HK 授权页 ====================
ALIPAY_AUTH_KEYWORDS = ["Alipay", "支付寶", "支付宝", "AlipayHK", "付款", "支付"]
ALIPAY_CONFIRM_BUTTONS = ["確認支付", "確認付款", "立即支付", "確認", "Confirm", "Pay", "支付"]

# ==================== 下单结果判断 ====================
ORDER_SUCCESS_KEYWORDS = ["正在為您呼叫車輛", "取消訂單", "附近車輛較少", "司機"]
ORDER_FAIL_KEYWORDS = ["未能查閱到付款記錄", "支付失敗", "支付失败",
                       "訂單已取消", "订单已取消",
                       "訂單已超時", "订单已超时",
                       "暫無司機接單", "暂无司机接单",
                       "系統繁忙", "系统繁忙"]
ORDER_PROCESSING_KEYWORDS = ["查詢結果中", "正在確認起終點", "處理中"]

# ==================== 优惠券 ====================
COUPON_XPATH = ""
COUPON_POCO_REGEX = ".*優惠券.*|.*优惠券.*|.*优惠.*|.*優惠.*|.*折扣.*"
COUPON_FALLBACK_COORD = (0.85, 0.8)
COUPON_TARGET_TEXTS = ["100元优惠卷", "100元优惠券", "100", "100元"]

# ==================== 测试数据 ====================
DEFAULT_START_ADDRESS = "北角地铁站"
DEFAULT_END_ADDRESS = "香港大学"
NORTH_POINT_SEARCH_TEXT = "北角"
NORTH_POINT_STATION_NAMES = ("北角(地鐵站)", "北角地鐵站", "北角地铁站")
NORTH_POINT_DISTRICT = "香港特別行政區東區Eastern District"
NORTH_POINT_START_PLACEHOLDER = "您從哪裡出發"
NORTH_POINT_EXIT = "A1出入口"

FALLBACK_END_ADDRESSES = ["銅鑼灣", "中環", "尖沙咀"]

DISTANCE_TOO_CLOSE_KEYWORDS = ["距離太近", "距离太近", "太近", "距离过近", "距離過近"]

BOOKING_START_ADDRESS = "铜锣湾地铁站"
BOOKING_END_ADDRESS = "香港大学"

TEST_CARD_NUMBER = "4054695723100768"
TEST_CARD_EXPIRY = "0929"
TEST_CARD_CVV = "999"
TEST_CARD_HOLDER = "TEST USER"
