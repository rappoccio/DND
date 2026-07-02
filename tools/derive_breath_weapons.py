#!/usr/bin/env python3
"""Derive NPC breath weapons from the bestiary's free-text Action Notes.

The authoritative bestiary (gui/DND2024_MonsterStats.json) describes recharge
breath weapons only in the prose `meta.action_notes` field (e.g. "Fire Breath
recharge on 5-6 60ft coone 59 fire damage"). This tool parses those clauses and
turns each damaging breath into a save-based AoE spell the combat engine can run:

  * a small family of generic, reusable catalog spells named
    Breath<Element><Shape><Tier>  (a "reskin of Burning Hands": Save AoE, d6 dice,
    once-per-turn then recharge). Tiers bucket the average damage:
        Low <=25 | Medium 26-50 | High 51-75 | Enormous >=76
    Sizes are tier-fixed (see TIER_* below); the per-monster *recharge value*
    (5-6 / 6 / 4-6) is attached on the monster, not baked into the catalog spell.
  * for each monster: the breath spell name is appended to `spell_indices` and the
    recharge die threshold recorded in `npc_spell_recharge` ({name: recharge_min}).

Outliers that don't fit the tier grid (Tarrasque's 150ft cone, Colossus's 300ft
line, multi-element Hellfire, mis-parsed sizes) and mechanically-special actions
are handled by tools/monster_breath_overrides.json.

Usage:
    python3 tools/derive_breath_weapons.py            # dry run: print a report
    python3 tools/derive_breath_weapons.py --write    # apply to spells.json + bestiary
"""
from __future__ import annotations
import json, os, re, sys

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_GUI = os.path.join(os.path.dirname(_TOOLS), "gui")
BESTIARY = os.path.join(_GUI, "DND2024_MonsterStats.json")
SPELLS = os.path.join(_GUI, "spells.json")
OVERRIDES = os.path.join(_TOOLS, "monster_breath_overrides.json")

# ── tier model ──────────────────────────────────────────────────────────────
# Tiers bucket the AoE *footprint* (the tactically decisive property): a breath's
# Low/Medium/High/Enormous label comes from its size, not its damage. Within a
# (element, shape, size-tier) bucket the catalog spell's damage dice are derived
# from the actual average damage of the monsters in that bucket (median), so both
# footprint and damage stay faithful while the spell remains shared/reusable.
TIERS = ("Low", "Medium", "High", "Enormous")

def size_tier(geom, size):
    """Map an AoE's primary size (cone/line length or sphere radius, ft) to a tier."""
    if geom == "Cone":
        bounds = (20, 45, 75)            # 15/30/60/90 ft cones → Low/Med/High/Enorm
    elif geom == "Line":
        bounds = (35, 75, 105)           # length: ≤30 / 40-60 / 90 / 120 ft
    else:                                # Sphere / Emanation / Cube (radius)
        bounds = (17, 28, 50)            # 10-15 / 20 / 30-40 / 60+ ft
    for tier, hi in zip(TIERS, bounds):
        if size <= hi:
            return tier
    return TIERS[-1]

def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

DICE = (4, 6, 8, 10, 12)
def decompose_d6(avg):
    """Dice count N so that N d6 has ≈ avg mean (avg of d6 = 3.5). >=1 die."""
    return max(1, round(avg / 3.5))

# Save ability defaults by damage type (honour an explicit "X save" in the text).
ELEM_SAVE = {
    "fire": "SaveDex", "lightning": "SaveDex", "acid": "SaveDex",
    "force": "SaveDex", "radiant": "SaveDex", "bludgeoning": "SaveDex",
    "cold": "SaveCon", "poison": "SaveCon", "necrotic": "SaveCon", "thunder": "SaveCon",
    "psychic": "SaveInt",
}
ELEM_SCHOOL = {"psychic": "enchantment", "necrotic": "necromancy"}  # else evocation

DMG_TYPES = list(ELEM_SAVE.keys())

# ── Action-Notes parsing ─────────────────────────────────────────────────────
def recharge_min(s):
    m = re.search(r"recharges?\s+(?:on\s+)?(?:a\s+)?(\d)\s*[-–]\s*6", s)
    if m: return int(m.group(1))
    m = re.search(r"recharges?\s+(?:on\s+)?(?:a\s+)?(\d)\b", s)
    return int(m.group(1)) if m else None

def shape_of(s):
    sl = s.lower()
    m = re.search(r"(\d+)\s*ft.{0,12}?(\d+)\s*ft\s*wide\s*line", sl)
    if m: return ("Line", int(m.group(1)), int(m.group(2)))            # length, width
    m = re.search(r"(\d+)\s*ft\s*wide.{0,12}?(\d+)\s*ft\s*line", sl)
    if m: return ("Line", int(m.group(2)), int(m.group(1)))
    m = re.search(r"(\d+)\s*ft\s*co?one\b|(\d+)\s*ft\s*cone", sl)
    if m: return ("Cone", int(m.group(1) or m.group(2)), None)
    m = re.search(r"(\d+)\s*ft\s*radius", sl)
    if m: return ("Sphere", int(m.group(1)), None)
    m = re.search(r"(\d+)\s*ft\s*sphere", sl)
    if m: return ("Sphere", int(m.group(1)), None)
    m = re.search(r"(\d+)\s*ft\s*emanation", sl)
    if m: return ("Emanation", int(m.group(1)), None)
    m = re.search(r"(\d+)\s*ft\s*cube", sl)
    if m: return ("Cube", int(m.group(1)), None)
    m = re.search(r"within\s*(\d+)\s*ft", sl)         # "each creature within Nft" → emanation
    if m: return ("Emanation", int(m.group(1)), None)
    return (None, None, None)

def damage_of(s):
    sl = s.lower()
    m = re.search(r"(\d+)\s+((?:" + "|".join(DMG_TYPES) + r")(?:\s+and\s+\w+)?)", sl)
    if not m:
        return None, []
    avg = int(m.group(1))
    types = [t for t in DMG_TYPES if t in m.group(2)]
    return avg, types

def save_of(s):
    sl = s.lower()
    for ab, key in [("strength","SaveStr"),("dexterity","SaveDex"),("constitution","SaveCon"),
                    ("wisdom","SaveWis"),("intelligence","SaveInt"),("charisma","SaveCha"),
                    ("str","SaveStr"),("dex","SaveDex"),("con","SaveCon"),
                    ("wis","SaveWis"),("int","SaveInt"),("cha","SaveCha")]:
        if re.search(rf"\b{ab}\.?\s*sav", sl):
            return key
    return None

def clauses(note):
    return [c.strip() for c in note.split(",") if c.strip()]

# ── catalog spell construction ───────────────────────────────────────────────
def make_catalog_spell(name, element, geom, tier, save, num_dice, radius, length, width):
    """Build a generic Breath<...> spell dict for spells.json. Size + dice are the
    bucket-derived values; the Low/Medium/High/Enormous label is footprint-based."""
    elem_cap = element.capitalize()
    # Most breaths deal a magic (elemental) type, but a few are physical (e.g. a
    # Bludgeoning rock/force breath). Route the damage roll into the matching list —
    # the engine (and _dict_to_spell) parse Bludgeoning/Piercing/Slashing only via
    # PhysicalDamage; putting them in magic_damage_types crashes the loader.
    dmg_roll = {"type": elem_cap, "num_dice": num_dice, "die_size": 6}
    is_physical = elem_cap in ("Bludgeoning", "Piercing", "Slashing")
    sp = {
        "name": name,
        "description": f"A {tier.lower()} {element} breath weapon ({geom.lower()}). "
                       f"Each creature in the area makes a saving throw, taking the "
                       f"damage on a failure or half as much on a success.",
        "type": "Harm", "geometry": geom, "attack_type": "Save",
        "save_ability": save, "range": 0, "radius": 0, "width": 0, "length": 0,
        "duration": 1,
        "magic_damage_types": [] if is_physical else [dmg_roll],
        "physical_damage_types": [dmg_roll] if is_physical else [],
        "level": 0, "upcast_dice_bonus": 0, "requires_concentration": False,
        "requires_los": False, "check_los_on_center": True,
        "school": ELEM_SCHOOL.get(element, "evocation"),
        # Once-per-turn-then-recharge: uses_max=1; recharge_min stays 0 in the
        # catalog (the actual 5-6/6/4 value is set per monster at load time).
        "uses_max": 1, "uses_remaining": 1, "recharge_min": 0,
    }
    if geom == "Line":
        sp["length"], sp["width"] = int(length), int(width)
    else:  # Cone / Sphere / Emanation
        sp["radius"] = int(radius)
    return sp

# ── main derivation ──────────────────────────────────────────────────────────
def derive():
    bestiary = json.load(open(BESTIARY, encoding="utf-8"))
    spells = json.load(open(SPELLS, encoding="utf-8"))
    overrides = {k: v for k, v in json.load(open(OVERRIDES)).items()
                 if not k.startswith("__")}

    by_name = {s["name"]: s for s in spells}
    catalog_lc = {s["name"].lower(): s["name"] for s in spells}   # for "cast X" resolution
    new_catalog = {}           # name -> spell dict to append
    assignments = {}           # monster -> [(spell_name, recharge_min)]
    report = {"assigned": [], "inline": [], "cast": [],
              "skipped": [], "condition": [], "unparsed": []}
    pending = []               # auto-tiered breaths, bucketed after the walk

    for mon, rec in bestiary.items():
        note = (rec.get("meta") or {}).get("action_notes") or ""
        if "recharge" not in note.lower():
            continue
        ov = overrides.get(mon)
        for cl in clauses(note):
            if "recharge" not in cl.lower():
                continue
            rmin = recharge_min(cl) or 5
            low = cl.lower()
            # Attack-slot recharges ("Attack 2 Recharges on 6") are weapon-level,
            # handled by monster_weapon_overrides / the weapon path — skip here.
            if re.search(r"\b(?:akt|atk|attack)\s*\d", low) and "breath" not in low:
                report["skipped"].append((mon, "attack-slot recharge", cl))
                continue

            if ov and ov.get("action") == "skip":
                report["skipped"].append((mon, ov.get("comment", ""), cl))
                continue
            if ov and ov.get("action") == "inline":
                sp = dict(ov["inline"]); sp["name"] = ov["name"]
                if "description" not in sp:
                    sp["description"] = ov.get("comment", sp["name"])
                new_catalog.setdefault(sp["name"], sp)
                assignments.setdefault(mon, []).append((sp["name"], rmin))
                report["inline"].append((mon, sp["name"], rmin, ov.get("comment", "")))
                continue
            if ov and ov.get("action") == "catalog":
                name = ov["spell"]   # forced reference; spell minted by the auto pass
                assignments.setdefault(mon, []).append((name, rmin))
                report["assigned"].append((mon, name, rmin, "override-catalog"))
                continue

            avg, dtypes = damage_of(cl)
            shape, a, b = shape_of(cl)

            # "<Name> recharges ... cast <Spell>" — a recharge on an existing
            # catalog spell (Ice Devil → Wall of Ice). Reference it + set recharge.
            cm = re.search(r"cast(?:ing)?\s+([a-z' ]+?)(?:\s*\(|$)", cl, re.I)
            if cm and (avg is None):
                cname = catalog_lc.get(cm.group(1).strip().lower())
                if cname:
                    assignments.setdefault(mon, []).append((cname, rmin))
                    report["cast"].append((mon, cname, rmin))
                    continue

            # Auto-tiered path: needs damage + a recognised single-element shape.
            if avg is None or not dtypes:
                # No damage parsed → a condition-only breath (Sleep/Petrifying/etc.),
                # deferred to the condition pass per the "damaging breaths first" scope.
                report["condition"].append((mon, cl))
                continue
            if shape is None:
                report["unparsed"].append((mon, cl))
                continue
            if len(dtypes) > 1:
                report["unparsed"].append((mon, "multi-element (needs override): " + cl))
                continue
            element = dtypes[0]
            geom = "Sphere" if shape == "Cube" else shape   # Cube→Sphere geometry
            size = a                                          # cone/line length or radius
            width = b if geom == "Line" else 0
            tier = size_tier(geom, size)
            save = save_of(cl) or ELEM_SAVE.get(element, "SaveDex")
            pending.append(dict(mon=mon, element=element, geom=geom, tier=tier,
                                size=size, width=width, avg=avg, save=save,
                                rmin=rmin, why=f"{avg} {element} {size}ft {geom}"))

    # ── second pass: build one catalog spell per (element, geom, size-tier),
    #    sizing it from the bucket's median footprint and damage from its median avg.
    buckets = {}
    for p in pending:
        buckets.setdefault((p["element"], p["geom"], p["tier"]), []).append(p)
    for (element, geom, tier), members in buckets.items():
        name = f"Breath{element.capitalize()}{geom}{tier}"
        radius = int(round(median([m["size"] for m in members])))
        length = radius
        width = int(round(median([m["width"] for m in members]))) or 5
        num_dice = decompose_d6(median([m["avg"] for m in members]))
        save = members[0]["save"]
        if name not in by_name and name not in new_catalog:
            new_catalog[name] = make_catalog_spell(
                name, element, geom, tier, save, num_dice, radius, length, width)
        for m in members:
            assignments.setdefault(m["mon"], []).append((name, m["rmin"]))
            report["assigned"].append((m["mon"], name, m["rmin"], m["why"]))

    # Sanity: any forced override-catalog reference must resolve to a real spell.
    for mon, lst in assignments.items():
        for name, _ in lst:
            if name not in by_name and name not in new_catalog:
                report["unparsed"].append((mon, f"override-catalog '{name}' not minted by any bucket"))

    return bestiary, spells, by_name, new_catalog, assignments, report


def apply_changes(bestiary, spells, by_name, new_catalog, assignments):
    # Append new catalog spells (idempotent).
    for name, sp in sorted(new_catalog.items()):
        if name not in by_name:
            spells.append(sp)
    # Attach to monsters.
    for mon, lst in assignments.items():
        rec = bestiary[mon]
        idx = rec.setdefault("spell_indices", [])
        rch = rec.setdefault("npc_spell_recharge", {})
        for name, rmin in lst:
            if name not in idx:
                idx.append(name)
            rch[name] = rmin
    json.dump(spells, open(SPELLS, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(bestiary, open(BESTIARY, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


def main():
    write = "--write" in sys.argv
    bestiary, spells, by_name, new_catalog, assignments, report = derive()

    print(f"=== {len(new_catalog)} catalog Breath spells to add ===")
    for name in sorted(new_catalog):
        sp = new_catalog[name]
        dmg = sp["magic_damage_types"]
        size = (f"radius {sp['radius']}" if sp["geometry"] in ("Cone","Sphere","Emanation")
                else f"{sp['length']}x{sp['width']}")
        d = "+".join(f"{x['num_dice']}d{x['die_size']} {x['type']}" for x in dmg)
        print(f"  {name:34} {sp['geometry']:9} {size:12} {sp['save_ability']:8} {d}")

    print(f"\n=== {sum(len(v) for v in assignments.values())} breath assignments "
          f"across {len(assignments)} monsters ===")
    for mon, name, rmin, why in report["assigned"]:
        print(f"  {mon:28} -> {name:34} recharge {rmin}-6   ({why})")
    for mon, name, rmin, why in report["inline"]:
        print(f"  {mon:28} -> {name:34} recharge {rmin}-6   [INLINE OVERRIDE] {why}")

    print(f"\n=== {len(report['cast'])} recharge-on-an-existing-spell (cast X) ===")
    for mon, name, rmin in report["cast"]:
        print(f"  {mon:28} -> {name:34} recharge {rmin}-6")

    print(f"\n=== {len(report['skipped'])} skipped (deferred / weapon-level) ===")
    for mon, why, cl in report["skipped"]:
        print(f"  {mon:28} {why}")
    print(f"\n=== {len(report['condition'])} condition-only breaths (deferred to condition pass) ===")
    for mon, cl in report["condition"]:
        print(f"  {mon:28} {cl}")
    print(f"\n=== {len(report['unparsed'])} UNPARSED — need review ===")
    for mon, cl in report["unparsed"]:
        print(f"  {mon:28} {cl}")

    if write:
        apply_changes(bestiary, spells, by_name, new_catalog, assignments)
        print(f"\nWROTE {SPELLS} and {BESTIARY}")
    else:
        print("\n(dry run — pass --write to apply)")


if __name__ == "__main__":
    main()
