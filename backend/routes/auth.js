const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');

const JWT_SECRET = process.env.JWT_SECRET || 'stock_agent_secret_key_2026';
const JWT_EXPIRES = process.env.JWT_EXPIRES_IN || '7d';

// JWT认证中间件
function authMiddleware(req, res, next) {
  const token = req.headers.authorization?.split(' ')[1];
  if (!token) return res.status(401).json({ error: '未登录' });
  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    req.user = decoded;
    next();
  } catch {
    return res.status(401).json({ error: '登录已过期' });
  }
}

module.exports = function(prepare) {
  const express = require('express');
  const router = express.Router();

  // 用户注册
  router.post('/register', (req, res) => {
    const { username, email, password, pushEmail } = req.body;
    if (!username || !email || !password) {
      return res.status(400).json({ error: '用户名、邮箱和密码不能为空' });
    }
    if (password.length < 6) {
      return res.status(400).json({ error: '密码至少6位' });
    }

    // 检查重复
    const existing = prepare('SELECT id FROM users WHERE username=? OR email=?').get(username, email);
    if (existing) {
      return res.status(409).json({ error: '用户名或邮箱已存在' });
    }

    const passwordHash = bcrypt.hashSync(password, 10);
    const pushEmailValue = pushEmail || email;

    try {
      const result = prepare(
        'INSERT INTO users (username, email, password_hash, push_email) VALUES (?, ?, ?, ?)'
      ).run(username, email, passwordHash, pushEmailValue);

      // 自动创建用户设置
      prepare('INSERT INTO user_settings (user_id) VALUES (?)').run(result.lastInsertRowid);

      const token = jwt.sign({ id: result.lastInsertRowid, username, email }, JWT_SECRET, { expiresIn: JWT_EXPIRES });
      res.json({ success: true, token, user: { id: result.lastInsertRowid, username, email, pushEmail: pushEmailValue } });
    } catch (e) {
      res.status(500).json({ error: '注册失败: ' + e.message });
    }
  });

  // 用户登录
  router.post('/login', (req, res) => {
    const { username, password } = req.body;
    if (!username || !password) {
      return res.status(400).json({ error: '用户名和密码不能为空' });
    }

    const user = prepare('SELECT * FROM users WHERE username=? OR email=?').get(username, username);
    if (!user) {
      return res.status(404).json({ error: '用户不存在' });
    }

    if (!bcrypt.compareSync(password, user.password_hash)) {
      return res.status(401).json({ error: '密码错误' });
    }

    // 更新登录时间
    prepare('UPDATE users SET last_login=datetime(\'now\',\'localtime\') WHERE id=?').run(user.id);

    const token = jwt.sign({ id: user.id, username: user.username, email: user.email }, JWT_SECRET, { expiresIn: JWT_EXPIRES });
    res.json({ success: true, token, user: { id: user.id, username: user.username, email: user.email, pushEmail: user.push_email } });
  });

  // 获取当前用户信息
  router.get('/me', authMiddleware, (req, res) => {
    const user = prepare('SELECT id, username, email, push_email, created_at FROM users WHERE id=?').get(req.user.id);
    if (!user) return res.status(404).json({ error: '用户不存在' });
    res.json({ user });
  });

  // 更新推送邮箱
  router.put('/push-email', authMiddleware, (req, res) => {
    const { pushEmail } = req.body;
    if (!pushEmail) return res.status(400).json({ error: '邮箱不能为空' });
    prepare('UPDATE users SET push_email=? WHERE id=?').run(pushEmail, req.user.id);
    res.json({ success: true, pushEmail });
  });

  return router;
};

module.exports.authMiddleware = authMiddleware;
