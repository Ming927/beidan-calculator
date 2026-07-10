"""集成测试 — Phase 3 API。"""

import pytest
from src.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestFetchIssue:
    """期号数据拉取"""

    def test_missing_expect(self, client):
        resp = client.post("/api/fetch-issue", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_invalid_expect(self, client):
        resp = client.post("/api/fetch-issue", json={"expect": "99999999"})
        assert resp.status_code in (200, 502)
        data = resp.get_json()
        assert "success" in data


class TestCalculateBatch:
    """批量计算"""

    def test_empty_request(self, client):
        resp = client.post("/api/calculate-batch", json={})
        assert resp.status_code == 400

    def test_no_matches_no_levels(self, client):
        resp = client.post("/api/calculate-batch", json={
            "issue_data": {"matches": []},
            "selected_ids": [],
            "parlay_levels": [],
        })
        assert resp.status_code == 400

    def test_with_mock_data(self, client):
        """用模拟数据测试批量计算"""
        payload = {
            "issue_data": {
                "success": True,
                "issue": "26073",
                "matches": [
                    {"id": "1", "home": "阿根廷", "away": "埃及", "handicap": -1,
                     "score_half": [0, 1], "score_full": [3, 2],
                     "plays": {"让球胜平负": {"result": "1", "sp": 3.68},
                               "总进球数": {"result": "5", "sp": 9.88},
                               "比分": {"result": "3:2", "sp": 30.94}}},
                    {"id": "2", "home": "弗洛里亚纳", "away": "沙姆洛克", "handicap": 0,
                     "score_half": [1, 0], "score_full": [2, 0],
                     "plays": {"让球胜平负": {"result": "3", "sp": 4.68},
                               "总进球数": {"result": "2", "sp": 5.97},
                               "比分": {"result": "2:0", "sp": 31.73}}},
                    {"id": "3", "home": "瑞士", "away": "哥伦比亚", "handicap": 0,
                     "score_half": [0, 0], "score_full": [1, 1],
                     "plays": {"让球胜平负": {"result": "1", "sp": 3.20},
                               "总进球数": {"result": "2", "sp": 4.50},
                               "比分": {"result": "1:1", "sp": 7.50}}},
                ],
            },
            "selected_ids": ["1", "2", "3"],
            "play_types": ["让球胜平负"],
            "parlay_levels": [2, 3],
            "multiplier": 1,
        }
        resp = client.post("/api/calculate-batch", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "让球胜平负" in data["results"]
        r = data["results"]["让球胜平负"]
        # C(3,2) + C(3,3) = 3 + 1 = 4 combos
        assert r["combo_count"] == 4

    def test_winning_combo_calculates_prize(self, client):
        """中奖组合应计算正确奖金"""
        payload = {
            "issue_data": {
                "success": True, "issue": "test",
                "matches": [
                    {"id": "1", "home": "A", "away": "B", "handicap": 0,
                     "score_half": [0, 0], "score_full": [2, 1],
                     "plays": {"让球胜平负": {"result": "3", "sp": 2.00}}},
                    {"id": "2", "home": "C", "away": "D", "handicap": 0,
                     "score_half": [0, 0], "score_full": [3, 1],
                     "plays": {"让球胜平负": {"result": "3", "sp": 3.00}}},
                ],
            },
            "selected_ids": ["1", "2"],
            "play_types": ["让球胜平负"],
            "parlay_levels": [2],
            "multiplier": 1,
        }
        resp = client.post("/api/calculate-batch", json=payload)
        data = resp.get_json()
        assert data["success"]
        r = data["results"]["让球胜平负"]
        # 2串1: 2元 × 2.0 × 3.0 × 0.65 = 7.80
        winning = [c for c in r["combos"] if c["won"]]
        assert len(winning) == 1
        assert winning[0]["prize_before_tax"] == pytest.approx(7.80, rel=0.01)


class TestRulesAPI:
    """规则查询"""

    def test_rules_endpoint(self, client):
        resp = client.get("/api/rules")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["return_rate"] == 0.65


class TestIndexPage:
    """首页"""

    def test_index_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "北单奖金计算器".encode("utf-8") in resp.data
