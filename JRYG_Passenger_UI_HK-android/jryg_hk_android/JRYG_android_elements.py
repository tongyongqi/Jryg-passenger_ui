"""
港版阳光出行 Android 乘客端 —— 全局 UI 元素变量定义
==============================================================================
所有 Android 测试用例共享的元素定位变量，统一管理，避免硬编码。
==============================================================================
"""

# ==================== App 基本信息 ====================
PASSENGER_PACKAGE = "com.sunlightmobility.client"
PASSENGER_ACTIVITY = "com.sunlightmobility.client.launcher.YGALoadingActivity"
DRIVER_PACKAGE = "com.sunlightmobility.driver"
DRIVER_ACTIVITY = "com.sunlightmobility.driver.activity.loading.YGALoadingActivity"

# ==================== 登录页元素 ====================
PHONE_INPUT_ID = "com.sunlightmobility.client:id/phone_num"
GET_CODE_BTN_ID = "com.sunlightmobility.client:id/rl_next"
VERIFY_CODE_INPUT_ID = "com.sunlightmobility.client:id/verify_code"
MINE_NAME_ID = "com.sunlightmobility.client:id/tv_mine_name"
AGREE_CHECKBOX_TEXT = "已閱讀並同意"

# 登录页文本
TEXT_AGREE = "同意"
TEXT_DISAGREE = "不同意"
TEXT_GO_AUTH = "去授權"
TEXT_CANCEL = "取消"
TEXT_ALLOW_LOCATION = "使用应用时允许"
TEXT_ALLOW_LOCATION_ALT = "仅在使用中允许"
TEXT_LOGIN_REGISTER = "登錄/註冊"
TEXT_INPUT_PHONE = "請輸入手機號"
TEXT_GET_CODE = "取得驗證碼"
TEXT_INPUT_CODE = "請輸入驗證碼"
TEXT_REGET_CODE_REGEX = ".*重新獲取.*"

# 登录测试数据
LOGIN_PHONE_NUMBER = "11001727"
LOGIN_VERIFY_CODE = "123456"

# ==================== 首页元素 ====================
TAB_HOME_ID = "com.sunlightmobility.client:id/item_tab_icon_layout"
START_ADDRESS_ID = "com.sunlightmobility.client:id/tv_start_address"
DEST_TEXT = "想要去哪裡？"
DEST_ID = "com.sunlightmobility.client:id/tv_destination"
DEST_LAYOUT_ID = "com.sunlightmobility.client:id/rl_destination_layout"
SEARCH_INPUT_ID = "com.sunlightmobility.client:id/et_search"
SEARCH_RESULT_TITLE_ID = "com.sunlightmobility.client:id/tv_title"
CALL_BTN_ID = "com.sunlightmobility.client:id/btn_call"

# 首页坐标（基于 1080x2700 分辨率）
HOME_TAB_COORD = (195, 2676)
AD_CLOSE_COORD = (585, 2047)
CALL_BTN_COORD = (586, 2551)

# ==================== 车型选择 ====================
CHARTER_CAR_REGEX = ".*包車.*|.*包车.*"
METER_CAR_REGEX = ".*打錶.*|.*打表.*"
CHARTER_CAR_COORD_RATIO = (0.25, 0.83)
METER_CAR_COORD_RATIO = (0.75, 0.83)

# ==================== 优惠券 ====================
COUPON_REGEX = ".*券.*|.*優惠.*|.*优惠.*|.*抵扣.*|.*HKD.*"
COUPON_TARGET_REGEX = ".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*|.*元.*|.*HKD.*|.*折.*"
COUPON_VERIFY_REGEX = ".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*"
COUPON_USE_BTN_REGEX = ".*確定.*|.*确定.*|.*確認.*|.*确认.*|.*使用.*"
COUPON_ENTRY_COORD_RATIO = (0.85, 0.81)

# ==================== 确认呼叫 ====================
CONFIRM_CALL_COORD_RATIO = (0.50, 0.928)

# ==================== 司机端元素 ====================
DRIVER_FEE_INPUT_ID = "com.sunlightmobility.driver:id/et_input_fee"
DRIVER_STATE_PICKUP_REGEX = ".*到達上車地點.*|.*到达上车地点.*"
DRIVER_STATE_RECEIVED_REGEX = ".*已接到乘客.*|.*接到乘客.*|.*已接載乘客.*|.*接載乘客.*"
DRIVER_STATE_DEST_REGEX = ".*到達目的地.*|.*到达目的地.*|.*已到達目的地.*|.*已到达目的地.*|.*行程結束.*|.*行程结束.*|.*結束行程.*|.*结束行程.*"
DRIVER_STATE_BILLING_REGEX = ".*發起收款.*|.*发起收款.*|.*確認賬單.*|.*确认账单.*|.*確認收款.*|.*确认收款.*"
DRIVER_FINISHED_REGEX = ".*今日營收.*|.*今日营收.*|.*聽單.*|.*听单.*|.*完單數.*|.*完单数.*"
DRIVER_BACK_HOME_REGEX = ".*返回首頁.*|.*返回首页.*|.*確定.*|.*确定.*|.*返回.*"

# 司机端订单入口文本
DRIVER_ORDER_ENTRY_TEXTS = [
    "訂單進行中", "订单进行中", "未確認賬單", "未确认账单",
    "進行中", "进行中", "去處理", "去处理", "待出發", "待出发",
    "新訂單", "新订单",
]
DRIVER_POPUP_TEXTS = ["同意", "我知道了", "知道了", "好的", "去授權", "去授权"]

# ==================== 下单结果判断 ====================
ORDER_SUCCESS_KEYWORDS = ["司機", "趕來", "赶來", "取消訂單", "附近車輛較少", "正在為您呼叫車輛"]
ORDER_FAIL_KEYWORDS = ["未能查閱到付款記錄", "支付失敗", "支付失败", "訂單已取消", "订单已取消"]

# ==================== 测试数据 ====================
DEFAULT_START_ADDRESS = "铜锣湾地铁站"
DEFAULT_END_ADDRESS = "香港大学"
