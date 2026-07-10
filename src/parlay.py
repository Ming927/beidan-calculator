"""串关分解器 - M串N预设表、自由过关组合计算、串关验证。"""

import math
from itertools import combinations
from src.models import ParlayMode, ParlayConfig, PlayType, PLAY_TYPE_MAX_PARLAY


def comb(n: int, k: int) -> int:
    """计算组合数 C(n, k)。"""
    if k < 0 or k > n:
        return 0
    return math.comb(n, k)


# ── M串N 预设表 ──
# key=(M, N), value=参与的串1级别列表（每个级别生成 C(M,k) 个组合）
# 注数 N = sum(C(M, k) for k in levels)

M_N_PRESETS: dict[tuple[int, int], list[int]] = {
    # M串1
    (2, 1): [2],
    (3, 1): [3],
    (4, 1): [4],
    (5, 1): [5],
    (6, 1): [6],
    (7, 1): [7],
    (8, 1): [8],

    # 3场
    (3, 3): [2],               # C(3,2) = 3
    (3, 4): [2, 3],            # 3 + 1 = 4

    # 4场
    (4, 6): [2],               # C(4,2) = 6
    (4, 11): [2, 3, 4],        # 6 + 4 + 1 = 11

    # 5场
    (5, 10): [2],              # C(5,2) = 10
    (5, 26): [2, 3, 4, 5],     # 10 + 10 + 5 + 1 = 26
    (5, 31): [1, 2, 3, 4, 5],  # 含单关: 5 + 10 + 10 + 5 + 1 = 31

    # 6场
    (6, 15): [2],              # C(6,2) = 15
    (6, 63): [1, 2, 3, 4, 5, 6],  # 全部组合

    # 7场
    (7, 21): [2],              # C(7,2) = 21
    (7, 127): [1, 2, 3, 4, 5, 6, 7],  # 全部组合

    # 8场
    (8, 28): [2],              # C(8,2) = 28
    (8, 255): [1, 2, 3, 4, 5, 6, 7, 8],  # 全部组合
}


def get_m_n_preset(m: int, n: int) -> list[int] | None:
    """获取 M串N 预设的参与级别列表。如果不存在返回 None。"""
    return M_N_PRESETS.get((m, n))


def decompose_parlay(config: ParlayConfig, match_indices: list[int]) -> list[list[int]]:
    """将串关配置分解为子票列表。

    每个子票是一个 match_indices 的索引组合，表示该子票包含哪些场次。

    参数:
        config: 串关配置
        match_indices: 场次索引列表，如 [0, 1, 2, 3]

    返回: [[idx1, idx2, ...], ...]，每个子列表表示一个 k串1 的场次组合
    """
    m = len(match_indices)

    if config.mode == ParlayMode.SINGLE:
        # 单场：每场一个子票
        return [[i] for i in match_indices]

    elif config.mode == ParlayMode.M_N:
        # M串N：从预设表查找级别列表
        levels = get_m_n_preset(m, config.n)
        if levels is None:
            raise ValueError(f"不支持的 M串N 组合: {m}串{config.n}")
        result: list[list[int]] = []
        for k in levels:
            for combo in combinations(match_indices, k):
                result.append(list(combo))
        return result

    elif config.mode == ParlayMode.FREE_PARLAY:
        # 自由过关：对每个选中关次生成所有组合
        result = []
        for k in config.selected_levels:
            for combo in combinations(match_indices, k):
                result.append(list(combo))
        return result

    else:
        raise ValueError(f"未知串关模式: {config.mode}")


def validate_parlay(
    match_count: int,
    play_type: PlayType,
    mode: ParlayMode,
    n: int | None = None,
    selected_levels: list[int] | None = None,
) -> list[str]:
    """验证串关配置是否合法。

    返回: 错误信息列表，空列表表示验证通过。
    """
    errors = []
    max_parlay = PLAY_TYPE_MAX_PARLAY[play_type]

    if match_count > 15:
        errors.append(f"最多选择15场比赛，当前选择了{match_count}场")

    if mode == ParlayMode.SINGLE:
        if play_type == PlayType.WIN_LOSE_PASS:
            errors.append("胜负过关不支持单场投注，至少需要3串1")

    elif mode == ParlayMode.M_N:
        if n is None:
            errors.append("M串N模式必须指定n值")
        else:
            levels = get_m_n_preset(match_count, n)
            if levels is None:
                errors.append(f"不支持的M串N组合: {match_count}串{n}")
            else:
                # 检查最大关次是否超出该玩法限制
                if max(levels) > max_parlay:
                    errors.append(
                        f"{play_type.value}最高{max_parlay}串1，"
                        f"但M串N包含{max(levels)}串1"
                    )

    elif mode == ParlayMode.FREE_PARLAY:
        if selected_levels:
            for level in selected_levels:
                if level > max_parlay:
                    errors.append(
                        f"{play_type.value}最高{max_parlay}串1，"
                        f"但选择了{level}串1"
                    )
                if level > match_count:
                    errors.append(f"关次{level}不能大于场次数{match_count}")

    return errors
