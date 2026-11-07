"""Small reproducible test on public JESD209-4D/4E Scope preview excerpts.

The short excerpts below come from the cited publisher preview pages. This
does not use or reproduce the full standards, and does not test LPDDR6.
"""
import json
from difflib import SequenceMatcher

from compare_baselines import similarity, tokens


OLD_URL = "https://store.accuristech.com/aia/products/preview/2505640"
NEW_URL = "https://store.accuristech.com/products/preview/2906163"
OLD = [
    {"id": "D-scope-dual", "text": "dual channel device density ranges from 4 Gb through 32 Gb"},
    {"id": "D-scope-single", "text": "single channel density ranges from 2 Gb through 16 Gb"},
]
NEW = [
    {"id": "E-scope-dual", "text": "dual channel device density ranges from 2 Gb through 32 Gb"},
    {"id": "E-scope-single", "text": "single channel density ranges from 1 Gb through 16 Gb"},
]


def edits(left, right):
    a, b = tokens(left), tokens(right)
    return [{"kind": kind, "old": " ".join(a[i:j]), "new": " ".join(b[k:l])}
            for kind, i, j, k, l in SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
            if kind != "equal"]


def run():
    pairs = []
    for old in OLD:
        ranked = sorted([{"new_id": new["id"], "lexical_score": round(similarity(old["text"], new["text"]), 4)}
                         for new in NEW], key=lambda x: x["lexical_score"], reverse=True)
        new = next(x for x in NEW if x["id"] == ranked[0]["new_id"])
        pairs.append({"old_id": old["id"], "old_text": old["text"],
                      "ranked_new_candidates": ranked, "chosen_new_id": new["id"],
                      "new_text": new["text"], "token_edits": edits(old["text"], new["text"])})
    assert len({p["chosen_new_id"] for p in pairs}) == len(pairs)
    return {"standard": "JEDEC JESD209-4", "old_revision": "D", "new_revision": "E",
            "source_location": "Section 1 Scope (public publisher previews)",
            "old_preview_url": OLD_URL, "new_preview_url": NEW_URL,
            "full_document_compared": False, "text_encoder_used": False, "pairs": pairs}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
