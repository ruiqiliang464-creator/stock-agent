const axios = require('axios');

// 数字货币默认关注列表
const DEFAULT_CRYPTO = [
  'bitcoin', 'ethereum', 'binancecoin', 'ripple', 'solana',
  'cardano', 'dogecoin', 'polkadot', 'avalanche-2', 'chainlink',
  'tether', 'usd-coin', 'litecoin', 'tron', 'uniswap',
  'near', 'stellar', 'polygon-pos', 'ethereum-classic', 'filecoin'
];

async function fetchCrypto(ids = DEFAULT_CRYPTO) {
  const results = [];

  try {
    // CoinGecko 市场数据API (批量)
    const url = `https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=${ids.join(',')}&order=market_cap_desc&per_page=50&page=1&sparkline=false`;
    const resp = await axios.get(url, { timeout: 20000 });

    if (Array.isArray(resp.data)) {
      resp.data.forEach(coin => {
        const prevPrice = coin.current_price - coin.price_change_24h;
        const changePct = coin.price_change_percentage_24h || 0;

        results.push({
          market: 'crypto',
          symbol: coin.symbol?.toUpperCase() || coin.id,
          name: coin.name,
          price: coin.current_price || 0,
          change_pct: Math.round(changePct * 100) / 100,
          volume: coin.total_volume || 0,
          high: coin.high_24h || 0,
          low: coin.low_24h || 0,
          open: prevPrice || coin.current_price,
          prev_close: prevPrice || coin.current_price,
          market_cap: coin.market_cap || 0,
          extra: JSON.stringify({
            rank: coin.market_cap_rank,
            circulating_supply: coin.circulating_supply,
            image: coin.image
          })
        });
      });
    }
  } catch (e) {
    console.error('[Crypto Collector] CoinGecko API失败:', e.message);

    // 备用：Binance API
    try {
      const url = 'https://api.binance.com/api/v3/ticker/24hr';
      const resp = await axios.get(url, { timeout: 20000 });
      const symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'SOLUSDT',
        'ADAUSDT', 'DOGEUSDT', 'DOTUSDT', 'AVAXUSDT', 'LINKUSDT',
        'LTCUSDT', 'TRXUSDT', 'UNIUSDT', 'NEARUSDT', 'MATICUSDT'];

      if (Array.isArray(resp.data)) {
        resp.data.filter(t => symbols.includes(t.symbol)).forEach(t => {
          results.push({
            market: 'crypto',
            symbol: t.symbol.replace('USDT', ''),
            name: t.symbol.replace('USDT', ''),
            price: parseFloat(t.lastPrice),
            change_pct: parseFloat(t.priceChangePercent),
            volume: parseFloat(t.volume),
            high: parseFloat(t.highPrice),
            low: parseFloat(t.lowPrice),
            open: parseFloat(t.openPrice),
            prev_close: parseFloat(t.prevClosePrice || t.openPrice),
            market_cap: 0,
            extra: JSON.stringify({ quoteVolume: parseFloat(t.quoteVolume) })
          });
        });
      }
    } catch (e2) {
      console.error('[Crypto Collector] Binance备用API也失败:', e2.message);
    }
  }

  return results;
}

async function run() {
  console.log('[Crypto Collector] 开始采集数字货币数据...');
  const data = await fetchCrypto();
  console.log(`[Crypto Collector] 采集完成, 共 ${data.length} 条`);
  return data;
}

module.exports = { run, fetchCrypto };
