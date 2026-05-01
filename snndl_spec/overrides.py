from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class OverrideHit:
    rule_index: int
    match: Dict[str, Any]


def _matches_selector(
    *,
    selector: Dict[str, Any],
    role: str,
    component_type: str,
    name: str,
    tags: Dict[str, Any],
) -> bool:
    if not selector:
        return True

    sel_role = selector.get("role")
    if sel_role is not None and str(sel_role) != str(role):
        return False

    sel_type = selector.get("type")
    if sel_type is not None and str(sel_type) != str(component_type):
        return False

    sel_name = selector.get("name")
    if sel_name is not None and str(sel_name) != str(name):
        return False

    sel_prefix = selector.get("name_prefix")
    if sel_prefix is not None and not str(name).startswith(str(sel_prefix)):
        return False

    sel_tags = selector.get("tags")
    if sel_tags is not None:
        if not isinstance(sel_tags, dict):
            return False
        for k, v in sel_tags.items():
            if tags.get(k) != v:
                return False

    return True


class OverrideEngine:
    """
    Apply ordered overrides rules onto SST component/subcomponent params.

    Rules schema (v1):
      - match: { role?, type?, name?, name_prefix?, tags? }
      - params: { ... }
      - strict?: bool  (if true, must match at least once; enforced in finalize())
    """

    def __init__(self, rules: List[Dict[str, Any]]):
        if not isinstance(rules, list):
            raise ValueError("overrides must be a list")
        self._rules: List[Dict[str, Any]] = list(rules)
        self._rule_match_counts: List[int] = [0 for _ in self._rules]

    def apply(
        self,
        *,
        role: str,
        component_type: str,
        name: str,
        tags: Dict[str, Any],
        base_params: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        out = dict(base_params)
        hits: List[Dict[str, Any]] = []

        for idx, rule in enumerate(self._rules):
            if not isinstance(rule, dict):
                continue
            selector = rule.get("match") or {}
            if not isinstance(selector, dict):
                continue

            if not _matches_selector(
                selector=selector,
                role=str(role),
                component_type=str(component_type),
                name=str(name),
                tags=dict(tags or {}),
            ):
                continue

            params = rule.get("params") or {}
            if not isinstance(params, dict):
                continue

            self._rule_match_counts[idx] += 1
            hits.append({"rule_index": idx, "match": selector})
            out.update(params)

        return out, hits

    def finalize(self) -> None:
        """
        Enforce strict rules: any rule with strict=true must match at least once.
        """
        missing: List[int] = []
        for idx, rule in enumerate(self._rules):
            if not isinstance(rule, dict):
                continue
            strict = bool(rule.get("strict", False))
            if strict and self._rule_match_counts[idx] <= 0:
                missing.append(idx)
        if missing:
            raise ValueError(f"strict override rules not matched: {missing}")

    def rules(self) -> List[Dict[str, Any]]:
        return list(self._rules)

