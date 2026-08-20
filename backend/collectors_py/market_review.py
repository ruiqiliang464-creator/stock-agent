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
    {'code': '899050', 'name': '北证50', 'em_secid': '0.899050', 'ak_symbol': 'bj899050', 'yf_symbol': '899050.BJ', 'sina_code': 'bj899050'},
    {'code': '000680', 'name': '科创综指', 'em_secid': '1.000680', 'ak_symbol': 'sh000680', 'yf_symbol': '000680.SH', 'sina_code': 'sh000680'},
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


def _fetch_total_market_amount():
    """两市A股总成交额(元) — 用于融资买入占比分母"""
    diff = _em_clist('f12,f6', 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23', pz=6000, fid='f6', po='1')
    total = 0.0
    for it in diff:
        amt = it.get('f6')
        if amt not in (None, '-'):
            try:
                total += float(amt)
            except (ValueError, TypeError):
                pass
    return total


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
                # RPTA_RZRQ_LSHJ 字段: dim_date, rzye, rqye, rzrqye, rzmre(融资买入额), rzche(融资偿还额)
                finance = float(latest.get('rzye', 0) or latest.get('RZYE', 0) or 0)
                securities = float(latest.get('rqye', 0) or latest.get('RQYE', 0) or 0)
                total = float(latest.get('rzrqye', 0) or latest.get('RZRQYE', 0) or 0)
                financing_buy = float(latest.get('rzmre', 0) or latest.get('RZMRE', 0) or 0)
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
                # 融资买入额 + 融资买入占比(占两市成交额)
                if financing_buy > 0:
                    result['financing_buy'] = financing_buy
                    result['financing_buy_yi'] = round(financing_buy / 1e8, 2)
                    try:
                        mkt_amt = _fetch_total_market_amount()
                        if mkt_amt and mkt_amt > 0:
                            result['financing_buy_ratio_pct'] = round(financing_buy / mkt_amt * 100, 2)
                    except Exception:
                        pass
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


# ─────────────────────────────────────────────────────
# 通用: 东财 push2 clist 辅助 (diff 可能为 dict, 统一转 list)
# ─────────────────────────────────────────────────────

def _em_clist(fields, fs, pz=50, fid='f3', po='1', kw=None):
    """东财 push2 clist 通用查询, 返回 list(dict)"""
    url = 'https://push2.eastmoney.com/api/qt/clist/get'
    params = {'fid': fid, 'po': po, 'pz': str(pz), 'pn': '1', 'fs': fs, 'fields': fields}
    if kw:
        params['kw'] = kw
    try:
        r = requests.get(url, params=params, headers=EM_HEADERS, timeout=(4, 10))
        d = r.json().get('data') or {}
        diff = d.get('diff', [])
        if isinstance(diff, dict):
            diff = list(diff.values())
        return diff
    except Exception as e:
        print(f'  [MarketReview] _em_clist 失败(fs={fs}): {e}')
        return []


# ═══════════════════════════════════════════════════
# 6. 国际指数 (恒生/日经/韩综/标普/纳指/道指/富时)
# ═══════════════════════════════════════════════════

INTL_INDICES = [
    {'name': '恒生指数', 'yf': '^HSI', 'region': '香港', 'sina': 'int_hangseng', 'em_secid': '100.HSI'},
    {'name': '日经225', 'yf': '^N225', 'region': '日本', 'sina': 'int_nikkei', 'em_secid': '100.N225'},
    {'name': '韩国综合', 'yf': '^KS11', 'region': '韩国', 'sina': 'int_kospi', 'em_secid': '100.KS11'},
    {'name': '标普500', 'yf': '^GSPC', 'region': '美国', 'sina': 'int_sp500', 'em_secid': None},
    {'name': '纳斯达克', 'yf': '^IXIC', 'region': '美国', 'sina': 'int_nasdaq', 'em_secid': None},
    {'name': '道琼斯', 'yf': '^DJI', 'region': '美国', 'sina': 'int_dji', 'em_secid': '100.DJIA'},
    {'name': '英国富时', 'yf': '^FTSE', 'region': '英国', 'sina': 'int_ftse', 'em_secid': '100.FTSE'},
]

SINA_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://finance.sina.com.cn/',
}


def _sina_intl_indices():
    """新浪国际指数兜底: hq.sinajs.cn/list=int_* (gbk编码, 格式: 名称,现价,涨跌点,涨跌幅%)"""
    mapping = {idx['sina']: idx for idx in INTL_INDICES if idx.get('sina')}
    url = 'https://hq.sinajs.cn/list=' + ','.join(mapping.keys())
    try:
        r = requests.get(url, headers=SINA_HEADERS, timeout=(4, 8))
        r.encoding = 'gbk'
        out = []
        for ln in r.text.strip().split('\n'):
            m = re.search(r'var\s+(\w+)\s*=\s*"([^"]*)"', ln)
            if not m:
                continue
            key, val = m.group(1), m.group(2)
            # 新浪变量名带 hq_str_ 前缀, 去掉以匹配 mapping
            key = key.replace('hq_str_', '')
            idx = mapping.get(key)
            if not idx or not val:
                continue
            parts = val.split(',')
            if len(parts) < 4:
                continue
            try:
                close = float(parts[1])
                chg_pct = float(parts[3])
            except (ValueError, IndexError):
                continue
            if close <= 0:
                continue
            out.append({
                'name': idx['name'], 'symbol': idx['yf'], 'region': idx['region'],
                'close': round(close, 2), 'change_pct': round(chg_pct, 2), 'source': 'sina',
            })
        return out
    except Exception as e:
        print(f'  [MarketReview] 新浪国际指数失败: {e}')
        return []


def _em_intl_indices():
    """东财 push2 stock/get 国际指数兜底 (secid=100.*, retry, 仅已知secid)"""
    out = []
    for idx in INTL_INDICES:
        sec = idx.get('em_secid')
        if not sec:
            continue
        for _ in range(2):
            try:
                r = requests.get('https://push2.eastmoney.com/api/qt/stock/get',
                                  params={'secid': sec, 'fields': 'f43,f170,f58'},
                                  headers=EM_HEADERS, timeout=(4, 8))
                d = r.json().get('data') or {}
                price = d.get('f43')
                chg = d.get('f170')
                if price not in (None, '-', 0):
                    p = float(price)
                    # 指数f43为原值*100 或 原值, 按量级自适应
                    close = round(p / 100, 2) if p > 10000 else round(p, 2)
                    cp = round(float(chg) / 100, 2) if chg not in (None, '-') else 0
                    out.append({
                        'name': idx['name'], 'symbol': idx['yf'], 'region': idx['region'],
                        'close': close, 'change_pct': cp, 'source': 'eastmoney',
                    })
                    break
            except Exception:
                continue
    return out


def fetch_intl_indices():
    """国际指数: yfinance主源(美国IP稳) → 新浪兜底(覆盖6/7) → 东财末位(已知secid)"""
    print('[MarketReview] 采集国际指数...')
    results = []
    seen = set()

    # 方法1: yfinance (美国IP可用, 最稳)
    try:
        for idx in INTL_INDICES:
            try:
                t = yf.Ticker(idx['yf'])
                hist = t.history(period='5d')
                if hist is not None and len(hist) >= 1:
                    close = float(hist.iloc[-1]['Close'])
                    prev = float(hist.iloc[-2]['Close']) if len(hist) > 1 else close
                    chg = round((close - prev) / prev * 100, 2) if prev else 0
                    results.append({
                        'name': idx['name'], 'symbol': idx['yf'], 'region': idx['region'],
                        'close': round(close, 2), 'change_pct': chg, 'source': 'yfinance',
                    })
                    seen.add(idx['name'])
            except Exception as e:
                print(f'  [MarketReview] yfinance {idx["name"]}: {e}')
        if len(results) >= 5:
            print(f'[MarketReview] 国际指数(yfinance): {len(results)}条')
            return results
    except Exception as e:
        print(f'  [MarketReview] yfinance 国际指数整体失败: {e}')

    # 方法2: 新浪兜底 (覆盖道琼斯/纳斯达克/标普/恒生/日经/富时, 韩国除外)
    sina_out = _sina_intl_indices()
    for it in sina_out:
        if it['name'] not in seen:
            results.append(it)
            seen.add(it['name'])
    print(f'[MarketReview] 国际指数(+新浪兜底): {len(results)}条')

    # 方法3: 东财末位 (韩国等新浪未覆盖的, 用已知secid)
    missing = [idx for idx in INTL_INDICES if idx['name'] not in seen and idx.get('em_secid')]
    if missing:
        em_out = _em_intl_indices()
        for it in em_out:
            if it['name'] not in seen:
                results.append(it)
                seen.add(it['name'])
        print(f'[MarketReview] 国际指数(+东财末位): {len(results)}条')

    print(f'[MarketReview] 国际指数: {len(results)}条')
    return results


# ═══════════════════════════════════════════════════
# 7. ETF 申赎 / 宽基 ETF 资金流向
# ═══════════════════════════════════════════════════

BROAD_ETF_KEYWORDS = ['沪深300', '中证500', '中证1000', '创业板', '科创50', '上证50']


def fetch_etf_flow():
    """宽基ETF资金流向: akshare 主源(命名列), 东财 push2 stock/get 兜底价量"""
    print('[MarketReview] 采集宽基ETF资金流向...')
    result = []
    seen = set()

    # 方法1: akshare fund_etf_spot_em (价/涨跌/成交额) + fund_etf_fund_flow_em (资金流)
    try:
        spot_func = getattr(ak, 'fund_etf_spot_em', None)
        flow_func = getattr(ak, 'fund_etf_fund_flow_em', None)
        spot_df = call_with_timeout(spot_func, timeout=15) if spot_func else None
        flow_df = call_with_timeout(flow_func, timeout=15) if flow_func else None

        flow_map = {}
        if flow_df is not None and len(flow_df) > 0:
            for _, row in flow_df.iterrows():
                name = str(row.get('名称', '') or '')
                code = str(row.get('代码', '') or '')
                item = {'name': name, 'code': code}
                for col in flow_df.columns:
                    cs = str(col)
                    if '主力' in cs and ('净流入' in cs or '净额' in cs):
                        try: item['main_net_inflow_yi'] = round(float(row[col] or 0) / 1e8, 2)
                        except (ValueError, TypeError): pass
                    elif '成交额' in cs or '成交金额' in cs:
                        try: item['amount_yi'] = round(float(row[col] or 0) / 1e8, 2)
                        except (ValueError, TypeError): pass
                flow_map[code] = item

        if spot_df is not None and len(spot_df) > 0:
            for _, row in spot_df.iterrows():
                name = str(row.get('名称', '') or '')
                if not any(k in name for k in BROAD_ETF_KEYWORDS):
                    continue
                code = str(row.get('代码', '') or '')
                if code in seen:
                    continue
                seen.add(code)
                item = {'name': name, 'code': code}
                for col in spot_df.columns:
                    cs = str(col)
                    if '最新价' in cs or '现价' in cs:
                        try: item['close'] = round(float(row[col] or 0), 3)
                        except (ValueError, TypeError): pass
                    elif '涨跌幅' in cs:
                        try: item['change_pct'] = round(float(row[col] or 0), 2)
                        except (ValueError, TypeError): pass
                    elif '成交额' in cs or '成交金额' in cs:
                        try: item['amount_yi'] = round(float(row[col] or 0) / 1e8, 2)
                        except (ValueError, TypeError): pass
                flow = flow_map.get(code, {})
                item['main_net_inflow_yi'] = flow.get('main_net_inflow_yi')
                item['source'] = 'akshare'
                result.append(item)
        if result:
            print(f'[MarketReview] 宽基ETF(akshare): {len(result)}只')
            return result
    except Exception as e:
        print(f'  [MarketReview] akshare ETF失败: {e}')

    # 方法2: 东财 push2 stock/get 兜底 (价/涨跌, 资金流标记为近似)
    try:
        for code, name in [('510300', '沪深300ETF'), ('510500', '中证500ETF'), ('159915', '创业板ETF'),
                           ('588000', '科创50ETF'), ('510050', '上证50ETF'), ('512100', '中证1000ETF')]:
            secid = ('1.' if code.startswith('5') and code[0] == '5' and code != '512100' else ('0.' if code.startswith('0') or code == '159915' else '1.')) + code
            # 沪深/科创/中证1000 在上交所(1.), 创业板在深交所(0.)
            secid = ('1.' if code in ('510300', '510500', '588000', '510050', '512100') else '0.') + code
            d = _em_clist_stock_get(secid)
            if d:
                result.append(d)
        if result:
            print(f'[MarketReview] 宽基ETF(东财兜底): {len(result)}只')
    except Exception as e:
        print(f'  [MarketReview] 东财 ETF兜底失败: {e}')

    return result


def _em_clist_stock_get(secid):
    """东财 push2 stock/get 单只查询 (ETF/个股兜底)"""
    try:
        url = 'https://push2.eastmoney.com/api/qt/stock/get'
        params = {'secid': secid, 'fields': 'f43,f57,f58,f170,f62', 'invt': 2}
        r = requests.get(url, params=params, headers=EM_HEADERS, timeout=(4, 8))
        d = r.json().get('data') or {}
        if not d:
            return None
        f43 = d.get('f43')
        price = round(float(f43) / 1000, 3) if f43 not in (None, '-') else None  # ETF 3位小数
        f170 = d.get('f170')
        chg = round(float(f170) / 100, 2) if f170 not in (None, '-') else None
        f62 = d.get('f62')
        net = round(float(f62) / 1e8, 2) if f62 not in (None, '-') and float(f62 or 0) != 0 else None
        return {
            'name': d.get('f58', ''), 'code': d.get('f57', ''),
            'close': price, 'change_pct': chg,
            'main_net_inflow_yi': net, 'source': 'eastmoney',
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════
# 8. 情绪池 (涨停/炸板/昨日涨停)
# ═══════════════════════════════════════════════════

def _em_zt_pool(kind, date_str):
    """东财 push2ex 涨停池直连 (kind: zt/yz/zb), 返回 pool list. 字段: c=代码 n=名称 zdp=涨跌幅 lbc=连板数 zbc=炸板次数"""
    urls = {
        'zt': 'https://push2ex.eastmoney.com/getTopicZTPool',
        'yz': 'https://push2ex.eastmoney.com/getYesterdayZTPool',
        'zb': 'https://push2ex.eastmoney.com/getTopicZBPool',
    }
    params = {'ut': '7eea3edcaed734bea9cbfc24409ed989', 'dpt': 'wz.ztzt',
              'Pageindex': '0', 'pagesize': '200', 'sort': 'fbt:asc', 'date': date_str}
    try:
        r = requests.get(urls[kind], params=params, headers=EM_HEADERS, timeout=(4, 10))
        d = r.json().get('data') or {}
        return d.get('pool') or []
    except Exception as e:
        print(f'  [MarketReview] 东财涨停池({kind})失败: {e}')
        return []


def _em_zt_pool_recent(kind, days=5):
    """东财涨停池: 遍历近days日, 返回首个有数据的(pool, date)"""
    for off in range(days):
        d = (datetime.now() - timedelta(days=off)).strftime('%Y%m%d')
        pool = _em_zt_pool(kind, d)
        if pool:
            return pool, d
    return [], None


def fetch_sentiment_pools():
    """情绪: 涨停池/昨日涨停池/炸板率 (akshare主源 → 东财push2ex直连兜底)"""
    print('[MarketReview] 采集情绪池(涨停/炸板/昨日涨停)...')
    result = {'limit_up_count': None, 'yesterday_zt_count': None, 'zhaban_count': None,
              'zhaban_rate': None, 'limit_up_names': [], 'yesterday_zt_names': [], 'source': 'akshare'}

    today_str = datetime.now().strftime('%Y%m%d')

    # ── 涨停池 ──
    try:
        zt_func = getattr(ak, 'stock_zt_pool_em', None)
        if zt_func:
            df = call_with_timeout(zt_func, timeout=12, date=today_str)
            if df is not None and len(df) > 0:
                names = [str(row.get('名称') or row.get('name') or '') for _, row in df.iterrows()]
                names = [n for n in names if n]
                result['limit_up_count'] = len(names)
                result['limit_up_names'] = names[:20]
    except Exception as e:
        print(f'  [MarketReview] akshare 涨停池失败: {e}')

    # 东财直连兜底
    if result['limit_up_count'] is None:
        pool, d = _em_zt_pool_recent('zt')
        if pool:
            names = [str(it.get('n') or '') for it in pool]
            names = [n for n in names if n]
            result['limit_up_count'] = len(names)
            result['limit_up_names'] = names[:20]
            result['source'] = 'eastmoney'
            print(f'  [MarketReview] 涨停池走东财直连(date={d}): {len(names)}只')

    # ── 昨日涨停 ──
    try:
        yz_func = getattr(ak, 'stock_zt_pool_previous_em', None)
        if yz_func:
            df2 = call_with_timeout(yz_func, timeout=12, date=today_str)
            if df2 is not None and len(df2) > 0:
                names2 = [str(row.get('名称') or row.get('name') or '') for _, row in df2.iterrows()]
                names2 = [n for n in names2 if n]
                result['yesterday_zt_count'] = len(names2)
                result['yesterday_zt_names'] = names2[:20]
    except Exception as e:
        print(f'  [MarketReview] akshare 昨日涨停失败: {e}')

    if result['yesterday_zt_count'] is None:
        pool, d = _em_zt_pool_recent('yz')
        if pool:
            names2 = [str(it.get('n') or '') for it in pool]
            names2 = [n for n in names2 if n]
            result['yesterday_zt_count'] = len(names2)
            result['yesterday_zt_names'] = names2[:20]
            if result['source'] == 'akshare':
                result['source'] = 'eastmoney'

    # ── 炸板池 ──
    zb_count = None
    try:
        zb_func = getattr(ak, 'stock_zt_pool_zbgc_em', None) or getattr(ak, 'stock_zt_pool_strong_em', None)
        if zb_func:
            df3 = call_with_timeout(zb_func, timeout=12, date=today_str)
            if df3 is not None and len(df3) > 0:
                zb_count = len(df3)
    except Exception as e:
        print(f'  [MarketReview] akshare 炸板池失败: {e}')

    if zb_count is None:
        pool, d = _em_zt_pool_recent('zb')
        if pool:
            zb_count = len(pool)
            if result['source'] == 'akshare':
                result['source'] = 'eastmoney'
    result['zhaban_count'] = zb_count

    # 炸板率: 炸板/(涨停+炸板)
    if result['zhaban_count'] is not None and result['limit_up_count']:
        total = result['zhaban_count'] + result['limit_up_count']
        result['zhaban_rate'] = round(result['zhaban_count'] / total * 100, 1) if total else None

    if result['limit_up_count'] is None and result['zhaban_count'] is None:
        result['source'] = 'none'
    elif result['limit_up_count'] is None:
        result['source'] = 'breadth'
    print(f'[MarketReview] 情绪池(src={result["source"]}): 涨停{result["limit_up_count"]} 昨日涨停{result["yesterday_zt_count"]} 炸板{result["zhaban_count"]}')
    return result


# ═══════════════════════════════════════════════════
# 9. 赛道拥挤度 (AI/新能源 等成交额占全市场比)
# ═══════════════════════════════════════════════════

TRACK_SECTORS = {
    'AI/人工智能': ['计算机', '传媒', '通信', '电子'],
    '新能源': ['电力设备', '有色金属', '汽车'],
    '半导体': ['电子'],
    '医药': ['医药生物'],
    '消费': ['食品饮料', '家用电器', '商贸零售', '社会服务'],
    '金融': ['银行', '非银金融'],
    '军工': ['国防军工'],
    '周期资源': ['煤炭', '石油石化', '钢铁', '基础化工', '有色金属'],
}


def _fetch_industry_turnover():
    """东财行业板块成交额(元) -> {行业名: 成交额元}"""
    diff = _em_clist('f14,f6', 'm:90+t:2', pz=80, fid='f6', po='1')
    out = {}
    for it in diff:
        name = it.get('f14')
        amt = it.get('f6')
        if name and amt not in (None, '-'):
            try:
                out[str(name)] = float(amt)
            except (ValueError, TypeError):
                pass
    return out


def fetch_track_crowding():
    """赛道拥挤度: 赛道=所属行业集合, 计算各赛道成交额占全市场比"""
    print('[MarketReview] 采集赛道拥挤度...')
    ind_turn = _fetch_industry_turnover()
    if not ind_turn:
        print('  [MarketReview] 行业成交额获取失败')
        return []
    total = sum(ind_turn.values())
    if total == 0:
        return []
    tracks = []
    for track, sectors in TRACK_SECTORS.items():
        amt = sum(ind_turn.get(s, 0) for s in sectors)
        share = round(amt / total * 100, 2) if total else 0
        tracks.append({
            'track': track, 'turnover_yi': round(amt / 1e8, 2),
            'share_pct': share, 'sectors': sectors,
            'crowded': share >= 15,  # 占比>=15% 视为拥挤预警
        })
    tracks.sort(key=lambda x: x['share_pct'], reverse=True)
    print(f'[MarketReview] 赛道拥挤度: {len(tracks)}条, 最高{ (tracks[0]["track"] if tracks else "-") } { (tracks[0]["share_pct"] if tracks else 0) }%')
    return tracks


# ═══════════════════════════════════════════════════
# 10. 量价异动 (放量突破 / 缩量回调 / 底部放量)
# ═══════════════════════════════════════════════════

def fetch_price_volume_anomalies():
    """量价异动: 东财 clist 按量比/涨幅筛选, 分类为 放量突破/缩量回调/底部放量"""
    print('[MarketReview] 采集量价异动...')
    fs = 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23'
    diff = _em_clist('f12,f14,f2,f3,f10,f8', fs, pz=600, fid='f10', po='1')
    if not diff:
        return []
    items = []
    for it in diff:
        code = it.get('f12')
        name = it.get('f14')
        if not code or not name:
            continue
        try:
            chg = float(it.get('f3', 0) or 0) / 100
            vol_ratio = float(it.get('f10', 0) or 0) / 100  # 量比*100
        except (ValueError, TypeError):
            continue
        if vol_ratio <= 0:
            continue
        kind = None
        if vol_ratio >= 3 and chg >= 3:
            kind = '放量突破'
        elif 0 < vol_ratio <= 0.6 and -3 <= chg < 0:
            kind = '缩量回调'
        elif vol_ratio >= 3 and chg < 0:
            kind = '底部放量'
        if kind:
            items.append({
                'code': code, 'name': name, 'change_pct': round(chg, 2),
                'vol_ratio': round(vol_ratio, 2), 'type': kind,
            })
    # 每类取前 10
    by_type = {}
    for it in items:
        by_type.setdefault(it['type'], []).append(it)
    out = []
    for kind, lst in by_type.items():
        out.extend(sorted(lst, key=lambda x: x['vol_ratio'], reverse=True)[:10])
    print(f'[MarketReview] 量价异动: {len(out)}条')
    return out


# ═══════════════════════════════════════════════════
# 11. 资金异动 / 龙虎榜 (机构净买 TOP + 北向扫货)
# ═══════════════════════════════════════════════════

def _em_lhb_detail():
    """东财 datacenter-web 龙虎榜直连: 取最近交易日个股净买TOP. 字段: SECURITY_CODE/NAME_ABBR/BILLBOARD_NET_AMT/BILLBOARD_BUY_AMT/BILLBOARD_SELL_AMT"""
    url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
    params = {
        'reportName': 'RPT_DAILYBILLBOARD_DETAILSNEW',
        'columns': 'ALL',
        'pageNumber': 1, 'pageSize': 500,
        'sortColumns': 'SECURITY_CODE',
        'sortTypes': 1,
    }
    try:
        r = requests.get(url, params=params, headers=EM_HEADERS, timeout=(4, 12))
        j = r.json()
        # 鲁棒解析: result.data 或 result 直接 list
        res = j.get('result')
        if isinstance(res, dict):
            rows = res.get('data') or []
        elif isinstance(res, list):
            rows = res
        else:
            rows = j.get('data') or []
        if not rows:
            return [], None
        # 取最近交易日
        dates = sorted({row.get('TRADE_DATE', '') for row in rows if row.get('TRADE_DATE')}, reverse=True)
        latest = dates[0] if dates else None
        if latest:
            rows = [row for row in rows if row.get('TRADE_DATE') == latest]
        ranked = []
        for row in rows:
            code = row.get('SECURITY_CODE')
            name = row.get('NAME_ABBR') or row.get('SECURITY_NAME_ABBR') or ''
            net = row.get('BILLBOARD_NET_AMT')
            buy = row.get('BILLBOARD_BUY_AMT')
            sell = row.get('BILLBOARD_SELL_AMT')
            if not code or net is None:
                continue
            try:
                ranked.append({
                    'code': str(code), 'name': str(name),
                    'inst_net_buy_yi': round(float(net) / 1e8, 2),
                    'inst_buy_yi': round(float(buy) / 1e8, 2) if buy is not None else 0,
                    'inst_sell_yi': round(float(sell) / 1e8, 2) if sell is not None else 0,
                })
            except (ValueError, TypeError):
                continue
        ranked.sort(key=lambda x: x['inst_net_buy_yi'], reverse=True)
        return ranked, latest
    except Exception as e:
        print(f'  [MarketReview] 东财龙虎榜直连失败: {e}')
        return [], None


def fetch_lhb_capital():
    """资金异动: 龙虎榜净买TOP (东财datacenter-web直连主源 → akshare兜底)"""
    print('[MarketReview] 采集龙虎榜机构异动...')
    result = {'lhb_institution': [], 'source': 'none'}

    # ── 主源: 东财 datacenter-web 直连 ──
    ranked, latest_date = _em_lhb_detail()
    if ranked:
        result['lhb_institution'] = ranked[:15]
        result['source'] = 'eastmoney'
        print(f'[MarketReview] 龙虎榜(东财直连 date={latest_date}): {len(ranked)}只, 取TOP15')
        return result

    # ── 兜底: akshare ──
    today_str = datetime.now().strftime('%Y%m%d')
    try:
        func = getattr(ak, 'stock_lhb_detail_em', None)
        if func:
            df = call_with_timeout(func, timeout=15, date=today_str)
            if df is not None and len(df) > 0:
                inst_net = {}
                for _, row in df.iterrows():
                    name = row.get('名称') or row.get('name')
                    code = row.get('代码') or row.get('code')
                    if not name:
                        continue
                    key = (str(code), str(name))
                    buy = sell = 0.0
                    for col in df.columns:
                        cs = str(col)
                        if '机构' in cs and ('买入' in cs or '买进' in cs):
                            try: buy += float(row[col] or 0)
                            except (ValueError, TypeError): pass
                        elif '机构' in cs and '卖出' in cs:
                            try: sell += float(row[col] or 0)
                            except (ValueError, TypeError): pass
                    if key not in inst_net:
                        inst_net[key] = {'code': str(code), 'name': str(name), 'inst_buy': 0.0, 'inst_sell': 0.0}
                    inst_net[key]['inst_buy'] += buy
                    inst_net[key]['inst_sell'] += sell
                ak_ranked = []
                for k, v in inst_net.items():
                    net = round((v['inst_buy'] - v['inst_sell']) / 1e8, 2)
                    ak_ranked.append({
                        'code': v['code'], 'name': v['name'],
                        'inst_net_buy_yi': net,
                        'inst_buy_yi': round(v['inst_buy'] / 1e8, 2),
                        'inst_sell_yi': round(v['inst_sell'] / 1e8, 2),
                    })
                ak_ranked.sort(key=lambda x: x['inst_net_buy_yi'], reverse=True)
                result['lhb_institution'] = ak_ranked[:15]
                result['source'] = 'akshare'
                print(f'[MarketReview] 龙虎榜(akshare兜底): {len(ak_ranked)}只, 取TOP15')
    except Exception as e:
        print(f'  [MarketReview] akshare 龙虎榜失败: {e}')
    return result


# ═══════════════════════════════════════════════════
# 13. 个股排名 (主力净流入/涨跌, 14子字段)
# ═══════════════════════════════════════════════════

def _parse_em_stock_row(it):
    """东财 clist 单只股票行 -> 标准化 dict (字段码已探针标定)"""
    try:
        code = it.get('f12')
        name = it.get('f14')
        if not code or not name:
            return None
        price = float(it.get('f2', 0) or 0) / 100 if it.get('f2') not in (None, '-') else None
        chg = float(it.get('f3', 0) or 0) / 100 if it.get('f3') not in (None, '-') else None
        net = float(it.get('f62', 0) or 0) if it.get('f62') not in (None, '-') else 0
        net_pct = float(it.get('f184', 0) or 0) / 100 if it.get('f184') not in (None, '-') else None
        industry = it.get('f100')
        net_5d = float(it.get('f164', 0) or 0) if it.get('f164') not in (None, '-') else 0
        net_10d = float(it.get('f166', 0) or 0) if it.get('f166') not in (None, '-') else 0
        chg_5d = float(it.get('f163', 0) or 0) / 100 if it.get('f163') not in (None, '-') else None
        chg_10d = float(it.get('f169', 0) or 0) / 100 if it.get('f169') not in (None, '-') else None
        return {
            'code': code, 'name': name,
            'close': round(price, 2) if price else None,
            'change_pct': round(chg, 2) if chg is not None else None,
            'main_net_inflow_yi': round(net / 1e8, 2),
            'main_net_pct': net_pct,
            'industry': industry or '',
            'net_5d_yi': round(net_5d / 1e8, 2),
            'net_10d_yi': round(net_10d / 1e8, 2),
            'chg_5d': chg_5d, 'chg_10d': chg_10d,
            'concept': '',  # 概念需 akshare 概念接口, 批次C补充
            'source': 'eastmoney',
        }
    except Exception:
        return None


def _parse_akshare_stock_rank(df):
    """akshare stock_individual_fund_flow_rank -> 标准化 list (命名列, 鲁棒)"""
    rows = []
    for _, row in df.iterrows():
        item = {}
        for col in df.columns:
            cs = str(col)
            if '代码' == cs or '代码' in cs:
                item['code'] = str(row[col])
            elif '名称' == cs:
                item['name'] = str(row[col])
            elif '最新价' in cs:
                try: item['close'] = round(float(row[col] or 0), 2)
                except (ValueError, TypeError): pass
            elif '涨跌幅' == cs:
                try: item['change_pct'] = round(float(row[col] or 0), 2)
                except (ValueError, TypeError): pass
            elif '主力净流入' in cs and ('净额' in cs or '净量' in cs or cs.endswith('主力净流入')):
                try: item['main_net_inflow_yi'] = round(float(row[col] or 0) / 1e8, 2)
                except (ValueError, TypeError): pass
            elif '主力净流入' in cs and '主力流入' in cs:
                try: item['main_inflow_yi'] = round(float(row[col] or 0) / 1e8, 2)
                except (ValueError, TypeError): pass
            elif '主力净流入' in cs and '主力流出' in cs:
                try: item['main_outflow_yi'] = round(float(row[col] or 0) / 1e8, 2)
                except (ValueError, TypeError): pass
            elif '净占比' in cs:
                try: item['main_net_pct'] = round(float(row[col] or 0), 2)
                except (ValueError, TypeError): pass
            elif '5日' in cs and '净额' in cs:
                try: item['net_5d_yi'] = round(float(row[col] or 0) / 1e8, 2)
                except (ValueError, TypeError): pass
            elif '10日' in cs and '净额' in cs:
                try: item['net_10d_yi'] = round(float(row[col] or 0) / 1e8, 2)
                except (ValueError, TypeError): pass
            elif '所属行业' in cs or '行业' == cs:
                item['industry'] = str(row[col])
        if item.get('code') and item.get('name'):
            item.setdefault('concept', '')
            item.setdefault('source', 'akshare')
            rows.append(item)
    return rows


def fetch_stock_rank():
    """个股排名: akshare 主源(主力流入/流出/概念命名列), 东财 clist 兜底并补充5日/10日涨幅"""
    print('[MarketReview] 采集个股排名(主力净流入/涨跌)...')
    rows = []
    # 主源: akshare
    try:
        func = getattr(ak, 'stock_individual_fund_flow_rank', None)
        if func:
            df = call_with_timeout(func, timeout=20, indicator='今日')
            if df is not None and len(df) > 0:
                rows = _parse_akshare_stock_rank(df)
    except Exception as e:
        print(f'  [MarketReview] akshare 个股排名失败: {e}')

    # 东财 clist: 兜底 + 补充 5日/10日涨幅/行业
    em_map = {}
    try:
        diff = _em_clist('f12,f14,f2,f3,f62,f184,f100,f164,f166,f163,f169',
                         'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23', pz=4000, fid='f62', po='1')
        for it in diff:
            r = _parse_em_stock_row(it)
            if r:
                em_map[r['code']] = r
    except Exception as e:
        print(f'  [MarketReview] 东财 个股排名失败: {e}')

    if not rows and em_map:
        rows = list(em_map.values())
    else:
        # 用东财补 5日/10日涨幅 与 行业
        for r in rows:
            em = em_map.get(r.get('code'))
            if em:
                if r.get('chg_5d') is None:
                    r['chg_5d'] = em.get('chg_5d')
                if r.get('chg_10d') is None:
                    r['chg_10d'] = em.get('chg_10d')
                if not r.get('industry'):
                    r['industry'] = em.get('industry')

    if not rows:
        print('  [MarketReview] 个股排名无数据')
        return {}

    top_inflow = sorted([r for r in rows if r.get('main_net_inflow_yi') is not None],
                        key=lambda x: x['main_net_inflow_yi'], reverse=True)[:30]
    top_gainers = sorted(rows, key=lambda x: (x.get('change_pct') if x.get('change_pct') is not None else -999), reverse=True)[:30]
    top_losers = sorted(rows, key=lambda x: (x.get('change_pct') if x.get('change_pct') is not None else 999))[:30]
    print(f'[MarketReview] 个股排名: 共{len(rows)}只, 净流入TOP{len(top_inflow)}, 涨TOP{len(top_gainers)}, 跌TOP{len(top_losers)}')
    return {'top_inflow': top_inflow, 'top_gainers': top_gainers, 'top_losers': top_losers, 'count': len(rows)}


# ═══════════════════════════════════════════════════
# 12. 事件驱动 (公告/财报预告/停复牌/解禁)
# ═══════════════════════════════════════════════════

def _ak_cell(row, df, *keywords):
    """从 akshare 行中按列名关键词提取第一个匹配列的值"""
    for col in df.columns:
        cs = str(col)
        if any(k in cs for k in keywords):
            return row[col]
    return None

def fetch_market_events():
    """事件驱动: 聚合当日重大公告/财报预告/停复牌/解禁 (akshare 主源, 单类隔离降级)"""
    print('[MarketReview] 采集事件驱动(公告/财报/停复牌/解禁)...')
    today_str = datetime.now().strftime('%Y%m%d')
    result = {'notices': [], 'earnings': [], 'suspension': [], 'unlocks': [],
              'source': 'akshare', 'has_data': False}

    # ── 重大事项公告 ──
    try:
        func = getattr(ak, 'stock_notice_report', None)
        if func:
            df = call_with_timeout(func, timeout=15, symbol='重大事项')
            if df is not None and len(df) > 0:
                for _, row in df.iterrows():
                    code = _ak_cell(row, df, '代码')
                    name = _ak_cell(row, df, '名称', '简称')
                    title = _ak_cell(row, df, '公告标题', '标题', '事项')
                    date = _ak_cell(row, df, '公告日期', '日期')
                    if code:
                        result['notices'].append({
                            'code': str(code), 'name': str(name or ''),
                            'title': str(title or ''), 'date': str(date or '')[:10],
                        })
                result['notices'] = result['notices'][:15]
    except Exception as e:
        print(f'  [MarketReview] 重大事项公告失败: {e}')

    # ── 财报预告 ──
    try:
        func = getattr(ak, 'stock_yjyg_em', None)
        if func:
            df = call_with_timeout(func, timeout=15)
            if df is not None and len(df) > 0:
                for _, row in df.iterrows():
                    code = _ak_cell(row, df, '代码')
                    name = _ak_cell(row, df, '名称', '简称')
                    typ = _ak_cell(row, df, '业绩变动类型', '类型', '预告类型')
                    date = _ak_cell(row, df, '公告日期', '业绩预告日期', '日期')
                    if code:
                        result['earnings'].append({
                            'code': str(code), 'name': str(name or ''),
                            'type': str(typ or ''), 'date': str(date or '')[:10],
                        })
                result['earnings'] = result['earnings'][:15]
    except Exception as e:
        print(f'  [MarketReview] 财报预告失败: {e}')

    # ── 停复牌 ──
    try:
        func = getattr(ak, 'stock_tfp_em', None)
        if func:
            df = call_with_timeout(func, timeout=15)
            if df is not None and len(df) > 0:
                for _, row in df.iterrows():
                    code = _ak_cell(row, df, '代码')
                    name = _ak_cell(row, df, '名称', '简称')
                    typ = _ak_cell(row, df, '停牌', '复牌', '类型')
                    date = _ak_cell(row, df, '日期', '停牌时间', '复牌时间')
                    if code:
                        result['suspension'].append({
                            'code': str(code), 'name': str(name or ''),
                            'type': str(typ or ''), 'date': str(date or '')[:10],
                        })
                result['suspension'] = result['suspension'][:15]
    except Exception as e:
        print(f'  [MarketReview] 停复牌失败: {e}')

    # ── 解禁 ──
    try:
        func = getattr(ak, 'stock_restricted_release_detail_em', None)
        if func:
            df = call_with_timeout(func, timeout=15, date=today_str)
            if df is not None and len(df) > 0:
                for _, row in df.iterrows():
                    code = _ak_cell(row, df, '代码')
                    name = _ak_cell(row, df, '名称', '简称')
                    amt = _ak_cell(row, df, '解禁数量', '解禁市值', '解禁股数')
                    date = _ak_cell(row, df, '解禁日期', '上市日期', '日期')
                    item = {'code': str(code), 'name': str(name or ''), 'date': str(date or '')[:10]}
                    try:
                        if amt is not None:
                            item['amount_yi'] = round(float(amt) / 1e8, 2) if float(amt) > 1e8 else round(float(amt), 2)
                    except (ValueError, TypeError):
                        pass
                    if code:
                        result['unlocks'].append(item)
                result['unlocks'] = result['unlocks'][:15]
    except Exception as e:
        print(f'  [MarketReview] 解禁失败: {e}')

    total = len(result['notices']) + len(result['earnings']) + len(result['suspension']) + len(result['unlocks'])
    result['has_data'] = total > 0
    print(f'[MarketReview] 事件驱动: 公告{len(result["notices"])} 财报{len(result["earnings"])} 停复牌{len(result["suspension"])} 解禁{len(result["unlocks"])}')
    return result


# ═══════════════════════════════════════════════════
# 15. 高低点 + MACD + 筹码分布 (仅主力净流入 TOP20)
# ═══════════════════════════════════════════════════

def _compute_macd(closes):
    """返回 (dif, dea, bar, state) 最近一日值; 参数 12/26/9"""
    try:
        import numpy as np
        import pandas as pd
    except Exception:
        return None, None, None, 'NA'
    s = pd.Series(closes, dtype=float)
    if len(s) < 35:
        return None, None, None, 'NA'
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    bar = 2 * (dif - dea)
    dif_v, dea_v, bar_v = float(dif.iloc[-1]), float(dea.iloc[-1]), float(bar.iloc[-1])
    # 状态: 金叉(dif上穿dea)/死叉(dif下穿dea)/多头(dif>dea)/空头
    prev_dif, prev_dea = float(dif.iloc[-2]), float(dea.iloc[-2])
    if prev_dif <= prev_dea and dif_v > dea_v:
        state = '金叉'
    elif prev_dif >= prev_dea and dif_v < dea_v:
        state = '死叉'
    elif dif_v > dea_v:
        state = '多头'
    else:
        state = '空头'
    return round(dif_v, 3), round(dea_v, 3), round(bar_v, 3), state


def _fallback_active_pool():
    """兜底股票池: 主力资金流采集失败时, 用当日成交额TOP20作为技术指标标的(东财clist主, akshare兜底)"""
    print('[MarketReview] 个股排名为空, 使用成交额TOP20兜底股票池...')
    try:
        diff = _em_clist('f12,f14,f6', 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23', pz=20, fid='f6', po='1')
        pool = []
        for it in diff:
            code = str(it.get('f12', ''))
            name = str(it.get('f14', ''))
            if code:
                pool.append({'code': code, 'name': name})
        if pool:
            print(f'  [MarketReview] 东财兜底股票池: {len(pool)}只')
            return pool
    except Exception as e:
        print(f'  [MarketReview] 东财兜底股票池失败: {e}')
    try:
        func = getattr(ak, 'stock_zh_a_spot_em', None)
        if func:
            df = call_with_timeout(func, timeout=20)
            if df is not None and len(df) > 0:
                df = df.sort_values('成交额', ascending=False).head(20)
                pool = [{'code': str(r['代码']), 'name': str(r['名称'])} for _, r in df.iterrows()]
                if pool:
                    print(f'  [MarketReview] akshare兜底股票池: {len(pool)}只')
                    return pool
    except Exception as e:
        print(f'  [MarketReview] akshare兜底失败: {e}')
    return []


def fetch_stock_technicals(top_inflow):
    """技术指标: 对主力净流入 TOP20 算 MACD(12/26/9)+近20日高低点+筹码分布"""
    print('[MarketReview] 采集技术指标(高低点/MACD/筹码)...')
    if not top_inflow:
        print('  [MarketReview] 无个股排名, 跳过技术指标')
        return []
    codes = [(r.get('code'), r.get('name')) for r in top_inflow[:20] if r.get('code')]
    out = []
    hist_func = getattr(ak, 'stock_zh_a_hist', None)
    cyq_func = getattr(ak, 'stock_cyq_em', None)
    for i, (code, name) in enumerate(codes):
        item = {'code': code, 'name': name or ''}
        # ── K线 + MACD + 高低点 ──
        try:
            if hist_func:
                df = call_with_timeout(hist_func, timeout=8, symbol=code, period='daily', adjust='qfq')
                if df is not None and len(df) > 0:
                    close = df['收盘'] if '收盘' in df.columns else df.iloc[:, 0]
                    closes = [float(x) for x in close.tolist()]
                    last = closes[-1]
                    hi20 = max(closes[-20:])
                    lo20 = min(closes[-20:])
                    item['close'] = round(last, 2)
                    item['high20'] = round(hi20, 2)
                    item['low20'] = round(lo20, 2)
                    item['drawdown_from_high_pct'] = round((last - hi20) / hi20 * 100, 2) if hi20 else None
                    dif, dea, bar, state = _compute_macd(closes)
                    item['macd_dif'] = dif
                    item['macd_dea'] = dea
                    item['macd_bar'] = bar
                    item['macd_state'] = state
                    # 保留近30日收盘价序列 + 日期, 供 PDF/看板画走势折线图
                    try:
                        item['close_series'] = [round(float(x), 2) for x in closes[-30:]]
                        if '日期' in df.columns:
                            dts = df['日期'].astype(str).tolist()[-30:]
                            item['date_series'] = [d[5:] if len(d) >= 10 else d for d in dts]
                        else:
                            item['date_series'] = list(range(1, len(item['close_series']) + 1))
                    except Exception:
                        pass
        except Exception as e:
            print(f'  [MarketReview] K线/MACD {code} 失败: {e}')
        # ── 筹码分布 ──
        try:
            if cyq_func:
                cdf = call_with_timeout(cyq_func, timeout=8, symbol=code, adjust='')
                if cdf is not None and len(cdf) > 0:
                    last = cdf.iloc[-1]
                    for col in cdf.columns:
                        cs = str(col)
                        if '获利比例' in cs or '盈利比例' in cs:
                            try: item['cyq_profit_pct'] = round(float(last[col]), 2)
                            except (ValueError, TypeError): pass
                        elif '平均成本' in cs:
                            try: item['cyq_avg_cost'] = round(float(last[col]), 2)
                            except (ValueError, TypeError): pass
                        elif '集中度' in cs:
                            try: item['cyq_concentration'] = round(float(last[col]), 2)
                            except (ValueError, TypeError): pass
        except Exception as e:
            print(f'  [MarketReview] 筹码 {code} 失败: {e}')
        out.append(item)
        if i < len(codes) - 1:
            time.sleep(0.2)  # 控频
    ok = [x for x in out if x.get('macd_state') and x.get('macd_state') != 'NA']
    print(f'[MarketReview] 技术指标: {len(out)}只, 有效MACD {len(ok)}只')
    return out


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

    # 1.1 扩展采集 (批次A: 国际指数/ETF/情绪/赛道/量价/龙虎榜/个股排名)
    intl_indices = fetch_intl_indices()
    etf_flow = fetch_etf_flow()
    sentiment_pools = fetch_sentiment_pools()
    track_crowding = fetch_track_crowding()
    price_volume_anomalies = fetch_price_volume_anomalies()
    lhb_capital = fetch_lhb_capital()
    stock_rank = fetch_stock_rank()
    market_events = fetch_market_events()
    # 技术指标股票池: 优先主力净流入TOP, 个股排名失败时用成交额TOP20兜底, 保证走势图始终有数据
    tech_pool = (stock_rank or {}).get('top_inflow')
    if not tech_pool:
        tech_pool = _fallback_active_pool()
    stock_technicals = fetch_stock_technicals(tech_pool)

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
        'intl_indices': intl_indices,
        'market_breadth': breadth,
        'northbound': northbound,
        'margin': margin,
        'etf_flow': etf_flow,
        'sector_flow': sector_flow[:10] if sector_flow else [],  # TOP10
        'sentiment_pools': sentiment_pools,
        'track_crowding': track_crowding,
        'price_volume_anomalies': price_volume_anomalies,
        'lhb_capital': lhb_capital,
        'stock_rank': stock_rank,
        'market_events': market_events,
        'stock_technicals': stock_technicals,
        'signals': signals,
        'anomalies': anomalies,
        'tomorrow_focus': tomorrow_focus,
    }

    print(f'[MarketReview] ═══ 复盘完成: {len(index_data)}指数, {len(anomalies)}异动, 情绪={signals.get("sentiment")} ═══')
    return result
