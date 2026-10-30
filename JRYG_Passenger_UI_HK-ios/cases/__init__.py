"""香港乘客端真机订单用例统一目录，只定义场景参数及pytest标记。

所有车型/渠道场景继承ui_framework.JRYG_order_flow.TestOrderBase；启动、地址和
付款共用iOSBase封装。公共实现不放在cases，离线回归统一放在tests。
"""
