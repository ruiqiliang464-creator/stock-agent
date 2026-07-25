const db = require('../db');
const fs = require('fs');
const path = require('path');

// 置信度计算规则
function calculateConfidence(signal, data) {
  let confidence = '低';

  // 多信号确认 → 高
  // 单信号但有强数据支撑 → 中
  // 单信号弱支撑 → 低

  if (signal.type === 'trend_reversal') {
    if (signal.confirmations >= 3) confidence = '高';
    else if (signal.confirmations >= 2) confidence = '中';
  } else if (signal.type === 'breakout') {
    if (data.volume > data.avgVolume * 2) confidence = '高';
    else if (data.volume > data.avgVolume * 1.5) confidence = '中';
  } else if (signal.type === 'risk_warning') {
    if (Math.abs(data.change_pct) > 5) confidence = '高';
    else if (Math.abs(data.change_pct) > 3) confidence = '中';
  } else if (signal.type === 'oversold_overbought') {
    confidence = '中'; // RSI类指标默认中等
  }

  return confidence;
}

// 趋势分析引擎
function analyzeTrends(grouped) {
  const trends = [];

  for (const [market, items] of Object.entries(grouped)) {
    if (!items || items.length === 0) continue;

    // 整体市场趋势判断
    const upItems = items.filter(d => d.change_pct > 0);
    const ratio = upItems.length / items.length;

    let marketTrend = '震荡';
    let marketConfidence = '低';
    if (ratio > 0.7) { marketTrend = '强势上涨'; marketConfidence = '中'; }
    else if (ratio > 0.5) { marketTrend = '偏强'; marketConfidence = '中'; }
    else if (ratio < 0.3) { marketTrend = '普遍下跌'; marketConfidence = '中'; }
    else if (ratio < 0.5) { marketTrend = '偏弱'; marketConfidence = '中'; }

    trends.push({
      market,
      type: 'market_trend',
      description: `${marketName(market)}整体${marketTrend}，上涨占比${Math.round(ratio*100)}%`,
      confidence: marketConfidence,
      items: []
    });

    // 个股趋势：涨幅超过3%的标的
    const strongItems = items.filter(d => d.change_pct > 3);
    strongItems.forEach(item => {
      trends.push({
        market,
        type: 'individual_strong',
        symbol: item.symbol,
        name: item.name,
        description: `${item.name}(${item.symbol})涨幅${item.change_pct}%，表现强势`,
        confidence: item.change_pct > 5 ? '高' : '中',
        price: item.price,
        change_pct: item.change_pct
      });
    });

    // 个股趋势：跌幅超过3%的标的
    const weakItems = items.filter(d => d.change_pct < -3);
    weakItems.forEach(item => {
      trends.push({
        market,
        type: 'individual_weak',
        symbol: item.symbol,
        name: item.name,
        description: `${item.name}(${item.symbol})跌幅${item.change_pct}%，表现疲弱`,
        confidence: item.change_pct < -5 ? '高' : '中',
        price: item.price,
        change_pct: item.change_pct
      });
    });
  }

  return trends;
}

// 机会提示引擎
function findOpportunities(grouped) {
  const opportunities = [];

  for (const [market, items] of Object.entries(grouped)) {
    if (!items || items.length === 0) continue;

    // 低吸机会：跌幅较大但基本面尚可的标的
    const dipItems = items.filter(d => d.change_pct < -3 && d.change_pct > -8);
    dipItems.forEach(item => {
      opportunities.push({
        market,
        type: 'dip_buying',
        symbol: item.symbol,
        name: item.name,
        description: `${item.name}回调${Math.abs(item.change_pct)}%，关注低吸机会`,
        confidence: Math.abs(item.change_pct) > 5 ? '低' : '中',
        price: item.price,
        change_pct: item.change_pct
      });
    });

    // 突破信号：涨幅温和(1.5-3%)但量能放大的标的
    const breakoutItems = items.filter(d => d.change_pct > 1.5 && d.change_pct < 3);
    breakoutItems.forEach(item => {
      opportunities.push({
        market,
        type: 'breakout_watch',
        symbol: item.symbol,
        name: item.name,
        description: `${item.name}温和上涨${item.change_pct}%，留意突破信号`,
        confidence: '低',
        price: item.price,
        change_pct: item.change_pct
      });
    });

    // 跨市场联动：数字货币与大宗商品关联
    if (market === 'crypto') {
      const btc = items.find(d => d.symbol === 'BTC');
      if (btc && btc.change_pct > 2) {
        opportunities.push({
          market: 'crypto',
          type: 'correlation',
          symbol: 'BTC',
          name: '比特币',
          description: `BTC领涨${btc.change_pct}%，关注主流币联动机会`,
          confidence: '中',
          price: btc.price,
          change_pct: btc.change_pct
        });
      }
    }
  }

  return opportunities;
}

// 风险预警引擎
function detectRisks(grouped) {
  const risks = [];

  for (const [market, items] of Object.entries(grouped)) {
    if (!items || items.length === 0) continue;

    // 暴跌预警
    const crashItems = items.filter(d => d.change_pct < -5);
    crashItems.forEach(item => {
      risks.push({
        market,
        type: 'crash_warning',
        symbol: item.symbol,
        name: item.name,
        description: `${item.name}暴跌${Math.abs(item.change_pct)}%，风险极高`,
        confidence: '高',
        price: item.price,
        change_pct: item.change_pct
      });
    });

    // 市场系统性风险
    const downRatio = items.filter(d => d.change_pct < 0).length / items.length;
    if (downRatio > 0.8) {
      risks.push({
        market,
        type: 'systemic_risk',
        symbol: 'ALL',
        name: marketName(market) + '整体',
        description: `${marketName(market)}超过80%标的下跌，存在系统性风险`,
        confidence: '高'
      });
    }

    // 数字货币特别风险
    if (market === 'crypto') {
      const btc = items.find(d => d.symbol === 'BTC');
      if (btc && btc.change_pct < -3) {
        risks.push({
          market,
          type: 'btc_decline',
          symbol: 'BTC',
          name: '比特币',
          description: `BTC下跌${Math.abs(btc.change_pct)}%，可能带动整体币市回调`,
          confidence: '高',
          price: btc.price,
          change_pct: btc.change_pct
        });
      }
    }
  }

  return risks;
}

function marketName(m) {
  const names = { us: '美股', cn: 'A股', crypto: '数字货币', commodity: '大宗商品' };
  return names[m] || m;
}

async function run() {
  console.log('[Analyze Scheduler] 开始分析生成...');

  const today = new Date().toISOString().split('T')[0];
  const processedPath = path.join(__dirname, '..', '..', 'data', `processed_${today}.json`);

  if (!fs.existsSync(processedPath)) {
    console.log('[Analyze Scheduler] 无清洗数据，跳过分析');
    return;
  }

  const processed = JSON.parse(fs.readFileSync(processedPath, 'utf-8'));

  // 生成三大维度分析
  const trends = analyzeTrends(processed.grouped);
  const opportunities = findOpportunities(processed.grouped);
  const risks = detectRisks(processed.grouped);

  const analysis = {
    date: today,
    trends,
    opportunities,
    risks,
    summary: processed.summary
  };

  // 保存分析结果
  const outputPath = path.join(__dirname, '..', '..', 'data', `analysis_${today}.json`);
  fs.writeFileSync(outputPath, JSON.stringify(analysis, null, 2));

  console.log(`[Analyze Scheduler] 分析完成: ${trends.length} 趋势, ${opportunities.length} 机会, ${risks.length} 风险`);
  return analysis;
}

module.exports = { run };
