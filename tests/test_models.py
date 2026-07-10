"""数据模型测试。"""

import pytest
from src.models import (
    PlayType, MatchStatus, ParlayMode,
    Match, MatchResult, BetSelection, ParlayConfig, Ticket,
    SubTicketResult, CalculationResult,
    PLAY_TYPE_OPTIONS, PLAY_TYPE_MAX_PARLAY,
)


class TestPlayType:
    """PlayType 枚举测试"""

    def test_all_six_types_exist(self):
        types = [t for t in PlayType]
        assert len(types) == 6

    def test_each_type_has_options(self):
        for pt in PlayType:
            assert pt in PLAY_TYPE_OPTIONS
            assert len(PLAY_TYPE_OPTIONS[pt]) >= 2

    def test_max_parlay_limits(self):
        assert PLAY_TYPE_MAX_PARLAY[PlayType.HANDICAP_WDL] == 15
        assert PLAY_TYPE_MAX_PARLAY[PlayType.TOTAL_GOALS] == 6
        assert PLAY_TYPE_MAX_PARLAY[PlayType.OVER_UNDER_ODD_EVEN] == 6
        assert PLAY_TYPE_MAX_PARLAY[PlayType.HALF_FULL_WDL] == 6
        assert PLAY_TYPE_MAX_PARLAY[PlayType.CORRECT_SCORE] == 3
        assert PLAY_TYPE_MAX_PARLAY[PlayType.WIN_LOSE_PASS] == 15


class TestMatch:
    """Match 数据类测试"""

    def test_create_match_with_handicap(self):
        m = Match(
            match_id="M001",
            home_team="曼联",
            away_team="利物浦",
            handicap=-1,
            play_type=PlayType.HANDICAP_WDL,
            status=MatchStatus.PENDING,
        )
        assert m.handicap == -1
        assert m.result is None

    def test_create_match_with_result(self):
        m = Match(
            match_id="M001",
            home_team="曼联",
            away_team="利物浦",
            handicap=0,
            play_type=PlayType.CORRECT_SCORE,
            status=MatchStatus.COMPLETED,
            result=MatchResult(home_score=2, away_score=1),
            sp_values={"2:1": 8.5, "1:0": 6.0},
        )
        assert m.result.home_score == 2
        assert m.sp_values["2:1"] == 8.5

    def test_total_goals_property(self):
        r = MatchResult(home_score=3, away_score=2)
        assert r.total_goals == 5


class TestBetSelection:
    """BetSelection 验证测试"""

    def test_valid_option(self):
        b = BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        assert b.selected_option == "3"

    def test_invalid_option_raises(self):
        with pytest.raises(ValueError, match="不是"):
            BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="99")


class TestParlayConfig:
    """ParlayConfig 验证测试"""

    def test_single_bet_mode(self):
        cfg = ParlayConfig(mode=ParlayMode.SINGLE)
        assert cfg.mode == ParlayMode.SINGLE

    def test_m_n_mode(self):
        cfg = ParlayConfig(mode=ParlayMode.M_N, m=4, n=11)
        assert cfg.m == 4
        assert cfg.n == 11

    def test_free_parlay_mode(self):
        cfg = ParlayConfig(mode=ParlayMode.FREE_PARLAY, m=8, selected_levels=[2, 4, 8])
        assert cfg.selected_levels == [2, 4, 8]

    def test_free_parlay_rejects_invalid_level(self):
        with pytest.raises(ValueError):
            ParlayConfig(mode=ParlayMode.FREE_PARLAY, m=5, selected_levels=[6])

    def test_m_n_needs_n(self):
        with pytest.raises(ValueError, match="必须提供 n"):
            ParlayConfig(mode=ParlayMode.M_N, m=4)


class TestTicket:
    """Ticket 数据类测试"""

    def test_create_valid_ticket(self):
        ticket = Ticket(
            ticket_id="T001",
            bets=[
                BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="3"),
                BetSelection(match_id="M002", play_type=PlayType.TOTAL_GOALS, selected_option="2"),
            ],
            parlay_config=ParlayConfig(mode=ParlayMode.SINGLE),
            multiplier=5,
        )
        assert len(ticket.bets) == 2
        assert ticket.multiplier == 5


class TestCalculationResult:
    """CalculationResult 数据类测试"""

    def test_breakdown_summary(self):
        r = CalculationResult(
            ticket_id="T001",
            total_prize=100.0,
            total_cost=10.0,
            net_profit=90.0,
            breakdown=[
                SubTicketResult(
                    combo_desc="2串1",
                    match_ids=["M001", "M002"],
                    sp_product=76.92,
                    won=True,
                    prize_before_tax=100.0,
                    tax=0.0,
                    prize_after_tax=100.0,
                )
            ],
        )
        assert r.net_profit == 90.0
        assert r.total_prize == 100.0
