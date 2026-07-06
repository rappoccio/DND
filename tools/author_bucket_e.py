#!/usr/bin/env python3
"""Phase 2 Bucket E: author multiattack recipes for the non-SRD 2-melee monsters.

Scope (see MULTIATTACK_RECIPES_PLAN.md Bucket E): the ~49 non-SRD records that
carry TWO distinct melee weapons and num_attacks > 1. These are the only Bucket E
monsters that genuinely need a recipe -- 1-melee and melee+ranged records fall
through to the legacy free-combo path (guarded by verify_legacy_multiattack.py),
and no monster is weaponless-with-spells.

All 49 store weapons dict-form with the two melee weapons at main_hand(0)/off_hand(1),
so recipes reference slots 0/1 only and are valid under the current layout -- no
migration needed (same as Bucket A).

Split heuristic: `[[0,1],[1,na-1]]` -- lead weapon once, remaining attacks with the
second weapon (the standard SRD "one special bite/beak + rest claws" shape). The
`action_notes` "Atk N / Akt N" shorthand is used only to CORROBORATE the split and
set a confidence tag; it never silently flips it. OVERRIDES pins any record whose
correct split differs from the heuristic.

Additive, idempotent. Asserts sum(counts) == num_attacks and every referenced slot
is a non-empty melee weapon. Writes a .bak_bucketE backup. Run with --write.
"""
import json, os, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_legacy_multiattack import LEGACY_NAMES  # single source of the Bucket C roster

PATH = "gui/DND2024_MonsterStats.json"
SLOT_KEY = {0: "main_hand", 1: "off_hand", 2: "ranged"}

# Bucket C monsters stay legacy (free-combo / bespoke). They must NOT get a recipe,
# else verify_legacy_multiattack.py fails. Dragons are matched by name there too, but
# they are all 1-melee so never reach this 2-melee bucket -- excluded defensively anyway.
def is_legacy(name):
    return name in LEGACY_NAMES or "dragon" in name.lower()

# SRD-verified pins: monster -> [[slot,count],...], cross-checked against stat-block
# text. Locks the split (and confidence) so a future note-parser change can't drift it.
# These four happen to match the lead-once heuristic; pinning records that they were
# confirmed, not merely inferred.
CONFIRMED = {
    "Arcanaloth":             [[0, 1], [1, 2]],  # 1 melee + 2 (user-confirmed)
    "Cockatrice Regent":      [[0, 1], [1, 2]],  # 1 Petrifying Bite + 2 Talons
    "Gnoll Fang of Yeenoghu": [[0, 1], [1, 2]],  # 1 Bite + 2 Bone Flail
    "Goristro":               [[0, 1], [1, 2]],  # 1 Brutal Gore + 2 Slam
}

# Manual pins for splits that DIFFER from the heuristic. Empty today. CONFIRMED and
# OVERRIDES are both consulted (OVERRIDES wins) before the heuristic.
OVERRIDES = {}

# Excluded from Bucket E entirely -- left to the legacy free-combo path (user: "ignore").
SKIP = {"Phaerimm Elder", "Queen Forfallen"}


def nonempty(w):
    return isinstance(w, dict) and bool(w.get("name"))


def melee_slots(w):
    """Slot indices (dict-form) holding a non-empty melee weapon, in order."""
    out = []
    for slot in (0, 1, 2):
        v = w.get(SLOT_KEY[slot])
        if nonempty(v) and v.get("type") != "ranged":
            out.append(slot)
    return out


def is_two_melee_target(name, rec):
    if is_legacy(name) or name in SKIP:
        return False
    st = rec.get("stats", {})
    if st.get("multiattack") or rec.get("multiattack"):
        return False
    if st.get("num_attacks", 1) <= 1:
        return False
    return len(melee_slots(rec.get("weapons", {}))) == 2


def derive(name, rec):
    """Return (recipe, confidence, reason)."""
    if name in OVERRIDES:
        return OVERRIDES[name], "pinned", "manual override (differs from heuristic)"
    if name in CONFIRMED:
        return CONFIRMED[name], "high", "SRD-verified"
    na = rec["stats"]["num_attacks"]
    s0, s1 = melee_slots(rec["weapons"])  # (0, 1) for all 49
    recipe = [[s0, 1], [s1, na - 1]]
    note = (rec.get("meta", {}) or {}).get("action_notes") or ""
    atk_ns = sorted(int(n) for n in re.findall(r"(?:Atk|Akt)\s*(\d+)", note))
    if na == 2:
        conf, why = "high", "na==2: split is unambiguous"
    elif atk_ns and max(atk_ns) >= 2 and 1 not in atk_ns[1:]:
        conf, why = "high", f"note Atk-index {atk_ns} corroborates lead-once"
    elif atk_ns:
        conf, why = "med", f"note has Atk-index {atk_ns}; heuristic split"
    else:
        conf, why = "med", "no note; layout-only heuristic"
    return recipe, conf, why


def main():
    write = "--write" in sys.argv
    d = json.load(open(PATH))
    targets = [(n, r) for n, r in d.items() if is_two_melee_target(n, r)]

    rows, errors = [], []
    for name, rec in targets:
        recipe, conf, why = derive(name, rec)
        na = rec["stats"]["num_attacks"]
        total = sum(c for _, c in recipe)
        if total != na:
            errors.append(f"{name}: sum(counts)={total} != num_attacks={na}")
        for slot, _ in recipe:
            v = rec["weapons"].get(SLOT_KEY[slot])
            if not nonempty(v) or v.get("type") == "ranged":
                errors.append(f"{name}: slot {slot} is not a melee weapon")
        rows.append((name, na, recipe, conf, why))

    w0 = max(len(r[0]) for r in rows)
    print(f"Bucket E: {len(rows)} two-melee recipes\n")
    print(f"  {'monster':<{w0}}  na  recipe            conf  reason")
    print("  " + "-" * (w0 + 55))
    for name, na, recipe, conf, why in rows:
        rc = str(recipe)
        print(f"  {name:<{w0}}  {na:<2}  {rc:<16}  {conf:<4}  {why}")

    by_conf = {}
    for r in rows:
        by_conf[r[3]] = by_conf.get(r[3], 0) + 1
    print("\n  confidence:", ", ".join(f"{k}={v}" for k, v in sorted(by_conf.items())))

    if errors:
        print("\nVALIDATION FAILED:")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    if not write:
        print("\n(dry run) re-run with --write to author these recipes.")
        return

    shutil.copy(PATH, PATH + ".bak_bucketE")
    for name, _, recipe, _, _ in rows:
        d[name]["stats"]["multiattack"] = recipe
    with open(PATH, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(rows)} Bucket E recipes. Backup: {PATH}.bak_bucketE")


if __name__ == "__main__":
    main()
