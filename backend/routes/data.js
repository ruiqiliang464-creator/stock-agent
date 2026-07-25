const { authMiddleware } = require('./auth');

module.exports = function(prepare) {
  const express = require('express');
  const router = express.Router();

  // 获取各市场实时数据
  router.get('/market/:market', authMiddleware, (req, res) => {
    const market = req.params.market;
    const validMarkets = ['us', 'cn', 'crypto', 'commodity'];
    if (!validMarkets.includes(market)) {
      return res.status(400).json({ error: '无效市场类型' });
    }

    const today = new Date().toISOString().split('T')[0];
    const data = prepare(
      'SELECT * FROM market_data WHERE market=? AND collected_at>=? ORDER BY change_pct DESC'
    ).all(market, today);

    res.json({ market, data, count: data.length, date: today });
  });

  // 获取所有市场概览
  router.get('/overview', authMiddleware, (req, res) => {
    const today = new Date().toISOString().split('T')[0];
    const markets = ['us', 'cn', 'crypto', 'commodity'];
    const overview = {};

    markets.forEach(m => {
      const topGainers = prepare(
        'SELECT symbol, name, price, change_pct, volume FROM market_data WHERE market=? AND collected_at>=? AND change_pct>0 ORDER BY change_pct DESC LIMIT 5'
      ).all(m, today);

      const topLosers = prepare(
        'SELECT symbol, name, price, change_pct, volume FROM market_data WHERE market=? AND collected_at>=? AND change_pct<0 ORDER BY change_pct ASC LIMIT 5'
      ).all(m, today);

      overview[m] = { topGainers, topLosers };
    });

    res.json({ overview, date: today });
  });

  return router;
};
