"""
formatter.py — 报告生成 + 邮件发送 (Python版)

从 Node.js 版 formatter/report.js + runner-github.js 邮件部分移植
"""

import json
import smtplib
import base64
import io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from email.header import Header
from datetime import datetime

MARKET_NAMES = {'us': '美股', 'cn': 'A股', 'crypto': '数字货币', 'commodity': '大宗商品'}
MARKET_ICONS = {'us': '🇺🇸', 'cn': '🇨🇳', 'crypto': '🪙', 'commodity': '📊'}
CONFIDENCE_COLORS = {'高': '#22c55e', '中': '#f59e0b', '低': '#ef4444'}
CONFIDENCE_BG = {'高': '#dcfce7', '中': '#fef3c7', '低': '#fee2e2'}


def generate_rank_table(items, title, ascending=False):
    """生成涨跌排行表格"""
    sorted_items = sorted(items, key=lambda x: x['change_pct'], reverse=not ascending)
    top5 = sorted_items[:5]

    if not top5:
        return ''

    rows = ''
    for item in top5:
        is_up = item['change_pct'] > 0
        color = '#dc2626' if is_up else '#16a34a'  # 涨红跌绿
        arrow = '↑' if is_up else '↓'
        price_str = f'{item["price"]:.2f}' if item['price'] > 1 else f'{item["price"]:.6f}'
        rows += f'''<tr>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">{item['name']}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#888">{item['symbol']}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;font-weight:500">{price_str}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:{color};font-weight:500">{arrow} {item['change_pct']:.2f}%</td>
        </tr>'''

    return f'''<table style="width:100%;border-collapse:collapse;margin:12px 0">
        <thead><tr style="background:#f8fafc">
            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#666;font-weight:500">名称</th>
            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#666;font-weight:500">代码</th>
            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#666;font-weight:500">价格</th>
            <th style="padding:8px 12px;text-align:left;font-size:12px;color:#666;font-weight:500">涨跌幅</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>'''


def generate_analysis_items(items, type_name):
    """生成分析条目"""
    if not items:
        return '<p style="color:#999;font-size:13px;padding:8px 0">暂无信号</p>'

    result = ''
    for item in items[:5]:
        conf = item.get('confidence', '低')
        conf_color = CONFIDENCE_COLORS.get(conf, '#6b7280')
        conf_bg = CONFIDENCE_BG.get(conf, '#f3f4f6')
        result += f'''<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #f1f5f9">
            <span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500;color:{conf_color};background:{conf_bg}">置信度:{conf}</span>
            <span style="font-size:13px;color:#333">{item['description']}</span>
        </div>'''
    return result


def generate_market_summary_section(analysis):
    """生成市场大盘总结区块 HTML — 总结前一天市场数据"""
    summary = analysis.get('summary', {})
    if not summary:
        return ''

    cards = ''
    for market in ['us', 'cn', 'crypto', 'commodity']:
        s = summary.get(market)
        if not s:
            continue

        avg = s.get('avgChange', 0)
        avg_color = '#dc2626' if avg > 0 else '#16a34a'
        avg_sign = '+' if avg > 0 else ''
        icon = MARKET_ICONS.get(market, '')
        name = MARKET_NAMES.get(market, market)

        max_up = s.get('maxUp', {})
        max_down = s.get('maxDown', {})
        up_count = s.get('upCount', 0)
        down_count = s.get('downCount', 0)

        cards += f'''
        <div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #f1f5f9">
            <span style="font-size:16px">{icon}</span>
            <div style="flex:1">
                <div style="font-size:13px;font-weight:500;color:#1e293b">{name}</div>
                <div style="font-size:11px;color:#94a3b8">涨{up_count} 跌{down_count} | 领涨: {max_up.get('name','-')} +{max_up.get('change_pct',0):.1f}% | 领跌: {max_down.get('name','-')} {max_down.get('change_pct',0):.1f}%</div>
            </div>
            <div style="font-size:16px;font-weight:600;color:{avg_color}">{avg_sign}{avg:.2f}%</div>
        </div>'''

    return f'''
    <div style="background:#f0f9ff;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #bae6fd">
        <h3 style="font-size:15px;font-weight:600;margin:0 0 8px 0;color:#0369a1">📋 市场大盘总结</h3>
        <p style="font-size:12px;color:#0284c7;margin:0 0 12px 0">前一交易日全球主要市场数据概览</p>
        {cards}
    </div>'''


def generate_news_section(news_items):
    """生成今日要闻区块 HTML — 带分类标签和影响分析"""
    if not news_items:
        return ''

    cards = ''
    for i, item in enumerate(news_items):
        title = item.get('title', '')
        title_zh = item.get('title_zh', '')
        summary = item.get('summary', '')
        summary_zh = item.get('summary_zh', '')
        source = item.get('source', '')
        news_time = item.get('time', '')
        analysis = item.get('analysis', '')
        cat_label = item.get('category_label', '')
        cat_icon = item.get('category_icon', '')
        cat_color = item.get('category_color', '#6b7280')
        cat_bg = item.get('category_bg', '#f3f4f6')

        # 分类标签
        cat_badge = f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500;color:{cat_color};background:{cat_bg};margin-bottom:6px">{cat_icon} {cat_label}</span>' if cat_label else ''

        # 来源+时间
        meta_badge = f'<span style="font-size:11px;color:#94a3b8">来源: {source}' + (f' &middot; {news_time}' if news_time else '') + '</span>'

        # 中文标题 (如有翻译)
        title_zh_html = f'<div style="font-size:13px;font-weight:500;color:#475569;margin-bottom:4px">{title_zh}</div>' if title_zh and title_zh != title else ''

        # 中文摘要 (如有翻译)
        summary_zh_html = f'<div style="font-size:12px;color:#94a3b8;line-height:1.5;margin-top:4px">{summary_zh}</div>' if summary_zh and summary_zh != summary else ''

        # 影响分析 (如果有)
        analysis_html = f'''<div style="margin-top:6px;padding:6px 10px;background:#f8fafc;border-radius:6px;border-left:3px solid {cat_color}">
            <div style="font-size:11px;color:#64748b;margin-bottom:2px">📊 影响分析</div>
            <div style="font-size:12px;color:#475569;line-height:1.5">{analysis}</div>
        </div>''' if analysis else ''

        cards += f'''
        <div style="display:flex;gap:12px;padding:12px 0;border-bottom:1px solid #e5e7eb">
            <div style="flex-shrink:0;width:24px;height:24px;border-radius:50%;background:#1e40af;color:#fff;font-size:12px;font-weight:600;display:flex;align-items:center;justify-content:center">{i+1}</div>
            <div style="flex:1">
                {cat_badge}
                <div style="font-size:14px;font-weight:500;color:#1e293b;margin-bottom:4px">{title}</div>
                {title_zh_html}
                <div style="font-size:13px;color:#64748b;line-height:1.5">{summary}</div>
                {summary_zh_html}
                {analysis_html}
                <div style="margin-top:4px">{meta_badge}</div>
            </div>
        </div>'''

    return f'''
    <div style="background:#fffbeb;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #fde68a">
        <h3 style="font-size:15px;font-weight:600;margin:0 0 8px 0;color:#92400e">📰 今日要闻</h3>
        <p style="font-size:12px;color:#b45309;margin:0 0 12px 0">以下为过去24小时内可能影响市场走势的重大新闻，含分类标签与影响分析</p>
        {cards}
    </div>'''


def generate_report(analysis, news_items=None):
    """生成HTML邮件报告"""
    if news_items is None:
        news_items = []

    today = analysis.get('date', '')
    date_display = today.replace('-', '/')

    # 四大市场概览
    market_sections = ''
    for market in ['us', 'cn', 'crypto', 'commodity']:
        data = analysis.get('grouped', {}).get(market, [])
        summary = analysis.get('summary', {}).get(market)

        if not summary:
            continue

        up_ratio = round(summary['upCount'] / summary['total'] * 100) if summary['total'] > 0 else 0
        avg_color = '#dc2626' if summary['avgChange'] > 0 else '#16a34a'
        avg_sign = '+' if summary['avgChange'] > 0 else ''

        market_sections += f'''
        <div style="background:#f8fafc;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #e5e7eb">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
                <h3 style="font-size:14px;font-weight:500;margin:0">{MARKET_ICONS[market]} {MARKET_NAMES[market]}</h3>
                <span style="font-size:12px;color:#888">涨跌比 {summary['upCount']}:{summary['downCount']} | 上涨占比 {up_ratio}%</span>
            </div>
            <div style="display:flex;gap:16px;margin-bottom:8px">
                <div style="flex:1;text-align:center;padding:8px;background:#fff;border-radius:8px">
                    <div style="font-size:11px;color:#999">平均涨跌幅</div>
                    <div style="font-size:18px;font-weight:500;color:{avg_color}">{avg_sign}{summary['avgChange']:.2f}%</div>
                </div>
                <div style="flex:1;text-align:center;padding:8px;background:#fff;border-radius:8px">
                    <div style="font-size:11px;color:#999">领涨标的</div>
                    <div style="font-size:14px;font-weight:500;color:#dc2626">{summary.get('maxUp', {}).get('name', '-')} +{summary.get('maxUp', {}).get('change_pct', 0):.2f}%</div>
                </div>
                <div style="flex:1;text-align:center;padding:8px;background:#fff;border-radius:8px">
                    <div style="font-size:11px;color:#999">领跌标的</div>
                    <div style="font-size:14px;font-weight:500;color:#16a34a">{summary.get('maxDown', {}).get('name', '-')} {summary.get('maxDown', {}).get('change_pct', 0):.2f}%</div>
                </div>
            </div>
            {generate_rank_table(data, '涨幅TOP5', False)}
            {generate_rank_table(data, '跌幅TOP5', True)}
        </div>'''

    # 趋势分析
    trend_items = [t for t in analysis.get('trends', []) if t.get('type') == 'market_trend']
    trend_section = f'''
        <div style="background:#f8fafc;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #e5e7eb">
            <h3 style="font-size:14px;font-weight:500;margin:0 0 12px 0">📈 趋势分析</h3>
            {generate_analysis_items(trend_items, 'trend')}
        </div>'''

    # 机会提示
    opp_items = analysis.get('opportunities', [])
    opp_section = f'''
        <div style="background:#f0fdf4;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #bbf7d0">
            <h3 style="font-size:14px;font-weight:500;margin:0 0 12px 0;color:#16a34a">💡 机会提示</h3>
            {generate_analysis_items(opp_items, 'opportunity')}
        </div>'''

    # 风险预警
    risk_items = analysis.get('risks', [])
    risk_section = f'''
        <div style="background:#fef2f2;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #fecaca">
            <h3 style="font-size:14px;font-weight:500;margin:0 0 12px 0;color:#dc2626">⚠️ 风险预警</h3>
            {generate_analysis_items(risk_items, 'risk')}
        </div>'''

    # 置信度说明
    confidence_explain = '''
        <div style="background:#f8fafc;border-radius:12px;padding:12px;margin-bottom:16px;border:1px solid #e5e7eb;font-size:12px;color:#666">
            <p style="margin:0"><strong>置信度说明</strong>：
                <span style="color:#22c55e;font-weight:500">高</span> = 多信号确认或异常波动显著；
                <span style="color:#f59e0b;font-weight:500">中</span> = 单信号较强支撑；
                <span style="color:#ef4444;font-weight:500">低</span> = 信号较弱仅供参考
            </p>
        </div>'''

    # 数据来源说明
    source_note = '''
        <div style="background:#f8fafc;border-radius:12px;padding:12px;margin-bottom:16px;border:1px solid #e5e7eb;font-size:12px;color:#888">
            <p style="margin:0"><strong>数据来源</strong>：美股(yfinance/CNBC) | A股(akshare/同花顺) | 数字货币(Binance) | 大宗商品(akshare/yfinance) | 要闻(CNBC/MarketWatch/Yahoo Finance/Google News/BBC/Seeking Alpha等RSS)</p>
        </div>'''

    html = f'''
    <div style="max-width:600px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#fff;color:#333;line-height:1.6">
        <div style="background:linear-gradient(135deg,#1e40af,#3b82f6);border-radius:12px 12px 0 0;padding:24px;text-align:center">
            <h1 style="color:#fff;font-size:20px;margin:0;font-weight:500">每日市场情报</h1>
            <p style="color:#e0e7ff;font-size:14px;margin:8px 0 0">{date_display}</p>
        </div>

        <div style="padding:20px">
            {generate_market_summary_section(analysis)}
            {generate_news_section(news_items)}
            {market_sections}
            {trend_section}
            {opp_section}
            {risk_section}
            {confidence_explain}
            {source_note}

            <div style="text-align:center;padding:16px;font-size:11px;color:#999;border-top:1px solid #e5e7eb;margin-top:8px">
                Stock Agent 每日推送 | 数据仅供参考，不构成投资建议 | {date_display}
            </div>
        </div>
    </div>'''

    return html


def generate_summary(analysis):
    """生成简要文字摘要"""
    lines = []
    for market in ['us', 'cn', 'crypto', 'commodity']:
        s = analysis.get('summary', {}).get(market)
        if s:
            sign = '+' if s['avgChange'] > 0 else ''
            lines.append(f"{MARKET_NAMES[market]}: 平均{sign}{s['avgChange']:.2f}%, 涨跌比{s['upCount']}:{s['downCount']}")

    risks = analysis.get('risks', [])
    opps = analysis.get('opportunities', [])
    if risks:
        lines.append(f"风险预警: {len(risks)}条")
    if opps:
        lines.append(f"机会提示: {len(opps)}条")

    return ' | '.join(lines)


def format_number_yi(val):
    """格式化亿元数值"""
    if val is None:
        return '-'
    if abs(val) >= 100:
        return f'{val:.0f}亿'
    elif abs(val) >= 10:
        return f'{val:.1f}亿'
    else:
        return f'{val:.2f}亿'


# ── 个股走势折线图 (matplotlib, 供 PDF 嵌入；weasyprint 不执行 JS 故不用 ECharts) ──
_CJK_FONT_CACHE = None


def _get_cjk_font():
    """探测一个可用的中文字体名, 找不到返回 None(标题回退为代码避免方块)。"""
    global _CJK_FONT_CACHE
    if _CJK_FONT_CACHE is not None:
        return _CJK_FONT_CACHE or None
    _CJK_FONT_CACHE = ''  # 标记已探测
    try:
        from matplotlib.font_manager import fontManager
        available = {f.name for f in fontManager.ttflist}
        for kw in ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK', 'WenQuanYi Micro Hei',
                   'WenQuanYi Zen Hei', 'Source Han Sans', 'PingFang', 'Heiti',
                   'Noto Serif CJK', 'Source Han Serif', 'AR PL UMing', 'AR PL UKai',
                   'Droid Sans Fallback']:
            for a in available:
                if kw.lower() in a.lower():
                    _CJK_FONT_CACHE = a
                    return a
    except Exception:
        pass
    return None


def _render_stock_line_png(item):
    """画近30日收盘价折线图, 标注20日高/低点与最新价, 返回 PNG bytes。失败返回 None。"""
    series = item.get('close_series') or []
    if not series or len(series) < 2:
        return None
    dates = item.get('date_series') or list(range(1, len(series) + 1))
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties
    except Exception as e:
        print(f'[Report] matplotlib 不可用, 跳过折线图: {e}')
        return None
    cjk = _get_cjk_font()
    fp = FontProperties(family=cjk) if cjk else None
    fig, ax = plt.subplots(figsize=(4.0, 1.85), dpi=135)
    x = list(range(len(series)))
    lo_all, hi_all = min(series), max(series)
    pad = (hi_all - lo_all) * 0.12 if hi_all > lo_all else max(abs(hi_all) * 0.02, 0.05)
    ax.plot(x, series, color='#2563eb', linewidth=1.5, zorder=3)
    ax.fill_between(x, series, lo_all - pad, color='#2563eb', alpha=0.08, zorder=1)
    hi20 = item.get('high20')
    lo20 = item.get('low20')
    if hi20 is not None:
        ax.axhline(hi20, color='#dc2626', linewidth=0.7, linestyle='--', alpha=0.7)
    if lo20 is not None:
        ax.axhline(lo20, color='#16a34a', linewidth=0.7, linestyle='--', alpha=0.7)
    ax.scatter([x[-1]], [series[-1]], color='#dc2626', s=16, zorder=5)
    name = item.get('name') or ''
    code = item.get('code') or ''
    title = (f'{name} {code}') if (cjk and name) else (code or name)
    ax.set_title(title, fontsize=8.5, color='#1e293b', pad=3, fontproperties=fp)
    ax.set_ylim(lo_all - pad, hi_all + pad)
    ax.tick_params(axis='both', labelsize=6, colors='#94a3b8')
    try:
        t = [0, len(dates) // 2, len(dates) - 1]
        ax.set_xticks(t)
        ax.set_xticklabels([str(dates[i]) for i in t], fontsize=6, fontproperties=fp)
    except Exception:
        pass
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#cbd5e1')
    ax.grid(axis='y', linestyle=':', linewidth=0.4, color='#e2e8f0')
    fig.tight_layout(pad=0.35)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return buf.getvalue()


def _stock_line_img_tag(item):
    """渲染个股折线图并返回 <img> 标签(base64 嵌入), 无数据返回空串。"""
    png = _render_stock_line_png(item)
    if not png:
        return ''
    b64 = base64.b64encode(png).decode('ascii')
    alt = item.get('name') or item.get('code') or ''
    return (f'<img alt="{alt}" src="data:image/png;base64,{b64}" '
            f'style="width:100%;display:block;border:1px solid #e2e8f0;border-radius:6px"/>')


def generate_review_report(review_data):
    """生成市场复盘与异动简报 HTML邮件"""
    today = review_data.get('date', '')
    date_display = today.replace('-', '年').replace('-', '月') + '日' if '-' in today else today

    summary = review_data.get('summary', '')
    indices = review_data.get('indices', [])
    breadth = review_data.get('market_breadth', {})
    northbound = review_data.get('northbound', {})
    margin = review_data.get('margin', {})
    sector_flow = review_data.get('sector_flow', [])
    signals = review_data.get('signals', {})
    anomalies = review_data.get('anomalies', [])
    tomorrow_focus = review_data.get('tomorrow_focus', [])

    # ── Phase A 新增字段提取 ──
    intl_indices = review_data.get('intl_indices', [])
    etf_flow = review_data.get('etf_flow', [])
    sentiment_pools = review_data.get('sentiment_pools', {})
    track_crowding = review_data.get('track_crowding', [])
    price_volume_anomalies = review_data.get('price_volume_anomalies', [])
    lhb_capital = review_data.get('lhb_capital', {})
    stock_rank = review_data.get('stock_rank', {})

    # ── Batch C 新增字段提取 ──
    market_events = review_data.get('market_events', {})
    stock_technicals = review_data.get('stock_technicals', [])

    # ── 1. 市场概况 ──
    index_cards = ''
    total_amount_yi = 0
    for idx in indices:
        pct = idx.get('change_pct', 0)
        color = '#dc2626' if pct > 0 else '#16a34a' if pct < 0 else '#6b7280'
        sign = '+' if pct > 0 else ''
        close = idx.get('close', 0)
        amount = idx.get('amount', 0)
        total_amount_yi += amount / 1e8 if amount else 0
        index_cards += f'''
        <div style="flex:1;text-align:center;padding:10px;background:#fff;border-radius:8px;border:1px solid #e5e7eb">
            <div style="font-size:11px;color:#94a3b8;margin-bottom:2px">{idx.get('name','')}</div>
            <div style="font-size:16px;font-weight:600;color:#1e293b">{close:.2f}</div>
            <div style="font-size:13px;font-weight:500;color:{color}">{sign}{pct:.2f}%</div>
        </div>'''

    breadth_html = ''
    if breadth:
        advance = breadth.get('advance_count', 0)
        decline = breadth.get('decline_count', 0)
        flat = breadth.get('flat_count', 0)
        limit_up = breadth.get('limit_up_count', 0)
        limit_down = breadth.get('limit_down_count', 0)
        breadth_html = f'''
        <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
            <span style="padding:3px 10px;border-radius:4px;font-size:12px;color:#dc2626;background:#fee2e2">涨停 {limit_up}</span>
            <span style="padding:3px 10px;border-radius:4px;font-size:12px;color:#16a34a;background:#dcfce7">跌停 {limit_down}</span>
            <span style="padding:3px 10px;border-radius:4px;font-size:12px;color:#dc2626;background:#fef2f2">上涨 {advance}</span>
            <span style="padding:3px 10px;border-radius:4px;font-size:12px;color:#16a34a;background:#f0fdf4">下跌 {decline}</span>
            <span style="padding:3px 10px;border-radius:4px;font-size:12px;color:#6b7280;background:#f3f4f6">平盘 {flat}</span>
        </div>'''

    # ── 1.1 国际指数 ──
    intl_cards = ''
    if intl_indices:
        for idx in intl_indices:
            pct = idx.get('change_pct', 0)
            color = '#dc2626' if pct > 0 else '#16a34a' if pct < 0 else '#6b7280'
            sign = '+' if pct > 0 else ''
            intl_cards += f'''
            <div style="flex:1;text-align:center;padding:8px;background:#fff;border-radius:8px;border:1px solid #e5e7eb">
                <div style="font-size:11px;color:#94a3b8;margin-bottom:2px">{idx.get('name','')}</div>
                <div style="font-size:15px;font-weight:600;color:#1e293b">{idx.get('close',0):.2f}</div>
                <div style="font-size:12px;font-weight:500;color:{color}">{sign}{pct:.2f}%</div>
            </div>'''
        intl_block = f'''
        <div style="margin-top:10px">
            <div style="font-size:12px;color:#64748b;margin-bottom:6px">国际指数</div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">{intl_cards}</div>
        </div>'''
    else:
        intl_block = ''

    overview_section = f'''
    <div style="background:#f8fafc;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #e5e7eb">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 12px 0;color:#1e293b">一、市场概况</h3>
        <div style="display:flex;gap:8px;margin-bottom:8px">{index_cards if index_cards else '<p style="color:#999;font-size:13px">指数数据暂不可用</p>'}</div>
        {breadth_html}
        {intl_block}
        {f'<div style="margin-top:8px;font-size:12px;color:#64748b">两市合计成交约 <strong style="color:#1e293b">{total_amount_yi:.0f}亿元</strong></div>' if total_amount_yi > 0 else ''}
    </div>'''

    # ── 2. 资金与微观结构 ──
    capital_parts = []

    # 北向资金
    if northbound and northbound.get('amount_yi', 0) > 0:
        nb_metric = northbound.get('metric', 'net_buy')
        if nb_metric == 'deal_amount':
            # 净买额因港交所披露调整暂停披露, 展示成交总额
            amt = northbound.get('amount_yi', 0)
            capital_parts.append(f'''
        <div style="display:flex;align-items:center;padding:8px 0;border-bottom:1px solid #f1f5f9">
            <span style="font-size:13px;color:#475569;width:80px">北向成交</span>
            <span style="font-size:14px;font-weight:600;color:#1e293b">成交额 {amt:.0f}亿</span>
            <span style="font-size:11px;color:#94a3b8;margin-left:8px">净买额因港交所披露调整暂停披露</span>
        </div>''')
        else:
            nb = northbound.get('net_buy_yi', 0)
            nb_color = '#dc2626' if nb > 0 else '#16a34a'
            nb_label = '净买入' if nb > 0 else '净卖出'
            extreme_badge = ''
            if northbound.get('is_extreme'):
                extreme_badge = '<span style="padding:2px 6px;border-radius:4px;font-size:10px;color:#fff;background:#f59e0b;margin-left:6px">极端值</span>'
            capital_parts.append(f'''
        <div style="display:flex;align-items:center;padding:8px 0;border-bottom:1px solid #f1f5f9">
            <span style="font-size:13px;color:#475569;width:80px">北向资金</span>
            <span style="font-size:14px;font-weight:600;color:{nb_color}">{nb_label} {abs(nb):.2f}亿</span>{extreme_badge}
        </div>''')

    # 两融
    if margin and margin.get('total_balance_yi'):
        change = margin.get('balance_change_yi', 0)
        change_color = '#dc2626' if change > 0 else '#16a34a' if change < 0 else '#6b7280'
        change_sign = '+' if change > 0 else ''
        capital_parts.append(f'''
        <div style="display:flex;align-items:center;padding:8px 0;border-bottom:1px solid #f1f5f9">
            <span style="font-size:13px;color:#475569;width:80px">两融余额</span>
            <span style="font-size:14px;font-weight:500;color:#1e293b">{margin["total_balance_yi"]:.0f}亿</span>
            <span style="font-size:12px;color:{change_color};margin-left:8px">({change_sign}{change:.1f}亿)</span>
        </div>''')
        # 融资买入额 + 占比 (杠杆资金情绪)
        fb = margin.get('financing_buy_yi')
        fbr = margin.get('financing_buy_ratio_pct')
        if fb:
            fb_txt = f'{fb:.0f}亿'
            if fbr is not None:
                fb_txt += f' <span style="font-size:11px;color:#94a3b8">(占两市成交{fbr:.1f}%)</span>'
            capital_parts.append(f'''
        <div style="display:flex;align-items:center;padding:8px 0;border-bottom:1px solid #f1f5f9">
            <span style="font-size:13px;color:#475569;width:80px">融资买入</span>
            <span style="font-size:14px;font-weight:500;color:#1e293b">{fb_txt}</span>
        </div>''')

    # 行业资金流TOP5
    if sector_flow:
        top5_in = sector_flow[:5]
        top5_out = sorted(sector_flow, key=lambda x: x.get('net_inflow', 0))[:5]
        flow_rows = ''
        for s in top5_in:
            inflow = s.get('net_inflow_yi', 0)
            if inflow > 0:
                flow_rows += f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px"><span style="color:#475569">{s.get("name","")}</span><span style="color:#dc2626;font-weight:500">+{inflow:.1f}亿</span></div>'
        for s in top5_out:
            outflow = s.get('net_inflow_yi', 0)
            if outflow < 0:
                flow_rows += f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px"><span style="color:#475569">{s.get("name","")}</span><span style="color:#16a34a;font-weight:500">{outflow:.1f}亿</span></div>'

        if flow_rows:
            capital_parts.append(f'''
            <div style="margin-top:8px">
                <div style="font-size:12px;color:#64748b;margin-bottom:4px">行业资金流向TOP5</div>
                {flow_rows}
            </div>''')

    # ── 2.1 宽基 ETF 资金流向 ──
    etf_block = ''
    if etf_flow:
        rows = ''
        for e in etf_flow[:10]:
            pct = e.get('change_pct', 0) or 0
            c = '#dc2626' if pct > 0 else '#16a34a' if pct < 0 else '#6b7280'
            net = e.get('main_net_inflow_yi')
            net_s = f'{net:+.2f}亿' if net is not None else '—'
            net_c = '#dc2626' if (net or 0) > 0 else '#16a34a' if (net or 0) < 0 else '#6b7280'
            rows += f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px"><span style="color:#475569">{e.get("name","")}</span><span style="color:{c}">{pct:+.2f}%</span><span style="color:{net_c};font-weight:500">{net_s}</span></div>'
        etf_block = f'''
        <div style="margin-top:10px">
            <div style="font-size:12px;color:#64748b;margin-bottom:4px">宽基ETF资金流向</div>
            {rows}
        </div>'''

    # ── 2.2 情绪池 ──
    sentiment_block = ''
    if sentiment_pools:
        sp = sentiment_pools
        sent_items = []
        if sp.get('limit_up_count') is not None:
            sent_items.append(f'涨停 <strong>{sp["limit_up_count"]}</strong> 家')
        if sp.get('yesterday_zt_count') is not None:
            sent_items.append(f'昨日涨停 <strong>{sp["yesterday_zt_count"]}</strong> 家')
        if sp.get('zhaban_count'):
            sent_items.append(f'炸板 <strong>{sp["zhaban_count"]}</strong> 家')
        if sp.get('zhaban_rate') is not None:
            sent_items.append(f'炸板率 <strong>{sp["zhaban_rate"]}%</strong>')
        if sent_items:
            sentiment_block = f'''
        <div style="margin-top:10px;padding:8px 10px;background:#fff;border-radius:8px;border:1px solid #e5e7eb">
            <div style="font-size:12px;color:#64748b;margin-bottom:4px">涨停情绪</div>
            <div style="font-size:12px;color:#475569">{' · '.join(sent_items)}</div>
        </div>'''

    # ── 2.3 赛道拥挤度 ──
    track_block = ''
    if track_crowding:
        rows = ''
        for t in track_crowding[:8]:
            share = t.get('share_pct', 0)
            c = '#dc2626' if t.get('crowded') else '#475569'
            flag = ' ⚠拥挤' if t.get('crowded') else ''
            rows += f'<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:12px"><span style="color:#475569">{t.get("track","")}</span><span style="color:{c};font-weight:500">{share:.1f}%{flag}</span></div>'
        track_block = f'''
        <div style="margin-top:10px">
            <div style="font-size:12px;color:#64748b;margin-bottom:4px">热门赛道拥挤度(成交额占比)</div>
            {rows}
        </div>'''

    capital_section = f'''
    <div style="background:#f0f9ff;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #bae6fd">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 12px 0;color:#0369a1">二、资金与微观结构</h3>
        {''.join(capital_parts) if capital_parts else '<p style="color:#999;font-size:13px">资金数据暂不可用</p>'}
        {etf_block}
        {sentiment_block}
        {track_block}
    </div>'''

    # ── 3. 波动率与情绪 ──
    vol_parts = []
    if signals.get('volatility_percentile') is not None:
        vp = signals['volatility_percentile']
        vp_color = '#dc2626' if vp >= 75 else '#f59e0b' if vp >= 50 else '#16a34a'
        vol_parts.append(f'<div style="display:flex;justify-content:space-between;padding:6px 0"><span style="font-size:13px;color:#475569">波动率分位</span><span style="font-size:13px;font-weight:500;color:{vp_color}">{vp}% ({signals.get("volatility_desc","")})</span></div>')

    if signals.get('advance_ratio') is not None:
        ar = signals['advance_ratio']
        ar_color = '#dc2626' if ar >= 55 else '#16a34a' if ar <= 45 else '#6b7280'
        vol_parts.append(f'<div style="display:flex;justify-content:space-between;padding:6px 0"><span style="font-size:13px;color:#475569">上涨占比</span><span style="font-size:13px;font-weight:500;color:{ar_color}">{ar:.1f}%</span></div>')

    if signals.get('sentiment'):
        sent = signals['sentiment']
        sent_color = '#dc2626' if '热' in sent else '#16a34a' if '冷' in sent else '#6b7280'
        vol_parts.append(f'<div style="display:flex;justify-content:space-between;padding:6px 0"><span style="font-size:13px;color:#475569">市场情绪</span><span style="font-size:13px;font-weight:500;color:{sent_color}">{sent}</span></div>')

    # 资金流向信号
    for fs in signals.get('fund_flow_signals', []):
        vol_parts.append(f'<div style="padding:6px 0;font-size:12px;color:#f59e0b">⚠ {fs}</div>')

    volatility_section = f'''
    <div style="background:#fefce8;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #fde68a">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 12px 0;color:#92400e">三、波动率与情绪</h3>
        {''.join(vol_parts) if vol_parts else '<p style="color:#999;font-size:13px">数据暂不可用</p>'}
    </div>'''

    # ── 4. 量化异动提醒 ──
    anomaly_rows = ''
    if anomalies:
        for a in anomalies:
            sev = a.get('severity', '中')
            sev_color = '#dc2626' if sev == '高' else '#f59e0b' if sev == '中' else '#6b7280'
            sev_bg = '#fee2e2' if sev == '高' else '#fef3c7' if sev == '中' else '#f3f4f6'
            anomaly_rows += f'''
            <div style="display:flex;align-items:flex-start;gap:8px;padding:8px 0;border-bottom:1px solid #f1f5f9">
                <span style="display:inline-block;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:500;color:{sev_color};background:{sev_bg};flex-shrink:0;margin-top:2px">{sev}</span>
                <span style="font-size:12px;color:#475569;line-height:1.5">{a.get("description","")}</span>
            </div>'''
    else:
        anomaly_rows = '<p style="color:#999;font-size:13px;padding:8px 0">暂无异动信号</p>'

    anomaly_section = f'''
    <div style="background:#fef2f2;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #fecaca">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 12px 0;color:#dc2626">四、量化异动提醒</h3>
        {anomaly_rows}
    </div>'''

    # ── 5. 明日关注 ──
    focus_rows = ''
    for i, f in enumerate(tomorrow_focus):
        focus_rows += f'''
        <div style="display:flex;align-items:flex-start;gap:8px;padding:6px 0">
            <span style="color:#3b82f6;font-size:14px;flex-shrink:0">{i+1}.</span>
            <span style="font-size:13px;color:#475569;line-height:1.5">{f}</span>
        </div>'''
    if not focus_rows:
        focus_rows = '<p style="color:#999;font-size:13px">暂无</p>'

    # ── 5. 量价异动 ──
    pva_section = ''
    if price_volume_anomalies:
        by_type = {}
        for a in price_volume_anomalies:
            by_type.setdefault(a.get('type', ''), []).append(a)
        rows = ''
        for kind, lst in by_type.items():
            rows += f'<div style="font-size:12px;color:#64748b;margin:6px 0 2px">▶ {kind}（{len(lst)}只）</div>'
            for a in lst[:8]:
                c = '#dc2626' if a.get('change_pct', 0) > 0 else '#16a34a'
                rows += f'<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:12px"><span style="color:#475569">{a.get("name","")}({a.get("code","")})</span><span style="color:{c}">{a.get("change_pct",0):+.2f}%</span><span style="color:#94a3b8">量比{a.get("vol_ratio",0):.1f}</span></div>'
        pva_section = f'''
    <div style="background:#eef2ff;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #c7d2fe">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 12px 0;color:#4338ca">五、量价异动</h3>
        {rows}
    </div>'''

    # ── 6. 龙虎榜机构异动 ──
    lhb_section = ''
    if lhb_capital and lhb_capital.get('lhb_institution'):
        rows = ''
        for it in lhb_capital['lhb_institution'][:12]:
            net = it.get('inst_net_buy_yi', 0) or 0
            c = '#dc2626' if net > 0 else '#16a34a'
            rows += f'<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:12px"><span style="color:#475569">{it.get("name","")}({it.get("code","")})</span><span style="color:{c};font-weight:500">机构净买{net:+.2f}亿</span></div>'
        lhb_section = f'''
    <div style="background:#fef2f2;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #fecaca">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 12px 0;color:#dc2626">六、龙虎榜机构异动</h3>
        {rows}
    </div>'''

    # ── 7. 个股排名 (14子字段) ──
    rank_section = ''
    if stock_rank and stock_rank.get('top_inflow'):
        def _rank_row(r, with_flow=True):
            pct = r.get('change_pct') or 0
            c = '#dc2626' if pct > 0 else '#16a34a'
            net = r.get('main_net_inflow_yi')
            net_s = f'{net:+.2f}' if net is not None else '—'
            nc = '#dc2626' if (net or 0) > 0 else '#16a34a'
            cells = f'<td style="padding:4px 6px;font-size:11px;color:#475569">{r.get("name","")}</td><td style="padding:4px 6px;font-size:11px;color:#94a3b8">{r.get("industry","") or "-"}</td><td style="padding:4px 6px;font-size:11px;color:{c}">{pct:+.2f}%</td>'
            if with_flow:
                cells += f'<td style="padding:4px 6px;font-size:11px;color:{nc};font-weight:500">{net_s}亿</td>'
                n5 = r.get('net_5d_yi'); n10 = r.get('net_10d_yi')
                cells += f'<td style="padding:4px 6px;font-size:11px;color:#64748b">{n5 if n5 is not None else "-"}</td><td style="padding:4px 6px;font-size:11px;color:#64748b">{n10 if n10 is not None else "-"}</td>'
            else:
                cells += f'<td style="padding:4px 6px;font-size:11px;color:{nc};font-weight:500">{net_s}亿</td>'
            return f'<tr>{cells}</tr>'

        head_flow = '<th style="padding:4px 6px;text-align:left;font-size:11px;color:#666">名称</th><th style="padding:4px 6px;text-align:left;font-size:11px;color:#666">行业</th><th style="padding:4px 6px;text-align:left;font-size:11px;color:#666">涨跌幅</th><th style="padding:4px 6px;text-align:left;font-size:11px;color:#666">主力净流入</th><th style="padding:4px 6px;text-align:left;font-size:11px;color:#666">5日净量</th><th style="padding:4px 6px;text-align:left;font-size:11px;color:#666">10日净量</th>'
        head_simple = '<th style="padding:4px 6px;text-align:left;font-size:11px;color:#666">名称</th><th style="padding:4px 6px;text-align:left;font-size:11px;color:#666">行业</th><th style="padding:4px 6px;text-align:left;font-size:11px;color:#666">涨跌幅</th><th style="padding:4px 6px;text-align:left;font-size:11px;color:#666">主力净流入</th>'

        inflow_rows = ''.join(_rank_row(r) for r in stock_rank['top_inflow'][:15])
        gain_rows = ''.join(_rank_row(r, False) for r in stock_rank.get('top_gainers', [])[:10])
        loss_rows = ''.join(_rank_row(r, False) for r in stock_rank.get('top_losers', [])[:10])
        rank_section = f'''
    <div style="background:#f8fafc;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #e5e7eb">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 8px 0;color:#1e293b">七、个股排名（主力净流入 TOP15）</h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:10px"><thead><tr style="background:#eef2ff">{head_flow}</tr></thead><tbody>{inflow_rows}</tbody></table>
        <h3 style="font-size:13px;font-weight:600;margin:8px 0 4px;color:#16a34a">涨幅 TOP10</h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:8px"><thead><tr style="background:#f0fdf4">{head_simple}</tr></thead><tbody>{gain_rows}</tbody></table>
        <h3 style="font-size:13px;font-weight:600;margin:8px 0 4px;color:#dc2626">跌幅 TOP10</h3>
        <table style="width:100%;border-collapse:collapse"><thead><tr style="background:#fef2f2">{head_simple}</tr></thead><tbody>{loss_rows}</tbody></table>
        <div style="font-size:10px;color:#94a3b8;margin-top:6px">单位：主力净流入/净量为亿元；概念字段批次C补充；5日/10日涨幅经东财clist补充（CI验证）</div>
    </div>'''

    # ── 九、事件驱动 ──
    events_section = ''
    if market_events and market_events.get('has_data'):
        def _ev_table(title, rows, cols):
            if not rows:
                return ''
            body = ''
            for r in rows:
                tds = ''.join(f'<td style="padding:3px 6px;font-size:11px;color:#475569">{r.get(c, "-") or "-"}</td>' for h, c in cols)
                body += f'<tr>{tds}</tr>'
            head = ''.join(f'<th style="padding:3px 6px;text-align:left;font-size:11px;color:#666">{h}</th>' for h, c in cols)
            return f'<h3 style="font-size:13px;font-weight:600;margin:8px 0 4px;color:#1e40af">{title}（{len(rows)}）</h3><table style="width:100%;border-collapse:collapse;margin-bottom:8px"><thead><tr style="background:#eff6ff">{head}</tr></thead><tbody>{body}</tbody></table>'
        blocks = ''
        blocks += _ev_table('重大事项公告', market_events.get('notices', []), [('代码','code'),('名称','name'),('公告','title'),('日期','date')])
        blocks += _ev_table('财报预告', market_events.get('earnings', []), [('代码','code'),('名称','name'),('类型','type'),('日期','date')])
        blocks += _ev_table('停复牌', market_events.get('suspension', []), [('代码','code'),('名称','name'),('状态','type'),('日期','date')])
        blocks += _ev_table('解禁', market_events.get('unlocks', []), [('代码','code'),('名称','name'),('解禁市值(亿)','amount_yi'),('日期','date')])
        events_section = f'''
    <div style="background:#eff6ff;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #bfdbfe">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 8px 0;color:#1e40af">九、事件驱动（公告 / 财报 / 停复牌 / 解禁）</h3>
        {blocks}
    </div>'''

    # ── 十、个股走势 / MACD / 筹码（主力净流入 TOP20）──
    technical_section = ''
    if stock_technicals:
        cards = ''
        for r in stock_technicals[:20]:
            st = r.get('macd_state', '-')
            stc = '#16a34a' if st in ('金叉', '多头') else '#dc2626' if st in ('死叉', '空头') else '#64748b'
            draw = r.get('drawdown_from_high_pct')
            draw_s = f'{draw:+.2f}%' if draw is not None else '-'
            img = _stock_line_img_tag(r)
            img_html = img if img else '<div style="height:70px;color:#cbd5e1;font-size:10px;text-align:center;line-height:70px;border:1px dashed #e2e8f0;border-radius:6px">无走势数据</div>'
            cards += f'''<div style="display:inline-block;width:48%;vertical-align:top;margin:0 1.5% 10px 0;box-sizing:border-box;border:1px solid #e2e8f0;border-radius:8px;padding:7px 8px;page-break-inside:avoid">
<div style="font-size:11px;font-weight:600;color:#1e293b;margin-bottom:3px">{r.get('name','')} <span style="color:#94a3b8;font-weight:400;font-size:10px">{r.get('code','')}</span></div>
{img_html}
<div style="font-size:9px;color:#475569;margin-top:3px;line-height:1.55">收盘<b>{r.get('close','-')}</b> · 高<b style="color:#dc2626">{r.get('high20','-')}</b> · 低<b style="color:#16a34a">{r.get('low20','-')}</b> · 回撤<b>{draw_s}</b> · MACD<b style="color:{stc}">{st}</b> · 获利<b>{r.get('cyq_profit_pct','-')}</b></div>
</div>'''
        technical_section = f'''
    <div style="background:#f5f3ff;border-radius:12px;padding:14px 16px;margin-bottom:16px;border:1px solid #ddd6fe;page-break-inside:avoid">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 10px 0;color:#6d28d9">十、个股走势 / MACD / 筹码（主力净流入 TOP20）</h3>
        <div>{cards}</div>
        <div style="font-size:9.5px;color:#94a3b8;margin-top:6px">折线=近30日收盘价(前复权)；红虚线=20日高，绿虚线=20日低，红点=最新价；MACD(12,26,9)；K线不足则图/指标为空</div>
    </div>'''

    focus_section = f'''
    <div style="background:#f0fdf4;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #bbf7d0">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 12px 0;color:#16a34a">八、明日关注</h3>
        {focus_rows}
    </div>'''

    # 数据来源
    source_note = '<div style="font-size:11px;color:#94a3b8;padding:8px 0;text-align:center">数据来源: akshare / 东方财富 / yfinance | 仅供参考，不构成投资建议</div>'

    html = f'''
    <style>
      @page {{ size: A4; margin: 12mm 10mm; }}
      .sec {{ page-break-inside: avoid; }}
      tr {{ page-break-inside: avoid; }}
      img {{ max-width: 100%; }}
      h3 {{ page-break-after: avoid; }}
    </style>
    <div style="max-width:720px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#fff;color:#333;line-height:1.6">
        <div style="background:linear-gradient(135deg,#7c2d12,#b45309);border-radius:12px 12px 0 0;padding:24px;text-align:center">
            <h1 style="color:#fff;font-size:18px;margin:0;font-weight:600">市场复盘与异动简报</h1>
            <p style="color:#fef3c7;font-size:14px;margin:8px 0 0">{date_display}</p>
        </div>

        <div style="padding:20px">
            <div style="background:#fffbeb;border-radius:10px;padding:14px;margin-bottom:16px;border-left:4px solid #f59e0b">
                <p style="font-size:14px;color:#78350f;margin:0;line-height:1.6">{summary}</p>
            </div>

            {overview_section}
            {capital_section}
            {volatility_section}
            {anomaly_section}
            {pva_section}
            {lhb_section}
            {rank_section}
            {events_section}
            {technical_section}
            {focus_section}
            {source_note}

            <div style="text-align:center;padding:12px;font-size:11px;color:#999;border-top:1px solid #e5e7eb;margin-top:8px">
                Stock Agent 每日复盘 | {date_display}
            </div>
        </div>
    </div>'''

    return html


def generate_review_pdf(review_data, base_url=None):
    """生成复盘 PDF (weasyprint)。复用 generate_review_report 的 HTML 模板。
    返回 PDF 字节；若 weasyprint 未安装或无头依赖缺失则抛异常，由调用方降级。"""
    try:
        import weasyprint
    except Exception as e:
        raise RuntimeError(f'weasyprint 不可用: {e}')
    html = generate_review_report(review_data)
    wp = weasyprint.HTML(string=html, base_url=base_url or '')
    pdf_bytes = wp.write_pdf()
    return pdf_bytes


def generate_review_summary_text(review_data):
    """生成复盘简要文字摘要"""
    summary = review_data.get('summary', '')
    anomalies = review_data.get('anomalies', [])
    parts = [summary]
    if anomalies:
        parts.append(f'异动提醒{len(anomalies)}条')
    return ' | '.join(parts)


def send_email(smtp_user, smtp_pass, smtp_host, smtp_port, subscribers, html_content, summary_text, today, subject=None, pdf_bytes=None):
    """发送邮件给订阅者"""
    results = []

    if not smtp_user or not smtp_pass:
        print('[Pipeline] SMTP 未配置，跳过邮件发送')
        return results

    try:
        # 创建SMTP连接
        server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        server.login(smtp_user, smtp_pass)

        for sub in subscribers:
            target = sub.get('pushEmail') or sub.get('email')
            if not target:
                continue

            msg = MIMEMultipart('mixed')
            # 使用 formataddr 正确编码 From header (RFC5322/RFC2047)
            msg['From'] = formataddr(('Stock Agent Daily Report', smtp_user))
            msg['To'] = target
            # Subject 使用 Header 正确编码中文和emoji
            msg['Subject'] = Header(subject or f'每日市场情报 {today}', 'utf-8')
            msg['Date'] = formatdate(localtime=True)
            msg['X-Mailer'] = 'StockAgent-Python'
            msg['List-ID'] = 'Stock Agent Daily Report <stock-agent.ruiqiliang464-creator>'
            msg['Precedence'] = 'bulk'
            msg['X-Auto-Response-Suppress'] = 'OOF, AutoReply'
            msg['Auto-Submitted'] = 'auto-generated'

            alt = MIMEMultipart('alternative')
            alt.attach(MIMEText(f'每日市场情报 {today} - 请查看HTML版本获取完整内容', 'plain'))
            alt.attach(MIMEText(html_content, 'html'))
            msg.attach(alt)

            if pdf_bytes:
                try:
                    from email.mime.application import MIMEApplication
                    part = MIMEApplication(pdf_bytes, Name='review.pdf')
                    part['Content-Disposition'] = f'attachment; filename="市场复盘_{today}.pdf"'
                    msg.attach(part)
                except Exception as e:
                    print(f'[Pipeline] PDF附件附加失败: {e}')

            try:
                server.sendmail(smtp_user, target, msg.as_string())
                print(f'[Pipeline] ✅ {target}')
                results.append({'email': target, 'success': True})
            except Exception as e:
                print(f'[Pipeline] ❌ {target}: {e}')
                # 重试一次
                try:
                    server.sendmail(smtp_user, target, msg.as_string())
                    print(f'[Pipeline] ✅ {target} (重试成功)')
                    results.append({'email': target, 'success': True})
                except Exception as e2:
                    results.append({'email': target, 'success': False})

        server.quit()
    except Exception as e:
        print(f'[Pipeline] SMTP连接失败: {e}')

    return results
