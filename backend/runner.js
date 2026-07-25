/**
 * 统一调度入口 — 所有定时任务的执行入口
 * 用法: node backend/runner.js <task>
 *   task: collect | process | analyze | report | all
 *
 * 负责:
 *   1. 加载 config/default.env 环境变量
 *   2. 初始化数据库 (sql.js 异步初始化)
 *   3. 分发到对应的调度模块
 */
const path = require('path');
const fs = require('fs');

// ── 1. 加载环境变量 ──
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

// ── 2. 设置 NODE_PATH 以找到全局安装的模块 ──
const nodeWorkspace = 'C:/Users/Richa/.workbuddy/binaries/node/workspace/node_modules';
if (fs.existsSync(nodeWorkspace) && !process.env.NODE_PATH) {
  process.env.NODE_PATH = nodeWorkspace;
  require('module').Module._initPaths();
}

// ── 3. 主逻辑 ──
async function main() {
  const task = process.argv[2] || 'all';
  const tasks = task === 'all' ? ['collect', 'process', 'analyze', 'report'] : [task];

  // 初始化数据库
  const { initDatabase } = require('./db');
  await initDatabase();
  console.log(`[Runner] 任务开始: ${tasks.join(' → ')}`);

  for (const t of tasks) {
    console.log(`\n[Runner] ─── 执行 ${t} ───`);
    try {
      const mod = require(`./scheduler/${t}`);
      if (typeof mod.run === 'function') {
        await mod.run();
      } else {
        console.error(`[Runner] 模块 ${t} 没有 run 函数`);
      }
    } catch (e) {
      console.error(`[Runner] ${t} 执行失败:`, e.message);
      console.error(e.stack);
    }
  }

  console.log('\n[Runner] 全部完成');
  process.exit(0);
}

main().catch(e => {
  console.error('[Runner] 致命错误:', e);
  process.exit(1);
});
