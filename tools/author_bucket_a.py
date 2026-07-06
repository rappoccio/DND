#!/usr/bin/env python3
"""Phase 2 Bucket A: author fixed-split multiattack recipes into the bestiary.
Additive, idempotent. References weapon slots 0 (main_hand) / 1 (off_hand) only,
so it is valid under the current dict-form weapon layout. Asserts
sum(counts) == num_attacks and every referenced slot is a non-empty weapon."""
import json, shutil, sys

PATH = "gui/DND2024_MonsterStats.json"

# monster -> ordered [[slot, count], ...]  (from MULTIATTACK_RECIPES_PLAN.md Bucket A)
RECIPES = {
    "Brown Bear":        [[0, 1], [1, 1]],
    "Bone Devil":        [[0, 2], [1, 1]],
    "Otyugh":            [[0, 1], [1, 2]],
    "Xorn":              [[0, 1], [1, 3]],
    "Wyvern":            [[0, 1], [1, 1]],
    "Grick":             [[0, 1], [1, 1]],
    "Ettercap":          [[0, 1], [1, 1]],
    "Ettin":             [[0, 1], [1, 1]],
    "Giant Crocodile":   [[0, 1], [1, 1]],
    "Tyrannosaurus Rex": [[0, 1], [1, 1]],
    "Unicorn":           [[0, 1], [1, 1]],
    "Purple Worm":       [[0, 1], [1, 1]],
    "Bearded Devil":     [[0, 1], [1, 1]],
    "Balor":             [[0, 1], [1, 1]],
    "Giant Scorpion":    [[0, 2], [1, 1]],
    "Cloaker":           [[0, 1], [1, 2]],
    "Tarrasque":         [[0, 1], [1, 3]],
}

SLOT_KEY = {0: "main_hand", 1: "off_hand", 2: "ranged"}


def nonempty(w):
    return isinstance(w, dict) and bool(w.get("name"))


def main():
    d = json.load(open(PATH))
    errors = []
    for name, recipe in RECIPES.items():
        rec = d.get(name)
        if rec is None:
            errors.append(f"{name}: not in bestiary")
            continue
        st = rec["stats"]
        w = rec["weapons"]
        na = st.get("num_attacks")
        total = sum(c for _, c in recipe)
        if total != na:
            errors.append(f"{name}: sum(counts)={total} != num_attacks={na}")
        for slot, _ in recipe:
            if not nonempty(w.get(SLOT_KEY[slot])):
                errors.append(f"{name}: slot {slot} ({SLOT_KEY[slot]}) is empty")
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    shutil.copy(PATH, PATH + ".bak_bucketA")
    for name, recipe in RECIPES.items():
        d[name]["stats"]["multiattack"] = recipe
    with open(PATH, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(RECIPES)} Bucket A recipes. Backup: {PATH}.bak_bucketA")


if __name__ == "__main__":
    main()
