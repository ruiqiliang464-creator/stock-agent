const fs = require('fs');
const path = require('path');

function marketName(m) {
  const names = { us: '美股', cn: 'A股', crypto: '数字货币', commodity: '大宗商品' };
  return names[m] || m;
}

function marketIcon(m) {
  const icons = { us: '🇺🇸', cn: '🇨🇳', crypto: '🪙', commodity: '📊' };
  return icons[m] || '📈';
}

function confidenceColor(c) {
  const colors = { '高': '#22c55e', '中': '#f59e0b', '低': '#ef4444' };
  return colors[c] || '#6b7280';
}

function confidenceBg(c) {
  const colors = { '高': '#dcfce7', '中': '#fef3c7', '低': '#fee2e2' };
  return colors[c] || '#f3f4f6';
}

// 生成涨跌排行表格
function generateRankTable(items, title, ascending = false) {
  const sorted = [...items].sort((a, b) =>
    ascending ? a.change_pct - b.change_pct : b.change_pct - a.change_pct
  );
  const top5 = sorted.slice(0, 5);

  if (top5.length === 0) return '';

  let rows = top5.map(item => {
    const isUp = item.change_pct > 0;
    const color = isUp ? '#dc2626' : '#16a34a'; // 涨红跌绿（中国惯例）
    const arrow = isUp ? '↑' : '↓';
    return `<tr>
      <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">${item.name}</td>
      <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#888">${item.symbol}</td>
      <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;font-weight:500">${item.price.toFixed(2)}</td>
      <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:${color};font-weight:500">${arrow} ${item.change_pct.toFixed(2)}%</td>
    </tr>`;
  }).join('');

  return `<table style="width:100%;border-collapse:collapse;margin:12px 0">
    <thead><tr style="background:#f8fafc">
      <th style="padding:8px 12px;text-align:left;font-size:12px;color:#666;font-weight:500">名称</th>
      <th style="padding:8px 12px;text-align:left;font-size:12px;color:#666;font-weight:500">代码</th>
      <th style="padding:8px 12px;text-align:left;font-size:12px;color:#666;font-weight:500">价格</th>
      <th style="padding:8px 12px;text-align:left;font-size:12px;color:#666;font-weight:500">涨跌幅</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

// 生成分析条目
function generateAnalysisItems(items, type) {
  if (!items || items.length === 0) return '<p style="color:#999;font-size:13px;padding:8px 0">暂无信号</p>';

  return items.slice(0, 5).map(item => {
    const conf = item.confidence || '低';
    return `<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #f1f5f9">
      <span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500;color:${confidenceColor(conf)};background:${confidenceBg(conf)}">置信度:${conf}</span>
      <span style="font-size:13px;color:#333">${item.description}</span>
    </div>`;
  }).join('');
}

function generateReport(analysis) {
  const today = analysis.date;
  const dateDisplay = today.replace(/-/g, '/');

  // 四大市场概览
  let marketSections = '';
  for (const market of ['us', 'cn', 'crypto', 'commodity']) {
    const data = analysis.grouped?.[market] || [];
    const summary = analysis.summary?.[market];

    if (!summary) continue;

    const upRatio = Math.round((summary.upCount / summary.total) * 100);

    // 涨跌颜色（涨红跌绿）
    const avgColor = summary.avgChange > 0 ? '#dc2626' : '#16a34a';
    const avgSign = summary.avgChange > 0 ? '+' : '';

    marketSections += `
    <div style="background:#f8fafc;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #e5e7eb">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <h3 style="font-size:14px;font-weight:500;margin:0">${marketIcon(market)} ${marketName(market)}</h3>
        <span style="font-size:12px;color:#888">涨跌比 ${summary.upCount}:${summary.downCount} | 上涨占比 ${upRatio}%</span>
      </div>
      <div style="display:flex;gap:16px;margin-bottom:8px">
        <div style="flex:1;text-align:center;padding:8px;background:#fff;border-radius:8px">
          <div style="font-size:11px;color:#999">平均涨跌幅</div>
          <div style="font-size:18px;font-weight:500;color:${avgColor}">${avgSign}${summary.avgChange.toFixed(2)}%</div>
        </div>
        <div style="flex:1;text-align:center;padding:8px;background:#fff;border-radius:8px">
          <div style="font-size:11px;color:#999">领涨标的</div>
          <div style="font-size:14px;font-weight:500;color:#dc2626">${summary.maxUp?.name || '-'} +${summary.maxUp?.change_pct?.toFixed(2) || '0'}%</div>
        </div>
        <div style="flex:1;text-align:center;padding:8px;background:#fff;border-radius:8px">
          <div style="font-size:11px;color:#999">领跌标的</div>
          <div style="font-size:14px;font-weight:500;color:#16a34a">${summary.maxDown?.name || '-'} ${summary.maxDown?.change_pct?.toFixed(2) || '0'}%</div>
        </div>
      </div>
      ${generateRankTable(data, '涨幅TOP5', false)}
      ${generateRankTable(data, '跌幅TOP5', true)}
    </div>`;
  }

  // 趋势分析
  const trendItems = analysis.trends?.filter(t => t.type === 'market_trend') || [];
  const trendSection = `
    <div style="background:#f8fafc;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #e5e7eb">
      <h3 style="font-size:14px;font-weight:500;margin:0 0 12px 0">📈 趋势分析</h3>
      ${generateAnalysisItems(trendItems, 'trend')}
    </div>`;

  // 机会提示
  const oppItems = analysis.opportunities || [];
  const oppSection = `
    <div style="background:#f0fdf4;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #bbf7d0">
      <h3 style="font-size:14px;font-weight:500;margin:0 0 12px 0;color:#16a34a">💡 机会提示</h3>
      ${generateAnalysisItems(oppItems, 'opportunity')}
    </div>`;

  // 风险预警
  const riskItems = analysis.risks || [];
  const riskSection = `
    <div style="background:#fef2f2;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #fecaca">
      <h3 style="font-size:14px;font-weight:500;margin:0 0 12px 0;color:#dc2626">⚠️ 风险预警</h3>
      ${generateAnalysisItems(riskItems, 'risk')}
    </div>`;

  // 置信度说明
  const confidenceExplain = `
    <div style="background:#f8fafc;border-radius:12px;padding:12px;margin-bottom:16px;border:1px solid #e5e7eb;font-size:12px;color:#666">
      <p style="margin:0"><strong>置信度说明</strong>：
        <span style="color:#22c55e;font-weight:500">高</span> = 多信号确认或异常波动显著；
        <span style="color:#f59e0b;font-weight:500">中</span> = 单信号较强支撑；
        <span style="color:#ef4444;font-weight:500">低</span> = 信号较弱仅供参考
      </p>
    </div>`;

  const html = `
  <div style="max-width:600px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#fff;color:#333;line-height:1.6">
    <div style="background:linear-gradient(135deg,#1e40af,#3b82f6);border-radius:12px 12px 0 0;padding:24px;text-align:center">
      <h1 style="color:#fff;font-size:20px;margin:0;font-weight:500">每日市场情报</h1>
      <p style="color:#e0e7ff;font-size:14px;margin:8px 0 0">${dateDisplay}</p>
    </div>

    <div style="padding:20px">
      ${marketSections}
      ${trendSection}
      ${oppSection}
      ${riskSection}
      ${confidenceExplain}

      <div style="text-align:center;padding:16px;font-size:11px;color:#999;border-top:1px solid #e5e7eb;margin-top:8px">
        Stock Agent 每日推送 | 数据仅供参考，不构成投资建议 | ${dateDisplay}
      </div>
    </div>
  </div>`;

  return html;
}

function generateSummary(analysis) {
  const lines = [];
  for (const market of ['us', 'cn', 'crypto', 'commodity']) {
    const s = analysis.summary?.[market];
    if (s) {
      lines.push(`${marketName(market)}: 平均${s.avgChange > 0 ? '+' : ''}${s.avgChange.toFixed(2)}%, 涨跌比${s.upCount}:${s.downCount}`);
    }
  }
  if (analysis.risks?.length > 0) lines.push(`风险预警: ${analysis.risks.length}条`);
  if (analysis.opportunities?.length > 0) lines.push(`机会提示: ${analysis.opportunities.length}条`);
  return lines.join(' | ');
}

module.exports = { generateReport, generateSummary };
