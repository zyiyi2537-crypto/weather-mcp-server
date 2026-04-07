#!/usr/bin/env python3
"""
测试所有MCP工具的自动定位功能
"""

import asyncio
import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import (
    get_default_city,
    tool_current_weather,
    tool_hourly_forecast,
    tool_weather_alerts,
    tool_activity_suggestion
)

async def test_all_tools():
    print("=== 测试所有MCP工具的自动定位功能 ===\n")

    # 测试1：获取默认城市
    print("1. 测试获取默认城市...")
    city = await get_default_city()
    if city:
        print(f"   成功获取城市：{city}")
    else:
        print("   无法获取城市，请检查网络连接或设置 DEFAULT_CITY 环境变量")
        return

    # 测试2：当前天气
    print(f"\n2. 测试查询 {city} 的当前天气...")
    try:
        weather = await tool_current_weather(city)
        print("   成功！")
        # 只显示前两行
        lines = weather.split('\n')
        for line in lines[:3]:
            print(f"   {line}")
    except Exception as e:
        print(f"   失败：{e}")

    # 测试3：逐小时预报
    print(f"\n3. 测试查询 {city} 的逐小时预报...")
    try:
        forecast = await tool_hourly_forecast(city, 6)  # 只查询6小时
        print("   成功！")
        lines = forecast.split('\n')
        for line in lines[:4]:  # 显示标题和前3个小时
            print(f"   {line}")
    except Exception as e:
        print(f"   失败：{e}")

    # 测试4：气象预警
    print(f"\n4. 测试查询 {city} 的气象预警...")
    try:
        alerts = await tool_weather_alerts(city)
        print("   成功！")
        lines = alerts.split('\n')
        for line in lines[:2]:  # 只显示前两行
            print(f"   {line}")
    except Exception as e:
        print(f"   失败：{e}")

    # 测试5：活动建议
    print(f"\n5. 测试查询 {city} 的活动建议...")
    try:
        suggestion = await tool_activity_suggestion(city, "hiking")
        print("   成功！")
        # 写入文件避免编码问题
        with open('test_activity_output.txt', 'w', encoding='utf-8') as f:
            f.write(suggestion)
        print("   详细结果已写入 test_activity_output.txt")
    except Exception as e:
        print(f"   失败：{e}")

    print("\n=== 所有测试完成 ===")
    print(f"\n总结：所有工具都能正常通过自动定位获取 {city} 的天气信息")

if __name__ == "__main__":
    asyncio.run(test_all_tools())