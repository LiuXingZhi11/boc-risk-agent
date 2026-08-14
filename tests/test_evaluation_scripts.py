from __future__ import annotations

import json

from scripts.build_evaluation_fixtures import CATEGORIES
from scripts.evaluate_retrieval import _load_manifest


def test_evaluation_fixture_catalog_has_five_risk_types() -> None:
    assert len(CATEGORIES) == 5
    assert all(len(item["facts"]) == 4 for item in CATEGORIES.values())


def test_evaluation_manifest_shape(tmp_path) -> None:
    manifest = [
        {
            "test_case_id": "QUERY_TEST",
            "query": "测试查询",
            "relevant_case_ids": ["CASE_TEST_01"],
        }
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    loaded = _load_manifest(path)

    assert loaded[0]["relevant_case_ids"] == ["CASE_TEST_01"]


def test_evaluation_manifest_rejects_non_array(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"query": "测试查询"}, ensure_ascii=False), encoding="utf-8")

    try:
        _load_manifest(path)
    except ValueError as exc:
        assert "非空数组" in str(exc)
    else:
        raise AssertionError("非数组 manifest 应被拒绝")
