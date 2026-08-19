"""
runner.py — Python版管道入口

完整流程: 采集 → 清洗 → 分析 → 报告 + 邮件 → 保存 latest.json

数据源:
  美股: yfinance + CNBC
  A股: akshare + 同花顺(东方财富)
  数字货币: Binance API
  大宗商品: akshare + yfinance

用法: python backend/runner.py [collect|process|analyze|report|all]
"""

import sys
import os
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 解决 Windows GBK 编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目根目录和 backend 目录到 Python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, BACKEND_DIR)

# ── 配置 ──
def load_config():
    """从环境变量和 env 文件加载配置"""
    config = {}
    env_path = os.path.join(PROJECT_ROOT, 'config', 'default.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    return config

config = load_config()
SMTP_USER = os.environ.get('SMTP_USER', config.get('SMTP_USER', ''))
SMTP_PASS = os.environ.get('SMTP_PASS', config.get('SMTP_PASS', ''))
SMTP_HOST = os.environ.get('SMTP_HOST', config.get('SMTP_HOST', 'smtp.qq.com'))
SMTP_PORT = int(os.environ.get('SMTP_PORT', config.get('SMTP_PORT', '465')))

DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

today = datetime.now().strftime('%Y-%m-%d')

# ── Step 1: 采集 ──
def collect():
    """并行采集四大市场数据"""
    print('\n[Pipeline] ─── Step 1: 采集数据 ──')

    from collectors_py.us_stock import run as us_run
    from collectors_py.cn_stock import run as cn_run
    from collectors_py.crypto import run as crypto_run
    from collectors_py.commodity import run as commodity_run
    from collectors_py.news import run as news_run

    all_data = []
    news_data = []

    # 并行采集四大市场数据
    collectors = {
        'us': us_run,
        'cn': cn_run,
        'crypto': crypto_run,
        'commodity': commodity_run
    }

    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(func): name for name, func in collectors.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                data = future.result()
                results[name] = data
                count = len(data) if data else 0
                print(f'  {name}: {count} 条')
            except Exception as e:
                results[name] = []
                print(f'  {name}: 0 条 ({e})')

    for name, data in results.items():
        if data:
            all_data.extend(data)

    # 采集金融要闻 (单独执行，避免阻塞市场数据采集)
    try:
        news_data = news_run()
    except Exception as e:
        print(f'  news: 0 条 ({e})')
        news_data = []

    # 保存原始数据
    raw_path = os.path.join(DATA_DIR, f'raw_{today}.json')
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    # 保存新闻数据
    if news_data:
        news_path = os.path.join(DATA_DIR, f'news_{today}.json')
        with open(news_path, 'w', encoding='utf-8') as f:
            json.dump(news_data, f, ensure_ascii=False, indent=2)

    print(f'[Pipeline] 采集完成: {len(all_data)} 条数据, {len(news_data)} 条要闻')
    return all_data, news_data


# ── Step 2: 清洗整合 ──
def process_data(raw_data):
    """清洗整合数据"""
    print('\n[Pipeline] ─── Step 2: 清洗整合 ──')

    # 去重
    seen = {}
    unique_data = []
    for item in raw_data:
        key = f"{item['market']}_{item['symbol']}"
        if not seen.get(key):
            seen[key] = True
            unique_data.append(item)

    # 显著变动筛选
    THRESHOLD = 1.5
    significant = [d for d in unique_data if abs(d.get('change_pct', 0)) >= THRESHOLD]

    # 分组
    grouped = {}
    for m in ['us', 'cn', 'crypto', 'commodity']:
        grouped[m] = [d for d in unique_data if d.get('market') == m]

    # 统计摘要
    summary = {}
    for market, items in grouped.items():
        if not items:
            continue
        up_count = sum(1 for d in items if d.get('change_pct', 0) > 0)
        down_count = sum(1 for d in items if d.get('change_pct', 0) < 0)
        avg_change = sum(d.get('change_pct', 0) for d in items) / len(items)
        max_up = max(items, key=lambda d: d.get('change_pct', 0))
        max_down = min(items, key=lambda d: d.get('change_pct', 0))

        summary[market] = {
            'total': len(items),
            'upCount': up_count,
            'downCount': down_count,
            'flatCount': len(items) - up_count - down_count,
            'avgChange': round(avg_change, 2),
            'maxUp': {'symbol': max_up['symbol'], 'name': max_up['name'], 'change_pct': max_up.get('change_pct', 0)},
            'maxDown': {'symbol': max_down['symbol'], 'name': max_down['name'], 'change_pct': max_down.get('change_pct', 0)}
        }

    processed = {
        'date': today,
        'totalRecords': len(unique_data),
        'significantRecords': len(significant),
        'grouped': grouped,
        'summary': summary,
        'significant': significant
    }

    # 保存
    processed_path = os.path.join(DATA_DIR, f'processed_{today}.json')
    with open(processed_path, 'w', encoding='utf-8') as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)

    print(f'[Pipeline] 清洗完成: {len(unique_data)} 唯一, {len(significant)} 显著')
    return processed


# ── Step 3: 分析 ──
MARKET_NAMES = {'us': '美股', 'cn': 'A股', 'crypto': '数字货币', 'commodity': '大宗商品'}


def analyze_data(processed):
    """生成分析: 趋势、机会、风险"""
    print('\n[Pipeline] ─── Step 3: 分析生成 ──')

    trends = []
    for market, items in processed.get('grouped', {}).items():
        if not items:
            continue
        ratio = sum(1 for d in items if d.get('change_pct', 0) > 0) / len(items)

        # 判断趋势
        if ratio > 0.7:
            mt, mc = '强势上涨', '中'
        elif ratio > 0.5:
            mt, mc = '偏强', '中'
        elif ratio < 0.3:
            mt, mc = '普遍下跌', '中'
        elif ratio < 0.5:
            mt, mc = '偏弱', '中'
        else:
            mt, mc = '震荡', '低'

        trends.append({
            'market': market, 'type': 'market_trend',
            'description': f"{MARKET_NAMES[market]}整体{mt}，上涨占比{round(ratio*100)}%",
            'confidence': mc
        })

        # 个股强势
        for d in items:
            if d.get('change_pct', 0) > 3:
                conf = '高' if d['change_pct'] > 5 else '中'
                trends.append({
                    'market': market, 'type': 'individual_strong',
                    'symbol': d['symbol'], 'name': d['name'],
                    'description': f"{d['name']}({d['symbol']})涨幅{d['change_pct']}%，表现强势",
                    'confidence': conf,
                    'price': d.get('price', 0),
                    'change_pct': d.get('change_pct', 0)
                })

        # 个股弱势
        for d in items:
            if d.get('change_pct', 0) < -3:
                conf = '高' if d['change_pct'] < -5 else '中'
                trends.append({
                    'market': market, 'type': 'individual_weak',
                    'symbol': d['symbol'], 'name': d['name'],
                    'description': f"{d['name']}({d['symbol']})跌幅{d['change_pct']}%，表现疲弱",
                    'confidence': conf,
                    'price': d.get('price', 0),
                    'change_pct': d.get('change_pct', 0)
                })

    # 机会提示
    opportunities = []
    for market, items in processed.get('grouped', {}).items():
        if not items:
            continue
        for d in items:
            pct = d.get('change_pct', 0)
            if pct < -3 and pct > -8:
                conf = '低' if abs(pct) > 5 else '中'
                opportunities.append({
                    'market': market, 'type': 'dip_buying',
                    'symbol': d['symbol'], 'name': d['name'],
                    'description': f"{d['name']}回调{abs(pct)}%，关注低吸机会",
                    'confidence': conf,
                    'price': d.get('price', 0),
                    'change_pct': pct
                })
            if pct > 1.5 and pct < 3:
                opportunities.append({
                    'market': market, 'type': 'breakout_watch',
                    'symbol': d['symbol'], 'name': d['name'],
                    'description': f"{d['name']}温和上涨{pct}%，留意突破信号",
                    'confidence': '低',
                    'price': d.get('price', 0),
                    'change_pct': pct
                })

        # BTC联动
        if market == 'crypto':
            btc = next((d for d in items if d.get('symbol') == 'BTC'), None)
            if btc and btc.get('change_pct', 0) > 2:
                opportunities.append({
                    'market': 'crypto', 'type': 'correlation',
                    'symbol': 'BTC', 'name': '比特币',
                    'description': f"BTC领涨{btc['change_pct']}%，关注主流币联动机会",
                    'confidence': '中',
                    'price': btc.get('price', 0),
                    'change_pct': btc.get('change_pct', 0)
                })

    # 风险预警
    risks = []
    for market, items in processed.get('grouped', {}).items():
        if not items:
            continue
        for d in items:
            if d.get('change_pct', 0) < -5:
                risks.append({
                    'market': market, 'type': 'crash_warning',
                    'symbol': d['symbol'], 'name': d['name'],
                    'description': f"{d['name']}暴跌{abs(d['change_pct'])}%，风险极高",
                    'confidence': '高',
                    'price': d.get('price', 0),
                    'change_pct': d.get('change_pct', 0)
                })

        down_ratio = sum(1 for d in items if d.get('change_pct', 0) < 0) / len(items)
        if down_ratio > 0.8:
            risks.append({
                'market': market, 'type': 'systemic_risk',
                'symbol': 'ALL', 'name': MARKET_NAMES[market] + '整体',
                'description': f"{MARKET_NAMES[market]}超过80%标的下跌，存在系统性风险",
                'confidence': '高'
            })

        if market == 'crypto':
            btc = next((d for d in items if d.get('symbol') == 'BTC'), None)
            if btc and btc.get('change_pct', 0) < -3:
                risks.append({
                    'market': 'crypto', 'type': 'btc_decline',
                    'symbol': 'BTC', 'name': '比特币',
                    'description': f"BTC下跌{abs(btc['change_pct'])}%，可能带动整体币市回调",
                    'confidence': '高',
                    'price': btc.get('price', 0),
                    'change_pct': btc.get('change_pct', 0)
                })

    analysis = {
        'date': today,
        'trends': trends,
        'opportunities': opportunities,
        'risks': risks,
        'summary': processed.get('summary', {}),
        'grouped': processed.get('grouped', {})
    }

    # 保存
    analysis_path = os.path.join(DATA_DIR, f'analysis_{today}.json')
    with open(analysis_path, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    print(f'[Pipeline] 分析完成: {len(trends)} 趋势, {len(opportunities)} 机会, {len(risks)} 风险')
    return analysis


# ── Step 4: 报告 + 邮件 ──
def report_and_push(analysis, news_items=None):
    """生成报告 + 发送邮件 + 保存latest.json"""
    print('\n[Pipeline] ─── Step 4: 报告 + 邮件推送 ──')

    if news_items is None:
        news_items = []

    from formatter_py.report import generate_report, generate_summary, send_email

    html_content = generate_report(analysis, news_items)
    summary_text = generate_summary(analysis)

    # 读取订阅者
    sub_path = os.path.join(DATA_DIR, 'subscribers.json')
    subscribers = []
    if os.path.exists(sub_path):
        try:
            with open(sub_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                subscribers = [s for s in data.get('subscribers', []) if s.get('enabled', True)]
        except Exception:
            pass

    print(f'[Pipeline] {len(subscribers)} 位订阅者')

    # 发送邮件
    results = send_email(
        SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT,
        subscribers, html_content, summary_text, today
    )

    # 保存 latest.json 供看板使用
    latest_data = {
        'date': today,
        'updatedAt': datetime.now().isoformat(),
        'markets': {},
        'news': news_items,
        'analysis': {
            'trends': analysis.get('trends', []),
            'opportunities': analysis.get('opportunities', []),
            'risks': analysis.get('risks', []),
            'summary': analysis.get('summary', {})
        },
        'report': {'summary': summary_text},
        'emailResults': results
    }

    for market, items in analysis.get('grouped', {}).items():
        latest_data['markets'][market] = [
            {
                'symbol': d.get('symbol', ''),
                'name': d.get('name', ''),
                'price': d.get('price', 0),
                'change_pct': d.get('change_pct', 0),
                'volume': d.get('volume', 0),
                'high': d.get('high', 0),
                'low': d.get('low', 0),
                'open': d.get('open', 0),
                'prev_close': d.get('prev_close', 0)
            }
            for d in items
        ]

    latest_path = os.path.join(DATA_DIR, 'latest.json')
    with open(latest_path, 'w', encoding='utf-8') as f:
        json.dump(latest_data, f, ensure_ascii=False, indent=2)

    print('[Pipeline] latest.json 已保存')

    sent = sum(1 for r in results if r.get('success'))
    print(f'[Pipeline] 邮件: {sent}/{len(results)} 成功')
    return {'sent': sent, 'total': len(results)}


# ── 复盘模式: 采集 → 分析 → 报告 ──
def run_review():
    """市场复盘模式: 采集A股复盘数据 → 生成复盘报告 → 推送"""
    print('\n[Pipeline] ═══ 复盘模式启动 ═══')

    from collectors_py.market_review import run as review_run
    from formatter_py.report import generate_review_report, generate_review_summary_text, send_email, generate_review_pdf

    # 1. 采集复盘数据
    review_data = review_run()

    # 2. 生成报告
    html_content = generate_review_report(review_data)
    summary_text = generate_review_summary_text(review_data)

    # 3. 保存复盘数据
    review_path = os.path.join(DATA_DIR, f'review_{today}.json')
    with open(review_path, 'w', encoding='utf-8') as f:
        json.dump(review_data, f, ensure_ascii=False, indent=2)
    print(f'[Pipeline] 复盘数据已保存: review_{today}.json')

    # 保存到 latest_review.json 供看板使用
    latest_review_path = os.path.join(DATA_DIR, 'latest_review.json')
    with open(latest_review_path, 'w', encoding='utf-8') as f:
        json.dump({
            'date': today,
            'updatedAt': datetime.now().isoformat(),
            **review_data,
        }, f, ensure_ascii=False, indent=2)
    print('[Pipeline] latest_review.json 已保存')

    # 4. 读取订阅者
    sub_path = os.path.join(DATA_DIR, 'subscribers.json')
    subscribers = []
    if os.path.exists(sub_path):
        try:
            with open(sub_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                subscribers = [s for s in data.get('subscribers', []) if s.get('enabled', True)]
        except Exception:
            pass

    print(f'[Pipeline] {len(subscribers)} 位订阅者')

    # 5. 发送邮件（带 PDF 附件，weasyprint 不可用时降级纯文本+看板链接）
    subject = f'市场复盘与异动简报 {today}'
    pdf_bytes = None
    try:
        pdf_bytes = generate_review_pdf(review_data, base_url=os.path.dirname(os.path.abspath(__file__)))
        pdf_path = os.path.join(DATA_DIR, f'review_{today}.pdf')
        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)
        print(f'[Pipeline] PDF 已生成: review_{today}.pdf ({len(pdf_bytes)} bytes)')
    except Exception as e:
        print(f'[Pipeline] PDF 生成跳过(降级): {e}')
    results = send_email(
        SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT,
        subscribers, html_content, summary_text, today, subject=subject, pdf_bytes=pdf_bytes
    )

    sent = sum(1 for r in results if r.get('success'))
    print(f'[Pipeline] 邮件: {sent}/{len(results)} 成功')
    return {'sent': sent, 'total': len(results)}


# ── 主入口 ──
def main():
    # 检查运行模式: morning(常规) / review(复盘)
    pipeline_mode = os.environ.get('PIPELINE_MODE', 'morning').lower()

    if pipeline_mode == 'review':
        print(f'[Pipeline] ═══ 复盘模式 (PIPELINE_MODE=review) 日期: {today} ═══')
        run_review()
        print('\n[Pipeline] ✅ 复盘完成')
        return

    task = sys.argv[1] if len(sys.argv) > 1 else 'all'
    tasks = ['collect', 'process', 'analyze', 'report'] if task == 'all' else [task]

    print(f'[Pipeline] 开始: {" → ".join(tasks)}  日期: {today}  模式: {pipeline_mode}')

    raw_data = None
    news_data = []
    processed_data = None
    analysis_data = None

    for t in tasks:
        try:
            if t == 'collect':
                raw_data, news_data = collect()
            elif t == 'process':
                if not raw_data:
                    p = os.path.join(DATA_DIR, f'raw_{today}.json')
                    if os.path.exists(p):
                        with open(p, 'r', encoding='utf-8') as f:
                            raw_data = json.load(f)
                if raw_data:
                    processed_data = process_data(raw_data)
                else:
                    print('[Pipeline] 无原始数据，跳过清洗')
            elif t == 'analyze':
                if not processed_data:
                    p = os.path.join(DATA_DIR, f'processed_{today}.json')
                    if os.path.exists(p):
                        with open(p, 'r', encoding='utf-8') as f:
                            processed_data = json.load(f)
                if processed_data:
                    analysis_data = analyze_data(processed_data)
                else:
                    print('[Pipeline] 无清洗数据，跳过分析')
            elif t == 'report':
                if not analysis_data:
                    p = os.path.join(DATA_DIR, f'analysis_{today}.json')
                    if os.path.exists(p):
                        with open(p, 'r', encoding='utf-8') as f:
                            analysis_data = json.load(f)
                if analysis_data:
                    report_and_push(analysis_data, news_data)
                else:
                    print('[Pipeline] 无分析数据，跳过推送')
        except Exception as e:
            print(f'[Pipeline] {t} 失败: {e}')

    print('\n[Pipeline] ✅ 全部完成')


if __name__ == '__main__':
    main()
