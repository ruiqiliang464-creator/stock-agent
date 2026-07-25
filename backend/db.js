const initSqlJs = require('sql.js');
const path = require('path');
const fs = require('fs');

const DB_PATH = process.env.DB_PATH || path.join(__dirname, '..', 'data', 'stock_agent.db');

// 确保data目录存在
const dataDir = path.dirname(DB_PATH);
if (!fs.existsSync(dataDir)) {
  fs.mkdirSync(dataDir, { recursive: true });
}

let db = null;

async function initDatabase() {
  const SQL = await initSqlJs();

  // 尝试加载已有数据库
  if (fs.existsSync(DB_PATH)) {
    const buf = fs.readFileSync(DB_PATH);
    db = new SQL.Database(buf);
  } else {
    db = new SQL.Database();
  }

  // 创建表
  db.run(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      push_email TEXT,
      created_at TEXT DEFAULT (datetime('now','localtime')),
      last_login TEXT
    );
  `);

  db.run(`
    CREATE TABLE IF NOT EXISTS user_settings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER UNIQUE NOT NULL,
      watchlist_us TEXT DEFAULT '[]',
      watchlist_cn TEXT DEFAULT '[]',
      watchlist_crypto TEXT DEFAULT '[]',
      watchlist_commodity TEXT DEFAULT '[]',
      push_time TEXT DEFAULT '08:30',
      push_enabled INTEGER DEFAULT 1
    );
  `);

  db.run(`
    CREATE TABLE IF NOT EXISTS market_data (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      market TEXT NOT NULL,
      symbol TEXT NOT NULL,
      name TEXT,
      price REAL,
      change_pct REAL,
      volume REAL,
      high REAL,
      low REAL,
      open REAL,
      prev_close REAL,
      market_cap REAL,
      extra TEXT,
      collected_at TEXT DEFAULT (datetime('now','localtime'))
    );
  `);

  db.run(`
    CREATE TABLE IF NOT EXISTS reports (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      date TEXT UNIQUE NOT NULL,
      html_content TEXT,
      summary TEXT,
      created_at TEXT DEFAULT (datetime('now','localtime'))
    );
  `);

  saveDb();
  console.log('[DB] 数据库初始化完成');
  return db;
}

function saveDb() {
  if (!db) return;
  const data = db.export();
  const buffer = Buffer.from(data);
  fs.writeFileSync(DB_PATH, buffer);
}

// 同步包装器 - 用于路由中
function prepare(sql) {
  return {
    run(...params) {
      db.run(sql, params);
      // 必须在 saveDb 之前获取，因为 db.export() 会重置 last_insert_rowid
      const lastId = getLastInsertId();
      const changes = getChanges();
      saveDb();
      return { lastInsertRowid: lastId, changes };
    },
    get(...params) {
      const stmt = db.prepare(sql);
      stmt.bind(params);
      if (stmt.step()) {
        const row = stmt.getAsObject();
        stmt.free();
        return row;
      }
      stmt.free();
      return undefined;
    },
    all(...params) {
      const stmt = db.prepare(sql);
      stmt.bind(params);
      const rows = [];
      while (stmt.step()) {
        rows.push(stmt.getAsObject());
      }
      stmt.free();
      return rows;
    }
  };
}

function getLastInsertId() {
  try {
    const stmt = db.prepare('SELECT last_insert_rowid() as id');
    stmt.step();
    const row = stmt.getAsObject();
    stmt.free();
    return row.id || 0;
  } catch {
    return 0;
  }
}

function getChanges() {
  try {
    const stmt = db.prepare('SELECT changes() as cnt');
    stmt.step();
    const row = stmt.getAsObject();
    stmt.free();
    return row.cnt || 0;
  } catch {
    return 0;
  }
}

function transaction(fn) {
  db.run('BEGIN TRANSACTION');
  try {
    fn();
    db.run('COMMIT');
    saveDb();
  } catch (e) {
    db.run('ROLLBACK');
    throw e;
  }
}

module.exports = { initDatabase, prepare, saveDb, transaction, getDb: () => db };
