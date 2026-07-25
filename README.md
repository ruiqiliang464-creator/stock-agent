# Stock Agent - 每日市场情报系统

## 简介
股票信息聚合 Agent 应用，自动采集四大市场数据（美股/A股/数字货币/大宗商品），经过清洗整合、趋势分析、风险预警后，生成简洁的 HTML 报告并于每日 8:30 通过 QQ 邮箱推送到用户邮箱。

## 功能特性
- **四大市场覆盖**：美股(Yahoo Finance)、A股(东方财富)、数字货币(CoinGecko/Binance)、大宗商品(金十/Yahoo ETF)
- **用户注册登录**：JWT 认证，支持自定义推送邮箱
- **数据看板**：实时行情展示，涨跌排行，市场概览
- **历史报告**：查看过往每日推送报告
- **自动调度**：WorkBuddy Automation 定时触发 + node-cron 内置调度
- **邮件推送**：QQ 邮箱 SMTP，简洁 HTML 模板，置信度标注

## 定时任务时间表
| 时间 | 任务 |
|------|------|
| 06:00 | 数据采集 (4大市场并行) |
| 07:00 | 清洗整合 (去重/筛选/分类) |
| 07:30 | 分析生成 (趋势/机会/风险) |
| 08:30 | 邮件推送 (QQ邮箱) |

## 快速启动

### 1. 启动服务器
```bash
cd stock-agent
NODE_PATH="node_modules_path" node backend/server.js
```

### 2. 配置 QQ 邮箱
编辑 `config/default.env`：
```
SMTP_USER=你的QQ邮箱@qq.com
SMTP_PASS=你的QQ邮箱授权码
```

获取授权码：登录 QQ邮箱 → 设置 → 账户 → POP3/SMTP服务 → 生成授权码

### 3. 访问网站
浏览器打开 http://localhost:3000

### 4. 注册用户
注册时填写邮箱，该邮箱将接收每日市场情报推送

## 项目结构
```
stock-agent/
├── backend/
│   ├── server.js          # 主服务器 + cron调度
│   ├── db.js              # SQLite数据库(sql.js)
│   ├── routes/            # API路由(auth/data/reports/settings)
│   ├── collectors/        # 数据采集模块(us/cn/crypto/commodity)
│   ├── scheduler/         # 定时调度脚本(collect/process/analyze/report)
│   ├── processor/         # 数据清洗整合
│   ├── analyzer/          # 趋势分析/机会/风险引擎
│   ├── formatter/         # HTML报告生成
│   └── mailer/            # QQ邮箱推送
├── frontend/
│   └── index.html          # 前端SPA(登录/看板/报告/设置)
├── config/
│   └── default.env         # 环境配置
├── templates/              # 邮件模板
├── data/                   # 数据库+中间数据文件
└── package.json
```

## 配色规则
遵循中国股市惯例：
- **涨 = 红色 (#dc2626)** 
- **跌 = 绿色 (#16a34a)**

## 置信度标注
- **高(绿底)**：多信号确认或异常波动显著
- **中(黄底)**：单信号较强支撑
- **低(红底)**：信号较弱仅供参考

## MCP Connector 集成
可通过 WorkBuddy Connector 获取更专业数据：
- `westock-mcp`：腾讯自选股数据
- `tdx-connector`：通达信行情数据
- `tongzhou-fin-research`：同舟金融研究

连接后可在 collectors 中直接使用 MCP 数据源。
