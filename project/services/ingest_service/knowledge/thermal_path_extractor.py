from __future__ import annotations

import re

from .atomic import split_sentences
from .contracts import KnowledgeUnitCandidate
from .normalizer import TERM_ALIASES, canonicalize_term, compact_text, display_name, make_dedup_key, sentence_windows

PATH_HINTS = [
    ["chip", "tim", "cold_plate", "coolant", "cdu"],
    ["processor", "cold plate", "coolant"],
    ["it loop", "facility loop"],
    ["technology cooling system", "facility water"],
]

EXTRA_NODE_ALIASES: dict[str, list[str]] = {
    "chip": ["芯片", "处理器"],
    "tim": ["导热界面材料"],
    "cold_plate": ["冷板", "水冷板"],
    "coolant": ["冷却液", "冷却工质"],
    "cdu": ["冷却分配单元"],
    "it_loop": ["IT侧回路", "二次侧回路"],
    "facility_loop": ["设施侧回路", "一次侧回路"],
    "facility_water": ["设施水", "一次侧水"],
    "tcs": ["技术冷却系统"],
}

_ARROW_RE = re.compile(r"\s*(?:->|→|➔|鈫|鉃|鈬)\s*")
_PATH_EVIDENCE_RE = re.compile(
    r"heat transfer path|cooling path|flow path|liquid path|cooling loop|liquid loop|fluid loop|liquid circuit|"
    r"technology cooling system|facility water system|IT loop|facility loop|route|from\b.+\bto\b|through|"
    r"散热路径|冷却路径|液冷回路|冷却回路|流路|从.+到|经过",
    re.I,
)
_NON_PATH_SENTENCE_RE = re.compile(
    r"ASHRAE|OCP|W17|W27|W32|W40|W45|W\+|A[1-4]|can support|support up to|up to \d|"
    r"CPU power|per CPU|per DIMM|telemetry|control requirement|monitoring requirement|endpoint filtration|"
    r"testing requirement|shock and vibration|hydrostatic pressure testing|should be considered|required|requirement|"
    r"water cooling class|cooling capability",
    re.I,
)
_LOOP_TO_LOOP_RE = re.compile(
    r"(?:IT loop|technology cooling system|TCS|liquid circuit|cooling loop|liquid loop)\b.+\bto\b.+"
    r"(?:facility loop|facility water|facility water system|rack|cold plates?)",
    re.I,
)


def _node_aliases() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for canonical, aliases in TERM_ALIASES.items():
        out[canonical] = list(dict.fromkeys(list(aliases or []) + EXTRA_NODE_ALIASES.get(canonical, [])))
    for canonical, aliases in EXTRA_NODE_ALIASES.items():
        out.setdefault(canonical, [])
        out[canonical] = list(dict.fromkeys(out[canonical] + aliases))
    return out


def _node_from_piece(piece: str) -> str:
    value = compact_text(piece).lower()
    best: tuple[int, int, str] | None = None
    for canonical, aliases in _node_aliases().items():
        for alias in aliases + [canonical, canonical.replace("_", " ")]:
            alias_lower = alias.lower()
            idx = value.rfind(alias_lower)
            if idx < 0:
                continue
            score = (idx, len(alias_lower), canonical)
            if best is None or score[:2] > best[:2]:
                best = score
    if best:
        return best[2]
    return canonicalize_term(piece)


def _clean_path_text(text: str) -> str:
    value = compact_text(text).replace("→", " -> ").replace("➔", " -> ")
    value = re.sub(r"\s*->\s*", " -> ", value)
    return value.strip(" 。.;；")


def _path_sentence(text: str) -> str:
    for sentence in split_sentences(text) + sentence_windows(text):
        if _ARROW_RE.search(sentence):
            return _clean_path_text(sentence)
        if _NON_PATH_SENTENCE_RE.search(sentence) and not _PATH_EVIDENCE_RE.search(sentence):
            continue
        lower = sentence.lower()
        if lower.count(" to ") >= 2 and _PATH_EVIDENCE_RE.search(sentence):
            return _clean_path_text(sentence)
        if _LOOP_TO_LOOP_RE.search(sentence):
            return _clean_path_text(sentence)
        if re.search(r"\bfrom\b.+\bto\b", lower) and _PATH_EVIDENCE_RE.search(sentence):
            return _clean_path_text(sentence)
    return ""


def _path_from_arrows(text: str) -> list[str]:
    path_text = _path_sentence(text)
    if not path_text or not _ARROW_RE.search(path_text):
        return []
    pieces = [piece.strip(" .。;；:,，)") for piece in _ARROW_RE.split(path_text) if piece.strip(" .。;；:,，)")]
    nodes = [_node_from_piece(piece) for piece in pieces]
    return [node for node in nodes if node and node != "unknown"]


def _path_from_to_patterns(text: str) -> list[str]:
    path_text = _path_sentence(text) or compact_text(text)
    lower = path_text.lower()
    if not _PATH_EVIDENCE_RE.search(path_text):
        return []
    for hint in PATH_HINTS:
        pos = []
        for alias in hint:
            idx = lower.find(alias.lower())
            if idx < 0:
                break
            pos.append((idx, canonicalize_term(alias)))
        if len(pos) == len(hint):
            return [name for _, name in sorted(pos)]

    if lower.count(" to ") >= 2:
        parts = [p.strip(" .;:,") for p in re.split(r"\bto\b", lower) if p.strip(" .;:,")]
        nodes = []
        for part in parts:
            node = _node_from_piece(part)
            if node:
                nodes.append(node)
        deduped = []
        for node in nodes:
            if node not in deduped:
                deduped.append(node)
        return deduped
    return []


def _edge_type(source: str, target: str) -> str:
    conduction_pairs = {("chip", "tim"), ("cpu", "tim"), ("gpu", "tim"), ("tim", "cold_plate")}
    convection_pairs = {("cold_plate", "coolant")}
    if (source, target) in conduction_pairs:
        return "conduction"
    if (source, target) in convection_pairs:
        return "convection"
    if "loop" in source or "loop" in target or target in {"cdu", "facility_water"}:
        return "heat_transfer"
    return "transport"


def extract(text: str, source: dict) -> list[KnowledgeUnitCandidate]:
    normalized = compact_text(text)
    if not normalized:
        return []

    path_text = _path_sentence(normalized)
    nodes = _path_from_arrows(normalized) or _path_from_to_patterns(normalized)
    nodes = [node for node in nodes if node]
    deduped = []
    for node in nodes:
        if node not in deduped:
            deduped.append(node)
    nodes = deduped
    if len(nodes) < 2:
        return []

    edges = [
        {"source": nodes[i], "target": nodes[i + 1], "type": _edge_type(nodes[i], nodes[i + 1])}
        for i in range(len(nodes) - 1)
    ]
    title = " -> ".join(display_name(node) for node in nodes)
    content = path_text or title
    return [
        KnowledgeUnitCandidate(
            unit_type="thermal_path",
            canonical_name="_".join(nodes),
            title=title,
            content=content,
            aliases=[],
            properties={"nodes": nodes, "edges": edges},
            source=source,
            confidence=0.82,
            extraction_method="rule_based",
            dedup_key=make_dedup_key("thermal_path", "_".join(nodes)),
            warnings=[],
        )
    ]
