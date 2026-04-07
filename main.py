"""
Weather MCP Server
支持 stdio 模式（本地）和 SSE 模式（远程部署）
使用 Open-Meteo API，无需 API Key

工具：
  - get_current_weather(city)       当前天气
  - get_hourly_forecast(city, hours) 逐小时预报（默认24小时）
  - get_weather_alerts(city)         气象预警（基于极端气象阈值推导）
  - get_activity_suggestion(city, activity) 活动建议（爬山/跑步/骑行/野餐）
"""

import asyncio
import sys
import os
import httpx
from datetime import datetime
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from mcp.server.lowlevel.server import NotificationOptions

# ── WMO 天气代码 ───────────────────────────────────────────────────────────────

WMO_CODES = {
    0: "晴天", 1: "基本晴朗", 2: "局部多云", 3: "阴天",
    45: "雾", 48: "冻雾",
    51: "小毛毛雨", 53: "中毛毛雨", 55: "大毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "小阵雨", 81: "中阵雨", 82: "大阵雨",
    95: "雷暴", 96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹",
}

# ── 地理编码 ───────────────────────────────────────────────────────────────────

def _http_client() -> httpx.AsyncClient:
    """创建 HTTP 客户端，自动使用系统代理（如有）"""
    import urllib.request
    sys_proxies = urllib.request.getproxies()
    proxy = sys_proxies.get("https") or sys_proxies.get("http")
    if proxy:
        transport = httpx.AsyncHTTPTransport(proxy=proxy)
        return httpx.AsyncClient(timeout=15, transport=transport)
    return httpx.AsyncClient(timeout=15)


async def geocode(city: str) -> tuple[float, float, str]:
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city, "count": 1, "language": "zh", "format": "json"}
    async with _http_client() as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    results = data.get("results")
    if not results:
        raise ValueError(f"找不到城市：{city}")
    r = results[0]
    return r["latitude"], r["longitude"], r.get("name", city)

# ── API 请求 ───────────────────────────────────────────────────────────────────

async def fetch_open_meteo(lat: float, lon: float, params: dict) -> dict:
    base = {"latitude": lat, "longitude": lon, "timezone": "auto"}
    base.update(params)
    async with _http_client() as client:
        resp = await client.get("https://api.open-meteo.com/v1/forecast", params=base)
        resp.raise_for_status()
        return resp.json()

# ── 工具实现 ───────────────────────────────────────────────────────────────────

async def tool_current_weather(city: str) -> str:
    lat, lon, name = await geocode(city)
    data = await fetch_open_meteo(lat, lon, {
        "current": [
            "temperature_2m", "relative_humidity_2m",
            "apparent_temperature", "weather_code", "wind_speed_10m",
        ]
    })
    c = data["current"]
    desc = WMO_CODES.get(c.get("weather_code", -1), "未知")
    return (
        f"{name} 当前天气\n"
        f"天气状况：{desc}\n"
        f"温度：{c['temperature_2m']}°C（体感 {c['apparent_temperature']}°C）\n"
        f"湿度：{c['relative_humidity_2m']}%\n"
        f"风速：{c['wind_speed_10m']} km/h"
    )


async def tool_hourly_forecast(city: str, hours: int = 24) -> str:
    hours = max(1, min(hours, 48))  # 限制 1-48 小时
    lat, lon, name = await geocode(city)
    data = await fetch_open_meteo(lat, lon, {
        "hourly": [
            "temperature_2m", "weather_code",
            "precipitation_probability", "wind_speed_10m",
        ],
        "forecast_hours": hours,
    })
    h = data["hourly"]
    lines = [f"{name} 未来 {hours} 小时预报\n"]
    for i in range(len(h["time"])):
        t = h["time"][i][11:]  # 只取时间部分 HH:MM
        desc = WMO_CODES.get(h["weather_code"][i], "未知")
        temp = h["temperature_2m"][i]
        pop = h["precipitation_probability"][i]
        wind = h["wind_speed_10m"][i]
        lines.append(f"{t}  {desc}  {temp}°C  降水概率:{pop}%  风速:{wind}km/h")
    return "\n".join(lines)


# 活动建议评分系统
_ACTIVITY_GUIDELINES = {
    "hiking": {  # 爬山
        "name": "爬山",
        "ideal_temp_range": (15, 25),
        "max_wind": 30,
        "max_precipitation_prob": 20,
        "avoid_weather_codes": [51, 53, 55, 61, 63, 65, 71, 73, 75, 80, 81, 82, 95, 96, 99],  # 雨、雪、雷暴
        "tips": {
            "excellent": "天气绝佳！非常适合爬山，记得带上足够的水和防晒用品。",
            "good": "天气不错，适合爬山。建议穿舒适的运动鞋，注意防晒。",
            "fair": "天气一般，可以爬山但需注意。建议携带防风外套，密切关注天气变化。",
            "poor": "天气不太适合爬山，建议谨慎考虑。如必须前往，请做好防护措施。",
            "avoid": "天气恶劣，强烈建议不要爬山！安全第一，请改期或选择室内活动。"
        }
    },
    "running": {  # 跑步
        "name": "跑步",
        "ideal_temp_range": (10, 22),
        "max_wind": 25,
        "max_precipitation_prob": 30,
        "avoid_weather_codes": [61, 63, 65, 71, 73, 75, 95, 96, 99],  # 中大雨、雪、雷暴
        "tips": {
            "excellent": "完美天气！适合户外跑步，空气质量良好，记得做好热身。",
            "good": "天气适宜跑步，穿着透气运动服，注意补水。",
            "fair": "可以跑步，但建议缩短距离或在健身房进行。",
            "poor": "不太适合户外跑步，建议室内运动。",
            "avoid": "天气恶劣，请避免户外跑步，选择室内运动。"
        }
    },
    "cycling": {  # 骑行
        "name": "骑行",
        "ideal_temp_range": (15, 28),
        "max_wind": 20,
        "max_precipitation_prob": 15,
        "avoid_weather_codes": [51, 53, 55, 61, 63, 65, 71, 73, 75, 80, 81, 82, 95, 96, 99],
        "tips": {
            "excellent": "天气绝佳！非常适合骑行，享受美好户外时光。",
            "good": "天气不错，适合骑行。注意安全，佩戴头盔。",
            "fair": "可以骑行但需谨慎，风力较大时减速慢行。",
            "poor": "天气不太适合骑行，建议改期。",
            "avoid": "天气恶劣，强烈建议不要骑行！"
        }
    },
    "picnic": {  # 野餐
        "name": "野餐",
        "ideal_temp_range": (18, 26),
        "max_wind": 15,
        "max_precipitation_prob": 10,
        "avoid_weather_codes": [45, 48, 51, 53, 55, 61, 63, 65, 71, 73, 75, 80, 81, 82, 95, 96, 99],
        "tips": {
            "excellent": "天气完美！非常适合野餐，带上美食享受户外时光。",
            "good": "天气不错，适合野餐。建议带上遮阳伞。",
            "fair": "天气一般，可以野餐但需准备应对天气变化的物品。",
            "poor": "不太适合野餐，建议选择室内聚餐。",
            "avoid": "天气不适合野餐，请改期安排。"
        }
    },
}

def _calculate_activity_score(weather_data: dict, activity: str) -> tuple[str, str]:
    """计算活动适宜度评分"""
    guidelines = _ACTIVITY_GUIDELINES.get(activity, _ACTIVITY_GUIDELINES["hiking"])

    c = weather_data["current"]
    hourly = weather_data.get("hourly", {})

    # 获取当前天气参数
    temp = c["temperature_2m"]
    weather_code = c["weather_code"]
    wind_speed = c["wind_speed_10m"]

    # 获取未来降水概率（如果可用）
    precip_prob = 0
    if hourly and "precipitation_probability" in hourly:
        # 取未来3小时平均降水概率
        precip_probs = hourly["precipitation_probability"][:3]
        precip_prob = sum(precip_probs) / len(precip_probs) if precip_probs else 0

    # 计算评分
    score = 100
    reasons = []

    # 1. 温度评分
    ideal_min, ideal_max = guidelines["ideal_temp_range"]
    if temp < ideal_min - 5 or temp > ideal_max + 10:
        score -= 40
        reasons.append(f"温度不适宜（当前{temp}°C，理想范围{ideal_min}-{ideal_max}°C）")
    elif temp < ideal_min or temp > ideal_max:
        score -= 20
        reasons.append(f"温度稍偏离理想范围（当前{temp}°C）")

    # 2. 风速评分
    if wind_speed > guidelines["max_wind"] + 10:
        score -= 30
        reasons.append(f"风速过大（{wind_speed} km/h）")
    elif wind_speed > guidelines["max_wind"]:
        score -= 15
        reasons.append(f"风速偏大（{wind_speed} km/h）")

    # 3. 降水概率评分
    if precip_prob > guidelines["max_precipitation_prob"] + 20:
        score -= 35
        reasons.append(f"降水概率很高（{precip_prob:.0f}%）")
    elif precip_prob > guidelines["max_precipitation_prob"]:
        score -= 20
        reasons.append(f"降水概率偏高（{precip_prob:.0f}%）")

    # 4. 天气状况评分
    if weather_code in guidelines["avoid_weather_codes"]:
        score -= 50
        desc = WMO_CODES.get(weather_code, "恶劣天气")
        reasons.append(f"天气状况不佳：{desc}")

    # 确定评级
    if score >= 85:
        rating = "excellent"
    elif score >= 65:
        rating = "good"
    elif score >= 45:
        rating = "fair"
    elif score >= 25:
        rating = "poor"
    else:
        rating = "avoid"

    return rating, guidelines["tips"][rating], reasons

async def tool_activity_suggestion(city: str, activity: str = "hiking") -> str:
    """根据天气提供活动建议"""
    activity = activity.lower().strip()

    # 验证活动类型
    if activity not in _ACTIVITY_GUIDELINES:
        valid_activities = ", ".join(_ACTIVITY_GUIDELINES.keys())
        return f"不支持的活動类型：{activity}\n支持的活动类型：{valid_activities}"

    lat, lon, name = await geocode(city)

    # 获取当前天气和未来3小时预报
    data = await fetch_open_meteo(lat, lon, {
        "current": [
            "temperature_2m", "relative_humidity_2m",
            "apparent_temperature", "weather_code", "wind_speed_10m",
        ],
        "hourly": ["precipitation_probability"],
        "forecast_hours": 3,
    })

    # 计算活动适宜度
    rating, tip, reasons = _calculate_activity_score(data, activity)
    activity_name = _ACTIVITY_GUIDELINES[activity]["name"]

    c = data["current"]
    desc = WMO_CODES.get(c["weather_code"], "未知")

    # 构建返回信息
    lines = [
        f"📍 {name} - {activity_name}建议",
        "",
        f"🌡️ 当前天气：{desc}",
        f"温度：{c['temperature_2m']}°C（体感 {c['apparent_temperature']}°C）",
        f"湿度：{c['relative_humidity_2m']}%",
        f"风速：{c['wind_speed_10m']} km/h",
        "",
        f"✨ 适宜度评级：{rating.upper()}",
        "",
        f"💡 建议：{tip}",
    ]

    if reasons:
        lines.append("")
        lines.append("⚠️ 注意事项：")
        for reason in reasons:
            lines.append(f"  - {reason}")

    return "\n".join(lines)

# 预警阈值
_ALERT_RULES = [
    ("temperature_2m_max", ">", 37,  "高温预警", "最高气温 {val}°C，超过 37°C"),
    ("temperature_2m_min", "<", 0,   "低温预警", "最低气温 {val}°C，低于 0°C"),
    ("wind_speed_10m_max", ">", 60,  "大风预警", "最大风速 {val} km/h，超过 60 km/h"),
    ("wind_speed_10m_max", ">", 40,  "风力提示", "最大风速 {val} km/h，超过 40 km/h"),
    ("precipitation_sum",  ">", 50,  "暴雨预警", "日降水量 {val} mm，超过 50 mm"),
    ("precipitation_sum",  ">", 25,  "大雨提示", "日降水量 {val} mm，超过 25 mm"),
]

async def tool_weather_alerts(city: str) -> str:
    lat, lon, name = await geocode(city)
    data = await fetch_open_meteo(lat, lon, {
        "daily": [
            "weather_code", "temperature_2m_max", "temperature_2m_min",
            "precipitation_sum", "wind_speed_10m_max",
        ],
        "forecast_days": 3,
    })
    d = data["daily"]
    alerts = []
    for i, date in enumerate(d["time"]):
        day_alerts = []
        for field, op, threshold, title, tmpl in _ALERT_RULES:
            val = d[field][i]
            if val is None:
                continue
            triggered = (op == ">" and val > threshold) or (op == "<" and val < threshold)
            if triggered:
                day_alerts.append(f"  [{title}] {tmpl.format(val=val)}")
        if day_alerts:
            desc = WMO_CODES.get(d["weather_code"][i], "未知")
            alerts.append(f"{date} ({desc}):")
            alerts.extend(day_alerts)

    if not alerts:
        return f"{name} 未来3天无气象预警，天气状况正常。"
    return f"{name} 气象预警（未来3天）\n\n" + "\n".join(alerts)

# ── MCP Server ─────────────────────────────────────────────────────────────────

app = Server("weather-mcp")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_current_weather",
            description="查询指定城市的当前天气，包括温度、湿度、风速和天气状况",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，支持中文或英文"}
                },
                "required": ["city"],
            },
        ),
        Tool(
            name="get_hourly_forecast",
            description="查询指定城市未来逐小时天气预报，包括温度、天气状况、降水概率、风速",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，支持中文或英文"},
                    "hours": {"type": "integer", "description": "预报小时数，1-48，默认24", "default": 24},
                },
                "required": ["city"],
            },
        ),
        Tool(
            name="get_weather_alerts",
            description="查询指定城市未来3天气象预警，包括高温、低温、大风、暴雨等极端天气提示",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，支持中文或英文"}
                },
                "required": ["city"],
            },
        ),
        Tool(
            name="get_activity_suggestion",
            description="根据天气条件提供户外活动建议，支持爬山、跑步、骑行、野餐等活动，给出适宜度评级和建议",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，支持中文或英文"},
                    "activity": {"type": "string", "description": "活动类型：hiking(爬山)、running(跑步)、cycling(骑行)、picnic(野餐)", "default": "hiking"},
                },
                "required": ["city"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    city = arguments.get("city", "").strip()
    if not city:
        return [TextContent(type="text", text="错误：请提供城市名称")]
    try:
        if name == "get_current_weather":
            result = await tool_current_weather(city)
        elif name == "get_hourly_forecast":
            hours = int(arguments.get("hours", 24))
            result = await tool_hourly_forecast(city, hours)
        elif name == "get_weather_alerts":
            result = await tool_weather_alerts(city)
        elif name == "get_activity_suggestion":
            activity = arguments.get("activity", "hiking")
            result = await tool_activity_suggestion(city, activity)
        else:
            raise ValueError(f"未知工具：{name}")
    except ValueError as e:
        result = f"错误：{e}"
    except httpx.HTTPError as e:
        result = f"网络请求失败：{e}"
    return [TextContent(type="text", text=result)]

# ── 启动入口 ───────────────────────────────────────────────────────────────────

async def run_stdio():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream, write_stream,
            InitializationOptions(
                server_name="weather-mcp",
                server_version="1.1.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


async def run_sse(host: str = "0.0.0.0", port: int = 8000):
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    import uvicorn

    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await app.run(
                streams[0], streams[1],
                InitializationOptions(
                    server_name="weather-mcp",
                    server_version="1.1.0",
                    capabilities=app.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    starlette_app = Starlette(routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages", app=sse.handle_post_message),
    ])
    config = uvicorn.Config(starlette_app, host=host, port=port)
    server = uvicorn.Server(config)
    print(f"SSE 模式启动：http://{host}:{port}/sse", file=sys.stderr)
    await server.serve()


if __name__ == "__main__":
    mode = os.environ.get("MCP_MODE", "stdio")
    if mode == "sse":
        host = os.environ.get("MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("MCP_PORT", "8000"))
        asyncio.run(run_sse(host, port))
    else:
        asyncio.run(run_stdio())
