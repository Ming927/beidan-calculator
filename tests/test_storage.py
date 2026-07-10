"""JSON存储层测试。"""

import json
import tempfile
import os
import pytest
from src.models import (
    PlayType, MatchStatus, ParlayMode,
    Match, MatchResult, BetSelection, ParlayConfig, Ticket,
)
from src.storage import BetStorage


@pytest.fixture
def storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_bets.json")
        yield BetStorage(db_path)


class TestBetStorage:
    """Ticket 和 Match 的 CRUD 测试"""

    def test_save_and_get_ticket(self, storage):
        ticket = Ticket(
            ticket_id="T001",
            bets=[BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="3")],
            parlay_config=ParlayConfig(mode=ParlayMode.SINGLE),
            multiplier=5,
        )
        storage.save_ticket(ticket)
        retrieved = storage.get_ticket("T001")
        assert retrieved is not None
        assert retrieved.ticket_id == "T001"
        assert retrieved.bets[0].selected_option == "3"
        assert retrieved.multiplier == 5

    def test_list_tickets(self, storage):
        for i in range(3):
            ticket = Ticket(
                ticket_id=f"T00{i}",
                bets=[BetSelection(match_id=f"M00{i}", play_type=PlayType.HANDICAP_WDL, selected_option="3")],
                parlay_config=ParlayConfig(mode=ParlayMode.SINGLE),
            )
            storage.save_ticket(ticket)
        tickets = storage.list_tickets()
        assert len(tickets) == 3

    def test_delete_ticket(self, storage):
        ticket = Ticket(
            ticket_id="T001",
            bets=[BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="3")],
            parlay_config=ParlayConfig(mode=ParlayMode.SINGLE),
        )
        storage.save_ticket(ticket)
        assert storage.delete_ticket("T001") is True
        assert storage.get_ticket("T001") is None

    def test_delete_nonexistent(self, storage):
        assert storage.delete_ticket("NONEXIST") is False

    def test_save_and_get_match(self, storage):
        match = Match(
            match_id="M001", home_team="曼联", away_team="利物浦",
            handicap=-1, play_type=PlayType.HANDICAP_WDL,
            status=MatchStatus.COMPLETED,
            result=MatchResult(home_score=2, away_score=0),
            sp_values={"3": 2.5, "1": 3.2, "0": 2.8},
        )
        storage.save_match(match)
        retrieved = storage.get_match("M001")
        assert retrieved is not None
        assert retrieved.home_team == "曼联"
        assert retrieved.sp_values["3"] == 2.5
        assert retrieved.result.home_score == 2

    def test_list_matches(self, storage):
        for i in range(3):
            match = Match(
                match_id=f"M00{i}", home_team=f"队{i}", away_team=f"客{i}",
                handicap=0, play_type=PlayType.HANDICAP_WDL,
            )
            storage.save_match(match)
        matches = storage.list_matches()
        assert len(matches) == 3

    def test_ticket_roundtrip_with_parlay_config(self, storage):
        """完整的 M串N 配置序列化/反序列化回环测试"""
        ticket = Ticket(
            ticket_id="T100",
            bets=[
                BetSelection(match_id="M001", play_type=PlayType.HANDICAP_WDL, selected_option="3"),
                BetSelection(match_id="M002", play_type=PlayType.HANDICAP_WDL, selected_option="1"),
                BetSelection(match_id="M003", play_type=PlayType.HANDICAP_WDL, selected_option="3"),
            ],
            parlay_config=ParlayConfig(mode=ParlayMode.M_N, m=3, n=3),
            multiplier=2,
        )
        storage.save_ticket(ticket)
        retrieved = storage.get_ticket("T100")
        assert retrieved.parlay_config.mode == ParlayMode.M_N
        assert retrieved.parlay_config.m == 3
        assert retrieved.parlay_config.n == 3

    def test_match_with_half_result_roundtrip(self, storage):
        """含半场数据的比赛序列化回环测试"""
        match = Match(
            match_id="M001", home_team="A", away_team="B",
            handicap=0, play_type=PlayType.HALF_FULL_WDL,
            status=MatchStatus.COMPLETED,
            result=MatchResult(
                home_score=3, away_score=1,
                half_home_score=1, half_away_score=0,
                second_half_home_score=2, second_half_away_score=1,
            ),
            sp_values={"3-3": 5.0},
        )
        storage.save_match(match)
        retrieved = storage.get_match("M001")
        assert retrieved.result.half_home_score == 1
        assert retrieved.result.second_half_home_score == 2
