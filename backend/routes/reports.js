const { authMiddleware } = require('./auth');

module.exports = function(prepare) {
  const express = require('express');
  const router = express.Router();

  // 获取今日报告
  router.get('/today', authMiddleware, (req, res) => {
    const today = new Date().toISOString().split('T')[0];
    const report = prepare('SELECT * FROM reports WHERE date=?').get(today);
    if (!report) {
      return res.json({ exists: false, message: '今日报告尚未生成' });
    }
    res.json({ exists: true, report });
  });

  // 获取历史报告列表
  router.get('/history', authMiddleware, (req, res) => {
    const limit = parseInt(req.query.limit) || 30;
    const reports = prepare(
      'SELECT id, date, summary, created_at FROM reports ORDER BY date DESC LIMIT ?'
    ).all(limit);
    res.json({ reports });
  });

  // 获取指定日期报告
  router.get('/:date', authMiddleware, (req, res) => {
    const report = prepare('SELECT * FROM reports WHERE date=?').get(req.params.date);
    if (!report) {
      return res.status(404).json({ error: '报告不存在' });
    }
    res.json({ report });
  });

  return router;
};
