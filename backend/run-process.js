/**
 * 独立运行清洗整合脚本的入口
 * 用法: node backend/run-process.js
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

  const processModule = require('./scheduler/process');
  const result = await processModule.run();

  if (result) {
    console.log('\n===== 清洗整合结果摘要 =====');
    console.log(`日期: ${result.date}`);
    console.log(`唯一记录数: ${result.totalRecords}`);
    console.log(`显著变动记录数: ${result.significantRecords}`);
    console.log('\n--- 各市场概况 ---');
    for (const [market, s] of Object.entries(result.summary)) {
      const names = { us: '美股', cn: 'A股', crypto: '数字货币', commodity: '大宗商品' };
      console.log(`[${names[market] || market}] 共${s.total}只 | 涨${s.upCount} 跌${s.downCount} 平${s.flatCount} | 均涨跌${s.avgChange}%`);
      if (s.maxUp) console.log(`  最大涨幅: ${s.maxUp.name}(${s.maxUp.symbol}) ${s.maxUp.change_pct}%`);
      if (s.maxDown) console.log(`  最大跌幅: ${s.maxDown.name}(${s.maxDown.symbol}) ${s.maxDown.change_pct}%`);
    }
  }

  console.log('\n[Run-Process] 完成');
  process.exit(0);
}

main().catch(e => {
  console.error('[Run-Process] 执行失败:', e);
  process.exit(1);
});
