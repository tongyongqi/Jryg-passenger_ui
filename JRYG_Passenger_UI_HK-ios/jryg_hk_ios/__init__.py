"""jryg_hk_ios 自动化模块 —— __init__.py
==============================================================================
港版阳光出行 iOS 乘客端 UI 自动化测试包。

本包按职责拆分为若干模块，各模块之间通过显式导入协作，
不依赖隐式副作用（目录初始化除外）。
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
#   - JRYG_ios_ui_base.py   ：UI 操作基础类（设备连接、地址搜索、车型选择、支付方式选择等）
#   - JRYG_ios_ui_elements.py：UI 元素定位常量（XPath、关键词、坐标）
#
# 用例体系：
#   - cases/JRYG_test_ios_order_base.py：参数化下单基类（车型×支付方式组合）
#   - cases/JRYG_test_ios_meter_*.py   ：打錶的士用例（cash / epayment / alipay）
#   - cases/JRYG_test_ios_charter_*.py ：包車價的士用例（alipay / bankcard / octopus）
#   - cases/conftest.py               ：pytest 夹具（WDA 超时限制、失败现场保存）
#   - JRYG_run_main_ios.py             ：主运行入口
#
# 约定：
#   - 所有真机操作均通过 WDA/Appium 完成，不依赖坐标以外的隐式行为。
#   - 任何未取得明确证据的场景都不得判为通过。
