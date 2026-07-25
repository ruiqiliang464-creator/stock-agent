/**
 * runner-github.js — GitHub Actions 专用管道入口
 *
 * 不依赖 SQLite 数据库，纯 JSON 文件驱动：
 *   1. 采集四大市场数据 → 保存 raw_YYYY-MM-DD.json
 *   2. 清洗整合 → 保存 processed_YYYY-MM-DD.json
 *   3. 分析生成 → 保存 analysis_YYYY-MM-DD.json
 *   4. 格式化报告 + 邮件推送（读 subscribers.json）
 *   5. 保存 latest.json 供静态看板使用
 *
 * 用法: node backend/runner-github.js [collect|process|analyze|report|all]
 */

const path = require('path');
const fs = require('fs');

// ── 配置 ──
// 优先从环境变量读取（GitHub Secrets 注入），其次从 env 文件读取
const config = {};

// 从 env 文件加载（不修改 process.env，避免沙箱限制）
try {
  const envPath = path.join(__dirname, '..', 'config', 'default.env');
  if (fs.existsSync(envPath)) {
    for (const line of fs.readFileSync(envPath, 'utf-8').split('\n')) {
      const t = line.trim();
      if (!t || t.startsWith('#')) continue;
      const i = t.indexOf('=');
      if (i <= 0) continue;
      config[t.substring(0, i).trim()] = t.substring(i + 1).trim();
    }
  }
} catch (e) { console.error('配置加载失败:', e.message); }

// 环境变量覆盖（GitHub Secrets 会注入到 process.env）
const SMTP_USER = process.env.SMTP_USER || config.SMTP_USER || '';
const SMTP_PASS = process.env.SMTP_PASS || config.SMTP_PASS || '';
const SMTP_HOST = process.env.SMTP_HOST || config.SMTP_HOST || 'smtp.qq.com';
const SMTP_PORT = parseInt(process.env.SMTP_PORT || config.SMTP_PORT || '465');

const DATA_DIR = path.join(__dirname, '..', 'data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

const today = new Date().toISOString().split('T')[0];

// ── Step 1: 采集 ──
async function collect() {
  console.log('\n[Pipeline] ─── Step 1: 采集数据 ───');
  const usCollector = require('./collectors/us-stock');
  const cnCollector = require('./collectors/cn-stock');
  const cryptoCollector = require('./collectors/crypto');
  const commodityCollector = require('./collectors/commodity');

  const [usData, cnData, cryptoData, commodityData] = await Promise.allSettled([
    usCollector.run(), cnCollector.run(), cryptoCollector.run(), commodityCollector.run()
  ]);

  const allData = [];
  const markets = { us: usData, cn: cnData, crypto: cryptoData, commodity: commodityData };
  for (const [mkt, result] of Object.entries(markets)) {
    if (result.status === 'fulfilled' && result.value.length > 0) {
      allData.push(...result.value);
      console.log(`  ${mkt}: ${result.value.length} 条`);
    } else {
      const reason = result.status === 'rejected' ? (result.reason?.message || '未知错误') : '无数据';
      console.log(`  ${mkt}: 0 条 (${reason})`);
    }
  }

  const rawPath = path.join(DATA_DIR, `raw_${today}.json`);
  fs.writeFileSync(rawPath, JSON.stringify(allData, null, 2));
  console.log(`[Pipeline] 采集完成: ${allData.length} 条`);
  return allData;
}

// ── Step 2: 清洗整合 ──
function processData(rawData) {
  console.log('\n[Pipeline] ─── Step 2: 清洗整合 ───');

  const seen = {};
  const uniqueData = [];
  for (const item of rawData) {
    const key = `${item.market}_${item.symbol}`;
    if (!seen[key]) { seen[key] = true; uniqueData.push(item); }
  }

  const THRESHOLD = 1.5;
  const significant = uniqueData.filter(d => Math.abs(d.change_pct) >= THRESHOLD);

  const grouped = {};
  ['us', 'cn', 'crypto', 'commodity'].forEach(m => { grouped[m] = uniqueData.filter(d => d.market === m); });

  const summary = {};
  for (const [market, items] of Object.entries(grouped)) {
    if (items.length === 0) continue;
    const upCount = items.filter(d => d.change_pct > 0).length;
    const downCount = items.filter(d => d.change_pct < 0).length;
    const avgChange = items.reduce((s, d) => s + d.change_pct, 0) / items.length;
    const maxUp = items.reduce((m, d) => d.change_pct > m.change_pct ? d : m, items[0]);
    const maxDown = items.reduce((m, d) => d.change_pct < m.change_pct ? d : m, items[0]);

    summary[market] = {
      total: items.length, upCount, downCount, flatCount: items.length - upCount - downCount,
      avgChange: Math.round(avgChange * 100) / 100,
      maxUp: { symbol: maxUp.symbol, name: maxUp.name, change_pct: maxUp.change_pct },
      maxDown: { symbol: maxDown.symbol, name: maxDown.name, change_pct: maxDown.change_pct }
    };
  }

  const processed = { date: today, totalRecords: uniqueData.length, significantRecords: significant.length, grouped, summary, significant };
  fs.writeFileSync(path.join(DATA_DIR, `processed_${today}.json`), JSON.stringify(processed, null, 2));
  console.log(`[Pipeline] 清洗完成: ${uniqueData.length} 唯一, ${significant.length} 显著`);
  return processed;
}

// ── Step 3: 分析 ──
function marketName(m) { return { us: '美股', cn: 'A股', crypto: '数字货币', commodity: '大宗商品' }[m] || m; }

function analyzeData(processed) {
  console.log('\n[Pipeline] ─── Step 3: 分析生成 ───');

  const trends = [];
  for (const [market, items] of Object.entries(processed.grouped)) {
    if (!items || items.length === 0) continue;
    const ratio = items.filter(d => d.change_pct > 0).length / items.length;
    let mt = '震荡', mc = '低';
    if (ratio > 0.7) { mt = '强势上涨'; mc = '中'; }
    else if (ratio > 0.5) { mt = '偏强'; mc = '中'; }
    else if (ratio < 0.3) { mt = '普遍下跌'; mc = '中'; }
    else if (ratio < 0.5) { mt = '偏弱'; mc = '中'; }
    trends.push({ market, type: 'market_trend', description: `${marketName(market)}整体${mt}，上涨占比${Math.round(ratio*100)}%`, confidence: mc });

    items.filter(d => d.change_pct > 3).forEach(d => {
      trends.push({ market, type: 'individual_strong', symbol: d.symbol, name: d.name, description: `${d.name}(${d.symbol})涨幅${d.change_pct}%，表现强势`, confidence: d.change_pct > 5 ? '高' : '中', price: d.price, change_pct: d.change_pct });
    });
    items.filter(d => d.change_pct < -3).forEach(d => {
      trends.push({ market, type: 'individual_weak', symbol: d.symbol, name: d.name, description: `${d.name}(${d.symbol})跌幅${d.change_pct}%，表现疲弱`, confidence: d.change_pct < -5 ? '高' : '中', price: d.price, change_pct: d.change_pct });
    });
  }

  const opportunities = [];
  for (const [market, items] of Object.entries(processed.grouped)) {
    if (!items || items.length === 0) continue;
    items.filter(d => d.change_pct < -3 && d.change_pct > -8).forEach(d => {
      opportunities.push({ market, type: 'dip_buying', symbol: d.symbol, name: d.name, description: `${d.name}回调${Math.abs(d.change_pct)}%，关注低吸机会`, confidence: Math.abs(d.change_pct) > 5 ? '低' : '中', price: d.price, change_pct: d.change_pct });
    });
    items.filter(d => d.change_pct > 1.5 && d.change_pct < 3).forEach(d => {
      opportunities.push({ market, type: 'breakout_watch', symbol: d.symbol, name: d.name, description: `${d.name}温和上涨${d.change_pct}%，留意突破信号`, confidence: '低', price: d.price, change_pct: d.change_pct });
    });
    if (market === 'crypto') {
      const btc = items.find(d => d.symbol === 'BTC');
      if (btc && btc.change_pct > 2) {
        opportunities.push({ market: 'crypto', type: 'correlation', symbol: 'BTC', name: '比特币', description: `BTC领涨${btc.change_pct}%，关注主流币联动机会`, confidence: '中', price: btc.price, change_pct: btc.change_pct });
      }
    }
  }

  const risks = [];
  for (const [market, items] of Object.entries(processed.grouped)) {
    if (!items || items.length === 0) continue;
    items.filter(d => d.change_pct < -5).forEach(d => {
      risks.push({ market, type: 'crash_warning', symbol: d.symbol, name: d.name, description: `${d.name}暴跌${Math.abs(d.change_pct)}%，风险极高`, confidence: '高', price: d.price, change_pct: d.change_pct });
    });
    const downRatio = items.filter(d => d.change_pct < 0).length / items.length;
    if (downRatio > 0.8) {
      risks.push({ market, type: 'systemic_risk', symbol: 'ALL', name: marketName(market) + '整体', description: `${marketName(market)}超过80%标的下跌，存在系统性风险`, confidence: '高' });
    }
    if (market === 'crypto') {
      const btc = items.find(d => d.symbol === 'BTC');
      if (btc && btc.change_pct < -3) {
        risks.push({ market, type: 'btc_decline', symbol: 'BTC', name: '比特币', description: `BTC下跌${Math.abs(btc.change_pct)}%，可能带动整体币市回调`, confidence: '高', price: btc.price, change_pct: btc.change_pct });
      }
    }
  }

  const analysis = { date: today, trends, opportunities, risks, summary: processed.summary, grouped: processed.grouped };
  fs.writeFileSync(path.join(DATA_DIR, `analysis_${today}.json`), JSON.stringify(analysis, null, 2));
  console.log(`[Pipeline] 分析完成: ${trends.length} 趋势, ${opportunities.length} 机会, ${risks.length} 风险`);
  return analysis;
}

// ── Step 4: 报告 + 邮件 ──
async function reportAndPush(analysis) {
  console.log('\n[Pipeline] ─── Step 4: 报告 + 邮件推送 ───');

  const { generateReport, generateSummary } = require('./formatter/report');
  const htmlContent = generateReport(analysis);
  const summary = generateSummary(analysis);

  // 读取订阅者
  const subPath = path.join(DATA_DIR, 'subscribers.json');
  let subscribers = [];
  if (fs.existsSync(subPath)) {
    try { subscribers = JSON.parse(fs.readFileSync(subPath, 'utf-8')).subscribers.filter(s => s.enabled); } catch(e) {}
  }
  console.log(`[Pipeline] ${subscribers.length} 位订阅者`);

  const results = [];

  if (!SMTP_USER || !SMTP_PASS) {
    console.error('[Pipeline] SMTP 未配置，跳过邮件发送');
  } else {
    const nodemailer = require('nodemailer');
    const transporter = nodemailer.createTransport({ host: SMTP_HOST, port: SMTP_PORT, secure: true, auth: { user: SMTP_USER, pass: SMTP_PASS } });

    for (const sub of subscribers) {
      const target = sub.pushEmail || sub.email;
      const mailOpts = {
        from: `"Stock Agent 每日情报" <${SMTP_USER}>`,
        to: target,
        subject: `每日市场情报 ${today}`,
        html: htmlContent,
        text: `每日市场情报 ${today} - 请查看HTML版本获取完整内容`
      };
      try {
        const info = await transporter.sendMail(mailOpts);
        console.log(`[Pipeline] ✅ ${target} (${info.messageId})`);
        results.push({ email: target, success: true });
      } catch (e) {
        console.error(`[Pipeline] ❌ ${target}: ${e.message}`);
        try {
          await transporter.sendMail(mailOpts);
          console.log(`[Pipeline] ✅ ${target} (重试成功)`);
          results.push({ email: target, success: true });
        } catch (e2) {
          results.push({ email: target, success: false });
        }
      }
    }
  }

  // 保存 latest.json 供看板
  const latestData = {
    date: today,
    updatedAt: new Date().toISOString(),
    markets: {},
    analysis: { trends: analysis.trends, opportunities: analysis.opportunities, risks: analysis.risks, summary: analysis.summary },
    report: { summary },
    emailResults: results
  };

  for (const [mkt, items] of Object.entries(analysis.grouped || {})) {
    latestData.markets[mkt] = items.map(d => ({
      symbol: d.symbol, name: d.name, price: d.price, change_pct: d.change_pct,
      volume: d.volume, high: d.high, low: d.low, open: d.open, prev_close: d.prev_close
    }));
  }

  fs.writeFileSync(path.join(DATA_DIR, 'latest.json'), JSON.stringify(latestData, null, 2));
  console.log(`[Pipeline] latest.json 已保存`);

  const sent = results.filter(r => r.success).length;
  console.log(`[Pipeline] 邮件: ${sent}/${results.length} 成功`);
  return { sent, total: results.length };
}

// ── 主入口 ──
async function main() {
  const task = process.argv[2] || 'all';
  const tasks = task === 'all' ? ['collect', 'process', 'analyze', 'report'] : [task];

  console.log(`[Pipeline] 开始: ${tasks.join(' → ')}  日期: ${today}`);

  let rawData, processedData, analysisData;

  for (const t of tasks) {
    try {
      if (t === 'collect') {
        rawData = await collect();
      } else if (t === 'process') {
        if (!rawData) {
          const p = path.join(DATA_DIR, `raw_${today}.json`);
          rawData = fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf-8')) : null;
        }
        if (rawData) processedData = processData(rawData);
        else console.error('[Pipeline] 无原始数据，跳过清洗');
      } else if (t === 'analyze') {
        if (!processedData) {
          const p = path.join(DATA_DIR, `processed_${today}.json`);
          processedData = fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf-8')) : null;
        }
        if (processedData) analysisData = analyzeData(processedData);
        else console.error('[Pipeline] 无清洗数据，跳过分析');
      } else if (t === 'report') {
        if (!analysisData) {
          const p = path.join(DATA_DIR, `analysis_${today}.json`);
          analysisData = fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf-8')) : null;
        }
        if (analysisData) await reportAndPush(analysisData);
        else console.error('[Pipeline] 无分析数据，跳过推送');
      }
    } catch (e) {
      console.error(`[Pipeline] ${t} 失败:`, e.message);
    }
  }

  console.log('\n[Pipeline] ✅ 全部完成');
}

main().catch(e => console.error('[Pipeline] 致命错误:', e.message));
