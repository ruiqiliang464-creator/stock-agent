# Vercel Cron Jobs 配置指南

## 方案说明

用 Vercel Cron Jobs（免费）每天定时触发 GitHub Actions pipeline，
替代不可靠的 GitHub 内部 cron 和被墙的 cron-job.org。

**链路**：Vercel Cron → `/api/trigger` → GitHub Actions dispatch API → 管道运行 → 邮件推送

---

## 步骤 1：注册 Vercel

1. 打开 https://vercel.com/signup
2. 用 **GitHub 账号**登录（最方便，一键注册）
3. 注册完成后进入 Dashboard

---

## 步骤 2：导入项目

1. 在 Vercel Dashboard 点击 **"Add New..." → "Project"**
2. 选择 **"Import Git Repository"**
3. 找到你的 `stock-agent` 仓库，点击 **"Import"**
4. 配置页面：
   - **Framework Preset**: 选 `Other`（因为这不是标准框架项目）
   - **Root Directory**: 保持默认（不用改）
   - **Build Command**: 不填（跳过）
   - **Output Directory**: 不填（跳过）
5. 点 **"Environment Variables"** 展开，添加 1 个变量：

| Key | Value |
|-----|-------|
| `GITHUB_TOKEN` | `<你的GitHub_PAT>`（格式如 ghp_xxxx，勾选 repo+workflow 权限） |

6. 点击 **"Deploy"** 按钮

---

## 步骤 3：确认 Cron Job 已配置

部署完成后：
1. 进入项目 **Settings → Cron Jobs**
2. 应该能看到 1 条 cron：
   - Path: `/api/trigger`
   - Schedule: `0 22 * * *`（UTC 22:00 = 北京时间 6:00 AM）

如果看不到，手动确认 `vercel.json` 已正确部署。

---

## 步骤 4：手动测试

在浏览器打开你的 Vercel 项目 URL：
```
https://你的项目名.vercel.app/api/trigger
```

预期返回：
```json
{"success": true, "message": "Pipeline triggered successfully", "timestamp": "..."}
```

同时打开 https://github.com/ruiqiliang464-creator/stock-agent/actions
应该看到新的 workflow 运行记录出现。

---

## 步骤 5：确认邮件

等 2-3 分钟后：
1. 检查 QQ 邮箱 (3339726915@qq.com)
2. 检查 Gmail (ruiqiliang464@gmail.com)
3. 检查看板：https://ruiqiliang464-creator.github.io/stock-agent/dashboard/

---

## 重要说明

### Vercel Cron Hobby 限制
- 免费账号支持 **2 个 cron jobs**
- 每个每天触发 1 次（在 1 小时时间窗口内，不精确到分钟）
- 对于我们每天 1 次的需求完全够用

### GitHub Token 安全
- Token 存在 Vercel 的 **Environment Variables** 中，不会出现在代码或日志里
- Token 90 天过期，到期需重新生成并更新 Vercel 环境变量

### 为什么这个方案可靠
- Vercel 在中国可以正常访问
- Vercel Cron Jobs 比 GitHub Actions 自带 cron 更稳定
- 即使 Vercel Cron 偶尔延迟，GitHub 内部的 1 个备用 cron 还能兜底
- 管道有防重复机制，双重触发不会发重复邮件

### 如果 Vercel 项目 URL 是什么？
部署完成后，Vercel 会分配一个域名，格式为 `stock-agent-xxx.vercel.app`。
你也可以在 Settings → Domains 中自定义域名。
