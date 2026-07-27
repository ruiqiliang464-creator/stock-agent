# cron-job.org 配置指南

## 用 cron-job.org 外部定时触发 GitHub Actions

GitHub Actions 内部 cron 对低活跃仓库非常不可靠（延迟数小时甚至跳过不触发）。
解决方案：用免费的外部定时服务 cron-job.org 每天准时发 API 请求触发 GitHub workflow。

---

## 步骤 1：注册 cron-job.org

1. 打开 https://cron-job.org/en/signup/
2. 填写邮箱和密码注册
3. 登录确认邮箱

---

## 步骤 2：创建定时任务

登录后，点击 **"Create Job"**，按以下表格填写：

### 基本信息

| 配置项 | 值 |
|--------|-----|
| **Title** | `Stock Agent Daily Pipeline` |
| **URL** | `https://api.github.com/repos/ruiqiliang464-creator/stock-agent/actions/workflows/daily-pipeline.yml/dispatches` |

### 请求配置

| 配置项 | 值 |
|--------|-----|
| **Request method** | `POST` |
| **Content-Type** | `application/json` |
| **Body** | `{"ref":"main"}` |

### 自定义 Headers（关键！）

需要添加 **2 个 Header**：

| Header Name | Header Value |
|-------------|-------------|
| `Authorization` | `token <你的GitHub_PAT>` |
| `Accept` | `application/vnd.github+json` |

> ⚠️ 注意 Authorization 格式：前面有 `token ` 这个词，不能省略

### 定时配置

| 配置项 | 值 |
|--------|-----|
| **Schedule** | 选 "Custom" 自定义 |
| **时区** | 选 `Asia/Shanghai` (UTC+8) |
| **时间** | 每天 6:00 AM |
| **cron 表达式** | `0 6 * * *` |

---

## 步骤 3：测试运行

创建完后，点击 **"Execute now"**（立即执行）按钮测试。

预期结果：
- 返回状态码 `204`（GitHub dispatch API 成功的正常响应）
- 打开 https://github.com/ruiqiliang464-creator/stock-agent/actions
- 应该看到一条新的 workflow 运行记录

---

## 步骤 4：确认邮件推送

等 2-3 分钟后：
1. 检查 QQ 邮箱 (3339726915@qq.com) 是否收到邮件
2. 检查 Gmail (ruiqiliang464@gmail.com) 是否收到邮件
3. 检查看板是否更新：https://ruiqiliang464-creator.github.io/stock-agent/dashboard/

---

## 验证日常运行

第二天早上 6:00 后，检查：
1. cron-job.org 的执行日志 — 是否准时触发了请求
2. GitHub Actions — 是否收到了触发并成功运行
3. 两个邮箱 — 是否收到了推送邮件

---

## 常见问题

### Q: GitHub PAT Token 过期怎么办？
GitHub PAT 默认有效期 90 天。过期后：
1. 打开 https://github.com/settings/tokens/new 重新生成（勾选 repo + workflow）
2. 在 cron-job.org 编辑定时任务，更新 Authorization header 中的新 Token

### Q: cron-job.org 本身可靠吗？
cron-job.org 已运营超过 15 年，每天执行数百万次任务，是业界最可靠的免费 cron 服务之一。

### Q: 如果同一天管道已经跑过了怎么办？
代码里有防重复机制：管道检查 `latest.json` 的 `date` 字段，如果今天已经跑过就自动跳过，不会发重复邮件。

### Q: 想改推送时间怎么办？
在 cron-job.org 编辑定时任务，修改 Schedule 时间即可。
