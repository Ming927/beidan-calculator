"""奖金计算器测试 - 覆盖单关、串关、税收、封顶、延期等场景。"""

import pytest
from src.models import (
    PlayType, MatchStatus, ParlayMode,
    Match, MatchResult, BetSelection, ParlayConfig, Ticket,
)
from src.calculator import calculate, TAX_THRESHOLD, MAX_PRIZE, RETURN_RATE, BASE_AMOUNT


def _make_match(mid, home_score, away_score, sp_3=2.0, handicap=0,
                play_type=PlayType.HANDICAP_WDL, status=MatchStatus.COMPLETED,
                **extra_sp):
    """Helper: 快速创建一场比赛的 Match 对象。"""
    sp = {"3": sp_3}
    sp.update(extra_sp)
    return Match(
        match_id=mid, home_team=f"主{mid}", away_team=f"客{mid}",
        handicap=handicap, play_type=play_type,
        status=status,
        result=MatchResult(home_score=home_score, away_score=away_score),
        sp_values=sp,
    )


def _make_ticket(tid, bets, mode=ParlayMode.SINGLE, m=1, n=None, levels=None, mult=1):
    """Helper: 快速创建 Ticket 对象。"""
    if mode == ParlayMode.M_N:
        config = ParlayConfig(mode=mode, m=m, n=n)
    elif mode == ParlayMode.FREE_PARLAY:
        config = ParlayConfig(mode=mode, m=m, selected_levels=levels)
    else:
        config = ParlayConfig(mode=mode)
    return Ticket(ticket_id=tid, bets=bets, parlay_config=config, multiplier=mult)


class TestCalculateSimple:
    """基础奖金计算"""

    def test_single_win(self):
        """单场中奖：2元 × SP × 65%"""
        matches = {"M1": _make_match("M1", 2, 1, sp_3=2.5)}
        ticket = _make_ticket("T001", [
            BetSelection(match_id="M1", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        ])
        result = calculate(ticket, matches)
        assert result.total_cost == 2.0
        assert result.total_prize == pytest.approx(2 * 2.5 * 0.65, rel=0.01)
        assert len(result.breakdown) == 1
        assert result.breakdown[0].won is True

    def test_single_lose(self):
        """单场未中奖"""
        matches = {"M1": _make_match("M1", 0, 1, sp_3=2.5)}
        ticket = _make_ticket("T001", [
            BetSelection(match_id="M1", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        ])
        result = calculate(ticket, matches)
        assert result.total_prize == 0.0
        assert result.breakdown[0].won is False

    def test_3_1_parlay_win(self):
        """3串1全中"""
        matches = {
            "M1": _make_match("M1", 2, 1, sp_3=2.0),
            "M2": _make_match("M2", 2, 1, sp_3=3.0),
            "M3": _make_match("M3", 2, 1, sp_3=1.8),
        }
        ticket = _make_ticket("T002", [
            BetSelection(match_id=f"M{i}", play_type=PlayType.HANDICAP_WDL, selected_option="3")
            for i in range(1, 4)
        ], mode=ParlayMode.M_N, m=3, n=1)
        result = calculate(ticket, matches)
        expected = 2 * 2.0 * 3.0 * 1.8 * RETURN_RATE
        assert result.total_prize == pytest.approx(expected, rel=0.01)

    def test_3_1_parlay_one_lose(self):
        """3串1错一场 = 全不中"""
        matches = {
            "M1": _make_match("M1", 2, 1, sp_3=2.0),
            "M2": _make_match("M2", 1, 2, sp_3=3.0),  # 主队输 -> 选3不中
            "M3": _make_match("M3", 2, 1, sp_3=1.8),
        }
        ticket = _make_ticket("T003", [
            BetSelection(match_id=f"M{i}", play_type=PlayType.HANDICAP_WDL, selected_option="3")
            for i in range(1, 4)
        ], mode=ParlayMode.M_N, m=3, n=1)
        result = calculate(ticket, matches)
        assert result.total_prize == 0.0


class TestParlayCombinations:
    """串关组合测试"""

    def test_3_3_parlay_one_wrong(self):
        """3串3 = 3个2串1，错1场仍有1注中奖"""
        matches = {
            "M1": _make_match("M1", 2, 1, sp_3=2.0),
            "M2": _make_match("M2", 1, 2, sp_3=3.0),  # 这场猜错
            "M3": _make_match("M3", 2, 1, sp_3=1.8),
        }
        ticket = _make_ticket("T004", [
            BetSelection(match_id=f"M{i}", play_type=PlayType.HANDICAP_WDL, selected_option="3")
            for i in range(1, 4)
        ], mode=ParlayMode.M_N, m=3, n=3)
        result = calculate(ticket, matches)
        assert result.total_cost == 6.0  # 3注 × 2元
        winning = [b for b in result.breakdown if b.won]
        assert len(winning) == 1
        assert set(winning[0].match_ids) == {"M1", "M3"}

    def test_4_11_all_correct(self):
        """4串11全部猜对"""
        matches = {
            f"M{i}": _make_match(f"M{i}", 2, 1, sp_3=2.0)
            for i in range(1, 5)
        }
        ticket = _make_ticket("T005", [
            BetSelection(match_id=f"M{i}", play_type=PlayType.HANDICAP_WDL, selected_option="3")
            for i in range(1, 5)
        ], mode=ParlayMode.M_N, m=4, n=11)
        result = calculate(ticket, matches)
        assert result.total_cost == 22.0  # 11注 × 2元
        assert len(result.breakdown) == 11
        assert all(b.won for b in result.breakdown)
        assert result.total_prize > 0


class TestSpecialCases:
    """特殊情况"""

    def test_postponed_match_in_parlay(self):
        """延期比赛在串关中 SP=1.0"""
        matches = {
            "M1": Match(
                match_id="M1", home_team="A", away_team="B",
                handicap=0, play_type=PlayType.HANDICAP_WDL,
                status=MatchStatus.POSTPONED,
            ),
            "M2": _make_match("M2", 2, 1, sp_3=3.0),
        }
        ticket = _make_ticket("T006", [
            BetSelection(match_id="M1", play_type=PlayType.HANDICAP_WDL, selected_option="3"),
            BetSelection(match_id="M2", play_type=PlayType.HANDICAP_WDL, selected_option="3"),
        ], mode=ParlayMode.M_N, m=2, n=1)
        result = calculate(ticket, matches)
        expected = 2 * 1.0 * 3.0 * RETURN_RATE  # SP = 1.0 × 3.0
        assert result.total_prize == pytest.approx(expected, rel=0.01)

    def test_multiplier(self):
        """倍数计算"""
        matches = {"M1": _make_match("M1", 2, 1, sp_3=2.5)}
        ticket = _make_ticket("T007", [
            BetSelection(match_id="M1", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        ], mult=10)
        result = calculate(ticket, matches)
        assert result.total_cost == 20.0  # 2元 × 10倍
        assert result.total_prize == pytest.approx(2 * 2.5 * 0.65 * 10, rel=0.01)

    def test_tax_apply(self):
        """奖金超过1万需缴20%个税"""
        matches = {"M1": _make_match("M1", 2, 1, sp_3=10000.0)}
        ticket = _make_ticket("T008", [
            BetSelection(match_id="M1", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        ])
        result = calculate(ticket, matches)
        before_tax = 2 * 10000 * RETURN_RATE  # 13000
        assert result.breakdown[0].prize_before_tax == pytest.approx(before_tax)
        assert result.breakdown[0].tax == pytest.approx(before_tax * 0.2)
        assert result.breakdown[0].prize_after_tax == pytest.approx(before_tax * 0.8)

    def test_max_cap(self):
        """500万封顶"""
        matches = {"M1": _make_match("M1", 2, 1, sp_3=5000000.0)}
        ticket = _make_ticket("T009", [
            BetSelection(match_id="M1", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        ])
        result = calculate(ticket, matches)
        assert result.breakdown[0].prize_before_tax == MAX_PRIZE

    def test_no_tax_below_threshold(self):
        """奖金低于1万不缴税"""
        matches = {"M1": _make_match("M1", 2, 1, sp_3=5000.0)}  # 2*5000*0.65=6500 < 10000
        ticket = _make_ticket("T010", [
            BetSelection(match_id="M1", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        ])
        result = calculate(ticket, matches)
        assert result.breakdown[0].tax == 0.0


class TestValidation:
    """输入验证"""

    def test_mixed_play_types_rejected(self):
        """混合玩法应被拒绝"""
        matches = {
            "M1": _make_match("M1", 2, 1, sp_3=2.0),
            "M2": _make_match("M2", 1, 1, sp_3=3.0, play_type=PlayType.TOTAL_GOALS),
        }
        ticket = Ticket(
            ticket_id="T011",
            bets=[
                BetSelection(match_id="M1", play_type=PlayType.HANDICAP_WDL, selected_option="3"),
                BetSelection(match_id="M2", play_type=PlayType.TOTAL_GOALS, selected_option="2"),
            ],
            parlay_config=ParlayConfig(mode=ParlayMode.M_N, m=2, n=1),
        )
        with pytest.raises(ValueError, match="不能混合不同玩法"):
            calculate(ticket, matches)

    def test_missing_match_data(self):
        """缺少比赛数据"""
        matches = {"M1": _make_match("M1", 2, 1, sp_3=2.0)}
        ticket = _make_ticket("T012", [
            BetSelection(match_id="M1", play_type=PlayType.HANDICAP_WDL, selected_option="3"),
            BetSelection(match_id="M2", play_type=PlayType.HANDICAP_WDL, selected_option="3"),
        ], mode=ParlayMode.M_N, m=2, n=1)
        with pytest.raises(ValueError, match="缺少比赛数据"):
            calculate(ticket, matches)

    def test_net_profit_calculation(self):
        """净收益 = 总奖金 - 总投入"""
        matches = {"M1": _make_match("M1", 2, 1, sp_3=2.5)}
        ticket = _make_ticket("T013", [
            BetSelection(match_id="M1", play_type=PlayType.HANDICAP_WDL, selected_option="3")
        ])
        result = calculate(ticket, matches)
        expected_profit = result.total_prize - result.total_cost
        assert result.net_profit == pytest.approx(expected_profit)


class TestFreeParlay:
    """自由过关测试"""

    def test_free_parlay_4m_2_and_3(self):
        """4场比赛，选2关+3关"""
        matches = {
            f"M{i}": _make_match(f"M{i}", 2, 1, sp_3=2.0)
            for i in range(1, 5)
        }
        ticket = _make_ticket("T014", [
            BetSelection(match_id=f"M{i}", play_type=PlayType.HANDICAP_WDL, selected_option="3")
            for i in range(1, 5)
        ], mode=ParlayMode.FREE_PARLAY, m=4, levels=[2, 3])
        result = calculate(ticket, matches)
        # C(4,2) + C(4,3) = 6 + 4 = 10 注
        assert result.total_cost == 20.0
        assert len(result.breakdown) == 10
        assert all(b.won for b in result.breakdown)
