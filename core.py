"""
核心数据逻辑 —— 被 streamlit_app.py（网页）和 alerts.py（定时推送）共用
不依赖任何本地 config.py，所有参数从外部传入，方便部署到云端
"""
import time
import datetime
import requests

DEXSCREENER_PROFILES_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
DEXSCREENER_TOKENS_URL = "https://api.dexscreener.com/tokens/v1/{chain}/{address}"
GOPLUS_TOKEN_SECURITY_URL = "https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
COINGECKO_SEARCH_URL = "https://api.coingecko.com/api/v3/search"
COINGECKO_CHART_URL = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"
COINGECKO_COIN_URL = "https://api.coingecko.com/api/v3/coins/{id}"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"
FEAR_GREED_URL = "https://api.alternative.me/fng/"
FRANKFURTER_URL = "https://api.frankfurter.app"
ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"

# 链名 -> GoPlus 需要的数字 chain_id（覆盖常见 EVM 链）
GOPLUS_CHAIN_MAP = {
    "ethereum": "1",
    "bsc": "56",
    "base": "8453",
    "arbitrum": "42161",
    "polygon": "137",
}

# CoinGecko 的 platform 字段命名 -> 我们统一使用的链名
CG_PLATFORM_MAP = {
    "ethereum": "ethereum",
    "binance-smart-chain": "bsc",
    "base": "base",
    "arbitrum-one": "arbitrum",
    "polygon-pos": "polygon",
}


# ========== 市场概览：大盘温度计 ==========

def get_market_overview():
    """BTC 市占率 + 恐慌贪婪指数，帮你快速判断当前是普涨普跌还是分化行情"""
    btc_dominance = None
    try:
        resp = requests.get(COINGECKO_GLOBAL_URL, timeout=15)
        resp.raise_for_status()
        btc_dominance = resp.json()["data"]["market_cap_percentage"].get("btc")
    except Exception:
        pass

    fng_value, fng_label = None, None
    try:
        resp = requests.get(FEAR_GREED_URL, params={"limit": 1}, timeout=15)
        resp.raise_for_status()
        item = resp.json()["data"][0]
        fng_value, fng_label = int(item["value"]), item["value_classification"]
    except Exception:
        pass

    return {"btc_dominance": btc_dominance, "fng_value": fng_value, "fng_label": fng_label}


# ========== 币种 id 解析（解决 sui / xrp 这类输错id查不到数据的问题）==========

def resolve_coin_id(query):
    """把用户输入的代号/名称/id 模糊匹配成 CoinGecko 标准 id
    例如输入 'xrp' 会被匹配成 'ripple'，输入 'sui' 会匹配成 'sui'
    找不到返回 None
    """
    q = query.strip().lower()
    try:
        resp = requests.get(COINGECKO_SEARCH_URL, params={"query": q}, timeout=15)
        resp.raise_for_status()
        coins = resp.json().get("coins", [])
    except Exception:
        return None

    if not coins:
        return None

    # 优先精确匹配 id 或代号(symbol)
    for c in coins:
        if c.get("id", "").lower() == q or c.get("symbol", "").lower() == q:
            return c["id"]

    # 否则取市值排名最靠前的候选，避免匹配到同名的小众山寨币
    ranked = [c for c in coins if c.get("market_cap_rank")]
    if ranked:
        return min(ranked, key=lambda c: c["market_cap_rank"])["id"]
    return coins[0]["id"]


def fetch_coin_platforms(coin_id):
    """查这个币在各条链上的合约地址，用于后续查持仓集中度"""
    url = COINGECKO_COIN_URL.format(id=coin_id)
    params = {"localization": "false", "tickers": "false", "market_data": "false",
              "community_data": "false", "developer_data": "false", "sparkline": "false"}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("platforms", {}) or {}
    except Exception:
        return {}


# ========== 关注币种：状态与买卖提示 ==========

def fetch_market_chart(coin_id, days=90):
    """拉取历史日线价格，用于计算 RSI / 均线。days=90 保证拿到的是按天粒度的数据"""
    url = COINGECKO_CHART_URL.format(id=coin_id)
    params = {"vs_currency": "usd", "days": days}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return [p[1] for p in data.get("prices", [])]


def compute_rsi(prices, period=14):
    """标准 RSI 计算（简单移动平均版本），prices 至少要有 period+1 个点"""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_ma(prices, window):
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window


def get_concentration_info(chain, address):
    """用 GoPlus 查持仓集中度（前10大地址占比、持有人数），作为"巨鲸集中度"信号
    只覆盖常见 EVM 链，其余链返回 None"""
    chain_id = GOPLUS_CHAIN_MAP.get(chain)
    if not chain_id:
        return None

    url = GOPLUS_TOKEN_SECURITY_URL.format(chain_id=chain_id)
    try:
        resp = requests.get(url, params={"contract_addresses": address}, timeout=15)
        resp.raise_for_status()
        info = resp.json().get("result", {}).get(address.lower(), {})
    except Exception:
        return None

    if not info:
        return None

    holders = info.get("holders", []) or []
    try:
        top10_pct = sum(float(h.get("percent", 0)) for h in holders[:10]) * 100
    except Exception:
        top10_pct = None

    return {
        "chain": chain,
        "address": address,
        "holder_count": info.get("holder_count"),
        "top10_pct": top10_pct,
    }


def get_watchlist_whale_info(coin_id):
    """给关注币种查一下主流 EVM 链上的合约地址，再查持仓集中度
    比特币这类原生资产、以及 Solana/XRP Ledger 等非 EVM 链暂不支持，返回 None"""
    platforms = fetch_coin_platforms(coin_id)
    for cg_key, chain in CG_PLATFORM_MAP.items():
        address = platforms.get(cg_key)
        if address:
            info = get_concentration_info(chain, address)
            if info:
                return info
    return None


def compute_signal(prices, extra_rules=True):
    """给定一段按时间正序排列的价格序列（最后一个视为"当前"价格），
    计算 RSI/均线打分，返回 dict。这是关注币种实时分析和历史回测共用的核心打分逻辑，
    保证"现在看到的提示"和"回测验证的规则"是同一套代码，不会两边逻辑不一致"""
    if len(prices) < 15:
        return None

    current_price = prices[-1]
    change_24h = (prices[-1] - prices[-2]) / prices[-2] * 100 if len(prices) >= 2 else 0
    change_7d = (prices[-1] - prices[-8]) / prices[-8] * 100 if len(prices) >= 8 else None

    rsi = compute_rsi(prices, period=14)
    ma7 = compute_ma(prices, 7)
    ma25 = compute_ma(prices, 25) if len(prices) >= 25 else None

    score = 0
    reasons = []

    if rsi is not None:
        if rsi < 30:
            score += 2
            reasons.append(f"RSI(14)={rsi:.0f}，超卖区间")
        elif rsi > 70:
            score -= 2
            reasons.append(f"RSI(14)={rsi:.0f}，超买区间")
        else:
            reasons.append(f"RSI(14)={rsi:.0f}，中性")

    if ma7 is not None and ma25 is not None:
        if current_price > ma7 > ma25:
            score += 1
            reasons.append("现价>MA7>MA25，多头排列")
        elif current_price < ma7 < ma25:
            score -= 1
            reasons.append("现价<MA7<MA25，空头排列")
        else:
            reasons.append("均线尚未形成明显排列")

    if extra_rules:
        if change_24h >= 15:
            score -= 1
            reasons.append(f"24h涨{change_24h:+.0f}%，追高风险上升")
        if change_7d is not None and change_7d <= -20 and rsi is not None and rsi < 40:
            score += 1
            reasons.append(f"7d跌{change_7d:+.0f}%且RSI偏低，或超跌企稳")

    if score >= 3:
        label, level = "🟢 关注买入区", "buy"
    elif score >= 1:
        label, level = "🟡 偏多可关注", "watch_buy"
    elif score <= -3:
        label, level = "🔴 关注卖出/止盈", "sell"
    elif score <= -1:
        label, level = "🟠 偏空注意风险", "watch_sell"
    else:
        label, level = "⚪ 中性观望", "neutral"

    return {
        "price": current_price, "change_24h": change_24h, "change_7d": change_7d,
        "rsi": rsi, "ma7": ma7, "ma25": ma25, "score": score, "label": label, "level": level,
        "reasons": reasons,
    }


def analyze_coin(raw_query):
    """综合价格、24h/7d涨跌、RSI、均线，给出一个状态提示 + 理由列表
    这是基于常见技术指标的规则打分，不是预测，仅作为你自己判断时的参考"""
    coin_id = resolve_coin_id(raw_query)
    if not coin_id:
        return {"coin": raw_query, "error": "找不到这个币种，换成官方英文名或代号再试一次"}

    prices_daily = fetch_market_chart(coin_id, days=90)
    sig = compute_signal(prices_daily)
    if sig is None:
        return {"coin": coin_id, "error": "历史数据不足，暂时无法分析"}

    sig["coin"] = coin_id
    sig["query"] = raw_query
    return sig


def analyze_watchlist(coin_ids, include_whale=False):
    results = []
    for coin_id in coin_ids:
        try:
            r = analyze_coin(coin_id)
            if include_whale and "error" not in r:
                r["whale"] = get_watchlist_whale_info(r["coin"])
        except Exception as e:
            r = {"coin": coin_id, "error": f"获取数据失败: {e}"}
        results.append(r)
        time.sleep(0.3)  # 避免请求过快被限流
    return results


# ========== 外汇货币对：状态与买卖提示 ==========

def fetch_forex_history(pair, days=100):
    """pair 格式如 'USD/JPY'，返回按日期排序的历史汇率列表
    数据源 ECB（欧洲央行），只有工作日数据，节假日/周末没有更新"""
    base, quote = [x.strip().upper() for x in pair.split("/")]
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    url = f"{FRANKFURTER_URL}/{start.isoformat()}..{end.isoformat()}"
    resp = requests.get(url, params={"from": base, "to": quote}, timeout=15)
    resp.raise_for_status()
    rates = resp.json().get("rates", {})
    sorted_dates = sorted(rates.keys())
    return [rates[d][quote] for d in sorted_dates if quote in rates[d]]


def analyze_forex_pair(pair):
    """外汇版的状态打分，跟加密货币共用同一套 RSI/均线打分逻辑
    （extra_rules=False，因为"24h暴涨追高"这类规则是为加密货币的高波动设计的，
    外汇日内波动通常远小于1%，套用同样阈值基本不会触发，意义不大）"""
    try:
        prices = fetch_forex_history(pair, days=100)
    except Exception as e:
        return {"coin": pair, "error": f"格式需要是 '美元/日元' 这种写法，如 USD/JPY（{e}）"}

    sig = compute_signal(prices, extra_rules=False)
    if sig is None:
        return {"coin": pair, "error": "历史数据不足（可能是货币代码写错，或者ECB不覆盖这个货币）"}

    sig["coin"] = pair.upper()
    return sig


def analyze_forex_watchlist(pairs):
    results = []
    for pair in pairs:
        try:
            results.append(analyze_forex_pair(pair))
        except Exception as e:
            results.append({"coin": pair, "error": f"获取数据失败: {e}"})
        time.sleep(0.2)
    return results


# ========== 历史信号回测：验证现在这套打分逻辑过去到底准不准 ==========

def backtest_signal(prices, forward_days=7, extra_rules=True):
    """把 compute_signal 应用到历史每一天，跟"forward_days天后"的真实涨跌做比对
    返回按信号等级(buy/watch_buy/neutral/watch_sell/sell)分组的胜率统计
    这是真实历史数据回放出来的结果，不是编的数字"""
    min_window = 25  # 至少要能算出MA25才开始回放
    if len(prices) < min_window + forward_days + 1:
        return None

    records = []
    for t in range(min_window, len(prices) - forward_days):
        window = prices[: t + 1]
        sig = compute_signal(window, extra_rules=extra_rules)
        if not sig:
            continue
        entry_price = prices[t]
        exit_price = prices[t + forward_days]
        fwd_return = (exit_price - entry_price) / entry_price * 100
        records.append({"level": sig["level"], "fwd_return": fwd_return})

    if not records:
        return None

    order = {"buy": 0, "watch_buy": 1, "neutral": 2, "watch_sell": 3, "sell": 4}
    level_label = {
        "buy": "🟢 关注买入区", "watch_buy": "🟡 偏多可关注", "neutral": "⚪ 中性观望",
        "watch_sell": "🟠 偏空注意风险", "sell": "🔴 关注卖出/止盈",
    }

    groups = {}
    for r in records:
        groups.setdefault(r["level"], []).append(r["fwd_return"])

    summary = []
    for level, rets in groups.items():
        win_rate = sum(1 for x in rets if x > 0) / len(rets) * 100
        avg_ret = sum(rets) / len(rets)
        summary.append({
            "level": level, "label": level_label.get(level, level),
            "count": len(rets), "win_rate": win_rate, "avg_return": avg_ret,
        })
    summary.sort(key=lambda s: order.get(s["level"], 9))

    return {"total_samples": len(records), "summary": summary}


def backtest_coin(raw_query, forward_days=7, days=365):
    coin_id = resolve_coin_id(raw_query)
    if not coin_id:
        return {"coin": raw_query, "error": "找不到这个币种"}
    try:
        prices = fetch_market_chart(coin_id, days=days)
    except Exception as e:
        return {"coin": coin_id, "error": f"获取历史数据失败: {e}"}

    result = backtest_signal(prices, forward_days=forward_days, extra_rules=True)
    if result is None:
        return {"coin": coin_id, "error": "历史数据不足，无法回测（换一个市值更高、上线更久的币种试试）"}

    result["coin"] = coin_id
    result["forward_days"] = forward_days
    return result


def backtest_forex(pair, forward_days=7, days=365):
    try:
        prices = fetch_forex_history(pair, days=days)
    except Exception as e:
        return {"coin": pair, "error": f"获取历史数据失败: {e}"}

    result = backtest_signal(prices, forward_days=forward_days, extra_rules=False)
    if result is None:
        return {"coin": pair, "error": "历史数据不足，无法回测"}

    result["coin"] = pair.upper()
    result["forward_days"] = forward_days
    return result


# ========== 每日报告：把当前所有数据汇总成一份文字摘要 ==========
# 完全由规则拼接生成，不调用任何AI模型，免费、确定性、不会"编造"内容

def generate_daily_report(watchlist_results, forex_results, new_coin_candidates, overview):
    today = datetime.date.today().strftime("%Y年%m月%d日")
    lines = [f"### 📅 {today} 市场速览\n"]

    if overview.get("fng_value") is not None:
        lines.append(f"**市场情绪**：恐慌贪婪指数 {overview['fng_value']}（{overview['fng_label']}）")
    if overview.get("btc_dominance") is not None:
        lines.append(f"**BTC市占率**：{overview['btc_dominance']:.1f}%")

    def group_by_bias(results):
        bullish = [r for r in results if not r.get("error") and r.get("level") in ("buy", "watch_buy")]
        bearish = [r for r in results if not r.get("error") and r.get("level") in ("sell", "watch_sell")]
        return bullish, bearish

    crypto_bull, crypto_bear = group_by_bias(watchlist_results or [])
    if crypto_bull:
        names = "、".join(f"{r['coin'].upper()}({r['label']})" for r in crypto_bull)
        lines.append(f"\n**加密货币偏多**：{names}")
    if crypto_bear:
        names = "、".join(f"{r['coin'].upper()}({r['label']})" for r in crypto_bear)
        lines.append(f"\n**加密货币偏空**：{names}")
    if not crypto_bull and not crypto_bear and watchlist_results:
        lines.append("\n**加密货币关注列表**：暂无明显偏多或偏空信号，整体中性")

    fx_bull, fx_bear = group_by_bias(forex_results or [])
    if fx_bull:
        names = "、".join(f"{r['coin']}({r['label']})" for r in fx_bull)
        lines.append(f"\n**外汇偏多**：{names}")
    if fx_bear:
        names = "、".join(f"{r['coin']}({r['label']})" for r in fx_bear)
        lines.append(f"\n**外汇偏空**：{names}")

    if new_coin_candidates:
        top = new_coin_candidates[:3]
        names = "、".join(f"{c['symbol']}({c['chain']}, 评分{c['score']:.0f})" for c in top)
        lines.append(f"\n**新币扫描Top{len(top)}**：{names}")

    lines.append(
        "\n\n⚠️ 以上内容由规则自动拼接生成，只是把当前已获取的数据结构化摘要，"
        "不涉及额外判断也不构成投资建议，仅供你快速浏览全貌"
    )
    return "\n".join(lines)


# ========== 新币动量扫描 ==========

def get_new_token_profiles(chains):
    resp = requests.get(DEXSCREENER_PROFILES_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return [t for t in data if t.get("chainId") in chains]


def get_pair_data(chain, address):
    url = DEXSCREENER_TOKENS_URL.format(chain=chain, address=address)
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return None
    pairs = resp.json()
    if not pairs:
        return None
    return max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))


def check_safety(chain, address):
    chain_id = GOPLUS_CHAIN_MAP.get(chain)
    if not chain_id:
        return True, "该链暂不支持自动安全检测，请手动检查"

    url = GOPLUS_TOKEN_SECURITY_URL.format(chain_id=chain_id)
    try:
        resp = requests.get(url, params={"contract_addresses": address}, timeout=15)
        resp.raise_for_status()
        info = resp.json().get("result", {}).get(address.lower(), {})
    except Exception as e:
        return True, f"安全检测请求失败({e})，请手动确认"

    if not info:
        return True, "未查到安全数据，请手动确认"

    flags = []
    if info.get("is_honeypot") == "1":
        flags.append("疑似蜜罐")
    if info.get("is_mintable") == "1":
        flags.append("合约可增发")
    if info.get("cannot_sell_all") == "1":
        flags.append("无法全部卖出")
    if info.get("is_blacklisted") == "1":
        flags.append("存在黑名单机制")
    if info.get("hidden_owner") == "1":
        flags.append("隐藏所有者权限")

    return (False, "；".join(flags)) if flags else (True, "未发现明显风险信号（仍需自行判断）")


def build_background_summary(chain, symbol, description, links, pair):
    """给新币拼一份背景+投资价值参考卡片：项目简介、社交链接是否齐全、
    资金/交易结构的几个客观指标。不是投资建议，只是把公开信息结构化展示"""
    txns_h24 = (pair.get("txns") or {}).get("h24", {})
    buys, sells = txns_h24.get("buys", 0), txns_h24.get("sells", 0)
    buy_sell_ratio = buys / sells if sells else None

    fdv = pair.get("fdv")
    liquidity = (pair.get("liquidity") or {}).get("usd", 0)
    fdv_liq_ratio = fdv / liquidity if fdv and liquidity else None

    link_types = {l.get("type") or l.get("label", "").lower() for l in (links or [])}
    has_website = any("website" in str(t).lower() or "site" in str(t).lower() for t in link_types) or bool(links)
    has_twitter = any("twitter" in str(t).lower() or "x" in str(t).lower() for t in link_types)

    notes = []
    if buy_sell_ratio is not None:
        if buy_sell_ratio >= 1.5:
            notes.append(f"24h买单/卖单比 {buy_sell_ratio:.1f}，买方力量偏强")
        elif buy_sell_ratio <= 0.7:
            notes.append(f"24h买单/卖单比 {buy_sell_ratio:.1f}，卖方力量偏强")
        else:
            notes.append(f"24h买单/卖单比 {buy_sell_ratio:.1f}，买卖相对均衡")

    if fdv_liq_ratio is not None:
        if fdv_liq_ratio > 50:
            notes.append(f"完全稀释估值/流动性 = {fdv_liq_ratio:.0f}倍，估值相对流动性偏高，抛压/滑点风险较大")
        else:
            notes.append(f"完全稀释估值/流动性 = {fdv_liq_ratio:.0f}倍，处于相对合理区间")

    if not links:
        notes.append("未查到官网/社交媒体链接，项目透明度存疑，建议谨慎")
    else:
        notes.append(f"{'已' if has_website else '未'}提供官网，{'已' if has_twitter else '未'}提供推特/X")

    return {
        "description": description or "暂无项目方提供的简介",
        "links": links or [],
        "buy_sell_ratio": buy_sell_ratio,
        "fdv_liq_ratio": fdv_liq_ratio,
        "notes": notes,
    }


def scan_new_coins(chains, min_liquidity, min_volume_24h, min_change_1h, check_security=True, with_background=True):
    candidates = []
    for p in get_new_token_profiles(chains):
        chain, address = p.get("chainId"), p.get("tokenAddress")
        if not chain or not address:
            continue

        pair = get_pair_data(chain, address)
        time.sleep(0.2)
        if not pair:
            continue

        liquidity = (pair.get("liquidity") or {}).get("usd", 0)
        volume_24h = (pair.get("volume") or {}).get("h24", 0)
        change_1h = (pair.get("priceChange") or {}).get("h1", 0)

        if liquidity < min_liquidity or volume_24h < min_volume_24h or change_1h < min_change_1h:
            continue

        safe, reason = check_safety(chain, address) if check_security else (None, "未检测")
        whale = get_concentration_info(chain, address)

        background = None
        buy_sell_ratio = None
        if with_background:
            background = build_background_summary(
                chain, pair.get("baseToken", {}).get("symbol", "?"),
                p.get("description"), p.get("links"), pair,
            )
            buy_sell_ratio = background.get("buy_sell_ratio")

        # 综合热度评分：涨幅 + 成交量相对流动性的换手强度 + 买卖力量，越高说明当前越强势
        # 三项分开算，UI里会把每一项拆开展示，不是一个说不清楚构成的黑箱数字
        turnover = volume_24h / liquidity if liquidity else 0
        change_score = change_1h
        turnover_score = min(turnover, 10) * 5
        buysell_score = (buy_sell_ratio - 1) * 10 if buy_sell_ratio else 0
        score = change_score + turnover_score + buysell_score
        score_breakdown = {
            "涨幅贡献": change_score, "换手强度贡献": turnover_score, "买卖力量贡献": buysell_score,
        }

        candidates.append({
            "chain": chain, "symbol": pair.get("baseToken", {}).get("symbol", "?"),
            "address": address, "price": pair.get("priceUsd"),
            "liquidity": liquidity, "volume_24h": volume_24h, "change_1h": change_1h,
            "market_cap": pair.get("marketCap"), "fdv": pair.get("fdv"),
            "safe": safe, "reason": reason, "url": pair.get("url"),
            "whale": whale, "background": background, "score": score, "score_breakdown": score_breakdown,
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(candidates, start=1):
        c["rank"] = i

    return candidates


# ========== 巨鲸钱包活动监控 ==========
# 这部分用 Etherscan V2 统一免费API，需要你自己申请一个免费 API Key（etherscan.io/myapikey）
# 只做"这个地址最近转入/转出了什么"的客观信息展示，不会自动判断"这是不是交易所"
# 或"这笔操作是买入还是卖出"——这类判断请结合区块浏览器链接自行核实，避免误导

def fetch_wallet_balance(chain, address, api_key):
    chain_id = GOPLUS_CHAIN_MAP.get(chain)
    if not chain_id or not api_key:
        return None
    params = {"chainid": chain_id, "module": "account", "action": "balance",
              "address": address, "tag": "latest", "apikey": api_key}
    try:
        resp = requests.get(ETHERSCAN_V2_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "1":
            return int(data["result"]) / 1e18
    except Exception:
        pass
    return None


def fetch_wallet_activity(chain, address, api_key, limit=30):
    """拉取这个地址最近的 ERC20 代币转账记录（进/出），作为"巨鲸最近在做什么"的活动流水"""
    chain_id = GOPLUS_CHAIN_MAP.get(chain)
    if not chain_id:
        return None, "该链暂不支持（目前仅支持以太坊/BSC/Base/Arbitrum/Polygon等EVM链）"
    if not api_key:
        return None, "需要先在左侧填入你自己的免费 Etherscan API Key"

    params = {"chainid": chain_id, "module": "account", "action": "tokentx",
              "address": address, "sort": "desc", "page": 1, "offset": limit, "apikey": api_key}
    try:
        resp = requests.get(ETHERSCAN_V2_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return None, f"请求失败: {e}"

    if data.get("status") != "1":
        return None, data.get("message", "未查到数据，请确认地址和API Key是否正确")

    results = []
    for tx in data.get("result", []):
        try:
            decimals = int(tx.get("tokenDecimal", 18))
            amount = int(tx["value"]) / (10 ** decimals)
        except Exception:
            continue

        is_in = tx.get("to", "").lower() == address.lower()
        ts = tx.get("timeStamp")
        time_str = datetime.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M UTC") if ts else "—"

        results.append({
            "time": time_str,
            "symbol": tx.get("tokenSymbol", "?"),
            "amount": amount,
            "direction": "转入" if is_in else "转出",
            "counterparty": tx.get("from") if is_in else tx.get("to"),
            "hash": tx.get("hash"),
            "chain": chain,
        })

    return results, None


def monitor_whale_wallets(wallets, api_key):
    """wallets: [{"chain": "ethereum", "address": "0x...", "label": "自定义备注名"}]"""
    results = []
    for w in wallets:
        chain, address = w["chain"], w["address"]
        balance = fetch_wallet_balance(chain, address, api_key)
        activity, error = fetch_wallet_activity(chain, address, api_key)
        results.append({
            "label": w.get("label") or address[:10] + "...",
            "chain": chain, "address": address,
            "native_balance": balance, "activity": activity, "error": error,
        })
        time.sleep(0.3)
    return results
