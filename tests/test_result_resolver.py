"""赛果判定器测试 - 覆盖全部7种玩法 + 延期/取消等特殊情况。"""

import pytest
from src.models import (
    PlayType, Match, MatchResult, BetSelection, MatchStatus,
)
from src.result_resolver import (
    resolve_bet, resolve_handicap_wdl,
    resolve_total_goals, resolve_over_under_odd_even,
    resolve_half_full_wdl, resolve_correct_score, resolve_win_lose_pass,
)


class TestHandicapWDL:
    """让球胜平负"""

    @pytest.mark.parametrize("home,away,handicap,expected", [
        # 主队让1球 (-1): 主队需净胜2球以上才能算"胜"
        (2, 0, -1, "3"),   # 调整后 1:0 → 胜
        (1, 0, -1, "1"),   # 调整后 0:0 → 平
        (0, 0, -1, "0"),   # 调整后 -1:0 → 负
        (3, 1, -1, "3"),   # 调整后 2:1 → 胜
        (2, 1, -1, "1"),   # 调整后 1:1 → 平
        # 主队让2球 (-2)
        (4, 0, -2, "3"),   # 调整后 2:0 → 胜
        (2, 0, -2, "1"),   # 调整后 0:0 → 平
        (1, 0, -2, "0"),   # 调整后 -1:0 → 负
        # 主队受让1球 (+1)
        (1, 0, 1, "3"),    # 调整后 2:0 → 胜
        (0, 0, 1, "3"),    # 调整后 1:0 → 胜
        (0, 1, 1, "1"),    # 调整后 1:1 → 平（恰好输1球）
        (0, 2, 1, "0"),    # 调整后 1:2 → 负（输2球以上）
        # 无让球 (0)
        (2, 1, 0, "3"),
        (1, 1, 0, "1"),
        (0, 1, 0, "0"),
    ])
    def test_resolve(self, home, away, handicap, expected):
        result = resolve_handicap_wdl(home, away, handicap)
        assert result == expected, f"{home}:{away} handicap={handicap} → {result}, expected {expected}"


class TestTotalGoals:
    """总进球数"""

    @pytest.mark.parametrize("home,away,expected", [
        (0, 0, "0"),
        (1, 0, "1"),
        (0, 1, "1"),
        (1, 1, "2"),
        (2, 1, "3"),
        (2, 2, "4"),
        (3, 2, "5"),
        (4, 2, "6"),
        (5, 2, "7+"),
        (4, 4, "7+"),
        (7, 0, "7+"),
    ])
    def test_resolve(self, home, away, expected):
        assert resolve_total_goals(home, away) == expected


class TestOverUnderOddEven:
    """上下盘单双数"""

    @pytest.mark.parametrize("home,away,expected", [
        (2, 2, "上双"),   # 4球 >=3, 偶数 → 上双
        (2, 0, "下双"),   # 2球 <3, 偶数 → 下双
        (2, 1, "上单"),   # 3球 >=3, 奇数 → 上单
        (1, 0, "下单"),   # 1球 <3, 奇数 → 下单
        (0, 0, "下双"),   # 0球 <3, 偶数 → 下双
        (0, 1, "下单"),   # 1球 <3, 奇数 → 下单
        (3, 3, "上双"),   # 6球 >=3, 偶数 → 上双
    ])
    def test_resolve(self, home, away, expected):
        assert resolve_over_under_odd_even(home, away) == expected


class TestHalfFullWDL:
    """半全场胜平负"""

    @pytest.mark.parametrize("h_home,h_away,f_home,f_away,expected", [
        (2, 0, 2, 0, "3-3"),   # 半场胜 + 全场胜
        (1, 0, 1, 1, "3-1"),   # 半场胜 + 全场平
        (1, 0, 1, 2, "3-0"),   # 半场胜 + 全场负（逆转）
        (0, 0, 1, 0, "1-3"),   # 半场平 + 全场胜
        (1, 1, 1, 1, "1-1"),   # 半场平 + 全场平
        (0, 0, 0, 1, "1-0"),   # 半场平 + 全场负
        (0, 1, 2, 1, "0-3"),   # 半场负 + 全场胜（逆转）
        (0, 1, 1, 1, "0-1"),   # 半场负 + 全场平
        (0, 1, 0, 2, "0-0"),   # 半场负 + 全场负
    ])
    def test_resolve(self, h_home, h_away, f_home, f_away, expected):
        assert resolve_half_full_wdl(h_home, h_away, f_home, f_away) == expected


class TestCorrectScore:
    """比分（含胜其他/平其他/负其他）"""

    @pytest.mark.parametrize("home,away,expected", [
        (1, 0, "1:0"),
        (3, 2, "3:2"),
        (0, 0, "0:0"),
        (4, 2, "4:2"),
        (5, 1, "胜其他"),   # 5:1 > 4:2 范围，算"胜其他"
        (2, 5, "负其他"),   # 2:5 不算标准模式，算"负其他"
        (4, 4, "平其他"),   # 4:4 > 3:3 范围，算"平其他"
        (6, 0, "胜其他"),
        (0, 5, "负其他"),
    ])
    def test_resolve(self, home, away, expected):
        assert resolve_correct_score(home, away) == expected


class TestWinLosePass:
    """胜负过关"""

    @pytest.mark.parametrize("home,away,expected", [
        (2, 1, "3"),   # 主胜
        (1, 1, "0"),   # 平局 → 主负
        (0, 1, "0"),   # 主负
        (3, 0, "3"),   # 主胜
    ])
    def test_resolve(self, home, away, expected):
        assert resolve_win_lose_pass(home, away) == expected


class TestResolveBet:
    """resolve_bet 完整流程测试"""

    def test_winning_bet(self):
        match = Match(
            match_id="M001", home_team="A", away_team="B",
            handicap=0, play_type=PlayType.HANDICAP_WDL,
            status=MatchStatus.COMPLETED,
            result=MatchResult(home_score=2, away_score=1),
            sp_values={"3": 2.5, "1": 3.0, "0": 2.8},
        )
        bet = BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        won, sp = resolve_bet(match, bet)
        assert won is True
        assert sp == 2.5

    def test_losing_bet(self):
        match = Match(
            match_id="M001", home_team="A", away_team="B",
            handicap=0, play_type=PlayType.HANDICAP_WDL,
            status=MatchStatus.COMPLETED,
            result=MatchResult(home_score=0, away_score=1),
            sp_values={"3": 2.5, "1": 3.0, "0": 2.8},
        )
        bet = BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        won, sp = resolve_bet(match, bet)
        assert won is False
        assert sp == 0.0

    def test_postponed_match_sp_is_1(self):
        """延期比赛: 所有选项算中, SP=1.0"""
        match = Match(
            match_id="M001", home_team="A", away_team="B",
            handicap=0, play_type=PlayType.HANDICAP_WDL,
            status=MatchStatus.CANCELLED,
        )
        bet = BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        won, sp = resolve_bet(match, bet)
        assert won is True
        assert sp == 1.0

    def test_missing_result_raises(self):
        """缺少赛果数据时报错"""
        match = Match(
            match_id="M001", home_team="A", away_team="B",
            handicap=0, play_type=PlayType.HANDICAP_WDL,
            status=MatchStatus.COMPLETED,
            result=None,
        )
        bet = BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        with pytest.raises(ValueError, match="没有赛果"):
            resolve_bet(match, bet)

    def test_handicap_bet_with_handicap(self):
        """主队让1球，实际2:0 → 调整后1:0 → 选"3"中奖"""
        match = Match(
            match_id="M001", home_team="A", away_team="B",
            handicap=-1, play_type=PlayType.HANDICAP_WDL,
            status=MatchStatus.COMPLETED,
            result=MatchResult(home_score=2, away_score=0),
            sp_values={"3": 2.0, "1": 3.0, "0": 4.0},
        )
        bet = BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        won, sp = resolve_bet(match, bet)
        assert won is True
        assert sp == 2.0

    def test_handicap_bet_draw_scenario(self):
        """主队让1球，实际1:0 → 调整后0:0 → 选"1"中奖"""
        match = Match(
            match_id="M001", home_team="A", away_team="B",
            handicap=-1, play_type=PlayType.HANDICAP_WDL,
            status=MatchStatus.COMPLETED,
            result=MatchResult(home_score=1, away_score=0),
            sp_values={"3": 2.0, "1": 3.5, "0": 4.0},
        )
        bet = BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="1")
        won, sp = resolve_bet(match, bet)
        assert won is True
        assert sp == 3.5
