#!/usr/bin/env python3
"""
RPG Battle Map Viewer
─────────────────────
Usage:  python main.py <map_image.png>

Left panel  – the battle map with grid / wall / agent overlays
Right panel – agent configuration GUI (add / remove / place agents)
"""

import sys
import os
import json
import re
import math
import random
import shutil

os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame
import pygame.gfxdraw

import textwrap
import copy
import read_stats_from_csv

# ── Import the C++ analysis core ──────────────────────────────────────────────
try:
    import rpg_battle_map as rpg
except ModuleNotFoundError:
    sys.exit(
        "ERROR: rpg_battle_map module not found.\n"
        "Build it first:  cmake --build build && cmake --install build"
    )

# ─────────────────────────────────────────────────────────────────────────────
#  Colour palette
# ─────────────────────────────────────────────────────────────────────────────

# ── Extracted modules ──────────────────────────────────────────────────────
from constants import *
from widgets import Button, TextInput, IntStepper
from helpers import (
    _dnd_mod, _mod_str,
    _parse_physical_damage, _parse_magic_damage,
    _DEFAULT_WEAPON, _weapon_to_dict, _dict_to_weapon,
    _DEFAULT_ARMOR, _armor_to_dict, _dict_to_armor,
    _ABILITY_TO_INT, _INT_TO_ABILITY, _DEFAULT_SPELL,
    _spell_to_dict, _dict_to_spell,
    can_place_agent, summon_cell_placeable, compute_companion_loadout,
)
from dialogs import FileBrowser, StatsDialog, MobSelectionDialog, ContextMenu, SpellSelectionDialog, ArmorSelectionDialog, WeaponSelectionDialog, ArmorDialog, WeaponsDialog, GENERAL_FEAT_NAMES, ElementPickerDialog, TeamPickerDialog, GridSpanDialog, NamePromptDialog
from dialogs_conditions import ConditionsDialog
from weapon_dialog import WeaponDialog
from spell_dialog import SpellDialog
from terrain_dialogs import TemporaryTerrainPlacementDialog, TerrainEditorDialog
from lighting_dialogs import LightingEditorDialog
from agent_loader import dict_to_stats, restore_class_resources, _dict_to_weapon, apply_damage_multipliers

# ── Summoning registry ─────────────────────────────────────────────────────
# Maps a summon spell's name to the DND2024_MonsterStats.json key it conjures.
# The RAW 2024 summon "spirit" stat blocks (Draconic/Bestial/Fey/Undead Spirit) are not in the
# monster file, so Summon Dragon currently uses the closest existing entry as a stand-in.
# Extend this dict as more summon spells/stat blocks are added.
SUMMON_SPELL_TO_MONSTER = {
    "Summon Dragon": "Spirit Dragon Wyrmling",
}

# Spells whose damage type is chosen per cast (not fixed in spells.json). Each maps to the
# ElementPickerDialog option list (label, MagicDamage_t int) of the legal types. The choice is
# stored as SpellAction.damage_type_override and rewrites the cast's damage type in executeSpell.
# MagicDamage_t: Acid=0, Cold=1, Fire=2, Lightning=4, Poison=6, Psychic=7, Thunder=9.
ELEMENT_CHOICE_SPELLS = {
    "Chromatic Orb":   [("Acid", 0), ("Cold", 1), ("Fire", 2), ("Lightning", 4), ("Poison", 6), ("Thunder", 9)],
    "Sorcerous Burst": [("Acid", 0), ("Cold", 1), ("Fire", 2), ("Lightning", 4), ("Poison", 6), ("Psychic", 7), ("Thunder", 9)],
}

class App:
    # ── Bonus-action economy: a thin view over the C++ engine budget ──────────
    # `self.bonus_used` is NOT a plain flag — it reads/writes the active combatant's
    # bonus-action budget in the engine (Agent::Stats.bonus_actions_remaining/max via
    # has_bonus_action / spend_bonus_action / reset_bonus_actions). Reading answers
    # "has the current combatant spent their bonus action(s) this turn?"; assigning
    # True spends one, False refills to max. Keeping the rule in C++ (not a Python
    # bool) makes it the single source of truth and lets feats grant extra bonus
    # actions (bonus_actions_max > 1). Before combat / with no active combatant it
    # falls back to a plain attribute so early __init__ assignments are harmless.
    def _bonus_economy_idx(self) -> int:
        """Active combatant index for the bonus-action budget, or -1 if the engine
        isn't ready / no one is acting (pre-combat __init__, between combats)."""
        if getattr(self, "combat", None) is None or getattr(self, "bm", None) is None:
            return -1
        return self._current_agent_idx()

    @property
    def bonus_used(self) -> bool:
        idx = self._bonus_economy_idx()
        if idx < 0:
            return getattr(self, "_bonus_used_fallback", False)
        return not self.combat.has_bonus_action(self.bm, idx)

    @bonus_used.setter
    def bonus_used(self, value: bool) -> None:
        idx = self._bonus_economy_idx()
        if idx < 0:
            self._bonus_used_fallback = bool(value)
            return
        if value:
            self.combat.spend_bonus_action(self.bm, idx)
        else:
            self.combat.reset_bonus_actions(self.bm, idx)

    def __init__(self, map_path: str):
        pygame.init()
        pygame.display.set_caption("RPG Battle Map")

        # ── Load json file containing all available mobs from a huge spreadsheet
        script_dir = os.path.dirname(os.path.abspath(__file__))
        map_dir = os.path.dirname(os.path.abspath(map_path))
        # Try multiple possible locations for the CSV file
        possible_paths = [
            os.path.join(script_dir, "gui", "DND2024_MonsterStats.csv"),
            os.path.join(script_dir, "..", "gui", "DND2024_MonsterStats.csv"),
            os.path.join(map_dir, "..", "gui", "DND2024_MonsterStats.csv"),
            "gui/DND2024_MonsterStats.csv",
        ]
        csv_path = None
        for path in possible_paths:
            if os.path.exists(path):
                csv_path = path
                break
        if not csv_path:
            sys.exit(f"ERROR: Could not find DND2024_MonsterStats.csv. Checked: {possible_paths}")

        # Create or load JSON file with mob stats
        json_path = os.path.splitext(csv_path)[0] + '.json'
        if not os.path.exists(json_path):
            json_path = read_stats_from_csv.save_stats_as_json(csv_path, json_path)
        self.mob_stats_json = read_stats_from_csv.load_stats_from_json(json_path)
        self.all_mobs = self.mob_stats_json

        # Determine sprites directory (CSV moved to gui, but sprites may be in sprites/ or ../sprites/)
        possible_sprite_dirs = [
            os.path.join(script_dir, "sprites"),
            os.path.join(script_dir, "..", "sprites"),
        ]
        self.sprites_dir = None
        for sprite_dir in possible_sprite_dirs:
            if os.path.exists(sprite_dir):
                self.sprites_dir = sprite_dir
                break
        if not self.sprites_dir:
            # Fallback to CSV directory if sprites directory not found
            self.sprites_dir = os.path.dirname(csv_path)

        # ── Load spells from spells.json ──────────────────────────────────
        self.all_spells = []  # list of spell dicts from spells.json
        possible_spell_paths = [
            os.path.join(script_dir, "spells.json"),
            os.path.join(script_dir, "..", "spells.json"),
            os.path.join(map_dir, "spells.json"),
            "spells.json",
        ]
        spells_loaded_from = None
        for spells_path in possible_spell_paths:
            if os.path.exists(spells_path):
                try:
                    with open(spells_path) as f:
                        self.all_spells = json.load(f)
                    spells_loaded_from = spells_path
                    break
                except (json.JSONDecodeError, IOError):
                    continue

        if self.all_spells:
            print(f"✓ Loaded {len(self.all_spells)} spells from {spells_loaded_from}")
        else:
            print("⚠ WARNING: No spells loaded. Agents with spells will not function.")

        # Create spell lookup: spell_name -> index
        self.spell_name_to_idx = {s.get("name"): i for i, s in enumerate(self.all_spells)}

        # ── Load class features from classfeatures.json ───────────────────
        # "Spells that aren't technically spells" — Channel Divinity options, etc.
        # Same schema as spells.json plus resource_name/resource_cost; cast via the
        # spell pipeline but spend a class resource instead of a spell slot.
        self.all_class_features = []
        for cf_path in (os.path.join(script_dir, "classfeatures.json"),
                        os.path.join(map_dir, "classfeatures.json"),
                        "classfeatures.json"):
            if os.path.exists(cf_path):
                try:
                    with open(cf_path) as f:
                        self.all_class_features = json.load(f)
                    print(f"✓ Loaded {len(self.all_class_features)} class features from {cf_path}")
                    break
                except (json.JSONDecodeError, IOError):
                    continue

        # ── Load weapons from weapons.json ──────────────────────────────────
        self.all_weapons = []  # list of weapon dicts from weapons.json
        possible_weapon_paths = [
            os.path.join(script_dir, "weapons.json"),
            os.path.join(script_dir, "..", "weapons.json"),
            os.path.join(map_dir, "weapons.json"),
            "weapons.json",
        ]
        weapons_loaded_from = None
        for weapons_path in possible_weapon_paths:
            if os.path.exists(weapons_path):
                try:
                    with open(weapons_path) as f:
                        self.all_weapons = json.load(f)
                    weapons_loaded_from = weapons_path
                    break
                except (json.JSONDecodeError, IOError):
                    continue

        if self.all_weapons:
            print(f"✓ Loaded {len(self.all_weapons)} weapons from {weapons_loaded_from}")
        else:
            print("⚠ WARNING: No weapons loaded. Agents with weapons will not function.")

        # Create weapon lookup: weapon_name -> weapon_dict
        self.weapon_name_to_dict = {w.get("name"): w for w in self.all_weapons}

        # ── Load armor from armor.json ──────────────────────────────────────
        self.all_armor = []  # list of armor dicts from armor.json
        possible_armor_paths = [
            os.path.join(script_dir, "armor.json"),
            os.path.join(script_dir, "..", "armor.json"),
            os.path.join(map_dir, "armor.json"),
            "armor.json",
        ]
        armor_loaded_from = None
        for armor_path in possible_armor_paths:
            if os.path.exists(armor_path):
                try:
                    with open(armor_path) as f:
                        self.all_armor = json.load(f)
                    armor_loaded_from = armor_path
                    break
                except (json.JSONDecodeError, IOError):
                    continue

        if self.all_armor:
            print(f"✓ Loaded {len(self.all_armor)} armor pieces from {armor_loaded_from}")
        else:
            print("⚠ WARNING: No armor loaded.")

        # Create armor lookup: armor_name -> armor_dict
        self.armor_name_to_dict = {a.get("name"): a for a in self.all_armor}

        # Selected mob's stats (loaded when a mob is selected from dropdown)
        self.selected_mob_stats = None
        self.current_mob_grid_size = 1  # Grid size for current mob (1-4)

        # Pending PC creation (used when placing a new PC)
        self._pending_pc_class = None
        self._pending_pc_stats = None

        # ── Load C++ battle map ───────────────────────────────────────────
        self.bm = rpg.BattleMap(map_path)
        self.bm.analyze_grid()
        self.bm.detect_walls()

        # ── Load image to get size BEFORE creating the display ────────────
        # convert_alpha() requires a display surface to exist first, so we
        # load raw here, create the window, then convert/scale below.
        raw_map = pygame.image.load(map_path)
        mw, mh  = raw_map.get_size()

        # ── Auto-scale map to fit within a reasonable display area ────────
        # Leave room for the right-side config panel and keep some margin.
        MAX_MAP_W = 1860 - PANEL_W   # fits comfortably on a 1920-wide display
        MAX_MAP_H = 1040             # fits comfortably on a 1080-tall display
        scale = min(MAX_MAP_W / mw, MAX_MAP_H / mh, 1.0)  # never upscale
        disp_mw = int(mw * scale)
        disp_mh = int(mh * scale)
        self.map_scale = scale       # used to convert C++ pixel coords → screen

        # ── Window sizing ─────────────────────────────────────────────────
        win_w = disp_mw + PANEL_W
        win_h = max(disp_mh, 600)
        self.screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)

        # ── Now safe to convert (display surface exists) ──────────────────
        converted = raw_map.convert_alpha()
        if scale < 1.0:
            self.map_surf = pygame.transform.smoothscale(converted, (disp_mw, disp_mh))
        else:
            self.map_surf = converted
        self.map_rect = pygame.Rect(0, 0, disp_mw, disp_mh)

        # ── Fonts ─────────────────────────────────────────────────────────
        self.font_sm = pygame.font.SysFont("sans", FONT_SM)
        self.font_md = pygame.font.SysFont("sans", FONT_MD)
        self.font_lg = pygame.font.SysFont("sans", FONT_LG, bold=True)

        # ── Overlay surfaces (alpha) – matches the displayed (scaled) size ──
        self.overlay = pygame.Surface((disp_mw, disp_mh), pygame.SRCALPHA)
        self._build_overlay()

        # ── Sprite cache  {sprite_path: pygame.Surface} ───────────────────
        self.sprites: dict[str, pygame.Surface] = {}

        # ── File browser (shared modal) ───────────────────────────────────
        self.file_browser   = FileBrowser(self.font_sm, self.font_md, self.font_lg)
        self.stats_dialog   = StatsDialog(self.font_sm, self.font_md, self.font_lg, spells=self.all_spells)
        self.weapon_dialog  = WeaponDialog(self.font_sm, self.font_md, self.font_lg)
        self.spell_dialog   = SpellDialog(self.font_sm, self.font_md, self.font_lg)
        self.spell_selection_dialog = SpellSelectionDialog(self.all_spells, self.font_sm, self.font_md)
        self.armor_selection_dialog = ArmorSelectionDialog(list(self.armor_name_to_dict.values()), self.font_sm, self.font_md)
        self.weapon_selection_dialog = WeaponSelectionDialog(list(self.weapon_name_to_dict.values()), self.font_sm, self.font_md)
        self.armor_dialog = ArmorDialog(self.font_sm, self.font_md)
        self.weapons_dialog = WeaponsDialog(self.font_sm, self.font_md)
        mob_names = sorted(self.all_mobs.keys())
        self.mob_dialog = MobSelectionDialog(mob_names, self.font_sm, self.font_md)
        self.terrain_editor = TerrainEditorDialog(self.font_sm, self.font_md)
        self.terrain_placement_dialog = TemporaryTerrainPlacementDialog(self.font_sm, self.font_md)
        self.lighting_editor = LightingEditorDialog(self.font_sm, self.font_md)
        self.conditions_dialog = ConditionsDialog(self.font_sm, self.font_md, self.font_lg)
        self.context_menu   = ContextMenu()
        # Cast-time element picker (Chromatic Orb / Sorcerous Burst). Reuses the same modal as
        # Elemental Adept's feat picker; opened from _activate, single-select.
        self._element_dialog = ElementPickerDialog(self.font_sm, self.font_md)

        # Asks how many cells a sampled grid box spanned (manual-grid precision).
        self._grid_span_dialog = GridSpanDialog(self.font_sm, self.font_md)
        self._pending_grid_box = None   # (x0, y0, w, h) in image px, awaiting span input

        # Team/faction picker (opened from an agent's right-click menu → "Set Teams…").
        self.team_dialog = TeamPickerDialog(self.font_sm, self.font_md)

        # Rename prompt (opened from an agent's right-click menu → "Edit Name…").
        self.name_prompt = NamePromptDialog(self.font_sm, self.font_md)

        # ── NPC spell mechanics ──────────────────────────────────────────────
        self._agent_meta: dict[int, dict] = {}  # {agent_idx: {"npc_spell_groups": {...}}} — for stats dialog

        self._map_dir  = os.path.dirname(os.path.abspath(map_path)) or "/"
        self._terrain_regions = []  # List of {type, x, y, width, height, multiplier}
        self._walls_enabled = True   # auto-detected walls active? (toggle persists in terrain JSON)

        # Manual grid (sample-a-tile) state. When _manual_grid is set the detected grid
        # has been replaced by a uniform one; persisted in the terrain JSON.
        self._manual_grid = None            # {"cell_px": int, "anchor": [x, y]} or None
        self._grid_sample_mode  = False     # True while waiting for the user to drag a tile
        self._grid_sample_start = None      # screen-space drag start (x, y)
        self._grid_sample_cur   = None      # screen-space drag current (x, y)

        # An "encounter" = agents + terrain + lighting + effects, stored as four
        # sidecar JSON files that share one base name. The map PNG is shared (passed
        # on the command line) so many encounters can reuse the same map. The initial
        # base name is derived from the map for backward compatibility; Save/Load can
        # re-point it anywhere via _set_encounter_base().
        default_agents = os.path.join(
            self._map_dir,
            os.path.splitext(os.path.basename(map_path))[0] + "_agents.json"
        )
        self._set_encounter_base(default_agents)

        # Load terrain, spell effects, and lighting data if they exist
        self._load_terrain()
        self._load_spell_effects()
        self._load_lighting()

        # Evoker "safe targets" editing: index of the Evoker whose safe set is being
        # edited via map clicks (-1 = not editing). Out-of-combat only.
        self.safe_target_edit_idx = -1

        # ── Drag-and-drop state ───────────────────────────────────────────
        self.drag_idx     = -1         # index of agent being dragged
        self.drag_origin  = None       # Cell: original position (for cancel)
        self.drag_offset  = (0, 0)     # (dcol, drow) within agent where click landed
        self.drag_cell    = None       # Cell: current snapped target
        self.drag_valid   = False      # is current drag_cell a legal drop?

        # ── Copy/paste clipboard (pre-combat encounter building) ───────────
        self._agent_clipboard = None   # snapshot dict of a copied agent (Ctrl+C / Ctrl+V)

        # ── Placement mode state (for floating agent placement) ────────────
        self.placement_mode_active = False  # True when placing new agent
        self.placement_config: rpg.AgentConfig | None = None  # Config for agent being placed
        self.placement_cell: rpg.Cell | None = None  # Current cell under mouse
        self.placement_valid = False  # Is current placement location valid?
        self._pc_name_input: TextInput | None = None  # Name input for new PC

        # ── Selection state ───────────────────────────────────────────────
        self.selected_idx  = -1        # index of selected agent (-1 = none)
        self._reach_walk: list = []    # Cell list for walk range overlay
        self._reach_fly:  list = []    # Cell list for fly range overlay
        self._reach_set:  set  = set() # union of walk+fly as (col,row) tuples for O(1) lookup

        # ── Visualization toggles ─────────────────────────────────────────
        self.show_lighting_overlay = False  # Toggle for lighting visualization

        # ── Combat engine (C++ — seeded PRNG, RL-ready) ──────────────────
        import time
        from replay_record import RecordingCombat
        self.combat_seed = int(time.time() * 1000) % (2**32)
        # Wrap the engine so every state-mutating call is recorded for checked replay.
        self.combat = RecordingCombat(rpg.CombatEngine(self.combat_seed), rpg)
        self.logger = rpg.MessageLogger()
        self.combat.set_logger(self.logger)
        self.replay_log_file = None  # Will be set during combat start

        # ── Attack-range overlay ──────────────────────────────────────────
        self._attack_cells_melee:  list = []   # cells attackable by active melee weapon
        self._attack_cells_rnorm:  list = []   # cells in ranged normal range
        self._attack_cells_rlong:  list = []   # cells only in ranged long range

        # ── Combat widget state ───────────────────────────────────────────
        self.combat_active        = False
        self.initiative_order     = []    # list[rpg.InitiativeEntry], high→low
        self.initiative_item_rects = []  # list[pygame.Rect], clickable areas for initiative items
        self.turn_idx             = 0     # index into initiative_order
        self.action_used          = False
        self.bonus_used           = False
        self.pending_attack_slot      = ""    # "" | "action" | "bonus"
        self.pending_weapon_idx       = 0
        # Generic extra-attack knobs (War Priest, Great Weapon Master, Nick, …). Reset per attack.
        self.pending_attack_offhand   = None  # None = derive from slot; True/False overrides proficiency
        self.pending_attack_resource  = None  # resource name to spend on a valid attack (e.g. "War Priest")
        # Cleave weapon mastery: awaiting a 2nd-target click. {"attacker","first","weapon"} or None.
        # Resolved out-of-band (no attacks_remaining / bonus-action accounting): Cleave is part of
        # the Attack action, not a bonus action.
        self.pending_cleave           = None
        self.pending_sweep            = None   # Battle Master Sweeping Attack: awaiting 2nd-target click
        self.pending_rally            = None   # Battle Master Rally: awaiting ally-target click
        self.pending_feint            = None   # Battle Master Feinting Attack: awaiting target click
        self.attacks_remaining        = 0     # attacks left in current pending slot
        self._attack_sequence_slot    = ""    # "action" | "bonus" | "" — which slot the sequence belongs to
        self.pending_spell_slot        = ""    # "" | "action" | "bonus"
        self.pending_spell_idx         = 0
        self.pending_spell_is_aoe      = False
        self.pending_spell_num_targets = 0     # For Multiple geometry: number of targets to select
        self.pending_spell_targets     = []    # For Multiple geometry: collected targets
        # Chromatic Orb leap chain: after the primary target is chosen, the player clicks the
        # orb's preferred leap path (each hop within 30 ft of the previous), then Enter to cast
        # / Esc to cancel. The chain rides on SpellAction.chromatic_leap_targets; unpicked hops
        # auto-target the nearest foe engine-side.
        self.pending_chromatic_active  = False
        self.pending_chromatic_primary = -1
        self.pending_chromatic_chain   = []
        # Summoning: awaiting a cell click to place a summoned creature.
        self.pending_summon_slot       = ""    # "" | "action" | "bonus"
        self.pending_summon_idx        = 0     # spell index of the summon spell being cast
        self.pending_summon_slot_level = 0     # chosen slot level
        self.pending_summon_monster    = ""    # monster-JSON key to spawn
        self.summon_hover_cell         = None  # cell under mouse while choosing a summon spot
        self.arcane_charge_pending     = False # Eldritch Knight L15: awaiting a teleport destination after Action Surge
        self.pending_shove_slot        = ""    # "" | "bonus" for shove actions
        self.pending_shove_type        = ""    # "push" | "prone"
        self.pending_grapple_slot      = ""
        self.pending_unarmed_type      = ""    # "" | "punch" | "grapple" | "push"
        self.pending_heal_light        = False # Celestial Warlock Healing Light: awaiting target click
        self.pending_lay_on_hands      = False # Paladin Lay on Hands: awaiting target click
        self.pending_grant_inspiration = False # Bard Grant Inspiration: awaiting ally target click
        self.pending_telekinetic       = False # Psi Warrior Telekinetic Movement: awaiting target click
        self.pending_flurry_target     = False # Monk Flurry of Blows: awaiting target click
        self.pending_vitality_target   = False # World Tree Vitality of the Tree: awaiting target click (within a parked turn-start window)
        self._vitality_option_index    = -1    # the chosen reaction option index to submit once a target is picked
        self.pending_flurry_atk_idx    = -1    # attacker index for Flurry
        self.pending_flurry_rider_option = -1  # Open Hand rider option (0=Knockdown, 1=Push, 2=DenyReaction, -1=None)
        self._unarmed_strike_original_weapons = None  # (idx, weapons) to restore after attack
        # Reaction system: OA detection/resolution lives in the C++ engine
        # (begin_move/pending_decision/submit_decision). These just track the parked mover for the
        # post-commit GUI refresh while a reaction checkpoint is open.
        self._reaction_mover_idx  = -1    # mover whose move is parked at a reaction checkpoint
        self._reaction_dist_moved = 0     # cells*5 of that move (running-jump tracking)
        # A reaction checkpoint can interrupt either a move (begin_move) or a spell cast (begin_cast,
        # OnDeclareCast/Shield). _reaction_finish is the continuation run once the parked flow resolves;
        # it's set before begin_move/begin_cast and invoked by _submit_reaction on completion.
        self._reaction_finish     = lambda: None
        self._turn_start_idx      = -1    # agent whose turn-start window (OnTurnStartNearby) is parked
        self._cast_post           = {}    # context the parked cast needs for post-resolve logging
        self._attack_post         = {}    # context the parked attack needs for post-resolve rider chain
        self.spell_hover_cell     = None  # cell under mouse during AoE targeting
        self.spell_anchor_cell    = None  # first click of a two-click wall (Rectangle) cast
        self.combat_log           = []    # list[str], newest first
        self.move_remaining_walk   = 0     # feet remaining this turn (walk)
        self.move_remaining_fly    = 0     # feet remaining this turn (fly)
        self.move_remaining_swim   = 0     # feet remaining this turn (swim)
        self.move_remaining_burrow = 0     # feet remaining this turn (burrow)
        self.move_type             = rpg.MovementType.Walk  # selected movement type
        self._move_type_btns: dict = {}    # MovementType -> pygame.Rect (built each draw)
        self.last_movement_dist    = 0     # distance of most recent movement (for running jump)
        self.jump_overlay_active   = False # whether jump overlay is showing
        self.jump_reachable_cells  = []    # cells reachable by jump

        # ── Temporary terrain effects (spells, items, etc. with duration) ───
        self.round_num              = 0     # current round number (incremented when turn_idx wraps)
        self._effect_meta: dict     = {}    # {effect_id: {"name": str, "color": tuple, "cells": [(col,row)]}}
        self.show_terrain            = False # toggle for showing all terrain regions
        self._status_msg             = ""    # transient confirmation text (Save/Load Terrain, …)
        self._status_msg_until       = 0     # pygame ticks (ms) when _status_msg expires
        self.show_spell_effects      = True  # toggle for showing persistent spell effect overlays
        self.show_visible_targets    = False # toggle for showing visible target debug info
        self._spell_metadata: dict = {} # {(agent_idx, spell_idx): {"terrain_effect": dict, "hatch_pattern": str, "level", "upcast_dice_bonus"}}

        # ── Spell slot economy (class-based caster tracking) ────────────────
        self.pending_spell_slot_level: int = 0          # slot level chosen for current spell cast
        self.pending_spell_damage_type: int = -1        # cast-time element choice (Chromatic Orb / Sorcerous
                                                        # Burst); -1 = use the spell's stored type

        # ── Agent config GUI state ────────────────────────────────────────
        # Combat panel first: it creates btn_show_terrain, which the config panel
        # also lays out (the toggle is available before combat too).
        self._init_combat_panel()
        self._init_config_panel()
        self.scroll_y = 0         # scroll offset for agent list

        # ── Map panning (mouse scroll) ────────────────────────────────────
        self.pan_x = 0            # horizontal pan offset in pixels
        self.pan_y = 0            # vertical pan offset in pixels

        self.clock = pygame.time.Clock()

    # ─────────────────────────────────────────────────────────────────────
    #  Build the static grid / wall / blocked overlay (drawn once)
    # ─────────────────────────────────────────────────────────────────────
    def _build_overlay(self):
        self.overlay.fill((0, 0, 0, 0))
        bm  = self.bm
        s   = self.map_scale          # C++ coords → screen coords
        cpx = int(bm.cell_pixel_size * s)

        # Scale all C++ pixel positions to match the displayed map size.
        raw_h = bm.h_line_positions
        raw_v = bm.v_line_positions
        if not raw_h or not raw_v:
            return
        hlines = [int(y * s) for y in raw_h]
        vlines = [int(x * s) for x in raw_v]

        ox = vlines[0]
        oy = hlines[0]

        # Blocked / wall cells – exact per-cell boundaries from the grid lines.
        for cell in bm.disallowed_cells:
            c, rw = cell.col, cell.row
            if c + 1 >= len(vlines) or rw + 1 >= len(hlines):
                continue
            rx  = vlines[c]
            ry  = hlines[rw]
            rw_ = vlines[c + 1] - rx
            rh_ = hlines[rw + 1] - ry
            pygame.draw.rect(self.overlay, COL_BLOCKED,
                             pygame.Rect(rx, ry, rw_, rh_))

        # Grid lines
        grid_color = (255, 255, 255, 55)
        span_x = vlines[-1] - vlines[0]
        span_y = hlines[-1] - hlines[0]
        for y in hlines:
            pygame.draw.line(self.overlay, grid_color, (ox, y), (ox + span_x, y))
        for x in vlines:
            pygame.draw.line(self.overlay, grid_color, (x, oy), (x, oy + span_y))

        # Edge-based walls (thick red lines between cells) – only when enabled.
        wall_color = (200, 60, 60, 220)
        for w in bm.walls:
            ax = ox + w.a.col * cpx
            ay = oy + w.a.row * cpx
            bx = ox + w.b.col * cpx
            by = oy + w.b.row * cpx
            if w.a.row != w.b.row:                   # horizontal wall (between rows)
                wy = max(ay, by)
                pygame.draw.line(self.overlay, wall_color,
                                 (ax, wy), (ax + cpx, wy), 4)
            else:                                    # vertical wall (between cols)
                wx = max(ax, bx)
                pygame.draw.line(self.overlay, wall_color,
                                 (wx, ay), (wx, ay + cpx), 4)

    # ─────────────────────────────────────────────────────────────────────
    #  Config panel widgets
    # ─────────────────────────────────────────────────────────────────────
    def _panel_x(self):
        return self.screen.get_width() - PANEL_W

    # Layout constants used by both init and reposition
    _PANEL_PAD    = 12   # left/right inset inside panel
    _LABEL_H      = 15   # height reserved for a label line
    _WIDGET_H     = 28   # height of inputs / steppers
    _LABEL_GAP    =  4   # gap between label and its widget
    _ROW_GAP      = 12   # gap between one row's widget and the next row's label
    _BTN_H        = 30   # button height
    _BTN_GAP      =  8   # gap between buttons
    _TITLE_H      = 26   # height of the bold title
    _BROWSE_W     = 34   # width of the "…" browse button

    def _panel_layout(self):
        """Return (px, W, list-of-y-positions) for a fresh layout pass."""
        px = self._panel_x() + self._PANEL_PAD
        W  = PANEL_W - self._PANEL_PAD * 2

        # Row stride = label + gap + widget + row-gap
        RS = self._LABEL_H + self._LABEL_GAP + self._WIDGET_H + self._ROW_GAP

        # y of the INPUT/STEPPER for each row (label sits RS-_WIDGET_H-_ROW_GAP above it)
        title_y  = 10
        row0_y   = title_y + self._TITLE_H + 10           # Mob dropdown
        btn0_y   = row0_y  + self._WIDGET_H + self._ROW_GAP + 8   # Clear All
        btn1_y   = btn0_y  + self._BTN_H + self._BTN_GAP + 4  # Save (half-width)
        # btn2 (Load) is at same y as btn1, right half

        return px, W, title_y, row0_y, btn0_y, btn1_y

    def _init_config_panel(self):
        """Initialize config panel using layout from _panel_layout()."""
        px, W, title_y, r0, b0, b1 = self._panel_layout()
        H   = self._WIDGET_H
        HW  = W // 2 - 2
        B   = self._BTN_H

        self.btn_select_mob = Button(pygame.Rect(px, r0, HW, B), "Select Mob", font=self.font_md)
        self.btn_select_pc = Button(pygame.Rect(px + HW + 4, r0, HW, B), "Select PC",
                                   (80, 100, 140), (110, 130, 170), font=self.font_md)
        self.btn_clear = Button(pygame.Rect(px, b0, W, B), "Clear All",
                               COL_BTN_DANGER, (180, 70, 70), font=self.font_md)
        SW = HW
        self.btn_save = Button(pygame.Rect(px,        b1, SW, B), "Save",
                              (50, 100, 60), (70, 130, 80), font=self.font_md)
        self.btn_load = Button(pygame.Rect(px + SW+4, b1, SW, B), "Load",
                              (50, 75, 120), (70, 100, 155), font=self.font_md)
        imp_y = b1 + B + self._BTN_GAP
        self.btn_import_ddb = Button(pygame.Rect(px, imp_y, W, B), "Import D&D Beyond",
                                     (95, 70, 120), (125, 95, 160), font=self.font_md)
        lr_y = imp_y + B + self._BTN_GAP
        self.btn_long_rest = Button(pygame.Rect(px, lr_y, HW, B), "Long Rest",
                                    (60, 100, 60), (80, 130, 80), font=self.font_md)
        self.btn_short_rest = Button(pygame.Rect(px + HW + 4, lr_y, HW, B), "Short Rest",
                                    (60, 90, 110), (80, 120, 150), font=self.font_md)
        bc_y = lr_y + B + self._BTN_GAP + 8
        self.btn_begin_combat = Button(pygame.Rect(px, bc_y, W, B),
                                      "Begin Combat",
                                      COL_BTN_COMBAT, COL_BTN_COMBAT_HOV, font=self.font_md)
        ter_y = bc_y + B + self._BTN_GAP
        self.btn_edit_terrain = Button(pygame.Rect(px, ter_y, W, B),
                                       "Edit Terrain",
                                       (80, 100, 120), (110, 130, 160), font=self.font_md)
        # btn_show_terrain (created in _init_combat_panel) is laid out here too, in the
        # reserved slot below Edit Terrain; _draw_panel positions/draws it each frame.
        show_ter_y = ter_y + B + self._BTN_GAP
        self.btn_show_terrain.rect.update(px, show_ter_y, W, B)
        # Save / Load Terrain (file pickers — lets terrain be saved before combat and
        # reused across maps/encounters, independent of the agents save).
        save_ter_y = show_ter_y + B + self._BTN_GAP
        self.btn_save_terrain = Button(pygame.Rect(px, save_ter_y, HW, B), "Save Terrain",
                                       (50, 100, 60), (70, 130, 80), font=self.font_md)
        self.btn_load_terrain = Button(pygame.Rect(px + HW + 4, save_ter_y, HW, B), "Load Terrain",
                                       (50, 75, 120), (70, 100, 155), font=self.font_md)
        light_y = save_ter_y + B + self._BTN_GAP
        self.btn_edit_lighting = Button(pygame.Rect(px, light_y, W, B),
                                        "Edit Lighting",
                                        (120, 100, 80), (160, 130, 110), font=self.font_md)
        toggle_light_y = light_y + B + self._BTN_GAP
        self.btn_toggle_lighting = Button(pygame.Rect(px, toggle_light_y, W, B),
                                          "Lighting: OFF",
                                          (80, 80, 120), (110, 110, 160), font=self.font_md)
        toggle_walls_y = toggle_light_y + B + self._BTN_GAP
        self.btn_toggle_walls = Button(pygame.Rect(px, toggle_walls_y, W, B),
                                       "Walls: ON" if self._walls_enabled else "Walls: OFF",
                                       (90, 80, 110), (125, 110, 150), font=self.font_md)
        set_grid_y = toggle_walls_y + B + self._BTN_GAP
        self.btn_set_grid = Button(pygame.Rect(px, set_grid_y, W, B),
                                   "Set Grid…",
                                   (80, 95, 95), (110, 130, 130), font=self.font_md)
        quit_y = set_grid_y + B + self._BTN_GAP
        self.btn_quit = Button(pygame.Rect(px, quit_y, W, B),
                              "Quit",
                              COL_BTN_DANGER, (180, 70, 70), font=self.font_md)

        self.pending_configs: list[rpg.AgentConfig] = []
        self.pending_mob_stats: list[dict | None] = []  # Parallel list of mob stats for each config

    def _reposition_panel(self):
        """Re-anchor all widgets after a window resize."""
        px, W, _, r0, b0, b1 = self._panel_layout()
        SW  = W // 2 - 2

        self.btn_select_mob.rect.update(px, r0, SW, self._WIDGET_H)
        self.btn_select_pc.rect.update(px + SW + 4, r0, SW, self._WIDGET_H)
        self.btn_clear.rect.update(px, b0, W, self._BTN_H)
        self.btn_save.rect.update(px,        b1, SW, self._BTN_H)
        self.btn_load.rect.update(px + SW+4, b1, SW, self._BTN_H)
        imp_y = b1 + self._BTN_H + self._BTN_GAP
        self.btn_import_ddb.rect.update(px, imp_y, W, self._BTN_H)
        lr_y = imp_y + self._BTN_H + self._BTN_GAP
        self.btn_long_rest.rect.update(px, lr_y, SW, self._BTN_H)
        self.btn_short_rest.rect.update(px + SW + 4, lr_y, SW, self._BTN_H)
        bc_y = lr_y + self._BTN_H + self._BTN_GAP + 8
        self.btn_begin_combat.rect.update(px, bc_y, W, self._BTN_H)
        ter_y = bc_y + self._BTN_H + self._BTN_GAP
        self.btn_edit_terrain.rect.update(px, ter_y, W, self._BTN_H)
        show_ter_y = ter_y + self._BTN_H + self._BTN_GAP
        self.btn_show_terrain.rect.update(px, show_ter_y, W, self._BTN_H)
        save_ter_y = show_ter_y + self._BTN_H + self._BTN_GAP
        self.btn_save_terrain.rect.update(px, save_ter_y, SW, self._BTN_H)
        self.btn_load_terrain.rect.update(px + SW + 4, save_ter_y, SW, self._BTN_H)
        light_y = save_ter_y + self._BTN_H + self._BTN_GAP
        self.btn_edit_lighting.rect.update(px, light_y, W, self._BTN_H)
        toggle_light_y = light_y + self._BTN_H + self._BTN_GAP
        self.btn_toggle_lighting.rect.update(px, toggle_light_y, W, self._BTN_H)
        toggle_walls_y = toggle_light_y + self._BTN_H + self._BTN_GAP
        self.btn_toggle_walls.rect.update(px, toggle_walls_y, W, self._BTN_H)
        set_grid_y = toggle_walls_y + self._BTN_H + self._BTN_GAP
        self.btn_set_grid.rect.update(px, set_grid_y, W, self._BTN_H)
        quit_y = set_grid_y + self._BTN_H + self._BTN_GAP
        self.btn_quit.rect.update(px, quit_y, W, self._BTN_H)
        # Update combat panel button x-positions (y is fixed by _draw_combat_panel)
        HW2 = W // 2 - 2
        TW3 = (W - 8) // 3
        self.btn_cbt_atk_action.rect.update( px,           self.btn_cbt_atk_action.rect.y,  HW2, self._BTN_H)
        self.btn_cbt_unarmed.rect.update(    px+HW2+4,     self.btn_cbt_unarmed.rect.y,     HW2, self._BTN_H)
        self.btn_cbt_pass_action.rect.update(px,           self.btn_cbt_pass_action.rect.y, W, self._BTN_H)
        self.btn_cbt_dash.rect.update(       px,           self.btn_cbt_dash.rect.y,       TW3, self._BTN_H)
        self.btn_cbt_dodge.rect.update(      px+TW3+4,     self.btn_cbt_dodge.rect.y,      TW3, self._BTN_H)
        self.btn_cbt_disengage.rect.update(  px+2*(TW3+4), self.btn_cbt_disengage.rect.y,  TW3, self._BTN_H)
        self.btn_cbt_atk_bonus.rect.update(   px,           self.btn_cbt_atk_bonus.rect.y,   TW3, self._BTN_H)
        self.btn_cbt_spell_bonus.rect.update( px+TW3+4,    self.btn_cbt_spell_bonus.rect.y,  TW3, self._BTN_H)
        self.btn_cbt_pass_bonus.rect.update(  px+2*(TW3+4),self.btn_cbt_pass_bonus.rect.y,   TW3, self._BTN_H)
        TW2_shove = (W - 4) // 2
        self.btn_cbt_shove_push.rect.update(  px,           self.btn_cbt_shove_push.rect.y,  TW2_shove, self._BTN_H)
        self.btn_cbt_shove_prone.rect.update( px+TW2_shove+4, self.btn_cbt_shove_prone.rect.y, TW2_shove, self._BTN_H)
        self.btn_cbt_grapple.rect.update(     px,            self.btn_cbt_grapple.rect.y,     TW2_shove, self._BTN_H)
        self.btn_cbt_grapple_esc.rect.update( px+TW2_shove+4, self.btn_cbt_grapple_esc.rect.y, TW2_shove, self._BTN_H)
        self.btn_cbt_spell_action.rect.update(px,          self.btn_cbt_spell_action.rect.y,  W,  self._BTN_H)
        self.btn_cbt_end_turn.rect.update(    px,          self.btn_cbt_end_turn.rect.y,       W,  self._BTN_H)
        self.btn_cbt_end_combat.rect.update(  px,          self.btn_cbt_end_combat.rect.y,     W,  self._BTN_H)

    def _init_combat_panel(self):
        """Create the buttons shown exclusively in the combat panel."""
        px  = self._panel_x() + self._PANEL_PAD
        W   = PANEL_W - self._PANEL_PAD * 2
        HW  = W // 2 - 2
        B   = self._BTN_H

        # Dummy Y (will be set in _draw_combat_panel)
        dummy_y = 0

        self.btn_cbt_atk_action  = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "⚔ Attack",
                                          COL_BTN_ATK, COL_BTN_ATK_HOV, self.font_md)
        self.btn_cbt_unarmed     = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "👊 Unarmed",
                                          COL_BTN_ATK, COL_BTN_ATK_HOV, self.font_md)
        self.btn_cbt_pass_action = Button(pygame.Rect(px+HW+4,  dummy_y, HW, B),
                                          "Pass",
                                          COL_BTN_PASS, COL_BTN_PASS_HOV, self.font_md)
        self.btn_cbt_dash        = Button(pygame.Rect(px,               dummy_y, HW, B),
                                          "Dash",
                                          COL_BTN_DASH, COL_BTN_DASH_HOV, self.font_md)
        self.btn_cbt_dodge       = Button(pygame.Rect(px+HW+4,         dummy_y, HW, B),
                                          "Dodge",
                                          COL_BTN_DODGE, COL_BTN_DODGE_HOV, self.font_md)
        self.btn_cbt_disengage   = Button(pygame.Rect(px,     dummy_y, HW, B),
                                          "Disengage",
                                          COL_BTN_DISENG, COL_BTN_DISENG_HOV, self.font_md)
        self.btn_cbt_hide        = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "Hide",
                                          (150, 150, 150), (180, 180, 180), self.font_md)
        self.btn_cbt_hide_bonus  = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "Hide",
                                          (150, 150, 150), (180, 180, 180), self.font_md)
        self.btn_cbt_dash_bonus  = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "Dash",
                                          COL_BTN_DASH, COL_BTN_DASH_HOV, self.font_md)
        self.btn_cbt_disengage_bonus = Button(pygame.Rect(px,   dummy_y, HW, B),
                                          "Disengage",
                                          COL_BTN_DISENG, COL_BTN_DISENG_HOV, self.font_md)
        self.btn_cbt_patient_defense = Button(pygame.Rect(px,   dummy_y, HW, B),
                                          "Patient Defense",
                                          (180, 150, 200), (210, 180, 230), self.font_md)
        self.btn_cbt_step_of_wind = Button(pygame.Rect(px,   dummy_y, HW, B),
                                          "Step of the Wind",
                                          (160, 180, 200), (190, 210, 230), self.font_md)
        self.btn_cbt_atk_bonus   = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "⚔ Bonus Atk",
                                          COL_BTN_ATK, COL_BTN_ATK_HOV, self.font_md)
        # Nick (weapon mastery): relocate the off-hand attack into the Attack action, freeing the
        # bonus action. Shown after the Attack action when the off-hand weapon has Nick + the agent
        # has Weapon Mastery + the off-hand attack hasn't been spent yet.
        self.btn_cbt_nick        = Button(pygame.Rect(px,       dummy_y, W, B),
                                          "🗡 Nick: Off-hand Atk",
                                          COL_BTN_ATK, COL_BTN_ATK_HOV, self.font_md)
        self.btn_cbt_pass_bonus  = Button(pygame.Rect(px+HW+4,  dummy_y, HW, B),
                                          "Pass",
                                          COL_BTN_PASS, COL_BTN_PASS_HOV, self.font_md)
        self.btn_cbt_shove_push  = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "🔨 Shove (Push)",
                                          (140, 100, 150), (160, 120, 170), self.font_md)
        self.btn_cbt_shove_prone = Button(pygame.Rect(px+HW+4,  dummy_y, HW, B),
                                          "⬇ Shove (Prone)",
                                          (140, 100, 150), (160, 120, 170), self.font_md)
        self.btn_cbt_grapple     = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "✊ Grapple",
                                          (150, 120, 80), (180, 150, 110), self.font_md)
        self.btn_cbt_grapple_esc = Button(pygame.Rect(px+HW+4,  dummy_y, HW, B),
                                          "💨 Escape",
                                          (150, 120, 80), (180, 150, 110), self.font_md)
        # Telekinetic feat — Telekinetic Shove (bonus action, 30 ft, STR save or pushed 5 ft).
        self.btn_cbt_telekinetic = Button(pygame.Rect(px,       dummy_y, W, B),
                                          "🌀 Telekinetic Shove",
                                          (110, 90, 170), (140, 120, 200), self.font_md)
        self.btn_cbt_spell_action= Button(pygame.Rect(px, dummy_y, W, B),
                                          "✨ Cast Spell",
                                          COL_BTN_SPELL, COL_BTN_SPELL_HOV, self.font_md)
        self.btn_cbt_spell_bonus = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "✨ Spell",
                                          COL_BTN_SPELL, COL_BTN_SPELL_HOV, self.font_md)
        self.btn_cbt_charge_arcane_ward = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "🔮 Ward",
                                          (120, 100, 180), (150, 130, 210), self.font_md)
        self.btn_cbt_wild_shape = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "🐺 Wild",
                                          (100, 150, 100), (130, 180, 130), self.font_md)
        self.btn_cbt_long_jump   = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Long Jump",
                                          (100, 150, 200), (120, 170, 220), self.font_md)
        self.btn_cbt_prone       = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "Go Prone",
                                          (180, 100, 100), (220, 140, 140), self.font_md)
        self.btn_cbt_standup     = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "Stand Up",
                                          (150, 180, 100), (180, 220, 130), self.font_md)
        self.btn_cbt_end_turn    = Button(pygame.Rect(px, dummy_y, W, B),
                                          "End Turn",
                                          COL_BTN_ENDTURN, COL_BTN_ENDTURN_HOV, self.font_md)
        self.btn_cbt_place_terrain = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "🌍 Place Terrain",
                                          (150, 120, 80), (180, 150, 110), self.font_md)
        self.btn_cbt_end_combat  = Button(pygame.Rect(px, dummy_y, W, B),
                                          "End Combat",
                                          COL_BTN_DANGER, (180, 70, 70), self.font_md)
        self.btn_cbt_drop_concentration = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Drop Concentration",
                                          (150, 100, 100), (200, 130, 130), self.font_md)
        self.btn_cbt_drop_weapon_main = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Drop Main Hand",
                                          (130, 80, 60), (170, 110, 90), self.font_md)
        self.btn_cbt_drop_weapon_off  = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Drop Off Hand",
                                          (130, 80, 60), (170, 110, 90), self.font_md)
        self.btn_cbt_drop_weapon_rng  = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Drop Ranged",
                                          (130, 80, 60), (170, 110, 90), self.font_md)
        self.btn_cbt_use_portent = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Use Portent Die",
                                          (200, 160, 100), (220, 180, 120), self.font_md)
        self.btn_cbt_rage = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Rage (Bonus)",
                                          (180, 80, 60), (220, 110, 90), self.font_md)
        self.btn_cbt_reckless = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Reckless Attack (Action)",
                                          (200, 100, 80), (240, 130, 110), self.font_md)
        self.btn_cbt_magical_cunning = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Magical Cunning",
                                          (120, 80, 180), (150, 110, 210), self.font_md)
        self.btn_cbt_healing_light = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Healing Light",
                                          (210, 180, 70), (240, 210, 100), self.font_md)
        self.btn_cbt_steady_aim = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Steady Aim",
                                          (90, 140, 190), (120, 170, 220), self.font_md)
        self.btn_cbt_turn_undead = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Turn Undead",
                                          (190, 190, 220), (220, 220, 250), self.font_md)
        self.btn_cbt_radiance = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Radiance of the Dawn",
                                          (230, 200, 90), (255, 225, 120), self.font_md)
        self.btn_cbt_war_priest = Button(pygame.Rect(px, dummy_y, W, B),
                                          "War Priest (Bonus Attack)",
                                          (200, 120, 90), (235, 150, 115), self.font_md)
        self.btn_cbt_martial_arts = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Martial Arts (Bonus Attack)",
                                          (180, 110, 200), (210, 140, 230), self.font_md)
        self.btn_cbt_flurry_of_blows = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Flurry of Blows (2 Attacks)",
                                          (180, 110, 200), (210, 140, 230), self.font_md)
        self.btn_cbt_one_with_shadows = Button(pygame.Rect(px, dummy_y, W, B),
                                          "One with Shadows (Invisible)",
                                          (90, 80, 150), (120, 110, 190), self.font_md)
        self.btn_cbt_second_wind = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Second Wind (Bonus Action)",
                                          (180, 150, 100), (220, 190, 130), self.font_md)
        self.btn_cbt_bm_maneuver = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Maneuver (Bonus Action)",
                                          (150, 120, 90), (190, 160, 120), self.font_md)
        self.btn_cbt_action_surge = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Action Surge",
                                          (220, 140, 90), (255, 170, 120), self.font_md)
        self.btn_cbt_lay_on_hands = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Lay on Hands",
                                          (180, 200, 150), (220, 240, 190), self.font_md)
        self.btn_cbt_grant_inspiration = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Grant Inspiration (Bonus Action)",
                                          (200, 160, 220), (230, 195, 250), self.font_md)
        self.btn_cbt_use_inspiration = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Use Inspiration Die",
                                          (180, 150, 220), (215, 185, 250), self.font_md)
        self.btn_cbt_sacred_weapon = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Sacred Weapon (Bonus Action)",
                                          (200, 180, 110), (240, 220, 150), self.font_md)
        self.btn_cbt_corona = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Corona of Light (Action)",
                                          (235, 215, 120), (255, 240, 160), self.font_md)
        self.btn_cbt_telekinetic = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Telekinetic Movement",
                                          (140, 160, 210), (170, 190, 240), self.font_md)
        self.btn_cbt_dread_ambusher = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Dread Ambusher",
                                          (80, 90, 130), (110, 120, 170), self.font_md)
        self.btn_cbt_tireless = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Tireless (Magic Action)",
                                          (90, 150, 120), (120, 185, 155), self.font_md)
        self.btn_cbt_natures_veil = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Nature's Veil (Bonus Action)",
                                          (70, 120, 90), (100, 155, 120), self.font_md)
        self.btn_cbt_companion = Button(pygame.Rect(px, dummy_y, W, B),
                                          "🐾 Primal Companion",
                                          (90, 140, 90), (120, 175, 120), self.font_md)
        self.btn_show_terrain = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "Show Terrain",
                                          (100, 150, 150), (130, 180, 200), self.font_md)
        dummy_y += B + 5
        self.btn_show_spell_effects = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "Show Spell Effects",
                                          (150, 120, 180), (180, 150, 210), self.font_md)
        dummy_y += B + 5
        self.btn_show_visible_targets = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "Show Visible",
                                          (100, 180, 150), (130, 210, 180), self.font_md)

    # ─────────────────────────────────────────────────────────────────────
    #  Sprite loading (cached)
    # ─────────────────────────────────────────────────────────────────────
    def _get_sprite(self, path: str, size_px: int) -> pygame.Surface | None:
        key = (path, size_px)
        if key not in self.sprites:
            if path and os.path.exists(path):
                try:
                    raw = pygame.image.load(path).convert_alpha()
                    self.sprites[key] = pygame.transform.scale(
                        raw, (size_px, size_px))
                except Exception:
                    self.sprites[key] = None
            else:
                self.sprites[key] = None
        return self.sprites[key]

    def _get_caster_color(self, caster_idx: int) -> tuple[int, int, int]:
        """Generate a distinctive color for a caster based on their agent index."""
        # Use different colors for different casters to visually link them to their targets
        colors = [
            (255, 100, 100),  # Red
            (100, 100, 255),  # Blue
            (100, 255, 100),  # Green
            (255, 255, 100),  # Yellow
            (255, 100, 255),  # Magenta
            (100, 255, 255),  # Cyan
            (255, 200, 100),  # Orange
            (200, 100, 255),  # Purple
        ]
        return colors[caster_idx % len(colors)]

    def _get_mob_sprite_path(self, mob_name: str) -> str:
        """Determine sprite path for a mob: use specific sprite if it exists, otherwise use first letter."""
        specific_path = os.path.join(self.sprites_dir, f"{mob_name}.png")
        if os.path.exists(specific_path):
            return specific_path
        return os.path.join(self.sprites_dir, f"{mob_name[0].upper()}.png")

    def _weapon_from_slot_value(self, val):
        """Build an rpg.Weapon from a bestiary weapon-slot value: a catalog
        name string (resolved via weapons.json) or a synthesized weapon dict.
        Empty/unknown -> a blank rpg.Weapon()."""
        if isinstance(val, dict):
            return _dict_to_weapon(val)
        if isinstance(val, str) and val and val in self.weapon_name_to_dict:
            return _dict_to_weapon(self.weapon_name_to_dict[val])
        return rpg.Weapon()

    @staticmethod
    def _has_real_weapons(weapons) -> bool:
        """True if any slot holds a real weapon. 'Unarmed'/'MonkUnarmed' is the
        default empty-slot sentinel (weapon.hpp), so it counts as no weapon."""
        return any(w.name and w.name not in ("Unarmed", "MonkUnarmed")
                   for w in weapons)

    def _auto_weapons_from_mob_stats(self, mob_record: dict) -> list:
        """Slot-aligned [main_hand, off_hand, ranged] rpg.Weapon list built from
        the bestiary record's pre-synthesized `weapons` dict. Empty slots are
        blank weapons so callers can assign them positionally."""
        wdict = mob_record.get("weapons", {})
        return [self._weapon_from_slot_value(wdict.get(slot, ""))
                for slot in ("main_hand", "off_hand", "ranged")]

    def _size_category_to_grid_size(self, size_category: str) -> int:
        """Convert D&D size category to grid size (cells)."""
        size_map = {
            "Small": 1,
            "Tiny": 1,
            "Medium": 1,
            "Large": 2,
            "Huge": 3,
            "Gargantuan": 4,
        }
        return size_map.get(size_category, 1)

    def _on_mob_selected(self, mob_name: str):
        """Callback when a mob is selected from the dialog."""
        # Load stats from JSON
        if mob_name in self.mob_stats_json:
            self.selected_mob_stats = self.mob_stats_json[mob_name]
            # Set size based on mob size category
            size_category = self.selected_mob_stats.get("size", "Medium")
            self.current_mob_grid_size = self._size_category_to_grid_size(size_category)
        else:
            self.selected_mob_stats = None
            self.current_mob_grid_size = 1

        # Enter placement mode immediately
        cfg = rpg.AgentConfig()
        cfg.name        = mob_name
        cfg.sprite_path = self._get_mob_sprite_path(mob_name)
        cfg.size        = self.current_mob_grid_size
        cfg.start_col   = 0
        cfg.start_row   = 0
        self.placement_mode_active = True
        self.placement_config = cfg
        self.placement_cell = None
        self.placement_valid = False

    def _on_pc_class_selected(self, class_name: str):
        """Callback when a PC class is selected."""
        self.selected_mob_stats = None  # No mob stats for PCs
        self.current_mob_grid_size = 1

        # Setup PC config
        cfg = rpg.AgentConfig()
        cfg.name        = f"{class_name} 1"
        cfg.sprite_path = ""  # PCs don't have sprites initially
        cfg.size        = 1
        cfg.start_col   = 0
        cfg.start_row   = 0

        # Create default PC stats (standard array: 15, 14, 13, 12, 10, 8)
        stats = rpg.Stats()
        stats.str        = 15
        stats.dex        = 14
        stats.con        = 13
        stats.intel      = 12
        stats.wis        = 10
        stats.cha        = 8
        stats.hp_max     = 8  # Will be updated based on class
        stats.hp_cur     = 8
        stats.base_ac    = 10
        stats.speed_walk = 30
        stats.prof_bonus = 2
        stats.num_attacks = 1
        # Set class and level (this also sets can_cast_spell and spell slots)
        stats.set_class_level(getattr(rpg.CharacterClass, class_name), 1)
        # Initialize class resources (Rage, Focus Points, etc.)
        stats.initialize_class_resources(getattr(rpg.CharacterClass, class_name), 1)

        # Store for use in placement handler
        self._pending_pc_class = class_name
        self._pending_pc_stats = stats

        self.placement_mode_active = False
        self.placement_config = cfg
        self.placement_cell = None
        self.placement_valid = False

        # Create TextInput for name editing in the panel
        px, W, _, _, _, _ = self._panel_layout()
        self._pc_name_input = TextInput(pygame.Rect(px, 70, W, 28), placeholder=cfg.name, font=self.font_md)
        self._pc_name_input.text = cfg.name
        self._pc_name_input.active = True

    def _mob_stats_to_d_d_stats(self, mob_record: dict):
        """Build rpg.Stats from an engine-ready bestiary record.

        The record's `stats` block is already in agent_loader.dict_to_stats
        shape (ability scores, speeds, save profs, resist/immune/vuln lists,
        is_npc), so this just loads it and applies the damage multipliers."""
        sd = mob_record.get("stats", {})
        stats = dict_to_stats(sd)
        apply_damage_multipliers(stats, sd)
        # Monsters whose bonus action grants Dash/Disengage (e.g. the Vampire
        # Spawn's "Deathless Agility") reuse the Cunning Action machinery, which
        # is what surfaces the bonus-action Dash/Disengage buttons in the GUI.
        ba = str(mob_record.get("meta", {}).get("bonus_action") or "").lower()
        if "dash" in ba or "disengage" in ba:
            stats.has_cunning_action = True
        return stats

    def _load_npc_spells_from_record(self, agent_idx: int, mob_record: dict):
        """Auto-populate an NPC's innate spells from its bestiary record.

        Mirrors the saved-agent spell-restore path: the record's `spell_indices`
        (canonical catalog names) become Spell objects via spells.json, then
        `npc_spell_groups` ({uses/day: [names]}) sets each spell's uses_max via
        init_npc_spell_groups. No-op for non-casters."""
        spell_names = mob_record.get("spell_indices", [])
        if not spell_names:
            return
        cpp_spells = []
        for spell_name in spell_names:
            idx = self.spell_name_to_idx.get(spell_name)
            if idx is None:
                print(f"WARNING: NPC spell '{spell_name}' not in catalog "
                      f"for {mob_record.get('name', agent_idx)}")
                continue
            spell_dict = self.all_spells[idx]
            self._spell_metadata[(agent_idx, len(cpp_spells))] = {
                "terrain_effect": spell_dict.get("terrain_effect"),
                "hatch_pattern": spell_dict.get("hatch_pattern"),
                "terrain_color": spell_dict.get("terrain_color"),
            }
            cpp_spells.append(self._dict_to_spell(agent_idx, spell_dict))
        self.combat.set_agent_spells(self.bm, agent_idx, cpp_spells)

        npc_spell_groups = mob_record.get("npc_spell_groups", {})
        if npc_spell_groups:
            groups_dict = {int(k): v for k, v in npc_spell_groups.items()}
            self.combat.init_npc_spell_groups(self.bm, agent_idx, groups_dict)
            self._agent_meta[agent_idx] = {
                "is_npc": True, "npc_spell_groups": npc_spell_groups}

    # ─────────────────────────────────────────────────────────────────────
    #  Grid coordinate helpers
    # ─────────────────────────────────────────────────────────────────────
    def _screen_to_cell(self, sx, sy):
        """Convert a screen pixel position to a grid Cell, or None if outside."""
        s     = self.map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        if not raw_v or not raw_h:
            return None
        # Remove pan offset, then unscale back to original image space
        ix = (sx - self.pan_x) / s
        iy = (sy - self.pan_y) / s
        # Binary-search which column/row we're in
        import bisect
        c = bisect.bisect_right(raw_v, ix) - 1
        r = bisect.bisect_right(raw_h, iy) - 1
        if 0 <= c < self.bm.grid_cols and 0 <= r < self.bm.grid_rows:
            return rpg.Cell(c, r)
        return None

    def _cell_to_screen(self, col, row):
        """Return top-left screen pixel of a grid cell."""
        s     = self.map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        return int(raw_v[col] * s + self.pan_x), int(raw_h[row] * s + self.pan_y)

    def _agent_at(self, cell):
        """Return index of the placed agent whose footprint contains cell, or -1."""
        for i, pt in enumerate(self.bm.placed_agents):
            oc, or_ = pt.origin.col, pt.origin.row
            if oc <= cell.col < oc + pt.size and or_ <= cell.row < or_ + pt.size:
                return i
        return -1

    def _can_place(self, cell, size, exclude_idx=-1):
        """Return True if a size×size agent can be placed with top-left at cell.
        Rule lives in helpers.can_place_agent (shared with the summon preview + tests)."""
        return can_place_agent(self.bm, cell, size, exclude_idx)

    # ─────────────────────────────────────────────────────────────────────
    #  Save / Load
    # ─────────────────────────────────────────────────────────────────────
    # ── Save / load callbacks called by the file browser ─────────────────────
    def _set_encounter_base(self, agents_path: str):
        """Point all per-encounter sidecar files at the same base name as the chosen
        agents file, so one map PNG can host many encounters.

        Given '<dir>/<base>_agents.json' (or '<dir>/<base>.json' if the user typed a
        plain name), the sidecars become '<dir>/<base>_terrain.json',
        '<base>_effects.json' and '<base>_lighting.json'.
        """
        self._save_path = agents_path
        d  = os.path.dirname(agents_path)
        fn = os.path.basename(agents_path)
        if fn.endswith("_agents.json"):
            base = fn[:-len("_agents.json")]
        else:
            base = os.path.splitext(fn)[0]
        self._terrain_path  = os.path.join(d, base + "_terrain.json")
        self._effects_path  = os.path.join(d, base + "_effects.json")
        self._lighting_path = os.path.join(d, base + "_lighting.json")

    def _on_save_path_chosen(self, path: str):
        # Capture the previous sidecar locations so lighting/effects (which have no GUI
        # re-serialization path) can be carried forward to the new encounter base.
        old_lighting = self._lighting_path
        old_effects  = self._effects_path
        self._set_encounter_base(path)
        self._save_agents(path)
        self._save_terrain()        # writes self._terrain_path (now at the new base)
        # Lighting & effects travel with the encounter: copy the previous files to the
        # new base if they exist and we aren't overwriting an existing encounter's scene.
        for old, new in ((old_lighting, self._lighting_path),
                         (old_effects,  self._effects_path)):
            if old != new and os.path.exists(old) and not os.path.exists(new):
                try:
                    shutil.copyfile(old, new)
                except Exception as e:
                    print(f"Warning: could not carry forward {os.path.basename(old)}: {e}")

    def _on_load_path_chosen(self, path: str):
        # The Load browser shows every .json, so the user can pick a sidecar
        # (terrain/lighting/effects) by mistake. Those have no "agents" key — refuse
        # them rather than wiping the current scene with an empty agent list.
        try:
            with open(path) as f:
                if "agents" not in json.load(f):
                    self._flash_status(f"Not an encounter file: {os.path.basename(path)}")
                    return
        except Exception as e:
            self._flash_status(f"Could not read {os.path.basename(path)}: {e}")
            return
        self._set_encounter_base(path)
        self._load_agents(path)
        # Re-load the rest of the scene from the new base (terrain resets even if the
        # new encounter has none of these files, so a stale scene doesn't bleed through).
        self._load_terrain()
        self._load_lighting()
        self._load_spell_effects()

    def _flash_status(self, msg: str, secs: float = 2.5):
        """Show a transient confirmation message in the panel for `secs` seconds."""
        self._status_msg = msg
        self._status_msg_until = pygame.time.get_ticks() + int(secs * 1000)

    def _on_save_terrain_chosen(self, path: str):
        """Export the current terrain to a chosen _terrain.json (does not change the
        active encounter base — pure export so terrain can be reused across maps)."""
        self._save_terrain(path)
        self._flash_status(f"Terrain saved: {os.path.basename(path)}")

    def _on_load_terrain_chosen(self, path: str):
        """Import terrain from a chosen _terrain.json into the current scene (it then
        saves with this encounter)."""
        # Load shows every .json, so refuse a non-terrain pick (no "regions" key)
        # rather than clearing the current terrain with an empty region list.
        try:
            with open(path) as f:
                if "regions" not in json.load(f):
                    self._flash_status(f"Not a terrain file: {os.path.basename(path)}")
                    return
        except Exception as e:
            self._flash_status(f"Could not read {os.path.basename(path)}: {e}")
            return
        self._load_terrain(path)
        if self.selected_idx >= 0:
            self._update_reach()
            self._update_attack_overlay()
        self._flash_status(f"Terrain loaded: {os.path.basename(path)}")

    # ─────────────────────────────────────────────────────────────────────
    #  Copy / paste agents (pre-combat encounter building)
    # ─────────────────────────────────────────────────────────────────────
    def _unique_agent_name(self, name: str) -> str:
        """Return a name not already in use, suffixing/incrementing a trailing number.
        e.g. 'Goblin' -> 'Goblin 2', 'Goblin 2' -> 'Goblin 3' (skipping taken names)."""
        existing = {pt.name for pt in self.bm.placed_agents}
        parts = name.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            base, n = parts[0], int(parts[1]) + 1
        else:
            base, n = name, 2
        candidate = f"{base} {n}"
        while candidate in existing:
            n += 1
            candidate = f"{base} {n}"
        return candidate

    def _find_free_cell_near(self, col: int, row: int, size: int):
        """Spiral out from (col,row) for the nearest cell where a size×size agent fits."""
        for radius in range(0, 13):
            for dc in range(-radius, radius + 1):
                for dr in range(-radius, radius + 1):
                    if max(abs(dc), abs(dr)) != radius:
                        continue   # only the ring at this radius
                    c = rpg.Cell(col + dc, row + dr)
                    if self._can_place(c, size):
                        return c
        return None

    def _copy_agent(self, idx: int):
        """Snapshot a placed agent's full loadout to the clipboard (Ctrl+C)."""
        if not (0 <= idx < len(self.bm.placed_agents)):
            self._flash_status("Select an agent first, then Ctrl+C")
            return
        pt = self.bm.placed_agents[idx]
        self._agent_clipboard = {
            "name":       pt.name,
            "sprite":     pt.sprite_path,
            "size":       pt.size,
            "stats":      self.combat.get_agent_stats(self.bm, idx),
            "weapons":    list(self.combat.get_agent_weapons(self.bm, idx)),
            "spells":     list(self.combat.get_agent_spells(self.bm, idx)),
            "armor":      list(self.combat.get_agent_armor(self.bm, idx)),
            "meta":       dict(self._agent_meta.get(idx, {})),
            # Spell rendering metadata for this agent, keyed by spell index.
            "spell_meta": {sp_idx: m for (a_idx, sp_idx), m in self._spell_metadata.items()
                           if a_idx == idx},
        }
        self._flash_status(f"Copied {pt.name} — Ctrl+V to paste")

    def _paste_agent(self, cell):
        """Spawn a clone of the clipboard agent at/near `cell` (pre-combat only)."""
        if self.combat_active:
            return
        if not self._agent_clipboard:
            self._flash_status("Nothing to paste — copy an agent first (Ctrl+C)")
            return
        if cell is None:
            self._flash_status("Hover the map, then Ctrl+V to paste")
            return
        clip = self._agent_clipboard
        dest = self._find_free_cell_near(cell.col, cell.row, clip["size"])
        if dest is None:
            self._flash_status("No free space to paste here")
            return

        # Append a new agent non-destructively (existing agents' state untouched).
        cfg = rpg.AgentConfig()
        cfg.name        = self._unique_agent_name(clip["name"])
        cfg.sprite_path = clip["sprite"]
        cfg.size        = clip["size"]
        cfg.start_col   = dest.col
        cfg.start_row   = dest.row
        new_idx = self.bm.spawn_agent(cfg)
        if new_idx < 0:
            self._flash_status("Paste failed — could not place the copy")
            return

        # Clone the full loadout. The copy is a fresh creature: start at full HP, no
        # temp HP, no carried-over conditions (spawn_agent already gives clean conditions).
        st = clip["stats"]
        st.hp_cur  = st.hp_max
        st.temp_hp = 0
        self.combat.set_agent_stats(self.bm, new_idx, st)
        self.combat.set_agent_weapons(self.bm, new_idx, clip["weapons"])
        self.combat.set_agent_spells(self.bm, new_idx, clip["spells"])
        self.combat.set_agent_armor(self.bm, new_idx, clip["armor"])

        # NPC innate-spell groups, so a copied NPC caster can still cast.
        meta = clip["meta"]
        if meta.get("is_npc") and meta.get("npc_spell_groups"):
            groups = {int(k): v for k, v in meta["npc_spell_groups"].items()}
            self.combat.init_npc_spell_groups(self.bm, new_idx, groups)
            self._agent_meta[new_idx] = {"is_npc": True,
                                         "npc_spell_groups": meta["npc_spell_groups"]}

        # Re-key spell rendering metadata onto the pasted agent.
        for sp_idx, m in clip["spell_meta"].items():
            self._spell_metadata[(new_idx, sp_idx)] = m

        self.sprites.clear()
        self.selected_idx = new_idx
        self._update_reach()
        self._update_attack_overlay()
        self._flash_status(f"Pasted {cfg.name}")

    def _update_reach(self):
        """Recompute walk/fly reachable-cell overlays for the selected agent.

        In combat mode the budget comes from CombatEngine so it shrinks as the
        agent moves.  Outside combat the full stat speed is used.
        """
        self._reach_walk   = []
        self._reach_fly    = []
        self._reach_swim   = []
        self._reach_burrow = []
        self._reach_set    = set()
        idx = self.selected_idx
        if idx < 0 or idx >= len(self.bm.placed_agents):
            return
        pt    = self.bm.placed_agents[idx]
        stats = self.combat.get_agent_stats(self.bm, idx)

        if self.combat_active:
            walk_ft   = self.move_remaining_walk
            fly_ft    = self.move_remaining_fly
            swim_ft   = self.move_remaining_swim
            burrow_ft = self.move_remaining_burrow
        else:
            walk_ft   = stats.speed_walk
            fly_ft    = stats.speed_fly
            swim_ft   = stats.speed_swim
            burrow_ft = stats.speed_burrow

        if walk_ft > 0:
            self._reach_walk = self.bm.reachable_cells(
                pt.origin, pt.size, walk_ft, rpg.MovementType.Walk)
        if fly_ft > 0:
            self._reach_fly = self.bm.reachable_cells(
                pt.origin, pt.size, fly_ft, rpg.MovementType.Fly)
        if swim_ft > 0:
            self._reach_swim = self.bm.reachable_cells(
                pt.origin, pt.size, swim_ft, rpg.MovementType.Swim)
        if burrow_ft > 0:
            self._reach_burrow = self.bm.reachable_cells(
                pt.origin, pt.size, burrow_ft, rpg.MovementType.Burrow)

        # Drag validity uses only the selected movement type's reach.
        _reach_by_type = {
            rpg.MovementType.Walk:   self._reach_walk,
            rpg.MovementType.Fly:    self._reach_fly,
            rpg.MovementType.Swim:   self._reach_swim,
            rpg.MovementType.Burrow: self._reach_burrow,
        }
        self._reach_set = {(c.col, c.row)
                           for c in _reach_by_type.get(self.move_type, [])}

    # Origin feats the GUI can assign (must mirror StatsDialog.ORIGIN_FEATS minus "NONE").
    _ORIGIN_FEATS = {"Alert", "Crafter", "Healer", "Lucky", "Magic Initiate", "Musician",
                     "Savage Attacker", "Skilled", "Tavern Brawler", "Tough"}

    @staticmethod
    def _set_origin_feat(stats, new_feat: str, char_level: int):
        """Set the agent's single origin feat idempotently.

        The dialog re-edits a live Stats whose hp_max/luck_points already include any prior
        feat's one-time bonus (the HP stepper round-trips the boosted value), so changing or
        re-confirming a feat must STRIP the previous origin feat's effects before applying the
        new one. add_feat() (the C++ source of truth) handles the apply; this only handles the
        inverse for the swap. No-op when the feat is unchanged.
        """
        new_feat = new_feat or "NONE"
        prev = next((f for f in list(stats.feats) if f in App._ORIGIN_FEATS), None)
        prev = prev or "NONE"
        if prev == new_feat:
            return  # already applied — leave hp_max/luck_points/initiative_prof as-is

        # Strip the previous origin feat's one-time effects.
        if prev == "Tough":
            stats.hp_max = max(1, stats.hp_max - 2 * char_level)
            stats.hp_cur = max(1, stats.hp_cur - 2 * char_level)
        elif prev == "Alert":
            stats.initiative_prof = False   # only this feat sets it
        elif prev == "Lucky":
            stats.luck_points = 0
            stats.luck_points_max = 0
        stats.feats = [f for f in list(stats.feats) if f not in App._ORIGIN_FEATS]

        # Apply the newly chosen feat via the engine (applies Tough HP / Alert prof / Lucky points).
        if new_feat != "NONE":
            stats.add_feat(new_feat)

    @staticmethod
    def _set_general_feats(stats, names):
        """Set the agent's general feats from the multi-select picker.

        General feats currently carry no one-time stat effects (ASI is not auto-applied —
        edit ability scores via the steppers), so this is a plain replace: drop all general
        feats, then re-add the selected ones. `add_feat` is used so any future general feat
        that gains an addFeat effect still applies on grant. Origin feats are untouched
        (the two name-sets are disjoint).
        """
        names = list(names or [])
        stats.feats = [f for f in list(stats.feats) if f not in GENERAL_FEAT_NAMES]
        for n in names:
            stats.add_feat(n)

    def _on_stats_ok(self, agent_idx: int, steppers: dict, prof_flags: dict, class_name: str = "None", char_level: int = 1, npc_data: dict = None, subclass_name: str = "NONE", eldritch_invocations: list = None, blessed_strike_name: str = "NONE", origin_feat: str = "NONE", general_feats: list = None, elemental_adept_types: list = None, hunter_prey_name: str = "NONE", defensive_tactics_name: str = "NONE"):
        """Called by StatsDialog when the user clicks OK."""
        # Start from current stats so flags not shown in the dialog are preserved.
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        stats.str        = steppers["str"].value
        stats.dex        = steppers["dex"].value
        stats.con        = steppers["con"].value
        stats.intel      = steppers["intel"].value
        stats.wis        = steppers["wis"].value
        stats.cha        = steppers["cha"].value
        stats.hp_cur     = steppers["hp_cur"].value
        stats.hp_max     = steppers["hp_max"].value
        stats.base_ac    = steppers["base_ac"].value
        stats.speed_walk   = steppers["speed_walk"].value
        stats.speed_swim   = steppers["speed_swim"].value
        stats.speed_fly    = steppers["speed_fly"].value
        stats.speed_burrow = steppers["speed_burrow"].value
        stats.prof_bonus   = steppers["prof_bonus"].value
        stats.num_attacks  = steppers["num_attacks"].value
        # Saving throw proficiency per ability
        stats.save_prof_str   = prof_flags.get("save_prof_str",   False)
        stats.save_prof_dex   = prof_flags.get("save_prof_dex",   False)
        stats.save_prof_con   = prof_flags.get("save_prof_con",   False)
        stats.save_prof_intel = prof_flags.get("save_prof_intel", False)
        stats.save_prof_wis   = prof_flags.get("save_prof_wis",   False)
        stats.save_prof_cha   = prof_flags.get("save_prof_cha",   False)

        # Set class and level; this updates spell_slots_max and can_cast_spell automatically
        stats.set_class_level(getattr(rpg.CharacterClass, class_name), char_level)
        # Restore remaining slots to max (they're newly set)
        stats.spell_slots_remaining = list(stats.spell_slots_max)

        # Set subclass BEFORE initializing resources (resource init may check subclass)
        if class_name == "Barbarian" and subclass_name != "NONE":
            stats.barbarian_subclass = getattr(rpg.BarbianSubclass, subclass_name)
        elif class_name == "Fighter" and subclass_name != "NONE":
            stats.fighter_subclass = getattr(rpg.FighterSubclass, subclass_name)
        elif class_name == "Druid" and subclass_name != "NONE":
            stats.druid_circle = getattr(rpg.DruidCircle, subclass_name)
        elif class_name == "Monk" and subclass_name != "NONE":
            stats.monk_subclass = getattr(rpg.MonkSubclass, subclass_name)
        elif class_name == "Paladin" and subclass_name != "NONE":
            stats.paladin_oath = getattr(rpg.PaladinOath, subclass_name)
        elif class_name == "Wizard" and subclass_name != "NONE":
            stats.wizard_subclass = getattr(rpg.WizardSubclass, subclass_name)
        elif class_name == "Warlock" and subclass_name != "NONE":
            stats.warlock_subclass = getattr(rpg.WarlockSubclass, subclass_name)
        elif class_name == "Rogue" and subclass_name != "NONE":
            stats.rogue_subclass = getattr(rpg.RogueSubclass, subclass_name)
        elif class_name == "Cleric" and subclass_name != "NONE":
            stats.cleric_subclass = getattr(rpg.ClericSubclass, subclass_name)
        elif class_name == "Bard" and subclass_name != "NONE":
            stats.bard_subclass = getattr(rpg.BardCollege, subclass_name)
        elif class_name == "Sorcerer" and subclass_name != "NONE":
            stats.sorcerer_subclass = getattr(rpg.SorcererSubclass, subclass_name)
        elif class_name == "Ranger" and subclass_name != "NONE":
            stats.ranger_subclass = getattr(rpg.RangerSubclass, subclass_name)
            # Hunter L3 Hunter's Prey / L7 Defensive Tactics: honor the in-dialog picker if it set a
            # choice; otherwise default it the first time (preserved across later edits since stats
            # start from the current agent). The StatsDialog picker passes the chosen enum names.
            if subclass_name == "Hunter":
                if hunter_prey_name not in (None, "NONE"):
                    stats.hunter_prey = getattr(rpg.HunterPrey, hunter_prey_name)
                elif stats.hunter_prey == rpg.HunterPrey.NONE:
                    stats.hunter_prey = rpg.HunterPrey.ColossusSlayer
                if defensive_tactics_name not in (None, "NONE"):
                    stats.defensive_tactics = getattr(rpg.DefensiveTactics, defensive_tactics_name)
                elif char_level >= 7 and stats.defensive_tactics == rpg.DefensiveTactics.NONE:
                    stats.defensive_tactics = rpg.DefensiveTactics.EscapeTheHorde
            # Beast Master L3 Primal Companion: default the form to Land when first set;
            # the player picks Land/Sea/Sky each time via the in-combat companion menu.
            if subclass_name == "BeastMaster" and stats.primal_companion == rpg.PrimalCompanion.NONE:
                stats.primal_companion = rpg.PrimalCompanion.Land

        # Cleric Blessed Strikes choice (L7+)
        if class_name == "Cleric" and blessed_strike_name != "NONE":
            stats.blessed_strike = getattr(rpg.BlessedStrike, blessed_strike_name)

        # Set Warlock invocations
        if class_name == "Warlock" and eldritch_invocations:
            stats.eldritch_invocations = list(eldritch_invocations)

        # Initialize class resources (Rage, Focus Points, Portent Dice, etc.)
        # This must come AFTER setting subclass since resource creation checks subclass
        stats.initialize_class_resources(getattr(rpg.CharacterClass, class_name), char_level)

        # Origin feat (one per PC). Applied after stats/level/prof_bonus are set so Tough HP,
        # Alert initiative proficiency, and Lucky points compute from the final values.
        self._set_origin_feat(stats, origin_feat, char_level)
        # General feats (multi-select). Disjoint from origin feats; no ASI auto-apply.
        self._set_general_feats(stats, general_feats)
        # Elemental Adept's chosen element(s) (set via the element picker). Kept only while the feat
        # is selected; cleared otherwise so a deselect doesn't leave stale types.
        stats.elemental_adept_types = list(elemental_adept_types or []) if stats.has_feat("Elemental Adept") else []

        self.combat.set_agent_stats(self.bm, agent_idx, stats)

        # For Monks, replace default "Unarmed" weapon with "MonkUnarmed" (1d8)
        if class_name == "Monk":
            current_weapons = list(self.combat.get_agent_weapons(self.bm, agent_idx))
            # Replace the first weapon (default) with MonkUnarmed if it's named "Unarmed"
            if current_weapons and current_weapons[0].name == "Unarmed":
                current_weapons[0] = self._create_monk_unarmed_weapon()
                self.combat.set_agent_weapons(self.bm, agent_idx, current_weapons)

        # Master of Myriad Forms (invocation 12): give the Warlock Alter Self claws
        # (1d6) in place of a bare unarmed strike.
        if class_name == "Warlock" and 12 in (eldritch_invocations or []):
            current_weapons = list(self.combat.get_agent_weapons(self.bm, agent_idx))
            if current_weapons and current_weapons[0].name == "Unarmed":
                current_weapons[0] = self._create_alter_self_claws_weapon()
                self.combat.set_agent_weapons(self.bm, agent_idx, current_weapons)

        # Pact of the Blade (invocation 13): conjure the pact weapon into the MAIN-HAND slot (0).
        # Weapons are a fixed 3-slot array (main/off/ranged); the pact weapon is the Warlock's
        # primary armament, so it always takes the main hand. pact_weapon=True drives the CHA
        # attack/damage + the pact-weapon rider gates.
        if class_name == "Warlock" and 13 in (eldritch_invocations or []):
            current_weapons = list(self.combat.get_agent_weapons(self.bm, agent_idx))
            if current_weapons and current_weapons[0].name != "PactBlade":
                current_weapons[0] = self._create_pact_blade_weapon()
                self.combat.set_agent_weapons(self.bm, agent_idx, current_weapons)

        # Store NPC metadata if provided, and initialize spell uses via C++
        if npc_data:
            self._agent_meta[agent_idx] = npc_data
            # Initialize spell uses_max/uses_remaining in C++ from npc_spell_groups
            npc_spell_groups = npc_data.get("npc_spell_groups", {})
            if npc_spell_groups:
                groups_dict = {int(k): v for k, v in npc_spell_groups.items()}
                self.combat.init_npc_spell_groups(self.bm, agent_idx, groups_dict)
        elif agent_idx in self._agent_meta:
            del self._agent_meta[agent_idx]

        # Always-prepared class features (Divine Spark, Radiance of the Dawn, domain spells) follow
        # from class/level/subclass — re-grant onto the agent's current spells so they show up
        # without needing to reopen the spell picker.
        cpp_spells = list(self.combat.get_agent_spells(self.bm, agent_idx))
        self._grant_class_features(agent_idx, cpp_spells)
        self.combat.set_agent_spells(self.bm, agent_idx, cpp_spells)

        if agent_idx == self.selected_idx:
            self._update_reach()

    # ── Weapon callbacks & overlays ───────────────────────────────────────────

    def _on_weapon_done(self, agent_idx: int, weapons: list[dict]):
        """Called by WeaponDialog when the user clicks Done.

        `weapons` is a list of plain dicts (the WeaponDialog's internal format).
        Convert each to an rpg.Weapon and push the list into the C++ layer.
        """
        cpp_weapons = [_dict_to_weapon(d) for d in weapons]
        self.combat.set_agent_weapons(self.bm, agent_idx, cpp_weapons)
        # Update has_offhand_attack based on whether any weapon is off-hand
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        stats.has_offhand_attack = any(d.get("off_hand", False) for d in weapons)
        self.combat.set_agent_stats(self.bm, agent_idx, stats)
        # Refresh attack overlay if this is the currently selected agent.
        if agent_idx == self.selected_idx:
            self._update_attack_overlay()

    def _update_attack_overlay(self):
        """Recompute attack-range overlays for the selected agent's weapons."""
        self._attack_cells_melee = []
        self._attack_cells_rnorm = []
        self._attack_cells_rlong = []
        idx = self.selected_idx
        if idx < 0 or idx >= len(self.bm.placed_agents):
            return
        weapons = self.combat.get_agent_weapons(self.bm, idx)   # list[rpg.Weapon] from C++
        if not weapons:
            return
        pt = self.bm.placed_agents[idx]
        melee_cells:  set[tuple[int, int]] = set()
        rnorm_cells:  set[tuple[int, int]] = set()
        rlongx_cells: set[tuple[int, int]] = set()  # long-range-only

        for w in weapons:
            if w.type == rpg.WeaponType.Melee:
                for c in self.bm.attack_target_cells(
                        pt.origin, pt.size, w.reach_ft):
                    melee_cells.add((c.col, c.row))
            else:  # Ranged
                for c in self.bm.attack_target_cells(
                        pt.origin, pt.size, w.normal_range_ft):
                    rnorm_cells.add((c.col, c.row))
                for c in self.bm.attack_target_cells(
                        pt.origin, pt.size, w.long_range_ft):
                    if (c.col, c.row) not in rnorm_cells:
                        rlongx_cells.add((c.col, c.row))

        # Convert back to Cell-like objects (just store as (col,row) dicts
        # to avoid depending on rpg.Cell construction in a hot path).
        def _as_cells(s):
            return [rpg.Cell(c, r) for c, r in s]

        self._attack_cells_melee = _as_cells(melee_cells)
        self._attack_cells_rnorm = _as_cells(rnorm_cells)
        self._attack_cells_rlong = _as_cells(rlongx_cells)

    # ─────────────────────────────────────────────────────────────────────
    #  Combat widget helpers
    # ─────────────────────────────────────────────────────────────────────

    def _current_agent_idx(self) -> int:
        """Return the BattleMap index of the currently acting combatant, or -1."""
        if not self.combat_active or not self.initiative_order:
            return -1
        return self.initiative_order[self.turn_idx].agent_idx

    def _reset_movement(self, agent_idx: int):
        """Seed this turn's movement budgets from the agent's stats."""
        if 0 <= agent_idx < len(self.bm.placed_agents):
            stats  = self.combat.get_agent_stats(self.bm, agent_idx)
            cond   = self.combat.get_agent_conditions(self.bm, agent_idx)
            agent  = self.bm.placed_agents[agent_idx]
            walk   = stats.speed_walk
            fly    = stats.speed_fly
            swim   = stats.speed_swim
            burrow = stats.speed_burrow
            # Pass base speeds to init_movement; C++ getWalkRemaining() applies exhaustion penalty
            agent.init_movement(walk, fly, swim, burrow)
            # Update UI with exhaustion-adjusted remaining movement
            exhaustion_reduction = 5 * cond.exhaustion_level
            self.move_remaining_walk   = max(0, walk - exhaustion_reduction)
            self.move_remaining_fly    = max(0, fly - exhaustion_reduction)
            self.move_remaining_swim   = max(0, swim - exhaustion_reduction)
            self.move_remaining_burrow = max(0, burrow - exhaustion_reduction)
            if cond.exhaustion_level > 0:
                print(f"[_reset_movement] Agent {agent.name}: exhaustion_level={cond.exhaustion_level} (−{exhaustion_reduction}ft)")
                print(f"  walk: {walk} → {self.move_remaining_walk}, fly: {fly} → {self.move_remaining_fly}, swim: {swim} → {self.move_remaining_swim}, burrow: {burrow} → {self.move_remaining_burrow}")
            else:
                print(f"[_reset_movement] Agent {agent.name}: exhaustion_level=0, walk={walk}, fly={fly}, swim={swim}, burrow={burrow}")
        else:
            self.move_remaining_walk   = 0
            self.move_remaining_fly    = 0
            self.move_remaining_swim   = 0
            self.move_remaining_burrow = 0
        # Default to Walk; fall back to first available type if walk speed is 0.
        if self.move_remaining_walk > 0:
            self.move_type = rpg.MovementType.Walk
        elif self.move_remaining_fly > 0:
            self.move_type = rpg.MovementType.Fly
        elif self.move_remaining_swim > 0:
            self.move_type = rpg.MovementType.Swim
        else:
            self.move_type = rpg.MovementType.Burrow
        self.last_movement_dist = 0
        self.jump_overlay_active = False
        self.jump_reachable_cells = set()

    def _toggle_jump_overlay(self):
        """Toggle the jump overlay visibility and recalculate if needed."""
        if self.jump_overlay_active:
            self.jump_overlay_active = False
            self.jump_reachable_cells = []
        else:
            self._update_jump_reachable()
            self.jump_overlay_active = True

    def _update_jump_reachable(self):
        """Calculate cells reachable by long jump from current agent."""
        self.jump_reachable_cells = []
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)):
            return

        agent = self.bm.placed_agents[idx]
        stats = self.combat.get_agent_stats(self.bm, idx)
        strength = stats.str

        if strength <= 0:
            return

        # Determine if running or standing jump (based on most recent movement).
        # Reach is the Strength SCORE in feet (running) or half (standing).
        is_running_jump = self.last_movement_dist >= 10
        max_jump_ft = strength if is_running_jump else (strength // 2)

        # Otherworldly Leap (invocation 10): Jump spell always active → triple distance.
        if stats.character_class == rpg.CharacterClass.Warlock and stats.has_invocation(10):
            max_jump_ft *= 3

        # Convert feet → whole 5-ft squares, rounding UP (matches the engine's jump_agent), so
        # Str 8 → 8 ft → 2 squares (10 ft). Manhattan distance below is measured in squares.
        max_jump_cells = (max_jump_ft + 4) // 5

        # Calculate reachable cells (Manhattan distance from current position).
        # Jumping clears Chasm/Water but is blocked by walls, so exclude wall cells
        # (MovementType.Jump); the engine's jump_agent enforces the same on execution.
        origin = agent.origin
        size = agent.size
        cols, rows = self.bm.grid_cols, self.bm.grid_rows
        for dr in range(-max_jump_cells, max_jump_cells + 1):
            for dc in range(-max_jump_cells, max_jump_cells + 1):
                manhattan_dist = abs(dc) + abs(dr)
                if manhattan_dist == 0:
                    continue  # Can't jump to current cell
                if manhattan_dist > max_jump_cells:
                    continue

                tc, tr = origin.col + dc, origin.row + dr
                if not (0 <= tc < cols and 0 <= tr < rows):
                    continue
                target_cell = rpg.Cell(tc, tr)
                if self.bm.is_blocked(target_cell, size, rpg.MovementType.Jump):
                    continue  # landing cell is a wall — not a valid jump target
                self.jump_reachable_cells.append(target_cell)

    def _execute_jump(self, agent_idx: int, target_cell):
        """Execute a jump to the target cell, deducting movement."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return

        # Refresh agent reference to ensure we have current position
        agent = self.bm.placed_agents[agent_idx]
        stats = self.combat.get_agent_stats(self.bm, agent_idx)

        # FLAG: Move to C++
        # Calculate jump distance for logging (from current position to target)
        jump_dist = (abs(target_cell.col - agent.origin.col) +
                     abs(target_cell.row - agent.origin.row)) * 5

        # Determine if running or standing jump based on most recent movement
        is_running = self.last_movement_dist >= 10

        # A jump may only be made while the bonus action is available (house rule: jumping
        # costs a Bonus Action in addition to movement).
        if self.bonus_used:
            self._combat_log_add(f"{agent.name}: Cannot jump — Bonus Action already used.")
            return

        # Execute jump (C++ handles all movement-budget deductions)
        if self.combat.jump_agent(self.bm, agent_idx, target_cell, is_running):
            self._flush_combat_log()  # Flush any spell effect damage messages
            # Update remaining movement values
            ag = self.bm.placed_agents[agent_idx]
            self.move_remaining_walk = ag.walk_remaining
            self.move_remaining_fly = ag.fly_remaining
            self.move_remaining_swim = ag.swim_remaining
            self.move_remaining_burrow = ag.burrow_remaining
            self.last_movement_dist = 0  # Reset run-up after jump
            self.bonus_used = True       # jumping spends the Bonus Action
            jump_type = "running" if is_running else "standing"
            self._combat_log_add(f"{agent.name}: {jump_type.capitalize()} long jump (+{jump_dist}ft, Bonus Action)")
            self._update_reach()
            # The bonus action is spent — close the jump overlay (no second jump this turn).
            self.jump_overlay_active = False
            self.jump_reachable_cells = []
        else:
            # Jump failed - out of range or insufficient movement. Report the ceiling'd cap in
            # feet (Strength score → squares, rounded up) to match the engine's range check.
            strength = stats.str
            max_ft = strength if is_running else (strength // 2)
            max_cells = (max_ft + 4) // 5
            self._combat_log_add(f"{agent.name}: Jump out of range ({jump_dist}ft > {max_cells * 5}ft max)")

    def _start_combat(self):
        """Roll initiative and enter combat mode."""
        if not self.bm.placed_agents:
            return
        order = list(self.combat.roll_initiative(self.bm))
        if not order:
            return
        # Superior Inspiration (Bard L18+): top up Bardic Inspiration to 2 at combat start.
        # RNG-free, so it doesn't perturb the dice stream; applied before recording begins
        # (replay.py mirrors this) so checked replays stay in sync.
        self.combat.apply_superior_inspiration(self.bm)
        self.initiative_order    = order
        self.combat_active       = True
        self.safe_target_edit_idx = -1  # exit any safe-target editing when combat starts
        self.turn_idx            = 0
        self.round_num           = 0
        self.action_used          = False
        self.bonus_used           = False
        self.pending_attack_slot       = ""
        self.attacks_remaining         = 0
        self.pending_cleave            = None
        self.pending_sweep             = None
        self.pending_rally             = None
        self.pending_feint             = None
        self.pending_spell_slot        = ""
        self.pending_spell_is_aoe      = False
        self.pending_spell_num_targets = 0
        self.pending_spell_targets     = []
        self.pending_shove_slot        = ""
        self.pending_shove_type        = ""
        self.pending_grapple_slot      = ""
        self.pending_unarmed_type      = ""
        self.combat_log                = []
        # Initialize combat log file
        self._combat_log_file = "combat_log.txt"
        # Initialize replay log file. Header carries the seed; the RecordingCombat
        # wrapper then appends one JSON event per engine call (with a state snapshot)
        # for deterministic checked replay (see replay.py / replay_record.py).
        self.replay_log_file = "replay_log.txt"
        with open(self.replay_log_file, "w") as f:
            f.write(f"=== COMBAT REPLAY LOG ===\n")
            f.write(f"Checked replay:  python3 replay.py <map_image> [replay_log.txt]\n")
            f.write(f"\nSEED: {self.combat_seed}\n")
            f.write(f"INITIATIVE: {[(self.bm.placed_agents[e.agent_idx].name, e.total) for e in order]}\n")
            f.write(f"\n=== EVENTS (JSON) ===\n")
        # Begin recording every engine mutation through the wrapper.
        self.combat.start_recording(self.replay_log_file, self.bm)
        with open(self._combat_log_file, "w") as f:
            f.write("=== COMBAT LOG ===\n")
            f.write(f"Seed: {self.combat_seed}\n")
        self._effect_meta         = {}
        self.bm.clear_terrain_effects()
        # Apply armor multipliers for all agents at combat start
        for i in range(len(self.bm.placed_agents)):
            self.combat.apply_armor_multipliers(self.bm, i)
        first = self._current_agent_idx()
        self.selected_idx = first
        self._reset_movement(first)
        self._update_reach()
        self._update_attack_overlay()
        print(f"[COMBAT START] Initiative order: {[(e.total, self.bm.placed_agents[e.agent_idx].name) for e in order]}")
        print(f"[COMBAT START] First turn: agent_idx={first}, name={self.bm.placed_agents[first].name if 0 <= first < len(self.bm.placed_agents) else '?'}")

    def _end_combat(self):
        """Leave combat mode and clear all combat state."""
        self.move_remaining_walk   = 0
        self.move_remaining_fly    = 0
        self.move_remaining_swim   = 0
        self.move_remaining_burrow = 0
        self.move_type             = rpg.MovementType.Walk
        self.combat_active         = False
        self.initiative_order    = []
        self.turn_idx            = 0
        self.round_num           = 0
        self.action_used          = False
        self.bonus_used           = False
        self.pending_attack_slot       = ""
        self.attacks_remaining         = 0
        self.pending_cleave            = None
        self.pending_sweep             = None
        self.pending_rally             = None
        self.pending_feint             = None
        self.pending_spell_slot        = ""
        self.pending_spell_is_aoe      = False
        self.pending_spell_num_targets = 0
        self.pending_spell_targets     = []
        self.pending_shove_slot        = ""
        self.pending_shove_type        = ""
        self.pending_grapple_slot      = ""
        self.pending_unarmed_type      = ""
        self.selected_idx              = -1
        self._reach_walk         = []
        self._reach_fly          = []
        self._reach_set          = set()
        self._effect_meta         = {}
        self._spell_metadata      = {}
        self.combat.clear_all_concentration(self.bm)  # drop lingering concentration on all agents
        self.combat.stop_recording()                  # finish the replay event log
        self.bm.clear_terrain_effects()
        self.bm.clear_spell_effects()
        self._attack_cells_melee = []
        self._attack_cells_rnorm = []
        self._attack_cells_rlong = []

    def _advance_turn(self):
        """Advance to the next living combatant in initiative order."""
        if not self.initiative_order:
            return
        n = len(self.initiative_order)
        prev_turn_idx = self.turn_idx
        prev_idx = self._current_agent_idx()

        # FLAG: Move to C++
        # Find next living agent (skip only if actually dead, not just unconscious at 0 HP)
        for _ in range(n):
            self.turn_idx = (self.turn_idx + 1) % n
            idx = self._current_agent_idx()
            if 0 <= idx < len(self.bm.placed_agents):
                # Tombstoned summons (dismissed on concentration loss) never take a turn.
                if self.bm.is_agent_removed_from_play(idx):
                    continue
                stats = self.combat.get_agent_stats(self.bm, idx)
                cond = self.combat.get_agent_conditions(self.bm, idx)
                # Skip only if dead; unconscious agents at 0 HP still get a turn for death saves
                if stats.hp_cur > 0 or (stats.hp_cur <= 0 and not cond.dead):
                    break
                else:
                    # Agent is dead, drop concentration if any
                    self._drop_concentration_for_agent(idx)

        # FLAG: Move to C++
        # Round advancement: when turn_idx wraps to 0
        if self.turn_idx < prev_turn_idx:
            self.round_num += 1
            # Tick DM-placed effects at round boundary
            expired_dm = self.bm.tick_dm_terrain_effects()
            for effect_id in expired_dm:
                if effect_id in self._effect_meta:
                    effect_name = self._effect_meta[effect_id].get("name", "Effect")
                    self._combat_log_add(f"{effect_name} fades.")
                    del self._effect_meta[effect_id]

        # End previous agent's turn
        if prev_idx >= 0:
            prev_name = self.bm.placed_agents[prev_idx].name if prev_idx < len(self.bm.placed_agents) else "Unknown"
            self._combat_log_add(f"[END TURN] {prev_name}")
            self.combat.end_turn(self.bm, prev_idx)

        # Reset action economy and per-turn conditions for the new combatant.
        self.action_used           = False
        self.bonus_used            = False
        self.pending_attack_slot       = ""
        self.attacks_remaining         = 0
        self._attack_sequence_slot     = ""
        self.pending_spell_slot        = ""
        self.pending_spell_is_aoe      = False
        self.pending_spell_num_targets = 0
        self.pending_spell_targets     = []
        self.pending_shove_slot        = ""
        self.pending_shove_type        = ""
        self.pending_grapple_slot      = ""
        self.pending_unarmed_type      = ""
        self.arcane_charge_pending     = False
        self._reaction_mover_idx       = -1

        # Begin new agent's turn (conditions reset + movement seed now happen in C++). The turn start
        # opens the OnTurnStartNearby reaction window (Branches of the Tree) via the
        # flow-checkpoint API; the rest of the turn-start work runs in _finish_turn_start once any
        # reactions resolve (parked windows resume through _submit_reaction → _reaction_finish).
        new_idx = self._current_agent_idx()
        self.selected_idx = new_idx
        if new_idx < 0:
            self._update_reach()
            self._update_attack_overlay()
            return
        self._turn_start_idx  = new_idx
        self._reaction_finish = self._finish_turn_start
        status = self.combat.begin_turn_flow(self.bm, new_idx, True)
        self._flush_combat_log()
        if status == rpg.FlowStatus.AwaitingDecision and self.combat.pending_decision().active:
            self._show_pending_reaction_menu()   # _submit_reaction → _finish_turn_start on completion
            return
        self._finish_turn_start()

    def _finish_turn_start(self):
        """Continuation of _advance_turn after the OnTurnStartNearby reaction window closes
        (begin_turn_flow). Reads the stored TurnStartResult and runs the rest of the turn-start work."""
        new_idx = self._turn_start_idx
        if new_idx < 0 or new_idx >= len(self.bm.placed_agents):
            self._update_reach()
            self._update_attack_overlay()
            return
        turn_result = self.combat.last_turn_start_result()

        # Tick conditions cast by this agent (duration counted in this agent's turns, not absolute turns)
        self.combat.tick_agent_conditions_for_caster(self.bm, new_idx)

        # Log any save rolls (e.g., paralyzed escape attempt)
        if turn_result.save_roll_message:
            self._combat_log_add(f"{self.bm.placed_agents[new_idx].name}: {turn_result.save_roll_message}")

        # If turn was skipped (e.g., paralyzed save failed), advance to next turn
        if turn_result.turn_skipped:
            self._advance_turn()
            return

        # Initialize Python-side movement tracking (C++ also seeds in beginTurn)
        self._reset_movement(new_idx)

        # Tick this agent's terrain in C++ (also clears concentration if a concentration terrain expired)
        tick = self.combat.tick_terrain_for_turn(self.bm, new_idx)
        for effect_id in tick.expired_terrain_ids:
            if effect_id in self._effect_meta:
                effect_name = self._effect_meta[effect_id].get("name", "Effect")
                self._combat_log_add(f"{effect_name} fades.")
                del self._effect_meta[effect_id]
        if tick.concentration.dropped:
            self._sync_spell_effect_cache()
            conc_name = self.bm.placed_agents[new_idx].name
            self._combat_log_add(f"{conc_name}'s {tick.concentration.spell_name or 'spell'} effect expired.")

        self._update_reach()
        self._update_attack_overlay()

    def _drop_concentration(self):
        """Drop concentration for the current agent (game logic in C++)."""
        self._drop_concentration_for_agent(self._current_agent_idx())

    def _drop_concentration_for_agent(self, agent_idx: int):
        """Drop concentration for an agent. Terrain/effect/condition removal lives in
        C++ drop_concentration; Python only refreshes the render cache and logs."""
        res = self.combat.drop_concentration(self.bm, agent_idx)
        if res.dropped:
            self._sync_spell_effect_cache()  # render cache only
            name = self.bm.placed_agents[agent_idx].name
            self._combat_log_add(f"{name} drops concentration on {res.spell_name or 'spell'}.")
            # Summons created by this caster were tombstoned (removed_from_play) in C++.
            # They stay in placedAgents_ to keep indices valid; we just log + un-render them.
            for s_idx in res.dismissed_summons:
                if 0 <= s_idx < len(self.bm.placed_agents):
                    self._combat_log_add(f"{self.bm.placed_agents[s_idx].name} vanishes.")


    def _combat_log_add(self, msg: str):
        self.combat_log.insert(0, msg)
        if len(self.combat_log) > 10:
            self.combat_log.pop()
        # Print to console
        print(msg)
        # Write to combat log file
        try:
            if not hasattr(self, '_combat_log_file'):
                self._combat_log_file = "combat_log.txt"
            with open(self._combat_log_file, "a") as f:
                f.write(msg + "\n")
        except Exception:
            pass  # Silently fail on file write errors

    def _flush_combat_log(self):
        """Flush messages from the combat engine logger into the combat log."""
        for msg in self.logger.flush():
            self._combat_log_add(msg)

    # FLAG: Move to C++
    def _drop_weapon(self, slot_idx: int):
        """Drop the equipped weapon in slot_idx onto the current agent's cell."""
        cur_idx = self._current_agent_idx()
        if cur_idx < 0:
            return
        weapons = list(self.combat.get_agent_weapons(self.bm, cur_idx))
        weapon = weapons[slot_idx]
        if not weapon.name or weapon.name == "Unnamed":
            return
        # Get sprite_path from weapons.json if available
        wdict = self.weapon_name_to_dict.get(weapon.name, {})
        sprite_path = wdict.get("sprite_path", "")
        # Place item at agent's current cell
        agent = self.bm.placed_agents[cur_idx]
        import traceback
        print(f"[_drop_weapon] Dropping {weapon.name} from slot {slot_idx} for agent {agent.name} at ({agent.origin.col},{agent.origin.row})")
        print(f"[_drop_weapon] Call stack:")
        for line in traceback.format_stack()[:-1]:
            print(f"  {line.strip()}")
        item_id = self.bm.place_item(agent.origin, weapon, sprite_path)
        # Clear the weapon slot
        weapons[slot_idx] = rpg.Weapon()
        self.combat.set_agent_weapons(self.bm, cur_idx, weapons)
        self._combat_log_add(f"{agent.name} drops {weapon.name}.")

    # FLAG: Move to C++
    def _show_item_pickup_menu(self, cell, items, agent_idx, pos):
        """Show context menu to pick up one of the items at this cell."""
        menu_items = []
        for item in items:
            def _pickup(i=item, a=agent_idx):
                self._pickup_item(i, a)
            menu_items.append((f"Pick up {item.weapon.name}", _pickup))
        if menu_items:
            self.context_menu.show(pos, menu_items, self.screen.get_size())

    # FLAG: Move to C++
    def _pickup_item(self, item, agent_idx: int):
        """Assign item weapon to agent slot and remove item from map."""
        weapons = list(self.combat.get_agent_weapons(self.bm, agent_idx))
        agent = self.bm.placed_agents[agent_idx]

        slot = self._find_pickup_slot(item.weapon, weapons)
        if slot == -1:
            self._combat_log_add(f"{agent.name}: no free weapon slot for {item.weapon.name}.")
            return

        weapons[slot] = item.weapon
        self.combat.set_agent_weapons(self.bm, agent_idx, weapons)
        self.bm.remove_item(item.id)
        self._combat_log_add(f"{agent.name} picks up {item.weapon.name}.")

    def _find_pickup_slot(self, weapon, weapons) -> int:
        """Auto-assign weapon to best available slot. Returns -1 if no slot free."""
        EMPTY = lambda w: not w.name or w.name == "Unnamed"
        # Ranged weapon → prefer ranged slot (index 2) if empty
        if weapon.type == rpg.WeaponType.Ranged and EMPTY(weapons[2]):
            return 2
        # Main hand empty → slot 0
        if EMPTY(weapons[0]):
            return 0
        # Off-hand empty → slot 1
        if EMPTY(weapons[1]):
            return 1
        # Ranged slot empty as last resort for melee
        if EMPTY(weapons[2]):
            return 2
        return -1   # all slots full

    def _open_team_picker(self):
        """Open the modal team picker listing every placed agent. Clicking a row cycles
        its team; on dismiss the chosen factions are written back to the engine."""
        agents = self.bm.placed_agents
        rows = [(i, pt.name, self.bm.get_agent_faction(i)) for i, pt in enumerate(agents)]
        if not rows:
            self._combat_log_add("No agents placed to assign to teams.")
            return

        def _commit(assign: dict):
            for idx, fac in assign.items():
                self.bm.set_agent_faction(int(idx), int(fac))
            self._combat_log_add("Teams updated.")

        self.team_dialog.show(_commit, rows)

    def _show_visible_targets_popup(self):
        """Debug popup showing visible targets for the selected agent."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._combat_log_add("No agent selected!")
            return

        agents = self.bm.placed_agents
        if idx >= len(agents):
            return

        # Compute visibility for this agent
        self.combat.compute_visibility(self.bm, idx)

        # Build popup text (header + each line annotated with the agent's team)
        selected_agent = agents[idx].name
        caster_team = faction_name(self.bm.get_agent_faction(idx))
        visibility_info = f"Visible targets for {selected_agent} ({caster_team} team):\n"

        visible_count = 0
        for target_idx, agent in enumerate(agents):
            if target_idx == idx:
                continue  # Skip self

            vis_level = self.combat.get_visibility(idx, target_idx)
            if vis_level != rpg.VisibilityLevel.Blocked:
                visible_count += 1
                vis_name = {
                    rpg.VisibilityLevel.Clear: "Clear",
                    rpg.VisibilityLevel.Dim: "Dim",
                    rpg.VisibilityLevel.LightlyObscured: "Lightly Obscured",
                    rpg.VisibilityLevel.Dark: "Dark",
                    rpg.VisibilityLevel.MagicalDark: "Magical Darkness",
                    rpg.VisibilityLevel.Blocked: "Blocked",
                    rpg.VisibilityLevel.Sunlight: "Sunlight"
                }.get(vis_level, "Unknown")
                tgt_team = faction_name(self.bm.get_agent_faction(target_idx))
                visibility_info += f"  • {agent.name} ({vis_name}, {tgt_team} team)\n"

        if visible_count == 0:
            visibility_info += "  (no visible targets)"

        self._combat_log_add(visibility_info)

    # FLAG: Move to C++
    def _activate_reckless_and_attack(self, idx: int, slot: str):
        """Set Reckless Attack flag and proceed with attack."""
        cond = self.combat.get_agent_conditions(self.bm, idx)
        cond.reckless_attack = True
        self.combat.set_agent_conditions(self.bm, idx, cond)
        self.combat.log_event("reckless", idx=idx)  # record for checked replay
        agent = self.bm.placed_agents[idx]
        self._combat_log_add(f"{agent.name}: Activates Reckless Attack (enemies gain advantage)")
        # Continue with weapon selection
        self._start_attack(slot)

    def _continue_attack_sequence_after_rider(self, atk_idx: int):
        """After a rider effect (Stunning Strike, etc.) is applied, check if more attacks remain
        and either re-prompt or end the attack sequence. Called from rider callbacks."""
        # Determine if more attacks remain. Key on the DURABLE _attack_sequence_slot (not the
        # transient pending_attack_slot, which _finish_attack disarms centrally so the player can
        # move between attacks — see the "central disarm" note there).
        seq_slot = self._attack_sequence_slot
        has_more_attacks = False
        if seq_slot == "bonus":
            stats = self.combat.get_agent_stats(self.bm, atk_idx)
            has_more_attacks = stats.bonus_attacks_remaining > 0
        elif seq_slot == "action":
            has_more_attacks = self.attacks_remaining > 0

        if has_more_attacks:
            atk_name = self.bm.placed_agents[atk_idx].name
            if seq_slot == "bonus":
                # Bonus multi-attack (Flurry, etc.): single target — keep auto-targeting (unchanged).
                stats = self.combat.get_agent_stats(self.bm, atk_idx)
                rem = stats.bonus_attacks_remaining
                self.pending_attack_slot = ""  # Clear to let _start_attack re-seed
                self._start_attack(self._attack_sequence_slot)
                self._combat_log_add(
                    f"{atk_name}: {rem} attack{'s' if rem != 1 else ''} remaining — click a target.")
            else:
                # Action Extra-Attack sequence: DISARM between attacks so the player can move; the
                # standing "⚔ Attack (N)" button resumes (count preserved, no re-seed). Mirrors the
                # non-rider path in _finish_attack.
                rem = self.attacks_remaining
                self.pending_attack_slot = ""
                self._combat_log_add(
                    f"{atk_name}: {rem} attack{'s' if rem != 1 else ''} remaining — "
                    f"move if you wish, then click Attack to continue.")
        else:
            # Attacks exhausted
            self.pending_attack_slot = ""
            self._attack_sequence_slot = ""
            self.pending_attack_offhand = None
            self.pending_attack_resource = None

        self._update_attack_overlay()

    def _start_attack(self, slot: str):
        """Begin target-selection for an attack in the given slot."""
        idx = self._current_agent_idx()
        if idx < 0:
            return
        weapons = self.combat.get_agent_weapons(self.bm, idx)
        if not weapons:
            self._combat_log_add("No weapons equipped!")
            if slot == "action":
                self.action_used = True
            else:
                self.bonus_used = True
            return

        stats = self.combat.get_agent_stats(self.bm, idx)
        conds = self.combat.get_agent_conditions(self.bm, idx)

        # Reckless Attack prompt for Barbarians
        if (stats.character_class == rpg.CharacterClass.Barbarian and
            conds.raging and not conds.reckless_attack):
            def _proceed_normal():
                self._start_attack(slot)
            options = [
                ("Use Reckless Attack", lambda: self._activate_reckless_and_attack(idx, slot)),
                ("Normal Attack", _proceed_normal)
            ]
            px_popup = self._panel_x() + self._PANEL_PAD
            self.context_menu.show((px_popup, 290), options, self.screen.get_size())
            return

        # Only seed attacks_remaining when starting a fresh sequence (== 0).
        # If mid-sequence and same slot, don't reset. If mid-sequence and different slot, reject.
        if self.attacks_remaining == 0:
            # Fresh start
            if slot == "action":
                self.attacks_remaining = stats.num_attacks
                # War Magic gates once per Attack action; a fresh Attack action (including the
                # second one granted by Action Surge) re-enables the substitution.
                if conds.war_magic_used:
                    conds.war_magic_used = False
                    self.combat.set_agent_conditions(self.bm, idx, conds)
            else:
                # Bonus slot: check C++ bonus_attacks_remaining (Flurry, Martial Arts, etc.)
                self.attacks_remaining = stats.bonus_attacks_remaining if stats.bonus_attacks_remaining > 0 else 1
            self._attack_sequence_slot = slot
            # A normal attack uses default (slot-derived) proficiency and no resource cost.
            self.pending_attack_offhand = None
            self.pending_attack_resource = None
        elif slot != self._attack_sequence_slot:
            # Can't start a different slot while attacks are pending
            return
        # print(f"[DEBUG _start_attack] idx={idx} slot={slot} stats.num_attacks={stats.num_attacks} n_atk={n_atk} attacks_remaining={self.attacks_remaining}")

        def _activate(s, wi_):
            self.pending_attack_slot = s
            self.pending_weapon_idx  = wi_
            rem = self.attacks_remaining
            suffix = f" ({rem} attack{'s' if rem != 1 else ''} remaining)"
            self._combat_log_add(f"Click a target on the map.{suffix}")

        # FLAG: Move to C++
        # Filter weapons for bonus attacks: only show off-hand weapons
        weapons_to_use = weapons
        if slot == "bonus":
            offhand_weapons = [w for w in weapons if w.off_hand]
            if offhand_weapons:
                weapons_to_use = offhand_weapons

        # Eldritch Knight War Magic (L7+): during the Attack action, one attack may be replaced by
        # casting a spell. Offer it only when the engine gate is open AND there is an eligible spell.
        war_magic_option = None
        if (slot == "action" and self.combat.can_use_war_magic(self.bm, idx)
                and self.combat.available_war_magic_spells(self.bm, idx)):
            def _pick_war_magic():
                self.pending_attack_slot = ""   # leave attack-target mode; enter spell-target mode
                self.pending_weapon_idx  = 0
                self._start_cast_spell("war_magic")
            war_magic_option = ("War Magic: cast spell (replaces an attack)", _pick_war_magic)

        if len(weapons_to_use) == 1 and war_magic_option is None:
            # Auto-select if only one weapon (or one off-hand weapon for bonus)
            wi = next((i for i, w in enumerate(weapons) if w == weapons_to_use[0]), 0)
            _activate(slot, wi)
        else:
            options = []
            for w in weapons_to_use:
                wi = next((i for i, weapon in enumerate(weapons) if weapon == w), 0)
                def _pick(s=slot, wi_=wi):
                    _activate(s, wi_)
                options.append((w.name, _pick))
            if war_magic_option is not None:
                options.append(war_magic_option)
            px_popup = self._panel_x() + self._PANEL_PAD
            self.context_menu.show(
                (px_popup, 290),
                options,
                self.screen.get_size()
            )

    def _damage_breakdown_str(self, result) -> str:
        """Return ' [4 (weapon) + 3 (rage)]' when a hit has multiple damage sources, else ''."""
        bd = getattr(result, "damage_breakdown", None)
        if not bd or len(bd) <= 1:
            return ""
        return " [" + " + ".join(f"{amt} ({label})" for label, amt in bd) + "]"

    def _start_extra_attack(self, weapon_idx=0, offhand=False, resource=None, label="Extra attack",
                            slot="bonus"):
        """Generic 'make one extra weapon attack' setup — reused by War Priest, Great Weapon Master,
        Nick, etc. Configures the pending-attack knobs and enters target selection; the shared
        target-click → _resolve_combat_attack does the attack and spends `resource` (if any).

        slot="bonus" consumes the bonus action (most callers); slot="action" adds the attack to the
        Attack action without touching the bonus action (Nick's off-hand relocation)."""
        idx = self._current_agent_idx()
        if idx < 0:
            return
        self._attack_sequence_slot = slot
        # Only set attacks_remaining if not already set (e.g., by Flurry of Blows which queues multiple)
        if self.attacks_remaining == 0:
            if slot == "bonus":
                stats = self.combat.get_agent_stats(self.bm, idx)
                self.attacks_remaining = stats.bonus_attacks_remaining if stats.bonus_attacks_remaining > 0 else 1
            else:
                self.attacks_remaining = 1   # a single extra Attack-action attack (Nick)
        self.pending_attack_slot = slot
        self.pending_weapon_idx = weapon_idx
        self.pending_attack_offhand = offhand     # proficient (not an off-hand strike) when False
        self.pending_attack_resource = resource   # spent on a valid attack (e.g. "War Priest")
        self._combat_log_add(f"{label} — click a target.")

    def _offhand_bonus_available(self, idx: int) -> bool:
        """Can this agent make an off-hand attack as a Bonus Action right now?

        The single Light-property off-hand extra attack lands in the bonus action by default. Once
        it's been spent (e.g. relocated into the Attack action via Nick, or already taken in the
        bonus), only the Dual Wielder feat grants a second bonus-action off-hand attack."""
        if idx < 0 or idx >= len(self.bm.placed_agents):
            return False
        weapons = self.combat.get_agent_weapons(self.bm, idx)
        if not any(w.off_hand for w in weapons):
            return False
        conds = self.combat.get_agent_conditions(self.bm, idx)
        if not conds.offhand_attack_used:
            return True
        return self.combat.get_agent_stats(self.bm, idx).has_feat("Dual Wielder")

    def _nick_offhand_idx(self, idx: int) -> int:
        """Weapon-array index of an off-hand weapon whose Nick mastery can relocate the off-hand
        attack into the Attack action right now (agent has the Weapon Mastery feature and the
        off-hand extra attack hasn't been spent), else -1."""
        if idx < 0 or idx >= len(self.bm.placed_agents):
            return -1
        # The Weapon Master general feat grants access to a weapon's Mastery property to anyone, so
        # it satisfies the same gate as the martials' auto-granted "Weapon Mastery" feature.
        st = self.combat.get_agent_stats(self.bm, idx)
        if not (st.has_feat("Weapon Mastery") or st.has_feat("Weapon Master")):
            return -1
        if self.combat.get_agent_conditions(self.bm, idx).offhand_attack_used:
            return -1
        weapons = self.combat.get_agent_weapons(self.bm, idx)
        for i, w in enumerate(weapons):
            if w.off_hand and w.mastery == rpg.WeaponMastery.Nick:
                return i
        return -1

    def _mark_offhand_attack_used(self, idx: int):
        """Mark the single per-turn off-hand extra attack as spent on agent `idx`."""
        if idx < 0 or idx >= len(self.bm.placed_agents):
            return
        conds = self.combat.get_agent_conditions(self.bm, idx)
        conds.offhand_attack_used = True
        self.combat.set_agent_conditions(self.bm, idx, conds)

    def _are_allies(self, a_idx: int, b_idx: int) -> bool:
        """GUI mirror of the engine's areAllies: same NON-zero faction. Neutral (0)
        is its own faction, allied with no one."""
        if a_idx == b_idx:
            return True
        n = len(self.bm.placed_agents)
        if not (0 <= a_idx < n and 0 <= b_idx < n):
            return False
        fa = self.bm.get_agent_faction(a_idx)
        fb = self.bm.get_agent_faction(b_idx)
        return fa != 0 and fa == fb

    def _pending_spell_is_harm(self) -> bool:
        """True if the spell currently being aimed is a Harm spell (so a friendly-fire
        confirm is warranted). Heal/Transport spells return False — healing an ally
        must never prompt."""
        ci = self._current_agent_idx()
        if ci < 0:
            return False
        spells = self.combat.get_agent_spells(self.bm, ci)
        if not (0 <= self.pending_spell_idx < len(spells)):
            return False
        return spells[self.pending_spell_idx].type == rpg.SpellType.Harm

    def _confirm_friendly_harm(self, target_idx: int, on_confirm) -> None:
        """Faction rule 4: if the acting agent and target_idx are on the same team,
        ask the player to confirm before a harmful action (e.g. accidentally clicking
        a teammate). Non-allies (or no current actor) run on_confirm() immediately."""
        actor = self._current_agent_idx()
        if actor < 0 or not self._are_allies(actor, target_idx):
            on_confirm()
            return
        tgt_name = self.bm.placed_agents[target_idx].name
        options = [
            (f"Harm ally {tgt_name}!", on_confirm),
            ("Cancel", lambda: None),
        ]
        px, py = self._agent_screen_pos(target_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _resolve_combat_attack(self, target_idx: int):
        """Resolve the pending attack against target_idx.

        Routes through begin_attack (not execute_action) so the target can cast Shield (+5 AC) as a
        reaction before any damage (the OnHit window). begin_attack rolls the
        attack, then either parks at the Shield checkpoint (AwaitingDecision) or resolves immediately
        (Completed). _finish_attack runs the post-resolution rider chain + logging in both cases,
        reading the result from last_attack_result()."""
        atk_idx = self._current_agent_idx()
        slot    = self.pending_attack_slot
        if atk_idx < 0 or not slot:
            return
        action = rpg.Attack(atk_idx, target_idx, self.pending_weapon_idx)
        action.is_offhand = (slot == "bonus") if self.pending_attack_offhand is None else self.pending_attack_offhand
        action.attack_slot = slot  # Pass the slot type to C++ ("action" or "bonus")

        # Stash what _finish_attack needs (the self.pending_* attrs stay set across the suspend) and
        # arm it as the reaction continuation, then begin the attack.
        self._attack_post = dict(atk_idx=atk_idx, target_idx=target_idx, slot=slot, action=action)
        self._reaction_finish = self._finish_attack

        status = self.combat.begin_attack(self.bm, action)
        self._flush_combat_log()
        if status == rpg.FlowStatus.AwaitingDecision:
            self._show_pending_reaction_menu()   # target's Shield menu; _submit_reaction → _finish_attack
        else:
            self._finish_attack()

    def _finish_attack(self):
        """Post-resolution of a begin_attack flow (immediate or after the OnHit Shield window). Reads
        the AttackResult from last_attack_result() and runs the attacker rider-offer chain + logging."""
        ctx        = self._attack_post
        atk_idx    = ctx["atk_idx"]
        target_idx = ctx["target_idx"]
        slot       = ctx["slot"]
        action     = ctx["action"]
        result     = self.combat.last_attack_result()

        # Generic extra-attack cost (War Priest, etc.): spend the resource once, only on a valid attack.
        if result.valid and self.pending_attack_resource:
            self.combat.spend_resource(self.bm, atk_idx, self.pending_attack_resource)
            self.pending_attack_resource = None

        # Spend the single per-turn off-hand extra attack when this strike used the off-hand weapon
        # (base bonus off-hand, Nick relocation, or Dual Wielder's bonus). Once spent, the base
        # bonus off-hand attack is no longer offered — only Dual Wielder grants a second one.
        if result.valid:
            weapons = self.combat.get_agent_weapons(self.bm, atk_idx)
            wi = action.weapon_idx
            if 0 <= wi < len(weapons) and weapons[wi].off_hand:
                self._mark_offhand_attack_used(atk_idx)

        self._flush_combat_log()

        agents   = self.bm.placed_agents
        atk_name = agents[atk_idx].name if atk_idx < len(agents) else "?"
        tgt_name = agents[target_idx].name if target_idx < len(agents) else "?"

        # FLAG: Move to C++
        if not result.valid:
            # Check if attack failed because agent slipped
            if atk_idx >= 0 and atk_idx < len(agents) and agents[atk_idx].conditions.slipped_this_turn:
                self._combat_log_add(f"{atk_name} slipped and cannot act — turn ends.")
                self.pending_attack_slot = ""
                self.attacks_remaining   = 0
                self._advance_turn()
            else:
                # Out of range / invalid target: this is a misclick, NOT a spent attack. Do not
                # decrement (the decrement is below this return) and — critically — do not zero
                # attacks_remaining. _start_attack re-seeds the count only when it is 0, so zeroing
                # here would let the next Attack click re-seed to num_attacks and hand out a bonus
                # attack (e.g. after a Forceful Blow / Push knocks the target out of reach mid-
                # sequence). Just clear pending_attack_slot so the player can reposition (drag-to-
                # move); clicking Attack again resumes the SAME sequence with the remaining count.
                rem = self.attacks_remaining
                tail = (f" ({rem} attack{'s' if rem != 1 else ''} remaining)" if rem > 0 else "")
                self._combat_log_add(
                    f"{atk_name}: out of range — move closer or click Attack to retry{tail}")
                # ── DEBUG: why was this attack invalid? Surface the weapon + geometry so a
                # ranged ("out of range") rejection can be diagnosed live (range vs LoS).
                try:
                    if 0 <= atk_idx < len(agents) and 0 <= target_idx < len(agents):
                        wi = action.weapon_idx
                        wlist = self.combat.get_agent_weapons(self.bm, atk_idx)
                        w = wlist[wi] if 0 <= wi < len(wlist) else None
                        ao = agents[atk_idx].origin; asz = agents[atk_idx].size
                        to = agents[target_idx].origin; tsz = agents[target_idx].size
                        dist_cells = max(abs(ao.col - to.col), abs(ao.row - to.row))
                        los = self.bm.has_line_of_sight(ao, asz, to, tsz)
                        if w is not None:
                            wtype = "Ranged" if w.type == rpg.WeaponType.Ranged else "Melee"
                            reach = w.long_range_ft if w.type == rpg.WeaponType.Ranged else w.reach_ft
                            self._combat_log_add(
                                f"  [debug] weapon slot {wi}='{w.name}' type={wtype} "
                                f"reach/range={reach}ft (reach_ft={w.reach_ft}, "
                                f"normal={w.normal_range_ft}, long={w.long_range_ft})")
                        self._combat_log_add(
                            f"  [debug] dist={dist_cells} cells ({dist_cells*5}ft), "
                            f"LoS={los}, target={tgt_name}")
                except Exception as _e:
                    self._combat_log_add(f"  [debug] (diagnostics failed: {_e})")
                self.pending_attack_slot = ""
            return

        # Check if attacker has exhaustion for potential penalty note
        # FLAG: Move to C++
        atk_cond = self.combat.get_agent_conditions(self.bm, atk_idx) if 0 <= atk_idx < len(agents) else None
        exh_note = ""
        if atk_cond and atk_cond.exhaustion_level >= 1:
            penalty = 2 * atk_cond.exhaustion_level
            exh_note = f" [−{penalty} exhaustion]"

        # FLAG: Move to C++
        # Check for a post-hit rider menu (Cunning Strike or Brutal Strike) before logging.
        has_brutal_strike = False
        has_cunning_strike = False
        has_divine_strike = False
        has_guided_strike = False
        has_push = False
        has_topple = False
        has_cleave = False
        has_stunning_strike = False
        has_open_hand_rider = False
        has_maneuver = False
        has_precision = False
        has_psionic_strike = False
        has_punch_and_grab = False
        has_divine_smite = False
        has_eldritch_smite = False
        has_reckless_reroll = False
        has_riposte = False
        has_protective_field = False
        has_interception = False
        has_sentinel_guard = False
        has_gwm_hew = False
        has_sudden_strike = False
        if result.valid:
            atk_cond = self.combat.get_agent_conditions(self.bm, atk_idx)
            # Riposte is a DEFENDER reaction: the flag is set on the target, not the attacker.
            tgt_cond = self.combat.get_agent_conditions(self.bm, target_idx) if 0 <= target_idx < len(agents) else None
            if result.hit and atk_cond and atk_cond.cunning_strike_available:
                has_cunning_strike = True
            elif result.hit and atk_cond and atk_cond.brutal_strike_available:
                has_brutal_strike = True
            elif result.hit and atk_cond and atk_cond.stunning_strike_available and self.pending_attack_slot == "action":
                has_stunning_strike = True
            elif result.hit and atk_cond and atk_cond.open_hand_rider_available:
                has_open_hand_rider = True
            elif result.hit and atk_cond and atk_cond.divine_strike_available:
                has_divine_strike = True
            elif result.hit and atk_cond and atk_cond.psionic_strike_available:
                has_psionic_strike = True
            elif result.hit and atk_cond and atk_cond.grappler_punch_grab_available:
                has_punch_and_grab = True
            elif result.hit and atk_cond and atk_cond.divine_smite_available:
                has_divine_smite = True
            elif result.hit and atk_cond and atk_cond.eldritch_smite_available:
                has_eldritch_smite = True
            elif result.hit and atk_cond and atk_cond.maneuver_available:
                has_maneuver = True
            elif (not result.hit) and atk_cond and atk_cond.guided_strike_available:
                has_guided_strike = True
            elif (not result.hit) and atk_cond and atk_cond.maneuver_precision_available:
                has_precision = True
            elif (not result.hit) and atk_cond and atk_cond.reckless_reroll_available:
                has_reckless_reroll = True
            # Riposte is offered LAST among on-miss options (v1): an attacker on-miss rider above
            # shadows the defender's riposte this swing (see known_limitations.md; full chaining is v2).
            elif (not result.hit) and tgt_cond and tgt_cond.riposte_available:
                has_riposte = True
            elif result.hit and atk_cond and atk_cond.push_available:
                has_push = True
            elif result.hit and atk_cond and atk_cond.topple_available:
                has_topple = True
            elif result.hit and atk_cond and atk_cond.cleave_available:
                has_cleave = True
            # Protective Field is a DEFENDER on-hit reaction (the flag-less mechanic re-validates in
            # C++). Offered LAST among on-hit options (v1): an attacker on-hit rider above shadows the
            # defender's Protective Field this swing (see known_limitations.md). Mirrors riposte's
            # on-miss shadowing.
            elif self._can_protective_field(target_idx, result):
                has_protective_field = True
            # Interception is a BYSTANDER on-hit damage-reduction reaction: an ally within 5 ft of the
            # target spends its reaction to reduce the damage by 1d10 + PB (post-hit heal-back). Offered
            # among the on-hit reductions; the full eligibility scan lives in C++ (can_intercept).
            elif (result.hit and result.total_damage > 0 and not result.target_down
                  and self._find_interceptor(action, target_idx, result) >= 0):
                has_interception = True
            # Sentinel Guardian is a BYSTANDER reaction (a third creature near the attacker), fired on a
            # hit OR a miss. Flagged on the attacker; offered LAST among the v1 single-rider chain (an
            # attacker's own rider shadows it this swing — see known_limitations.md).
            elif atk_cond and atk_cond.sentinel_guard_available:
                has_sentinel_guard = True
            # Great Weapon Master — Hew: a melee crit/kill with a Heavy weapon offers one bonus-action
            # attack (only when the bonus action is still free). Offered last; uses the shared
            # extra-attack flow. Distinct economy from the on-hit riders above (it spends the bonus action).
            elif (atk_cond and atk_cond.gwm_hew_available and not self.bonus_used
                  and self._attack_sequence_slot != "bonus"):
                has_gwm_hew = True
            # Stalker's Flurry — Sudden Strike (Gloom Stalker L11): a Dreadful Strike hit grants one
            # FREE extra weapon attack (no action/bonus cost). Flagged on the attacker by the engine
            # when the Dreadful Strike rider fires; offered last (an attacker's own rider shadows it
            # this swing, like GWM Hew). Mass Fear (the alternative) is deferred — see known_limitations.
            elif atk_cond and atk_cond.sudden_strike_available:
                has_sudden_strike = True

        # FLAG: Move to C++
        # Format attack message
        if result.hit:
            dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            atk_msg = (f"{atk_name}→{tgt_name}: "
                       f"HIT {result.total_damage}{self._damage_breakdown_str(result)} {dmg_type_str}"
                       f"{' CRIT!' if result.critical else ''}"
                       f"{' — DOWN' if result.target_down else ''}"
                       f"{exh_note}")
        else:
            atk_msg = (f"{atk_name}→{tgt_name}: "
                       f"miss (roll {result.total_roll} vs AC {result.target_ac})"
                       f"{exh_note}")

        # Decrement attack counter: action attacks use Python attacks_remaining,
        # bonus-action attacks use C++ bonus_attacks_remaining
        has_more_attacks = False
        if self.pending_attack_slot == "bonus":
            has_more_attacks = self.combat.consume_bonus_attack(self.bm, atk_idx)
        elif self.pending_attack_slot == "action":
            self.attacks_remaining -= 1
            has_more_attacks = self.attacks_remaining > 0

        # Central disarm for the ACTION sequence: clear pending_attack_slot NOW, before any rider
        # menu, so the map leaves target-selection between attacks regardless of which rider (if any)
        # fires. Without this, the many on-hit riders that don't re-prompt (brutal/cunning/divine/
        # push/topple/…) left the map armed → clicking your own sprite resolved as a self-attack
        # ("out of range"). The standing "⚔ Attack (N)" button resumes the sequence; the count is
        # preserved. Bonus sequences keep their own armed auto-target flow (single target). The
        # rider continuations and the no-rider block below key on _attack_sequence_slot, not this
        # field, so the early clear is safe. Also commit the Action here (and end the sequence when
        # the last attack is spent) so it happens even for the many riders that skip the no-rider
        # block — otherwise a rider on the LAST attack would leave action_used False + a stale
        # _attack_sequence_slot, and the next Attack click would re-seed a fresh full set of attacks.
        # action_used True mid-sequence is fine: mid_sequence_action keeps the "⚔ Attack (N)" button
        # alive (and the handler lets it fire). Frenzy / unarmed-weapon restore stay in the no-rider
        # block (rider-laden actions skip them — a pre-existing edge, see known_limitations.md).
        if self._attack_sequence_slot == "action":
            self.pending_attack_slot = ""
            self.action_used = True
            if not has_more_attacks:
                self._attack_sequence_slot = ""
                self.pending_attack_offhand = None
                self.pending_attack_resource = None

        # FLAG: Move to C++
        # Defer logging until the rider effect is chosen; otherwise log immediately.
        if has_cunning_strike:
            self._offer_cunning_strike(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_stunning_strike:
            self._offer_stunning_strike(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_open_hand_rider:
            self._offer_open_hand_rider(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_brutal_strike:
            self._offer_brutal_strike(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_divine_strike:
            self._offer_divine_strike(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_psionic_strike:
            self._offer_psionic_strike(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_punch_and_grab:
            self._offer_punch_and_grab(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_divine_smite:
            self._offer_divine_smite(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_eldritch_smite:
            self._offer_eldritch_smite(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_guided_strike:
            self._offer_guided_strike(action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_maneuver:
            self._offer_maneuver(action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_precision:
            self._offer_precision_attack(action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_reckless_reroll:
            self._offer_reckless_reroll(action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_riposte:
            self._offer_riposte(action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_protective_field:
            self._offer_protective_field(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_interception:
            self._offer_interception(action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_sentinel_guard:
            self._offer_sentinel_guard(action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_push:
            self._offer_push(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_topple:
            self._offer_topple(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, action.weapon_idx)
        elif has_cleave:
            self._offer_cleave(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, action.weapon_idx)
        elif has_gwm_hew:
            self._offer_gwm_hew(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, action.weapon_idx)
        elif has_sudden_strike:
            self._offer_sudden_strike(atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, action.weapon_idx)
        else:
            self._combat_log_add(atk_msg)

        # Concentration on weapon damage is rolled inside execute_action (C++ owns the CON save and,
        # on a failure, fully drops the spell's terrain/effects/conditions). Surface the log + sync caches.
        if result.hit and result.total_damage > 0:
            self._flush_combat_log()
            self._sync_spell_effect_cache()

        # FLAG: Move to C++
        # If target is down, drop their concentration
        if result.target_down:
            self._drop_concentration_for_agent(target_idx)

        # Only run this re-prompt logic if NO rider was offered. If a rider was offered,
        # the rider callback will handle re-prompting via _continue_attack_sequence_after_rider().
        has_rider = has_cunning_strike or has_stunning_strike or has_open_hand_rider or has_brutal_strike or has_divine_strike or has_psionic_strike or has_guided_strike or has_push or has_topple or has_cleave or has_reckless_reroll or has_protective_field or has_interception or has_gwm_hew or has_sudden_strike
        if not has_rider:
            # Check if more attacks are queued (action or bonus)
            if has_more_attacks:
                # More attacks left in this sequence.
                if self._attack_sequence_slot == "bonus":
                    # Bonus multi-attack (e.g. Flurry of Blows): single target, no standing
                    # mid-sequence button, so keep auto-targeting the next strike (unchanged).
                    stats = self.combat.get_agent_stats(self.bm, atk_idx)
                    rem = stats.bonus_attacks_remaining
                    self.pending_attack_slot = ""  # Clear to let _start_attack re-seed
                    self._start_attack("bonus")
                    self._combat_log_add(
                        f"{atk_name}: {rem} attack{'s' if rem != 1 else ''} remaining — click a target.")
                else:
                    # Action Extra-Attack sequence: DISARM target-selection between attacks so the
                    # player can move (clicking your own sprite no longer reads as a self-attack).
                    # The standing "⚔ Attack (N)" button (mid_sequence_action) resumes the sequence;
                    # the count is preserved, so re-clicking does NOT re-seed to a fresh full set
                    # (see _start_attack's `attacks_remaining == 0` guard). Requested by the user as
                    # the general fix for "allow movement mid-attack-sequence".
                    rem = self.attacks_remaining
                    self.pending_attack_slot = ""
                    self._combat_log_add(
                        f"{atk_name}: {rem} attack{'s' if rem != 1 else ''} remaining — "
                        f"move if you wish, then click Attack to continue.")
            else:
                # Attacks exhausted — mark action used and clear sequence state
                self.pending_attack_slot = ""
                self._attack_sequence_slot = ""
                # Clear the generic extra-attack knobs so they don't leak to the next attack.
                self.pending_attack_offhand = None
                self.pending_attack_resource = None

            # Restore original weapons if this was an unarmed strike
            if self._unarmed_strike_original_weapons:
                idx_to_restore, orig_weapons = self._unarmed_strike_original_weapons
                self.combat.set_agent_weapons(self.bm, idx_to_restore, orig_weapons)
                self._unarmed_strike_original_weapons = None

            # FLAG: Move to C++
            if slot == "action":
                self.action_used = True
                # Check Berserker Frenzy: bonus melee attack every turn while raging
                atk_stats = self.combat.get_agent_stats(self.bm, atk_idx)
                atk_cond  = self.combat.get_agent_conditions(self.bm, atk_idx)
                if (atk_stats.character_class == rpg.CharacterClass.Barbarian and
                        atk_stats.barbarian_subclass == rpg.BarbianSubclass.Berserker and
                        atk_cond.raging and
                        not self.bonus_used):
                    self._combat_log_add(f"{atk_name}: Berserker Frenzy — bonus melee attack!")
                    self._start_attack("bonus")
            else:
                self.bonus_used = True
        # Refresh attack overlay (HP may have changed).
        self._update_attack_overlay()

    def _offer_brutal_strike(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Show Brutal Strike effect menu after a hit. Logs the attack after effect is chosen."""
        atk_stats = self.combat.get_agent_stats(self.bm, atk_idx)
        level = atk_stats.char_level
        dice_str = "2d10" if level >= 17 else "1d10"

        # FLAG: Move to C++
        def _apply(effects):
            if effects:
                # Apply Brutal Strike effect and modify result
                self.combat.apply_brutal_strike_effect(self.bm, atk_idx, target_idx, effects, result)
                # Re-format attack message with updated damage breakdown
                dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                updated_msg = (f"{atk_name}→{tgt_name}: "
                               f"HIT {result.total_damage}{self._damage_breakdown_str(result)} {dmg_type_str}"
                               f"{' CRIT!' if result.critical else ''}"
                               f"{' — DOWN' if result.target_down else ''}")
                self._combat_log_add(updated_msg)
            else:
                # Skip chosen - log original attack
                self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._update_attack_overlay()

        options = [
            (f"Forceful Blow ({dice_str} + push 15ft)", lambda: _apply([0])),
            (f"Hamstring Blow ({dice_str} + speed −15ft)", lambda: _apply([1])),
        ]
        if level >= 13:
            options += [
                (f"Staggering Blow ({dice_str} + disadv next save)", lambda: _apply([2])),
                (f"Sundering Blow ({dice_str} + +5 next atk vs target)", lambda: _apply([3])),
            ]
        options.append(("Skip Brutal Strike", lambda: _apply([])))

        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_push(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Push weapon mastery: optionally shove the target 10 ft straight away (Large or smaller).
        The shove itself is applied in C++ via apply_push, which clears the availability flag."""
        def _apply(do):
            self._combat_log_add(atk_msg)
            if do:
                feet = self.combat.apply_push(self.bm, atk_idx, target_idx)
                if feet > 0:
                    self._combat_log_add(f"{atk_name} pushes {tgt_name} {feet} ft (Push).")
                else:
                    self._combat_log_add(f"{atk_name}: Push had no effect.")
            else:
                # Skip push: mark as used this turn so it won't be offered again
                c = self.combat.get_agent_conditions(self.bm, atk_idx)
                c.push_used_this_turn = True
                self.combat.set_agent_conditions(self.bm, atk_idx, c)
            self._flush_combat_log()
            self._update_attack_overlay()
        options = [
            ("Push 10 ft (away)", lambda: _apply(True)),
            ("Skip Push", lambda: _apply(False)),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_topple(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, weapon_idx):
        """Topple weapon mastery: optionally force a CON save or knock the target Prone.
        The save + prone are resolved in C++ via apply_topple, which clears the flag."""
        def _apply(do):
            self._combat_log_add(atk_msg)
            if do:
                res = self.combat.apply_topple(self.bm, atk_idx, target_idx, weapon_idx)
                if res.toppled:
                    self._combat_log_add(
                        f"{tgt_name} is knocked Prone (Topple — save {res.save_roll} vs DC {res.save_dc}).")
                else:
                    self._combat_log_add(
                        f"{tgt_name} resists Topple (save {res.save_roll} vs DC {res.save_dc}).")
            else:
                # Skip topple: mark as used this turn so it won't be offered again
                c = self.combat.get_agent_conditions(self.bm, atk_idx)
                c.topple_used_this_turn = True
                self.combat.set_agent_conditions(self.bm, atk_idx, c)
            self._flush_combat_log()
            self._update_attack_overlay()
        options = [
            ("Topple (CON save or Prone)", lambda: _apply(True)),
            ("Skip Topple", lambda: _apply(False)),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_cleave(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, weapon_idx):
        """Cleave weapon mastery: optionally make one extra attack vs a 2nd creature within 5 ft of
        the first target, with no ability modifier on damage (once per turn). Cleave is part of the
        Attack action, so it is resolved out-of-band (see _resolve_cleave) — it does not consume the
        bonus action or a sequence attack."""
        def _apply(do):
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            if do:
                # Mark Cleave spent for the turn so the engine won't re-offer it (and a chained
                # Cleave hit can't recurse). Then await the 2nd-target click.
                c = self.combat.get_agent_conditions(self.bm, atk_idx)
                c.cleave_used_this_turn = True
                c.cleave_available = False
                self.combat.set_agent_conditions(self.bm, atk_idx, c)
                self.pending_cleave = {"attacker": atk_idx, "first": target_idx, "weapon": weapon_idx}
                self._combat_log_add(f"Cleave — click a 2nd creature within 5 ft of {tgt_name}.")
                self._flush_combat_log()
            self._update_attack_overlay()
        options = [
            ("Cleave: extra attack (no ability mod)", lambda: _apply(True)),
            ("Skip Cleave", lambda: _apply(False)),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _resolve_cleave(self, second_target: int):
        """Resolve a pending Cleave attack against the clicked 2nd creature. One weapon attack with
        no positive ability modifier on damage; validates the RAW 'within 5 ft of the first target'
        rule (reach to the attacker is enforced by execute_action). No action/bonus is consumed."""
        info = self.pending_cleave
        self.pending_cleave = None
        if not info:
            return
        atk, first, wi = info["attacker"], info["first"], info["weapon"]
        agents = self.bm.placed_agents
        if not (0 <= second_target < len(agents)):
            return
        if second_target in (atk, first):
            self._combat_log_add("Cleave: must target a different creature.")
            self._flush_combat_log()
            return
        # Within 5 ft of the first target (adjacent on the grid, including diagonals).
        fo, so = agents[first].origin, agents[second_target].origin
        if max(abs(fo.col - so.col), abs(fo.row - so.row)) > 1:
            self._combat_log_add("Cleave: the 2nd creature must be within 5 ft of the first target.")
            self._flush_combat_log()
            return

        action = rpg.Attack(atk, second_target, wi)
        action.no_ability_damage = True
        # FLAG: stays on execute_action (the auto Shield path) by design — a Cleave is itself a
        # rider-spawned attack, so routing it through begin_attack would open a Shield window during
        # another reaction (reaction-during-reaction), which the engine has no decision stack for yet.
        # Move to begin_attack once that stack lands.
        result = self.combat.execute_action(self.bm, action)
        self._flush_combat_log()

        atk_name = agents[atk].name if atk < len(agents) else "?"
        tgt_name = agents[second_target].name
        if not result.valid:
            self._combat_log_add(f"Cleave: {tgt_name} is out of reach.")
        elif result.hit:
            dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            self._combat_log_add(
                f"Cleave {atk_name}→{tgt_name}: HIT {result.total_damage}"
                f"{self._damage_breakdown_str(result)} {dmg_type_str}"
                f"{' — DOWN' if result.target_down else ''}")
            if result.target_down:
                self._drop_concentration_for_agent(second_target)
        else:
            self._combat_log_add(
                f"Cleave {atk_name}→{tgt_name}: miss (roll {result.total_roll} vs AC {result.target_ac})")
        self._flush_combat_log()
        self._update_attack_overlay()

    def _offer_gwm_hew(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, weapon_idx):
        """Great Weapon Master — Hew: after a Critical Hit or a kill with a Heavy melee weapon,
        optionally make one attack with that weapon as a Bonus Action. Routes through the shared
        extra-attack flow (which spends the bonus action). Clearing gwm_hew_available stops a re-offer.

        v1 sequencing: accepting Hew now forgoes any remaining Attack-action attacks (the bonus attack
        takes over the pending sequence). RAW lets you finish your attacks first, then Hew — deferred
        (see known_limitations.md)."""
        def _apply(do):
            self._combat_log_add(atk_msg)
            c = self.combat.get_agent_conditions(self.bm, atk_idx)
            c.gwm_hew_available = False
            self.combat.set_agent_conditions(self.bm, atk_idx, c)
            self._flush_combat_log()
            if do:
                # Forgo any leftover action attacks so the bonus-action Hew sets up cleanly.
                self.attacks_remaining = 0
                self._attack_sequence_slot = ""
                self.pending_attack_slot = ""
                self._start_extra_attack(weapon_idx=weapon_idx, offhand=False,
                                         label="Great Weapon Master: Hew")
            self._update_attack_overlay()
        options = [
            ("Hew: bonus-action attack", lambda: _apply(True)),
            ("Skip Hew", lambda: _apply(False)),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_sudden_strike(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, weapon_idx):
        """Stalker's Flurry — Sudden Strike (Gloom Stalker L11): immediately after a Dreadful Strike
        hit, optionally make one FREE additional attack with the same weapon against a creature within
        5 ft of the target. Routes through the shared extra-attack flow with slot="action" so it does
        NOT consume the bonus action (it's a free attack granted by the feature). Clearing
        sudden_strike_available stops a re-offer.

        v1 sequencing: like GWM Hew, accepting forgoes any remaining Attack-action attacks (the extra
        attack takes over the pending sequence). The "within 5 ft of the target" constraint is left to
        the player's target click (noted in the prompt). Mass Fear (the alternative L11 effect) is
        deferred — see known_limitations.md."""
        def _apply(do):
            self._combat_log_add(atk_msg)
            c = self.combat.get_agent_conditions(self.bm, atk_idx)
            c.sudden_strike_available = False
            self.combat.set_agent_conditions(self.bm, atk_idx, c)
            self._flush_combat_log()
            if do:
                # Forgo any leftover action attacks so the free Sudden Strike sets up cleanly.
                self.attacks_remaining = 0
                self._attack_sequence_slot = ""
                self.pending_attack_slot = ""
                self._start_extra_attack(weapon_idx=weapon_idx, offhand=False, slot="action",
                                         label="Stalker's Flurry: Sudden Strike (target within 5 ft)")
            self._update_attack_overlay()
        options = [
            ("Sudden Strike: free extra attack", lambda: _apply(True)),
            ("Skip Sudden Strike", lambda: _apply(False)),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_divine_strike(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """After a qualifying weapon hit, offer Cleric Divine Strike (Radiant or Necrotic).
        Mirrors _offer_brutal_strike; the extra die is applied in C++ via apply_divine_strike_effect."""
        def _apply(radiant):
            if radiant is not None:
                self.combat.apply_divine_strike_effect(self.bm, atk_idx, target_idx, radiant, result)
                dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                self._combat_log_add(
                    f"{atk_name}→{tgt_name}: HIT {result.total_damage}{self._damage_breakdown_str(result)} "
                    f"{dmg_type_str}{' CRIT!' if result.critical else ''}{' — DOWN' if result.target_down else ''}")
            else:
                self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._update_attack_overlay()
        options = [
            ("Divine Strike: Radiant", lambda: _apply(True)),
            ("Divine Strike: Necrotic", lambda: _apply(False)),
            ("Skip Divine Strike", lambda: _apply(None)),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_psionic_strike(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """After a qualifying hit, offer Psi Warrior Psionic Strike (spend 1 Psionic Energy die → Force).
        Mirrors _offer_divine_strike; the extra die is applied in C++ via apply_psionic_strike_effect."""
        def _apply(use_it):
            if use_it:
                self.combat.apply_psionic_strike_effect(self.bm, atk_idx, target_idx, result)
                dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                self._combat_log_add(
                    f"{atk_name}→{tgt_name}: HIT {result.total_damage}{self._damage_breakdown_str(result)} "
                    f"{dmg_type_str}{' CRIT!' if result.critical else ''}{' — DOWN' if result.target_down else ''}")
            else:
                self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._update_attack_overlay()
        options = [
            ("Psionic Strike (1 die → Force)", lambda: _apply(True)),
            ("Skip Psionic Strike", lambda: _apply(False)),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_punch_and_grab(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """After an Unarmed-Strike hit in the Attack action, offer the Grappler feat's Punch-and-Grab:
        ALSO attempt a Grapple this attack (normally damage OR grapple), once per turn. The contested
        grapple runs in C++ via apply_punch_and_grab → resolveGrapple. Mirrors _offer_psionic_strike."""
        def _apply(use_it):
            self._combat_log_add(atk_msg)   # the unarmed-strike damage still landed
            if use_it:
                grab = self.combat.apply_punch_and_grab(self.bm, atk_idx, target_idx)
                if grab.valid and grab.success:
                    self._combat_log_add(
                        f"{atk_name}→{tgt_name}: Punch-and-Grab — grappled (escape DC {grab.escape_dc})")
                elif grab.valid:
                    self._combat_log_add(
                        f"{atk_name}→{tgt_name}: Punch-and-Grab — grapple failed "
                        f"(atk {grab.attacker_roll} vs def {grab.defender_roll})")
            self._flush_combat_log()
            self._sync_spell_effect_cache()
            self._update_attack_overlay()
        options = [
            ("Punch-and-Grab (also attempt a Grapple)", lambda: _apply(True)),
            ("Skip Grapple", lambda: _apply(False)),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_divine_smite(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """After a melee/unarmed hit, offer Paladin Divine Smite with one entry per available
        spell-slot level (1st→2d8 … 5th→6d8, +1d8 vs Undead/Fiend). The Radiant damage and the
        slot + bonus-action spend happen in C++ via apply_divine_smite_effect. Mirrors
        _offer_divine_strike."""
        def _apply(slot_level):
            if slot_level is not None:
                self.combat.apply_divine_smite_effect(self.bm, atk_idx, target_idx, slot_level, result)
                dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                self._combat_log_add(
                    f"{atk_name}→{tgt_name}: HIT {result.total_damage}{self._damage_breakdown_str(result)} "
                    f"{dmg_type_str}{' CRIT!' if result.critical else ''}{' — DOWN' if result.target_down else ''}")
            else:
                self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._update_attack_overlay()

        def _ordinal(n):
            return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")

        stats = self.combat.get_agent_stats(self.bm, atk_idx)
        tgt_stats = self.combat.get_agent_stats(self.bm, target_idx)
        bonus = 1 if (tgt_stats.is_undead or tgt_stats.is_fiend) else 0
        options = []
        for lvl in range(1, 10):
            if stats.spell_slots_remaining[lvl - 1] > 0:
                dice = 1 + min(lvl, 5) + bonus
                options.append((f"Divine Smite ({_ordinal(lvl)} slot → {dice}d8 Radiant)",
                                lambda l=lvl: _apply(l)))
        options.append(("Skip Divine Smite", lambda: _apply(None)))
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_eldritch_smite(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """After a pact-weapon hit, offer Warlock Eldritch Smite. Pact Magic slots are all one level
        (pact_slot_level), so there's a single option: expend the pact slot → (lvl+1)d8 Force + knock
        Prone. The damage, slot + bonus-action spend, and Prone happen in C++ via
        apply_eldritch_smite_effect. Mirrors _offer_divine_smite."""
        def _apply(slot_level):
            if slot_level is not None:
                self.combat.apply_eldritch_smite_effect(self.bm, atk_idx, target_idx, slot_level, result)
                dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                self._combat_log_add(
                    f"{atk_name}→{tgt_name}: HIT {result.total_damage}{self._damage_breakdown_str(result)} "
                    f"{dmg_type_str}{' CRIT!' if result.critical else ''}{' — DOWN' if result.target_down else ''}")
            else:
                self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._update_attack_overlay()

        stats = self.combat.get_agent_stats(self.bm, atk_idx)
        psl = stats.pact_slot_level()
        options = []
        if psl >= 1 and stats.spell_slots_remaining[psl - 1] > 0:
            dice = psl + 1
            options.append((f"Eldritch Smite (pact slot L{psl} → {dice}d8 Force + Prone)",
                            lambda l=psl: _apply(l)))
        options.append(("Skip Eldritch Smite", lambda: _apply(None)))
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _eligible_guided_clerics(self, atk_idx):
        """War Clerics (L3+, Channel Divinity left) who can Guide a missed attack: the attacker, or an
        ally within 30 ft who still has a reaction. apply_guided_strike_effect re-validates in C++."""
        agents = self.bm.placed_agents
        out = []
        if not (0 <= atk_idx < len(agents)):
            return out
        ao = agents[atk_idx].origin
        for ci in range(len(agents)):
            s = self.combat.get_agent_stats(self.bm, ci)
            if (s.character_class != rpg.CharacterClass.Cleric or
                    s.cleric_subclass != rpg.ClericSubclass.WarDomain or s.char_level < 3):
                continue
            cd = s.get_resource("Channel Divinity")
            if not cd or cd.current <= 0:
                continue
            if ci == atk_idx:
                out.append(ci)
                continue
            if self.combat.get_agent_conditions(self.bm, ci).reaction_used:
                continue
            co = agents[ci].origin
            if ((co.col - ao.col) ** 2 + (co.row - ao.row) ** 2) ** 0.5 * 5 <= 30:
                out.append(ci)
        return out

    def _offer_guided_strike(self, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """After a miss, offer War Domain Guided Strike (+10) via an eligible War Cleric. The +10 and
        any resulting hit/damage are applied in C++ via apply_guided_strike_effect."""
        agents = self.bm.placed_agents
        eligible = self._eligible_guided_clerics(atk_idx)

        def _apply(cleric_idx):
            if cleric_idx is not None:
                self.combat.apply_guided_strike_effect(self.bm, action, cleric_idx, result)
                if result.hit:
                    dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
                    dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                    self._combat_log_add(
                        f"{atk_name}→{tgt_name}: Guided Strike → HIT {result.total_damage}"
                        f"{self._damage_breakdown_str(result)} {dmg_type_str}{' — DOWN' if result.target_down else ''}")
                else:
                    self._combat_log_add(
                        f"{atk_name}→{tgt_name}: Guided Strike +10 → still misses "
                        f"(roll {result.total_roll} vs AC {result.target_ac})")
            else:
                self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._update_attack_overlay()

        options = []
        for ci in eligible:
            label = "Guided Strike (+10)" if ci == atk_idx else f"Guided Strike: {agents[ci].name} reacts (+10)"
            options.append((label, (lambda c=ci: _apply(c))))
        options.append(("Skip Guided Strike", lambda: _apply(None)))
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_cunning_strike(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Show the Sneak Attack / Cunning Strike menu after a qualifying hit.

        Mirrors _offer_brutal_strike: the attack already resolved, so the chosen riders (and the
        Sneak Attack dice) are applied out of band via apply_cunning_strike_effect. "Sneak Attack
        only" spends no dice on a rider. Logs the final attack message after the choice.
        """
        atk_stats = self.combat.get_agent_stats(self.bm, atk_idx)
        level = atk_stats.char_level

        def _apply(effects):
            self.combat.apply_cunning_strike_effect(self.bm, atk_idx, target_idx, effects, result)
            dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            updated_msg = (f"{atk_name}→{tgt_name}: "
                           f"HIT {result.total_damage}{self._damage_breakdown_str(result)} {dmg_type_str}"
                           f"{' CRIT!' if result.critical else ''}"
                           f"{' — DOWN' if result.target_down else ''}")
            self._combat_log_add(updated_msg)
            self._flush_combat_log()
            # Sneak Attack damage can drop the target after the base attack already settled.
            if result.target_down:
                self._drop_concentration_for_agent(target_idx)
            self._update_attack_overlay()

        options = []
        if level >= 5:
            options += [
                ("Poison (1 die)", lambda: _apply([0])),
                ("Trip (1 die)", lambda: _apply([1])),
                ("Withdraw (1 die)", lambda: _apply([2])),
            ]
        if level >= 11:
            options.append(("Poison + Trip (2 dice)", lambda: _apply([0, 1])))
        if level >= 14:
            options += [
                ("Knock Out (6 dice)", lambda: _apply([4])),
                ("Obscure (3 dice)", lambda: _apply([5])),
            ]
        options.append(("Sneak Attack only", lambda: _apply([])))

        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _show_flurry_rider_menu(self, atk_idx):
        """Show Open Hand rider menu when Flurry of Blows is activated (Way of the Open Hand only)."""
        options = [
            ("Knockdown", lambda: self._execute_flurry(atk_idx, 0)),
            ("Push", lambda: self._execute_flurry(atk_idx, 1)),
            ("Deny Reaction", lambda: self._execute_flurry(atk_idx, 2)),
            ("No Rider", lambda: self._execute_flurry(atk_idx, -1)),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _execute_flurry(self, atk_idx, rider_option):
        """Execute Flurry of Blows with the chosen rider option."""
        agents = self.bm.placed_agents
        if atk_idx < 0 or atk_idx >= len(agents):
            return

        # Prompt for target selection
        self.pending_flurry_atk_idx = atk_idx
        self.pending_flurry_rider_option = rider_option
        self.pending_flurry_target = True
        self.hint = "Click target for Flurry of Blows"

    def _resolve_flurry_target(self, target_idx):
        """Resolve Flurry of Blows target selection and execute."""
        if not hasattr(self, 'pending_flurry_atk_idx') or not self.pending_flurry_target:
            return

        atk_idx = self.pending_flurry_atk_idx
        rider_option = self.pending_flurry_rider_option
        self.pending_flurry_target = False

        # Execute Flurry in C++
        result = self.combat.execute_flurry_of_blows(
            self.bm, atk_idx, target_idx, rider_option
        )

        agents = self.bm.placed_agents
        atk_name = agents[atk_idx].name if atk_idx < len(agents) else "?"
        tgt_name = agents[target_idx].name if target_idx < len(agents) else "?"

        # Log both attacks
        if result.attack1.valid:
            msg1 = f"{atk_name}→{tgt_name}: "
            if result.attack1.hit:
                msg1 += f"HIT {result.attack1.total_damage} Bludgeoning"
            else:
                msg1 += "MISS"
            self._combat_log_add(msg1)

        if result.attack2.valid:
            msg2 = f"{atk_name}→{tgt_name}: "
            if result.attack2.hit:
                msg2 += f"HIT {result.attack2.total_damage} Bludgeoning"
            else:
                msg2 += "MISS"
            self._combat_log_add(msg2)

        # Log rider results if applicable
        if result.rider1.valid and result.attack1.hit:
            if result.rider1.option == 0:
                self._combat_log_add(
                    f"  → Knockdown (STR save DC {result.rider1.knockdown_save_dc}: rolled {result.rider1.knockdown_save_roll}) "
                    f"— {'Prone!' if result.rider1.target_knocked_prone else 'Resisted'}")
            elif result.rider1.option == 1:
                self._combat_log_add(f"  → Push: {tgt_name} pushed back {result.rider1.push_distance} feet")
            elif result.rider1.option == 2:
                self._combat_log_add(f"  → Deny Reaction: {tgt_name} cannot use a reaction")

        if result.rider2.valid and result.attack2.hit:
            if result.rider2.option == 0:
                self._combat_log_add(
                    f"  → Knockdown (STR save DC {result.rider2.knockdown_save_dc}: rolled {result.rider2.knockdown_save_roll}) "
                    f"— {'Prone!' if result.rider2.target_knocked_prone else 'Resisted'}")
            elif result.rider2.option == 1:
                self._combat_log_add(f"  → Push: {tgt_name} pushed back {result.rider2.push_distance} feet")
            elif result.rider2.option == 2:
                self._combat_log_add(f"  → Deny Reaction: {tgt_name} cannot use a reaction")

        self._flush_combat_log()
        self.bonus_used = True

    def _offer_stunning_strike(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Show Stunning Strike menu after a qualifying unarmed hit.
        Monk can spend 1 Focus Point to force a CON save or the target is Stunned.
        """
        atk_stats = self.combat.get_agent_stats(self.bm, atk_idx)
        tgt_stats = self.combat.get_agent_stats(self.bm, target_idx)
        fp = atk_stats.get_resource("Focus Points")

        # Can't use Stunning Strike if no Focus Points
        if not fp or fp.current <= 0:
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            return

        def _apply_stunning_strike():
            # Apply Stunning Strike in C++ (spends resource, rolls save, applies condition)
            res = self.combat.apply_stunning_strike(self.bm, atk_idx, target_idx)

            if res.valid:
                if res.stunned:
                    self._combat_log_add(
                        f"  → CON save DC {res.save_dc}: rolled {res.save_roll} vs DC {res.save_dc} — Stunned!")
                else:
                    self._combat_log_add(
                        f"  → CON save DC {res.save_dc}: rolled {res.save_roll} vs DC {res.save_dc} — Resisted")

            # Log original attack
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._update_attack_overlay()

        def _skip_stunning_strike():
            self._combat_log_add(atk_msg)
            self._flush_combat_log()

        options = [
            (f"Stunning Strike (1 FP)", _apply_stunning_strike),
            ("Don't use", _skip_stunning_strike),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_open_hand_rider(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Show Open Hand rider menu after a qualifying Flurry hit.
        Warrior of the Open Hand can spend 1 Focus Point to apply one of three riders:
        0=Knockdown (STR save or Prone), 1=Push (5 ft), 2=Deny Reaction.
        """
        atk_stats = self.combat.get_agent_stats(self.bm, atk_idx)
        fp = atk_stats.get_resource("Focus Points")

        # Can't use Open Hand rider if no Focus Points
        if not fp or fp.current <= 0:
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            return

        def _apply_knockdown():
            # Knockdown: STR save DC = 8 + DEX mod + prof, on fail apply Prone
            res = self.combat.apply_open_hand_rider(self.bm, atk_idx, target_idx, 0)
            if res.valid:
                if res.target_knocked_prone:
                    self._combat_log_add(
                        f"  → Knockdown (STR save DC {res.knockdown_save_dc}: rolled {res.knockdown_save_roll}) — Prone!")
                else:
                    self._combat_log_add(
                        f"  → Knockdown (STR save DC {res.knockdown_save_dc}: rolled {res.knockdown_save_roll}) — Resisted")
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _apply_push():
            # Push: 5 feet
            res = self.combat.apply_open_hand_rider(self.bm, atk_idx, target_idx, 1)
            if res.valid:
                self._combat_log_add(f"  → Push: {tgt_name} pushed back {res.push_distance} feet")
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _apply_deny_reaction():
            # Deny Reaction: set reaction_used on target
            res = self.combat.apply_open_hand_rider(self.bm, atk_idx, target_idx, 2)
            if res.valid:
                self._combat_log_add(f"  → Deny Reaction: {tgt_name} cannot use a reaction this turn")
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _skip_open_hand():
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)

        options = [
            (f"Knockdown (1 FP, STR save)", _apply_knockdown),
            (f"Push (1 FP, 5 ft)", _apply_push),
            (f"Deny Reaction (1 FP)", _apply_deny_reaction),
            ("Don't use", _skip_open_hand),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_maneuver(self, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Show Battle Master Maneuver menu after a qualifying hit. Spend 1 Superiority Die for
        Trip (Prone), Menacing (Frightened), Pushing (15 ft), Goading (Disadvantage vs others),
        Distracting (allies get Advantage), Disarming (improvised Unarmed), or Sweeping (splash a
        2nd creature). Mirrors _offer_open_hand_rider; preserves the Extra Attack chain via
        _continue_attack_sequence_after_rider."""
        def _apply_save_maneuver(mtype, label, save_name):
            # Trip / Menacing / Goading / Disarming: a save-rider with a uniform log shape.
            res = self.combat.apply_maneuver_effect(self.bm, atk_idx, target_idx, mtype)
            if res.valid:
                outcome = "applied!" if res.condition_applied else "Resisted"
                self._combat_log_add(
                    f"  → {label} ({save_name} save DC {res.save_dc}: rolled {res.save_roll}) — {outcome}")
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            if result.target_down:
                self._drop_concentration_for_agent(target_idx)
            self._update_attack_overlay()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _apply_distracting():
            res = self.combat.apply_maneuver_effect(self.bm, atk_idx, target_idx, 4)
            if res.valid:
                self._combat_log_add(
                    f"  → Distracting Strike: the next attack vs {tgt_name} by another creature has Advantage")
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            if result.target_down:
                self._drop_concentration_for_agent(target_idx)
            self._update_attack_overlay()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _apply_sweeping():
            # Mark the die-spend pending; the 2nd target is chosen by a follow-up map click.
            self._combat_log_add(atk_msg)
            self.pending_sweep = {"action": action, "result": result, "first": target_idx, "attacker": atk_idx}
            self._combat_log_add(f"Sweeping Attack — click a 2nd creature within 5 ft of {tgt_name}.")
            self._flush_combat_log()
            self._update_attack_overlay()

        def _apply_pushing():
            res = self.combat.apply_maneuver_effect(self.bm, atk_idx, target_idx, 2)
            if res.valid:
                self._combat_log_add(f"  → Pushing Attack: {tgt_name} pushed {res.push_distance} feet")
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            if result.target_down:
                self._drop_concentration_for_agent(target_idx)
            self._update_attack_overlay()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _skip_maneuver():
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)

        options = [
            ("Trip (1 die, STR save → Prone)",
                lambda: _apply_save_maneuver(0, "Tripping Attack", "STR")),
            ("Menacing (1 die, WIS save → Frightened)",
                lambda: _apply_save_maneuver(1, "Menacing Attack", "WIS")),
            ("Pushing (1 die, 15 ft push)", _apply_pushing),
            ("Goading (1 die, WIS save → Disadv. vs others)",
                lambda: _apply_save_maneuver(3, "Goading Attack", "WIS")),
            ("Distracting (1 die, allies get Advantage)", _apply_distracting),
            ("Disarming (1 die, STR save → improvised unarmed)",
                lambda: _apply_save_maneuver(5, "Disarming Attack", "STR")),
            ("Sweeping (1 die, splash a 2nd creature)", _apply_sweeping),
            ("Skip", _skip_maneuver),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _resolve_sweep(self, second_target: int):
        """Resolve a pending Sweeping Attack against the clicked 2nd creature (within 5 ft of the
        first target). Spends the superiority die; the original attack roll is reused to see if it
        would hit the 2nd creature's AC. No new attack roll, no action/bonus consumed."""
        info = self.pending_sweep
        self.pending_sweep = None
        if not info:
            return
        atk, first = info["attacker"], info["first"]
        agents = self.bm.placed_agents
        if not (0 <= second_target < len(agents)) or second_target in (atk, first):
            self._combat_log_add("Sweeping Attack: must target a different creature.")
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk)
            return
        fo, so = agents[first].origin, agents[second_target].origin
        if max(abs(fo.col - so.col), abs(fo.row - so.row)) > 1:
            self._combat_log_add("Sweeping Attack: the 2nd creature must be within 5 ft of the first target.")
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk)
            return
        res = self.combat.apply_sweeping_attack(self.bm, info["action"], info["result"], second_target)
        tgt2 = agents[second_target].name
        if res.valid and res.condition_applied:
            self._combat_log_add(
                f"  → Sweeping Attack: {tgt2} takes {res.extra_damage} damage "
                f"(roll {res.save_roll} vs AC {res.save_dc}){' — DOWN' if res.extra_target_down else ''}")
            if res.extra_target_down:
                self._drop_concentration_for_agent(second_target)
        elif res.valid:
            self._combat_log_add(
                f"  → Sweeping Attack misses {tgt2} (roll {res.save_roll} vs AC {res.save_dc})")
        self._flush_combat_log()
        self._update_attack_overlay()
        self._continue_attack_sequence_after_rider(atk)

    def _offer_precision_attack(self, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Show Battle Master Precision Attack menu after a non-fumble miss.
        Spend 1 Superiority Die to add 1d8/d10 to the roll, potentially converting the miss to a hit.
        Mirrors _offer_guided_strike.
        """
        def _apply():
            self.combat.apply_precision_attack_effect(self.bm, action, result)
            if result.hit:
                dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                self._combat_log_add(
                    f"{atk_name}→{tgt_name}: Precision Attack → HIT {result.total_damage}"
                    f"{self._damage_breakdown_str(result)} {dmg_type_str}{' — DOWN' if result.target_down else ''}")
                if result.target_down:
                    self._drop_concentration_for_agent(target_idx)
            else:
                self._combat_log_add(
                    f"{atk_name}→{tgt_name}: Precision Attack +die → still misses "
                    f"(roll {result.total_roll} vs AC {result.target_ac})")
            self._flush_combat_log()
            self._update_attack_overlay()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _skip():
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)

        options = [
            ("Precision Attack (spend 1 Superiority Die)", _apply),
            ("Skip", _skip),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_reckless_reroll(self, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Offer a Barbarian a post-hoc Reckless Attack after a miss: reroll the SAME attack with
        advantage, at the cost of the downside (enemies have advantage vs you until your next turn).
        The other entry point is pre-declaring Reckless before attacking. Mirrors _offer_precision_attack."""
        def _apply():
            new_result = self.combat.apply_reckless_reroll(self.bm, atk_idx, target_idx, action.weapon_idx)
            if new_result.hit:
                dmg_parts = self._get_damage_type_names(new_result.magic_damage_types, new_result.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                self._combat_log_add(
                    f"{atk_name}→{tgt_name}: Reckless reroll → HIT {new_result.total_damage}"
                    f"{self._damage_breakdown_str(new_result)} {dmg_type_str}"
                    f"{' CRIT!' if new_result.critical else ''}{' — DOWN' if new_result.target_down else ''}")
                if new_result.target_down:
                    self._drop_concentration_for_agent(target_idx)
            else:
                self._combat_log_add(
                    f"{atk_name}→{tgt_name}: Reckless reroll → still misses "
                    f"(roll {new_result.total_roll} vs AC {new_result.target_ac})")
            self._flush_combat_log()
            self._sync_spell_effect_cache()
            self._update_attack_overlay()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _skip():
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)

        options = [
            ("Reckless Attack — reroll w/ advantage (enemies gain advantage vs you)", _apply),
            ("Skip", _skip),
        ]
        px, py = self._agent_screen_pos(atk_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_riposte(self, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Offer a Battle Master DEFENDER a Riposte after a melee attack misses them: spend the
        reaction + 1 Superiority Die to make a melee attack back at the attacker, adding the die to
        the damage on a hit. The reactor is the TARGET of the missed attack. Mirrors _offer_reckless_reroll."""
        def _apply():
            # Riposte = the target (defender) attacks the original attacker.
            rip = self.combat.apply_riposte(self.bm, target_idx, atk_idx, action.weapon_idx)
            self._combat_log_add(atk_msg)   # the original miss still happened
            if rip.valid and rip.hit:
                dmg_parts = self._get_damage_type_names(rip.magic_damage_types, rip.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                self._combat_log_add(
                    f"{tgt_name}→{atk_name}: Riposte → HIT {rip.total_damage}"
                    f"{self._damage_breakdown_str(rip)} {dmg_type_str}"
                    f"{' CRIT!' if rip.critical else ''}{' — DOWN' if rip.target_down else ''}")
                if rip.target_down:
                    self._drop_concentration_for_agent(atk_idx)
            elif rip.valid:
                self._combat_log_add(
                    f"{tgt_name}→{atk_name}: Riposte → misses "
                    f"(roll {rip.total_roll} vs AC {rip.target_ac})")
            self._flush_combat_log()
            self._sync_spell_effect_cache()
            self._update_attack_overlay()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _skip():
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)

        options = [
            ("Riposte — melee attack back (reaction + 1 Superiority Die)", _apply),
            ("Skip", _skip),
        ]
        px, py = self._agent_screen_pos(target_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _offer_sentinel_guard(self, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Offer a Sentinel BYSTANDER a Guardian reaction after an adjacent enemy attacks an ally: spend
        the reaction to make a melee attack at the attacker. The reactor is a third creature within 5 ft
        of the attacker (NOT the attacker or the attack's target). Scans for the first eligible Sentinel
        via can_sentinel_guard. Fires on a hit OR a miss; never alters the original attack. Mirrors
        _offer_riposte, but the reactor is found by scan (like _offer_guided_strike)."""
        agents = self.bm.placed_agents
        sentinel_idx = -1
        for i in range(len(agents)):
            if self.combat.can_sentinel_guard(self.bm, action, i):
                sentinel_idx = i
                break
        if sentinel_idx < 0:                       # eligibility lapsed since the flag was set
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)
            return
        sent_name = agents[sentinel_idx].name if sentinel_idx < len(agents) else "?"
        # First melee weapon the Sentinel wields (mirrors C++ riposteWeaponIdx; the engine re-validates).
        widx = next((i for i, w in enumerate(self.combat.get_agent_weapons(self.bm, sentinel_idx))
                     if w.type == rpg.WeaponType.Melee), -1)

        def _apply():
            self._combat_log_add(atk_msg)          # the original attack still happened
            grd = self.combat.apply_sentinel_guard(self.bm, sentinel_idx, atk_idx, widx)
            if grd.valid and grd.hit:
                dmg_parts = self._get_damage_type_names(grd.magic_damage_types, grd.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                self._combat_log_add(
                    f"{sent_name}→{atk_name}: Sentinel Guardian → HIT {grd.total_damage}"
                    f"{self._damage_breakdown_str(grd)} {dmg_type_str}"
                    f"{' CRIT!' if grd.critical else ''}{' — DOWN' if grd.target_down else ''}")
                if grd.target_down:
                    self._drop_concentration_for_agent(atk_idx)
            elif grd.valid:
                self._combat_log_add(
                    f"{sent_name}→{atk_name}: Sentinel Guardian → misses "
                    f"(roll {grd.total_roll} vs AC {grd.target_ac})")
            self._flush_combat_log()
            self._sync_spell_effect_cache()
            self._update_attack_overlay()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _skip():
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)

        options = [
            (f"Sentinel Guardian — {sent_name} melee attacks the attacker (reaction)", _apply),
            ("Skip", _skip),
        ]
        px, py = self._agent_screen_pos(sentinel_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _can_protective_field(self, target_idx, result):
        """Eligibility gate for the Psi Warrior Protective Field reaction (mirrors the checks in
        applyProtectiveField). Reactor = the hit target: Fighter L3+ Psi Warrior, reaction free, not
        incapacitated, ≥1 Psionic Energy die, and a hit that actually dealt damage. We also require the
        target to NOT be down — the engine models Protective Field as a post-hit heal-back and rejects a
        now-incapacitated defender, so v1 can't yet save a creature from a drop to 0 (see
        known_limitations.md). apply_protective_field re-validates everything in C++."""
        agents = self.bm.placed_agents
        if not (0 <= target_idx < len(agents)):
            return False
        if not (result.hit and result.total_damage > 0) or result.target_down:
            return False
        s = self.combat.get_agent_stats(self.bm, target_idx)
        if (s.character_class != rpg.CharacterClass.Fighter or
                s.fighter_subclass != rpg.FighterSubclass.PsiWarrior or
                s.char_level < 3):
            return False
        c = self.combat.get_agent_conditions(self.bm, target_idx)
        if c.reaction_used or c.incapacitated:
            return False
        ped = s.get_resource("Psionic Energy")
        return ped is not None and ped.current > 0

    def _offer_protective_field(self, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Offer a Psi Warrior DEFENDER (Fighter L3+) Protective Field after they're hit: spend the
        reaction + 1 Psionic Energy die to reduce the damage by (die + INT mod), healing back what the
        hit actually cost. The reactor is the TARGET of the hit. apply_protective_field re-validates and
        applies in C++. Mirrors _offer_riposte (DEFENDER reaction keyed on the target)."""
        def _apply():
            self._combat_log_add(atk_msg)   # the hit (and its damage) still landed
            prevented = self.combat.apply_protective_field(self.bm, target_idx, result.total_damage)
            if prevented > 0:
                self._combat_log_add(
                    f"{tgt_name}: Protective Field — prevents {prevented} damage (reaction + 1 Psionic die).")
            else:
                self._combat_log_add(f"{tgt_name}: Protective Field had no effect.")
            self._flush_combat_log()
            self._sync_spell_effect_cache()
            self._update_attack_overlay()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _skip():
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)

        options = [
            ("Protective Field — reduce damage (reaction + 1 Psionic die)", _apply),
            ("Skip", _skip),
        ]
        px, py = self._agent_screen_pos(target_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _find_interceptor(self, action, target_idx, result):
        """Return the first agent eligible to use the Interception fighting style against this hit, or
        -1. All the rules (Interception feat, reaction free, Shield/weapon, within 5 ft of the still-
        standing target, can see the attacker) live in C++ can_intercept; we only pre-gate on the hit
        actually dealing damage and not dropping the target (the v1 heal-back can't rescue a drop to 0)."""
        if not (result.hit and result.total_damage > 0) or result.target_down:
            return -1
        agents = self.bm.placed_agents
        for i in range(len(agents)):
            if i == target_idx:
                continue
            if self.combat.can_intercept(self.bm, action, i, result.total_damage):
                return i
        return -1

    def _offer_interception(self, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
        """Offer a bystander with the Interception fighting style (holding a Shield/weapon, within 5 ft
        of the target) to spend its reaction reducing the damage by 1d10 + PB. The reactor is a THIRD
        creature (not the target). apply_interception re-validates and heals the target back in C++.
        Mirrors _offer_protective_field but keyed on the interceptor."""
        agents = self.bm.placed_agents
        interceptor_idx = self._find_interceptor(action, target_idx, result)
        itc_name = agents[interceptor_idx].name if 0 <= interceptor_idx < len(agents) else "Ally"

        def _apply():
            self._combat_log_add(atk_msg)   # the hit (and its damage) still landed
            prevented = self.combat.apply_interception(self.bm, interceptor_idx, target_idx, result.total_damage)
            if prevented > 0:
                self._combat_log_add(
                    f"{itc_name}: Interception — prevents {prevented} damage to {tgt_name} (reaction + 1d10 + PB).")
            else:
                self._combat_log_add(f"{itc_name}: Interception had no effect.")
            self._flush_combat_log()
            self._sync_spell_effect_cache()
            self._update_attack_overlay()
            self._continue_attack_sequence_after_rider(atk_idx)

        def _skip():
            self._combat_log_add(atk_msg)
            self._flush_combat_log()
            self._continue_attack_sequence_after_rider(atk_idx)

        options = [
            (f"Interception — {itc_name} reduces damage (reaction + 1d10 + PB)", _apply),
            ("Skip", _skip),
        ]
        px, py = self._agent_screen_pos(interceptor_idx if interceptor_idx >= 0 else target_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _create_unarmed_punch_weapon(self):
        """Create a synthetic unarmed punch weapon (1 + STR bludgeoning)."""
        unarmed = rpg.Weapon()
        unarmed.name = "Unarmed Strike"
        unarmed.type = rpg.WeaponType.Melee
        unarmed.proficient = True
        unarmed.finesse = True
        unarmed.reach_ft = 5
        unarmed.bonus_hit = 0
        dmg_roll = rpg.PhysicalDamageRoll()
        dmg_roll.type = rpg.PhysicalDamage.Bludgeoning
        dmg_roll.num_dice = 1
        dmg_roll.die_size = 1
        dmg_roll.bonus = 0
        unarmed.physical_damage_types = [dmg_roll]
        return unarmed

    def _create_monk_unarmed_weapon(self):
        """Create Monk unarmed strike weapon (1d8 + DEX bludgeoning)."""
        unarmed = rpg.Weapon()
        unarmed.name = "MonkUnarmed"
        unarmed.type = rpg.WeaponType.Melee
        unarmed.proficient = True
        unarmed.finesse = True
        unarmed.reach_ft = 5
        unarmed.bonus_hit = 0
        dmg_roll = rpg.PhysicalDamageRoll()
        dmg_roll.type = rpg.PhysicalDamage.Bludgeoning
        dmg_roll.num_dice = 1
        dmg_roll.die_size = 8
        dmg_roll.bonus = 0
        unarmed.physical_damage_types = [dmg_roll]
        return unarmed

    def _create_alter_self_claws_weapon(self):
        """Master of Myriad Forms (invocation 12): Alter Self Natural Weapons —
        a 1d6 finesse natural weapon the Warlock is proficient with. ("Counts as
        magical" has no engine effect: no nonmagical-resistance is modeled.)"""
        claws = rpg.Weapon()
        claws.name = "AlterSelfClaws"
        claws.type = rpg.WeaponType.Melee
        claws.proficient = True
        claws.finesse = True
        claws.reach_ft = 5
        claws.bonus_hit = 0
        dmg_roll = rpg.PhysicalDamageRoll()
        dmg_roll.type = rpg.PhysicalDamage.Slashing
        dmg_roll.num_dice = 1
        dmg_roll.die_size = 6
        dmg_roll.bonus = 0
        claws.physical_damage_types = [dmg_roll]
        return claws

    def _create_pact_blade_weapon(self):
        """Pact of the Blade (invocation 13): the conjured pact weapon — a 1d8 slashing martial
        melee weapon the Warlock is proficient with. pact_weapon=True both lets the engine use CHA
        for the attack/damage rolls AND identifies it for Thirsting Blade / Eldritch Smite /
        Lifedrinker. (Modeled as a fixed weapon; "choose any melee weapon" is a combat-sim
        simplification.)"""
        blade = rpg.Weapon()
        blade.name = "PactBlade"
        blade.type = rpg.WeaponType.Melee
        blade.proficient = True
        blade.pact_weapon = True
        blade.reach_ft = 5
        blade.bonus_hit = 0
        dmg_roll = rpg.PhysicalDamageRoll()
        dmg_roll.type = rpg.PhysicalDamage.Slashing
        dmg_roll.num_dice = 1
        dmg_roll.die_size = 8
        dmg_roll.bonus = 0
        blade.physical_damage_types = [dmg_roll]
        return blade

    def _show_portent_dice_menu(self):
        """Show available portent dice for selection."""
        idx = self._current_agent_idx()
        if idx < 0:
            return
        stats = self.combat.get_agent_stats(self.bm, idx)
        if (stats.character_class != rpg.CharacterClass.Wizard or
            stats.wizard_subclass != rpg.WizardSubclass.Diviner):
            self._combat_log_add("Not a Diviner Wizard!")
            return
        if len(stats.portent_dice) == 0:
            self._combat_log_add("No portent dice available!")
            return

        # Create menu items for each portent die
        items = []
        for die_idx, die_value in enumerate(stats.portent_dice):
            label = f"⚔️  Portent d20 → {die_value}"
            items.append((label, lambda idx=die_idx: self._use_portent_die_at_index(idx)))

        mouse_pos = pygame.mouse.get_pos()
        self.context_menu.show(mouse_pos, items, self.screen.get_size())

    # FLAG: Move to C++
    def _use_portent_die_at_index(self, die_index: int):
        """Use the selected portent die."""
        idx = self._current_agent_idx()
        if idx < 0:
            return
        success = self.combat.use_portent_die(self.bm, idx, die_index, self.round_num)
        if success:
            stats = self.combat.get_agent_stats(self.bm, idx)
            portent_res = stats.get_resource("Portent Dice")
            remaining = portent_res.current if portent_res else 0
            agent_name = self.bm.placed_agents[idx].name if idx < len(self.bm.placed_agents) else "Unknown"
            self._combat_log_add(f"{agent_name}: Portent die activated! ({remaining} remaining)")
        else:
            self._combat_log_add("Cannot use Portent Die (already used this round)")

    def _show_arcane_ward_menu(self):
        """Show available spell slots for Arcane Ward charging."""
        idx = self._current_agent_idx()
        if idx < 0:
            return
        stats = self.combat.get_agent_stats(self.bm, idx)
        if (stats.character_class != rpg.CharacterClass.Wizard or
            stats.wizard_subclass != rpg.WizardSubclass.Abjurer or
            stats.char_level < 3 or stats.temp_hp <= 0):
            self._combat_log_add("Cannot charge Arcane Ward!")
            return

        # Create menu items for available spell slots
        items = []
        max_ward = 2 * stats.char_level + (stats.intel - 10) // 2
        for slot_level in range(1, 10):
            remaining = stats.spell_slots_remaining[slot_level - 1]
            if remaining > 0:
                ward_gain = 2 * slot_level
                label = f"Level {slot_level} Slot (+{ward_gain} HP)"
                items.append((label, lambda lvl=slot_level: self._expend_arcane_ward_slot(lvl)))

        if not items:
            self._combat_log_add("No spell slots available!")
            return

        mouse_pos = pygame.mouse.get_pos()
        self.context_menu.show(mouse_pos, items, self.screen.get_size())

    # FLAG: Move to C++
    def _expend_arcane_ward_slot(self, slot_level: int):
        """Expend a spell slot to charge Arcane Ward."""
        idx = self._current_agent_idx()
        if idx < 0:
            return
        success = self.combat.expend_arcane_ward_slot(self.bm, idx, slot_level)
        if success:
            stats = self.combat.get_agent_stats(self.bm, idx)
            agent_name = self.bm.placed_agents[idx].name if idx < len(self.bm.placed_agents) else "Unknown"
            max_ward = 2 * stats.char_level + (stats.intel - 10) // 2
            self._combat_log_add(f"{agent_name}: Expends Level {slot_level} slot, Arcane Ward now {stats.temp_hp}/{max_ward}")
            self.bonus_used = True
        else:
            self._combat_log_add("Failed to expend spell slot for Arcane Ward!")

    def _show_wild_shape_menu(self):
        """Show Wild Shape form options or end Wild Shape if already active."""
        idx = self._current_agent_idx()
        if idx < 0:
            return
        stats = self.combat.get_agent_stats(self.bm, idx)
        if stats.character_class != rpg.CharacterClass.Druid or stats.char_level < 2:
            self._combat_log_add("Cannot use Wild Shape!")
            return

        if stats.wild_shape_active:
            self.combat.deactivate_wild_shape(self.bm, idx)
            self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Exits Wild Shape")
            self.bonus_used = True
            return

        ws_resource = stats.get_resource("Wild Shape")
        if ws_resource is None or ws_resource.current <= 0:
            self._combat_log_add("No Wild Shape uses remaining!")
            return

        import json
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        beast_path = os.path.join(script_dir, "beast_forms.json")

        try:
            with open(beast_path, 'r') as f:
                beasts = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._combat_log_add("Error loading beast forms!")
            return

        # Determine CR cap and fly restriction based on level and circle
        level = stats.char_level
        allow_fly = level >= 8

        if stats.druid_circle == rpg.DruidCircle.CircleOfMoon:
            cr_cap = level / 3
        else:
            if level < 4:
                cr_cap = 0.25
            elif level < 8:
                cr_cap = 0.5
            else:
                cr_cap = 1.0

        # Filter available beasts
        available = []
        for beast in beasts:
            if beast['cr'] <= cr_cap and (allow_fly or not beast['fly_speed']):
                available.append(beast)

        if not available:
            self._combat_log_add("No valid wild shapes available!")
            return

        # Create menu items
        items = []
        for beast in available:
            label = f"🐺 {beast['name']} (CR {beast['cr']})"
            items.append((label, lambda b=beast['name']: self._activate_wild_shape(idx, b)))

        mouse_pos = pygame.mouse.get_pos()
        self.context_menu.show(mouse_pos, items, self.screen.get_size())

    def _activate_wild_shape(self, idx: int, beast_name: str):
        """Activate Wild Shape with the given beast form."""
        import os
        import json
        script_dir = os.path.dirname(os.path.abspath(__file__))
        beast_path = os.path.join(script_dir, "beast_forms.json")
        weapons_path = os.path.join(script_dir, "weapons.json")

        # Mapping from beast name to weapon name (for the beast's primary attack)
        beast_to_weapon = {
            "Brown Bear": "BrownBearBite",
            "Giant Spider": "GiantSpiderBite",
        }

        try:
            # Load weapons from weapons.json
            with open(weapons_path, 'r') as f:
                all_weapons = json.load(f)

            # Find the weapon for this beast
            weapon_name = beast_to_weapon.get(beast_name)
            if not weapon_name:
                self._combat_log_add(f"No weapon mapping for beast {beast_name}!")
                return

            weapon_dict = next((w for w in all_weapons if w['name'] == weapon_name), None)
            if not weapon_dict:
                self._combat_log_add(f"Weapon {weapon_name} not found in weapons.json!")
                return

            # Convert dict to rpg.Weapon
            main_weapon = _dict_to_weapon(weapon_dict)

            # Load beast_forms.json to get condition_rider from the beast's attacks
            with open(beast_path, 'r') as f:
                beasts = json.load(f)

            # Find the beast and get its condition_rider
            for beast_data in beasts:
                if beast_data.get('name') == beast_name:
                    attacks = beast_data.get('attacks', [])
                    if attacks and len(attacks) > 0:
                        condition_rider = attacks[0].get('condition_rider')
                        if condition_rider:
                            main_weapon.condition_rider = condition_rider
                    break

            # Create 3-weapon array: [main, offhand, ranged]
            weapons_array = [main_weapon, rpg.Weapon(), rpg.Weapon()]

            # Activate Wild Shape in C++ (which now sets the weapons)
            success = self.combat.activate_wild_shape(self.bm, idx, beast_name, weapons_array, beast_path)
            if success:
                agent_name = self.bm.placed_agents[idx].name if idx < len(self.bm.placed_agents) else "Unknown"
                self._combat_log_add(f"{agent_name}: Transforms into {beast_name}!")
                self.bonus_used = True
            else:
                self._combat_log_add(f"Failed to activate {beast_name}!")
        except Exception as e:
            self._combat_log_add(f"Error activating Wild Shape: {e}")

    def _show_unarmed_menu(self, mouse_pos):
        """Show the unarmed strike options menu at mouse position."""
        items = [
            ("👊 Punch", lambda: self._start_unarmed_punch()),
            ("🤝 Grapple", lambda: self._start_unarmed_grapple()),
            ("🔨 Push", lambda: self._start_unarmed_push()),
        ]
        self.context_menu.show(mouse_pos, items, self.screen.get_size())

    def _start_unarmed_punch(self):
        """Start an unarmed punch attack (1 + STR bludgeoning)."""
        idx = self._current_agent_idx()
        if idx < 0:
            return
        unarmed = self._create_unarmed_punch_weapon()
        orig_weapons = self.combat.get_agent_weapons(self.bm, idx)
        new_weapons = [unarmed] + orig_weapons[1:]
        self.combat.set_agent_weapons(self.bm, idx, new_weapons)
        self._unarmed_strike_original_weapons = (idx, orig_weapons)
        self.pending_unarmed_type = "punch"
        self._combat_log_add("Click a target to punch.")

    def _start_unarmed_grapple(self):
        """Start an unarmed grapple action (requires target selection)."""
        if self._current_agent_idx() < 0:
            return
        self.pending_unarmed_type = "grapple"
        self._combat_log_add("Click a target to grapple.")

    def _start_unarmed_push(self):
        """Start an unarmed push action (requires target selection)."""
        if self._current_agent_idx() < 0:
            return
        self.pending_unarmed_type = "push"
        self._combat_log_add("Click a target to push.")

    def _resolve_unarmed_option(self, target_idx: int):
        """Route unarmed option to appropriate resolver."""
        if not self.pending_unarmed_type:
            return

        if self.pending_unarmed_type == "punch":
            self._resolve_combat_attack(target_idx)
        elif self.pending_unarmed_type == "grapple":
            self.pending_grapple_slot = "action"  # Set before resolver checks it
            self._resolve_grapple(target_idx)
            self.bonus_used = False  # _resolve_grapple marks bonus_used, but this is an action
            self.action_used = True
        elif self.pending_unarmed_type == "push":
            self.pending_shove_slot = "action"
            self.pending_shove_type = "push"
            self._resolve_shove(target_idx)
            self.bonus_used = False  # _resolve_shove marks bonus_used, but this is an action
            self.action_used = True

        self.pending_unarmed_type = ""

    def _resolve_healing_light(self, target_idx: int):
        """Celestial Warlock Healing Light: spend max(1, CHA mod) d6 on the clicked target."""
        self.pending_heal_light = False
        healer_idx = self._current_agent_idx()
        if not (0 <= healer_idx < len(self.bm.placed_agents)):
            return
        stats = self.combat.get_agent_stats(self.bm, healer_idx)
        cha_mod = (stats.cha - 10) // 2
        num_dice = max(1, cha_mod)
        healed = self.combat.use_healing_light(self.bm, healer_idx, target_idx, num_dice)
        if healed > 0:
            tgt_name = self.bm.placed_agents[target_idx].name
            self._combat_log_add(
                f"{self.bm.placed_agents[healer_idx].name}: Healing Light restores {healed} HP to {tgt_name}.")
            self._flush_combat_log()
        else:
            self._combat_log_add("Healing Light unavailable (no dice left or invalid target).")
        self.bonus_used = True

    def _use_second_wind(self, agent_idx: int):
        """Fighter Second Wind: spend resource, roll 1d10 + level, heal self."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        sw = stats.get_resource("Second Wind")
        if not (sw and sw.current > 0):
            self._combat_log_add(f"{self.bm.placed_agents[agent_idx].name}: No Second Wind uses left.")
            return
        # Roll 1d10 + level
        roll = self.combat.roll(10)
        healing = roll + stats.char_level
        # Apply healing
        old_hp = stats.hp_cur
        stats.hp_cur = min(stats.hp_cur + healing, stats.hp_max)
        self.combat.set_agent_stats(self.bm, agent_idx, stats)
        # Log and spend resource
        sw.spend(1)
        stats.resources["Second Wind"] = sw
        self.combat.set_agent_stats(self.bm, agent_idx, stats)
        self._combat_log_add(
            f"{self.bm.placed_agents[agent_idx].name}: Second Wind! Rolled {roll} + {stats.char_level} level = {healing} HP restored ({old_hp} → {stats.hp_cur}).")
        self.bonus_used = True

    def _offer_bonus_maneuver(self, idx: int):
        """Battle Master bonus-action maneuvers menu: Rally (ally temp HP), Feinting (Advantage +
        die vs an adjacent creature), Quick Toss (thrown attack + die). Each spends 1 Superiority Die."""
        def _rally():
            self.pending_rally = idx
            self._combat_log_add("Rally — click a creature within 30 ft to bolster.")
            self._flush_combat_log()

        def _feint():
            self.pending_feint = idx
            self._combat_log_add("Feinting Attack — click a creature within 5 ft to feint.")
            self._flush_combat_log()

        def _quick_toss():
            if self.combat.prepare_quick_toss(self.bm, idx):
                self.bonus_used = True
                self._flush_combat_log()
                self._start_extra_attack(weapon_idx=self.pending_weapon_idx, offhand=False,
                                         resource=None, label="Quick Toss (thrown weapon)")
            else:
                self._combat_log_add("Quick Toss: no Superiority Dice left.")
                self._flush_combat_log()

        options = [
            ("Rally (ally within 30 ft gains temp HP)", _rally),
            ("Feinting Attack (creature within 5 ft)", _feint),
            ("Quick Toss (thrown attack + die)", _quick_toss),
        ]
        px, py = self._agent_screen_pos(idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _resolve_rally(self, target_idx: int):
        """Resolve a pending Rally against the clicked creature (within 30 ft)."""
        fighter = self.pending_rally
        self.pending_rally = None
        agents = self.bm.placed_agents
        if fighter is None or not (0 <= target_idx < len(agents)):
            return
        fo, to = agents[fighter].origin, agents[target_idx].origin
        if max(abs(fo.col - to.col), abs(fo.row - to.row)) > 6:   # 30 ft = 6 cells (Chebyshev)
            self._combat_log_add("Rally: the target must be within 30 ft.")
            self._flush_combat_log()
            return
        amount = self.combat.apply_rally(self.bm, fighter, target_idx)
        if amount > 0:
            self.bonus_used = True
        self._flush_combat_log()
        self._update_attack_overlay()

    def _resolve_feint(self, target_idx: int):
        """Resolve a pending Feinting Attack against the clicked creature (within 5 ft)."""
        fighter = self.pending_feint
        self.pending_feint = None
        agents = self.bm.placed_agents
        if fighter is None or not (0 <= target_idx < len(agents)) or target_idx == fighter:
            return
        fo, to = agents[fighter].origin, agents[target_idx].origin
        if max(abs(fo.col - to.col), abs(fo.row - to.row)) > 1:    # 5 ft = adjacent
            self._combat_log_add("Feinting Attack: the target must be within 5 ft.")
            self._flush_combat_log()
            return
        if self.combat.apply_feinting_attack(self.bm, fighter, target_idx):
            self.bonus_used = True
        self._flush_combat_log()
        self._update_attack_overlay()

    def _use_tireless(self, agent_idx: int):
        """Ranger L10 Tireless: Magic action, grant self 1d8 + WIS mod (min 1) temp HP."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        tl = stats.get_resource("Tireless")
        if not (tl and tl.current > 0):
            self._combat_log_add(f"{self.bm.placed_agents[agent_idx].name}: No Tireless uses left.")
            return
        wis_mod = (stats.wis - 10) // 2
        amount = max(1, self.combat.roll(8) + wis_mod)
        old_thp = stats.temp_hp
        # Temp HP never stacks — take the higher (5e semantics).
        if amount > stats.temp_hp:
            stats.temp_hp = amount
        tl.spend(1)
        stats.resources["Tireless"] = tl
        self.combat.set_agent_stats(self.bm, agent_idx, stats)
        self._combat_log_add(
            f"{self.bm.placed_agents[agent_idx].name}: Tireless — {amount} temp HP "
            f"(was {old_thp}, now {stats.temp_hp}).")
        self.action_used = True

    def _use_natures_veil(self, agent_idx: int):
        """Ranger L14 Nature's Veil: Bonus action, turn Invisible (drops on attack)."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        nv = stats.get_resource("Nature's Veil")
        if not (nv and nv.current > 0):
            self._combat_log_add(f"{self.bm.placed_agents[agent_idx].name}: No Nature's Veil uses left.")
            return
        nv.spend(1)
        stats.resources["Nature's Veil"] = nv
        self.combat.set_agent_stats(self.bm, agent_idx, stats)
        cond = self.combat.get_agent_conditions(self.bm, agent_idx)
        cond.invisible = True
        self.combat.set_agent_conditions(self.bm, agent_idx, cond)
        self._combat_log_add(
            f"{self.bm.placed_agents[agent_idx].name}: Nature's Veil — now invisible "
            f"until the end of your next turn.")
        self.bonus_used = True

    def _use_action_surge(self, agent_idx: int):
        """Fighter Action Surge: spend resource, regain an Action this turn."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        as_res = stats.get_resource("Action Surge")
        if not (as_res and as_res.current > 0):
            self._combat_log_add(f"{self.bm.placed_agents[agent_idx].name}: No Action Surge uses left.")
            return
        # Spend the resource
        as_res.spend(1)
        stats.resources["Action Surge"] = as_res
        self.combat.set_agent_stats(self.bm, agent_idx, stats)
        # Reset action_used to allow another action
        self.action_used = False
        self._combat_log_add(f"{self.bm.placed_agents[agent_idx].name}: Action Surge! You can take another Action this turn.")

        # Eldritch Knight L15 — Arcane Charge: may teleport up to 30 ft when using Action Surge.
        if (stats.character_class == rpg.CharacterClass.Fighter and
                stats.fighter_subclass == rpg.FighterSubclass.EldritchKnight and
                stats.char_level >= 15):
            self.arcane_charge_pending = True
            self._combat_log_add(
                "Arcane Charge: click a destination within 30 ft to teleport (or click yourself to skip).")

    def _resolve_arcane_charge(self, cell):
        """Eldritch Knight L15 Arcane Charge: teleport the EK up to 30 ft to the clicked cell.
        Validation + the teleport live in C++ (apply_arcane_charge); this only handles the
        skip gesture (click your own cell) and maps the engine's status code to a message."""
        idx = self._current_agent_idx()
        if idx < 0:
            self.arcane_charge_pending = False
            return
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self.arcane_charge_pending = False
            self._combat_log_add("Arcane Charge skipped.")
            return
        feet = self.combat.apply_arcane_charge(self.bm, idx, cell.col, cell.row)
        if feet >= 0:
            self.arcane_charge_pending = False
            self._flush_combat_log()  # surface the engine's teleport log line
        elif feet == -2:
            self._combat_log_add("Arcane Charge: out of range (max 30 ft) — pick a closer cell.")
        else:  # -3 blocked (or -1 ineligible, which shouldn't reach here)
            self._combat_log_add("Arcane Charge: destination is blocked — pick another cell.")

    def _use_sacred_weapon(self, agent_idx: int):
        """Paladin Oath of Devotion Sacred Weapon: spend 1 Channel Oath, +CHA to weapon attacks for 1 min."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return
        bonus = self.combat.activate_sacred_weapon(self.bm, agent_idx)
        name = self.bm.placed_agents[agent_idx].name
        if bonus < 0:
            self._combat_log_add(f"{name}: Cannot use Sacred Weapon (needs Oath of Devotion and a Channel Oath use).")
            return
        self.bonus_used = True
        self._combat_log_add(f"{name}: Sacred Weapon! +{bonus} to weapon attack rolls for 1 minute.")

    def _use_corona_of_light(self, agent_idx: int):
        """Cleric Light Domain (L17+) Corona of Light: Magic action, 1-minute aura giving enemies
        within 60 ft Disadvantage on saves vs this caster's Fire/Radiant spells."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return
        ok = self.combat.activate_corona_of_light(self.bm, agent_idx)
        name = self.bm.placed_agents[agent_idx].name
        if not ok:
            self._combat_log_add(f"{name}: Cannot use Corona of Light (needs Light Domain Cleric, level 17+).")
            return
        self.action_used = True
        self._combat_log_add(
            f"{name}: Corona of Light! Enemies within 60 ft have Disadvantage on saves vs its "
            f"Fire/Radiant spells for 1 minute.")

    def _resolve_telekinetic(self, target_idx: int):
        """Psi Warrior Telekinetic Movement: push the clicked target up to 30 ft away (once per rest)."""
        self.pending_telekinetic = False
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)) or not (0 <= target_idx < len(self.bm.placed_agents)):
            return
        feet = self.combat.apply_telekinetic_movement(self.bm, idx, target_idx)
        name = self.bm.placed_agents[idx].name
        tgt_name = self.bm.placed_agents[target_idx].name
        if feet < 0:
            self._combat_log_add(f"{name}: Telekinetic Movement unavailable (no uses left).")
        else:
            self._combat_log_add(f"{name}: Telekinetic Movement pushes {tgt_name} {feet} ft.")
        self._flush_combat_log()

    def _resolve_lay_on_hands(self, target_idx: int):
        """Paladin Lay on Hands: spend from pool, heal target."""
        self.pending_lay_on_hands = False
        healer_idx = self._current_agent_idx()
        if not (0 <= healer_idx < len(self.bm.placed_agents)):
            return
        if not (0 <= target_idx < len(self.bm.placed_agents)):
            return

        # Check healer has Lay on Hands
        healer_stats = self.combat.get_agent_stats(self.bm, healer_idx)
        loh = healer_stats.get_resource("Lay on Hands")
        if not (loh and loh.current > 0):
            self._combat_log_add(f"{self.bm.placed_agents[healer_idx].name}: Lay on Hands pool is empty.")
            return

        # Determine max healable
        target_stats = self.combat.get_agent_stats(self.bm, target_idx)
        heal_needed = target_stats.hp_max - target_stats.hp_cur
        max_healing = min(loh.current, heal_needed)

        # For now, heal the full amount (can add a dialog for partial healing later)
        healing = max_healing
        if healing <= 0:
            self._combat_log_add(f"{self.bm.placed_agents[target_idx].name}: Already at full HP.")
            return

        # Call C++ lay_on_hands method
        actual_healed = self.combat.lay_on_hands(self.bm, healer_idx, target_idx, healing)
        if actual_healed <= 0:
            self._combat_log_add(f"Lay on Hands failed (pool error).")
            return

        # Fetch updated stats for logging
        healer_stats = self.combat.get_agent_stats(self.bm, healer_idx)
        loh = healer_stats.get_resource("Lay on Hands")
        pool_remaining = loh.current if loh else 0
        tgt_name = self.bm.placed_agents[target_idx].name
        healer_name = self.bm.placed_agents[healer_idx].name
        self._combat_log_add(
            f"{healer_name}: Lay on Hands restores {actual_healed} HP to {tgt_name} ({pool_remaining} pool remaining).")
        self.action_used = True

    def _resolve_grant_inspiration(self, target_idx: int):
        """Bard Grant Inspiration (bonus action): spend a Bardic Inspiration use to give
        an ally a Bardic Inspiration die of the bard's current size."""
        self.pending_grant_inspiration = False
        bard_idx = self._current_agent_idx()
        if not (0 <= bard_idx < len(self.bm.placed_agents)):
            return
        if not (0 <= target_idx < len(self.bm.placed_agents)):
            return
        if target_idx == bard_idx:
            self._combat_log_add("Bardic Inspiration must be granted to another creature.")
            return

        bard_stats = self.combat.get_agent_stats(self.bm, bard_idx)
        bi = bard_stats.get_resource("Bardic Inspiration")
        if not (bi and bi.current > 0):
            self._combat_log_add(f"{self.bm.placed_agents[bard_idx].name}: no Bardic Inspiration uses left.")
            return

        die = bard_stats.bardic_inspiration_die_size
        if not self.combat.spend_resource(self.bm, bard_idx, "Bardic Inspiration", 1):
            self._combat_log_add("Grant Inspiration failed (resource error).")
            return
        self.combat.grant_bardic_die(self.bm, target_idx, die)
        self._flush_combat_log()

        bi = self.combat.get_agent_stats(self.bm, bard_idx).get_resource("Bardic Inspiration")
        remaining = bi.current if bi else 0
        bard_name = self.bm.placed_agents[bard_idx].name
        tgt_name = self.bm.placed_agents[target_idx].name
        self._combat_log_add(
            f"{bard_name}: grants a Bardic Inspiration d{die} to {tgt_name} ({remaining} uses left).")
        self.bonus_used = True

    def _use_inspiration_die(self, agent_idx: int):
        """Spend a held Bardic Inspiration die (free): primes a +die bonus on the holder's
        next d20 Test."""
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        if stats.bardic_inspiration_die <= 0:
            self._combat_log_add(f"{self.bm.placed_agents[agent_idx].name}: no Bardic Inspiration die held.")
            return
        value = self.combat.use_bardic_die(self.bm, agent_idx)
        self._flush_combat_log()
        name = self.bm.placed_agents[agent_idx].name
        if value > 0:
            self._combat_log_add(f"{name}: Bardic Inspiration (+{value}) will apply to the next D20 Test.")

    def _set_fiendish_resilience(self, agent_idx: int, dmg_idx: int):
        """Fiend Warlock L10: set the chosen damage resistance (0.5x), clearing any prior choice."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        old = stats.fiendish_resilience_type
        if old >= 0:
            stats.set_magic_damage_multiplier(old, 1.0)  # clear previous selection
        stats.fiendish_resilience_type = dmg_idx
        stats.set_magic_damage_multiplier(dmg_idx, 0.5)
        self.combat.set_agent_stats(self.bm, agent_idx, stats)
        self._combat_log_add(
            f"{self.bm.placed_agents[agent_idx].name}: Fiendish Resilience set (damage type {dmg_idx}, resistance).")

    def _start_shove(self, shove_type: str):
        """Start a shove action (requires target selection)."""
        if self.bonus_used:
            return
        self.pending_shove_slot = "bonus"
        self.pending_shove_type = shove_type
        hint = f"shove and {'knock prone' if shove_type == 'prone' else 'push 5ft'}"
        self._combat_log_add(f"Click a target to {hint}.")

    def _start_telekinetic_shove(self):
        """Telekinetic feat — Telekinetic Shove (bonus action, 30 ft, STR save or pushed 5 ft)."""
        if self.bonus_used:
            return
        self.pending_shove_slot = "bonus"
        self.pending_shove_type = "telekinetic"
        self._combat_log_add("Click a target within 30 ft to telekinetically shove (STR save or pushed 5 ft).")

    def _resolve_shove(self, target_idx: int):
        """Execute the pending shove action."""
        if not self.pending_shove_slot or not self.pending_shove_type:
            return

        atk_idx = self._current_agent_idx()
        if atk_idx < 0:
            self.pending_shove_slot = ""
            self.pending_shove_type = ""
            return

        # Telekinetic Shove is a STR-save shove at 30 ft (reuses the C++ Thunderwave knockback);
        # the ordinary push/prone shove is a contested Athletics check at 5 ft.
        if self.pending_shove_type == "telekinetic":
            result = self.combat.apply_telekinetic_shove(self.bm, atk_idx, target_idx)
            if result.valid:
                self._combat_log_add(result.log_message)
                if result.push_ft_applied > 0:
                    self._update_reach()
                    self._update_attack_overlay()
            else:
                self._combat_log_add(f"Telekinetic Shove failed: {result.log_message}")
            self.pending_shove_slot = ""
            self.pending_shove_type = ""
            self.bonus_used = True
            return

        # Create ShoveAction
        action = rpg.ShoveAction()
        action.attacker_idx = atk_idx
        action.target_idx = target_idx
        action.knock_prone = (self.pending_shove_type == "prone")

        # Execute shove
        result = self.combat.execute_shove(self.bm, action)

        # Log result
        if result.valid:
            self._combat_log_add(result.log_message)
            if result.push_ft_applied > 0 or result.knocked_prone:
                self._update_reach()
                self._update_attack_overlay()
        else:
            self._combat_log_add(f"Shove failed: {result.log_message}")

        # Mark bonus action as used
        self.pending_shove_slot = ""
        self.pending_shove_type = ""
        self.bonus_used = True

    def _start_grapple(self):
        """Start a grapple action (requires target selection)."""
        if self.bonus_used:
            return
        self.pending_grapple_slot = "bonus"
        self._combat_log_add("Click a target to grapple.")

    def _resolve_grapple(self, target_idx: int):
        """Execute the pending grapple action."""
        if not self.pending_grapple_slot:
            return

        atk_idx = self._current_agent_idx()
        if atk_idx < 0:
            self.pending_grapple_slot = ""
            return

        # Create GrappleAction
        action = rpg.GrappleAction()
        action.attacker_idx = atk_idx
        action.target_idx = target_idx

        # Execute grapple
        result = self.combat.execute_grapple(self.bm, action)

        # Log result
        if result.valid:
            self._combat_log_add(result.log_message)
            if result.success:
                self._update_reach()
                self._update_attack_overlay()
        else:
            self._combat_log_add(f"Grapple failed: {result.log_message}")

        # Mark bonus action as used
        self.pending_grapple_slot = ""
        self.bonus_used = True

    # FLAG: Move to C++
    def _execute_grapple_escape(self):
        """Execute escape from grapple (bonus action, no target selection)."""
        if self.bonus_used:
            return

        agent_idx = self._current_agent_idx()
        if agent_idx < 0:
            return

        # Check if agent is actually grappled
        conds = self.combat.get_agent_conditions(self.bm, agent_idx)
        if not conds.grappled:
            self._combat_log_add("Not grappled!")
            return

        # Execute escape
        result = self.combat.execute_grapple_escape(self.bm, agent_idx)

        # Log result
        if result.valid:
            self._combat_log_add(result.log_message)
            if result.success:
                self._update_reach()
                self._update_attack_overlay()
        else:
            self._combat_log_add(f"Escape failed: {result.log_message}")

        # Mark bonus action as used
        self.bonus_used = True

    def _on_spell_done(self, agent_idx: int, spells: list[dict]):
        cpp_spells = []
        for j, d in enumerate(spells):
            cpp_spells.append(self._dict_to_spell(agent_idx, d))
            # Store all metadata for this spell (terrain, level, upcast)
            meta = {
                "terrain_effect": d.get("terrain_effect"),
                "hatch_pattern": d.get("hatch_pattern"),
                "terrain_color": d.get("terrain_color"),
                "level": d.get("level", 0),
                "upcast_dice_bonus": d.get("upcast_dice_bonus", 0),
            }
            self._spell_metadata[(agent_idx, j)] = meta
        self._grant_class_features(agent_idx, cpp_spells)
        self.combat.set_agent_spells(self.bm, agent_idx, cpp_spells)

    def _grant_class_features(self, agent_idx: int, cpp_spells: list):
        """Append always-prepared class features (Channel Divinity options, etc.) from
        classfeatures.json that match this agent's class and level, baking scaling dice
        from level. Mutates and returns cpp_spells; skips any already present by name."""
        if not self.all_class_features:
            return cpp_spells
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        class_name = stats.character_class.name
        level = stats.char_level
        existing = {sp.name for sp in cpp_spells}
        for feat in self.all_class_features:
            if feat.get("class") != class_name:
                continue
            if level < int(feat.get("min_level", 1)):
                continue
            # Subclass-gated features (e.g. Radiance of the Dawn) only for the matching domain.
            sub = feat.get("subclass")
            if sub and (class_name != "Cleric" or stats.cleric_subclass.name != sub):
                continue
            name = feat.get("name")
            if name in existing:
                continue
            sp = self._dict_to_spell(agent_idx, feat)
            self._apply_feature_scaling(sp, feat, level, stats)
            cpp_spells.append(sp)
            existing.add(name)

        # Always-prepared divine domain spells (regular spells from spells.json).
        if class_name == "Cleric":
            domain_table = self._DOMAIN_SPELLS.get(stats.cleric_subclass.name, {})
            for min_lvl, names in domain_table.items():
                if level < min_lvl:
                    continue
                for name in names:
                    if name in existing:
                        continue
                    idx = self.spell_name_to_idx.get(name)
                    if idx is None:
                        continue  # not in spells.json — skip gracefully
                    cpp_spells.append(self._dict_to_spell(agent_idx, self.all_spells[idx]))
                    existing.add(name)

        # Always-prepared Ranger subclass spells (regular spells from spells.json).
        if class_name == "Ranger":
            sub_table = self._RANGER_SUBCLASS_SPELLS.get(stats.ranger_subclass.name, {})
            for min_lvl, names in sub_table.items():
                if level < min_lvl:
                    continue
                for name in names:
                    if name in existing:
                        continue
                    idx = self.spell_name_to_idx.get(name)
                    if idx is None:
                        continue  # not in spells.json (e.g. Summon Fey) — skip gracefully
                    cpp_spells.append(self._dict_to_spell(agent_idx, self.all_spells[idx]))
                    existing.add(name)
        return cpp_spells

    # Always-prepared Ranger subclass spells by subclass and Ranger level (2024 PHB).
    # (Summon Fey at L9 is intentionally omitted — not yet in spells.json; see known_limitations.)
    _RANGER_SUBCLASS_SPELLS = {
        "FeyWanderer": {
            3: ["Charm Person"],
            5: ["Misty Step"],
            13: ["Dimension Door"],
            17: ["Mislead"],
        },
    }

    # Always-prepared Cleric domain spells by domain and Cleric level (2024 PHB).
    _DOMAIN_SPELLS = {
        "LightDomain": {
            3: ["Burning Hands", "Faerie Fire", "Scorching Ray", "See Invisibility"],
            5: ["Daylight", "Fireball"],
            7: ["Arcane Eye", "Wall of Fire"],
            9: ["Flame Strike", "Scrying"],
        },
        "WarDomain": {
            3: ["Guiding Bolt", "Magic Weapon", "Shield of Faith", "Spiritual Weapon"],
            5: ["Crusader's Mantle", "Spirit Guardians"],
            7: ["Fire Shield", "Freedom of Movement"],
            9: ["Hold Monster", "Steel Wind Strike"],
        },
    }

    def _apply_feature_scaling(self, sp, feat: dict, level: int, stats):
        """Bake a feature's level-scaled dice count and ability-mod bonus into its damage
        rolls (e.g. Divine Spark 1d8->4d8 + WIS mod at levels 1/7/13/18)."""
        scaling = feat.get("scaling")
        if not scaling:
            return
        num_dice = None
        for lvl_str, n in sorted((scaling.get("dice_by_level") or {}).items(), key=lambda kv: int(kv[0])):
            if level >= int(lvl_str):
                num_dice = int(n)
        bonus = 0
        ab = (scaling.get("ability_bonus") or "").upper()
        if ab:
            score = {"STR": stats.str, "DEX": stats.dex, "CON": stats.con,
                     "INT": stats.intel, "WIS": stats.wis, "CHA": stats.cha}.get(ab, 10)
            bonus = (score - 10) // 2
        if scaling.get("level_bonus"):
            bonus = level  # flat bonus equal to character level (e.g. Radiance of the Dawn: 2d10 + level)

        def _rescale(rolls, factory):
            out = []
            for r in rolls:
                nr = factory()
                nr.type = r.type
                nr.die_size = r.die_size
                nr.num_dice = num_dice if num_dice is not None else r.num_dice
                nr.bonus = bonus
                out.append(nr)
            return out

        sp.magic_damage_rolls = _rescale(sp.magic_damage_rolls, rpg.MagicDamageRoll)
        sp.physical_damage_rolls = _rescale(sp.physical_damage_rolls, rpg.PhysicalDamageRoll)

    # FLAG: Move to C++
    def _start_cast_spell(self, slot: str):
        self.jump_overlay_active = False  # Close jump overlay when casting spell
        self.jump_reachable_cells = []
        idx = self._current_agent_idx()
        if idx < 0:
            return

        # Get castable spells from C++ layer (respects both NPC and player rules). War Magic has
        # its own engine-side eligibility list (action-cantrips L7+, level 1-5 action spells L18+).
        if slot == "war_magic":
            available_indices = self.combat.available_war_magic_spells(self.bm, idx)
        else:
            available_indices = self.combat.available_castable_spells(self.bm, idx)
        if not available_indices:
            self._combat_log_add("No available spells!")
            if slot == "action":
                self.action_used = True
            elif slot == "bonus":
                self.bonus_used = True
            # "war_magic": consume nothing — the Attack action's weapon attacks remain available.
            return

        spells = self.combat.get_agent_spells(self.bm, idx)
        stats = self.combat.get_agent_stats(self.bm, idx)

        def _activate(s, si_, slot_level_=0):
            sp_ = spells[si_]
            # Cleared for every fresh cast; only the element-choice branch below sets it.
            self.pending_spell_damage_type = -1
            # A new cast always starts with no leftover Chromatic Orb leap chain (e.g. if a prior
            # chain was abandoned by a turn change), so stale hops can't hijack this cast's clicks.
            self.pending_chromatic_active  = False
            self.pending_chromatic_primary = -1
            self.pending_chromatic_chain   = []

            # Cast-time element choice (Chromatic Orb, Sorcerous Burst): pick one damage type via
            # the ElementPickerDialog, store it as the SpellAction override, then continue to the
            # normal Single-target selection. Both spells are Single geometry, so the callback sets
            # up single-target pending state directly.
            elem_opts = ELEMENT_CHOICE_SPELLS.get(sp_.name)
            if elem_opts is not None:
                def _on_elem(chosen, s=s, si_=si_, sp_=sp_, slot_level_=slot_level_, elem_opts=elem_opts):
                    self.pending_spell_damage_type = chosen[0] if chosen else -1
                    self.pending_spell_is_aoe     = False
                    self.pending_spell_targets    = []
                    self.pending_spell_slot       = s
                    self.pending_spell_idx        = si_
                    self.pending_spell_slot_level = slot_level_
                    type_name = next((lbl for lbl, val in elem_opts
                                      if val == self.pending_spell_damage_type), "?")
                    self._combat_log_add(f"Casting {sp_.name} ({type_name}) — click a target.")
                self._element_dialog.show(_on_elem, elem_opts, current_values=None, multi=False,
                                          title=f"{sp_.name}: damage type")
                return

            # Summon spells: pick an empty cell within range to manifest the creature, rather than
            # targeting a creature or placing an AoE. Routed here BEFORE the
            # geometry branches because Summon Dragon is Single geometry ("click a target").
            monster = SUMMON_SPELL_TO_MONSTER.get(sp_.name)
            if monster:
                self.pending_summon_slot       = s
                self.pending_summon_idx        = si_
                self.pending_summon_slot_level = slot_level_
                self.pending_summon_monster    = monster
                self._combat_log_add(
                    f"Casting {sp_.name} — click an empty cell within range to place the {monster}.")
                return

            # Emanation (a moves_with_caster Sphere) is always centered on the caster,
            # so there is no placement to choose — cast immediately on the caster's cell.
            if getattr(sp_, "moves_with_caster", False) and sp_.geometry == rpg.SpellGeometry.Sphere:
                self.pending_spell_slot       = s
                self.pending_spell_idx        = si_
                self.pending_spell_slot_level = slot_level_
                ci = self._current_agent_idx()
                origin = self.bm.placed_agents[ci].origin
                self._combat_log_add(f"Casting {sp_.name} — centered on caster.")
                self._resolve_spell_cast_aoe(rpg.Cell(origin.col, origin.row))
                return

            # Teleportation spells: select a destination, then optionally select additional targets
            if getattr(sp_, "teleportation_spell", False):
                self.pending_spell_is_aoe = True
                self.pending_spell_slot       = s
                self.pending_spell_idx        = si_
                self.pending_spell_slot_level = slot_level_
                self.pending_spell_targets    = []
                hint = f"click a destination ({sp_.teleport_range_ft} ft away)"
                self._combat_log_add(f"Casting {sp_.name} — {hint}.")
                return

            if sp_.geometry == rpg.SpellGeometry.Single:
                self.pending_spell_is_aoe = False
                self.pending_spell_targets = []
                hint = "click a target"
            elif sp_.geometry == rpg.SpellGeometry.Multiple:
                # Multiple geometry: collect N independent targets
                caster_level_ = self.combat.get_agent_stats(self.bm, idx).char_level
                num_targets = self.combat.get_num_targets_for_spell(sp_, slot_level_, caster_level_)
                self.pending_spell_is_aoe = False
                self.pending_spell_targets = []  # Will collect targets sequentially
                self.pending_spell_num_targets = num_targets
                hint = f"click {num_targets} target{'s' if num_targets != 1 else ''} ({0}/{num_targets})"
            else:
                # AoE (Line, Cone, Sphere, Square, Rectangle)
                self.pending_spell_is_aoe = True
                self.spell_anchor_cell    = None
                if sp_.geometry == rpg.SpellGeometry.Rectangle:
                    # Oriented wall: click an anchor, then click again to set
                    # direction/length (up to the spell's max length).
                    hint = "click the wall's start point"
                else:
                    hint = "click a map location"

            self.pending_spell_slot       = s
            self.pending_spell_idx        = si_
            self.pending_spell_slot_level = slot_level_
            self._combat_log_add(f"Casting {sp_.name} — {hint}.")

        def _ordinal(n):
            return {1:"1st",2:"2nd",3:"3rd"}.get(n, f"{n}th")

        # Build spell menu from available spells
        options = []
        for si in available_indices:
            sp = spells[si]
            sp_level = sp.level

            # Filter by casting_time based on which action button was clicked. (War Magic's list is
            # already filtered engine-side by available_war_magic_spells, so no extra filter here.)
            if slot == "action" and sp.casting_time == rpg.CastingTime.BonusAction:
                continue  # Skip bonus-action spells from the action menu
            elif slot == "bonus" and sp.casting_time != rpg.CastingTime.BonusAction:
                continue  # Skip non-bonus-action spells from the bonus menu

            if sp_level == 0:
                # Cantrip - always available
                def _pick_cantrip(s=slot, si_=si):
                    _activate(s, si_, 0)
                options.append((f"{sp.name} ∞", _pick_cantrip))
            else:
                # Leveled spell - check available slots for players
                if not stats.is_npc:
                    available_levels = []
                    for lvl in range(sp_level, 10):
                        if stats.spell_slots_remaining[lvl - 1] > 0:
                            available_levels.append((lvl, stats.spell_slots_remaining[lvl - 1]))

                    if not available_levels:
                        continue

                    # Add submenu for each available slot level
                    for slot_lvl, remaining in available_levels:
                        label = f"{sp.name} @ {_ordinal(slot_lvl)} ({remaining})"
                        def _pick_slot(s=slot, si_=si, sl=slot_lvl):
                            _activate(s, si_, sl)
                        options.append((label, _pick_slot))
                else:
                    # NPC: just add the spell (availability already checked by available_castable_spells)
                    def _pick_npc(s=slot, si_=si):
                        _activate(s, si_, 0)
                    options.append((sp.name, _pick_npc))

        if not options:
            self._combat_log_add("No available spells!")
            if slot == "action":
                self.action_used = True
            elif slot == "bonus":
                self.bonus_used = True
            # "war_magic": consume nothing — the Attack action's weapon attacks remain available.
            return

        if len(options) == 1:
            options[0][1]()  # Call the action directly
        else:
            px_popup = self._panel_x() + self._PANEL_PAD
            self.context_menu.show(
                (px_popup, 290),
                options,
                self.screen.get_size()
            )

    def _get_damage_type_names(self, magic_damage_types, physical_damage_types):
        """Convert damage type enums to their string names."""
        magic_damage_names = {
            rpg.MagicDamage.Acid: "Acid",
            rpg.MagicDamage.Cold: "Cold",
            rpg.MagicDamage.Fire: "Fire",
            rpg.MagicDamage.Force: "Force",
            rpg.MagicDamage.Lightning: "Lightning",
            rpg.MagicDamage.Necrotic: "Necrotic",
            rpg.MagicDamage.Poison: "Poison",
            rpg.MagicDamage.Psychic: "Psychic",
            rpg.MagicDamage.Radiant: "Radiant",
            rpg.MagicDamage.Thunder: "Thunder",
        }

        physical_damage_names = {
            rpg.PhysicalDamage.Bludgeoning: "Bludgeoning",
            rpg.PhysicalDamage.Piercing: "Piercing",
            rpg.PhysicalDamage.Slashing: "Slashing",
        }

        names = []
        for dmg_type in physical_damage_types:
            names.append(physical_damage_names.get(dmg_type, "Unknown"))
        for dmg_type in magic_damage_types:
            names.append(magic_damage_names.get(dmg_type, "Unknown"))

        return names

    def _get_damage_modifier_names(self, spell, tgt_agent):
        """Extract damage type names from spell and target multipliers. Returns dict with modifier info."""
        # Magic damage type names
        magic_damage_names = {
            rpg.MagicDamage.Acid: "Acid",
            rpg.MagicDamage.Cold: "Cold",
            rpg.MagicDamage.Fire: "Fire",
            rpg.MagicDamage.Force: "Force",
            rpg.MagicDamage.Lightning: "Lightning",
            rpg.MagicDamage.Necrotic: "Necrotic",
            rpg.MagicDamage.Poison: "Poison",
            rpg.MagicDamage.Psychic: "Psychic",
            rpg.MagicDamage.Radiant: "Radiant",
            rpg.MagicDamage.Thunder: "Thunder",
        }

        # Physical damage type names
        physical_damage_names = {
            rpg.PhysicalDamage.Bludgeoning: "Bludgeoning",
            rpg.PhysicalDamage.Piercing: "Piercing",
            rpg.PhysicalDamage.Slashing: "Slashing",
        }

        result = {
            "immune": [],
            "vulnerable": [],
            "resistant": [],
            "damage_types": []
        }

        if not spell or not tgt_agent:
            return result

        # Collect damage types from spell with their multipliers
        for dmg_roll in spell.magic_damage_rolls:
            dmg_type_name = magic_damage_names.get(dmg_roll.type, "Unknown")
            mult = tgt_agent.stats.get_magic_damage_multiplier(int(dmg_roll.type))

            result["damage_types"].append((dmg_type_name, mult))
            if mult == 0.0:
                result["immune"].append(dmg_type_name)
            elif mult == 2.0:
                result["vulnerable"].append(dmg_type_name)
            elif mult == 0.5:
                result["resistant"].append(dmg_type_name)

        for dmg_roll in spell.physical_damage_rolls:
            dmg_type_name = physical_damage_names.get(dmg_roll.type, "Unknown")
            mult = tgt_agent.stats.get_physical_damage_multiplier(int(dmg_roll.type))

            result["damage_types"].append((dmg_type_name, mult))
            if mult == 0.0:
                result["immune"].append(dmg_type_name)
            elif mult == 2.0:
                result["vulnerable"].append(dmg_type_name)
            elif mult == 0.5:
                result["resistant"].append(dmg_type_name)

        return result

    def _get_immunity_message(self, spell, tgt_agent, tr) -> str:
        """Check if target is immune to spell damage and return immunity message, or empty string."""
        if tr.total_damage > 0 or not spell or not tgt_agent:
            return ""

        mods = self._get_damage_modifier_names(spell, tgt_agent)
        if not mods["damage_types"]:
            return ""

        # Check if target is immune to all damage types
        all_immune = len(mods["immune"]) == len(mods["damage_types"])
        if all_immune and mods["immune"]:
            immune_str = ", ".join(mods["immune"])
            return f"Immune to {immune_str}"

        return ""

    def _get_vulnerability_message(self, spell, tgt_agent, tr) -> str:
        """Check if target is vulnerable to spell damage and return message with vulnerability indicator."""
        if not spell or not tgt_agent or tr.total_damage == 0:
            return ""

        mods = self._get_damage_modifier_names(spell, tgt_agent)
        if not mods["vulnerable"]:
            return ""

        # Check if all damage types are vulnerable
        if len(mods["vulnerable"]) == len(mods["damage_types"]):
            vuln_str = ", ".join(mods["vulnerable"])
            return f"{tr.total_damage} dmg (Vulnerable to {vuln_str})"

        return ""

    def _get_resistance_message(self, spell, tgt_agent, tr) -> str:
        """Check if target is resistant to spell damage and return message with resistance indicator."""
        if not spell or not tgt_agent or tr.total_damage == 0:
            return ""

        mods = self._get_damage_modifier_names(spell, tgt_agent)
        if not mods["resistant"]:
            return ""

        # Check if all damage types are resistant
        if len(mods["resistant"]) == len(mods["damage_types"]):
            resist_str = ", ".join(mods["resistant"])
            return f"{tr.total_damage} dmg (Resistant to {resist_str})"

        return ""

    # FLAG: Move to C++
    def _log_spell_results(self, result, cast_name: str, caster_idx: int = -1, spell_idx: int = -1):
        agents = self.bm.placed_agents
        spell = None
        if caster_idx >= 0 and spell_idx >= 0 and caster_idx < len(agents) and spell_idx < len(agents[caster_idx].spells):
            spell = agents[caster_idx].spells[spell_idx]

        for tr in result.target_results:
            tgt_name = agents[tr.target_idx].name if 0 <= tr.target_idx < len(agents) else "?"
            tgt_agent = agents[tr.target_idx] if 0 <= tr.target_idx < len(agents) else None

            if result.attack_type == rpg.SpellAttack.AttackRoll:
                # Check for damage modifiers in AttackRoll spells
                immunity_msg = self._get_immunity_message(spell, tgt_agent, tr)
                vuln_msg = self._get_vulnerability_message(spell, tgt_agent, tr)
                resist_msg = self._get_resistance_message(spell, tgt_agent, tr)

                modifier_suffix = ""
                if immunity_msg:
                    modifier_suffix = f" ({immunity_msg})"
                elif vuln_msg:
                    modifier_suffix = f" (Vulnerable to {', '.join(self._get_damage_modifier_names(spell, tgt_agent)['vulnerable'])})"
                elif resist_msg:
                    modifier_suffix = f" (Resistant to {', '.join(self._get_damage_modifier_names(spell, tgt_agent)['resistant'])})"

                msg = f"{cast_name}→{tgt_name}: {result.spell_name} {tr.log_message}{modifier_suffix}"
            elif result.attack_type == rpg.SpellAttack.Save:
                if spell and tgt_agent:
                    save_ability_map = {
                        rpg.SaveAbility.SaveStr: "STR",
                        rpg.SaveAbility.SaveDex: "DEX",
                        rpg.SaveAbility.SaveCon: "CON",
                        rpg.SaveAbility.SaveInt: "INT",
                        rpg.SaveAbility.SaveWis: "WIS",
                        rpg.SaveAbility.SaveCha: "CHA",
                    }
                    ability_str = save_ability_map.get(spell.save_ability, "???")
                    # Use the engine's actual save modifier (ability + proficiency + Paladin
                    # Aura of Protection), not a GUI recompute — otherwise auras stay invisible.
                    save_mod = tr.save_mod
                    save_total = tr.save_d20 + save_mod
                    # Surface the Aura of Protection contribution so it's visible in the log.
                    aura_bonus = self.combat.aura_save_bonus(self.bm, tr.target_idx)
                    aura_note = f" (incl. +{aura_bonus} Aura of Protection)" if aura_bonus > 0 else ""

                    result_str = "SAVED" if tr.saved else "FAILED"
                    dmg_str = f"{tr.total_healing} heal" if tr.total_healing else f"{tr.total_damage} dmg"
                    if tr.saved and tr.total_damage > 0:
                        dmg_str = f"{tr.total_damage // 2} dmg (half)"

                    # Check for damage modifiers (immunity > vulnerability > resistance > normal)
                    immunity_msg = self._get_immunity_message(spell, tgt_agent, tr)
                    if immunity_msg:
                        dmg_str = immunity_msg
                    else:
                        vuln_msg = self._get_vulnerability_message(spell, tgt_agent, tr)
                        if vuln_msg:
                            dmg_str = vuln_msg
                        else:
                            resist_msg = self._get_resistance_message(spell, tgt_agent, tr)
                            if resist_msg:
                                dmg_str = resist_msg

                    # Add condition information to result string
                    condition_suffix = ""
                    if not tr.saved and spell and spell.conditions:
                        condition_names = ", ".join([c.condition_name for c in spell.conditions])
                        condition_suffix = f" → {condition_names}"

                    msg = (f"{cast_name}→{tgt_name}: {ability_str} save — "
                           f"rolled {tr.save_d20} + {save_mod}{aura_note} = {save_total} vs DC {tr.save_dc} — "
                           f"{result_str}{condition_suffix} — {dmg_str}"
                           f"{' — DOWN' if tr.target_down else ''}")
                else:
                    saved_str = " (saved — half)" if tr.saved else ""
                    if tr.total_healing:
                        msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                               f"HEAL {tr.total_healing}{saved_str}")
                    else:
                        # Check for damage modifiers (immunity > vulnerability > resistance > normal)
                        immunity_msg = self._get_immunity_message(spell, tgt_agent, tr)
                        if immunity_msg:
                            dmg_text = immunity_msg
                        else:
                            vuln_msg = self._get_vulnerability_message(spell, tgt_agent, tr)
                            if vuln_msg:
                                dmg_text = f"{vuln_msg}{saved_str}"
                            else:
                                resist_msg = self._get_resistance_message(spell, tgt_agent, tr)
                                if resist_msg:
                                    dmg_text = f"{resist_msg}{saved_str}"
                                else:
                                    dmg_text = f"{tr.total_damage} dmg{saved_str}"
                        msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                               f"{dmg_text}"
                               f"{' — DOWN' if tr.target_down else ''}")
            else:  # Automatic
                if tr.total_healing:
                    msg = f"{cast_name}→{tgt_name}: {result.spell_name} HEAL {tr.total_healing}"
                else:
                    # Check for damage modifiers (immunity > vulnerability > resistance > normal)
                    immunity_msg = self._get_immunity_message(spell, tgt_agent, tr)
                    if immunity_msg:
                        dmg_text = immunity_msg
                    else:
                        vuln_msg = self._get_vulnerability_message(spell, tgt_agent, tr)
                        if vuln_msg:
                            dmg_text = vuln_msg
                        else:
                            resist_msg = self._get_resistance_message(spell, tgt_agent, tr)
                            if resist_msg:
                                dmg_text = resist_msg
                            else:
                                dmg_text = f"{tr.total_damage} dmg"
                    msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                           f"{dmg_text}"
                           f"{' — DOWN' if tr.target_down else ''}")
            self._combat_log_add(msg)

    # FLAG: Move to C++
    def _on_long_rest(self):
        """Reset all spell slots, NPC spell uses, decrement exhaustion by 1, and regenerate Portent Dice."""
        # Apply combat engine long rest (restores resources, regenerates Portent Dice)
        self.combat.apply_long_rest(self.bm)

        agents = self.bm.placed_agents
        for idx in range(len(agents)):
            # Decrement exhaustion by 1 (minimum 0)
            cond = self.combat.get_agent_conditions(self.bm, idx)
            if cond.exhaustion_level > 0:
                cond.exhaustion_level = max(0, cond.exhaustion_level - 1)
                self.combat.set_agent_conditions(self.bm, idx, cond)
            # Reset NPC spell uses: copy uses_max back to uses_remaining
            if idx in self._agent_meta:
                spells = self.combat.get_agent_spells(self.bm, idx)
                for spell in spells:
                    if spell.uses_max > 0:
                        spell.uses_remaining = spell.uses_max
        if self.combat_active:
            self._combat_log_add("Long rest — spell slots, resources, and Portent Dice restored.")
        self._report_celestial_resilience()

    def _on_short_rest(self):
        """Restore short-rest resources (Warlock Pact Magic slots, Monk Focus Points, etc.)."""
        self.combat.apply_short_rest(self.bm)
        self._combat_log_add("Short rest — short-rest resources restored (e.g. Pact Magic slots).")
        self._report_celestial_resilience()

    def _report_celestial_resilience(self):
        """Surface Celestial Resilience temp HP in the combat log so the L10 gate is visible."""
        agents = self.bm.placed_agents
        for idx in range(len(agents)):
            s = self.combat.get_agent_stats(self.bm, idx)
            if (s.character_class == rpg.CharacterClass.Warlock and
                    s.warlock_subclass == rpg.WarlockSubclass.Celestial and
                    s.char_level >= 10 and s.temp_hp > 0):
                self._combat_log_add(f"{agents[idx].name}: Celestial Resilience — {s.temp_hp} temp HP")

    # FLAG: Move to C++
    def _show_pending_reaction_menu(self):
        """Render the menu for whatever reaction checkpoint the engine is parked on (OA, …).

        The C++ engine owns OA detection + resolution via the flow-checkpoint API
        (begin_move → pending_decision → submit_decision). This just
        draws ctx.options at the reactor and routes the click back through submit_decision."""
        pd = self.combat.pending_decision()
        if not pd.active:
            self._reaction_finish()
            return
        ctx = pd.ctx
        agents = self.bm.placed_agents
        if 0 <= ctx.reactor_idx < len(agents) and 0 <= ctx.source_idx < len(agents):
            if ctx.window == rpg.ReactionWindow.OnDeclareCast:
                self._combat_log_add(
                    f"{agents[ctx.reactor_idx].name} may react to {agents[ctx.source_idx].name}'s spell!")
            elif ctx.window == rpg.ReactionWindow.OnHit:
                kind = "spell attack" if ctx.spell_idx >= 0 else "attack"
                # The OnHit defender window may offer Shield (negate) and/or Uncanny Dodge (halve).
                feats = [o.feature for o in ctx.options
                         if o.kind == rpg.ReactionOptionKind.Feature]
                names = {"Shield": "Shield", "UncannyDodge": "Uncanny Dodge",
                         "SuperiorHuntersDefense": "Superior Hunter's Defense",
                         "DefensiveDuelist": "Defensive Duelist", "Parry": "Parry"}
                choices = " / ".join(names.get(f, f) for f in feats) or "Shield"
                self._combat_log_add(
                    f"{agents[ctx.reactor_idx].name} may react ({choices}) vs "
                    f"{agents[ctx.source_idx].name}'s {kind}!")
            elif ctx.window == rpg.ReactionWindow.OnD20Seen:
                self._combat_log_add(
                    f"{agents[ctx.reactor_idx].name} may lower {agents[ctx.source_idx].name}'s "
                    f"attack roll ({ctx.d20_value}) — Bend Luck / Cutting Words / Silvery Barbs / Warding Flare!")
            elif ctx.window == rpg.ReactionWindow.OnSaveFail:
                who = ("their own" if ctx.reactor_idx == ctx.source_idx
                       else f"{agents[ctx.source_idx].name}'s")
                self._combat_log_add(
                    f"{agents[ctx.reactor_idx].name} may reroll {who} failed save "
                    f"({ctx.d20_value}) — Countercharm / Indomitable!")
            elif ctx.window == rpg.ReactionWindow.OnTurnStartNearby:
                if ctx.reactor_idx == ctx.source_idx:
                    # Self-option: the World Tree Barbarian may grant temp HP at its own turn start.
                    self._combat_log_add(
                        f"{agents[ctx.source_idx].name} may grant a creature within 10 ft "
                        f"temp HP — Vitality of the Tree!")
                else:
                    self._combat_log_add(
                        f"{agents[ctx.reactor_idx].name} may react to {agents[ctx.source_idx].name} "
                        f"starting its turn nearby — Branches of the Tree!")
            else:
                # LeftReach (OA). A Sentinel-feated reactor is flagged so the player knows a hit will
                # drop the mover's speed to 0 (and that it provokes even through Disengage).
                try:
                    has_sentinel = self.combat.get_agent_stats(self.bm, ctx.reactor_idx).has_sentinel
                except Exception:
                    has_sentinel = False
                if has_sentinel:
                    self._combat_log_add(
                        f"{agents[ctx.reactor_idx].name} gets a Sentinel opportunity attack vs "
                        f"{agents[ctx.source_idx].name} (a hit stops it — speed → 0)!")
                else:
                    self._combat_log_add(
                        f"{agents[ctx.reactor_idx].name} gets an opportunity attack vs {agents[ctx.source_idx].name}!")
        def _make_cb(i, feature):
            # Vitality of the Tree needs a target pick before submitting; everything else submits at once.
            if feature == "VitalityOfTheTree":
                return lambda i=i: self._begin_vitality_target_pick(i)
            return lambda i=i: self._submit_reaction(i)
        options = [(opt.label, _make_cb(i, opt.feature)) for i, opt in enumerate(ctx.options)]
        px, py = self._agent_screen_pos(ctx.reactor_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _submit_reaction(self, option_index: int):
        """Resume the parked move with the chosen reaction option, then chain to the next
        checkpoint or finish the move."""
        resp = rpg.ReactionResponse()
        resp.option = option_index
        status = self.combat.submit_decision(self.bm, resp)
        self._flush_combat_log()
        self._sync_spell_effect_cache()
        self._update_attack_overlay()
        if status == rpg.FlowStatus.AwaitingDecision:
            self._show_pending_reaction_menu()
        else:
            self._reaction_finish()

    def _begin_vitality_target_pick(self, option_index: int):
        """World Tree Vitality of the Tree (turn-start self-option): the player picked the option;
        now arm a target click so they choose which creature within 10 ft gets the temp HP. The
        OnTurnStartNearby window stays parked until _resolve_vitality_target submits the response."""
        self._vitality_option_index = option_index
        self.pending_vitality_target = True
        pd = self.combat.pending_decision()
        src = pd.ctx.source_idx if pd.active else -1
        agents = self.bm.placed_agents
        name = agents[src].name if 0 <= src < len(agents) else "?"
        self._combat_log_add(f"{name}: click a creature within 10 ft to grant temporary HP (Vitality of the Tree).")
        self._flush_combat_log()

    def _vitality_in_range(self, src: int, target: int) -> bool:
        """10 ft (2-cell) footprint Chebyshev check, mirroring C++ threateningAgents(src, 2)."""
        agents = self.bm.placed_agents
        if not (0 <= src < len(agents) and 0 <= target < len(agents)) or src == target:
            return False
        s = agents[src]; o = agents[target]
        dc = max(s.origin.col - o.origin.col, o.origin.col - (s.origin.col + s.size - 1), 0)
        dr = max(s.origin.row - o.origin.row, o.origin.row - (s.origin.row + s.size - 1), 0)
        return max(dc, dr) <= 2

    def _resolve_vitality_target(self, target_idx: int):
        """Submit the parked Vitality of the Tree response with the clicked target, then resume the
        turn-start flow (which completes the window). Re-prompts on an invalid/out-of-range pick so
        the once-per-turn grant isn't wasted."""
        pd = self.combat.pending_decision()
        src = pd.ctx.source_idx if pd.active else -1
        agents = self.bm.placed_agents
        if (target_idx == src or not self._vitality_in_range(src, target_idx)
                or not (0 <= target_idx < len(agents))
                or self.combat.get_agent_stats(self.bm, target_idx).hp_cur <= 0):
            self._combat_log_add("Pick a living creature within 10 ft (or choose Skip).")
            self._flush_combat_log()
            return  # keep pending_vitality_target armed for another click
        self.pending_vitality_target = False
        resp = rpg.ReactionResponse()
        resp.option     = self._vitality_option_index
        resp.target_idx = target_idx
        self._vitality_option_index = -1
        status = self.combat.submit_decision(self.bm, resp)
        self._flush_combat_log()
        self._sync_spell_effect_cache()
        self._update_attack_overlay()
        if status == rpg.FlowStatus.AwaitingDecision:
            self._show_pending_reaction_menu()
        else:
            self._reaction_finish()

    def _sync_spell_effect_cache(self):
        """Remove cache entries for spell effects that have been removed in C++."""
        active_effect_ids = {effect.effect_id for effect in self.bm.active_spell_effects}
        to_remove = [eid for eid in self._effect_meta if eid not in active_effect_ids]
        for eid in to_remove:
            del self._effect_meta[eid]

    def _agent_screen_pos(self, agent_idx: int) -> tuple:
        """Get screen position of agent for context menu anchor."""
        agents = self.bm.placed_agents
        if agent_idx >= len(agents):
            return (100, 100)
        ag = agents[agent_idx]
        cpx = int(self.bm.cell_pixel_size)
        x = ag.origin.col * cpx + cpx // 2
        y = ag.origin.row * cpx + cpx // 2
        return (x, y)


    def _after_move_committed(self, idx: int):
        """Refresh GUI state after the engine commits a (possibly OA-interrupted) move.

        The engine (begin_move/submit_decision) has already performed the actual movement and
        resolved any opportunity attacks; this only syncs render caches, budgets, slip/hidden,
        and overlays. Replaces the old _complete_pending_move."""
        agents = self.bm.placed_agents
        if idx < 0 or idx >= len(agents):
            return
        ag = agents[idx]
        self._flush_combat_log()
        self._sync_spell_effect_cache()
        # Slip ends the turn (the engine sets slipped_this_turn during the committed move).
        if ag.conditions.slipped_this_turn:
            self._combat_log_add(f"{ag.name} slipped and cannot act — turn ends.")
            self._advance_turn()
            self._update_reach()
            self._update_attack_overlay()
            return
        # Hidden agent detection after moving into LOS.
        if ag.conditions.hidden:
            in_combat = len(self.initiative_order) > 0
            detection_msg = self.combat.check_hidden_agent_detection(self.bm, idx, in_combat)
            if detection_msg:
                self._combat_log_add(detection_msg)
        self.move_remaining_walk   = ag.walk_remaining
        self.move_remaining_fly    = ag.fly_remaining
        self.move_remaining_swim   = ag.swim_remaining
        self.move_remaining_burrow = ag.burrow_remaining
        self.last_movement_dist    = getattr(self, "_reaction_dist_moved", 0)
        self.selected_idx          = idx
        self._update_reach()
        self._update_attack_overlay()

    # FLAG: Move to C++
    def _apply_pact_slot_level(self, caster_idx: int, sp, action):
        """Warlocks cast leveled spells at their single Pact Magic slot level (and consume
        that slot). Cantrips (level 0) are unaffected."""
        if sp.level >= 1:
            cs = self.combat.get_agent_stats(self.bm, caster_idx)
            if cs.character_class == rpg.CharacterClass.Warlock:
                pl = cs.pact_slot_level()
                if pl > 0:
                    action.slot_level = pl

    def _consume_cast_slot(self, slot: str, caster_idx: int):
        """Charge the action economy for a resolved cast. Normally a cast consumes the whole
        action (or bonus action). War Magic (slot=='war_magic') instead replaces ONE weapon attack
        inside the Attack action: mark the once-per-Attack-action gate, spend one attack, and either
        re-prompt for the remaining attack(s) or end the action."""
        if slot == "war_magic":
            self.combat.mark_war_magic_used(self.bm, caster_idx)
            self.attacks_remaining -= 1
            if self.attacks_remaining > 0:
                # War Magic replaced one attack; DISARM between attacks so the player can move. The
                # standing "⚔ Attack (N)" button resumes the remaining attack(s) — count preserved,
                # and war_magic_used stays set (only a fresh Attack-action seed clears it) so the
                # substitution option won't reappear.
                self.pending_attack_slot = ""
                rem = self.attacks_remaining
                nm = (self.bm.placed_agents[caster_idx].name
                      if 0 <= caster_idx < len(self.bm.placed_agents) else "?")
                self._combat_log_add(
                    f"{nm}: {rem} attack{'s' if rem != 1 else ''} remaining — "
                    f"move if you wish, then click Attack to continue.")
            else:
                self.attacks_remaining     = 0
                self.action_used           = True
                self._attack_sequence_slot = ""
        elif slot == "action":
            self.action_used = True
        else:
            self.bonus_used = True

    def _resolve_summon(self, cell):
        """Place a summoned creature at `cell` (Phase 3).

        Manual-control summon: it shares the summoner's initiative count (acts immediately
        after them) and is auto-dismissed when the summoner loses concentration — that cascade
        lives in C++ (dropConcentration scans summoner_idx and tombstones via removed_from_play).
        The creature is spawned non-destructively (bm.spawn_agent) so no existing agent's runtime
        state is disturbed."""
        caster_idx = self._current_agent_idx()
        slot       = self.pending_summon_slot
        monster    = self.pending_summon_monster
        spell_idx  = self.pending_summon_idx
        slot_level = self.pending_summon_slot_level
        if caster_idx < 0 or not slot or not monster:
            return
        spells = self.combat.get_agent_spells(self.bm, caster_idx)
        sp = spells[spell_idx] if 0 <= spell_idx < len(spells) else None
        mob_stats = self.mob_stats_json.get(monster)
        if sp is None or not mob_stats:
            self._combat_log_add(f"Summon failed: missing spell or '{monster}' stat block.")
            return

        # Validate placement: in range, line of sight, unoccupied.
        size   = self._size_category_to_grid_size(mob_stats.get("size", "Medium"))
        caster = self.bm.placed_agents[caster_idx]
        dist_cells = math.hypot(cell.col - caster.origin.col, cell.row - caster.origin.row)
        if dist_cells * 5.0 > sp.range + 1e-6:
            self._combat_log_add("Out of range — pick a closer cell.")
            return
        if not self.bm.has_line_of_sight(caster.origin, caster.size, cell, size):
            self._combat_log_add("No line of sight to that cell.")
            return
        if not self._can_place(cell, size):
            self._combat_log_add("That cell is blocked or occupied.")
            return

        # Spawn WITHOUT rebuilding existing agents (preserves HP/conditions/concentration).
        cfg = rpg.AgentConfig()
        cfg.name        = monster
        cfg.sprite_path = self._get_mob_sprite_path(monster)
        cfg.size        = size
        cfg.start_col   = cell.col
        cfg.start_row   = cell.row
        new_idx = self.bm.spawn_agent(cfg)
        if new_idx < 0:
            self._combat_log_add("Summon failed: could not place the creature.")
            return

        # Stats + auto-weapons from the monster JSON (same path as bestiary placement).
        self.combat.set_agent_stats(self.bm, new_idx, self._mob_stats_to_d_d_stats(mob_stats))
        weapons = list(self.combat.get_agent_weapons(self.bm, new_idx))
        if not self._has_real_weapons(weapons):
            for i, w in enumerate(self._auto_weapons_from_mob_stats(mob_stats)[:3]):
                weapons[i] = w
            self.combat.set_agent_weapons(self.bm, new_idx, weapons)
        # Innate spells from the conjured creature's stat block (no-op for non-casters).
        self._load_npc_spells_from_record(new_idx, mob_stats)

        # Link summon → summoner + spell (drives dismiss-on-concentration-loss in C++).
        self.bm.set_agent_summoner_idx(new_idx, caster_idx)
        self.bm.set_agent_summon_spell(new_idx, sp.name)
        # Inherit the summoner's team so the conjured creature fights alongside it (and is
        # spared by the summoner's selective spells / can be healed by them).
        self.bm.set_agent_faction(new_idx, self.bm.get_agent_faction(caster_idx))

        # Concentration: a new concentration spell replaces the caster's previous one
        # (which dismisses any creature the earlier spell had summoned).
        if sp.requires_concentration:
            cond = self.combat.get_agent_conditions(self.bm, caster_idx)
            if cond.concentrating:
                self._drop_concentration_for_agent(caster_idx)
                cond = self.combat.get_agent_conditions(self.bm, caster_idx)
            cond.concentrating    = True
            cond.concentrating_on = sp.name
            self.combat.set_agent_conditions(self.bm, caster_idx, cond)

        # Spend the spell slot (PC slots only; NPC spell-group casting is out of scope here).
        cstats = self.combat.get_agent_stats(self.bm, caster_idx)
        if not cstats.is_npc and slot_level >= 1:
            slots = list(cstats.spell_slots_remaining)
            if slots[slot_level - 1] > 0:
                slots[slot_level - 1] -= 1
                cstats.spell_slots_remaining = slots
                self.combat.set_agent_stats(self.bm, caster_idx, cstats)

        # Insert into initiative immediately after the summoner (shares its count).
        if self.combat_active and self.initiative_order:
            caster_pos = next((p for p, e in enumerate(self.initiative_order)
                               if e.agent_idx == caster_idx), -1)
            if caster_pos >= 0:
                base = self.initiative_order[caster_pos]
                entry = rpg.InitiativeEntry()
                entry.agent_idx = new_idx
                entry.d20       = base.d20
                entry.modifier  = base.modifier
                entry.total     = base.total
                self.initiative_order.insert(caster_pos + 1, entry)

        self._combat_log_add(f"{caster.name} summons a {monster}!")

        # Clear pending state + consume the action economy.
        self.pending_summon_slot       = ""
        self.pending_summon_idx        = 0
        self.pending_summon_slot_level = 0
        self.pending_summon_monster    = ""
        self.summon_hover_cell         = None
        self.sprites.clear()
        self._consume_cast_slot(slot, caster_idx)

    # ── Beast Master: Primal Companion (L3) ─────────────────────────────────
    def _find_companion_idx(self, ranger_idx: int) -> int:
        """Index of the Ranger's live Primal Companion, or -1 if none is active.
        Tombstoned (dismissed/dead) companions are skipped."""
        for i, pt in enumerate(self.bm.placed_agents):
            if (pt.summoner_idx == ranger_idx and not pt.removed_from_play
                    and pt.summon_spell == "Primal Companion"):
                return i
        return -1

    def _show_companion_menu(self):
        """Beast Master L3+: summon a Beast of the Land/Sea/Sky, or dismiss the
        active companion. Mirrors the Wild Shape menu (context_menu)."""
        idx = self._current_agent_idx()
        if idx < 0:
            return
        stats = self.combat.get_agent_stats(self.bm, idx)
        if (stats.character_class != rpg.CharacterClass.Ranger or
                stats.ranger_subclass != rpg.RangerSubclass.BeastMaster or
                stats.char_level < 3):
            self._combat_log_add("Only a Beast Master Ranger (L3+) has a Primal Companion.")
            return
        existing = self._find_companion_idx(idx)
        if existing >= 0:
            self._dismiss_companion(idx, existing)
            return
        items = [(f"🐾 Beast of the {form}",
                  lambda f=form: self._summon_companion(idx, f))
                 for form in ("Land", "Sea", "Sky")]
        self.context_menu.show(pygame.mouse.get_pos(), items, self.screen.get_size())

    def _dismiss_companion(self, ranger_idx: int, companion_idx: int):
        """Tombstone the companion (removed_from_play) like a dismissed summon: it
        stays in placedAgents_/initiative so indices stay valid, but is skipped in
        turns and rendering."""
        name = self.bm.placed_agents[companion_idx].name
        self.bm.set_agent_removed_from_play(companion_idx, True)
        self._combat_log_add(f"{self.bm.placed_agents[ranger_idx].name} dismisses {name}.")
        self.sprites.clear()

    def _summon_companion(self, ranger_idx: int, form: str):
        """Conjure the Beast Master's Primal Companion (Beast of the Land/Sea/Sky).

        Scaled off the Ranger: HP = base + per-level x Ranger level, AC = 13 + PB,
        attack to-hit = Ranger's spell-attack modifier (PB + WIS mod), damage bonus = PB
        (RAW), independent of the beast's own ability mod. The companion is summon-linked
        (faction/summoner) so it shares the Ranger's initiative and tombstones on dismissal/
        death — same machinery as summon spells (memory `summoning_plan`)."""
        if not (0 <= ranger_idx < len(self.bm.placed_agents)):
            return
        if self._find_companion_idx(ranger_idx) >= 0:
            self._combat_log_add("A Primal Companion is already active — dismiss it first.")
            return
        import json
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, "primal_companions.json")
        try:
            with open(path, 'r') as f:
                blocks = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._combat_log_add("Error loading primal_companions.json!")
            return
        block = next((b for b in blocks if b.get("form") == form), None)
        if block is None:
            self._combat_log_add(f"Unknown companion form '{form}'.")
            return

        rstats = self.combat.get_agent_stats(self.bm, ranger_idx)
        ranger = self.bm.placed_agents[ranger_idx]
        size = self._size_category_to_grid_size(block.get("size", "Medium"))
        cell = self._find_free_cell_near(ranger.origin.col, ranger.origin.row, size)
        if cell is None:
            self._combat_log_add("No free space next to the Ranger to summon the companion.")
            return

        pb  = rstats.prof_bonus
        lvl = rstats.char_level
        stats_d, weapon_d = compute_companion_loadout(
            block, pb, lvl, (rstats.wis - 10) // 2)

        cfg = rpg.AgentConfig()
        cfg.name        = block.get("name", "Primal Companion")
        cfg.sprite_path = self._get_mob_sprite_path(cfg.name)
        cfg.size        = size
        cfg.start_col   = cell.col
        cfg.start_row   = cell.row
        new_idx = self.bm.spawn_agent(cfg)
        if new_idx < 0:
            self._combat_log_add("Could not place the companion.")
            return

        cs = rpg.Stats()
        for field, val in stats_d.items():
            setattr(cs, field, val)
        self.combat.set_agent_stats(self.bm, new_idx, cs)
        self.combat.set_agent_weapons(
            self.bm, new_idx, [_dict_to_weapon(weapon_d), rpg.Weapon(), rpg.Weapon()])

        # Link companion -> Ranger (faction/summoner/summon name) so it fights alongside
        # the Ranger and tombstones on dismissal — same path as summon spells.
        self.bm.set_agent_summoner_idx(new_idx, ranger_idx)
        self.bm.set_agent_summon_spell(new_idx, "Primal Companion")
        self.bm.set_agent_faction(new_idx, self.bm.get_agent_faction(ranger_idx))

        # Remember the chosen form on the Ranger so it round-trips on save/load.
        rstats.primal_companion = getattr(rpg.PrimalCompanion, form)
        self.combat.set_agent_stats(self.bm, ranger_idx, rstats)

        # Share the Ranger's initiative count (acts right after them), like a summon.
        if self.combat_active and self.initiative_order:
            rpos = next((p for p, e in enumerate(self.initiative_order)
                         if e.agent_idx == ranger_idx), -1)
            if rpos >= 0:
                base = self.initiative_order[rpos]
                entry = rpg.InitiativeEntry()
                entry.agent_idx = new_idx
                entry.d20       = base.d20
                entry.modifier  = base.modifier
                entry.total     = base.total
                self.initiative_order.insert(rpos + 1, entry)

        self.sprites.clear()
        self._combat_log_add(
            f"{ranger.name} summons a {cfg.name} (HP {stats_d['hp_max']}, "
            f"AC {stats_d['base_ac']}"
            f"{', 2 attacks' if stats_d['num_attacks'] > 1 else ''}).")

    # ── Chromatic Orb leap chain (GUI picker) ──────────────────────────────────
    def _is_chromatic_pending(self) -> bool:
        """True when the spell currently being aimed is Chromatic Orb."""
        sp = self._pending_spell()
        return sp is not None and sp.name == "Chromatic Orb"

    def _footprint_dist_ft(self, a_idx: int, b_idx: int) -> int:
        """Chebyshev footprint distance in feet (5 ft / cell), or -1 for bad indices."""
        agents = self.bm.placed_agents
        if not (0 <= a_idx < len(agents) and 0 <= b_idx < len(agents)):
            return -1
        s = agents[a_idx]; o = agents[b_idx]
        dc = max(s.origin.col - o.origin.col, o.origin.col - (s.origin.col + s.size - 1), 0)
        dr = max(s.origin.row - o.origin.row, o.origin.row - (s.origin.row + s.size - 1), 0)
        return max(dc, dr) * 5

    def _chromatic_last_hop(self) -> int:
        """The creature the next leap would spring from (primary, or the last chained hop)."""
        return self.pending_chromatic_chain[-1] if self.pending_chromatic_chain \
            else self.pending_chromatic_primary

    def _enter_chromatic_chain(self, primary_idx: int):
        """Primary target chosen — switch to leap-chain collection mode (no cast yet)."""
        self.pending_chromatic_active  = True
        self.pending_chromatic_primary = primary_idx
        self.pending_chromatic_chain   = []
        name = self.bm.placed_agents[primary_idx].name
        self._combat_log_add(
            f"Chromatic Orb → {name}. Click leap targets in order (≤30 ft each hop); "
            f"Enter to cast, Esc to cancel.")

    def _chromatic_add_leap(self, hit: int):
        """Validate and append a clicked creature to the leap chain (or explain the rejection)."""
        if hit < 0:
            return
        caster_idx = self._current_agent_idx()
        if hit == caster_idx:
            self._combat_log_add("The orb can't leap to its caster.")
            return
        if hit == self.pending_chromatic_primary or hit in self.pending_chromatic_chain:
            self._combat_log_add("That creature is already in the chain.")
            return
        if self._are_allies(caster_idx, hit):
            self._combat_log_add("The orb leaps to foes, not allies.")
            return
        if self.combat.get_agent_stats(self.bm, hit).hp_cur <= 0:
            self._combat_log_add("That creature is already down.")
            return
        prev = self._chromatic_last_hop()
        dist = self._footprint_dist_ft(prev, hit)
        if dist < 0 or dist > 30:
            self._combat_log_add(
                f"Too far — {self.bm.placed_agents[hit].name} is {dist} ft from the previous hop (max 30).")
            return
        self.pending_chromatic_chain.append(hit)
        self._combat_log_add(
            f"  leap {len(self.pending_chromatic_chain)} → {self.bm.placed_agents[hit].name} ({dist} ft)")

    def _finalize_chromatic_cast(self):
        """Enter pressed — cast Chromatic Orb with the collected leap chain."""
        primary = self.pending_chromatic_primary
        if primary < 0:
            return
        self.pending_chromatic_active = False
        # _resolve_spell_cast reads pending_chromatic_chain and clears the chain state.
        self._resolve_spell_cast(primary)

    def _cancel_chromatic_chain(self):
        self.pending_chromatic_active  = False
        self.pending_chromatic_primary = -1
        self.pending_chromatic_chain   = []
        self.pending_spell_slot        = ""
        self.pending_spell_is_aoe      = False
        self.spell_hover_cell          = None
        self._combat_log_add("Chromatic Orb cancelled.")

    def _resolve_spell_cast(self, target_idx: int):
        caster_idx = self._current_agent_idx()
        slot       = self.pending_spell_slot
        if caster_idx < 0 or not slot:
            return

        spells_orig = self.combat.get_agent_spells(self.bm, caster_idx)
        sp = spells_orig[self.pending_spell_idx]

        # For Multiple geometry spells, collect targets until we have enough
        if sp.geometry == rpg.SpellGeometry.Multiple:
            self.pending_spell_targets.append(target_idx)

            targets_collected = len(self.pending_spell_targets)
            targets_needed = self.pending_spell_num_targets

            if targets_collected < targets_needed:
                # Still collecting targets
                self._combat_log_add(f"Target selected ({targets_collected}/{targets_needed})")
                return
            # else: we have all targets, fall through to execute

        action = rpg.SpellAction()
        action.caster_idx     = caster_idx
        action.spell_idx      = self.pending_spell_idx
        action.slot_level     = self.pending_spell_slot_level
        action.target_indices = self.pending_spell_targets if sp.geometry == rpg.SpellGeometry.Multiple else [target_idx]
        action.damage_type_override = self.pending_spell_damage_type  # cast-time element choice (-1 = none)
        # Chromatic Orb's player-chosen leap chain (empty for every other spell / an un-chained cast).
        action.chromatic_leap_targets = list(self.pending_chromatic_chain)
        self._apply_pact_slot_level(caster_idx, sp, action)

        # Cast through the OnDeclareCast window (begin_cast): a targeted creature may react before the
        # spell resolves (Shield vs Magic Missile). begin_cast resolves inline when no reaction is
        # offered (Completed) or parks at the reaction checkpoint (AwaitingDecision); _finish_cast does
        # the post-resolution logging in both cases.
        # Beast Master L15 Share Spells: remember whether this was a Self-range buff cast on the
        # Ranger itself (Single geometry, range 0, target == caster) so _finish_cast can duplicate
        # it onto the Primal Companion within 30 ft after the cast resolves.
        self_target = (sp.geometry == rpg.SpellGeometry.Single and sp.range == 0 and
                       target_idx == caster_idx)
        self._cast_post = dict(caster_idx=caster_idx, slot=slot, spell_idx=self.pending_spell_idx,
                               aoe=False, self_target=self_target,
                               slot_level=self.pending_spell_slot_level)
        self._reaction_finish = self._finish_cast

        self.pending_spell_slot        = ""
        self.pending_spell_is_aoe      = False
        self.pending_spell_num_targets = 0
        self.pending_spell_targets     = []
        self.pending_spell_damage_type = -1
        self.spell_hover_cell          = None
        self.pending_chromatic_active  = False
        self.pending_chromatic_primary = -1
        self.pending_chromatic_chain   = []

        status = self.combat.begin_cast(self.bm, action)
        self._flush_combat_log()
        if status == rpg.FlowStatus.AwaitingDecision:
            self._show_pending_reaction_menu()
        else:
            self._finish_cast()

    def _finish_cast(self):
        """Post-resolution handling once a begin_cast flow completes (immediately or after the
        OnDeclareCast reaction window). Reads the result from last_cast_result() and logs/consumes the
        slot using the context captured in self._cast_post."""
        ctx        = self._cast_post
        caster_idx = ctx["caster_idx"]
        result     = self.combat.last_cast_result()
        self._flush_combat_log()

        agents    = self.bm.placed_agents
        cast_name = agents[caster_idx].name if caster_idx < len(agents) else "?"
        # A Counterspell fizzled the cast before it resolved: the action is still spent (wasted), but
        # the engine never ran executeSpell, so the slot is retained (2024 rules). Report it cleanly
        # rather than as "invalid" (the Counterspell save is already in the combat log).
        if self.combat.last_cast_countered():
            self._combat_log_add(f"{cast_name}'s spell was countered!")
            self._sync_spell_effect_cache()
            self._consume_cast_slot(ctx["slot"], caster_idx)
            return
        if not result.valid:
            self._combat_log_add(f"{cast_name}: spell failed (invalid)")
            # If the agent slipped and can't act, auto-advance their turn (AoE cast path).
            if ctx.get("aoe") and 0 <= caster_idx < len(agents) and agents[caster_idx].conditions.slipped_this_turn:
                self._combat_log_add(f"{cast_name} slipped and cannot act — turn ends.")
                self._advance_turn()
            return
        if ctx.get("aoe") and not result.target_results:
            self._combat_log_add(f"{cast_name}: {result.spell_name} — no targets in area")
        else:
            self._log_spell_results(result, cast_name, caster_idx, ctx["spell_idx"])
        # Beast Master L15 Share Spells: a Self-range buff the Ranger cast on itself also affects
        # its Primal Companion within 30 ft.
        if ctx.get("self_target"):
            self._share_spell_with_companion(caster_idx, ctx["spell_idx"], ctx.get("slot_level", 0))
        # Clear spell effect cache entries for any removed effects (e.g., from concentration loss)
        self._sync_spell_effect_cache()
        self._consume_cast_slot(ctx["slot"], caster_idx)

    def _companion_in_range(self, ranger_idx: int, comp_idx: int, ft: int) -> bool:
        """Chebyshev footprint distance check (5 ft / cell), mirroring _vitality_in_range."""
        agents = self.bm.placed_agents
        if not (0 <= ranger_idx < len(agents) and 0 <= comp_idx < len(agents)) or ranger_idx == comp_idx:
            return False
        s = agents[ranger_idx]; o = agents[comp_idx]
        dc = max(s.origin.col - o.origin.col, o.origin.col - (s.origin.col + s.size - 1), 0)
        dr = max(s.origin.row - o.origin.row, o.origin.row - (s.origin.row + s.size - 1), 0)
        return max(dc, dr) * 5 <= ft

    def _share_spell_with_companion(self, caster_idx: int, spell_idx: int, slot_level: int):
        """Beast Master L15 Share Spells: re-apply a Self-range buff to the Ranger's live Primal
        Companion within 30 ft via execute_spell (no extra slot consumed; the duplicated effect ties
        to the same concentration, so it drops with the original). Only true Self buffs qualify
        (Single geometry, range 0) — self-origin AoEs (Burning Hands etc.) are Cone/Cube and excluded."""
        stats = self.combat.get_agent_stats(self.bm, caster_idx)
        if (stats.character_class != rpg.CharacterClass.Ranger or
                stats.ranger_subclass != rpg.RangerSubclass.BeastMaster or
                stats.char_level < 15):
            return
        comp = self._find_companion_idx(caster_idx)
        if comp < 0 or not self._companion_in_range(caster_idx, comp, 30):
            return
        spells = self.combat.get_agent_spells(self.bm, caster_idx)
        if not (0 <= spell_idx < len(spells)):
            return
        sp = spells[spell_idx]
        if sp.geometry != rpg.SpellGeometry.Single or sp.range != 0:
            return
        action = rpg.SpellAction()
        action.caster_idx     = caster_idx
        action.spell_idx      = spell_idx
        action.slot_level     = slot_level
        action.target_indices = [comp]
        self.combat.execute_spell(self.bm, action)
        self._combat_log_add(
            f"Share Spells: {sp.name} also affects {self.bm.placed_agents[comp].name}.")

    def _pending_spell(self):
        """The Spell object currently being aimed, or None."""
        caster_idx = self._current_agent_idx()
        if caster_idx < 0 or not self.pending_spell_slot:
            return None
        spells = self.combat.get_agent_spells(self.bm, caster_idx)
        if 0 <= self.pending_spell_idx < len(spells):
            return spells[self.pending_spell_idx]
        return None

    def _pending_spell_is_wall(self) -> bool:
        """True when the pending AoE spell is an oriented Rectangle 'wall'."""
        sp = self._pending_spell()
        return sp is not None and sp.geometry == rpg.SpellGeometry.Rectangle

    def _wall_anchor_in_range(self, cell) -> bool:
        """The wall's start point must lie within the spell's range of the caster."""
        sp = self._pending_spell()
        caster_idx = self._current_agent_idx()
        if sp is None or caster_idx < 0:
            return True
        origin = self.bm.placed_agents[caster_idx].origin
        dist_cells = math.hypot(cell.col - origin.col, cell.row - origin.row)
        return dist_cells * 5.0 <= sp.range + 1e-6

    # FLAG: Move to C++
    def _resolve_spell_cast_aoe(self, cell):
        caster_idx = self._current_agent_idx()
        slot       = self.pending_spell_slot
        if caster_idx < 0 or not slot:
            return

        spells_orig = self.combat.get_agent_spells(self.bm, caster_idx)
        sp = spells_orig[self.pending_spell_idx]

        # Handle teleportation spells separately
        if getattr(sp, "teleportation_spell", False):
            self._resolve_teleport_spell(cell)
            return

        action = rpg.SpellAction()
        action.caster_idx     = caster_idx
        action.spell_idx      = self.pending_spell_idx
        action.slot_level     = self.pending_spell_slot_level
        action.target_indices = []
        if sp.geometry == rpg.SpellGeometry.Rectangle and self.spell_anchor_cell is not None:
            # Oriented wall: anchor is the first click, `cell` is the endpoint.
            action.aoe_col  = self.spell_anchor_cell.col
            action.aoe_row  = self.spell_anchor_cell.row
            action.aoe_col2 = cell.col
            action.aoe_row2 = cell.row
        else:
            action.aoe_col  = cell.col
            action.aoe_row  = cell.row
        self._apply_pact_slot_level(caster_idx, sp, action)

        # Cast through the OnDeclareCast window (begin_cast) so a targeted creature can react before
        # the spell resolves; _finish_cast does the post-resolution logging (incl. AoE no-targets and
        # slip handling) whether the cast resolves inline or after a parked reaction.
        self._cast_post = dict(caster_idx=caster_idx, slot=slot, spell_idx=self.pending_spell_idx, aoe=True)
        self._reaction_finish = self._finish_cast

        self.pending_spell_slot       = ""
        self.pending_spell_is_aoe     = False
        self.pending_spell_num_targets = 0
        self.spell_hover_cell         = None
        self.spell_anchor_cell        = None

        status = self.combat.begin_cast(self.bm, action)
        self._flush_combat_log()
        if status == rpg.FlowStatus.AwaitingDecision:
            self._show_pending_reaction_menu()
        else:
            self._finish_cast()

    def _resolve_teleport_spell(self, destination_cell):
        """Handle teleportation spell casting. Teleports caster + additional targets to destination."""
        caster_idx = self._current_agent_idx()
        slot       = self.pending_spell_slot
        if caster_idx < 0 or not slot:
            return

        spells_orig = self.combat.get_agent_spells(self.bm, caster_idx)
        sp = spells_orig[self.pending_spell_idx]

        # Validate destination is in range and not blocked
        if not self.combat.is_valid_teleport_destination(self.bm, destination_cell.col, destination_cell.row):
            self._combat_log_add("Cannot teleport there — destination is blocked or out of range.")
            return

        # For now, teleport only the caster. In Phase 3B, add multi-target support.
        agents_to_teleport = [caster_idx]

        # Place teleported agents
        placed_count = self.combat.place_teleported_agents(
            self.bm, agents_to_teleport, destination_cell.col, destination_cell.row
        )

        if placed_count == 0:
            self._combat_log_add("Failed to teleport — no valid destination.")
            return

        # Log successful teleportation
        agents = self.bm.placed_agents
        cast_name = agents[caster_idx].name if caster_idx < len(agents) else "?"
        self._combat_log_add(f"{cast_name} casts {sp.name} and teleports to ({destination_cell.col}, {destination_cell.row}).")

        # Clean up pending spell state
        self.pending_spell_slot        = ""
        self.pending_spell_is_aoe      = False
        self.pending_spell_num_targets = 0
        self.pending_spell_targets     = []
        self.spell_hover_cell          = None

        # Mark action/bonus as used
        self._consume_cast_slot(slot, caster_idx)

    # FLAG: Move to C++
    def _aoe_cells(self, center_cell, spell) -> list:
        """Return list of rpg.Cell objects covered by the spell AoE (1 cell = 5 ft)."""
        import math
        geo   = spell.geometry
        cols  = self.bm.grid_cols
        rows  = self.bm.grid_rows
        cells = []
        ax = float(center_cell.col)
        ay = float(center_cell.row)

        # Emanation: a Sphere whose center follows the caster — preview it on the caster.
        if getattr(spell, "moves_with_caster", False) and geo == rpg.SpellGeometry.Sphere:
            caster_idx = self._current_agent_idx()
            if caster_idx >= 0:
                cp = self.bm.placed_agents[caster_idx].origin
                ax, ay = float(cp.col), float(cp.row)

        if geo == rpg.SpellGeometry.Sphere:
            r_cells = spell.radius / 5.0
            for c in range(cols):
                for r in range(rows):
                    dx, dy = c - ax, r - ay
                    if math.sqrt(dx*dx + dy*dy) <= r_cells:
                        cells.append(rpg.Cell(c, r))

        elif geo == rpg.SpellGeometry.Cone:
            caster_idx = self._current_agent_idx()
            if caster_idx < 0:
                return cells
            cp = self.bm.placed_agents[caster_idx].origin
            cx, cy = float(cp.col), float(cp.row)
            dx, dy = ax - cx, ay - cy
            ln = math.sqrt(dx*dx + dy*dy)
            if ln < 0.001:
                return cells
            ux, uy = dx/ln, dy/ln
            r_cells = spell.radius / 5.0
            for c in range(cols):
                for r in range(rows):
                    px, py = c - cx, r - cy
                    plen = math.sqrt(px*px + py*py)
                    if plen < 0.001:
                        continue
                    dot = px*ux + py*uy
                    if dot > 0 and plen <= r_cells and (dot/plen) >= 0.866:
                        cells.append(rpg.Cell(c, r))

        elif geo == rpg.SpellGeometry.Line:
            caster_idx = self._current_agent_idx()
            if caster_idx < 0:
                return cells
            cp = self.bm.placed_agents[caster_idx].origin
            cx, cy = float(cp.col), float(cp.row)
            dx, dy = ax - cx, ay - cy
            ln = math.sqrt(dx*dx + dy*dy)
            if ln < 0.001:
                return cells
            ux, uy = dx/ln, dy/ln
            l_cells = spell.length / 5.0
            w_cells = spell.width  / 5.0
            for c in range(cols):
                for r in range(rows):
                    px, py = c - cx, r - cy
                    along = px*ux + py*uy
                    perp  = abs(-py*ux + px*uy)
                    if 0.0 <= along <= l_cells and perp <= w_cells / 2.0:
                        cells.append(rpg.Cell(c, r))

        elif geo == rpg.SpellGeometry.Square:
            w_cells = spell.width  / 5.0
            l_cells = spell.length / 5.0
            for c in range(cols):
                for r in range(rows):
                    dx, dy = abs(c - ax), abs(r - ay)
                    if dx <= w_cells / 2.0 and dy <= l_cells / 2.0:
                        cells.append(rpg.Cell(c, r))

        # Rectangle (oriented wall) is previewed directly via bm.wall_cells in
        # _draw_spell_aoe_preview, so it is intentionally not handled here.

        return cells


    # FLAG: Move to C++
    def _filter_spell_cells_by_range_and_los(self, cells: list, caster_idx: int, spell, center_cell=None) -> list:
        """Filter cells using C++ method that respects spell's requires_los and check_los_on_center flags."""
        if caster_idx < 0 or caster_idx >= len(self.bm.placed_agents):
            return cells
        if not center_cell:
            return cells

        caster = self.bm.placed_agents[caster_idx]
        return self.bm.filter_spell_cells(cells, caster.origin, caster.size, spell, center_cell)

    # FLAG: Move to C++
    def _draw_spell_aoe_preview(self, cpx: int):
        """Translucent AoE highlight while the player is aiming a non-Single spell."""
        if not self.pending_spell_is_aoe or self.spell_hover_cell is None:
            return
        caster_idx = self._current_agent_idx()
        if caster_idx < 0:
            return
        spells = self.combat.get_agent_spells(self.bm, caster_idx)
        if not (0 <= self.pending_spell_idx < len(spells)):
            return
        sp    = spells[self.pending_spell_idx]
        if sp.geometry == rpg.SpellGeometry.Rectangle:
            # Oriented wall: before the anchor is set there is nothing to preview
            # (the hovered cell is the candidate start point). Once anchored, the
            # wall runs from the anchor toward the cursor, clamped to its length.
            if self.spell_anchor_cell is None:
                return
            cells = self.bm.wall_cells(self.spell_anchor_cell, self.spell_hover_cell,
                                       sp.width, sp.length)
        else:
            aoe_cells = self._aoe_cells(self.spell_hover_cell, sp)
            # Filter by spell range and line of sight
            cells = self._filter_spell_cells_by_range_and_los(aoe_cells, caster_idx, sp, center_cell=self.spell_hover_cell)

        fill_s   = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        fill_s.fill((160, 80, 220, 60))
        border_s = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        pygame.draw.rect(border_s, (200, 130, 255, 160), border_s.get_rect(), 1)

        # Only render cells that fall within the map viewport
        map_w, map_h = self.map_rect.width, self.map_rect.height
        cell_set = {(c.col, c.row) for c in cells}
        for c in cells:
            sx, sy = self._cell_to_screen(c.col, c.row)
            # Skip cells whose rendered area extends beyond the map
            if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                continue
            self.screen.blit(fill_s,   (sx, sy))
            self.screen.blit(border_s, (sx, sy))

        # Orange ring around each agent caught in the blast
        for pt in self.bm.placed_agents:
            if (pt.origin.col, pt.origin.row) in cell_set:
                size_px = cpx * pt.size
                sx, sy  = self._cell_to_screen(pt.origin.col, pt.origin.row)
                pygame.draw.rect(self.screen, (255, 140, 0),
                                 pygame.Rect(sx, sy, size_px, size_px), 3,
                                 border_radius=3)

        # Bright white outline on the aimed cell
        ax, ay = self._cell_to_screen(self.spell_hover_cell.col,
                                      self.spell_hover_cell.row)
        pygame.draw.rect(self.screen, (255, 255, 255),
                         pygame.Rect(ax, ay, cpx, cpx), 2)

        # Green marker on a wall's anchor (the committed first click)
        if sp.geometry == rpg.SpellGeometry.Rectangle and self.spell_anchor_cell is not None:
            gx, gy = self._cell_to_screen(self.spell_anchor_cell.col,
                                          self.spell_anchor_cell.row)
            pygame.draw.rect(self.screen, (60, 220, 90),
                             pygame.Rect(gx, gy, cpx, cpx), 3)

        # Draw spell range circle (thin line showing max reach from caster). Self-origin AoEs
        # (Cone, Line) store their reach in radius/length, not `range` (which is 0 for them), so a
        # 60-ft Cone of Cold would otherwise draw a 0-ft ring. Use the geometry's extent for those.
        caster = self.bm.placed_agents[caster_idx]
        if sp.geometry == rpg.SpellGeometry.Cone:
            reach_ft = sp.radius
        elif sp.geometry == rpg.SpellGeometry.Line:
            reach_ft = sp.length
        else:
            reach_ft = sp.range
        range_cells = reach_ft / 5
        range_px = range_cells * cpx
        caster_sx, caster_sy = self._cell_to_screen(caster.origin.col, caster.origin.row)
        caster_center_x = caster_sx + (caster.size * cpx) / 2
        caster_center_y = caster_sy + (caster.size * cpx) / 2
        pygame.draw.circle(self.screen, (100, 150, 255, 100),
                          (int(caster_center_x), int(caster_center_y)),
                          int(range_px), 1)

    def _draw_chromatic_chain(self, cpx: int):
        """Overlay the orb's leap path while the player builds it: caster → primary → each hop,
        with a numbered ring on every chosen leap target and a white ring on the primary."""
        if not (self.pending_chromatic_active and self.pending_spell_slot):
            return
        agents = self.bm.placed_agents
        caster_idx = self._current_agent_idx()

        def _center(idx):
            if not (0 <= idx < len(agents)):
                return None
            pt = agents[idx]
            sx, sy = self._cell_to_screen(pt.origin.col, pt.origin.row)
            half = pt.size * cpx // 2
            return (sx + half, sy + half)

        path = [caster_idx, self.pending_chromatic_primary] + list(self.pending_chromatic_chain)
        pts = [c for c in (_center(i) for i in path) if c is not None]
        for i in range(len(pts) - 1):
            pygame.draw.line(self.screen, (200, 130, 255), pts[i], pts[i + 1], 3)

        ring = max(8, cpx // 3)
        pc = _center(self.pending_chromatic_primary)
        if pc is not None:
            pygame.draw.circle(self.screen, (255, 255, 255), pc, ring, 2)
        for n, idx in enumerate(self.pending_chromatic_chain, start=1):
            c = _center(idx)
            if c is None:
                continue
            pygame.draw.circle(self.screen, (200, 130, 255), c, ring, 3)
            if getattr(self, "font_sm", None):
                label = self.font_sm.render(str(n), True, (255, 255, 255))
                self.screen.blit(label, (c[0] - label.get_width() // 2,
                                         c[1] - label.get_height() // 2))

    def _draw_attack_overlays(self, cpx: int):
        """Draw melee / ranged-normal / ranged-long attack-range overlays."""
        map_w, map_h = self.map_rect.width, self.map_rect.height
        def _draw_zone(cells, fill_rgba, border_rgba):
            if not cells:
                return
            fill_s   = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fill_s.fill(fill_rgba)
            border_s = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_s, border_rgba, border_s.get_rect(), 1)
            for cell in cells:
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                # Skip cells whose rendered area extends beyond the map
                if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                    continue
                self.screen.blit(fill_s,   (sx, sy))
                self.screen.blit(border_s, (sx, sy))

        # Melee: warm red
        _draw_zone(self._attack_cells_melee, (200, 55, 55, 70), (255, 100, 100, 150))
        # Ranged normal: orange
        _draw_zone(self._attack_cells_rnorm, (200, 120, 40, 55), (255, 165, 60, 130))
        # Ranged long (disadvantage): dull yellow
        _draw_zone(self._attack_cells_rlong, (180, 165, 40, 35), (220, 200, 60, 90))

    def _spell_to_dict(self, agent_idx: int, spell_idx: int, s) -> dict:
        """Convert C++ Spell object to dict, including metadata."""
        geo = s.geometry.name
        uses_radius = geo in ("Sphere", "Cone")
        uses_line   = geo == "Line"
        metadata = self._spell_metadata.get((agent_idx, spell_idx), {})

        # Convert magic_damage_rolls to dict format
        magic_dmg = []
        for roll in s.magic_damage_rolls:
            magic_dmg.append({
                "type": roll.type.name,
                "num_dice": roll.num_dice,
                "die_size": roll.die_size
            })

        # Convert physical_damage_rolls to dict format
        phys_dmg = []
        for roll in s.physical_damage_rolls:
            phys_dmg.append({
                "type": roll.type.name,
                "num_dice": roll.num_dice,
                "die_size": roll.die_size
            })

        # Convert conditions to dict format
        conditions = []
        _on_dmg_name = {rpg.OnDamage.End: "end", rpg.OnDamage.RepeatSave: "repeat_save"}
        for cond in s.conditions:
            conditions.append({
                "condition_name": cond.condition_name,
                "condition_duration": cond.condition_duration,
                "save_repeat_turns": cond.save_repeat_turns,
                "save_ability": cond.save_ability.name,
                "save_dc_ability": cond.save_dc_ability.name,
                "on_damage": _on_dmg_name.get(cond.on_damage),
            })

        return {
            "name":                  s.name,
            "type":                  s.type.name,
            "geometry":              geo,
            "attack_type":           s.attack_type.name,
            "save_ability":          s.save_ability.name if s.attack_type == rpg.SpellAttack.Save else None,
            "school":                s.school.name,
            "casting_time":          s.casting_time.name,
            "range":                 s.range,
            "radius":                s.radius if uses_radius else None,
            "width":                 s.width  if uses_line   else None,
            "length":                s.length if uses_line   else None,
            "duration":              s.duration,
            "magic_damage_types":    magic_dmg,
            "physical_damage_types": phys_dmg,
            "terrain_effect":        metadata.get("terrain_effect"),
            "hatch_pattern":         metadata.get("hatch_pattern"),
            "terrain_color":         metadata.get("terrain_color"),
            "level":                 s.level,
            "upcast_dice_bonus":     s.upcast_dice_bonus,
            "requires_concentration": s.requires_concentration,
            "requires_los":          s.requires_los,
            "check_los_on_center":   s.check_los_on_center,
            "requires_sight":        s.requires_sight,
            "moves_with_caster":     s.moves_with_caster,
            "selective_targeting":   s.selective_targeting,
            "resource_name":         s.resource_name or None,
            "resource_cost":         s.resource_cost,
            "teleportation_spell":   s.teleportation_spell,
            "max_teleport_targets":  s.max_teleport_targets,
            "teleport_range_ft":     s.teleport_range_ft,
            "conditions":            conditions,
        }

    def _dict_to_spell(self, agent_idx: int, d: dict):
        """Convert dict to C++ Spell, storing metadata separately."""
        s = rpg.Spell()
        s.name         = d.get("name",         "Unnamed Spell")
        s.type         = getattr(rpg.SpellType,     d.get("type",         "Harm"),     rpg.SpellType.Harm)
        s.geometry     = getattr(rpg.SpellGeometry, d.get("geometry",     "Single"),   rpg.SpellGeometry.Single)
        s.attack_type  = getattr(rpg.SpellAttack,   d.get("attack_type",  "AttackRoll"), rpg.SpellAttack.AttackRoll)
        s.save_ability = getattr(rpg.SaveAbility,   d.get("save_ability") or "SaveDex", rpg.SaveAbility.SaveDex)
        s.school       = getattr(rpg.SpellSchool,   d.get("school",       "NONE"),     rpg.SpellSchool.NONE)
        s.range        = int(d.get("range")  or 30)
        s.radius       = int(d.get("radius") or 10)
        s.width        = int(d.get("width")  or  5)
        s.length       = int(d.get("length") or 30)
        s.duration     = int(d.get("duration",   1))

        # Parse magic damage types - handle both new (object) and old (string) formats
        magic_dmg_raw = d.get("magic_damage_types", [])
        magic_rolls = []
        for dmg in magic_dmg_raw:
            if isinstance(dmg, dict):
                # New format: {"type": "Fire", "num_dice": 2, "die_size": 6, "bonus": 1}
                dmg_type = _parse_magic_damage(dmg.get("type", "Fire"))
                roll = rpg.MagicDamageRoll()
                roll.type = dmg_type
                roll.num_dice = int(dmg.get("num_dice", 1))
                roll.die_size = int(dmg.get("die_size", 6))
                roll.bonus = int(dmg.get("bonus", 0))
                magic_rolls.append(roll)
            else:
                # Old format: just the string "Fire"
                dmg_type = _parse_magic_damage(dmg)
                roll = rpg.MagicDamageRoll()
                roll.type = dmg_type
                roll.num_dice = int(d.get("num_dice", 1))
                roll.die_size = int(d.get("die_size", 6))
                roll.bonus = int(d.get("bonus", 0))
                magic_rolls.append(roll)
        s.magic_damage_rolls = magic_rolls

        # Parse physical damage types - handle both new (object) and old (string) formats
        phys_dmg_raw = d.get("physical_damage_types", [])
        phys_rolls = []
        for dmg in phys_dmg_raw:
            if isinstance(dmg, dict):
                # New format: {"type": "Slashing", "num_dice": 1, "die_size": 8, "bonus": 0}
                dmg_type = _parse_physical_damage(dmg.get("type", "Bludgeoning"))
                roll = rpg.PhysicalDamageRoll()
                roll.type = dmg_type
                roll.num_dice = int(dmg.get("num_dice", 1))
                roll.die_size = int(dmg.get("die_size", 6))
                roll.bonus = int(dmg.get("bonus", 0))
                phys_rolls.append(roll)
            else:
                # Old format: just the string "Slashing"
                dmg_type = _parse_physical_damage(dmg)
                roll = rpg.PhysicalDamageRoll()
                roll.type = dmg_type
                roll.num_dice = int(d.get("num_dice", 1))
                roll.die_size = int(d.get("die_size", 6))
                roll.bonus = int(d.get("bonus", 0))
                phys_rolls.append(roll)
        s.physical_damage_rolls = phys_rolls

        # Parse healing type (for Heal spells)
        healing_raw = d.get("healing_type")
        if healing_raw and isinstance(healing_raw, dict):
            healing = rpg.HealingRoll()
            healing.num_dice = int(healing_raw.get("num_dice", 1))
            healing.die_size = int(healing_raw.get("die_size", 6))
            healing.bonus = int(healing_raw.get("bonus", 0))
            s.healing_type = healing

        s.requires_concentration = d.get("requires_concentration", False)
        s.moves_with_caster = d.get("moves_with_caster", False)
        s.selective_targeting = d.get("selective_targeting", False)
        s.resource_name = d.get("resource_name", "") or ""
        s.resource_cost = int(d.get("resource_cost", 1))
        s.requires_los = d.get("requires_los", False)
        s.check_los_on_center = d.get("check_los_on_center", True)
        s.level = int(d.get("level", 0))
        s.upcast_dice_bonus = int(d.get("upcast_dice_bonus", 0))
        s.num_targets = int(d.get("num_targets", 1))
        s.targets_per_upcast_level = int(d.get("targets_per_upcast_level", 0))
        s.effects_on_begin_turn = d.get("effects_on_begin_turn", True)
        s.effects_on_end_turn = d.get("effects_on_end_turn", False)

        # Parse terrain effect (Grease, Spike Growth, etc.) onto the C++ Spell.
        # Cosmetic color/hatch stay in _spell_metadata for rendering.
        te = d.get("terrain_effect")
        if te:
            if te.get("type") == "Slipping":
                s.terrain_difficulty = rpg.TerrainDifficulty.Slipping
                s.slip_save_dc       = int(te.get("slip_save_dc", 10))
                s.slip_distance_feet = int(te.get("slip_distance_feet", 5))
            else:
                m = float(te.get("multiplier", 0.5))
                s.terrain_difficulty = (rpg.TerrainDifficulty.Quartered if m <= 0.25
                                        else rpg.TerrainDifficulty.Halved)

        # Parse conditions applied by this spell (e.g., Hold Person applies Paralyzed)
        conditions = []
        for cond_entry in d.get("conditions", []):
            if isinstance(cond_entry, dict):
                # Full condition spec: {"condition_name": "Paralyzed", "condition_duration": 10, ...}
                c = rpg.AttackCondition()
                c.condition_name = cond_entry.get("condition_name", "")
                c.condition_duration = int(cond_entry.get("condition_duration", 0))
                c.push_ft = int(cond_entry.get("push_ft", 0))
                c.save_repeat_turns = int(cond_entry.get("save_repeat_turns", 1))
                c.requires_save = ("save_ability" in cond_entry)
                # Parse save_ability string (target's save) - defaults to spell's save_ability
                save_ability_str = cond_entry.get("save_ability")
                if save_ability_str:
                    try:
                        c.save_ability = getattr(rpg.SaveAbility, save_ability_str)
                    except AttributeError:
                        c.save_ability = s.save_ability  # fallback to spell's ability
                else:
                    c.save_ability = s.save_ability  # use spell's ability as default
                # Parse save_dc_ability string (caster's ability for DC)
                save_dc_ability_str = cond_entry.get("save_dc_ability", "SaveSpellcasterMod")
                try:
                    c.save_dc_ability = getattr(rpg.SaveAbility, save_dc_ability_str)
                except AttributeError:
                    c.save_dc_ability = rpg.SaveAbility.SaveSpellcasterMod
                # on_damage: "end" ends the condition on any damage; "repeat_save" re-rolls at advantage
                od = str(cond_entry.get("on_damage", "") or "").lower()
                if od == "end":
                    c.on_damage = rpg.OnDamage.End
                elif od in ("repeat_save", "repeatsave", "repeat-save"):
                    c.on_damage = rpg.OnDamage.RepeatSave
                conditions.append(c)
            else:
                # Simple string: just the condition name (legacy support)
                c = rpg.AttackCondition()
                c.condition_name = str(cond_entry)
                c.condition_duration = 0  # will use spell duration
                c.push_ft = 0
                c.save_repeat_turns = 1
                c.requires_save = False
                c.save_ability = s.save_ability  # use spell's ability for legacy conditions
                c.save_dc_ability = rpg.SaveAbility.SaveSpellcasterMod
                conditions.append(c)
        s.conditions = conditions

        # Parse teleportation spell fields
        s.teleportation_spell = d.get("teleportation_spell", False)
        s.max_teleport_targets = int(d.get("max_teleport_targets", 0))
        s.teleport_range_ft = int(d.get("teleport_range_ft", 0))

        # Parse casting time
        casting_time_str = d.get("casting_time", "Action")
        s.casting_time = getattr(rpg.CastingTime, casting_time_str, rpg.CastingTime.Action)

        return s


    # FLAG: Move to C++
    def _save_agents(self, path: str | None = None):
        path = path or self._save_path
        data = []
        for i, pt in enumerate(self.bm.placed_agents):
            # Summoned creatures are transient (concentration-tied) and have no persisted
            # summoner link, so they are never written to the save — they vanish on reload
            # rather than becoming orphaned permanent agents.
            if pt.summoner_idx >= 0 or pt.removed_from_play:
                continue
            s = self.combat.get_agent_stats(self.bm, i)
            # Save only the filename, not the full path, for portability
            sprite_filename = os.path.basename(pt.sprite_path) if pt.sprite_path else ""
            data.append({
                "name":        pt.name,
                "sprite_path": sprite_filename,
                "size":        pt.size,
                "col":         pt.origin.col,
                "row":         pt.origin.row,
                "faction":     pt.faction,
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
                    "num_attacks":        s.num_attacks,
                    "has_cunning_action": s.has_cunning_action,
                    "has_offhand_attack": s.has_offhand_attack,
                    "has_sentinel":             s.has_sentinel,
                    "has_branches_of_the_tree": s.has_branches_of_the_tree,
                    "spellcasting_ability": _INT_TO_ABILITY.get(s.spellcasting_ability, "cha"),
                    "temp_hp": s.temp_hp,
                    "available_hit_points": s.available_hit_points,
                    "feats": list(s.feats),
                    "elemental_adept_types": list(s.elemental_adept_types),
                    "luck_points": s.luck_points,
                    "luck_points_max": s.luck_points_max,
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
                # without depending on the PC weapons.json catalog. Loader accepts dicts or, for older
                # saves, bare name strings (catalog lookup).
                "weapons": {
                    "main_hand": _weapon_to_dict(self.combat.get_agent_weapons(self.bm, i)[0]),
                    "off_hand": _weapon_to_dict(self.combat.get_agent_weapons(self.bm, i)[1]),
                    "ranged": _weapon_to_dict(self.combat.get_agent_weapons(self.bm, i)[2]),
                },
                "armor": {
                    "helmet": self.combat.get_agent_armor(self.bm, i)[0].name or "",
                    "chest": self.combat.get_agent_armor(self.bm, i)[1].name or "",
                    "leggings": self.combat.get_agent_armor(self.bm, i)[2].name or "",
                    "boots": self.combat.get_agent_armor(self.bm, i)[3].name or "",
                    "gloves": self.combat.get_agent_armor(self.bm, i)[4].name or "",
                    "cloak": self.combat.get_agent_armor(self.bm, i)[5].name or "",
                },
                "spell_indices": [s.name
                                  for s in self.combat.get_agent_spells(self.bm, i)],
                "agent_class":      s.character_class.name,
                "agent_char_level": s.char_level,
                "agent_barbarian_subclass": s.barbarian_subclass.name,
                "agent_fighter_subclass": s.fighter_subclass.name,
                "agent_druid_circle": s.druid_circle.name,
                "agent_monk_subclass": s.monk_subclass.name,
                "agent_paladin_oath": s.paladin_oath.name,
                "agent_wizard_subclass": s.wizard_subclass.name,
                "agent_warlock_subclass": s.warlock_subclass.name,
                "agent_rogue_subclass": s.rogue_subclass.name,
                "agent_cleric_subclass": s.cleric_subclass.name,
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
            if s.is_npc or i in self._agent_meta:
                meta = self._agent_meta.get(i, {})
                data[-1]["is_npc"] = bool(s.is_npc) or bool(meta.get("is_npc", False))
                data[-1]["npc_spell_groups"] = meta.get("npc_spell_groups", {})
                # Save current uses_remaining from each spell
                npc_uses = {}
                spells = self.combat.get_agent_spells(self.bm, i)
                for spell in spells:
                    if spell.uses_max > 0:  # Only save if this is an N/day spell
                        npc_uses[spell.name] = spell.uses_remaining
                data[-1]["npc_spell_uses_cur"] = npc_uses
        # Serialize map items
        items_data = []
        for item in self.bm.get_all_items():
            items_data.append({
                "col":         item.cell.col,
                "row":         item.cell.row,
                "weapon_name": item.weapon.name,
                "sprite_path": item.sprite_path,
            })
        with open(path, "w") as f:
            json.dump({"agents": data, "map_items": items_data}, f, indent=2)

    # FLAG: Move to C++
    # ── D&D Beyond import ─────────────────────────────────────────────────────
    def _import_ddb_character(self):
        """Fetch a public D&D Beyond character, derive our agent record via
        tools/import_character.py, append it to the current encounter file and
        reload. Thin GUI wrapper around the standalone importer."""
        url = self._modal_text_prompt(
            "Import D&D Beyond Character",
            "Paste a character URL or ID (the sheet must be publicly shared):")
        if not url:
            return
        # lazy-import the standalone tool from the repo tools/ dir
        tools_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        try:
            import import_character as ic
        except Exception as e:                       # noqa: BLE001 — surface any import error
            self._modal_message(["Importer unavailable:", str(e)])
            return

        self._modal_message(["Importing from D&D Beyond…"], blocking=False)
        try:
            data = ic.fetch_character(url)
            ic._WARN = []                            # capture this character's warnings
            agent = ic.build_agent(data, ic.load_catalogs(), faction=0)
            warnings = list(ic._WARN)
        except Exception as e:                       # noqa: BLE001 — network/parse/derive errors
            self._modal_message(["Import failed:", str(e)])
            return

        # lossless sidecar (raw DDB JSON), best-effort
        try:
            cid = re.search(r"(\d{4,})", str(url))
            side_dir = os.path.join(tools_dir, "ddb_sources")
            os.makedirs(side_dir, exist_ok=True)
            slug = ic.slugify(data.get("name", ""))
            fn = f"{cid.group(1) if cid else slug}_{slug}.ddb.json"
            with open(os.path.join(side_dir, fn), "w") as f:
                json.dump({"data": data}, f, indent=2)
        except Exception:                            # noqa: BLE001 — sidecar is best-effort
            pass

        # Persist current placements, append the new agent at a free column, reload.
        self._save_agents()
        try:
            with open(self._save_path) as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            doc = {"agents": [], "map_items": []}
        agents = doc.setdefault("agents", [])
        occupied = {(a.get("col"), a.get("row")) for a in agents}
        cols, rows = self.bm.grid_cols, self.bm.grid_rows
        spot = next(((c, r) for c in range(cols) for r in range(rows)
                     if (c, r) not in occupied), (0, 0))
        agent["col"], agent["row"] = spot
        agents.append(agent)
        doc.setdefault("map_items", [])
        with open(self._save_path, "w") as f:
            json.dump(doc, f, indent=2)
        self._load_agents()

        sub = ""
        for k, v in agent.items():
            if k.startswith("agent_") and k.endswith(("subclass", "circle", "oath")) and v != "NONE":
                sub = f" / {v}"
                break
        lines = [f"Imported {agent['name']}",
                 f"{agent['agent_class']} {agent['agent_char_level']}{sub}   "
                 f"HP {agent['stats']['hp_max']}   spells {len(agent['spell_indices'])}",
                 "Placed at the right edge — drag it into position, set its team via right-click."]
        if warnings:
            lines.append(f"{len(warnings)} note(s) (best-effort import):")
            lines.extend("• " + w[:70] for w in warnings[:8])
            if len(warnings) > 8:
                lines.append(f"  …and {len(warnings) - 8} more (see console).")
        self._modal_message(lines)

    def _modal_text_prompt(self, title: str, prompt: str) -> str | None:
        """Blocking single-line text prompt. Returns the entered text, or None on cancel."""
        sw, sh = self.screen.get_size()
        W, H = min(560, sw - 80), 180
        box = pygame.Rect((sw - W) // 2, (sh - H) // 2, W, H)
        inp = TextInput(pygame.Rect(box.x + 20, box.y + 86, W - 40, 32), font=self.font_md)
        inp.active = True
        ok = Button(pygame.Rect(box.right - 210, box.bottom - 46, 90, 32), "Import",
                    (60, 110, 70), (80, 140, 90), font=self.font_md)
        cancel = Button(pygame.Rect(box.right - 110, box.bottom - 46, 90, 32), "Cancel",
                        (110, 60, 60), (150, 80, 80), font=self.font_md)
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return None
                    if event.key == pygame.K_RETURN:
                        return inp.text.strip() or None
                inp.handle(event)
                if ok.clicked(event):
                    return inp.text.strip() or None
                if cancel.clicked(event):
                    return None
            self.screen.blit(overlay, (0, 0))
            pygame.draw.rect(self.screen, (35, 35, 50), box, border_radius=8)
            pygame.draw.rect(self.screen, (90, 90, 110), box, 1, border_radius=8)
            self.screen.blit(self.font_lg.render(title, True, (235, 235, 245)),
                             (box.x + 20, box.y + 18))
            self.screen.blit(self.font_md.render(prompt, True, (185, 185, 200)),
                             (box.x + 20, box.y + 52))
            inp.draw(self.screen)
            ok.draw(self.screen)
            cancel.draw(self.screen)
            pygame.display.flip()
            self.clock.tick(60)

    def _modal_message(self, lines, blocking: bool = True):
        """Blocking message box (OK to dismiss). blocking=False draws once and returns
        (for a transient 'working…' splash)."""
        sw, sh = self.screen.get_size()
        W = min(640, sw - 80)
        line_h = 24
        H = 44 + line_h * len(lines) + (46 if blocking else 18)
        box = pygame.Rect((sw - W) // 2, (sh - H) // 2, W, H)
        ok = Button(pygame.Rect(box.centerx - 45, box.bottom - 40, 90, 30), "OK",
                    (60, 90, 120), (80, 120, 150), font=self.font_md)
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))

        def render():
            self.screen.blit(overlay, (0, 0))
            pygame.draw.rect(self.screen, (35, 35, 50), box, border_radius=8)
            pygame.draw.rect(self.screen, (90, 90, 110), box, 1, border_radius=8)
            y = box.y + 16
            for i, ln in enumerate(lines):
                f = self.font_lg if i == 0 else self.font_md
                col = (235, 235, 245) if i == 0 else (190, 190, 205)
                self.screen.blit(f.render(ln, True, col), (box.x + 20, y))
                y += line_h + (6 if i == 0 else 0)
            if blocking:
                ok.draw(self.screen)
            pygame.display.flip()

        if not blocking:
            render()
            return
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    return
                if ok.clicked(event):
                    return
            render()
            self.clock.tick(60)

    def _load_agents(self, path: str | None = None):
        path = path or self._save_path
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"\n{'='*60}")
            print(f"ERROR: Agents file corrupted: {path}")
            print(f"Details: {e}")
            print(f"\nFix: Delete the corrupted file and start fresh:")
            print(f"  rm \"{path}\"")
            print(f"Then reload the map.")
            print(f"{'='*60}\n")
            return
        self.bm.clear_agents()
        self.pending_configs.clear()
        self.selected_idx = -1
        self.drag_idx     = -1
        self._spell_metadata.clear()
        # _agent_meta is index-keyed; stale entries from the previous scene would
        # otherwise bleed onto whatever agent lands at that index (e.g. a non-NPC
        # written out as an NPC on the next save). It is repopulated below per agent.
        self._agent_meta.clear()
        agent_data = data.get("agents", [])
        for t in agent_data:
            cfg = rpg.AgentConfig()
            cfg.name        = t["name"]
            # Resolve sprite path relative to sprites directory
            sprite_filename = t.get("sprite_path", "")
            cfg.sprite_path = os.path.join(self.sprites_dir, sprite_filename) if sprite_filename else ""
            cfg.size        = t["size"]
            cfg.start_col   = t["col"]
            cfg.start_row   = t["row"]
            self.combat.add_agent_config(self.bm, cfg)
            self.pending_configs.append(cfg)
        self.combat.apply_agent_configs(self.bm)
        self.sprites.clear()
        # Restore stats for each placed agent
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            sd = t.get("stats")
            if not sd:
                continue
            s = dict_to_stats(sd)

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

            self.combat.set_agent_stats(self.bm, i, s)

            # Restore team/faction (0 = neutral for older saves that predate factions).
            self.bm.set_agent_faction(i, int(t.get("faction", 0)))

        # Restore weapons — load from weapons dict (slot format) or legacy formats
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            cpp_weapons = [rpg.Weapon(), rpg.Weapon(), rpg.Weapon()]  # 3 slots: main, off, ranged

            # Try new weapons dict format first. Each slot holds either a full weapon dict
            # (current format — lossless, works for NPC/monster/custom weapons) or, for older
            # saves, a bare weapon name string resolved against the PC weapons.json catalog.
            weapons_dict = t.get("weapons", {})
            if weapons_dict and isinstance(weapons_dict, dict):
                slot_names = ["main_hand", "off_hand", "ranged"]
                for slot_idx, slot_name in enumerate(slot_names):
                    weapon_data = weapons_dict.get(slot_name, "")
                    if isinstance(weapon_data, dict):
                        cpp_weapons[slot_idx] = _dict_to_weapon(weapon_data)
                    elif weapon_data and weapon_data in self.weapon_name_to_dict:
                        cpp_weapons[slot_idx] = _dict_to_weapon(self.weapon_name_to_dict[weapon_data])
            else:
                # Fallback to legacy weapon_indices format (list of weapon names)
                weapon_names = t.get("weapon_indices", [])
                if weapon_names:
                    for slot_idx, weapon_name in enumerate(weapon_names):
                        if slot_idx >= 3:
                            break
                        if weapon_name and weapon_name in self.weapon_name_to_dict:
                            weapon_dict = self.weapon_name_to_dict[weapon_name]
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
            stats = self.combat.get_agent_stats(self.bm, i)
            if stats.character_class == rpg.CharacterClass.Monk and cpp_weapons[0].name == "Unarmed":
                cpp_weapons[0] = self._create_monk_unarmed_weapon()

            # Master of Myriad Forms (invocation 12): Alter Self claws (1d6) for Warlocks
            if (stats.character_class == rpg.CharacterClass.Warlock and
                    stats.has_invocation(12) and cpp_weapons[0].name == "Unarmed"):
                cpp_weapons[0] = self._create_alter_self_claws_weapon()

            # Pact of the Blade (invocation 13): re-conjure the pact weapon into the main-hand slot.
            if (stats.character_class == rpg.CharacterClass.Warlock and
                    stats.has_invocation(13) and cpp_weapons[0].name != "PactBlade"):
                cpp_weapons[0] = self._create_pact_blade_weapon()

            self.combat.set_agent_weapons(self.bm, i, cpp_weapons)

        # Restore spells — load from spell_indices or legacy "spells" field.
        # Class features (Channel Divinity options like Divine Spark / Radiance of the Dawn) live in
        # classfeatures.json, not spells.json. They're auto-granted by _grant_class_features (by class +
        # level + subclass, with level-scaled dice), so any such names persisted into a save's
        # spell_indices are skipped here (not looked up in spells.json) to avoid a bogus "not found" warning.
        cf_names = {f.get("name") for f in self.all_class_features}
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            cpp_spells = []

            # Try new spell_indices format first (spell names as strings)
            spell_names = t.get("spell_indices", [])
            if spell_names:
                for j, spell_name in enumerate(spell_names):
                    if spell_name in self.spell_name_to_idx:
                        idx = self.spell_name_to_idx[spell_name]
                        spell_dict = self.all_spells[idx]
                        cpp_spell = self._dict_to_spell(i, spell_dict)
                        cpp_spells.append(cpp_spell)
                        # Store metadata (terrain, hatch, color)
                        meta = {
                            "terrain_effect": spell_dict.get("terrain_effect"),
                            "hatch_pattern": spell_dict.get("hatch_pattern"),
                            "terrain_color": spell_dict.get("terrain_color"),
                        }
                        self._spell_metadata[(i, j)] = meta
                    elif spell_name in cf_names:
                        continue  # class feature — granted below via _grant_class_features, not from spells.json
                    else:
                        available = ", ".join(sorted(list(self.spell_name_to_idx.keys())[:5])) + "..."
                        print(f"WARNING: Spell '{spell_name}' not found for agent {t.get('name', i)}")
                        print(f"         Available spells: {available}")
            else:
                # Fallback to legacy "spells" format for backward compatibility
                spell_data = t.get("spells", [])
                for j, item in enumerate(spell_data):
                    # Handle both old formats: spell dicts or spell names (strings)
                    if isinstance(item, dict):
                        cpp_spells.append(self._dict_to_spell(i, item))
                        # Store metadata from dict
                        meta = {
                            "terrain_effect": item.get("terrain_effect"),
                            "hatch_pattern": item.get("hatch_pattern"),
                            "terrain_color": item.get("terrain_color"),
                        }
                        self._spell_metadata[(i, j)] = meta
                    elif isinstance(item, str):
                        # Legacy format: spell stored as name string
                        # Look up in all_spells by name
                        if item in self.spell_name_to_idx:
                            idx = self.spell_name_to_idx[item]
                            spell_dict = self.all_spells[idx]
                            cpp_spells.append(self._dict_to_spell(i, spell_dict))
                            # Store metadata
                            meta = {
                                "terrain_effect": spell_dict.get("terrain_effect"),
                                "hatch_pattern": spell_dict.get("hatch_pattern"),
                                "terrain_color": spell_dict.get("terrain_color"),
                            }
                            self._spell_metadata[(i, j)] = meta

            # Grant always-prepared class features (Channel Divinity options, etc.) from
            # classfeatures.json by class + level + subclass — same path as _apply_spells_to_agent, so
            # a loaded agent gets its features regardless of what was persisted in spell_indices.
            self._grant_class_features(i, cpp_spells)
            self.combat.set_agent_spells(self.bm, i, cpp_spells)

        # Restore armor — load from armor dict (new format) or legacy armor_indices (old format)
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            cpp_armor = [rpg.Armor() for _ in range(6)]  # 6 slots: [helmet, chest, leggings, boots, gloves, cloak]

            # Slot order: helmet, chest, leggings, boots, gloves, cloak
            SLOT_NAMES = ["helmet", "chest", "leggings", "boots", "gloves", "cloak"]

            # Try new armor dict format first (slot name -> armor name)
            armor_dict_new = t.get("armor", {})
            if armor_dict_new and isinstance(armor_dict_new, dict):
                for slot_idx, slot_name in enumerate(SLOT_NAMES):
                    armor_name = armor_dict_new.get(slot_name, "")
                    if armor_name and armor_name in self.armor_name_to_dict:
                        armor_def = self.armor_name_to_dict[armor_name]
                        cpp_armor[slot_idx] = _dict_to_armor(armor_def)
            else:
                # Fallback to legacy armor_indices format (list of names)
                armor_names = t.get("armor_indices", [])
                if armor_names:
                    for slot_idx, armor_name in enumerate(armor_names):
                        if slot_idx >= 6:
                            break
                        if armor_name and armor_name in self.armor_name_to_dict:
                            armor_dict = self.armor_name_to_dict[armor_name]
                            cpp_armor[slot_idx] = _dict_to_armor(armor_dict)

            # Store armor in the C++ layer (as array of 6 pieces)
            self.combat.set_agent_armor(self.bm, i, cpp_armor)

            # Check STR requirements and warn if insufficient
            agent_stats = self.combat.get_agent_stats(self.bm, i)
            for piece in cpp_armor:
                if piece.name and not self.combat.can_equip_armor(self.bm, i, piece):
                    print(f"⚠ {self.bm.placed_agents[i].name} wearing {piece.name} (requires STR {piece.str_requirement}, has {agent_stats.str})")

        # Restore NPC spell mechanics if present
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            is_npc = t.get("is_npc", False)
            if is_npc:
                npc_spell_groups = t.get("npc_spell_groups", {})
                # Initialize NPC spell groups in C++ (converts string keys to ints)
                if npc_spell_groups:
                    groups_dict = {int(k): v for k, v in npc_spell_groups.items()}
                    self.combat.init_npc_spell_groups(self.bm, i, groups_dict)
                # Keep in _agent_meta for stats dialog to access
                self._agent_meta[i] = {"is_npc": True, "npc_spell_groups": npc_spell_groups}

        # Restore map items
        self.bm.clear_items()
        for idata in data.get("map_items", []):
            wname = idata.get("weapon_name", "")
            if not wname or wname not in self.weapon_name_to_dict:
                continue
            weapon_dict = self.weapon_name_to_dict[wname]
            weapon = _dict_to_weapon(weapon_dict)
            cell = rpg.Cell(int(idata["col"]), int(idata["row"]))
            sprite_path = idata.get("sprite_path", weapon_dict.get("sprite_path", ""))
            self.bm.place_item(cell, weapon, sprite_path)

        self._attack_cells_melee = []
        self._attack_cells_rnorm = []
        self._attack_cells_rlong = []

    def _load_terrain(self, path: str | None = None):
        """Load terrain data from JSON file if it exists.

        If the file doesn't exist on first load, terrain starts empty.
        User can manually label terrain using the terrain editor,
        or choose to auto-detect walls as a fallback.
        """
        # Reset first so this is safe to call repeatedly when swapping encounters
        # (a new encounter with no terrain file must not inherit the previous scene).
        path = path or self._terrain_path
        self._terrain_regions = []
        self._walls_enabled = True
        self._manual_grid = None
        self.bm.reset_terrain_multipliers()

        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                # A saved manual grid must be applied first: it resizes the per-cell
                # terrain/light buffers, so it has to run before terrain regions are
                # written into them.
                mg = data.get("manual_grid")
                if mg:
                    try:
                        self.bm.set_uniform_grid(int(mg["cell_px"]),
                                                 int(mg["anchor"][0]),
                                                 int(mg["anchor"][1]))
                        self._manual_grid = mg
                    except Exception:
                        self._manual_grid = None
                self._terrain_regions = data.get("regions", [])
                self._walls_enabled = bool(data.get("walls_enabled", True))
                self._apply_terrain_to_battle_map()
            except Exception:
                self._terrain_regions = []

        # Honour the walls preference: ON re-detects from a clean slate; OFF drops every
        # auto-detected obstacle so a map the detector mis-read isn't blocked. (On first
        # load detect_walls already ran in __init__; clear+detect reproduces that result.)
        if self._walls_enabled:
            self.bm.clear_walls()
            self.bm.detect_walls()
        else:
            self.bm.clear_walls()

    def _save_terrain(self, path: str | None = None):
        """Save terrain data to JSON file (defaults to the active encounter's path)."""
        path = path or self._terrain_path
        data = {"regions": self._terrain_regions, "walls_enabled": self._walls_enabled}
        if self._manual_grid:
            data["manual_grid"] = self._manual_grid
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def _toggle_grid_sample_mode(self):
        """Enter/leave 'sample a tile' mode for defining a manual uniform grid.

        While active, the next left-drag on the map outlines a single tile; on
        release the grid is rebuilt from that tile's size (square) and corner.
        """
        self._grid_sample_mode = not self._grid_sample_mode
        self._grid_sample_start = None
        self._grid_sample_cur   = None
        self.btn_set_grid.text = "Drag one tile…" if self._grid_sample_mode else "Set Grid…"
        if self._grid_sample_mode:
            self._combat_log_add("Grid sample: drag a box over a single map tile.")

    def _finalize_grid_sample(self, start, end):
        """Capture a sampled box (screen-space drag start/end) and ask how many cells
        it spanned. The drag is converted to image-pixel space (undoing pan + scale);
        the box is then divided by the spanned cols/rows to recover the cell size.
        """
        self._grid_sample_mode = False
        self.btn_set_grid.text = "Set Grid…"

        s = self.map_scale
        x0 = (min(start[0], end[0]) - self.pan_x) / s
        y0 = (min(start[1], end[1]) - self.pan_y) / s
        x1 = (max(start[0], end[0]) - self.pan_x) / s
        y1 = (max(start[1], end[1]) - self.pan_y) / s
        w, h = x1 - x0, y1 - y0
        if w < 4 or h < 4:
            self._combat_log_add("Grid sample too small — cancelled.")
            return

        self._pending_grid_box = (x0, y0, w, h)
        self._grid_span_dialog.show(self._on_grid_span)

    def _on_grid_span(self, result):
        """Callback from GridSpanDialog: result is (cols, rows) spanned, or None.

        Divides the sampled box by the spanned cell count to get a square cell size,
        then rebuilds the grid. Replaces auto-detection, so wall auto-detect is forced
        off and old (now-misindexed) terrain regions are dropped.
        """
        box = self._pending_grid_box
        self._pending_grid_box = None
        if result is None or box is None:
            self._combat_log_add("Grid sample cancelled.")
            return

        cols_spanned, rows_spanned = result
        x0, y0, w, h = box
        cell_px  = int(round((w / cols_spanned + h / rows_spanned) / 2.0))  # square
        anchor_x = int(round(x0))
        anchor_y = int(round(y0))
        if cell_px <= 0:
            self._combat_log_add("Grid sample too small — cancelled.")
            return
        try:
            self.bm.set_uniform_grid(cell_px, anchor_x, anchor_y)
        except Exception as e:
            self._combat_log_add(f"Grid sample failed: {e}")
            return

        self._manual_grid = {"cell_px": cell_px, "anchor": [anchor_x, anchor_y]}
        self._terrain_regions = []
        self._walls_enabled = False
        self.btn_toggle_walls.text = "Walls: OFF"
        self._build_overlay()
        self._save_terrain()
        self._combat_log_add(
            f"Manual grid set: {self.bm.grid_cols}×{self.bm.grid_rows} cells, {cell_px}px/cell.")

    def _toggle_walls(self):
        """Turn auto-detected walls/obstacles on or off.

        The detector occasionally mis-reads a map (the "janky walls" bug). Toggling
        OFF discards every auto-detected obstacle so only explicit terrain blocks
        movement; toggling ON re-runs detection from a clean slate. The choice is
        persisted in the terrain JSON so it survives a reload.
        """
        self._walls_enabled = not self._walls_enabled
        if self._walls_enabled:
            self.bm.clear_walls()   # start clean so detection doesn't accumulate
            self.bm.detect_walls()
        else:
            self.bm.clear_walls()
        self.btn_toggle_walls.text = "Walls: ON" if self._walls_enabled else "Walls: OFF"
        self._build_overlay()       # redraw blocked/wall cells
        self._save_terrain()        # persist the preference
        state = "on" if self._walls_enabled else "off"
        n = len(self.bm.disallowed_cells)
        self._combat_log_add(f"Wall auto-detection turned {state} ({n} blocked cells).")

    def _load_spell_effects(self):
        """Load spell effect data from JSON file if it exists."""
        if os.path.exists(self._effects_path):
            try:
                rpg.apply_spell_effect_configuration(self.bm, self._effects_path)
                self._build_spell_effect_metadata()
            except Exception as e:
                print(f"Warning: Failed to load spell effects: {e}")

    def _build_spell_effect_metadata(self):
        """Build metadata for spell effects to use in rendering."""
        for effect in self.bm.active_spell_effects:
            # Find the spell in all_spells to get its visual properties
            spell_color = None
            for spell_dict in self.all_spells:
                if spell_dict.get("name") == effect.spell.name:
                    # Look for terrain_color property (RGB array)
                    if "terrain_color" in spell_dict:
                        rgb = spell_dict["terrain_color"]
                        # Add alpha for semi-transparency
                        spell_color = tuple(rgb + [120])
                    break

            # Default color if not found
            if not spell_color:
                spell_color = (100, 180, 220, 120)  # Cyan

            self._effect_meta[effect.effect_id] = {
                "name": effect.spell.name,
                "color": spell_color,
                "cells": [(c.col, c.row) for c in effect.cells]
            }

    def _load_lighting(self):
        """Load lighting data from JSON file if it exists.

        When the encounter has no lighting file, reset to a fully-lit default so a
        previous encounter's darkness/sources don't bleed through on a swap.
        """
        if os.path.exists(self._lighting_path):
            try:
                with open(self._lighting_path, 'r') as f:
                    data = json.load(f)
                default_str = data.get("default_light", "BrightLight")
                default_lvl = self._parse_light_level(default_str)
                sources = []
                for src in data.get("light_sources", []):
                    lvl = self._parse_light_level(src.get("light_level", "BrightLight"))
                    sources.append((int(src["x"]), int(src["y"]),
                                   int(src.get("bright_radius", 20)),
                                   int(src.get("dim_radius", 40))))
                self.bm.apply_base_lighting(default_lvl, sources)
            except Exception as e:
                print(f"[App] Error loading lighting: {e}")
        else:
            # No lighting file for this encounter: clean, fully-lit default.
            self.bm.apply_base_lighting(rpg.VisibilityLevel.Clear, [])

    def _save_lighting(self, light_sources, default_light):
        """Save lighting data to JSON file."""
        # Convert enum to string
        light_str_map = {
            rpg.VisibilityLevel.Clear: "BrightLight",
            rpg.VisibilityLevel.Dim: "DimLight",
            rpg.VisibilityLevel.Dark: "Darkness",
            rpg.VisibilityLevel.MagicalDark: "MagicalDarkness",
            rpg.VisibilityLevel.Sunlight: "Sunlight",
        }
        default_str = light_str_map.get(default_light, "Darkness")

        data = {
            "default_light": default_str,
            "light_sources": light_sources
        }
        with open(self._lighting_path, 'w') as f:
            json.dump(data, f, indent=2)

        # Reload lighting into battle map
        self._load_lighting()

    @staticmethod
    def _parse_light_level(s: str) -> 'rpg.VisibilityLevel':
        """Convert string to VisibilityLevel enum."""
        mapping = {
            "BrightLight": rpg.VisibilityLevel.Clear,
            "DimLight": rpg.VisibilityLevel.Dim,
            "Darkness": rpg.VisibilityLevel.Dark,
            "MagicalDarkness": rpg.VisibilityLevel.MagicalDark,
            "Sunlight": rpg.VisibilityLevel.Sunlight,
        }
        return mapping.get(s, rpg.VisibilityLevel.Clear)

    def _clear_temporary_terrain(self):
        """Remove spell-created temporary terrain (regions with 'source' field)."""
        self._terrain_regions = [r for r in self._terrain_regions if "source" not in r]

    def _apply_terrain_to_battle_map(self):
        """Apply terrain regions to the C++ battle map multiplier system."""
        self.bm.reset_terrain_multipliers()
        for region in self._terrain_regions:
            terrain_type = region.get("type", "Difficult Terrain")
            if terrain_type == "Difficult Terrain":
                mult = region.get("multiplier", 0.5)
                px = region.get("x", 0)
                py = region.get("y", 0)
                pw = region.get("width", 0)
                ph = region.get("height", 0)
                if pw > 0 and ph > 0:
                    self._apply_pixel_terrain(px, py, pw, ph, mult)

    def _apply_pixel_terrain(self, px, py, pw, ph, mult):
        """Convert pixel coordinates to grid and apply multiplier."""
        import bisect
        s = self.map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        if not raw_v or not raw_h:
            return

        # Convert pixel coords (scaled) to original image coords
        ix, iy = px / s, py / s
        iw, ih = pw / s, ph / s

        # Find grid cell range using binary search
        c_start = max(0, bisect.bisect_right(raw_v, ix) - 1)
        r_start = max(0, bisect.bisect_right(raw_h, iy) - 1)
        c_end = min(self.bm.grid_cols - 1, bisect.bisect_right(raw_v, ix + iw) - 1)
        r_end = min(self.bm.grid_rows - 1, bisect.bisect_right(raw_h, iy + ih) - 1)

        width = max(1, c_end - c_start + 1)
        height = max(1, r_end - r_start + 1)

        self.bm.set_terrain_multiplier_rect(rpg.Cell(c_start, r_start), width, height, mult)

    # ─────────────────────────────────────────────────────────────────────
    #  Drawing
    # ─────────────────────────────────────────────────────────────────────
    def _draw_map(self):
        # Apply pan offset to map drawing
        panned_rect = self.map_rect.copy()
        panned_rect.x += self.pan_x
        panned_rect.y += self.pan_y
        self.screen.blit(self.map_surf, panned_rect)
        # Draw regular overlay unless lighting editor is active
        if not self.lighting_editor.active:
            self.screen.blit(self.overlay, panned_rect)
            # Draw lighting overlay if persistent toggle is on
            if self.show_lighting_overlay:
                self._draw_lighting_overlay()
        elif self.lighting_editor.show_overlay:
            # Draw lighting overlay if editor dialog toggle is on
            self._draw_lighting_overlay()

        # Rubber-band box while sampling a tile for a manual grid
        if (self._grid_sample_mode and self._grid_sample_start is not None
                and self._grid_sample_cur is not None):
            x0, y0 = self._grid_sample_start
            x1, y1 = self._grid_sample_cur
            box = pygame.Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            pygame.draw.rect(self.screen, (255, 220, 60), box, 2)

    def _draw_lighting_overlay(self):
        """Draw the lighting visualization overlay on the map."""
        if not self.bm or not self.map_rect:
            return

        cpx = self.bm.cell_pixel_size
        cols = self.bm.grid_cols
        rows = self.bm.grid_rows
        h_lines = self.bm.h_line_positions
        v_lines = self.bm.v_line_positions

        # Create a surface for the lighting overlay
        lighting_surf = pygame.Surface((self.map_rect.width, self.map_rect.height), pygame.SRCALPHA)

        # Draw each cell with its light level
        for r in range(rows):
            for c in range(cols):
                if c >= len(v_lines) - 1 or r >= len(h_lines) - 1:
                    continue

                # Get the light level at this cell
                light_level = self.bm.get_light_level(rpg.Cell(c, r))

                # Calculate opacity based on light level
                # BrightLight: 0% opacity (transparent)
                # DimLight: 50% opacity
                # Darkness: 90% opacity
                # MagicalDarkness: 100% opacity
                opacity = {
                    rpg.VisibilityLevel.Clear: 0,
                    rpg.VisibilityLevel.Dim: 128,      # 50% of 255
                    rpg.VisibilityLevel.Dark: 230,      # 90% of 255
                    rpg.VisibilityLevel.MagicalDark: 255,
                    rpg.VisibilityLevel.Sunlight: 45,  # faint warm tint (bright light, just flagged)
                }.get(light_level, 0)

                if opacity > 0:
                    # Draw semi-transparent overlay for this cell
                    cell_x = v_lines[c]
                    cell_y = h_lines[r]
                    cell_w = v_lines[c + 1] - v_lines[c]
                    cell_h = h_lines[r + 1] - h_lines[r]

                    # Color depends on light level
                    if light_level == rpg.VisibilityLevel.MagicalDark:
                        color = (0, 0, 0, opacity)  # Black for magical darkness
                    elif light_level == rpg.VisibilityLevel.Sunlight:
                        color = (255, 235, 130, opacity)  # warm yellow for sunlight
                    else:
                        color = (50, 50, 50, opacity)  # Dark grey for other darkness

                    pygame.draw.rect(lighting_surf, color, (cell_x, cell_y, cell_w, cell_h))

        # Blit the lighting overlay onto the screen with pan offset
        panned_rect = self.map_rect.copy()
        panned_rect.x += self.pan_x
        panned_rect.y += self.pan_y
        self.screen.blit(lighting_surf, panned_rect)

        # Draw markers for light sources (golden circles)
        h_lines = self.bm.h_line_positions
        v_lines = self.bm.v_line_positions

        for light_src in self.lighting_editor.light_sources:
            px = light_src["x"]
            py = light_src["y"]

            # Find grid cell containing this pixel
            grid_c = -1
            grid_r = -1
            for c in range(len(v_lines) - 1):
                if px >= v_lines[c] and px < v_lines[c + 1]:
                    grid_c = c
                    break
            for r in range(len(h_lines) - 1):
                if py >= h_lines[r] and py < h_lines[r + 1]:
                    grid_r = r
                    break

            if grid_c >= 0 and grid_r >= 0:
                # Draw a circle marker at the light source center
                cell_x = v_lines[grid_c]
                cell_y = h_lines[grid_r]
                cell_w = v_lines[grid_c + 1] - v_lines[grid_c]
                cell_h = h_lines[grid_r + 1] - h_lines[grid_r]
                center_x = cell_x + cell_w // 2
                center_y = cell_y + cell_h // 2
                radius = max(6, cell_w // 6)

                # Draw outer circle (golden yellow)
                pygame.draw.circle(self.screen, (255, 200, 0), (center_x, center_y), radius, 3)
                # Draw inner circle (bright yellow)
                pygame.draw.circle(self.screen, (255, 255, 100), (center_x, center_y), radius - 2, 1)

    def _draw_hp_bar(self, screen_x, screen_y, size_px, stats):
        """Draw a thin at-a-glance HP bar along the bottom edge of an agent's sprite.

        Reuses the panel's HP color convention (COL_HP_HIGH/MID/LOW at 66%/33%).
        Temp HP, if any, is shown as a cyan segment appended at the current-HP end.
        """
        hp_max = stats.hp_max
        if hp_max <= 0:
            return  # unknown/uninitialized HP — nothing meaningful to show
        hp_cur = max(0, stats.hp_cur)
        frac   = min(1.0, hp_cur / hp_max)

        inset = 2
        bar_h = max(3, size_px // 12)
        bar_w = size_px - 2 * inset
        bar_x = screen_x + inset
        bar_y = screen_y + size_px - bar_h - inset

        # Track (missing-HP background)
        pygame.draw.rect(self.screen, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))

        # Current-HP fill, colored by fraction
        hp_col = (COL_HP_HIGH if frac > 0.66 else
                  COL_HP_MID  if frac > 0.33 else
                  COL_HP_LOW)
        fill_w = int(round(bar_w * frac))
        if fill_w > 0:
            pygame.draw.rect(self.screen, hp_col, (bar_x, bar_y, fill_w, bar_h))

        # Temp HP overlay (cyan), clamped to the remaining bar width
        if stats.temp_hp > 0:
            temp_w = min(bar_w - fill_w, int(round(bar_w * (stats.temp_hp / hp_max))))
            if temp_w > 0:
                pygame.draw.rect(self.screen, (80, 200, 230),
                                 (bar_x + fill_w, bar_y, temp_w, bar_h))

        # Drained max-HP overlay (dark red): the slice of the maximum currently unavailable
        # (vampiric Bite life-drain, etc.), pinned to the right end of the bar.
        drained = getattr(stats, "available_hit_points", 0)
        if drained > 0:
            drain_w = min(bar_w, int(round(bar_w * (drained / hp_max))))
            if drain_w > 0:
                pygame.draw.rect(self.screen, (90, 20, 20),
                                 (bar_x + bar_w - drain_w, bar_y, drain_w, bar_h))

        # Outline for contrast over varied sprite art
        pygame.draw.rect(self.screen, (10, 10, 10), (bar_x, bar_y, bar_w, bar_h), 1)

    def _draw_one_agent(self, pt, screen_x, screen_y, cpx, alpha=255, tint=None, agent_idx=-1):
        """Draw a single agent (sprite or placeholder) at the given screen coords."""
        # Render gate: tombstoned agents (e.g. summons dismissed on concentration loss)
        # are kept in placedAgents_ to preserve indices but are no longer drawn.
        # (Future: reuse this gate for the Invisible condition — see known_limitations.md.)
        if getattr(pt, "removed_from_play", False):
            return
        size_px = cpx * pt.size
        sprite  = self._get_sprite(pt.sprite_path, size_px)
        if sprite:
            if alpha < 255 or tint:
                surf = sprite.copy()
                if tint:
                    surf.fill(tint, special_flags=pygame.BLEND_RGBA_MULT)
                surf.set_alpha(alpha)
                self.screen.blit(surf, (screen_x, screen_y))
            else:
                self.screen.blit(sprite, (screen_x, screen_y))
        else:
            r = pygame.Rect(screen_x+2, screen_y+2, size_px-4, size_px-4)
            placeholder = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
            fill_col    = tint if tint else COL_AGENT_FILL
            placeholder.fill((*fill_col[:3], alpha))
            self.screen.blit(placeholder, r)
            pygame.draw.rect(self.screen, COL_AGENT_BORDER, r, 2, border_radius=3)
        # Down hatching (diagonal lines when HP <= 0)
        if pt.stats.hp_cur <= 0:
            hatch = pygame.Surface((size_px, size_px), pygame.SRCALPHA)
            hatch.fill((0, 0, 0, 0))
            step = max(4, size_px // 8)
            col  = (180, 0, 0, 200)
            for offset in range(-size_px, size_px * 2, step):
                pygame.draw.line(hatch, col, (offset, 0), (offset + size_px, size_px), 2)
                pygame.draw.line(hatch, col, (offset + size_px, 0), (offset, size_px), 2)
            self.screen.blit(hatch, (screen_x, screen_y))

        # HP bar (skip translucent previews, e.g. movement ghosts)
        if alpha == 255:
            self._draw_hp_bar(screen_x, screen_y, size_px, pt.stats)

        # Name label
        lbl = self.font_sm.render(pt.name, True, (255, 255, 255))
        self.screen.blit(lbl, (screen_x + 3, screen_y + 3))

        # Concentration indicator (circle around agent if concentrating)
        if pt.conditions.concentrating:
            center_x = int(screen_x + size_px / 2)
            center_y = int(screen_y + size_px / 2)
            radius = int(size_px / 2 + 6)
            # Use the agent's own color if they're casting Hold Person, otherwise use orange
            caster_color = self._get_caster_color(agent_idx) if agent_idx >= 0 else (255, 200, 100)
            pygame.draw.circle(self.screen, caster_color, (center_x, center_y), radius, 2)
            spell_name = pt.conditions.concentrating_on or 'Spell'
            spell_lbl = self.font_sm.render(spell_name, True, caster_color)
            self.screen.blit(spell_lbl, (screen_x + size_px + 5, screen_y))

        # Paralyzed indicator (circle linking to caster)
        if pt.conditions.paralyzed and agent_idx >= 0:
            # Find the caster of the paralysis from active conditions
            for cond in self.combat.active_agent_conditions:
                if cond.agent_idx == agent_idx and cond.condition_name == "Paralyzed":
                    # Get caster's color - use a color based on caster index for visual linking
                    caster_color = self._get_caster_color(cond.caster_idx)
                    center_x = int(screen_x + size_px / 2)
                    center_y = int(screen_y + size_px / 2)
                    radius = int(size_px / 2 + 10)  # Slightly larger than concentration circle
                    pygame.draw.circle(self.screen, caster_color, (center_x, center_y), radius, 3)
                    break

        # Blinded indicator (circle linking to caster)
        if pt.conditions.blinded and agent_idx >= 0:
            # Find the caster of the blinded condition from active conditions
            for cond in self.combat.active_agent_conditions:
                if cond.agent_idx == agent_idx and cond.condition_name == "Blinded":
                    # Get caster's color - use a color based on caster index for visual linking
                    caster_color = self._get_caster_color(cond.caster_idx)
                    center_x = int(screen_x + size_px / 2)
                    center_y = int(screen_y + size_px / 2)
                    radius = int(size_px / 2 + 10)  # Slightly larger than concentration circle
                    pygame.draw.circle(self.screen, caster_color, (center_x, center_y), radius, 3)
                    break

        # Incapacitated indicator (circle linking to source)
        if pt.conditions.incapacitated and agent_idx >= 0:
            # Find the source of the incapacitated condition from active conditions
            for cond in self.combat.active_agent_conditions:
                if cond.agent_idx == agent_idx and cond.condition_name == "Incapacitated":
                    # Get source's color - use a color based on caster index for visual linking
                    source_color = self._get_caster_color(cond.caster_idx)
                    center_x = int(screen_x + size_px / 2)
                    center_y = int(screen_y + size_px / 2)
                    radius = int(size_px / 2 + 10)  # Slightly larger than concentration circle
                    pygame.draw.circle(self.screen, source_color, (center_x, center_y), radius, 3)
                    break

        # Stunned indicator (circle linking to source)
        if pt.conditions.stunned and agent_idx >= 0:
            # Find the source of the stunned condition from active conditions
            for cond in self.combat.active_agent_conditions:
                if cond.agent_idx == agent_idx and cond.condition_name == "Stunned":
                    # Get source's color - use a color based on caster index for visual linking
                    source_color = self._get_caster_color(cond.caster_idx)
                    center_x = int(screen_x + size_px / 2)
                    center_y = int(screen_y + size_px / 2)
                    radius = int(size_px / 2 + 10)  # Slightly larger than concentration circle
                    pygame.draw.circle(self.screen, source_color, (center_x, center_y), radius, 3)
                    break

        # Charmed indicator (circle linking to charmer)
        if pt.conditions.charmed and agent_idx >= 0:
            # Find the charmer from active conditions
            for cond in self.combat.active_agent_conditions:
                if cond.agent_idx == agent_idx and cond.condition_name == "Charmed":
                    # Get charmer's color - use a color based on charmer index for visual linking
                    charmer_color = self._get_caster_color(cond.caster_idx)
                    center_x = int(screen_x + size_px / 2)
                    center_y = int(screen_y + size_px / 2)
                    radius = int(size_px / 2 + 10)  # Slightly larger than concentration circle
                    pygame.draw.circle(self.screen, charmer_color, (center_x, center_y), radius, 3)
                    break

        # Grappled indicator (brown "GR" badge)
        if pt.conditions.grappled:
            badge_font = self.font_sm
            gr_badge = badge_font.render("GR", True, (210, 150, 80))  # Brown/tan
            badge_x = int(screen_x + 4)
            badge_y = int(screen_y + 4)
            self.screen.blit(gr_badge, (badge_x, badge_y))

        # Frightened indicator (purple "FR" badge)
        if pt.conditions.frightened:
            badge_font = self.font_sm
            fr_badge = badge_font.render("FR", True, (180, 100, 200))  # Purple
            badge_x = int(screen_x + 4)
            badge_y = int(screen_y + 22)  # Below grappled badge if both present
            self.screen.blit(fr_badge, (badge_x, badge_y))

        # Hidden indicator (eye-slash symbol)
        if pt.conditions.hidden:
            # Draw an eye-slash symbol in the top-right corner
            icon_font = self.font_md
            hidden_icon = icon_font.render("🚫", True, (200, 200, 200))
            icon_x = int(screen_x + size_px - 16)
            icon_y = int(screen_y - 8)
            self.screen.blit(hidden_icon, (icon_x, icon_y))

        # Death save bubbles (for unconscious agents)
        if pt.conditions.unconscious and pt.stats.hp_cur <= 0:
            bubble_radius = 3
            bubble_spacing = 2
            bubble_y = int(screen_y + size_px + 2)
            bubble_x_start = int(screen_x + size_px // 2 - (3 * (bubble_radius * 2 + bubble_spacing) // 2))

            # Draw 3 green bubbles for successes
            for i in range(3):
                x = bubble_x_start + i * (bubble_radius * 2 + bubble_spacing)
                if i < pt.conditions.death_save_successes:
                    pygame.draw.circle(self.screen, (50, 200, 50), (x, bubble_y), bubble_radius)
                else:
                    pygame.draw.circle(self.screen, (50, 100, 50), (x, bubble_y), bubble_radius, 1)

            # Draw 3 red bubbles for failures
            bubble_x_start_red = int(screen_x + size_px // 2 - (3 * (bubble_radius * 2 + bubble_spacing) // 2))
            bubble_y_red = bubble_y + bubble_radius * 2 + bubble_spacing
            for i in range(3):
                x = bubble_x_start_red + i * (bubble_radius * 2 + bubble_spacing)
                if i < pt.conditions.death_save_failures:
                    pygame.draw.circle(self.screen, (200, 50, 50), (x, bubble_y_red), bubble_radius)
                else:
                    pygame.draw.circle(self.screen, (100, 50, 50), (x, bubble_y_red), bubble_radius, 1)

        # Dead indicator (skull-and-crossbones or ⚰️)
        if pt.conditions.dead:
            skull_icon = self.font_lg.render("☠", True, (150, 50, 50))
            skull_x = int(screen_x + size_px // 2 - 8)
            skull_y = int(screen_y + size_px // 2 - 12)
            self.screen.blit(skull_icon, (skull_x, skull_y))

    def _draw_reach_overlays(self, cpx: int, raw_h=None, raw_v=None):
        """Draw walk (blue) and fly (gold) reachable-cell overlays."""
        # Get map dimensions if not provided
        if raw_h is None:
            raw_h = self.bm.h_line_positions
        if raw_v is None:
            raw_v = self.bm.v_line_positions

        # Walk range: semi-transparent cornflower blue
        if self._reach_walk:
            walk_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            walk_surf.fill((60, 120, 220, 55))
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, (80, 150, 255, 120),
                             border_surf.get_rect(), 1)
            map_w, map_h = self.map_rect.width, self.map_rect.height
            for cell in self._reach_walk:
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                    continue
                self.screen.blit(walk_surf,   (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

        # Fly range: semi-transparent gold — drawn on top so overlapping
        # cells show both colours (fly usually extends beyond walk).
        if self._reach_fly:
            fly_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fly_surf.fill((220, 180, 0, 45))
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, (255, 210, 0, 110),
                             border_surf.get_rect(), 1)
            map_w, map_h = self.map_rect.width, self.map_rect.height
            for cell in self._reach_fly:
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                    continue
                self.screen.blit(fly_surf,    (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

        # Jump range: semi-transparent cyan (when overlay is active)
        if self.jump_overlay_active and self.jump_reachable_cells:
            jump_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            jump_surf.fill((100, 200, 255, 70))
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, (150, 230, 255, 150),
                             border_surf.get_rect(), 2)
            for cell in self.jump_reachable_cells:
                # Skip cells outside map bounds
                if (cell.col < 0 or cell.row < 0 or
                    cell.col >= len(raw_v) or cell.row >= len(raw_h)):
                    continue
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                self.screen.blit(jump_surf,   (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

    def _draw_temp_terrain_overlays(self, cpx: int):
        """Draw temporary terrain effect overlays."""
        if not self.bm.has_active_terrain_effects():
            return

        s = self.map_scale
        raw_h = self.bm.h_line_positions
        raw_v = self.bm.v_line_positions

        for effect in self.bm.active_terrain_effects:
            # Color by the spell's name. Terrain effect ids share an integer space with
            # persistent spell-effect ids, so keying color off _effect_meta[id] bleeds the
            # latest spell-effect color onto all terrain. Look up terrain_color by name instead.
            color = None
            si = self.spell_name_to_idx.get(effect.name)
            if si is not None:
                rgb = self.all_spells[si].get("terrain_color")
                if rgb:
                    color = (rgb[0], rgb[1], rgb[2], 90)
            if color is None:
                # Default colors by difficulty
                if effect.difficulty == rpg.TerrainDifficulty.Halved:
                    color = (80, 200, 80, 80)  # Green
                elif effect.difficulty == rpg.TerrainDifficulty.Quartered:
                    color = (200, 60, 60, 80)  # Red
                else:
                    color = (100, 180, 220, 80)  # Cyan

            # Create surfaces for fill and border
            fill_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fill_surf.fill(color)
            border_color = tuple(min(c + 40, 255) for c in color[:3]) + (color[3],)
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, border_color, border_surf.get_rect(), 1)

            # Render each cell of the effect
            map_w, map_h = self.map_rect.width, self.map_rect.height
            for cell_idx in effect.cell_indices:
                # Convert flat index back to (col, row)
                col = cell_idx % self.bm.grid_cols
                row = cell_idx // self.bm.grid_cols
                if col < 0 or row < 0 or col >= len(raw_v) or row >= len(raw_h):
                    continue
                sx, sy = self._cell_to_screen(col, row)
                if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                    continue
                self.screen.blit(fill_surf, (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

            # Draw turns_remaining as a small label in the first cell
            if effect.cell_indices and effect.turns_remaining >= 0:
                first_idx = effect.cell_indices[0]
                col = first_idx % self.bm.grid_cols
                row = first_idx // self.bm.grid_cols
                if col >= 0 and row >= 0 and col < len(raw_v) and row < len(raw_h):
                    sx, sy = self._cell_to_screen(col, row)
                    # Draw a small number in the top-left corner
                    txt = self.font_sm.render(str(effect.turns_remaining), True, (255, 255, 255))
                    self.screen.blit(txt, (sx + 2, sy + 2))

    def _draw_spell_effects(self, cpx: int):
        """Draw persistent spell effect overlays."""
        if not self.show_spell_effects:
            return

        # Sync cache with C++ engine state before rendering
        self._sync_spell_effect_cache()

        active_effects = self.bm.active_spell_effects
        if not active_effects:
            return

        s = self.map_scale
        raw_h = self.bm.h_line_positions
        raw_v = self.bm.v_line_positions
        if not raw_h or not raw_v:
            return

        for effect in active_effects:
            # Build metadata for this effect if not already present
            if effect.effect_id not in self._effect_meta:
                spell_color = None
                for spell_dict in self.all_spells:
                    if spell_dict.get("name") == effect.spell.name:
                        if "terrain_color" in spell_dict:
                            rgb = spell_dict["terrain_color"]
                            spell_color = tuple(rgb + [120])
                        break
                if not spell_color:
                    spell_color = (100, 180, 220, 120)  # Cyan default
                self._effect_meta[effect.effect_id] = {
                    "name": effect.spell.name,
                    "color": spell_color,
                    "cells": [(c.col, c.row) for c in effect.cells]
                }

            # Get color from metadata
            if effect.effect_id in self._effect_meta:
                color = self._effect_meta[effect.effect_id].get("color", (100, 180, 220, 120))
            else:
                color = (100, 180, 220, 120)  # Cyan default

            # Create surfaces for fill and border
            fill_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fill_surf.fill(color)
            border_color = tuple(min(c + 40, 255) for c in color[:3]) + (color[3],)
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, border_color, border_surf.get_rect(), 1)

            # Render each cell of the effect
            map_w, map_h = self.map_rect.width, self.map_rect.height
            for cell in effect.cells:
                col = cell.col
                row = cell.row
                if col < 0 or row < 0 or col >= len(raw_v) or row >= len(raw_h):
                    continue
                sx, sy = self._cell_to_screen(col, row)
                if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                    continue
                self.screen.blit(fill_surf, (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

            # Draw turns_remaining as a small label in the first cell
            if effect.cells and effect.turns_remaining >= 0:
                first_cell = effect.cells[0]
                sx, sy = self._cell_to_screen(first_cell.col, first_cell.row)
                txt = self.font_sm.render(str(effect.turns_remaining), True, (255, 255, 255))
                self.screen.blit(txt, (sx + 2, sy + 2))

    def _draw_concentration_terrain(self, cpx: int):
        """Draw all terrain: permanent features and concentration-based effects."""
        if not self.show_terrain:
            return

        # Draw permanent terrain (walls, chasms, difficult terrain)
        for region in self._terrain_regions:
            # Skip concentration-based terrain for now (draw separately below)
            if "cells" in region or region.get("source", {}).get("requires_concentration"):
                continue

            # Permanent terrain from JSON
            if "x" not in region or "y" not in region:
                continue

            x = int(region.get("x", 0))
            y = int(region.get("y", 0))
            w = int(region.get("width", 0))
            h = int(region.get("height", 0))
            terrain_type = region.get("type", "Difficult Terrain")

            if terrain_type == "Wall":
                color = (0, 0, 0, 255)           # opaque black
            elif terrain_type == "Chasm":
                color = (128, 128, 128, 255)     # opaque grey
            elif terrain_type == "Water":
                color = (50, 100, 230, 128)      # blue, 50% transparent
            else:  # Difficult Terrain
                color = (139, 90, 43, 128)       # brown, 50% transparent

            # Anchor to the map's on-screen top-left, including the pan offset, so terrain
            # moves with the map when scrolling (the map blit also adds pan_x/pan_y).
            ox = self.map_rect.x + self.pan_x
            oy = self.map_rect.y + self.pan_y

            # Draw filled rectangle
            fill_surf = pygame.Surface((w, h), pygame.SRCALPHA)
            fill_surf.fill(color)
            self.screen.blit(fill_surf, (x + ox, y + oy))

            # Draw border
            border_rect = pygame.Rect(x + ox, y + oy, w, h)
            border_color = tuple(min(c + 40, 255) for c in color[:3]) + (color[3],)
            pygame.draw.rect(self.screen, border_color, border_rect, 2)

        # Concentration/spell terrain now renders via _draw_temp_terrain_overlays
        # (reads bm.active_terrain_effects); only static DM-painted terrain is drawn above.

    def _draw_hatching(self, pattern: str, x: float, y: float, w: float, h: float, color: tuple):
        """Draw a hatching pattern on the screen within bounds."""
        screen_x = int(x + self.map_rect.x + self.pan_x)
        screen_y = int(y + self.map_rect.y + self.pan_y)
        screen_w = int(w)
        screen_h = int(h)
        hatch_color = tuple(min(c + 100, 255) for c in color[:3]) + (120,)

        # Create a clipping rectangle for the hatching
        clip_rect = pygame.Rect(screen_x, screen_y, screen_w, screen_h)
        old_clip = self.screen.get_clip()
        self.screen.set_clip(clip_rect)

        if pattern == '//':
            for i in range(-screen_h, screen_w + screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i + screen_h, screen_y + screen_h), 1)
        elif pattern == '\\\\':
            for i in range(-screen_h, screen_w + screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i - screen_h, screen_y + screen_h), 1)
        elif pattern == '||':
            for i in range(0, screen_w, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i, screen_y + screen_h), 1)
        elif pattern == '--':
            for i in range(0, screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x, screen_y + i), (screen_x + screen_w, screen_y + i), 1)
        elif pattern == '++':
            for i in range(0, screen_w, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i, screen_y + screen_h), 1)
            for i in range(0, screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x, screen_y + i), (screen_x + screen_w, screen_y + i), 1)
        elif pattern == 'xx':
            for i in range(-screen_h, screen_w + screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i + screen_h, screen_y + screen_h), 1)
            for i in range(-screen_h, screen_w + screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i - screen_h, screen_y + screen_h), 1)

        # Restore the clip rect
        self.screen.set_clip(old_clip)

    def _draw_items(self, cpx: int):
        """Draw all weapon items sitting on the map grid."""
        items = self.bm.get_all_items()
        if not items:
            return

        # Group items by cell: dict[(col, row)] -> list[MapItem]
        by_cell: dict = {}
        for item in items:
            key = (item.cell.col, item.cell.row)
            by_cell.setdefault(key, []).append(item)

        ICON_FRAC = 0.45          # item icon is 45% of cell width
        CASCADE_OFFSET = 3        # pixels per stacked item offset
        ITEM_COL = (200, 170, 40) # amber/gold fill for fallback box
        ITEM_BORDER = (255, 215, 0)

        icon_px = max(8, int(cpx * ICON_FRAC))

        for (col, row), cell_items in by_cell.items():
            sx, sy = self._cell_to_screen(col, row)
            for stack_idx, item in enumerate(cell_items):
                offset = stack_idx * CASCADE_OFFSET
                ix = sx + offset + 2
                iy = sy + offset + 2
                # Try sprite first
                sprite = self._get_sprite(item.sprite_path, icon_px)
                if sprite:
                    self.screen.blit(sprite, (ix, iy))
                else:
                    # Fallback: amber colored box with weapon name initial
                    r = pygame.Rect(ix, iy, icon_px, icon_px)
                    pygame.draw.rect(self.screen, ITEM_COL, r, border_radius=2)
                    pygame.draw.rect(self.screen, ITEM_BORDER, r, 1, border_radius=2)
                    initial = item.weapon.name[0].upper() if item.weapon.name else "?"
                    lbl = self.font_sm.render(initial, True, (255, 255, 255))
                    self.screen.blit(lbl, (ix + (icon_px - lbl.get_width()) // 2,
                                           iy + (icon_px - lbl.get_height()) // 2))

    def _toggle_safe_target(self, hit: int):
        """Toggle an agent in/out of the edited Evoker's safe-target set; empty/self finishes."""
        caster = self.safe_target_edit_idx
        if caster < 0 or caster >= len(self.bm.placed_agents):
            self.safe_target_edit_idx = -1
            return
        if hit < 0 or hit == caster:
            self._combat_log_add(f"Done editing safe targets for {self.bm.placed_agents[caster].name}.")
            self.safe_target_edit_idx = -1
            return
        safe = list(self.combat.get_safe_targets(caster))
        if hit in safe:
            safe.remove(hit)
            verb = "no longer safe from"
        else:
            safe.append(hit)
            verb = "now safe from"
        self.combat.set_safe_targets(caster, safe)
        self._combat_log_add(
            f"{self.bm.placed_agents[hit].name} is {verb} {self.bm.placed_agents[caster].name}'s AoEs.")

    def _draw_safe_target_highlights(self):
        """While editing an Evoker's safe set, outline the Evoker (cyan) and its safe targets (green)."""
        if self.safe_target_edit_idx < 0:
            return
        agents = self.bm.placed_agents
        caster = self.safe_target_edit_idx
        if caster >= len(agents):
            return
        cpx = int(self.bm.cell_pixel_size * self.map_scale)
        safe = set(self.combat.get_safe_targets(caster))

        def _outline(idx, color):
            if idx < 0 or idx >= len(agents):
                return
            pt = agents[idx]
            sx, sy = self._cell_to_screen(pt.origin.col, pt.origin.row)
            size_px = cpx * pt.size
            pygame.draw.rect(self.screen, color, pygame.Rect(sx, sy, size_px, size_px), 3)

        _outline(caster, (100, 180, 220))   # the Evoker being edited (cyan)
        for idx in safe:
            _outline(idx, (60, 220, 80))     # safe allies (green)

    def _draw_paladin_auras(self, cpx):
        """Translucent gold ring around each Paladin showing its aura reach — Aura of
        Protection (L6+) / Aura of Courage (L10+): 10 ft, or 30 ft at L18. Same-team
        allies (and the Paladin) inside the ring get the aura; it vanishes while the
        Paladin is down (matching the engine's suppression)."""
        bm = self.bm
        GOLD = (255, 215, 90)
        clip = self.screen.get_clip()
        self.screen.set_clip(self.map_rect)
        for pt in bm.placed_agents:
            if pt.removed_from_play:
                continue
            st = pt.stats
            if st.character_class != rpg.CharacterClass.Paladin or st.char_level < 6:
                continue
            if pt.stats.hp_cur <= 0 or pt.conditions.unconscious or pt.conditions.incapacitated:
                continue  # aura suppressed while the Paladin is down
            radius_cells = 6 if st.char_level >= 18 else 2   # 30 ft / 10 ft (5 ft per cell)
            sx, sy = self._cell_to_screen(pt.origin.col, pt.origin.row)
            half = (pt.size * cpx) / 2.0
            r = int(radius_cells * cpx + half)
            if r <= 0:
                continue
            surf = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
            pygame.draw.circle(surf, (*GOLD, 22), (r, r), r)          # faint fill
            pygame.draw.circle(surf, (*GOLD, 140), (r, r), r, 2)      # ring outline
            self.screen.blit(surf, (int(sx + half) - r, int(sy + half) - r))
        self.screen.set_clip(clip)

    def _draw_agents(self):
        bm    = self.bm
        s     = self.map_scale
        cpx   = int(bm.cell_pixel_size * s)
        raw_h = bm.h_line_positions
        raw_v = bm.v_line_positions
        if not raw_h or not raw_v:
            return

        agents = bm.placed_agents

        # ── Movement reach overlays (beneath all agents) ──────────────────
        self._draw_reach_overlays(cpx, raw_h, raw_v)

        # ── Attack range overlays (beneath all agents) ────────────────────
        self._draw_attack_overlays(cpx)

        # ── Temporary terrain effects overlays (beneath all agents) ────────
        self._draw_temp_terrain_overlays(cpx)

        # ── Spell effect overlays (beneath all agents) ─────────────────────
        self._draw_spell_effects(cpx)

        # ── Concentration-based terrain overlays (beneath all agents) ──────
        self._draw_concentration_terrain(cpx)

        # ── Paladin aura rings (beneath all agents) ───────────────────────
        self._draw_paladin_auras(cpx)

        # ── Draw items on the map ─────────────────────────────────────────
        self._draw_items(cpx)

        # ── Draw all settled agents ───────────────────────────────────────
        for i, pt in enumerate(agents):
            if i == self.drag_idx:
                continue    # skip the one being dragged (draw as ghost below)
            if pt.removed_from_play:
                continue    # tombstoned (dismissed summon): not rendered, not selectable
            sx, sy = self._cell_to_screen(pt.origin.col, pt.origin.row)
            self._draw_one_agent(pt, sx, sy, cpx, agent_idx=i)

            # Selection highlight (yellow border)
            if i == self.selected_idx:
                size_px = cpx * pt.size
                pygame.draw.rect(self.screen, (255, 215, 0),
                                 pygame.Rect(sx, sy, size_px, size_px), 3,
                                 border_radius=3)

        # ── Spell AoE preview (above agents, below drag ghost) ───────────
        self._draw_spell_aoe_preview(cpx)
        self._draw_chromatic_chain(cpx)

        # ── Draw drag ghost ───────────────────────────────────────────────
        if self.drag_idx >= 0 and self.drag_cell is not None:
            pt  = agents[self.drag_idx]
            sx, sy = self._cell_to_screen(self.drag_cell.col, self.drag_cell.row)
            tint = (100, 255, 100) if self.drag_valid else (255, 80, 80)
            self._draw_one_agent(pt, sx, sy, cpx, alpha=180, tint=tint)
            # Outline
            size_px = cpx * pt.size
            border_col = (80, 220, 80) if self.drag_valid else (220, 60, 60)
            pygame.draw.rect(self.screen, border_col,
                             pygame.Rect(sx, sy, size_px, size_px), 3,
                             border_radius=3)

        # ── Draw placement mode ghost ──────────────────────────────────────
        if self.placement_mode_active and self.placement_cell is not None:
            sx, sy = self._cell_to_screen(self.placement_cell.col, self.placement_cell.row)
            size_px = cpx * self.placement_config.size
            # Draw sprite if it exists
            sprite = self._get_sprite(self.placement_config.sprite_path, size_px)
            if sprite:
                surf = sprite.copy()
                surf.set_alpha(200)
                self.screen.blit(surf, (sx, sy))
            else:
                # Draw placeholder
                r = pygame.Rect(sx + 2, sy + 2, size_px - 4, size_px - 4)
                placeholder = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
                placeholder.fill((150, 150, 200, 200))
                self.screen.blit(placeholder, r)
            # Red outline if invalid, green if valid
            border_col = (220, 60, 60) if not self.placement_valid else (80, 220, 80)
            pygame.draw.rect(self.screen, border_col,
                             pygame.Rect(sx, sy, size_px, size_px), 3,
                             border_radius=3)

        # ── Summon placement preview ───────────────────────────────────────
        if self.pending_summon_slot and self.summon_hover_cell is not None:
            cell = self.summon_hover_cell
            mob  = self.mob_stats_json.get(self.pending_summon_monster, {})
            ssize = self._size_category_to_grid_size(mob.get("size", "Medium"))
            valid = self._summon_cell_valid(cell, ssize)
            sx, sy = self._cell_to_screen(cell.col, cell.row)
            size_px = cpx * ssize
            sprite = self._get_sprite(self._get_mob_sprite_path(self.pending_summon_monster), size_px)
            if sprite:
                surf = sprite.copy()
                surf.set_alpha(160)
                if not valid:
                    surf.fill((255, 90, 90), special_flags=pygame.BLEND_RGBA_MULT)
                self.screen.blit(surf, (sx, sy))
            else:
                r = pygame.Rect(sx + 2, sy + 2, size_px - 4, size_px - 4)
                ph = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
                ph.fill((80, 220, 80, 150) if valid else (220, 60, 60, 150))
                self.screen.blit(ph, r)
            border_col = (80, 220, 80) if valid else (220, 60, 60)
            pygame.draw.rect(self.screen, border_col,
                             pygame.Rect(sx, sy, size_px, size_px), 3, border_radius=3)

    def _summon_cell_valid(self, cell, size) -> bool:
        """Whether the pending summon may be placed at `cell` (range + LOS + unoccupied).
        Same rule (helpers.summon_cell_placeable) that _resolve_summon enforces; used to
        colour the placement preview."""
        caster_idx = self._current_agent_idx()
        if caster_idx < 0:
            return False
        spells = self.combat.get_agent_spells(self.bm, caster_idx)
        sp = spells[self.pending_summon_idx] if 0 <= self.pending_summon_idx < len(spells) else None
        if sp is None:
            return False
        caster = self.bm.placed_agents[caster_idx]
        return summon_cell_placeable(self.bm, caster.origin, caster.size, cell, size, sp.range)

    def _draw_combat_panel(self):
        """Draw the right panel while combat is active."""
        # Stale-rect guard: every combat-action button below is (re)positioned only on the
        # frame it is actually drawn. Park them all off-screen first so a button that is NOT
        # drawn this frame can't capture clicks at a stale location — e.g. one agent's
        # grapple/dash button overlapping a Bard's Grant Inspiration button. (All btn_cbt_*
        # buttons are drawn exclusively within this method, so this is safe.)
        for _bname, _btn in vars(self).items():
            if _bname.startswith("btn_cbt_") and isinstance(_btn, Button):
                _btn.rect.x = -10000

        sw, sh = self.screen.get_size()
        px = self._panel_x()
        lx = px + self._PANEL_PAD
        W  = PANEL_W - self._PANEL_PAD * 2
        HW = W // 2 - 2
        B  = self._BTN_H
        gap = 4
        section_gap = 8

        # Background + border
        pygame.draw.rect(self.screen, COL_PANEL_BG, pygame.Rect(px, 0, PANEL_W, sh))
        pygame.draw.line(self.screen, COL_PANEL_BORDER, (px, 0), (px, sh))

        def txt(s, x, y, col=COL_TEXT, fnt=None):
            surf = (fnt or self.font_sm).render(s, True, col)
            self.screen.blit(surf, (x, y))

        y = 10

        # ── Title ──────────────────────────────────────────────────────────
        txt("⚔  Combat", lx, y, COL_INITIATIVE_CUR, self.font_lg)
        y += 28

        # ── Initiative list ────────────────────────────────────────────────
        txt("Initiative Order", lx, y, COL_LABEL)
        y += 16
        agents = self.bm.placed_agents
        self.initiative_item_rects = []  # Reset for this frame
        for i, entry in enumerate(self.initiative_order[:8]):
            aidx   = entry.agent_idx
            is_cur = (i == self.turn_idx)
            col    = COL_INITIATIVE_CUR if is_cur else COL_TEXT
            name   = agents[aidx].name if aidx < len(agents) else "?"
            alive  = True
            dismissed = (aidx < len(agents) and agents[aidx].removed_from_play)
            if aidx < len(agents):
                s = self.combat.get_agent_stats(self.bm, aidx)
                alive = s.hp_cur > 0
            if not alive or dismissed:
                col = (90, 90, 90)
            prefix = "▶ " if is_cur else "  "
            suffix = "  (dismissed)" if dismissed else ""
            row_s  = f"{prefix}{entry.total:2d}  {name}{suffix}"
            txt(row_s, lx, y, col)
            # Track clickable area for this initiative item
            item_rect = pygame.Rect(lx, y, W, 16)
            self.initiative_item_rects.append((item_rect, aidx))
            y += 16
        if len(self.initiative_order) > 8:
            txt(f"  …+{len(self.initiative_order)-8} more", lx, y, COL_LABEL)
            y += 16

        y += section_gap

        # ── Separator ──────────────────────────────────────────────────────
        pygame.draw.line(self.screen, COL_PANEL_BORDER,
                         (px + 6, y), (px + PANEL_W - 6, y))
        y += section_gap

        # ── Current combatant info ─────────────────────────────────────────
        cur_idx = self._current_agent_idx()
        if 0 <= cur_idx < len(agents):
            pt    = agents[cur_idx]
            stats = self.combat.get_agent_stats(self.bm, cur_idx)
            frac  = stats.hp_cur / max(stats.hp_max, 1)
            hp_col = (COL_HP_HIGH if frac > 0.66 else
                      COL_HP_MID  if frac > 0.33 else
                      COL_HP_LOW)
            txt(f"Turn: {pt.name}", lx, y, COL_TEXT, self.font_md)
            y += 20

            # Draw HP bar with temp HP indicator
            total_bar_width = stats.hp_max + stats.temp_hp
            bar_width = W if total_bar_width == 0 else W * (stats.hp_max / max(total_bar_width, 1))
            temp_hp_width = W - bar_width

            pygame.draw.rect(self.screen, (50, 50, 50),
                             pygame.Rect(lx, y, W, 12), border_radius=3)
            # Draw regular HP in color
            pygame.draw.rect(self.screen, hp_col,
                             pygame.Rect(lx, y, int(bar_width), 12), border_radius=3)
            # Draw temp HP in blue
            if stats.temp_hp > 0:
                pygame.draw.rect(self.screen, (100, 150, 255),
                                 pygame.Rect(lx + int(bar_width), y, int(temp_hp_width), 12), border_radius=3)

            # Display HP text with temp HP indicator (and any drained max-HP)
            drained = getattr(stats, "available_hit_points", 0)
            drain_sfx = f" [-{drained} max]" if drained > 0 else ""
            eff_max = stats.hp_max - drained
            if stats.temp_hp > 0:
                txt(f"HP {stats.hp_cur} (+{stats.temp_hp}){drain_sfx}", lx + W//2 - 40, y - 1)
            else:
                txt(f"HP {stats.hp_cur}/{eff_max}{drain_sfx}", lx + W//2 - 22, y - 1)
            y += 12

            # ── Focus Points display (Monk) ────────────────────────────────────
            if stats.character_class == rpg.CharacterClass.Monk:
                fp = stats.get_resource("Focus Points")
                if fp:
                    # Draw Focus Points bar
                    fp_bar_width = W * (fp.current / max(fp.max, 1)) if fp.max > 0 else 0
                    pygame.draw.rect(self.screen, (50, 50, 50),
                                     pygame.Rect(lx, y, W, 12), border_radius=3)
                    pygame.draw.rect(self.screen, (150, 180, 255),
                                     pygame.Rect(lx, y, int(fp_bar_width), 12), border_radius=3)
                    txt(f"Focus Pts {fp.current}/{fp.max}", lx + W//2 - 45, y - 1)
                    y += 12

            # ── Exhaustion display ─────────────────────────────────────────────
            cond = self.combat.get_agent_conditions(self.bm, cur_idx)
            if cond.exhaustion_level >= 1:
                exh_col = ((200, 100, 50) if cond.exhaustion_level < 6 else
                          (200, 50, 50))  # Red at level 6 (death)
                txt(f"🔗 Exhaustion L{cond.exhaustion_level}", lx, y, exh_col, self.font_sm)
                y += 16

            # ── Death saves display (if unconscious) ────────────────────────

            if cond.unconscious and stats.hp_cur <= 0:
                y += 8
                if cond.dead:
                    txt("DEAD", lx, y, (200, 50, 50), self.font_md)
                    y += 16
                elif cond.stabilized:
                    txt("Stabilized", lx, y, (100, 200, 100), self.font_md)
                    y += 16
                else:
                    txt(f"Death Saves: {cond.death_save_successes}/3 {cond.death_save_failures}/3", lx, y, (200, 200, 150), self.font_sm)
                    y += 14
                    # Draw bubble visualization in panel
                    bubble_radius = 2
                    bubble_spacing = 1
                    bubble_x_start = lx
                    bubble_y = y

                    # Green bubbles for successes
                    txt("✓", bubble_x_start, bubble_y - 8, (100, 200, 100), self.font_sm)
                    for i in range(3):
                        x = bubble_x_start + 16 + i * (bubble_radius * 2 + bubble_spacing)
                        if i < cond.death_save_successes:
                            pygame.draw.circle(self.screen, (100, 200, 100), (x, bubble_y), bubble_radius)
                        else:
                            pygame.draw.circle(self.screen, (50, 100, 50), (x, bubble_y), bubble_radius, 1)

                    # Red bubbles for failures
                    bubble_y_red = bubble_y + 10
                    txt("✗", bubble_x_start, bubble_y_red - 8, (200, 100, 100), self.font_sm)
                    for i in range(3):
                        x = bubble_x_start + 16 + i * (bubble_radius * 2 + bubble_spacing)
                        if i < cond.death_save_failures:
                            pygame.draw.circle(self.screen, (200, 100, 100), (x, bubble_y_red), bubble_radius)
                        else:
                            pygame.draw.circle(self.screen, (100, 50, 50), (x, bubble_y_red), bubble_radius, 1)

                    y += 24

        y += section_gap

        # ── Action section ─────────────────────────────────────────────────
        act_lbl = "Action" + (" ✓" if self.action_used else "")
        txt(act_lbl, lx, y, COL_LABEL)
        y += 16

        # Check weapon/spell capability for current agent.
        _cur_has_weapons = False
        _cur_has_offhand = False
        _cur_can_spell   = False
        _cur_has_spells  = False
        if 0 <= cur_idx < len(agents):
            _cur_has_weapons = len(self.combat.get_agent_weapons(self.bm, cur_idx)) > 0
            _cur_has_offhand = self._offhand_bonus_available(cur_idx)
            _cur_has_spells  = len(self.combat.get_agent_spells(self.bm, cur_idx)) > 0
            _cur_can_spell   = _cur_has_spells  # can cast if has spells

        # Check if mid-sequence (attacks remaining, but action_used not yet set)
        mid_sequence_action = (self.attacks_remaining > 0 and self._attack_sequence_slot == "action")

        if self.action_used and not mid_sequence_action:
            txt("[Action used]", lx, y, (100, 100, 120))
            y += B
            # Nick: after the Attack action, relocate the off-hand attack here (frees the bonus
            # action). Only when the off-hand weapon has Nick + the agent has Weapon Mastery + the
            # off-hand attack hasn't been spent (checked by _nick_offhand_idx).
            if self._nick_offhand_idx(cur_idx) >= 0:
                self.btn_cbt_nick.rect.x = lx
                self.btn_cbt_nick.rect.y = y
                self.btn_cbt_nick.rect.w = W
                self.btn_cbt_nick.draw(self.screen)
                y += B + gap
        else:
            # Check if agent is Frightened - if so, only Dash is allowed
            cur_cond = self.combat.get_agent_conditions(self.bm, cur_idx) if 0 <= cur_idx < len(agents) else None
            is_frightened = cur_cond.frightened if cur_cond else False

            if is_frightened:
                # Frightened: only Dash button allowed
                txt("Frightened — must Dash", lx, y, (180, 100, 200))  # Purple
                y += B
                self.btn_cbt_dash.rect.x = lx
                self.btn_cbt_dash.rect.y = y
                self.btn_cbt_dash.rect.w = W
                self.btn_cbt_dash.draw(self.screen)
                y += B + gap
            else:
                # Attack and Pass buttons
                # Update Attack button label with attack count if mid-sequence
                if mid_sequence_action:
                    self.btn_cbt_atk_action.text = f"⚔ Attack ({self.attacks_remaining})"
                else:
                    self.btn_cbt_atk_action.text = "⚔ Attack"

                TW2_action = (W - gap) // 2
                self.btn_cbt_atk_action.rect.x  = lx
                self.btn_cbt_atk_action.rect.y  = y
                self.btn_cbt_atk_action.rect.w  = TW2_action
                self.btn_cbt_unarmed.rect.x     = lx + TW2_action + gap
                self.btn_cbt_unarmed.rect.y     = y
                self.btn_cbt_unarmed.rect.w     = TW2_action
                if _cur_has_weapons:
                    self.btn_cbt_atk_action.draw(self.screen)
                self.btn_cbt_unarmed.draw(self.screen)
                y += B + gap

                self.btn_cbt_pass_action.rect.x = lx
                self.btn_cbt_pass_action.rect.y = y
                self.btn_cbt_pass_action.rect.w = W
                self.btn_cbt_pass_action.draw(self.screen)
                y += B + gap

                # Dash, Dodge, Disengage, Hide buttons
                TW4 = (W - 12) // 4
                self.btn_cbt_dash.rect.x       = lx
                self.btn_cbt_dash.rect.y       = y
                self.btn_cbt_dash.rect.w       = TW4
                self.btn_cbt_dodge.rect.x      = lx + TW4 + gap
                self.btn_cbt_dodge.rect.y      = y
                self.btn_cbt_dodge.rect.w      = TW4
                self.btn_cbt_disengage.rect.x  = lx + 2 * (TW4 + gap)
                self.btn_cbt_disengage.rect.y  = y
                self.btn_cbt_disengage.rect.w  = TW4
                self.btn_cbt_hide.rect.x       = lx + 3 * (TW4 + gap)
                self.btn_cbt_hide.rect.y       = y
                self.btn_cbt_hide.rect.w       = TW4
                self.btn_cbt_dash.draw(self.screen)
                self.btn_cbt_dodge.draw(self.screen)
                self.btn_cbt_disengage.draw(self.screen)
                self.btn_cbt_hide.draw(self.screen)
                y += B + gap

                # Prone / Stand Up buttons
                cond = self.combat.get_agent_conditions(self.bm, cur_idx) if 0 <= cur_idx < len(agents) else None
                is_prone = cond.prone if cond else False
                if is_prone:
                    self.btn_cbt_standup.rect.x = lx
                    self.btn_cbt_standup.rect.y = y
                    self.btn_cbt_standup.rect.w = W
                    self.btn_cbt_standup.draw(self.screen)
                else:
                    self.btn_cbt_prone.rect.x = lx
                    self.btn_cbt_prone.rect.y = y
                    self.btn_cbt_prone.rect.w = W
                    self.btn_cbt_prone.draw(self.screen)
                y += B + gap

                # Cast Spell button (if available)
                if _cur_can_spell and _cur_has_spells:
                    self.btn_cbt_spell_action.rect.x = lx
                    self.btn_cbt_spell_action.rect.y = y
                    self.btn_cbt_spell_action.rect.w = W
                    self.btn_cbt_spell_action.draw(self.screen)
                    y += B + gap

        # ── Spell Slots / N/day display ────────────────────────────────────
        if 0 <= cur_idx < len(agents):
            stats = self.combat.get_agent_stats(self.bm, cur_idx)

            if stats.is_npc:
                # NPC N/day spell display
                spells = self.combat.get_agent_spells(self.bm, cur_idx)
                npc_spells = [sp for sp in spells if sp.uses_max > 0]
                if npc_spells:
                    y += 4
                    txt("Spells (N/day):", lx, y, (160, 120, 200), self.font_sm)
                    y += 14
                    for spell in npc_spells:
                        txt(f"{spell.name:20} {spell.uses_remaining}/{spell.uses_max}", lx, y, (200, 200, 220), self.font_sm)
                        y += 14
            else:
                # Player spell slot display (existing logic)
                slots_max = list(stats.spell_slots_max)
                if any(slots_max):
                    y += 4
                    slots_cur = list(stats.spell_slots_remaining)
                    pip_chars = []
                    for lvl in range(9):
                        if slots_max[lvl] > 0:
                            filled = min(slots_cur[lvl], slots_max[lvl])
                            empty = slots_max[lvl] - filled
                            lvl_label = {0:"C", 1:"1", 2:"2", 3:"3", 4:"4", 5:"5", 6:"6", 7:"7", 8:"8", 9:"9"}.get(lvl+1, "?")
                            pip_str = "●" * filled + "○" * empty
                            pip_chars.append(f"{lvl_label}:{pip_str}")
                    if pip_chars:
                        # Wrap spell slot display to multiple lines if needed
                        lines = []
                        current_line = "Spells: "
                        for i, level_str in enumerate(pip_chars):
                            test_str = current_line + level_str + ("  " if i < len(pip_chars) - 1 else "")
                            test_surf = self.font_sm.render(test_str, True, (160, 120, 200))
                            if test_surf.get_width() > W and current_line != "Spells: ":
                                lines.append(current_line.rstrip())
                                current_line = "  " + level_str + ("  " if i < len(pip_chars) - 1 else "")
                            else:
                                current_line = test_str
                        if current_line.strip():
                            lines.append(current_line)
                        for line in lines:
                            txt(line, lx, y, (160, 120, 200), self.font_sm)
                            y += 14

        y += section_gap

        # ── Portent Dice section (Diviner Wizards) ─────────────────────────
        if 0 <= cur_idx < len(agents):
            stats = self.combat.get_agent_stats(self.bm, cur_idx)
            is_wizard = stats.character_class == rpg.CharacterClass.Wizard
            is_diviner = stats.wizard_subclass == rpg.WizardSubclass.Diviner
            if is_wizard and is_diviner:
                portent_res = stats.get_resource("Portent Dice")
                if portent_res and len(stats.portent_dice) > 0:
                    txt("Portent Dice:", lx, y, (200, 180, 100), self.font_sm)
                    y += 14
                    # Show available dice
                    dice_str = ", ".join(str(d) for d in stats.portent_dice)
                    txt(f"  [{dice_str}]", lx, y, (220, 200, 120), self.font_sm)
                    y += 14
                    # Use Portent button
                    self.btn_cbt_use_portent.rect.x = lx
                    self.btn_cbt_use_portent.rect.y = y
                    self.btn_cbt_use_portent.rect.w = W
                    self.btn_cbt_use_portent.draw(self.screen)
                    y += B + gap
                    y += section_gap

        # ── Bonus Action section ───────────────────────────────────────────
        bon_lbl = "Bonus Action" + (" ✓" if self.bonus_used else "")
        txt(bon_lbl, lx, y, COL_LABEL)
        y += 16

        # Check if mid-sequence for bonus action
        mid_sequence_bonus = (self.attacks_remaining > 0 and self._attack_sequence_slot == "bonus")

        if self.bonus_used and not mid_sequence_bonus:
            txt("[Bonus used]", lx, y, (100, 100, 120))
            y += B
        else:
            # Update bonus button label with attack count if mid-sequence
            if mid_sequence_bonus:
                self.btn_cbt_atk_bonus.text = f"⚔ Bonus ({self.attacks_remaining})"
            else:
                self.btn_cbt_atk_bonus.text = "⚔ Bonus Atk"

            # Layout depends on whether spells are available
            if _cur_can_spell and _cur_has_spells:
                TW3_bonus = (W - 8) // 3
                self.btn_cbt_atk_bonus.rect.x   = lx
                self.btn_cbt_atk_bonus.rect.y   = y
                self.btn_cbt_atk_bonus.rect.w   = TW3_bonus
                self.btn_cbt_spell_bonus.rect.x = lx + TW3_bonus + gap
                self.btn_cbt_spell_bonus.rect.y = y
                self.btn_cbt_spell_bonus.rect.w = TW3_bonus
                self.btn_cbt_pass_bonus.rect.x  = lx + 2 * (TW3_bonus + gap)
                self.btn_cbt_pass_bonus.rect.y  = y
                self.btn_cbt_pass_bonus.rect.w  = TW3_bonus
                if _cur_has_offhand or mid_sequence_bonus:
                    self.btn_cbt_atk_bonus.draw(self.screen)
                self.btn_cbt_spell_bonus.draw(self.screen)
                self.btn_cbt_pass_bonus.draw(self.screen)
            else:
                self.btn_cbt_atk_bonus.rect.x  = lx
                self.btn_cbt_atk_bonus.rect.y  = y
                self.btn_cbt_atk_bonus.rect.w  = HW
                self.btn_cbt_pass_bonus.rect.x = lx + HW + gap
                self.btn_cbt_pass_bonus.rect.y = y
                self.btn_cbt_pass_bonus.rect.w = HW
                if _cur_has_offhand or mid_sequence_bonus:
                    self.btn_cbt_atk_bonus.draw(self.screen)
                self.btn_cbt_pass_bonus.draw(self.screen)
            y += B

        # Long Jump — costs a Bonus Action (house rule) and also spends movement. Lives in the
        # Bonus Action area and is only offered while the bonus action is available; executing a
        # jump consumes it (see _execute_jump). The engine's jump_agent still enforces the
        # remaining movement budget when a landing cell is clicked.
        if not self.bonus_used:
            y += gap
            self.btn_cbt_long_jump.rect.x = lx
            self.btn_cbt_long_jump.rect.y = y
            self.btn_cbt_long_jump.rect.w = W
            self.btn_cbt_long_jump.draw(self.screen)
            y += B + gap

        # Arcane Ward charging button (Abjurer L3+ with active ward)
        if not self.bonus_used and 0 <= cur_idx < len(agents):
            cur_stats = self.bm.placed_agents[cur_idx].stats
            if (cur_stats.character_class == rpg.CharacterClass.Wizard and
                cur_stats.wizard_subclass == rpg.WizardSubclass.Abjurer and
                cur_stats.char_level >= 3 and cur_stats.temp_hp > 0):
                self.btn_cbt_charge_arcane_ward.rect.x = lx
                self.btn_cbt_charge_arcane_ward.rect.y = y
                self.btn_cbt_charge_arcane_ward.rect.w = W
                self.btn_cbt_charge_arcane_ward.draw(self.screen)
                y += B + gap

        # Wild Shape button (Druid L2+)
        if not self.bonus_used and 0 <= cur_idx < len(agents):
            cur_stats = self.bm.placed_agents[cur_idx].stats
            if (cur_stats.character_class == rpg.CharacterClass.Druid and
                cur_stats.char_level >= 2):
                if cur_stats.wild_shape_active:
                    txt(f"🐺 {cur_stats.wild_shape_form_name}", lx, y, COL_LABEL)
                    y += 12
                    self.btn_cbt_wild_shape.text = "Exit Wild Shape"
                else:
                    self.btn_cbt_wild_shape.text = "🐺 Wild Shape"
                self.btn_cbt_wild_shape.rect.x = lx
                self.btn_cbt_wild_shape.rect.y = y
                self.btn_cbt_wild_shape.rect.w = W
                self.btn_cbt_wild_shape.draw(self.screen)
                y += B + gap

        # Shove buttons (only if there are adjacent enemies, outside the spell layout logic)
        if not self.bonus_used:
            _has_adjacent = False
            if 0 <= cur_idx < len(agents):
                cur_agent = agents[cur_idx]
                for i, agent in enumerate(agents):
                    if i == cur_idx:
                        continue
                    dx = abs(agent.origin.col - cur_agent.origin.col)
                    dy = abs(agent.origin.row - cur_agent.origin.row)
                    if max(dx, dy) <= 1:  # Adjacent (within 5ft)
                        _has_adjacent = True
                        break

            if _has_adjacent:
                TW2_shove = (W - gap) // 2
                self.btn_cbt_shove_push.rect.x  = lx
                self.btn_cbt_shove_push.rect.y  = y
                self.btn_cbt_shove_push.rect.w  = TW2_shove
                self.btn_cbt_shove_prone.rect.x = lx + TW2_shove + gap
                self.btn_cbt_shove_prone.rect.y = y
                self.btn_cbt_shove_prone.rect.w = TW2_shove
                self.btn_cbt_shove_push.draw(self.screen)
                self.btn_cbt_shove_prone.draw(self.screen)
                y += B + gap

            # Grapple buttons (only if there are adjacent enemies)
            if _has_adjacent:
                TW2_grapple = (W - gap) // 2
                # Check if current agent is grappled
                if 0 <= cur_idx < len(agents):
                    cur_conds = self.combat.get_agent_conditions(self.bm, cur_idx)
                    if cur_conds.grappled:
                        # Show escape button (full width, can't initiate new grapple while grappled)
                        self.btn_cbt_grapple_esc.rect.x = lx
                        self.btn_cbt_grapple_esc.rect.y = y
                        self.btn_cbt_grapple_esc.rect.w = W
                        self.btn_cbt_grapple_esc.draw(self.screen)
                        y += B + gap
                    else:
                        # Show initiate grapple button (split width with pass/escape placeholder)
                        self.btn_cbt_grapple.rect.x = lx
                        self.btn_cbt_grapple.rect.y = y
                        self.btn_cbt_grapple.rect.w = TW2_grapple
                        self.btn_cbt_grapple.draw(self.screen)
                        y += B + gap

            # Telekinetic Shove (general feat) — bonus action, 30 ft range (not gated on adjacency).
            if 0 <= cur_idx < len(agents):
                if self.combat.get_agent_stats(self.bm, cur_idx).has_feat("Telekinetic"):
                    self.btn_cbt_telekinetic.rect.x = lx
                    self.btn_cbt_telekinetic.rect.y = y
                    self.btn_cbt_telekinetic.rect.w = W
                    self.btn_cbt_telekinetic.draw(self.screen)
                    y += B + gap

            # Hide, Dash, Disengage (Cunning Action) buttons - only if agent has cunning action
            if 0 <= cur_idx < len(agents):
                agent = agents[cur_idx]
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.has_cunning_action:
                    self.btn_cbt_hide_bonus.rect.x = lx
                    self.btn_cbt_hide_bonus.rect.y = y
                    self.btn_cbt_hide_bonus.rect.w = W
                    self.btn_cbt_hide_bonus.draw(self.screen)
                    y += B + gap
                    self.btn_cbt_dash_bonus.rect.x = lx
                    self.btn_cbt_dash_bonus.rect.y = y
                    self.btn_cbt_dash_bonus.rect.w = W
                    self.btn_cbt_dash_bonus.draw(self.screen)
                    y += B + gap
                    self.btn_cbt_disengage_bonus.rect.x = lx
                    self.btn_cbt_disengage_bonus.rect.y = y
                    self.btn_cbt_disengage_bonus.rect.w = W
                    self.btn_cbt_disengage_bonus.draw(self.screen)
                    y += B + gap

            # Patient Defense (Dodge) button - Monk (L1+) with Focus Points, bonus action
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Monk:
                    fp = stats.get_resource("Focus Points")
                    if fp and fp.current > 0:
                        self.btn_cbt_patient_defense.rect.x = lx
                        self.btn_cbt_patient_defense.rect.y = y
                        self.btn_cbt_patient_defense.rect.w = W
                        self.btn_cbt_patient_defense.draw(self.screen)
                        y += B + gap

            # Step of the Wind button - Monk (L1+) with Focus Points, bonus action (Disengage + Dash)
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Monk:
                    fp = stats.get_resource("Focus Points")
                    if fp and fp.current > 0:
                        self.btn_cbt_step_of_wind.rect.x = lx
                        self.btn_cbt_step_of_wind.rect.y = y
                        self.btn_cbt_step_of_wind.rect.w = W
                        self.btn_cbt_step_of_wind.draw(self.screen)
                        y += B + gap

            # Rage button - only if agent is Barbarian, not raging, and has uses
            if 0 <= cur_idx < len(agents):
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Barbarian:
                    conds = self.combat.get_agent_conditions(self.bm, cur_idx)
                    rage_resource = stats.get_resource("Rage")
                    if not conds.raging and rage_resource and rage_resource.current > 0:
                        self.btn_cbt_rage.rect.x = lx
                        self.btn_cbt_rage.rect.y = y
                        self.btn_cbt_rage.rect.w = W
                        self.btn_cbt_rage.draw(self.screen)
                        y += B + gap

            # Magical Cunning button - Warlock (L2+) with the feature still available this long rest
            if 0 <= cur_idx < len(agents):
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Warlock:
                    mc = stats.get_resource("Magical Cunning")
                    if mc and mc.current > 0:
                        self.btn_cbt_magical_cunning.rect.x = lx
                        self.btn_cbt_magical_cunning.rect.y = y
                        self.btn_cbt_magical_cunning.rect.w = W
                        self.btn_cbt_magical_cunning.draw(self.screen)
                        y += B + gap

            # Healing Light button - Celestial Warlock (L3+) with dice left in the pool
            if 0 <= cur_idx < len(agents):
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if (stats.character_class == rpg.CharacterClass.Warlock and
                        stats.warlock_subclass == rpg.WarlockSubclass.Celestial and
                        stats.char_level >= 3):
                    hl = stats.get_resource("Healing Light")
                    if hl and hl.current > 0:
                        self.btn_cbt_healing_light.rect.x = lx
                        self.btn_cbt_healing_light.rect.y = y
                        self.btn_cbt_healing_light.rect.w = W
                        self.btn_cbt_healing_light.draw(self.screen)
                        y += B + gap

            # Channel Divinity (Magic action) buttons — Cleric (L2+) with a use remaining
            if 0 <= cur_idx < len(agents) and not self.action_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Cleric and stats.char_level >= 2:
                    cd = stats.get_resource("Channel Divinity")
                    if cd and cd.current > 0:
                        self.btn_cbt_turn_undead.rect.x = lx
                        self.btn_cbt_turn_undead.rect.y = y
                        self.btn_cbt_turn_undead.rect.w = W
                        self.btn_cbt_turn_undead.draw(self.screen)
                        y += B + gap
                        if (stats.cleric_subclass == rpg.ClericSubclass.LightDomain and
                                stats.char_level >= 3):
                            self.btn_cbt_radiance.rect.x = lx
                            self.btn_cbt_radiance.rect.y = y
                            self.btn_cbt_radiance.rect.w = W
                            self.btn_cbt_radiance.draw(self.screen)
                            y += B + gap

            # Steady Aim button - Rogue (L3+): advantage on next attack, but speed drops to 0
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                conds = self.combat.get_agent_conditions(self.bm, cur_idx)
                if (stats.character_class == rpg.CharacterClass.Rogue and
                        stats.char_level >= 3 and not conds.steady_aim):
                    self.btn_cbt_steady_aim.rect.x = lx
                    self.btn_cbt_steady_aim.rect.y = y
                    self.btn_cbt_steady_aim.rect.w = W
                    self.btn_cbt_steady_aim.draw(self.screen)
                    y += B + gap

            # War Priest button — War Cleric (L3+) with a War Priest use, bonus-action weapon attack
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if (stats.character_class == rpg.CharacterClass.Cleric and
                        stats.cleric_subclass == rpg.ClericSubclass.WarDomain and stats.char_level >= 3):
                    wp = stats.get_resource("War Priest")
                    if wp and wp.current > 0:
                        self.btn_cbt_war_priest.rect.x = lx
                        self.btn_cbt_war_priest.rect.y = y
                        self.btn_cbt_war_priest.rect.w = W
                        self.btn_cbt_war_priest.draw(self.screen)
                        y += B + gap

            # Martial Arts button — Monk (L1+), bonus-action unarmed strike (always available)
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Monk:
                    self.btn_cbt_martial_arts.rect.x = lx
                    self.btn_cbt_martial_arts.rect.y = y
                    self.btn_cbt_martial_arts.rect.w = W
                    self.btn_cbt_martial_arts.draw(self.screen)
                    y += B + gap

            # Flurry of Blows button — Monk (L1+) with Focus Points, two bonus-action unarmed strikes
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Monk:
                    fp = stats.get_resource("Focus Points")
                    if fp and fp.current > 0:
                        self.btn_cbt_flurry_of_blows.rect.x = lx
                        self.btn_cbt_flurry_of_blows.rect.y = y
                        self.btn_cbt_flurry_of_blows.rect.w = W
                        self.btn_cbt_flurry_of_blows.draw(self.screen)
                        y += B + gap

            # Second Wind button — Fighter (L1+) with a Second Wind use, bonus-action self-heal
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Fighter:
                    sw = stats.get_resource("Second Wind")
                    if sw and sw.current > 0:
                        self.btn_cbt_second_wind.rect.x = lx
                        self.btn_cbt_second_wind.rect.y = y
                        self.btn_cbt_second_wind.rect.w = W
                        self.btn_cbt_second_wind.draw(self.screen)
                        y += B + gap

            # Maneuver (Bonus) button — Battle Master with a Superiority Die: Rally / Feinting / Quick Toss
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if (stats.character_class == rpg.CharacterClass.Fighter and
                        stats.fighter_subclass == rpg.FighterSubclass.BattleMaster):
                    sd = stats.get_resource("Superiority Dice")
                    if sd and sd.current > 0:
                        self.btn_cbt_bm_maneuver.rect.x = lx
                        self.btn_cbt_bm_maneuver.rect.y = y
                        self.btn_cbt_bm_maneuver.rect.w = W
                        self.btn_cbt_bm_maneuver.draw(self.screen)
                        y += B + gap

            # One with Shadows button — Warlock (invocation 8). Free Invisibility while the
            # Warlock stands in Dim Light/Darkness; the click enforces the lighting gate.
            if 0 <= cur_idx < len(agents):
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Warlock and stats.has_invocation(8):
                    self.btn_cbt_one_with_shadows.rect.x = lx
                    self.btn_cbt_one_with_shadows.rect.y = y
                    self.btn_cbt_one_with_shadows.rect.w = W
                    self.btn_cbt_one_with_shadows.draw(self.screen)
                    y += B + gap

            # Action Surge button — Fighter (L1+), resets action_used (available anytime)
            if 0 <= cur_idx < len(agents):
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Fighter:
                    as_res = stats.get_resource("Action Surge")
                    if as_res and as_res.current > 0:
                        self.btn_cbt_action_surge.rect.x = lx
                        self.btn_cbt_action_surge.rect.y = y
                        self.btn_cbt_action_surge.rect.w = W
                        self.btn_cbt_action_surge.draw(self.screen)
                        y += B + gap

            # Lay on Hands button — Paladin (L1+), requires target selection for healing
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Paladin:
                    loh = stats.get_resource("Lay on Hands")
                    if loh and loh.current > 0:
                        self.btn_cbt_lay_on_hands.rect.x = lx
                        self.btn_cbt_lay_on_hands.rect.y = y
                        self.btn_cbt_lay_on_hands.rect.w = W
                        self.btn_cbt_lay_on_hands.draw(self.screen)
                        y += B + gap

            # Grant Inspiration button — Bard (bonus action), spend a Bardic Inspiration use
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.character_class == rpg.CharacterClass.Bard:
                    bi = stats.get_resource("Bardic Inspiration")
                    if bi and bi.current > 0:
                        self.btn_cbt_grant_inspiration.rect.x = lx
                        self.btn_cbt_grant_inspiration.rect.y = y
                        self.btn_cbt_grant_inspiration.rect.w = W
                        self.btn_cbt_grant_inspiration.draw(self.screen)
                        y += B + gap

            # Use Inspiration Die button — any creature currently holding a granted die
            # (free, no action). Primes a +die bonus on the holder's next d20 Test.
            if 0 <= cur_idx < len(agents):
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if stats.bardic_inspiration_die > 0:
                    self.btn_cbt_use_inspiration.rect.x = lx
                    self.btn_cbt_use_inspiration.rect.y = y
                    self.btn_cbt_use_inspiration.rect.w = W
                    self.btn_cbt_use_inspiration.draw(self.screen)
                    y += B + gap

            # Sacred Weapon button — Paladin Oath of Devotion (bonus action), spend a Channel Oath use
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if (stats.character_class == rpg.CharacterClass.Paladin and
                        stats.paladin_oath == rpg.PaladinOath.OathOfDevotion):
                    co = stats.get_resource("Channel Oath")
                    if co and co.current > 0 and stats.sacred_weapon_turns == 0:
                        self.btn_cbt_sacred_weapon.rect.x = lx
                        self.btn_cbt_sacred_weapon.rect.y = y
                        self.btn_cbt_sacred_weapon.rect.w = W
                        self.btn_cbt_sacred_weapon.draw(self.screen)
                        y += B + gap

            # Corona of Light button — Cleric Light Domain (L17+), Magic action, 1-minute aura
            if 0 <= cur_idx < len(agents) and not self.action_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if (stats.character_class == rpg.CharacterClass.Cleric and
                        stats.cleric_subclass == rpg.ClericSubclass.LightDomain and
                        stats.char_level >= 17 and stats.corona_of_light_turns == 0):
                    self.btn_cbt_corona.rect.x = lx
                    self.btn_cbt_corona.rect.y = y
                    self.btn_cbt_corona.rect.w = W
                    self.btn_cbt_corona.draw(self.screen)
                    y += B + gap

            # Telekinetic Movement button — Psi Warrior (L3+), once per rest, push a creature 30 ft
            if 0 <= cur_idx < len(agents):
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if (stats.character_class == rpg.CharacterClass.Fighter and
                        stats.fighter_subclass == rpg.FighterSubclass.PsiWarrior):
                    tk = stats.get_resource("Telekinetic Movement")
                    if tk and tk.current > 0:
                        self.btn_cbt_telekinetic.rect.x = lx
                        self.btn_cbt_telekinetic.rect.y = y
                        self.btn_cbt_telekinetic.rect.w = W
                        self.btn_cbt_telekinetic.draw(self.screen)
                        y += B + gap

            # Dread Ambusher button — Gloom Stalker Ranger (L3+): arm +2d6 Psychic on your next
            # weapon hit this turn (+10 ft Speed). WIS-mod uses/long rest, once per turn. Shows uses left.
            if 0 <= cur_idx < len(agents):
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if (stats.character_class == rpg.CharacterClass.Ranger and
                        stats.ranger_subclass == rpg.RangerSubclass.GloomStalker and
                        stats.char_level >= 3):
                    da = stats.get_resource("Dread Ambusher")
                    cond = self.combat.get_agent_conditions(self.bm, cur_idx)
                    if (da and da.current > 0 and not cond.dread_ambusher_used and
                            not cond.dreadful_strike_armed):
                        self.btn_cbt_dread_ambusher.text = f"Dread Ambusher ({da.current})"
                        self.btn_cbt_dread_ambusher.rect.x = lx
                        self.btn_cbt_dread_ambusher.rect.y = y
                        self.btn_cbt_dread_ambusher.rect.w = W
                        self.btn_cbt_dread_ambusher.draw(self.screen)
                        y += B + gap

            # Tireless button — Ranger (L10+): Magic action, 1d8 + WIS-mod temp HP to self.
            if 0 <= cur_idx < len(agents) and not self.action_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if (stats.character_class == rpg.CharacterClass.Ranger and
                        stats.char_level >= 10):
                    tl = stats.get_resource("Tireless")
                    if tl and tl.current > 0:
                        self.btn_cbt_tireless.text = f"Tireless ({tl.current})"
                        self.btn_cbt_tireless.rect.x = lx
                        self.btn_cbt_tireless.rect.y = y
                        self.btn_cbt_tireless.rect.w = W
                        self.btn_cbt_tireless.draw(self.screen)
                        y += B + gap

            # Nature's Veil button — Ranger (L14+): Bonus action, turn Invisible.
            if 0 <= cur_idx < len(agents) and not self.bonus_used:
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if (stats.character_class == rpg.CharacterClass.Ranger and
                        stats.char_level >= 14):
                    nv = stats.get_resource("Nature's Veil")
                    if nv and nv.current > 0:
                        self.btn_cbt_natures_veil.text = f"Nature's Veil ({nv.current})"
                        self.btn_cbt_natures_veil.rect.x = lx
                        self.btn_cbt_natures_veil.rect.y = y
                        self.btn_cbt_natures_veil.rect.w = W
                        self.btn_cbt_natures_veil.draw(self.screen)
                        y += B + gap

            # Primal Companion button — Beast Master Ranger (L3+): summon a Beast of
            # the Land/Sea/Sky, or dismiss the active companion (label toggles).
            if 0 <= cur_idx < len(agents):
                stats = self.combat.get_agent_stats(self.bm, cur_idx)
                if (stats.character_class == rpg.CharacterClass.Ranger and
                        stats.ranger_subclass == rpg.RangerSubclass.BeastMaster and
                        stats.char_level >= 3):
                    active = self._find_companion_idx(cur_idx) >= 0
                    self.btn_cbt_companion.text = ("🐾 Dismiss Companion" if active
                                                   else "🐾 Primal Companion")
                    self.btn_cbt_companion.rect.x = lx
                    self.btn_cbt_companion.rect.y = y
                    self.btn_cbt_companion.rect.w = W
                    self.btn_cbt_companion.draw(self.screen)
                    y += B + gap


        y += section_gap

        # ── Movement type toggles ──────────────────────────────────────────
        txt("Movement", lx, y, COL_LABEL)
        y += 16

        # Show exhaustion speed reduction if active
        mv_stats = self.combat.get_agent_stats(self.bm, cur_idx) if 0 <= cur_idx < len(self.bm.placed_agents) else None
        cur_cond = self.combat.get_agent_conditions(self.bm, cur_idx) if 0 <= cur_idx < len(self.bm.placed_agents) else None
        if cur_cond and cur_cond.exhaustion_level >= 1:
            reduction = 5 * cur_cond.exhaustion_level
            exh_note = f"(−{reduction}ft exhaustion)" if reduction < 30 else "(exhaustion: 0ft movement)"
            txt(exh_note, lx, y, (200, 100, 50), self.font_sm)
            y += 14
        mv_entries = [
            (rpg.MovementType.Walk,   "Walk",   self.move_remaining_walk,
             mv_stats.speed_walk   if mv_stats else 0),
            (rpg.MovementType.Fly,    "Fly",    self.move_remaining_fly,
             mv_stats.speed_fly    if mv_stats else 0),
            (rpg.MovementType.Swim,   "Swim",   self.move_remaining_swim,
             mv_stats.speed_swim   if mv_stats else 0),
            (rpg.MovementType.Burrow, "Burrow", self.move_remaining_burrow,
             mv_stats.speed_burrow if mv_stats else 0),
        ]
        available_mv = [(mt, lbl, rem, spd) for mt, lbl, rem, spd in mv_entries if spd > 0]
        self._move_type_btns = {}
        HW = W // 2 - 2
        for i, (mt, lbl, rem, spd) in enumerate(available_mv):
            bx = lx + (i % 2) * (HW + gap)
            by = y + (i // 2) * (B + gap)
            r  = pygame.Rect(bx, by, HW, B)
            self._move_type_btns[mt] = r
            if rem == 0:
                bg = (40, 40, 55)
                fg = (80, 80, 95)
            elif mt == self.move_type:
                bg = COL_BTN_ENDTURN
                fg = (230, 230, 230)
            else:
                bg = COL_BTN_PASS
                fg = (190, 190, 210)
            pygame.draw.rect(self.screen, bg, r, border_radius=4)
            surf = self.font_sm.render(f"{lbl}  {rem}ft", True, fg)
            self.screen.blit(surf, (bx + 4, by + (B - surf.get_height()) // 2))
        rows_used = max(1, (len(available_mv) + 1) // 2)
        y += rows_used * (B + gap)

        # Pending action hints
        if self.pending_attack_slot:
            rem = self.attacks_remaining
            _atk_hint = "→ Click a target on the map" + (f" ({rem} left)" if rem > 1 else "")
            txt(_atk_hint, lx, y, COL_INITIATIVE_CUR)
            y += 14
        elif self.pending_spell_slot:
            if self._pending_spell_is_wall():
                hint = ("Click the wall's end (sets direction & length)"
                        if self.spell_anchor_cell is not None
                        else "Click the wall's start point")
            elif self.pending_spell_is_aoe:
                hint = "Click a map location"
            else:
                hint = "Click a target"
            txt(f"→ {hint} to cast spell", lx, y, (190, 150, 255))
            y += 14
        elif self.pending_shove_slot:
            txt("→ Click a target to shove", lx, y, (190, 190, 150))
            y += 14
        elif self.pending_grapple_slot:
            txt("→ Click a target to grapple", lx, y, (190, 190, 150))
            y += 14
        elif self.pending_unarmed_type:
            hint_text = {
                "punch": "→ Click a target to punch",
                "grapple": "→ Click a target to grapple",
                "push": "→ Click a target to push",
            }.get(self.pending_unarmed_type, "→ Click a target")
            txt(hint_text, lx, y, (190, 190, 150))
            y += 14

        y += section_gap

        # ── Place Terrain / End Turn ───────────────────────────────────────
        HW = (W - 4) // 2
        self.btn_cbt_place_terrain.rect.x = lx
        self.btn_cbt_place_terrain.rect.y = y
        self.btn_cbt_place_terrain.rect.w = HW
        self.btn_cbt_place_terrain.draw(self.screen)

        self.btn_cbt_end_turn.rect.x  = lx + HW + 4
        self.btn_cbt_end_turn.rect.y  = y
        self.btn_cbt_end_turn.rect.w  = HW
        self.btn_cbt_end_turn.draw(self.screen)
        y += B + gap

        self.btn_show_terrain.rect.x = lx
        self.btn_show_terrain.rect.y = y
        self.btn_show_terrain.rect.w = HW
        self.btn_show_terrain.draw(self.screen)
        y += B + gap

        self.btn_show_spell_effects.rect.x = lx
        self.btn_show_spell_effects.rect.y = y
        self.btn_show_spell_effects.rect.w = HW
        self.btn_show_spell_effects.draw(self.screen)
        y += B + gap

        self.btn_show_visible_targets.rect.x = lx
        self.btn_show_visible_targets.rect.y = y
        self.btn_show_visible_targets.rect.w = HW
        self.btn_show_visible_targets.draw(self.screen)

        self.btn_cbt_end_combat.rect.x = lx + HW + 4
        self.btn_cbt_end_combat.rect.y = y
        self.btn_cbt_end_combat.rect.w = HW
        self.btn_cbt_end_combat.draw(self.screen)
        y += B + gap

        # Drop Concentration button (if current agent is concentrating)
        cur_idx = self._current_agent_idx()
        is_concentrating = (0 <= cur_idx < len(self.bm.placed_agents) and
                           self.bm.placed_agents[cur_idx].conditions.concentrating)
        if is_concentrating:
            self.btn_cbt_drop_concentration.rect.x = lx
            self.btn_cbt_drop_concentration.rect.y = y
            self.btn_cbt_drop_concentration.rect.w = W
            self.btn_cbt_drop_concentration.draw(self.screen)
            y += B + gap

        # Drop Weapon buttons (show only when slot has a real weapon)
        if 0 <= cur_idx < len(agents):
            cur_weapons = self.combat.get_agent_weapons(self.bm, cur_idx)
            slot_labels = [("Drop Main", cur_weapons[0], 0),
                          ("Drop Off",  cur_weapons[1], 1),
                          ("Drop Rng",  cur_weapons[2], 2)]
            drop_btns = [self.btn_cbt_drop_weapon_main,
                        self.btn_cbt_drop_weapon_off,
                        self.btn_cbt_drop_weapon_rng]
            for btn, (lbl, wpn, _slot_idx) in zip(drop_btns, slot_labels):
                if wpn.name and wpn.name != "Unnamed":
                    btn.text = lbl + f": {wpn.name[:10]}"
                    btn.rect.x = lx
                    btn.rect.y = y
                    btn.rect.w = W
                    btn.draw(self.screen)
                    y += B + gap

        y += section_gap

        # ── Combat log ─────────────────────────────────────────────────────
        txt("Combat Log:", lx, y, COL_LABEL)
        y += 16

        max_log_w = W - 2

        def _wrap_draw(s, x, start_y, max_w, fnt, line_h=15):
            """Draw s word-wrapped within max_w pixels; return the new y after last line."""
            y_pos = start_y
            remaining = s
            while remaining:
                if y_pos + line_h > sh:
                    break
                if fnt.size(remaining)[0] <= max_w:
                    txt(remaining, x, y_pos)
                    y_pos += line_h
                    break
                lo, hi = 0, len(remaining)
                while lo < hi - 1:
                    mid = (lo + hi) // 2
                    if fnt.size(remaining[:mid])[0] <= max_w:
                        lo = mid
                    else:
                        hi = mid
                cut = lo
                space = remaining.rfind(" ", 0, lo)
                if space > 0:
                    cut = space
                txt(remaining[:cut], x, y_pos)
                y_pos += line_h
                remaining = remaining[cut:].lstrip(" ")
            return y_pos + 2

        for msg in self.combat_log[:5]:
            y = _wrap_draw(msg, lx, y, max_log_w, self.font_sm)


    def _draw_panel(self):
        if self.combat_active:
            self._draw_combat_panel()
            return

        sw, sh = self.screen.get_size()
        px  = self._panel_x()
        lx  = px + self._PANEL_PAD          # left edge for text
        loff = self._LABEL_H + self._LABEL_GAP   # how far above a widget its label sits

        # Panel background + left border
        pygame.draw.rect(self.screen, COL_PANEL_BG,
                         pygame.Rect(px, 0, PANEL_W, sh))
        pygame.draw.line(self.screen, COL_PANEL_BORDER, (px, 0), (px, sh))

        # ── PC name input (after selecting PC class) ──────────────────────
        if self._pc_name_input:
            title = self.font_md.render("Enter character name:", True, COL_TEXT)
            self.screen.blit(title, (lx, 30))
            self._pc_name_input.draw(self.screen)
            hint = self.font_sm.render("Press Enter to continue", True, (150, 150, 150))
            self.screen.blit(hint, (lx, self._pc_name_input.rect.bottom + 8))
            return

        # ── Placement mode ─────────────────────────────────────────────────
        if self.placement_mode_active:
            title = self.font_lg.render("Click to place", True, (255, 200, 100))
            self.screen.blit(title, (lx, 20))
            status_col = (80, 220, 80) if self.placement_valid else (220, 60, 60)
            status_txt = "Valid placement" if self.placement_valid else "Invalid placement (ESC to cancel)"
            status = self.font_sm.render(status_txt, True, status_col)
            self.screen.blit(status, (lx, 50))
            return

        # ── Title ─────────────────────────────────────────────────────────
        _, _, title_y, *_ = self._panel_layout()
        title = self.font_lg.render("⚔  Agent Config", True, COL_TEXT)
        self.screen.blit(title, (lx, title_y))

        # ── Field labels (sit loff px above their widget) ──────────────
        def label(text, x, widget_y):
            t = self.font_sm.render(text, True, COL_LABEL)
            self.screen.blit(t, (x, widget_y - loff))

        # ── Widgets ───────────────────────────────────────────────────────
        for w in [self.btn_select_mob, self.btn_select_pc, self.btn_clear, self.btn_save,
                  self.btn_load, self.btn_import_ddb]:
            w.draw(self.screen)

        # Current save-file hint (updates when user picks a different path)
        hint_txt = os.path.basename(self._save_path) if self._save_path else ""
        hint = self.font_sm.render(hint_txt, True, (100, 100, 130))
        self.screen.blit(hint, (lx, self.btn_begin_combat.rect.bottom + 4))

        # ── Long Rest / Short Rest buttons (only when agents are placed) ──
        if self.bm.placed_agents:
            self.btn_long_rest.draw(self.screen)
            self.btn_short_rest.draw(self.screen)

        # ── Begin Combat button (only when agents are placed) ─────────────
        if self.bm.placed_agents:
            self.btn_begin_combat.draw(self.screen)

        # ── Edit Terrain button ────────────────────────────────────────────
        self.btn_edit_terrain.draw(self.screen)

        # ── Show/Hide Terrain toggle (shared with the combat panel) ────────
        # Re-anchor each frame: the combat panel resizes this same button, so we
        # restore the pre-combat slot (full width, below Edit Terrain) here.
        self.btn_show_terrain.rect.update(
            self.btn_edit_terrain.rect.x,
            self.btn_edit_terrain.rect.bottom + self._BTN_GAP,
            self.btn_edit_terrain.rect.w, self._BTN_H)
        self.btn_show_terrain.text = "Hide Terrain" if self.show_terrain else "Show Terrain"
        self.btn_show_terrain.draw(self.screen)

        # ── Save / Load Terrain (file pickers) ─────────────────────────────
        self.btn_save_terrain.draw(self.screen)
        self.btn_load_terrain.draw(self.screen)

        # ── Edit Lighting button ───────────────────────────────────────────
        self.btn_edit_lighting.draw(self.screen)

        # ── Toggle Lighting Overlay button ─────────────────────────────────
        self.btn_toggle_lighting.draw(self.screen)

        # ── Toggle Wall Auto-Detection button ──────────────────────────────
        self.btn_toggle_walls.draw(self.screen)

        # ── Set Grid (sample a tile) button ────────────────────────────────
        self.btn_set_grid.draw(self.screen)

        # ── Quit button ────────────────────────────────────────────────────
        self.btn_quit.draw(self.screen)

        # ── Grid / map stats (bottom of panel) ───────────────────────────
        def text(txt, x, y, color=COL_LABEL):
            """Plain text blit with no offset (unlike label() which is for widgets)."""
            t = self.font_sm.render(txt, True, color)
            self.screen.blit(t, (x, y))

        info_y = sh - 72
        text(f"Grid: {self.bm.grid_cols}×{self.bm.grid_rows}  "
             f"cell={self.bm.cell_pixel_size}px  scale={self.map_scale:.2f}",
             lx, info_y)
        text(f"Walls: {len(self.bm.walls)}   Blocked: {len(self.bm.disallowed_cells)}",
             lx, info_y + 18)
        text(f"Agents placed: {len(self.bm.placed_agents)}", lx, info_y + 36)

        # Transient confirmation (e.g. "Terrain saved: …")
        if self._status_msg and pygame.time.get_ticks() < self._status_msg_until:
            text(self._status_msg, lx, info_y - 20, (120, 220, 140))

    # ─────────────────────────────────────────────────────────────────────
    #  Event handling
    # ─────────────────────────────────────────────────────────────────────
    def _panel_rect(self):
        return pygame.Rect(self._panel_x(), 0, PANEL_W, self.screen.get_height())

    def _modal_active(self) -> bool:
        """True if any scroll-capturing dialog/menu is open. Used to suppress
        map-level input (wheel/arrow panning) so scrolling a menu doesn't also
        pan the map underneath it."""
        return (self.stats_dialog.active or self.spell_dialog.active or
                self.weapon_dialog.active or self.armor_dialog.active or
                self.weapons_dialog.active or self.conditions_dialog.active or
                self.file_browser.active or self.terrain_placement_dialog.active or
                self.terrain_editor.active or self.lighting_editor.active or
                self.weapon_selection_dialog.visible or
                self.armor_selection_dialog.visible or
                self.spell_selection_dialog.visible or
                self.mob_dialog.visible or self.context_menu.visible or
                self._grid_span_dialog.visible or self.name_prompt.visible)

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            # Map-level pan input (wheel / arrow keys) is suppressed while any
            # menu is open, so scrolling a dialog doesn't also pan the map.
            map_input_allowed = not self._modal_active()

            # ── Grid sample mode: drag one tile to define a uniform grid ──────
            # Intercepts left-click drags on the map before any agent/placement
            # handling. Panel clicks (e.g. cancelling via the button) fall through.
            if self._grid_sample_mode and map_input_allowed and hasattr(event, "pos"):
                on_map_evt = self.map_rect.move(self.pan_x, self.pan_y).collidepoint(event.pos)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and on_map_evt:
                    self._grid_sample_start = event.pos
                    self._grid_sample_cur   = event.pos
                    continue
                if event.type == pygame.MOUSEMOTION and self._grid_sample_start is not None:
                    self._grid_sample_cur = event.pos
                    continue
                if (event.type == pygame.MOUSEBUTTONUP and event.button == 1
                        and self._grid_sample_start is not None):
                    self._finalize_grid_sample(self._grid_sample_start, event.pos)
                    self._grid_sample_start = None
                    self._grid_sample_cur   = None
                    continue

            # ── Mouse wheel for map panning ───────────────────────────────
            if map_input_allowed and event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 4:  # Scroll up
                    if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                        self.pan_x += 30
                    else:
                        self.pan_y += 30
                elif event.button == 5:  # Scroll down
                    if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                        self.pan_x -= 30
                    else:
                        self.pan_y -= 30
            # Newer pygame versions use MOUSEWHEEL event
            elif map_input_allowed and hasattr(pygame, 'MOUSEWHEEL') and event.type == pygame.MOUSEWHEEL:
                if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                    self.pan_x += event.x * 30
                else:
                    self.pan_y += event.y * 30

            # ── Keyboard panning (arrow keys) ─────────────────────────────
            if map_input_allowed and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_UP:
                    self.pan_y += 30
                elif event.key == pygame.K_DOWN:
                    self.pan_y -= 30
                elif event.key == pygame.K_LEFT:
                    self.pan_x += 30
                elif event.key == pygame.K_RIGHT:
                    self.pan_x -= 30

            # ── Copy / paste agents (Ctrl+C / Ctrl+V; Cmd on macOS) — pre-combat only ──
            if (map_input_allowed and event.type == pygame.KEYDOWN
                    and (event.mod & (pygame.KMOD_CTRL | pygame.KMOD_META))
                    and not self.combat_active
                    and not self._pc_name_input
                    and not self.placement_mode_active):
                if event.key == pygame.K_c:
                    self._copy_agent(self.selected_idx)
                elif event.key == pygame.K_v:
                    mx, my = pygame.mouse.get_pos()
                    self._paste_agent(self._screen_to_cell(mx, my))

            # ── Terrain editor gets first pick when open ──────────────────
            if self.terrain_editor.active:
                self.terrain_editor.handle(event)
                # Handle close/save for terrain editor
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self._terrain_regions = self.terrain_editor.terrain_regions
                    self._save_terrain()
                    self._apply_terrain_to_battle_map()
                    self.terrain_editor.close()
                    # Recalculate reach and attack overlays if an agent is selected
                    if self.selected_idx >= 0:
                        self._update_reach()
                        self._update_attack_overlay()
                continue

            # ── Lighting editor gets priority when open ──────────────────
            if self.lighting_editor.active:
                self.lighting_editor.handle(event)
                continue

            # ── Cast-time element picker is a top modal: consume events while open ──
            if self._element_dialog.visible:
                self._element_dialog.handle(event)
                continue

            # ── Grid-span picker is a top modal: consume events while open ─────────
            if self._grid_span_dialog.visible:
                self._grid_span_dialog.handle(event)
                continue

            # ── Name prompt is a top modal: consume events while open ──────────────
            if self.name_prompt.visible:
                self.name_prompt.handle(event)
                continue

            # ── Team picker is a top modal: consume events while open ──────────────
            if self.team_dialog.visible:
                self.team_dialog.handle(event)
                continue

            # ── Terrain placement dialog gets priority when open ────────────
            if self.terrain_placement_dialog.active:
                self.terrain_placement_dialog.handle(event)
                continue

            # ── Modals get first pick when open ───────────────────────────
            if self.file_browser.active:
                self.file_browser.handle(event, self.screen)
                continue
            if self.stats_dialog.active:
                self.stats_dialog.handle(event, self.screen)
                continue
            # Selection dialogs get priority (handle before parent dialogs)
            if self.weapon_selection_dialog.visible:
                if self.weapon_selection_dialog.handle(event):
                    continue
            if self.armor_selection_dialog.visible:
                if self.armor_selection_dialog.handle(event):
                    continue
            if self.spell_selection_dialog.visible:
                if self.spell_selection_dialog.handle(event):
                    continue

            # Parent dialogs
            if self.weapon_dialog.active:
                self.weapon_dialog.handle(event, self.screen)
                continue
            if self.armor_dialog.active:
                self.armor_dialog.handle(event, self.screen)
                continue
            if self.weapons_dialog.active:
                self.weapons_dialog.handle(event, self.screen)
                continue
            if self.spell_dialog.active:
                self.spell_dialog.handle(event, self.screen)
                continue
            if self.conditions_dialog.active:
                was_active = self.conditions_dialog.active
                self.conditions_dialog.handle(event)
                # Check if dialog just closed, apply modified conditions
                if was_active and not self.conditions_dialog.active and self.conditions_dialog.agent_idx is not None:
                    agent_idx = self.conditions_dialog.agent_idx
                    if 0 <= agent_idx < len(self.bm.placed_agents):
                        modified_cond = self.conditions_dialog.conditions
                        print(f"[main.py] Dialog closed for agent {agent_idx}, applying conditions: exhaustion_level={modified_cond.exhaustion_level}")
                        self.combat.set_agent_conditions(self.bm, agent_idx, modified_cond)
                        print(f"[main.py] Conditions applied, verifying: {self.combat.get_agent_conditions(self.bm, agent_idx).exhaustion_level}")
                    self.conditions_dialog.agent_idx = None  # Clear after applying
                    self.conditions_dialog.conditions = {}  # Clear conditions
                continue
            # ── PC name input (editing name after selecting class) ─────────
            if self._pc_name_input:
                self._pc_name_input.handle(event)
                if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                    # User confirmed the name; start placement mode
                    if self.placement_config:
                        self.placement_config.name = self._pc_name_input.text.strip() or self.placement_config.name
                    self._pc_name_input = None
                    self.placement_mode_active = True
                    continue
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    # Cancel PC placement
                    self._pc_name_input = None
                    self.placement_config = None
                    continue
                else:
                    continue
            # ── Placement mode (floating agent) ───────────────────────────────
            if self.placement_mode_active:
                if event.type == pygame.MOUSEMOTION:
                    mx, my = event.pos
                    # Check if mouse is on the map
                    if self.map_rect.collidepoint(mx, my):
                        self.placement_cell = self._screen_to_cell(mx, my)
                        if self.placement_cell:
                            self.placement_valid = self._can_place(self.placement_cell, self.placement_config.size)
                        else:
                            self.placement_valid = False
                    else:
                        self.placement_cell = None
                        self.placement_valid = False
                    continue
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    # Place the agent immediately on the map
                    if self.placement_cell and self.placement_valid:
                        cfg = self.placement_config
                        cfg.start_col = self.placement_cell.col
                        cfg.start_row = self.placement_cell.row
                        # Append non-destructively, the same primitive paste/summon
                        # use. Using spawn_agent instead of add_agent_config +
                        # apply_agent_configs avoids rebuilding the whole roster from
                        # the config list. That rebuild (applyAgentConfigs clears
                        # placedAgents_) silently dropped every agent created via
                        # spawn_agent — pasted clones and summons never enter the
                        # config list — so placing one new mob wiped them, and the
                        # next save then persisted only the rebuilt roster.
                        idx = self.bm.spawn_agent(cfg)
                        if idx < 0:
                            self._flash_status("Could not place agent here")
                            continue
                        # Apply mob stats and auto-weapons to the newly placed agent
                        if self.selected_mob_stats:
                            d_d_stats = self._mob_stats_to_d_d_stats(self.selected_mob_stats)
                            self.combat.set_agent_stats(self.bm, idx, d_d_stats)
                            # For auto-weapons, we need to update the weapons array
                            current_weapons = list(self.combat.get_agent_weapons(self.bm, idx))
                            # Default slots are "Unarmed" (the empty sentinel), so
                            # check for a *real* weapon before auto-filling.
                            has_weapons = self._has_real_weapons(current_weapons)
                            if not has_weapons:
                                # Fill empty weapon slots with auto-weapons
                                auto_weapons = self._auto_weapons_from_mob_stats(self.selected_mob_stats)
                                for i, auto_w in enumerate(auto_weapons):
                                    if i < 3:
                                        current_weapons[i] = auto_w
                                self.combat.set_agent_weapons(self.bm, idx, current_weapons)
                            # Auto-load innate spells (no-op for non-casters).
                            self._load_npc_spells_from_record(idx, self.selected_mob_stats)
                        elif self._pending_pc_class:
                            # Apply PC stats (class/level and spell slots already set)
                            self.combat.set_agent_stats(self.bm, idx, self._pending_pc_stats)
                            self._pending_pc_class = None
                            self._pending_pc_stats = None
                        self.sprites.clear()
                        self.placement_mode_active = False
                        self.placement_config = None
                        self.placement_cell = None
                        self._pc_name_input = None
                    continue
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    # Cancel placement
                    self.placement_mode_active = False
                    self.placement_config = None
                    self.placement_cell = None
                    self._pc_name_input = None
                    continue

            # Context menu sits above normal map events but below modals.
            if self.context_menu.visible:
                if self.context_menu.handle(event):
                    continue

            # ── Keyboard shortcuts ────────────────────────────────────────
            if event.type == pygame.KEYDOWN:
                # Esc finishes Evoker safe-target editing.
                if event.key == pygame.K_ESCAPE and self.safe_target_edit_idx >= 0:
                    self._combat_log_add(
                        f"Done editing safe targets for "
                        f"{self.bm.placed_agents[self.safe_target_edit_idx].name}.")
                    self.safe_target_edit_idx = -1
                    continue
                # Esc cancels a pending summon placement (no slot/action spent yet).
                if event.key == pygame.K_ESCAPE and self.pending_summon_slot:
                    self.pending_summon_slot       = ""
                    self.pending_summon_idx        = 0
                    self.pending_summon_slot_level = 0
                    self.pending_summon_monster    = ""
                    self.summon_hover_cell         = None
                    self._combat_log_add("Summon cancelled.")
                    continue
                # Enter casts Chromatic Orb with the leap chain collected so far (may be empty —
                # the orb still leaps to the nearest foe on a match). Esc cancels the whole cast.
                if self.pending_chromatic_active and self.pending_spell_slot \
                        and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._finalize_chromatic_cast()
                    continue
                if self.pending_chromatic_active and self.pending_spell_slot \
                        and event.key == pygame.K_ESCAPE:
                    self._cancel_chromatic_chain()
                    continue
                # Esc cancels a pending spell cast. For an anchored wall, the first
                # Esc drops back to anchor selection; a second Esc cancels the cast.
                if event.key == pygame.K_ESCAPE and self.pending_spell_slot:
                    if self._pending_spell_is_wall() and self.spell_anchor_cell is not None:
                        self.spell_anchor_cell = None
                        self._combat_log_add("Wall anchor cleared — click a new start point.")
                    else:
                        self.pending_spell_slot   = ""
                        self.pending_spell_is_aoe = False
                        self.spell_anchor_cell    = None
                        self.spell_hover_cell     = None
                        self._combat_log_add("Spell cast cancelled.")
                    continue
                # Delete / Backspace removes the selected placed agent,
                # but ONLY when not in combat.
                if event.key in (pygame.K_DELETE, pygame.K_BACKSPACE) \
                        and not self.combat_active:
                    if self.selected_idx >= 0:
                        idx = self.selected_idx
                        self.bm.remove_agent(idx)
                        # Weapon data lives in C++ and is removed with the agent.
                        self.selected_idx        = -1
                        self.drag_idx            = -1
                        self._reach_walk         = []
                        self._reach_fly          = []
                        self._reach_set          = set()
                        self._attack_cells_melee = []
                        self._attack_cells_rnorm = []
                        self._attack_cells_rlong = []

            if event.type == pygame.VIDEORESIZE:
                self._reposition_panel()

            # ── Map area: drag-and-drop ───────────────────────────────────
            on_map = not self._panel_rect().collidepoint(
                *getattr(event, 'pos', (-1, -1)))

            # Right-click on a placed agent → context menu (disabled during combat)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and on_map \
                    and not self.combat_active:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    hit = self._agent_at(cell)
                    if hit >= 0:
                        pt = self.bm.placed_agents[hit]
                        # Capture hit by value for the lambdas.
                        def _open_stats(h=hit):
                            pt2   = self.bm.placed_agents[h]
                            stats = self.combat.get_agent_stats(self.bm, h)
                            class_name = stats.character_class.name
                            char_level = stats.char_level
                            is_npc = stats.is_npc
                            npc_spell_groups = self._agent_meta.get(h, {}).get("npc_spell_groups", {})
                            armor = self.combat.get_agent_armor(self.bm, h)
                            # Get subclass name from stats based on class
                            subclass_name = "NONE"
                            if class_name == "Barbarian":
                                subclass_name = stats.barbarian_subclass.name
                            elif class_name == "Wizard":
                                subclass_name = stats.wizard_subclass.name
                            elif class_name == "Fighter":
                                subclass_name = stats.fighter_subclass.name
                            elif class_name == "Druid":
                                subclass_name = stats.druid_circle.name
                            elif class_name == "Monk":
                                subclass_name = stats.monk_subclass.name
                            elif class_name == "Paladin":
                                subclass_name = stats.paladin_oath.name
                            elif class_name == "Warlock":
                                subclass_name = stats.warlock_subclass.name
                            elif class_name == "Rogue":
                                subclass_name = stats.rogue_subclass.name
                            elif class_name == "Cleric":
                                subclass_name = stats.cleric_subclass.name
                            elif class_name == "Bard":
                                subclass_name = stats.bard_subclass.name
                            elif class_name == "Sorcerer":
                                subclass_name = stats.sorcerer_subclass.name
                            elif class_name == "Ranger":
                                subclass_name = stats.ranger_subclass.name
                            blessed_strike_name = stats.blessed_strike.name if class_name == "Cleric" else "NONE"
                            is_hunter = (class_name == "Ranger" and subclass_name == "Hunter")
                            hunter_prey_name = stats.hunter_prey.name if is_hunter else "NONE"
                            defensive_tactics_name = stats.defensive_tactics.name if is_hunter else "NONE"
                            self.stats_dialog.open(
                                self.screen, h, pt2.name, stats,
                                class_name, char_level,
                                self._on_stats_ok,
                                is_npc=is_npc,
                                npc_spell_groups=npc_spell_groups,
                                armor_list=armor,
                                subclass_name=subclass_name,
                                blessed_strike_name=blessed_strike_name,
                                hunter_prey_name=hunter_prey_name,
                                defensive_tactics_name=defensive_tactics_name)
                        def _open_weapons(h=hit):
                            pt2 = self.bm.placed_agents[h]
                            weapon_array = self.combat.get_agent_weapons(self.bm, h)
                            def _on_weapons_done():
                                # Collect weapons from dialog and save back to combat engine
                                cpp_weapons = []
                                for weapon_dict in self.weapons_dialog.current_weapons:
                                    if weapon_dict.get("name"):
                                        cpp_weapons.append(_dict_to_weapon(weapon_dict))
                                    else:
                                        cpp_weapons.append(rpg.Weapon())
                                self.combat.set_agent_weapons(self.bm, h, cpp_weapons)
                            self.weapons_dialog.open(self.screen, h, pt2.name, weapon_array,
                                                    self.weapon_selection_dialog, _on_weapons_done,
                                                    self.combat, self.bm)
                        def _open_spells(h=hit):
                            pt2 = self.bm.placed_agents[h]
                            spell_dicts = [self._spell_to_dict(h, j, s)
                                           for j, s in enumerate(self.combat.get_agent_spells(self.bm, h))]
                            def _open_spell_selector():
                                self.spell_selection_dialog.show(self.spell_dialog._on_spell_selected)
                            self.spell_dialog.open(
                                self.screen, h, pt2.name,
                                spell_dicts,
                                self._on_spell_done,
                                add_spell_callback=_open_spell_selector)
                        def _open_armor(h=hit):
                            pt2 = self.bm.placed_agents[h]
                            armor_array = self.combat.get_agent_armor(self.bm, h)
                            def _on_armor_done():
                                # Collect armor from dialog and save back to combat engine
                                cpp_armor = []
                                for armor_dict in self.armor_dialog.current_armor:
                                    if armor_dict.get("name"):
                                        cpp_armor.append(_dict_to_armor(armor_dict))
                                    else:
                                        cpp_armor.append(rpg.Armor())
                                self.combat.set_agent_armor(self.bm, h, cpp_armor)
                            self.armor_dialog.open(self.screen, h, pt2.name, armor_array,
                                                  self.armor_selection_dialog, _on_armor_done)
                        def _edit_safe_targets(h=hit):
                            self.safe_target_edit_idx = h
                            self._combat_log_add(
                                f"Editing safe targets for {self.bm.placed_agents[h].name}: "
                                f"click allies to toggle them safe from this Evoker's AoEs "
                                f"(Esc or click empty space to finish).")
                        def _edit_name(h=hit):
                            old = self.bm.placed_agents[h].name
                            def _commit(new_name, hh=h, prev=old):
                                self.bm.set_agent_name(hh, new_name)
                                self._combat_log_add(f"Renamed '{prev}' → '{new_name}'.")
                            self.name_prompt.show(old, _commit,
                                                  title=f"Rename '{old}'")
                        def _edit_sprite(h=hit):
                            def _commit(path, hh=h):
                                self.bm.set_agent_sprite(hh, path)
                                self._combat_log_add(
                                    f"{self.bm.placed_agents[hh].name}: sprite set to "
                                    f"{os.path.basename(path)}.")
                            start = self.sprites_dir if os.path.isdir(self.sprites_dir) else "."
                            self.file_browser.open(start, _commit)
                        _menu_opts = [("Edit Name…",   _edit_name),
                                      ("Edit Sprite…", _edit_sprite),
                                      ("Edit Stats",   _open_stats),
                                      ("Edit Weapons", _open_weapons),
                                      ("Edit Armor",   _open_armor),
                                      ("Edit Spells",  _open_spells),
                                      ("Set Teams…",   self._open_team_picker)]
                        # Evoker Wizards only: manage the set of creatures safe from their AoEs.
                        _hs = self.combat.get_agent_stats(self.bm, hit)
                        if (_hs.character_class == rpg.CharacterClass.Wizard and
                                _hs.wizard_subclass == rpg.WizardSubclass.Evoker):
                            _menu_opts.append(("Edit Safe Targets", _edit_safe_targets))
                        # Fiend Warlock L10+: choose the Fiendish Resilience damage resistance.
                        if (_hs.character_class == rpg.CharacterClass.Warlock and
                                _hs.warlock_subclass == rpg.WarlockSubclass.Fiend and
                                _hs.char_level >= 10):
                            def _choose_fiendish_resilience(h=hit, pos=event.pos):
                                # Force (index 3) is excluded by the feature.
                                _types = [("Acid", 0), ("Cold", 1), ("Fire", 2), ("Lightning", 4),
                                          ("Necrotic", 5), ("Poison", 6), ("Psychic", 7),
                                          ("Radiant", 8), ("Thunder", 9)]
                                _opts = [(nm, (lambda hh=h, ii=ix: self._set_fiendish_resilience(hh, ii)))
                                         for nm, ix in _types]
                                self.context_menu.show(pos, _opts, self.screen.get_size())
                            _menu_opts.append(("Fiendish Resilience", _choose_fiendish_resilience))
                        self.context_menu.show(event.pos, _menu_opts, self.screen.get_size())

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and on_map:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    hit = self._agent_at(cell)
                    if self.safe_target_edit_idx >= 0 and not self.combat_active:
                        # Evoker safe-target editing: clicking an ally toggles it; empty/self finishes.
                        self._toggle_safe_target(hit)
                    elif self.combat_active:
                        # Arcane Charge (EK L15): teleport up to 30 ft after Action Surge.
                        if self.arcane_charge_pending:
                            self._resolve_arcane_charge(cell)
                        # Pending attack: resolve against the clicked agent.
                        elif self.pending_cleave is not None and hit >= 0:
                            self._resolve_cleave(hit)
                        elif self.pending_sweep is not None and hit >= 0:
                            self._resolve_sweep(hit)
                        elif self.pending_rally is not None and hit >= 0:
                            self._resolve_rally(hit)
                        elif self.pending_feint is not None and hit >= 0:
                            self._resolve_feint(hit)
                        elif self.pending_attack_slot and hit >= 0:
                            self._confirm_friendly_harm(hit, lambda h=hit: self._resolve_combat_attack(h))
                        elif self.pending_summon_slot:
                            self._resolve_summon(cell)
                        elif self.pending_chromatic_active and self.pending_spell_slot:
                            # Collecting Chromatic Orb's leap chain: each click adds a hop.
                            self._chromatic_add_leap(hit)
                        elif self.pending_spell_slot:
                            if self.pending_spell_is_aoe:
                                if self._pending_spell_is_wall():
                                    if self.spell_anchor_cell is None:
                                        # First click: anchor the wall (must be in range).
                                        if self._wall_anchor_in_range(cell):
                                            self.spell_anchor_cell = cell
                                            self._combat_log_add("Wall anchored — click to set its direction and length.")
                                        else:
                                            self._combat_log_add("Out of range — pick a closer start point.")
                                    else:
                                        # Second click: commit the wall toward this cell.
                                        self._resolve_spell_cast_aoe(cell)
                                else:
                                    self._resolve_spell_cast_aoe(cell)
                            elif hit >= 0:
                                # Check line of sight for single-target spells
                                caster_idx = self._current_agent_idx()
                                if caster_idx >= 0 and caster_idx < len(self.bm.placed_agents):
                                    caster = self.bm.placed_agents[caster_idx]
                                    target = self.bm.placed_agents[hit]
                                    if not self.bm.has_line_of_sight(caster.origin, caster.size, target.origin, target.size):
                                        self._combat_log_add("No line of sight to target!")
                                    elif not self.combat.can_perceive_target(self.bm, caster_idx, hit):
                                        self._combat_log_add("Cannot perceive target (invisible)!")
                                    elif self._is_chromatic_pending():
                                        # Chromatic Orb: the primary target opens leap-chain selection
                                        # instead of casting immediately (confirm friendly harm first).
                                        self._confirm_friendly_harm(hit, lambda h=hit: self._enter_chromatic_chain(h))
                                    elif self._pending_spell_is_harm():
                                        # Faction rule 4: confirm before a harmful spell on a teammate.
                                        self._confirm_friendly_harm(hit, lambda h=hit: self._resolve_spell_cast(h))
                                    else:
                                        self._resolve_spell_cast(hit)
                                else:
                                    self._resolve_spell_cast(hit)
                        elif self.pending_shove_slot and hit >= 0:
                            self._resolve_shove(hit)
                        elif self.pending_grapple_slot and hit >= 0:
                            self._resolve_grapple(hit)
                        elif self.pending_unarmed_type and hit >= 0:
                            self._resolve_unarmed_option(hit)
                        elif self.pending_heal_light and hit >= 0:
                            self._resolve_healing_light(hit)
                        elif self.pending_lay_on_hands and hit >= 0:
                            self._resolve_lay_on_hands(hit)
                        elif self.pending_grant_inspiration and hit >= 0:
                            self._resolve_grant_inspiration(hit)
                        elif self.pending_telekinetic and hit >= 0:
                            self._resolve_telekinetic(hit)
                        elif self.pending_flurry_target and hit >= 0:
                            self._resolve_flurry_target(hit)
                        elif self.pending_vitality_target and hit >= 0:
                            self._resolve_vitality_target(hit)
                        else:
                            # Only allow dragging the current combatant.
                            cur = self._current_agent_idx()
                            if hit == cur and hit >= 0:
                                pt = self.bm.placed_agents[hit]
                                self.drag_idx    = hit
                                self.drag_origin = rpg.Cell(pt.origin.col, pt.origin.row)
                                self.drag_offset = (cell.col - pt.origin.col,
                                                    cell.row - pt.origin.row)
                                self.drag_cell   = rpg.Cell(pt.origin.col, pt.origin.row)
                                self.drag_valid  = True
                                # Keep selected_idx on the current combatant.
                    else:
                        # Normal mode: drag any agent or deselect.
                        # But disable dragging if jump overlay is active (use jump instead)
                        if hit >= 0 and not self.jump_overlay_active:
                            pt = self.bm.placed_agents[hit]
                            self.drag_idx    = hit
                            self.drag_origin = rpg.Cell(pt.origin.col, pt.origin.row)
                            self.drag_offset = (cell.col - pt.origin.col,
                                                cell.row - pt.origin.row)
                            self.drag_cell   = rpg.Cell(pt.origin.col, pt.origin.row)
                            self.drag_valid  = True
                            self.selected_idx = hit
                            self._update_reach()
                            self._update_attack_overlay()
                        else:
                            self.selected_idx        = -1
                            self._reach_walk         = []
                            self._reach_fly          = []
                            self._reach_set          = set()
                            self._attack_cells_melee = []
                            self._attack_cells_rnorm = []
                            self._attack_cells_rlong = []

            if event.type == pygame.MOUSEMOTION and self.pending_spell_is_aoe:
                if on_map:
                    self.spell_hover_cell = self._screen_to_cell(*event.pos)
                else:
                    self.spell_hover_cell = None

            if event.type == pygame.MOUSEMOTION and self.pending_summon_slot:
                self.summon_hover_cell = self._screen_to_cell(*event.pos) if on_map else None

            if event.type == pygame.MOUSEMOTION and self.drag_idx >= 0:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    pt   = self.bm.placed_agents[self.drag_idx]
                    tcol = cell.col - self.drag_offset[0]
                    trow = cell.row - self.drag_offset[1]
                    self.drag_cell  = rpg.Cell(tcol, trow)
                    self.drag_valid = self._can_place(
                        self.drag_cell, pt.size, exclude_idx=self.drag_idx)
                    # The movement-range clamp applies only in combat. Before combat the
                    # agent can be repositioned anywhere it legally fits (DM free placement);
                    # placement validity (bounds + no overlap) was checked just above.
                    if self.drag_valid and self.combat_active:
                        if self._reach_set:
                            self.drag_valid = (
                                self.drag_cell.col, self.drag_cell.row
                            ) in self._reach_set
                        else:
                            self.drag_valid = False   # movement exhausted

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if self.drag_idx >= 0:
                    if self.drag_valid and self.drag_cell is not None and not self.combat_active:
                        # Free pre-combat repositioning: placement validity was already
                        # checked (_can_place), so bypass the movement rules (speed / range /
                        # pathing) entirely and set the agent's position directly.
                        if self.bm.set_agent_position(self.drag_idx, self.drag_cell):
                            self.selected_idx = self.drag_idx
                        self._update_reach()
                        self._update_attack_overlay()
                    elif self.drag_valid and self.drag_cell is not None:
                        # Calculate Manhattan distance moved (for running jump qualification)
                        ag_old = self.bm.placed_agents[self.drag_idx]
                        dist_moved = abs(self.drag_cell.col - ag_old.origin.col) + abs(self.drag_cell.row - ag_old.origin.row)
                        dist_moved *= 5  # Each cell = 5 feet

                        # Compute Chebyshev distance (D&D 5e diagonal = 5 ft).
                        print(f"[Movement] Attempting to move agent {self.drag_idx} to ({self.drag_cell.col},{self.drag_cell.row}) using {self.move_type}")
                        # Debug: check terrain types along the path
                        print(f"[Movement] Terrain at dest: {self.bm.get_terrain_type(self.drag_cell)}")

                        # Check if agent can move at all (Speed = 0 check)
                        agents = self.bm.placed_agents
                        moving_agent = agents[self.drag_idx]
                        can_move = self.combat.can_agent_move(self.bm, self.drag_idx)

                        if not can_move:
                            # Speed = 0, no movement possible, no OA
                            move_success = False
                            print(f"[Movement] Move result: {move_success}")
                            self._combat_log_add(f"{moving_agent.name}: movement blocked — Speed = 0")
                            self.drag_idx = -1
                            self.drag_cell = None
                            self.drag_valid = False
                            self._update_reach()
                            self._update_attack_overlay()
                        else:
                            # In combat, the C++ engine owns Opportunity-Attack detection AND
                            # resolution via the flow-checkpoint API (begin_move -> pending_decision
                            # -> submit_decision). It does per-creature /
                            # per-step provoke and commits the move itself. Out of combat, just move.
                            self._reaction_mover_idx  = self.drag_idx
                            self._reaction_dist_moved = dist_moved
                            self._reaction_finish     = lambda: self._after_move_committed(self._reaction_mover_idx)
                            if self.combat_active:
                                status = self.combat.begin_move(self.bm, self.drag_idx, self.drag_cell, self.move_type)
                                self._flush_combat_log()
                                if status == rpg.FlowStatus.AwaitingDecision:
                                    # Engine parked at an OA checkpoint — render the menu; the click
                                    # routes back through submit_decision, which resumes the move.
                                    self._show_pending_reaction_menu()
                                else:
                                    self._after_move_committed(self.drag_idx)
                            else:
                                move_success = self.combat.move_agent(self.bm, self.drag_idx, self.drag_cell, self.move_type)
                                print(f"[Movement] Move result: {move_success}")
                                self._flush_combat_log()
                                if move_success:
                                    self._after_move_committed(self.drag_idx)
                                else:
                                    print(f"[Movement] Move failed - likely blocked by terrain")
                                    self.selected_idx = self.drag_idx
                                    self._update_reach()
                                    self._update_attack_overlay()
                    # else: agent stays at original position (C++ not updated)
                    self.drag_idx = -1
                    self.drag_cell = None

            # ── Handle jump clicks ────────────────────────────────────────────
            if self.jump_overlay_active and event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                cell = self._screen_to_cell(*event.pos) if on_map else None
                # on_map only bounds the map image; _screen_to_cell still returns None for a
                # click outside the detected grid, so guard against that before dereferencing.
                if cell is not None:
                    # Check if clicked cell is in jump range (compare by coordinates)
                    is_jump_cell = any(c.col == cell.col and c.row == cell.row for c in self.jump_reachable_cells)
                    if is_jump_cell:
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._execute_jump(idx, cell)

            # ── Mob selection dialog ──────────────────────────────────────
            if not self.combat_active:
                if self.mob_dialog.handle(event):
                    pass  # Event was consumed by dialog

                # ── Panel widgets ─────────────────────────────────────────────
                # Select Mob button
                if self.btn_select_mob.clicked(event):
                    self.mob_dialog.show(lambda mob: self._on_mob_selected(mob))

                # Select PC
                if self.btn_select_pc.clicked(event):
                    pc_classes = ["Barbarian", "Bard", "Cleric", "Druid", "Fighter", "Monk", "Paladin", "Ranger", "Rogue", "Sorcerer", "Warlock", "Wizard"]
                    options = [(cls, lambda c=cls: self._on_pc_class_selected(c)) for cls in pc_classes]
                    px_popup = self._panel_x() + self._PANEL_PAD
                    self.context_menu.show((px_popup, 100), options, self.screen.get_size())

                # Clear All
                if self.btn_clear.clicked(event):
                    self.bm.clear_agents()
                    self.bm.clear_terrain_effects()
                    self.bm.clear_items()
                    self.selected_idx        = -1
                    self.drag_idx            = -1
                    self._attack_cells_melee = []
                    self._attack_cells_rnorm = []
                    self._attack_cells_rlong = []

                # Save — open browser in save mode
                if self.btn_save.clicked(event):
                    start = os.path.dirname(self._save_path) or self._map_dir
                    self.file_browser.open(
                        start, self._on_save_path_chosen,
                        save_mode=True,
                        extensions=JSON_EXTS,
                        default_filename=os.path.basename(self._save_path),
                        name_pattern="_agents.json"
                    )

                # Load — open browser in load mode. No name_pattern: show ALL .json so
                # encounters saved with custom names (not just *_agents.json) are visible.
                if self.btn_load.clicked(event):
                    start = os.path.dirname(self._save_path) or self._map_dir
                    self.file_browser.open(
                        start, self._on_load_path_chosen,
                        save_mode=False,
                        extensions=JSON_EXTS,
                    )

                # Import a D&D Beyond character into the current encounter
                if self.btn_import_ddb.clicked(event):
                    self._import_ddb_character()

                # Long Rest — reset all spell slots
                if self.btn_long_rest.clicked(event):
                    self._on_long_rest()

                # Short Rest — restore short-rest resources (Warlock pact slots, Monk Focus Points, …)
                if self.btn_short_rest.clicked(event):
                    self._on_short_rest()

                # Remove pending agent by clicking ✕
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    list_y = self.btn_clear.rect.bottom + 20 + 18
                    px_rm = self._panel_x()
                    for i in range(len(self.pending_configs)):
                        rx = px_rm + PANEL_W - 22
                        rb = pygame.Rect(rx, list_y + i*18 - 1, 16, 16)
                        if rb.collidepoint(event.pos):
                            self.pending_configs.pop(i)
                            break

                # Begin Combat
                if self.btn_begin_combat.clicked(event):
                    self._start_combat()

                # Edit Terrain
                if self.btn_edit_terrain.clicked(event):
                    self.terrain_editor.open(self.map_surf, self._terrain_regions, self.bm)

                # Show/Hide Terrain (same toggle as in combat)
                if self.btn_show_terrain.clicked(event):
                    self.show_terrain = not self.show_terrain

                # Save Terrain — open browser in save mode
                if self.btn_save_terrain.clicked(event):
                    start = os.path.dirname(self._terrain_path) or self._map_dir
                    self.file_browser.open(
                        start, self._on_save_terrain_chosen,
                        save_mode=True,
                        extensions=JSON_EXTS,
                        default_filename=os.path.basename(self._terrain_path),
                        name_pattern="_terrain.json"
                    )

                # Load Terrain — open browser in load mode. No name_pattern: show ALL
                # .json so terrain saved with custom names (not just *_terrain.json) shows.
                if self.btn_load_terrain.clicked(event):
                    start = os.path.dirname(self._terrain_path) or self._map_dir
                    self.file_browser.open(
                        start, self._on_load_terrain_chosen,
                        save_mode=False,
                        extensions=JSON_EXTS,
                    )

                # Edit Lighting
                if self.btn_edit_lighting.clicked(event):
                    light_sources = []
                    if os.path.exists(self._lighting_path):
                        try:
                            with open(self._lighting_path, 'r') as f:
                                data = json.load(f)
                                light_sources = data.get("light_sources", [])
                        except:
                            light_sources = []
                    self.lighting_editor.open(self.map_surf, self.bm, self, light_sources)

                # Toggle Lighting Overlay
                if self.btn_toggle_lighting.clicked(event):
                    self.show_lighting_overlay = not self.show_lighting_overlay
                    self.btn_toggle_lighting.text = "Lighting: ON" if self.show_lighting_overlay else "Lighting: OFF"

                # Toggle Wall Auto-Detection
                if self.btn_toggle_walls.clicked(event):
                    self._toggle_walls()

                # Set Grid (sample a tile to define a uniform grid)
                if self.btn_set_grid.clicked(event):
                    self._toggle_grid_sample_mode()

                # Quit
                if self.btn_quit.clicked(event):
                    return False

            else:
                # ── Initiative list click detection ────────────────────────────
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for item_rect, agent_idx in self.initiative_item_rects:
                        if item_rect.collidepoint(event.pos):
                            # Show conditions dialog for clicked agent
                            if 0 <= agent_idx < len(self.bm.placed_agents):
                                agent = self.bm.placed_agents[agent_idx]
                                cond = self.combat.get_agent_conditions(self.bm, agent_idx)
                                self.conditions_dialog.open(agent.name, cond, agent_idx)
                            break

                # ── Combat panel buttons ───────────────────────────────────
                _ev_idx = self._current_agent_idx()
                _has_wpn = (0 <= _ev_idx < len(self.bm.placed_agents) and
                            len(self.combat.get_agent_weapons(self.bm, _ev_idx)) > 0)
                _has_offhand = self._offhand_bonus_available(_ev_idx)
                # The Attack button also continues an in-progress Extra Attack sequence: mid-sequence
                # the Action is already marked used, but the standing "⚔ Attack (N)" button must
                # still resume the remaining attacks. A FRESH Attack needs an unused Action.
                _mid_seq_atk = (self.attacks_remaining > 0 and self._attack_sequence_slot == "action")
                if _has_wpn and (not self.action_used or _mid_seq_atk) and \
                        self.btn_cbt_atk_action.clicked(event):
                    self._start_attack("action")
                # Nick: relocate the off-hand attack into the Attack action (frees the bonus action).
                # Ungated by action_used — the button is only drawn after the Attack action is taken.
                _nick_idx = self._nick_offhand_idx(_ev_idx)
                if _nick_idx >= 0 and self.btn_cbt_nick.clicked(event):
                    self._start_extra_attack(weapon_idx=_nick_idx, offhand=True, slot="action",
                                             label="Nick: off-hand attack (part of Attack action)")
                if not self.action_used:
                    if self.btn_cbt_unarmed.clicked(event):
                        self._show_unarmed_menu(pygame.mouse.get_pos())
                    if self.btn_cbt_pass_action.clicked(event):
                        self.action_used = True
                    if self.btn_cbt_dash.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            agent = self.bm.placed_agents[idx]
                            self.bm.apply_dash(idx)
                            self.move_remaining_walk   = agent.walk_remaining
                            self.move_remaining_fly    = agent.fly_remaining
                            self.move_remaining_swim   = agent.swim_remaining
                            self.move_remaining_burrow = agent.burrow_remaining
                            self._combat_log_add(f"{agent.name}: Dashing (+{self.combat.get_agent_stats(self.bm, idx).speed_walk}ft)")
                            self._update_reach()
                        self.action_used = True
                    if self.btn_cbt_dodge.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self.bm.placed_agents[idx].dodge()
                            self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Dodging")
                        self.action_used = True
                    if self.btn_cbt_disengage.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self.bm.placed_agents[idx].disengage()
                            self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Disengaging")
                        self.action_used = True
                    if self.btn_cbt_hide.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            in_combat = len(self.initiative_order) > 0
                            result = self.combat.check_hide(self.bm, idx, in_combat)
                            if result.hidden:
                                self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Hide (stealth {result.stealth_total})")
                            else:
                                self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Hide failed - {result.log_message}")
                        self.action_used = True
                    if self.btn_cbt_prone.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self.combat.apply_prone(self.bm, idx)
                            self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Going prone")
                            self._update_reach()
                            self._update_attack_overlay()
                        self.action_used = True
                    if self.btn_cbt_spell_action.clicked(event):
                        self._start_cast_spell("action")
                # Long Jump costs a Bonus Action (and movement) — available regardless of the
                # Action, but only while the bonus action is unspent.
                if not self.bonus_used and self.btn_cbt_long_jump.clicked(event):
                    if not self.pending_spell_slot:  # Don't allow jump while casting spell
                        self._toggle_jump_overlay()
                # Stand up doesn't use an action, so it's available regardless of action_used
                if self.btn_cbt_standup.clicked(event):
                    idx = self._current_agent_idx()
                    if 0 <= idx < len(self.bm.placed_agents):
                        self.combat.standup(self.bm, idx)
                        agent = self.bm.placed_agents[idx]
                        self.move_remaining_walk   = agent.walk_remaining
                        self.move_remaining_fly    = agent.fly_remaining
                        self.move_remaining_swim   = agent.swim_remaining
                        self.move_remaining_burrow = agent.burrow_remaining
                        self._combat_log_add(f"{agent.name}: Standing up")
                        self._update_reach()
                        self._update_attack_overlay()
                if self.btn_cbt_use_portent.clicked(event):
                    self._show_portent_dice_menu()
                if not self.bonus_used:
                    if _has_offhand and self.btn_cbt_atk_bonus.clicked(event):
                        self._start_attack("bonus")
                    if self.btn_cbt_spell_bonus.clicked(event):
                        self._start_cast_spell("bonus")
                    if self.btn_cbt_shove_push.clicked(event):
                        self._start_shove("push")
                    if self.btn_cbt_shove_prone.clicked(event):
                        self._start_shove("prone")
                    if self.btn_cbt_grapple.clicked(event):
                        self._start_grapple()
                    if self.btn_cbt_grapple_esc.clicked(event):
                        self._execute_grapple_escape()
                    if self.btn_cbt_telekinetic.clicked(event):
                        self._start_telekinetic_shove()
                    if self.btn_cbt_hide_bonus.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            in_combat = len(self.initiative_order) > 0
                            result = self.combat.check_hide(self.bm, idx, in_combat)
                            if result.hidden:
                                self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Hide (Cunning Action, stealth {result.stealth_total})")
                            else:
                                self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Hide failed - {result.log_message}")
                        self.bonus_used = True
                    if self.btn_cbt_dash_bonus.clicked(event) and not self.context_menu.visible:
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            agent = self.bm.placed_agents[idx]
                            self.bm.apply_dash(idx)
                            self.move_remaining_walk   = agent.walk_remaining
                            self.move_remaining_fly    = agent.fly_remaining
                            self.move_remaining_swim   = agent.swim_remaining
                            self.move_remaining_burrow = agent.burrow_remaining
                            self._combat_log_add(f"{agent.name}: Dashing (Cunning Action, +{self.combat.get_agent_stats(self.bm, idx).speed_walk}ft)")
                            self._update_reach()
                        self.bonus_used = True
                    if self.btn_cbt_disengage_bonus.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self.bm.placed_agents[idx].disengage()
                            self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Disengaging (Cunning Action)")
                        self.bonus_used = True
                    if self.btn_cbt_patient_defense.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            stats = self.combat.get_agent_stats(self.bm, idx)
                            fp = stats.get_resource("Focus Points")
                            if fp and fp.current > 0:
                                self.combat.spend_resource(self.bm, idx, "Focus Points")
                                self.bm.placed_agents[idx].dodge()
                                self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Patient Defense (dodging)")
                            self.bonus_used = True
                    if self.btn_cbt_step_of_wind.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            stats = self.combat.get_agent_stats(self.bm, idx)
                            fp = stats.get_resource("Focus Points")
                            if fp and fp.current > 0:
                                self.combat.spend_resource(self.bm, idx, "Focus Points")
                                agent = self.bm.placed_agents[idx]
                                agent.disengage()
                                self.bm.apply_dash(idx)
                                self.move_remaining_walk   = agent.walk_remaining
                                self.move_remaining_fly    = agent.fly_remaining
                                self.move_remaining_swim   = agent.swim_remaining
                                self.move_remaining_burrow = agent.burrow_remaining
                                self._combat_log_add(f"{agent.name}: Step of the Wind (disengaging and dashing)")
                                self._update_reach()
                            self.bonus_used = True
                    if self.btn_cbt_rage.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self.combat.activate_rage(self.bm, idx)
                            agent = self.bm.placed_agents[idx]
                            self._combat_log_add(f"{agent.name}: Enters a rage!")
                        self.bonus_used = True
                    if self.btn_cbt_reckless.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            cond = self.combat.get_agent_conditions(self.bm, idx)
                            cond.reckless_attack = True
                            self.combat.set_agent_conditions(self.bm, idx, cond)
                            self.combat.log_event("reckless", idx=idx)  # record for checked replay
                            agent = self.bm.placed_agents[idx]
                            self._combat_log_add(f"{agent.name}: Activates Reckless Attack (enemies gain advantage on attacks vs you)")
                        self.action_used = True
                    if self.btn_cbt_magical_cunning.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            if self.combat.use_magical_cunning(self.bm, idx):
                                self._flush_combat_log()
                            else:
                                self._combat_log_add("Magical Cunning unavailable.")
                    if self.btn_cbt_healing_light.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self.pending_heal_light = True
                            self._combat_log_add("Healing Light — click an ally (or self) to heal.")
                    if self.btn_cbt_turn_undead.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            res = self.combat.use_turn_undead(self.bm, idx)
                            self._flush_combat_log()
                            if res.valid:
                                self._combat_log_add(
                                    f"Turn Undead (DC {res.save_dc}): {len(list(res.turned))} turned"
                                    + (f", {res.sear_damage} Radiant each" if res.sear_damage else ""))
                                self.action_used = True
                            else:
                                self._combat_log_add("Turn Undead unavailable.")
                    if self.btn_cbt_radiance.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            spells = self.combat.get_agent_spells(self.bm, idx)
                            ridx = next((i for i, sp in enumerate(spells)
                                         if sp.name == "Radiance of the Dawn"), -1)
                            if ridx >= 0:
                                self.pending_spell_slot = "action"
                                self.pending_spell_idx = ridx
                                self.pending_spell_slot_level = 0
                                origin = self.bm.placed_agents[idx].origin
                                self._resolve_spell_cast_aoe(rpg.Cell(origin.col, origin.row))
                            else:
                                self._combat_log_add("Radiance of the Dawn is not prepared.")
                    if self.btn_cbt_steady_aim.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            cond = self.combat.get_agent_conditions(self.bm, idx)
                            cond.steady_aim = True
                            self.combat.set_agent_conditions(self.bm, idx, cond)
                            # Steady Aim sets your Speed to 0 for the rest of the turn.
                            self.move_remaining_walk = 0
                            self.move_remaining_fly = 0
                            self.move_remaining_swim = 0
                            self.move_remaining_burrow = 0
                            self._update_reach()
                            self.bonus_used = True
                            self._combat_log_add(
                                f"{self.bm.placed_agents[idx].name}: Steady Aim — advantage on next attack (Speed 0).")
                    if self.btn_cbt_war_priest.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._start_extra_attack(weapon_idx=0, offhand=False,
                                                     resource="War Priest", label="War Priest")
                    if self.btn_cbt_martial_arts.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._start_extra_attack(weapon_idx=0, offhand=False,
                                                     resource=None, label="Martial Arts")
                    if self.btn_cbt_flurry_of_blows.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            stats = self.combat.get_agent_stats(self.bm, idx)
                            fp = stats.get_resource("Focus Points")
                            if fp and fp.current > 0:
                                # Show Open Hand rider menu if Way of the Open Hand
                                if stats.monk_subclass == rpg.MonkSubclass.WarriorOfTheOpenHand:
                                    self._show_flurry_rider_menu(idx)
                                else:
                                    # No rider options, execute with no rider
                                    self._execute_flurry(idx, -1)
                    if self.btn_cbt_second_wind.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._use_second_wind(idx)
                    if self.btn_cbt_bm_maneuver.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._offer_bonus_maneuver(idx)
                    if self.btn_cbt_one_with_shadows.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            if self.combat.apply_one_with_shadows(self.bm, idx):
                                self._combat_log_add(f"{self.bm.placed_agents[idx].name}: One with Shadows — now invisible.")
                            else:
                                self._combat_log_add("One with Shadows requires standing in Dim Light or Darkness.")
                    if self.btn_cbt_action_surge.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._use_action_surge(idx)
                    if self.btn_cbt_lay_on_hands.clicked(event):
                        self.pending_lay_on_hands = True
                        self.hint = "Click target for Lay on Hands healing"
                    if self.btn_cbt_grant_inspiration.clicked(event):
                        self.pending_grant_inspiration = True
                        self.hint = "Click an ally to grant a Bardic Inspiration die"
                    if self.btn_cbt_use_inspiration.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._use_inspiration_die(idx)
                    if self.btn_cbt_sacred_weapon.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._use_sacred_weapon(idx)
                    if self.btn_cbt_corona.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._use_corona_of_light(idx)
                    if self.btn_cbt_telekinetic.clicked(event):
                        self.pending_telekinetic = True
                        self.hint = "Click a creature to move with Telekinetic Movement"
                    if self.btn_cbt_dread_ambusher.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            stats = self.combat.get_agent_stats(self.bm, idx)
                            da = stats.get_resource("Dread Ambusher")
                            cond = self.combat.get_agent_conditions(self.bm, idx)
                            if (da and da.current > 0 and not cond.dread_ambusher_used and
                                    not cond.dreadful_strike_armed):
                                if self.combat.spend_resource(self.bm, idx, "Dread Ambusher", 1):
                                    cond.dreadful_strike_armed = True
                                    cond.dread_ambusher_used = True
                                    self.combat.set_agent_conditions(self.bm, idx, cond)
                                    # Ambusher's Leap: +10 ft Speed this turn.
                                    self.move_remaining_walk += 10
                                    self._update_reach()
                                    dn = stats.dreadful_strike_dice
                                    dz = stats.dreadful_strike_die_size
                                    self._combat_log_add(
                                        f"{self.bm.placed_agents[idx].name}: Dread Ambusher — "
                                        f"next weapon hit deals +{dn}d{dz} Psychic, +10 ft Speed.")
                    if self.btn_cbt_tireless.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._use_tireless(idx)
                    if self.btn_cbt_natures_veil.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._use_natures_veil(idx)
                    if self.btn_cbt_companion.clicked(event):
                        self._show_companion_menu()
                    if self.btn_cbt_pass_bonus.clicked(event):
                        self.bonus_used = True
                    if self.btn_cbt_charge_arcane_ward.clicked(event):
                        self._show_arcane_ward_menu()
                    if self.btn_cbt_wild_shape.clicked(event):
                        self._show_wild_shape_menu()
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for mv_mt, mv_rect in self._move_type_btns.items():
                        if mv_rect.collidepoint(event.pos):
                            self.move_type = mv_mt
                            self._update_reach()
                            break
                if self.btn_cbt_place_terrain.clicked(event):
                    self.terrain_placement_dialog.open(self.map_surf, self.bm, self)
                if self.btn_show_terrain.clicked(event):
                    self.show_terrain = not self.show_terrain
                if self.btn_show_spell_effects.clicked(event):
                    self.show_spell_effects = not self.show_spell_effects
                if self.btn_show_visible_targets.clicked(event):
                    self._show_visible_targets_popup()
                if self.btn_cbt_end_turn.clicked(event):
                    self._advance_turn()
                    self._flush_combat_log()
                if self.btn_cbt_end_combat.clicked(event):
                    self._end_combat()
                if self.btn_cbt_drop_concentration.clicked(event):
                    self._drop_concentration()
                if self.btn_cbt_drop_weapon_main.clicked(event):
                    self._drop_weapon(0)
                if self.btn_cbt_drop_weapon_off.clicked(event):
                    self._drop_weapon(1)
                if self.btn_cbt_drop_weapon_rng.clicked(event):
                    self._drop_weapon(2)
                # Item pickup: click a cell with items
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and on_map \
                        and not self.pending_attack_slot and not self.pending_spell_slot and not self.pending_shove_slot and not self.pending_grapple_slot:
                    items_at_cell = self.bm.get_items_at_cell(cell) if cell is not None else []
                    if items_at_cell:
                        cur_idx = self._current_agent_idx() if self.combat_active else self.selected_idx
                        if cur_idx >= 0:
                            agent = self.bm.placed_agents[cur_idx]
                            # Don't allow pickup if agent is dead
                            if agent.conditions.dead:
                                return True
                            # Chebyshev distance from agent footprint edge to clicked cell
                            dc = max(agent.origin.col - cell.col,
                                    cell.col - (agent.origin.col + agent.size - 1), 0)
                            dr = max(agent.origin.row - cell.row,
                                    cell.row - (agent.origin.row + agent.size - 1), 0)
                            if max(dc, dr) <= 1:
                                self._show_item_pickup_menu(cell, items_at_cell, cur_idx, event.pos)

        return True

    # ─────────────────────────────────────────────────────────────────────
    #  Main loop
    # ─────────────────────────────────────────────────────────────────────
    def run(self):
        running = True
        while running:
            running = self._handle_events()
            self.screen.fill(COL_BG)
            self._draw_map()
            self._draw_agents()
            self._draw_safe_target_highlights()
            self._draw_panel()
            self.terrain_editor.draw(self.screen)          # modal — always on top
            self.lighting_editor.draw(self.screen)         # modal — always on top
            self.terrain_placement_dialog.draw(self.screen)  # modal — always on top
            self.file_browser.draw(self.screen)     # modal — always on top
            self.stats_dialog.draw(self.screen)    # modal — always on top
            self.weapon_dialog.draw(self.screen)   # modal — always on top
            self.armor_dialog.draw(self.screen)    # modal — always on top
            self.weapons_dialog.draw(self.screen)  # modal — always on top
            self.spell_dialog.draw(self.screen)    # modal — always on top
            self.spell_selection_dialog.draw(self.screen)  # modal — always on top
            self.armor_selection_dialog.draw(self.screen)  # modal — always on top
            self.weapon_selection_dialog.draw(self.screen)  # modal — always on top
            self.mob_dialog.draw(self.screen)      # modal — always on top
            self.conditions_dialog.draw(self.screen)  # modal — always on top
            self.context_menu.draw(self.screen)    # popup — topmost
            self._element_dialog.draw(self.screen) # cast-time element picker — topmost modal
            self._grid_span_dialog.draw(self.screen) # grid-span picker — topmost modal
            self.team_dialog.draw(self.screen)     # team picker — topmost modal
            self.name_prompt.draw(self.screen)     # rename prompt — topmost modal
            pygame.display.flip()
            self.clock.tick(60)
        # Clean up temporary terrain effects before quitting
        self.bm.clear_terrain_effects()
        self._clear_temporary_terrain()
        self._save_terrain()
        pygame.quit()


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python main.py <map_image.png>")
    App(sys.argv[1]).run()
