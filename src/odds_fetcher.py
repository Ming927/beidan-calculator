"""赔率获取模块 - 从互联网实时抓取北单比赛 SP 值。

架构:
    OddsFetcher (抽象基类)
    ├── WebScraperFetcher — 网页爬取（基于 requests + BeautifulSoup）
    └── CachedOddsFetcher — 缓存装饰器（默认 5 分钟 TTL）

使用:
    from src.odds_fetcher import get_default_fetcher, format_matches_for_api

    fetcher = get_default_fetcher()
    matches = fetcher.fetch_matches()  # → list[Match]
    api_data = format_matches_for_api(matches)  # → 前端可直接用的 dict

扩展新数据源:
    class MyFetcher(OddsFetcher):
        def fetch_matches(self) -> list[Match]:
            ...
"""

import time
import re
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.models import PlayType, MatchStatus, Match, MatchResult

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
    """赔率获取器抽象基类。所有数据源必须实现此接口。"""

    @abstractmethod
    def fetch_matches(self) -> list[Match]:
        """获取当前可投注比赛的列表（含 SP 值）。"""
        ...


# ═══════════════════════════════════════════
# 缓存装饰器
# ═══════════════════════════════════════════

class CachedOddsFetcher(OddsFetcher):
    """带 TTL 缓存的赔率获取器包装。

    参数:
        inner: 被包装的 OddsFetcher 实例
        ttl_seconds: 缓存有效期（秒），默认 300（5分钟）
    """

    def __init__(self, inner: OddsFetcher, ttl_seconds: int = 300):
        self._inner = inner
        self._ttl = ttl_seconds
        self._cache: Optional[list[Match]] = None
        self._last_fetch: float = 0.0

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
# 网页爬取实现
# ═══════════════════════════════════════════

class WebScraperFetcher(OddsFetcher):
    """从公开彩票数据网站爬取北单赔率。

    支持:
        - HTML table 解析（自动尝试多种 CSS 选择器）
        - 内嵌 JSON 数据提取（作为回退方案）
        - GBK/UTF-8 编码自动检测
        - 可自定义目标 URL

    参数:
        base_url: 目标网站 URL
        timeout: HTTP 请求超时（秒）
    """

    DEFAULT_URL = "https://odds.500.com/index_bd.shtml"

    def __init__(self, base_url: str = "", timeout: int = 10):
        self.base_url = base_url or self.DEFAULT_URL
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

    def fetch_matches(self) -> list[Match]:
        """获取比赛列表。网络错误时返回空列表。"""
        try:
            resp = self.session.get(self.base_url, timeout=self.timeout)
            resp.raise_for_status()
            resp.encoding = self._detect_encoding(resp)
            return self._parse_html(resp.text)
        except requests.RequestException:
            logger.warning("获取赔率失败：网络请求异常", exc_info=True)
            return []
        except Exception:
            logger.error("解析赔率异常", exc_info=True)
            return []

    def _detect_encoding(self, resp: requests.Response) -> str:
        """检测网页编码（优先响应头 → meta 标签 → 默认 GBK）。"""
        if resp.encoding and resp.encoding.lower() not in ('iso-8859-1', 'latin-1'):
            return resp.encoding
        match = re.search(rb'charset=["\']?([\w-]+)', resp.content[:2048])
        if match:
            return match.group(1).decode('ascii')
        return 'gbk'

    def _parse_html(self, html: str) -> list[Match]:
        """解析 HTML，提取所有比赛行。"""
        soup = BeautifulSoup(html, 'lxml')
        matches = []

        # 尝试多种常见的表格选择器
        row_selectors = [
            'table[class*="bet"] tr',
            'table[class*="odds"] tr',
            'table[class*="match"] tr',
            '.match-list tr',
            '.odds-list tr',
            'table tr[class*="match"]',
            'tr[class*="odds"]',
        ]
        rows = []
        for sel in row_selectors:
            rows = soup.select(sel)
            if rows:
                break

        # 如果选择器没匹配到，尝试找所有 table 中的 tr
        if not rows:
            for table in soup.find_all('table'):
                rows = table.find_all('tr')
                if len(rows) >= 3:  # 至少表头+2行数据
                    break

        for i, row in enumerate(rows):
            try:
                m = self._parse_row(row, i)
                if m:
                    matches.append(m)
            except Exception:
                continue

        # 回退：尝试从内嵌 JSON 提取
        if not matches:
            matches = self._try_extract_json(soup)

        return matches

    def _parse_row(self, row, index: int) -> Optional[Match]:
        """解析单行比赛数据。提取主队、客队、让球、SP值。

        支持的常见列结构：
          [联赛, 主队, 客队, 让球, SP胜, SP平, SP负, ...]  (500.com format)
          [编号, 主队, 客队, 让球, SP胜, SP平, SP负, ...]
          [主队, 客队, 让球, SP胜, SP平, SP负, ...]
        """
        cells = row.find_all(['td', 'th'])
        if not cells:
            return None

        # 跳过表头行
        if row.find('th'):
            return None

        texts = [c.get_text(strip=True) for c in cells]

        # 过滤空行和标题行
        if len(texts) < 4:
            return None
        if any(kw in ''.join(texts[:3]) for kw in ['比赛', '赛事', '主队', '日期', '编号']):
            return None

        # 将文本分类：队名 vs 数字
        names = []
        numbers = []
        for t in texts:
            stripped = t.strip()
            # 数字类: 纯数字、带符号整数、浮点数
            is_num = bool(re.match(r'^-?\d+(\.\d+)?$', stripped))
            if is_num:
                numbers.append(stripped)
            elif stripped and not stripped.startswith('SP'):
                names.append(stripped)

        home, away, handicap, sp_values = "", "", 0, {}

        # 根据 names 长度判断格式
        if len(names) >= 3:
            # [联赛, 主队, 客队, ...] 格式 — 跳过联赛名
            home, away = names[1], names[2]
        elif len(names) == 2:
            home, away = names[0], names[1]
        else:
            return None

        # 从数字中提取 SP 值
        sp_candidates = [parse_sp_value(t) for t in numbers if parse_sp_value(t) > 0]
        if len(sp_candidates) >= 3:
            sp_values["3"] = sp_candidates[0]
            sp_values["1"] = sp_candidates[1]
            sp_values["0"] = sp_candidates[2]

        # 让球数：在数字中找带符号的整数
        for t in numbers:
            if t.startswith('-') or t.startswith('+'):
                try:
                    handicap = int(t)
                    break
                except ValueError:
                    pass

        if not home or not away or not sp_values:
            return None

        return Match(
            match_id=f"BD{index+1:03d}",
            home_team=home,
            away_team=away,
            handicap=handicap,
            play_type=PlayType.HANDICAP_WDL,
            status=MatchStatus.PENDING,
            sp_values=sp_values,
        )

    def _try_extract_json(self, soup: BeautifulSoup) -> list[Match]:
        """从页面内嵌的 JS 变量中提取 JSON 比赛数据。"""
        matches = []
        for script in soup.find_all('script'):
            if not script.string:
                continue
            # 匹配常见模式: var xxx = [{...}];
            m = re.search(r'(?:var|let|const|window\.)\s*\w+\s*=\s*(\[[\s\S]*?\])\s*;', script.string)
            if not m:
                continue
            try:
                data = json.loads(m.group(1))
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    matches = self._parse_json_data(data)
                    if matches:
                        break
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return matches

    def _parse_json_data(self, data: list[dict]) -> list[Match]:
        """解析 JSON 格式的比赛数据（兼容 NamiData/AntScore 等商业 API 格式）。"""
        matches = []
        for i, item in enumerate(data):
            try:
                home = item.get('home', item.get('home_team', item.get('h', '')))
                away = item.get('away', item.get('away_team', item.get('a', '')))
                if not home or not away:
                    continue

                handicap = 0
                sp_values = {}

                # 尝试标准格式: item.odds.spf
                odds = item.get('odds', item.get('sp', {}))
                if isinstance(odds, dict):
                    spf = odds.get('spf', odds.get('had', {}))
                    if isinstance(spf, dict):
                        handicap = int(spf.get('goal', spf.get('handicap', 0)))
                        sp_values = {}
                        for k, v in spf.items():
                            if k in ('goal', 'handicap', 'id'):
                                continue
                            option_key = k.replace('sf', '').replace('h', '').replace('a', '')
                            val = parse_sp_value(str(v))
                            if val > 0:
                                sp_values[option_key] = val

                # 回退：直接字段
                if not sp_values:
                    for key in ('sf3', 'h3', '3'):
                        v = item.get(key, item.get('sp_win', ''))
                        if v:
                            sp_values['3'] = parse_sp_value(str(v))
                            break
                    for key in ('sf1', 'h1', '1'):
                        v = item.get(key, item.get('sp_draw', ''))
                        if v:
                            sp_values['1'] = parse_sp_value(str(v))
                            break
                    for key in ('sf0', 'h0', '0'):
                        v = item.get(key, item.get('sp_lose', ''))
                        if v:
                            sp_values['0'] = parse_sp_value(str(v))
                            break

                if not sp_values:
                    continue

                matches.append(Match(
                    match_id=str(item.get('id', item.get('match_id', f'BD{i+1:03d}'))),
                    home_team=str(home),
                    away_team=str(away),
                    handicap=handicap,
                    play_type=PlayType.HANDICAP_WDL,
                    status=MatchStatus.PENDING,
                    sp_values=sp_values,
                ))
            except Exception:
                continue
        return matches


# ═══════════════════════════════════════════
# 模块级默认实例
# ═══════════════════════════════════════════

_default_fetcher: Optional[CachedOddsFetcher] = None


def get_default_fetcher() -> CachedOddsFetcher:
    """获取默认的赔率获取器实例（单例，带 5 分钟缓存）。"""
    global _default_fetcher
    if _default_fetcher is None:
        _default_fetcher = CachedOddsFetcher(WebScraperFetcher(), ttl_seconds=300)
    return _default_fetcher
