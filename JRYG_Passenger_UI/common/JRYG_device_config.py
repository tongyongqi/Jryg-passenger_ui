"""
Android 真机 UI 自动化配置文件（已迁入 JRYG_Passenger_UI 项目结构）
"""

# ========== 设备信息 ==========
DEVICE_UDID = "10AE6U20A7001H5"      # 设备 UDID
DEVICE_NAME = "一叶随风"             # 设备名称
PLATFORM_VERSION = "15"              # Android 系统版本

# ========== App 配置 ==========
APP_PACKAGE = "com.jryg.client"       # 被测应用包名
APP_ACTIVITY = "com.jryg.client.activity.loading.YGALoadingActivity"  # 启动 Activity

APP_PATH = ""                         # apk 路径

# ========== Appium Server ==========
APPIUM_HOST = "127.0.0.1"
APPIUM_PORT = 4723
SYSTEM_PORT = 8201                    # 每台设备唯一的 systemPort
