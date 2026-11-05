from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.evaluation.demoqa_dataset import load_demoqa_dataset
from services.retrieval_service.evaluation.runner import run_demoqa_dataset


def main() -> None:
    items = load_demoqa_dataset()
    representatives = []
    seen = set()
    for item in items:
        if item.category not in seen:
            representatives.append(item)
            seen.add(item.category)
    assert len(representatives) == 10
    results = run_demoqa_dataset(representatives)
    for result in results:
        assert result.top_level_contract_ok is True, result.to_dict()
        assert result.retrieval_count_ok is True, result.to_dict()
        assert result.json_serializable_ok is True, result.to_dict()
        assert result.forbidden_claims_ok is True, result.to_dict()
        assert result.self_critique_ok is True, result.to_dict()
        assert result.multi_agent_ok is True, result.to_dict()
    json.dumps([result.to_dict() for result in results], ensure_ascii=False)
    print(json.dumps({"status": "ok", "representative_cases": len(results)}, indent=2))


if __name__ == "__main__":
    main()
