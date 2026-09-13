"""离线评估：配置矩阵 vs 真值 / 策略对比。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from backend.core.algorithm import process_image
from backend.core.smart import smart_count

CASES_DIR = Path(__file__).resolve().parent.parent / "eval" / "cases"
OUT_DIR = Path(__file__).resolve().parent.parent / "eval" / "out"


def load_case(case_path: Path) -> Dict[str, Any]:
    data = json.loads(case_path.read_text(encoding="utf-8"))
    image_name = data.get("image") or case_path.with_suffix(".jpg").name
    # image path: relative to cases dir or repo root
    candidates = [
        CASES_DIR / image_name,
        case_path.parent / image_name,
        Path(__file__).resolve().parents[2] / image_name,
    ]
    image_path = next((p for p in candidates if p.exists()), None)
    return {
        "id": case_path.stem,
        "image_path": image_path,
        "count": data.get("count"),
        "confidence": data.get("confidence"),
        "notes": data.get("notes", ""),
        "raw": data,
    }


def iter_cases(only: Optional[str] = None) -> List[Dict[str, Any]]:
    if not CASES_DIR.exists():
        return []
    cases = []
    for p in sorted(CASES_DIR.glob("*.json")):
        if only and p.stem != only:
            continue
        cases.append(load_case(p))
    return cases


def run_strategies(image: np.ndarray) -> List[Dict[str, Any]]:
    """评估矩阵：经典 / 旧式分水岭开关 / labels / peaks / smart。"""
    configs = [
        ("classic", {}),
        ("classic_petri", {"detect_petri_dish": True}),
        ("labels_petri", {"detect_petri_dish": True, "use_watershed": True, "segment_mode": "labels"}),
        ("peaks_petri", {"detect_petri_dish": True, "segment_mode": "peaks"}),
        ("labels_only", {"use_watershed": True, "segment_mode": "labels"}),
    ]
    rows: List[Dict[str, Any]] = []
    for name, kw in configs:
        t0 = time.time()
        try:
            r = process_image(image, **kw)
            err = r.get("error")
            count = int(r.get("count") or 0)
        except Exception as e:
            err, count = str(e), 0
        dt = (time.time() - t0) * 1000
        rows.append({"strategy": name, "count": count, "error": err, "ms": round(dt, 1)})

    t0 = time.time()
    try:
        s = smart_count(image)
        rows.append({
            "strategy": "smart",
            "count": int(s.get("count") or 0),
            "error": s.get("error"),
            "ms": round((time.time() - t0) * 1000, 1),
            "chosen": s.get("strategy"),
            "candidates": s.get("candidates"),
        })
    except Exception as e:
        rows.append({"strategy": "smart", "count": 0, "error": str(e), "ms": 0.0})
    return rows


def evaluate_case(case: Dict[str, Any]) -> Dict[str, Any]:
    image_path = case["image_path"]
    if image_path is None or not Path(image_path).exists():
        return {**case, "rows": [], "error": "image not found"}

    image = cv2.imread(str(image_path))
    if image is None:
        return {**case, "rows": [], "error": "image decode failed"}

    rows = run_strategies(image)
    gt = case.get("count")
    for row in rows:
        if gt is not None:
            row["abs_err"] = abs(row["count"] - int(gt))
            row["rel_err"] = round(row["abs_err"] / max(int(gt), 1), 4)
    return {
        "id": case["id"],
        "image": str(image_path),
        "count": gt,
        "confidence": case.get("confidence"),
        "notes": case.get("notes", ""),
        "rows": rows,
        "error": None,
    }


def format_report(results: List[Dict[str, Any]]) -> str:
    lines = [
        "# 菌落计数评估报告",
        "",
        f"用例数: {len(results)}",
        "",
    ]
    for res in results:
        lines.append(f"## {res.get('id')}")
        if res.get("error"):
            lines.append(f"- 错误: {res['error']}")
            lines.append("")
            continue
        gt = res.get("count")
        conf = res.get("confidence")
        lines.append(f"- 图像: `{res.get('image')}`")
        lines.append(f"- 真值: {gt if gt is not None else '（无）'}  置信度: {conf}")
        if res.get("notes"):
            lines.append(f"- 备注: {res['notes']}")
        lines.append("")
        lines.append("| 策略 | count | abs_err | rel_err | ms | 备注 |")
        lines.append("|------|------:|--------:|--------:|---:|------|")
        for row in res.get("rows") or []:
            note = row.get("chosen") or row.get("error") or ""
            lines.append(
                "| {strategy} | {count} | {abs_err} | {rel_err} | {ms} | {note} |".format(
                    strategy=row.get("strategy"),
                    count=row.get("count"),
                    abs_err=row.get("abs_err", ""),
                    rel_err=row.get("rel_err", ""),
                    ms=row.get("ms"),
                    note=note,
                )
            )
        lines.append("")
    return "\n".join(lines)


def run_eval(case_id: Optional[str] = None, save: bool = True) -> Dict[str, Any]:
    cases = iter_cases(only=case_id)
    results = [evaluate_case(c) for c in cases]
    report = format_report(results)
    payload = {"results": results, "report": report}
    if save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "report.md").write_text(report, encoding="utf-8")
        (OUT_DIR / "report.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return payload
