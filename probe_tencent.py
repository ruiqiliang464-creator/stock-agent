# -*- coding: utf-8 -*-
"""
腾讯 + 新浪 数据源探针 (用于验证美国 IP / GHA 环境连通性)
验证:
  1. 腾讯 Q=  批量行情: 量比[49] / 换手率[38] / 成交额[37] / 涨跌幅[32] / 现价[3]  (注意 [47]/[48] 是涨停/跌停价)
  2. 腾讯 K 线 web.ifzq.gtimg.cn (日K前复权)
  3. 新浪 getHQNodeData 全市场排行 (成交额/换手率 TOP)
  4. 新浪 moneyflow 个股资金流 (当日净流入 netamount / 超大单 r0_net)
  5. 稳定性: 腾讯 Q= 连续 5 次请求成功率
已确认不可用(不再探针): 腾讯 ff_ 资金流(v_pv_none_match)、腾讯 getHsRankList(方法不存在)
"""
import json
import sys
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TIMEOUT = 10
RESULTS = {}


def fetch_qt(codes):
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    r = requests.get(url, timeout=TIMEOUT, headers=UA)
    r.encoding = "gbk"
    return r.text


def parse_qt(text):
    out = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip().rstrip(";").strip('"')
        out[key.strip()] = val.split("~")
    return out


def probe_batch(codes):
    print(f"\n===== 1. 腾讯 Q= 批量行情 ({len(codes)}只) =====")
    t0 = time.time()
    text = fetch_qt(codes)
    dt = time.time() - t0
    parsed = parse_qt(text)
    print(f"耗时 {dt*1000:.0f}ms, 返回行数 {len(parsed)}, 原始字节 {len(text)}")
    ok = 0
    for key, f in parsed.items():
        if len(f) < 50:
            print(f"  {key}: 字段不足({len(f)}): {f[:5]}")
            continue
        try:
            pct = float(f[32]); amount = float(f[37]); turnover = float(f[38]); vr = float(f[49])
        except (ValueError, IndexError):
            print(f"  {key}: 字段解析异常 name={f[1]}")
            continue
        ok += 1
        print(f"  {key} name={f[1]} 现价={f[3]} 涨跌幅%={pct} 成交额万={amount} 换手%={turnover} 量比={vr}")
    print(f"有效解析 {ok}/{len(codes)}")
    RESULTS["batch"] = {"ok": ok, "total": len(codes), "ms": int(dt * 1000)}
    return ok


def probe_batch_stability(codes, n=5):
    print(f"\n===== 1b. 腾讯 Q= 连续 {n} 次稳定性 =====")
    fails = 0
    times = []
    for i in range(n):
        try:
            t0 = time.time()
            text = fetch_qt(codes)
            times.append(int((time.time() - t0) * 1000))
            parsed = parse_qt(text)
            nlines = len(parsed)
            if nlines < len(codes):
                fails += 1
                print(f"  第{i+1}次: 仅返回 {nlines} 行")
            else:
                print(f"  第{i+1}次: OK ({nlines}行, {times[-1]}ms)")
        except Exception as e:
            fails += 1
            print(f"  第{i+1}次: 异常 {e}")
    RESULTS["stability"] = {"fails": fails, "n": n, "ms_list": times}
    return fails


def probe_kline(symbol="sh600519", n=10):
    print(f"\n===== 2. 腾讯日K线 web.ifzq.gtimg.cn ({symbol}, {n}日) =====")
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={symbol},day,,,{n},qfq"
    )
    t0 = time.time()
    r = requests.get(url, timeout=TIMEOUT, headers=UA)
    dt = time.time() - t0
    data = r.json()
    node = data.get("data", {}).get(symbol, {})
    kl = node.get("qfqday") or node.get("day") or []
    print(f"HTTP {r.status_code}, 耗时 {dt*1000:.0f}ms, K线条数: {len(kl)}")
    if kl:
        print(f"  样例: {kl[0]}")
    RESULTS["kline"] = {"ok": len(kl) > 0, "n": len(kl), "ms": int(dt * 1000)}
    return len(kl)


def probe_sina_rank(sort="amount", num=10):
    print(f"\n===== 3. 新浪 getHQNodeData 全市场排行 (sort={sort}) =====")
    url = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"Market_Center.getHQNodeData?page=1&num={num}&sort={sort}&asc=0&node=hs_a&symbol=&_s_r_a=page"
    )
    t0 = time.time()
    r = requests.get(url, timeout=TIMEOUT, headers=UA)
    r.encoding = "gbk"
    dt = time.time() - t0
    try:
        rows = r.json()
    except Exception:
        rows = []
    print(f"HTTP {r.status_code}, 耗时 {dt*1000:.0f}ms, 返回 {len(rows)} 行")
    for row in rows[:5]:
        print(f"  {row.get('symbol')} {row.get('name')} 涨跌%={row.get('changepercent')} "
              f"成交额={row.get('amount')} 换手%={row.get('turnoverratio')}")
    RESULTS[f"sina_rank_{sort}"] = {"ok": len(rows) > 0, "n": len(rows), "ms": int(dt * 1000)}
    return len(rows)


def probe_sina_moneyflow(codes):
    print(f"\n===== 4. 新浪 moneyflow 个股资金流 ({len(codes)}只) =====")
    ok = 0
    for code in codes:
        url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"MoneyFlow.ssl_qsfx_zjlrqs?daima={code}"
        )
        try:
            t0 = time.time()
            r = requests.get(url, timeout=TIMEOUT, headers=UA)
            r.encoding = "gbk"
            dt = time.time() - t0
            rows = r.json()
            if rows and isinstance(rows, list) and len(rows) > 0:
                today = rows[0]
                print(f"  {code} 日期={today.get('opendate')} 净流入={today.get('netamount')} "
                      f"超大单净={today.get('r0_net')} ({dt*1000:.0f}ms)")
                ok += 1
            else:
                print(f"  {code}: 空返回")
        except Exception as e:
            print(f"  {code}: 异常 {e}")
    RESULTS["sina_moneyflow"] = {"ok": ok, "total": len(codes)}
    return ok


if __name__ == "__main__":
    BATCH = [
        "sh600519", "sz000858", "sz300750", "sh601318", "sz000001",
        "sh600036", "sz002594", "sh601899", "sh600030", "sz000333",
        "sh601166", "sz002415", "sh600887", "sz300059", "sh601012",
        "sz002475", "sh600900", "sz000651", "sh601668", "sz002714",
    ]
    ok1 = probe_batch(BATCH)
    fails = probe_batch_stability(BATCH[:8])
    ok2 = probe_kline()
    ok3a = probe_sina_rank("amount")
    ok3b = probe_sina_rank("turnoverratio")
    ok4 = probe_sina_moneyflow(["sz000858", "sh600519", "sz300750"])
    print("\n===== SUMMARY =====")
    print(json.dumps(RESULTS, ensure_ascii=False, indent=2))
    verdict = all([
        ok1 == len(BATCH),
        fails == 0,
        ok2 > 0,
        ok3a > 0,
        ok3b > 0,
        ok4 == 3,
    ])
    print("VERDICT:", "ALL OK" if verdict else "PARTIAL FAIL")
    sys.exit(0 if verdict else 1)
