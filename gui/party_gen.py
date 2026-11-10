"""Generated parties (NPC_LEARNING_PLAN.md Step 3b): PCs built from the role table.

    generate_party(seed) -> (records, meta)     a party of four, a pure function of the seed
    build_pc(subclass, role, level) -> record   one PC, the save format the importer writes

The build data is ``pc_templates.json``: a kit per class, one build per (class, role), and
the role table's 48 subclasses with their signature abilities (B9a), feature choices and
overrides. Nothing here imports the engine; the records go through the GUI's loaders like
any saved PC, which grant subclass spells and class resources from class + level.

The rules, as frozen (B1–B13):
  · level: a tier drawn uniformly (1–4, 5–10, 11–16, 17–20), then a level within it (B3);
  · composition: 50% balanced / 30% four distinct primaries / 20% skewed; a role slot draws a
    subclass 3:1 where the role is its primary vs its secondary (B4);
  · abilities 17/16/14/10/8/8 by the build's priority; ASIs at 4/8/12/16 (+ the class's extra
    ones): the build's feat takes the first, the rest raise the abilities in order to 20 (B5);
  · HP: max die, then the average, + CON per level, + Tough (B6);
  · AC through ``stats.ac`` as the importer does (B7); a shield is a real off-hand Shield;
  · magic weapons +1 / +2 / +3 from levels 5 / 11 / 17 (B8);
  · spells: signatures first, then the build's ranked lists round-robin from the highest
    castable spell level down, up to the class's prepared count (B9, B9a).

Signature spells go on the record as ``signature_spells`` (names, including ones a subclass
or a class feature grants, such as Radiance of the Dawn); the arena's automated PCs cast them
first (``arena.signature_policy``).
"""

from __future__ import annotations

import copy
import json
import os
import random

_GUI = os.path.dirname(os.path.abspath(__file__))

ROLES = ("DEF", "ST", "MT", "CC", "SUP")
ABILITIES = ("str", "dex", "con", "intel", "wis", "cha")
SCORES = (17, 16, 14, 10, 8, 8)
ASI_LEVELS = (4, 8, 12, 16)
TIERS = ((1, 4), (5, 10), (11, 16), (17, 20))
PARTY_SIZE = 4

# The plan's party templates (B4).
TEMPLATE_WEIGHTS = (("balanced", 0.5), ("distinct", 0.3), ("skewed", 0.2))
BALANCED_SLOTS = (("DEF", "ST"), ("ST", "MT"), ("MT", "CC", "SUP"), ("SUP",))
SKEWS = {
    "two_def_no_sup": (("DEF",), ("DEF",), ("ST",), ("MT", "CC")),
    "no_def":         (("ST", "MT"), ("ST", "MT"), ("CC",), ("SUP",)),
    "double_caster":  (("MT",), ("CC",), ("ST",), ("ST",)),
    "three_st":       (("ST",), ("ST",), ("ST",), ("SUP",)),
}
PRIMARY_WEIGHT, SECONDARY_WEIGHT = 3, 1     # the 75 / 25 split

SUBCLASS_FIELD = {
    "Barbarian": "agent_barbarian_subclass", "Bard": "agent_bard_subclass",
    "Cleric": "agent_cleric_subclass", "Druid": "agent_druid_circle",
    "Fighter": "agent_fighter_subclass", "Monk": "agent_monk_subclass",
    "Paladin": "agent_paladin_oath", "Ranger": "agent_ranger_subclass",
    "Rogue": "agent_rogue_subclass", "Sorcerer": "agent_sorcerer_subclass",
    "Warlock": "agent_warlock_subclass", "Wizard": "agent_wizard_subclass",
}
# Feature choices that live in the stats block rather than at the record's top level.
STATS_CHOICES = {"draconic_affinity_type", "metamagic_options"}
METAMAGIC = ["NONE", "Careful", "Distant", "Empowered", "Extended", "Heightened", "Quickened",
             "Seeking", "Subtle", "Transmuted", "Twinned"]     # rpg.MetamagicOption order
METAMAGIC_KNOWN = ((2, 2), (10, 4), (17, 6))                    # (Sorcerer level, options known)
FIGHTER_MASTERY = ((1, 3), (4, 4), (10, 5), (16, 6))


def _load(name: str):
    with open(os.path.join(_GUI, name)) as f:
        return json.load(f)


class _Data:
    def __init__(self):
        self.t = _load("pc_templates.json")
        self.weapons = {w["name"]: w for w in _load("weapons.json")}
        self.spells = {s["name"]: s for s in _load("spells.json")}
        self.features = {f["name"] for f in _load("classfeatures.json")}


_DATA: _Data | None = None


def data() -> _Data:
    global _DATA
    if _DATA is None:
        _DATA = _Data()
    return _DATA


# ── The role table ──────────────────────────────────────────────────────────

def subclasses() -> dict:
    return data().t["subclasses"]


def builds() -> list[tuple[str, str]]:
    """Every (subclass key, role) the generator can build: each subclass's primary and secondary."""
    out = []
    for key, sc in subclasses().items():
        for role in (sc["primary"], sc.get("secondary")):
            if role:
                out.append((key, role))
    return out


def resolved_build(sub_key: str, role: str) -> dict:
    """The (class, role) build with the subclass's overrides merged over it."""
    cls = sub_key.split(".")[0]
    b = copy.deepcopy(data().t["builds"][f"{cls}.{role}"])
    over = subclasses()[sub_key].get("override") or {}
    for k, v in over.items():
        b[k] = copy.deepcopy(v)
    return b


# ── One PC ──────────────────────────────────────────────────────────────────

def _mod(score: int) -> int:
    return (score - 10) // 2


def _threshold(table: dict, level: int, default: int = 0) -> int:
    """The value of the highest ``{"<level>": value}`` key at or below ``level``."""
    out = default
    for k, v in sorted(((int(k), v) for k, v in table.items())):
        if level >= k:
            out = v
    return out


def max_spell_level(caster: str | None, level: int) -> int:
    """The highest spell level the caster type can cast at this class level (2024 tables)."""
    if caster == "full":
        return min(9, (level + 1) // 2)
    if caster == "half":
        return min(5, (level - 1) // 4 + 1)
    if caster == "pact":
        return min(5, (level + 1) // 2)
    if caster == "third":
        return 0 if level < 3 else 1 if level < 7 else 2 if level < 13 else 3 if level < 19 else 4
    return 0


def _ability_scores(build: dict, cls: dict, level: int) -> tuple[dict, list]:
    scores = dict(zip(build["abilities"], SCORES))
    asis = sorted(a for a in set(ASI_LEVELS) | set(cls.get("extra_asi", [])) if a <= level)
    feats = []
    for k, _ in enumerate(asis):
        if k == 0 and build.get("feat"):
            feats.append(build["feat"])
            continue
        points = 2
        for ab in build["abilities"]:
            while points and scores[ab] < 20:
                scores[ab] += 1
                points -= 1
    return scores, feats


def _weapon(name: str | None, bonus: int, off_hand: bool = False):
    if not name:
        return ""
    cat = data().weapons
    if name not in cat:
        raise KeyError(f"weapon {name!r} not in weapons.json")
    w = None
    if bonus and not cat[name].get("is_shield"):
        w = copy.deepcopy(cat.get(f"{name} +{bonus}"))
        if w is None:
            w = copy.deepcopy(cat[name])
            w["bonus_hit"] = w.get("bonus_hit", 0) + bonus
            w["bonus_damage"] = w.get("bonus_damage", 0) + bonus
    if w is None:
        w = copy.deepcopy(cat[name])
    w.setdefault("two_handed", False)
    w.setdefault("is_shield", False)
    w.setdefault("ac_bonus", 0)
    w["proficient"] = True
    if off_hand and not w["is_shield"]:
        w["off_hand"] = True
    return w


def _base_ac(armor: str, level: int, dex_mod: int, defense: bool) -> int:
    """``stats.ac`` such that the engine's PC formula (base + DEX, nothing equipped) gives the
    armor's AC. Unarmored classes with Unarmored Defense ignore it (the engine's own formula)."""
    if armor == "heavy":
        ac = (16 if level < 9 else 18) - dex_mod
    elif armor == "medium":
        ac = (14 if level < 5 else 15) + min(dex_mod, 2) - dex_mod
    elif armor == "light":
        ac = 12
    elif armor == "mage":
        ac = 13
    else:
        ac = 10
    return ac + (1 if defense and armor in ("heavy", "medium", "light") else 0)


def _choose_spells(names: list, ranked: dict, top: int, count: int, *, cantrip: bool) -> list:
    """Signatures first, then the ranked lists round-robin from the highest spell level down."""
    cat = data().spells
    out: list[str] = []

    def ok(n):
        sp = cat.get(n)
        if sp is None or n in out:
            return False
        return (sp["level"] == 0) if cantrip else (1 <= sp["level"] <= top)
    for n in names:
        if len(out) < count and ok(n):
            out.append(n)
    if cantrip:
        lists = [ranked]
    else:
        lists = [ranked.get(str(lv), []) for lv in range(top, 0, -1)]
    depth = max((len(lst) for lst in lists), default=0)
    for i in range(depth):
        for lst in lists:
            if len(out) >= count:
                return out
            if i < len(lst) and ok(lst[i]):
                out.append(lst[i])
    return out


def build_pc(sub_key: str, role: str, level: int, *, name: str | None = None) -> dict:
    """One PC as a save-format agent record (PC side, unplaced)."""
    t = data().t
    cls_name = sub_key.split(".")[0]
    sc = subclasses()[sub_key]
    if role not in (sc["primary"], sc.get("secondary")):
        raise ValueError(f"{sub_key} has no {role} build")
    cls = t["classes"][cls_name]
    b = resolved_build(sub_key, role)
    level = max(1, min(20, int(level)))
    prof = 2 + (level - 1) // 4

    scores, asi_feats = _ability_scores(b, cls, level)
    dex_m, con_m = _mod(scores["dex"]), _mod(scores["con"])
    feats = [f for f in (b.get("origin_feat"),) if f]
    style_level = 1 if cls_name == "Fighter" else 2
    if b.get("style") and level >= style_level:
        feats.append(b["style"])
    feats += [f for f in asi_feats if f not in feats]

    hd = cls["hit_die"]
    hp = hd + con_m + (level - 1) * (hd // 2 + 1 + con_m)
    if "Tough" in feats:
        hp += 2 * level

    bonus = 3 if level >= 17 else 2 if level >= 11 else 1 if level >= 5 else 0
    wb = b.get("weapons", {})
    off = _weapon(wb.get("off_hand"), bonus, off_hand=True)
    weapons = {"main_hand": _weapon(wb.get("main_hand"), bonus) or "Unarmed",
               "off_hand": off or "Unarmed", "ranged": _weapon(wb.get("ranged"), bonus)}

    attacks = dict(cls.get("attacks", {}))
    attacks.update(sc.get("attacks", {}))
    speed = 30 + (cls.get("fast_movement", 0) if level >= 5 else 0)
    speed += _threshold(cls.get("unarmored_movement", {}), level)
    mastery = (_threshold({str(k): v for k, v in FIGHTER_MASTERY}, level) if cls_name == "Fighter"
               else cls.get("mastery", 0))

    # Spells: the class's own casting, or a third caster's (Eldritch Knight / Arcane Trickster).
    caster, kit = cls.get("caster"), cls
    if sc.get("third_caster"):
        caster, kit = "third", t["third_caster"]
    top = max_spell_level(caster, level)
    sig_spells = list((sc.get("signatures") or {}).get("spells", []))
    spell_names: list[str] = []
    if caster:
        n_cantrips = _threshold(kit.get("cantrips", {}), level)
        n_prepared = kit["prepared"][level - 1] if top else 0
        spell_names = (_choose_spells(sig_spells, b.get("cantrips", []), top, n_cantrips, cantrip=True)
                       + _choose_spells(sig_spells, b.get("spells", {}), top, n_prepared,
                                        cantrip=False))

    stats = {**scores, "hp_max": hp, "hp_cur": hp,
             "ac": _base_ac(b["armor"], level, dex_m, "Defense" in feats),
             "speed_walk": speed, "speed_swim": 0, "speed_fly": 0, "speed_burrow": 0,
             "prof_bonus": prof, "num_attacks": _threshold(attacks, level, 1),
             "weapon_mastery": mastery,
             "has_cunning_action": level >= cls.get("cunning_action", 99),
             "has_offhand_attack": isinstance(off, dict) and not off.get("is_shield"),
             "spellcasting_ability": kit.get("spell_ability", "cha"),
             "temp_hp": 0, "feats": feats,
             "luck_points": prof if "Lucky" in feats else 0,
             "luck_points_max": prof if "Lucky" in feats else 0}
    for ab in ABILITIES:
        stats[f"save_prof_{ab}"] = ab in cls["saves"]

    rec = {"name": name or f"{cls_name} ({sc['enum']}·{role}) {level}",
           "sprite_path": "", "size": 1, "col": 0, "row": 0, "faction": 2,
           "stats": stats, "weapons": weapons,
           "armor": {k: "" for k in ("helmet", "chest", "leggings", "boots", "gloves", "cloak")},
           "spell_indices": spell_names,
           "agent_class": cls_name, "agent_char_level": level}
    for c, field in SUBCLASS_FIELD.items():
        rec[field] = sc["enum"] if c == cls_name else "NONE"
    choices = dict(sc.get("choices") or {})
    choices.update((sc.get("choices_by_role") or {}).get(role, {}))
    for k, v in choices.items():
        if k == "metamagic_options":
            n = _threshold({str(a): b_ for a, b_ in METAMAGIC_KNOWN}, level)
            stats[k] = [METAMAGIC.index(m) for m in v[:n]]
        elif k in STATS_CHOICES:
            stats[k] = v
        else:
            rec[k] = v
    if cls_name == "Warlock":
        n_inv = cls["invocations"][level - 1]
        rec["agent_eldritch_invocations"] = list(b.get("invocations", []))[:n_inv]
    # Signature spells that are on the sheet, or granted by a subclass / class feature.
    granted = set(spell_names)
    rec["signature_spells"] = [n for n in sig_spells
                               if n in granted or n not in data().spells]
    rec["signature_features"] = list((sc.get("signatures") or {}).get("features", []))
    rec["pc_build"] = {"subclass": sub_key, "role": role}
    return rec


# ── A party ─────────────────────────────────────────────────────────────────

def draw_level(rng: random.Random) -> int:
    lo, hi = rng.choice(TIERS)
    return rng.randint(lo, hi)


def draw_roles(rng: random.Random) -> tuple[str, list[str]]:
    r = rng.random()
    acc = 0.0
    kind = TEMPLATE_WEIGHTS[-1][0]
    for k, w in TEMPLATE_WEIGHTS:
        acc += w
        if r < acc:
            kind = k
            break
    if kind == "balanced":
        return kind, [rng.choice(s) for s in BALANCED_SLOTS]
    if kind == "distinct":
        return kind, rng.sample(ROLES, PARTY_SIZE)
    name = rng.choice(sorted(SKEWS))
    return f"skewed:{name}", [rng.choice(s) for s in SKEWS[name]]


def pick_subclass(rng: random.Random, role: str, taken: set) -> str:
    """A subclass for ``role``: weight 3 where it is the primary, 1 where it is the secondary.
    Subclasses already in the party are avoided while any other one fits."""
    cands = []
    for key in sorted(subclasses()):
        sc = subclasses()[key]
        w = PRIMARY_WEIGHT if sc["primary"] == role else SECONDARY_WEIGHT if sc.get("secondary") == role else 0
        if w:
            cands.append((key, w))
    fresh = [c for c in cands if c[0] not in taken] or cands
    return rng.choices([k for k, _ in fresh], weights=[w for _, w in fresh])[0]


def generate_party(seed: int, *, level: int | None = None) -> tuple[list[dict], dict]:
    """Four PCs and a description of how they were drawn. Deterministic in ``seed``."""
    rng = random.Random(f"party:{seed}")
    lv = level if level is not None else draw_level(rng)
    kind, roles = draw_roles(rng)
    taken: set = set()
    party = []
    for role in roles:
        key = pick_subclass(rng, role, taken)
        taken.add(key)
        party.append(build_pc(key, role, lv))
    meta = {"generated": True, "seed": int(seed), "template": kind, "roles": roles,
            "level": lv, "builds": [p["pc_build"]["subclass"] for p in party]}
    return party, meta
