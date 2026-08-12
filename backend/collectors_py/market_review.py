"""
market_review.py — A股市场复盘数据采集与异动分析

数据采集:
  1. 核心指数收盘数据 (上证指数, 深证成指, 创业板指, 沪深300, 科创50)
  2. 涨跌停家数、涨跌家数比
  3. 北向资金流向
  4. 两融余额变化
  5. 行业板块资金净流入/流出排名

信号计算:
  1. 市场广度指标 (上涨占比)
  2. 资金流向极端值 (北向单日净买入超100亿)
  3. 波动率分位与情绪冷热

异动识别:
  1. 量价配合异常、资金大幅调仓的板块
  2. 情绪过热或过冷的极端信号

数据源优先级: akshare → 新浪财经(并发) → 东方财富API(直连) → yfinance(仅指数)
"""

import akshare as ak
import requests
import json
import re
import math
import os
import time
import yfinance as yf
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed


def call_with_timeout(func, timeout=10, *args, **kwargs):
    """带超时保护地调用函数 (防止akshare等阻塞调用卡住管道)"""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            print(f'  [MarketReview] 调用超时 ({timeout}s), 跳过')
            return None

# ── 核心指数列表 ──
CORE_INDICES = [
    {'code': '000001', 'name': '上证指数', 'em_secid': '1.000001', 'ak_symbol': 'sh000001', 'yf_symbol': '000001.SS', 'sina_code': 'sh000001'},
    {'code': '399001', 'name': '深证成指', 'em_secid': '0.399001', 'ak_symbol': 'sz399001', 'yf_symbol': '399001.SZ', 'sina_code': 'sz399001'},
    {'code': '399006', 'name': '创业板指', 'em_secid': '0.399006', 'ak_symbol': 'sz399006', 'yf_symbol': '399006.SZ', 'sina_code': 'sz399006'},
    {'code': '000300', 'name': '沪深300', 'em_secid': '1.000300', 'ak_symbol': 'sh000300', 'yf_symbol': '000300.SS', 'sina_code': 'sh000300'},
    {'code': '000688', 'name': '科创50', 'em_secid': '1.000688', 'ak_symbol': 'sh000688', 'yf_symbol': '000688.SS', 'sina_code': 'sh000688'},
]

EM_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.eastmoney.com/',
}

# 新浪财经请求头
SINA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://vip.stock.finance.sina.com.cn/',
}

# 申万一级行业分类 (31个板块)
SW1_SECTORS = [
    ('煤炭', 'sw1_740000'), ('石油石化', 'sw1_750000'), ('美容护理', 'sw1_770000'),
    ('环保', 'sw1_760000'), ('电力设备', 'sw1_630000'), ('社会服务', 'sw1_460000'),
    ('商贸零售', 'sw1_450000'), ('纺织服饰', 'sw1_350000'), ('基础化工', 'sw1_220000'),
    ('通信', 'sw1_730000'), ('传媒', 'sw1_720000'), ('计算机', 'sw1_710000'),
    ('国防军工', 'sw1_650000'), ('机械设备', 'sw1_640000'), ('建筑装饰', 'sw1_620000'),
    ('建筑材料', 'sw1_610000'), ('非银金融', 'sw1_490000'), ('银行', 'sw1_480000'),
    ('房地产', 'sw1_430000'), ('交通运输', 'sw1_420000'), ('公用事业', 'sw1_410000'),
    ('医药生物', 'sw1_370000'), ('轻工制造', 'sw1_360000'), ('食品饮料', 'sw1_340000'),
    ('家用电器', 'sw1_330000'), ('汽车', 'sw1_280000'), ('电子', 'sw1_270000'),
    ('有色金属', 'sw1_240000'), ('钢铁', 'sw1_230000'), ('农林牧渔', 'sw1_110000'),
    ('综合', 'sw1_510000'),
]


# ═══════════════════════════════════════════════════
# 1. 核心指数收盘数据
# ═══════════════════════════════════════════════════

def fetch_index_data():
    """获取核心指数收盘数据、涨跌幅度及成交额"""
    print('[MarketReview] 采集核心指数数据...')

    # 方法1: 新浪财经实时行情 (US IP 可用, 一次请求获取全部指数)
    sina_results = _fetch_index_sina()
    if sina_results and len(sina_results) >= 3:
        print(f'[MarketReview] sina指数: {len(sina_results)}条')
        return sina_results

    # 方法2: akshare
    results = []
    ak_results = _fetch_index_akshare()
    if ak_results:
        results.extend(ak_results)
    if len(results) >= 3:
        print(f'[MarketReview] akshare指数: {len(results)}条')
        return results

    # 方法3: 东方财富 push2his API (直连, 不稳定)
    em_results = _fetch_index_eastmoney()
    if em_results:
        existing = {r['code'] for r in results}
        for r in em_results:
            if r['code'] not in existing:
                results.append(r)
        if len(results) >= 3:
            print(f'[MarketReview] eastmoney指数: {len(results)}条')
            return results

    # 方法4: yfinance (海外IP可用, 数据可能不全)
    yf_results = _fetch_index_yfinance()
    if yf_results:
        existing = {r['code'] for r in results}
        for r in yf_results:
            if r['code'] not in existing:
                results.append(r)

    # 补充: 如果新浪有部分数据, 也加入
    if sina_results:
        existing = {r['code'] for r in results}
        for r in sina_results:
            if r['code'] not in existing:
                results.append(r)

    print(f'[MarketReview] 指数采集完成: {len(results)}条')
    return results


def _fetch_index_sina():
    """新浪财经实时行情获取指数数据 (US IP 可用, 一次请求获取全部指数)"""
    try:
        codes = ','.join(idx['sina_code'] for idx in CORE_INDICES)
        url = f'https://hq.sinajs.cn/list={codes}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn/',
        }
        resp = requests.get(url, headers=headers, timeout=(3, 8))
        resp.encoding = 'gbk'
        if resp.status_code != 200:
            print(f'  [MarketReview] sina指数 HTTP {resp.status_code}')
            return []

        results = []
        for line in resp.text.strip().split('\n'):
            m = re.search(r'var hq_str_\w+="(.+)"', line)
            if not m:
                continue
            parts = m.group(1).split(',')
            if len(parts) < 10:
                continue
            name = parts[0]
            prev_close = float(parts[1]) if parts[1] else 0
            open_price = float(parts[2]) if parts[2] else 0
            close = float(parts[3]) if parts[3] else 0
            high = float(parts[4]) if parts[4] else 0
            low = float(parts[5]) if parts[5] else 0
            volume = float(parts[8]) if parts[8] else 0
            amount = float(parts[9]) if parts[9] else 0
            date_str = parts[30] if len(parts) > 30 else ''

            if close <= 0:
                continue

            change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0

            idx_info = next((idx for idx in CORE_INDICES if idx['sina_code'] in line), None)
            code = idx_info['code'] if idx_info else ''
            display_name = idx_info['name'] if idx_info else name

            results.append({
                'name': display_name,
                'code': code,
                'close': round(close, 2),
                'change_pct': change_pct,
                'volume': int(volume),
                'amount': amount,
                'source': 'sina',
            })

        if results:
            print(f'[MarketReview] sina指数: {len(results)}条')
        return results
    except Exception as e:
        print(f'  [MarketReview] sina指数失败: {e}')
        return []


def _fetch_index_akshare():
    """akshare 获取指数数据"""
    results = []
    for idx in CORE_INDICES:
        try:
            df = call_with_timeout(ak.stock_zh_index_daily_em, timeout=10, symbol=idx['ak_symbol'])
            if df is not None and len(df) > 0:
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest
                close = float(latest.get('close', 0) or 0)
                prev_close = float(prev.get('close', 0) or 0)
                if close > 0:
                    change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                    results.append({
                        'name': idx['name'],
                        'code': idx['code'],
                        'close': round(close, 2),
                        'change_pct': change_pct,
                        'volume': int(latest.get('volume', 0) or 0),
                        'amount': float(latest.get('amount', 0) or 0),
                        'source': 'akshare',
                    })
        except Exception as e:
            print(f'  [MarketReview] akshare指数 {idx["name"]}: {e}')
    return results


def _fetch_index_eastmoney():
    """东方财富 push2his API 获取指数K线数据"""
    results = []
    today_str = datetime.now().strftime('%Y%m%d')
    beg_str = (datetime.now() - timedelta(days=10)).strftime('%Y%m%d')

    for idx in CORE_INDICES:
        try:
            url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
            params = {
                'secid': idx['em_secid'],
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57',
                'klt': '101',  # 日K
                'fqt': '0',
                'beg': beg_str,
                'end': today_str,
            }
            resp = requests.get(url, params=params, headers=EM_HEADERS, timeout=(3, 8))
            if resp.status_code == 200:
                data = resp.json()
                em_data = data.get('data') or {}
                klines = em_data.get('klines', [])
                if klines and len(klines) >= 2:
                    # 格式: date,open,close,high,low,volume,amount
                    parts_latest = klines[-1].split(',')
                    parts_prev = klines[-2].split(',')
                    close = float(parts_latest[2])
                    prev_close = float(parts_prev[2])
                    change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                    results.append({
                        'name': idx['name'],
                        'code': idx['code'],
                        'close': round(close, 2),
                        'change_pct': change_pct,
                        'volume': int(float(parts_latest[5])) if parts_latest[5] else 0,
                        'amount': float(parts_latest[6]) if len(parts_latest) > 6 else 0,
                        'source': 'eastmoney',
                    })
        except Exception as e:
            print(f'  [MarketReview] eastmoney指数 {idx["name"]}: {e}')
        time.sleep(0.2)

    return results


def _fetch_index_yfinance():
    """yfinance 获取指数数据 (海外IP可用)"""
    results = []
    for idx in CORE_INDICES:
        try:
            ticker = yf.Ticker(idx['yf_symbol'])
            hist = ticker.history(period='1mo')
            if hist is not None and len(hist) > 0:
                latest = hist.iloc[-1]
                prev_close = float(hist.iloc[-2]['Close']) if len(hist) > 1 else float(latest['Close'])
                close = float(latest['Close'])
                if close > 0:
                    change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                    results.append({
                        'name': idx['name'],
                        'code': idx['code'],
                        'close': round(close, 2),
                        'change_pct': change_pct,
                        'volume': int(latest.get('Volume', 0) or 0),
                        'amount': 0,
                        'source': 'yfinance',
                    })
        except Exception as e:
            print(f'  [MarketReview] yfinance指数 {idx["name"]}: {e}')
    return results


# ═══════════════════════════════════════════════════
# 2. 涨跌停家数、涨跌家数比
# ═══════════════════════════════════════════════════

def fetch_market_breadth():
    """获取涨跌停家数、涨跌家数比"""
    print('[MarketReview] 采集市场广度数据...')

    # 方法1: akshare stock_market_activity_legu (带超时保护)
    try:
        df = call_with_timeout(ak.stock_market_activity_legu, timeout=15)
        if df is not None and len(df) > 0:
            result = _parse_market_breadth_akshare(df)
            if result:
                return result
    except Exception as e:
        print(f'  [MarketReview] akshare市场广度失败: {e}')

    # 方法2: 新浪财经 (并发获取全A股, 统计涨跌家数)
    try:
        result = _fetch_breadth_sina()
        if result:
            return result
    except Exception as e:
        print(f'  [MarketReview] 新浪市场广度失败: {e}')

    # 方法3: 东方财富 API (直连, 带超时)
    try:
        result = _fetch_breadth_eastmoney()
        if result:
            return result
    except Exception as e:
        print(f'  [MarketReview] eastmoney市场广度失败: {e}')

    print('[MarketReview] 市场广度数据不可用')
    return {}


def _parse_market_breadth_akshare(df):
    """解析 akshare 返回的市场活跃度数据"""
    result = {}
    try:
        # akshare stock_market_activity_legu 返回 DataFrame
        # 尝试各种可能的列名
        for _, row in df.iterrows():
            # 转换为字典
            row_dict = {}
            for col in df.columns:
                row_dict[str(col)] = row[col]

            # 尝试匹配涨跌家数
            for key, val in row_dict.items():
                key_lower = str(key).lower()
                if '上涨' in key and '家' in key:
                    result['advance_count'] = int(val) if val else 0
                elif '下跌' in key and '家' in key:
                    result['decline_count'] = int(val) if val else 0
                elif '平盘' in key or '平' == str(key).strip():
                    result['flat_count'] = int(val) if val else 0
                elif '涨停' in key:
                    result['limit_up_count'] = int(val) if val else 0
                elif '跌停' in key:
                    result['limit_down_count'] = int(val) if val else 0
                elif '总成交' in key and '额' in key:
                    try:
                        result['total_amount'] = float(val) if val else 0
                    except (ValueError, TypeError):
                        pass
    except Exception as e:
        print(f'  [MarketReview] 解析市场广度失败: {e}')

    if result:
        advance = result.get('advance_count', 0)
        decline = result.get('decline_count', 0)
        total = advance + decline + result.get('flat_count', 0)
        result['advance_ratio'] = round(advance / total, 4) if total > 0 else 0
        result['source'] = 'akshare'
        print(f'[MarketReview] 市场广度: 涨{advance} 跌{decline} 涨停{result.get("limit_up_count", 0)} 跌停{result.get("limit_down_count", 0)}')

    return result


def _fetch_breadth_sina():
    """新浪财经并发获取全A股行情, 统计涨跌家数和涨跌停"""
    try:
        sina_url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'

        def _fetch_page(page):
            params = {
                'page': page, 'num': 100, 'sort': 'symbol',
                'asc': 1, 'node': 'hs_a', '_s_r_a': 'auto',
            }
            try:
                r = requests.get(sina_url, params=params, headers=SINA_HEADERS, timeout=8)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                pass
            return []

        all_stocks = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(_fetch_page, p): p for p in range(1, 56)}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    all_stocks.extend(result)

        if not all_stocks:
            print('  [MarketReview] 新浪 breadth: 无数据返回')
            return None

        up = down = flat = limit_up = limit_down = 0
        for s in all_stocks:
            try:
                pct = float(s.get('changepercent', 0) or 0)
            except (ValueError, TypeError):
                continue
            if pct > 0:
                up += 1
                if pct >= 9.8:
                    limit_up += 1
            elif pct < 0:
                down += 1
                if pct <= -9.8:
                    limit_down += 1
            else:
                flat += 1

        total = up + down + flat
        if total == 0:
            return None

        result = {
            'advance_count': up,
            'decline_count': down,
            'flat_count': flat,
            'limit_up_count': limit_up,
            'limit_down_count': limit_down,
            'advance_ratio': round(up / total, 4),
            'total_count': total,
            'source': 'sina',
        }
        print(f'[MarketReview] 市场广度(新浪): 涨{up} 跌{down} 平{flat} 涨停{limit_up} 跌停{limit_down} (共{total}只)')
        return result
    except Exception as e:
        print(f'  [MarketReview] 新浪 breadth: {e}')
    return None


def _fetch_breadth_eastmoney():
    """东方财富 datacenter API 获取市场广度"""
    try:
        # 尝试获取全市场行情统计
        url = 'https://push2.eastmoney.com/api/qt/clist/get'
        params = {
            'fid': 'f3',
            'po': '1',
            'pz': '6000',
            'pn': '1',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f2,f3,f12,f14',
        }
        resp = requests.get(url, params=params, headers=EM_HEADERS, timeout=(3, 10))
        if resp.status_code == 200:
            data = resp.json()
            diff = (data.get('data') or {}).get('diff', [])
            if diff:
                advance = 0
                decline = 0
                flat = 0
                limit_up = 0
                limit_down = 0
                for item in diff:
                    pct = item.get('f3', 0)
                    if isinstance(pct, (int, float)):
                        pct = pct / 100  # eastmoney 返回的是百分比*100
                    else:
                        continue
                    if pct > 0:
                        advance += 1
                        if pct >= 9.8:
                            limit_up += 1
                    elif pct < 0:
                        decline += 1
                        if pct <= -9.8:
                            limit_down += 1
                    else:
                        flat += 1

                total = advance + decline + flat
                result = {
                    'advance_count': advance,
                    'decline_count': decline,
                    'flat_count': flat,
                    'limit_up_count': limit_up,
                    'limit_down_count': limit_down,
                    'advance_ratio': round(advance / total, 4) if total > 0 else 0,
                    'source': 'eastmoney',
                }
                print(f'[MarketReview] 市场广度(eastmoney): 涨{advance} 跌{decline} 涨停{limit_up} 跌停{limit_down}')
                return result
            else:
                print(f'  [MarketReview] eastmoney breadth: 响应无数据 (keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__})')
        else:
            print(f'  [MarketReview] eastmoney breadth: HTTP {resp.status_code}')
    except Exception as e:
        print(f'  [MarketReview] eastmoney breadth: {e}')
    return None


# ═══════════════════════════════════════════════════
# 3. 北向资金流向
# ═══════════════════════════════════════════════════

def fetch_northbound_flow():
    """获取北向资金流向数据 (东财datacenter-web主源, 沪股通+深股通成交总额/净买额)"""
    print('[MarketReview] 采集北向资金数据...')

    # 主源: 东财 datacenter-web (RPT_MUTUAL_DEAL_HISTORY, 从US IP可用)
    # 注: 新浪 getHKData 接口已失效(Service not valid); 港交所2024披露调整致北向净买额不再公开
    try:
        result = _fetch_northbound_eastmoney_dc()
        if result and result.get('amount_yi', 0) > 0:
            return result
    except Exception as e:
        print(f'  [MarketReview] eastmoney datacenter 北向资金失败: {e}')

    # 备用: akshare (stock_hsgt_hist_em, 现也走datacenter-web)
    try:
        result = _fetch_northbound_akshare()
        if result and result.get('net_buy', 0) != 0 and not math.isnan(result.get('net_buy', 0)):
            return result
    except Exception as e:
        print(f'  [MarketReview] akshare北向资金失败: {e}')

    # 备用: Tushare (需token + 2000积分)
    try:
        result = _fetch_northbound_tushare()
        if result and result.get('net_buy', 0) != 0 and not math.isnan(result.get('net_buy', 0)):
            return result
    except Exception as e:
        print(f'  [MarketReview] tushare北向资金失败: {e}')

    print('[MarketReview] 北向资金数据不可用')
    return {}


def _fetch_northbound_tushare():
    """Tushare moneyflow_hsgt 获取北向资金 (需要token + 2000积分)"""
    token = os.environ.get('TUSHARE_TOKEN', '')
    if not token:
        print('  [MarketReview] tushare: 未配置 TUSHARE_TOKEN 环境变量')
        return None

    try:
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()

        # 查最近3天数据, 取最新一行
        today_str = datetime.now().strftime('%Y%m%d')
        beg_str = (datetime.now() - timedelta(days=5)).strftime('%Y%m%d')

        df = pro.moneyflow_hsgt(start_date=beg_str, end_date=today_str)
        if df is None or len(df) == 0:
            print('  [MarketReview] tushare: moneyflow_hsgt 返回空数据')
            return None

        # 按交易日期降序排序, 取最新一行
        if 'trade_date' in df.columns:
            df = df.sort_values('trade_date', ascending=False)

        latest = df.iloc[0]

        # north_money: 北向资金(百万元), hgt: 沪股通(百万元), sgt: 深股通(百万元)
        north_million = 0
        hgt_million = 0
        sgt_million = 0
        date_str = ''

        for col in df.columns:
            col_str = str(col)
            if 'north_money' in col_str:
                try:
                    val = float(latest[col])
                    if not math.isnan(val):
                        north_million = val
                except (ValueError, TypeError):
                    pass
            elif col_str == 'hgt':
                try:
                    val = float(latest[col])
                    if not math.isnan(val):
                        hgt_million = val
                except (ValueError, TypeError):
                    pass
            elif col_str == 'sgt':
                try:
                    val = float(latest[col])
                    if not math.isnan(val):
                        sgt_million = val
                except (ValueError, TypeError):
                    pass
            elif 'trade_date' in col_str or '日期' in col_str:
                date_str = str(latest[col])

        # 如果north_money为0, 尝试用hgt+sgt
        if north_million == 0 and (hgt_million != 0 or sgt_million != 0):
            north_million = hgt_million + sgt_million

        # 百万元 → 元
        total_net = north_million * 1e6

        if total_net == 0:
            print(f'  [MarketReview] tushare: 北向资金净额为0 (date={date_str})')
            return None

        result = {
            'net_buy': round(total_net, 2),
            'net_buy_yi': round(total_net / 1e8, 2),
            'hgt_yi': round(hgt_million / 100, 2),  # 百万→亿
            'sgt_yi': round(sgt_million / 100, 2),
            'date': date_str,
            'is_extreme': abs(total_net) > 10e8,
            'extreme_note': '',
            'source': 'tushare(moneyflow_hsgt)',
        }
        if total_net > 10e8:
            result['extreme_note'] = '北向单日净买入超100亿，极端流入信号'
        elif total_net < -10e8:
            result['extreme_note'] = '北向单日净卖出超100亿，极端流出信号'
        print(f'[MarketReview] 北向资金(tushare): 净{("买入" if total_net > 0 else "卖出")}{result["net_buy_yi"]:.2f}亿')
        return result

    except ImportError:
        print('  [MarketReview] tushare: tushare包未安装')
        return None
    except Exception as e:
        err_str = str(e)
        if '积分' in err_str or '权限' in err_str:
            print(f'  [MarketReview] tushare: 积分不足或无权限 - {err_str}')
        elif 'token' in err_str.lower() or '认证' in err_str:
            print(f'  [MarketReview] tushare: token认证失败 - {err_str}')
        else:
            print(f'  [MarketReview] tushare: {err_str}')
        return None


def _fetch_northbound_akshare():
    """akshare 获取北向资金 (分别查沪股通+深股通, 求和)"""
    func = getattr(ak, 'stock_hsgt_hist_em', None)
    if func is None:
        return None

    total_net = 0
    date_str = ''
    for symbol in ['沪股通', '深股通']:
        df = call_with_timeout(func, timeout=10, symbol=symbol)
        if df is None or len(df) == 0:
            continue
        # 尝试最后一行, 如果是NaN则用倒数第二行
        for row_idx in [-1, -2]:
            if abs(row_idx) > len(df):
                break
            latest = df.iloc[row_idx]
            found_val = False
            for col in df.columns:
                col_str = str(col)
                if '累计' in col_str:
                    continue
                if '净买' in col_str or '净流入' in col_str or 'value' in col_str.lower():
                    try:
                        val = float(latest[col])
                        if math.isnan(val):
                            continue
                        total_net += val
                        found_val = True
                    except (ValueError, TypeError):
                        pass
                elif 'date' in col_str.lower() or '日期' in col_str:
                    date_str = str(latest[col])
            if found_val:
                break

    if math.isnan(total_net) or total_net == 0:
        if not date_str:
            return None

    result = {
        'net_buy': round(total_net, 2),
        'net_buy_yi': round(total_net / 1e8, 2),
        'date': date_str,
        'is_extreme': abs(total_net) > 10e8,
        'extreme_note': '',
        'source': 'akshare(stock_hsgt_hist_em, 沪+深)',
    }
    if total_net > 10e8:
        result['extreme_note'] = '北向单日净买入超100亿，极端流入信号'
    elif total_net < -10e8:
        result['extreme_note'] = '北向单日净卖出超100亿，极端流出信号'
    print(f'[MarketReview] 北向资金(akshare): 净{("买入" if total_net > 0 else "卖出")}{result["net_buy_yi"]:.2f}亿')
    return result


def _fetch_northbound_eastmoney_dc():
    """东方财富 datacenter-web RPT_MUTUAL_DEAL_HISTORY 获取北向资金 (沪股通001 + 深股通003)
    净买额(NET_DEAL_AMT)因港交所2024年披露机制调整已不公开, 优先展示成交总额(DEAL_AMT, 万元)
    """
    url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.eastmoney.com/hsgt/',
    }
    amount_yi = 0.0
    net_yi = 0.0
    has_net = True
    date_str = ''
    found = False

    for mtype, label in [('001', '沪股通'), ('003', '深股通')]:
        params = {
            'sortColumns': 'TRADE_DATE',
            'sortTypes': '-1',
            'pageSize': '5',
            'pageNumber': '1',
            'reportName': 'RPT_MUTUAL_DEAL_HISTORY',
            'columns': 'ALL',
            'source': 'WEB',
            'client': 'WEB',
            'filter': f'(MUTUAL_TYPE="{mtype}")',
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
            rows = (data.get('result') or {}).get('data') or []
            if not rows:
                print(f'  [MarketReview] eastmoney dc {label}: 无数据')
                continue
            # 取最新有成交总额的行
            latest = None
            for r in rows:
                if r.get('DEAL_AMT') is not None:
                    latest = r
                    break
            if latest is None:
                print(f'  [MarketReview] eastmoney dc {label}: 无成交总额')
                continue
            deal_amt_wan = float(latest.get('DEAL_AMT') or 0)  # 单位: 万元
            amount_yi += deal_amt_wan / 1e4  # 万元 -> 亿元
            if not date_str:
                date_str = str(latest.get('TRADE_DATE', ''))[:10]
            found = True
            # 净买额 (港交所披露调整后多为 None)
            net = latest.get('NET_DEAL_AMT')
            if net is None or (isinstance(net, float) and math.isnan(net)):
                has_net = False
            else:
                net_yi += float(net) / 1e4  # 万元 -> 亿元
        except Exception as e:
            print(f'  [MarketReview] eastmoney dc {label}: {e}')
            continue

    if not found or amount_yi == 0:
        print('  [MarketReview] eastmoney dc 北向: 无成交总额数据')
        return None

    if has_net and net_yi != 0:
        # 净买额披露: 用净买额
        return {
            'net_buy': round(net_yi * 1e8, 2),
            'net_buy_yi': round(net_yi, 2),
            'amount_yi': round(amount_yi, 2),
            'date': date_str,
            'is_extreme': abs(net_yi) > 100,
            'extreme_note': '',
            'metric': 'net_buy',
            'source': 'eastmoney(datacenter-web)',
        }
    else:
        # 净买额未披露: 展示成交总额
        return {
            'net_buy': 0,
            'net_buy_yi': 0.0,
            'amount_yi': round(amount_yi, 2),
            'date': date_str,
            'is_extreme': False,
            'extreme_note': '',
            'metric': 'deal_amount',
            'note': '北向净买额因港交所披露机制调整暂停披露, 展示成交总额',
            'source': 'eastmoney(datacenter-web)',
        }


# ═══════════════════════════════════════════════════
# 4. 两融余额变化
# ═══════════════════════════════════════════════════

def fetch_margin_stats():
    """获取两融余额变化"""
    print('[MarketReview] 采集两融数据...')

    today_str = datetime.now().strftime('%Y%m%d')
    prev_str = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

    # 方法1: akshare stock_margin_account_info (两融汇总数据, 单位: 亿元)
    func_account = getattr(ak, 'stock_margin_account_info', None)
    if func_account:
        try:
            df = call_with_timeout(func_account, timeout=10)
            if df is not None and len(df) > 0:
                latest = df.iloc[-1]
                result = {}
                for col in df.columns:
                    col_str = str(col)
                    if '日期' in col_str or 'date' in col_str.lower():
                        result['date'] = str(latest[col])
                    elif '融资余额' in col_str and '融资买入' not in col_str:
                        try:
                            val = float(latest[col] or 0)
                            result['finance_balance'] = val * 1e8  # 亿元→元
                            result['finance_balance_yi'] = round(val, 2)
                        except (ValueError, TypeError):
                            pass
                    elif '融券余额' in col_str and '融券卖出' not in col_str:
                        try:
                            val = float(latest[col] or 0)
                            result['securities_balance'] = val * 1e8
                            result['securities_balance_yi'] = round(val, 2)
                        except (ValueError, TypeError):
                            pass

                if result.get('finance_balance_yi') and result.get('securities_balance_yi'):
                    result['total_balance_yi'] = round(result['finance_balance_yi'] + result['securities_balance_yi'], 2)
                    result['total_balance'] = result['finance_balance'] + result['securities_balance']

                # 计算变化
                if len(df) >= 2:
                    prev = df.iloc[-2]
                    for col in df.columns:
                        if '融资余额' in str(col) and '融资买入' not in str(col):
                            try:
                                prev_finance = float(prev[col] or 0)
                            except (ValueError, TypeError):
                                prev_finance = 0
                            break
                    for col in df.columns:
                        if '融券余额' in str(col) and '融券卖出' not in str(col):
                            try:
                                prev_securities = float(prev[col] or 0)
                            except (ValueError, TypeError):
                                prev_securities = 0
                            break
                    prev_total_yi = prev_finance + prev_securities
                    if result.get('total_balance_yi'):
                        result['balance_change_yi'] = round(result['total_balance_yi'] - prev_total_yi, 2)
                        result['balance_change'] = round(result['balance_change_yi'] * 1e8, 2)

                result['source'] = 'akshare_account'
                result.setdefault('balance_change', 0)
                result.setdefault('balance_change_yi', 0)
                print(f'[MarketReview] 两融余额(account): {result.get("total_balance_yi", 0):.2f}亿 变化{result.get("balance_change_yi", 0):+.2f}亿')
                return result
        except Exception as e:
            print(f'  [MarketReview] akshare两融(account)失败: {e}')

    # 方法2: akshare SSE (stock_margin_detail_sse 接受 date 参数, 返回个股明细需聚合)
    try:
        df = call_with_timeout(ak.stock_margin_detail_sse, timeout=10, date=today_str)
        if df is not None and len(df) > 0:
            # stock_margin_detail_sse 返回个股明细, 需要聚合求和
            result = {}
            for col in df.columns:
                col_str = str(col)
                if '融资余额' in col_str and '买入' not in col_str:
                    try:
                        result['finance_balance'] = float(df[col].sum())
                    except (ValueError, TypeError):
                        pass
                elif '融券余额' in col_str and '卖出' not in col_str:
                    try:
                        result['securities_balance'] = float(df[col].sum())
                    except (ValueError, TypeError):
                        pass
                elif '融资融券余额' in col_str or '两融余额' in col_str:
                    try:
                        result['total_balance'] = float(df[col].sum())
                    except (ValueError, TypeError):
                        pass
                elif '日期' in col_str or 'date' in col_str.lower():
                    result['date'] = str(df.iloc[0][col])

            if result.get('total_balance') is None and result.get('finance_balance') and result.get('securities_balance'):
                result['total_balance'] = result['finance_balance'] + result['securities_balance']

            result['source'] = 'akshare_sse'
            result.setdefault('balance_change', 0)
            result.setdefault('balance_change_yi', 0)
            if result.get('total_balance'):
                result['total_balance_yi'] = round(result['total_balance'] / 1e8, 2)
            if result.get('finance_balance'):
                result['finance_balance_yi'] = round(result['finance_balance'] / 1e8, 2)
            if result.get('securities_balance'):
                result['securities_balance_yi'] = round(result['securities_balance'] / 1e8, 2)
            print(f'[MarketReview] 两融余额(sse): {result.get("total_balance_yi", 0):.2f}亿')
            return result
    except Exception as e:
        print(f'  [MarketReview] akshare两融(sse)失败: {e}')

    # 方法2: 东方财富 datacenter API
    try:
        result = _fetch_margin_eastmoney()
        if result:
            return result
    except Exception as e:
        print(f'  [MarketReview] eastmoney两融失败: {e}')

    print('[MarketReview] 两融数据不可用')
    return {}


def _fetch_margin_eastmoney():
    """东方财富 datacenter API 获取两融数据 (使用正确的报表名 RPTA_RZRQ_LSHJ)"""
    try:
        url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
        params = {
            'reportName': 'RPTA_RZRQ_LSHJ',  # 融资融券历史汇总
            'columns': 'ALL',
            'source': 'WEB',
            'sortColumns': 'dim_date',  # 按交易日期排序
            'sortTypes': '-1',  # 倒序
            'pageSize': '5',
            'pageNumber': '1',
        }
        resp = requests.get(url, params=params, headers=EM_HEADERS, timeout=(3, 8))
        if resp.status_code == 200:
            data = resp.json()
            rows = (data.get('result') or {}).get('data', [])
            if not rows:
                rows = data.get('data', [])
            if rows and len(rows) >= 1:
                latest = rows[0]
                # RPTA_RZRQ_LSHJ 字段: dim_date, rzye, rqye, rzrqye
                finance = float(latest.get('rzye', 0) or latest.get('RZYE', 0) or 0)
                securities = float(latest.get('rqye', 0) or latest.get('RQYE', 0) or 0)
                total = float(latest.get('rzrqye', 0) or latest.get('RZRQYE', 0) or 0)
                if total == 0:
                    total = finance + securities
                date_str = str(latest.get('dim_date', '') or latest.get('DATE', '') or latest.get('RQ', ''))
                result = {
                    'total_balance': total,
                    'finance_balance': finance,
                    'securities_balance': securities,
                    'date': date_str[:10] if date_str else '',
                    'source': 'eastmoney',
                }
                result['total_balance_yi'] = round(result['total_balance'] / 1e8, 2)
                result['finance_balance_yi'] = round(result['finance_balance'] / 1e8, 2)
                result['securities_balance_yi'] = round(result['securities_balance'] / 1e8, 2)

                if len(rows) >= 2:
                    prev = rows[1]
                    prev_total = float(prev.get('rzrqye', 0) or prev.get('RZRQYE', 0) or 0)
                    if prev_total == 0:
                        prev_finance = float(prev.get('rzye', 0) or prev.get('RZYE', 0) or 0)
                        prev_securities = float(prev.get('rqye', 0) or prev.get('RQYE', 0) or 0)
                        prev_total = prev_finance + prev_securities
                    result['balance_change'] = round(result['total_balance'] - prev_total, 2)
                    result['balance_change_yi'] = round(result['balance_change'] / 1e8, 2)
                else:
                    result['balance_change'] = 0
                    result['balance_change_yi'] = 0

                print(f'[MarketReview] 两融余额(eastmoney): {result["total_balance_yi"]:.2f}亿')
                return result
            else:
                print(f'  [MarketReview] eastmoney margin: 响应无数据 (success={data.get("success")}, message={data.get("message", "N/A")})')
        else:
            print(f'  [MarketReview] eastmoney margin: HTTP {resp.status_code}')
    except Exception as e:
        print(f'  [MarketReview] eastmoney margin: {e}')
    return None


# ═══════════════════════════════════════════════════
# 5. 行业板块资金净流入/流出排名
# ═══════════════════════════════════════════════════

def fetch_sector_flow():
    """获取行业板块资金净流入/流出排名"""
    print('[MarketReview] 采集行业板块资金流...')

    # 方法1: akshare
    try:
        df = call_with_timeout(ak.stock_sector_fund_flow_rank, timeout=10, indicator='今日', sector_type='行业资金流')
        if df is not None and len(df) > 0:
            results = []
            for _, row in df.iterrows():
                item = {}
                for col in df.columns:
                    col_str = str(col)
                    if '名称' in col_str or 'name' in col_str.lower():
                        item['name'] = str(row[col])
                    elif '涨跌幅' in col_str:
                        item['change_pct'] = float(row[col] or 0)
                    elif '主力净流入' in col_str and '净额' in col_str:
                        item['net_inflow'] = float(row[col] or 0)
                        item['net_inflow_yi'] = round(float(row[col] or 0) / 1e8, 2)
                    elif '主力净流入' in col_str and '净占比' in col_str:
                        item['net_inflow_pct'] = float(row[col] or 0)
                    elif '今日主力净流入最大股' in col_str:
                        item['top_stock'] = str(row[col])

                if item.get('name'):
                    results.append(item)

            if results:
                # 排序: 净流入降序
                results.sort(key=lambda x: x.get('net_inflow', 0), reverse=True)
                print(f'[MarketReview] 行业资金流(akshare): {len(results)}个板块')
                return results
    except Exception as e:
        print(f'  [MarketReview] akshare板块资金流失败: {e}')

    # 方法2: 新浪财经 (并发获取申万一级行业板块数据)
    try:
        result = _fetch_sector_flow_sina()
        if result:
            return result
    except Exception as e:
        print(f'  [MarketReview] 新浪板块资金流失败: {e}')

    # 方法3: 东方财富 API
    try:
        result = _fetch_sector_flow_eastmoney()
        if result:
            return result
    except Exception as e:
        print(f'  [MarketReview] eastmoney板块资金流失败: {e}')

    print('[MarketReview] 行业板块资金流数据不可用')
    return []


def _fetch_sector_flow_sina():
    """新浪财经并发获取申万一级行业板块数据 (成交额+涨跌幅作为资金流代理)"""
    try:
        sina_url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'

        def _fetch_sector(name, node):
            params = {
                'page': 1, 'num': 100, 'sort': 'amount',
                'asc': 0, 'node': node, '_s_r_a': 'auto',
            }
            try:
                r = requests.get(sina_url, params=params, headers=SINA_HEADERS, timeout=8)
                if r.status_code == 200:
                    return name, r.json()
            except Exception:
                pass
            return name, []

        sector_results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(_fetch_sector, name, node): name for name, node in SW1_SECTORS}
            for future in as_completed(futures):
                sector_name, stocks = future.result()
                if not stocks:
                    continue
                total_amount = sum(float(s.get('amount', 0) or 0) for s in stocks)
                avg_change = sum(float(s.get('changepercent', 0) or 0) for s in stocks) / len(stocks)
                up = sum(1 for s in stocks if float(s.get('changepercent', 0) or 0) > 0)
                down = sum(1 for s in stocks if float(s.get('changepercent', 0) or 0) < 0)
                total_amount_yi = total_amount / 1e8
                # 用成交额作为资金活跃度代理, 涨跌幅作为方向
                sector_results.append({
                    'name': sector_name,
                    'stock_count': len(stocks),
                    'net_inflow': total_amount,  # 用成交额代理
                    'net_inflow_yi': round(total_amount_yi, 2),
                    'change_pct': round(avg_change, 2),
                    'turnover_yi': round(total_amount_yi, 2),
                    'up_count': up,
                    'down_count': down,
                    'source': 'sina',
                })

        if sector_results:
            # 按成交额降序排列 (成交额最大 = 资金最活跃)
            sector_results.sort(key=lambda x: x['net_inflow'], reverse=True)
            print(f'[MarketReview] 板块资金流(新浪): {len(sector_results)}个板块')
            for s in sector_results[:3]:
                print(f'  {s["name"]}: 成交{s["turnover_yi"]:.2f}亿, 均涨跌{s["change_pct"]:+.2f}%')
            return sector_results
        else:
            print('  [MarketReview] 新浪 sector: 无数据返回')
    except Exception as e:
        print(f'  [MarketReview] 新浪 sector flow: {e}')
    return None


def _fetch_sector_flow_eastmoney():
    """东方财富 API 获取行业板块资金流"""
    try:
        url = 'https://push2.eastmoney.com/api/qt/clist/get'
        params = {
            'fid': 'f62',  # 按主力净流入排序
            'po': '1',
            'pz': '30',
            'pn': '1',
            'fs': 'm:90+t:2',  # 行业板块
            'fields': 'f12,f14,f62,f184,f3,f2',
        }
        resp = requests.get(url, params=params, headers=EM_HEADERS, timeout=(3, 8))
        if resp.status_code == 200:
            data = resp.json()
            diff = (data.get('data') or {}).get('diff', [])
            if diff:
                results = []
                for item in diff:
                    net_inflow = float(item.get('f62', 0) or 0)
                    results.append({
                        'name': item.get('f14', ''),
                        'code': item.get('f12', ''),
                        'net_inflow': net_inflow,
                        'net_inflow_yi': round(net_inflow / 1e8, 2),
                        'net_inflow_pct': float(item.get('f184', 0) or 0),
                        'change_pct': float(item.get('f3', 0) or 0) / 100,
                    })

                results.sort(key=lambda x: x['net_inflow'], reverse=True)
                print(f'[MarketReview] 板块资金流(eastmoney): {len(results)}个板块')
                return results
            else:
                print(f'  [MarketReview] eastmoney sector: 响应无数据 (keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__})')
        else:
            print(f'  [MarketReview] eastmoney sector: HTTP {resp.status_code}')
    except Exception as e:
        print(f'  [MarketReview] eastmoney sector flow: {e}')
    return None


# ═══════════════════════════════════════════════════
# 信号计算与分析
# ═══════════════════════════════════════════════════

def calculate_signals(index_data, breadth, northbound, margin, sector_flow):
    """计算市场广度指标、资金流向极端值、波动率分位与情绪冷热"""
    signals = {}

    # 1. 市场广度指标
    if breadth and breadth.get('advance_count') is not None:
        ratio = breadth.get('advance_ratio', 0)
        if ratio >= 0.7:
            breadth_desc = '强势上涨'
            sentiment = '偏热'
        elif ratio >= 0.55:
            breadth_desc = '偏强'
            sentiment = '中性偏热'
        elif ratio >= 0.45:
            breadth_desc = '震荡'
            sentiment = '中性'
        elif ratio >= 0.3:
            breadth_desc = '偏弱'
            sentiment = '中性偏冷'
        else:
            breadth_desc = '普遍下跌'
            sentiment = '偏冷'

        signals['market_breadth'] = breadth_desc
        signals['advance_ratio'] = round(ratio * 100, 1)
        signals['sentiment'] = sentiment
    else:
        signals['market_breadth'] = '数据不足'
        signals['advance_ratio'] = None
        signals['sentiment'] = '未知'

    # 2. 资金流向极端值
    flow_signals = []
    if northbound and northbound.get('is_extreme'):
        flow_signals.append(northbound.get('extreme_note', ''))

    if margin and margin.get('balance_change_yi') is not None:
        change = margin.get('balance_change_yi', 0)
        if change > 50:
            flow_signals.append(f'两融余额增加{change:.1f}亿，杠杆资金积极入场')
        elif change < -50:
            flow_signals.append(f'两融余额减少{abs(change):.1f}亿，杠杆资金减仓')

    # 板块资金极端值
    if sector_flow:
        top_sector = sector_flow[0] if sector_flow else {}
        # 判断数据源: sina 用成交额, eastmoney/akshare 用净流入
        is_sina = top_sector.get('source') == 'sina'
        if is_sina:
            # 新浪数据: 用成交额和涨跌幅
            if top_sector.get('turnover_yi', 0) > 1000:
                flow_signals.append(f'{top_sector["name"]}板块成交活跃，成交额{top_sector["turnover_yi"]:.1f}亿')
            # 找最大涨幅/跌幅板块
            top_gain = max(sector_flow, key=lambda x: x.get('change_pct', 0))
            top_loss = min(sector_flow, key=lambda x: x.get('change_pct', 0))
            if top_gain.get('change_pct', 0) > 2.0:
                flow_signals.append(f'{top_gain["name"]}板块均涨{top_gain["change_pct"]:.1f}%，领涨市场')
            if top_loss.get('change_pct', 0) < -2.0:
                flow_signals.append(f'{top_loss["name"]}板块均跌{abs(top_loss["change_pct"]):.1f}%，领跌市场')
        else:
            # eastmoney/akshare 数据: 用主力净流入
            if top_sector.get('net_inflow_yi', 0) > 20:
                flow_signals.append(f'{top_sector["name"]}板块资金大幅净流入{top_sector["net_inflow_yi"]:.1f}亿')
            bottom_outflow = min(sector_flow, key=lambda x: x.get('net_inflow', 0))
            if bottom_outflow.get('net_inflow_yi', 0) < -20:
                flow_signals.append(f'{bottom_outflow["name"]}板块资金大幅净流出{abs(bottom_outflow["net_inflow_yi"]):.1f}亿')

    signals['fund_flow_signals'] = flow_signals if flow_signals else ['无明显极端资金流向信号']

    # 3. 波动率分位 (基于指数涨跌幅估算)
    if index_data:
        changes = [idx.get('change_pct', 0) for idx in index_data]
        avg_abs_change = sum(abs(c) for c in changes) / len(changes) if changes else 0
        max_abs_change = max(abs(c) for c in changes) if changes else 0

        # 简化的波动率分位评估
        if max_abs_change > 2.0:
            vol_percentile = 85
            vol_desc = '偏高'
        elif max_abs_change > 1.0:
            vol_percentile = 65
            vol_desc = '中等偏高'
        elif max_abs_change > 0.5:
            vol_percentile = 45
            vol_desc = '中等'
        else:
            vol_percentile = 25
            vol_desc = '偏低'

        signals['volatility_percentile'] = vol_percentile
        signals['volatility_desc'] = vol_desc
        signals['max_index_change'] = max_abs_change
    else:
        signals['volatility_percentile'] = None
        signals['volatility_desc'] = '数据不足'

    # 4. 情绪冷热综合评估
    if signals.get('sentiment') == '未知':
        if index_data:
            avg_change = sum(idx.get('change_pct', 0) for idx in index_data) / len(index_data)
            if avg_change > 0.5:
                signals['sentiment'] = '偏热'
            elif avg_change > 0:
                signals['sentiment'] = '中性偏热'
            elif avg_change > -0.5:
                signals['sentiment'] = '中性偏冷'
            else:
                signals['sentiment'] = '偏冷'

    print(f'[MarketReview] 信号计算完成: 广度={signals.get("market_breadth")} 情绪={signals.get("sentiment")} 波动率={signals.get("volatility_desc")}')
    return signals


# ═══════════════════════════════════════════════════
# 异动识别
# ═══════════════════════════════════════════════════

def identify_anomalies(index_data, breadth, northbound, sector_flow, signals):
    """识别量价配合异常、资金大幅调仓的板块、情绪过热或过冷的极端信号"""
    anomalies = []

    # 1. 量价配合异常 (指数级别)
    if index_data:
        for idx in index_data:
            pct = idx.get('change_pct', 0)
            vol = idx.get('volume', 0)
            # 放量上涨/缩量下跌
            if pct > 1.5:
                anomalies.append({
                    'type': 'volume_price',
                    'description': f'{idx["name"]}放量上涨{pct:.2f}%，多头力量强劲',
                    'severity': '高' if pct > 2.5 else '中',
                })
            elif pct < -1.5:
                anomalies.append({
                    'type': 'volume_price',
                    'description': f'{idx["name"]}下跌{abs(pct):.2f}%，空头力量释放',
                    'severity': '高' if pct < -2.5 else '中',
                })

    # 2. 涨跌停极端信号
    if breadth:
        limit_up = breadth.get('limit_up_count', 0)
        limit_down = breadth.get('limit_down_count', 0)

        if limit_up > 50:
            anomalies.append({
                'type': 'sentiment_extreme',
                'description': f'涨停家数达{limit_up}家，市场情绪过热',
                'severity': '高',
            })
        elif limit_up > 20:
            anomalies.append({
                'type': 'sentiment_extreme',
                'description': f'涨停{limit_up}家，赚钱效应较好',
                'severity': '中',
            })

        if limit_down > 30:
            anomalies.append({
                'type': 'sentiment_extreme',
                'description': f'跌停家数达{limit_down}家，市场情绪过冷',
                'severity': '高',
            })
        elif limit_down > 10:
            anomalies.append({
                'type': 'sentiment_extreme',
                'description': f'跌停{limit_down}家，亏钱效应明显',
                'severity': '中',
            })

        # 涨跌家数比极端
        advance = breadth.get('advance_count', 0)
        decline = breadth.get('decline_count', 0)
        if advance > 0 and decline > 0:
            ratio = advance / decline
            if ratio > 3:
                anomalies.append({
                    'type': 'breadth_extreme',
                    'description': f'涨跌比{advance}:{decline}，多头全面占优',
                    'severity': '中',
                })
            elif ratio < 0.33:
                anomalies.append({
                    'type': 'breadth_extreme',
                    'description': f'涨跌比{advance}:{decline}，空头全面压制',
                    'severity': '高',
                })

    # 3. 北向资金极端信号
    if northbound and northbound.get('is_extreme'):
        anomalies.append({
            'type': 'fund_flow_extreme',
            'description': northbound.get('extreme_note', ''),
            'severity': '高',
        })

    # 4. 板块资金大幅调仓 / 板块轮动
    if sector_flow and len(sector_flow) >= 2:
        top = sector_flow[0]
        bottom = sector_flow[-1]
        is_sina = top.get('source') == 'sina'

        if is_sina:
            # 新浪数据: 用涨跌幅检测极端板块
            top_gain = max(sector_flow, key=lambda x: x.get('change_pct', 0))
            top_loss = min(sector_flow, key=lambda x: x.get('change_pct', 0))
            if top_gain.get('change_pct', 0) > 2.0:
                anomalies.append({
                    'type': 'sector_rotation',
                    'description': f'{top_gain["name"]}板块均涨{top_gain["change_pct"]:.1f}%，成交{top_gain.get("turnover_yi", 0):.0f}亿，领涨资金方向',
                    'severity': '中',
                })
            if top_loss.get('change_pct', 0) < -2.0:
                anomalies.append({
                    'type': 'sector_rotation',
                    'description': f'{top_loss["name"]}板块均跌{abs(top_loss["change_pct"]):.1f}%，注意调仓风险',
                    'severity': '中',
                })
        else:
            # eastmoney/akshare 数据: 用主力净流入
            top_inflow = top.get('net_inflow_yi', 0)
            bottom_outflow = bottom.get('net_inflow_yi', 0)
            if top_inflow > 10:
                anomalies.append({
                    'type': 'sector_rotation',
                    'description': f'{top["name"]}板块资金大幅净流入{top_inflow:.1f}亿，领涨资金方向',
                    'severity': '中',
                })
            if bottom_outflow < -10:
                anomalies.append({
                    'type': 'sector_rotation',
                    'description': f'{bottom["name"]}板块资金大幅净流出{abs(bottom_outflow):.1f}亿，注意调仓风险',
                    'severity': '中',
                })

    # 5. 波动率极端
    if signals.get('volatility_percentile'):
        vp = signals['volatility_percentile']
        if vp >= 85:
            anomalies.append({
                'type': 'volatility_extreme',
                'description': f'波动率分位{vp}%，市场波动剧烈',
                'severity': '高',
            })
        elif vp <= 20:
            anomalies.append({
                'type': 'volatility_extreme',
                'description': f'波动率分位{vp}%，市场处于极低波动状态，变盘可能临近',
                'severity': '中',
            })

    print(f'[MarketReview] 异动识别完成: {len(anomalies)}条')
    return anomalies


# ═══════════════════════════════════════════════════
# 总结生成
# ═══════════════════════════════════════════════════

def generate_summary(index_data, breadth, northbound, signals):
    """生成1-2句话总结当日市场特征"""
    parts = []

    # 趋势描述
    if index_data:
        sh = next((i for i in index_data if i['code'] == '000001'), None)
        sz = next((i for i in index_data if i['code'] == '399001'), None)
        if sh and sz:
            avg = (sh['change_pct'] + sz['change_pct']) / 2
            if avg > 0.5:
                trend = '放量上涨'
            elif avg > 0:
                trend = '震荡上行'
            elif avg > -0.5:
                trend = '缩量震荡'
            elif avg > -1.5:
                trend = '震荡下行'
            else:
                trend = '放量下跌'
            parts.append(trend)

    # 广度描述
    if breadth and breadth.get('advance_ratio') is not None:
        ratio = breadth['advance_ratio']
        if ratio > 0.7:
            parts.append('赚钱效应明显')
        elif ratio < 0.3:
            parts.append('亏钱效应明显')

    # 北向资金
    if northbound and northbound.get('amount_yi', 0) > 0:
        nb_metric = northbound.get('metric', 'net_buy')
        amt = northbound.get('amount_yi', 0)
        if nb_metric == 'deal_amount':
            parts.append(f'北向资金成交总额约{amt:.0f}亿（净买额因港交所披露调整暂停披露）')
        else:
            nb = northbound.get('net_buy_yi', 0)
            if nb > 50:
                parts.append(f'北向资金大幅净买入{nb:.0f}亿')
            elif nb > 0:
                parts.append(f'北向资金小幅净买入{nb:.0f}亿')
            elif nb > -50:
                parts.append(f'北向资金小幅净卖出{abs(nb):.0f}亿')
            else:
                parts.append(f'北向资金大幅净卖出{abs(nb):.0f}亿')

    # 情绪
    sentiment = signals.get('sentiment', '')
    if sentiment and sentiment not in ('未知',):
        parts.append(f'市场情绪{sentiment}')

    if not parts:
        return '今日市场数据采集受限，请关注后续更新。'

    # 组合成1-2句话
    if len(parts) <= 3:
        summary = '，'.join(parts)
    else:
        summary = '，'.join(parts[:3]) + '；' + '，'.join(parts[3:])

    return summary


def generate_tomorrow_focus(signals, anomalies, sector_flow, northbound):
    """生成明日关注要点"""
    focus = []

    # 北向资金方向
    if northbound and northbound.get('amount_yi', 0) > 0:
        nb_metric = northbound.get('metric', 'net_buy')
        if nb_metric == 'net_buy':
            nb = northbound.get('net_buy_yi', 0)
            if nb > 0:
                focus.append(f'关注北向资金持续流入方向的板块')
            else:
                focus.append(f'关注北向资金流出对大盘的持续影响')
        else:
            focus.append(f'关注北向资金成交活跃度变化（净买额暂停披露）')

    # 板块轮动
    if sector_flow:
        top_sector = sector_flow[0]
        if top_sector.get('net_inflow_yi', 0) > 0:
            focus.append(f'关注{top_sector["name"]}板块资金持续流入情况')

        bottom_sector = min(sector_flow, key=lambda x: x.get('net_inflow', 0))
        if bottom_sector.get('net_inflow_yi', 0) < 0:
            focus.append(f'注意{bottom_sector["name"]}板块资金持续流出风险')

    # 情绪极端
    for a in anomalies:
        if a.get('severity') == '高' and a.get('type') == 'sentiment_extreme':
            focus.append(a.get('description', ''))
            break

    # 波动率
    if signals.get('volatility_percentile'):
        vp = signals['volatility_percentile']
        if vp >= 85:
            focus.append('高波动环境下注意控制仓位')
        elif vp <= 20:
            focus.append('低波动状态可能临近变盘，留意方向选择')

    # 两融变化
    # (已在信号计算中处理)

    if not focus:
        focus.append('关注明日开盘量能变化及北向资金动向')

    # 去重并限制5条
    seen = set()
    unique = []
    for f in focus:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique[:5]


# ═══════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════

def run():
    """主函数：采集 → 信号计算 → 异动识别 → 返回结构化数据"""
    print('[MarketReview] ═══ 开始市场复盘数据采集 ═══')

    today = datetime.now().strftime('%Y-%m-%d')

    # 1. 数据采集
    index_data = fetch_index_data()
    breadth = fetch_market_breadth()
    northbound = fetch_northbound_flow()
    margin = fetch_margin_stats()
    sector_flow = fetch_sector_flow()

    # 2. 信号计算
    signals = calculate_signals(index_data, breadth, northbound, margin, sector_flow)

    # 3. 异动识别
    anomalies = identify_anomalies(index_data, breadth, northbound, sector_flow, signals)

    # 4. 总结
    summary = generate_summary(index_data, breadth, northbound, signals)

    # 5. 明日关注
    tomorrow_focus = generate_tomorrow_focus(signals, anomalies, sector_flow, northbound)

    result = {
        'date': today,
        'summary': summary,
        'indices': index_data,
        'market_breadth': breadth,
        'northbound': northbound,
        'margin': margin,
        'sector_flow': sector_flow[:10] if sector_flow else [],  # TOP10
        'signals': signals,
        'anomalies': anomalies,
        'tomorrow_focus': tomorrow_focus,
    }

    print(f'[MarketReview] ═══ 复盘完成: {len(index_data)}指数, {len(anomalies)}异动, 情绪={signals.get("sentiment")} ═══')
    return result
