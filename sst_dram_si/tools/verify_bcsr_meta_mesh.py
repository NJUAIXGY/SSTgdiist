#!/usr/bin/env python3
"""Verify that global BCSR meta files follow expected layout."""
import argparse
import json
from pathlib import Path


def load_meta(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"无法解析 {path}: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="../weights/bcsr_global_16pe_fanout256",
                        help="目录包含 peXX/coreYY.bcsr.bin.meta.json")
    parser.add_argument("--rows-per-core", type=int, default=5000)
    parser.add_argument("--cols", type=int, default=1600000)
    args = parser.parse_args()
    root = Path(args.dir).resolve()
    if not root.exists():
        raise SystemExit(f"目录不存在: {root}")
    metas = list(root.glob("pe*/core*.bcsr.bin.meta.json"))
    if not metas:
        raise SystemExit("未找到任何 meta.json")
    issues = []
    sample = None
    for meta_path in metas:
        meta = load_meta(meta_path)
        rows = int(meta.get("rows", 0))
        cols = int(meta.get("cols", 0))
        br = int(meta.get("br", 0))
        bc = int(meta.get("bc", 0))
        idx_bytes = int(meta.get("idx_bytes", 0))
        val_bytes = int(meta.get("val_bytes", 0))
        if rows != args.rows_per_core:
            issues.append(f"{meta_path}: rows={rows} != {args.rows_per_core}")
        if cols != args.cols:
            issues.append(f"{meta_path}: cols={cols} != {args.cols}")
        if idx_bytes not in (2, 4):
            issues.append(f"{meta_path}: idx_bytes={idx_bytes} 不支持")
        if val_bytes != 4:
            issues.append(f"{meta_path}: val_bytes={val_bytes} (仅支持4)")
        if sample is None:
            sample = {
                "br": br,
                "bc": bc,
                "idx_bytes": idx_bytes,
                "val_bytes": val_bytes,
                "rowptr_offset": meta.get("rowptr_offset"),
                "colidx_offset": meta.get("colidx_offset"),
                "blockdata_offset": meta.get("blockdata_offset"),
                "blockids_offset": meta.get("blockids_offset"),
            }
    if issues:
        print("⚠️ 校验发现问题：")
        for msg in issues:
            print("  -", msg)
    else:
        print("✅ 所有 meta.json 通过校验")
    if sample:
        print("示例布局:")
        for key, val in sample.items():
            print(f"  {key}: {val}")


if __name__ == "__main__":
    main()
