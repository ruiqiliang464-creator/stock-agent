"""
commodity.py — 大宗商品数据采集

数据源：
  主力: akshare (国内期货主力合约)
  备用: yfinance (国际商品ETF/期货)

采集标的: 黄金、白银、原油、天然气、铜、铝、玉米、大豆、小麦、铁矿石、橡胶等
"""

import akshare as ak
import yfinance as yf
import requests
import json
import time

# 大宗商品关注列表
# 国内期货代码 (akshare用)
AKSHARE_FUTURES = [
    {'symbol': 'AU0', 'name': '沪金主力', 'target': 'GOLD'},
    {'symbol': 'AG0', 'name': '沪银主力', 'target': 'SILVER'},
    {'symbol': 'CU0', 'name': '沪铜主力', 'target': 'COPPER'},
    {'symbol': 'AL0', 'name': '沪铝主力', 'target': 'ALUMINUM'},
    {'symbol': 'RU0', 'name': '橡胶主力', 'target': 'RUBBER'},
    {'symbol': 'I0', 'name': '铁矿主力', 'target': 'IRON_ORE'},
    {'symbol': 'SC0', 'name': '原油主力', 'target': 'CRUDE_OIL'},
    {'symbol': 'C0', 'name': '玉米主力', 'target': 'CORN'},
    {'symbol': 'A0', 'name': '豆一主力', 'target': 'SOYBEAN'},
    {'symbol': 'M0', 'name': '豆粕主力', 'target': 'SOYBEAN_MEAL'},
    {'symbol': 'Y0', 'name': '豆油主力', 'target': 'SOYBEAN_OIL'},
    {'symbol': 'W0', 'name': '麦主力', 'target': 'WHEAT'},
    {'symbol': 'FG0', 'name': '玻璃主力', 'target': 'GLASS'},
    {'symbol': 'RB0', 'name': '螺纹主力', 'target': 'REBAR'},
]

# yfinance 国际商品代码
YFINANCE_COMMODITY = {
    'GC=F': {'target': 'GOLD', 'name': '黄金期货'},
    'SI=F': {'target': 'SILVER', 'name': '白银期货'},
    'CL=F': {'target': 'CRUDE_OIL', 'name': '原油期货(WTI)'},
    'BZ=F': {'target': 'BRENT', 'name': '原油期货(布伦特)'},
    'NG=F': {'target': 'NATURAL_GAS', 'name': '天然气期货'},
    'HG=F': {'target': 'COPPER', 'name': '铜期货'},
    'ALI=F': {'target': 'ALUMINUM', 'name': '铝期货'},
    'ZC=F': {'target': 'CORN', 'name': '玉米期货'},
    'ZS=F': {'target': 'SOYBEAN', 'name': '大豆期货'},
    'ZW=F': {'target': 'WHEAT', 'name': '小麦期货'},
}

# 单位映射
UNIT_MAP = {
    'GOLD': 'CNY/g', 'SILVER': 'CNY/kg', 'CRUDE_OIL': 'CNY/barrel',
    'COPPER': 'CNY/ton', 'ALUMINUM': 'CNY/ton', 'IRON_ORE': 'CNY/ton',
    'RUBBER': 'CNY/ton', 'CORN': 'CNY/ton', 'SOYBEAN': 'CNY/ton',
    'WHEAT': 'CNY/ton', 'BRENT': 'USD/barrel', 'NATURAL_GAS': 'USD/MMBtu',
    'REBAR': 'CNY/ton', 'GLASS': 'CNY/ton',
}


def fetch_with_akshare():
    """用 akshare 获取国内期货主力合约行情（主力数据源）"""
    results = []

    try:
        # akshare 获取期货主力合约行情
        df = ak.futures_zh_spot(symbol='主力合约', market='SHFE')
        if df is not None and len(df) > 0:
            for row in df.itertuples():
                # 尝试匹配我们的关注列表
                variety = getattr(row, '品种', '')
                price = float(getattr(row, '最新价', 0) or 0)
                change_pct = float(getattr(row, '涨跌幅', 0) or 0)
                prev_close = float(getattr(row, '昨结算', 0) or 0)
                volume = int(getattr(row, '成交量', 0) or 0)

                if price > 0:
                    results.append({
                        'market': 'commodity',
                        'symbol': variety,
                        'name': getattr(row, '合约', variety),
                        'price': round(price, 2),
                        'change_pct': round(change_pct, 2),
                        'volume': volume,
                        'high': float(getattr(row, '最高价', 0) or price),
                        'low': float(getattr(row, '最低价', 0) or price),
                        'open': float(getattr(row, '今开盘', 0) or price),
                        'prev_close': round(prev_close, 2),
                        'market_cap': 0,
                        'extra': json.dumps({'source': 'akshare_shfe', 'unit': 'CNY'})
                    })
                    print(f'[Commodity] akshare: {variety} {price:.2f} ({change_pct:+.2f}%)')
    except Exception as e:
        print(f'[Commodity] akshare SHFE期货失败: {e}')

    # 尝试其他交易所 (DCE大商所, CZCE郑商所)
    for market_code, market_name in [('DCE', '大商所'), ('CZCE', '郑商所'), ('INE', '能源中心'), ('GFEX', '广期所')]:
        try:
            df = ak.futures_zh_spot(symbol='主力合约', market=market_code)
            if df is not None and len(df) > 0:
                for row in df.itertuples():
                    variety = getattr(row, '品种', '')
                    price = float(getattr(row, '最新价', 0) or 0)
                    change_pct = float(getattr(row, '涨跌幅', 0) or 0)
                    prev_close = float(getattr(row, '昨结算', 0) or 0)
                    volume = int(getattr(row, '成交量', 0) or 0)

                    if price > 0:
                        results.append({
                            'market': 'commodity',
                            'symbol': variety,
                            'name': getattr(row, '合约', variety),
                            'price': round(price, 2),
                            'change_pct': round(change_pct, 2),
                            'volume': volume,
                            'high': float(getattr(row, '最高价', 0) or price),
                            'low': float(getattr(row, '最低价', 0) or price),
                            'open': float(getattr(row, '今开盘', 0) or price),
                            'prev_close': round(prev_close, 2),
                            'market_cap': 0,
                            'extra': json.dumps({'source': f'akshare_{market_code}', 'unit': 'CNY'})
                        })
                        print(f'[Commodity] akshare {market_name}: {variety} {price:.2f} ({change_pct:+.2f}%)')
        except Exception as e:
            print(f'[Commodity] akshare {market_name} 失败: {e}')

    return results


def fetch_with_yfinance():
    """用 yfinance 获取国际商品期货行情（备用数据源）"""
    results = []

    for yf_symbol, info in YFINANCE_COMMODITY.items():
        try:
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period='1d')

            if hist is not None and len(hist) > 0:
                latest = hist.iloc[-1]
                price = float(latest.get('Close', 0))
                open_price = float(latest.get('Open', 0))
                high = float(latest.get('High', 0))
                low = float(latest.get('Low', 0))
                volume = int(latest.get('Volume', 0) or 0)
                prev_close = open_price  # 期货没有昨收，用开盘价近似

                # 如果有2天数据，用前一天收盘作为昨收
                if len(hist) > 1:
                    prev_close = float(hist.iloc[-2].get('Close', open_price))

                change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0

                if price > 0:
                    results.append({
                        'market': 'commodity',
                        'symbol': info['target'],
                        'name': info['name'],
                        'price': round(price, 2),
                        'change_pct': change_pct,
                        'volume': volume,
                        'high': round(high, 2),
                        'low': round(low, 2),
                        'open': round(open_price, 2),
                        'prev_close': round(prev_close, 2),
                        'market_cap': 0,
                        'extra': json.dumps({
                            'source': 'yfinance',
                            'yf_symbol': yf_symbol,
                            'unit': 'USD'
                        })
                    })
                    print(f'[Commodity] yfinance: {info["name"]} ${price:.2f} ({change_pct:+.2f}%)')

        except Exception as e:
            print(f'[Commodity] yfinance {yf_symbol} 失败: {e}')

    return results


def fetch_with_eastmoney_futures():
    """用东方财富API获取期货行情（三级备用）"""
    results = []

    futures_codes = [
        {'code': '113.aum', 'name': '沪金主力', 'symbol': 'GOLD'},
        {'code': '113.agm', 'name': '沪银主力', 'symbol': 'SILVER'},
        {'code': '113.cum', 'name': '沪铜主力', 'symbol': 'COPPER'},
        {'code': '113.alm', 'name': '沪铝主力', 'symbol': 'ALUMINUM'},
        {'code': '113.rum', 'name': '橡胶主力', 'symbol': 'RUBBER'},
        {'code': '113.im', 'name': '铁矿主力', 'symbol': 'IRON_ORE'},
        {'code': '113.sc0', 'name': '原油主力', 'symbol': 'CRUDE_OIL'},
        {'code': '113.cm', 'name': '玉米主力', 'symbol': 'CORN'},
        {'code': '113.am', 'name': '豆一主力', 'symbol': 'SOYBEAN'},
        {'code': '113.wm', 'name': '麦主力', 'symbol': 'WHEAT'},
    ]

    secids = ','.join([f['code'] for f in futures_codes])
    try:
        url = f'https://push2.eastmoney.com/api/qt/ulist.np/get?secids={secids}&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18'
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.eastmoney.com/'}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()

        diff = data.get('data', {}).get('diff', [])
        if diff and isinstance(diff, list):
            for item in diff:
                matched = next((f for f in futures_codes if f['code'] == f"113.{item.get('f12', '')}"), None)
                symbol = matched['symbol'] if matched else 'UNKNOWN'
                name = matched['name'] if matched else (item.get('f14', '') or symbol)
                price = item.get('f2', 0) / 100 if isinstance(item.get('f2'), (int, float)) else 0
                change_pct = item.get('f3', 0) / 100 if isinstance(item.get('f3'), (int, float)) else 0

                if price > 0:
                    results.append({
                        'market': 'commodity',
                        'symbol': symbol,
                        'name': name,
                        'price': round(price, 2),
                        'change_pct': round(change_pct, 2),
                        'volume': int(item.get('f5', 0) or 0),
                        'high': round(item.get('f15', 0) / 100, 2) if isinstance(item.get('f15'), (int, float)) else round(price, 2),
                        'low': round(item.get('f16', 0) / 100, 2) if isinstance(item.get('f16'), (int, float)) else round(price, 2),
                        'open': round(item.get('f17', 0) / 100, 2) if isinstance(item.get('f17'), (int, float)) else round(price, 2),
                        'prev_close': round(item.get('f18', 0) / 100, 2) if isinstance(item.get('f18'), (int, float)) else 0,
                        'market_cap': 0,
                        'extra': json.dumps({'source': 'eastmoney_futures', 'unit': 'CNY'})
                    })
    except Exception as e:
        print(f'[Commodity] 东方财富期货API失败: {e}')

    return results


def run():
    """运行大宗商品采集: akshare主力 → yfinance备用 → 东方财富三级备用"""
    print('[Commodity Collector] 开始采集大宗商品数据...')

    # 先尝试 akshare（主力）
    results = fetch_with_akshare()

    # 用 yfinance 补充国际品种 (布伦特原油、天然气等国内期货覆盖不到的)
    target_symbols = {r['symbol'] for r in results}
    missing_international = [s for s in ['BRENT', 'NATURAL_GAS'] if s not in target_symbols]
    if missing_international or len(results) < 5:
        print('[Commodity] 用 yfinance 补充国际品种')
        yf_results = fetch_with_yfinance()
        existing = {r['symbol'] for r in results}
        for r in yf_results:
            if r['symbol'] not in existing:
                results.append(r)

    # 如果数据仍然不足，用东方财富兜底
    if len(results) < 5:
        print('[Commodity] 数据不足，用东方财富兜底')
        em_results = fetch_with_eastmoney_futures()
        existing = {r['symbol'] for r in results}
        for r in em_results:
            if r['symbol'] not in existing:
                results.append(r)

    # 如果 akshare 完全失败，全量 yfinance
    if len(results) == 0:
        print('[Commodity] akshare 无数据，全量切换 yfinance')
        results = fetch_with_yfinance()

    print(f'[Commodity Collector] 采集完成, 共 {len(results)} 条')
    return results
