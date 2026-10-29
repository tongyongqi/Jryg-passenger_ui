"""
港版阳光出行 iOS 乘客端 —— 全局 UI 元素变量定义
==============================================================================
所有 iOS 测试用例共享的元素定位变量，统一管理，避免硬编码。
==============================================================================
"""

# ==================== App 基本信息 ====================
PASSENGER_BUNDLE_ID = "com.sunlightmobility.client"

# ==================== 首页元素 ====================
# 起点入口（XPath 匹配多种占位文案）
START_GATE_XPATH = (
    '//*[contains(@label, "起點") or contains(@value, "起點") '
    'or contains(@label, "起点") or contains(@value, "起点") '
    'or contains(@label, "您從哪") or contains(@value, "您從哪")]'
)
START_GATE_POCO_REGEX = ".*起點.*|.*起点.*|.*您從哪.*|.*您从哪.*"
START_GATE_FALLBACK_COORD = (0.5, 0.72)  # 起点绿色圆点常见位置

# 终点入口
DEST_GATE_XPATH = (
    '//*[contains(@label, "想去") or contains(@value, "想去") '
    'or contains(@label, "哪裡") or contains(@value, "哪裡") '
    'or contains(@label, "哪里") or contains(@value, "哪里")]'
)
DEST_GATE_POCO_REGEX = ".*想去哪.*|.*目的地.*|.*去哪.*"
DEST_GATE_FALLBACK_COORD = (0.5, 0.68)

# 搜索页输入框
SEARCH_TEXTFIELD_TYPE = "XCUIElementTypeTextField"
SEARCH_INPUT_COORD = (0.5, 0.125)  # 搜索页输入框常见位置
SEARCH_FIRST_RESULT_COORD = (0.5, 0.25)  # 搜索结果首行常见位置

# 键盘完成按钮
KEYBOARD_DONE_XPATH = (
    '//XCUIElementTypeButton[@name="完成" or @label="完成" '
    'or @name="Done" or @label="Done"]'
)

# 引导页跳过按钮
GUIDE_SKIP_XPATH = '//XCUIElementTypeButton[@name="icon hd gb" or @label="icon hd gb"]'

# 广告弹窗关闭按钮标识
AD_CLOSE_IDENTIFIERS = ["iv_cancel", "close", "关闭", "叉号"]

# ==================== 车型选择 ====================
# 包車價的士
CHARTER_CAR_LABEL = "包車價的士"
CHARTER_CAR_XPATH_EXACT = '//*[(@label="包車價的士" or @value="包車價的士" or @name="包車價的士")]'
CHARTER_CAR_XPATH_CONTAINS = (
    '//*[contains(@label, "包車價") or contains(@value, "包車價") '
    'or contains(@label, "包车价") or contains(@value, "包车价")]'
)
CHARTER_CAR_POCO_REGEX = ".*包車價.*|.*包车价.*"
CHARTER_CAR_FALLBACK_COORD = (0.25, 0.72)

# 打錶的士
METER_CAR_LABEL = "打錶的士"
METER_CAR_XPATH_EXACT = '//*[(@label="打錶的士" or @value="打錶的士" or @name="打錶的士")]'
METER_CAR_XPATH_CONTAINS = (
    '//*[contains(@label, "打錶") or contains(@value, "打錶") '
    'or contains(@label, "打表") or contains(@value, "打表")]'
)
METER_CAR_POCO_REGEX = ".*打錶.*|.*打表.*"
METER_CAR_FALLBACK_COORD = (0.75, 0.72)

# ==================== 确认呼叫按钮 ====================
CONFIRM_CALL_XPATH = (
    '//*[contains(@label, "確認呼叫") or contains(@value, "確認呼叫") '
    'or contains(@label, "确认呼叫") or contains(@value, "确认呼叫")]'
)
CONFIRM_CALL_POCO_REGEX = ".*確認呼叫.*|.*确认呼叫.*|.*呼叫.*"
CONFIRM_CALL_FALLBACK_COORD = (0.5, 0.95)

# ==================== 收银台（先付後乘） ====================
CASHIER_PAGE_KEYWORDS = ["預付車費", "先付後乘", "確認支付並呼叫"]
CONFIRM_PAY_XPATH = (
    '//*[contains(@label, "確認支付並呼叫") or contains(@value, "確認支付並呼叫") '
    'or contains(@label, "确认支付并呼叫") or contains(@value, "确认支付并呼叫")]'
)
CONFIRM_PAY_POCO_REGEX = ".*確認支付.*|.*确认支付.*|.*支付並呼叫.*|.*支付并呼叫.*"
CONFIRM_PAY_FALLBACK_COORD = (0.5, 0.92)

# ==================== 支付方式选项 ====================
# Alipay HK
ALIPAY_KEYWORDS = ["Alipay HK", "Alipay", "支付寶HK", "支付寶"]
ALIPAY_POCO_REGEX = ".*Alipay.*|.*支付寶.*|.*支付宝.*"

# 信用卡/扣帳卡
BANKCARD_KEYWORDS = ["信用卡", "扣帳卡", "扣帐卡"]
BANKCARD_POCO_REGEX = ".*信用卡.*|.*扣帳卡.*|.*扣帐卡.*"

# 现金支付
CASH_KEYWORDS = ["現金", "现金", "Cash"]

# 电子支付
EPAYMENT_KEYWORDS = ["電子支付", "电子支付", "Electronic", "e-payment", "E-Payment"]

# 八达通（仅检测，不做下单）
OCTOPUS_KEYWORDS = ["八達通", "八达通", "Octopus"]

# ==================== 银行卡填写页 ====================
BANK_PAGE_KEYWORDS = ["銀行卡", "卡號", "需付總額"]
FINAL_PAY_XPATH = (
    '//*[contains(@label, "請支付") or contains(@value, "請支付") '
    'or contains(@label, "请支付") or contains(@value, "请支付")]'
)
FINAL_PAY_POCO_REGEX = ".*請支付.*|.*请支付.*|.*支付.*"
FINAL_PAY_FALLBACK_COORD = (0.5, 0.92)

# OTP / 3D Secure 验证页
OTP_PAGE_KEYWORDS = ["安全結帳", "One-Time Password", "OTP"]
OTP_VERIFY_XPATH = (
    '//XCUIElementTypeButton[contains(@label, "Verify") or contains(@name, "Verify") '
    'or contains(@label, "验证") or contains(@name, "验证")]'
)
OTP_VERIFY_FALLBACK_COORD = (0.5, 0.68)
OTP_DEFAULT_CODE = "123456"
OTP_FALLBACK_COORD = (196, 539)

# ==================== Alipay HK 授权页 ====================
ALIPAY_AUTH_KEYWORDS = ["Alipay", "支付寶", "支付宝", "AlipayHK", "付款", "支付"]
ALIPAY_CONFIRM_BUTTONS = ["確認支付", "確認付款", "立即支付", "確認", "Confirm", "Pay", "支付"]

# ==================== 下单结果判断 ====================
ORDER_SUCCESS_KEYWORDS = ["正在為您呼叫車輛", "取消訂單", "附近車輛較少", "司機"]
ORDER_FAIL_KEYWORDS = ["未能查閱到付款記錄", "支付失敗", "支付失败", "訂單已取消", "订单已取消"]
ORDER_PROCESSING_KEYWORDS = ["查詢結果中", "正在確認起終點", "處理中"]

# ==================== 优惠券 ====================
COUPON_XPATH = (
    '//*[contains(@label, "優惠券") or contains(@value, "優惠券") '
    'or contains(@label, "优惠券") or contains(@value, "优惠券") '
    'or contains(@label, "优惠") or contains(@value, "优惠") '
    'or contains(@label, "折扣") or contains(@value, "折扣")]'
)
COUPON_POCO_REGEX = ".*優惠券.*|.*优惠券.*|.*优惠.*|.*優惠.*|.*折扣.*"
COUPON_FALLBACK_COORD = (0.85, 0.8)
COUPON_TARGET_TEXTS = ["100元优惠卷", "100元优惠券", "100", "100元"]

# ==================== 测试数据 ====================
DEFAULT_START_ADDRESS = "北角地铁站"
DEFAULT_END_ADDRESS = "香港大学"

# 距离太近时的备选终点（按优先级排列）
FALLBACK_END_ADDRESSES = ["銅鑼灣", "中環", "尖沙咀"]

# 距离太近提示关键词
DISTANCE_TOO_CLOSE_KEYWORDS = ["距離太近", "距离太近", "太近", "距离过近", "距離過近"]
BOOKING_START_ADDRESS = "铜锣湾地铁站"
BOOKING_END_ADDRESS = "香港大学"

# 银行卡测试数据
TEST_CARD_NUMBER = "4054695723100768"
TEST_CARD_EXPIRY = "0928"
TEST_CARD_CVV = "999"
TEST_CARD_HOLDER = "TEST USER"
