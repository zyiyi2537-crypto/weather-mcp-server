#!/usr/bin/env python3
"""
测试所有定位方式
"""

import asyncio
import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import (
    get_default_city,
    get_location_by_gps,
    get_location_by_wifi
)

async def test_location_methods():
    print("=== 测试所有定位方式 ===\n")

    # 测试1：GPS定位
    print("1. 测试GPS定位...")
    try:
        gps_city = await get_location_by_gps()
        if gps_city:
            print(f"   GPS定位成功：{gps_city}")
        else:
            print("   GPS定位失败（未检测到GPS模块或无法获取卫星信号）")
    except Exception as e:
        print(f"   GPS定位异常：{e}")

    # 测试2：WiFi定位
    print("\n2. 测试WiFi定位...")
    try:
        wifi_city = await get_location_by_wifi()
        if wifi_city:
            print(f"   WiFi定位成功：{wifi_city}")
        else:
            print("   WiFi定位失败（未连接WiFi或权限不足）")
    except Exception as e:
        print(f"   WiFi定位异常：{e}")

    # 测试3：完整定位流程
    print("\n3. 测试完整定位流程...")
    try:
        city = await get_default_city()
        if city:
            print(f"   定位成功：{city}")
        else:
            print("   所有定位方式均失败")
    except Exception as e:
        print(f"   定位流程异常：{e}")

    print("\n=== 测试完成 ===")
    print("\n说明：")
    print("- GPS定位：需要GPS硬件模块和卫星信号")
    print("- WiFi定位：需要连接WiFi网络和管理员权限")
    print("- 如果都失败，系统会使用IP定位作为备用方案")

if __name__ == "__main__":
    asyncio.run(test_location_methods())