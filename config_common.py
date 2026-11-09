# config_common.py
# ==========================================
# 🌐 公共通用系统参数配置文件 (coupon_manage / coupon_give 共享)
# ==========================================

# 1. 后台主页管理 URL 路径
BASE_URL = "https://dcms-test6-tx.jryghq.com/#/admin/v1/coupon_manage"

# 2. 账号、密码与验证码登录信息
USERNAME = "18618251727"
PASSWORD = "Tyq302152131,.?"
IMAGE_CAPTCHA = "9"            # 默认填充的图形验证码
SMS_CAPTCHA = "999999"          # 默认填充的短信验证码

# 3. 浏览器核心底层运行配置
DEFAULT_TIMEOUT = 60000         # 网络延迟/操作超时时间限制 (毫秒)
