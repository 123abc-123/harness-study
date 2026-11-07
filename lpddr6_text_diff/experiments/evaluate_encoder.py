"""Reproducible candidate matching comparison using a local ONNX text encoder.

Install fastembed outside product dependencies, then run from repo root:
  python lpddr6_text_diff/experiments/evaluate_encoder.py --deps .test-workspace/encoder-deps --cache .test-workspace/encoder-models
The model download stays in the ignored cache. No document text is uploaded.
"""
import argparse
import json
import sys
from pathlib import Path

from compare_baselines import build_cases, select, similarity
from real_jedec_scope import OLD as REAL_OLD, NEW as REAL_NEW


MODEL_ID = "BAAI/bge-small-en-v1.5"


def groups(case):
    items = [[b] for b in case["new"]]
    for size in (2, 3):
        for start in range(len(case["new"]) - size + 1):
            group = case["new"][start:start + size]
            if len({b["title"] for b in group}) == 1:
                items.append(group)
    return items


def run(model, np):
    cases = build_cases()
    for row in REAL_OLD:
        cases.append({"name": "real_jedec_" + row["id"],
                      "old": {**row, "title": "1 Scope"},
                      "new": [{**x, "title": "1 Scope"} for x in REAL_NEW],
                      "gold_ids": [row["id"].replace("D-", "E-")]})
    texts = []
    for case in cases:
        texts.append(case["old"]["text"])
        texts.extend(" ".join(b["text"] for b in group) for group in groups(case))
    unique = list(dict.fromkeys(texts))
    vectors = list(model.embed(unique))
    lookup = dict(zip(unique, vectors))
    result = []
    for case in cases:
        old = case["old"]
        candidates = []
        for group in groups(case):
            text = " ".join(b["text"] for b in group)
            cosine = float(np.dot(lookup[old["text"]], lookup[text]) /
                           (np.linalg.norm(lookup[old["text"]]) * np.linalg.norm(lookup[text])))
            lex = similarity(old["text"], text)
            title = sum(similarity(old["title"], b["title"]) for b in group) / len(group)
            ids = [b["id"] for b in group]
            candidates.append({"ids": ids, "encoder_cosine": round(cosine, 5),
                               "lexical": round(lex, 5), "title": round(title, 5),
                               "lexical_context_score": round(.7*lex+.3*title-.02*(len(group)-1),5)})
        encoder_ranked = sorted(candidates, key=lambda x: x["encoder_cosine"], reverse=True)
        lex_ranked = sorted(candidates, key=lambda x: x["lexical_context_score"], reverse=True)
        gold = set(case["gold_ids"])
        result.append({"case": case["name"], "gold_ids": sorted(gold),
                       "lexical_selected": select(case, "lexical_context_groups"),
                       "encoder_ranked": encoder_ranked, "lexical_ranked": lex_ranked,
                       "encoder_top1_exact": bool(gold) and set(encoder_ranked[0]["ids"]) == gold,
                       "lexical_top1_exact": bool(gold) and set(lex_ranked[0]["ids"]) == gold,
                       "encoder_top2_contains_gold": bool(gold) and any(set(x["ids"]) == gold for x in encoder_ranked[:2]),
                       "lexical_top2_contains_gold": bool(gold) and any(set(x["ids"]) == gold for x in lex_ranked[:2])})
    matched = [r for r in result if r["gold_ids"]]
    return {"model": MODEL_ID, "dataset": "15 hand-authored cases + 2 real public JEDEC Scope excerpts",
            "encoder_used_for": "candidate matching only", "gold_nonempty": len(matched),
            "lexical_top1_exact": sum(x["lexical_top1_exact"] for x in matched),
            "encoder_top1_exact": sum(x["encoder_top1_exact"] for x in matched),
            "lexical_top2_contains_gold": sum(x["lexical_top2_contains_gold"] for x in matched),
            "encoder_top2_contains_gold": sum(x["encoder_top2_contains_gold"] for x in matched),
            "details": result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--deps", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.deps.resolve()))
    import numpy as np
    from fastembed import TextEmbedding
    args.cache.mkdir(parents=True, exist_ok=True)
    model = TextEmbedding(model_name=MODEL_ID, cache_dir=str(args.cache.resolve()), providers=["CPUExecutionProvider"])
    report = run(model, np)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "details"}, indent=2))
