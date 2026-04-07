# Weather MCP Server

基于 [MCP 协议](https://modelcontextprotocol.io) 的天气查询服务，使用 [Open-Meteo](https://open-meteo.com) 免费 API，**无需任何 API Key**。

## 功能

- **智能自动定位**：所有工具的城市参数均可留空，系统会自动通过IP定位获取当前位置
  - 优先使用环境变量 `DEFAULT_CITY`
  - 其次尝试多个IP定位服务（ip-api.com、ipinfo.io、ipapi.co）
  - 定位结果缓存1小时，避免频繁请求
- 工具：`get_current_weather(city)` — 查询任意城市当前天气
- 工具：`get_hourly_forecast(city, hours)` — 查询未来逐小时天气预报
- 工具：`get_weather_alerts(city)` — 查询未来3天气象预警
- **工具：`get_activity_suggestion(city, activity)` — 根据天气提供户外活动建议**
  - 支持：爬山(hiking)、跑步(running)、骑行(cycling)、野餐(picnic)
  - 根据温度、风速、降水概率、天气状况综合评分
  - 给出适宜度评级（EXCELLENT/GOOD/FAIR/POOR/AVOID）和具体建议
- 支持中文/英文城市名
- 支持 **stdio 模式**（本地）和 **SSE 模式**（远程部署）

---

## 安装

```bash
cd D:\mcp
pip install -r requirements.txt
```

---

## 本地运行测试

```bash
# 直接运行（stdio 模式，会等待 MCP 协议输入，Ctrl+C 退出）
python main.py

# SSE 模式本地测试
MCP_MODE=sse python main.py
# Windows:
set MCP_MODE=sse && python main.py
```

---

## 配置 Claude Desktop

编辑 Claude Desktop 配置文件：

- **Windows**：`%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**：`~/Library/Application Support/Claude/claude_desktop_config.json`

添加以下内容：

```json
{
  "mcpServers": {
    "weather": {
      "command": "python",
      "args": ["D:\\mcp\\main.py"]
    }
  }
}
```

保存后**重启 Claude Desktop**，即可在对话中使用天气查询。

---

## 配置 Claude Code（CLI）

```bash
claude mcp add weather -- python D:\mcp\main.py
```

---

## 上传 GitHub

```bash
cd D:\mcp
git init
git add .
git commit -m "feat: weather MCP server"
git remote add origin https://github.com/你的用户名/weather-mcp.git
git push -u origin main
```

---

## 部署到阿里云（SSE 模式）

1. **上传代码**到服务器（`git clone` 或 `scp`）
2. **安装依赖**：
   ```bash
   pip install -r requirements.txt
   ```
3. **启动 SSE 服务**：
   ```bash
   MCP_MODE=sse MCP_PORT=8000 python main.py
   ```
4. **配置 Nginx 反向代理**（可选，用于 HTTPS）：
   ```nginx
   location /sse {
       proxy_pass http://127.0.0.1:8000;
       proxy_buffering off;
       proxy_cache off;
       proxy_set_header Connection '';
       proxy_http_version 1.1;
   }
   location /messages {
       proxy_pass http://127.0.0.1:8000;
   }
   ```
5. **客户端连接**：将 Claude 配置中的 `command` 改为 SSE URL：
   ```json
   {
     "mcpServers": {
       "weather-remote": {
         "url": "http://你的服务器IP:8000/sse"
       }
     }
   }
   ```

---

## 项目结构

```
D:\mcp\
├── main.py          # MCP Server 主程序
├── requirements.txt # 依赖列表
└── README.md        # 本文件
```
