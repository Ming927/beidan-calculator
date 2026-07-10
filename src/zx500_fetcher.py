"""500.com 北单开奖数据解析器。

从 https://zx.500.com/zqdc/kaijiang.php?expect=<期号> 抓取北单开奖数据。
每场比赛包含5种玩法的彩果和 SP 值。

数据结构:
    每行 22 列:
    [场次, 赛事, 时间, 主队, 让球, 客队, 比分(半:全), 空,
     让球胜平负-彩果, SP, 空,
     总进球数-彩果, SP, 空,
     比分-彩果, SP, 空,
     上下单双-彩果, SP, 空,
     半全场-彩果, SP]

使用:
    from src.zx500_fetcher import fetch_issue
    data = fetch_issue("26073")  # → {"issue":"26073", "matches":[...]}
"""

import re
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.models import PlayType, MatchStatus, Match, MatchResult

logger = logging.getLogger(__name__)

# 500.com 列索引 → (玩法名, 彩果列, SP列)
_COLUMN_MAP = [
    ("让球胜平负", 8, 9),
    ("总进球数",   11, 12),
    ("比分",       14, 15),
    ("上下单双",   17, 18),
    ("半全场",     20, 21),
]

# 500.com 玩法名 → PlayType 枚举
_PLAY_TYPE_MAP = {
    "让球胜平负": PlayType.HANDICAP_WDL,
    "总进球数":   PlayType.TOTAL_GOALS,
    "比分":       PlayType.CORRECT_SCORE,
    "上下单双":   PlayType.OVER_UNDER_ODD_EVEN,
    "半全场":     PlayType.HALF_FULL_WDL,
}

# 比分解析正则: (0:1) 3:2
_SCORE_RE = re.compile(r'\((\d+):(\d+)\)\s*(\d+):(\d+)')

# 标准比分模式（与 models.py 中 PLAY_TYPE_OPTIONS 一致）
_STANDARD_SCORES = {
    "1:0", "2:0", "2:1", "3:0", "3:1", "3:2", "4:0", "4:1", "4:2",
    "0:0", "1:1", "2:2", "3:3",
    "0:1", "0:2", "1:2", "0:3", "1:3", "2:3", "0:4", "1:4", "2:4",
}


def _normalize_score(score_text: str) -> str:
    """将非标准比分映射为 胜其他/平其他/负其他。"""
    if score_text in _STANDARD_SCORES:
        return score_text
    # 尝试解析 "5:1" 格式
    parts = score_text.split(":")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        h, a = int(parts[0]), int(parts[1])
        if h > a:
            return "胜其他"
        elif h == a:
            return "平其他"
        else:
            return "负其他"
    return score_text

BASE_URL = "https://zx.500.com/zqdc/kaijiang.php"


def fetch_issue(expect: str, timeout: int = 15) -> dict:
    """拉取指定期号的北单开奖数据。

    返回:
        {"success": True, "issue": "26073", "matches": [...]}
        {"success": False, "error": "..."}
    """
    try:
        url = f"{BASE_URL}?expect={expect}"
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        resp.raise_for_status()
        resp.encoding = _detect_encoding(resp)
        return _parse_html(resp.text, expect)
    except requests.RequestException as e:
        logger.warning("获取期号 %s 失败: %s", expect, e)
        return {"success": False, "error": f"网络请求失败: {e}"}
    except Exception as e:
        logger.error("解析期号 %s 异常: %s", expect, e)
        return {"success": False, "error": f"解析失败: {e}"}


def _detect_encoding(resp) -> str:
    """检测编码（500.com 使用 GBK）。"""
    if resp.encoding and resp.encoding.lower() not in ('iso-8859-1', 'latin-1', 'utf-8'):
        return resp.encoding
    match = re.search(rb'charset=["\']?([\w-]+)', resp.content[:2048])
    if match:
        return match.group(1).decode('ascii')
    return 'gbk'


def _parse_html(html: str, expect: str) -> dict:
    """解析 500.com 开奖页面 HTML。"""
    soup = BeautifulSoup(html, 'lxml')
    table = soup.find('table', class_='ld_table')
    if not table:
        return {"success": False, "error": "未找到数据表格，请检查期号是否正确"}

    rows = table.find_all('tr')
    matches = []

    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 22:
            continue

        # 解析比分: "(0:1) 3:2" → 半场(0,1), 全场(3,2)
        score_text = cells[6].get_text(strip=True)
        score_match = _SCORE_RE.search(score_text)
        half_home, half_away = 0, 0
        full_home, full_away = 0, 0
        if score_match:
            half_home = int(score_match.group(1))
            half_away = int(score_match.group(2))
            full_home = int(score_match.group(3))
            full_away = int(score_match.group(4))

        match_id = cells[0].get_text(strip=True)
        handicap_raw = cells[4].get_text(strip=True)

        try:
            handicap = int(handicap_raw)
        except ValueError:
            handicap = 0

        # 提取每种玩法的彩果和 SP
        plays = {}
        for play_name, result_col, sp_col in _COLUMN_MAP:
            result_text = cells[result_col].get_text(strip=True)
            sp_text = cells[sp_col].get_text(strip=True)
            try:
                sp_val = float(sp_text)
            except ValueError:
                sp_val = 0.0
            # 标准化结果名，映射 500.com 中文 → 系统内部码
            normalized = result_text
            if play_name == "让球胜平负":
                normalized = {"胜": "3", "平": "1", "负": "0"}.get(result_text, result_text)
            elif play_name == "半全场":
                normalized = {
                    "胜-胜": "3-3", "胜-平": "3-1", "胜-负": "3-0",
                    "平-胜": "1-3", "平-平": "1-1", "平-负": "1-0",
                    "负-胜": "0-3", "负-平": "0-1", "负-负": "0-0",
                }.get(result_text, result_text)
            elif play_name == "总进球数":
                try:
                    n = int(result_text)
                    normalized = "7+" if n >= 7 else str(n)
                except ValueError:
                    normalized = result_text
            elif play_name == "比分" or play_name == "下半场比分":
                normalized = _normalize_score(result_text)
            plays[play_name] = {"result": normalized, "sp": sp_val}

        matches.append({
            "id": match_id,
            "league": cells[1].get_text(strip=True),
            "time": cells[2].get_text(strip=True),
            "home": cells[3].get_text(strip=True),
            "away": cells[5].get_text(strip=True),
            "handicap": handicap,
            "score_half": (half_home, half_away),
            "score_full": (full_home, full_away),
            "score_text": score_text,
            "plays": plays,
        })

    if not matches:
        return {"success": False, "error": "未解析到比赛数据"}

    return {"success": True, "issue": expect, "matches": matches, "count": len(matches)}


def build_match_objects(issue_data: dict, play_type_name: str) -> list[Match]:
    """将 fetch_issue 返回的数据转为指定玩法的 Match 对象列表。

    参数:
        issue_data: fetch_issue() 的返回值
        play_type_name: 玩法中文名，如 "让球胜平负"

    返回:
        list[Match] — 可直接传入 calculator.calculate()
    """
    if not issue_data.get("success"):
        return []

    pt = _PLAY_TYPE_MAP.get(play_type_name)
    if pt is None:
        return []

    result = []
    for m in issue_data["matches"]:
        play = m["plays"].get(play_type_name)
        if not play or play["sp"] <= 0:
            continue

        # 确定赛果
        score_half = m["score_half"]
        score_full = m["score_full"]
        second_half_home = score_full[0] - score_half[0]
        second_half_away = score_full[1] - score_half[1]

        match = Match(
            match_id=m["id"],
            home_team=m["home"],
            away_team=m["away"],
            handicap=m["handicap"],
            play_type=pt,
            status=MatchStatus.COMPLETED,
            result=MatchResult(
                home_score=score_full[0],
                away_score=score_full[1],
                half_home_score=score_half[0],
                half_away_score=score_half[1],
                second_half_home_score=second_half_home,
                second_half_away_score=second_half_away,
            ),
            sp_values={play["result"]: play["sp"]},
        )
        result.append(match)

    return result
