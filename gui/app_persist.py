"""Save and load for the scene: the map PNG (`load_map_png`, the re-entrant rebuild of
`app.bm`), the encounter's agents (`save_agents` / `load_agents`), its terrain
(`save_terrain` / `load_terrain`, with the ladder and secret-door restores), the
mid-combat engine sidecar (`save_combat_state` / `load_combat_state`), and the file
browser callbacks and Save Encounter As that drive them.

Moved out of `App` in APP_REFACTOR_PLAN.md A7, the same way as A5 / A6: module-level
functions taking the app; all state stays on `app`. The lighting editor is not here: it
shares no helpers with load/save, so it is its own step (A7b).

`App` keeps a one-line forwarder for every function here except `normalize_ladders` and
`restore_secret_door`. They are reached by name from tests, `autosave`, `saves`,
`run_control`, `playback`, `arena`, the menus and the net layer, or bound as file-browser
callbacks; calls between the moved functions go through the forwarder so an instance
patch still sees them.
"""

import json
import os
import shutil

import pygame

import rpg_battle_map as rpg

import app_dungeon_pages
import placed_items
from agent_loader import dict_to_stats, restore_class_resources
from atomic_io import atomic_write_json
from constants import *
from helpers import (
    _INT_TO_ABILITY,
    _weapon_to_dict, _dict_to_weapon, _weapons_to_list,
    _armor_to_dict, _dict_to_armor,
    _dict_to_spell,
    _item_to_dict, _dict_to_item,
    is_item_spell, is_granted_spell_entry,
    _condition_to_dict, _dict_to_condition,
    edge_key, edge_from_key,
)
from menus import dm
from net.roster import DM_PRINCIPAL_ID
from run_state import keep_current_design
from terrain_dialogs import door_link_key
from tracker import Tracker


# ─────────────────────────────────────────────────────────────────────
#  (Re)build the active battle map from a PNG (re-entrant map loading)
def _keep_window_on_screen(win_w: int, win_h: int) -> None:
    """Re-centre the window on the desktop after a resize.

    ``set_mode`` on an existing window changes its size but not its position, and the
    container's Xvfb has no window manager to pull it back. A dungeon whose first load
    made a small window (centred for that size) then grew for a wider floor ran off the
    right of the display, clipping the panel. Skipped on the headless dummy driver: it
    has no windows to place, and taking an SDL window handle there crashes later
    ``set_mode`` calls (segfaults in the GUI suites).

    **The wrapper must outlive the window.** In pygame 2.6, ``from_display_module()``
    stores a *borrowed* pointer to the Python ``Window`` on the SDL window
    (``SDL_SetWindowData(win, "pg_window", self)``), and ``pygame.event.get()`` reads it
    back for every window event to fill ``event.window``. A wrapper dropped right away
    leaves that pointer dangling, and the next focus/enter/resize event — a click under
    X11 is enough — dereferences freed memory: the native SIGSEGV in ``event.get`` of
    plans/CRASH_HANDOFF.md. So the latest wrapper is kept in ``_DISPLAY_WINDOW``; taking a
    new one re-points the window data at it before the old one is released."""
    global _DISPLAY_WINDOW
    try:
        if pygame.display.get_driver() == "dummy":
            return
        from pygame._sdl2.video import Window
        dw, dh = pygame.display.get_desktop_sizes()[0]
        _DISPLAY_WINDOW = Window.from_display_module()
        _DISPLAY_WINDOW.position = (max(0, (dw - win_w) // 2), max(0, (dh - win_h) // 2))
    except Exception:
        pass


# The display window's `pygame._sdl2` wrapper, held for the process lifetime — see
# `_keep_window_on_screen`. Never read; existing is its whole job.
_DISPLAY_WINDOW = None


# ─────────────────────────────────────────────────────────────────────
def load_map_png(app, path):
    """Load (or swap to) the PNG at ``path`` as the active battle map.

    Rebuilds ``app.bm`` (running ``analyze_grid`` / ``detect_walls``),
    ``app.map_surf``, ``app.map_scale``, ``app.map_rect`` and
    ``app.overlay``, resizes the display window to fit, and resets the
    viewport / interaction state (pan, selection, drag). Safe to call at
    runtime to page between floors/maps (FLOORS_IMPLEMENTATION_PLAN.md).

    The sprite cache (``app.sprites``) is keyed by sprite path and is
    intentionally left untouched so it survives a swap.
    """
    # ── C++ battle map ─────────────────────────────────────────────────
    app._map_path = path       # active PNG (dungeon pages reference it by name)
    app.bm = rpg.BattleMap(path)
    try:
        app.bm.analyze_grid()
    except RuntimeError:
        # Too small/plain for auto-detection (e.g. a lone tower-top page). Start
        # from a uniform 16 px grid; the page's saved manual_grid replaces it when
        # _load_terrain runs.
        app.bm.set_uniform_grid(16, 0, 0)
    app.bm.detect_walls()

    # ── Load image to get size BEFORE creating/resizing the display ────
    # convert_alpha() requires a display surface to exist first, so we
    # load raw here, create the window, then convert/scale below.
    raw_map = pygame.image.load(path)
    mw, mh  = raw_map.get_size()

    # ── Auto-scale map to fit within a reasonable display area ────────
    # Leave room for the right-side config panel and keep some margin.
    MAX_MAP_W = 1860 - PANEL_W   # fits comfortably on a 1920-wide display
    MAX_MAP_H = 1040             # fits comfortably on a 1080-tall display
    scale = min(MAX_MAP_W / mw, MAX_MAP_H / mh, 1.0)  # never upscale
    disp_mw = int(mw * scale)
    disp_mh = int(mh * scale)
    # ``base_map_scale`` is the fit-to-window scale; ``view_zoom`` is the
    # user-controlled zoom multiplier (Ctrl+wheel / +/- keys). The effective
    # ``map_scale`` used by every coord transform is base × zoom.
    app.base_map_scale = scale
    app.view_zoom      = 1.0
    app.map_scale = scale       # used to convert C++ pixel coords → screen

    # ── Window sizing ─────────────────────────────────────────────────
    win_w = disp_mw + PANEL_W
    win_h = max(disp_mh, 600)
    app.screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)
    _keep_window_on_screen(win_w, win_h)

    # ── Now safe to convert (display surface exists) ──────────────────
    # Keep the full-resolution converted surface around so zoom can rescale
    # from native pixels each time (avoids cumulative smoothscale blur).
    converted = raw_map.convert_alpha()
    app._map_converted  = converted
    app._map_native_size = (mw, mh)
    if scale < 1.0:
        app.map_surf = pygame.transform.smoothscale(converted, (disp_mw, disp_mh))
    else:
        app.map_surf = converted
    app.map_rect = pygame.Rect(0, 0, disp_mw, disp_mh)

    # ── Overlay surface (alpha) – matches the displayed (scaled) size ──
    app.overlay = pygame.Surface((disp_mw, disp_mh), pygame.SRCALPHA)
    app._build_overlay()

    # ── Reset viewport / interaction state ─────────────────────────────
    # On first load these attributes may not exist yet (they're initialized
    # later in __init__); guard so the initial call is a harmless no-op and
    # a mid-session swap starts from a clean viewport.
    app.pan_x = 0
    app.pan_y = 0
    app.view_zoom = 1.0
    if hasattr(app, "selected_idx"):
        app.selected_idx = -1
    if hasattr(app, "drag_idx"):
        app.drag_idx    = -1
        app.drag_origin = None
        app.drag_cell   = None
        app.drag_valid  = False
    if hasattr(app, "drag_item_id"):
        app.drag_item_id     = -1
        app.drag_item        = None
        app.drag_item_origin = None
        app.drag_item_cell   = None

    # A mid-session swap to a differently sized map resizes the window, so the
    # right-side panel widgets (absolute rects) must be re-anchored. Guarded so
    # the first __init__ call — before the panel exists — is a no-op.
    if hasattr(app, "btn_agents"):
        app._reposition_panel()


def save_session(app):
    """Persist the session roster beside the encounter. Principals must survive a
    restart or every saved `controller` would load orphaned; credentials must not,
    and are never written (A3/A5)."""
    try:
        app.roster.save(app._session_path)
    except OSError as e:
        print(f"Warning: could not write {os.path.basename(app._session_path)}: {e}")


def on_save_path_chosen(app, path: str):
    if app.dungeon is not None and app.dungeon_page is not None:
        targets = [path]
    else:
        d, base = app._sidecar_base(path)
        targets = [path, os.path.join(d, base + "_terrain.json")]
    app._confirm_overwrite(targets, "Save Encounter",
                            lambda: app._save_encounter_as(path))


def save_encounter_as(app, path: str):
    # A dungeon's pages own their files; Save As there writes one multi-floor encounter
    # file instead of re-pointing the page at a new base (see _save_dungeon_encounter).
    if app.dungeon is not None and app.dungeon_page is not None:
        app_dungeon_pages.save_dungeon_encounter(app, path)
        return
    # Capture the previous sidecar locations so lighting/effects (which have no GUI
    # re-serialization path) can be carried forward to the new encounter base.
    old_lighting = app._lighting_path
    old_effects  = app._effects_path
    app._set_encounter_base(path)
    app._save_agents(path)     # also writes the combat sidecar at the new base
    app._save_terrain()        # writes app._terrain_path (now at the new base)
    # Lighting & effects travel with the encounter: copy the previous files to the
    # new base if they exist and we aren't overwriting an existing encounter's scene.
    for old, new in ((old_lighting, app._lighting_path),
                     (old_effects,  app._effects_path)):
        if old != new and os.path.exists(old) and not os.path.exists(new):
            try:
                shutil.copyfile(old, new)
            except Exception as e:
                print(f"Warning: could not carry forward {os.path.basename(old)}: {e}")


def on_load_path_chosen(app, path: str):
    # The Load browser shows every .json, so the user can pick a sidecar
    # (terrain/lighting/effects) by mistake. Those have no "agents" key — refuse
    # them rather than wiping the current scene with an empty agent list.
    try:
        with open(path) as f:
            if "agents" not in json.load(f):
                app._flash_status(f"Not an encounter file: {os.path.basename(path)}")
                return
    except Exception as e:
        app._flash_status(f"Could not read {os.path.basename(path)}: {e}")
        return
    # A dungeon page owns its scene: its terrain (grid, walls, doors), lighting and
    # sidecar file names. Loading an encounter there brings in the creatures only.
    # Re-pointing the page at the encounter's base would load that file's grid and
    # walls now, and save this page's scene under the encounter's name later.
    if app.dungeon is not None and app.dungeon_page is not None:
        app_dungeon_pages.import_encounter_onto_page(app, path)
        return
    app._set_encounter_base(path)
    app._load_agents(path)
    # Re-load the rest of the scene from the new base (terrain resets even if the
    # new encounter has none of these files, so a stale scene doesn't bleed through).
    app._load_terrain()
    app._load_lighting()
    app._load_spell_effects()
    # Last: the resume check compares against the agent list _load_agents just built.
    app._load_combat_state()


def on_save_terrain_chosen(app, path: str):
    """Export the current terrain to a chosen _terrain.json (does not change the
    active encounter base — pure export so terrain can be reused across maps)."""
    def write():
        app._save_terrain(path)
        app._flash_status(f"Terrain saved: {os.path.basename(path)}")
    app._confirm_overwrite([path], "Save Terrain", write)


def on_load_terrain_chosen(app, path: str):
    """Import terrain from a chosen _terrain.json into the current scene (it then
    saves with this encounter)."""
    # Load shows every .json, so refuse a non-terrain pick (no "regions" key)
    # rather than clearing the current terrain with an empty region list.
    try:
        with open(path) as f:
            if "regions" not in json.load(f):
                app._flash_status(f"Not a terrain file: {os.path.basename(path)}")
                return
    except Exception as e:
        app._flash_status(f"Could not read {os.path.basename(path)}: {e}")
        return
    app._load_terrain(path)
    if app.selected_idx >= 0:
        app._update_reach()
        app._update_attack_overlay()
    app._flash_status(f"Terrain loaded: {os.path.basename(path)}")


# FLAG: Move to C++
def save_agents(app, path: str | None = None, exclude_indices=None, raw: bool = False):
    path = path or app._save_path
    # exclude_indices: agent indices to omit (e.g. a party being carried to another
    # page — they are written to the destination instead of this page's file).
    exclude_indices = exclude_indices or set()
    # raw (MULTIPLAYER_PLAN.md D-M6-2): keep summons and tombstones, so the file's agent
    # list is the RAW index basis a board/engine snapshot is keyed by. Only the autosave
    # and the restore oracle ask for it; the DM's encounter file keeps its compaction.
    data = []
    for i, pt in enumerate(app.bm.placed_agents):
        # Summoned creatures are transient (concentration-tied) and have no persisted
        # summoner link, so they are never written to the save — they vanish on reload
        # rather than becoming orphaned permanent agents.
        if not raw and (pt.summoner_idx >= 0 or pt.removed_from_play):
            continue
        if i in exclude_indices:
            continue
        s = app.combat.get_agent_stats(app.bm, i)
        # Save only the filename, not the full path, for portability
        sprite_filename = os.path.basename(pt.sprite_path) if pt.sprite_path else ""
        col, row = pt.origin.col, pt.origin.row
        if pt.removed_from_play:
            # A tombstone sits off-map at (-1, -1), where _load_agents could not place
            # it. Write it at any placeable cell instead; the board snapshot's overlay
            # banishes it again and restores removed_from_play.
            col, row = app._placeable_cell(pt.size)
        data.append({
            "name":        pt.name,
            "sprite_path": sprite_filename,
            "size":        pt.size,
            "col":         col,
            "row":         row,
            "faction":     pt.faction,
            # Ownership (MULTIPLAYER_PLAN.md A1): an opaque principal id, "dm" for
            # DM-controlled. The sole persisted source of truth for who drives this
            # token — the session roster stores no seat list, because agent indices
            # are renumbered by this very loop and would not survive it.
            "controller":  pt.controller,
            "on_deck":     app.bm.is_agent_on_deck(i),
            "is_npc_automated":               app.bm.is_agent_npc_automated(i),
            "npc_automation_difficulty_level": app.bm.get_agent_npc_automation_difficulty(i),
            "npc_automation_strategy":         int(app.bm.get_agent_npc_automation_strategy(i)),
            "stats": {
                "str": s.str, "dex": s.dex, "con": s.con,
                "intel": s.intel, "wis": s.wis, "cha": s.cha,
                "hp_max": s.hp_max, "hp_cur": s.hp_cur,
                "ac": s.base_ac,
                "speed_walk": s.speed_walk, "speed_swim": s.speed_swim,
                "speed_fly":  s.speed_fly,  "speed_burrow": s.speed_burrow,
                "prof_bonus": s.prof_bonus,
                "save_prof_str":   s.save_prof_str,
                "save_prof_dex":   s.save_prof_dex,
                "save_prof_con":   s.save_prof_con,
                "save_prof_intel": s.save_prof_intel,
                "save_prof_wis":   s.save_prof_wis,
                "save_prof_cha":      s.save_prof_cha,
                "save_advantage_mask": s.save_advantage_mask,
                "blessed":            s.blessed,
                "baned":              s.baned,
                "hasted":                 s.hasted,
                "haste_speed_bonus":      s.haste_speed_bonus,
                "haste_action_available": s.haste_action_available,
                "aid_hp_bonus":           s.aid_hp_bonus,
                # Tier 1 spell buffs / debuffs (SPELL_IMPLEMENTATION_PLAN.md). Each must
                # round-trip or a saved mid-combat Longstrider/Blur/Barkskin/Foresight/
                # Enfeeblement/Enlarge-Reduce/Mind Blank/Regenerate/Expeditious Retreat is
                # silently reset on reload (dict_to_stats reads all of these back).
                "longstrider_bonus":       s.longstrider_bonus,
                "expeditious_retreat":     s.expeditious_retreat,
                "attackers_disadvantage":  s.attackers_disadvantage,
                "blade_warded":            s.blade_warded,
                "has_foresight":           s.has_foresight,
                "barkskin_ac_bonus":       s.barkskin_ac_bonus,
                "enfeebled":               s.enfeebled,
                "size_damage_dice":        s.size_damage_dice,
                "immune_charm":            s.immune_charm,
                "mind_blank_psychic_saved":s.mind_blank_psychic_saved,
                "regenerate_saved":        s.regenerate_saved,
                "divine_intervention_lock": s.divine_intervention_lock,
                "sleight_of_hand_prof":      s.sleight_of_hand_prof,
                "sleight_of_hand_expertise": s.sleight_of_hand_expertise,
                "athletics_prof":            s.athletics_prof,
                "athletics_expertise":       s.athletics_expertise,
                "initiative_bonus":          s.initiative_bonus,
                "attack_bonus":              s.attack_bonus,
                "spell_attack_bonus":        s.spell_attack_bonus,
                "spell_dc_bonus":            s.spell_dc_bonus,
                "num_attacks":        s.num_attacks,
                # NPC segmented multiattack recipe: ordered (weapon_slot, count) segments.
                # dict_to_stats reads it back; empty ⇒ legacy num_attacks behavior.
                "multiattack":        [[int(slot), int(n)] for (slot, n) in s.multiattack],
                # Weapon Mastery feature count — gates ALL weapon masteries (Cleave/Topple/Sap/...);
                # if dropped here it reloads as 0 and every mastery silently stops working
                # (agent_loader.dict_to_stats reads it back).
                "weapon_mastery":     s.weapon_mastery,
                # Creature-type flags — must round-trip or saved monsters silently lose them
                # (e.g. a reloaded Vampire stops taking Sunlight radiant damage). dict_to_stats
                # reads all of these back from this stats block.
                # is_npc MUST live here: dict_to_stats reads it from the stats sub-dict, and it
                # gates "die outright at 0 HP" (no death saves). If it's dropped, a reloaded
                # non-caster monster reverts to is_npc=False and its corpse is never cleared
                # from the map (only spellcasters get it re-set, via init_npc_spell_groups).
                "is_npc":     s.is_npc,
                "is_undead":  s.is_undead,
                "is_fiend":   s.is_fiend,
                # Remaining Magic Circle / Hallow creature types (D4 movement wards).
                "is_celestial":  getattr(s, "is_celestial", False),
                "is_elemental":  getattr(s, "is_elemental", False),
                "is_fey":        getattr(s, "is_fey", False),
                "is_aberration": getattr(s, "is_aberration", False),
                "is_vampire": s.is_vampire,
                "is_construct": s.is_construct,
                # Magic Resistance trait (Advantage on saves vs spells/magical effects). Must
                # round-trip or a reloaded Pit Fiend/Balor loses it (dict_to_stats reads it back).
                "magic_resistance": s.magic_resistance,
                # On-death AoE (Balor Death Throes): names a spell in this creature's own list.
                # Must round-trip or a reloaded exploder stops detonating. dict_to_stats reads it back.
                "death_burst_spell": s.death_burst_spell,
                # Regeneration (Troll/Vampire/…): amount + interrupting damage types must round-trip
                # or a reloaded regenerator stops healing / becomes unkillable. (regen_suppressed is
                # transient combat state and is intentionally NOT saved.)
                "regeneration_amount":          s.regeneration_amount,
                "regen_interrupt_damage_types": list(s.regen_interrupt_damage_types),
                "condition_immunities":         list(s.condition_immunities),
                "has_cunning_action": s.has_cunning_action,
                "has_offhand_attack": s.has_offhand_attack,
                "has_sentinel":             s.has_sentinel,
                "has_branches_of_the_tree": s.has_branches_of_the_tree,
                "reads_any_scroll":         s.reads_any_scroll,
                "spellcasting_ability": _INT_TO_ABILITY.get(s.spellcasting_ability, "cha"),
                "temp_hp": s.temp_hp,
                "available_hit_points": s.available_hit_points,
                "feats": list(s.feats),
                "stolen_spell_names": list(s.stolen_spell_names),
                "elemental_adept_types": list(s.elemental_adept_types),
                "irresistible_offense_ability": s.irresistible_offense_ability,
                "metamagic_options": [int(m) for m in s.metamagic_options],
                "arcane_shot_options": [int(o) for o in s.arcane_shot_options],
                "draconic_hp_applied": s.draconic_hp_applied,
                "draconic_affinity_type": s.draconic_affinity_type,
                "draconic_affinity_used_this_turn": s.draconic_affinity_used_this_turn,
                "draconic_affinity_resist_turns": s.draconic_affinity_resist_turns,
                "dragon_wings_active": s.dragon_wings_active,
                "trance_of_order_turns": s.trance_of_order_turns,
                "bastion_ward": s.bastion_ward,
                "revelation_in_flesh_turns": s.revelation_in_flesh_turns,
                "revelation_prior_fly": s.revelation_prior_fly,
                "revelation_prior_swim": s.revelation_prior_swim,
                "revelation_prior_truesight": s.revelation_prior_truesight,
                "luck_points": s.luck_points,
                "luck_points_max": s.luck_points_max,
                "boon_of_fate_used": s.boon_of_fate_used,
                "species": s.species,
                "species_option": s.species_option,
                "species_size": s.species_size,
                "species_spell_ability": s.species_spell_ability,
                "species_applied": {k: getattr(s.species_applied, k) for k in
                                    ("speed_from", "speed_to", "darkvision_from",
                                     "darkvision_to", "magic_resist_mask",
                                     "save_advantage_bits", "hp_bonus",
                                     "perception_prof")},
                "condition_save_adv": list(s.condition_save_adv),
                # Granted spells (D3): the species' entries are rebuilt on load; the list
                # carries their free casts spent and any other source's entries.
                "granted_spells": [{k: getattr(g, k) for k in
                                    ("name", "source", "unlock_level", "uses",
                                     "free_used", "ability")}
                                   for g in s.granted_spells],
                "vampiric_bite_used": s.vampiric_bite_used,
                # SP4: Skillful pick, Orc pools, Heroic Inspiration
                "species_skill": s.species_skill,
                "adrenaline_rush_used": s.adrenaline_rush_used,
                "relentless_endurance_used": s.relentless_endurance_used,
                "heroic_inspiration": s.heroic_inspiration,
                "vampiric_strengthen_bonus": s.vampiric_strengthen_bonus,
                "vampiric_strengthen_turns": s.vampiric_strengthen_turns,
                "primal_champion_applied": s.primal_champion_applied,
                "relentless_rage_dc": s.relentless_rage_dc,
                # Legendary Actions & Resistance — written in the bestiary meta.legendary shape so
                # dict_to_stats reloads it. The resolved per-round / per-day maxes are stored in
                # BOTH the base and in-lair slots so the reload is independent of the lair branch.
                "legendary": {
                    "resistance": s.legendary_resistance_max,
                    "resistance_in_lair": s.legendary_resistance_max,
                    "actions": s.legendary_actions_max,
                    "actions_in_lair": s.legendary_actions_max,
                    "has_lair": s.is_in_lair,
                    "action_names": list(s.legendary_action_names),
                    "action_costs": dict(s.legendary_action_costs),
                    "action_spells": dict(s.legendary_action_spells),
                    "lair_actions": list(s.lair_action_names),
                },
                "magic_resistances": [
                    name for idx, name in enumerate(["Acid", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Poison", "Psychic", "Radiant", "Thunder"])
                    if s.get_magic_damage_multiplier(idx) == 0.5
                ],
                "magic_immunities": [
                    name for idx, name in enumerate(["Acid", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Poison", "Psychic", "Radiant", "Thunder"])
                    if s.get_magic_damage_multiplier(idx) == 0.0
                ],
                "magic_vulnerabilities": [
                    name for idx, name in enumerate(["Acid", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Poison", "Psychic", "Radiant", "Thunder"])
                    if s.get_magic_damage_multiplier(idx) == 2.0
                ],
                "physical_resistances": [
                    name for idx, name in enumerate(["Bludgeoning", "Piercing", "Slashing"])
                    if s.get_physical_damage_multiplier(idx) == 0.5
                ],
                "physical_immunities": [
                    name for idx, name in enumerate(["Bludgeoning", "Piercing", "Slashing"])
                    if s.get_physical_damage_multiplier(idx) == 0.0
                ],
                "physical_vulnerabilities": [
                    name for idx, name in enumerate(["Bludgeoning", "Piercing", "Slashing"])
                    if s.get_physical_damage_multiplier(idx) == 2.0
                ],
            },
            # Full weapon dicts (not just names) so NPC / monster weapons and any per-weapon
            # customizations (bonus_hit, mastery, damage dice, heavy/light) survive the round-trip
            # without depending on the PC weapons.json catalog. Saved as a flat variable-length
            # "Attack N" list (index 0=main_hand, 1=off_hand, 2=ranged by convention, 3+=extra
            # attacks). Trailing empty (nameless) slots are dropped. The loader accepts BOTH this
            # list form and the legacy {main_hand,off_hand,ranged} dict for back-compat.
            "weapons": _weapons_to_list(app.combat.get_agent_weapons(app.bm, i)),
            # Slot → armor name. An enspelled piece is saved as its full dict instead, so its
            # uses, charges and `attuned` survive (ENSPELLED_ITEMS_PLAN.md D0).
            "armor": {
                slot: (_armor_to_dict(a) if not a.item_spells.empty() else (a.name or ""))
                for slot, a in zip(("helmet", "chest", "leggings", "boots", "gloves", "cloak"),
                                   app.combat.get_agent_armor(app.bm, i))
            },
            "spell_indices": [s.name
                              for s in app.combat.get_agent_spells(app.bm, i)
                              if not is_item_spell(s)            # item spells are re-derived (E3),
                              and not is_granted_spell_entry(s)],  # granted ones too (D3)
            # Carried consumables. Full dicts (not just names) so the quantity left mid-campaign
            # and any hand-tuned dice survive the round-trip without re-reading items.json.
            "items": [_item_to_dict(it)
                      for it in app.combat.get_agent_items(app.bm, i)],
            # Multiclassing (MULTICLASSING_PLAN.md Phase 1): class_levels is the
            # source of truth. agent_class/agent_char_level are kept as derived
            # mirrors (primary class / total level) for back-compat and for the
            # UI/readers that show a single "primary" class.
            "agent_class":      s.character_class.name,
            "agent_char_level": s.char_level,
            "agent_class_levels": {rpg.CharacterClass(i).name: lvl
                                   for i, lvl in enumerate(s.class_levels) if lvl > 0},
            "agent_barbarian_subclass": s.barbarian_subclass.name,
            "agent_wild_heart_power": s.wild_heart_power.name,
            "agent_rage_of_gods_used": s.rage_of_gods_used,
            "agent_fighter_subclass": s.fighter_subclass.name,
            "agent_druid_circle": s.druid_circle.name,
            "agent_monk_subclass": s.monk_subclass.name,
            "agent_paladin_oath": s.paladin_oath.name,
            "agent_wizard_subclass": s.wizard_subclass.name,
            "agent_warlock_subclass": s.warlock_subclass.name,
            "agent_rogue_subclass": s.rogue_subclass.name,
            "agent_cleric_subclass": s.cleric_subclass.name,
            "agent_blessed_strike": s.blessed_strike.name,
            "agent_bard_subclass": s.bard_subclass.name,
            "agent_sorcerer_subclass": s.sorcerer_subclass.name,
            "agent_ranger_subclass": s.ranger_subclass.name,
            "agent_hunter_prey": s.hunter_prey.name,
            "agent_defensive_tactics": s.defensive_tactics.name,
            "agent_primal_companion": s.primal_companion.name,
            "agent_eldritch_invocations": list(s.eldritch_invocations),
            "agent_fiendish_resilience_type": s.fiendish_resilience_type,
            # Druid state
            "druid_wild_shape_active": s.wild_shape_active,
            "druid_wild_shape_form_name": s.wild_shape_form_name,
            "druid_starry_form_active": s.starry_form_active,
            "druid_starry_constellation": s.starry_constellation,
            "druid_land_type": s.land_type,
            "druid_wrath_of_sea_active": s.wrath_of_sea_active,
            "spell_slots_max":  list(s.spell_slots_max),
            "spell_slots_cur":  list(s.spell_slots_remaining),
        })
        # Add NPC data if this agent is an NPC. is_npc comes from the authoritative C++ stats
        # flag (set by init_npc_spell_groups) so it can't silently flip to false on a round-trip.
        if s.is_npc or i in app._agent_meta:
            meta = app._agent_meta.get(i, {})
            data[-1]["is_npc"] = bool(s.is_npc)
            # Cosmetic boss-finale flag (dungeon generator) — round-trip so the ★ persists.
            if meta.get("is_boss"):
                data[-1]["is_boss"] = True
            # Derive ALL NPC spell metadata from the LIVE spell objects of THIS agent
            # (index i), NOT from the index-keyed _agent_meta. _agent_meta is keyed by a
            # volatile agent index that drifts whenever the agent list is reordered,
            # summoned into, or deleted from — which silently attaches one caster's
            # uses/day groups to a DIFFERENT creature on save (e.g. a Vampire
            # Infernalist's Fireball group landing on a Goblin that has no spells,
            # leaving the Infernalist with empty groups → its leveled AoE spells become
            # un-castable → PreferAOE wrongly falls back to melee). The live spells are
            # the single source of truth: init_npc_spell_groups writes uses_max/
            # recharge_min onto them by name, so grouping by uses_max round-trips exactly.
            npc_groups: dict[str, list[str]] = {}
            npc_recharge, npc_uses, npc_expended = {}, {}, {}
            spells = app.combat.get_agent_spells(app.bm, i)
            for spell in spells:
                if is_item_spell(spell) or is_granted_spell_entry(spell):
                    continue   # paid for by its item / its grant, which save their own uses
                if spell.uses_max > 0:  # N/day or recharge spell → record its group + count
                    npc_groups.setdefault(str(spell.uses_max), []).append(spell.name)
                    npc_uses[spell.name] = spell.uses_remaining
                if spell.recharge_min > 0:  # breath-weapon recharge threshold
                    npc_recharge[spell.name] = spell.recharge_min
                if spell.expended:
                    npc_expended[spell.name] = True
            data[-1]["npc_spell_groups"]   = npc_groups
            data[-1]["npc_spell_recharge"] = npc_recharge
            data[-1]["npc_spell_uses_cur"] = npc_uses
            data[-1]["npc_spell_expended"] = npc_expended
    # Serialize map items
    items_data = []
    for item in app.bm.get_all_items():
        if item.pid >= 0:
            continue            # a DM-placed design item: saved with the terrain
        if item.kind != rpg.MapItemKind.Weapon:
            # Armor taken off for a swap, and the like (plans/ITEMS_AND_CHESTS_PLAN.md).
            rec = {"col": item.cell.col, "row": item.cell.row, "label": item.label}
            if item.kind == rpg.MapItemKind.Armor:
                rec.update(kind="armor", armor=_armor_to_dict(item.armor))
            else:
                rec.update(kind="item", item=_item_to_dict(item.item))
            items_data.append(rec)
            continue
        items_data.append({
            "col":         item.cell.col,
            "row":         item.cell.row,
            "weapon_name": item.weapon.name,
            # The full weapon, not just its name: a catalog lookup by name loses per-instance
            # state — a bonded pact weapon's pact_weapon flag (a slept Warlock's dropped
            # Longsword came back swinging with STR/DEX), thrown quantity, and conjured weapons
            # (PactBlade) that aren't in weapons.json at all.
            "weapon":      _weapon_to_dict(item.weapon),
            "sprite_path": item.sprite_path,
        })
    # Serialize the live active-condition list (durations, save timers, delayed effects, and
    # Vistani-Curse kickbacks). agent_idx/caster_idx are indices into placed_agents, but the
    # saved `agents` list SKIPS summoned/removed agents — so a raw index would drift on reload.
    # Remap each saved agent to its post-reload (compacted) index; drop any condition that
    # references a skipped agent (its target/caster won't exist after reload anyway).
    old_to_new = {}
    new_idx = 0
    for old_idx, pt in enumerate(app.bm.placed_agents):
        if not raw and (pt.summoner_idx >= 0 or pt.removed_from_play):
            continue
        if old_idx in exclude_indices:
            continue
        old_to_new[old_idx] = new_idx
        new_idx += 1
    conditions_data = []
    for c in app.combat.active_agent_conditions:
        if c.agent_idx not in old_to_new:
            continue
        if c.caster_idx >= 0 and c.caster_idx not in old_to_new:
            continue
        cd = _condition_to_dict(c)
        cd["agent_idx"]  = old_to_new[c.agent_idx]
        cd["caster_idx"] = old_to_new.get(c.caster_idx, -1)
        conditions_data.append(cd)
    doc = {"agents": data, "map_items": items_data, "active_conditions": conditions_data}
    if path == app._save_path:
        app.store.write_creatures(doc)
    else:                                   # a temp carry export, or the autosave ring
        atomic_write_json(path, doc)

    # Keep the engine's resume sidecar in step with the file just written — every
    # path that persists the active encounter has to persist the matching combat
    # state, or a reload pairs fresh agent HP with a stale snapshot. Skipped for
    # the two callers that are NOT writing the active encounter: a party-carry
    # export to a temp file (_read_agent_records) and the page-switch save that
    # deliberately omits the agents being carried away.
    if path == app._save_path and not exclude_indices:
        app._save_combat_state()
        # The roster travels with the encounter: the `controller` ids just written
        # are meaningless without the principals they name (M0 / A1).
        app._save_session()


# ── Mid-combat resume (COMBAT_REFACTOR_PLAN.md R5) ────────────────────────
#  The encounter save above stores the SCENE — agents, items, and the handful of
#  conditions it can remap onto its compacted agent list. It deliberately drops
#  summons and removed agents and renumbers what is left, so it cannot carry the
#  engine's own state: pending reaction windows, in-flight casts, per-turn movement
#  budgets and the RNG stream are all keyed by RAW agent index.
#
#  These two write that state to its own sidecar instead, together with the Python
#  turn loop (initiative_order / turn_idx / round_num) that MULTIPLAYER_PLAN.md
#  calls out — without it a restored engine comes back with no turn loop at all.
#  `agent_basis` records the index basis the snapshot was taken against so a load
#  REFUSES rather than silently restoring conditions onto the wrong creatures.
def save_combat_state(app, path: str | None = None):
    """Write the engine snapshot + turn loop to ``<base>_combat.json``."""
    path = path or app._combat_path
    if not app.combat_active and not app.initiative_order:
        # Nothing to resume. Remove any stale sidecar rather than leave one behind
        # that would restore a finished fight over the next load of this encounter.
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"Warning: could not clear {os.path.basename(path)}: {e}")
        return
    doc = {
        "version":      1,
        "agent_basis":  [pt.name for pt in app.bm.placed_agents],
        "engine":       json.loads(app.combat.snapshot_json()),
        "combat_active": bool(app.combat_active),
        "combat_paused": bool(app.combat_paused),
        "reaction_timeout_s": app.reaction_timeout_s,
        "turn_idx":      int(app.turn_idx),
        "round_num":     int(app.round_num),
        # The board snapshot (M6.2): effects, per-cell terrain and light, and every
        # agent's fight state at its raw index — conditions, movement budgets (F-M6-7),
        # full stats, loadout. Keyed by the same basis as `engine`.
        "board":        json.loads(app.bm.snapshot_json()),
        "initiative_order": [
            {"agent_idx": e.agent_idx, "d20": e.d20,
             "modifier": e.modifier, "total": e.total}
            for e in app.initiative_order
        ],
        # Tracker mode (INITIATIVE_TRACKER_PLAN.md T6): the typed-in order is the turn
        # loop, so it is what a resume restores. HP rides on the board snapshot.
        "tracker_mode":  bool(app.tracker_mode),
    }
    if app.tracker_mode:
        doc["tracker"] = app.tracker.to_json()
    try:
        atomic_write_json(path, doc)
    except OSError as e:
        print(f"Warning: could not save combat state: {e}")


def load_combat_state(app, path: str | None = None, keep_design: bool = False) -> bool:
    """Restore a ``_combat.json`` sidecar. Returns True if combat was resumed.

    Call AFTER the agents are loaded — the basis check compares against the live
    placed-agent list. A missing file is the normal case (no fight was running)
    and is not an error. ``keep_design``: the board rests on the scene as loaded
    rather than on the terrain and light it was saved with (run_state.keep_current_design)."""
    path = path or app._combat_path
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        app._flash_status(f"Could not read combat state: {e}")
        return False

    current = [pt.name for pt in app.bm.placed_agents]
    if doc.get("agent_basis") != current:
        # The usual cause: the encounter save compacted indices because a summon or
        # a removed agent was on the map. Restoring anyway would apply every stored
        # index to the wrong creature, so skip the resume and keep the loaded scene.
        app._flash_status("Combat state skipped — agent list changed since save")
        return False

    # The board first (M6.2): the engine's effects refer to the board's effect ids.
    # A refused board changes nothing, so refusing the whole resume keeps the scene
    # exactly as the load built it. Absent in a sidecar written before M6.2.
    board = doc.get("board")
    if board is not None and keep_design:
        board = keep_current_design(board, json.loads(app.bm.snapshot_json()),
                                    int(rpg.TerrainType.Wall))
    if board is not None and not app.bm.restore_json(json.dumps(board)):
        app._flash_status("Combat state skipped — board snapshot unreadable")
        return False
    if not app.combat.restore_json(json.dumps(doc.get("engine", {}))):
        app._flash_status("Combat state skipped — snapshot unreadable")
        return False
    if board is not None:
        app._mark_fog_dirty()   # placements and light may have changed under the fog
    # The restore rebuilt the engine's context, and record_moves is not save state.
    app.combat.record_moves = True
    # A sidecar written between F-M6-7's fix and M6.2 carries each agent's own budget
    # as `agent_budgets` instead of a board. The getter takes exhaustion off on read,
    # so the seed adds back whatever exhaustion this load left the agent with: the
    # agent then reads exactly what it read at the save. Older sidecars have neither,
    # which leaves the budgets where `_load_agents` put them.
    budgets = doc.get("agent_budgets") if board is None else None
    if isinstance(budgets, list) and len(budgets) == len(app.bm.placed_agents):
        for i, (pt, b) in enumerate(zip(app.bm.placed_agents, budgets)):
            if isinstance(b, list) and len(b) == 4:
                exh = 5 * app.combat.get_agent_conditions(app.bm, i).exhaustion_level
                pt.init_movement(*(max(0, int(ft)) + exh for ft in b))

    order = []
    for e in doc.get("initiative_order", []):
        entry = rpg.InitiativeEntry()
        entry.agent_idx = int(e.get("agent_idx", -1))
        entry.d20       = int(e.get("d20", 0))
        entry.modifier  = int(e.get("modifier", 0))
        entry.total     = int(e.get("total", 0))
        order.append(entry)
    app.initiative_order = order
    if app._sim_trace is not None:   # the restored fight gets its own trace, opened lazily
        app._sim_trace.close({"reason": "superseded"})
        app._sim_trace = None
    app.combat_active    = bool(doc.get("combat_active", False)) and bool(order)
    app._seen_armed      = set()
    app.combat_paused    = bool(doc.get("combat_paused", False))
    # Absent in a sidecar written before D-M5-7: keep the session's value. An unknown
    # value is refused the same way, rather than trusted as a number of seconds.
    timeout = doc.get("reaction_timeout_s", app.reaction_timeout_s)
    if timeout in REACTION_TIMEOUT_CHOICES_S:
        app.reaction_timeout_s = timeout
    app.turn_idx  = min(max(0, int(doc.get("turn_idx", 0))), max(0, len(order) - 1))
    app.round_num = int(doc.get("round_num", 0))
    app._initiative_autopaged_turn = -1   # re-arm auto-paging for the resumed turn
    # Tracker mode (T6) follows the save, either way. The toggle refuses mid-fight, so
    # it runs with the fight held off; the tracker then decides whether one is on.
    live = app.combat_active
    app.combat_active = False
    dm.set_tracker_mode(app, bool(doc.get("tracker_mode", False)))
    app.combat_active = live
    if app.tracker_mode:
        app.tracker = Tracker.from_json(doc.get("tracker") or {})
        app._tracker_edit = None
        app._tracker_hp = -1
        app._mirror_tracker()
        app.combat_active = app.tracker.phase in ("collecting", "running")
        return True
    if app.combat_active:
        app.show_terrain = True           # matches how combat start leaves it
    return True


def load_agents(app, path: str | None = None):
    path = path or app._save_path
    from_store = (path == app._save_path)
    if not (app.store.has_creatures() if from_store else os.path.exists(path)):
        return
    try:
        if from_store:
            data = app.store.creatures()
        else:
            with open(path) as f:
                data = json.load(f)
    except ValueError as e:
        print(f"\n{'='*60}")
        print(f"ERROR: Agents file corrupted: {path}")
        print(f"Details: {e}")
        print(f"\nFix: Delete the corrupted file and start fresh:")
        print(f"  rm \"{path}\"")
        print(f"Then reload the map.")
        print(f"{'='*60}\n")
        return
    app.bm.clear_agents()
    app.pending_configs.clear()
    app.selected_idx = -1
    app.drag_idx     = -1
    app._spell_metadata.clear()
    # _agent_meta is index-keyed; stale entries from the previous scene would
    # otherwise bleed onto whatever agent lands at that index (e.g. a non-NPC
    # written out as an NPC on the next save). It is repopulated below per agent.
    app._agent_meta.clear()
    # Fresh scene → new agent indices; drop the awarded-corpse set so the
    # next combat's XP tally starts clean (cumulative party_xp_total persists).
    app._xp_awarded_agents.clear()
    agent_data = data.get("agents", [])
    # A record off this grid (saved under an older, larger grid — Set Grid used to
    # leave creatures behind) lands on the nearest open cell instead. The engine
    # skips a blocked placement, which would shift every later record's stats onto
    # the wrong creature, so nothing may reach apply_agent_configs off the grid.
    cols, rows = app.bm.grid_cols, app.bm.grid_rows

    def _on_grid(t):
        sz = int(t["size"])
        return 0 <= int(t["col"]) <= cols - sz and 0 <= int(t["row"]) <= rows - sz
    def _blocked(t):
        return app.bm.is_blocked(rpg.Cell(int(t["col"]), int(t["row"])), int(t["size"]))

    taken: set[tuple[int, int]] = set()
    for t in agent_data:
        if _on_grid(t) and not t.get("land_near") and not _blocked(t):
            for dc in range(int(t["size"])):
                for dr in range(int(t["size"])):
                    taken.add((int(t["col"]) + dc, int(t["row"]) + dr))
    moved = []
    kept = []      # the records the engine will place, in its order (stats follow this)
    for t in agent_data:
        cfg = rpg.AgentConfig()
        cfg.name        = t["name"]
        # Resolve sprite path relative to sprites directory
        sprite_filename = t.get("sprite_path", "")
        cfg.sprite_path = os.path.join(app.sprites_dir, sprite_filename) if sprite_filename else ""
        cfg.size        = t["size"]
        cfg.start_col   = t["col"]
        cfg.start_row   = t["row"]
        # Sent here by the DM's "Send to floor…" (_send_to_page), which can't see this
        # page's walls: land on the nearest open cell rather than be skipped as blocked.
        # A cell that is blocked now (a door closed on it, a wall drawn there since) is
        # moved the same way: the engine would skip it, and every later record's stats
        # would land on the creature before it.
        if t.get("land_near") or not _on_grid(t) or _blocked(t):
            if not _on_grid(t) or (_blocked(t) and not t.get("land_near")):
                moved.append(cfg.name)
            cfg.start_col, cfg.start_row = app._open_cell_near(
                int(t["col"]), int(t["row"]), int(t["size"]), taken)
            for dc in range(cfg.size):
                for dr in range(cfg.size):
                    taken.add((cfg.start_col + dc, cfg.start_row + dr))
        if app.bm.is_blocked(rpg.Cell(cfg.start_col, cfg.start_row), cfg.size):
            # Nowhere open on the whole map: leave it out here, and out of the stats
            # pass below, rather than shift everyone after it.
            print(f"Warning: no open cell for '{cfg.name}'; not placed.")
            continue
        app.combat.add_agent_config(app.bm, cfg)
        app.pending_configs.append(cfg)
        kept.append(t)
    app.combat.apply_agent_configs(app.bm)
    agent_data = kept
    if moved:
        app._combat_log_add(f"Off the {cols}×{rows} grid or blocked, moved onto it: "
                             f"{', '.join(moved)}.")
    app._mark_fog_dirty()   # roster (re)built — party placed, so re-run reveal
    app.sprites.clear()
    # Restore stats for each placed agent
    for i, t in enumerate(agent_data):
        if i >= len(app.bm.placed_agents):
            break
        sd = t.get("stats")
        if not sd:
            continue
        s = dict_to_stats(sd)

        # Back-compat: older GUI saves wrote is_npc only at the top level of the
        # agent dict (not inside "stats"), so dict_to_stats read it back as False and
        # the reloaded monster stopped dying outright at 0 HP (its corpse lingered on
        # the map). Honor the top-level flag as a fallback so those saves self-heal.
        # Only as a fallback: a stats flag that is present wins, because a stale top-level
        # flag is how PCs got turned into NPCs (see _remove_placed_agent).
        s.is_npc = app._saved_is_npc(t)

        # Restore character class and subclasses BEFORE committing stats to engine
        restore_class_resources(s, t)

        # Restore Druid state if present
        if t.get("druid_wild_shape_active"):
            s.wild_shape_active = t.get("druid_wild_shape_active", False)
            s.wild_shape_form_name = t.get("druid_wild_shape_form_name", "")
        if t.get("druid_starry_form_active"):
            s.starry_form_active = t.get("druid_starry_form_active", False)
            s.starry_constellation = t.get("druid_starry_constellation", 0)
        s.land_type = t.get("druid_land_type", 0)
        s.wrath_of_sea_active = t.get("druid_wrath_of_sea_active", False)

        # Load magic damage multipliers (resistances/immunities/vulnerabilities)
        magic_damage_names = ["Acid", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Poison", "Psychic", "Radiant", "Thunder"]
        for idx in range(len(magic_damage_names)):
            s.set_magic_damage_multiplier(idx, 1.0)  # default: normal damage

        for res in sd.get("magic_resistances", []):
            if res in magic_damage_names:
                idx = magic_damage_names.index(res)
                s.set_magic_damage_multiplier(idx, 0.5)
        for imm in sd.get("magic_immunities", []):
            if imm in magic_damage_names:
                idx = magic_damage_names.index(imm)
                s.set_magic_damage_multiplier(idx, 0.0)
        for vuln in sd.get("magic_vulnerabilities", []):
            if vuln in magic_damage_names:
                idx = magic_damage_names.index(vuln)
                s.set_magic_damage_multiplier(idx, 2.0)
        # Species resistances (Dhampir Trace of Undeath), even if the file only names the species.
        for idx, name in enumerate(magic_damage_names):
            if (s.species_magic_mult(getattr(rpg.MagicDamage, name)) == 0.5
                    and s.magic_damage_multipliers[idx] > 0.5):
                s.set_magic_damage_multiplier(idx, 0.5)

        # Load physical damage multipliers
        physical_damage_names = ["Bludgeoning", "Piercing", "Slashing"]
        for idx in range(len(physical_damage_names)):
            s.set_physical_damage_multiplier(idx, 1.0)  # default: normal damage

        for res in sd.get("physical_resistances", []):
            if res in physical_damage_names:
                idx = physical_damage_names.index(res)
                s.set_physical_damage_multiplier(idx, 0.5)
        for imm in sd.get("physical_immunities", []):
            if imm in physical_damage_names:
                idx = physical_damage_names.index(imm)
                s.set_physical_damage_multiplier(idx, 0.0)
        for vuln in sd.get("physical_vulnerabilities", []):
            if vuln in physical_damage_names:
                idx = physical_damage_names.index(vuln)
                s.set_physical_damage_multiplier(idx, 2.0)

        app.combat.set_agent_stats(app.bm, i, s)

        # Restore team/faction (0 = neutral for older saves that predate factions).
        app.bm.set_agent_faction(i, int(t.get("faction", 0)))

        # Restore on-deck reserve flag (older saves default to False = in the fight).
        app.bm.set_agent_on_deck(i, bool(t.get("on_deck", False)))

        # Restore the controlling principal (saves predating multiplayer default to
        # the DM). A controller naming a principal with no seat in this session's
        # roster loads as DM-controlled (A1) rather than handing a real person the
        # wrong creature — the fold happens in the roster's ownership cache, while
        # the id itself is kept so re-seating that principal restores the link.
        app.bm.set_agent_controller(i, str(t.get("controller", DM_PRINCIPAL_ID)))

        # Restore NPC automation settings (older saves default to manual control).
        app.bm.set_agent_npc_automated(i, bool(t.get("is_npc_automated", False)))
        app.bm.set_agent_npc_automation_difficulty(i, int(t.get("npc_automation_difficulty_level", 0)))
        app.bm.set_agent_npc_automation_strategy(
            i, rpg.NpcAutomationStrategy(int(t.get("npc_automation_strategy", 0))))

    # Restore weapons — load from weapons dict (slot format) or legacy formats
    for i, t in enumerate(agent_data):
        if i >= len(app.bm.placed_agents):
            break
        cpp_weapons = [rpg.Weapon(), rpg.Weapon(), rpg.Weapon()]  # >=3 slots: main, off, ranged, then extras

        # A per-slot value is either a full weapon dict (current, lossless), a bare weapon-name
        # string (older saves, resolved via the PC weapons.json catalog), or empty.
        def _resolve_slot(val):
            if isinstance(val, dict):
                return _dict_to_weapon(val)
            if val and val in app.weapon_name_to_dict:
                return _dict_to_weapon(app.weapon_name_to_dict[val])
            return rpg.Weapon()

        # Try the new flat "Attack N" list first, then the legacy {main_hand,off_hand,ranged} dict.
        weapons_dict = t.get("weapons", {})
        if isinstance(weapons_dict, list):
            cpp_weapons = [_resolve_slot(v) for v in weapons_dict]
            while len(cpp_weapons) < 3:
                cpp_weapons.append(rpg.Weapon())
        elif weapons_dict and isinstance(weapons_dict, dict):
            slot_names = ["main_hand", "off_hand", "ranged"]
            for slot_idx, slot_name in enumerate(slot_names):
                cpp_weapons[slot_idx] = _resolve_slot(weapons_dict.get(slot_name, ""))
        else:
            # Fallback to legacy weapon_indices format (list of weapon names)
            weapon_names = t.get("weapon_indices", [])
            if weapon_names:
                for slot_idx, weapon_name in enumerate(weapon_names):
                    if slot_idx >= 3:
                        break
                    if weapon_name and weapon_name in app.weapon_name_to_dict:
                        weapon_dict = app.weapon_name_to_dict[weapon_name]
                        cpp_weapons[slot_idx] = _dict_to_weapon(weapon_dict)
            else:
                # Fallback to legacy "weapons" field with full weapon dicts
                legacy_weapons = t.get("weapons_legacy", [])
                if legacy_weapons:
                    for slot_idx, w_dict in enumerate(legacy_weapons):
                        if slot_idx >= 3:
                            break
                        cpp_weapons[slot_idx] = _dict_to_weapon(w_dict)

        # For Monks, replace "Unarmed" with "MonkUnarmed" (1d8)
        stats = app.combat.get_agent_stats(app.bm, i)
        if stats.character_class == rpg.CharacterClass.Monk and cpp_weapons[0].name == "Unarmed":
            cpp_weapons[0] = app._create_monk_unarmed_weapon()

        # Master of Myriad Forms (invocation 12): Alter Self claws (1d6) for Warlocks
        if (stats.character_class == rpg.CharacterClass.Warlock and
                stats.has_invocation(12) and cpp_weapons[0].name == "Unarmed"):
            cpp_weapons[0] = app._create_alter_self_claws_weapon()

        # Pact of the Blade (invocation 13): the main-hand weapon becomes the pact weapon again
        # (pact_weapon is re-set on every load, so a weapon resolved by name regains CHA).
        if stats.character_class == rpg.CharacterClass.Warlock and stats.has_invocation(13):
            app._bond_pact_weapon(cpp_weapons)

        # Soulknife (L3+): re-manifest the Psychic Blades. Saves made before the psychic_blade
        # binding existed (or while the grant failed) restored an empty default weapon — this
        # re-equips real blades so loaded Soulknives deal Psychic damage.
        cpp_weapons, sk_changed = app._apply_psychic_blades(stats, cpp_weapons)
        if sk_changed:
            stats.has_offhand_attack = True
            app.combat.set_agent_stats(app.bm, i, stats)

        app.combat.set_agent_weapons(app.bm, i, cpp_weapons)

    # Restore carried items (potions). Saves written before items existed simply have no
    # "items" key and load with an empty pack.
    for i, t in enumerate(agent_data):
        if i >= len(app.bm.placed_agents):
            break
        item_data = t.get("items", [])
        if item_data:
            app.combat.set_agent_items(
                app.bm, i, [_dict_to_item(d) for d in item_data])

    # Restore spells — load from spell_indices or legacy "spells" field.
    # Class features (Channel Divinity options like Divine Spark / Radiance of the Dawn) live in
    # classfeatures.json, not spells.json. They're auto-granted by _grant_class_features (by class +
    # level + subclass, with level-scaled dice), so any such names persisted into a save's
    # spell_indices are skipped here (not looked up in spells.json) to avoid a bogus "not found" warning.
    cf_names = {f.get("name") for f in app.all_class_features}
    for i, t in enumerate(agent_data):
        if i >= len(app.bm.placed_agents):
            break
        cpp_spells = []

        # Try new spell_indices format first (spell names as strings)
        spell_names = t.get("spell_indices", [])
        if spell_names:
            for j, spell_name in enumerate(spell_names):
                if spell_name in app.spell_name_to_idx:
                    idx = app.spell_name_to_idx[spell_name]
                    spell_dict = app.all_spells[idx]
                    cpp_spell = _dict_to_spell(spell_dict)
                    cpp_spells.append(cpp_spell)
                    # Store metadata (terrain, hatch, color)
                    meta = {
                        "terrain_effect": spell_dict.get("terrain_effect"),
                        "hatch_pattern": spell_dict.get("hatch_pattern"),
                        "terrain_color": spell_dict.get("terrain_color"),
                    }
                    app._spell_metadata[(i, j)] = meta
                elif spell_name in cf_names:
                    continue  # class feature — granted below via _grant_class_features, not from spells.json
                else:
                    available = ", ".join(sorted(list(app.spell_name_to_idx.keys())[:5])) + "..."
                    print(f"WARNING: Spell '{spell_name}' not found for agent {t.get('name', i)}")
                    print(f"         Available spells: {available}")
        else:
            # Fallback to legacy "spells" format for backward compatibility
            spell_data = t.get("spells", [])
            for j, item in enumerate(spell_data):
                # Handle both old formats: spell dicts or spell names (strings)
                if isinstance(item, dict):
                    cpp_spells.append(_dict_to_spell(item))
                    # Store metadata from dict
                    meta = {
                        "terrain_effect": item.get("terrain_effect"),
                        "hatch_pattern": item.get("hatch_pattern"),
                        "terrain_color": item.get("terrain_color"),
                    }
                    app._spell_metadata[(i, j)] = meta
                elif isinstance(item, str):
                    # Legacy format: spell stored as name string
                    # Look up in all_spells by name
                    if item in app.spell_name_to_idx:
                        idx = app.spell_name_to_idx[item]
                        spell_dict = app.all_spells[idx]
                        cpp_spells.append(_dict_to_spell(spell_dict))
                        # Store metadata
                        meta = {
                            "terrain_effect": spell_dict.get("terrain_effect"),
                            "hatch_pattern": spell_dict.get("hatch_pattern"),
                            "terrain_color": spell_dict.get("terrain_color"),
                        }
                        app._spell_metadata[(i, j)] = meta

        # Grant always-prepared class features (Channel Divinity options, etc.) from
        # classfeatures.json by class + level + subclass — same path as _apply_spells_to_agent, so
        # a loaded agent gets its features regardless of what was persisted in spell_indices.
        app._grant_class_features(i, cpp_spells)
        app.combat.set_agent_spells(app.bm, i, cpp_spells)

    # Restore armor — load from armor dict (new format) or legacy armor_indices (old format)
    for i, t in enumerate(agent_data):
        if i >= len(app.bm.placed_agents):
            break
        cpp_armor = [rpg.Armor() for _ in range(6)]  # 6 slots: [helmet, chest, leggings, boots, gloves, cloak]

        # Slot order: helmet, chest, leggings, boots, gloves, cloak
        SLOT_NAMES = ["helmet", "chest", "leggings", "boots", "gloves", "cloak"]

        # Try new armor dict format first (slot name -> armor name)
        armor_dict_new = t.get("armor", {})
        if armor_dict_new and isinstance(armor_dict_new, dict):
            for slot_idx, slot_name in enumerate(SLOT_NAMES):
                armor_name = armor_dict_new.get(slot_name, "")
                if isinstance(armor_name, dict):          # an enspelled piece, saved whole
                    cpp_armor[slot_idx] = _dict_to_armor(armor_name)
                elif armor_name and armor_name in app.armor_name_to_dict:
                    armor_def = app.armor_name_to_dict[armor_name]
                    cpp_armor[slot_idx] = _dict_to_armor(armor_def)
        else:
            # Fallback to legacy armor_indices format (list of names)
            armor_names = t.get("armor_indices", [])
            if armor_names:
                for slot_idx, armor_name in enumerate(armor_names):
                    if slot_idx >= 6:
                        break
                    if armor_name and armor_name in app.armor_name_to_dict:
                        armor_dict = app.armor_name_to_dict[armor_name]
                        cpp_armor[slot_idx] = _dict_to_armor(armor_dict)

        # Store armor in the C++ layer (as array of 6 pieces)
        app.combat.set_agent_armor(app.bm, i, cpp_armor)

        # Check STR requirements and warn if insufficient
        agent_stats = app.combat.get_agent_stats(app.bm, i)
        for piece in cpp_armor:
            if piece.name and not app.combat.can_equip_armor(app.bm, i, piece):
                print(f"⚠ {app.bm.placed_agents[i].name} wearing {piece.name} (requires STR {piece.str_requirement}, has {agent_stats.str})")

    # Restore NPC spell mechanics if present
    for i, t in enumerate(agent_data):
        if i >= len(app.bm.placed_agents):
            break
        is_npc = app._saved_is_npc(t)
        if is_npc:
            # An agent saved without a stats dict skipped the restore above.
            live = app.combat.get_agent_stats(app.bm, i)
            if not live.is_npc:
                live.is_npc = True
                app.combat.set_agent_stats(app.bm, i, live)
            npc_spell_groups = t.get("npc_spell_groups", {})
            # Initialize NPC spell groups in C++ (converts string keys to ints)
            if npc_spell_groups:
                groups_dict = {int(k): v for k, v in npc_spell_groups.items()}
                app.combat.init_npc_spell_groups(app.bm, i, groups_dict)
            # Restore breath-weapon recharge state: re-apply the per-monster
            # recharge_min and the saved uses_remaining / expended onto the
            # rebuilt Spell objects (spell_indices reload them at recharge_min=0).
            recharge_map = t.get("npc_spell_recharge", {})
            uses_cur     = t.get("npc_spell_uses_cur", {})
            expended_map = t.get("npc_spell_expended", {})
            if recharge_map or uses_cur or expended_map:
                spells = list(app.combat.get_agent_spells(app.bm, i))
                for sp in spells:
                    rmin = recharge_map.get(sp.name)
                    if rmin:
                        sp.recharge_min   = int(rmin)
                        sp.uses_max       = max(1, sp.uses_max)
                        sp.uses_remaining = sp.uses_max
                    if sp.name in uses_cur:
                        sp.uses_remaining = int(uses_cur[sp.name])
                    if expended_map.get(sp.name):
                        sp.expended = True
                app.combat.set_agent_spells(app.bm, i, spells)
            # Keep in _agent_meta for stats dialog to access
            app._agent_meta[i] = {"is_npc": True,
                                   "npc_spell_groups": npc_spell_groups,
                                   "npc_spell_recharge": recharge_map}

    # Boss finale flag (set by the dungeon generator on the deepest room's toughest mob).
    # Cosmetic only — drives the ★ badge in _draw_one_agent. Merged (not overwritten) so a
    # boss that is also a spellcaster keeps its npc_spell metadata from the loop above.
    for i, t in enumerate(agent_data):
        if i >= len(app.bm.placed_agents):
            break
        if t.get("is_boss"):
            app._agent_meta.setdefault(i, {})["is_boss"] = True

    # Restore the live active-condition list (durations, save timers, delayed effects, and
    # Vistani-Curse kickbacks). Done AFTER every agent is placed + stats/spells restored so the
    # saved agent_idx/caster_idx (already remapped to compacted order on save) resolve. Without
    # this a curse's flag might linger but its tracking entry — and thus its kickback — is lost.
    n_placed = len(app.bm.placed_agents)
    for cd in data.get("active_conditions", []):
        try:
            cond = _dict_to_condition(cd)
        except Exception as e:                       # noqa: BLE001 — skip a malformed entry, keep loading
            print(f"WARNING: could not restore active condition {cd}: {e}")
            continue
        if not (0 <= cond.agent_idx < n_placed):
            continue                                 # target no longer on the map
        app.combat.add_agent_condition(app.bm, cond)

    # Restore map items (dropped weapons). DM-placed design items come with the
    # terrain, so they survive the wipe.
    restore_design = placed_items.keep_design_items(app.bm)
    app.bm.clear_items()
    restore_design()
    for idata in data.get("map_items", []):
        if idata.get("kind") in ("armor", "item"):
            body = idata.get(idata["kind"]) or {}
            mi = placed_items.to_map_item(
                {"pid": -1, "kind": idata["kind"], "record": body,
                 "label": idata.get("label", "")},
                (int(idata["col"]), int(idata["row"])))
            app.bm.place_map_item(mi)
            continue
        wname = idata.get("weapon_name", "")
        weapon_dict = app.weapon_name_to_dict.get(wname, {})
        if isinstance(idata.get("weapon"), dict):
            weapon = _dict_to_weapon(idata["weapon"])
        elif weapon_dict:                       # legacy save: name only
            weapon = _dict_to_weapon(weapon_dict)
        else:
            continue
        cell = rpg.Cell(int(idata["col"]), int(idata["row"]))
        sprite_path = idata.get("sprite_path", weapon_dict.get("sprite_path", ""))
        app.bm.place_item(cell, weapon, sprite_path)

    app._attack_cells_melee = []
    app._attack_cells_rnorm = []
    app._attack_cells_rlong = []

    # Item-granted spells are derived from the restored items, weapons and armor (E3).
    app._sync_all_item_spells()

    # The agent list was just rebuilt, so every cached ownership index is stale.
    app._sync_roster_tokens()


def load_terrain(app, path: str | None = None, blank: bool = False):
    """Load terrain data from JSON file if it exists.

    If the file doesn't exist on first load, terrain starts empty.
    User can manually label terrain using the terrain editor,
    or choose to auto-detect walls as a fallback.

    ``blank=True`` skips the SCENE content (regions/doors/ladders/rooms/fog) —
    used at startup so a fresh session begins with an empty scene instead of
    inheriting whatever terrain was last saved for this map (load it explicitly
    via Terrain… → Load). MAP-INTRINSIC calibration is still honoured: the
    manual grid (Set Grid…, e.g. simplemap's 20×16 @ 50px that auto-detection
    misreads as 19×16) and the walls-detector preference describe how to read
    the PNG, not what's placed on it.
    """
    # Reset first so this is safe to call repeatedly when swapping encounters
    # (a new encounter with no terrain file must not inherit the previous scene).
    path = path or app._terrain_path
    app._terrain_regions = []
    app._terrain_rooms = []       # dungeon_from_png walk-order room metadata (if any)
    # Exact floor cells of the room the dungeon generator left empty for the party
    # (results[0] after the min-cells filter). Load PCs drops the party here, so it
    # must match the generator's choice rather than re-deriving "room 0". None ⇒ none.
    app._staging_cells = None
    app._walls_enabled = True
    app._walls_shown = True
    app._detection = None
    app._edge_overrides = None
    app._edge_review = None
    app._edges_carried_from = None
    app._manual_grid = None
    app.bm.reset_terrain_multipliers()
    # Doors live in BattleMap.doors. Clear any from the previous encounter; saved
    # doors are collected here and re-applied AFTER wall detection below (their closed
    # state sets the cell to Wall, which the clear/detect pass would otherwise wipe).
    for d in list(app.bm.doors):
        app.bm.remove_door(d.id)
    doors_data = []
    # Ladders are Python-side; clear the previous scene's before loading this one.
    app._ladders = []
    # Cross-map door links are also Python-side; rebuilt from door records below.
    app._door_links = {}
    explored_data = None  # fog-of-war mask from JSON; None = key absent (start fogged)
    # Placed items and chests (plans/ITEMS_AND_CHESTS_PLAN.md): the design lists, and
    # what play did to them (None = as designed). Applied after the doors below.
    app._design_items = []
    app._design_chests = []
    items_state = chests_state = None

    # The scene's own terrain comes through the store; an explicit other path (Terrain
    # → Import) is read as a file.
    from_store = (path == app._terrain_path)

    def _read_terrain():
        if from_store:
            return app.store.terrain()
        with open(path, 'r') as f:
            return json.load(f)

    have = app.store.has_terrain() if from_store else os.path.exists(path)
    if blank and have:
        # Blank startup: apply ONLY the map-intrinsic calibration keys.
        try:
            data = _read_terrain()
            mg = data.get("manual_grid")
            if mg:
                try:
                    app.bm.set_uniform_grid(int(mg["cell_px"]),
                                             int(mg["anchor"][0]),
                                             int(mg["anchor"][1]))
                    app._manual_grid = mg
                except Exception:
                    app._manual_grid = None
            app._walls_enabled = bool(data.get("walls_enabled", True))
            app._walls_shown = bool(data.get("walls_shown", True))
            app._detection = data.get("detection")
            app._edge_overrides = data.get("edge_overrides")
            app._edge_review = data.get("edge_review")
            app._edges_carried_from = data.get("edges_carried_from")
        except Exception:
            pass
    elif have:
        try:
            data = _read_terrain()
            # A saved manual grid must be applied first: it resizes the per-cell
            # terrain/light buffers, so it has to run before terrain regions are
            # written into them.
            mg = data.get("manual_grid")
            if mg:
                try:
                    app.bm.set_uniform_grid(int(mg["cell_px"]),
                                             int(mg["anchor"][0]),
                                             int(mg["anchor"][1]))
                    app._manual_grid = mg
                except Exception:
                    app._manual_grid = None
            app._terrain_regions = data.get("regions", [])
            app._terrain_rooms = data.get("rooms", [])
            app._staging_cells = data.get("staging_cells")  # None if absent
            app._walls_enabled = bool(data.get("walls_enabled", True))
            app._walls_shown = bool(data.get("walls_shown", True))
            app._detection = data.get("detection")
            app._edge_overrides = data.get("edge_overrides")
            app._edge_review = data.get("edge_review")
            app._edges_carried_from = data.get("edges_carried_from")
            doors_data = data.get("doors", [])
            app._ladders = normalize_ladders(data.get("ladders", []))
            explored_data = data.get("explored")  # None if absent → stays fully fogged
            app._design_items = [r for r in data.get("items", []) or []
                                  if isinstance(r, dict)]
            app._design_chests = [c for c in data.get("chests", []) or []
                                   if isinstance(c, dict)]
            items_state = data.get("items_state")
            chests_state = data.get("chests_state")
        except Exception:
            app._terrain_regions = []

    # Always reconcile painted terrain with the engine — even with no file — so swapping to a
    # fileless encounter reverts the previous scene's painted Wall/Chasm/Water cells to Standard.
    app._apply_terrain_to_battle_map()

    # Saved doors go in before wall detection: the outside flood stops at doors, so it
    # needs them placed (detection re-syncs each door's terrain afterwards).
    # New saves store a "cells" list (multi-cell wide doors); fall back to the legacy
    # single-cell "cell" field for older encounter files.
    for d in doors_data:
        try:
            raw = d.get("cells")
            if d.get("edges"):
                did = app.bm.add_edge_door([edge_from_key(e) for e in d["edges"]],
                                            bool(d.get("open", False)),
                                            bool(d.get("locked", False)),
                                            int(d.get("lock_dc", 15)),
                                            bool(d.get("arcane_lock", False)),
                                            int(d.get("break_dc", 15)))
                if bool(d.get("broken", False)):
                    app.bm.break_door(did)
                restore_secret_door(app, did, d)
                if d.get("lair_lock"):
                    app.bm.set_door_lair_lock(did, True)
                continue
            if raw:
                cells = [rpg.Cell(int(c[0]), int(c[1])) for c in raw]
            else:
                c = d["cell"]
                cells = [rpg.Cell(int(c[0]), int(c[1]))]
            did = app.bm.add_door(cells,
                                   bool(d.get("open", False)),
                                   bool(d.get("locked", False)),
                                   int(d.get("lock_dc", 15)),
                                   bool(d.get("arcane_lock", False)),
                                   int(d.get("break_dc", 15)))
            # A door saved smashed off its frame comes back broken (permanently open).
            if bool(d.get("broken", False)):
                app.bm.break_door(did)
            restore_secret_door(app, did, d)
            if d.get("lair_lock"):
                app.bm.set_door_lair_lock(did, True)
            # Re-associate a cross-map staple target (null/absent on ordinary doors).
            lt = d.get("link_target")
            if lt:
                app._door_links[door_link_key(cells)] = [int(lt[0]), int(lt[1]), int(lt[2])]
        except Exception:
            continue

    placed_items.place_chests(app.bm, app._design_chests, chests_state)
    placed_items.place_floor_items(app.bm, app._design_items, items_state)

    # Honour the walls preference: ON re-detects from a clean slate; OFF drops every
    # auto-detected obstacle so a map the detector mis-read isn't blocked. (On first
    # load detect_walls already ran in __init__; clear+detect reproduces that result.)
    app._redetect_walls()

    # Grid (re)analysis in C++ resets the explored mask to fully fogged. Restore the
    # persisted mask here (after all grid/wall/door processing that would clear it), so
    # rooms seen in a prior session stay revealed. An absent "explored" key (old saves)
    # leaves the map fully fogged. _mark_fog_dirty then ORs in whatever the party can
    # currently see on top of the restored set (monotonic, so this is always safe).
    if explored_data is not None:
        try:
            cells = [rpg.Cell(int(c[0]), int(c[1])) for c in explored_data]
            app.bm.set_explored_cells(cells)
        except Exception:
            pass
    app._mark_fog_dirty()
    # The walls/doors just applied must reach the screen too. Without this a loaded
    # page showed "Walls: ON" with nothing drawn until Walls was toggled off and on,
    # and that OFF window let the fog reveal straight through every wall.
    app._build_overlay()
    if hasattr(app, "btn_toggle_walls"):     # the first load runs before the panel exists
        app.btn_toggle_walls.text = app._walls_label()


def normalize_ladders(raw):
    """Coerce ladder records from JSON into the in-memory shape
    ``{"cells": [(col,row),...], "target": [X, Y, Z]}``. Skips malformed entries."""
    out = []
    for lad in raw or []:
        try:
            cells = [(int(c[0]), int(c[1])) for c in lad["cells"]]
            tgt = lad["target"]
            target = [int(tgt[0]), int(tgt[1]), int(tgt[2])]
            if cells:
                out.append({"cells": cells, "target": target})
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return out


def restore_secret_door(app, did: int, rec: dict):
    """A saved door record's secret design and hidden state onto door ``did``: a
    secret door comes back hidden unless the record says it was found."""
    if rec.get("secret"):
        app.bm.set_door_secret(did, True)
        if not rec.get("hidden", True):
            app.bm.set_door_hidden(did, False)


def save_terrain(app, path: str | None = None):
    """Save terrain data to JSON file (defaults to the active encounter's path)."""
    path = path or app._terrain_path
    data = {"regions": app._terrain_regions, "walls_enabled": app._walls_enabled}
    if not app._walls_shown:           # only HIDDEN writes it: other files stay as they were
        data["walls_shown"] = False
    # Doors (source of truth is BattleMap.doors). "cells" carries every doorway cell
    # so wide (multi-cell) doors round-trip; "cell" is kept for backward readability.
    # An edge door (drawn maps) carries "edges", [c, r, "E"|"S"] each, in place of
    # "cells" and "cell".
    data["doors"] = [
        dict(({"edges": [list(edge_key(e)) for e in d.edges]} if d.edges else
              {"cells": [[c.col, c.row] for c in d.cells],
               "cell": [d.cell.col, d.cell.row]}),
             open=d.open, locked=d.locked, lock_dc=d.lock_dc,
             arcane_lock=d.arcane_lock, break_dc=d.break_dc, broken=d.broken,
             # Cross-map staple target in GLOBAL (X,Y,Z); null for an ordinary in-map door.
             link_target=app._door_link_at(d),
             # Only a secret door carries these, so other doors' records are unchanged.
             **({"secret": True, "hidden": d.hidden} if d.secret else {}),
             # Strahd's lair lock (STRAHD_LAIR_PLAN D4) likewise rides only when set.
             **({"lair_lock": True} if d.lair_lock else {}))
        for d in app.bm.doors
    ]
    # Placed items and chests: the design (map data) and what play did to them. Only
    # a map that has some writes the keys, so an untouched map.json stays untouched.
    if app._design_items:
        data["items"] = app._design_items
        data["items_state"] = placed_items.floor_state(app.bm)
    if app._design_chests:
        data["chests"] = app._design_chests
        data["chests_state"] = placed_items.chests_state(app.bm)
    # Ladders (vertical portals) — Python-only cell objects; target is GLOBAL (X,Y,Z).
    data["ladders"] = [
        {"cells": [[int(c[0]), int(c[1])] for c in lad["cells"]],
         "target": [int(lad["target"][0]), int(lad["target"][1]), int(lad["target"][2])]}
        for lad in app._ladders
    ]
    if app._manual_grid:
        data["manual_grid"] = app._manual_grid
    # Written only once the DM has set them, so an untouched page's file is unchanged.
    if app._detection:
        data["detection"] = app._detection
    if app._edge_overrides and (app._edge_overrides.get("add") or app._edge_overrides.get("remove")):
        data["edge_overrides"] = app._edge_overrides
    if app._edge_review:
        data["edge_review"] = app._edge_review
    if app._edges_carried_from:
        data["edges_carried_from"] = app._edges_carried_from
    # Walk-order rooms from the terrain carver — the link between the terrain
    # floor plan and the encounter floor plan (Generate Dungeon populates these
    # exact rooms). Persisted so the linkage survives save/reload; previously only
    # the multi-floor generator's sidecars carried it (app_dungeon_gen.write_generated_terrain).
    if getattr(app, "_terrain_rooms", None):
        data["rooms"] = app._terrain_rooms
    # Staging room the dungeon generator left empty for the party (Load PCs targets it).
    if getattr(app, "_staging_cells", None):
        data["staging_cells"] = [[int(c), int(r)] for (c, r) in app._staging_cells]
    # Fog of war: persist the PC-party explored mask so a room seen once stays
    # revealed across save/reload. Compact [col, row] pairs; absent → fully fogged.
    data["explored"] = [[c.col, c.row] for c in app.bm.explored_cells()]
    if path == app._terrain_path:
        app.store.write_terrain(data)
    else:                                   # Terrain → Export to a chosen file
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
