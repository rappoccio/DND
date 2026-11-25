"""A campaign's PCs: one sheet each, play state per run (plans/NEW_DUNGEON_PLAN.md D3).

Stdlib only, like ``run_state``: ``scene_store.CampaignStore`` calls it on every creature
read and write, and the tools use it headless.

A PC (U3: ``faction == PC_FACTION``) whose ``pcs/<slug>.json`` exists is **sheet-backed**:

  * the **sheet** is who the PC is: stats, class, spells, weapons, armor and items. It is
    shared by every dungeon of the campaign, so a level-up or an item picked up in one
    dungeon shows up in all of them.
  * the run keeps, per PC, only its **play state** (``PLAY_KEYS``, ``PLAY_STATS``): where
    it stands, HP, spell slots left, buffs, and its one-shot resources. The record is
    tagged ``"pc_sheet": <slug>`` so it reads as play state.

A run record is rebuilt as the sheet with the play state laid over it. A save goes the
other way: the play state to the run, and the rest to the sheet when it changed.

**Unsettled PCs are held whole.** Wild Shape, Aid, Haste and the like rewrite a creature's
base numbers (AC, max HP, speed) while they last, so a PC under any of them, or the target
of any active condition, is kept in the run whole, as before, tagged ``"pc_whole": true``,
and its sheet is not written. The first save after it settles splits it again.

A PC record in a run with neither tag (a run saved before this module) is play state over
its sheet too: the sheet wins (D3). A PC with no sheet is an ordinary creature.

**Party (D3).** The PCs who join a run: the run's ``"party"``, else the dungeon's, else the
campaign's, else every sheet in ``pcs/``. Names or slugs. A party PC the run has nowhere
yet arrives on the page's staging cells (``arrivals``).
"""

from __future__ import annotations

import copy
import json
import os

from atomic_io import atomic_write_json
from constants import PC_FACTION
import save_layout as sl

SHEET_TAG = "pc_sheet"
WHOLE_TAG = "pc_whole"

# Top-level record keys that are play state. ``name`` and ``faction`` are kept on the
# play record too, so anything reading a run by name still finds the PC.
PLAY_KEYS = ("col", "row", "on_deck", "land_near", "spell_slots_cur",
             "agent_rage_of_gods_used",
             "druid_wild_shape_active", "druid_wild_shape_form_name",
             "druid_starry_form_active", "druid_starry_constellation",
             "druid_wrath_of_sea_active")
ID_KEYS = ("name", "faction")
# Keys of a record that say where it was saved, never part of a sheet.
PLACEMENT_KEYS = ("encounter", "page", "z", SHEET_TAG, WHOLE_TAG)
# ``stats`` keys that are play state: HP, buffs and their bookkeeping, per-rest uses.
PLAY_STATS = (
    "hp_cur", "temp_hp", "available_hit_points",
    "blessed", "baned", "hasted", "haste_speed_bonus", "haste_action_available",
    "aid_hp_bonus", "longstrider_bonus", "expeditious_retreat", "attackers_disadvantage",
    "blade_warded", "has_foresight", "barkskin_ac_bonus", "enfeebled", "size_damage_dice",
    "mind_blank_psychic_saved", "regenerate_saved", "divine_intervention_lock",
    "stolen_spell_names", "draconic_affinity_used_this_turn",
    "draconic_affinity_resist_turns", "dragon_wings_active", "trance_of_order_turns",
    "bastion_ward", "revelation_in_flesh_turns", "revelation_prior_fly",
    "revelation_prior_swim", "revelation_prior_truesight", "luck_points",
    "boon_of_fate_used", "vampiric_bite_used", "vampiric_strengthen_bonus",
    "vampiric_strengthen_turns", "relentless_rage_dc",
    "adrenaline_rush_used", "relentless_endurance_used", "heroic_inspiration",
    "breath_weapon_used", "draconic_flight_used", "draconic_flight_rounds",
    "draconic_flight_fly_from", "giant_ancestry_used", "large_form_used",
    "large_form_rounds", "large_form_speed_added",
)
# Any of these set ⇒ the PC's base numbers are not its own right now (held whole).
UNSETTLED_STATS = ("hasted", "haste_speed_bonus", "aid_hp_bonus", "longstrider_bonus",
                   "expeditious_retreat", "barkskin_ac_bonus", "enfeebled",
                   "size_damage_dice", "dragon_wings_active", "revelation_in_flesh_turns",
                   "vampiric_strengthen_bonus", "draconic_flight_rounds", "large_form_rounds")
UNSETTLED_KEYS = ("druid_wild_shape_active",)


def is_pc(rec) -> bool:
    return isinstance(rec, dict) and rec.get("faction") == PC_FACTION and bool(rec.get("name"))


def slug_of(name) -> str | None:
    try:
        return sl.slugify(name)
    except ValueError:
        return None


def read_sheet(path: str):
    """The sheet at ``path``, or None when there is none or it can't be read."""
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and "stats" in doc else None


# ── One record ⇄ sheet + play state ──────────────────────────────────────────
def play_state(rec: dict, slug: str) -> dict:
    """The run's record for a settled sheet-backed PC: its play keys only."""
    out = {k: copy.deepcopy(rec[k]) for k in ID_KEYS + PLAY_KEYS if k in rec}
    stats = rec.get("stats") or {}
    out["stats"] = {k: copy.deepcopy(stats[k]) for k in PLAY_STATS if k in stats}
    out[SHEET_TAG] = slug
    return out


def sheet_from(rec: dict, old_sheet: dict | None) -> dict:
    """``old_sheet`` with every sheet key taken from ``rec``. The sheet's own play keys
    (where Save PC last put it, its HP then) stay as they were, so the file still loads
    whole through Load PCs."""
    out = copy.deepcopy(old_sheet) if old_sheet else {}
    for k, v in rec.items():
        if k in PLAY_KEYS or k in PLACEMENT_KEYS or k == "stats":
            continue
        out[k] = copy.deepcopy(v)
    stats = dict(out.get("stats") or {})
    for k, v in (rec.get("stats") or {}).items():
        if k not in PLAY_STATS or k not in stats:
            stats[k] = copy.deepcopy(v)
    out["stats"] = stats
    for k in PLAY_KEYS:
        if k not in out and k in rec:
            out[k] = copy.deepcopy(rec[k])
    return out


def build(sheet: dict, play: dict | None) -> dict:
    """A full record: ``sheet`` with ``play`` laid over it. HP and spell slots left are
    clamped to the sheet's maxima, which a level change may have moved."""
    rec = copy.deepcopy(sheet)
    for k in PLACEMENT_KEYS:
        rec.pop(k, None)
    play = play or {}
    for k in PLAY_KEYS:
        if k in play:
            rec[k] = copy.deepcopy(play[k])
    stats = rec.setdefault("stats", {})
    for k in PLAY_STATS:
        if k in (play.get("stats") or {}):
            stats[k] = copy.deepcopy(play["stats"][k])
    if "hp_max" in stats and "hp_cur" in stats:
        stats["hp_cur"] = min(int(stats["hp_cur"]), int(stats["hp_max"]))
    if "spell_slots_max" in rec:
        mx = [int(v) for v in rec["spell_slots_max"]]
        cur = [int(v) for v in rec.get("spell_slots_cur", mx)]
        cur += mx[len(cur):]
        rec["spell_slots_cur"] = [min(c, m) for c, m in zip(cur, mx)]
    rec["name"] = play.get("name", rec.get("name"))
    rec["faction"] = PC_FACTION
    return rec


def unsettled(rec: dict, idx: int, conditions) -> bool:
    """True when the PC at ``idx`` of its document is under an effect that rewrites its
    base numbers (see the module docstring)."""
    stats = rec.get("stats") or {}
    if any(stats.get(k) for k in UNSETTLED_STATS) or any(rec.get(k) for k in UNSETTLED_KEYS):
        return True
    return any(isinstance(c, dict) and int(c.get("agent_idx", -1)) == idx
               for c in conditions or [])


# ── A map's creatures document ───────────────────────────────────────────────
class Sheets:
    """The sheets of a campaign's ``pcs/``, read once per use and written back only when
    a save changed one."""

    def __init__(self, camp: sl.Campaign):
        self.camp = camp
        self._cache: dict[str, dict | None] = {}

    def path(self, slug: str) -> str:
        return os.path.join(self.camp.pcs_dir, slug + ".json")

    def get(self, slug: str | None):
        if not slug:
            return None
        if slug not in self._cache:
            self._cache[slug] = read_sheet(self.path(slug))
        return self._cache[slug]

    def put(self, slug: str, sheet: dict) -> bool:
        """Write ``sheet`` when it differs from the file's. True when it wrote."""
        if self.get(slug) == sheet:
            return False
        atomic_write_json(self.path(slug), sheet)
        self._cache[slug] = copy.deepcopy(sheet)
        return True

    def slugs(self) -> list[str]:
        return [os.path.splitext(os.path.basename(p))[0] for p in self.camp.list_pcs()]


def _record_slug(rec: dict) -> str | None:
    return rec.get(SHEET_TAG) or slug_of(rec.get("name"))


def expand(doc: dict, sheets: Sheets) -> dict:
    """A run section's creatures, each sheet-backed PC rebuilt from its sheet (a deep copy;
    ``doc`` is left alone). A PC held whole is returned as it was, untagged."""
    out = copy.deepcopy(doc)
    agents = out.get("agents", []) or []
    for i, rec in enumerate(agents):
        if not is_pc(rec):
            continue
        if rec.pop(WHOLE_TAG, False):
            rec.pop(SHEET_TAG, None)
            continue
        sheet = sheets.get(_record_slug(rec))
        if sheet is None:
            rec.pop(SHEET_TAG, None)
            continue
        if SHEET_TAG not in rec and unsettled(rec, i, out.get("active_conditions")):
            continue                     # an old run's PC caught mid-effect: as it was
        agents[i] = build(sheet, rec)
    return out


def collapse(doc: dict, sheets: Sheets, write: bool = True) -> tuple[dict, list[str]]:
    """The run section to store for a creatures document: settled sheet-backed PCs as play
    state, with their sheets written when changed (unless ``write`` is False: a sheet that
    wins over the document, D4); unsettled ones whole. Returns the section and the slugs
    of the sheets written."""
    out = copy.deepcopy(doc)
    agents = out.get("agents", []) or []
    wrote = []
    for i, rec in enumerate(agents):
        if not is_pc(rec):
            continue
        slug = slug_of(rec.get("name"))
        sheet = sheets.get(slug)
        if sheet is None:
            continue
        if unsettled(rec, i, out.get("active_conditions")):
            agents[i] = {**rec, SHEET_TAG: slug, WHOLE_TAG: True}
            continue
        if write and sheets.put(slug, sheet_from(rec, sheet)):
            wrote.append(slug)
        agents[i] = play_state(rec, slug)
    return out, wrote


# ── Party ────────────────────────────────────────────────────────────────────
def party_slugs(sheets: Sheets, *overrides) -> list[str]:
    """The party's sheet slugs: the first override that is a list (run, dungeon,
    campaign), names or slugs, else every sheet. Names without a sheet are dropped."""
    have = set(sheets.slugs())
    for names in overrides:
        if isinstance(names, list):
            out = []
            for n in names:
                s = slug_of(n)
                if s in have and s not in out:
                    out.append(s)
            return out
    return sorted(have)


def present_slugs(run: dict) -> set[str]:
    """Slugs of the PCs a run has on any of its maps."""
    out = set()
    for sec in (run.get("maps") or {}).values():
        for rec in sec.get("agents", []) or []:
            if is_pc(rec):
                s = _record_slug(rec)
                if s:
                    out.add(s)
    return out


def arrivals(sheets: Sheets, slugs, staging, occupied=()) -> list[dict]:
    """Records for party PCs arriving on a map: on its free staging cells in order (one
    footprint each, top-left cell), else on deck at the sheet's cell. Each is tagged
    ``land_near`` so the load moves it off a wall."""
    taken = {tuple(c) for c in occupied}
    free = [tuple(c) for c in (staging or []) if tuple(c) not in taken]
    out = []
    for s in slugs:
        sheet = sheets.get(s)
        if sheet is None:
            continue
        rec = build(sheet, None)
        if free:
            rec["col"], rec["row"] = free.pop(0)
            rec["on_deck"] = False
        else:
            rec["on_deck"] = True
        rec.setdefault("col", 0)
        rec.setdefault("row", 0)
        rec["land_near"] = True
        out.append(rec)
    return out
