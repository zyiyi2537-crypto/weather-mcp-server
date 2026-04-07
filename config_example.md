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

### 方法2：GPS定位（最准确）

**要求：**
- 需要GPS硬件模块（USB GPS接收器、树莓派GPS帽等）
- 需要安装额外依赖：`pip install pyserial pynmea2`

**支持的GPS模块：**
- USB GPS接收器
- 树莓派GPS扩展板
- Arduino GPS模块
- 手机GPS（通过串口连接）

**使用方式：**
1. 连接GPS模块到电脑
2. 确保GPS模块已获取到卫星信号（通常需要室外环境）
3. 系统会自动检测GPS端口并读取位置

**精度：** 5-10米（取决于GPS模块和卫星信号）

### 方法3：WiFi定位

**要求：**
- 需要连接到WiFi网络
- 需要管理员/root权限（用于读取WiFi BSSID）

**工作原理：**
1. 获取当前连接的WiFi BSSID（MAC地址）
2. 查询WiFi位置数据库获取经纬度
3. 将经纬度转换为城市名称

**精度：** 20-50米（取决于WiFi接入点密度）

**注意：**
- 需要网络连接
- 某些系统可能需要管理员权限
- 定位精度受周围WiFi接入点数量影响

### 方法4：IP自动定位（备用方案）

如果不设置环境变量，且GPS和WiFi定位都失败，系统会使用IP定位：

- 使用多个定位服务提高成功率
- 支持国际和国内网络环境
- 定位结果缓存1小时

**精度：** 城市级（可能不准确，特别是使用移动网络或代理时）

### 方法5：手动指定城市

在调用工具时直接指定城市名称：
```json
{
  "city": "上海"
}
```

## 定位优先级

系统按以下顺序尝试定位：
1. 环境变量 `DEFAULT_CITY`（最优先）
2. GPS定位（最准确）
3. WiFi定位（较准确）
4. IP定位（备用方案）

任一方式成功后，结果会缓存1小时，避免重复定位。

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