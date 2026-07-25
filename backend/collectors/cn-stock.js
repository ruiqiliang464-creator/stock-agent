const axios = require('axios');

// A股默认关注列表 - 沪深主要指数和热门个股
const DEFAULT_INDEX = [
  { code: '1.000001', name: '上证指数' },
  { code: '0.399001', name: '深证成指' },
  { code: '0.399006', name: '创业板指' }
];

const DEFAULT_STOCKS = [
  { code: '1.600519', name: '贵州茅台' },
  { code: '0.000858', name: '五粮液' },
  { code: '1.601318', name: '中国平安' },
  { code: '0.000333', name: '美的集团' },
  { code: '1.600036', name: '招商银行' },
  { code: '1.601012', name: '隆基绿能' },
  { code: '0.002594', name: '比亚迪' },
  { code: '0.000001', name: '平安银行' },
  { code: '1.600900', name: '长江电力' },
  { code: '0.300750', name: '宁德时代' },
  { code: '1.601899', name: '紫金矿业' },
  { code: '0.002415', name: '海康威视' },
  { code: '1.600276', name: '恒瑞医药' },
  { code: '0.000651', name: '格力电器' },
  { code: '1.603259', name: '药明康德' },
  { code: '0.002714', name: '牧原股份' },
  { code: '1.688981', name: '中芯国际' },
  { code: '0.300059', name: '东方财富' },
  { code: '1.600030', name: '中信证券' },
  { code: '1.601398', name: '工商银行' }
];

async function fetchCNStocks() {
  const results = [];
  const allItems = [...DEFAULT_INDEX, ...DEFAULT_STOCKS];

  // 东方财富实时行情API (批量)
  const secids = allItems.map(s => s.code).join(',');
  try {
    const url = `https://push2.eastmoney.com/api/qt/ulist.np/get?secids=${secids}&fields=f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18`;
    const resp = await axios.get(url, { timeout: 8000 });
    const diff = resp.data?.data?.diff;

    if (diff && Array.isArray(diff)) {
      diff.forEach(item => {
        // f2=最新价, f3=涨跌幅, f4=涨跌额, f5=成交量(手), f6=成交额, f12=代码, f14=名称, f15=最高, f16=最低, f17=今开, f18=昨收
        const code = item.f12;
        const name = item.f14;
        if (!name || !code) return;

        results.push({
          market: 'cn',
          symbol: code,
          name: name,
          price: item.f2 / 100 || 0,
          change_pct: item.f3 / 100 || 0,
          volume: item.f5 || 0,
          high: item.f15 / 100 || 0,
          low: item.f16 / 100 || 0,
          open: item.f17 / 100 || 0,
          prev_close: item.f18 / 100 || 0,
          market_cap: 0,
          extra: JSON.stringify({ amount: item.f6 || 0 })
        });
      });
    }
  } catch (e) {
    console.error('[CN Collector] 东方财富批量API失败:', e.message);

    // 备用方案：逐个采集
    for (const item of allItems) {
      try {
        const url = `https://push2.eastmoney.com/api/qt/stock/get?secid=${item.code}&fields=f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18`;
        const resp = await axios.get(url, { timeout: 5000 });
        const d = resp.data?.data;
        if (d) {
          results.push({
            market: 'cn',
            symbol: d.f12,
            name: d.f14 || item.name,
            price: d.f2 / 100 || 0,
            change_pct: d.f3 / 100 || 0,
            volume: d.f5 || 0,
            high: d.f15 / 100 || 0,
            low: d.f16 / 100 || 0,
            open: d.f17 / 100 || 0,
            prev_close: d.f18 / 100 || 0,
            market_cap: 0,
            extra: JSON.stringify({ amount: d.f6 || 0 })
          });
        }
      } catch (e2) {
        console.error(`[CN Collector] ${item.name} 采集失败:`, e2.message);
      }
    }
  }

  return results;
}

async function run() {
  console.log('[CN Collector] 开始采集A股数据...');
  const data = await fetchCNStocks();
  console.log(`[CN Collector] 采集完成, 共 ${data.length} 条`);
  return data;
}

module.exports = { run, fetchCNStocks };
