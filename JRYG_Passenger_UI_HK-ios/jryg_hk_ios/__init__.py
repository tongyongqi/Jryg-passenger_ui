"""jryg_hk_ios 自动化模块 —— __init__.py
==============================================================================
"""

# JRYG HK UI Automation Package
# 港版阳光出行 iOS UI 自动化测试包
#
# 本包按职责拆分为若干模块：
#   - JRYG_config.py        ：目录与全局配置（YAML）加载
#   - JRYG_dir_init.py      ：运行前初始化所需目录
#   - JRYG_logger.py        ：统一日志记录器
#   - JRYG_connect_device.py：Appium / WDA 真机连接
#   - JRYG_page_monitor.py  ：页面树读取与页面状态识别
#   - JRYG_ios_base.py      ：UI 操作基础类（打开、登录、下单通用能力）
#   - JRYG_order_api.py     ：测试环境订单接口通道
#   - JRYG_order_guard.py   ：订单硬校验（目标司机、完成终态）
#   - JRYG_verified_order_flow.py：下单流程编排
#
# 约定：
#   - 所有真机操作均通过 WDA/Appium 完成，不依赖坐标以外的隐式行为。
#   - 任何未取得明确证据的场景都不得判为通过。
