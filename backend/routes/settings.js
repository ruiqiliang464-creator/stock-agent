const { authMiddleware } = require('./auth');

module.exports = function(prepare) {
  const express = require('express');
  const router = express.Router();

  // 获取用户设置
  router.get('/', authMiddleware, (req, res) => {
    let settings = prepare('SELECT * FROM user_settings WHERE user_id=?').get(req.user.id);
    if (!settings) {
      prepare('INSERT INTO user_settings (user_id) VALUES (?)').run(req.user.id);
      settings = prepare('SELECT * FROM user_settings WHERE user_id=?').get(req.user.id);
    }
    // 解析JSON字段
    settings.watchlist_us = JSON.parse(settings.watchlist_us || '[]');
    settings.watchlist_cn = JSON.parse(settings.watchlist_cn || '[]');
    settings.watchlist_crypto = JSON.parse(settings.watchlist_crypto || '[]');
    settings.watchlist_commodity = JSON.parse(settings.watchlist_commodity || '[]');
    res.json({ settings });
  });

  // 更新用户设置
  router.put('/', authMiddleware, (req, res) => {
    const { watchlist_us, watchlist_cn, watchlist_crypto, watchlist_commodity, push_time, push_enabled } = req.body;
    prepare(`
      UPDATE user_settings SET
        watchlist_us=?, watchlist_cn=?, watchlist_crypto=?, watchlist_commodity=?,
        push_time=?, push_enabled=? WHERE user_id=?
    `).run(
      JSON.stringify(watchlist_us || []),
      JSON.stringify(watchlist_cn || []),
      JSON.stringify(watchlist_crypto || []),
      JSON.stringify(watchlist_commodity || []),
      push_time || '08:30',
      push_enabled ? 1 : 0,
      req.user.id
    );
    res.json({ success: true });
  });

  return router;
};
