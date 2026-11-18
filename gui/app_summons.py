"""Summons: conjured creatures and companions. Scaling summon spells (form choice, placement,
the spawn itself, the automated Summon Fey cast), the summon placement rule, the Trickery
Cleric's Invoke Duplicity (invoke / move / swap), the Beast Master's Primal Companion and the
Pact of the Chain familiar (find / summon / dismiss).

Moved out of `App` in APP_REFACTOR_PLAN.md A4b, the same way as `app_spells.py` (A4):
module-level functions taking the app. The arm itself is `app.pending` (`pending.Summon`);
`combat`, `bm` and the turn state stay on `app` (D3).

`App` keeps a one-line forwarder for each function here that is reached by name from
outside `main.py` (`app_spells.py`, `actions.py`, `arena.py`, `menus/features.py`,
`app_board_render.py`, tests). Calls between those go through the forwarder
(`app._spawn_summon(...)`), so a test that wraps one on the instance still sees every call;
the rest are called directly.

The summon registry (`SUMMON_SPELL_TO_SPIRIT`, `SUMMON_SPELL_TO_MONSTER`) and the synthetic
Mage Hand / Duplicate stat blocks live here too; `app_spells.py` and `main.py` import the
registry back.
"""

import copy
import json
import math
import os

import rpg_battle_map as rpg

import pending
from agent_loader import _dict_to_weapon
from helpers import (_INT_TO_ABILITY, compute_companion_loadout, compute_summon_loadout,
                     summon_cell_placeable)
from menus import features


# ── Summoning registry ─────────────────────────────────────────────────────
# Maps a summon spell's name to a FIXED DND2024_MonsterStats.json key it conjures (non-scaling).
# The 2024 "Summon X" line now uses the scaling SUMMON_SPELL_TO_SPIRIT path instead (which takes
# precedence); this dict is for fixed-statblock summons that don't scale with the slot level.
SUMMON_SPELL_TO_MONSTER = {
    # Arcane Trickster's Mage Hand Legerdemain is modeled as a tiny, controllable summon so it has a
    # real grid position — that anchors Versatile Trickster (L13: Advantage vs creatures next to it).
    # Not in the bestiary, so it uses the synthetic MAGE_HAND_STATBLOCK below (see resolve_summon).
    "Mage Hand": "Mage Hand",
}


def _load_summon_spirits():
    """Load summons.json → {spell_name: {form_name: block}}. Each 'Summon X' / 'Conjure X'
    spell maps to its forms; the chosen form's block is scaled at cast time by
    compute_summon_loadout. README/comment records (spell starting with '_') are skipped."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "summons.json")
    try:
        with open(path) as f:
            records = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    out = {}
    for rec in records:
        spell = rec.get("spell", "")
        form  = rec.get("form", "")
        if not spell or spell.startswith("_") or not form:
            continue
        out.setdefault(spell, {})[form] = rec
    return out


# 2024 "Summon X" spells whose conjured spirit scales with the slot level used. spell → {form: block}.
# The form picker reuses the Primal-Companion context menu; the chosen block is scaled at cast time
# (compute_summon_loadout). Takes precedence over SUMMON_SPELL_TO_MONSTER when both match.
SUMMON_SPELL_TO_SPIRIT = _load_summon_spirits()


# Synthetic stat block for the Mage Hand summon (it isn't in DND2024_MonsterStats.json). Tiny, ~1 HP,
# no attacks; exists only to occupy a cell the player drags around. Shape matches the engine-ready
# bestiary record consumed by _mob_stats_to_d_d_stats (a "stats" sub-dict in dict_to_stats form).
MAGE_HAND_STATBLOCK = {
    "name": "Mage Hand",
    "size": "Tiny",
    "stats": {
        "ac": 10, "hp_cur": 1, "hp_max": 1,
        "str": 1, "dex": 10, "con": 10, "intel": 10, "wis": 10, "cha": 10,
        "prof_bonus": 2, "num_attacks": 0, "is_npc": True,
        "speed_walk": 30, "speed_fly": 30,
    },
    "weapons": [],
    "meta": {},
}

# Synthetic stat block for the Trickery Cleric's Invoke Duplicity illusion. Like Mage Hand it's a
# tiny-footprint, ~1 HP, attackless summon that exists only to hold a position the engine measures
# the "both you AND the duplicate within 5 ft of the target → Advantage" rule from. It is NOT a
# concentration effect (Channel Divinity, fixed 1-minute duration), so dropConcentration leaves it
# alone. Medium size + the cleric's own sprite (set at spawn) so it reads as a copy of the caster.
DUPLICATE_STATBLOCK = {
    "name": "Duplicate",
    "size": "Medium",
    "stats": {
        "ac": 10, "hp_cur": 1, "hp_max": 1,
        "str": 10, "dex": 10, "con": 10, "intel": 10, "wis": 10, "cha": 10,
        "prof_bonus": 2, "num_attacks": 0, "is_npc": True,
        "speed_walk": 0, "speed_fly": 0,
    },
    "weapons": [],
    "meta": {},
}



def choose_summon_form(app, spell_name: str, block: dict):
    """A scaling-summon FORM was picked from the context menu — stash the spirit `block`
    and prompt for the placement cell. The spawn happens in _resolve_summon on click; the
    block is scaled to the slot level there (compute_summon_loadout)."""
    summon = app._armed(pending.Summon)
    if summon is not None:
        summon.spirit  = block
        summon.monster = block.get("name", spell_name)
    app._combat_log_add(
        f"{spell_name} — click an empty cell within range to place the "
        f"{block.get('name', 'spirit')}.")

def resolve_summon(app, cell):
    """Place a summoned creature at `cell` (Phase 3).

    Manual-control summon: it shares the summoner's initiative count (acts immediately
    after them) and is auto-dismissed when the summoner loses concentration — that cascade
    lives in C++ (dropConcentration scans summoner_idx and tombstones via removed_from_play).
    The creature is spawned non-destructively (bm.spawn_agent) so no existing agent's runtime
    state is disturbed. The spawn itself is _spawn_summon, shared with the automated Summon
    Fey cast (features.auto_summon_fey)."""
    caster_idx = app._current_agent_idx()
    summon     = app._armed(pending.Summon)
    if caster_idx < 0 or summon is None or not summon.monster:
        return
    slot       = summon.slot
    monster    = summon.monster
    spirit     = summon.spirit
    spell_idx  = summon.idx
    slot_level = summon.slot_level
    free_summon = summon.free_cast  # Wish-duplicated summon: charge no slot
    spells = app.combat.get_agent_spells(app.bm, caster_idx)
    sp = spells[spell_idx] if 0 <= spell_idx < len(spells) else None
    if spirit is not None:
        # Scaling spirit (summons.json): no bestiary record; size comes from the block.
        size = app._size_category_to_grid_size(spirit.get("size", "Medium"))
        has_block = True
    else:
        mob_stats = (MAGE_HAND_STATBLOCK if monster == "Mage Hand"
                     else app.mob_stats_json.get(monster))
        size = app._size_category_to_grid_size(mob_stats.get("size", "Medium")) if mob_stats else 1
        has_block = bool(mob_stats)
    if sp is None or not has_block:
        app._combat_log_add(f"Summon failed: missing spell or '{monster}' stat block.")
        return

    # Validate placement: in range, line of sight, unoccupied.
    caster = app.bm.placed_agents[caster_idx]
    dist_cells = math.hypot(cell.col - caster.origin.col, cell.row - caster.origin.row)
    if dist_cells * 5.0 > sp.range + 1e-6:
        app._combat_log_add("Out of range — pick a closer cell.")
        return
    if not app.bm.has_line_of_sight(caster.origin, caster.size, cell, size):
        app._combat_log_add("No line of sight to that cell.")
        return
    if not app._can_place(cell, size):
        app._combat_log_add("That cell is blocked or occupied.")
        return

    new_idx = app._spawn_summon(caster_idx, sp, monster, spirit, slot_level, cell,
                                 no_conc=summon.no_conc)
    if new_idx < 0:
        app._combat_log_add("Summon failed: could not place the creature.")
        return

    # Spend the spell slot (PC slots only; NPC spell-group casting is out of scope here). A
    # Wish-duplicated summon is free (Wish already paid its 9th-level slot); a Fey
    # Reinforcements cast spends its use instead.
    cstats = app.combat.get_agent_stats(app.bm, caster_idx)
    if app.cast_setup.fey_reinforcements:
        app.combat.spend_resource(app.bm, caster_idx, "Fey Reinforcements", 1)
    elif not cstats.is_npc and slot_level >= 1 and not summon.free_cast:
        slots = list(cstats.spell_slots_remaining)
        if slots[slot_level - 1] > 0:
            slots[slot_level - 1] -= 1
            cstats.spell_slots_remaining = slots
            app.combat.set_agent_stats(app.bm, caster_idx, cstats)

    # Insert into initiative immediately after the summoner (shares its count).
    if app.combat_active and app.initiative_order:
        caster_pos = next((p for p, e in enumerate(app.initiative_order)
                           if e.agent_idx == caster_idx), -1)
        if caster_pos >= 0:
            base = app.initiative_order[caster_pos]
            entry = rpg.InitiativeEntry()
            entry.agent_idx = new_idx
            entry.d20       = base.d20
            entry.modifier  = base.modifier
            entry.total     = base.total
            app.initiative_order.insert(caster_pos + 1, entry)

    app._combat_log_add(f"{caster.name} summons a {monster}!")

    # Clear pending state + consume the action economy.
    fey_free = app.cast_setup.fey_reinforcements
    app._disarm(pending.Summon)
    app.cast_setup.fey_reinforcements = False
    app.summon_hover_cell         = None
    app.sprites.clear()
    app._consume_cast_slot(slot, caster_idx)
    # Wild Magic Surge: a summon spell cast with a spell slot triggers a surge (not a free
    # Wish-duplicated summon — no slot was spent).
    if slot_level >= 1 and not cstats.is_npc and not free_summon and not fey_free:
        features.maybe_wild_magic_surge(app, caster_idx)

def spawn_summon(app, caster_idx: int, sp, monster: str, spirit, slot_level: int, cell,
                  no_conc: bool = False) -> int:
    """Spawn `monster` (a summons.json spirit `block` when `spirit` is given, else a bestiary
    record) for `caster_idx`'s spell `sp` at `cell`, linked to the caster and its faction,
    and take up Concentration when the spell needs it. No placement checks, no slot, no
    initiative. `no_conc` (Fey Reinforcements) skips Concentration and gives the summon a
    1-minute timer instead (summon_rounds_left = 10). Returns the new index, or -1."""
    if spirit is not None:
        mob_stats = None
        size = app._size_category_to_grid_size(spirit.get("size", "Medium"))
    else:
        # Mage Hand isn't in the bestiary — use its synthetic block (deep-copied so dict_to_stats'
        # in-place legendary tweak in _mob_stats_to_d_d_stats can't mutate the shared constant).
        mob_stats = (copy.deepcopy(MAGE_HAND_STATBLOCK) if monster == "Mage Hand"
                     else app.mob_stats_json.get(monster))
        if not mob_stats:
            return -1
        size = app._size_category_to_grid_size(mob_stats.get("size", "Medium"))

    # Spawn WITHOUT rebuilding existing agents (preserves HP/conditions/concentration).
    cfg = rpg.AgentConfig()
    cfg.name        = monster
    cfg.sprite_path = app._get_mob_sprite_path(monster)
    cfg.size        = size
    cfg.start_col   = cell.col
    cfg.start_row   = cell.row
    new_idx = app.bm.spawn_agent(cfg)
    if new_idx < 0:
        return -1

    if spirit is not None:
        # Scaling spirit: stats + the single natural attack scale off the slot level and the
        # caster's spell-attack modifier (PB + spellcasting-ability mod) — compute_summon_loadout.
        cstats   = app.combat.get_agent_stats(app.bm, caster_idx)
        ab_name  = _INT_TO_ABILITY.get(cstats.spellcasting_ability, "cha")
        ab_score = getattr(cstats, ab_name, cstats.cha)
        spell_ability_mod = (ab_score - 10) // 2
        stats_d, weapon_d = compute_summon_loadout(
            spirit, slot_level, cstats.prof_bonus, spell_ability_mod)
        cs = rpg.Stats()
        for field, val in stats_d.items():
            setattr(cs, field, val)
        app.combat.set_agent_stats(app.bm, new_idx, cs)
        app.combat.set_agent_weapons(
            app.bm, new_idx, [_dict_to_weapon(weapon_d), rpg.Weapon(), rpg.Weapon()])
    else:
        # Stats + auto-weapons from the monster JSON (same path as bestiary placement).
        app.combat.set_agent_stats(app.bm, new_idx, app._mob_stats_to_d_d_stats(mob_stats))
        weapons = list(app.combat.get_agent_weapons(app.bm, new_idx))
        if not app._has_real_weapons(weapons):
            for i, w in enumerate(app._auto_weapons_from_mob_stats(mob_stats)[:3]):
                weapons[i] = w
            app.combat.set_agent_weapons(app.bm, new_idx, weapons)
        # Innate spells from the conjured creature's stat block (no-op for non-casters).
        app._load_npc_spells_from_record(new_idx, mob_stats)

    # Link summon → summoner + spell (drives dismiss-on-concentration-loss in C++).
    app.bm.set_agent_summoner_idx(new_idx, caster_idx)
    app.bm.set_agent_summon_spell(new_idx, sp.name)
    # Inherit the summoner's team so the conjured creature fights alongside it (and is
    # spared by the summoner's selective spells / can be healed by them).
    app.bm.set_agent_faction(new_idx, app.bm.get_agent_faction(caster_idx))

    if no_conc:
        # Fey Reinforcements: no Concentration, and the spell lasts 1 minute (10 rounds).
        app.bm.set_agent_summon_rounds_left(new_idx, 10)
        app._combat_log_add(f"{sp.name} cast without Concentration (lasts 1 minute).")
    elif sp.requires_concentration:
        # A new concentration spell replaces the caster's previous one (which dismisses
        # any creature the earlier spell had summoned).
        cond = app.combat.get_agent_conditions(app.bm, caster_idx)
        if cond.concentrating:
            app._drop_concentration_for_agent(caster_idx)
            cond = app.combat.get_agent_conditions(app.bm, caster_idx)
        cond.concentrating    = True
        cond.concentrating_on = sp.name
        app.combat.set_agent_conditions(app.bm, caster_idx, cond)
    return new_idx

def auto_summon_fey(app, idx: int) -> int:
    """The automated Fey Wanderer's Summon Fey (Ranger R3, D8). The engine's NpcDriver casts no
    summon spells, so the arena and the GUI's automated driver call this at the top of the
    Ranger's turn; when it summons, that cast is the turn (no move or Bonus Action follows).

    Casts when the Ranger (L9+, Summon Fey prepared) has no spirit of its own out and a living
    enemy is on the board. Pays with Fey Reinforcements first (L11, slotless, 3rd level), else
    its highest slot of 3rd level or above. From L11 it always skips Concentration (1 minute),
    which keeps Concentration free for Hunter's Mark; below L11 it casts only when it is not
    already concentrating. The spirit (the first mood in summons.json) lands in the free,
    visible cell within 90 ft nearest the nearest enemy, joins the Ranger's side, is automated
    like its summoner, and takes the next initiative slot. Returns the new index, or -1."""
    agents = app.bm.placed_agents
    if not (0 <= idx < len(agents)):
        return -1
    st = app.combat.get_agent_stats(app.bm, idx)
    rlvl = st.class_level(rpg.CharacterClass.Ranger)
    if st.ranger_subclass != rpg.RangerSubclass.FeyWanderer or rlvl < 9:
        return -1
    spells = app.combat.get_agent_spells(app.bm, idx)
    si = next((i for i, sp in enumerate(spells) if sp.name == "Summon Fey"), -1)
    forms = SUMMON_SPELL_TO_SPIRIT.get("Summon Fey")
    if si < 0 or not forms:
        return -1
    if any(pt.summoner_idx == idx and not pt.removed_from_play and pt.summon_spell == "Summon Fey"
           for pt in agents):
        return -1
    me = agents[idx]
    foes = [pt for i, pt in enumerate(agents)
            if i != idx and (pt.faction != me.faction or me.faction == 0)
            and not pt.removed_from_play
            and not app.bm.is_agent_on_deck(i) and not pt.conditions.dead and pt.stats.hp_cur > 0]
    if not foes:
        return -1
    no_conc = rlvl >= 11
    if not no_conc and app.combat.get_agent_conditions(app.bm, idx).concentrating:
        return -1
    fr = st.get_resource("Fey Reinforcements")
    use_fr = rlvl >= 11 and fr is not None and fr.current > 0
    slot_level = 3
    if not use_fr:
        slots = list(st.spell_slots_remaining)
        usable = [lv for lv in range(len(slots), 2, -1) if slots[lv - 1] > 0]
        if not usable:
            return -1
        slot_level = usable[0]
    block = next(iter(forms.values()))
    size = app._size_category_to_grid_size(block.get("size", "Medium"))
    sp = spells[si]
    rng = max(1, int(sp.range // 5))
    best, best_d = None, None
    for r in range(me.origin.row - rng, me.origin.row + rng + 1):
        for c in range(me.origin.col - rng, me.origin.col + rng + 1):
            if math.hypot(c - me.origin.col, r - me.origin.row) * 5.0 > sp.range + 1e-6:
                continue
            cell = rpg.Cell(c, r)
            if not app._can_place(cell, size):
                continue
            if not app.bm.has_line_of_sight(me.origin, me.size, cell, size):
                continue
            d = min(max(abs(c - f.origin.col), abs(r - f.origin.row)) for f in foes)
            if best_d is None or d < best_d:
                best, best_d = cell, d
    if best is None:
        return -1
    new_idx = app._spawn_summon(idx, sp, block.get("name", "Fey Spirit"), block, slot_level,
                                 best, no_conc=no_conc)
    if new_idx < 0:
        return -1
    app.bm.set_agent_npc_automated(new_idx, True)
    if use_fr:
        app.combat.spend_resource(app.bm, idx, "Fey Reinforcements", 1)
        how = "Fey Reinforcements, no slot"
    else:
        app.combat.spend_spell_slot(app.bm, idx, slot_level)
        how = f"level {slot_level} slot"
    if app.combat_active and app.initiative_order:
        pos = next((p for p, e in enumerate(app.initiative_order) if e.agent_idx == idx), -1)
        if pos >= 0:
            base = app.initiative_order[pos]
            entry = rpg.InitiativeEntry()
            entry.agent_idx, entry.d20 = new_idx, base.d20
            entry.modifier, entry.total = base.modifier, base.total
            app.initiative_order.insert(pos + 1, entry)
    app.sprites.clear()
    app._combat_log_add(f"{me.name} casts Summon Fey ({how}) — a {block.get('name')} appears!")
    return new_idx

def my_duplicates(app, idx: int) -> list:
    """Indices of `idx`'s live Invoke Duplicity illusions (tombstoned ones skipped)."""
    return [i for i, pt in enumerate(app.bm.placed_agents)
            if (pt.summoner_idx == idx and not pt.removed_from_play
                and pt.summon_spell == "Invoke Duplicity")]

def resolve_invoke_duplicity(app, cell):
    """Place one Invoke Duplicity illusion at `cell` (Trickery Cleric, Channel Divinity).

    The illusion is an intangible 1-HP summon (summon_spell == "Invoke Duplicity") used only as a
    position for the 'both you AND the duplicate within 5 ft of a target → Advantage' rule (the C++
    advantage hook). It is NOT a concentration effect, so dropConcentration spares it. Channel
    Divinity + the Bonus Action are spent on the FIRST placement of an activation; at L17 (Improved
    Duplicity) up to four duplicates are placed across successive clicks."""
    caster_idx = app._current_agent_idx()
    if caster_idx < 0 or not app._picking("invoke_duplicity"):
        return
    cstats = app.combat.get_agent_stats(app.bm, caster_idx)
    caster = app.bm.placed_agents[caster_idx]

    # Validate placement: within 30 ft, line of sight, unoccupied (RAW range for Invoke Duplicity).
    size = app._size_category_to_grid_size(DUPLICATE_STATBLOCK.get("size", "Medium"))
    dist_cells = math.hypot(cell.col - caster.origin.col, cell.row - caster.origin.row)
    if dist_cells * 5.0 > 30.0 + 1e-6:
        app._combat_log_add("Out of range — place the duplicate within 30 ft.")
        return
    if not app.bm.has_line_of_sight(caster.origin, caster.size, cell, size):
        app._combat_log_add("No line of sight to that cell.")
        return
    if not app._can_place(cell, size):
        app._combat_log_add("That cell is blocked or occupied.")
        return

    # First placement of this activation: spend Channel Divinity + the Bonus Action and clear any
    # already-active illusions (you may only have one set at a time). Doing this on the first
    # successful placement (not on the button click) means a cancelled placement wastes nothing.
    if app._duplicity_cd_pending:
        cd = cstats.get_resource("Channel Divinity")
        if not cd or cd.current <= 0:
            app._combat_log_add("No Channel Divinity uses remaining.")
            app._drop_pick("invoke_duplicity")
            app.pending_duplicity_remaining = 0
            return
        for di in app._my_duplicates(caster_idx):
            app.bm.set_agent_removed_from_play(di, True)
        cd.spend(1)
        cstats.resources["Channel Divinity"] = cd
        app.combat.set_agent_stats(app.bm, caster_idx, cstats)
        app.bonus_used = True
        app._duplicity_cd_pending = False

    # Spawn the illusion non-destructively, wearing the cleric's own sprite so it reads as a copy.
    cfg = rpg.AgentConfig()
    cfg.name        = f"{caster.name} (Duplicate)"
    cfg.sprite_path = caster.sprite_path
    cfg.size        = size
    cfg.start_col   = cell.col
    cfg.start_row   = cell.row
    new_idx = app.bm.spawn_agent(cfg)
    if new_idx < 0:
        app._combat_log_add("Could not place the duplicate there.")
        return
    app.combat.set_agent_stats(
        app.bm, new_idx, app._mob_stats_to_d_d_stats(copy.deepcopy(DUPLICATE_STATBLOCK)))
    app.bm.set_agent_summoner_idx(new_idx, caster_idx)
    app.bm.set_agent_summon_spell(new_idx, "Invoke Duplicity")
    app.bm.set_agent_faction(new_idx, app.bm.get_agent_faction(caster_idx))
    app._combat_log_add(f"{caster.name}: Invoke Duplicity — an illusory duplicate appears.")

    # Improved Duplicity (L17) places up to four across successive clicks; otherwise we're done.
    app.pending_duplicity_remaining -= 1
    if app.pending_duplicity_remaining > 0:
        app._combat_log_add(
            f"Improved Duplicity — click to place {app.pending_duplicity_remaining} more duplicate(s).")
    else:
        app._drop_pick("invoke_duplicity")
        if cstats.char_level >= 6:
            app._combat_log_add("Trickster's Transposition available — 'Swap w/ Duplicate' to teleport.")

def resolve_move_duplicity(app, cell):
    """Move a duplicate up to 30 ft (Bonus Action). With multiple duplicates the first click selects
    one; the lone-duplicate case pre-selects it so the click is its destination."""
    caster_idx = app._current_agent_idx()
    if caster_idx < 0 or not app._picking("move_duplicity"):
        return
    dups = app._my_duplicates(caster_idx)
    if not dups:
        app._drop_pick("move_duplicity")
        app.move_duplicity_idx = -1
        return
    if app.move_duplicity_idx < 0:
        hit = app._agent_at(cell)
        if hit in dups:
            app.move_duplicity_idx = hit
            app._combat_log_add("Duplicate selected — click its destination (within 30 ft).")
        else:
            app._combat_log_add("Click one of your duplicates first.")
        return
    if app.combat.move_duplicate(app.bm, caster_idx, app.move_duplicity_idx, cell.col, cell.row):
        app.bonus_used = True
        app._flush_combat_log()
        cstats = app.combat.get_agent_stats(app.bm, caster_idx)
        if cstats.char_level >= 6:
            app._combat_log_add("Trickster's Transposition available — 'Swap w/ Duplicate' to teleport.")
    else:
        app._flush_combat_log()
        app._combat_log_add("Cannot move the duplicate there (out of range or blocked).")
    app._drop_pick("move_duplicity")
    app.move_duplicity_idx = -1

def resolve_swap_duplicity(app, cell):
    """Multi-duplicate Trickster's Transposition: the click picks which duplicate to swap with."""
    caster_idx = app._current_agent_idx()
    if caster_idx < 0 or not app._picking("swap_duplicity"):
        return
    hit = app._agent_at(cell)
    if hit in app._my_duplicates(caster_idx):
        do_swap_duplicity(app, caster_idx, hit)
        app._drop_pick("swap_duplicity")
    else:
        app._combat_log_add("Click one of your duplicates to swap with it.")

def do_swap_duplicity(app, caster_idx, dup_idx):
    """Run the Trickster's Transposition swap (engine validates L6+ + ownership)."""
    if app.combat.swap_with_duplicate(app.bm, caster_idx, dup_idx):
        app._flush_combat_log()
        app._combat_log_add("Trickster's Transposition — swapped places with the duplicate.")
    else:
        app._flush_combat_log()
        app._combat_log_add("Cannot swap with the duplicate.")

def find_companion_idx(app, ranger_idx: int) -> int:
    """Index of the Ranger's live Primal Companion, or -1 if none is active.
    Tombstoned (dismissed/dead) companions are skipped."""
    for i, pt in enumerate(app.bm.placed_agents):
        if (pt.summoner_idx == ranger_idx and not pt.removed_from_play
                and pt.summon_spell == "Primal Companion"):
            return i
    return -1

def dismiss_companion(app, ranger_idx: int, companion_idx: int):
    """Tombstone the companion (removed_from_play) like a dismissed summon: it
    stays in placedAgents_/initiative so indices stay valid, but is skipped in
    turns and rendering."""
    name = app.bm.placed_agents[companion_idx].name
    app.bm.set_agent_removed_from_play(companion_idx, True)
    app._combat_log_add(f"{app.bm.placed_agents[ranger_idx].name} dismisses {name}.")
    app.sprites.clear()

def summon_companion(app, ranger_idx: int, form: str):
    """Conjure the Beast Master's Primal Companion (Beast of the Land/Sea/Sky).

    Scaled off the Ranger: HP = base + per-level x Ranger level, AC = 13 + PB,
    attack to-hit = Ranger's spell-attack modifier (PB + WIS mod), damage bonus = PB
    (RAW), independent of the beast's own ability mod. The companion is summon-linked
    (faction/summoner) so it shares the Ranger's initiative and tombstones on dismissal/
    death — same machinery as summon spells (memory `summoning_plan`)."""
    if not (0 <= ranger_idx < len(app.bm.placed_agents)):
        return
    if app._find_companion_idx(ranger_idx) >= 0:
        app._combat_log_add("A Primal Companion is already active — dismiss it first.")
        return
    import json
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(script_dir, "primal_companions.json")
    try:
        with open(path, 'r') as f:
            blocks = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        app._combat_log_add("Error loading primal_companions.json!")
        return
    block = next((b for b in blocks if b.get("form") == form), None)
    if block is None:
        app._combat_log_add(f"Unknown companion form '{form}'.")
        return

    rstats = app.combat.get_agent_stats(app.bm, ranger_idx)
    ranger = app.bm.placed_agents[ranger_idx]
    size = app._size_category_to_grid_size(block.get("size", "Medium"))
    cell = app._find_free_cell_near(ranger.origin.col, ranger.origin.row, size)
    if cell is None:
        app._combat_log_add("No free space next to the Ranger to summon the companion.")
        return

    pb  = rstats.prof_bonus
    lvl = rstats.char_level
    stats_d, weapon_d = compute_companion_loadout(
        block, pb, lvl, (rstats.wis - 10) // 2)

    cfg = rpg.AgentConfig()
    cfg.name        = block.get("name", "Primal Companion")
    cfg.sprite_path = app._get_mob_sprite_path(cfg.name)
    cfg.size        = size
    cfg.start_col   = cell.col
    cfg.start_row   = cell.row
    new_idx = app.bm.spawn_agent(cfg)
    if new_idx < 0:
        app._combat_log_add("Could not place the companion.")
        return

    cs = rpg.Stats()
    for field, val in stats_d.items():
        setattr(cs, field, val)
    app.combat.set_agent_stats(app.bm, new_idx, cs)
    app.combat.set_agent_weapons(
        app.bm, new_idx, [_dict_to_weapon(weapon_d), rpg.Weapon(), rpg.Weapon()])

    # Link companion -> Ranger (faction/summoner/summon name) so it fights alongside
    # the Ranger and tombstones on dismissal — same path as summon spells.
    app.bm.set_agent_summoner_idx(new_idx, ranger_idx)
    app.bm.set_agent_summon_spell(new_idx, "Primal Companion")
    app.bm.set_agent_faction(new_idx, app.bm.get_agent_faction(ranger_idx))

    # Remember the chosen form on the Ranger so it round-trips on save/load.
    rstats.primal_companion = getattr(rpg.PrimalCompanion, form)
    app.combat.set_agent_stats(app.bm, ranger_idx, rstats)

    # Share the Ranger's initiative count (acts right after them), like a summon.
    if app.combat_active and app.initiative_order:
        rpos = next((p for p, e in enumerate(app.initiative_order)
                     if e.agent_idx == ranger_idx), -1)
        if rpos >= 0:
            base = app.initiative_order[rpos]
            entry = rpg.InitiativeEntry()
            entry.agent_idx = new_idx
            entry.d20       = base.d20
            entry.modifier  = base.modifier
            entry.total     = base.total
            app.initiative_order.insert(rpos + 1, entry)

    app.sprites.clear()
    app._combat_log_add(
        f"{ranger.name} summons a {cfg.name} (HP {stats_d['hp_max']}, "
        f"AC {stats_d['base_ac']}"
        f"{', 2 attacks' if stats_d['num_attacks'] > 1 else ''}).")

def find_familiar_idx(app, warlock_idx: int) -> int:
    """Index of the Warlock's live Pact familiar, or -1 if none is active.
    Tombstoned (dismissed/dead) familiars are skipped — same convention as
    summons/companions (memory `summoning_plan`)."""
    for i, pt in enumerate(app.bm.placed_agents):
        if (pt.summoner_idx == warlock_idx and not pt.removed_from_play
                and pt.summon_spell == "Pact Familiar"):
            return i
    return -1

def dismiss_familiar(app, warlock_idx: int, familiar_idx: int):
    """Tombstone the familiar (removed_from_play) like a dismissed summon: it stays in
    placedAgents_/initiative so indices stay valid, but is skipped in turns and rendering."""
    name = app.bm.placed_agents[familiar_idx].name
    app.bm.set_agent_removed_from_play(familiar_idx, True)
    app._combat_log_add(f"{app.bm.placed_agents[warlock_idx].name} dismisses {name}.")
    app.sprites.clear()

def summon_familiar(app, warlock_idx: int, form: str):
    """Conjure the Pact of the Chain familiar (`form` = a bestiary key). The familiar is
    summon-linked (faction/summoner/summon name) so it shares the Warlock's initiative and
    tombstones on dismissal/death — same machinery as summon spells. Investment of the Chain
    Master (invocation 19, L5+) buffs it on summon (see below)."""
    if not (0 <= warlock_idx < len(app.bm.placed_agents)):
        return
    if app._find_familiar_idx(warlock_idx) >= 0:
        app._combat_log_add("A familiar is already active — dismiss it first.")
        return
    mob_stats = app.mob_stats_json.get(form)
    if not mob_stats:
        app._combat_log_add(f"Summon failed: missing '{form}' stat block.")
        return

    wstats  = app.combat.get_agent_stats(app.bm, warlock_idx)
    warlock = app.bm.placed_agents[warlock_idx]
    size = app._size_category_to_grid_size(mob_stats.get("size", "Small"))
    cell = app._find_free_cell_near(warlock.origin.col, warlock.origin.row, size)
    if cell is None:
        app._combat_log_add("No free space next to the Warlock to summon the familiar.")
        return

    cfg = rpg.AgentConfig()
    cfg.name        = form
    cfg.sprite_path = app._get_mob_sprite_path(form)
    cfg.size        = size
    cfg.start_col   = cell.col
    cfg.start_row   = cell.row
    new_idx = app.bm.spawn_agent(cfg)
    if new_idx < 0:
        app._combat_log_add("Could not place the familiar.")
        return

    # Stats + auto-weapons from the bestiary (same path as _resolve_summon).
    app.combat.set_agent_stats(app.bm, new_idx, app._mob_stats_to_d_d_stats(mob_stats))
    weapons = list(app.combat.get_agent_weapons(app.bm, new_idx))
    if not app._has_real_weapons(weapons):
        for i, w in enumerate(app._auto_weapons_from_mob_stats(mob_stats)[:3]):
            weapons[i] = w
        app.combat.set_agent_weapons(app.bm, new_idx, weapons)
    # Innate spells from the familiar's stat block (no-op for non-casters).
    app._load_npc_spells_from_record(new_idx, mob_stats)

    # Investment of the Chain Master (invocation 19, L5+): buff the familiar on summon —
    # grant a 40 ft fly speed and add the Warlock's CHA modifier to its attacks (a sim
    # simplification of RAW "+CHA to one damage roll/turn" + "its attacks count as magical").
    invested = wstats.has_invocation(19) and wstats.char_level >= 5
    if invested:
        fstats = app.combat.get_agent_stats(app.bm, new_idx)
        fstats.speed_fly = max(fstats.speed_fly, 40)
        app.combat.set_agent_stats(app.bm, new_idx, fstats)
        cha_mod = (wstats.cha - 10) // 2
        if cha_mod > 0:
            fw = list(app.combat.get_agent_weapons(app.bm, new_idx))
            for i, w in enumerate(fw):
                if w.name and w.name != "Unarmed":
                    w.bonus_damage += cha_mod
                    fw[i] = w
            app.combat.set_agent_weapons(app.bm, new_idx, fw)

    # Link familiar → Warlock (faction/summoner/summon name) so it fights alongside the
    # Warlock and tombstones on dismissal — same path as summon spells.
    app.bm.set_agent_summoner_idx(new_idx, warlock_idx)
    app.bm.set_agent_summon_spell(new_idx, "Pact Familiar")
    app.bm.set_agent_faction(new_idx, app.bm.get_agent_faction(warlock_idx))

    # Share the Warlock's initiative count (acts right after them), like a summon.
    if app.combat_active and app.initiative_order:
        wpos = next((p for p, e in enumerate(app.initiative_order)
                     if e.agent_idx == warlock_idx), -1)
        if wpos >= 0:
            base = app.initiative_order[wpos]
            entry = rpg.InitiativeEntry()
            entry.agent_idx = new_idx
            entry.d20       = base.d20
            entry.modifier  = base.modifier
            entry.total     = base.total
            app.initiative_order.insert(wpos + 1, entry)

    app.sprites.clear()
    buff = " (Chain Master: +fly, +CHA atk)" if invested else ""
    app._combat_log_add(f"{warlock.name} summons {form} as a Pact familiar{buff}.")

def summon_cell_valid(app, cell, size) -> bool:
    """Whether the pending summon may be placed at `cell` (range + LOS + unoccupied).
    Same rule (helpers.summon_cell_placeable) that _resolve_summon enforces; used to
    colour the placement preview."""
    caster_idx = app._current_agent_idx()
    summon     = app._armed(pending.Summon)
    if caster_idx < 0 or summon is None:
        return False
    spells = app.combat.get_agent_spells(app.bm, caster_idx)
    sp = spells[summon.idx] if 0 <= summon.idx < len(spells) else None
    if sp is None:
        return False
    caster = app.bm.placed_agents[caster_idx]
    return summon_cell_placeable(app.bm, caster.origin, caster.size, cell, size, sp.range)
