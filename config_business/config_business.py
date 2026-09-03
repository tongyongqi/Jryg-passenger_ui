# -*- coding: utf-8 -*-
# 这个文件的功能是保存各业务个性化参数配置的代码
# config_business.py
# ==========================================
# ⚙️ 业务个性化参数配置文件 (create_coupon / send_coupon 各自专有)
# ==========================================

# 🎫 1. 创建优惠券 (create_coupon.py) 专属业务配置
COUPON_NAME = "自动化创建优惠卷1000元"        # 拟创建的优惠券名称
FACE_VALUE = "1000"                          # 优惠券面值金额 (元)
USE_RULE = "1"                               # 使用门槛：满多少元可用 (元)
MAX_DISCOUNT = "100"                         # 最高抵扣比例百分比 (100 代表 100%)
COUPON_QTY = "100000"                        # 优惠券发行量 (张)
START_DATE = "2026-08-12"                    # 有效期开始日期 (YYYY-MM-DD)
END_DATE = "2048-09-30"                      # 有效期结束日期 (YYYY-MM-DD)
REMARK_HTML = "<p>123</p>"                   # 富文本使用说明 (HTML 格式)
CITY_LIMIT = "全国"                           # 发券覆盖城市

# 适用商家勾选列表 (可根据喜好自由增减商家名称)
MERCHANTS = ["小马智行", "金葵花", "阳光智行", "阳光自营"]

# ------------------------------------------

# 🚀 2. 发放优惠券 (send_coupon.py) 专属业务配置
TARGET_PHONE = "11000006910"                 # 接收优惠券的目标客户手机号 (支持多手机号换行输入)
SEND_QTY = "10"                               # 每次给客户发放的优惠券张数
REMARK_TEXT = "自动发送优惠卷"                # 发放备注说明
SEND_COUPON_BATCH = "34303"                  # 要高精度过滤并选中的发放优惠券批次号

# 3. 发放时浏览器调试设置
HEADLESS_DEBUG = True                       # 是否开启调试：False 代表真实弹出浏览器看效果并停留10秒，True 代表无头静默运行

# ------------------------------------------

# 🛠️ 3. 工单业务专属配置 (1, 5, 6 分开配置)

# 🛠️ 3.1 创建工单配置 (MODE 1)
TARGET_ORDER_ID_1 = "7358984706"        # 待创建工单的真实订单编号 (可在此随意热更改)
META_ID_1 = "113491"                    # 默认关联的 meta_id 属性
ORDER_TYPE_1 = "5"                      # 默认关联的 order_type 属性
WORK_ORDER_TYPE_1 = "投诉"              # 工单类型选择 (如投诉、建议等)
WORK_ORDER_REMARK_1 = "自动创建工单"     # 工单内容/受理备注说明

# 🛠️ 3.5 工单受理配置 (MODE 5)
TARGET_ORDER_ID_5 = "7358984706"        # 待受理的订单号

# 🛠️ 3.6 工单退款结算配置 (MODE 6)
TARGET_ORDER_ID_6 = "7358984706"        # 待结算的订单号

# 兼容旧代码默认属性 (默认指向 MODE 1 配置)
TARGET_ORDER_ID = TARGET_ORDER_ID_1
META_ID = META_ID_1
ORDER_TYPE = ORDER_TYPE_1
WORK_ORDER_TYPE = WORK_ORDER_TYPE_1
WORK_ORDER_REMARK = WORK_ORDER_REMARK_1

# ------------------------------------------

# 💰 4. 接口退款 (refund_order.py) 专属业务配置
REFUND_API_URL = "http://cashier.tx-test6.jryghq.cn/pay/v1/applyTradeRefund"
REFUND = {
    "order_id": 7359087690,               # 订单号 (int 类型)
    "order_no": "2693DPESEIWX4ER",         # 订单编号
    "refund_amount": 380,                 # 退款金额 (分)
    "refund_reason": "测试",                # 退款原因
    "work_id": 1                           # 工单ID
}
