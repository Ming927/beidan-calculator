"""北单数据模型定义 - 枚举、数据类、常量。"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


class PlayType(Enum):
    """7种北单玩法类型"""
    HANDICAP_WDL = "让球胜平负"
    TOTAL_GOALS = "总进球数"
    OVER_UNDER_ODD_EVEN = "上下盘单双数"
    HALF_FULL_WDL = "半全场胜平负"
    CORRECT_SCORE = "比分"
    WIN_LOSE_PASS = "胜负过关"
    SECOND_HALF_SCORE = "下半场比分"


class MatchStatus(Enum):
    """比赛状态"""
    PENDING = "pending"
    COMPLETED = "completed"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class ParlayMode(Enum):
    """串关模式"""
    SINGLE = "single"           # 单场
    M_N = "m_n"                 # M串N
    FREE_PARLAY = "free_parlay" # 自由过关


# ── 每种玩法的可选选项 ──

PLAY_TYPE_OPTIONS: dict[PlayType, list[str]] = {
    PlayType.HANDICAP_WDL: ["3", "1", "0"],
    PlayType.TOTAL_GOALS: ["0", "1", "2", "3", "4", "5", "6", "7+"],
    PlayType.OVER_UNDER_ODD_EVEN: ["上单", "上双", "下单", "下双"],
    PlayType.HALF_FULL_WDL: [
        "3-3", "3-1", "3-0", "1-3", "1-1", "1-0", "0-3", "0-1", "0-0",
    ],
    PlayType.CORRECT_SCORE: [
        "1:0", "2:0", "2:1", "3:0", "3:1", "3:2", "4:0", "4:1", "4:2",
        "0:0", "1:1", "2:2", "3:3",
        "0:1", "0:2", "1:2", "0:3", "1:3", "2:3", "0:4", "1:4", "2:4",
        "胜其他", "平其他", "负其他",
    ],
    PlayType.WIN_LOSE_PASS: ["3", "0"],
    PlayType.SECOND_HALF_SCORE: [
        "1:0", "2:0", "2:1", "3:0", "3:1", "3:2", "4:0", "4:1", "4:2",
        "0:0", "1:1", "2:2", "3:3",
        "0:1", "0:2", "1:2", "0:3", "1:3", "2:3", "0:4", "1:4", "2:4",
        "胜其他", "平其他", "负其他",
    ],
}

# ── 每种玩法的最高串关数 ──

PLAY_TYPE_MAX_PARLAY: dict[PlayType, int] = {
    PlayType.HANDICAP_WDL: 15,
    PlayType.TOTAL_GOALS: 6,
    PlayType.OVER_UNDER_ODD_EVEN: 6,
    PlayType.HALF_FULL_WDL: 6,
    PlayType.CORRECT_SCORE: 3,
    PlayType.WIN_LOSE_PASS: 15,
    PlayType.SECOND_HALF_SCORE: 3,
}


# ── 数据类 ──

@dataclass
class MatchResult:
    """赛果（90分钟常规时间+伤停补时，不含加时/点球）"""
    home_score: int
    away_score: int
    half_home_score: int = 0
    half_away_score: int = 0
    second_half_home_score: int = 0
    second_half_away_score: int = 0

    @property
    def total_goals(self) -> int:
        return self.home_score + self.away_score


@dataclass
class Match:
    """单场比赛"""
    match_id: str
    home_team: str
    away_team: str
    handicap: int                          # 让球数(主队让球为负,受让为正), 0=无让球
    play_type: PlayType
    status: MatchStatus = MatchStatus.PENDING
    result: Optional[MatchResult] = None
    sp_values: dict[str, float] = field(default_factory=dict)


@dataclass
class BetSelection:
    """单场比赛的一个投注选项"""
    match_id: str
    play_type: PlayType
    selected_option: str

    def __post_init__(self):
        options = PLAY_TYPE_OPTIONS.get(self.play_type, [])
        if self.selected_option not in options:
            raise ValueError(
                f"'{self.selected_option}' 不是 {self.play_type.value} 的有效选项，"
                f"可选: {options}"
            )


@dataclass
class ParlayConfig:
    """串关配置"""
    mode: ParlayMode
    m: int = 1                           # 所选比赛场次数
    n: Optional[int] = None              # M串N 中的 N
    selected_levels: Optional[list[int]] = None  # 自由过关选中的关次

    def __post_init__(self):
        if self.mode == ParlayMode.M_N:
            if self.n is None:
                raise ValueError("M串N模式必须提供 n 值")
        elif self.mode == ParlayMode.FREE_PARLAY:
            if not self.selected_levels:
                raise ValueError("自由过关模式必须提供 selected_levels")
            for level in self.selected_levels:
                if level > self.m:
                    raise ValueError(f"关次 {level} 不能大于场次数 {self.m}")


@dataclass
class Ticket:
    """一张投注彩票"""
    ticket_id: str
    bets: list[BetSelection]
    parlay_config: ParlayConfig
    multiplier: int = 1
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SubTicketResult:
    """单个子票（一注M串1）的奖金结果"""
    combo_desc: str               # 如 "3串1"
    match_ids: list[str]
    sp_product: float             # SP连乘积
    won: bool                     # 是否中奖
    prize_before_tax: float       # 税前奖金
    tax: float                    # 税金
    prize_after_tax: float        # 税后奖金


@dataclass
class CalculationResult:
    """整张彩票的奖金汇总结果"""
    ticket_id: str
    total_prize: float            # 总奖金（税后）
    total_cost: float             # 总投入
    net_profit: float             # 净收益
    breakdown: list[SubTicketResult]
