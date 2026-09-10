"""
JRYG 接口自动化测试 —— 入口
"""
from core.api_framework import ApiTestFramework

if __name__ == "__main__":
    framework = ApiTestFramework("config")
    framework.run()
