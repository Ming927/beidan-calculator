"""串关分解器测试 - M串N预设、自由过关、串关验证。"""

import pytest
from src.models import ParlayMode, ParlayConfig, PlayType
from src.parlay import (
    comb, decompose_parlay, validate_parlay,
    M_N_PRESETS, get_m_n_preset,
)


class TestComb:
    """组合数计算"""

    def test_comb_basic(self):
        assert comb(5, 2) == 10    # C(5,2)
        assert comb(5, 3) == 10    # C(5,3)
        assert comb(5, 5) == 1     # C(5,5)
        assert comb(8, 4) == 70    # C(8,4)
        assert comb(15, 1) == 15

    def test_comb_edge_cases(self):
        assert comb(1, 1) == 1
        assert comb(10, 0) == 1
        assert comb(10, 11) == 0
        assert comb(10, -1) == 0


class TestMNPresents:
    """M串N 预设表"""

    def test_4_11_levels(self):
        """4串11 = [2, 3, 4] 级别"""
        levels = get_m_n_preset(4, 11)
        assert levels is not None
        assert levels == [2, 3, 4]
        from src.parlay import comb
        total = sum(comb(4, k) for k in levels)
        assert total == 11  # 6 + 4 + 1

    def test_3_3_levels(self):
        """3串3 = [2] 级别"""
        levels = get_m_n_preset(3, 3)
        assert levels is not None
        assert levels == [2]

    def test_3_4_levels(self):
        """3串4 = [2, 3] 级别"""
        levels = get_m_n_preset(3, 4)
        assert levels is not None
        assert levels == [2, 3]

    def test_5_10_decomposition(self):
        """5串10 = 10个2串1"""
        combos = get_m_n_preset(5, 10)
        assert combos is not None
        assert combos == [2]  # 只有2串1级别

    def test_all_presets_valid(self):
        """所有预设的注数 = sum(C(m, k) for k in levels)"""
        for (m, n), levels in M_N_PRESETS.items():
            total = sum(comb(m, k) for k in levels)
            assert total == n, f"{m}串{n}: levels={levels}, 计算注数={total}, 期望={n}"

    def test_nonexistent_preset(self):
        assert get_m_n_preset(10, 999) is None


class TestDecomposeParlay:
    """串关分解"""

    def test_single_mode(self):
        """单场模式：每个比赛单独一注"""
        cfg = ParlayConfig(mode=ParlayMode.SINGLE)
        indices = list(range(3))
        result = decompose_parlay(cfg, indices)
        assert len(result) == 3
        assert result == [[0], [1], [2]]

    def test_m_n_mode_3x3(self):
        """3串3 = 3个2串1"""
        cfg = ParlayConfig(mode=ParlayMode.M_N, m=3, n=3)
        indices = [0, 1, 2]
        result = decompose_parlay(cfg, indices)
        assert len(result) == 3
        assert sorted(result) == [[0, 1], [0, 2], [1, 2]]

    def test_m_n_mode_3x4(self):
        """3串4 = 3个2串1 + 1个3串1"""
        cfg = ParlayConfig(mode=ParlayMode.M_N, m=3, n=4)
        indices = [0, 1, 2]
        result = decompose_parlay(cfg, indices)
        assert len(result) == 4

    def test_free_parlay_mode(self):
        """4场选2关+3关: C(4,2) + C(4,3) = 6 + 4 = 10"""
        cfg = ParlayConfig(mode=ParlayMode.FREE_PARLAY, m=4, selected_levels=[2, 3])
        indices = [0, 1, 2, 3]
        result = decompose_parlay(cfg, indices)
        assert len(result) == 10

    def test_m_1_mode(self):
        """5串1: 只有1种组合"""
        cfg = ParlayConfig(mode=ParlayMode.M_N, m=5, n=1)
        indices = [0, 1, 2, 3, 4]
        result = decompose_parlay(cfg, indices)
        assert len(result) == 1
        assert result[0] == [0, 1, 2, 3, 4]

    def test_free_parlay_single_level(self):
        """自由过关选单关次: 8场选4关 = C(8,4) = 70"""
        cfg = ParlayConfig(mode=ParlayMode.FREE_PARLAY, m=8, selected_levels=[4])
        indices = list(range(8))
        result = decompose_parlay(cfg, indices)
        assert len(result) == 70

    def test_invalid_m_n_raises(self):
        """不支持的M串N组合"""
        cfg = ParlayConfig(mode=ParlayMode.M_N, m=10, n=999)
        with pytest.raises(ValueError, match="不支持"):
            decompose_parlay(cfg, [0, 1, 2, 3, 5, 6, 7, 8, 9, 10])


class TestValidateParlay:
    """串关验证"""

    def test_valid_single(self):
        errors = validate_parlay(1, PlayType.HANDICAP_WDL, ParlayMode.SINGLE, None)
        assert len(errors) == 0

    def test_valid_m_n(self):
        errors = validate_parlay(4, PlayType.HANDICAP_WDL, ParlayMode.M_N, n=11)
        assert len(errors) == 0

    def test_valid_free_parlay(self):
        errors = validate_parlay(5, PlayType.HANDICAP_WDL, ParlayMode.FREE_PARLAY,
                                 selected_levels=[2, 3])
        assert len(errors) == 0

    def test_too_many_matches(self):
        errors = validate_parlay(16, PlayType.HANDICAP_WDL, ParlayMode.M_N, n=1)
        assert any("最多选择15场" in e for e in errors)

    def test_score_max_3(self):
        """比分最高3串1"""
        errors = validate_parlay(5, PlayType.CORRECT_SCORE, ParlayMode.M_N, n=1)
        assert any("最高" in e for e in errors) or any("不支持" in e for e in errors)

    def test_free_parlay_level_too_high(self):
        """比分选了4串1（超过最高3串1限制）"""
        errors = validate_parlay(5, PlayType.CORRECT_SCORE, ParlayMode.FREE_PARLAY,
                                 selected_levels=[2, 4])
        assert any("最高3串1" in e for e in errors)

    def test_level_greater_than_match_count(self):
        errors = validate_parlay(3, PlayType.HANDICAP_WDL, ParlayMode.FREE_PARLAY,
                                 selected_levels=[4])
        assert any("不能大于场次数" in e for e in errors)

    def test_win_lose_pass_no_single(self):
        """胜负过关不支持单场"""
        errors = validate_parlay(1, PlayType.WIN_LOSE_PASS, ParlayMode.SINGLE)
        assert any("不支持单场" in e for e in errors)
