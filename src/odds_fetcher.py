"""赔率获取模块 - 从互联网实时获取北单比赛 SP 值。

架构:
    OddsFetcher (抽象基类)
    ├── ApiFetcher — 商业API客户端 (NamiData/AntScore格式)
    ├── DemoFetcher — 演示模式，生成逼真样本数据（默认）
    └── CachedOddsFetcher — 缓存包装器 (默认 5 分钟 TTL)

配置 (环境变量):
    BEIDAN_API_URL  — 商业API地址 (如 https://api.example.com/sport/api/v1/lot/bd/odds)
    BEIDAN_API_KEY  — API密钥
    BEIDAN_API_USER — API用户名 (部分服务需要)
    设置后自动切换为 API 模式，否则使用演示模式。

使用:
    from src.odds_fetcher import get_default_fetcher, format_matches_for_api
    fetcher = get_default_fetcher()
    matches = fetcher.fetch_matches()  # → list[Match]
"""

import os
import time
import re
import json
import random
import logging
from abc import ABC, abstractmethod
from typing import Optional

import requests

from src.models import PlayType, MatchStatus, Match

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════

def parse_sp_value(raw: str) -> float:
    """将 SP 值字符串转为 float。无法解析时返回 0.0。"""
    try:
        return float(raw.strip())
    except (ValueError, AttributeError):
        return 0.0


def format_matches_for_api(matches: list[Match]) -> dict:
    """将 Match 列表转为前端 /api/calculate 期望的 matches JSON 格式。"""
    result = {}
    for m in matches:
        match_data: dict = {
            "home_team": m.home_team,
            "away_team": m.away_team,
            "handicap": m.handicap,
            "play_type": m.play_type.value,
            "status": m.status.value,
            "sp_values": m.sp_values,
        }
        if m.result:
            match_data["result"] = {
                "home_score": m.result.home_score,
                "away_score": m.result.away_score,
                "half_home_score": m.result.half_home_score,
                "half_away_score": m.result.half_away_score,
                "second_half_home_score": m.result.second_half_home_score,
                "second_half_away_score": m.result.second_half_away_score,
            }
        result[m.match_id] = match_data
    return result


# ═══════════════════════════════════════════
# 抽象基类
# ═══════════════════════════════════════════

class OddsFetcher(ABC):
    """赔率获取器抽象基类。"""

    @abstractmethod
    def fetch_matches(self) -> list[Match]:
        """获取当前可投注比赛的列表（含 SP 值）。"""
        ...


# ═══════════════════════════════════════════
# 缓存包装器
# ═══════════════════════════════════════════

class CachedOddsFetcher(OddsFetcher):
    """带 TTL 缓存的赔率获取器包装。"""

    def __init__(self, inner: OddsFetcher, ttl_seconds: int = 300):
        self._inner = inner
        self._ttl = ttl_seconds
        self._cache: Optional[list[Match]] = None
        self._last_fetch: float = 0.0

    @property
    def inner(self) -> OddsFetcher:
        return self._inner

    def fetch_matches(self) -> list[Match]:
        now = time.time()
        if self._cache is not None and (now - self._last_fetch) < self._ttl:
            return self._cache
        self._cache = self._inner.fetch_matches()
        self._last_fetch = now
        return self._cache

    def invalidate(self):
        """手动清除缓存，强制下次 fetch 重新请求。"""
        self._cache = None
        self._last_fetch = 0.0


# ═══════════════════════════════════════════
# 商业 API 客户端
# ═══════════════════════════════════════════

class ApiFetcher(OddsFetcher):
    """商业体育数据 API 客户端。

    支持 NamiData / AntScore 等主流数据服务商的北单接口格式。
    通过环境变量配置:
        BEIDAN_API_URL  — API端点
        BEIDAN_API_KEY  — API密钥 (token参数)
        BEIDAN_API_USER — 用户名 (部分服务需要)

    兼容的API返回格式:
        {"code": 0, "data": {"list": [{
            "id": 43, "comp": "联赛", "home": "主队", "away": "客队",
            "issue": "45", "issue_num": "45",
            "odds": {
                "spf": {"goal": "0", "sf3": "1.85", "sf1": "3.20", "sf0": "3.80"},
                "jq": {...}, "bqc": {...}, "sxp": {...}, "bf": {...}
            }
        }]}}
    """

    def __init__(self, base_url: str = "", api_key: str = "", api_user: str = "",
                 timeout: int = 10):
        self.base_url = base_url or os.environ.get("BEIDAN_API_URL", "")
        self.api_key = api_key or os.environ.get("BEIDAN_API_KEY", "")
        self.api_user = api_user or os.environ.get("BEIDAN_API_USER", "")
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    def fetch_matches(self) -> list[Match]:
        if not self.base_url:
            logger.warning("API未配置，请设置 BEIDAN_API_URL 环境变量")
            return []

        params = {"token": self.api_key}
        if self.api_user:
            params["user"] = self.api_user

        try:
            resp = requests.get(
                self.base_url,
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "BeidanCalculator/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                logger.warning("API返回错误: %s", data.get("msg", "未知错误"))
                return []

            items = data.get("data", {}).get("list", [])
            return self._parse_response(items)

        except requests.RequestException:
            logger.warning("API请求失败", exc_info=True)
            return []
        except Exception:
            logger.error("API数据解析异常", exc_info=True)
            return []

    def _parse_response(self, items: list[dict]) -> list[Match]:
        """解析 NamiData/AntScore 格式的 API 响应。"""
        matches = []
        for item in items:
            try:
                mid = str(item.get("id", item.get("match_id", "")))
                home = item.get("home", item.get("home_team", ""))
                away = item.get("away", item.get("away_team", ""))
                if not home or not away:
                    continue

                odds = item.get("odds", item.get("sp", {}))
                spf = odds.get("spf", odds.get("had", {}))

                handicap = int(spf.get("goal", spf.get("handicap", 0)))
                sp_values = {}
                for k in ("sf3", "sf1", "sf0"):
                    option = k.replace("sf", "")
                    val = parse_sp_value(str(spf.get(k, "")))
                    if val > 0:
                        sp_values[option] = val

                if not sp_values:
                    continue

                matches.append(Match(
                    match_id=mid,
                    home_team=home,
                    away_team=away,
                    handicap=handicap,
                    play_type=PlayType.HANDICAP_WDL,
                    status=MatchStatus.PENDING,
                    sp_values=sp_values,
                ))
            except Exception:
                continue
        return matches


# ═══════════════════════════════════════════
# 演示模式 (Demo Mode)
# ═══════════════════════════════════════════

# 演示数据：逼真的球队名和 SP 值范围
_DEMO_TEAMS = [
    ("曼联", "利物浦"), ("曼城", "阿森纳"), ("切尔西", "热刺"),
    ("皇马", "巴萨"), ("马竞", "塞维利亚"), ("拜仁", "多特蒙德"),
    ("巴黎", "马赛"), ("尤文", "国际米兰"), ("AC米兰", "罗马"),
    ("阿贾克斯", "埃因霍温"), ("波尔图", "本菲卡"), ("凯尔特人", "流浪者"),
    ("上海海港", "山东泰山"), ("北京国安", "广州队"), ("武汉三镇", "浙江队"),
]

_DEMO_LEAGUES = ["英超", "西甲", "德甲", "法甲", "意甲", "中超", "欧冠"]


class DemoFetcher(OddsFetcher):
    """演示模式赔率获取器。

    生成逼真的样本比赛数据用于测试和演示。
    每次调用返回 8-12 场随机生成的比赛，含合理的 SP 值。
    """

    def __init__(self, match_count: int = 0, seed: int = 0):
        self._rng = random.Random(seed) if seed else random.Random()
        self._match_count = match_count or self._rng.randint(8, 12)

    def fetch_matches(self) -> list[Match]:
        rng = self._rng
        count = self._match_count
        teams = rng.sample(_DEMO_TEAMS, min(count, len(_DEMO_TEAMS)))
        if len(teams) < count:
            while len(teams) < count:
                teams.append(rng.choice(_DEMO_TEAMS))

        matches = []
        for i, (home, away) in enumerate(teams):
            handicap = rng.choices([0, -1, 1, -2, 2], weights=[3, 3, 3, 1, 1])[0]

            base_sp3 = round(rng.uniform(1.5, 4.0), 2)
            base_sp1 = round(rng.uniform(2.5, 5.0), 2)
            base_sp0 = round(rng.uniform(2.0, 6.0), 2)

            if handicap < 0:
                base_sp3 = round(max(1.2, base_sp3 - 0.3 * abs(handicap)), 2)
            elif handicap > 0:
                base_sp0 = round(max(1.2, base_sp0 - 0.3 * abs(handicap)), 2)

            sp_values = {"3": base_sp3, "1": base_sp1, "0": base_sp0}
            league = rng.choice(_DEMO_LEAGUES)

            matches.append(Match(
                match_id=f"demo_{i+1:03d}",
                home_team=f"[{league}] {home}",
                away_team=away,
                handicap=handicap,
                play_type=PlayType.HANDICAP_WDL,
                status=MatchStatus.PENDING,
                sp_values=sp_values,
            ))

        return matches


# ═══════════════════════════════════════════
# 默认实例工厂
# ═══════════════════════════════════════════

_default_fetcher: Optional[CachedOddsFetcher] = None


def get_default_fetcher() -> CachedOddsFetcher:
    """获取默认的赔率获取器实例（单例，带缓存）。

    自动检测配置:
    - 若设置了 BEIDAN_API_URL，使用 ApiFetcher (商业API模式)
    - 否则使用 DemoFetcher (演示模式，生成样本数据)
    """
    global _default_fetcher
    if _default_fetcher is not None:
        return _default_fetcher

    api_url = os.environ.get("BEIDAN_API_URL", "")
    if api_url:
        logger.info("使用商业API模式: %s", api_url)
        inner = ApiFetcher(base_url=api_url)
    else:
        logger.info("使用演示模式（设置 BEIDAN_API_URL 可切换为实时API）")
        inner = DemoFetcher()

    _default_fetcher = CachedOddsFetcher(inner, ttl_seconds=300)
    return _default_fetcher
