"""JSON 文件持久化存储 - Ticket 和 Match 的 CRUD。"""

import json
import os
import threading
from typing import Optional
from src.models import Ticket, Match


class BetStorage:
    """JSON 文件持久化存储。线程安全（简单锁），自动创建数据文件和目录。"""

    def __init__(self, db_path: str = "data/bets.json"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self):
        """确保数据文件存在。"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        if not os.path.exists(self.db_path):
            self._write({"tickets": {}, "matches": {}})

    def _read(self) -> dict:
        with open(self.db_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    # ── Ticket CRUD ──

    def save_ticket(self, ticket: Ticket):
        with self.lock:
            data = self._read()
            data["tickets"][ticket.ticket_id] = _ticket_to_dict(ticket)
            self._write(data)

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        data = self._read()
        raw = data["tickets"].get(ticket_id)
        if raw is None:
            return None
        return _dict_to_ticket(raw)

    def list_tickets(self, limit: int = 100) -> list[Ticket]:
        data = self._read()
        tickets = [_dict_to_ticket(v) for v in data["tickets"].values()]
        tickets.sort(key=lambda t: t.created_at, reverse=True)
        return tickets[:limit]

    def delete_ticket(self, ticket_id: str) -> bool:
        with self.lock:
            data = self._read()
            if ticket_id not in data["tickets"]:
                return False
            del data["tickets"][ticket_id]
            self._write(data)
            return True

    # ── Match CRUD ──

    def save_match(self, match: Match):
        with self.lock:
            data = self._read()
            data["matches"][match.match_id] = _match_to_dict(match)
            self._write(data)

    def get_match(self, match_id: str) -> Optional[Match]:
        data = self._read()
        raw = data["matches"].get(match_id)
        if raw is None:
            return None
        return _dict_to_match(raw)

    def list_matches(self) -> list[Match]:
        data = self._read()
        return [_dict_to_match(v) for v in data["matches"].values()]


# ── 序列化辅助函数 ──

def _ticket_to_dict(t: Ticket) -> dict:
    return {
        "ticket_id": t.ticket_id,
        "bets": [
            {
                "match_id": b.match_id,
                "play_type": b.play_type.value,
                "selected_option": b.selected_option,
            }
            for b in t.bets
        ],
        "parlay_config": {
            "mode": t.parlay_config.mode.value,
            "m": t.parlay_config.m,
            "n": t.parlay_config.n,
            "selected_levels": t.parlay_config.selected_levels,
        },
        "multiplier": t.multiplier,
        "created_at": t.created_at,
    }


def _dict_to_ticket(d: dict) -> Ticket:
    from src.models import ParlayConfig, PlayType, BetSelection, ParlayMode

    bets = [
        BetSelection(
            match_id=b["match_id"],
            play_type=PlayType(b["play_type"]),
            selected_option=b["selected_option"],
        )
        for b in d["bets"]
    ]
    pc = d["parlay_config"]
    parlay_config = ParlayConfig(
        mode=ParlayMode(pc["mode"]),
        m=pc.get("m", len(bets)),
        n=pc.get("n"),
        selected_levels=pc.get("selected_levels"),
    )
    return Ticket(
        ticket_id=d["ticket_id"],
        bets=bets,
        parlay_config=parlay_config,
        multiplier=d.get("multiplier", 1),
        created_at=d.get("created_at", ""),
    )


def _match_to_dict(m: Match) -> dict:
    d: dict = {
        "match_id": m.match_id,
        "home_team": m.home_team,
        "away_team": m.away_team,
        "handicap": m.handicap,
        "play_type": m.play_type.value,
        "status": m.status.value,
        "sp_values": m.sp_values,
    }
    if m.result:
        r = m.result
        d["result"] = {
            "home_score": r.home_score,
            "away_score": r.away_score,
            "half_home_score": r.half_home_score,
            "half_away_score": r.half_away_score,
            "second_half_home_score": r.second_half_home_score,
            "second_half_away_score": r.second_half_away_score,
        }
    return d


def _dict_to_match(d: dict) -> Match:
    from src.models import PlayType, MatchStatus, MatchResult

    result = None
    if "result" in d and d["result"]:
        r = d["result"]
        result = MatchResult(
            home_score=r["home_score"],
            away_score=r["away_score"],
            half_home_score=r.get("half_home_score", 0),
            half_away_score=r.get("half_away_score", 0),
            second_half_home_score=r.get("second_half_home_score", 0),
            second_half_away_score=r.get("second_half_away_score", 0),
        )
    return Match(
        match_id=d["match_id"],
        home_team=d.get("home_team", ""),
        away_team=d.get("away_team", ""),
        handicap=d.get("handicap", 0),
        play_type=PlayType(d["play_type"]),
        status=MatchStatus(d.get("status", "pending")),
        result=result,
        sp_values=d.get("sp_values", {}),
    )
