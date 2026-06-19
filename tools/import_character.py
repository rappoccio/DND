#!/usr/bin/env python3
"""
import_character.py — Build one of our agent JSON records from a D&D Beyond character.

Source of truth is D&D Beyond's *public* character API:
    https://character-service.dndbeyond.com/character/v5/character/<id>
which returns the character as base values + a `modifiers` rules engine. This tool
*derives* the final, flat numbers our combat engine wants (final ability scores, AC,
HP, proficiency bonus, save proficiencies, spell slots, …) and maps names onto our
catalogs (weapons.json / armor.json / spells.json) and class/subclass enums.

Design (decided 2026-06-11, "Option A"):
  - Digital only: accept a DDB character URL or bare id; fetch with urllib (no deps).
  - Best-effort + warn: map what we can, approximate/drop the rest (e.g. multiclass →
    highest single class), printing warnings to stderr; still emit a usable record.
  - Lossless source: the raw DDB JSON is saved alongside as a sidecar (.ddb.json) so we
    never lose data and can re-derive later (see TODO.md "Option B" — native rich schema).

This script reads only plain JSON catalogs (no rpg_battle_map import), so it runs on the
host without the C++ build.

Usage:
    python tools/import_character.py <url_or_id> [<url_or_id> ...]
        [--out FILE.json]              # write a standalone {"agents":[...]} file
        [--merge encounters/FILE.json] # merge into an existing agents file (in place)
        [--faction N]                  # faction for newly-appended agents (default 0)
        [--sidecar-dir DIR]            # where to drop raw .ddb.json (default tools/ddb_sources)
        [--no-fetch]                   # treat args as local .ddb.json paths instead of ids
"""
import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
GUI = os.path.join(os.path.dirname(HERE), "gui")

API = "https://character-service.dndbeyond.com/character/v5/character/{}"

# DDB ability ids → our stat keys (note our key is 'intel', not 'int').
ABILITY_BY_ID = {1: "str", 2: "dex", 3: "con", 4: "intel", 5: "wis", 6: "cha"}
ABILITY_NAME = {1: "strength", 2: "dexterity", 3: "constitution",
                4: "intelligence", 5: "wisdom", 6: "charisma"}
SCORE_SUBTYPE = {f"{ABILITY_NAME[i]}-score": ABILITY_BY_ID[i] for i in ABILITY_BY_ID}
SPELLCAST_ABILITY = {1: "str", 2: "dex", 3: "con", 4: "intel", 5: "wis", 6: "cha"}

MAGIC_DAMAGE = ["Acid", "Cold", "Fire", "Force", "Lightning",
                "Necrotic", "Poison", "Psychic", "Radiant", "Thunder"]
PHYSICAL_DAMAGE = ["Bludgeoning", "Piercing", "Slashing"]

# Our engine enum value strings per class (from gui/dialogs.py subclass lists).
SUBCLASS_KEY = {
    "Barbarian": "agent_barbarian_subclass", "Fighter": "agent_fighter_subclass",
    "Druid": "agent_druid_circle", "Monk": "agent_monk_subclass",
    "Paladin": "agent_paladin_oath", "Wizard": "agent_wizard_subclass",
    "Warlock": "agent_warlock_subclass", "Rogue": "agent_rogue_subclass",
    "Cleric": "agent_cleric_subclass", "Bard": "agent_bard_subclass",
    "Sorcerer": "agent_sorcerer_subclass",
}
SUBCLASS_ENUMS = {
    "Barbarian": ["Berserker", "WildHeart", "WorldTree", "Zealot"],
    "Fighter": ["Champion", "BattleMaster", "PsiWarrior", "EldritchKnight"],
    "Druid": ["CircleOfMoon", "CircleOfLand", "CircleOfSea", "CircleOfStars",
              "CircleOfSpores", "CircleOfWildfire"],
    "Monk": ["WarriorOfTheOpenHand", "WarriorOfMercy", "WarriorOfShadow",
             "WarriorOfFourElements"],
    "Paladin": ["OathOfDevotion", "OathOftheMountedWarrior", "OathOfRedemption",
                "OathOfVengeance"],
    "Wizard": ["Abjurer", "Diviner", "Evoker", "Illusionist"],
    "Warlock": ["Archfey", "Celestial", "Fiend", "GreatOldOne"],
    "Rogue": ["ArcaneTrickster", "Assassin", "Soulknife", "Thief"],
    "Cleric": ["LifeDomain", "LightDomain", "TrickeryDomain", "WarDomain"],
    "Bard": ["Dance", "Glamour", "Lore", "Valor"],
    "Sorcerer": ["Aberrant", "Clockwork", "Draconic", "WildMagic"],
}
# DDB subclass display name (normalized) → our enum value, for the cases a normalized
# or substring match can't reach (school-of-X → X-er, suffixed sorcery names, etc.).
SUBCLASS_ALIASES = {
    "schoolofabjuration": "Abjurer", "schoolofdivination": "Diviner",
    "schoolofevocation": "Evoker", "schoolofillusion": "Illusionist",
    "draconicbloodline": "Draconic", "draconicsorcery": "Draconic",
    "clockworksoul": "Clockwork", "aberrantmind": "Aberrant", "aberrantsorcery": "Aberrant",
    "wildmagicsorcery": "WildMagic", "thecollegeoflore": "Lore",
}

# Engine-recognized feat names we are willing to pass into the feats vector. Anything
# else from DDB (homebrew, ASI markers, non-combat) is dropped with a warning.
KNOWN_FEATS = {
    "Tough", "Alert", "Savage Attacker", "Tavern Brawler", "Lucky",
    "Crusher", "Piercer", "Slasher", "Great Weapon Master", "Grappler", "Sentinel",
    "War Caster", "Mage Slayer", "Defensive Duelist", "Shield Master",
    "Sharpshooter", "Crossbow Expert", "Spell Sniper", "Dual Wielder",
    "Heavy Armor Master", "Medium Armor Master", "Durable", "Speedy", "Athlete",
    "Skulker", "Telekinetic", "Weapon Master", "Resilient", "Elemental Adept", "Poisoner",
    "Weapon Mastery",
}

# DDB sometimes prefixes the granted-at level, e.g. "4: Weapon Mastery". Strip that.
_FEAT_LEVEL_PREFIX = re.compile(r"^\d+:\s*")

# Per-class spell-slot tables (index 0 == 1st-level slots), keyed by class LEVEL.
FULL_CASTER = {
    1: [2], 2: [3], 3: [4, 2], 4: [4, 3], 5: [4, 3, 2], 6: [4, 3, 3],
    7: [4, 3, 3, 1], 8: [4, 3, 3, 2], 9: [4, 3, 3, 3, 1], 10: [4, 3, 3, 3, 2],
    11: [4, 3, 3, 3, 2, 1], 12: [4, 3, 3, 3, 2, 1], 13: [4, 3, 3, 3, 2, 1, 1],
    14: [4, 3, 3, 3, 2, 1, 1], 15: [4, 3, 3, 3, 2, 1, 1, 1], 16: [4, 3, 3, 3, 2, 1, 1, 1],
    17: [4, 3, 3, 3, 2, 1, 1, 1, 1], 18: [4, 3, 3, 3, 3, 1, 1, 1, 1],
    19: [4, 3, 3, 3, 3, 2, 1, 1, 1], 20: [4, 3, 3, 3, 3, 2, 2, 1, 1],
}
HALF_CASTER = {
    1: [], 2: [2], 3: [3], 4: [3], 5: [4, 2], 6: [4, 2], 7: [4, 3], 8: [4, 3],
    9: [4, 3, 2], 10: [4, 3, 2], 11: [4, 3, 3], 12: [4, 3, 3], 13: [4, 3, 3, 1],
    14: [4, 3, 3, 1], 15: [4, 3, 3, 2], 16: [4, 3, 3, 2], 17: [4, 3, 3, 3, 1],
    18: [4, 3, 3, 3, 1], 19: [4, 3, 3, 3, 2], 20: [4, 3, 3, 3, 2],
}
# Warlock Pact Magic: (number_of_slots, slot_level) by class level.
PACT = {1: (1, 1), 2: (2, 1), 3: (2, 2), 4: (2, 2), 5: (2, 3), 6: (2, 3),
        7: (2, 4), 8: (2, 4), 9: (2, 5), 10: (2, 5), 11: (3, 5), 12: (3, 5),
        13: (3, 5), 14: (3, 5), 15: (3, 5), 16: (3, 5), 17: (4, 5), 18: (4, 5),
        19: (4, 5), 20: (4, 5)}
CASTER_TYPE = {"Bard": "full", "Cleric": "full", "Druid": "full", "Sorcerer": "full",
               "Wizard": "full", "Paladin": "half", "Ranger": "half", "Warlock": "pact"}
EXTRA_ATTACK_5 = {"Barbarian", "Monk", "Paladin", "Ranger"}

_WARN = []


def warn(msg):
    _WARN.append(msg)
    print(f"  ! {msg}", file=sys.stderr)


def norm(s):
    """ASCII-fold, lowercase, strip non-letters."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


# ── fetch ────────────────────────────────────────────────────────────────────
def fetch_character(arg, no_fetch=False):
    if no_fetch:
        with open(arg) as f:
            blob = json.load(f)
        return blob.get("data", blob)
    m = re.search(r"(\d{4,})", str(arg))
    if not m:
        raise ValueError(f"could not find a character id in {arg!r}")
    cid = m.group(1)
    req = urllib.request.Request(API.format(cid), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        blob = json.load(resp)
    if not blob.get("success", True):
        raise RuntimeError(f"DDB API failure for {cid}: {blob.get('message')}")
    return blob["data"]


# ── derivation helpers ─────────────────────────────────────────────────────────
def all_modifiers(data):
    out = []
    for lst in (data.get("modifiers") or {}).values():
        out.extend(lst or [])
    return out


def final_ability_scores(data, mods):
    base = {ABILITY_BY_ID[s["id"]]: s["value"] for s in data.get("stats", [])}
    override = {ABILITY_BY_ID[s["id"]]: s["value"] for s in data.get("overrideStats", [])}
    bonusst = {ABILITY_BY_ID[s["id"]]: s["value"] for s in data.get("bonusStats", [])}
    score_bonus = {k: 0 for k in ABILITY_BY_ID.values()}
    for m in mods:
        if m.get("type") == "bonus" and m.get("subType") in SCORE_SUBTYPE:
            score_bonus[SCORE_SUBTYPE[m["subType"]]] += m.get("value") or 0
    final = {}
    for k in ABILITY_BY_ID.values():
        if override.get(k) is not None:
            final[k] = override[k]
        else:
            final[k] = (base.get(k) or 10) + (bonusst.get(k) or 0) + score_bonus[k]
    return final


def mod(score):
    return (score - 10) // 2


def total_level(data):
    return sum(c.get("level", 0) for c in data.get("classes", []))


def primary_class(data):
    classes = data.get("classes", [])
    if not classes:
        return None
    return max(classes, key=lambda c: c.get("level", 0))


def compute_hp(data, mods, con_mod, tlevel):
    if data.get("overrideHitPoints") is not None:
        return int(data["overrideHitPoints"])
    base = data.get("baseHitPoints") or 0
    bonus = data.get("bonusHitPoints") or 0
    per_level = sum((m.get("value") or 0) for m in mods
                    if m.get("type") == "bonus" and m.get("subType") == "hit-points-per-level")
    return int(base + con_mod * tlevel + bonus + per_level * tlevel)


def compute_ac(data, mods, dex_mod):
    """Final AC from equipped armor + DEX(capped) + shield + AC-bonus modifiers.
    armorTypeId: 1 light, 2 medium, 3 heavy, 4 shield."""
    cap_by_type = {1: 99, 2: 2, 3: 0}
    body, shield_ac = None, 0
    for it in data.get("inventory", []):
        de = it.get("definition", {})
        if de.get("filterType") != "Armor" or not it.get("equipped"):
            continue
        at = de.get("armorTypeId")
        if at == 4:
            shield_ac += de.get("armorClass") or 0
        elif at in (1, 2, 3):
            if body is None or (de.get("armorClass") or 0) > (body[0]):
                body = (de.get("armorClass") or 0, at)
    ac_bonus = sum((m.get("value") or 0) for m in mods if m.get("type") == "bonus"
                   and m.get("subType") in ("armor-class", "armored-armor-class",
                                            "unarmored-armor-class"))
    if body:
        return body[0] + min(dex_mod, cap_by_type[body[1]]) + shield_ac + ac_bonus
    # Unarmored: 10 + DEX (+ shield + AC mods). Class unarmored-defense (Barb/Monk/etc.)
    # is recomputed by the engine on its own; this is the generic floor.
    return 10 + dex_mod + shield_ac + ac_bonus


def match_subclass(cls, ddb_name):
    if not ddb_name:
        return "NONE"
    enums = SUBCLASS_ENUMS.get(cls, [])
    n = norm(ddb_name)
    nt = n.replace("the", "")
    for e in enums:                                  # exact / 'the'-insensitive
        if n == norm(e) or nt == norm(e).replace("the", ""):
            return e
    if n in SUBCLASS_ALIASES and SUBCLASS_ALIASES[n] in enums:
        return SUBCLASS_ALIASES[n]
    for pre in ("pathof", "wayof", "collegeof", "schoolof"):  # strip filler prefix
        if n.startswith(pre):
            rest = n[len(pre):].replace("the", "")
            for e in enums:
                if norm(e).replace("the", "") == rest:
                    return e
    for e in enums:                                  # substring fallback (warned)
        if norm(e) in n or n in norm(e):
            warn(f"subclass '{ddb_name}' matched '{e}' by substring — verify")
            return e
    warn(f"subclass '{ddb_name}' ({cls}) not in our enums — left NONE")
    return "NONE"


def compute_slots(cls, level):
    slots = [0] * 9
    ct = CASTER_TYPE.get(cls)
    if ct == "full":
        for i, v in enumerate(FULL_CASTER.get(level, [])):
            slots[i] = v
    elif ct == "half":
        for i, v in enumerate(HALF_CASTER.get(level, [])):
            slots[i] = v
    elif ct == "pact":
        count, lvl = PACT.get(level, (0, 1))
        slots[lvl - 1] = count
    return slots


def collect_spells(data, spell_catalog):
    names, seen = [], set()

    def add(nm):
        if nm and nm not in seen:
            seen.add(nm)
            names.append(nm)

    for cs in data.get("classSpells", []):
        for s in cs.get("spells", []):
            add((s.get("definition") or {}).get("name"))
    for bucket in (data.get("spells") or {}).values():
        if isinstance(bucket, list):
            for s in bucket:
                add((s.get("definition") or {}).get("name"))
    keep = [n for n in names if n in spell_catalog]
    dropped = [n for n in names if n not in spell_catalog]
    if dropped:
        warn(f"spells not in our catalog (dropped): {', '.join(dropped)}")
    return keep


def _catalog_lookup(name, weapon_catalog):
    """Exact then case-insensitive lookup; returns a fresh dict with defaults, or None."""
    src = weapon_catalog.get(name)
    if src is None:
        for k, v in weapon_catalog.items():
            if k.lower() == name.lower():
                src = v
                break
    if src is None:
        return None
    w = dict(src)
    w.setdefault("two_handed", False)
    w.setdefault("is_shield", False)
    w.setdefault("ac_bonus", 0)
    return w


def map_weapon(name, weapon_catalog):
    w = _catalog_lookup(name, weapon_catalog)
    if w is not None:
        return w, True
    # Magic/enchanted weapons come through DDB as e.g. "Rapier, +1" or "Longsword +2".
    # Strip the bonus suffix, map the base weapon, and fold +N into bonus_hit/bonus_damage.
    m = re.match(r"^(.*?)[,\s]+\+(\d+)\s*$", name)
    if m:
        base, bonus = m.group(1).strip(), int(m.group(2))
        w = _catalog_lookup(base, weapon_catalog)
        if w is not None:
            w["bonus_hit"] = w.get("bonus_hit", 0) + bonus
            w["bonus_damage"] = w.get("bonus_damage", 0) + bonus
            return w, True
    return None, False


def build_weapons(data, weapon_catalog):
    melee, ranged = [], []
    for it in data.get("inventory", []):
        de = it.get("definition", {})
        if de.get("filterType") != "Weapon" or not it.get("equipped"):
            continue
        nm = de.get("name", "")
        w, ok = map_weapon(nm, weapon_catalog)
        if not ok:
            warn(f"weapon '{nm}' not in weapons.json — slot left/approximated")
            continue
        (ranged if w.get("type") == "ranged" else melee).append((nm, w))
    main = melee[0][1] if melee else "Unarmed"
    off = "Unarmed"
    for nm, w in melee[1:]:
        if w.get("light"):
            off = w
            break
    rng = ranged[0][1] if ranged else ""
    return {"main_hand": main, "off_hand": off, "ranged": rng}


def damage_adjustments(mods):
    out = {k: [] for k in ("magic_resistances", "magic_immunities", "magic_vulnerabilities",
                           "physical_resistances", "physical_immunities",
                           "physical_vulnerabilities")}
    kind = {"resistance": "resistances", "immunity": "immunities",
            "vulnerability": "vulnerabilities"}
    for m in mods:
        t = m.get("type")
        if t not in kind:
            continue
        st = (m.get("subType") or "").title()
        if st in MAGIC_DAMAGE:
            out[f"magic_{kind[t]}"].append(st)
        elif st in PHYSICAL_DAMAGE:
            out[f"physical_{kind[t]}"].append(st)
    return out


# ── main build ────────────────────────────────────────────────────────────────
def build_agent(data, catalogs, faction=0):
    weapon_catalog, armor_catalog, spell_catalog = catalogs
    mods = all_modifiers(data)
    final = final_ability_scores(data, mods)
    tlevel = total_level(data)
    prof = 2 + (tlevel - 1) // 4
    dex_m = mod(final["dex"])
    con_m = mod(final["con"])

    pc = primary_class(data)
    classes = data.get("classes", [])
    if len(classes) > 1:
        others = ", ".join(f"{c['definition']['name']} {c['level']}" for c in classes
                           if c is not pc)
        warn(f"multiclass character — using {pc['definition']['name']} {pc['level']}, "
             f"dropping: {others}")
    cls_name = pc["definition"]["name"] if pc else "None"
    char_level = pc.get("level", 1) if pc else 1
    sub_ddb = (pc.get("subclassDefinition") or {}).get("name") if pc else None

    # AC: back-solve base_ac so the engine's calculateAC (base_ac + DEX on empty armor)
    # returns the true final AC without double-counting DEX. Armor slots left empty.
    final_ac = compute_ac(data, mods, dex_m)
    base_ac = final_ac - dex_m
    has_body_armor = any(it.get("equipped") and it.get("definition", {}).get("armorTypeId")
                         in (1, 2, 3) for it in data.get("inventory", []))
    # Barbarian/Monk Unarmored Defense fires in the engine only when NO armor piece is
    # present. If this character actually wears body armor, drop a (DEX-uncapped) Leather
    # piece into the chest slot so calculateAC uses the standard path (base_ac + DEX =
    # final_ac) instead of the unarmored 10+DEX+CON formula. base_ac is unchanged.
    armor_chest = ""
    if cls_name in ("Barbarian", "Monk") and has_body_armor:
        # Barb/Monk use the better of armored AC vs Unarmored Defense; DDB's equipped
        # state already reflects that choice (here it chose armor). Our engine only runs
        # Unarmored Defense when NO armor piece is present, so insert a DEX-uncapped
        # Leather chest piece to pin it to the armored AC DDB reports (base_ac + DEX).
        armor_chest = "Leather"
        warn(f"{cls_name} uses armored AC {final_ac} (its equipped choice over Unarmored "
             f"Defense) — inserted a Leather chest piece so the engine matches")

    # spellcasting ability
    spell_ability = "cha"
    for c in classes:
        cd = c["definition"]
        if cd.get("canCastSpells") and cd.get("spellCastingAbilityId"):
            spell_ability = SPELLCAST_ABILITY.get(cd["spellCastingAbilityId"], "cha")
            if c is pc:
                break

    # num attacks
    na = 1
    if cls_name == "Fighter":
        na = 4 if char_level >= 20 else 3 if char_level >= 11 else 2 if char_level >= 5 else 1
    elif cls_name in EXTRA_ATTACK_5:
        na = 2 if char_level >= 5 else 1

    # speed
    ws = (data.get("race", {}).get("weightSpeeds") or {}).get("normal") or {}
    speed_walk = ws.get("walk", 30) or 30
    for m in mods:
        if m.get("type") == "bonus" and m.get("subType") in ("speed", "speed-walking",
                                                              "unarmored-movement"):
            speed_walk += m.get("value") or 0

    # size: from the race 'size' modifier (medium/small/large…); 1 grid cell unless Large+.
    size = 1
    for m in mods:
        if m.get("subType") in ("large",):
            size = 2
        elif m.get("subType") in ("huge",):
            size = 3

    saves = {}
    for i in range(1, 7):
        saves[f"save_prof_{ABILITY_BY_ID[i]}"] = any(
            m.get("type") == "proficiency" and m.get("subType") == f"{ABILITY_NAME[i]}-saving-throws"
            for m in mods)

    feats = []
    for f in data.get("feats", []):
        fn = _FEAT_LEVEL_PREFIX.sub("", (f.get("definition") or {}).get("name", "")).strip()
        if fn in KNOWN_FEATS:
            if fn not in feats:
                feats.append(fn)
        elif fn:
            warn(f"feat '{fn}' not engine-recognized — not added to feats vector")

    slots = compute_slots(cls_name, char_level)
    spell_indices = collect_spells(data, spell_catalog)

    stats = {
        "str": final["str"], "dex": final["dex"], "con": final["con"],
        "intel": final["intel"], "wis": final["wis"], "cha": final["cha"],
        "hp_max": compute_hp(data, mods, con_m, tlevel),
        "ac": base_ac,
        "speed_walk": int(speed_walk),
        "speed_swim": int(ws.get("swim", 0) or 0),
        "speed_fly": int(ws.get("fly", 0) or 0),
        "speed_burrow": int(ws.get("burrow", 0) or 0),
        "prof_bonus": prof,
        "num_attacks": na,
        "has_cunning_action": cls_name == "Rogue" and char_level >= 2,
        "has_offhand_attack": False,
        "spellcasting_ability": spell_ability,
        "temp_hp": int(data.get("temporaryHitPoints") or 0),
        "feats": feats,
    }
    stats["hp_cur"] = stats["hp_max"]
    stats.update(saves)
    stats.update(damage_adjustments(mods))

    agent = {
        "name": data.get("name", "Imported"),
        "sprite_path": "",
        "size": size,
        "col": 0, "row": 0,
        "faction": faction,
        "stats": stats,
        "weapons": build_weapons(data, weapon_catalog),
        "armor": {"helmet": "", "chest": armor_chest, "leggings": "",
                  "boots": "", "gloves": "", "cloak": ""},
        "spell_indices": spell_indices,
        "agent_class": cls_name,
        "agent_char_level": char_level,
    }
    for k in ("agent_barbarian_subclass", "agent_fighter_subclass", "agent_druid_circle",
              "agent_monk_subclass", "agent_paladin_oath", "agent_wizard_subclass",
              "agent_warlock_subclass", "agent_rogue_subclass", "agent_cleric_subclass",
              "agent_bard_subclass", "agent_sorcerer_subclass"):
        agent[k] = "NONE"
    if cls_name in SUBCLASS_KEY:
        agent[SUBCLASS_KEY[cls_name]] = match_subclass(cls_name, sub_ddb)
    agent["agent_eldritch_invocations"] = []
    agent["agent_fiendish_resilience_type"] = -1
    agent["druid_wild_shape_active"] = False
    agent["druid_wild_shape_form_name"] = ""
    agent["druid_starry_form_active"] = False
    agent["druid_starry_constellation"] = 0
    agent["druid_land_type"] = 0
    agent["druid_wrath_of_sea_active"] = False
    agent["spell_slots_max"] = slots
    agent["spell_slots_cur"] = list(slots)
    return agent


# ── catalogs / IO ──────────────────────────────────────────────────────────────
def load_catalogs():
    with open(os.path.join(GUI, "weapons.json")) as f:
        weapons = {w["name"]: w for w in json.load(f)}
    with open(os.path.join(GUI, "armor.json")) as f:
        armor = {a["name"]: a for a in json.load(f)}
    with open(os.path.join(GUI, "spells.json")) as f:
        sj = json.load(f)
        spells = set(sj.keys()) if isinstance(sj, dict) else {s["name"] for s in sj}
    return weapons, armor, spells


def slugify(name):
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "character"


def merge_into(path, agents, default_faction):
    with open(path) as f:
        doc = json.load(f)
    existing = doc.get("agents", [])
    by_name = {norm(a.get("name", "")): i for i, a in enumerate(existing)}
    next_col = max([a.get("col", 0) for a in existing], default=0) + 1
    for ag in agents:
        # match an existing agent on first-name token (ascii-folded), then full name.
        key_full = norm(ag["name"])
        key_first = norm(ag["name"].split()[0]) if ag["name"].split() else key_full
        idx = by_name.get(key_full)
        if idx is None:
            for nk, i in by_name.items():
                if nk and (nk.startswith(key_first) or key_first.startswith(nk)):
                    idx = i
                    break
        if idx is not None:
            old = existing[idx]
            # preserve placement / identity fields from the existing entry
            for keep in ("col", "row", "faction", "sprite_path", "size", "name"):
                if keep in old:
                    ag[keep] = old[keep]
            existing[idx] = ag
            print(f"  replaced existing agent '{old.get('name')}' (pos {ag['col']},{ag['row']})")
        else:
            ag["faction"] = default_faction
            ag["col"], ag["row"] = next_col, 0
            next_col += 1
            existing.append(ag)
            print(f"  appended new agent '{ag['name']}' (pos {ag['col']},{ag['row']})")
    doc["agents"] = existing
    doc.setdefault("map_items", [])
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"  wrote {path} ({len(existing)} agents)")


def main():
    ap = argparse.ArgumentParser(description="Import a D&D Beyond character into our agent JSON.")
    ap.add_argument("ids", nargs="+", help="DDB character URL(s) or id(s)")
    ap.add_argument("--out", help="write a standalone {'agents':[...]} file")
    ap.add_argument("--merge", help="merge into an existing agents JSON (in place)")
    ap.add_argument("--faction", type=int, default=0, help="faction for newly-appended agents")
    ap.add_argument("--sidecar-dir", default=os.path.join(HERE, "ddb_sources"),
                    help="directory for raw .ddb.json source files")
    ap.add_argument("--no-fetch", action="store_true",
                    help="treat args as local .ddb.json paths instead of ids")
    args = ap.parse_args()

    catalogs = load_catalogs()
    os.makedirs(args.sidecar_dir, exist_ok=True)
    built = []
    for arg in args.ids:
        print(f"importing {arg} …")
        global _WARN
        _WARN = []
        try:
            data = fetch_character(arg, no_fetch=args.no_fetch)
        except Exception as e:
            warn(f"fetch failed for {arg}: {e}")
            continue
        # sidecar (lossless source of truth)
        cid = re.search(r"(\d{4,})", str(arg))
        side = os.path.join(args.sidecar_dir,
                            f"{cid.group(1) if cid else slugify(data.get('name',''))}"
                            f"_{slugify(data.get('name',''))}.ddb.json")
        if not args.no_fetch:
            with open(side, "w") as f:
                json.dump({"data": data}, f, indent=2)
        agent = build_agent(data, catalogs, faction=args.faction)
        print(f"  -> {agent['name']}: {agent['agent_class']} {agent['agent_char_level']} "
              f"({agent[SUBCLASS_KEY.get(agent['agent_class'], 'name')] if agent['agent_class'] in SUBCLASS_KEY else '—'})"
              f" AC base={agent['stats']['ac']} HP={agent['stats']['hp_max']} "
              f"spells={len(agent['spell_indices'])}")
        built.append(agent)

    if args.merge:
        merge_into(args.merge, built, args.faction)
    if args.out:
        with open(args.out, "w") as f:
            json.dump({"agents": built, "map_items": []}, f, indent=2)
        print(f"wrote {args.out} ({len(built)} agents)")
    if not args.merge and not args.out:
        json.dump({"agents": built, "map_items": []}, sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
