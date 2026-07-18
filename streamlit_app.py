"""
加密货币 & 外汇 投资监控看板
本地运行：streamlit run streamlit_app.py
云端部署：见 DEPLOY_GUIDE.md
"""
import streamlit as st
import core

st.set_page_config(page_title="投资监控看板", page_icon="📊", layout="wide")
st.title("📊 加密货币 & 外汇 投资监控看板")

LEVEL_COLOR = {
    "buy": "green", "watch_buy": "green",
    "sell": "red", "watch_sell": "orange",
    "neutral": "gray",
}

saved = core.load_user_config()


def render_watchlist_row(r, show_whale=False):
    if "error" in r:
        st.warning(f"**{r.get('query', r['coin'])}**：{r['error']}")
        return

    reason_line = "　".join(r["reasons"])
    change7 = f"7d {r['change_7d']:+.1f}%" if r.get("change_7d") is not None else ""

    whale_line = ""
    if show_whale:
        if r.get("whale"):
            w = r["whale"]
            if w.get("top10_pct") is not None:
                whale_line = f"　🐋前10持仓占比 {w['top10_pct']:.1f}%（持有人数 {w.get('holder_count', '—')}）"
        else:
            whale_line = "　🐋该链暂不支持集中度检测"

    st.markdown(
        f"**{r['coin'].upper()}**　`{r['price']:,.4f}`　"
        f"24h {r['change_24h']:+.1f}%　{change7}　:{LEVEL_COLOR.get(r['level'],'gray')}[{r['label']}]"
    )
    st.caption(f"理由：{reason_line}{whale_line}")
    st.divider()


# ---------- 顶部：市场概览 ----------
@st.cache_data(ttl=300)
def get_overview():
    return core.get_market_overview()

@st.cache_data(ttl=1800)
def get_fed_overview(fred_key):
    return core.get_fed_overview(fred_key)

ov = get_overview()
fed = get_fed_overview(saved.get("fred_key", ""))

oc1, oc2, oc3, oc4 = st.columns(4)
if ov.get("btc_dominance") is not None:
    oc1.metric("BTC 市占率", f"{ov['btc_dominance']:.1f}%")
if ov.get("fng_value") is not None:
    oc2.metric("恐慌贪婪指数", f"{ov['fng_value']}", ov.get("fng_label"))

rate = fed["rate"]
oc3.metric("联邦基金利率目标区间", f"{rate['lower']:.2f}%–{rate['upper']:.2f}%")
oc3.caption(f"数据日期 {rate['as_of']}" + ("" if rate["live"] else "　（未接入实时数据）"))

meeting = fed["meeting"]
if meeting:
    oc4.metric("距下次议息会议", f"{meeting['days_until']} 天", f"{meeting['start']} ~ {meeting['end']}")
else:
    oc4.warning("今年FOMC会议日程已用完，需要更新明年日程，告诉我一声我帮你更新")

st.caption("💡 恐慌区间历史上常伴随阶段性底部，贪婪区间需警惕追高风险；议息会议前后市场波动通常会放大，仅供参考")

risk_signal = fed["risk_signal"]
if risk_signal["available"]:
    bias_color = {"偏多": "green", "偏空": "red", "中性": "gray"}.get(risk_signal["bias"], "gray")
    st.markdown(f"**利率驱动的风险市场参考信号**：:{bias_color}[{risk_signal['trend']}，{risk_signal['bias']}]")
    for reason in risk_signal["reasons"]:
        st.caption(f"• {reason}")
else:
    st.markdown("**利率驱动的风险市场参考框架**")
    st.caption(risk_signal["note"])
    for line in risk_signal.get("framework", []):
        st.caption(f"• {line}")

st.divider()

with st.sidebar:
    st.header("⚙️ 参数设置")

    st.subheader("👀 关注加密货币")
    st.caption("每行一个，支持直接写代号/名称（如 xrp、sui），会自动识别")
    watchlist_text = st.text_area(
        "币种列表", value=saved.get("watchlist_text", "bitcoin\nethereum\nsolana\nxrp\nsui"),
        height=120, label_visibility="collapsed"
    )
    watchlist = [c.strip() for c in watchlist_text.splitlines() if c.strip()]
    show_whale_watchlist = st.checkbox("同时查持仓集中度(巨鲸信号)", value=saved.get("show_whale_watchlist", True),
                                        help="仅覆盖以太坊/BSC/Base/Arbitrum/Polygon 上的代币")

    st.divider()
    st.subheader("💱 关注外汇货币对")
    st.caption("每行一个，格式：基准货币/计价货币，如 USD/JPY")
    forex_text = st.text_area(
        "货币对列表", value=saved.get("forex_text", "USD/JPY\nEUR/USD\nGBP/USD"),
        height=100, label_visibility="collapsed"
    )
    forex_watchlist = [p.strip() for p in forex_text.splitlines() if p.strip()]

    st.divider()
    st.subheader("🚀 新币扫描阈值")
    min_liquidity = st.number_input("最低流动性(USD)", value=saved.get("min_liquidity", 30000), step=5000)
    min_volume = st.number_input("最低24h成交量(USD)", value=saved.get("min_volume", 100000), step=10000)
    min_change_1h = st.number_input("最低1h涨幅(%)", value=saved.get("min_change_1h", 20), step=5)
    chains = st.multiselect(
        "监控的链",
        ["solana", "ethereum", "base", "bsc", "arbitrum", "polygon"],
        default=saved.get("chains", ["solana", "ethereum", "base"]),
    )
    run_security_check = st.checkbox("安全检测(GoPlus)", value=saved.get("run_security_check", True))
    run_background = st.checkbox("生成背景与投资价值分析", value=saved.get("run_background", True))

    st.divider()
    st.subheader("🐋 巨鲸钱包监控")
    st.caption("需要免费的 Etherscan API Key：etherscan.io/myapikey")
    etherscan_key = st.text_input("Etherscan API Key", value=saved.get("etherscan_key", ""), type="password")
    st.caption("每行一个：链,地址,备注（备注可省略）")
    wallets_text = st.text_area(
        "监控地址", value=saved.get("wallets_text", ""), height=100, label_visibility="collapsed",
        placeholder="ethereum,0xAbC...,某巨鲸"
    )

    st.divider()
    st.subheader("🏦 美联储利率（可选）")
    st.caption("免费Key：fred.stlouisfed.org/docs/api/api_key.html，不填也能看会议倒计时，只是利率不实时")
    fred_key = st.text_input("FRED API Key", value=saved.get("fred_key", ""), type="password")

    st.divider()
    if st.button("💾 保存当前设置", type="primary", use_container_width=True):
        cfg = {
            "watchlist_text": watchlist_text, "forex_text": forex_text,
            "show_whale_watchlist": show_whale_watchlist,
            "min_liquidity": min_liquidity, "min_volume": min_volume, "min_change_1h": min_change_1h,
            "chains": chains, "run_security_check": run_security_check, "run_background": run_background,
            "etherscan_key": etherscan_key, "wallets_text": wallets_text, "fred_key": fred_key,
        }
        if core.save_user_config(cfg):
            st.success("已保存，下次打开会自动填充")
        else:
            st.error("保存失败（可能是部署环境没有写入权限），换个平台部署或者每次手动填一下")
    st.caption("⚠️ 保存在服务器本地文件里；如果你重新推送代码触发平台重新构建，需要重新保存一次")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["👀 加密货币关注", "💱 外汇关注", "🚀 新币动量扫描", "🐋 巨鲸监控", "📈 信号回测", "📰 每日报告"]
)

# ---------- Tab 1: 加密货币关注 ----------
with tab1:
    st.caption("基于 RSI、均线等技术指标做规则打分，仅供参考，不构成投资建议")

    if st.button("🔄 刷新分析", key="refresh_watchlist"):
        st.cache_data.clear()

    @st.cache_data(ttl=120)
    def get_watchlist_analysis(coin_ids, include_whale):
        return core.analyze_watchlist(coin_ids, include_whale=include_whale)

    if not watchlist:
        st.info("请在左侧输入你想关注的币种")
        watchlist_results = []
    else:
        with st.spinner("正在获取数据并计算指标..."):
            watchlist_results = get_watchlist_analysis(tuple(watchlist), show_whale_watchlist)
        for r in watchlist_results:
            render_watchlist_row(r, show_whale=show_whale_watchlist)


# ---------- Tab 2: 外汇关注 ----------
with tab2:
    st.caption(
        "数据源：欧洲央行(ECB)每日参考汇率，只有工作日数据；同样基于 RSI/均线打分，仅供参考"
    )

    if st.button("🔄 刷新分析", key="refresh_forex"):
        st.cache_data.clear()

    @st.cache_data(ttl=300)
    def get_forex_analysis(pairs):
        return core.analyze_forex_watchlist(pairs)

    if not forex_watchlist:
        st.info("请在左侧输入你想关注的货币对")
        forex_results = []
    else:
        with st.spinner("正在获取汇率数据并计算指标..."):
            forex_results = get_forex_analysis(tuple(forex_watchlist))
        for r in forex_results:
            render_watchlist_row(r, show_whale=False)


# ---------- Tab 3: 新币动量扫描 ----------
with tab3:
    st.caption("点击下方按钮开始扫描；结果按综合热度评分从高到低排序，评分构成会拆开显示，不是黑箱数字")

    if st.button("🔍 开始扫描新币", type="primary"):
        with st.spinner("正在扫描新币，请稍候..."):
            candidates = core.scan_new_coins(
                chains, min_liquidity, min_volume, min_change_1h,
                run_security_check, with_background=run_background,
            )
        st.session_state["candidates"] = candidates

    candidates = st.session_state.get("candidates", [])

    if not candidates:
        st.info("还没有扫描结果，点击上方按钮开始")
    else:
        st.success(f"发现 {len(candidates)} 个候选标的，按综合热度评分排序")
        for c in candidates:
            flag = "✅" if c["safe"] else ("🚫" if c["safe"] is False else "❔")
            with st.container(border=True):
                mc = f"　市值: ${c['market_cap']:,.0f}" if c.get("market_cap") else ""
                st.markdown(f"### #{c['rank']} {flag} {c['symbol']} ({c['chain']})　热度评分 {c['score']:.0f}")

                if c.get("score_breakdown"):
                    parts = "　".join(f"{k} {v:+.1f}" for k, v in c["score_breakdown"].items())
                    st.caption(f"评分构成：{parts}")

                st.write(f"价格: ${c['price']}　1h涨幅: {c['change_1h']:+.1f}%　流动性: ${c['liquidity']:,.0f}　24h量: ${c['volume_24h']:,.0f}{mc}")
                st.write(f"安全检测: {c['reason']}")

                if c.get("whale") and c["whale"].get("top10_pct") is not None:
                    w = c["whale"]
                    st.write(f"🐋 前10地址持仓占比: {w['top10_pct']:.1f}%　持有人数: {w.get('holder_count','—')}")

                if c.get("background"):
                    bg = c["background"]
                    st.markdown(f"**项目简介**：{bg['description']}")
                    if bg["links"]:
                        link_str = "　".join(
                            f"[{l.get('type', l.get('label','link'))}]({l.get('url')})" for l in bg["links"] if l.get("url")
                        )
                        st.markdown(f"**相关链接**：{link_str}")
                    st.markdown("**投资参考要点**：")
                    for note in bg["notes"]:
                        st.write(f"• {note}")

                st.markdown(f"[在 DexScreener 查看]({c['url']})")

        st.caption("⚠️ 综合热度评分是涨幅+换手强度+买卖力量的加权结果，用于排序参考，不构成投资建议")


# ---------- Tab 4: 巨鲸钱包监控 ----------
with tab4:
    st.caption(
        "只展示指定地址最近的转入/转出记录，不会自动判断'这是不是交易所'或'是买入还是卖出'，"
        "请点交易哈希去区块浏览器自行核实。仅覆盖以太坊/BSC/Base/Arbitrum/Polygon等EVM链"
    )

    wallets = []
    for line in wallets_text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0] and parts[1]:
            wallets.append({"chain": parts[0], "address": parts[1], "label": parts[2] if len(parts) > 2 else ""})

    if not etherscan_key:
        st.info("请在左侧填入你自己的免费 Etherscan API Key（etherscan.io/myapikey 几分钟就能申请到）")
    elif not wallets:
        st.info("请在左侧按 `链,地址,备注` 的格式，添加你想监控的巨鲸钱包地址")
    else:
        if st.button("🔄 刷新巨鲸活动", key="refresh_whale"):
            st.cache_data.clear()

        @st.cache_data(ttl=180)
        def get_whale_data(wallets_tuple, api_key):
            wallets_list = [dict(zip(["chain", "address", "label"], w)) for w in wallets_tuple]
            return core.monitor_whale_wallets(wallets_list, api_key)

        wallets_tuple = tuple((w["chain"], w["address"], w["label"]) for w in wallets)
        with st.spinner("正在查询链上活动..."):
            whale_results = get_whale_data(wallets_tuple, etherscan_key)

        for w in whale_results:
            with st.container(border=True):
                bal = f"　原生代币余额: {w['native_balance']:.4f}" if w.get("native_balance") is not None else ""
                st.markdown(f"### 🐋 {w['label']}　`{w['address'][:10]}...{w['address'][-6:]}`（{w['chain']}）{bal}")

                if w.get("error"):
                    st.warning(w["error"])
                    continue

                if not w["activity"]:
                    st.caption("近期没有代币转账记录")
                else:
                    for tx in w["activity"][:15]:
                        arrow = "⬅️ 转入" if tx["direction"] == "转入" else "➡️ 转出"
                        st.write(
                            f"{tx['time']}　{arrow}　**{tx['amount']:,.4f} {tx['symbol']}**　"
                            f"对手方: `{tx['counterparty'][:10]}...`"
                        )


# ---------- Tab 5: 信号回测 ----------
with tab5:
    st.caption(
        "把左侧的 RSI/均线打分规则，套用到这个币种/货币对过去每一天的真实历史价格上，"
        "统计每种信号等级出现后，未来N天的真实涨跌胜率——这是真实回放出来的数据，不是编的"
    )

    bc1, bc2, bc3 = st.columns([2, 1, 1])
    bt_query = bc1.text_input("要回测的币种或货币对", value="bitcoin", placeholder="bitcoin 或 USD/JPY")
    bt_type = bc2.selectbox("类型", ["加密货币", "外汇"])
    bt_forward = bc3.selectbox("往后看几天", [3, 7, 14, 30], index=1)

    if st.button("📈 开始回测", type="primary"):
        with st.spinner("正在拉取历史数据并回放规则，可能需要十几秒..."):
            if bt_type == "加密货币":
                bt_result = core.backtest_coin(bt_query, forward_days=bt_forward)
            else:
                bt_result = core.backtest_forex(bt_query, forward_days=bt_forward)
        st.session_state["bt_result"] = bt_result

    bt_result = st.session_state.get("bt_result")
    if bt_result:
        if bt_result.get("error"):
            st.warning(bt_result["error"])
        else:
            st.success(f"{bt_result['coin'].upper()}　共回放 {bt_result['total_samples']} 个历史样本点")
            for s in bt_result["summary"]:
                bar_color = LEVEL_COLOR.get(s["level"], "gray")
                st.markdown(
                    f":{bar_color}[{s['label']}]　出现 {s['count']} 次　"
                    f"未来{bt_result['forward_days']}天上涨概率 **{s['win_rate']:.0f}%**　"
                    f"平均涨跌 **{s['avg_return']:+.1f}%**"
                )
            st.caption(
                "⚠️ 历史胜率不代表未来一定重复，样本量较小时（比如新币种历史数据不到一年）"
                "统计意义有限，仅供参考"
            )


# ---------- Tab 6: 每日报告 ----------
with tab6:
    st.caption("把当前关注列表、外汇、最近一次新币扫描结果，规则拼接成一份摘要，方便你快速过一遍全貌")

    if st.button("📰 生成今日报告", type="primary"):
        report_candidates = st.session_state.get("candidates", [])
        report_text = core.generate_daily_report(watchlist_results, forex_results, report_candidates, ov, fed)
        st.session_state["daily_report"] = report_text

    if st.session_state.get("daily_report"):
        st.markdown(st.session_state["daily_report"])
    else:
        st.info("点击上方按钮生成，会用到「加密货币关注」「外汇关注」「新币动量扫描」当前已经加载的数据")
