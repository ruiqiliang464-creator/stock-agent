"""
news.py — 金融要闻采集与影响分析

从多个主流财经新闻 RSS 源抓取最新新闻，
用关键词筛选可能影响股票走势的重大新闻，
自动分类并生成市场影响分析。

新闻分类:
  1. 美联储政策 (fed_policy)
  2. 全球经济 (global_economy)
  3. 地缘政治 (geopolitics)
  4. 自然灾害 (natural_disaster)
  5. 市场表现 (market_performance)
  6. 投资人动态 (investor_insight)
  7. 科技突破 (tech_breakthrough)
  8. 央行政策 (central_bank)

数据源:
  CNBC / MarketWatch / Yahoo Finance / Investing.com / Nasdaq
  Google News World / BBC World / Seeking Alpha

用法:
  from collectors_py.news import run
  news_items = run()
"""

import requests
import json
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    {
        'name': 'Google News World',
        'url': 'https://news.google.com/rss/headlines/section/topic/WORLD?hl=en&gl=US',
        'lang': 'en',
    },
    {
        'name': 'Google News Business',
        'url': 'https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en&gl=US',
        'lang': 'en',
    },
    {
        'name': 'BBC World',
        'url': 'http://feeds.bbci.co.uk/news/world/rss.xml',
        'lang': 'en',
    },
    {
        'name': 'Seeking Alpha Market',
        'url': 'https://seekingalpha.com/market_currents.xml',
        'lang': 'en',
    },
]

# ── 新闻分类关键词 ──
# 每个分类: 关键词列表 → 匹配则归入该分类
CATEGORY_KEYWORDS = {
    'fed_policy': {
        'label': '美联储政策',
        'icon': '🏦',
        'color': '#7c3aed',
        'bg': '#f3e8ff',
        'keywords': [
            'fed', 'federal reserve', 'powell', 'fomc', 'interest rate',
            'rate cut', 'rate hike', 'balance sheet', 'quantitative easing',
            'taper', 'monetary policy', 'federal open market', 'jerome powell',
            'fed minutes', 'beige book', 'terminal rate', 'dot plot',
            '美联储', '鲍威尔', '降息', '加息', '联邦基金利率', '量化宽松', '缩表',
        ],
    },
    'central_bank': {
        'label': '央行政策',
        'icon': '🏛️',
        'color': '#6d28d9',
        'bg': '#ede9fe',
        'keywords': [
            'ecb', 'european central bank', 'boj', 'bank of japan',
            'boe', 'bank of england', 'pbo c', "people's bank of china",
            'rba', 'reserve bank of australia', 'rbnz', 'bcc',
            'central bank', 'policy rate', 'deposit rate', 'refi rate',
            'quantitative tightening', 'yield curve control',
            '欧洲央行', '日本央行', '英国央行', '中国央行', '央行', '再融资',
        ],
    },
    'global_economy': {
        'label': '全球经济',
        'icon': '🌍',
        'color': '#1d4ed8',
        'bg': '#dbeafe',
        'keywords': [
            'gdp', 'inflation', 'cpi', 'ppi', 'recession', 'soft landing',
            'pmi', 'manufacturing', 'services pmi', 'trade deficit',
            'imf', 'world bank', 'g20', 'g7', 'oecd', 'wtio',
            'jobs report', 'employment', 'unemployment', 'nonfarm', 'payroll',
            'consumer confidence', 'retail sales', 'durable goods',
            'housing', 'mortgage', 'jobless claims',
            '经济', '通胀', '衰退', '就业', '失业', '制造业', '消费',
            'gdp', 'cpi', 'pmi', '零售', '房地产', '抵押贷款',
        ],
    },
    'geopolitics': {
        'label': '地缘政治',
        'icon': '⚔️',
        'color': '#b91c1c',
        'bg': '#fee2e2',
        'keywords': [
            'war', 'conflict', 'military', 'nuclear', 'coup',
            'sanction', 'embargo', 'tariff', 'trade war', 'trade deal',
            'invasion', 'strike', 'ceasefire', 'nato', 'un security',
            'opec', 'iran', 'russia', 'ukraine', 'israel', 'gaza',
            'north korea', 'taiwan strait', 'south china sea',
            'china-us', 'us-china', 'beijing', 'kremlin',
            '战争', '冲突', '军事', '核', '政变', '制裁', '关税',
            '贸易战', '入侵', '打击', '停火', '北约',
            '伊朗', '俄罗斯', '乌克兰', '以色列', '朝鲜', '台海', '南海',
        ],
    },
    'natural_disaster': {
        'label': '自然灾害',
        'icon': '🌪️',
        'color': '#c2410c',
        'bg': '#ffedd5',
        'keywords': [
            'earthquake', 'hurricane', 'typhoon', 'tsunami', 'flood',
            'wildfire', 'tornado', 'volcano', 'eruption', 'drought',
            'heatwave', 'blizzard', 'avalanche', 'landslide',
            'disaster', 'emergency', 'evacuate', 'casualt',
            '地震', '飓风', '台风', '海啸', '洪水', '火灾', '龙卷风',
            '火山', '干旱', '热浪', '暴风雪', '山体滑坡', '灾害', '疏散',
        ],
    },
    'market_performance': {
        'label': '市场表现',
        'icon': '📊',
        'color': '#15803d',
        'bg': '#dcfce7',
        'keywords': [
            'dow', 's&p 500', 'sp500', 'nasdaq', 'russell', 'nikkei',
            'dax', 'ftse', 'hang seng', 'shanghai', 'kospi',
            'circuit breaker', 'trading halt', 'limit up', 'limit down',
            'rally', 'selloff', 'surge', 'plunge', 'crash', 'record high',
            'record low', 'bear market', 'bull market', 'correction',
            'volatility', 'vix', 'fear index', 'margin call',
            'stock market', 'market close', 'market open',
            '道琼斯', '标普', '纳斯达克', '日经', '恒生', '上证',
            '熔断', '涨停', '跌停', '暴涨', '暴跌', '创新高', '熊市', '牛市',
            '波动', '恐慌指数', '股市', '收盘', '开盘',
        ],
    },
    'investor_insight': {
        'label': '投资人动态',
        'icon': '🎯',
        'color': '#9d174d',
        'bg': '#fce7f3',
        'keywords': [
            'buffett', 'berkshire', 'soros', 'ackman', 'pershing',
            'druckenmiller', 'dalio', 'bridgewater', 'icahn', 'burry',
            'scion', 'cohn', 'dimon', 'jamie dimon', 'wood', 'ark invest',
            'cathie wood', 'tepper', 'appaloosa', 'kusner', 'carl icahn',
            '13f', '13f filing', 'form 13f', 'hedge fund', 'activist',
            'stake', 'position', 'portfolio', 'holding',
            'buyout', 'takeover', 'acquire', 'merge', 'stake increase',
            'increase stake', 'reduce stake', 'trim position', 'exit position',
            '增持', '减持', '建仓', '清仓', '加仓', '减仓', '对冲基金',
            '巴菲特', '索罗斯', '达利欧', '木头西', '阿克曼', '仓位',
        ],
    },
    'tech_breakthrough': {
        'label': '科技突破',
        'icon': '🔬',
        'color': '#0369a1',
        'bg': '#e0f2fe',
        'keywords': [
            'breakthrough', 'innovation', 'patent', 'invent', 'discover',
            'quantum', 'fusion', 'nuclear fusion', 'battery', 'solid state',
            'autonomous', 'self-driving', 'robot', 'humanoid',
            'gene therapy', 'crispr', 'mrna', 'clinical trial',
            'supercomputer', 'exaflop', 'quantum computing',
            '6g', 'satellite', 'space launch', 'reusable rocket',
            'fusion energy', 'hydrogen', 'carbon capture',
            'ai model', 'llm', 'gpt', 'gemini', 'foundation model',
            'ai', 'artificial intelligence', 'machine learning',
            'chip', 'semiconductor', 'gpu', 'npu', '3nm', '2nm',
            'openai', 'anthropic', 'deepmind',
            '突破', '创新', '专利', '发明', '量子', '核聚变', '电池',
            '自动驾驶', '机器人', '基因', '超算', '量子计算',
            '卫星', '火箭', '氢能', '碳捕捉', '人工智能', '芯片', '半导体',
        ],
    },
}

# ── 影响分析模板 (按分类×关键词) ──
IMPACT_ANALYSIS = {
    'fed_policy': {
        'rate cut': '美联储释放宽松信号，降息预期升温，流动性改善利好成长股、科技股和加密资产；债券收益率下行利好REITs和公用事业',
        'rate hike': '美联储收紧货币政策，加息预期升温，可能压制高估值成长股；银行股或受益于息差扩大',
        'powell': '美联储主席讲话释放政策信号，市场将重新定价货币政策路径，关注后续经济数据验证',
        'balance sheet': '央行资产负债表调整直接影响市场流动性，缩表放缓可能提振风险资产',
        'taper': '量化紧缩节奏变化影响市场流动性预期，放缓节奏利好风险资产',
        'minutes': '美联储会议纪要透露政策走向线索，市场据此调整利率路径预期',
        'fomc': 'FOMC决议影响利率预期和资产定价，关注点阵图和经济预测',
        'quantitative easing': '量化宽松政策影响市场流动性，推升风险资产估值',
        'terminal rate': '终端利率预期变化影响长端收益率和资产定价',
        'beige book': '美联储褐皮书反映经济状况，影响政策预期',
    },
    'central_bank': {
        'ecb': '欧洲央行政策影响欧元汇率和欧洲资产定价，利率决议引导资本流动方向',
        'boj': '日本央行政策影响日元汇率和亚太资本流动，YCC调整可能引发套利交易平仓',
        'boe': '英国央行政策影响英镑和英国资产定价，利率路径反映通胀治理决心',
        'rba': '澳洲央行政策影响澳元和大宗商品定价',
        'central bank': '全球央行政策协调影响跨境资本流动和汇率格局',
        'yield curve control': '收益率曲线控制调整可能引发债券市场重定价',
    },
    'global_economy': {
        'recession': '经济衰退风险上升，避险情绪升温，利好黄金美债等避险资产；周期股和新兴市场可能承压',
        'soft landing': '软着陆预期增强，风险偏好回暖，利好股市和风险资产',
        'inflation': '通胀数据影响央行政策预期，CPI超预期升温可能加速紧缩，利空债券和高估值成长股',
        'gdp': 'GDP数据反映经济基本面，增速放缓可能引发宽松预期利好股市，过热则引发紧缩担忧',
        'pmi': 'PMI数据反映制造业/服务业景气度，扩张区间利好周期股，收缩区间利空',
        'jobs report': '就业数据影响美联储政策路径，强劲就业可能延缓降息，疲软则加速宽松',
        'unemployment': '失业率变化反映经济健康度，影响消费预期和政策走向',
        'consumer confidence': '消费者信心影响消费支出预期，进而影响零售和消费板块',
        'retail sales': '零售销售数据反映消费动能，影响零售板块和经济增长预期',
        'housing': '房地产数据影响建材、家居和银行抵押贷款板块',
        'trade deficit': '贸易逆差数据影响汇率和跨国企业利润预期',
        'imf': 'IMF预测影响全球经济增长预期和大类资产配置',
    },
    'geopolitics': {
        'war': '地缘冲突升级推升避险情绪，利好黄金、原油和军工板块；航空、旅游和能源进口国承压',
        'sanction': '制裁措施影响相关国家出口和供应链，关注能源、金属和大宗商品价格波动',
        'tariff': '贸易关税变化影响跨国企业利润和供应链格局，出口导向型行业受冲击',
        'trade war': '贸易战升级推升市场不确定性，全球供应链重构影响制造业',
        'nuclear': '核相关事件推升地缘风险溢价，避险资产受益',
        'military': '军事行动推升市场不确定性和油价，避险情绪上升',
        'ceasefire': '停火协议降低地缘风险溢价，利好风险资产，利空避险资产',
        'opec': 'OPEC决议影响原油供给和油价，能源板块直接受益',
        'iran': '伊朗局势影响中东地缘稳定和油价，能源和军工板块关注',
        'russia': '俄乌冲突进展影响能源和粮食供应，全球通胀预期',
        'taiwan': '台海局势影响半导体供应链和中美关系，科技股关注',
    },
    'natural_disaster': {
        'earthquake': '地震灾害可能影响当地产业链和基础设施，关注保险赔付和重建需求',
        'hurricane': '飓风影响能源生产和物流运输，油价和保险板块可能波动',
        'typhoon': '台风影响亚太地区制造业产能和航运，供应链短期受阻',
        'flood': '洪涝灾害影响农产品供应和制造业产能，关注大宗商品价格',
        'wildfire': '火灾影响当地经济活动和保险赔付，能源和林业可能受影响',
        'volcano': '火山喷发影响航空运输和当地经济，保险板块关注',
        'drought': '干旱影响农业产量和水电供给，粮食和能源价格可能上涨',
        'heatwave': '热浪影响电力需求和农业生产，能源和农业板块关注',
    },
    'market_performance': {
        'circuit breaker': '触发熔断机制表明市场恐慌情绪极端，短期波动加剧，关注政策干预信号',
        'crash': '市场暴跌反映恐慌性抛售，关注超跌反弹机会但需警惕系统性风险',
        'rally': '市场大涨显示风险偏好回暖，关注领涨板块的持续性和资金流向',
        'record high': '指数创历史新高，关注后续资金流向和估值压力，警惕获利了结',
        'bear market': '进入熊市区域，市场信心承压，关注政策对冲和估值底',
        'bull market': '维持牛市格局，风险偏好积极，关注领涨主线持续性',
        'correction': '市场修正释放短期超买压力，关注基本面支撑和资金回流信号',
        'vix': '恐慌指数飙升反映市场避险情绪上升，期权市场定价波动加剧',
        'selloff': '抛售潮反映资金撤离，关注超跌反弹机会和政策面信号',
        'surge': '暴涨行情显示资金积极涌入，关注领涨标的和板块轮动',
        'plunge': '暴跌行情反映恐慌抛售，关注超跌标的和政策对冲可能',
    },
    'investor_insight': {
        'buffett': '巴菲特操作动向引发市场跟风效应，关注伯克希尔持仓变化和受益标的',
        'soros': '索罗斯仓位变动反映对冲基金宏观方向判断，关注大类资产配置线索',
        'ackman': '阿克曼建仓动作通常针对特定标的，关注目标公司基本面变化',
        'druckenmiller': '德鲁肯米勒宏观观点影响大类资产配置思路',
        'dalio': '达利欧全天候策略观点影响大类资产配置方向',
        'burry': '伯里做空信号引发市场关注，关注其目标标的的风险',
        'cathie wood': '木头西(ARK)持仓变化反映成长股和创新主题方向',
        'dimon': '摩根大通CEO戴蒙观点反映银行业和经济前景判断',
        '13f': '知名机构13F持仓报告披露调仓方向，跟风效应可能短期推动相关标的',
        'activist': '激进投资者介入推动公司治理变革，关注催化剂和估值修复',
        'acquire': '并购交易影响相关公司估值和行业格局，关注溢价和协同效应',
        'merger': '合并交易重塑行业格局，关注反垄断审查和整合风险',
        'increase stake': '知名投资人增持释放看多信号，可能引发跟风买入',
        'reduce stake': '知名投资人减持释放看空信号，可能引发跟风卖出',
    },
    'tech_breakthrough': {
        'ai': 'AI技术突破推动相关产业链投资机会，关注芯片、算力和应用层受益标的',
        'artificial intelligence': 'AI技术突破推动相关产业链投资机会，关注算力基础设施和应用落地',
        'chip': '芯片技术突破影响半导体产业链格局，关注设备、材料和封测环节',
        'semiconductor': '半导体技术进展影响产业链估值，关注国产替代和技术迭代',
        'gpu': 'GPU算力需求增长利好芯片设计公司，关注AI训练和推理需求',
        'quantum': '量子计算突破可能重塑计算产业格局，长期投资主题',
        'fusion': '核聚变进展影响长期能源格局，关注相关材料和设备公司',
        'battery': '电池技术突破影响新能源产业链，关注材料和整车环节',
        'autonomous': '自动驾驶突破影响汽车和出行产业，关注传感器和软件公司',
        'gene therapy': '基因疗法突破影响医药板块，关注研发管线和商业化进度',
        'crispr': 'CRISPR基因编辑技术突破影响精准医疗产业链',
        'rocket': '火箭发射和可回收技术影响航天产业链，关注卫星和通信公司',
        'hydrogen': '氢能技术进展影响新能源格局，关注制氢、储运和应用环节',
        'openai': 'OpenAI产品发布影响AI产业链估值，关注合作方和竞争格局',
    },
}

# 默认分析（当没有匹配到具体关键词时使用）
DEFAULT_ANALYSIS = {
    'fed_policy': '央行政策动向影响市场流动性预期和资产定价方向',
    'central_bank': '全球央行政策协调影响跨境资本流动和汇率格局',
    'global_economy': '全球经济事件影响跨国资本流动和市场风险偏好',
    'geopolitics': '地缘政治事件推升市场不确定性，避险资产可能受益',
    'natural_disaster': '自然灾害可能冲击局部供应链，关注保险和重建需求',
    'market_performance': '全球市场表现反映资金风险偏好变化，关注跨市场联动',
    'investor_insight': '知名投资人观点影响市场情绪和资金流向，关注跟风效应',
    'tech_breakthrough': '科技突破可能重塑行业格局，关注商业化带来的投资机会',
}


def clean_html(text):
    """去除HTML标签，清理文本"""
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    text = text.replace('&apos;', "'")
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def translate_to_chinese(text, max_retries=1):
    """将英文文本翻译为中文 (使用 Google Translate 免费API，MyMemory 备用)

    如果文本已包含大量中文字符，则跳过翻译。
    翻译失败时返回原文，不影响管道运行。
    超时设置较短(3+8s)以避免阻塞管道。
    """
    if not text or not text.strip():
        return ''

    # 检测是否已包含大量中文，如果是则跳过翻译
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if cjk_count / max(len(text), 1) > 0.3:
        return text

    # 方案1: Google Translate 免费API
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                'https://translate.googleapis.com/translate_a/single',
                params={
                    'client': 'gtx',
                    'sl': 'en',
                    'tl': 'zh-CN',
                    'dt': 't',
                    'q': text,
                },
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                },
                timeout=(3, 8),
            )

            if resp.status_code == 200:
                data = resp.json()
                if data and data[0]:
                    translated = ''.join(seg[0] for seg in data[0] if seg and seg[0])
                    if translated:
                        return translated
        except Exception:
            pass

        if attempt < max_retries - 1:
            time.sleep(0.5)

    # 方案2: MyMemory 备用翻译API
    try:
        resp = requests.get(
            'https://api.mymemory.translated.net/get',
            params={
                'q': text[:500],
                'langpair': 'en|zh-CN',
            },
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            },
            timeout=(3, 8),
        )

        if resp.status_code == 200:
            data = resp.json()
            translated = data.get('responseData', {}).get('translatedText', '')
            if translated and translated.upper() != text.upper():
                return translated
    except Exception:
        pass

    # 所有翻译方案均失败，返回原文
    return text


def keyword_match(keyword, text):
    """检查关键词是否出现在文本中

    英文短关键词(<=8字符)使用单词边界匹配，避免 "war" 匹配到 "Warner" 等误匹配。
    中文关键词和长英文短语使用子串匹配。
    """
    if keyword.isascii() and len(keyword) <= 8:
        return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))
    else:
        return keyword in text


def truncate_sentences(text, max_sentences=3):
    """截取前 N 句话"""
    if not text:
        return ''
    sentences = re.split(r'(?<=[.!?。！？])\s+', text)
    result = '. '.join(sentences[:max_sentences])
    if len(sentences) > max_sentences:
        result += '...'
    return result


def parse_pub_date(date_str):
    """解析 RSS/Atom 的发布时间，返回 aware datetime (UTC)"""
    if not date_str:
        return None
    date_str = date_str.strip()

    try:
        dt = parsedate_to_datetime(date_str)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except (TypeError, ValueError):
        pass

    try:
        iso_str = date_str.replace('Z', '+00:00')
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        pass

    return None


def format_news_time(pub_dt):
    """把 datetime 格式化为简短的中文时间显示，如 '08/03 05:30'"""
    if pub_dt is None:
        return ''
    cst = pub_dt.astimezone(timezone(timedelta(hours=8)))
    return cst.strftime('%m/%d %H:%M')


def categorize_news(title, description):
    """给新闻分类，返回 category key

    优先级: fed_policy > central_bank > geopolitics > natural_disaster
            > market_performance > investor_insight > tech_breakthrough > global_economy
    """
    text = (title + ' ' + description).lower()

    # 按优先级检查每个分类
    priority_order = [
        'fed_policy', 'central_bank', 'geopolitics', 'natural_disaster',
        'market_performance', 'investor_insight', 'tech_breakthrough',
        'global_economy',
    ]

    matched_categories = []
    for cat_key in priority_order:
        cat_info = CATEGORY_KEYWORDS.get(cat_key, {})
        keywords = cat_info.get('keywords', [])
        for kw in keywords:
            if keyword_match(kw, text):
                matched_categories.append(cat_key)
                break

    if not matched_categories:
        return None

    # 返回第一个匹配的分类（按优先级）
    return matched_categories[0]


def generate_impact_analysis(title, description, category):
    """基于分类和关键词生成市场影响分析"""
    text = (title + ' ' + description).lower()

    cat_analyses = IMPACT_ANALYSIS.get(category, {})

    # 查找最匹配的分析模板
    for keyword, analysis_text in cat_analyses.items():
        if keyword_match(keyword, text):
            return analysis_text

    # 使用默认分析
    return DEFAULT_ANALYSIS.get(category, '该事件可能影响相关市场走势，建议持续关注后续发展')


def has_any_keyword(text):
    """检查文本是否包含任意分类的关键词"""
    text_lower = text.lower()
    for cat_info in CATEGORY_KEYWORDS.values():
        for kw in cat_info.get('keywords', []):
            if keyword_match(kw, text_lower):
                return True
    return False


def score_news(title, description, category):
    """给新闻打分，越高越重要"""
    text = (title + ' ' + description).lower()
    score = 0

    # 高权重分类 (直接影响市场的事件)
    high_categories = ['fed_policy', 'geopolitics', 'natural_disaster', 'market_performance']
    if category in high_categories:
        score += 3

    # 中权重分类
    mid_categories = ['central_bank', 'global_economy', 'investor_insight']
    if category in mid_categories:
        score += 2

    # 低权重分类
    if category == 'tech_breakthrough':
        score += 1

    # 高权重关键词加成
    high_weight = ['fed', 'federal reserve', 'rate cut', 'rate hike', 'inflation',
                   'recession', 'crash', 'plunge', 'surge', 'rally', 'earnings',
                   'tariff', 'trade war', 'bankruptcy', 'crisis', 'war', 'conflict',
                   'earthquake', 'hurricane', 'circuit breaker', 'buffett', 'soros',
                   '降息', '加息', '通胀', '衰退', '暴跌', '暴涨', '破产', '危机',
                   '战争', '地震', '飓风', '熔断', '巴菲特', '索罗斯']
    for kw in high_weight:
        if keyword_match(kw, text):
            score += 3

    # 中权重关键词加成
    mid_weight = ['apple', 'microsoft', 'nvidia', 'google', 'amazon', 'tesla',
                  'meta', 'earnings', 'acquisition', 'merger', 'layoff', 'fda',
                  'ai', 'chip', 'semiconductor', 'bitcoin', 'crypto', 'oil', 'gold',
                  'ecb', 'boj', 'boe', 'powell', 'dimon', 'dalio', 'ackman',
                  '苹果', '微软', '英伟达', '谷歌', '特斯拉', '财报', '收购', '芯片',
                  '人工智能', '欧洲央行', '日本央行', '鲍威尔']
    for kw in mid_weight:
        if keyword_match(kw, text):
            score += 2

    # 低权重关键词加成
    low_weight = ['stock', 'market', 'dow', 's&p', 'nasdaq', 'bond', 'yield',
                  '股市', '市场', '央行', 'gdp', 'cpi', 'pmi']
    for kw in low_weight:
        if keyword_match(kw, text):
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
        print(f"[News] {feed_info['name']} failed: {e}")

    return items


def run():
    """采集金融要闻: 抓取RSS → 时效过滤 → 关键词筛选 → 分类 → 打分 → 影响分析 → 返回Top新闻"""
    print('[News Collector] start collecting financial news...')

    all_items = []

    for feed in RSS_FEEDS:
        items = parse_rss_feed(feed)
        all_items.extend(items)

    print(f'[News Collector] raw news: {len(all_items)}')

    # ── 时效性过滤: 只保留过去 24 小时内的新闻 ──
    TIME_WINDOW_HOURS = 24
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(hours=TIME_WINDOW_HOURS)
    print(f'[News Collector] time window: {format_news_time(window_start)} ~ {format_news_time(now_utc)} (CST)')

    time_filtered = []
    skipped_no_time = 0
    skipped_old = 0
    skipped_future = 0
    for item in all_items:
        pub_dt = parse_pub_date(item.get('pubDate', ''))
        if pub_dt is None:
            skipped_no_time += 1
            item['_pub_dt'] = None
            item['_time_str'] = ''
            time_filtered.append(item)
            continue
        if pub_dt < window_start:
            skipped_old += 1
            continue
        if pub_dt > now_utc + timedelta(hours=1):
            skipped_future += 1
            continue
        item['_pub_dt'] = pub_dt
        item['_time_str'] = format_news_time(pub_dt)
        time_filtered.append(item)

    print(f'[News Collector] time filter: kept {len(time_filtered)} (skipped: {skipped_old} old, {skipped_future} future, {skipped_no_time} no_time)')

    # 去重 (按标题)
    seen_titles = set()
    unique_items = []
    for item in time_filtered:
        title_key = item['title'].lower().strip()[:80]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_items.append(item)

    print(f'[News Collector] after dedup: {len(unique_items)}')

    # 分类 + 关键词筛选 + 打分
    scored_items = []
    category_counts = {}
    for item in unique_items:
        title = item['title']
        desc = item['description']
        combined_text = title + ' ' + desc

        # 必须包含至少一个关键词
        if not has_any_keyword(combined_text):
            continue

        # 分类
        category = categorize_news(title, desc)
        if not category:
            continue

        category_counts[category] = category_counts.get(category, 0) + 1

        # 打分
        score = score_news(title, desc, category)
        item['score'] = score
        item['category'] = category

        # 生成影响分析
        item['analysis'] = generate_impact_analysis(title, desc, category)

        scored_items.append(item)

    # 打印分类统计
    print(f'[News Collector] category distribution:')
    for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
        label = CATEGORY_KEYWORDS.get(cat, {}).get('label', cat)
        print(f'  {label}: {count}')

    # 按分数排序，分数相同则按时间倒序
    scored_items.sort(
        key=lambda x: (x['score'], x.get('_pub_dt') or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )

    # 确保分类多样性: 每个分类最多取3条，剩余按分数补充
    MAX_PER_CATEGORY = 3
    category_used = {}
    selected = []
    remaining = []

    for item in scored_items:
        cat = item['category']
        if category_used.get(cat, 0) < MAX_PER_CATEGORY:
            selected.append(item)
            category_used[cat] = category_used.get(cat, 0) + 1
        else:
            remaining.append(item)

    # 补充到8条
    TARGET_COUNT = 8
    for item in remaining:
        if len(selected) >= TARGET_COUNT:
            break
        selected.append(item)

    top_news = selected[:TARGET_COUNT]

    # 格式化输出 (含中文翻译 — 并行执行以加速)
    results = []
    print(f'[News Collector] translating {len(top_news)} news items to Chinese (parallel)...')

    # 准备每条新闻的摘要
    for item in top_news:
        summary = truncate_sentences(item['description'], max_sentences=3)
        if not summary or len(summary) < 20:
            summary = item['title']
        item['_summary'] = summary

    # 并行翻译所有标题和摘要
    translations = {}
    num_workers = min(len(top_news) * 2, 16)
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        future_map = {}
        for idx, item in enumerate(top_news):
            future_map[executor.submit(translate_to_chinese, item['title'])] = ('title', idx)
            future_map[executor.submit(translate_to_chinese, item['_summary'])] = ('summary', idx)
        for future in as_completed(future_map):
            field, idx = future_map[future]
            try:
                translations[(field, idx)] = future.result()
            except Exception:
                translations[(field, idx)] = top_news[idx]['title'] if field == 'title' else top_news[idx]['_summary']

    # 构建结果
    for idx, item in enumerate(top_news):
        title_zh = translations.get(('title', idx), item['title'])
        summary_zh = translations.get(('summary', idx), item['_summary'])
        summary = item['_summary']

        cat_info = CATEGORY_KEYWORDS.get(item['category'], {})
        results.append({
            'title': item['title'],
            'title_zh': title_zh,
            'summary': summary,
            'summary_zh': summary_zh,
            'analysis': item.get('analysis', ''),
            'category': item['category'],
            'category_label': cat_info.get('label', ''),
            'category_icon': cat_info.get('icon', ''),
            'category_color': cat_info.get('color', ''),
            'category_bg': cat_info.get('bg', ''),
            'source': item['source'],
            'link': item['link'],
            'pubDate': item.get('pubDate', ''),
            'time': item.get('_time_str', ''),
            'score': item['score'],
        })
        translated_ok = title_zh != item['title']
        print(f'  [{idx+1}/{len(top_news)}] {"OK" if translated_ok else "--"} {item["title"][:60]} -> {title_zh[:40]}')

    print(f'[News Collector] done: {len(results)} news items with Chinese translation (filtered from {len(unique_items)})')
    return results
