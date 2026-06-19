#!/usr/bin/env python3
"""Parser for gui/DND2024_MonsterStats.json.

The raw file is a flat, spreadsheet-export dict keyed by monster name, where
*every* value is a string ("" for blank), numbers included, attacks are
flattened into Atk 1..4 column groups, and a handful of "lair" stats are
duplicated under differently-named columns. This module turns one raw entry
into a structured `Monster` with typed fields and grouped sub-structures.

API:
    from tools.monster_parser import load_monsters, parse_monster, Monster

    monsters = load_monsters()          # dict[str, Monster]
    m = monsters["Aboleth"]
    m.ac                                # 17 (int)
    m.speeds                            # {"walk": 10, "swim": 40}
    m.attacks[0].damage                 # 12
    m.abilities["str"].mod              # 5
    m.raw                               # original dict, untouched

Coercion is lenient: anything that fails to parse as the expected type is kept
as None for the typed field, with the original string always available in
`m.raw`. Run this file directly to parse the whole file and report anomalies.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "gui",
    "DND2024_MonsterStats.json",
)

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
SPEED_KINDS = ("Walk", "Burrow", "Climb", "Fly", "Hover", "Swim")
SENSE_KINDS = ("Blindsight", "Darkvision", "Truesight", "Tremorsense")

# Damage-type names exactly as the engine spells them (used to split a
# monster's mixed resistance/immunity/vulnerability lists into the engine's
# separate magic vs physical buckets).
PHYSICAL_DAMAGE = ("Bludgeoning", "Piercing", "Slashing")
MAGIC_DAMAGE = ("Acid", "Cold", "Fire", "Force", "Lightning",
                "Necrotic", "Poison", "Psychic", "Radiant", "Thunder")

# Spellcasting-ability field ("Ability" column) -> engine stat key.
_SPELL_ABILITY = {
    "strength": "str", "dexterity": "dex", "constitution": "con",
    "intelligence": "intel", "wisdom": "wis", "charisma": "cha",
}


# --- coercion helpers -------------------------------------------------------

def _int(s: object) -> Optional[int]:
    """Coerce a cell to int, tolerating commas/whitespace. None if not numeric."""
    if isinstance(s, (int, float)):
        return int(s)
    if not isinstance(s, str):
        return None
    t = s.strip().replace(",", "")
    if not t:
        return None
    try:
        return int(t)
    except ValueError:
        return None


def _cr(s: str) -> Optional[Fraction]:
    """CR as a Fraction ('1/2' -> Fraction(1,2)). None for '' / 'None'."""
    t = (s or "").strip()
    if not t or t.lower() == "none":
        return None
    try:
        return Fraction(t)
    except (ValueError, ZeroDivisionError):
        return None


def _list(s: str) -> list[str]:
    """Split a comma-separated cell into a clean list ([] for blank)."""
    if not s:
        return []
    return [part.strip() for part in s.split(",") if part.strip()]


def _str(s: str) -> Optional[str]:
    """Blank-as-None for free-text cells."""
    t = (s or "").strip()
    return t or None


# --- attack -> engine weapon dict -------------------------------------------

def _avg_to_dice(avg: int) -> tuple[int, int]:
    """Pick (num_dice, die_size) whose average is `avg` (avg of dN = (N+1)/2,
    so num*die == 2*avg with no flat bonus). Falls back to d6s. Mirrors the
    GUI's prior _avg_damage_to_dice so combat math is unchanged by the refactor."""
    total = avg * 2
    for die in (6, 8, 10):
        if total % die == 0:
            return total // die, die
    return max(1, total // 6), 6


DICE = (4, 6, 8, 10, 12)

# Authoritative weapon-damage overrides for monsters whose source averages are
# wrong/ambiguous (multi-component riders, data typos, condition-only attacks).
# Loaded once; see monster_weapon_overrides.json for the schema.
_OVERRIDES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "monster_weapon_overrides.json")
_OVERRIDES = None


def _override_for(name, slot):
    global _OVERRIDES
    if _OVERRIDES is None:
        try:
            with open(_OVERRIDES_PATH) as f:
                _OVERRIDES = {k: v for k, v in json.load(f).items()
                              if not k.startswith("__")}
        except FileNotFoundError:
            _OVERRIDES = {}
    mon = _OVERRIDES.get(name)
    return mon.get(str(slot)) if mon else None


def _decompose(base):
    """Find (num_dice, die_size) whose listed (floored) average equals `base`.
    Prefers fewest dice, then larger die, then an exact mean over a floored one.
    Returns None if no standard NdX (N<=20, X in DICE) fits."""
    if base <= 0:
        return None
    cands = []
    for X in DICE:
        if (2 * base) % (X + 1) == 0:           # exact integer mean
            N = (2 * base) // (X + 1)
            if 1 <= N <= 20:
                cands.append((N, X, 0))
        for N in range(1, 21):                  # floored mean
            if (N * (X + 1)) // 2 == base and not any(c[0] == N and c[1] == X for c in cands):
                cands.append((N, X, 1))
    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], -c[1], c[2]))
    return cands[0][0], cands[0][1]


# --- structured sub-objects -------------------------------------------------

@dataclass
class Ability:
    mod: Optional[int]
    save: Optional[int]


@dataclass
class Attack:
    type: Optional[str]          # "Melee" / "Ranged"
    to_hit: Optional[int]        # attack-roll modifier
    reach: Optional[int]         # "Atk N Range" — melee reach / single range
    range_short: Optional[int]   # ranged short
    range_long: Optional[int]    # ranged long
    damage: Optional[int]        # average damage
    damage_type: Optional[str]


@dataclass
class Monster:
    name: str
    raw: dict = field(repr=False)

    # identity
    source: Optional[str] = None
    size: Optional[str] = None
    type: Optional[str] = None
    alignment: Optional[str] = None
    habitats: list[str] = field(default_factory=list)
    treasure: Optional[str] = None

    # core stats
    ac: Optional[int] = None
    hp: Optional[int] = None
    hp_text: Optional[str] = None   # kept when HP isn't a plain number
    initiative: Optional[int] = None
    cr: Optional[Fraction] = None
    xp: Optional[int] = None
    xp_in_lair: Optional[int] = None
    pb: Optional[int] = None
    pb_text: Optional[str] = None   # e.g. "Same as caster"

    speeds: dict = field(default_factory=dict)        # kind(lower) -> int
    abilities: dict = field(default_factory=dict)     # 'str'.. -> Ability
    senses: dict = field(default_factory=dict)        # kind(lower) -> int
    passive_perception: Optional[int] = None
    languages: list[str] = field(default_factory=list)

    skills_proficient: list[str] = field(default_factory=list)
    skills_expertise: list[str] = field(default_factory=list)
    vulnerabilities: list[str] = field(default_factory=list)
    resistances: list[str] = field(default_factory=list)
    immunities_damage: list[str] = field(default_factory=list)
    immunities_conditions: list[str] = field(default_factory=list)

    traits: list[str] = field(default_factory=list)
    attacks: list[Attack] = field(default_factory=list)
    weapons: Optional[dict] = None   # {main_hand, off_hand, ranged} when present

    # action economy / save-based actions (free text preserved from raw)
    save_dc: Optional[int] = None
    saving_throws: list[str] = field(default_factory=list)
    action_notes: Optional[str] = None
    bonus_action: Optional[str] = None
    reaction: Optional[str] = None
    spellcasting_ability: Optional[str] = None   # engine key: 'wis'/'cha'/...

    # legendary / lair (base vs in-lair variants resolved here)
    legendary_resistance: Optional[int] = None
    legendary_resistance_in_lair: Optional[int] = None
    legendary_actions: Optional[int] = None
    legendary_actions_in_lair: Optional[int] = None
    has_lair: bool = False
    legendary_action_names: list[str] = field(default_factory=list)  # ["Bite", "Claw", "Dash", ...]

    # --- engine conversion --------------------------------------------------
    # These emit the shapes the combat engine already loads (see
    # gui/agent_loader.dict_to_stats and gui/helpers._dict_to_weapon), so a
    # monster can be auto-populated as a first-class NPC agent.

    def to_stats_dict(self) -> dict:
        """The engine `stats` dict (keys consumed by agent_loader.dict_to_stats).

        Ability *scores* are reconstructed from the stat block's *modifiers*
        (score = mod*2 + 10). Damage resist/immune/vuln lists are split into the
        engine's separate magic vs physical buckets. NPCs are flagged is_npc."""
        def score(ab):
            mod = self.abilities.get(ab)
            return (mod.mod * 2 + 10) if mod and mod.mod is not None else 10

        def save_prof(full_name):
            return any(s.lower() == full_name for s in self.saving_throws)

        def split(names):
            mag = [n for n in names if n in MAGIC_DAMAGE]
            phys = [n for n in names if n in PHYSICAL_DAMAGE]
            return mag, phys

        res_m, res_p = split(self.resistances)
        imm_m, imm_p = split(self.immunities_damage)
        vul_m, vul_p = split(self.vulnerabilities)

        sd = {
            "str": score("str"), "dex": score("dex"), "con": score("con"),
            "intel": score("int"), "wis": score("wis"), "cha": score("cha"),
            "hp_max": self.hp if self.hp is not None else 10,
            "hp_cur": self.hp if self.hp is not None else 10,
            "ac": self.ac if self.ac is not None else 10,
            "speed_walk": self.speeds.get("walk", 30),
            "speed_fly": self.speeds.get("fly", 0),
            "speed_swim": self.speeds.get("swim", 0),
            "speed_burrow": self.speeds.get("burrow", 0),
            "prof_bonus": self.pb if self.pb is not None else 2,
            "num_attacks": _int(self.raw.get("# of Atk")) or 1,
            "save_prof_str": save_prof("strength"),
            "save_prof_dex": save_prof("dexterity"),
            "save_prof_con": save_prof("constitution"),
            "save_prof_intel": save_prof("intelligence"),
            "save_prof_wis": save_prof("wisdom"),
            "save_prof_cha": save_prof("charisma"),
            "temp_hp": 0,
            "is_npc": True,
            "magic_resistances": res_m, "physical_resistances": res_p,
            "magic_immunities": imm_m, "physical_immunities": imm_p,
            "magic_vulnerabilities": vul_m, "physical_vulnerabilities": vul_p,
        }
        if self.spellcasting_ability:
            sd["spellcasting_ability"] = self.spellcasting_ability
        return sd

    def _engine_auto_mod(self, is_ranged, finesse=False):
        """Mirror CombatEngine::damageAbilityMod: the ability mod the engine will
        auto-add to this weapon's damage (STR melee, DEX ranged, max if finesse).
        We then set bonus_damage = intended_mod - this, so the total lands on
        dice+intended_mod regardless of the source data's PB/to-hit bugs."""
        sm = self.abilities.get("str")
        dm = self.abilities.get("dex")
        sm = sm.mod if sm and sm.mod is not None else 0
        dm = dm.mod if dm and dm.mod is not None else 0
        if finesse:
            return max(sm, dm)
        return dm if is_ranged else sm

    def _reconstruct_damage(self, atk):
        """Reconstruct (damage_groups, mod) for a non-overridden attack from its
        average + M=AtkMod-PB. Falls back to M=0 (pure-elemental, no ability mod),
        then to a crude avg->dice. Single damage type only (multi-component
        attacks are handled by the overrides table)."""
        avg = atk.damage if atk.damage is not None else 6
        dtype = (atk.damage_type or "Bludgeoning").split(",")[0].strip()
        pb = self.pb if self.pb is not None else 2
        cand_mods = [atk.to_hit - pb] if atk.to_hit is not None else []
        cand_mods.append(0)
        for mod in cand_mods:
            dice = _decompose(avg - mod)
            if dice:
                return [{"type": dtype, "num_dice": dice[0], "die_size": dice[1]}], mod
        n, x = _avg_to_dice(avg)
        return [{"type": dtype, "num_dice": n, "die_size": x}], 0

    def _weapon_for_slot(self, slot, atk):
        """Build (is_ranged, weapon_dict) for one attack, or None to exclude it
        (breath/save-based or condition-only attacks aren't weapons)."""
        is_ranged = (atk.type or "").lower() == "ranged"
        ov = _override_for(self.name, slot)
        name = atk.type or "Attack"
        # On-hit riders (conditions) and weapon-mastery come only from overrides —
        # the source averages can't express secondary effects. Prone is modelled as
        # mastery "Topple"; Grappled as a "Grappled" condition (shared grapple core).
        ov_conditions = ov.get("conditions", []) if ov else []
        ov_mastery = ov.get("mastery", "None") if ov else "None"
        if ov is not None:
            if ov.get("condition_only"):
                # A pure rider attack (e.g., Roper Tentacle grapple): no damage roll,
                # but still a real weapon so its conditions land on a hit.
                groups, mod = [], 0
                name = ov.get("name", name)
            else:
                groups, mod = ov.get("damage", []), ov.get("mod", 0)
                name = ov.get("name", name)
        elif atk.to_hit is None:
            return None                       # breath weapon / save-based action
        elif atk.damage is not None and atk.damage <= 2:
            # Tiny creature: flat avg damage (encoded as N d1), no ability mod.
            dtype = (atk.damage_type or "Bludgeoning").split(",")[0].strip()
            groups = [{"type": dtype, "num_dice": max(1, atk.damage), "die_size": 1}]
            mod = 0
        else:
            groups, mod = self._reconstruct_damage(atk)

        # Without an override the source gives no attack name; label by reach +
        # damage type(s) so the GUI weapon-picker is legible ("Melee (Slashing)").
        if ov is None:
            types = "/".join(dict.fromkeys(g["type"] for g in groups))
            kind = "Ranged" if is_ranged else "Melee"
            name = f"{kind} ({types})" if types else kind

        phys = [g for g in groups if g["type"] in PHYSICAL_DAMAGE]
        mag = [g for g in groups if g["type"] in MAGIC_DAMAGE]
        if is_ranged:
            normal = atk.range_short or atk.reach or 80
            long = atk.range_long or normal * 4
            reach = 5
        else:
            reach = atk.reach or 5
            normal, long = 80, 320
        # The engine adds damageAbilityMod automatically; bonus_damage carries the
        # remainder so the total equals dice + the intended (book) modifier.
        bonus = mod - self._engine_auto_mod(is_ranged)
        return is_ranged, {
            "name": name,
            "type": "ranged" if is_ranged else "melee",
            "reach_ft": reach,
            "normal_range_ft": normal,
            "long_range_ft": long,
            "proficient": True,
            "bonus_damage": bonus,
            "physical_damage_types": phys,
            "magic_damage_types": mag,
            "conditions": ov_conditions,
            "mastery": ov_mastery,
        }

    def to_weapons(self) -> dict:
        """Return {main_hand, off_hand, ranged}. A hand-authored `weapons` dict
        (catalog-name strings) is passed through verbatim; otherwise weapon dicts
        are synthesized per attack (overrides table > tiny-flat > avg-reconstruct,
        excluding breath/condition-only). Ranged attacks fill the ranged slot;
        melee fill main_hand then off_hand. Empty slots are ""."""
        if isinstance(self.weapons, dict):
            return {slot: self.weapons.get(slot, "")
                    for slot in ("main_hand", "off_hand", "ranged")}
        slots = {"main_hand": "", "off_hand": "", "ranged": ""}
        for i, atk in enumerate(self.attacks):
            built = self._weapon_for_slot(i, atk)
            if built is None:
                continue
            is_ranged, w = built
            if is_ranged:
                if not slots["ranged"]:
                    slots["ranged"] = w
            elif not slots["main_hand"]:
                slots["main_hand"] = w
            elif not slots["off_hand"]:
                w["off_hand"] = True
                slots["off_hand"] = w
        return slots

    def to_record(self) -> dict:
        """The engine-ready bestiary record persisted to JSON: size category +
        engine stats + weapons, plus display/reference metadata under 'meta'."""
        stats = self.to_stats_dict()
        weapons = self.to_weapons()
        # The Topple mastery (our model for on-hit Prone) only fires when the
        # wielder has the Weapon Mastery feature (weapon_mastery > 0); NPCs don't
        # get it by default, so enable it when a synthesized weapon carries a mastery.
        if any(isinstance(w, dict) and w.get("mastery", "None") != "None"
               for w in weapons.values()):
            stats["weapon_mastery"] = 1
        return {
            "name": self.name,
            "size": self.size or "Medium",
            "stats": stats,
            "weapons": weapons,
            "meta": {
                "type": self.type,
                "cr": str(self.cr) if self.cr is not None else None,
                "alignment": self.alignment,
                "source": self.source,
                "traits": self.traits,
                "languages": self.languages,
                "senses": self.senses,
                "passive_perception": self.passive_perception,
                "immunities_conditions": self.immunities_conditions,
                "save_dc": self.save_dc,
                "saving_throws": self.saving_throws,
                "action_notes": self.action_notes,
                "bonus_action": self.bonus_action,
                "reaction": self.reaction,
                "legendary": {
                    "resistance": self.legendary_resistance,
                    "resistance_in_lair": self.legendary_resistance_in_lair,
                    "actions": self.legendary_actions,
                    "actions_in_lair": self.legendary_actions_in_lair,
                    "has_lair": self.has_lair,
                    "action_names": self.legendary_action_names,
                },
            },
        }


def _parse_attacks(raw: dict) -> list[Attack]:
    attacks = []
    for i in (1, 2, 3, 4):
        atype = raw.get(f"Atk {i} Type", "").strip()
        dmg = raw.get(f"Atk {i} Dam.", "").strip()
        if not atype and not dmg:
            continue
        # column casing is inconsistent across slots: "Range Short"/"Range short"
        short = raw.get(f"Atk {i} Range Short") or raw.get(f"Atk {i} Range short")
        long = raw.get(f"Atk {i} Range Long")
        attacks.append(Attack(
            type=_str(atype),
            to_hit=_int(raw.get(f"Atk {i} Mod")),
            reach=_int(raw.get(f"Atk {i} Range")),
            range_short=_int(short),
            range_long=_int(long),
            damage=_int(dmg),
            damage_type=_str(raw.get(f"Atk {i} Damage Type")),
        ))
    return attacks


def parse_monster(name: str, raw: dict) -> Monster:
    m = Monster(name=name, raw=raw)

    m.source = _str(raw.get("Source"))
    m.size = _str(raw.get("Size"))
    m.type = _str(raw.get("Type"))
    m.alignment = _str(raw.get("Alignment"))
    # "Habitat" is the combined field; Main/Other are its split halves.
    m.habitats = _list(raw.get("Habitat", ""))
    m.treasure = _str(raw.get("Treasure"))

    m.ac = _int(raw.get("AC"))
    hp = _int(raw.get("HP"))
    m.hp = hp
    if hp is None:
        m.hp_text = _str(raw.get("HP"))
    m.initiative = _int(raw.get("Initiative"))
    m.cr = _cr(raw.get("CR", ""))
    m.xp = _int(raw.get("XP."))
    m.xp_in_lair = _int(raw.get("xp"))
    pb = _int(raw.get("PB"))
    m.pb = pb
    if pb is None:
        m.pb_text = _str(raw.get("PB"))

    for kind in SPEED_KINDS:
        v = _int(raw.get(kind))
        if v is not None:
            m.speeds[kind.lower()] = v

    for ab in ABILITIES:
        m.abilities[ab] = Ability(
            mod=_int(raw.get(f"{ab.upper()} Mod")),
            save=_int(raw.get(f"{ab.upper()} Save")),
        )

    for kind in SENSE_KINDS:
        v = _int(raw.get(kind))
        if v is not None:
            m.senses[kind.lower()] = v
    m.passive_perception = _int(raw.get("Passive Perception"))
    m.languages = _list(raw.get("Languages", ""))

    m.skills_proficient = _list(raw.get("Proficient", ""))
    m.skills_expertise = _list(raw.get("Expertise", ""))
    m.vulnerabilities = _list(raw.get("Vulnerabilities", ""))
    m.resistances = _list(raw.get("Resistances", ""))
    m.immunities_damage = _list(raw.get("Immunities Damage", ""))
    m.immunities_conditions = _list(raw.get("Immunities Conditions", ""))

    m.traits = _list(raw.get("Traits", ""))
    m.attacks = _parse_attacks(raw)
    w = raw.get("weapons")
    if isinstance(w, dict):
        m.weapons = w

    m.save_dc = _int(raw.get("Save DC"))
    m.saving_throws = _list(raw.get("Saving Throw", ""))
    m.action_notes = _str(raw.get("Action Notes"))
    m.bonus_action = _str(raw.get("Bonus Action"))
    m.reaction = _str(raw.get("Reaction"))
    m.spellcasting_ability = _SPELL_ABILITY.get((raw.get("Ability") or "").strip().lower())

    # Lair creatures duplicate these: "# of Legendary Resistance"/"Amount" are
    # the base values; "Legendary Resistance"/"Legendary Actions" are the
    # (usually +1) in-lair values. Treat the former as base, the latter as lair.
    m.legendary_resistance = _int(raw.get("# of Legendary Resistance"))
    m.legendary_resistance_in_lair = _int(raw.get("Legendary Resistance"))
    m.legendary_actions = _int(raw.get("Amount"))
    m.legendary_actions_in_lair = _int(raw.get("Legendary Actions"))
    m.has_lair = (raw.get("Lair", "").strip().lower() == "yes")

    return m


def load_monsters(path: str = DEFAULT_PATH) -> dict[str, Monster]:
    with open(path) as f:
        data = json.load(f)
    return {name: parse_monster(name, raw) for name, raw in data.items()}


def _report(path: str = DEFAULT_PATH) -> None:
    """Parse everything and print a summary + anything that didn't coerce."""
    monsters = load_monsters(path)
    print(f"Parsed {len(monsters)} monsters from {path}\n")
    anomalies = []
    for name, m in monsters.items():
        if m.ac is None:
            anomalies.append((name, "AC", m.raw.get("AC")))
        if m.hp is None:
            anomalies.append((name, "HP", m.raw.get("HP")))
        if m.cr is None and m.raw.get("CR", "").strip().lower() != "none":
            anomalies.append((name, "CR", m.raw.get("CR")))
        if m.pb is None:
            anomalies.append((name, "PB", m.raw.get("PB")))
    if anomalies:
        print(f"{len(anomalies)} cells did not coerce to a number:")
        for name, fieldname, val in anomalies:
            print(f"  {name:30} {fieldname:4} = {val!r}")
    else:
        print("No coercion anomalies.")


if __name__ == "__main__":
    import sys
    _report(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)
