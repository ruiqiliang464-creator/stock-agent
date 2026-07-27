"""
cn_stock.py — A股数据采集

数据源：
  主力: akshare (Python库, 最全的A股数据源)
  备用1: 东方财富API (同花顺等行情接口)
  备用2: yfinance (Yahoo Finance国际接口, 可从境外IP访问)

采集标的: 3大指数 + 20只热门个股
"""

import akshare as ak
import requests
import json
import time
import yfinance as yf

# A股关注列表
DEFAULT_INDEX = [
    {'code': '000001', 'name': '上证指数', 'market': 'sh'},
    {'code': '399001', 'name': '深证成指', 'market': 'sz'},
    {'code': '399006', 'name': '创业板指', 'market': 'sz'},
]

DEFAULT_STOCKS = [
    {'code': '600519', 'name': '贵州茅台', 'market': 'sh'},
    {'code': '000858', 'name': '五粮液', 'market': 'sz'},
    {'code': '601318', 'name': '中国平安', 'market': 'sh'},
    {'code': '000333', 'name': '美的集团', 'market': 'sz'},
    {'code': '600036', 'name': '招商银行', 'market': 'sh'},
    {'code': '601012', 'name': '隆基绿能', 'market': 'sh'},
    {'code': '002594', 'name': '比亚迪', 'market': 'sz'},
    {'code': '000001', 'name': '平安银行', 'market': 'sz'},
    {'code': '600900', 'name': '长江电力', 'market': 'sh'},
    {'code': '300750', 'name': '宁德时代', 'market': 'sz'},
    {'code': '601899', 'name': '紫金矿业', 'market': 'sh'},
    {'code': '002415', 'name': '海康威视', 'market': 'sz'},
    {'code': '600276', 'name': '恒瑞医药', 'market': 'sh'},
    {'code': '000651', 'name': '格力电器', 'market': 'sz'},
    {'code': '603259', 'name': '药明康德', 'market': 'sh'},
    {'code': '002714', 'name': '牧原股份', 'market': 'sz'},
    {'code': '688981', 'name': '中芯国际', 'market': 'sh'},
    {'code': '300059', 'name': '东方财富', 'market': 'sz'},
    {'code': '600030', 'name': '中信证券', 'market': 'sh'},
    {'code': '601398', 'name': '工商银行', 'market': 'sh'},
]


def fetch_with_akshare():
    """用 akshare 获取A股行情（主力数据源）"""
    results = []
    all_items = DEFAULT_INDEX + DEFAULT_STOCKS

    for item in all_items:
        code = item['code']
        market_prefix = item['market']

        try:
            # akshare 获取个股实时行情
            # 指数用 stock_zh_index_daily_em, 个股用 stock_zh_a_spot_em
            if market_prefix in ('sh', 'sz') and code.startswith(('399', '0000')):
                # 指数行情
                try:
                    df = ak.stock_zh_index_daily_em(symbol=f'{market_prefix}{code}')
                    if df is not None and len(df) > 0:
                        latest = df.iloc[-1]
                        price = float(latest.get('close', 0))
                        prev_close = float(df.iloc[-2].get('close', 0)) if len(df) > 1 else price
                        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                        results.append({
                            'market': 'cn',
                            'symbol': code,
                            'name': item['name'],
                            'price': round(price, 2),
                            'change_pct': change_pct,
                            'volume': int(latest.get('volume', 0) or 0),
                            'high': float(latest.get('high', 0) or price),
                            'low': float(latest.get('low', 0) or price),
                            'open': float(latest.get('open', 0) or price),
                            'prev_close': round(prev_close, 2),
                            'market_cap': 0,
                            'extra': json.dumps({'source': 'akshare_index'})
                        })
                        print(f'[CN Stock] akshare指数: {item["name"]} {price:.2f} ({change_pct:+.2f}%)')
                except Exception as e:
                    print(f'[CN Stock] akshare指数 {code} 失败: {e}')
            else:
                # 个股行情 - 用批量接口效率更高
                pass  # 批量在下面处理

        except Exception as e:
            print(f'[CN Stock] akshare {code} 失败: {e}')

    # 批量获取A股个股行情
    try:
        df = ak.stock_zh_a_spot_em()
        if df is not None and len(df) > 0:
            stock_codes = {item['code']: item['name'] for item in DEFAULT_STOCKS}
            for row in df.itertuples():
                row_code = str(row.代码)
                if row_code in stock_codes:
                    price = float(row.最新价 or 0)
                    change_pct = float(row.涨跌幅 or 0)
                    prev_close = float(row.昨收 or 0)
                    if price > 0:
                        results.append({
                            'market': 'cn',
                            'symbol': row_code,
                            'name': stock_codes[row_code],
                            'price': round(price, 2),
                            'change_pct': round(change_pct, 2),
                            'volume': int(row.成交量 or 0),
                            'high': float(row.最高 or 0),
                            'low': float(row.最低 or 0),
                            'open': float(row.今开 or 0),
                            'prev_close': round(prev_close, 2),
                            'market_cap': float(row.总市值 or 0),
                            'extra': json.dumps({'source': 'akshare_spot'})
                        })
                        print(f'[CN Stock] akshare个股: {stock_codes[row_code]} {price:.2f} ({change_pct:+.2f}%)')
    except Exception as e:
        print(f'[CN Stock] akshare批量个股失败: {e}')

    return results


def fetch_with_eastmoney():
    """用东方财富API获取A股行情（备用数据源，兼容同花顺接口）"""
    results = []
    all_items = DEFAULT_INDEX + DEFAULT_STOCKS

    # 东方财富实时行情API (批量)
    secids = []
    for item in all_items:
        prefix = '1' if item['market'] == 'sh' else '0'
        secids.append(f'{prefix}.{item["code"]}')

    secid_str = ','.join(secids)
    try:
        url = f'https://push2.eastmoney.com/api/qt/ulist.np/get?secids={secid_str}&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18'
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.eastmoney.com/'}
        resp = requests.get(url, headers=headers, timeout=(10, 30))
        data = resp.json()

        diff = data.get('data', {}).get('diff', [])
        if diff and isinstance(diff, list):
            name_map = {item['code']: item['name'] for item in all_items}
            for item in diff:
                code = item.get('f12', '')
                name = item.get('f14', '') or name_map.get(code, code)
                price = item.get('f2', 0) / 100 if isinstance(item.get('f2'), (int, float)) else 0
                change_pct = item.get('f3', 0) / 100 if isinstance(item.get('f3'), (int, float)) else 0
                prev_close = item.get('f18', 0) / 100 if isinstance(item.get('f18'), (int, float)) else 0

                if price > 0 and code:
                    results.append({
                        'market': 'cn',
                        'symbol': code,
                        'name': name,
                        'price': round(price, 2),
                        'change_pct': round(change_pct, 2),
                        'volume': int(item.get('f5', 0) or 0),
                        'high': round(item.get('f15', 0) / 100, 2) if isinstance(item.get('f15'), (int, float)) else round(price, 2),
                        'low': round(item.get('f16', 0) / 100, 2) if isinstance(item.get('f16'), (int, float)) else round(price, 2),
                        'open': round(item.get('f17', 0) / 100, 2) if isinstance(item.get('f17'), (int, float)) else round(price, 2),
                        'prev_close': round(prev_close, 2),
                        'market_cap': 0,
                        'extra': json.dumps({'source': 'eastmoney'})
                    })
    except Exception as e:
        print(f'[CN Stock] 东方财富API失败: {e}')

    return results


def fetch_with_yfinance():
    """用 yfinance 获取A股行情（第三备用，可从境外IP访问）

    Yahoo Finance 对中国股票使用后缀:
      上海证券交易所: .SS (如 600519.SS)
      深圳证券交易所: .SZ (如 000858.SZ)
    """
    results = []

    # yfinance 指数代码映射 (Yahoo Finance 对指数使用不同格式)
    index_yf_map = {
        '000001': '000001.SS',   # 上证指数
        '399001': '399001.SZ',   # 深证成指
        '399006': '399006.SZ',   # 创业板指
    }

    # 先处理指数
    for item in DEFAULT_INDEX:
        code = item['code']
        yf_symbol = index_yf_map.get(code)
        if not yf_symbol:
            continue

        try:
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period='5d')

            if hist is not None and len(hist) > 0:
                latest = hist.iloc[-1]
                prev_close = float(hist.iloc[-2].get('Close', 0)) if len(hist) > 1 else float(latest.get('Close', 0))
                price = float(latest.get('Close', 0))

                if price > 0:
                    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                    results.append({
                        'market': 'cn',
                        'symbol': code,
                        'name': item['name'],
                        'price': round(price, 2),
                        'change_pct': change_pct,
                        'volume': int(latest.get('Volume', 0) or 0),
                        'high': float(latest.get('High', 0) or price),
                        'low': float(latest.get('Low', 0) or price),
                        'open': float(latest.get('Open', 0) or price),
                        'prev_close': round(prev_close, 2),
                        'market_cap': 0,
                        'extra': json.dumps({'source': 'yfinance_cn_index'})
                    })
                    print(f'[CN Stock] yfinance指数: {item["name"]}({yf_symbol}) {price:.2f} ({change_pct:+.2f}%)')
            else:
                print(f'[CN Stock] yfinance指数 {yf_symbol} 无数据')
        except Exception as e:
            print(f'[CN Stock] yfinance指数 {yf_symbol} 失败: {e}')

    # 再处理个股
    for item in DEFAULT_STOCKS:
        code = item['code']
        market_prefix = item['market']

        if market_prefix == 'sh':
            yf_symbol = f'{code}.SS'
        else:
            yf_symbol = f'{code}.SZ'

        try:
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period='5d')

            if hist is not None and len(hist) > 0:
                latest = hist.iloc[-1]
                prev_close = float(hist.iloc[-2].get('Close', 0)) if len(hist) > 1 else float(latest.get('Close', 0))
                price = float(latest.get('Close', 0))

                if price > 0:
                    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                    results.append({
                        'market': 'cn',
                        'symbol': code,
                        'name': item['name'],
                        'price': round(price, 2),
                        'change_pct': change_pct,
                        'volume': int(latest.get('Volume', 0) or 0),
                        'high': float(latest.get('High', 0) or price),
                        'low': float(latest.get('Low', 0) or price),
                        'open': float(latest.get('Open', 0) or price),
                        'prev_close': round(prev_close, 2),
                        'market_cap': 0,
                        'extra': json.dumps({'source': 'yfinance_cn_stock'})
                    })
                    print(f'[CN Stock] yfinance个股: {item["name"]}({yf_symbol}) {price:.2f} ({change_pct:+.2f}%)')
            else:
                print(f'[CN Stock] yfinance个股 {yf_symbol} 无数据')
        except Exception as e:
            print(f'[CN Stock] yfinance个股 {yf_symbol} 失败: {e}')

    return results


def run():
    """运行A股采集: akshare主力 → 东方财富备用 → yfinance第三备用"""
    print('[CN Stock Collector] 开始采集A股数据...')

    total_target = len(DEFAULT_INDEX + DEFAULT_STOCKS)
    half_target = total_target * 0.5

    # 先尝试 akshare（主力），最多重试3次
    results = []
    for attempt in range(3):
        results = fetch_with_akshare()
        if len(results) >= half_target:
            break
        if attempt < 2:
            print(f'[CN Stock] akshare 第{attempt+1}次尝试数据不足({len(results)}条)，等待5秒后重试')
            time.sleep(5)

    # 如果 akshare 结果不足，用东方财富补充，最多重试3次
    if len(results) < half_target:
        print(f'[CN Stock] akshare 数据不足({len(results)}条)，用东方财富补充')
        for attempt in range(3):
            em_results = fetch_with_eastmoney()
            if em_results:
                existing_codes = {r['symbol'] for r in results}
                for r in em_results:
                    if r['symbol'] not in existing_codes:
                        results.append(r)
                break
            if attempt < 2:
                print(f'[CN Stock] 东方财富第{attempt+1}次尝试失败，等待5秒后重试')
                time.sleep(5)

    # 如果东方财富也不足，用 yfinance 补充
    if len(results) < half_target:
        print(f'[CN Stock] 东方财富数据不足({len(results)}条)，用yfinance补充')
        yf_results = fetch_with_yfinance()
        if yf_results:
            existing_codes = {r['symbol'] for r in results}
            for r in yf_results:
                if r['symbol'] not in existing_codes:
                    results.append(r)

    # 如果全部失败，全量用 yfinance
    if len(results) == 0:
        print('[CN Stock] 全部数据源失败，全量切换yfinance')
        results = fetch_with_yfinance()

    print(f'[CN Stock Collector] 采集完成, 共 {len(results)} 条')
    return results
