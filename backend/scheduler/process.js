const { prepare } = require('../db');

async function run() {
  console.log('[Process Scheduler] 开始清洗整合...');

  const today = new Date().toISOString().split('T')[0];
  const allData = prepare(
    'SELECT * FROM market_data WHERE collected_at>=?'
  ).all(today + ' 00:00:00');

  if (allData.length === 0) {
    console.log('[Process Scheduler] 今日无数据，跳过清洗');
    return;
  }

  // 1. 去重 - 同标的多条记录取最新
  const uniqueData = [];
  const seen = {};
  allData.sort((a, b) => new Date(b.collected_at) - new Date(a.collected_at));
  for (const item of allData) {
    const key = `${item.market}_${item.symbol}`;
    if (!seen[key]) {
      seen[key] = true;
      uniqueData.push(item);
    }
  }

  // 2. 筛选
  const THRESHOLD = 1.5;
  const significant = uniqueData.filter(d => Math.abs(d.change_pct) >= THRESHOLD);

  // 3. 按市场分类
  const grouped = {};
  ['us', 'cn', 'crypto', 'commodity'].forEach(m => {
    grouped[m] = uniqueData.filter(d => d.market === m);
  });

  // 4. 计算市场概况统计
  const summary = {};
  for (const [market, items] of Object.entries(grouped)) {
    if (items.length === 0) continue;
    const upCount = items.filter(d => d.change_pct > 0).length;
    const downCount = items.filter(d => d.change_pct < 0).length;
    const avgChange = items.reduce((s, d) => s + d.change_pct, 0) / items.length;
    const maxUp = items.reduce((m, d) => d.change_pct > m.change_pct ? d : m, items[0]);
    const maxDown = items.reduce((m, d) => d.change_pct < m.change_pct ? d : m, items[0]);

    summary[market] = {
      total: items.length,
      upCount,
      downCount,
      flatCount: items.length - upCount - downCount,
      avgChange: Math.round(avgChange * 100) / 100,
      maxUp: { symbol: maxUp.symbol, name: maxUp.name, change_pct: maxUp.change_pct },
      maxDown: { symbol: maxDown.symbol, name: maxDown.name, change_pct: maxDown.change_pct }
    };
  }

  // 5. 保存处理结果到文件
  const processedData = { date: today, totalRecords: uniqueData.length, significantRecords: significant.length, grouped, summary, significant };

  const fs = require('fs');
  const path = require('path');
  const outputPath = path.join(__dirname, '..', '..', 'data', `processed_${today}.json`);
  fs.writeFileSync(outputPath, JSON.stringify(processedData, null, 2));

  console.log(`[Process Scheduler] 清洗完成: ${uniqueData.length} 唯一记录, ${significant.length} 显著变动`);
  return processedData;
}

module.exports = { run };
