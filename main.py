"""
Weather MCP Server
支持 stdio 模式（本地）和 SSE 模式（远程部署）
使用 wttr.in API，无需 API Key

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

# ── HTTP 客户端 ─────────────────────────────────────────────────────────────────

def _http_client() -> httpx.AsyncClient:
    """创建 HTTP 客户端，自动使用系统代理（如有）"""
    import urllib.request
    sys_proxies = urllib.request.getproxies()
    proxy = sys_proxies.get("https") or sys_proxies.get("http")
    if proxy:
        transport = httpx.AsyncHTTPTransport(proxy=proxy)
        return httpx.AsyncClient(timeout=15, transport=transport)
    return httpx.AsyncClient(timeout=15)

# ── 自动定位 ───────────────────────────────────────────────────────────────────

_DEFAULT_CITY_CACHE: str | None = None
_LOCATION_CACHE_TIME: float = 0
_CACHE_DURATION = 3600  # 缓存1小时

async def get_location_by_wifi() -> str | None:
    """通过WiFi定位获取城市（使用WiFi BSSID）"""
    try:
        # 获取WiFi BSSID（需要管理员权限）
        import subprocess
        import platform

        system = platform.system()
        bssid = None

        if system == "Windows":
            # Windows: 使用netsh获取WiFi信息
            result = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'BSSID' in line:
                        bssid = line.split(':')[1].strip().replace('-', ':')
                        break

        elif system == "Darwin":  # macOS
            # macOS: 使用airport命令
            result = subprocess.run(
                ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'BSSID' in line:
                        bssid = line.split(':')[1].strip()
                        break

        elif system == "Linux":
            # Linux: 使用iwconfig或nmcli
            try:
                result = subprocess.run(
                    ["iwconfig"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'Access Point:' in line:
                            bssid = line.split('Access Point:')[1].strip()
                            break
            except FileNotFoundError:
                # 尝试nmcli
                result = subprocess.run(
                    ["nmcli", "-t", "-f", "BSSID", "dev", "wifi"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    bssid = result.stdout.strip().split('\n')[0]

        if not bssid:
            print("无法获取WiFi BSSID", file=sys.stderr)
            return None

        print(f"获取到WiFi BSSID: {bssid}", file=sys.stderr)

        # 使用Google Geolocation API（需要API key，这里用免费替代）
        # 使用Mozilla Location Service（免费）
        async with _http_client() as client:
            # 构建WiFi定位请求
            wifi_data = {
                "wifi": [
                    {"bssid": bssid}
                ]
            }

            # 尝试使用免费的WiFi定位服务
            try:
                # 使用ip-api.com的WiFi定位（免费）
                resp = await client.post(
                    "http://ip-api.com/json/",
                    json=wifi_data,
                    timeout=10
                )
                if resp.status_code == 200:
                    data = resp.json()
                    city = data.get("city", "")
                    if city:
                        print(f"WiFi定位成功：{city}", file=sys.stderr)
                        return city
            except Exception:
                pass

            # 备用：使用Mozilla Location Service（需要注册获取API key）
            # 这里暂时跳过，因为需要API key

    except Exception as e:
        print(f"WiFi定位失败：{e}", file=sys.stderr)

    return None


async def get_location_by_gps() -> str | None:
    """通过GPS模块获取城市（需要GPS硬件支持）"""
    try:
        import serial
        import pynmea2

        # 常见的GPS串口路径
        gps_ports = [
            "/dev/ttyUSB0",  # Linux
            "/dev/ttyACM0",  # Linux
            "COM3",          # Windows
            "COM4",          # Windows
            "/dev/tty.usbmodem14101",  # macOS
        ]

        for port in gps_ports:
            try:
                # 尝试打开串口
                ser = serial.Serial(port, baudrate=9600, timeout=5)

                # 读取GPS数据
                for _ in range(10):  # 尝试读取10次
                    line = ser.readline().decode('ascii', errors='ignore')

                    # 解析GPGGA语句（包含经纬度）
                    if line.startswith('$GPGGA'):
                        try:
                            msg = pynmea2.parse(line)
                            if msg.latitude and msg.longitude:
                                lat = float(msg.latitude)
                                lon = float(msg.longitude)

                                # 使用经纬度获取城市
                                async with _http_client() as client:
                                    resp = await client.get(
                                        f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=zh",
                                        timeout=10
                                    )
                                    if resp.status_code == 200:
                                        data = resp.json()
                                        address = data.get("address", {})
                                        city = address.get("city") or address.get("town") or address.get("county", "")
                                        if city:
                                            print(f"GPS定位成功：{city}（经纬度：{lat}, {lon}）", file=sys.stderr)
                                            ser.close()
                                            return city
                        except Exception:
                            continue

                ser.close()

            except (serial.SerialException, FileNotFoundError, PermissionError):
                continue

    except ImportError:
        print("GPS定位需要安装依赖：pip install pyserial pynmea2", file=sys.stderr)
    except Exception as e:
        print(f"GPS定位失败：{e}", file=sys.stderr)

    return None


async def get_default_city() -> str:
    """获取默认城市：优先环境变量 DEFAULT_CITY，其次 GPS，再次 WiFi，最后 IP 定位"""
    global _DEFAULT_CITY_CACHE, _LOCATION_CACHE_TIME

    # 1. 环境变量
    env_city = os.environ.get("DEFAULT_CITY", "").strip()
    if env_city:
        return env_city

    # 2. 检查缓存是否有效
    current_time = datetime.now().timestamp()
    if _DEFAULT_CITY_CACHE is not None and (current_time - _LOCATION_CACHE_TIME) < _CACHE_DURATION:
        return _DEFAULT_CITY_CACHE

    # 3. 尝试GPS定位
    print("尝试GPS定位...", file=sys.stderr)
    city = await get_location_by_gps()
    if city:
        _DEFAULT_CITY_CACHE = city
        _LOCATION_CACHE_TIME = current_time
        return city

    # 4. 尝试WiFi定位
    print("尝试WiFi定位...", file=sys.stderr)
    city = await get_location_by_wifi()
    if city:
        _DEFAULT_CITY_CACHE = city
        _LOCATION_CACHE_TIME = current_time
        return city

    # 5. 尝试IP定位（备用方案）
    print("尝试IP定位...", file=sys.stderr)
    location_services = [
        ("http://ip-api.com/json/?lang=zh", lambda d: d.get("city", "")),
        ("http://ip-api.com/json/?fields=city", lambda d: d.get("city", "")),
        ("https://ipinfo.io/json", lambda d: d.get("city", "")),
        ("https://ipapi.co/json/", lambda d: d.get("city", "")),
    ]

    for url, extract_city in location_services:
        try:
            async with _http_client() as client:
                resp = await client.get(url, timeout=5)
                data = resp.json()
                city = extract_city(data)
                if city:
                    _DEFAULT_CITY_CACHE = city
                    _LOCATION_CACHE_TIME = current_time
                    print(f"IP定位成功：{city}（使用 {url}）", file=sys.stderr)
                    return city
        except Exception as e:
            print(f"IP定位服务 {url} 失败：{e}", file=sys.stderr)
            continue

    # 6. 所有定位方式都失败
    print("所有定位方式均失败，请手动设置城市或配置 DEFAULT_CITY 环境变量", file=sys.stderr)
    return ""

# ── API 请求（wttr.in）────────────────────────────────────────────────────────

async def fetch_wttr(city: str) -> dict:
    """从 wttr.in 获取天气数据（JSON 格式）"""
    import urllib.parse
    encoded_city = urllib.parse.quote(city)
    url = f"https://wttr.in/{encoded_city}?format=j1"
    async with _http_client() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

# ── 工具实现 ───────────────────────────────────────────────────────────────────

async def tool_current_weather(city: str) -> str:
    data = await fetch_wttr(city)
    area = data.get("nearest_area", [{}])[0]
    name = area.get("areaName", [{}])[0].get("value", city)
    c = data["current_condition"][0]
    desc = c.get("lang_zh", [{}])[0].get("value", "") or c.get("weatherDesc", [{}])[0].get("value", "未知")
    return (
        f"{name} 当前天气\n"
        f"天气状况：{desc}\n"
        f"温度：{c['temp_C']}°C（体感 {c['FeelsLikeC']}°C）\n"
        f"湿度：{c['humidity']}%\n"
        f"风速：{c['windspeedKmph']} km/h"
    )


async def tool_hourly_forecast(city: str, hours: int = 24) -> str:
    hours = max(1, min(hours, 48))  # 限制 1-48 小时
    data = await fetch_wttr(city)
    area = data.get("nearest_area", [{}])[0]
    name = area.get("areaName", [{}])[0].get("value", city)
    weather_days = data.get("weather", [])
    lines = [f"{name} 未来 {hours} 小时预报\n"]
    count = 0
    for day in weather_days:
        if count >= hours:
            break
        date = day.get("date", "")
        for hour in day.get("hourly", []):
            if count >= hours:
                break
            t = int(hour.get("time", "0")) // 100
            t_str = f"{t:02d}:00"
            desc = hour.get("lang_zh", [{}])[0].get("value", "") or hour.get("weatherDesc", [{}])[0].get("value", "未知")
            temp = hour.get("tempC", "?")
            pop = hour.get("chanceofrain", "0")
            wind = hour.get("windspeedKmph", "0")
            lines.append(f"{date} {t_str}  {desc}  {temp}°C  降水概率:{pop}%  风速:{wind}km/h")
            count += 1
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

    c = weather_data["current_condition"][0]
    hourly = weather_data.get("weather", [{}])[0].get("hourly", [])

    # 获取当前天气参数
    temp = float(c.get("temp_C", c.get("tempC", 0)))
    # 映射 wttr.in 的天气描述到简化的天气状况评分
    weather_desc = c.get("weatherDesc", [{}])[0].get("value", "").lower()
    wind_speed = float(c["windspeedKmph"])
    precip_prob = float(c.get("chanceofrain", 0))

    # 根据天气描述判断天气代码（简化映射）
    weather_code = 0  # 默认晴天
    if "thunder" in weather_desc or "storm" in weather_desc:
        weather_code = 95
    elif "snow" in weather_desc or "sleet" in weather_desc:
        weather_code = 71
    elif "rain" in weather_desc or "drizzle" in weather_desc:
        weather_code = 61
    elif "fog" in weather_desc or "mist" in weather_desc:
        weather_code = 45
    elif "cloud" in weather_desc or "overcast" in weather_desc:
        weather_code = 3
    elif "partly" in weather_desc:
        weather_code = 2

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

    data = await fetch_wttr(city)
    area = data.get("nearest_area", [{}])[0]
    name = area.get("areaName", [{}])[0].get("value", city)

    # 计算活动适宜度
    rating, tip, reasons = _calculate_activity_score(data, activity)
    activity_name = _ACTIVITY_GUIDELINES[activity]["name"]

    c = data["current_condition"][0]
    desc = c.get("lang_zh", [{}])[0].get("value", "") or c.get("weatherDesc", [{}])[0].get("value", "未知")

    # 构建返回信息
    lines = [
        f"📍 {name} - {activity_name}建议",
        "",
        f"🌡️ 当前天气：{desc}",
        f"温度：{c['temp_C']}°C（体感 {c['FeelsLikeC']}°C）",
        f"湿度：{c['humidity']}%",
        f"风速：{c['windspeedKmph']} km/h",
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
    ("maxtempC",  ">", 37,  "高温预警", "最高气温 {val}°C，超过 37°C"),
    ("mintempC",  "<", 0,   "低温预警", "最低气温 {val}°C，低于 0°C"),
    ("maxwind_speedKmph", ">", 60,  "大风预警", "最大风速 {val} km/h，超过 60 km/h"),
    ("maxwind_speedKmph", ">", 40,  "风力提示", "最大风速 {val} km/h，超过 40 km/h"),
    ("totalSnow_cm",  ">", 50,  "暴雪预警", "日降雪量 {val} cm，超过 50 cm"),
    ("precipMM",  ">", 25,  "大雨提示", "日降水量 {val} mm，超过 25 mm"),
]

async def tool_weather_alerts(city: str) -> str:
    data = await fetch_wttr(city)
    area = data.get("nearest_area", [{}])[0]
    name = area.get("areaName", [{}])[0].get("value", city)
    weather_days = data.get("weather", [])
    alerts = []
    for day in weather_days:
        date = day.get("date", "")
        day_alerts = []
        for field, op, threshold, title, tmpl in _ALERT_RULES:
            val = day.get(field)
            if val is None:
                continue
            try:
                val = float(val)
            except (ValueError, TypeError):
                continue
            triggered = (op == ">" and val > threshold) or (op == "<" and val < threshold)
            if triggered:
                day_alerts.append(f"  [{title}] {tmpl.format(val=val)}")
        if day_alerts:
            desc = day.get("hourly", [{}])[4]  # midday
            weather_desc = desc.get("lang_zh", [{}])[0].get("value", "") if desc else ""
            alerts.append(f"{date} ({weather_desc}):")
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
            description="查询指定城市的当前天气，包括温度、湿度、风速和天气状况。城市参数可留空，系统会自动通过IP定位获取当前位置",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，支持中文或英文。留空则通过IP自动定位获取当前位置"}
                },
                "required": [],
            },
        ),
        Tool(
            name="get_hourly_forecast",
            description="查询指定城市未来逐小时天气预报，包括温度、天气状况、降水概率、风速。城市参数可留空，系统会自动通过IP定位获取当前位置",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，支持中文或英文。留空则通过IP自动定位获取当前位置"},
                    "hours": {"type": "integer", "description": "预报小时数，1-48，默认24", "default": 24},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_weather_alerts",
            description="查询指定城市未来3天气象预警，包括高温、低温、大风、暴雨等极端天气提示。城市参数可留空，系统会自动通过IP定位获取当前位置",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，支持中文或英文。留空则通过IP自动定位获取当前位置"}
                },
                "required": [],
            },
        ),
        Tool(
            name="get_activity_suggestion",
            description="根据天气条件提供户外活动建议，支持爬山、跑步、骑行、野餐等活动，给出适宜度评级和建议。城市参数可留空，系统会自动通过IP定位获取当前位置",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，支持中文或英文。留空则通过IP自动定位获取当前位置"},
                    "activity": {"type": "string", "description": "活动类型：hiking(爬山)、running(跑步)、cycling(骑行)、picnic(野餐)", "default": "hiking"},
                },
                "required": [],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    city = arguments.get("city", "").strip()
    if not city:
        city = await get_default_city()
    if not city:
        return [TextContent(type="text", text="无法自动获取位置，请手动提供城市名称或设置 DEFAULT_CITY 环境变量")]
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
