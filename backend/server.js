const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');

// 加载环境配置
const envPath = path.join(__dirname, '..', 'config', 'default.env');
if (fs.existsSync(envPath)) {
  const envContent = fs.readFileSync(envPath, 'utf-8');
  envContent.split('\n').forEach(line => {
    const match = line.match(/^([^#=]+)=(.*)$/);
    if (match) {
      const key = match[1].trim();
      const val = match[2].trim();
      if (!process.env[key]) process.env[key] = val;
    }
  });
}

const app = express();
const PORT = process.env.PORT || 3000;

// 中间件
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// 静态前端
app.use(express.static(path.join(__dirname, '..', 'frontend')));

// 初始化数据库后再启动路由和调度
async function startServer() {
  const { initDatabase, prepare, saveDb, transaction } = require('./db');
  await initDatabase();

  // API路由 (传入 prepare 函数)
  const authRoutes = require('./routes/auth')(prepare);
  const dataRoutes = require('./routes/data')(prepare);
  const reportRoutes = require('./routes/reports')(prepare);
  const settingsRoutes = require('./routes/settings')(prepare);

  app.use('/api/auth', authRoutes);
  app.use('/api/data', dataRoutes);
  app.use('/api/reports', reportRoutes);
  app.use('/api/settings', settingsRoutes);

  // SPA fallback
  app.get('*', (req, res) => {
    const indexPath = path.join(__dirname, '..', 'frontend', 'index.html');
    if (fs.existsSync(indexPath)) {
      res.sendFile(indexPath);
    } else {
      res.status(404).send('页面不存在');
    }
  });

  // 启动服务器
  app.listen(PORT, () => {
    console.log(`[StockAgent] 服务器启动: http://localhost:${PORT}`);
  });

  // 内置定时调度 (node-cron)
  const cron = require('node-cron');
  const collectModule = require('./scheduler/collect');
  const processModule = require('./scheduler/process');
  const analyzeModule = require('./scheduler/analyze');
  const reportModule = require('./scheduler/report');

  // 06:00 数据采集
  cron.schedule('0 6 * * *', async () => {
    console.log('[Scheduler] 06:00 - 开始数据采集...');
    try {
      await collectModule.run();
      console.log('[Scheduler] 06:00 - 数据采集完成');
    } catch (e) {
      console.error('[Scheduler] 数据采集失败:', e.message);
    }
  });

  // 07:00 清洗整合
  cron.schedule('0 7 * * *', async () => {
    console.log('[Scheduler] 07:00 - 开始清洗整合...');
    try {
      await processModule.run();
      console.log('[Scheduler] 07:00 - 清洗整合完成');
    } catch (e) {
      console.error('[Scheduler] 清洗整合失败:', e.message);
    }
  });

  // 07:30 分析生成
  cron.schedule('30 7 * * *', async () => {
    console.log('[Scheduler] 07:30 - 开始分析生成...');
    try {
      await analyzeModule.run();
      console.log('[Scheduler] 07:30 - 分析生成完成');
    } catch (e) {
      console.error('[Scheduler] 分析生成失败:', e.message);
    }
  });

  // 08:30 邮件推送
  cron.schedule('30 8 * * *', async () => {
    console.log('[Scheduler] 08:30 - 开始邮件推送...');
    try {
      await reportModule.run();
      console.log('[Scheduler] 08:30 - 邮件推送完成');
    } catch (e) {
      console.error('[Scheduler] 邮件推送失败:', e.message);
    }
  });
}

startServer().catch(e => {
  console.error('[StockAgent] 启动失败:', e);
});

module.exports = app;
