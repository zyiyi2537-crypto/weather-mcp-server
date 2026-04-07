#!/usr/bin/env python3
"""
测试自动定位功能
"""

import asyncio
import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import get_default_city, tool_current_weather

async def test_auto_location():
    print("=== 测试自动定位功能 ===\n")

    # 测试1：获取默认城市
    print("1. 测试获取默认城市...")
    city = await get_default_city()
    if city:
        print(f"   成功获取城市：{city}")
    else:
        print("   无法获取城市，请检查网络连接或设置 DEFAULT_CITY 环境变量")
        return

    # 测试2：使用自动定位的城市查询天气
    print(f"\n2. 测试查询 {city} 的天气...")
    try:
        weather = await tool_current_weather(city)
        print("   天气查询成功：")
        print("   " + weather.replace("\n", "\n   "))
    except Exception as e:
        print(f"   天气查询失败：{e}")

    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    asyncio.run(test_auto_location())