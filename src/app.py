"""Flask Web 应用 - 北单奖金计算器 API。"""

import json
import os
import time
from flask import Flask, request, jsonify, render_template
from src.models import PlayType
from src.calculator import calculate_batch, RETURN_RATE, MAX_PRIZE, TAX_THRESHOLD, TAX_RATE, BASE_AMOUNT
from src.zx500_fetcher import fetch_issue, build_match_objects, _PLAY_TYPE_MAP

app = Flask(__name__)

HISTORY_FILE = "data/history.json"


def _load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_history(records):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=str)

# ── 页面路由 ──

@app.route("/")
def index():
    return render_template("index.html")


# ── 拉取期号数据 ──

@app.route("/api/fetch-issue", methods=["POST"])
def api_fetch_issue():
    """从 500.com 拉取指定期号的北单开奖数据。

    请求: {"expect": "26073"}
    返回: 5种玩法的彩果+SP值 + 比赛列表
    """
    try:
        data = request.get_json(silent=True) or {}
        expect = data.get("expect", "").strip()
        if not expect:
            return jsonify({"success": False, "error": "请输入期号"}), 400

        result = fetch_issue(expect)
        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": f"获取失败: {str(e)}"}), 500


# ── 批量奖金计算 ──

@app.route("/api/calculate-batch", methods=["POST"])
def api_calculate_batch():
    """批量计算奖金：对选中场次+串关级别，自动计算全部玩法×全部组合。

    请求: {
        "issue_data": {...},        // fetch_issue 返回的数据
        "selected_ids": ["1","3","5"],  // 选中的场次ID
        "play_types": ["让球胜平负", "比分"],  // 要计算的玩法
        "parlay_levels": [4, 3, 2],  // 串关级别
        "multiplier": 1
    }
    """
    try:
        req = request.get_json(silent=True) or {}
        issue_data = req.get("issue_data", {})
        selected_ids = set(req.get("selected_ids", []))
        play_type_names = req.get("play_types", list(_PLAY_TYPE_MAP.keys()))
        parlay_levels = req.get("parlay_levels", [])
        multiplier = req.get("multiplier", 1)

        if not selected_ids or not parlay_levels:
            return jsonify({"success": False, "error": "请选择场次和串关级别"}), 400

        # 过滤选中的比赛
        issue_data["matches"] = [
            m for m in issue_data.get("matches", [])
            if m["id"] in selected_ids
        ]

        all_results = {}
        grand_total = 0.0

        for pt_name in play_type_names:
            if pt_name not in _PLAY_TYPE_MAP:
                continue
            pt = _PLAY_TYPE_MAP[pt_name]
            matches = build_match_objects(issue_data, pt_name)

            if not matches or len(matches) < min(parlay_levels, default=2):
                continue

            batch = calculate_batch(matches, [pt], parlay_levels, multiplier)
            if pt.value in batch["results"]:
                all_results[pt.value] = batch["results"][pt.value]
                grand_total += batch["results"][pt.value]["total_prize"]

        result_data = {
            "success": True,
            "results": all_results,
            "grand_total": round(grand_total, 2),
            "play_types_count": len(all_results),
        }

        # 保存到历史记录
        try:
            records = _load_history()
            records.insert(0, {
                "id": str(int(time.time() * 1000)),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "issue": issue_data.get("issue", ""),
                "matches_count": len(selected_ids),
                "parlay_levels": sorted(parlay_levels, reverse=True),
                "multiplier": multiplier,
                "grand_total": round(grand_total, 2),
                "play_types": list(all_results.keys()),
                "details": all_results,
            })
            _save_history(records[:50])  # 最多保留50条
        except Exception:
            pass

        return jsonify(result_data)

    except Exception as e:
        return jsonify({"success": False, "error": f"计算失败: {str(e)}"}), 500


# ── 历史记录 ──

@app.route("/api/history", methods=["GET"])
def api_history():
    """查询历史计算记录。"""
    records = _load_history()
    # 返回摘要（不含 details）
    summary = []
    for r in records[:30]:
        summary.append({
            "id": r["id"],
            "time": r["time"],
            "issue": r.get("issue", ""),
            "matches_count": r.get("matches_count", 0),
            "parlay_levels": r.get("parlay_levels", []),
            "multiplier": r.get("multiplier", 1),
            "grand_total": r.get("grand_total", 0),
            "play_types": r.get("play_types", []),
        })
    return jsonify({"records": summary})


@app.route("/api/history/<record_id>", methods=["GET"])
def api_history_detail(record_id):
    """查询一条历史记录的详细信息。"""
    records = _load_history()
    for r in records:
        if r["id"] == record_id:
            return jsonify({"success": True, "record": r})
    return jsonify({"success": False, "error": "记录不存在"}), 404


@app.route("/api/history/<record_id>", methods=["DELETE"])
def api_history_delete(record_id):
    """删除一条历史记录。"""
    records = _load_history()
    records = [r for r in records if r["id"] != record_id]
    _save_history(records)
    return jsonify({"success": True})


# ── 规则信息 ──

@app.route("/api/rules", methods=["GET"])
def api_rules():
    return jsonify({
        "play_types": {name: {"enum": pt.value, "options": []}
                       for name, pt in _PLAY_TYPE_MAP.items()},
        "return_rate": RETURN_RATE,
        "max_prize": MAX_PRIZE,
        "tax_threshold": TAX_THRESHOLD,
        "tax_rate": TAX_RATE,
        "base_amount": BASE_AMOUNT,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
