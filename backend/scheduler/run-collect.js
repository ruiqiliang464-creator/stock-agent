// Temporary runner script for data collection
const { initDatabase } = require('../db');
const collect = require('./collect');

async function main() {
  console.log('=== StockAgent 数据采集任务启动 ===');
  console.log('时间:', new Date().toLocaleString('zh-CN'));
  console.log('');

  // Initialize database first
  await initDatabase();

  // Run collection
  const data = await collect.run();

  console.log('');
  console.log('=== 采集任务完成 ===');
  console.log('总计:', data.length, '条数据已入库');

  // Print summary by market
  const byMarket = {};
  for (const item of data) {
    if (!byMarket[item.market]) byMarket[item.market] = [];
    byMarket[item.market].push(item);
  }

  const marketNames = {
    us: '美股',
    cn: 'A股',
    crypto: '数字货币',
    commodity: '大宗商品'
  };

  for (const [market, items] of Object.entries(byMarket)) {
    console.log(`\n[${marketNames[market] || market}] ${items.length} 条:`);
    for (const item of items) {
      const changeStr = item.change_pct >= 0 ? `+${item.change_pct}%` : `${item.change_pct}%`;
      console.log(`  ${item.name} (${item.symbol}): ${item.price} ${changeStr}`);
    }
  }

  process.exit(0);
}

main().catch(e => {
  console.error('采集任务失败:', e);
  process.exit(1);
});
