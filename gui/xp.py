# ─────────────────────────────────────────────────────────────────────────────
#  xp.py  –  Experience-point award calculations for combat encounters
# ─────────────────────────────────────────────────────────────────────────────
#
#  XP for defeating a monster is a fixed function of its Challenge Rating (CR),
#  transcribed verbatim from the SRD 5.2 "Experience Points by Challenge Rating"
#  table (SRD_CC_v5.2.pdf, "Monsters" chapter). A party earns the summed XP value
#  of every enemy it defeats, scaled by an encounter difficulty multiplier that
#  depends on how many creatures were in the fight.

from __future__ import annotations

# CR (as it appears in DND2024_MonsterStats.json meta.cr, e.g. "1/8", "5") → XP.
# CR 0 is worth "0 or 10 XP" in the table; we use 0 (harmless critters grant none).
XP_BY_CR = {
    "0":    0,
    "1/8":  25,
    "1/4":  50,
    "1/2":  100,
    "1":    200,
    "2":    450,
    "3":    700,
    "4":    1100,
    "5":    1800,
    "6":    2300,
    "7":    2900,
    "8":    3900,
    "9":    5000,
    "10":   5900,
    "11":   7200,
    "12":   8400,
    "13":   10000,
    "14":   11500,
    "15":   13000,
    "16":   15000,
    "17":   18000,
    "18":   20000,
    "19":   22000,
    "20":   25000,
    "21":   33000,
    "22":   41000,
    "23":   50000,
    "24":   62000,
    "25":   75000,
    "26":   90000,
    "27":   105000,
    "28":   120000,
    "29":   135000,
    "30":   155000,
}

# ─────────────────────────────────────────────────────────────────────────────
#  Character Advancement — XP thresholds by level, transcribed verbatim from the
#  SRD 5.2 (2024) "Character Advancement" table (SRD_CC_v5.2.pdf, "Character
#  Creation" chapter, "Level Advancement"). "When your XP total equals or exceeds
#  a number in the Experience Points column, you reach the corresponding level."
# ─────────────────────────────────────────────────────────────────────────────
# (level, cumulative XP required, proficiency bonus).
CHARACTER_ADVANCEMENT = [
    (1,       0, 2),
    (2,     300, 2),
    (3,     900, 2),
    (4,    2700, 2),
    (5,    6500, 3),
    (6,   14000, 3),
    (7,   23000, 3),
    (8,   34000, 3),
    (9,   48000, 4),
    (10,  64000, 4),
    (11,  85000, 4),
    (12, 100000, 4),
    (13, 120000, 5),
    (14, 140000, 5),
    (15, 165000, 5),
    (16, 195000, 5),
    (17, 225000, 6),
    (18, 265000, 6),
    (19, 305000, 6),
    (20, 355000, 6),
]

# level → cumulative XP required, and level → proficiency bonus.
XP_FOR_LEVEL = {lvl: xp for lvl, xp, _pb in CHARACTER_ADVANCEMENT}
PB_FOR_LEVEL = {lvl: pb for lvl, _xp, pb in CHARACTER_ADVANCEMENT}
MAX_LEVEL = CHARACTER_ADVANCEMENT[-1][0]


def xp_for_level(level: int) -> int:
    """Cumulative XP required to reach `level` (clamped to the 1–20 table)."""
    level = max(1, min(MAX_LEVEL, int(level)))
    return XP_FOR_LEVEL[level]


def level_for_xp(xp: int) -> int:
    """Character level attained at a cumulative Experience-Point total: the
    highest level whose XP threshold `xp` equals or exceeds (SRD 5.2)."""
    lvl = 1
    for level, threshold, _pb in CHARACTER_ADVANCEMENT:
        if xp >= threshold:
            lvl = level
        else:
            break
    return lvl


def proficiency_bonus_for_level(level: int) -> int:
    """Proficiency Bonus for a character of the given level (SRD 5.2)."""
    level = max(1, min(MAX_LEVEL, int(level)))
    return PB_FOR_LEVEL[level]


# Numeric CR of each key, for tolerant lookup when a caller passes a float/int CR
# rather than the canonical string (e.g. 0.125 → "1/8", 5.0 → "5").
_CR_VALUE = {
    "0": 0.0, "1/8": 0.125, "1/4": 0.25, "1/2": 0.5,
    **{str(n): float(n) for n in range(1, 31)},
}


def _normalize_cr(cr) -> str | None:
    """Coerce a CR (string like "1/8"/"5", or a number) to the canonical XP_BY_CR
    key. Returns None if it doesn't correspond to a known CR."""
    if cr is None:
        return None
    if isinstance(cr, str):
        key = cr.strip()
        if key in XP_BY_CR:
            return key
        # Fall through to numeric parsing for oddities like "5.0" or "0.25".
        try:
            if "/" in key:
                num, den = key.split("/", 1)
                cr = float(num) / float(den)
            else:
                cr = float(key)
        except (ValueError, ZeroDivisionError):
            return None
    # Numeric CR: match the closest table value exactly.
    for k, v in _CR_VALUE.items():
        if abs(v - float(cr)) < 1e-6:
            return k
    return None


def cr_to_xp(cr) -> int:
    """XP awarded for defeating a single creature of Challenge Rating `cr`.
    Unknown / missing CRs are worth 0 XP."""
    key = _normalize_cr(cr)
    return XP_BY_CR.get(key, 0) if key is not None else 0


def encounter_multiplier(num_agents: int) -> float:
    """Difficulty multiplier applied to the summed XP of the defeated creatures,
    as a function of how many creatures were involved.

    SRD 5.2 (2024) does NOT define such a multiplier — it builds encounter
    difficulty purely from a flat XP budget — so the default is a no-op 1.0.

    The 2014 DMG *did* publish an "encounter multiplier" that scaled the summed
    XP up as the number of monsters grew (×1.5 for 2, ×2 for 3–6, etc.). It is
    left here, commented out, in case a DM wants that old feel — flip the return
    to `_MULTIPLIER_2014(num_agents)` to enable it.
    """
    return 1.0


# 2014 DMG encounter multiplier (unused; see encounter_multiplier above).
def _MULTIPLIER_2014(num_agents: int) -> float:
    if num_agents <= 1:
        return 1.0
    if num_agents == 2:
        return 1.5
    if num_agents <= 6:
        return 2.0
    if num_agents <= 10:
        return 2.5
    if num_agents <= 14:
        return 3.0
    return 4.0


def compute_encounter_xp(crs) -> dict:
    """Total XP a party earns for defeating creatures with the given CRs.

    `crs` is an iterable of Challenge Ratings (strings and/or numbers). Returns a
    dict with the raw summed XP, the applied difficulty multiplier, and the final
    (rounded) XP total.
    """
    crs = list(crs)
    base_xp = sum(cr_to_xp(cr) for cr in crs)
    mult = encounter_multiplier(len(crs))
    return {
        "count":      len(crs),
        "base_xp":    base_xp,
        "multiplier": mult,
        "total_xp":   int(round(base_xp * mult)),
    }
