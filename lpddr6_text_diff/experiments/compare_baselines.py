"""Small synthetic diagnostic, not a JEDEC benchmark. Python standard library only.

Run from repository root:
  python lpddr6_text_diff/experiments/compare_baselines.py
No model calls, no network, no writes unless --output is given.
"""
import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path


def normalize(text):
    return " ".join(text.split())


def tokens(text):
    # Case and technical tokens remain significant.
    return re.findall(r"[A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?|>=|<=|!=|[^\w\s]", text)


def similarity(a, b):
    a, b = tokens(a), tokens(b)
    # SequenceMatcher can be asymmetric: use the mean for ranking.
    return (SequenceMatcher(None, a, b, autojunk=False).ratio()
            + SequenceMatcher(None, b, a, autojunk=False).ratio()) / 2


def block(identifier, text, title="CMD_X timing"):
    return {"id": identifier, "text": text, "title": title}


def build_cases():
    old = "The controller shall wait at least 10 ns after CMD_X."
    distractor = block("other", "The device shall remain in State_Z.", "State_Z")

    def case(name, new, changed, old_text=old, old_title="CMD_X timing",
             new_title="CMD_X timing"):
        return {"name": name, "old": block("old", old_text, old_title),
                "new": [distractor, block("target", new, new_title)],
                "gold_ids": ["target"], "gold_requirement_changed": changed}

    cases = [
        case("unchanged", old, False),
        case("line_wrap", old.replace("shall wait", "shall\n  wait"), False),
        case("paraphrase", "Following CMD_X, a minimum delay of 10 ns is required of the controller.", False),
        case("numeric", old.replace("10", "12"), True),
        case("negation", "The controller shall not issue CMD_X.", True,
             old_text="The controller shall issue CMD_X."),
        case("boundary", old.replace("at least", "more than"), True),
        case("modality", old.replace("shall", "may"), True),
        case("condition", "In Mode_B, " + old, True, old_text="In Mode_A, " + old),
        case("unit_equivalence", old.replace("10 ns", "10000 ps"), False),
        case("renumber", "See Table 9 for the CMD_X timing requirements.", False,
             old_text="See Table 7 for the CMD_X timing requirements."),
        case("inherited_condition", old, True),
        case("repeated_boilerplate", "Wait for the operation to finish.", False,
             old_text="Wait until the operation completes.", old_title="Calibration", new_title="Calibration"),
        case("section_move", old, False, old_title="4.2 CMD_X timing", new_title="5.1 CMD_X timing"),
    ]
    cases[9]["context_note"] = "Table 7 and Table 9 are the same table, unchanged except its number."
    cases[10]["old_context"] = "This section applies in Mode_A."
    cases[10]["new_context"] = "This section applies in Mode_B."
    cases[11]["new"][0] = block("other", "Wait until the operation completes.", "Initialization")
    cases.append({"name": "split", "old": block("old", old + " The device shall remain in State_Z."),
                  "new": [block("a", old), block("b", "The device shall remain in State_Z.")],
                  "gold_ids": ["a", "b"], "gold_requirement_changed": False})
    cases.append({"name": "deletion", "old": block("old", old),
                  "new": [distractor], "gold_ids": [], "gold_requirement_changed": True})
    return cases


def select(case, method):
    old, new = case["old"], case["new"]
    if method == "exact":
        matches = [b for b in new if normalize(b["text"]) == normalize(old["text"])]
        return [matches[0]["id"]] if len(matches) == 1 else []
    groups = [[b] for b in new]
    if method == "lexical_context_groups":
        for size in (2, 3):
            for start in range(len(new) - size + 1):
                group = new[start:start + size]
                if len({b["title"] for b in group}) == 1:
                    groups.append(group)
    scores = []
    for group in groups:
        lex = similarity(old["text"], " ".join(b["text"] for b in group))
        if method == "lexical":
            score = lex
        else:
            ctx = sum(similarity(old["title"], b["title"]) for b in group) / len(group)
            score = .7 * lex + .3 * ctx - .02 * (len(group) - 1)
        scores.append((score, [b["id"] for b in group]))
    scores.sort(key=lambda x: x[0], reverse=True)
    # Diagnostic setting only; empty means unmatched, NOT confirmed deletion.
    return scores[0][1] if scores and scores[0][0] >= .5 else []


def metrics(gold, predicted):
    tp = sum(g and p for g, p in zip(gold, predicted))
    fp = sum(not g and p for g, p in zip(gold, predicted))
    fn = sum(g and not p for g, p in zip(gold, predicted))
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None}


def run():
    cases = build_cases()
    result = {"synthetic_only": True, "case_count": len(cases),
              "encoder_tested": False,
              "limitations": ["Hand-authored tiny diagnostic, not held-out performance.",
                              "Per-case candidate pools; no full-document global matching.",
                              "Similarity-only semantic baselines intentionally lack dependency analysis.",
                              "No measured semantic LLM or encoder result."],
              "matching": {}, "comparison_on_gold_alignment": {}}
    for method in ("exact", "lexical", "lexical_context", "lexical_context_groups"):
        detail = [{"case": c["name"], "predicted_ids": select(c, method), "gold_ids": c["gold_ids"]}
                  for c in cases]
        matched = [d for d in detail if d["gold_ids"]]
        result["matching"][method] = {
            "gold_nonempty_groups": len(matched),
            "correct_groups": sum(set(d["predicted_ids"]) == set(d["gold_ids"]) for d in matched),
            "deletion_case_unmatched": detail[-1]["predicted_ids"] == [], "detail": detail}
    gold = [c["gold_requirement_changed"] for c in cases]
    for method in ("any_text_change", "similarity_below_0.85", "similarity_below_0.90", "similarity_below_0.95"):
        predictions, details = [], []
        for c in cases:
            target = " ".join(b["text"] for b in c["new"] if b["id"] in c["gold_ids"])
            sim = similarity(c["old"]["text"], target)
            if method == "any_text_change":
                p = normalize(c["old"]["text"]) != normalize(target)
            else:
                p = sim < float(method.rsplit("_", 1)[1])
            predictions.append(p)
            details.append({"case": c["name"], "lexical_similarity": round(sim, 6),
                            "predicted_requirement_changed": p, "gold_requirement_changed": c["gold_requirement_changed"]})
        result["comparison_on_gold_alignment"][method] = {**metrics(gold, predictions), "detail": details}
    # Fixture integrity: targets must exist, and identifiers must be unique per case.
    for c in cases:
        ids = [b["id"] for b in c["new"]]
        assert len(set(ids)) == len(ids)
        assert set(c["gold_ids"]) <= set(ids)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = run()
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    compact = {**results,
               "matching": {k: {a: b for a, b in v.items() if a != "detail"} for k, v in results["matching"].items()},
               "comparison_on_gold_alignment": {k: {a: b for a, b in v.items() if a != "detail"} for k, v in results["comparison_on_gold_alignment"].items()}}
    print(json.dumps(compact, indent=2))
