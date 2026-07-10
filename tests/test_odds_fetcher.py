"""赔率获取模块测试。"""

import os
import pytest
from unittest.mock import patch, MagicMock
from src.odds_fetcher import (
    OddsFetcher, ApiFetcher, DemoFetcher, CachedOddsFetcher,
    parse_sp_value, format_matches_for_api, get_default_fetcher,
)
from src.models import PlayType, MatchStatus, Match


class TestParseSPValue:
    """SP 值字符串解析"""

    def test_parse_float(self):
        assert parse_sp_value("3.58") == 3.58

    def test_parse_integer_string(self):
        assert parse_sp_value("2") == 2.0

    def test_parse_invalid_returns_zero(self):
        assert parse_sp_value("--") == 0.0
        assert parse_sp_value("") == 0.0

    def test_parse_whitespace(self):
        assert parse_sp_value("  1.85  ") == 1.85


class TestFormatMatchesForAPI:
    """format_matches_for_api"""

    def test_formats_matches_correctly(self):
        matches = [
            Match(match_id="M1", home_team="曼联", away_team="利物浦",
                  handicap=-1, play_type=PlayType.HANDICAP_WDL,
                  status=MatchStatus.PENDING,
                  sp_values={"3": 2.5, "1": 3.2, "0": 2.8}),
        ]
        result = format_matches_for_api(matches)
        assert "M1" in result
        assert result["M1"]["sp_values"]["3"] == 2.5
        assert result["M1"]["handicap"] == -1

    def test_formats_empty_list(self):
        assert format_matches_for_api([]) == {}


class TestApiFetcher:
    """商业 API 客户端"""

    def test_not_configured_returns_empty(self):
        fetcher = ApiFetcher(base_url="")
        assert not fetcher.is_configured
        assert fetcher.fetch_matches() == []

    def test_is_configured_with_url(self):
        fetcher = ApiFetcher(base_url="https://api.example.com/odds")
        assert fetcher.is_configured

    def test_fetch_parses_standard_response(self):
        fetcher = ApiFetcher(base_url="https://api.example.com/odds", api_key="test")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {"list": [{
                "id": 43, "home": "博阿维斯塔", "away": "吉马良斯",
                "odds": {"spf": {"goal": "0", "sf3": "3.58", "sf1": "3.58", "sf0": "2.53"}},
            }]},
        }
        mock_resp.raise_for_status = MagicMock()
        with patch('src.odds_fetcher.requests.get', return_value=mock_resp):
            matches = fetcher.fetch_matches()
            assert len(matches) == 1
            m = matches[0]
            assert m.home_team == "博阿维斯塔"
            assert m.sp_values["3"] == 3.58
            assert m.sp_values["0"] == 2.53

    def test_fetch_handles_error_code(self):
        fetcher = ApiFetcher(base_url="https://api.example.com/odds")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 1, "msg": "无效token"}
        mock_resp.raise_for_status = MagicMock()
        with patch('src.odds_fetcher.requests.get', return_value=mock_resp):
            assert fetcher.fetch_matches() == []

    def test_fetch_handles_network_error(self):
        fetcher = ApiFetcher(base_url="https://api.example.com/odds")
        with patch('src.odds_fetcher.requests.get', side_effect=Exception("timeout")):
            assert fetcher.fetch_matches() == []


class TestDemoFetcher:
    """演示模式"""

    def test_generates_matches_with_fixed_seed(self):
        fetcher = DemoFetcher(match_count=10, seed=42)
        matches = fetcher.fetch_matches()
        assert len(matches) == 10
        for m in matches:
            assert m.home_team
            assert m.away_team
            assert m.sp_values["3"] > 0
            assert m.sp_values["1"] > 0
            assert m.sp_values["0"] > 0
            assert m.play_type == PlayType.HANDICAP_WDL
            assert m.status == MatchStatus.PENDING

    def test_same_seed_same_output(self):
        """相同种子的单实例产生相同结果"""
        f1 = DemoFetcher(match_count=8, seed=123)
        m1 = f1.fetch_matches()
        # 重建后重新设置种子
        f2 = DemoFetcher(match_count=8, seed=123)
        m2 = f2.fetch_matches()
        assert len(m1) == len(m2)
        for a, b in zip(m1, m2):
            assert a.home_team == b.home_team
            assert a.sp_values == b.sp_values

    def test_sp_values_are_reasonable(self):
        fetcher = DemoFetcher(match_count=50, seed=99)
        matches = fetcher.fetch_matches()
        for m in matches:
            assert 1.1 <= m.sp_values["3"] <= 6.5, f"SP3={m.sp_values['3']} out of range"
            assert 2.0 <= m.sp_values["1"] <= 5.5, f"SP1={m.sp_values['1']} out of range"
            assert 1.1 <= m.sp_values["0"] <= 7.0, f"SP0={m.sp_values['0']} out of range"


class TestCachedOddsFetcher:
    """缓存机制"""

    def test_cache_returns_same_result_within_ttl(self):
        inner = MagicMock(spec=OddsFetcher)
        inner.fetch_matches.return_value = [Match(
            match_id="M1", home_team="A", away_team="B",
            handicap=0, play_type=PlayType.HANDICAP_WDL)]
        cached = CachedOddsFetcher(inner, ttl_seconds=300)
        r1 = cached.fetch_matches()
        r2 = cached.fetch_matches()
        assert r1 is r2
        assert inner.fetch_matches.call_count == 1

    def test_cache_expires_after_ttl_zero(self):
        inner = MagicMock(spec=OddsFetcher)
        inner.fetch_matches.return_value = []
        cached = CachedOddsFetcher(inner, ttl_seconds=0)
        cached.fetch_matches()
        cached.fetch_matches()
        assert inner.fetch_matches.call_count == 2

    def test_invalidate_clears_cache(self):
        inner = MagicMock(spec=OddsFetcher)
        inner.fetch_matches.return_value = []
        cached = CachedOddsFetcher(inner, ttl_seconds=300)
        cached.fetch_matches()
        cached.invalidate()
        cached.fetch_matches()
        assert inner.fetch_matches.call_count == 2


class TestDefaultFetcher:
    """默认实例工厂"""

    def test_returns_demo_mode_by_default(self):
        # 确保没有设置环境变量
        old = os.environ.pop("BEIDAN_API_URL", None)
        try:
            # 重置单例
            import src.odds_fetcher as of
            of._default_fetcher = None
            fetcher = get_default_fetcher()
            assert isinstance(fetcher.inner, DemoFetcher)
        finally:
            if old:
                os.environ["BEIDAN_API_URL"] = old
            of._default_fetcher = None

    def test_returns_api_mode_when_configured(self):
        old = os.environ.get("BEIDAN_API_URL")
        os.environ["BEIDAN_API_URL"] = "https://api.example.com/odds"
        try:
            import src.odds_fetcher as of
            of._default_fetcher = None
            fetcher = get_default_fetcher()
            assert isinstance(fetcher.inner, ApiFetcher)
        finally:
            if old:
                os.environ["BEIDAN_API_URL"] = old
            else:
                os.environ.pop("BEIDAN_API_URL", None)
            of._default_fetcher = None
