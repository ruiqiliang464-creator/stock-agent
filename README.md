# Stock Agent - 每日市场情报系统（混合方案）

## 简介
股票信息聚合 Agent 应用，自动采集四大市场数据（美股/A股/数字货币/大宗商品），经过清洗整合、趋势分析、风险预警后，生成简洁的 HTML 报告并通过 QQ 邮箱推送到订阅者邮箱。

**混合方案**：GitHub Actions 执行定时管道 + 静态看板在线查看。

## 架构

| 组件 | 方式 | 说明 |
|------|------|------|
| 定时调度 | GitHub Actions | 每天 6:00 AM CST 自动执行，无需本地电脑在线 |
| 数据管道 | `runner-github.js` | 无数据库依赖，纯 JSON 文件驱动 |
| 邮件推送 | `nodemailer` + QQ SMTP | 读 `subscribers.json` 发送 |
| 数据看板 | 静态 HTML | 暗色主题，从 `latest.json` 拉取数据 |

## 定时任务（GitHub Actions）
| 时间 (CST) | 任务 |
|------------|------|
| 06:00 | 全流程：采集→清洗→分析→格式化→邮件推送→提交数据到仓库 |

**与旧方案的区别**：旧方案需要 4 个分散时间点、依赖本地电脑在线。新方案一次性跑完所有步骤，由 GitHub 全球基础设施保障可靠性。

## 快速部署

### 1. 创建 GitHub 仓库
1. 登录 GitHub，创建新仓库 `stock-agent`（建议 Public）
2. 复制仓库 URL

### 2. 推送代码
```bash
cd stock-agent
git remote add origin https://github.com/<你的用户名>/stock-agent.git
git push -u origin main
```

### 3. 配置 GitHub Secrets
进入仓库 Settings → Secrets and variables → Actions，添加：
- `SMTP_USER` = `3339726915@qq.com`
- `SMTP_PASS` = `你的QQ邮箱授权码`

### 4. 手动测试
进入 Actions 页面 → 选择 `Daily Market Pipeline` → `Run workflow`

### 5. 添加新订阅者
编辑 `data/subscribers.json`，添加邮箱：
```json
{
  "subscribers": [
    { "email": "新用户@example.com", "pushEmail": "新用户@example.com", "enabled": true, "name": "新用户" }
  ]
}
```
提交并推送到 GitHub。

### 6. 看板部署
看板是纯静态页面（`dashboard/index.html`），可部署到：
- CloudStudio（推荐）
- GitHub Pages
- Vercel / Netlify
- 本地文件直接打开（需更新 `DATA_SOURCE` 路径）

部署前需修改 `dashboard/index.html` 中的 `DATA_SOURCE` URL：
```javascript
const DATA_SOURCE = 'https://raw.githubusercontent.com/<你的用户名>/stock-agent/main/data/latest.json';
```

## 项目结构
```
stock-agent/
├── .github/workflows/
│   └── daily-pipeline.yml    # GitHub Actions 定时管道
├── backend/
│   ├── runner-github.js      # 管道入口（无数据库依赖）
│   ├── collectors/           # 数据采集模块
│   ├── formatter/report.js   # HTML报告生成
│   └── scheduler/            # 旧版调度模块（本地用）
│   ├── server.js             # 旧版Web服务器（本地用）
│   └── db.js                 # 旧版数据库（本地用）
│   └── routes/               # 旧版API路由（本地用）
│   └── mailer/               # 旧版邮件推送（本地用）
├── dashboard/
│   ├── index.html            # 静态看板（在线）
│   └── data/latest.json      # 看板数据
├── data/
│   ├── subscribers.json      # 订阅者列表
│   ├── latest.json           # 管道输出数据
│   ├── raw_*.json            # 采集原始数据
│   ├── processed_*.json      # 清洗整合数据
│   └── analysis_*.json       # 分析结果数据
├── config/
│   └── default.env           # 环境配置
├── frontend/
│   └── index.html            # 旧版前端（本地用）
└── package.json
```

## 配色规则
遵循中国股市惯例：涨 = 红色 / 跌 = 绿色

## 置信度标注
- **高**：多信号确认或异常波动显著
- **中**：单信号较强支撑
- **低**：信号较弱仅供参考

## 新旧方案切换
- **混合方案**（推荐）：GitHub Actions 自动执行，无需电脑在线
- **本地方案**（备用）：手动启动 `node backend/server.js`，使用数据库+注册登录系统
