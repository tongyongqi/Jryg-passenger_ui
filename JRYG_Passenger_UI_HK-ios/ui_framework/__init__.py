"""ui_framework 自动化模块 —— __init__.py
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
#   - JRYG_ios_payment.py   ：银行卡/Alipay HK共用支付入口，由iOSBase继承
#   - JRYG_driver_runtime.py：单/双设备配置解析，不访问司机业务接口
#   - JRYG_driver_ui.py     ：司机UI封装（出车、接单、滑动、账单、同单到账核验）
#   - JRYG_order_flow.py    ：参数化双端订单编排基类，所有cases共用
# App启动遮挡清理及起终点配置统一调用iOSBase公共方法，订单顺序由OrderBase编排。
#
# 按职责归档：
#   - cases/   ：全部真机场景文件，只配置车型和渠道；conftest负责生命周期
#   - tests/   ：离线回归，不与真机订单混跑
#   - runners/ ：主运行器、司机薄入口和WDA准备Shell
#   - tools/   ：设备检查；legacy/仅保留历史接口工具，不供UI流程调用
#   - config/  ：配置文件；docs/保存已有验证记录
# 公共函数只在本包维护，不在运行脚本或场景用例中复制实现。
#
# 约定：
#   - 所有真机操作均通过 WDA/Appium 完成，不依赖坐标以外的隐式行为。
#   - 任何未取得明确证据的场景都不得判为通过。
