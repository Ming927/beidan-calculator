"""赛果判定器 - 根据玩法和实际赛果判定投注选项是否中奖。"""

from src.models import (
    PlayType, Match, BetSelection, MatchStatus,
)

# 标准比分模式（不含"其他"）
SCORE_PATTERNS = {
    "1:0", "2:0", "2:1", "3:0", "3:1", "3:2",
    "4:0", "4:1", "4:2",
    "0:0", "1:1", "2:2", "3:3",
    "0:1", "0:2", "1:2", "0:3", "1:3", "2:3",
    "0:4", "1:4", "2:4",
}


def resolve_handicap_wdl(home_score: int, away_score: int, handicap: int) -> str:
    """解析让球胜平负结果。

    handicap: 主队让球数。正数=主队受让, 负数=主队让球。
    调整后比分 = (home_score + handicap) vs away_score
    """
    adjusted = home_score + handicap
    if adjusted > away_score:
        return "3"
    elif adjusted == away_score:
        return "1"
    else:
        return "0"


def resolve_total_goals(home_score: int, away_score: int) -> str:
    """解析总进球数结果。7球及以上统一归为'7+'。"""
    total = home_score + away_score
    if total >= 7:
        return "7+"
    return str(total)


def resolve_over_under_odd_even(home_score: int, away_score: int) -> str:
    """解析上下盘单双数结果。

    上盘: 总进球数 >= 3
    下盘: 总进球数 < 3
    单双: 总进球数的奇偶性
    """
    total = home_score + away_score
    pan = "上" if total >= 3 else "下"
    parity = "单" if total % 2 == 1 else "双"
    return f"{pan}{parity}"


def resolve_half_full_wdl(
    half_home: int, half_away: int, full_home: int, full_away: int
) -> str:
    """解析半全场胜平负结果。格式: "半场-全场", 如 "3-1" 表示半场胜全场平。"""

    def _wdl(h: int, a: int) -> str:
        if h > a:
            return "3"
        elif h == a:
            return "1"
        else:
            return "0"

    return f"{_wdl(half_home, half_away)}-{_wdl(full_home, full_away)}"


def resolve_correct_score(home_score: int, away_score: int) -> str:
    """解析比分结果。不在标准模式中的归为"胜其他/平其他/负其他"。"""
    key = f"{home_score}:{away_score}"
    if key in SCORE_PATTERNS:
        return key
    if home_score > away_score:
        return "胜其他"
    elif home_score == away_score:
        return "平其他"
    else:
        return "负其他"


def resolve_win_lose_pass(home_score: int, away_score: int) -> str:
    """解析胜负过关结果。无平局，平局或主负均算'0'。"""
    if home_score > away_score:
        return "3"
    else:
        return "0"


def resolve_bet(match: Match, bet: BetSelection) -> tuple[bool, float]:
    """判定投注是否中奖。

    参数:
        match: 比赛对象（含赛果、状态、SP值）
        bet: 投注选项

    返回: (是否中奖, SP值)
        - 延期/取消比赛: 始终返回 (True, 1.0)
        - 中奖: 返回 (True, 对应选项的SP值)
        - 未中奖: 返回 (False, 0.0)
    """
    play_type = bet.play_type

    # 延期或取消的比赛：所有选项都算中，SP = 1.0
    if match.status in (MatchStatus.POSTPONED, MatchStatus.CANCELLED):
        return True, 1.0

    if match.result is None:
        raise ValueError(f"比赛 {match.match_id} 状态为 {match.status.value} 但没有赛果数据")

    r = match.result

    # 根据玩法类型计算实际赛果
    if play_type == PlayType.HANDICAP_WDL:
        actual = resolve_handicap_wdl(r.home_score, r.away_score, match.handicap)
    elif play_type == PlayType.TOTAL_GOALS:
        actual = resolve_total_goals(r.home_score, r.away_score)
    elif play_type == PlayType.OVER_UNDER_ODD_EVEN:
        actual = resolve_over_under_odd_even(r.home_score, r.away_score)
    elif play_type == PlayType.HALF_FULL_WDL:
        actual = resolve_half_full_wdl(
            r.half_home_score, r.half_away_score,
            r.home_score, r.away_score,
        )
    elif play_type == PlayType.CORRECT_SCORE:
        actual = resolve_correct_score(r.home_score, r.away_score)
    elif play_type == PlayType.WIN_LOSE_PASS:
        actual = resolve_win_lose_pass(r.home_score, r.away_score)
    elif play_type == PlayType.SECOND_HALF_SCORE:
        actual = resolve_correct_score(
            r.second_half_home_score, r.second_half_away_score
        )
    else:
        raise ValueError(f"未知玩法类型: {play_type}")

    won = (actual == bet.selected_option)
    sp = match.sp_values.get(bet.selected_option, 0.0) if won else 0.0
    return won, sp
