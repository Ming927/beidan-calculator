"""奖金计算器 - 核心奖金计算：SP连乘 → 65%返奖 → 500万封顶 → 1万纳税。"""

from src.models import (
    Match, Ticket, BetSelection, ParlayConfig, PlayType,
    SubTicketResult, CalculationResult,
)
from src.result_resolver import resolve_bet
from src.parlay import decompose_parlay, validate_parlay

# ── 北单规则常量 ──

RETURN_RATE = 0.65       # 北单固定返奖率 65%
MAX_PRIZE = 5_000_000    # 单注封顶 500万
TAX_THRESHOLD = 10_000   # 1万元以上需缴税
TAX_RATE = 0.20          # 税率 20%
BASE_AMOUNT = 2.0        # 每注基础金额 2元


def _compute_sub_ticket(
    match_indices: list[int],
    bets: list[BetSelection],
    match_map: dict[str, Match],
    multiplier: int,
) -> SubTicketResult:
    """计算一个子票（M串1）的奖金。

    参数:
        match_indices: 该子票包含的场次索引列表
        bets: 所有投注选项
        match_map: {match_id: Match} 比赛数据
        multiplier: 投注倍数

    返回: SubTicketResult
    """
    sp_product = 1.0
    all_won = True
    match_ids = []

    for idx in match_indices:
        bet = bets[idx]
        match = match_map[bet.match_id]
        match_ids.append(bet.match_id)

        won, sp = resolve_bet(match, bet)
        if not won:
            all_won = False
            break
        sp_product *= sp

    k = len(match_indices)
    combo_desc = f"{k}串1" if k > 1 else "单场"

    if not all_won:
        return SubTicketResult(
            combo_desc=combo_desc,
            match_ids=match_ids,
            sp_product=0.0,
            won=False,
            prize_before_tax=0.0,
            tax=0.0,
            prize_after_tax=0.0,
        )

    # 税前奖金 = 2元 × SP连乘 × 返奖率 × 倍数
    prize_before_tax = BASE_AMOUNT * sp_product * RETURN_RATE * multiplier

    # 500万封顶
    if prize_before_tax > MAX_PRIZE:
        prize_before_tax = MAX_PRIZE

    # 税收：超过1万缴20%
    if prize_before_tax > TAX_THRESHOLD:
        tax = prize_before_tax * TAX_RATE
    else:
        tax = 0.0

    prize_after_tax = prize_before_tax - tax

    return SubTicketResult(
        combo_desc=combo_desc,
        match_ids=match_ids,
        sp_product=round(sp_product, 4),
        won=True,
        prize_before_tax=round(prize_before_tax, 2),
        tax=round(tax, 2),
        prize_after_tax=round(prize_after_tax, 2),
    )


def calculate(ticket: Ticket, match_map: dict[str, Match]) -> CalculationResult:
    """计算一张彩票的总奖金。

    参数:
        ticket: 投注彩票（含投注选项、串关配置、倍数）
        match_map: {match_id: Match} 所有相关比赛的赛果和SP值

    返回: CalculationResult（总奖金、总投入、子票明细）

    异常:
        ValueError: 如果验证失败（混合玩法、不支持的串关等）
    """
    # 验证不能混合不同玩法
    play_types = set(b.play_type for b in ticket.bets)
    if len(play_types) > 1:
        raise ValueError(
            f"同一张彩票不能混合不同玩法: {[pt.value for pt in play_types]}"
        )

    # 验证串关合法性
    errors = validate_parlay(
        len(ticket.bets),
        list(play_types)[0],
        ticket.parlay_config.mode,
        ticket.parlay_config.n,
        ticket.parlay_config.selected_levels,
    )
    if errors:
        raise ValueError("; ".join(errors))

    # 检查 match_map 是否包含所有需要的比赛
    for bet in ticket.bets:
        if bet.match_id not in match_map:
            raise ValueError(f"缺少比赛数据: {bet.match_id}")

    # 分解子票
    match_indices = list(range(len(ticket.bets)))
    sub_ticket_indices = decompose_parlay(ticket.parlay_config, match_indices)

    # 计算每个子票的奖金
    breakdown = []
    for indices in sub_ticket_indices:
        sub_result = _compute_sub_ticket(indices, ticket.bets, match_map, ticket.multiplier)
        breakdown.append(sub_result)

    # 汇总
    total_prize = sum(r.prize_after_tax for r in breakdown)
    total_cost = BASE_AMOUNT * len(breakdown) * ticket.multiplier
    net_profit = round(total_prize - total_cost, 2)

    return CalculationResult(
        ticket_id=ticket.ticket_id,
        total_prize=round(total_prize, 2),
        total_cost=total_cost,
        net_profit=net_profit,
        breakdown=breakdown,
    )


def calculate_batch(
    matches: list[Match],
    play_types: list[PlayType],
    parlay_levels: list[int],
    multiplier: int = 1,
) -> dict:
    """批量计算：对每种玩法，生成 C(n,k) 个组合并计算奖金。

    参数:
        matches: 选中的比赛列表
        play_types: 要计算的玩法列表
        parlay_levels: 串关级别列表，如 [2, 3, 4]
        multiplier: 倍数

    返回:
        {"results": {play_type_name: {
            "total_prize": float, "total_cost": float, "net_profit": float,
            "combos": [{combo_desc, match_ids, won, sp_product, prize_before_tax, tax, prize_after_tax}, ...]
        }}, "grand_total": float}
    """
    from itertools import combinations
    from src.result_resolver import resolve_bet

    results = {}

    for pt in play_types:
        # 筛选该玩法的比赛
        pt_matches = [m for m in matches if m.play_type == pt]
        if len(pt_matches) < 2:
            continue

        n = len(pt_matches)
        match_map = {m.match_id: m for m in pt_matches}
        all_combos = []

        for k in parlay_levels:
            if k > n:
                continue
            for combo_indices in combinations(range(n), k):
                combo_matches = [pt_matches[i] for i in combo_indices]
                match_ids = [m.match_id for m in combo_matches]

                # 计算该组合
                sp_product = 1.0
                all_won = True
                for m in combo_matches:
                    from src.models import BetSelection
                    from src.result_resolver import resolve_bet
                    bet = BetSelection(
                        match_id=m.match_id,
                        play_type=pt,
                        selected_option=list(m.sp_values.keys())[0],
                    )
                    won, sp = resolve_bet(m, bet)
                    if not won:
                        all_won = False
                        break
                    sp_product *= sp

                combo_desc = f"{k}串1"
                if not all_won:
                    all_combos.append({
                        "combo_desc": combo_desc,
                        "match_ids": match_ids,
                        "sp_product": 0.0,
                        "won": False,
                        "prize_before_tax": 0.0,
                        "tax": 0.0,
                        "prize_after_tax": 0.0,
                    })
                    continue

                prize_before_tax = BASE_AMOUNT * sp_product * RETURN_RATE * multiplier
                if prize_before_tax > MAX_PRIZE:
                    prize_before_tax = MAX_PRIZE
                tax = prize_before_tax * TAX_RATE if prize_before_tax > TAX_THRESHOLD else 0.0
                prize_after_tax = prize_before_tax - tax

                all_combos.append({
                    "combo_desc": combo_desc,
                    "match_ids": match_ids,
                    "sp_product": round(sp_product, 4),
                    "won": True,
                    "prize_before_tax": round(prize_before_tax, 2),
                    "tax": round(tax, 2),
                    "prize_after_tax": round(prize_after_tax, 2),
                })

        total_prize = sum(c["prize_after_tax"] for c in all_combos)
        total_cost = BASE_AMOUNT * len(all_combos) * multiplier
        net_profit = round(total_prize - total_cost, 2)

        results[pt.value] = {
            "total_prize": round(total_prize, 2),
            "total_cost": total_cost,
            "net_profit": net_profit,
            "combo_count": len(all_combos),
            "combos": sorted(all_combos, key=lambda c: (c["won"], c["prize_after_tax"]), reverse=True),
        }

    grand_total = sum(r["total_prize"] for r in results.values())

    return {
        "results": results,
        "grand_total": round(grand_total, 2),
        "play_types_count": len(results),
    }
