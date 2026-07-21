"""
核心数据逻辑 —— 被 streamlit_app.py（网页）和 alerts.py（定时推送）共用
不依赖任何本地 config.py，所有参数从外部传入，方便部署到云端
"""
import time
import datetime
import json
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
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"
BINANCE_FUTURES_DATA = "https://fapi.binance.com/futures/data"
# Binance 对美国地区的云服务器IP有地域限制（会返回451），Streamlit Cloud/Hugging Face等
# 免费平台大概率跑在美国的云机房，所以经常连不上Binance。Bybit 作为备用数据源，
# 通常对这类云服务器IP限制没那么严格
BYBIT_MARKET = "https://api.bybit.com/v5/market"
BYBIT_INTERVAL_MAP = {"15m": "15", "1h": "60", "1d": "D", "1w": "W"}
CONFIG_PATH = "user_config.json"

# 链名 -> GoPlus 需要的数字 chain_id（覆盖常见 EVM 链）
GOPLUS_CHAIN_MAP = {
    "ethereum": "1",
    "bsc": "56",
    "base": "8453",
    "arbitrum": "42161",
    "polygon": "137",
}

# 巨鲸监控里你手动填的链名，容错处理常见的大小写/别名写法，统一转换成上面这几个标准key
CHAIN_ALIASES = {
    "eth": "ethereum", "ethereum": "ethereum", "ether": "ethereum", "以太坊": "ethereum",
    "bsc": "bsc", "bnb": "bsc", "binance": "bsc", "bnbchain": "bsc", "bnb chain": "bsc", "币安智能链": "bsc",
    "base": "base",
    "arbitrum": "arbitrum", "arb": "arbitrum",
    "polygon": "polygon", "matic": "polygon", "pol": "polygon",
}


def normalize_chain_name(chain):
    """把你手动输入的链名（不管大小写、常见别名）统一转换成标准key，
    转换不了的原样返回小写形式，交给后面的判断逻辑处理"""
    key = (chain or "").strip().lower()
    return CHAIN_ALIASES.get(key, key)


# 知名做市商/机构地址预设，方便你一键添加到巨鲸监控列表，不用自己去找地址
# 【可信度说明】：Wintermute地址是你自己提供的；Jump Trading的两个地址来自Etherscan官方
# 公开标签（Etherscan Name Tags，相对可信但仍是第三方标注，不是100%官方认证）；
# 没有找到能确认的Cumberland具体地址，所以没有收录，建议你自己去Etherscan/Arkham核实后手动添加
PRESET_INSTITUTION_ADDRESSES = [
    {"label": "Wintermute", "chain": "ethereum", "address": "0xdbf5e9c520de273fc5996963770d460b31efbf16",
     "source": "用户提供"},
    {"label": "Jump Trading", "chain": "ethereum", "address": "0xf584f8728b874a6a5c7a8d4d387c9aae9172d621",
     "source": "Etherscan公开标签"},
    {"label": "Jump Trading 2", "chain": "ethereum", "address": "0x9507c04b10486547584c37bcbd931b2a4fee9a41",
     "source": "Etherscan公开标签"},
]

# CoinGecko 的 platform 字段命名 -> 我们统一使用的链名
CG_PLATFORM_MAP = {
    "ethereum": "ethereum",
    "binance-smart-chain": "bsc",
    "base": "base",
    "arbitrum-one": "arbitrum",
    "polygon-pos": "polygon",
}

# 常见代号 -> CoinGecko 标准 id 的静态对照表
# 覆盖这张表的币种，直接查表就能拿到id，不用消耗搜索接口的免费额度
# （CoinGecko 免费公开接口限速只有 5~15次/分钟，很容易被限流，这张表能省下一大半调用）
COMMON_TICKER_MAP = {
    "btc": "bitcoin", "eth": "ethereum", "xrp": "ripple", "sol": "solana", "sui": "sui",
    "bnb": "binancecoin", "ada": "cardano", "doge": "dogecoin", "dot": "polkadot",
    "matic": "matic-network", "pol": "polygon-ecosystem-token", "ltc": "litecoin",
    "trx": "tron", "link": "chainlink", "avax": "avalanche-2", "shib": "shiba-inu",
    "uni": "uniswap", "atom": "cosmos", "xlm": "stellar", "near": "near", "apt": "aptos",
    "arb": "arbitrum", "op": "optimism", "tia": "celestia", "inj": "injective-protocol",
    "pepe": "pepe", "wif": "dogwifcoin", "bch": "bitcoin-cash", "etc": "ethereum-classic",
    "fil": "filecoin", "icp": "internet-computer", "hbar": "hedera-hashgraph", "vet": "vechain",
    "render": "render-token", "imx": "immutable-x", "stx": "blockstack", "algo": "algorand",
    "fet": "fetch-ai", "sand": "the-sandbox", "mana": "decentraland", "aave": "aave",
    "mkr": "maker", "ldo": "lido-dao", "grt": "the-graph", "rune": "thorchain",
    "kas": "kaspa", "ftm": "fantom", "sei": "sei-network", "ton": "the-open-network",
    "usdt": "tether", "usdc": "usd-coin", "wbtc": "wrapped-bitcoin", "leo": "leo-token",
    "cro": "crypto-com-chain", "okb": "okb", "gt": "gatetoken",
}


def cg_params(extra, cg_api_key=None):
    """给CoinGecko请求拼参数，如果填了免费Demo Key就带上（稳定30次/分钟），
    不填的话用公开接口（只有5~15次/分钟，容易被限流）"""
    params = dict(extra)
    if cg_api_key:
        params["x_cg_demo_api_key"] = cg_api_key
    return params

# 2026年FOMC议息会议日期（美联储官网公布的固定日程，每年年初会公布下一年的完整日程）
# 到了2027年需要更新这个列表，我会到时候提醒你
FOMC_MEETINGS_2026 = [
    ("2026-01-27", "2026-01-28"),
    ("2026-03-17", "2026-03-18"),
    ("2026-04-28", "2026-04-29"),
    ("2026-06-16", "2026-06-17"),
    ("2026-07-28", "2026-07-29"),
    ("2026-09-15", "2026-09-16"),
    ("2026-10-27", "2026-10-28"),
    ("2026-12-08", "2026-12-09"),
]

# 2026年美国CPI公布日期（来源：美国劳工统计局BLS官方日程，https://www.bls.gov/schedule/news_release/cpi.htm）
# 到了2027年需要更新这个列表
CPI_DATES_2026 = [
    "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10",
    "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10",
]


def _first_friday(year, month):
    d = datetime.date(year, month, 1)
    offset = (4 - d.weekday()) % 7  # Monday=0 ... Friday=4
    return d + datetime.timedelta(days=offset)


def get_upcoming_macro_events(days_ahead=14):
    """近期可能大幅影响美联储利率预期、进而影响风险资产波动的重要事件：
    CPI通胀数据(高影响) / FOMC利率决议(高影响) / 非农就业数据(中等影响)
    非农是按"每月第一个周五"规则估算的，遇到节假日BLS可能顺延1天，仅供参考，
    以官方公布为准；CPI和FOMC日期来自官方公开日程，相对准确"""
    today = datetime.date.today()
    horizon = today + datetime.timedelta(days=days_ahead)
    events = []

    for date_str in CPI_DATES_2026:
        d = datetime.date.fromisoformat(date_str)
        if today <= d <= horizon:
            events.append({"date": d, "name": "美国CPI通胀数据公布", "importance": "high"})

    for start, end in FOMC_MEETINGS_2026:
        d = datetime.date.fromisoformat(end)
        if today <= d <= horizon:
            events.append({"date": d, "name": "美联储FOMC利率决议", "importance": "high"})

    for m_offset in range(0, 2):
        year = today.year + (today.month - 1 + m_offset) // 12
        month = (today.month - 1 + m_offset) % 12 + 1
        d = _first_friday(year, month)
        if today <= d <= horizon:
            events.append({"date": d, "name": "美国非农就业数据(NFP，日期为估算，节假日可能顺延1天)", "importance": "medium"})

    events.sort(key=lambda e: e["date"])
    for e in events:
        e["days_until"] = (e["date"] - today).days
    return events


def get_macro_risk_advisory(caution_days=3):
    """近期(caution_days天内)如果有高影响力事件，给一句"建议空仓观望"式的提醒
    不代表一定会大跌大涨，只是提醒你这几天数据/决议公布前后波动通常会放大，
    仓位控制和风险管理比平时更重要"""
    events = get_upcoming_macro_events(days_ahead=14)
    imminent = [e for e in events if e["importance"] == "high" and e["days_until"] <= caution_days]
    return {"events": events, "imminent": imminent}


# ========== 本地设置持久化：保存/读取你填入的Key、关注列表等 ==========
# 保存在部署环境自己的文件系统里，不会上传到 GitHub（.gitignore 已排除）
# 注意：Streamlit Cloud / Hugging Face Spaces 的免费额度下，只要应用不重新构建
# （没有push新代码、没有平台侧的重启清空），这个文件就会一直保留；
# 一旦重新构建（比如你更新了代码），文件会被清空，需要重新保存一次

def save_user_config(config: dict, path=CONFIG_PATH):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_user_config(path=CONFIG_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ========== 美联储利率 + 议息会议倒计时 ==========

def get_next_fomc_meeting(today=None):
    today = today or datetime.date.today()
    for start, end in FOMC_MEETINGS_2026:
        end_date = datetime.date.fromisoformat(end)
        if end_date >= today:
            start_date = datetime.date.fromisoformat(start)
            days_until = (start_date - today).days
            return {"start": start, "end": end, "days_until": max(days_until, 0)}
    return None  # 今年的会议都开完了，需要更新下一年的日程


def fetch_fed_funds_rate(fred_api_key=None):
    """联邦基金利率目标区间。填入免费的 FRED API Key（fred.stlouisfed.org/docs/api/api_key.html）
    可以拿到实时数据；不填就显示一份写死的静态快照并标注日期，可能不是最新的"""
    if not fred_api_key:
        return {"upper": 3.75, "lower": 3.50, "as_of": "2026-06-17（静态快照，填FRED Key可实时更新）", "live": False}

    def get_latest(series_id):
        params = {"series_id": series_id, "api_key": fred_api_key, "file_type": "json",
                   "sort_order": "desc", "limit": 1}
        resp = requests.get(FRED_URL, params=params, timeout=15)
        resp.raise_for_status()
        obs = resp.json()["observations"][0]
        return float(obs["value"]), obs["date"]

    try:
        upper, date_u = get_latest("DFEDTARU")
        lower, _ = get_latest("DFEDTARL")
        return {"upper": upper, "lower": lower, "as_of": date_u, "live": True}
    except Exception:
        return {"upper": 3.75, "lower": 3.50, "as_of": "获取失败，显示静态快照", "live": False}


def fetch_fed_rate_series(fred_api_key, limit=250):
    """拉取联邦基金利率目标上限的历史序列，按日期从新到旧排列"""
    params = {"series_id": "DFEDTARU", "api_key": fred_api_key, "file_type": "json",
              "sort_order": "desc", "limit": limit}
    resp = requests.get(FRED_URL, params=params, timeout=15)
    resp.raise_for_status()
    obs = resp.json()["observations"]
    return [(o["date"], float(o["value"])) for o in obs if o.get("value") not in (".", None)]


def get_rate_risk_signal(fred_api_key=None):
    """根据利率趋势（降息/加息/持平）给一个"风险市场偏多偏空"的参考框架
    这是宏观流动性层面的粗略经验规律，不是精确预测，具体行情还受很多其他因素影响"""
    if not fred_api_key:
        return {
            "available": False,
            "note": "填入FRED Key后可以看到基于利率趋势的实时参考信号；没填的时候先给你一个通用判断框架：",
            "framework": [
                "利率下行（降息周期）：融资成本降低、流动性转松，历史上通常对加密货币、成长股这类风险资产偏正面；"
                "但如果降息是因为经济数据明显走弱触发的'衰退式降息'，市场可能先跌后涨，不是看到降息就无脑做多",
                "利率上行（加息周期）：融资成本上升，市场风险偏好通常收缩，历史上对高波动资产压力较大",
                "利率持平：市场更多交易会议声明和点阵图释放的未来预期信号，而不是当前利率水平本身",
            ],
        }

    try:
        series = fetch_fed_rate_series(fred_api_key)
    except Exception as e:
        return {"available": False, "note": f"获取利率历史失败: {e}"}

    if len(series) < 2:
        return {"available": False, "note": "利率历史数据不足，暂时无法判断趋势"}

    latest_date, latest_rate = series[0]
    target_date = datetime.date.fromisoformat(latest_date) - datetime.timedelta(days=180)
    past_rate = next((r for d, r in series if datetime.date.fromisoformat(d) <= target_date), series[-1][1])

    diff = latest_rate - past_rate

    if diff <= -0.2:
        trend, bias = "降息周期", "偏多"
        reasons = [
            f"过去约180天利率从 {past_rate:.2f}% 降至 {latest_rate:.2f}%，处于降息周期",
            "融资成本下降、流动性转松，历史上通常对加密货币、成长股这类风险资产偏正面",
            "但需留意：如果这轮降息是被经济数据走弱推动的'衰退式降息'，市场可能先跌后涨，"
            "不能只看到降息就无脑做多，要结合当时的经济数据背景一起看",
        ]
    elif diff >= 0.2:
        trend, bias = "加息周期", "偏空"
        reasons = [
            f"过去约180天利率从 {past_rate:.2f}% 升至 {latest_rate:.2f}%，处于加息周期",
            "融资成本上升，市场风险偏好通常收缩，历史上对高波动的加密货币、成长股压力较大",
        ]
    else:
        trend, bias = "利率持平", "中性"
        reasons = [
            f"过去约180天利率维持在 {min(past_rate, latest_rate):.2f}%~{max(past_rate, latest_rate):.2f}% 区间，没有明显趋势",
            "这种阶段市场更多交易的是会议声明和未来预期信号（比如点阵图释放的降息/加息暗示），而不是当前利率水平本身",
        ]

    return {
        "available": True, "trend": trend, "bias": bias,
        "current_rate": latest_rate, "past_rate": past_rate, "reasons": reasons,
    }


def get_fed_overview(fred_api_key=None):
    return {
        "meeting": get_next_fomc_meeting(),
        "rate": fetch_fed_funds_rate(fred_api_key),
        "risk_signal": get_rate_risk_signal(fred_api_key),
    }


# ========== 市场概览：大盘温度计 ==========

def get_market_overview(cg_api_key=None):
    """BTC 市占率 + 恐慌贪婪指数，帮你快速判断当前是普涨普跌还是分化行情"""
    btc_dominance = None
    try:
        resp = requests.get(COINGECKO_GLOBAL_URL, params=cg_params({}, cg_api_key), timeout=15)
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

def resolve_coin_id(query, cg_api_key=None):
    """把用户输入的代号/名称/id 解析成 CoinGecko 标准 id
    例如输入 'xrp' 会被解析成 'ripple'，输入 'btc' 会解析成 'bitcoin'
    第一步先查静态对照表（不消耗API额度），查不到再调用搜索接口
    返回 (coin_id, error_message)，成功时 error_message 为 None
    """
    q = query.strip().lower()

    if q in COMMON_TICKER_MAP:
        return COMMON_TICKER_MAP[q], None

    coins, last_error = None, None
    for attempt in range(2):
        try:
            resp = requests.get(COINGECKO_SEARCH_URL, params=cg_params({"query": q}, cg_api_key), timeout=15)
            if resp.status_code == 429:
                last_error = "接口限流(429)"
                time.sleep(2)
                continue
            resp.raise_for_status()
            coins = resp.json().get("coins", [])
            last_error = None
            break
        except Exception as e:
            last_error = str(e)
            time.sleep(1.5)

    if coins is None:
        return None, (
            f"查询接口暂时不稳定（{last_error}），大概率是CoinGecko免费公开接口限速太严"
            "（只有5~15次/分钟），建议在侧边栏填一个免费的CoinGecko Demo API Key，或稍后重试"
        )

    if not coins:
        return None, "找不到这个币种，换成官方英文名/代号再试一次"

    for c in coins:
        if c.get("id", "").lower() == q or c.get("symbol", "").lower() == q:
            return c["id"], None

    ranked = [c for c in coins if c.get("market_cap_rank")]
    if ranked:
        return min(ranked, key=lambda c: c["market_cap_rank"])["id"], None
    return coins[0]["id"], None


def fetch_coin_platforms(coin_id, cg_api_key=None):
    """查这个币在各条链上的合约地址，用于后续查持仓集中度"""
    url = COINGECKO_COIN_URL.format(id=coin_id)
    params = cg_params({"localization": "false", "tickers": "false", "market_data": "false",
                         "community_data": "false", "developer_data": "false", "sparkline": "false"}, cg_api_key)
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("platforms", {}) or {}
    except Exception:
        return {}


# ========== 关注币种：状态与买卖提示 ==========

def fetch_market_chart(coin_id, days=90, cg_api_key=None):
    """拉取历史日线价格，用于计算 RSI / 均线。days=90 保证拿到的是按天粒度的数据"""
    url = COINGECKO_CHART_URL.format(id=coin_id)
    params = cg_params({"vs_currency": "usd", "days": days}, cg_api_key)
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


def compute_ema_series(prices, period):
    """指数移动平均的完整序列（不是只返回最新值），因为判断"金叉/死叉"
    需要比较最新值和前一个值，只算一个数字不够用"""
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    series = [sum(prices[:period]) / period]  # 用简单均线做种子
    for p in prices[period:]:
        series.append(p * k + series[-1] * (1 - k))
    return series


def compute_macd(prices, fast=12, slow=26, signal=9):
    """标准MACD：DIF(快慢EMA差) + DEA(DIF的EMA) + 柱状图(DIF-DEA)
    返回最新一期和上一期的柱状图数值，用来判断"由负转正"这种转折"""
    if len(prices) < slow + signal + 2:
        return None
    fast_series = compute_ema_series(prices, fast)
    slow_series = compute_ema_series(prices, slow)
    offset = len(fast_series) - len(slow_series)
    if offset < 0:
        return None
    dif_series = [f - s for f, s in zip(fast_series[offset:], slow_series)]
    if len(dif_series) < signal + 2:
        return None
    dea_series = compute_ema_series(dif_series, signal)
    dif_offset = len(dif_series) - len(dea_series)
    hist_series = [d - e for d, e in zip(dif_series[dif_offset:], dea_series)]
    if len(hist_series) < 2:
        return None
    return {"hist": hist_series[-1], "prev_hist": hist_series[-2], "dif": dif_series[-1], "dea": dea_series[-1]}


def detect_divergence(prices, lookback=14):
    """简化版RSI背离检测：
    价格创近期新低但RSI没有跟着创新低 -> 底背离(卖压减弱，可能反转向上)
    价格创近期新高但RSI没有跟着创新高 -> 顶背离(上涨动能减弱，可能反转向下)
    这是简化实现（用区间起止点比较，不是完整的波峰波谷算法），仅供参考"""
    if len(prices) < lookback + 15:
        return None

    price_then, price_now = prices[-lookback], prices[-1]
    rsi_then = compute_rsi(prices[: len(prices) - lookback + 1], 14)
    rsi_now = compute_rsi(prices, 14)
    if rsi_then is None or rsi_now is None:
        return None

    if price_now < price_then and rsi_now > rsi_then:
        return "bullish"
    if price_now > price_then and rsi_now < rsi_then:
        return "bearish"
    return None


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


def get_watchlist_whale_info(coin_id, cg_api_key=None):
    """给关注币种查一下主流 EVM 链上的合约地址，再查持仓集中度
    比特币这类原生资产、以及 Solana/XRP Ledger 等非 EVM 链暂不支持，返回 None"""
    platforms = fetch_coin_platforms(coin_id, cg_api_key)
    for cg_key, chain in CG_PLATFORM_MAP.items():
        address = platforms.get(cg_key)
        if address:
            info = get_concentration_info(chain, address)
            if info:
                return info
    return None


def compute_signal(prices, extra_rules=True):
    """给定一段按时间正序排列的价格序列（最后一个视为"当前"价格），
    综合 RSI、EMA20/60/120多周期结构、SMA20动能、MACD、RSI背离 做多因子打分。
    这是关注币种实时分析和历史回测共用的核心打分逻辑，保证"现在看到的提示"和
    "回测验证的规则"是同一套代码，不会两边逻辑不一致
    EMA参数用20/60/120（对应约1个月/3个月/6个月），而不是常见的20/50/200，
    是因为这套系统要在多个不同周期（15分钟/1小时/日线/周线）上统一复用同一套逻辑，
    20/60/120整数倍关系更整齐，各周期含义一致"""
    if len(prices) < 15:
        return None

    current_price = prices[-1]
    change_24h = (prices[-1] - prices[-2]) / prices[-2] * 100 if len(prices) >= 2 else 0
    change_7d = (prices[-1] - prices[-8]) / prices[-8] * 100 if len(prices) >= 8 else None

    rsi = compute_rsi(prices, period=14)
    ema20_series = compute_ema_series(prices, 20)
    ema60_series = compute_ema_series(prices, 60)
    ema120_series = compute_ema_series(prices, 120)
    ema20 = ema20_series[-1] if ema20_series else None
    ema60 = ema60_series[-1] if ema60_series else None
    ema120 = ema120_series[-1] if ema120_series else None
    sma20 = compute_ma(prices, 20)
    macd = compute_macd(prices)
    divergence = detect_divergence(prices)

    score = 0
    reasons = []

    def add_reason(text, direction=0):
        reasons.append({"text": text, "dir": direction})

    # RSI 水平
    if rsi is not None:
        if rsi < 30:
            score += 2
            add_reason(f"RSI(14)={rsi:.0f}，超卖区间", 1)
        elif rsi > 70:
            score -= 2
            add_reason(f"RSI(14)={rsi:.0f}，超买区间", -1)
        else:
            add_reason(f"RSI(14)={rsi:.0f}，中性", 0)

    # EMA20/60/120 多周期结构
    if ema20 is not None and ema60 is not None:
        if ema120 is not None:
            if current_price < ema120 and current_price > ema20 and ema20 > ema60:
                score += 2
                add_reason("现价<EMA120但现价>EMA20>EMA60，趋势末期恢复迹象", 1)
            elif current_price > ema120 and current_price > ema20 > ema60:
                score += 1
                add_reason("现价>EMA20>EMA60>EMA120，多头排列", 1)
            elif current_price < ema60 and ema20 < ema60:
                score -= 2
                add_reason("现价<EMA60且EMA20<EMA60，趋势转弱", -1)
            else:
                add_reason("EMA尚未形成明显多头或空头排列", 0)
        else:
            if current_price > ema20 > ema60:
                score += 1
                add_reason("现价>EMA20>EMA60，短中期偏多", 1)
            elif current_price < ema20 < ema60:
                score -= 1
                add_reason("现价<EMA20<EMA60，短中期偏空", -1)

    # SMA20 vs EMA20：判断近期动能是在加速还是减速
    # EMA对近期价格更敏感，EMA20明显高于SMA20说明最近涨得比前段时间更猛（加速）
    if ema20 is not None and sma20 is not None and sma20 != 0:
        gap_pct = (ema20 - sma20) / sma20 * 100
        if gap_pct > 0.3:
            score += 1
            add_reason(f"EMA20高于SMA20 {gap_pct:.1f}%，近期上涨动能在加速", 1)
        elif gap_pct < -0.3:
            score -= 1
            add_reason(f"EMA20低于SMA20 {abs(gap_pct):.1f}%，近期下跌动能在加速", -1)

    # MACD 柱状图转折
    if macd is not None:
        if macd["prev_hist"] <= 0 < macd["hist"]:
            score += 1
            add_reason("MACD柱状图由负转正，动能转强", 1)
        elif macd["prev_hist"] >= 0 > macd["hist"]:
            score -= 1
            add_reason("MACD柱状图由正转负，动能转弱", -1)
        elif macd["hist"] > 0 and macd["hist"] < macd["prev_hist"]:
            add_reason("MACD柱状图仍为正但在缩小，上涨动能减弱", 0)
        elif macd["hist"] < 0 and macd["hist"] > macd["prev_hist"]:
            add_reason("MACD柱状图仍为负但在收窄，下跌动能减弱", 0)

    # RSI 背离
    if divergence == "bullish":
        score += 2
        add_reason("价格创近期新低但RSI未跟随创新低，底背离信号", 1)
    elif divergence == "bearish":
        score -= 2
        add_reason("价格创近期新高但RSI未跟随创新高，顶背离信号", -1)

    if extra_rules:
        if change_24h >= 15:
            score -= 1
            add_reason(f"24h涨{change_24h:+.0f}%，追高风险上升", -1)
        if change_7d is not None and change_7d <= -20 and rsi is not None and rsi < 40:
            score += 1
            add_reason(f"7d跌{change_7d:+.0f}%且RSI偏低，或超跌企稳", 1)

    if score >= 5:
        label, level = "🟢 关注买入区", "buy"
    elif score >= 2:
        label, level = "🟡 偏多可关注", "watch_buy"
    elif score <= -5:
        label, level = "🔴 关注卖出/止盈", "sell"
    elif score <= -2:
        label, level = "🟠 偏空注意风险", "watch_sell"
    else:
        label, level = "⚪ 中性观望", "neutral"

    return {
        "price": current_price, "change_24h": change_24h, "change_7d": change_7d,
        "rsi": rsi, "ema20": ema20, "ema60": ema60, "ema120": ema120, "sma20": sma20,
        "macd_hist": macd["hist"] if macd else None, "divergence": divergence,
        "score": score, "label": label, "level": level, "reasons": reasons,
    }


# ========== 衍生品层：资金费率 + 未平仓合约 ==========
# 数据源 Binance 合约公开API，完全免费不需要key。这两个指标是加密货币独有的、
# 反映短期杠杆情绪是否过热的硬指标，参考了你贴的那份多因子系统文档里排第3、4优先级的建议

def guess_exchange_ticker(coin_id, raw_query):
    """从币种id或者你输入的原始文本猜一个交易所常用的代号（比如 bitcoin -> BTC）
    猜不出来就返回None，猜错了也没关系，后面请求会直接返回空结果，不会报错"""
    rev = {v: k for k, v in COMMON_TICKER_MAP.items()}
    if coin_id in rev:
        return rev[coin_id].upper()
    q = raw_query.strip().upper()
    if q.isalpha() and 2 <= len(q) <= 6:
        return q
    return None


def fetch_bybit_funding_rate(ticker):
    symbol = ticker.upper() + "USDT"
    try:
        resp = requests.get(f"{BYBIT_MARKET}/funding/history",
                             params={"category": "linear", "symbol": symbol, "limit": 1}, timeout=10)
        if resp.status_code != 200:
            return None
        rows = (resp.json().get("result") or {}).get("list") or []
        if not rows:
            return None
        return {"symbol": symbol, "funding_rate_pct": float(rows[0]["fundingRate"]) * 100, "mark_price": None}
    except Exception:
        return None


def fetch_funding_rate(ticker):
    """永续合约资金费率，正值代表多头付钱给空头（多头拥挤），负值反过来
    优先用Binance，连不上（比如被地域限制）就自动换Bybit"""
    symbol = ticker.upper() + "USDT"
    try:
        resp = requests.get(f"{BINANCE_FAPI}/premiumIndex", params={"symbol": symbol}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if "lastFundingRate" in data:
                return {
                    "symbol": symbol, "funding_rate_pct": float(data["lastFundingRate"]) * 100,
                    "mark_price": float(data.get("markPrice", 0)),
                }
    except Exception:
        pass
    return fetch_bybit_funding_rate(ticker)


def fetch_bybit_open_interest(ticker, days=7):
    symbol = ticker.upper() + "USDT"
    try:
        resp = requests.get(f"{BYBIT_MARKET}/open-interest",
                             params={"category": "linear", "symbol": symbol, "intervalTime": "1d", "limit": days},
                             timeout=10)
        if resp.status_code != 200:
            return None
        rows = (resp.json().get("result") or {}).get("list") or []
        if not rows:
            return None
        rows = list(reversed(rows))
        values = [float(r["openInterest"]) for r in rows]
        change_pct = (values[-1] - values[0]) / values[0] * 100 if values[0] else 0
        return {"symbol": symbol, "current": values[-1], "change_pct": change_pct, "days": len(values)}
    except Exception:
        return None


def fetch_open_interest_trend(ticker, days=7):
    """未平仓合约总价值近几天的变化趋势，优先Binance，连不上就换Bybit"""
    symbol = ticker.upper() + "USDT"
    try:
        resp = requests.get(f"{BINANCE_FUTURES_DATA}/openInterestHist",
                             params={"symbol": symbol, "period": "1d", "limit": days}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                values = [float(d["sumOpenInterestValue"]) for d in data]
                change_pct = (values[-1] - values[0]) / values[0] * 100 if values[0] else 0
                return {"symbol": symbol, "current": values[-1], "change_pct": change_pct, "days": len(values)}
    except Exception:
        pass
    return fetch_bybit_open_interest(ticker, days)


def analyze_derivatives(ticker, change_24h=None):
    """把资金费率和未平仓合约变化拼成一份"杠杆情绪"参考，只覆盖 Binance 合约有上架的币种
    （主要是主流币和有一定交易量的山寨币，很多小市值新币没有合约，会返回None）"""
    funding = fetch_funding_rate(ticker)
    oi = fetch_open_interest_trend(ticker)
    if funding is None and oi is None:
        return None

    reasons = []
    bias = "neutral"

    if funding is not None:
        fr = funding["funding_rate_pct"]
        if fr >= 0.05:
            reasons.append(f"资金费率 {fr:+.3f}%，多头拥挤、杠杆偏热，警惕挤仓回调")
            bias = "risk"
        elif fr <= -0.02:
            reasons.append(f"资金费率 {fr:+.3f}%，空头拥挤，存在挤空反弹的可能")
            bias = "risk"
        else:
            reasons.append(f"资金费率 {fr:+.3f}%，杠杆情绪相对健康")

    if oi is not None:
        oi_chg = oi["change_pct"]
        if abs(oi_chg) >= 15:
            direction = "上升" if oi_chg > 0 else "下降"
            reasons.append(f"未平仓合约近{oi['days']}天{direction}{abs(oi_chg):.1f}%，杠杆仓位变化明显")
        else:
            reasons.append(f"未平仓合约近{oi['days']}天变化{oi_chg:+.1f}%，杠杆仓位相对稳定")

    if funding is not None and oi is not None and change_24h is not None:
        fr, oi_chg = funding["funding_rate_pct"], oi["change_pct"]
        if change_24h > 5 and oi_chg > 10 and fr > 0.03:
            reasons.append("⚠️ 价格涨+持仓涨+费率涨三连击，历史上常是杠杆过热的最后一波，见顶风险上升")
            bias = "overheat"
        elif change_24h < -5 and oi_chg < -10 and fr < 0.01:
            reasons.append("💡 价格跌+持仓降+费率回落，可能是杠杆出清后的机会窗口，不一定是趋势破坏")
            bias = "washout"

    return {"funding": funding, "open_interest": oi, "bias": bias, "reasons": reasons}


# ========== 多周期共振：15分钟/1小时/日线/周线（加密），日/周/月（外汇）==========
# 核心思路：大周期定方向、小周期找时机。每个周期各自跑一遍compute_signal，
# 结果一致="共振"，可信度更高；结果打架="市场方向不明朗"，倾向观望
# 加密货币用 Binance 现货K线（免费，不需要key，能精确指定任意周期）

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


def test_exchange_connectivity():
    """诊断工具：直接测几个关键接口，把真实的HTTP状态码和返回内容显示出来，
    帮你判断到底是网络连不上、被地域限制(常见是451)、还是别的问题"""
    tests = [
        ("Binance 现货K线", "https://api.binance.com/api/v3/klines",
         {"symbol": "BTCUSDT", "interval": "1d", "limit": 5}),
        ("Binance 合约资金费率", "https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"}),
        ("Bybit K线", "https://api.bybit.com/v5/market/kline",
         {"category": "linear", "symbol": "BTCUSDT", "interval": "D", "limit": 5}),
        ("Bybit 资金费率", "https://api.bybit.com/v5/market/funding/history",
         {"category": "linear", "symbol": "BTCUSDT", "limit": 1}),
    ]
    results = []
    for name, url, params in tests:
        try:
            resp = requests.get(url, params=params, timeout=10)
            results.append({
                "name": name, "url": url, "status": resp.status_code,
                "ok": resp.status_code == 200, "snippet": resp.text[:300],
            })
        except Exception as e:
            results.append({"name": name, "url": url, "status": None, "ok": False, "snippet": f"请求异常: {e}"})
    return results


def fetch_bybit_klines(ticker, interval, limit=200):
    symbol = ticker.upper() + "USDT"
    bybit_interval = BYBIT_INTERVAL_MAP.get(interval)
    if not bybit_interval:
        return None
    try:
        resp = requests.get(f"{BYBIT_MARKET}/kline",
                             params={"category": "linear", "symbol": symbol, "interval": bybit_interval, "limit": limit},
                             timeout=10)
        if resp.status_code != 200:
            return None
        rows = (resp.json().get("result") or {}).get("list") or []
        if not rows:
            return None
        rows = list(reversed(rows))  # Bybit返回是从新到旧，反转成从旧到新
        closes = [float(r[4]) for r in rows]
        return {"closes": closes, "last_close_time_ms": int(rows[-1][0])}
    except Exception:
        return None


def fetch_binance_klines(ticker, interval, limit=300):
    """interval: 15m / 1h / 1d / 1w 等Binance支持的周期写法
    优先用Binance，连不上（比如被地域限制）就自动换Bybit（内部会转换成Bybit的周期写法）"""
    symbol = ticker.upper() + "USDT"
    try:
        resp = requests.get(BINANCE_KLINES_URL, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data and not isinstance(data, dict):  # 出错时Binance会返回一个带code字段的dict而不是列表
                closes = [float(k[4]) for k in data]
                return {"closes": closes, "last_close_time_ms": data[-1][6]}
    except Exception:
        pass
    return fetch_bybit_klines(ticker, interval, limit)


def resample_to_periods(daily_prices, period_days):
    """把日线序列往回每隔period_days天取一个点，粗略聚合成周线/月线
    （用来在没有分钟级外汇数据的情况下，从日线自己拼出周期结构，不用额外调接口）"""
    if period_days <= 1 or len(daily_prices) < period_days:
        return daily_prices
    reversed_prices = daily_prices[::-1]
    sampled = reversed_prices[::period_days]
    return sampled[::-1]


def compute_resonance(timeframe_results):
    """timeframe_results: {label: {"level":..., "weight":...} 或 None}
    综合多个周期的方向，判断是"共振"还是"打架" """
    def direction(level):
        if level in ("buy", "watch_buy"):
            return 1
        if level in ("sell", "watch_sell"):
            return -1
        return 0

    valid = {k: v for k, v in timeframe_results.items() if v}
    if not valid:
        return None

    dirs = [direction(v["level"]) for v in valid.values()]
    weighted_sum = sum(d * v["weight"] for d, v in zip(dirs, valid.values()))
    total_weight = sum(v["weight"] for v in valid.values())
    n = len(dirs)

    if all(d > 0 for d in dirs) and n >= 3:
        strength, desc = "strong_bull", f"{'🟢' * n} {n}个周期共振向上，信号强度高"
    elif all(d < 0 for d in dirs) and n >= 3:
        strength, desc = "strong_bear", f"{'🔴' * n} {n}个周期共振向下，信号强度高"
    elif total_weight and weighted_sum > total_weight * 0.4:
        strength, desc = "lean_bull", "🟡 多数周期偏多，但未完全共振，注意背离"
    elif total_weight and weighted_sum < -total_weight * 0.4:
        strength, desc = "lean_bear", "🟠 多数周期偏空，但未完全共振，注意背离"
    else:
        strength, desc = "mixed", "⚪ 各周期方向不一致，市场方向不明朗，建议观望"

    return {"strength": strength, "desc": desc, "weighted_sum": weighted_sum, "total_weight": total_weight}


def analyze_crypto_multi_timeframe(ticker):
    """周线(权重4,大趋势) / 日线(权重2,中期) / 1小时(权重1) / 15分钟(权重1,进场时机)"""
    tf_config = [("1w", "1w", 4, "周线·大趋势"), ("1d", "1d", 2, "日线·中期"),
                 ("1h", "1h", 1, "小时线·短期"), ("15m", "15m", 1, "15分钟·进场时机")]

    results = {}
    close_time_15m = None
    closes_15m = None
    for key, interval, weight, cn_label in tf_config:
        kl = fetch_binance_klines(ticker, interval, limit=200)
        if not kl or len(kl["closes"]) < 15:
            results[key] = None
            continue
        sig = compute_signal(kl["closes"], extra_rules=(interval in ("1d", "1w")))
        if sig is None:
            results[key] = None
            continue
        results[key] = {"level": sig["level"], "label": sig["label"], "score": sig["score"],
                         "weight": weight, "cn_label": cn_label}
        if key == "15m":
            close_time_15m = kl["last_close_time_ms"]
            closes_15m = kl["closes"]

    if not any(results.values()):
        return None

    resonance = compute_resonance(results)
    macro_level = (results.get("1w") or results.get("1d") or {}).get("level", "neutral") if (results.get("1w") or results.get("1d")) else "neutral"
    macro_bias = "bullish" if macro_level in ("buy", "watch_buy") else ("bearish" if macro_level in ("sell", "watch_sell") else "neutral")

    entry = find_entry_signal_15m(closes_15m, macro_bias) if macro_bias != "neutral" else None

    return {
        "timeframes": results, "resonance": resonance, "macro_bias": macro_bias,
        "entry": entry, "close_time_15m_ms": close_time_15m,
    }


def find_entry_signal_15m(prices, macro_bias):
    """在15分钟周期上找"顺大势"的精准进场点，只在macro_bias方向上找，不逆势用15分钟单独判断
    prices 直接复用外层已经拉取过的15分钟收盘价，不再重复请求Binance"""
    if not prices or len(prices) < 130:
        return None

    rsi_now = compute_rsi(prices, 14)
    rsi_prev = compute_rsi(prices[:-1], 14)
    ema20_series = compute_ema_series(prices, 20)
    ema20 = ema20_series[-1] if ema20_series else None
    macd = compute_macd(prices)
    current = prices[-1]

    reasons = []
    if macro_bias == "bullish":
        if ema20 and abs(current - ema20) / ema20 < 0.006 and prices[-1] >= prices[-2]:
            reasons.append("15分钟价格回踩EMA20附近后重新收高，顺大势逢低企稳")
        if rsi_now is not None and rsi_prev is not None and rsi_now < 40 and rsi_now > rsi_prev:
            reasons.append(f"15分钟RSI从{rsi_prev:.0f}回升至{rsi_now:.0f}，短期超卖修复")
        if macd and macd["prev_hist"] <= 0 < macd["hist"]:
            reasons.append("15分钟MACD柱状图由负转正，短期动能转强")
        action = "顺势逢低进场参考" if reasons else None
    else:  # bearish
        if ema20 and abs(current - ema20) / ema20 < 0.006 and prices[-1] <= prices[-2]:
            reasons.append("15分钟价格反弹至EMA20附近后重新回落，顺大势逢高承压")
        if rsi_now is not None and rsi_prev is not None and rsi_now > 60 and rsi_now < rsi_prev:
            reasons.append(f"15分钟RSI从{rsi_prev:.0f}回落至{rsi_now:.0f}，短期超买修复")
        if macd and macd["prev_hist"] >= 0 > macd["hist"]:
            reasons.append("15分钟MACD柱状图由正转负，短期动能转弱")
        action = "顺势减仓/止盈参考" if reasons else None

    return {"triggered": bool(reasons), "reasons": reasons, "action": action, "price": current}


def analyze_forex_multi_timeframe(pair):
    """月线(权重4,大趋势) / 周线(权重2,中期) / 日线(权重1,短期)
    没有免费的外汇分钟级数据，周线月线是从日线数据自己聚合出来的，不需要额外请求接口"""
    try:
        daily = fetch_forex_history(pair, days=800)
    except Exception:
        return None
    if len(daily) < 60:
        return None

    weekly = resample_to_periods(daily, 5)
    monthly = resample_to_periods(daily, 21)

    tf_config = [("1mo", monthly, 4, "月线·大趋势"), ("1w", weekly, 2, "周线·中期"), ("1d", daily, 1, "日线·短期")]
    results = {}
    for key, series, weight, cn_label in tf_config:
        sig = compute_signal(series, extra_rules=False) if len(series) >= 15 else None
        results[key] = {"level": sig["level"], "label": sig["label"], "score": sig["score"],
                         "weight": weight, "cn_label": cn_label} if sig else None

    if not any(results.values()):
        return None

    resonance = compute_resonance(results)
    return {"timeframes": results, "resonance": resonance}


def analyze_coin(raw_query, cg_api_key=None, include_derivatives=True, include_resonance=True):
    """综合价格、24h/7d涨跌、RSI、EMA、MACD、背离，给出一个状态提示 + 理由列表
    这是基于常见技术指标的规则打分，不是预测，仅作为你自己判断时的参考"""
    coin_id, err = resolve_coin_id(raw_query, cg_api_key)
    if not coin_id:
        return {"coin": raw_query, "error": err}

    prices_daily = fetch_market_chart(coin_id, days=365, cg_api_key=cg_api_key)
    sig = compute_signal(prices_daily)
    if sig is None:
        return {"coin": coin_id, "error": "历史数据不足，暂时无法分析"}

    sig["coin"] = coin_id
    sig["query"] = raw_query
    sig["display"] = raw_query.strip().upper()  # 显示用你输入的简写，而不是CoinGecko的全称id

    ticker = guess_exchange_ticker(coin_id, raw_query)

    sig["derivatives"] = None
    if include_derivatives and ticker:
        try:
            sig["derivatives"] = analyze_derivatives(ticker, sig.get("change_24h"))
        except Exception:
            sig["derivatives"] = None

    sig["resonance_data"] = None
    if include_resonance and ticker:
        try:
            sig["resonance_data"] = analyze_crypto_multi_timeframe(ticker)
        except Exception:
            sig["resonance_data"] = None

    return sig


def analyze_watchlist(coin_ids, include_whale=False, cg_api_key=None, include_derivatives=True, include_resonance=True):
    results = []
    for coin_id in coin_ids:
        try:
            r = analyze_coin(coin_id, cg_api_key, include_derivatives=include_derivatives, include_resonance=include_resonance)
            if include_whale and "error" not in r:
                r["whale"] = get_watchlist_whale_info(r["coin"], cg_api_key)
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


def analyze_forex_pair(pair, include_resonance=True):
    """外汇版的状态打分，跟加密货币共用同一套 RSI/均线打分逻辑
    （extra_rules=False，因为"24h暴涨追高"这类规则是为加密货币的高波动设计的，
    外汇日内波动通常远小于1%，套用同样阈值基本不会触发，意义不大）"""
    try:
        prices = fetch_forex_history(pair, days=300)
    except Exception as e:
        return {"coin": pair, "error": f"格式需要是 '美元/日元' 这种写法，如 USD/JPY（{e}）"}

    sig = compute_signal(prices, extra_rules=False)
    if sig is None:
        return {"coin": pair, "error": "历史数据不足（可能是货币代码写错，或者ECB不覆盖这个货币）"}

    sig["coin"] = pair.upper()
    sig["display"] = pair.strip().upper()

    sig["resonance_data"] = None
    if include_resonance:
        try:
            sig["resonance_data"] = analyze_forex_multi_timeframe(pair)
        except Exception:
            sig["resonance_data"] = None

    return sig


def analyze_forex_watchlist(pairs, include_resonance=True):
    results = []
    for pair in pairs:
        try:
            results.append(analyze_forex_pair(pair, include_resonance=include_resonance))
        except Exception as e:
            results.append({"coin": pair, "error": f"获取数据失败: {e}"})
        time.sleep(0.2)
    return results


# ========== 历史信号回测：验证现在这套打分逻辑过去到底准不准 ==========

def backtest_signal(prices, forward_days=7, extra_rules=True):
    """把 compute_signal 应用到历史每一天，跟"forward_days天后"的真实涨跌做比对
    返回按信号等级(buy/watch_buy/neutral/watch_sell/sell)分组的胜率统计
    这是真实历史数据回放出来的结果，不是编的数字"""
    min_window = 40  # 至少要能算出MACD(26+9)才开始回放，前面数据不够的天数直接跳过
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


def backtest_coin(raw_query, forward_days=7, days=365, cg_api_key=None):
    coin_id, err = resolve_coin_id(raw_query, cg_api_key)
    if not coin_id:
        return {"coin": raw_query, "error": err}
    try:
        prices = fetch_market_chart(coin_id, days=days, cg_api_key=cg_api_key)
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

def generate_daily_report(watchlist_results, forex_results, new_coin_candidates, overview, fed_overview=None):
    today = datetime.date.today().strftime("%Y年%m月%d日")
    lines = [f"### 📅 {today} 市场速览\n"]

    if overview.get("fng_value") is not None:
        lines.append(f"**市场情绪**：恐慌贪婪指数 {overview['fng_value']}（{overview['fng_label']}）")
    if overview.get("btc_dominance") is not None:
        lines.append(f"**BTC市占率**：{overview['btc_dominance']:.1f}%")

    if fed_overview:
        meeting = fed_overview.get("meeting")
        if meeting:
            lines.append(f"**距下次FOMC议息会议**：{meeting['days_until']}天（{meeting['start']}~{meeting['end']}）")
        risk_signal = fed_overview.get("risk_signal")
        if risk_signal and risk_signal.get("available"):
            lines.append(f"**利率驱动的风险市场信号**：{risk_signal['trend']}，{risk_signal['bias']}")

    macro = get_macro_risk_advisory(caution_days=3)
    if macro["imminent"]:
        names = "、".join(f"{e['name']}({e['days_until']}天后)" for e in macro["imminent"])
        lines.append(f"\n**🚨 近期临近重要宏观事件，建议空仓观望**：{names}")
    elif macro["events"]:
        names = "、".join(f"{e['name']}({e['days_until']}天后)" for e in macro["events"][:3])
        lines.append(f"\n**📅 近期重要宏观事件**：{names}")

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

    overheat = [r for r in (watchlist_results or []) if not r.get("error") and (r.get("derivatives") or {}).get("bias") == "overheat"]
    washout = [r for r in (watchlist_results or []) if not r.get("error") and (r.get("derivatives") or {}).get("bias") == "washout"]
    if overheat:
        names = "、".join(r["coin"].upper() for r in overheat)
        lines.append(f"\n**⚠️ 杠杆过热提醒**：{names} 出现价格+持仓+费率三连击，见顶风险上升")
    if washout:
        names = "、".join(r["coin"].upper() for r in washout)
        lines.append(f"\n**💡 杠杆出清提醒**：{names} 价格跌+持仓降+费率回落，可能是机会窗口")

    lines.append(
        "\n\n⚠️ 以上内容由规则自动拼接生成，只是把当前已获取的数据结构化摘要，"
        "不涉及额外判断也不构成投资建议，仅供你快速浏览全貌"
    )
    return "\n".join(lines)


# ========== 二级市场：当前强势、有叙事有背景的主流/中大市值项目 ==========
# 数据源 CoinGecko trending 接口（免费），这是CoinGecko根据全网搜索量实时算出来的
# "现在大家都在搜什么币"，跟新币扫描（DexScreener挖的是刚起步的微盘新币）是互补的两层：
# 这里覆盖的是已经有一定市值、正在被广泛关注、有明确叙事和项目背景的币种

COINGECKO_TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"


def fetch_trending_coins(cg_api_key=None):
    resp = requests.get(COINGECKO_TRENDING_URL, params=cg_params({}, cg_api_key), timeout=15)
    resp.raise_for_status()
    return [c["item"] for c in resp.json().get("coins", [])]


def fetch_coin_detail_summary(coin_id, cg_api_key=None):
    """拿项目简介、赛道分类(叙事)、市值排名等背景信息"""
    url = COINGECKO_COIN_URL.format(id=coin_id)
    params = cg_params({"localization": "false", "tickers": "false", "market_data": "true",
                         "community_data": "false", "developer_data": "false", "sparkline": "false"}, cg_api_key)
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    desc_raw = (data.get("description") or {}).get("en", "") or ""
    desc = desc_raw.split(". ")[0].strip()
    if desc and not desc.endswith("."):
        desc += "."
    desc = desc or "暂无项目方提供的英文简介"

    categories = [c for c in (data.get("categories") or []) if c]
    market = data.get("market_data") or {}

    return {
        "coin": coin_id, "name": data.get("name"), "symbol": (data.get("symbol") or "").upper(),
        "categories": categories, "description": desc,
        "price": (market.get("current_price") or {}).get("usd"),
        "change_24h": market.get("price_change_percentage_24h"),
        "change_7d": market.get("price_change_percentage_7d"),
        "market_cap": (market.get("market_cap") or {}).get("usd"),
        "market_cap_rank": data.get("market_cap_rank"),
    }


def scan_trending_secondary(cg_api_key=None, limit=7):
    """CoinGecko trending Top N，逐个拉背景信息拼成"二级市场强势+有叙事"的列表"""
    try:
        trending = fetch_trending_coins(cg_api_key)
    except Exception as e:
        return None, f"trending接口暂时不可用({e})，建议稍后重试"

    results = []
    for item in trending[:limit]:
        coin_id = item.get("id")
        if not coin_id:
            continue
        try:
            detail = fetch_coin_detail_summary(coin_id, cg_api_key)
        except Exception:
            continue
        detail["search_rank"] = item.get("score", 0) + 1  # CoinGecko原始score从0开始，+1显示更直观
        results.append(detail)
        time.sleep(0.3)

    if not results:
        return None, "暂时没拉到trending数据，建议稍后重试"
    return results, None


# ========== 一级市场：近期融资动态 ==========
# 数据源 DefiLlama 的公开融资数据（defillama.com/raises 页面背后的接口）。
# 老实说明：这个接口不在DefiLlama官方文档列出的正式API目录里，是页面本身在用的接口，
# 理论上公开可访问，但字段结构没有官方保证，如果哪天返回异常，会提示你去网页手动查看

DEFILLAMA_RAISES_URL = "https://api.llama.fi/raises"

# 一二线加密VC机构名单（不完整，只覆盖最常见的几家），命中会标注"知名机构参投"
TIER1_INVESTORS = {
    "a16z", "a16z crypto", "andreessen horowitz", "paradigm", "binance labs", "ybb capital",
    "coinbase ventures", "pantera capital", "sequoia capital", "multicoin capital",
    "polychain capital", "dragonfly", "dragonfly capital", "jump crypto", "framework ventures",
    "1kx", "variant fund", "electric capital", "hashkey capital", "okx ventures",
}


def fetch_primary_market_raises(days=30, top_n=15):
    """近N天的融资事件，优先展示有知名机构参投的、金额较大的"""
    try:
        resp = requests.get(DEFILLAMA_RAISES_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return None, f"一级市场融资数据源暂时不可用（{e}），建议直接去 https://defillama.com/raises 手动查看"

    raises = data.get("raises") if isinstance(data, dict) else data
    if not raises:
        return None, "暂时没有拉到融资数据，建议直接去 https://defillama.com/raises 手动查看"

    cutoff = time.time() - days * 86400
    results = []
    for r in raises:
        ts = r.get("date")
        if not ts or ts < cutoff:
            continue
        leads = [x for x in (r.get("leadInvestors") or []) if x]
        others = [x for x in (r.get("otherInvestors") or []) if x]
        tier1_hit = [x for x in (leads + others) if x.lower() in TIER1_INVESTORS]
        results.append({
            "name": r.get("name"), "date": datetime.date.fromtimestamp(ts).isoformat(),
            "amount": r.get("amount"), "round": r.get("round"), "category": r.get("category"),
            "chains": r.get("chains") or [], "lead_investors": leads, "other_investors": others,
            "tier1_hit": tier1_hit, "source": r.get("source"), "valuation": r.get("valuation"),
        })

    if not results:
        return None, f"最近{days}天没有查到新的融资记录，可以去 https://defillama.com/raises 看更早的历史"

    results.sort(key=lambda x: (len(x["tier1_hit"]) > 0, x["amount"] or 0), reverse=True)
    return results[:top_n], None


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
        return None, "该链暂不支持（目前仅支持 ethereum/bsc/base/arbitrum/polygon 这几条EVM链，Solana、比特币等非EVM链暂时做不了）"
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
        time_str = datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else "—"

        results.append({
            "time": time_str,
            "symbol": tx.get("tokenSymbol", "?"),
            "amount": amount,
            "direction": "转入" if is_in else "转出",
            "counterparty": tx.get("from") if is_in else tx.get("to"),
            "hash": tx.get("hash"),
            "chain": chain,
            "contract": tx.get("contractAddress", ""),
        })

    return results, None


# ========== 垃圾空投代币过滤 ==========
# 公开地址（尤其是名人、机构地址）每天会收到大量恶意空投的仿冒代币（假USDT、钓鱼链接
# 伪装成代币名称等），这些噪音会把真正有意义的转账记录淹没，需要先过滤掉

SAFE_TOKEN_SYMBOLS = {
    "eth", "weth", "btc", "wbtc", "usdt", "usdc", "dai", "bnb", "wbnb", "matic",
    "sol", "arb", "op", "avax", "link", "uni", "aave", "mkr", "ldo", "pepe", "shib",
}

SPAM_TEXT_PATTERNS = [".com", ".io", ".net", ".xyz", ".org", "http", "www.", "claim", "visit", "airdrop", "reward", "$"]


def is_likely_spam_token(symbol, chain=None, contract=None):
    """判断一笔转账收到的代币是不是垃圾空投。两层过滤：
    1. 文本模式：仿冒代币的symbol经常带链接/诱导性文字（比如"Visit xxx.com to claim"），零成本，先过滤一遍
    2. 流动性检测：不在常见主流币白名单里的代币，去DexScreener查一下有没有真实交易对，
       完全查不到流动性的，大概率是空气/仿冒代币（这一步会消耗一次请求，只对陌生代币做）
    """
    sym = (symbol or "").strip().lower()
    if not sym:
        return True
    if sym in SAFE_TOKEN_SYMBOLS:
        return False
    if any(p in sym for p in SPAM_TEXT_PATTERNS):
        return True
    if len(symbol) > 20:  # 正常代号很少超过20个字符，经常是塞了一整句宣传语
        return True

    if chain and contract:
        try:
            pair = get_pair_data(chain, contract)
            if not pair or not (pair.get("liquidity") or {}).get("usd"):
                return True
        except Exception:
            pass  # 查询失败不算它是垃圾，避免误杀

    return False


def get_address_type(chain, address, api_key):
    """判断一个地址是普通钱包(EOA)还是合约地址，如果是已验证合约还能拿到合约名字
    这是从Etherscan查到的客观事实（不是猜的），后面用来辅助判断"这笔转账可能是什么类型的操作" """
    chain_id = GOPLUS_CHAIN_MAP.get(chain)
    if not chain_id or not api_key:
        return {"is_contract": None, "name": None}

    try:
        code_resp = requests.get(ETHERSCAN_V2_URL, params={
            "chainid": chain_id, "module": "proxy", "action": "eth_getCode",
            "address": address, "tag": "latest", "apikey": api_key,
        }, timeout=15).json()
        code = code_resp.get("result", "0x")
        is_contract = code not in ("0x", "0x0", "", None)
    except Exception:
        return {"is_contract": None, "name": None}

    name = None
    if is_contract:
        try:
            src_resp = requests.get(ETHERSCAN_V2_URL, params={
                "chainid": chain_id, "module": "contract", "action": "getsourcecode",
                "address": address, "apikey": api_key,
            }, timeout=15).json()
            result = (src_resp.get("result") or [{}])[0]
            name = result.get("ContractName") or None
        except Exception:
            pass

    return {"is_contract": is_contract, "name": name}


DEX_ROUTER_KEYWORDS = ("router", "swap", "aggregator", "1inch", "uniswap", "sushiswap",
                       "paraswap", "curve", "balancer", "kyber", "zeroex", "0x")


def build_whale_daily_report(chain, address, api_key, label="", known_addresses=None):
    """给某个巨鲸地址出一份"今天做了什么"的报告：
    1. 先过滤掉垃圾空投代币（仿冒币/无流动性代币），避免噪音淹没有意义的记录
    2. 按代币聚合今天的净流入/净流出（这是客观算出来的事实）
    3. 查一下今天主要交易对手方是合约还是普通钱包、合约叫什么名字（客观查到的事实）；
       如果对手方命中你自己维护的"已知交易所/机构地址库"，直接用你标记的名字，
       并结合转账方向判断"疑似充值到交易所"还是"疑似从交易所提现"
    4. 基于以上给几条解读思路（明确框定为"可能性/建议核实方向"，不是确定结论——
       链上数据本身不包含"意图"，任何"背后深意"的判断都需要你结合交易hash自行核实）
    """
    known_addresses = known_addresses or {}
    activity, error = fetch_wallet_activity(chain, address, api_key, limit=150)
    if error:
        return {"label": label, "address": address, "chain": chain, "error": error}

    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    today_txs_raw = [tx for tx in activity if tx["time"].startswith(today)]

    if not today_txs_raw:
        return {"label": label, "address": address, "chain": chain, "has_activity": False, "date": today}

    today_txs, spam_count = [], 0
    for tx in today_txs_raw:
        if is_likely_spam_token(tx["symbol"], tx.get("chain"), tx.get("contract")):
            spam_count += 1
            continue
        today_txs.append(tx)

    if not today_txs:
        return {
            "label": label, "address": address, "chain": chain, "has_activity": False,
            "date": today, "spam_filtered": spam_count,
        }

    token_flows = {}
    counterparties = {}
    for tx in today_txs:
        sym = tx["symbol"]
        signed_amt = tx["amount"] if tx["direction"] == "转入" else -tx["amount"]
        flow = token_flows.setdefault(sym, {"net": 0.0, "in_count": 0, "out_count": 0})
        flow["net"] += signed_amt
        flow["in_count" if tx["direction"] == "转入" else "out_count"] += 1
        counterparties.setdefault(tx["counterparty"], []).append(tx)

    known_lower = {k.lower(): v for k, v in known_addresses.items()}

    # 只查交易笔数最多的前5个对手方的地址类型，避免请求太多超出免费额度
    top_counterparties = sorted(counterparties.items(), key=lambda kv: len(kv[1]), reverse=True)[:5]
    hypothesis = []
    for cp_addr, txs in top_counterparties:
        n_tx = len(txs)
        short_addr = f"{cp_addr[:10]}...{cp_addr[-6:]}"
        directions = {t["direction"] for t in txs}

        known_label = known_lower.get(cp_addr.lower())
        if known_label:
            if directions == {"转出"}:
                note = f"今天{n_tx}笔转出到你标记的「{known_label}」，如果这是交易所地址，可能是充值准备卖出/操作"
            elif directions == {"转入"}:
                note = f"今天{n_tx}笔从你标记的「{known_label}」转入，如果这是交易所地址，可能是提现（囤币倾向）"
            else:
                note = f"今天跟你标记的「{known_label}」发生了{n_tx}笔往返转账"
            hypothesis.append({"counterparty": cp_addr, "short": short_addr, "tx_count": n_tx,
                                "type": "已知地址", "note": note})
            continue

        info = get_address_type(chain, cp_addr, api_key)
        time.sleep(0.2)
        if info.get("is_contract"):
            name = info.get("name") or "未在Etherscan验证的合约"
            if any(kw in name.lower() for kw in DEX_ROUTER_KEYWORDS):
                note = (f"对手方是「{name}」，从名字看疑似DEX路由/聚合器合约，发生了{n_tx}笔交易，"
                        f"大概率是在做链上swap（换币）；具体换成了什么、金额是否对等，建议点交易hash核实")
            else:
                note = (f"对手方是合约「{name}」，发生了{n_tx}笔交易，具体是什么操作建议点交易hash"
                        f"到区块浏览器核实调用的方法")
            hypothesis.append({"counterparty": cp_addr, "short": short_addr, "tx_count": n_tx,
                                "type": "合约", "note": note})
        elif info.get("is_contract") is False:
            hypothesis.append({
                "counterparty": cp_addr, "short": short_addr, "tx_count": n_tx, "type": "普通钱包",
                "note": f"对手方是普通钱包地址，发生了{n_tx}笔交易。更像是钱包间转账，可能是资金归集、"
                        f"分仓到多个地址，或者转给别人，链上数据本身看不出具体意图",
            })
        else:
            hypothesis.append({
                "counterparty": cp_addr, "short": short_addr, "tx_count": n_tx, "type": "未知",
                "note": "地址类型没查到，需要你自己去区块浏览器核实",
            })

    return {
        "label": label, "address": address, "chain": chain, "has_activity": True,
        "date": today, "tx_count": len(today_txs), "token_flows": token_flows,
        "hypothesis": hypothesis, "raw_txs": today_txs, "spam_filtered": spam_count,
    }


def monitor_whale_wallets(wallets, api_key, known_addresses=None):
    """wallets: [{"chain": "ethereum", "address": "0x...", "label": "自定义备注名"}]
    known_addresses: {"0x...": "Binance 14"} 这类你自己维护的已知交易所/机构地址库，
    用于识别转账对手方，不是我们瞎猜的
    给每个地址生成一份"今天做了什么"的报告"""
    results = []
    for w in wallets:
        chain, address, label = normalize_chain_name(w["chain"]), w["address"], w.get("label", "")
        balance = fetch_wallet_balance(chain, address, api_key)
        report = build_whale_daily_report(chain, address, api_key, label, known_addresses=known_addresses)
        report["native_balance"] = balance
        results.append(report)
        time.sleep(0.3)
    return results
