# 配置示例

## 自动定位配置

### 方法1：设置环境变量（推荐）

在系统中设置 `DEFAULT_CITY` 环境变量，指定默认城市：

**Windows:**
```cmd
set DEFAULT_CITY=北京
```

**Linux/macOS:**
```bash
export DEFAULT_CITY="北京"
```

**永久设置（Windows）：**
1. 右键"此电脑" → 属性 → 高级系统设置 → 环境变量
2. 添加用户变量：变量名 `DEFAULT_CITY`，变量值 `北京`

### 方法2：IP自动定位

如果不设置环境变量，系统会自动通过IP定位获取当前位置：

- 使用多个定位服务提高成功率
- 支持国际和国内网络环境
- 定位结果缓存1小时

### 方法3：手动指定城市

在调用工具时直接指定城市名称：
```json
{
  "city": "上海"
}
```

## MCP服务器配置

### Claude Desktop配置

编辑配置文件：
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "weather": {
      "command": "python",
      "args": ["D:\\mcp\\weather-mcp-server\\main.py"],
      "env": {
        "DEFAULT_CITY": "北京"
      }
    }
  }
}
```

### Claude Code CLI配置

```bash
# 添加MCP服务器
claude mcp add weather -- python D:\mcp\weather-mcp-server\main.py

# 带环境变量的配置
claude mcp add weather --env DEFAULT_CITY=北京 -- python D:\mcp\weather-mcp-server\main.py
```

## 使用示例

### 自动定位（城市参数留空）
```
用户：今天天气怎么样？
AI：我来为您查询当前位置的天气。
[调用 get_current_weather(city="")]
```

### 指定城市
```
用户：北京今天天气怎么样？
AI：我来为您查询北京的天气。
[调用 get_current_weather(city="北京")]
```

### 活动建议
```
用户：明天适合爬山吗？
AI：我来根据天气情况给您提供爬山建议。
[调用 get_activity_suggestion(city="", activity="hiking")]
```