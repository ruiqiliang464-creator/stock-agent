"""
news.py — 金融要闻采集

从多个主流财经新闻 RSS 源抓取最新新闻，
用关键词筛选可能影响股票走势的重大新闻，
每条生成 2-3 句简短概括。

数据源:
  CNBC Markets / Reuters Business / MarketWatch / Yahoo Finance
  Investing.com / Nasdaq

用法:
  from collectors_py.news import run
  news_items = run()
"""

import requests
import json
import re
import time
from datetime import datetime, timedelta
from xml.etree import ElementTree

# ── RSS 源 ──
RSS_FEEDS = [
    {
        'name': 'CNBC Markets',
        'url': 'https://www.cnbc.com/id/100003114/device/rss/rss.html',
        'lang': 'en',
    },
    {
        'name': 'CNBC Top News',
        'url': 'https://www.cnbc.com/id/10000664/device/rss/rss.html',
        'lang': 'en',
    },
    {
        'name': 'Reuters Business',
        'url': 'https://feeds.reuters.com/reuters/businessNews',
        'lang': 'en',
    },
    {
        'name': 'MarketWatch Top',
        'url': 'https://feeds.content.dowjones.io/public/rss/mw_topstories',
        'lang': 'en',
    },
    {
        'name': 'Yahoo Finance',
        'url': 'https://finance.yahoo.com/news/rssindex',
        'lang': 'en',
    },
    {
        'name': 'Investing.com News',
        'url': 'https://www.investing.com/rss/news_1.rss',
        'lang': 'en',
    },
    {
        'name': 'Nasdaq Stocks',
        'url': 'https://www.nasdaq.com/feed/rssoutbound?category=Stocks',
        'lang': 'en',
    },
]

# ── 关键词过滤 (可能影响股票走势的重大新闻) ──
MARKET_KEYWORDS_EN = [
    # 宏观经济
    'fed', 'federal reserve', 'interest rate', 'rate cut', 'rate hike',
    'inflation', 'cpi', 'ppi', 'gdp', 'recession', 'soft landing',
    'jobs report', 'employment', 'unemployment', 'nonfarm', 'payroll',
    'treasury', 'yield', 'bond', 'powell', 'fomc', 'minutes',
    # 贸易/政策
    'tariff', 'trade war', 'trade deal', 'sanction', 'embargo',
    'regulation', 'antitrust', 'doj', 'sec', 'ftc',
    # 企业/行业
    'earnings', 'revenue', 'profit', 'loss', 'guidance', 'outlook',
    'acquisition', 'merger', 'deal', 'buyout', 'ipo', 'spac',
    'layoff', 'job cut', 'restructuring', 'bankruptcy',
    'fda', 'approve', 'approval', 'clinical trial',
    'ai', 'artificial intelligence', 'chip', 'semiconductor', 'gpu',
    'nvidia', 'apple', 'microsoft', 'google', 'alphabet', 'amazon',
    'meta', 'tesla', 'openai', 'anthropic',
    # 商品/加密
    'oil', 'crude', 'opec', 'gold', 'silver', 'copper',
    'bitcoin', 'crypto', 'ethereum', 'binance', 'sec crypto',
    # 地缘政治
    'geopolitical', 'war', 'conflict', 'tension', 'crisis',
    'china', 'beijing', 'taiwan', 'ukraine', 'russia', 'middle east',
    # 市场
    'stock market', 'dow', 's&p', 'nasdaq', 'rally', 'selloff',
    'surge', 'plunge', 'crash', 'record high', 'bear market', 'bull market',
    'volatility', 'vix', 'fear index',
]

MARKET_KEYWORDS_ZH = [
    '降息', '加息', '通胀', 'CPI', 'GDP', '衰退', '就业', '失业',
    '财报', '营收', '利润', ' guidance', '收购', '合并', '上市',
    '裁员', '破产', 'FDA', '批准', '人工智能', '芯片', '半导体',
    '英伟达', '苹果', '微软', '谷歌', '亚马逊', '特斯拉',
    '油价', '原油', 'OPEC', '黄金', '比特币', '加密货币',
    '关税', '贸易战', '制裁', '监管', '反垄断',
    '股市', '道琼斯', '标普', '纳斯达克', '暴涨', '暴跌',
    '熔断', '熊市', '牛市', '地缘', '冲突', '危机',
]

ALL_KEYWORDS = MARKET_KEYWORDS_EN + MARKET_KEYWORDS_ZH


def clean_html(text):
    """去除HTML标签，清理文本"""
    if not text:
        return ''
    # 去除 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 去除 HTML 实体
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    text = text.replace('&apos;', "'")
    # 压缩多余空白
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def truncate_sentences(text, max_sentences=3):
    """截取前 N 句话"""
    if not text:
        return ''
    # 按句号、问号、感叹号分割
    sentences = re.split(r'(?<=[.!?。！？])\s+', text)
    result = '. '.join(sentences[:max_sentences])
    if len(sentences) > max_sentences:
        result += '...'
    return result


def has_keyword(text):
    """检查文本是否包含市场相关关键词"""
    text_lower = text.lower()
    for kw in ALL_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    return False


def score_news(title, description):
    """给新闻打分，越高越重要"""
    text = (title + ' ' + description).lower()
    score = 0

    # 高权重关键词 (重大事件)
    high_weight = ['fed', 'federal reserve', 'rate cut', 'rate hike', 'inflation',
                   'recession', 'crash', 'plunge', 'surge', 'rally', 'earnings',
                   'tariff', 'trade war', 'bankruptcy', 'crisis', 'war', 'conflict',
                   '降息', '加息', '通胀', '衰退', '暴跌', '暴涨', '破产', '危机']
    for kw in high_weight:
        if kw in text:
            score += 3

    # 中权重关键词 (企业/行业)
    mid_weight = ['apple', 'microsoft', 'nvidia', 'google', 'amazon', 'tesla',
                  'meta', 'earnings', 'acquisition', 'merger', 'layoff', 'fda',
                  'ai', 'chip', 'semiconductor', 'bitcoin', 'crypto', 'oil', 'gold',
                  '苹果', '微软', '英伟达', '谷歌', '特斯拉', '财报', '收购', '芯片', '人工智能']
    for kw in mid_weight:
        if kw in text:
            score += 2

    # 低权重关键词 (一般市场)
    low_weight = ['stock', 'market', 'dow', 's&p', 'nasdaq', 'bond', 'yield',
                  '股市', '市场']
    for kw in low_weight:
        if kw in text:
            score += 1

    return score


def parse_rss_feed(feed_info):
    """解析单个 RSS 源，返回新闻列表"""
    items = []
    try:
        resp = requests.get(
            feed_info['url'],
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            },
            timeout=(10, 20),
        )
        if resp.status_code != 200:
            print(f"[News] {feed_info['name']} HTTP {resp.status_code}")
            return items

        # 解析 XML
        root = ElementTree.fromstring(resp.content)

        # RSS 2.0 格式
        channel = root.find('channel')
        if channel is not None:
            for item in channel.findall('item'):
                title = clean_html(item.findtext('title', default=''))
                desc = clean_html(item.findtext('description', default=''))
                link = item.findtext('link', default='')
                pub_date = item.findtext('pubDate', default='')

                if title:
                    items.append({
                        'title': title,
                        'description': desc,
                        'link': link,
                        'pubDate': pub_date,
                        'source': feed_info['name'],
                    })

        # Atom 格式
        elif root.tag.endswith('feed'):
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            for entry in root.findall('atom:entry', ns):
                title = clean_html(entry.findtext('atom:title', default='', namespaces=ns))
                summary = entry.findtext('atom:summary', default='', namespaces=ns)
                content = entry.findtext('atom:content', default='', namespaces=ns)
                desc = clean_html(summary or content)
                link_elem = entry.find('atom:link', ns)
                link = link_elem.get('href', '') if link_elem is not None else ''
                pub_date = entry.findtext('atom:updated', default='', namespaces=ns)

                if title:
                    items.append({
                        'title': title,
                        'description': desc,
                        'link': link,
                        'pubDate': pub_date,
                        'source': feed_info['name'],
                    })

        print(f"[News] {feed_info['name']}: {len(items)} 条")

    except Exception as e:
        print(f"[News] {feed_info['name']} 失败: {e}")

    return items


def run():
    """采集金融要闻: 从多个RSS源抓取 → 关键词筛选 → 打分排序 → 返回Top新闻"""
    print('[News Collector] 开始采集金融要闻...')

    all_items = []

    # 逐个抓取 RSS 源
    for feed in RSS_FEEDS:
        items = parse_rss_feed(feed)
        all_items.extend(items)

    print(f'[News Collector] 原始新闻: {len(all_items)} 条')

    # 去重 (按标题)
    seen_titles = set()
    unique_items = []
    for item in all_items:
        title_key = item['title'].lower().strip()[:80]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_items.append(item)

    print(f'[News Collector] 去重后: {len(unique_items)} 条')

    # 关键词筛选 + 打分
    scored_items = []
    for item in unique_items:
        title = item['title']
        desc = item['description']

        # 必须包含至少一个关键词
        combined_text = title + ' ' + desc
        if not has_keyword(combined_text):
            continue

        score = score_news(title, desc)
        item['score'] = score
        scored_items.append(item)

    # 按分数排序
    scored_items.sort(key=lambda x: x['score'], reverse=True)

    # 取 Top 8
    top_news = scored_items[:8]

    # 格式化输出
    results = []
    for item in top_news:
        # 生成简短概括: 优先用 description, 截取2-3句
        summary = truncate_sentences(item['description'], max_sentences=3)
        if not summary or len(summary) < 20:
            # 如果 description 太短，用 title 作为概括
            summary = item['title']

        results.append({
            'title': item['title'],
            'summary': summary,
            'source': item['source'],
            'link': item['link'],
            'pubDate': item.get('pubDate', ''),
            'score': item['score'],
        })

    print(f'[News Collector] 采集完成: {len(results)} 条要闻 (筛选自 {len(unique_items)} 条)')
    return results
