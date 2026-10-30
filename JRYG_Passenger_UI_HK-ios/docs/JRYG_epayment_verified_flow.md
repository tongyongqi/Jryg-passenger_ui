# 港版 iOS 電子支付全 UI：已走通流程与代码对应记录

记录日期：2026-10-30。适用场景：打錶的士（meter）＋電子支付（epayment）。

本记录根据真机实际走通步骤整理，不调用司机业务 API、不读取 token、不模拟 Socket 定位。WDA 是设备 UI 自动化服务，不是订单业务接口。其他支付场景可以复用基类，但不因此视为已完成本次同等真机验证。

## 一、固定执行顺序与对应方法

主入口：`cases/JRYG_test_ios_meter_epayment_order.py::TestMeterEpayment::test_order_flow`。
主编排：`ui_framework/JRYG_order_flow.py::TestOrderBase.test_order_flow`。

目录归档后，本文路径均相对 `JRYG_Passenger_UI_HK-ios/` 项目根。真机场景集中在 `cases/`，公共乘客函数入口为 `ui_framework/JRYG_ios_ui_base.py`，公共支付在 `JRYG_ios_payment.py`，司机状态机在 `ui_framework/JRYG_driver_ui.py`。主运行入口移至 `runners/JRYG_run_main_ios.py` 和 `runners/JRYG_run_hk_ios.sh`，设备检查移至 `tools/JRYG_setup_driver.py`。归档不改变下方历史真机验证结果。

| 顺序 | 真机实际操作 | 页面验证与停止规则 | 对应代码方法 |
| --- | --- | --- | --- |
| 1 | 打开已登录司机 App；离线时点击出车 | 进入「接單中」或新订单页；已有进行中/未支付订单停止，不自动清理 | `TestOrderBase._driver_ui_go_online` → `DriverUIFlow.ensure_online` |
| 2 | 切乘客 App，处理遗留订单及登录页面 | 不以司机 token 为前置；按原 UI 清理逻辑处理 | `TestOrderBase._ui_cleanup_ongoing_order` |
| 3 | 设置北角地铁站为起点、香港大学为终点 | 地址选择完成，进入车型页 | `iOSBase._ios_launch_setup_and_addresses`、`iOSBase._ios_search_address` |
| 4 | 选择「打錶的士」，打开「可選服務」，选「電子支付」，点击「確認選擇」 | 所选车型与支付方式可见 | `TestOrderBase._ios_select_car_type`、`iOSBase._ios_select_payment` |
| 5 | 点击「確認呼叫」；如出现乘客登录，则 UI 登录后重选路线/支付再下单 | 呼叫提交成功不等于司机接单成功，进入下一阶段才验证接单 | `TestOrderBase._click_call_and_check_login_then_retry`、`iOSBase._ios_wait_order_success` |
| 6 | 切回司机 App，等待新订单；显示接单卡片则点击/滑动接单；App 指派已进入行程则不重复接单 | 进入 `departure` 或 `pickup`；没有真实派单则超时失败 | `TestOrderBase._driver_ui_grab_and_flow` → `DriverUIFlow.run` |
| 7 | 如司机页面存在待确认「已出發」按钮/滑块，则操作；已在前往上车点则不重复确认 | 根据可操作控件判阶段，不把历史「已出發」文本当按钮 | `detect_phase`、`DriverUIFlow.act` |
| 8 | 滑动「到達上車地點」 | 必须进入等待乘客上车页；不直接跳到开始/结束 | `DriverUIFlow.run` 的 `pickup` 分支 → `act` → `wait_for` |
| 9 | 滑动「已接載乘客」 | 必须进入送乘客页；若要求尾号，使用显式四位测试配置，不猜测 | `DriverUIFlow.run` 的 `onboard` 分支、`enter_tail` |
| 10 | 滑动「到達目的地」 | 必须进入「確認賬單」；仍为同阶段且无系统弹窗时最多重滑一次，不模拟定位、不绕过 App 校验 | `DriverUIFlow.run` 的 `destination` 分支、`slider_points`、`wait_for` |
| 11 | 输入车费 5 HKD，再输入附加费 0 HKD，收起键盘 | 分别读取两个输入框数值确认一致，输入失败禁止提交 | `DriverUIFlow.submit_bill` → `fill` → `dismiss_keyboard` → `field` |
| 12 | 滑动「確認收款」提交账单 | 进入「已完成｜未支付」，读取并保存本次唯一订单号；在线支付此时不视为已支付 | `DriverUIFlow.submit_bill`、`DriverUIFlow.run`、`read_order_no` |
| 13 | 切乘客 App，等待「行程結束」及「確認支付5HKD」 | 确认按钮金额必须等于司机提交的车费＋附加费；缺页或金额不一致立即失败 | `TestOrderBase._ios_wait_current_payment` |
| 14 | 选择「信用卡或扣帳卡」，点击确认支付；依次填写卡号、月/年、CVV、持卡人，点击「請支付」 | 任一必填字段未填写就停止；卡号/CVV/持卡人值不写入步骤日志 | `TestOrderBase._ios_complete_payment` → `iOSBase._ios_fill_bank_card_form` |
| 15 | 3DS 页面聚焦 OTP，退格清空旧输入，输入测试验证码，点击一次「Verify & Proceed」 | WebView 按钮用元素 UUID 点击；聚焦/清空/输入失败或验证失败/超时就停止。弹层退出只表示此步骤结束，不表示订单已到账 | `iOSBase._ios_handle_otp_page`、`_ios_click_element_by_label` |
| 16 | 处理返回 App 弹窗（如出现），返回乘客首页 | 不重复点击确认支付或再次提交卡表单 | `iOSBase._ios_handle_otp_page`、`TestOrderBase._ios_back_to_home` |
| 17 | 切司机完成页。如果仍「未支付」，点击「返回首頁」，等待「收入到賬」，打开「查看詳情」 | 真实「查看詳情」label 可能带尾空格；详情加载时短暂空白必须等待；不重新收款或提交账单 | `DriverUIFlow.wait_completed` |
| 18 | 司机同订单详情显示「已完成｜已支付」 | 必须同时满足完成、支付、订单号与步骤12一致。其他订单的到账通知不可代替验证；最终停留司机详情，不自动收车 | `DriverUIFlow.wait_completed`、`read_order_no`、`detect_phase` |

## 二、固化的逻辑与顺序约束

- 所有行程状态均使用司机 UI 控件，不再包含 `grab`、`serviceChange`、`confirmBill`、`tripDetail` 等业务接口调用。
- 订单用例默认 `HK_DRIVER_UI_STOP_AFTER=submitted`，含义是司机账单提交后暂停司机操作，让乘客先支付，再核验司机详情；不是跳过最终验证。
- `HK_DRIVER_UI_STOP_AFTER=accepted` 仅用于下单/接单调试。该模式不走行程、账单、支付，不可用其通过结果宣称完整闭环通过。
- 滑块指针从箭头中心拖到轨道右侧内缘。旧终点额外减半个滑块宽度，真机偶尔达不到有效阈值，已修正。
- 对出发、到达、接载、结束分支，第一次操作超时后重新读取真实页面。仅仍为原阶段、没有系统 Alert 时最多重试一次。接单卡片和账单提交不自动重提。
- 下单成功、卡表单已提交、OTP 页面退出、乘客回首页，均不是最终支付成功的充分条件。
- 最终成功由司机同订单详情「已完成＋已支付」决定。司机旧完成页可能不自动刷新，必须按上述首页到账详情顺序重新打开。
- 司机账单总额与司机到账净收入可能不同：已验证样例为乘客付款 5 HKD、司机净收入 4.5 HKD，不能把司机净收入硬断言等于乘客付款金额。
- 状态等待、派单等待、支付详情等待分开限时；服务端不派单/自动取消时明确失败，不从历史订单取成功，不无限重试或重新下单。
- 新一次执行如停留已支付详情，可返回司机首页再出车。此详情页左上返回箭头在真机未暴露 accessibility；只有已完成已支付且有唯一订单号时允许使用截图验证的比例坐标返回。

## 三、配置与运行

配置：`config/JRYG_settings.yaml`。

- `driver.device_mode=auto`：无独立 WDA 时同设备顺序切换；双设备使用真实独立 `driver.wda_url` 或 `HK_DRIVER_WDA_URL`。
- `driver.fare="5"`、`driver.surcharge="0"`；环境变量 `HK_ORDER_AMOUNT`、`HK_OTHER_AMOUNT` 可覆盖。
- 需要尾号时设置 `driver.passenger_tail` 或 `HK_DRIVER_PASSENGER_TAIL`。
- `order_validation.state_timeout=30`、`dispatch_timeout=90`、`completion_timeout=90`、`total_timeout=900` 分别用于单步、派单、到账及司机段总时限。
- 前置：真机解锁、WDA证书已信任且服务可读页面、司机App已经登录、App定位与派单连接可用、支付测试服务可用。

在工作区根目录执行完整电子支付用例：

```bash
cd JRYG_Passenger_UI_HK-ios
HK_DRIVER_UI_STOP_AFTER=submitted HK_ORDER_AMOUNT=5 HK_OTHER_AMOUNT=0 ../.venv/bin/python -m pytest -c pytest.ini cases/JRYG_test_ios_meter_epayment_order.py::TestMeterEpayment::test_order_flow -v --tb=short --html=report/JRYG_epayment_full.html --self-contained-html
```

执行离线顺序及失败分支回归：

```bash
cd JRYG_Passenger_UI_HK-ios
../.venv/bin/python -m pytest -c pytest.ini tests/test_epayment_verified_flow.py tests/test_driver_readiness.py tests/test_driver_hybrid.py tests/test_driver_runtime.py tests/test_driver_ui_input.py -q -o addopts=''
```

## 四、真实验证记录（区分通过与失败）

| 验证 | 真实结果 | 证据 |
| --- | --- | --- |
| 2026-10-30 17:00，出车→乘客下单→司机接单 | 仅接单调试 1 项通过；司机停在「到達上車地點」 | `report/JRYG_epayment_ui_accept_20261030_170020.html` |
| 原订单 `26A4J04WECNY`，后续状态→5+0账单→乘客支付→司机详情 | 已完成且已支付；初版结束首滑未生效、静态支付页未刷新，现场有限重滑和首页详情刷新后确认通过 | `logs/epayment-current-5hkd.log`，`report/driver_ui/` 中最终详情现场；该日志包含旧核验超时，不能将整条旧命令记作通过 |
| 17:28完整回归，订单 `26A6P1KWECNY` | 下单/接单成功，但到达滑块首滑未生效，首次pytest失败；修正滑块终点后用代码续跑完成5+0账单及付款，同订单已完成且已支付 | `report/JRYG_epayment_verified_full_20261030_172848.html`（失败报告），`logs/epayment-verified-driver-resume.log`、`logs/epayment-verified-payment-resume.log`（续跑通过） |
| 17:38从头回归（历史失败） | 乘客呼叫成功，但司机App未出现派单。该次pytest失败，随后乘客页面确认「呼叫超時，已自動取消訂單」。没有推进司机行程或支付，没有继续重下单 | `report/JRYG_epayment_verified_final_20261030_173821.html`、`logs/epayment-verified-final-run.log` |
| 最终离线回归 | 125 项通过；保留环境原有 urllib3/LibreSSL 警告 | 上述离线命令；覆盖真实顺序、金额校验、有限重试、OTP失败停止、同订单刷新、无派单限时停止 |
| 18:01—18:06最新完整真机回归，订单 `26A6P22WECNY` | 单设备顺序切换全UI从头执行，1项通过，耗时301.11秒。司机出车→乘客下单→司机接单及状态→5+0账单→乘客银行卡/OTP支付→司机返回首页、查看到账详情，确认同订单已完成且已支付；未人工续跑、未调用司机业务接口、未自动收车。仅环境原有1项LibreSSL警告 | `report/JRYG_epayment_real_20261030_180133.html`、`logs/epayment_real_20261030_180133.log`、`report/driver_ui/1793354794885355000_completed_paid.png`及同名XML |

代码已按实际通过步骤固化，125项离线回归通过；最新18:01完整真机pytest从头通过，订单详情确认本次订单已完成且已支付。保留之前失败与修复记录，不将历史失败改写为成功。真实派单、网络、定位与支付服务仍是外部前置，不能保证永不失败；不得修改断言掩盖环境问题。

## 五、日志与关键实现文件

- `ui_framework/JRYG_driver_ui.py`：司机页面状态机、真实滑块坐标、账单字段核对、订单号采集与付款后的同订单详情刷新；`runners/JRYG_run_driver_flow.py` 仅委托此公共模块。
- `ui_framework/JRYG_order_flow.py`：先司机出车→乘客下单→司机账单→乘客支付→司机详情核验的唯一主编排。
- `ui_framework/JRYG_ios_ui_base.py`：地址/车型/支付通用UI，卡表单字段顺序、有限UUID元素遍历、一次OTP清空输入验证。
- `cases/JRYG_test_ios_meter_epayment_order.py`：指定本次已验证的 `meter` 与 `epayment` 参数。
- `tests/test_driver_readiness.py`：主流程顺序与失败停止。
- `tests/test_driver_hybrid.py`：司机滑块/账单/订单号/到账详情刷新、派单等待。
- `tests/test_epayment_verified_flow.py`：乘客金额、卡表单输入顺序、OTP输入与异常停止。
- `logs/JRYG_run.log`：乘客与司机UI步骤统一日志；`report/driver_ui/` 保存司机关键截图和XML，`screenshots/` 保存乘客截图。截图及历史日志可能含测试账号信息，仅用于本地验证，不对外公开。
