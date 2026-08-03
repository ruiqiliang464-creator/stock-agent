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


def generate_news_section(news_items):
    """生成今日要闻区块 HTML"""
    if not news_items:
        return ''

    cards = ''
    for i, item in enumerate(news_items):
        title = item.get('title', '')
        summary = item.get('summary', '')
        source = item.get('source', '')
        link = item.get('link', '')
        news_time = item.get('time', '')

        # 时间标签 (如果有)
        time_badge = f'<span style="font-size:11px;color:#94a3b8;margin-top:4px">来源: {source}' + (f' · {news_time}' if news_time else '') + '</span>'

        # 序号圆圈
        cards += f'''
        <div style="display:flex;gap:12px;padding:12px 0;border-bottom:1px solid #e5e7eb">
            <div style="flex-shrink:0;width:24px;height:24px;border-radius:50%;background:#1e40af;color:#fff;font-size:12px;font-weight:600;display:flex;align-items:center;justify-content:center">{i+1}</div>
            <div style="flex:1">
                <div style="font-size:14px;font-weight:500;color:#1e293b;margin-bottom:4px">{title}</div>
                <div style="font-size:13px;color:#64748b;line-height:1.5">{summary}</div>
                <div style="margin-top:4px">{time_badge}</div>
            </div>
        </div>'''

    return f'''
    <div style="background:#fffbeb;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #fde68a">
        <h3 style="font-size:15px;font-weight:600;margin:0 0 8px 0;color:#92400e">📰 今日要闻</h3>
        <p style="font-size:12px;color:#b45309;margin:0 0 12px 0">以下为过去24小时内可能影响市场走势的重大新闻</p>
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
            <p style="margin:0"><strong>数据来源</strong>：美股(yfinance/CNBC) | A股(akshare/同花顺) | 数字货币(Binance) | 大宗商品(akshare/yfinance) | 要闻(CNBC/Reuters/MarketWatch等RSS)</p>
        </div>'''

    html = f'''
    <div style="max-width:600px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#fff;color:#333;line-height:1.6">
        <div style="background:linear-gradient(135deg,#1e40af,#3b82f6);border-radius:12px 12px 0 0;padding:24px;text-align:center">
            <h1 style="color:#fff;font-size:20px;margin:0;font-weight:500">每日市场情报</h1>
            <p style="color:#e0e7ff;font-size:14px;margin:8px 0 0">{date_display}</p>
        </div>

        <div style="padding:20px">
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


def send_email(smtp_user, smtp_pass, smtp_host, smtp_port, subscribers, html_content, summary_text, today):
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
            msg['Subject'] = Header(f'每日市场情报 {today}', 'utf-8')
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
