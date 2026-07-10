"""集成测试 - 端到端 API 测试，覆盖所有玩法和串关模式。"""

import pytest
from src.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestIntegrationAPI:
    """端到端 API 测试"""

    def test_full_workflow_3_1(self, client):
        """3串1胜平负计算"""
        payload = {
            "bets": [
                {"match_id": "M001", "play_type": "让球胜平负", "selected_option": "3"},
                {"match_id": "M002", "play_type": "让球胜平负", "selected_option": "3"},
                {"match_id": "M003", "play_type": "让球胜平负", "selected_option": "3"},
            ],
            "parlay": {"mode": "m_n", "m": 3, "n": 1},
            "multiplier": 1,
            "matches": {
                "M001": {"handicap": 0, "play_type": "让球胜平负", "status": "completed",
                         "result": {"home_score": 2, "away_score": 1},
                         "sp_values": {"3": 2.0, "1": 3.0, "0": 2.8}},
                "M002": {"handicap": 0, "play_type": "让球胜平负", "status": "completed",
                         "result": {"home_score": 3, "away_score": 1},
                         "sp_values": {"3": 3.0, "1": 2.5, "0": 2.2}},
                "M003": {"handicap": 0, "play_type": "让球胜平负", "status": "completed",
                         "result": {"home_score": 1, "away_score": 0},
                         "sp_values": {"3": 1.8, "1": 3.5, "0": 4.0}},
            },
        }
        resp = client.post("/api/calculate", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        # 2 × 2.0 × 3.0 × 1.8 × 0.65 = 14.04
        assert data["result"]["total_prize"] == pytest.approx(14.04, rel=0.01)

    def test_full_workflow_handicap(self, client):
        """让球胜平负计算"""
        payload = {
            "bets": [{"match_id": "M001", "play_type": "让球胜平负", "selected_option": "3"}],
            "parlay": {"mode": "single"},
            "multiplier": 1,
            "matches": {
                "M001": {"handicap": -1, "play_type": "让球胜平负", "status": "completed",
                         "result": {"home_score": 2, "away_score": 0},  # 2-1=1 > 0 → 3(胜)
                         "sp_values": {"3": 2.5, "1": 3.0, "0": 2.8}},
            },
        }
        resp = client.post("/api/calculate", json=payload)
        data = resp.get_json()
        assert data["success"] is True
        assert data["result"]["total_prize"] > 0

    def test_mixed_play_types_rejected(self, client):
        """混合玩法应被拒绝"""
        payload = {
            "bets": [
                {"match_id": "M001", "play_type": "让球胜平负", "selected_option": "3"},
                {"match_id": "M002", "play_type": "总进球数", "selected_option": "2"},
            ],
            "parlay": {"mode": "m_n", "m": 2, "n": 1},
            "multiplier": 1,
            "matches": {
                "M001": {"handicap": 0, "play_type": "让球胜平负", "status": "completed",
                         "result": {"home_score": 2, "away_score": 1},
                         "sp_values": {"3": 2.0}},
                "M002": {"handicap": 0, "play_type": "总进球数", "status": "completed",
                         "result": {"home_score": 1, "away_score": 1},
                         "sp_values": {"2": 3.0}},
            },
        }
        resp = client.post("/api/calculate", json=payload)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_all_play_types_can_calculate(self, client):
        """所有7种玩法都能正确计算"""
        test_cases = [
            ("总进球数", "2", {"home_score": 1, "away_score": 1}, {"2": 3.5}, "single"),
            ("上下盘单双数", "上单", {"home_score": 2, "away_score": 1}, {"上单": 4.0}, "single"),
            ("半全场胜平负", "3-3", {"home_score": 2, "away_score": 0, "half_home_score": 1, "half_away_score": 0}, {"3-3": 5.0}, "single"),
            ("比分", "2:1", {"home_score": 2, "away_score": 1}, {"2:1": 7.0}, "single"),
            ("胜负过关", "3", {"home_score": 2, "away_score": 1}, {"3": 1.8, "0": 2.0}, "m_n_3x1"),  # 胜负过关至少3串1
            ("下半场比分", "1:0", {"home_score": 3, "away_score": 1,
                                  "second_half_home_score": 1, "second_half_away_score": 0}, {"1:0": 6.0}, "single"),
        ]
        for play_type, option, result, sp, parlay_mode in test_cases:
            if parlay_mode == "m_n_3x1":
                # 胜负过关需要3串1，创建3场相同比赛
                bets = [
                    {"match_id": "M001", "play_type": play_type, "selected_option": option},
                    {"match_id": "M002", "play_type": play_type, "selected_option": option},
                    {"match_id": "M003", "play_type": play_type, "selected_option": option},
                ]
                matches = {
                    "M001": {"handicap": 0, "play_type": play_type, "status": "completed", "result": result, "sp_values": sp},
                    "M002": {"handicap": 0, "play_type": play_type, "status": "completed", "result": result, "sp_values": sp},
                    "M003": {"handicap": 0, "play_type": play_type, "status": "completed", "result": result, "sp_values": sp},
                }
                parlay = {"mode": "m_n", "m": 3, "n": 1}
            else:
                bets = [{"match_id": "M001", "play_type": play_type, "selected_option": option}]
                matches = {"M001": {"handicap": 0, "play_type": play_type, "status": "completed", "result": result, "sp_values": sp}}
                parlay = {"mode": "single"}

            payload = {"bets": bets, "parlay": parlay, "multiplier": 1, "matches": matches}
            resp = client.post("/api/calculate", json=payload)
            data = resp.get_json()
            assert data["success"] is True, f"{play_type} 计算失败: {data.get('error')}"
            assert data["result"]["total_prize"] > 0, f"{play_type} 应中奖"

    def test_free_parlay(self, client):
        """自由过关: 4场比赛选2关+3关"""
        matches = {}
        bets = []
        for i in range(1, 5):
            mid = f"M00{i}"
            matches[mid] = {
                "handicap": 0, "play_type": "让球胜平负",
                "status": "completed",
                "result": {"home_score": 2, "away_score": 1},
                "sp_values": {"3": 1.5 + i * 0.3, "1": 3.0, "0": 2.8},
            }
            bets.append({"match_id": mid, "play_type": "让球胜平负", "selected_option": "3"})

        payload = {
            "bets": bets,
            "parlay": {"mode": "free_parlay", "m": 4, "selected_levels": [2, 3]},
            "multiplier": 1,
            "matches": matches,
        }
        resp = client.post("/api/calculate", json=payload)
        data = resp.get_json()
        assert data["success"] is True
        # C(4,2) + C(4,3) = 6 + 4 = 10 注
        assert len(data["result"]["breakdown"]) == 10

    def test_config_endpoint(self, client):
        """配置查询接口"""
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "play_types" in data
        assert "max_parlay" in data
        assert "m_n_presets" in data
        assert "rules" in data
        assert len(data["play_types"]) == 7
        assert data["rules"]["return_rate"] == 0.65

    def test_history_endpoint(self, client):
        """历史查询接口"""
        resp = client.get("/api/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tickets" in data

    def test_empty_request(self, client):
        """空请求应返回错误"""
        resp = client.post("/api/calculate", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_invalid_play_type(self, client):
        """无效玩法类型"""
        payload = {
            "bets": [{"match_id": "M001", "play_type": "不存在的玩法", "selected_option": "3"}],
            "parlay": {"mode": "single"},
            "multiplier": 1,
            "matches": {"M001": {"handicap": 0, "play_type": "让球胜平负", "status": "completed",
                                  "result": {"home_score": 2, "away_score": 1},
                                  "sp_values": {"3": 2.5}}},
        }
        resp = client.post("/api/calculate", json=payload)
        assert resp.status_code in (400, 500)

    def test_index_page(self, client):
        """首页正常返回"""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "北单奖金计算器".encode("utf-8") in resp.data
