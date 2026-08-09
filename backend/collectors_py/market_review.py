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

数据源优先级: akshare → 东方财富API(直连) → yfinance(仅指数)
"""

import akshare as ak
import requests
import json
import time
import yfinance as yf
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError


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
    {'code': '000001', 'name': '上证指数', 'em_secid': '1.000001', 'ak_symbol': 'sh000001', 'yf_symbol': '000001.SS'},
    {'code': '399001', 'name': '深证成指', 'em_secid': '0.399001', 'ak_symbol': 'sz399001', 'yf_symbol': '399001.SZ'},
    {'code': '399006', 'name': '创业板指', 'em_secid': '0.399006', 'ak_symbol': 'sz399006', 'yf_symbol': '399006.SZ'},
    {'code': '000300', 'name': '沪深300', 'em_secid': '1.000300', 'ak_symbol': 'sh000300', 'yf_symbol': '000300.SS'},
    {'code': '000688', 'name': '科创50', 'em_secid': '1.000688', 'ak_symbol': 'sh000688', 'yf_symbol': '000688.SS'},
]

EM_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.eastmoney.com/',
}


# ═══════════════════════════════════════════════════
# 1. 核心指数收盘数据
# ═══════════════════════════════════════════════════

def fetch_index_data():
    """获取核心指数收盘数据、涨跌幅度及成交额"""
    print('[MarketReview] 采集核心指数数据...')

    # 方法1: akshare
    results = _fetch_index_akshare()
    if len(results) >= 3:
        print(f'[MarketReview] akshare指数: {len(results)}条')
        return results

    # 方法2: 东方财富 push2his API (直连, 不同hostname可能可用)
    em_results = _fetch_index_eastmoney()
    if em_results:
        existing = {r['code'] for r in results}
        for r in em_results:
            if r['code'] not in existing:
                results.append(r)
        if len(results) >= 3:
            print(f'[MarketReview] eastmoney指数: {len(results)}条')
            return results

    # 方法3: yfinance (仅指数, 可从海外IP访问)
    yf_results = _fetch_index_yfinance()
    if yf_results:
        existing = {r['code'] for r in results}
        for r in yf_results:
            if r['code'] not in existing:
                results.append(r)

    print(f'[MarketReview] 指数采集完成: {len(results)}条')
    return results


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
            hist = ticker.history(period='5d')
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
            return _parse_market_breadth_akshare(df)
    except Exception as e:
        print(f'  [MarketReview] akshare市场广度失败: {e}')

    # 方法2: 东方财富 API (直连, 带超时)
    try:
        result = _fetch_breadth_eastmoney()
        if result:
            return result
    except Exception as e:
        print(f'  [MarketReview] eastmoney市场广度失败: {e}')

    # 注意: 不再调用 stock_zh_a_spot_em() (下载全市场行情, 过慢)
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
    """获取北向资金流向数据"""
    print('[MarketReview] 采集北向资金数据...')

    # 方法1: akshare (尝试多个可能的函数名, 兼容不同版本)
    ak_funcs = [
        ('stock_hsgt_north_net_flow_in_em', {'symbol': '北向资金'}),
        ('stock_hsgt_hist_em', {'symbol': '北向资金'}),
        ('stock_hsgt_north_acc_flow_in_em', {'symbol': '北向资金'}),
    ]
    for func_name, kwargs in ak_funcs:
        func = getattr(ak, func_name, None)
        if func is None:
            continue
        try:
            df = call_with_timeout(func, timeout=10, **kwargs)
            if df is not None and len(df) > 0:
                latest = df.iloc[-1]
                net_buy = 0
                date_str = ''
                for col in df.columns:
                    col_str = str(col)
                    if '净流入' in col_str or '净买入' in col_str or 'value' in col_str.lower():
                        try:
                            net_buy = float(latest[col] or 0)
                        except (ValueError, TypeError):
                            net_buy = 0
                    elif 'date' in col_str.lower() or '日期' in col_str:
                        date_str = str(latest[col])

                if net_buy != 0 or date_str:
                    result = {
                        'net_buy': round(net_buy, 2),
                        'net_buy_yi': round(net_buy / 1e8, 2),
                        'date': date_str,
                        'is_extreme': abs(net_buy) > 10e8,
                        'extreme_note': '',
                        'source': f'akshare({func_name})',
                    }
                    if net_buy > 10e8:
                        result['extreme_note'] = '北向单日净买入超100亿，极端流入信号'
                    elif net_buy < -10e8:
                        result['extreme_note'] = '北向单日净卖出超100亿，极端流出信号'
                    print(f'[MarketReview] 北向资金({func_name}): 净{("买入" if net_buy > 0 else "卖出")}{result["net_buy_yi"]:.2f}亿')
                    return result
        except Exception as e:
            print(f'  [MarketReview] akshare北向资金({func_name})失败: {e}')

    # 方法2: 东方财富 push2his API
    try:
        result = _fetch_northbound_eastmoney()
        if result:
            return result
    except Exception as e:
        print(f'  [MarketReview] eastmoney北向资金失败: {e}')

    print('[MarketReview] 北向资金数据不可用')
    return {}


def _fetch_northbound_eastmoney():
    """东方财富 push2his API 获取北向资金"""
    try:
        today_str = datetime.now().strftime('%Y%m%d')
        beg_str = (datetime.now() - timedelta(days=10)).strftime('%Y%m%d')

        url = 'https://push2his.eastmoney.com/api/qt/kamt.kline/get'
        params = {
            'fields1': 'f1,f2,f3,f4',
            'fields2': 'f51,f52,f53,f54,f55,f56',
            'klt': '101',
            'beg': beg_str,
            'end': today_str,
        }
        resp = requests.get(url, params=params, headers=EM_HEADERS, timeout=(3, 8))
        if resp.status_code == 200:
            data = resp.json()
            # 使用 or {} 防止 data['data'] 为 None 时崩溃
            em_data = data.get('data') or {}
            klines = em_data.get('klines', [])
            if klines and len(klines) >= 1:
                # 格式: date,sh_connect_net,sz_connect_net,total_net,...
                parts = klines[-1].split(',')
                date_str = parts[0]
                # 尝试解析北向净流入 (通常是第2或第4个字段)
                sh_net = float(parts[1]) if len(parts) > 1 and parts[1] else 0
                sz_net = float(parts[2]) if len(parts) > 2 and parts[2] else 0
                total_net = float(parts[-1]) if parts[-1] else 0

                # 如果total为0，尝试用sh+sz
                if total_net == 0:
                    total_net = sh_net + sz_net

                result = {
                    'net_buy': round(total_net, 2),
                    'net_buy_yi': round(total_net / 1e8, 2),
                    'sh_connect_yi': round(sh_net / 1e8, 2),
                    'sz_connect_yi': round(sz_net / 1e8, 2),
                    'date': date_str,
                    'is_extreme': abs(total_net) > 10e8,
                    'extreme_note': '',
                    'source': 'eastmoney',
                }
                if total_net > 10e8:
                    result['extreme_note'] = '北向单日净买入超100亿，极端流入信号'
                elif total_net < -10e8:
                    result['extreme_note'] = '北向单日净卖出超100亿，极端流出信号'
                print(f'[MarketReview] 北向资金(eastmoney): 净{("买入" if total_net > 0 else "卖出")}{result["net_buy_yi"]:.2f}亿')
                return result
            else:
                print(f'  [MarketReview] eastmoney northbound: 响应无klines数据 (data={data.get("data")})')
        else:
            print(f'  [MarketReview] eastmoney northbound: HTTP {resp.status_code}')
    except Exception as e:
        print(f'  [MarketReview] eastmoney northbound: {e}')
    return None


# ═══════════════════════════════════════════════════
# 4. 两融余额变化
# ═══════════════════════════════════════════════════

def fetch_margin_stats():
    """获取两融余额变化"""
    print('[MarketReview] 采集两融数据...')

    today_str = datetime.now().strftime('%Y%m%d')
    prev_str = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

    # 方法1: akshare SSE (stock_margin_detail_sse 接受 date 参数)
    try:
        df = call_with_timeout(ak.stock_margin_detail_sse, timeout=10, date=today_str)
        if df is not None and len(df) > 0:
            latest = df.iloc[-1]
            result = {}
            for col in df.columns:
                col_str = str(col)
                if '融资余额' in col_str:
                    try:
                        result['finance_balance'] = float(latest[col] or 0)
                    except (ValueError, TypeError):
                        result['finance_balance'] = 0
                elif '融券余额' in col_str:
                    try:
                        result['securities_balance'] = float(latest[col] or 0)
                    except (ValueError, TypeError):
                        result['securities_balance'] = 0
                elif '融资融券余额' in col_str or '两融余额' in col_str:
                    try:
                        result['total_balance'] = float(latest[col] or 0)
                    except (ValueError, TypeError):
                        result['total_balance'] = 0
                elif '日期' in col_str or 'date' in col_str.lower():
                    result['date'] = str(latest[col])

            if result.get('total_balance') is None and result.get('finance_balance') and result.get('securities_balance'):
                result['total_balance'] = result['finance_balance'] + result['securities_balance']

            # 获取前一交易日数据计算变化
            df_prev = call_with_timeout(ak.stock_margin_detail_sse, timeout=10, date=prev_str)
            if df_prev is not None and len(df_prev) > 0:
                prev = df_prev.iloc[-1]
                for col in df_prev.columns:
                    if '融资融券余额' in str(col) or '两融余额' in str(col):
                        try:
                            prev_balance = float(prev[col] or 0)
                        except (ValueError, TypeError):
                            prev_balance = 0
                        if result.get('total_balance') and prev_balance:
                            result['balance_change'] = round(result['total_balance'] - prev_balance, 2)
                            result['balance_change_yi'] = round(result['balance_change'] / 1e8, 2)
                        break

            result['source'] = 'akshare_sse'
            result.setdefault('balance_change', 0)
            result.setdefault('balance_change_yi', 0)

            # 转换为亿元
            if result.get('total_balance'):
                result['total_balance_yi'] = round(result['total_balance'] / 1e8, 2)
            if result.get('finance_balance'):
                result['finance_balance_yi'] = round(result['finance_balance'] / 1e8, 2)
            if result.get('securities_balance'):
                result['securities_balance_yi'] = round(result['securities_balance'] / 1e8, 2)

            print(f'[MarketReview] 两融余额: {result.get("total_balance_yi", 0):.2f}亿 变化{result.get("balance_change_yi", 0):+.2f}亿')
            return result
    except Exception as e:
        print(f'  [MarketReview] akshare两融失败: {e}')

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
    """东方财富 datacenter API 获取两融数据"""
    try:
        url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
        params = {
            'reportName': 'RPTZRZMRZB',
            'sortColumns': 'RQ',
            'sortTypes': '-1',
            'pageSize': '5',
            'pageNumber': '1',
            'columns': 'ALL',
        }
        resp = requests.get(url, params=params, headers=EM_HEADERS, timeout=(3, 8))
        if resp.status_code == 200:
            data = resp.json()
            rows = (data.get('result') or {}).get('data', [])
            if not rows:
                # 尝试不同的数据路径
                rows = data.get('data', [])
            if rows and len(rows) >= 1:
                latest = rows[0]
                result = {
                    'total_balance': float(latest.get('RZYE', 0) or 0) + float(latest.get('RQYE', 0) or 0),
                    'finance_balance': float(latest.get('RZYE', 0) or 0),
                    'securities_balance': float(latest.get('RQYE', 0) or 0),
                    'date': str(latest.get('RQ', '')),
                    'source': 'eastmoney',
                }
                result['total_balance_yi'] = round(result['total_balance'] / 1e8, 2)
                result['finance_balance_yi'] = round(result['finance_balance'] / 1e8, 2)
                result['securities_balance_yi'] = round(result['securities_balance'] / 1e8, 2)

                if len(rows) >= 2:
                    prev = rows[1]
                    prev_total = float(prev.get('RZYE', 0) or 0) + float(prev.get('RQYE', 0) or 0)
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
                print(f'[MarketReview] 行业资金流: {len(results)}个板块')
                return results
    except Exception as e:
        print(f'  [MarketReview] akshare板块资金流失败: {e}')

    # 方法2: 东方财富 API
    try:
        result = _fetch_sector_flow_eastmoney()
        if result:
            return result
    except Exception as e:
        print(f'  [MarketReview] eastmoney板块资金流失败: {e}')

    print('[MarketReview] 行业板块资金流数据不可用')
    return []


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
        top_inflow = sector_flow[0] if sector_flow else {}
        if top_inflow.get('net_inflow_yi', 0) > 20:
            flow_signals.append(f'{top_inflow["name"]}板块资金大幅净流入{top_inflow["net_inflow_yi"]:.1f}亿')

        # 找最大流出
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

    # 4. 板块资金大幅调仓
    if sector_flow and len(sector_flow) >= 2:
        top = sector_flow[0]
        bottom = sector_flow[-1]
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
    if northbound and northbound.get('net_buy_yi'):
        nb = northbound['net_buy_yi']
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
    if northbound and northbound.get('net_buy_yi'):
        nb = northbound['net_buy_yi']
        if nb > 0:
            focus.append(f'关注北向资金持续流入方向的板块')
        else:
            focus.append(f'关注北向资金流出对大盘的持续影响')

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
