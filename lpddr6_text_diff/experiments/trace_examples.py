"""Print auditable matching traces for the hand-authored synthetic cases.

Run: python lpddr6_text_diff/experiments/trace_examples.py
This demonstrates a narrow rule comparator, not a JEDEC semantic classifier.
"""
import json
import re
from difflib import SequenceMatcher

from compare_baselines import build_cases, normalize, select, similarity, tokens


def candidates(case):
    blocks = case["new"]
    groups = [[b] for b in blocks]
    for size in (2, 3):
        for start in range(len(blocks) - size + 1):
            group = blocks[start:start + size]
            if len({b["title"] for b in group}) == 1:
                groups.append(group)
    result = []
    for group in groups:
        lexical = similarity(case["old"]["text"], " ".join(b["text"] for b in group))
        context = sum(similarity(case["old"]["title"], b["title"]) for b in group) / len(group)
        score = .7 * lexical + .3 * context - .02 * (len(group) - 1)
        result.append({"new_ids": [b["id"] for b in group],
                       "text": " ".join(b["text"] for b in group),
                       "lexical": round(lexical, 4),
                       "title": round(context, 4),
                       "score": round(score, 4)})
    return sorted(result, key=lambda x: x["score"], reverse=True)


def token_edits(old, new):
    a, b = tokens(old), tokens(new)
    return [{"operation": op, "old": " ".join(a[i:j]), "new": " ".join(b[k:l])}
            for op, i, j, k, l in SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
            if op != "equal"]


def narrow_rule(case, selected, new_text):
    """Rule decisions only for provable cases in this miniature vocabulary."""
    if not selected:
        return {"result": "unmatched", "reason": "No candidate above 0.50; deletion not proved."}
    old = case["old"]["text"]
    old_context, new_context = case.get("old_context"), case.get("new_context")
    if old_context or new_context:
        if old_context != new_context:
            return {"result": "requirement_changed", "field": "inherited_condition",
                    "old": old_context, "new": new_context}
    if normalize(old) == normalize(new_text):
        return {"result": "same_local_text", "reason": "Other dependencies not checked in this demo."}
    old_neg, new_neg = bool(re.search(r"\bshall not\b", old)), bool(re.search(r"\bshall not\b", new_text))
    if old_neg != new_neg and old.replace("shall not", "shall") == new_text.replace("shall not", "shall"):
        return {"result": "requirement_changed", "field": "polarity", "old": old_neg, "new": new_neg}
    pattern = r"\bat least (\d+) (ns|ps)\b"
    old_amount, new_amount = re.search(pattern, old), re.search(pattern, new_text)
    if old_amount and new_amount and old_amount.group(2) == new_amount.group(2):
        old_num, new_num = int(old_amount.group(1)), int(new_amount.group(1))
        if old_num != new_num and re.sub(pattern, "at least VALUE UNIT", old) == re.sub(pattern, "at least VALUE UNIT", new_text):
            return {"result": "requirement_changed", "field": "minimum_wait",
                    "old": f"{old_num} {old_amount.group(2)}", "new": f"{new_num} {new_amount.group(2)}"}
    return {"result": "unresolved", "reason": "No sound rule for this wording and its dependencies."}


def run():
    chosen = {"numeric", "negation", "paraphrase", "inherited_condition", "repeated_boilerplate", "split", "deletion"}
    traces = []
    for case in build_cases():
        if case["name"] not in chosen:
            continue
        ranked = candidates(case)
        selected = select(case, "lexical_context_groups")
        new_text = " ".join(b["text"] for b in case["new"] if b["id"] in selected)
        traces.append({"case": case["name"], "old_text": case["old"]["text"],
                       "old_title": case["old"]["title"],
                       "old_context": case.get("old_context"), "new_context": case.get("new_context"),
                       "ranked_candidates": ranked, "selected_ids": selected,
                       "gold_ids": case["gold_ids"], "matching_correct": set(selected) == set(case["gold_ids"]),
                       "token_edits_on_selected": token_edits(case["old"]["text"], new_text) if selected else [],
                       "narrow_rule": narrow_rule(case, selected, new_text),
                       "expert_label_in_fixture": "requirement_changed" if case["gold_requirement_changed"] else "equivalent"})
    return {"synthetic_only": True, "matcher": "lexical_context_groups",
            "selection_cutoff": 0.5, "traces": traces}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
