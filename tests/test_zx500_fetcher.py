"""500.com 数据解析器测试。"""

import pytest
from unittest.mock import patch, MagicMock
from src.zx500_fetcher import (
    fetch_issue, build_match_objects, _parse_html,
    _SCORE_RE, _PLAY_TYPE_MAP, _COLUMN_MAP,
)
from src.models import PlayType

# 模拟 500.com 页面 HTML（2场比赛）
MOCK_HTML = """<html><body><table class="ld_table">
<tr><th colspan="20">期号 26073</th></tr>
<tr><td colspan="2">让球胜平负</td></tr>
<tr><td>彩果</td><td>SP值</td></tr>
<tr><td colspan="2">总进球数</td></tr>
<tr><td>彩果</td><td>SP值</td></tr>
<tr><td colspan="2">比分</td></tr>
<tr><td>彩果</td><td>SP值</td></tr>
<tr><td colspan="2">上下单双</td></tr>
<tr><td>彩果</td><td>SP值</td></tr>
<tr><td colspan="2">半全场</td></tr>
<tr><td>彩果</td><td>SP值</td></tr>
<tr>
<td>1</td><td>世界杯</td><td>07-08 00:00</td>
<td class="text_r">阿根廷</td><td class="eng">-1</td><td class="text_l">埃及</td>
<td class="eng">(0:1) 3:2</td><td></td>
<td>平</td><td class="eng">3.68</td><td></td>
<td>5</td><td class="eng">9.88</td><td></td>
<td>3:2</td><td class="eng">30.94</td><td></td>
<td>上单</td><td class="eng">2.98</td><td></td>
<td>负-胜</td><td class="eng">13.43</td>  <!-- 半全场: "负-胜" → 标准化为 "0-3" -->
</tr>
<tr>
<td>2</td><td>欧冠资格</td><td>07-08 01:30</td>
<td class="text_r">弗洛里亚纳</td><td class="eng">0</td><td class="text_l">沙姆洛克</td>
<td class="eng">(1:0) 2:0</td><td></td>
<td>胜</td><td class="eng">4.68</td><td></td>
<td>2</td><td class="eng">5.97</td><td></td>
<td>2:0</td><td class="eng">31.73</td><td></td>
<td>下双</td><td class="eng">3.64</td><td></td>
<td>胜-胜</td><td class="eng">9.56</td>  <!-- 半全场: "胜-胜" → 标准化为 "3-3" -->
</tr>
</table></body></html>"""


class TestScoreRegex:
    def test_parse_score(self):
        m = _SCORE_RE.search("(0:1) 3:2")
        assert m.group(1) == "0"
        assert m.group(2) == "1"
        assert m.group(3) == "3"
        assert m.group(4) == "2"

    def test_parse_single_digit(self):
        m = _SCORE_RE.search("(1:0) 2:0")
        assert m.group(3) == "2"
        assert m.group(4) == "0"


class TestParseHTML:
    def test_parse_mock_html(self):
        result = _parse_html(MOCK_HTML, "26073")
        assert result["success"] is True
        assert result["issue"] == "26073"
        assert result["count"] == 2

        m1 = result["matches"][0]
        assert m1["id"] == "1"
        assert m1["home"] == "阿根廷"
        assert m1["away"] == "埃及"
        assert m1["handicap"] == -1
        assert m1["score_half"] == (0, 1)
        assert m1["score_full"] == (3, 2)

        # 让球胜平负 (500.com 原始值 "平" 在 _parse_html 中标准化为 "1")
        assert m1["plays"]["让球胜平负"]["result"] == "1"
        assert m1["plays"]["让球胜平负"]["sp"] == 3.68
        # 总进球数
        assert m1["plays"]["总进球数"]["result"] == "5"
        assert m1["plays"]["总进球数"]["sp"] == 9.88
        # 比分
        assert m1["plays"]["比分"]["result"] == "3:2"
        assert m1["plays"]["比分"]["sp"] == 30.94
        # 上下单双
        assert m1["plays"]["上下单双"]["result"] == "上单"
        # 半全场 (500.com "负-胜" → 标准化为 "0-3")
        assert m1["plays"]["半全场"]["result"] == "0-3"

    def test_parse_empty_html(self):
        result = _parse_html("<html></html>", "99999")
        assert result["success"] is False


class TestBuildMatchObjects:
    def test_build_wdl_matches(self):
        issue = _parse_html(MOCK_HTML, "26073")
        matches = build_match_objects(issue, "让球胜平负")
        assert len(matches) == 2
        m = matches[0]
        assert m.play_type == PlayType.HANDICAP_WDL
        assert m.sp_values["1"] == 3.68  # 500.com "平" → 标准化为 "1"
        assert m.result.home_score == 3
        assert m.result.away_score == 2
        assert m.result.half_home_score == 0
        assert m.result.half_away_score == 1

    def test_build_total_goals_matches(self):
        issue = _parse_html(MOCK_HTML, "26073")
        matches = build_match_objects(issue, "总进球数")
        assert len(matches) == 2
        assert matches[0].sp_values["5"] == 9.88
        assert matches[0].play_type == PlayType.TOTAL_GOALS

    def test_build_all_five_play_types(self):
        issue = _parse_html(MOCK_HTML, "26073")
        for name in ["让球胜平负", "总进球数", "比分", "上下单双", "半全场"]:
            matches = build_match_objects(issue, name)
            assert len(matches) == 2, f"{name} should have 2 matches"

    def test_invalid_play_type_returns_empty(self):
        issue = _parse_html(MOCK_HTML, "26073")
        assert build_match_objects(issue, "不存在的玩法") == []


class TestFetchIssue:
    def test_network_error(self):
        with patch('src.zx500_fetcher.requests.get', side_effect=Exception("timeout")):
            result = fetch_issue("26073")
            assert result["success"] is False

    def test_successful_fetch(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_HTML
        mock_resp.content = MOCK_HTML.encode('utf-8')
        mock_resp.encoding = 'utf-8'
        mock_resp.raise_for_status = MagicMock()
        with patch('src.zx500_fetcher.requests.get', return_value=mock_resp):
            result = fetch_issue("26073")
            assert result["success"] is True
            assert result["count"] == 2


class TestPlayTypeMapping:
    def test_all_five_types_mapped(self):
        assert len(_PLAY_TYPE_MAP) == 5
        for name, pt in _PLAY_TYPE_MAP.items():
            assert isinstance(pt, PlayType)

    def test_column_map_correct(self):
        assert len(_COLUMN_MAP) == 5
        for name, res_col, sp_col in _COLUMN_MAP:
            assert res_col in (8, 11, 14, 17, 20)
            assert sp_col == res_col + 1
