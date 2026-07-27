"""
crypto.py — 数字货币数据采集

数据源: Binance REST API (主力, 无需认证)

采集标的: 20种主流数字货币
"""

import requests
import json
import time

# 数字货币关注列表 (Binance交易对)
DEFAULT_SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'SOLUSDT',
    'ADAUSDT', 'DOGEUSDT', 'DOTUSDT', 'AVAXUSDT', 'LINKUSDT',
    'LTCUSDT', 'TRXUSDT', 'UNIUSDT', 'NEARUSDT', 'XLMUSDT',
    'MATICUSDT', 'ETCUSDT', 'FILUSDT', 'SHIBUSDT', 'APTUSDT'
]

# 名称映射
NAME_MAP = {
    'BTCUSDT': '比特币', 'ETHUSDT': '以太坊', 'BNBUSDT': '币安币',
    'XRPUSDT': '瑞波币', 'SOLUSDT': 'Solana', 'ADAUSDT': 'Cardano',
    'DOGEUSDT': '狗狗币', 'DOTUSDT': 'Polkadot', 'AVAXUSDT': 'Avalanche',
    'LINKUSDT': 'Chainlink', 'LTCUSDT': '莱特币', 'TRXUSDT': '波场',
    'UNIUSDT': 'Uniswap', 'NEARUSDT': 'NEAR', 'XLMUSDT': 'Stellar',
    'MATICUSDT': 'Polygon', 'ETCUSDT': '以太经典', 'FILUSDT': 'Filecoin',
    'SHIBUSDT': '柴犬币', 'APTUSDT': 'Aptos'
}

SYMBOL_SHORT = {
    'BTCUSDT': 'BTC', 'ETHUSDT': 'ETH', 'BNBUSDT': 'BNB',
    'XRPUSDT': 'XRP', 'SOLUSDT': 'SOL', 'ADAUSDT': 'ADA',
    'DOGEUSDT': 'DOGE', 'DOTUSDT': 'DOT', 'AVAXUSDT': 'AVAX',
    'LINKUSDT': 'LINK', 'LTCUSDT': 'LTC', 'TRXUSDT': 'TRX',
    'UNIUSDT': 'UNI', 'NEARUSDT': 'NEAR', 'XLMUSDT': 'XLM',
    'MATICUSDT': 'MATIC', 'ETCUSDT': 'ETC', 'FILUSDT': 'FIL',
    'SHIBUSDT': 'SHIB', 'APTUSDT': 'APT'
}


def fetch_from_binance(symbols=None):
    """用 Binance REST API 获取24h行情（主力数据源）"""
    if symbols is None:
        symbols = DEFAULT_SYMBOLS

    results = []

    # Binance 24h ticker API (批量获取所有交易对，然后筛选)
    try:
        url = 'https://api.binance.com/api/v3/ticker/24hr'
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=20)

        if resp.status_code == 200:
            all_tickers = resp.json()
            # 筛选我们关注的交易对
            for ticker in all_tickers:
                symbol = ticker.get('symbol', '')
                if symbol in symbols:
                    price = float(ticker.get('lastPrice', 0))
                    change_pct = float(ticker.get('priceChangePercent', 0))
                    volume = float(ticker.get('volume', 0))
                    high = float(ticker.get('highPrice', 0))
                    low = float(ticker.get('lowPrice', 0))
                    open_price = float(ticker.get('openPrice', 0))
                    prev_close = open_price  # Binance没有昨收，用开盘价近似

                    if price > 0:
                        short_symbol = SYMBOL_SHORT.get(symbol, symbol.replace('USDT', ''))
                        name = NAME_MAP.get(symbol, short_symbol)
                        results.append({
                            'market': 'crypto',
                            'symbol': short_symbol,
                            'name': name,
                            'price': round(price, 2) if price > 1 else round(price, 6),
                            'change_pct': round(change_pct, 2),
                            'volume': round(volume, 2),
                            'high': round(high, 2) if high > 1 else round(high, 6),
                            'low': round(low, 2) if low > 1 else round(low, 6),
                            'open': round(open_price, 2) if open_price > 1 else round(open_price, 6),
                            'prev_close': round(prev_close, 2) if prev_close > 1 else round(prev_close, 6),
                            'market_cap': 0,
                            'extra': json.dumps({
                                'quote_volume': float(ticker.get('quoteVolume', 0)),
                                'source': 'binance'
                            })
                        })
                        display_price = f'${price:.2f}' if price > 1 else f'${price:.6f}'
                        print(f'[Crypto] Binance: {name}({short_symbol}) {display_price} ({change_pct:+.2f}%)')
    except Exception as e:
        print(f'[Crypto] Binance API批量失败: {e}')

    # 如果批量获取失败，逐个获取
    if len(results) == 0:
        for symbol in symbols:
            try:
                url = f'https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}'
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    ticker = resp.json()
                    price = float(ticker.get('lastPrice', 0))
                    change_pct = float(ticker.get('priceChangePercent', 0))
                    volume = float(ticker.get('volume', 0))
                    high = float(ticker.get('highPrice', 0))
                    low = float(ticker.get('lowPrice', 0))
                    open_price = float(ticker.get('openPrice', 0))

                    if price > 0:
                        short_symbol = SYMBOL_SHORT.get(symbol, symbol.replace('USDT', ''))
                        name = NAME_MAP.get(symbol, short_symbol)
                        results.append({
                            'market': 'crypto',
                            'symbol': short_symbol,
                            'name': name,
                            'price': round(price, 2) if price > 1 else round(price, 6),
                            'change_pct': round(change_pct, 2),
                            'volume': round(volume, 2),
                            'high': round(high, 2) if high > 1 else round(high, 6),
                            'low': round(low, 2) if low > 1 else round(low, 6),
                            'open': round(open_price, 2) if open_price > 1 else round(open_price, 6),
                            'prev_close': round(open_price, 2) if open_price > 1 else round(open_price, 6),
                            'market_cap': 0,
                            'extra': json.dumps({'source': 'binance_single'})
                        })
            except Exception as e:
                print(f'[Crypto] Binance {symbol} 失败: {e}')

    return results


def fetch_from_coingecko():
    """用 CoinGecko API 获取数字货币行情（备用数据源）"""
    ids = [
        'bitcoin', 'ethereum', 'binancecoin', 'ripple', 'solana',
        'cardano', 'dogecoin', 'polkadot', 'avalanche-2', 'chainlink',
        'litecoin', 'tron', 'uniswap', 'near', 'stellar',
        'polygon-pos', 'ethereum-classic', 'filecoin', 'shiba-inu', 'aptos'
    ]

    results = []
    try:
        url = f'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={",".join(ids)}&order=market_cap_desc&per_page=50&page=1&sparkline=false'
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=20)

        if resp.status_code == 200 and isinstance(resp.json(), list):
            for coin in resp.json():
                price = float(coin.get('current_price', 0) or 0)
                change_pct = float(coin.get('price_change_percentage_24h', 0) or 0)
                prev_price = price - float(coin.get('price_change_24h', 0) or 0)

                if price > 0:
                    results.append({
                        'market': 'crypto',
                        'symbol': coin.get('symbol', '').upper(),
                        'name': coin.get('name', ''),
                        'price': round(price, 2) if price > 1 else round(price, 6),
                        'change_pct': round(change_pct, 2),
                        'volume': float(coin.get('total_volume', 0) or 0),
                        'high': float(coin.get('high_24h', 0) or price),
                        'low': float(coin.get('low_24h', 0) or price),
                        'open': round(prev_price, 2) if prev_price > 1 else round(prev_price, 6),
                        'prev_close': round(prev_price, 2) if prev_price > 1 else round(prev_price, 6),
                        'market_cap': float(coin.get('market_cap', 0) or 0),
                        'extra': json.dumps({'source': 'coingecko'})
                    })
    except Exception as e:
        print(f'[Crypto] CoinGecko失败: {e}')

    return results


def run():
    """运行数字货币采集: Binance主力 → CoinGecko备用"""
    print('[Crypto Collector] 开始采集数字货币数据...')

    # 先尝试 Binance（主力）
    results = fetch_from_binance()

    # 如果 Binance 结果不足，用 CoinGecko 补充
    if len(results) < len(DEFAULT_SYMBOLS) * 0.5:
        print(f'[Crypto] Binance 数据不足({len(results)}条)，用CoinGecko补充')
        cg_results = fetch_from_coingecko()
        existing = {r['symbol'] for r in results}
        for r in cg_results:
            if r['symbol'] not in existing:
                results.append(r)

    # 如果 Binance 完全失败，全量用 CoinGecko
    if len(results) == 0:
        print('[Crypto] Binance 无数据，全量切换 CoinGecko')
        results = fetch_from_coingecko()

    print(f'[Crypto Collector] 采集完成, 共 {len(results)} 条')
    return results
