/**
 * 独立运行数据采集脚本的入口
 * 用法: node backend/run-collect.js
 */
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

async function main() {
  const { initDatabase } = require('./db');
  await initDatabase();

  const collectModule = require('./scheduler/collect');
  const result = await collectModule.run();

  console.log('\n[Run-Collect] 采集完成，共获取 ' + (result ? result.length : 0) + ' 条数据');
  process.exit(0);
}

main().catch(e => {
  console.error('[Run-Collect] 执行失败:', e);
  process.exit(1);
});
