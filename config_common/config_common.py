# -*- coding: utf-8 -*-
# 这个文件的功能是保存公共通用系统参数配置的代码
# config_common.py
# ==========================================
# 🌐 公共通用系统参数配置文件 (coupon_manage / coupon_give 共享)
# ==========================================

# ==========================================
# 环境切换：test = 测试环境，pre = 预发环境
# ==========================================
ENVIRONMENT = "test"  # 修改为 "pre" 即可切换到预发环境

# 1. 后台主页管理 URL 路径
BASE_URL_TEST = "https://dcms-test6-tx.jryghq.com/#/admin/v1/coupon_manage"
BASE_URL_PRE = "https://pre-dcms.jryghq.com/#/admin/v1/coupon_manage"
BASE_URL = BASE_URL_PRE if ENVIRONMENT == "pre" else BASE_URL_TEST

# 2. 账号、密码与验证码登录信息
USERNAME_TEST = "18618251727"
PASSWORD_TEST = "Tyq302152131,.?"
USERNAME_PRE = "18618251727"
PASSWORD_PRE = "Tyq302152124,.?"
USERNAME = USERNAME_PRE if ENVIRONMENT == "pre" else USERNAME_TEST
PASSWORD = PASSWORD_PRE if ENVIRONMENT == "pre" else PASSWORD_TEST
IMAGE_CAPTCHA = "9"            # 默认填充的图形验证码
SMS_CAPTCHA = "999999"          # 默认填充的短信验证码

# 3. 浏览器核心底层运行配置
DEFAULT_TIMEOUT = 60000         # 网络延迟/操作超时时间限制 (毫秒)
