"""
formatter.py — 报告生成 + 邮件发送 (Python版)

从 Node.js 版 formatter/report.js + runner-github.js 邮件部分移植
"""

import json
import smtplib
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

    overview_section = f'''
    <div style="background:#f8fafc;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #e5e7eb">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 12px 0;color:#1e293b">一、市场概况</h3>
        <div style="display:flex;gap:8px;margin-bottom:8px">{index_cards if index_cards else '<p style="color:#999;font-size:13px">指数数据暂不可用</p>'}</div>
        {breadth_html}
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

    capital_section = f'''
    <div style="background:#f0f9ff;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #bae6fd">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 12px 0;color:#0369a1">二、资金与微观结构</h3>
        {''.join(capital_parts) if capital_parts else '<p style="color:#999;font-size:13px">资金数据暂不可用</p>'}
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

    focus_section = f'''
    <div style="background:#f0fdf4;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #bbf7d0">
        <h3 style="font-size:14px;font-weight:600;margin:0 0 12px 0;color:#16a34a">五、明日关注</h3>
        {focus_rows}
    </div>'''

    # 数据来源
    source_note = '<div style="font-size:11px;color:#94a3b8;padding:8px 0;text-align:center">数据来源: akshare / 东方财富 / yfinance | 仅供参考，不构成投资建议</div>'

    html = f'''
    <div style="max-width:600px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#fff;color:#333;line-height:1.6">
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
            {focus_section}
            {source_note}

            <div style="text-align:center;padding:12px;font-size:11px;color:#999;border-top:1px solid #e5e7eb;margin-top:8px">
                Stock Agent 每日复盘 | {date_display}
            </div>
        </div>
    </div>'''

    return html


def generate_review_summary_text(review_data):
    """生成复盘简要文字摘要"""
    summary = review_data.get('summary', '')
    anomalies = review_data.get('anomalies', [])
    parts = [summary]
    if anomalies:
        parts.append(f'异动提醒{len(anomalies)}条')
    return ' | '.join(parts)


def send_email(smtp_user, smtp_pass, smtp_host, smtp_port, subscribers, html_content, summary_text, today, subject=None):
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

            msg = MIMEMultipart('alternative')
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

            msg.attach(MIMEText(f'每日市场情报 {today} - 请查看HTML版本获取完整内容', 'plain'))
            msg.attach(MIMEText(html_content, 'html'))

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
