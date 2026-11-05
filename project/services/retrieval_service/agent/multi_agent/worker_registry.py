from __future__ import annotations

from .contracts import AgentRoleCard
from .role_cards import get_role_card as _get_role_card, list_role_cards as _list_role_cards


_STAGE_TO_ROLE = {
    "task": "task_understanding_agent",
    "rewrite": "query_rewrite_agent",
    "retrieval": "retrieval_agent",
    "calculation": "calculation_agent",
    "property_lookup": "property_lookup_agent",
    "analysis": "analysis_agent",
    "critique": "critique_agent",
    "answer": "answer_agent",
}


def list_workers() -> list[AgentRoleCard]:
    return _list_role_cards()


def get_worker(role_id: str) -> AgentRoleCard | None:
    return _get_role_card(role_id)


def get_role_card(role_id: str) -> AgentRoleCard | None:
    return _get_role_card(role_id)


def list_role_cards() -> list[AgentRoleCard]:
    return _list_role_cards()


def map_stage_to_role(stage_name: str) -> str | None:
    return _STAGE_TO_ROLE.get(stage_name)


def validate_worker_registry() -> list[str]:
    errors: list[str] = []
    cards = list_workers()
    role_ids = [card.role_id for card in cards]
    if len(role_ids) != len(set(role_ids)):
        errors.append("duplicate_role_id")
    for stage_name, role_id in _STAGE_TO_ROLE.items():
        card = get_worker(role_id)
        if card is None:
            errors.append(f"missing_role:{role_id}")
        elif card.stage_name != stage_name:
            errors.append(f"stage_mismatch:{stage_name}:{role_id}")
    return errors


__all__ = [
    "get_role_card",
    "get_worker",
    "list_role_cards",
    "list_workers",
    "map_stage_to_role",
    "validate_worker_registry",
]
