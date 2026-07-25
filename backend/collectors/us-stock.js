const axios = require('axios');

// 美股默认关注列表
const DEFAULT_SYMBOLS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'JPM', 'V', 'WMT',
  'DIS', 'NFLX', 'AMD', 'INTC', 'BA', 'GS', 'CVX', 'XOM', 'PFE', 'UNH'];

async function fetchUSStocks(symbols = DEFAULT_SYMBOLS) {
  const results = [];

  for (const symbol of symbols) {
    try {
      // 使用Yahoo Finance v8 API
      const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=1d&interval=1d`;
      const resp = await axios.get(url, {
        headers: { 'User-Agent': 'Mozilla/5.0' },
        timeout: 15000
      });

      const meta = resp.data?.chart?.result?.[0]?.meta;
      if (!meta) continue;

      const price = meta.regularMarketPrice;
      const prevClose = meta.chartPreviousClose || meta.previousClose;
      const changePct = prevClose ? ((price - prevClose) / prevClose * 100) : 0;

      results.push({
        market: 'us',
        symbol,
        name: meta.shortName || symbol,
        price,
        change_pct: Math.round(changePct * 100) / 100,
        volume: meta.regularMarketVolume || 0,
        high: meta.regularMarketDayHigh || price,
        low: meta.regularMarketDayLow || price,
        open: meta.regularMarketOpen || price,
        prev_close: prevClose,
        market_cap: 0,
        extra: JSON.stringify({ currency: meta.currency || 'USD' })
      });
    } catch (e) {
      console.error(`[US Collector] ${symbol} 采集失败:`, e.message);
    }
  }

  return results;
}

async function run() {
  console.log('[US Collector] 开始采集美股数据...');
  const data = await fetchUSStocks();
  console.log(`[US Collector] 采集完成, 共 ${data.length} 条`);
  return data;
}

module.exports = { run, fetchUSStocks };
