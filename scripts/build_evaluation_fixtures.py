#!/usr/bin/env python3
"""生成公开、虚构、脱敏的检索评估案例。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models import Case, CaseBundle, Fact, RuleHypothesis, TargetEvent
from src.storage.repository import CaseRepository

CATEGORIES = {
    "HIDDEN_CONTROL": {
        "name": "隐性控制与分散融资",
        "query": "多家表面独立企业由同一实际控制关系支配，分别向多家银行融资，资金集中流向同一项目。",
        "facts": [
            ("relationship", "多家企业表面独立但存在共同实际控制关系。"),
            ("action", "多个主体分别向不同银行申请贷款。"),
            ("transaction", "贷款资金集中流向同一房地产项目。"),
            ("risk_event", "项目销售不及预期后出现共同还款压力。"),
        ],
        "rule": "表面独立企业群可能通过分散融资规避单一客户识别。",
    },
    "CIRCULAR_CASH": {
        "name": "关联方循环资金",
        "query": "关联企业之间反复划转资金形成虚假销售回款，资金没有真实沉淀。",
        "facts": [
            ("relationship", "多个交易主体存在关联或共同利益关系。"),
            ("transaction", "主体之间反复进行资金划转。"),
            ("financial_observation", "报表显示销售回款但账户资金基本没有沉淀。"),
            ("risk_event", "剔除循环资金后缺少支持还款的真实经营回款。"),
        ],
        "rule": "关联方循环资金可能制造虚假销售和还款能力。",
    },
    "HIGH_COST_FINANCE": {
        "name": "高成本融资与展期压力",
        "query": "房地产项目销售不及预期，高成本融资到期无法偿还，展期后财务成本继续累积。",
        "facts": [
            ("transaction", "企业以项目资产抵押取得高成本融资。"),
            ("financial_observation", "融资期限届满时项目销售回款低于预期。"),
            ("risk_event", "企业无法按期偿还全部本金。"),
            ("outcome", "展期后财务成本继续增加且本金没有减少。"),
        ],
        "rule": "高成本融资叠加销售回款不足可能形成持续展期压力。",
    },
    "CROSS_INDUSTRY": {
        "name": "跨行业投资失败",
        "query": "企业缺乏目标行业经验却跨行业投资重资产项目，投产延期、价格下跌并持续亏损。",
        "facts": [
            ("entity_attribute", "控股股东原有主营业务与投资项目行业不同。"),
            ("action", "企业投资建设重资产生产项目。"),
            ("business_observation", "项目投产延期且产能长期未达到计划。"),
            ("risk_event", "市场价格下跌后项目持续亏损并停产。"),
        ],
        "rule": "跨行业投资中的经验不足和产能不达预期可能放大项目风险。",
    },
    "GUARANTEE_CIRCLE": {
        "name": "互保网络风险传播",
        "query": "企业之间形成多层互保圈，一家企业危机触发多家银行收贷，风险沿担保网络向外传播。",
        "facts": [
            ("relationship", "多个企业之间存在相互担保关系。"),
            ("transaction", "担保圈涉及多级企业和多家银行授信。"),
            ("risk_event", "核心企业发生危机后银行集中收回贷款。"),
            ("outcome", "风险沿多层互保网络向关联企业扩散。"),
        ],
        "rule": "多层互保关系可能形成风险传播网络。",
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成合成检索评估案例")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repository = CaseRepository(args.database)
    now = datetime.now(timezone.utc).isoformat()
    manifest: list[dict[str, object]] = []
    for category, template in CATEGORIES.items():
        expected_ids: list[str] = []
        for variant in range(1, 5):
            case_id = f"EVAL_{category}_{variant:02d}"
            expected_ids.append(case_id)
            facts = tuple(
                Fact(
                    f"{case_id}_F{index:03d}",
                    f"{statement}（变体{variant}）",
                    statement,
                    fact_category,
                    "reported_fact",
                    None,
                    "known_at_target" if fact_category == "risk_event" else "known_before_target",
                )
                for index, (fact_category, statement) in enumerate(template["facts"], start=1)
            )
            target_fact = next(fact for fact in facts if fact.category == "risk_event")
            bundle = CaseBundle(
                case=Case(
                    case_id=case_id,
                    case_name=f"{template['name']}（虚构变体{variant}）",
                    raw_text="；".join(fact.statement for fact in facts),
                    source="synthetic_eval",
                    case_type="evaluation",
                    target_event=TargetEvent(target_fact.fact_id),
                    review_status="approved",
                    created_at=now,
                    updated_at=now,
                ),
                facts=facts,
                rule_hypotheses=(
                    RuleHypothesis(
                        f"{case_id}_R001",
                        case_id,
                        template["rule"],
                        tuple(fact.fact_id for fact in facts),
                        review_status="approved",
                    ),
                ),
            )
            repository.save_case_bundle(bundle, replace=True)
        manifest.append(
            {
                "test_case_id": f"QUERY_{category}",
                "risk_type": template["name"],
                "query": template["query"],
                "relevant_case_ids": expected_ids,
            }
        )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"case_count": 20, "query_count": len(manifest), "manifest": str(args.manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
