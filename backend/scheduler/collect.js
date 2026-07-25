const { prepare, saveDb } = require('../db');
const usCollector = require('../collectors/us-stock');
const cnCollector = require('../collectors/cn-stock');
const cryptoCollector = require('../collectors/crypto');
const commodityCollector = require('../collectors/commodity');

async function run() {
  console.log('[Collect Scheduler] 开始全市场数据采集...');

  const allData = [];

  // 并行采集四大市场数据
  const [usData, cnData, cryptoData, commodityData] = await Promise.allSettled([
    usCollector.run(),
    cnCollector.run(),
    cryptoCollector.run(),
    commodityCollector.run()
  ]);

  if (usData.status === 'fulfilled') allData.push(...usData.value);
  if (cnData.status === 'fulfilled') allData.push(...cnData.value);
  if (cryptoData.status === 'fulfilled') allData.push(...cryptoData.value);
  if (commodityData.status === 'fulfilled') allData.push(...commodityData.value);

  console.log(`[Collect Scheduler] 总计采集 ${allData.length} 条数据`);

  // 写入数据库
  const insertStmt = prepare(`
    INSERT OR REPLACE INTO market_data (market, symbol, name, price, change_pct, volume, high, low, open, prev_close, market_cap, extra)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);

  for (const item of allData) {
    try {
      insertStmt.run(
        item.market, item.symbol, item.name, item.price, item.change_pct,
        item.volume, item.high, item.low, item.open, item.prev_close,
        item.market_cap, item.extra
      );
    } catch (e) {
      console.error(`[Collect Scheduler] ${item.symbol} 入库失败:`, e.message);
    }
  }

  saveDb();
  console.log('[Collect Scheduler] 数据入库完成');
  return allData;
}

module.exports = { run };
