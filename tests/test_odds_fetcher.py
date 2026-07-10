"""赔率获取模块测试。"""

import pytest
from unittest.mock import patch, MagicMock
from src.odds_fetcher import (
    OddsFetcher, WebScraperFetcher, CachedOddsFetcher,
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

    def test_parse_negative(self):
        assert parse_sp_value("-1") == -1.0


class TestFormatMatchesForAPI:
    """format_matches_for_api 格式转换"""

    def test_formats_matches_correctly(self):
        matches = [
            Match(
                match_id="M1", home_team="曼联", away_team="利物浦",
                handicap=-1, play_type=PlayType.HANDICAP_WDL,
                status=MatchStatus.PENDING,
                sp_values={"3": 2.5, "1": 3.2, "0": 2.8},
            )
        ]
        result = format_matches_for_api(matches)
        assert "M1" in result
        assert result["M1"]["sp_values"]["3"] == 2.5
        assert result["M1"]["handicap"] == -1
        assert result["M1"]["status"] == "pending"
        assert result["M1"]["play_type"] == "让球胜平负"

    def test_formats_empty_list(self):
        assert format_matches_for_api([]) == {}


class TestWebScraperFetcher:
    """网页爬虫测试"""

    def test_fetch_returns_empty_on_connection_error(self):
        fetcher = WebScraperFetcher(timeout=1)
        with patch('src.odds_fetcher.requests.Session.get', side_effect=Exception("Connection refused")):
            matches = fetcher.fetch_matches()
            assert matches == []

    def test_fetch_parses_simple_html(self):
        html = """<html><body><table><tr>
        <td>英超</td><td>曼联</td><td>利物浦</td><td>-1</td>
        <td>2.50</td><td>3.20</td><td>2.80</td>
        </tr></table></body></html>"""
        fetcher = WebScraperFetcher()
        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                content=html.encode('utf-8'),
                text=html,
                encoding='utf-8',
            )
            mock_get.return_value.raise_for_status = MagicMock()
            matches = fetcher.fetch_matches()
            assert len(matches) >= 1
            m = matches[0]
            assert m.home_team == "曼联"
            assert m.away_team == "利物浦"
            assert m.handicap == -1
            assert m.sp_values["3"] == 2.50
            assert m.play_type == PlayType.HANDICAP_WDL

    def test_fetch_handles_http_error(self):
        fetcher = WebScraperFetcher(timeout=1)
        with patch.object(fetcher.session, 'get') as mock_get:
            mock_get.side_effect = __import__('requests').exceptions.HTTPError("404")
            matches = fetcher.fetch_matches()
            assert matches == []

    def test_parse_json_data_standard_format(self):
        """测试 NamiData 风格的 JSON 解析"""
        fetcher = WebScraperFetcher()
        data = [{
            "id": 43,
            "home": "博阿维斯塔",
            "away": "吉马良斯",
            "odds": {
                "spf": {
                    "goal": "0",
                    "sf3": "3.58",
                    "sf1": "3.58",
                    "sf0": "2.53"
                }
            }
        }]
        matches = fetcher._parse_json_data(data)
        assert len(matches) == 1
        m = matches[0]
        assert m.home_team == "博阿维斯塔"
        assert m.away_team == "吉马良斯"
        assert m.handicap == 0
        assert m.sp_values["3"] == 3.58
        assert m.sp_values["1"] == 3.58
        assert m.sp_values["0"] == 2.53

    def test_parse_json_data_flat_format(self):
        """测试简单字段格式的 JSON 解析"""
        fetcher = WebScraperFetcher()
        data = [{
            "home_team": "皇马",
            "away_team": "巴萨",
            "handicap": -1,
            "sp_win": 2.10,
            "sp_draw": 3.50,
            "sp_lose": 3.20,
        }]
        matches = fetcher._parse_json_data(data)
        assert len(matches) == 1
        m = matches[0]
        assert m.home_team == "皇马"
        assert m.sp_values["3"] == 2.10
        assert m.sp_values["1"] == 3.50
        assert m.sp_values["0"] == 3.20


class TestCachedOddsFetcher:
    """缓存机制测试"""

    def test_cache_returns_same_result_within_ttl(self):
        inner = MagicMock(spec=OddsFetcher)
        inner.fetch_matches.return_value = [
            Match(match_id="M1", home_team="A", away_team="B",
                  handicap=0, play_type=PlayType.HANDICAP_WDL)
        ]
        cached = CachedOddsFetcher(inner, ttl_seconds=300)
        r1 = cached.fetch_matches()
        r2 = cached.fetch_matches()
        # 相同对象引用，说明走了缓存
        assert r1 is r2
        assert inner.fetch_matches.call_count == 1

    def test_cache_expires_after_ttl(self):
        inner = MagicMock(spec=OddsFetcher)
        inner.fetch_matches.return_value = []
        cached = CachedOddsFetcher(inner, ttl_seconds=0)  # TTL=0 立即过期
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
    """默认实例"""

    def test_get_default_fetcher_returns_cached(self):
        f1 = get_default_fetcher()
        f2 = get_default_fetcher()
        assert f1 is f2  # 单例
        assert isinstance(f1, CachedOddsFetcher)
