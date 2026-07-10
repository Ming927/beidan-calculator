"""Flask Web 应用 - 北单奖金计算器 API 服务。"""

import uuid
from flask import Flask, request, jsonify, render_template
from src.models import (
    PlayType, MatchStatus, ParlayMode,
    Match, MatchResult, BetSelection, ParlayConfig, Ticket,
    PLAY_TYPE_OPTIONS, PLAY_TYPE_MAX_PARLAY,
)
from src.calculator import calculate, RETURN_RATE, MAX_PRIZE, TAX_THRESHOLD, TAX_RATE, BASE_AMOUNT
from src.parlay import M_N_PRESETS, validate_parlay
from src.storage import BetStorage
from src.odds_fetcher import (
    get_default_fetcher, format_matches_for_api,
    ApiFetcher, DemoFetcher,
)

app = Flask(__name__)
storage = BetStorage("data/bets.json")


# ── 页面路由 ──

@app.route("/")
def index():
    """首页"""
    return render_template("index.html")


# ── 计算 API ──

@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    """奖金计算接口。"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "请求体不能为空"}), 400

        bets = []
        for b in data.get("bets", []):
            bets.append(BetSelection(
                match_id=b["match_id"],
                play_type=PlayType(b["play_type"]),
                selected_option=b["selected_option"],
            ))

        if not bets:
            return jsonify({"success": False, "error": "至少需要1个投注选项"}), 400

        p = data.get("parlay", {})
        mode_str = p.get("mode", "single")
        if mode_str == "single":
            parlay_config = ParlayConfig(mode=ParlayMode.SINGLE)
        elif mode_str == "free_parlay":
            parlay_config = ParlayConfig(
                mode=ParlayMode.FREE_PARLAY,
                m=p.get("m", len(bets)),
                selected_levels=p.get("selected_levels", []),
            )
        else:
            parlay_config = ParlayConfig(
                mode=ParlayMode.M_N,
                m=p.get("m", len(bets)),
                n=p.get("n", 1),
            )

        match_map = {}
        for mid, md in data.get("matches", {}).items():
            result = None
            if "result" in md and md["result"]:
                r = md["result"]
                result = MatchResult(
                    home_score=r.get("home_score", 0),
                    away_score=r.get("away_score", 0),
                    half_home_score=r.get("half_home_score", 0),
                    half_away_score=r.get("half_away_score", 0),
                    second_half_home_score=r.get("second_half_home_score", 0),
                    second_half_away_score=r.get("second_half_away_score", 0),
                )
            match_map[mid] = Match(
                match_id=mid,
                home_team=md.get("home_team", ""),
                away_team=md.get("away_team", ""),
                handicap=md.get("handicap", 0),
                play_type=PlayType(md.get("play_type", "让球胜平负")),
                status=MatchStatus(md.get("status", "pending")),
                result=result,
                sp_values=md.get("sp_values", {}),
            )

        ticket = Ticket(
            ticket_id=str(uuid.uuid4())[:8],
            bets=bets,
            parlay_config=parlay_config,
            multiplier=data.get("multiplier", 1),
        )

        result = calculate(ticket, match_map)

        try:
            storage.save_ticket(ticket)
            for m in match_map.values():
                storage.save_match(m)
        except Exception:
            pass

        return jsonify({
            "success": True,
            "ticket_id": ticket.ticket_id,
            "result": {
                "total_prize": result.total_prize,
                "total_cost": result.total_cost,
                "net_profit": result.net_profit,
                "breakdown": [
                    {
                        "combo_desc": b.combo_desc,
                        "match_ids": b.match_ids,
                        "sp_product": b.sp_product,
                        "won": b.won,
                        "prize_before_tax": b.prize_before_tax,
                        "tax": b.tax,
                        "prize_after_tax": b.prize_after_tax,
                    }
                    for b in result.breakdown
                ],
            },
        })

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"内部错误: {str(e)}"}), 500


# ── 配置查询 API ──

@app.route("/api/config", methods=["GET"])
def api_config():
    """返回所有玩法类型、选项、串关限制、M串N预设等配置信息。"""
    presets_formatted = {}
    for (m_val, n_val), levels in M_N_PRESETS.items():
        from src.parlay import comb
        key = f"{m_val}串{n_val}"
        breakdown_parts = []
        for k in sorted(set(levels)):
            count = comb(m_val, k)
            breakdown_parts.append(f"{count}个{k}串1")
        presets_formatted[key] = {
            "m": m_val, "n": n_val, "levels": levels,
            "breakdown": breakdown_parts,
        }

    fetcher = get_default_fetcher()
    odds_mode = "api" if isinstance(fetcher.inner, ApiFetcher) else "demo"

    return jsonify({
        "play_types": {pt.value: PLAY_TYPE_OPTIONS[pt] for pt in PlayType},
        "max_parlay": {pt.value: v for pt, v in PLAY_TYPE_MAX_PARLAY.items()},
        "m_n_presets": presets_formatted,
        "odds_mode": odds_mode,
        "rules": {
            "return_rate": RETURN_RATE,
            "max_prize": MAX_PRIZE,
            "tax_threshold": TAX_THRESHOLD,
            "tax_rate": TAX_RATE,
            "base_bet_amount": BASE_AMOUNT,
            "max_multiplier": 99,
            "max_matches": 15,
        },
    })


# ── 历史查询 API ──

@app.route("/api/history", methods=["GET"])
def api_history():
    """查询历史投注记录。"""
    tickets = storage.list_tickets(limit=50)
    return jsonify({
        "tickets": [
            {
                "ticket_id": t.ticket_id,
                "bets": [
                    {"match_id": b.match_id, "play_type": b.play_type.value,
                     "selected_option": b.selected_option}
                    for b in t.bets
                ],
                "parlay": {
                    "mode": t.parlay_config.mode.value,
                    "m": t.parlay_config.m,
                    "n": t.parlay_config.n,
                    "selected_levels": t.parlay_config.selected_levels,
                },
                "multiplier": t.multiplier,
                "created_at": t.created_at,
            }
            for t in tickets
        ]
    })


# ── 赔率获取 API ──

@app.route("/api/fetch-odds", methods=["POST"])
def api_fetch_odds():
    """获取最新的北单赔率数据。

    请求: POST /api/fetch-odds
    可选参数 JSON: {"url": "API地址", "api_key": "API密钥", "force": true}

    返回: {"success": true, "mode": "demo"|"api", "matches": {...}, "count": N}
    """
    try:
        req_data = request.get_json(silent=True) or {}
        force_refresh = req_data.get("force", False)
        api_url = req_data.get("url", "")
        api_key = req_data.get("api_key", "")

        fetcher = get_default_fetcher()
        inner = fetcher.inner

        # 动态切换模式
        if api_url and api_key:
            new_inner = ApiFetcher(base_url=api_url, api_key=api_key)
            fetcher._inner = new_inner
            fetcher.invalidate()
            mode = "api"
        elif isinstance(inner, ApiFetcher):
            mode = "api"
        else:
            mode = "demo"

        if force_refresh:
            fetcher.invalidate()

        matches = fetcher.fetch_matches()

        if not matches:
            if mode == "demo":
                msg = "演示模式未返回数据，请重试。"
            else:
                msg = ("API 未返回数据。请检查 API 地址和密钥是否正确。"
                       "可设置环境变量 BEIDAN_API_URL 和 BEIDAN_API_KEY 持久化配置。")
            return jsonify({"success": False, "mode": mode, "error": msg}), 502

        formatted = format_matches_for_api(matches)

        return jsonify({
            "success": True,
            "mode": mode,
            "count": len(matches),
            "matches": formatted,
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"获取失败: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
