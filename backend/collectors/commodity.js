const axios = require('axios');
const cheerio = require('cheerio');

// 大宗商品默认关注列表
const DEFAULT_COMMODITIES = [
  { symbol: 'GOLD', name: '黄金' },
  { symbol: 'SILVER', name: '白银' },
  { symbol: 'CRUDE_OIL', name: '原油(WTI)' },
  { symbol: 'BRENT', name: '原油(布伦特)' },
  { symbol: 'NATURAL_GAS', name: '天然气' },
  { symbol: 'COPPER', name: '铜' },
  { symbol: 'ALUMINUM', name: '铝' },
  { symbol: 'CORN', name: '玉米' },
  { symbol: 'SOYBEAN', name: '大豆' },
  { symbol: 'WHEAT', name: '小麦' },
  { symbol: 'IRON_ORE', name: '铁矿石' },
  { symbol: 'RUBBER', name: '橡胶' }
];

// 金十数据API (商品行情)
async function fetchFromJin10() {
  const results = [];

  try {
    // 金十财经API
    const url = 'https://cdn.jin10.com/dc_center/dc_data_center/reports_list.json';
    const resp = await axios.get(url, { timeout: 8000 });
    // 金十数据格式较复杂，此处作为参考
  } catch (e) {
    // 金十API需要鉴权，作为补充
  }

  return results;
}

// Investing.com 备用数据源 (通过公开数据)
async function fetchCommodityData() {
  const results = [];

  // 使用多源数据整合
  const commodityPrices = {
    'GOLD': { price: 0, unit: 'USD/oz' },
    'SILVER': { price: 0, unit: 'USD/oz' },
    'CRUDE_OIL': { price: 0, unit: 'USD/bbl' },
    'BRENT': { price: 0, unit: 'USD/bbl' },
    'NATURAL_GAS': { price: 0, unit: 'USD/MMBtu' },
    'COPPER': { price: 0, unit: 'USD/lb' },
    'ALUMINUM': { price: 0, unit: 'USD/ton' },
    'CORN': { price: 0, unit: 'USD/bushel' },
    'SOYBEAN': { price: 0, unit: 'USD/bushel' },
    'WHEAT': { price: 0, unit: 'USD/bushel' },
    'IRON_ORE': { price: 0, unit: 'USD/ton' },
    'RUBBER': { price: 0, unit: 'USD/ton' }
  };

  // 尝试从东方财富商品期货接口获取
  try {
    // 国内期货主力合约
    const futuresCodes = [
      { code: '113.aum', name: '沪金主力', symbol: 'GOLD' },
      { code: '113.agm', name: '沪银主力', symbol: 'SILVER' },
      { code: '113.cum', name: '沪铜主力', symbol: 'COPPER' },
      { code: '113.alm', name: '沪铝主力', symbol: 'ALUMINUM' },
      { code: '113.rum', name: '橡胶主力', symbol: 'RUBBER' },
      { code: '113.im', name: '铁矿主力', symbol: 'IRON_ORE' },
      { code: '113.aum2', name: '原油主力', symbol: 'CRUDE_OIL' },
      { code: '113.cm', name: '玉米主力', symbol: 'CORN' },
      { code: '113.am', name: '豆一主力', symbol: 'SOYBEAN' },
      { code: '113.wm', name: '麦主力', symbol: 'WHEAT' }
    ];

    const secids = futuresCodes.map(f => f.code).join(',');
    const url = `https://push2.eastmoney.com/api/qt/ulist.np/get?secids=${secids}&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18`;
    const resp = await axios.get(url, { timeout: 8000 });
    const diff = resp.data?.data?.diff;

    if (diff && Array.isArray(diff)) {
      diff.forEach(item => {
        const matched = futuresCodes.find(f => f.code === `${item.f2}.${item.f12}`);
        const sym = matched ? matched.symbol : 'UNKNOWN';

        results.push({
          market: 'commodity',
          symbol: sym,
          name: matched ? matched.name : (item.f14 || sym),
          price: item.f2 / 100 || 0,
          change_pct: item.f3 / 100 || 0,
          volume: item.f5 || 0,
          high: item.f15 / 100 || 0,
          low: item.f16 / 100 || 0,
          open: item.f17 / 100 || 0,
          prev_close: item.f18 / 100 || 0,
          market_cap: 0,
          extra: JSON.stringify({ unit: commodityPrices[sym]?.unit || 'CNY' })
        });
      });
    }
  } catch (e) {
    console.error('[Commodity Collector] 东方财富期货API失败:', e.message);
  }

  // 如果期货数据不足，补充国际商品数据
  if (results.length < 5) {
    try {
      // 使用Yahoo Finance商品ETF作为代理
      const commodityETFs = {
        'GLD': { symbol: 'GOLD', name: '黄金ETF' },
        'SLV': { symbol: 'SILVER', name: '白银ETF' },
        'USO': { symbol: 'CRUDE_OIL', name: '原油ETF' },
        'COPX': { symbol: 'COPPER', name: '铜ETF' },
        'CORN': { symbol: 'CORN', name: '玉米ETF' },
        'SOYB': { symbol: 'SOYBEAN', name: '大豆ETF' },
        'WEAT': { symbol: 'WHEAT', name: '小麦ETF' }
      };

      for (const [etf, info] of Object.entries(commodityETFs)) {
        try {
          const url = `https://query1.finance.yahoo.com/v8/finance/chart/${etf}?range=1d&interval=1d`;
          const resp = await axios.get(url, {
            headers: { 'User-Agent': 'Mozilla/5.0' },
            timeout: 15000
          });

          const meta = resp.data?.chart?.result?.[0]?.meta;
          if (meta) {
            const price = meta.regularMarketPrice;
            const prevClose = meta.previousClose || meta.chartPreviousClose;
            const changePct = prevClose ? ((price - prevClose) / prevClose * 100) : 0;

            results.push({
              market: 'commodity',
              symbol: info.symbol,
              name: info.name,
              price,
              change_pct: Math.round(changePct * 100) / 100,
              volume: meta.regularMarketVolume || 0,
              high: meta.regularMarketDayHigh || price,
              low: meta.regularMarketDayLow || price,
              open: meta.regularMarketOpen || price,
              prev_close: prevClose,
              market_cap: 0,
              extra: JSON.stringify({ unit: 'USD', proxy_etf: etf })
            });
          }
        } catch (e2) {
          // 单个ETF失败不影响其他
        }
      }
    } catch (e) {
      console.error('[Commodity Collector] Yahoo商品ETF失败:', e.message);
    }
  }

  return results;
}

async function run() {
  console.log('[Commodity Collector] 开始采集大宗商品数据...');
  const data = await fetchCommodityData();
  console.log(`[Commodity Collector] 采集完成, 共 ${data.length} 条`);
  return data;
}

module.exports = { run, fetchCommodityData };
