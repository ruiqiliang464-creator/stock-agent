"""
us_stock.py — 美股数据采集

数据源：
  主力: yfinance (Python库, Yahoo Finance封装)
  备用: CNBC API (实时行情)

采集标的: 20只美股龙头
"""

import yfinance as yf
import requests
import json
import time

# 美股关注列表
DEFAULT_SYMBOLS = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'JPM', 'V', 'WMT',
    'DIS', 'NFLX', 'AMD', 'INTC', 'BA', 'GS', 'CVX', 'XOM', 'PFE', 'UNH'
]


def fetch_with_yfinance(symbols=None):
    """用 yfinance 批量获取美股行情（主力数据源）"""
    if symbols is None:
        symbols = DEFAULT_SYMBOLS

    results = []
    # yfinance 支持批量下载
    try:
        tickers = yf.Tickers(' '.join(symbols))
        for symbol in symbols:
            try:
                ticker = tickers.tickers[symbol]
                info = ticker.info

                # 优先从 info 获取完整数据
                price = info.get('currentPrice') or info.get('regularMarketPrice') or 0
                prev_close = info.get('previousClose') or info.get('regularMarketPreviousClose') or 0
                change_pct = info.get('regularMarketChangePercent', 0)

                # 如果 info 数据不完整，从 fast_info 补充
                if price == 0:
                    try:
                        fast = ticker.fast_info
                        price = fast.last_price or 0
                        prev_close = fast.previous_close or 0
                        if prev_close > 0 and price > 0:
                            change_pct = round((price - prev_close) / prev_close * 100, 2)
                    except Exception:
                        pass

                # 如果仍然没有数据，用 history 兜底
                if price == 0 or prev_close == 0:
                    try:
                        hist = ticker.history(period='1d')
                        if not hist.empty:
                            price = hist['Close'].iloc[-1] if len(hist) > 0 else 0
                            prev_close = hist['Open'].iloc[0] if len(hist) > 0 else 0
                            if prev_close > 0 and price > 0:
                                change_pct = round((price - prev_close) / prev_close * 100, 2)
                    except Exception:
                        pass

                if price > 0:
                    name = info.get('shortName') or info.get('longName') or symbol
                    results.append({
                        'market': 'us',
                        'symbol': symbol,
                        'name': name,
                        'price': round(price, 2),
                        'change_pct': round(change_pct, 2) if change_pct else 0,
                        'volume': info.get('volume') or info.get('regularMarketVolume') or 0,
                        'high': info.get('dayHigh') or info.get('regularMarketDayHigh') or round(price, 2),
                        'low': info.get('dayLow') or info.get('regularMarketDayLow') or round(price, 2),
                        'open': info.get('open') or info.get('regularMarketOpen') or round(prev_close, 2),
                        'prev_close': round(prev_close, 2),
                        'market_cap': info.get('marketCap') or 0,
                        'extra': json.dumps({'currency': info.get('currency', 'USD'), 'source': 'yfinance'})
                    })
                    print(f'[US Stock] yfinance: {symbol} ${price:.2f} ({change_pct:+.2f}%)')

            except Exception as e:
                print(f'[US Stock] yfinance {symbol} 失败: {e}')

    except Exception as e:
        print(f'[US Stock] yfinance 批量失败: {e}')

    return results


def fetch_with_cnbc(symbols=None):
    """用 CNBC API 获取美股行情（备用数据源）"""
    if symbols is None:
        symbols = DEFAULT_SYMBOLS

    results = []
    for symbol in symbols:
        try:
            # CNBC 实时行情接口
            url = f'https://quote.cnbc.com/quote-html-webservice/quoteData.json?symbols={symbol}&requestMethod=quick&exg=US&fields=lastPrice,change,changePercent,volume,high,low,open,previousClose,name'
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Accept': 'application/json'}
            resp = requests.get(url, headers=headers, timeout=10)

            if resp.status_code != 200:
                continue

            data = resp.json()
            quote = data.get('QuickQuoteResult', {}).get('QuickQuote', {})
            if not quote:
                # 尝试另一种结构
                quotes = data.get('quotedata', {})
                if isinstance(quotes, dict):
                    quote = quotes.get(symbol, {})
                elif isinstance(quotes, list) and len(quotes) > 0:
                    quote = quotes[0]

            if not quote:
                continue

            price = float(quote.get('lastPrice', 0) or 0)
            prev_close = float(quote.get('previousClose', 0) or 0)
            change_pct = float(quote.get('changePercent', 0) or 0)

            # CNBC 返回的 changePercent 可能是绝对值而非百分比
            if abs(change_pct) < 1 and prev_close > 0:
                # 可能是小数形式 (如 0.0352 表示 3.52%)
                change_pct = round(change_pct * 100, 2)
            else:
                change_pct = round(change_pct, 2)

            if price > 0:
                name = quote.get('name', symbol)
                results.append({
                    'market': 'us',
                    'symbol': symbol,
                    'name': name,
                    'price': round(price, 2),
                    'change_pct': change_pct,
                    'volume': int(quote.get('volume', 0) or 0),
                    'high': float(quote.get('high', 0) or 0),
                    'low': float(quote.get('low', 0) or 0),
                    'open': float(quote.get('open', 0) or 0),
                    'prev_close': round(prev_close, 2),
                    'market_cap': 0,
                    'extra': json.dumps({'source': 'cnbc'})
                })
                print(f'[US Stock] CNBC: {symbol} ${price:.2f} ({change_pct:+.2f}%)')

        except Exception as e:
            print(f'[US Stock] CNBC {symbol} 失败: {e}')

    return results


def run(symbols=None):
    """运行美股采集: yfinance主力 → CNBC备用"""
    print('[US Stock Collector] 开始采集美股数据...')

    # 先尝试 yfinance（主力）
    results = fetch_with_yfinance(symbols)

    # 如果 yfinance 结果不足，用 CNBC 补充缺失的标的
    if len(results) < len(symbols or DEFAULT_SYMBOLS) * 0.8:
        missing = [s for s in (symbols or DEFAULT_SYMBOLS)
                   if not any(r['symbol'] == s for r in results)]
        if missing:
            print(f'[US Stock] yfinance 缺失 {len(missing)} 个标的，尝试 CNBC 补充')
            cnbc_results = fetch_with_cnbc(missing)
            results.extend(cnbc_results)

    # 如果 yfinance 完全失败，全量用 CNBC
    if len(results) == 0:
        print('[US Stock] yfinance 无数据，全量切换 CNBC')
        results = fetch_with_cnbc(symbols)

    print(f'[US Stock Collector] 采集完成, 共 {len(results)} 条')
    return results
