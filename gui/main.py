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
import time
from collections import deque

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
from constants import _ROOM_FLOOD_CAP
from widgets import Button, TextInput, IntStepper, edit_line
from helpers import (
    _dnd_mod, _mod_str,
    _parse_physical_damage, _parse_magic_damage,
    _DEFAULT_WEAPON, _weapon_to_dict, _dict_to_weapon,
    _weapons_to_list, _weapons_from_list,
    _DEFAULT_ARMOR, _armor_to_dict, _dict_to_armor,
    _ABILITY_TO_INT, _INT_TO_ABILITY, _DEFAULT_SPELL,
    _spell_to_dict, _dict_to_spell,
    _item_to_dict, _dict_to_item,
    is_item_spell, sync_item_spells, item_spell_label, item_spells_summary,
    is_scroll, scroll_line, can_read_scroll,
    attuned_count, attunement_warning,
    _condition_to_dict, _dict_to_condition,
    can_place_agent, edge_key, edge_from_key, door_touch_cells, _weapon_slot_is_empty,
)
from dialogs import FileBrowser, StatsDialog, MobSelectionDialog, ContextMenu, SpellGridMenu, SpellSelectionDialog, ArmorSelectionDialog, WeaponSelectionDialog, ItemSelectionDialog, ArmorDialog, WeaponsDialog, ItemsDialog, GENERAL_FEAT_NAMES, EPIC_BOON_FEAT_NAMES, ElementPickerDialog, TeamPickerDialog, GridSpanDialog, NamePromptDialog, WallDetectionDialog, NpcAutomationDialog
from dialogs_conditions import ConditionsDialog
from menus import board, dm, features, panel, reactions, riders
from weapon_dialog import WeaponDialog
from spell_dialog import SpellDialog
from terrain_dialogs import (TemporaryTerrainPlacementDialog, TerrainEditorDialog, draw_door_glyph,
                             draw_chest_glyph,
                             draw_ladder_glyph, draw_stair_glyph, door_link_key,
                             border_door_target,
                             edge_door_rect)
from lighting_dialogs import LightingEditorDialog
from agent_loader import dict_to_stats, restore_class_resources, _dict_to_weapon, apply_damage_multipliers
from dungeon import Dungeon, MapPage, dungeon_path_for
import grid_rescale
from floor_overlay import FloorAlign, load_floor_ghosts
from xp import compute_encounter_xp, cr_to_xp, level_for_xp, xp_for_level
from tracker import Tracker
# S1: every save that a crash could tear goes through this (MULTIPLAYER_PLAN.md).
from atomic_io import atomic_write_json
from run_state import keep_current_design
from scene_store import CampaignStore, LegacyStore
import save_layout
import campaign_import
import autosave
import lair
import run_control
import sim_trace
import pending
import playback
import app_board_render
import app_dungeon_pages
import app_initiative
import app_attacks
import app_spells
from app_spells import CLERIC_DI_SPELL_NAMES
import app_summons
import app_dungeon_gen
from dungeon_wizard import DungeonWizard
from floor_checklist import FloorChecklist
import app_panel_render
import app_persist
import app_lighting
import app_char_setup
from app_summons import SUMMON_SPELL_TO_SPIRIT
import saves
import placed_items
import items_play
# Multiplayer (MULTIPLAYER_PLAN.md M0). The roster owns identity and the single
# authorization chokepoint; main.py only wires it to the save path and the DM's menu.
from net.roster import (SessionRoster, Role, DM_PRINCIPAL_ID, tokens_from_battle_map)
from net.mapimg import MapImageCache, FOG_OVERLAP
from net.commands import CommandQueue
from net.events import EventStream, outcome as net_outcome
from net.submit import SubmitLog
from net import sessionlog as net_sessionlog
from net import link as net_link
# `perform` (D-M5-1) asks `authorize()` for a verb, and reaches it qualified as
# `net_roster.Action` so that the unqualified name stays unused (see below).
from net import roster as net_roster
# D-M5-2: a player's own turn, as one prompt on the bus; see net/offer.py.
from net import offer as net_offer
from net import picks as net_picks
# S3 (M2): what the combat panel may offer, as data. `actions.Action` is the game
# option; `net.roster.Action` above is the authorization verb — unrelated, so only
# ActionMenu is imported here and neither `Action` is in this module's namespace.
from actions import (ActionMenu, ECONOMY_ATTACK, fey_rider_index, GROUP_SESSION,
                     METAMAGIC_OPTIONS, METAMAGIC_ID_BY_VALUE, METAMAGIC_VALUE_BY_ID)
# M1, seam S2: every choice is a Prompt on the bus, and ContextMenu is one renderer of
# it. The bus also fills the roster's prompt_lookup hook that M0 left empty (D-M0-3).
from prompts import (PromptBus, Option, ContextMenuRenderer, SpellGridRenderer,
                     ElementPickerRenderer, RemoteRenderer, SpellBrowserRenderer,
                     SPELL_BROWSER_RENDER, options_from_pairs)

# D-M5-7: the reaction deadline constants live in constants.py (A7).

# S3 (M2b): the §4 / §7 row tuples live with the draw code that reads them (A6).
# `vars(main)` is how test_action_menu / test_gui_headless_smoke find them.
from app_panel_render import (_ACT_ROW_ATTACK, _ACT_ROW_BITE, _ACT_ROW_MOVE, _ACT_ROW_SPELL,
                              _BON_ROW_SHOVE, _BON_ROW_CUNNING, _BON_RUN_ESCAPE,
                              _BON_RUN_UNBANDED, _BON_FEY_TRIO, _BON_RUN_BAND,
                              _BON_RUN_METAMAGIC, _BON_DRAW_RUNS)


# MetamagicOption int value → display name, for combat-log messages.
METAMAGIC_NAME_BY_VALUE = {int(v): n for v, n, sp, note in METAMAGIC_OPTIONS}


# Draconic Sorcerer L6 Elemental Affinity: legal dragon ancestry types (excludes Force/Necrotic/Radiant).
DRACONIC_AFFINITY_OPTIONS = [("Acid", 0), ("Cold", 1), ("Fire", 2), ("Lightning", 4), ("Poison", 6)]

class App:
    # ── Action economy: a thin view over the C++ engine ──────────────────────
    # `self.action_used` and `self.bonus_used` are NOT plain flags. Each reads/writes the
    # active combatant's own copy in the engine:
    #   · action_used → Agent::Conditions.action_used, cleared by beginTurn (Agent::turn()).
    #     The engine stores it and serializes it; it does not enforce it (APP_REFACTOR_PLAN A3b).
    #   · bonus_used  → the bonus-action budget, Agent::Stats.bonus_actions_remaining/max via
    #     has_bonus_action / spend_bonus_action / reset_bonus_actions. Assigning True spends
    #     one, False refills to max, so feats can grant extra bonus actions (max > 1).
    # Before combat / with no active combatant both fall back to a plain attribute so early
    # __init__ assignments are harmless.
    def _economy_idx(self) -> int:
        """Active combatant index for the action economy, or -1 if the engine
        isn't ready / no one is acting (pre-combat __init__, between combats)."""
        if getattr(self, "combat", None) is None or getattr(self, "bm", None) is None:
            return -1
        return self._current_agent_idx()

    @property
    def action_used(self) -> bool:
        idx = self._economy_idx()
        if idx < 0:
            return getattr(self, "_action_used_fallback", False)
        return self.combat.get_agent_conditions(self.bm, idx).action_used

    @action_used.setter
    def action_used(self, value: bool) -> None:
        idx = self._economy_idx()
        if idx < 0:
            self._action_used_fallback = bool(value)
            return
        cond = self.combat.get_agent_conditions(self.bm, idx)
        cond.action_used = bool(value)
        self.combat.set_agent_conditions(self.bm, idx, cond)

    @property
    def bonus_used(self) -> bool:
        idx = self._economy_idx()
        if idx < 0:
            return getattr(self, "_bonus_used_fallback", False)
        return not self.combat.has_bonus_action(self.bm, idx)

    @bonus_used.setter
    def bonus_used(self, value: bool) -> None:
        idx = self._economy_idx()
        if idx < 0:
            self._bonus_used_fallback = bool(value)
            return
        if value:
            self.combat.spend_bonus_action(self.bm, idx)
        else:
            self.combat.reset_bonus_actions(self.bm, idx)

    def __init__(self, map_path: str, seed=None):
        pygame.init()
        pygame.display.set_caption("RPG Battle Map")
        # Optional fixed combat RNG seed (CLI --seed) for reproducible play/tests;
        # None ⇒ time-based random seed (set below).
        self._cli_seed = seed

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
        # Challenge Rating by bestiary name, for XP awards when enemies are defeated.
        # Keyed by the exact bestiary name; placed copies ("Goblin 2") strip the
        # trailing number in _agent_cr() to hit this map. See xp.py.
        self._cr_by_name = {
            name: rec.get("meta", {}).get("cr")
            for name, rec in self.mob_stats_json.items()
        }

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

        # ── Load items from items.json ──────────────────────────────────────
        # Carried consumables (healing potions today). Same data-driven pattern as
        # spells.json: the catalog is authored here, _dict_to_item builds the C++ Item.
        self.all_items = []  # list of item dicts from items.json
        possible_item_paths = [
            os.path.join(script_dir, "items.json"),
            os.path.join(script_dir, "..", "items.json"),
            os.path.join(map_dir, "items.json"),
            "items.json",
        ]
        items_loaded_from = None
        for items_path in possible_item_paths:
            if os.path.exists(items_path):
                try:
                    with open(items_path) as f:
                        self.all_items = json.load(f)
                    items_loaded_from = items_path
                    break
                except (json.JSONDecodeError, IOError):
                    continue

        if self.all_items:
            print(f"✓ Loaded {len(self.all_items)} items from {items_loaded_from}")
        else:
            print("⚠ WARNING: No items loaded.")

        # Create item lookup: item_name -> item_dict
        self.item_name_to_dict = {i.get("name"): i for i in self.all_items}

        # Selected mob's stats (loaded when a mob is selected from dropdown)
        self.selected_mob_stats = None
        self.current_mob_grid_size = 1  # Grid size for current mob (1-4)

        # Pending PC creation (used when placing a new PC)
        self._pending_pc_class = None
        self._pending_pc_stats = None

        # ── Fonts ─────────────────────────────────────────────────────────
        # Set up once, independent of the active map. SysFont needs no display
        # surface, and _build_overlay (called from _load_map_png) doesn't use them.
        self.font_sm = pygame.font.SysFont("sans", FONT_SM)
        self.font_md = pygame.font.SysFont("sans", FONT_MD)
        self.font_lg = pygame.font.SysFont("sans", FONT_LG, bold=True)
        self.font_room = pygame.font.SysFont("sans", 12)   # the DM's room-key layer
        self._letter_fonts = {}   # size -> bold SysFont, for on-token placeholder glyphs

        # Walls: HIDDEN is enabled but not shown: the walls block and the fog respects them,
        # but the DM console draws no red wall lines. Persisted as "walls_shown". Set before
        # the map loads, whose overlay reads it.
        self._walls_shown = True

        # ── Load C++ battle map + image + overlay (re-entrant) ────────────
        # Builds self.bm, map_surf, map_scale, map_rect, overlay and (re)creates
        # the display window. Callable at runtime to swap the active PNG (floor
        # paging — see FLOORS_IMPLEMENTATION_PLAN.md Phase 0).
        self._load_map_png(map_path)

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
        self.item_selection_dialog = ItemSelectionDialog(self.all_items, self.font_sm, self.font_md)
        self.item_selection_dialog.finish = lambda rec, done: items_play.finish_spell_scroll(self, rec, done)
        self.armor_dialog = ArmorDialog(self.font_sm, self.font_md)
        self.weapons_dialog = WeaponsDialog(self.font_sm, self.font_md)
        self.items_dialog = ItemsDialog(self.font_sm, self.font_md)
        mob_names = sorted(self.all_mobs.keys())
        self.mob_dialog = MobSelectionDialog(mob_names, self.font_sm, self.font_md)
        self.terrain_editor = TerrainEditorDialog(self.font_sm, self.font_md)
        self.terrain_placement_dialog = TemporaryTerrainPlacementDialog(self.font_sm, self.font_md)
        self.lighting_editor = LightingEditorDialog(self.font_sm, self.font_md)
        self.conditions_dialog = ConditionsDialog(self.font_sm, self.font_md, self.font_lg)
        self.context_menu   = ContextMenu()
        self.spell_grid_menu = SpellGridMenu()   # multi-column grid for the combat spell list
        # Cast-time element picker (Chromatic Orb / Sorcerous Burst). Reuses the same modal as
        # Elemental Adept's feat picker; opened from _activate, single-select.
        self._element_dialog = ElementPickerDialog(self.font_sm, self.font_md)

        # Asks how many cells a sampled grid box spanned (manual-grid precision).
        self._grid_span_dialog = GridSpanDialog(self.font_sm, self.font_md)
        self._wall_detect_dialog = WallDetectionDialog(self.font_sm, self.font_md)
        # Dungeon → New Dungeon…: the wizard, docked over the panel (DUNGEON_WIZARD_PLAN W4).
        self.dungeon_wizard = DungeonWizard(self.font_sm, self.font_md)
        self.floor_checklist = FloorChecklist(self.font_sm, self.font_md)   # Floors… (W7)
        # Agents… → Automate NPCs…: one slider for every red creature (menus/dm.py).
        self._npc_auto_dialog = NpcAutomationDialog(self.font_sm, self.font_md)
        self._npc_auto_level = None     # the slider's last value this session
        self._pending_grid_box = None   # (x0, y0, w, h) in image px, awaiting span input

        # Team/faction picker (opened from an agent's right-click menu → "Set Teams…").
        self.team_dialog = TeamPickerDialog(self.font_sm, self.font_md)

        # Rename prompt (opened from an agent's right-click menu → "Edit Name…").
        self.name_prompt = NamePromptDialog(self.font_sm, self.font_md)

        # ── NPC spell mechanics ──────────────────────────────────────────────
        self._agent_meta: dict[int, dict] = {}  # {agent_idx: {"npc_spell_groups": {...}}} — for stats dialog
        # XP awards: cumulative party XP this session, and the set of enemy agent
        # indices already counted (so repeated / phased End-Combat tallies never
        # double-award the same corpse). Reset when a new scene loads.
        # The tracker begins at the party's current level (the XP already required
        # to reach it) and adds XP earned from defeated enemies on top — see
        # _ensure_xp_baseline / _party_xp_total. `party_xp_baseline` is locked once
        # a party is known; `party_xp_earned` is the running combat tally.
        self.party_xp_baseline: int | None = None
        self.party_xp_earned: int = 0
        self._xp_awarded_agents: set[int] = set()

        self._map_dir  = os.path.dirname(os.path.abspath(map_path)) or "/"
        self._terrain_regions = []  # List of {type, x, y, width, height, multiplier}
        # Ladders: Python-only vertical portals (Phase 4). Each is
        # {"cells": [(col,row),...], "target": [X, Y, Z]} in GLOBAL coords. Round-trips
        # through _terrain.json alongside doors; resolved against the dungeon manifest.
        self._ladders = []
        # Cross-map door staples (Floors Phase 5): a door's cell-key -> global [X,Y,Z]
        # target on an abutting same-z page. The door itself lives in bm.doors (C++) and
        # can't hold this, so links are kept side-by-side, keyed by the door's cells, and
        # round-trip through _terrain.json as each door record's "link_target".
        self._door_links = {}
        self._painted_terrain_cells = []  # cells set to Wall/Chasm/Water by _apply_terrain_to_battle_map
        self._walls_enabled = True   # auto-detected walls active? (toggle persists in terrain JSON)
        self._detection = None       # the page's "detection" block (drawn-map mode); None = today's detector
        self._edge_overrides = None  # {"add": [[c, r, "E"|"S"], ...], "remove": [...]} or None
        # Edges carried from another floor (_maybe_carry_edges): the ones where that floor
        # and this image's detection disagree, drawn blue in the terrain editor until the
        # DM decides them. ``_edges_carried_from`` names the source pages; once set, the
        # carry never runs again for this page (until Set Grid renumbers the cells).
        self._edge_review = None     # [[c, r, "E"|"S"], ...] or None
        self._edges_carried_from = None

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
        default_agents = standalone_encounter_base(map_path)
        # Multiplayer session roster (MULTIPLAYER_PLAN.md M0): principals, the join code
        # and the one authorize() chokepoint. Built empty first so _set_encounter_base
        # can re-point it — that call then loads this encounter's session file.
        self.roster = SessionRoster()
        # Where the scene's terrain and creatures live on disk (gui/scene_store.py).
        self.store = LegacyStore(self)
        self._set_encounter_base(default_agents)
        # The autosave ring (NN7, gui/autosave.py) writes at every turn start. RPG_AUTOSAVE=0
        # turns it off; the test runner sets that, so a suite's fights don't leave slots
        # beside the repo's maps. A test of the ring turns it back on for its own App.
        self.autosave_enabled = os.environ.get("RPG_AUTOSAVE", "1") != "0"
        self._fight_started = None
        # The prompt bus (M1). Built after the roster so it can install prompt_lookup;
        # the screen does not exist yet, so the renderer resolves its size lazily.
        # Three renderers, because Step 0.2 found three widgets already drawing prompts:
        # the popup for a short list (the default), the grid for the spell list, and the
        # centred modal for a value picker. A prompt names one with `render=`.
        self.prompts = PromptBus(
            roster=self.roster,
            renderer=ContextMenuRenderer(self.context_menu,
                                         lambda: self.screen.get_size()),
            renderers={
                # The default popup with the prompt's title drawn as a header row.
                "titled": ContextMenuRenderer(self.context_menu,
                                              lambda: self.screen.get_size(),
                                              show_title=True),
                "grid":   SpellGridRenderer(self.spell_grid_menu,
                                            lambda: self.screen.get_size()),
                "picker": ElementPickerRenderer(self._element_dialog),
                # M5e E-5: Wish's and Divine Intervention's spell lists.
                SPELL_BROWSER_RENDER: SpellBrowserRenderer(self.spell_selection_dialog,
                                                           lambda: self.all_spells),
                # D-M5-2: the player's action offer. Drawn only in their browser.
                net_offer.OFFER_RENDER: RemoteRenderer(),
            })
        # D-M5-6a: the intent log. It observes the bus so that the DM taking a player's
        # prompt from them is a line too (D-M5-7); remote submits log themselves.
        self.submit_log = SubmitLog()
        self.prompts.add_observer(self.submit_log.observe)
        # D-M7-4: the table's log, read by everyone seated. The submit log repeats its
        # takeover and expiry lines into it, so the rules for those live in one place.
        self.session_log = net_sessionlog.SessionLog()
        self.submit_log.announce = lambda event, prompt: net_sessionlog.announce_prompt(
            self, event, prompt)

        # ── Multi-map dungeon state (FLOORS_IMPLEMENTATION_PLAN.md, Phase 3) ─
        # self.dungeon is None outside "dungeon mode"; when set, the app is paging
        # between the manifest's PNG pages on a shared (X, Y, Z) global grid.
        # dungeon_page is the MapPage currently loaded into the engine.
        self.dungeon: Dungeon | None = None
        self.dungeon_page: MapPage | None = None
        # Where the active manifest lives on disk (Save Dungeon rewrites it).
        self._dungeon_manifest_path: str | None = None
        # Clickable rects for the Floor-nav block, rebuilt each draw:
        #   {"left"/"right"/"up"/"down"/"floor_up"/"floor_down": pygame.Rect}
        # The block is docked in the right-side config panel (not over the map).
        self._dungeon_nav_rects: dict = {}
        # Align Floor (DUNGEON_LEVELS_PLAN.md Phase 1): ghost the floor below/above and
        # nudge this page's origin onto it.
        self.floor_align = FloorAlign()
        # Vertical scroll of the setup/config panel (pixels; 0 = top). The panel can
        # grow taller than the window (esp. with the Floor-nav block), so it scrolls.
        self.panel_scroll     = 0
        self._panel_max_scroll = 0
        # Same, for the COMBAT panel — its content (initiative + on-deck + every
        # class/subclass action button for the current agent + the log) routinely runs
        # taller than the window, so it scrolls independently of the setup panel.
        self.combat_panel_scroll      = 0
        self._combat_panel_max_scroll = 0
        self._panel_floor_nav_h   = 0
        self._panel_floor_nav_top = None
        self._panel_stats_y       = 0

        # Start with a BLANK scene: the terrain/lighting/effects sidecars are read
        # only when explicitly loaded (Terrain… / Lighting… menus, Agents… → Load),
        # never auto-inherited from whatever encounter last touched this map.
        # blank=True still resets all terrain state + wall detection to a clean slate.
        self._load_terrain(blank=True)

        # Evoker "safe targets" editing: index of the Evoker whose safe set is being
        # edited via map clicks (-1 = not editing). Out-of-combat only.
        self.safe_target_edit_idx = -1

        # Evoker L14 Overchannel: while True, the caster's next eligible damaging spell (level 1-5)
        # is cast at maximum damage. Armed/disarmed from the Evoker's right-click menu. Persistent
        # (stays on until disarmed) since the escalating self-damage is handled by the engine.
        self.overchannel_armed = False
        self.enhanced_necromancy_armed = False  # Grave Cleric L17: next eligible single-target spell takes a 2nd target

        # Sorcerer Metamagic (Phase 2): the sidebar-armed option modifies the NEXT player
        # spell cast (folded in by _apply_armed_metamagic at both cast sites). Radio-style —
        # arming one clears the others — except Seeking, the one option that stacks (SRD p.65),
        # tracked independently. Transmuted's replacement damage type is chosen at arm time.
        # Persistent (stays armed until manually toggled), mirroring Overchannel.
        # Phase 4 (Sorcery Incarnate, L7 + Innate Sorcery active): a SECOND non-Seeking option may
        # be armed at the same time; armed_metamagic2 holds it. Outside Sorcery Incarnate the
        # sidebar refuses to fill that slot and the engine would drop it unpaid anyway.
        self.armed_metamagic = rpg.MetamagicOption.NONE
        self.armed_metamagic2 = rpg.MetamagicOption.NONE
        self.armed_seeking = False
        self.pending_metamagic_transmute_type = -1

        # ── Drag-and-drop state ───────────────────────────────────────────
        self.drag_idx     = -1         # index of agent being dragged
        self.drag_origin  = None       # Cell: original position (for cancel)
        self.drag_offset  = (0, 0)     # (dcol, drow) within agent where click landed
        self.drag_cell    = None       # Cell: current snapped target
        self.drag_valid   = False      # is current drag_cell a legal drop?

        # ── Dropped-weapon drag state (DM relocates ground items by dragging) ─
        self.drag_item_id     = -1     # id of the MapItem being dragged (-1 = none)
        self.drag_item        = None   # the MapItem snapshot (weapon + sprite) being dragged
        self.drag_item_origin = None   # Cell: where the item started (for click vs. drag detection)
        self.drag_item_cell   = None   # Cell: current cursor cell while dragging
        # Items… click-to-place: ("weapon"|"armor"|"item", record) or ("chest", None)
        self._item_placing = None

        # ── Copy/paste clipboard (pre-combat encounter building) ───────────
        self._agent_clipboard = None   # snapshot dict of a copied agent (Ctrl+C / Ctrl+V)

        # ── Placement mode state (for floating agent placement) ────────────
        self.placement_mode_active = False  # True when placing new agent
        self.placement_config: rpg.AgentConfig | None = None  # Config for agent being placed
        self.placement_cell: rpg.Cell | None = None  # Current cell under mouse
        self.placement_valid = False  # Is current placement location valid?
        self._pending_import_agent: dict | None = None  # D&D Beyond record awaiting its click
        self._pc_name_input: TextInput | None = None  # Name input for new PC

        # ── Selection state ───────────────────────────────────────────────
        self.selected_idx  = -1        # index of selected agent (-1 = none)
        self._reach_walk: list = []    # Cell list for walk range overlay
        self._reach_fly:  list = []    # Cell list for fly range overlay
        self._reach_set:  set  = set() # union of walk+fly as (col,row) tuples for O(1) lookup

        # ── Visualization toggles ─────────────────────────────────────────
        self.show_lighting_overlay = False  # Toggle for lighting visualization
        # The DM's room keys ("K10") from the dungeon manifest's per-page "rooms". DM-only:
        # the player screen is served the page PNG, never this screen. On by default; the
        # Dungeon menu's Show/Hide Room Labels flips it for the session.
        self.show_room_labels = True
        self._room_label_hits: list = []     # [(screen Rect, RoomLabel)] from the last draw
        self._room_label_surfs: dict = {}    # key -> outlined text surface (cached)

        # ── Fog of war (see FOG_OF_WAR_PLAN.md) ───────────────────────────
        # Persistent explored mask lives in the C++ BattleMap; the GUI just re-runs
        # the monotonic reveal after any event that can change party vision. A dirty
        # flag keeps that off the hot render path — reveal only recomputes when a
        # trigger has marked the mask stale since the last _refresh_fog().
        self._fog_dirty = True   # force one reveal on first frame
        # Render toggle for the grey "never seen" overlay + enemy-token hiding. Default
        # OFF so a freshly opened map (terrain authoring) isn't a wall of grey; the DM
        # turns it on from the FOG button's menu (btn_fog) when running a party through.
        # Generate Dungeon turns it on for you (_set_fog) since a generated dungeon is
        # meant to be explored.
        self.show_fog = False
        # How opaque the DM's own screen draws the fog, in percent (FOG button → Opacity).
        # Below 100 the DM sees through it, enemy tokens in it included, to keep track of
        # what is going on; the players' fog (net/mapimg.py) stays opaque regardless.
        self.fog_opacity = 100
        # Ask before a save or a big operation writes over an existing file
        # (_confirm_overwrite). Off until run() starts the real loop, so a headless App —
        # every test — keeps writing at once.
        self.confirm_overwrites = False
        # Set by _request_quit: "save" (strip temporary terrain and save it) or "nosave".
        self._quit_requested: str | None = None
        # M4b B-7: the DM screen's "Animate: ON/OFF". Off lands every move at once; bubbles,
        # flashes and HP timing still play. Session-only, like the browser's own checkbox.
        self.animate_moves = True

        # ── Combat engine (C++ — seeded PRNG, RL-ready) ──────────────────
        import time
        from replay_record import RecordingCombat
        self.combat_seed = (self._cli_seed if self._cli_seed is not None
                            else int(time.time() * 1000)) % (2**32)
        # Wrap the engine so every state-mutating call is recorded for checked replay.
        self.combat = RecordingCombat(rpg.CombatEngine(self.combat_seed), rpg)
        # M4b B-2: record human moves too, so they slide (B-6) and reach the players' stream.
        # Off by default in the engine, so RL and headless runs are untouched.
        self.combat.record_moves = True
        self.logger = rpg.MessageLogger()
        self.combat.set_logger(self.logger)
        self.replay_log_file = None  # Will be set during combat start
        self._sim_trace = None       # sim_trace.TraceWriter for the fight (NPC_LEARNING_PLAN Step 1)
        self._sim_trace_nagents = 0  # placed_agents the trace has records for (header + spawned)

        # ── Attack-range overlay ──────────────────────────────────────────
        self._attack_cells_melee:  list = []   # cells attackable by active melee weapon
        self._attack_cells_rnorm:  list = []   # cells in ranged normal range
        self._attack_cells_rlong:  list = []   # cells only in ranged long range

        # ── Combat widget state ───────────────────────────────────────────
        self.combat_active        = False
        # Initiative tracker mode (plans/INITIATIVE_TRACKER_PLAN.md): the table rolls real
        # dice; player screens only broadcast the board, no NPC automation, no action rows.
        # Set via menus.dm.set_tracker_mode, which refuses mid-combat.
        self.tracker_mode         = False
        # "Players see: map only" (menus.dm.set_players_map_only): player screens get the page,
        # fog and terrain only, and every prompt goes to the DM (a table with miniatures).
        self.players_map_only     = False
        self.tracker              = Tracker()  # the typed-in turn order; _mirror_tracker
        self._tracker_hits        = []    # this frame's sheet click targets: (rect, kind, arg)
        self._tracker_edit        = None  # the row (tuple of agent idxs) being typed into
        self._tracker_edit_text   = ""
        self._tracker_hp          = -1    # agent idx whose HP box is open (T4), or -1
        self._tracker_hp_text     = ""    # the amount typed into the HP box
        self.dm_view              = False # D1: show monster HP and fogged mobs (T4b toggles)
        self.combat_paused    = False  # True when paused between turns
        self._seen_armed          = set()  # agent idxs seen holding a droppable weapon this fight
        self.initiative_order     = []    # list[rpg.InitiativeEntry], high→low
        self.initiative_item_rects = []  # list[pygame.Rect], clickable areas for initiative items
        self.on_deck_item_rects   = []    # list[(pygame.Rect, name)], clickable Deploy rows for On Deck groups
        self._action_menu         = {}    # id -> actions.Action, rebuilt each combat-panel frame (S3/M2)
        self._offer               = None  # D-M5-2: the player's live action offer (a Prompt), if any
        # D-M5-7: how long a player has to answer a reaction before it is skipped, in
        # seconds, or None for no limit. A table rule the DM sets from the session row; it
        # is not reset between fights, and `_combat.json` carries it across a resume.
        self.reaction_timeout_s   = REACTION_TIMEOUT_DEFAULT_S
        self._offer_key           = None  # ...and the projection it was built from (net/offer.py)
        # A2a: the click pick in progress (pending.py), at most one; None while nothing is armed.
        self.pick: pending.Pick | None = None
        self._move_prompt         = None  # D-M5-4: the player's live Move prompt, if any (net/move.py)
        self._pick_prompt         = None  # M5d: the player's live target prompt, if any (net/picks.py)
        self._pick_key            = None  # ...and the projection it was built from
        # M5e E-8: a remote caster's tapped center for an area spell, held until they
        # confirm it (net/picks.py). None while nothing is aimed.
        self._aoe_aim             = None
        # M5d: the attack-sequence fields as they were before the last `perform`, so that
        # cancelling an armed attack undoes the arm (net/picks.cancel_attack). A resolved
        # pick and the turn boundary drop it.
        self._attack_arm_snapshot = None
        self.turn_idx             = 0     # index into initiative_order
        self.action_used          = False
        self.bonus_used           = False
        self.attack_action_taken  = False
        self.grapple_bite_used    = False
        # The action being built, awaiting a click (pending.py: Attack / Spell / Shove /
        # Unarmed / Summon), or None. A click pick (`self.pick`) can sit on top of it.
        self.pending              = None
        # The Attack action's sequence across its swings, and the cast menu's staged choices:
        # both outlive a single arm (pending.py).
        self.attack_seq           = pending.AttackSequence()
        # An Attack action's swings still owed when Hew interrupted it with its bonus-action
        # attack: (remaining, weapon_idx, offhand, resource), or None. Restored when Hew ends.
        self.hew_paused_action_seq = None
        self.cast_setup           = pending.CastSetup()
        self.pending_horde_breaker_targets = []  # Horde Breaker: the only creatures the armed attack may strike
        self.pending_sudden_strike_targets = []  # Sudden Strike (Gloom Stalker L11): likewise
        self.pending_beasts_strike_targets = []  # Beast's Strike (Beast Master): the companion's legal targets
        self._beasts_strike_paid_now = False     # ...and whether arming it just paid an attack (cancel refunds it)
        # Dispel Magic picker: the DM-chosen effect's structure ids (dict of three id lists) to end
        # on the next cast, or None to dispel everything at the target (NPC/RL default). See
        # _begin_dispel_pick / _cast_dispel_selection.
        self.pending_dispel_selection  = None
        # Chromatic Orb leap chain (the "chromatic" pick): the primary target and the hops chosen.
        self.pending_chromatic_primary = -1
        self.pending_chromatic_chain   = []
        self._summon_conc_chosen       = False # Summon Fey's Concentration question already answered
        self.summon_hover_cell         = None  # cell under mouse while choosing a summon spot
        # Wish: spells duplicated by Wish are injected into the caster's own spell list (the engine
        # casts by index) and kept there permanently — indices stay stable so any concentration /
        # dispel bookkeeping that re-reads spells[spell_idx] remains valid. Their indices are tracked
        # here so the cast menu skips them (they must never be re-cast for free with a normal slot).
        self._wish_temp_spells: set = set()
        # Divine Intervention (Cleric L10): mirror of _wish_temp_spells — indices of spells injected by
        # a DI free-cast, skipped in the cast menu. Session-only (not serialized), like _wish_temp_spells.
        self._di_temp_spells: set = set()
        # Greater-DI (L20): set while a DI-chosen Wish runs its own duplicate flow, so _on_wish_duplicate
        # skips the 9th-slot charge (DI's 2d4 recharge lock is the cost instead).
        self._di_wish_free             = False
        self.steps_of_fey_effect       = 0     # rider: 0 None,1 Refreshing,2 Taunting,3 Disappearing,4 Dreadful
        # Trickery Cleric — Invoke Duplicity (Channel Divinity illusion).
        self.pending_duplicity_remaining = 0   # duplicates still to place this activation (L17 → up to 4)
        self._duplicity_cd_pending     = False # spend Channel Divinity on the FIRST placement of an activation
        self.move_duplicity_idx        = -1    # selected duplicate to move/swap (-1 = pick one first)
        self.pending_bastion_sp        = 0     # SP chosen for the pending Bastion of Law ward (1-5)
        self.pending_mantle_targets    = []    # chosen recipient indices (capped to CHA mod on resolve)
        self.pending_beguiling_bard    = -1    # the Glamour bard who cast the qualifying Enchantment/Illusion spell
        self._shadowy_dodge_option_index = -1   # the chosen AfterAttack option to submit once a cell is picked
        self._reaction_cell_option_index = -1   # Masterful Shots / Indomitable Teleport: the same, for its pick
        self._vitality_option_index    = -1    # the chosen reaction option index to submit once a target is picked
        self.pending_flurry_atk_idx    = -1    # attacker index for Flurry
        self.pending_flurry_rider_option = -1  # Open Hand rider option (0=Knockdown, 1=Push, 2=DenyReaction, -1=None)
        self._unarmed_strike_original_weapons = None  # (idx, weapons) to restore after attack
        self.pending_bite_empower      = 0     # Dhampir Vampiric Bite: 1 Drain / 2 Strengthen for the armed bite
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
        # NPC automation (NPC_AUTOMATION_PLAN Step 2): when an automated agent's turn starts, the
        # turn-start continuation arms this flag instead of recursing. The main loop drives exactly ONE
        # automated turn per frame (so the board renders between turns and a run is watchable), then
        # advances. -1 = no automated turn pending.
        self._npc_drive_idx       = -1
        self._npc_fresh_turn      = False  # the armed drive is a turn's first step, not a resume
        self._beguiling_twist_queue = []   # (reactor, saver) offers drained from the engine
        # Legendary Actions: after a creature's turn ends, eligible legendary creatures (enemies of
        # the just-ended creature, with actions left) may each spend legendary actions before the
        # next turn begins. _legendary_queue holds those creature indices, drained one at a time.
        self._legendary_queue        = []    # creature indices still owed a legendary-action offer
        self._legendary_actor        = -1    # creature currently being offered / resolving an action
        # Lair actions on initiative 20 (lair.py, STRAHD_LAIR_PLAN.md): the lair's owner while its
        # turn runs and the Doors choices (the map pick itself is the "lair" pick).
        self._lair_actor             = -1
        self._lair_doors             = {}
        self._legendary_spell_idx    = -1
        self._legendary_spell_label  = ""
        self._legendary_cost_pending = 1     # legendary actions the chosen option will spend
        self._legendary_attack_name  = ""    # the chosen attack option (for the target-pick prompt)
        self._legendary_attack_widx  = -1    # weapon index the chosen attack resolves through
        self._legendary_move_active  = False # armed: a legendary Dash/DashHalf move is in progress
        self._cast_post           = {}    # context the parked cast needs for post-resolve logging
        self._attack_post         = {}    # context the parked attack needs for post-resolve rider chain
        self.spell_hover_cell     = None  # cell under mouse during AoE targeting
        self.spell_anchor_cell    = None  # first click of a two-click wall (Rectangle) cast
        self.combat_log           = []    # list[str], newest first
        self.combat_log_wire      = deque(maxlen=200)  # every line, oldest first, for net views
        self.move_type             = rpg.MovementType.Walk  # selected movement type
        self._move_type_btns: dict = {}    # MovementType -> pygame.Rect (built each draw)
        self.last_movement_dist    = 0     # distance of most recent movement (for running jump)
        self.jump_overlay_active   = False # whether jump overlay is showing
        self.jump_reachable_cells  = []    # cells reachable by jump

        # ── Temporary terrain effects (spells, items, etc. with duration) ───
        self.round_num              = 0     # current round number (incremented when turn_idx wraps)
        self._effect_meta: dict     = {}    # {effect_id: {"name": str, "color": tuple, "cells": [(col,row)]}}
        self.show_terrain            = True  # toggle for showing all terrain regions (shown by default, pre-combat too)
        self._status_msg             = ""    # transient confirmation text (Save/Load Terrain, …)
        self._status_msg_until       = 0     # pygame ticks (ms) when _status_msg expires
        self._floating_texts: list   = []    # transient on-map outcome flashes
                                             # {agent_idx, text, color, spawn_ms, dur_ms, rise}
        self._npc_anim               = None  # in-flight NPC-turn playback (see _npc_anim_start);
                                             # None = live rendering, no animation running
        self._npc_anim_speed         = 1.0   # playback-time multiplier (Playback's speed control)
        self.playback                = None  # playback.Playback while a trace is on screen
        self.show_spell_effects      = True  # toggle for showing persistent spell effect overlays
        self.show_visible_targets    = False # toggle for showing visible target debug info
        self._spell_metadata: dict = {} # {(agent_idx, spell_idx): {"terrain_effect": dict, "hatch_pattern": str, "level", "upcast_dice_bonus"}}

        # ── Spell slot economy (class-based caster tracking) ────────────────

        # ── Agent config GUI state ────────────────────────────────────────
        # Combat panel first: it creates btn_show_terrain, the in-combat Show/Hide
        # Terrain toggle (pre-combat, that toggle lives in the Terrain… menu).
        panel.init_combat_panel(self)
        self._init_config_panel()
        self.scroll_y = 0         # scroll offset for agent list
        self.initiative_scroll_offset = 0  # scroll offset for initiative tracker
        self._initiative_autopaged_turn = -1  # last turn_idx auto-paged into view

        # ── Map panning (drag empty map, arrow keys) ────────────────────────────────────
        self.pan_x = 0            # horizontal pan offset in pixels
        self.pan_y = 0            # vertical pan offset in pixels
        self._pan_drag = None     # an armed drag-to-pan (see _arm_pan_drag)

        self.clock = pygame.time.Clock()

        # ── The player server (MULTIPLAYER_PLAN.md M4) ─────────────────────
        # The cache is the handoff itself and exists with or without a transport: the
        # frame tick publishes into it, and `net.view._published_page` reads what was
        # published so a view never names a `?v=` the route cannot serve (D-M4-1).
        self.map_images   = MapImageCache()
        self._net         = None    # PlayerServer, or None when aiohttp is absent (D1)
        self._net_push_ms = 0       # pygame ticks at the last push cycle (D-M4-2's 250 ms)
        self._net_turn    = None    # last (combat_active, round, turn) — the boundary test
        # M4b's global event stream (seam S3, `net.events`). Like the image cache it exists
        # with or without a transport: the sources append on the frame tick whether anyone
        # is listening or not, and a stream nobody projects holds nothing.
        self.events       = EventStream()
        # The net thread → frame tick handoff (M4c, D-M4c-1). Exists with or without a
        # transport for the same reason the image cache does: it is the seam, not the
        # server. `GET /state` is its first caller; D-M4-3's `_pump_net()` in the blocking
        # modals and M5's `submit` are the other two.
        # A read whose requester timed out is dropped unrun (D-M7-2).
        self._net_commands = CommandQueue(skip_abandoned=True)
        # M5a: `submit`s get a queue of their own, drained by `run()` beside the event
        # handler and never by `_pump_net()` — a submit is input, and may do anything a
        # click may, including open a modal (see `net.submit`).
        self._net_submits = CommandQueue()
        # D-M4d-4's guard. A command is a read that returns freshly-built data and draws
        # nothing; opening a modal violates both, and this is what makes that a refusal
        # rather than a note in the plan.
        self._net_pumping = False
        # NOT started here. `__init__` builds an App; `run()` starts one (see `net.link`).

        # NOTE: dungeon manifests are opened explicitly (Dungeon →
        # Open Dungeon…). Startup stays a blank single-map scene even when a
        # <base>.dungeon.json sits beside this map's encounter.

    # ── Save / load (gui/app_persist.py, APP_REFACTOR_PLAN A7) ──
    def _load_map_png(self, path):
        return app_persist.load_map_png(self, path)

    def _save_session(self):
        return app_persist.save_session(self)

    def _on_save_path_chosen(self, path: str):
        return app_persist.on_save_path_chosen(self, path)

    def _save_encounter_as(self, path: str):
        return app_persist.save_encounter_as(self, path)

    def _on_load_path_chosen(self, path: str):
        return app_persist.on_load_path_chosen(self, path)

    def _on_save_terrain_chosen(self, path: str):
        return app_persist.on_save_terrain_chosen(self, path)

    def _on_load_terrain_chosen(self, path: str):
        return app_persist.on_load_terrain_chosen(self, path)

    def _save_agents(self, path: str | None = None, exclude_indices=None, raw: bool = False):
        return app_persist.save_agents(self, path, exclude_indices, raw)

    def _save_combat_state(self, path: str | None = None):
        return app_persist.save_combat_state(self, path)

    def _load_combat_state(self, path: str | None = None, keep_design: bool = False) -> bool:
        return app_persist.load_combat_state(self, path, keep_design)

    def _load_agents(self, path: str | None = None):
        return app_persist.load_agents(self, path)

    def _load_terrain(self, path: str | None = None, blank: bool = False):
        return app_persist.load_terrain(self, path, blank)

    def _save_terrain(self, path: str | None = None):
        return app_persist.save_terrain(self, path)

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

        # Edge-based walls (thick red lines between cells) – only when enabled, and not
        # under Walls: HIDDEN (which keeps them blocking but undrawn).
        wall_color = (200, 60, 60, 220)
        for w in (bm.walls if self._walls_shown else ()):
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

        # Outside seeds, while the Wall Detection dialog is open.
        if getattr(self, "_wall_detect_dialog", None) is not None and self._wall_detect_dialog.visible:
            for c, rw in self._wall_detect_dialog.settings.get("outside_seeds", []):
                if 0 <= c < len(vlines) - 1 and 0 <= rw < len(hlines) - 1:
                    cx = (vlines[c] + vlines[c + 1]) // 2
                    cy = (hlines[rw] + hlines[rw + 1]) // 2
                    rad = max(3, (vlines[c + 1] - vlines[c]) // 3)
                    pygame.draw.circle(self.overlay, (40, 220, 120, 255), (cx, cy), rad)
                    pygame.draw.circle(self.overlay, (10, 60, 30, 255), (cx, cy), rad, 2)

        # Blocking edge walls (DUNGEON_LEVELS_PLAN Phase 2A), on the exact grid lines.
        for e in (getattr(bm, "edge_walls", ()) if self._walls_shown else ()):
            c, rw = e.cell.col, e.cell.row
            if c + 1 >= len(vlines) or rw + 1 >= len(hlines):
                continue
            if e.side == rpg.EdgeSide.East:
                x = vlines[c + 1]
                pygame.draw.line(self.overlay, wall_color, (x, hlines[rw]), (x, hlines[rw + 1]), 7)
            else:
                y = hlines[rw + 1]
                pygame.draw.line(self.overlay, wall_color, (vlines[c], y), (vlines[c + 1], y), 7)

    # ─────────────────────────────────────────────────────────────────────
    #  Zoom (Ctrl/Cmd + wheel, +/- keys, 0 to reset)
    # ─────────────────────────────────────────────────────────────────────
    ZOOM_MIN     = 0.5    # user-zoom multiplier floor (relative to fit scale)
    ZOOM_MAX     = 10.0   # user-zoom multiplier ceiling
    ZOOM_STEP    = 1.15   # per wheel-notch / keypress factor
    ZOOM_BTN_STEP = 1.25  # one press of the on-map + or − (net/static/app.js ZOOM_STEP)
    ZOOM_MAX_DIM = 8000   # hard cap on rendered map dimension (px) — memory guard
    PAN_SLOP_PX  = 6      # a press that moves further than this is a pan (app.js TAP_SLOP_PX)

    def _apply_zoom(self, new_zoom, center=None):
        """Set ``view_zoom`` to ``new_zoom`` (clamped), re-render the map/overlay
        surfaces at the new effective scale, and keep the image point under
        ``center`` (screen px, default = map viewport center) fixed on screen.

        Everything else reads ``self.map_scale`` (= base × zoom) and ``pan_x/y``,
        so no other draw/transform code needs to change.
        """
        if not hasattr(self, "_map_converted"):
            return
        new_zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, new_zoom))
        mw, mh = self._map_native_size
        # Clamp zoom so the rendered surface can't blow past ZOOM_MAX_DIM on
        # either axis (guards against multi-hundred-MB allocations on big maps).
        biggest = max(mw, mh) * self.base_map_scale
        if biggest > 0:
            new_zoom = min(new_zoom, self.ZOOM_MAX_DIM / biggest)
            new_zoom = max(self.ZOOM_MIN, new_zoom)
        old_scale = self.map_scale
        new_scale = self.base_map_scale * new_zoom
        if abs(new_scale - old_scale) < 1e-6:
            return

        disp_mw = max(1, int(mw * new_scale))
        disp_mh = max(1, int(mh * new_scale))

        # Rescale the map from native pixels; rebuild the (scaled) overlay.
        self.map_surf = pygame.transform.smoothscale(self._map_converted, (disp_mw, disp_mh))
        self.map_rect = pygame.Rect(0, 0, disp_mw, disp_mh)
        self.map_scale = new_scale
        self.view_zoom = new_zoom
        self.overlay = pygame.Surface((disp_mw, disp_mh), pygame.SRCALPHA)
        self._build_overlay()

        # Keep the point under ``center`` anchored: pan' = c*(1-f) + pan*f,
        # where f = new_scale / old_scale.
        if center is None:
            cx = self._panel_x() // 2               # center of the map viewport
            cy = self.screen.get_height() // 2
        else:
            cx, cy = center
        f = new_scale / old_scale
        self.pan_x = int(cx * (1.0 - f) + self.pan_x * f)
        self.pan_y = int(cy * (1.0 - f) + self.pan_y * f)
        self._clamp_pan()

    def _clamp_pan(self):
        """Keep the map viewport's centre over the map, so it cannot be panned out of
        sight — the player screen's ``clampCentre`` (net/static/app.js)."""
        if not hasattr(self, "map_rect"):
            return
        vx = self._panel_x() // 2
        vy = self.screen.get_height() // 2
        self.pan_x = max(vx - self.map_rect.w, min(vx, self.pan_x))
        self.pan_y = max(vy - self.map_rect.h, min(vy, self.pan_y))

    def _pan_by(self, dx, dy):
        self.pan_x += int(dx)
        self.pan_y += int(dy)
        self._clamp_pan()

    def _wheel_zoom(self, event, center):
        """Zoom at ``center`` for one wheel event, as the player screen does: the wheel
        zooms, no modifier needed. ``MOUSEBUTTONDOWN`` 4/5 is the older pygame form."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
            self._zoom_by(self.ZOOM_STEP if event.button == 4 else 1.0 / self.ZOOM_STEP,
                          center=center)
            return True
        if hasattr(pygame, 'MOUSEWHEEL') and event.type == pygame.MOUSEWHEEL:
            if event.y:
                self._zoom_by(self.ZOOM_STEP if event.y > 0 else 1.0 / self.ZOOM_STEP,
                              center=center)
            return True
        return False

    def _handle_map_view_event(self, event):
        """Zoom / pan the map from ``event`` alone, for a modal that draws over the live
        map (the lighting editor) while the regular map handlers are shut off: the wheel
        zooms at the cursor, arrows pan, +/- zoom, 0 fits. Returns True when the event
        was consumed."""
        if hasattr(pygame, 'MOUSEWHEEL') and event.type == pygame.MOUSEWHEEL:
            return self._wheel_zoom(event, pygame.mouse.get_pos())
        if event.type == pygame.KEYDOWN:
            pans = {pygame.K_UP: (0, 30), pygame.K_DOWN: (0, -30),
                    pygame.K_LEFT: (30, 0), pygame.K_RIGHT: (-30, 0)}
            if event.key in pans:
                self._pan_by(*pans[event.key])
            elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                self._zoom_by(self.ZOOM_STEP)
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self._zoom_by(1.0 / self.ZOOM_STEP)
            elif event.key in (pygame.K_0, pygame.K_KP0):
                self._reset_zoom()
            else:
                return False
            return True
        return False

    def _zoom_by(self, factor, center=None):
        """Multiply the current zoom by ``factor`` (wheel notch / keypress)."""
        self._apply_zoom(self.view_zoom * factor, center=center)

    def _reset_zoom(self):
        """Fit: the fit-to-window scale with the map back at the top-left, where a load
        puts it (the player screen's Fit button)."""
        self._apply_zoom(1.0)
        self.pan_x = 0
        self.pan_y = 0

    # ── The on-map zoom control (− 100% + Fit), as on the player screen ─────
    def _zoom_control_rects(self):
        """The control's buttons, keyed "out" / "level" / "in" / "fit", pinned to the
        bottom-right corner of the map viewport."""
        bh, gap, pad = 26, 4, 10
        widths = (("out", 28), ("level", 54), ("in", 28), ("fit", 40))
        total = sum(w for _, w in widths) + gap * (len(widths) - 1)
        x = self._panel_x() - pad - total
        y = self.screen.get_height() - pad - bh
        rects = {}
        for key, w in widths:
            rects[key] = pygame.Rect(x, y, w, bh)
            x += w + gap
        return rects

    def _draw_dm_view_banner(self):
        return app_board_render.draw_dm_view_banner(self)

    def _set_dm_view(self, on: bool):
        """D1's toggle. A view switch only: the explored mask is never touched."""
        self.dm_view = bool(on)
        self._combat_log_add("DM view on." if on else "DM view off: table view.")

    def _draw_zoom_control(self):
        return app_board_render.draw_zoom_control(self)

    def _handle_zoom_control(self, event):
        """A left click on the zoom control. True when the click was on it."""
        if not (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1):
            return False
        hit = next((k for k, r in self._zoom_control_rects().items()
                    if r.collidepoint(event.pos)), None)
        if hit is None:
            return False
        centre = (self._panel_x() // 2, self.screen.get_height() // 2)
        if hit == "in":
            self._zoom_by(self.ZOOM_BTN_STEP, center=centre)
        elif hit == "out":
            self._zoom_by(1.0 / self.ZOOM_BTN_STEP, center=centre)
        elif hit == "fit":
            self._reset_zoom()
        return True

    # ── Drag to pan: a press on empty map (or a token it can't move) that leaves the
    # slop pans, as on the player screen. Armed by the map's left-press handler. ──
    def _arm_pan_drag(self, pos):
        self._pan_drag = {"x0": pos[0], "y0": pos[1], "last": pos, "moved": False}

    def _handle_pan_drag(self, event):
        """Motion / release of an armed pan. True when the event was the pan's."""
        drag = getattr(self, "_pan_drag", None)
        if drag is None:
            return False
        if event.type == pygame.MOUSEMOTION:
            if not drag["moved"] and math.hypot(event.pos[0] - drag["x0"],
                                                event.pos[1] - drag["y0"]) < self.PAN_SLOP_PX:
                return False
            drag["moved"] = True
            self._pan_by(event.pos[0] - drag["last"][0], event.pos[1] - drag["last"][1])
            drag["last"] = event.pos
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._pan_drag = None
            return drag["moved"]      # a pan's release is no click (the jump overlay's, say)
        return False

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
    _BON_DRAW_RUNS = _BON_DRAW_RUNS   # for `net/offer.py`, which cannot import main
    _BTN_GAP      =  8   # gap between buttons
    _TITLE_H      = 26   # height of the bold title
    _BROWSE_W     = 34   # width of the "…" browse button

    def _init_config_panel(self):
        """Initialize config panel using layout from _panel_layout()."""
        px, W, title_y, r0, b0, b1 = app_panel_render.panel_layout(self)
        HW  = W // 2 - 2
        B   = self._BTN_H

        # Grouped popup menus (Agents… / Terrain… / Lighting…) replace the old
        # per-action button rows — each opens a ContextMenu with that group's
        # actions (save/load/edit/generate/…).
        self.btn_agents = Button(pygame.Rect(px, r0, W, B), "Agents…",
                                 (80, 100, 140), (110, 130, 170), font=self.font_md)
        self.btn_clear = Button(pygame.Rect(px, b0, W, B), "Clear All",
                               COL_BTN_DANGER, (180, 70, 70), font=self.font_md)
        self.btn_long_rest = Button(pygame.Rect(px, b1, HW, B), "Long Rest",
                                    (60, 100, 60), (80, 130, 80), font=self.font_md)
        self.btn_short_rest = Button(pygame.Rect(px + HW + 4, b1, HW, B), "Short Rest",
                                    (60, 90, 110), (80, 120, 150), font=self.font_md)
        bc_y = b1 + B + self._BTN_GAP + 8
        self.btn_begin_combat = Button(pygame.Rect(px, bc_y, W, B),
                                      "Begin Combat",
                                      COL_BTN_COMBAT, COL_BTN_COMBAT_HOV, font=self.font_md)
        # The way back into a fight after a crash, or a rewind (M6.4, D-M6-5). Its own
        # button rather than a row in Agents…, and under Begin Combat because it is the
        # other way a fight starts.
        rs_y = bc_y + B + self._BTN_GAP
        self.btn_restore_autosave = Button(pygame.Rect(px, rs_y, W, B), "Restore Autosave…",
                                           (95, 95, 75), (130, 130, 100), font=self.font_md)
        # D-M7-5: the Table menu shares the row. The combat panel has its own `table` tool.
        self.btn_table = Button(pygame.Rect(px, rs_y, W, B), "Table…",
                                (95, 95, 75), (130, 130, 100), font=self.font_md)
        # Campaign dungeons only; elsewhere they say so (plans/DUNGEON_RELEASES_PLAN.md D10).
        rd_y = rs_y + B + self._BTN_GAP
        self.btn_reset_dungeon = Button(pygame.Rect(px, rd_y, HW, B), "Reset Dungeon",
                                        (120, 75, 70), (160, 100, 95), font=self.font_md)
        # Undo Reset shares the row: the newest reset's maps and board back.
        self.btn_undo_reset = Button(pygame.Rect(px + HW + 4, rd_y, HW, B), "Undo Reset",
                                     (110, 90, 70), (150, 120, 95), font=self.font_md)
        ls_y = rd_y + B + self._BTN_GAP
        self.btn_load_save = Button(pygame.Rect(px, ls_y, W, B), "Load Save File…",
                                    (95, 95, 75), (130, 130, 100), font=self.font_md)
        ter_y = ls_y + B + self._BTN_GAP
        self.btn_terrain = Button(pygame.Rect(px, ter_y, W, B), "Terrain…",
                                  (80, 100, 120), (110, 130, 160), font=self.font_md)
        light_y = ter_y + B + self._BTN_GAP
        self.btn_lighting = Button(pygame.Rect(px, light_y, W, B), "Lighting…",
                                   (120, 100, 80), (160, 130, 110), font=self.font_md)
        # Items… (plans/ITEMS_AND_CHESTS_PLAN.md I4) shares the Lighting row.
        self.btn_items = Button(pygame.Rect(px, light_y, W, B), "Items…",
                                (105, 95, 60), (145, 130, 85), font=self.font_md)
        # One Dungeon button (plans/DUNGEON_WIZARD_PLAN.md D1): New / Open / Floors… /
        # Populate Floor… and the rest. It replaced Generate Dungeon and Dungeon
        # Configuration (W3).
        dung_y = light_y + B + self._BTN_GAP
        self.btn_dungeon = Button(pygame.Rect(px, dung_y, W, B), "Dungeon…",
                                  (95, 80, 115), (130, 110, 155), font=self.font_md)
        toggle_walls_y = dung_y + B + self._BTN_GAP
        self.btn_toggle_walls = Button(pygame.Rect(px, toggle_walls_y, W, B),
                                       self._walls_label(),
                                       (90, 80, 110), (125, 110, 150), font=self.font_md)
        toggle_fog_y = toggle_walls_y + B + self._BTN_GAP
        # One FOG button; its menu turns fog on/off, sets the DM-screen opacity and
        # resets the floor's fog (menus/board.py show_fog_button_menu).
        self.btn_fog = Button(pygame.Rect(px, toggle_fog_y, W, B), self._fog_label(),
                              (70, 90, 105), (100, 125, 145), font=self.font_md)
        toggle_anim_y = toggle_fog_y + B + self._BTN_GAP
        self.btn_toggle_animate = Button(pygame.Rect(px, toggle_anim_y, W, B),
                                         "Animate: ON" if self.animate_moves else "Animate: OFF",
                                         (70, 90, 105), (100, 125, 145), font=self.font_md)
        set_grid_y = toggle_anim_y + B + self._BTN_GAP
        self.btn_set_grid = Button(pygame.Rect(px, set_grid_y, W, B),
                                   "Set Grid…",
                                   (80, 95, 95), (110, 130, 130), font=self.font_md)
        quit_y = set_grid_y + B + self._BTN_GAP
        self.btn_quit = Button(pygame.Rect(px, quit_y, W, B),
                              "Quit",
                              COL_BTN_DANGER, (180, 70, 70), font=self.font_md)

        self.pending_configs: list[rpg.AgentConfig] = []
        self.pending_mob_stats: list[dict | None] = []  # Parallel list of mob stats for each config

    # ── Panel drawing (gui/app_panel_render.py, APP_REFACTOR_PLAN A6) ──
    def _reposition_panel(self):
        return app_panel_render.reposition_panel(self)

    def _draw_combat_panel(self):
        return app_panel_render.draw_combat_panel(self)

    def _draw_panel(self):
        return app_panel_render.draw_panel(self)

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
        """Variable-length rpg.Weapon list built from the bestiary record's
        pre-synthesized `weapons` field. Accepts BOTH the new flat "Attack N"
        list AND the legacy {main_hand,off_hand,ranged} dict. Padded to >=3 so
        callers can still assign main/off/ranged positionally; extra attacks
        (index 3+) follow. Empty slots are blank weapons."""
        wfield = mob_record.get("weapons", {})
        if isinstance(wfield, list):
            weapons = [self._weapon_from_slot_value(v) for v in wfield]
        else:
            weapons = [self._weapon_from_slot_value(wfield.get(slot, ""))
                       for slot in ("main_hand", "off_hand", "ranged")]
        while len(weapons) < 3:
            weapons.append(rpg.Weapon())
        return weapons

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
        self._pending_import_agent = None
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

    def _commit_placement(self):
        """Drop the floating agent (an imported record, a new PC or a mob) on
        ``placement_cell`` when it is valid, and leave placement mode."""
        if self.placement_cell and self.placement_valid and self._pending_import_agent:
            app_dungeon_gen.place_imported_agent(self, self._pending_import_agent, self.placement_cell)
            self._pending_import_agent = None
            self.placement_mode_active = False
            self.placement_config = None
            self.placement_cell = None
        elif self.placement_cell and self.placement_valid:
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
                return
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

    def _place_in_staging(self) -> bool:
        """Drop the floating new PC straight into the staging room (see
        ``_staging_room``) instead of waiting for a click. False, leaving placement
        mode as it is, when there is no room, no free footprint, or combat is on."""
        if self.combat_active or self.placement_config is None:
            return False
        cfg = self.placement_config
        state = (self.selected_mob_stats, self._pending_pc_class,
                 getattr(self, "_pending_pc_stats", None))
        room = self._staging_room()          # may switch to the entry page
        # A page switch reloads the scene; put the floating PC back as it was.
        self.placement_config = cfg
        self.placement_mode_active = True
        self.selected_mob_stats, self._pending_pc_class, self._pending_pc_stats = state
        if not room:
            return False
        cell = self._place_in_room(int(cfg.size or 1), room, set())
        if cell is None:
            self._flash_status("Staging room is full: click to place.")
            return False
        self.placement_cell, self.placement_valid = cell, True
        self._commit_placement()
        self._flash_status(f"{cfg.name} placed in the staging room")
        return True

    def _on_pc_class_selected(self, class_name: str):
        """Callback when a PC class is selected."""
        self.selected_mob_stats = None  # No mob stats for PCs
        self.current_mob_grid_size = 1
        self._pending_import_agent = None

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
        px, W, _, _, _, _ = app_panel_render.panel_layout(self)
        self._pc_name_input = TextInput(pygame.Rect(px, 70, W, 28), placeholder=cfg.name, font=self.font_md)
        self._pc_name_input.text = cfg.name
        self._pc_name_input.active = True

    def _mob_stats_to_d_d_stats(self, mob_record: dict):
        """Build rpg.Stats from an engine-ready bestiary record.

        The record's `stats` block is already in agent_loader.dict_to_stats
        shape (ability scores, speeds, save profs, resist/immune/vuln lists,
        is_npc), so this just loads it and applies the damage multipliers."""
        sd = mob_record.get("stats", {})
        # Add legendary data from meta.legendary to the stats dict for dict_to_stats to consume
        meta = mob_record.get("meta", {})
        if "legendary" in meta:
            sd["legendary"] = meta["legendary"]
        # Condition Immunities live in meta (stat-block display list); the engine enforces them.
        if "immunities_conditions" in meta:
            sd["condition_immunities"] = list(meta.get("immunities_conditions") or [])
        stats = dict_to_stats(sd)
        apply_damage_multipliers(stats, sd)
        # Creature type from the stat block's meta.type (e.g. "Fiend (Devil)", "Undead", "Fey").
        # Drives the Magic Circle / Hallow movement wards (D4) and Divine Smite's +1d8 vs
        # Fiend/Undead. Substring match handles the parenthetical subtypes in the bestiary.
        mtype = str(meta.get("type") or "").lower()
        for _needle, _flag in (("aberration", "is_aberration"), ("celestial", "is_celestial"),
                               ("elemental", "is_elemental"), ("fey", "is_fey"),
                               ("fiend", "is_fiend"), ("undead", "is_undead"),
                               ("construct", "is_construct")):
            if _needle in mtype and hasattr(stats, _flag):
                setattr(stats, _flag, True)
        # Monsters whose bonus action grants Dash/Disengage (e.g. the Vampire
        # Spawn's "Deathless Agility") reuse the Cunning Action machinery, which
        # is what surfaces the bonus-action Dash/Disengage buttons in the GUI.
        ba = str(meta.get("bonus_action") or "").lower()
        if "dash" in ba or "disengage" in ba:
            stats.has_cunning_action = True
        return stats

    def _load_npc_spells_from_record(self, agent_idx: int, mob_record: dict):
        return app_char_setup.load_npc_spells_from_record(self, agent_idx, mob_record)

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

    def _pixel_to_cell(self, ix, iy):
        """Convert image pixel coordinates to a grid Cell, or None if outside.
        Unlike _screen_to_cell, this works with raw image pixels (no pan/scale adjustment)."""
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        if not raw_v or not raw_h:
            return None
        # Binary-search which column/row we're in
        import bisect
        c = bisect.bisect_right(raw_v, ix) - 1
        r = bisect.bisect_right(raw_h, iy) - 1
        if 0 <= c < self.bm.grid_cols and 0 <= r < self.bm.grid_rows:
            return rpg.Cell(c, r)
        return None

    def _cell_to_screen(self, col, row):
        """Return top-left screen pixel of a grid cell.

        An encounter can carry a token whose saved cell lies outside the grid the
        currently-loaded map/terrain produces (e.g. an agent saved at row 16 on a
        16-row map, or a scene authored against a differently-anchored manual grid).
        Clamp the index into the grid-line arrays so such a stray token renders at
        the map edge — still visible and draggable back onto the map — instead of
        crashing the whole app on the first draw. Mirrors the clamp in
        _cell_to_screen_f's lerp()."""
        s     = self.map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        c = max(0, min(int(col), len(raw_v) - 1))
        r = max(0, min(int(row), len(raw_h) - 1))
        return int(raw_v[c] * s + self.pan_x), int(raw_h[r] * s + self.pan_y)

    def _cell_to_screen_f(self, col, row):
        """_cell_to_screen for FRACTIONAL grid coordinates (NPC-turn playback: a token
        mid-slide between two cells). Interpolates between adjacent grid-line positions."""
        s     = self.map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions

        def lerp(lines, v):
            i = max(0, min(int(v), len(lines) - 1))
            f = v - i
            if f <= 0 or i + 1 >= len(lines):
                return lines[i]
            return lines[i] + f * (lines[i + 1] - lines[i])

        return int(lerp(raw_v, col) * s + self.pan_x), int(lerp(raw_h, row) * s + self.pan_y)

    def _agent_at(self, cell):
        """Return index of the placed agent whose footprint contains cell, or -1.

        A truly dead corpse (conditions.dead) or a tombstoned agent is skipped so it can
        never be clicked/targeted — a live creature now shares its square, and that's the
        one we want. A downed-but-alive creature (hp 0, making death saves) is NOT skipped,
        so it can still be selected to be healed."""
        for i, pt in enumerate(self.bm.placed_agents):
            if pt.removed_from_play or pt.conditions.dead:
                continue
            oc, or_ = pt.origin.col, pt.origin.row
            if oc <= cell.col < oc + pt.size and or_ <= cell.row < or_ + pt.size:
                return i
        return -1

    def _corpse_at(self, cell):
        """Return the index of a true-dead corpse (conditions.dead) whose footprint contains
        cell, or -1. The mirror image of _agent_at, which deliberately skips corpses: revive /
        raise spells (revives_dead) select a body the normal click can't reach. A tombstoned
        (removed_from_play) corpse is still skipped — it's gone from the board."""
        for i, pt in enumerate(self.bm.placed_agents):
            if pt.removed_from_play or not pt.conditions.dead:
                continue
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
    # ── Multiplayer session roster (MULTIPLAYER_PLAN.md M0) ─────────────────
    def _sync_roster_tokens(self):
        """Refresh the roster's ownership cache from the live agent records.

        Ownership is derived, never stored twice (A1): the agent record's `controller`
        is the only persisted truth, and the roster caches the reverse mapping. Runs on
        the pygame thread only (NN1) — it reads pybind11 accessors, which are C++ calls.
        Call after anything that changes the agent list or a controller assignment."""
        self.roster.sync_tokens(tokens_from_battle_map(self.bm))

    def _prompt_owner(self, agent_idx: int) -> str:
        """Who answers a prompt for this token: its controller, or the DM while players see
        the map only (their screens carry no prompts then) or in tracker mode (the DM enters
        everything; player screens only broadcast the board)."""
        if self.players_map_only or self.tracker_mode:
            return DM_PRINCIPAL_ID
        return self.roster.controller_of(agent_idx)

    # ── Save / load callbacks called by the file browser ─────────────────────
    @staticmethod
    def _sidecar_base(agents_path: str) -> tuple[str, str]:
        """(dir, base) for an agents file: '<dir>/<base>_agents.json', or
        '<dir>/<base>.json' for a plain name. Every sidecar is '<dir>/<base>_<kind>.json'."""
        fn = os.path.basename(agents_path)
        if fn.endswith("_agents.json"):
            base = fn[:-len("_agents.json")]
        else:
            base = os.path.splitext(fn)[0]
        return os.path.dirname(agents_path), base

    def _set_encounter_base(self, agents_path: str):
        """Point all per-encounter sidecar files at the same base name as the chosen
        agents file, so one map PNG can host many encounters.

        Given '<dir>/<base>_agents.json' (or '<dir>/<base>.json' if the user typed a
        plain name), the sidecars become '<dir>/<base>_terrain.json',
        '<base>_effects.json' and '<base>_lighting.json'.
        """
        self._save_path = agents_path
        d, base = self._sidecar_base(agents_path)
        self._terrain_path  = os.path.join(d, base + "_terrain.json")
        self._effects_path  = os.path.join(d, base + "_effects.json")
        self._lighting_path = os.path.join(d, base + "_lighting.json")
        # Mid-combat resume sidecar (COMBAT_REFACTOR_PLAN.md R5): the C++ engine's
        # snapshot plus the Python turn loop. Written only while a fight is running.
        self._combat_path   = os.path.join(d, base + "_combat.json")
        # Table metadata, NOT scene data (MULTIPLAYER_PLAN.md M0): who is seated at this
        # table and the join code. Gitignored, and never part of the encounter proper —
        # the encounter records only each token's controller id.
        self._point_session(os.path.join(d, base + "_session.json"))

    def _point_scene_at(self, page: MapPage):
        """Point the per-scene paths at a dungeon page: the run's in a campaign (the
        store says where), else the page's own encounter sidecars."""
        if isinstance(self.store, CampaignStore):
            paths = self.store.point_at(page)
            self._save_path     = paths["agents"]
            self._terrain_path  = paths["terrain"]
            self._lighting_path = paths["lighting"]
            self._effects_path  = paths["effects"]
            self._combat_path   = paths["combat"]
            self._point_session(paths["session"])
            return
        enc = page.encounter_base
        self._set_encounter_base(enc if (not enc or os.path.isabs(enc))
                                 else os.path.join(app_dungeon_pages.dungeon_dir(self), enc))

    def _point_session(self, _new_session: str):
        """Load the session roster from ``_new_session`` when the table changes."""
        # Re-point the roster at the new base — but ONLY when the base actually moved.
        #
        # `SessionRoster.__init__` mints a fresh signing key (A5), so REPLACING the roster
        # invalidates every outstanding credential at once. That is exactly right when the
        # table changes: the seats are a different table's. It is a mass logout when the
        # table does NOT change — re-loading the encounter that is already open, which a DM
        # does constantly, used to close every connected socket with
        # WS_CLOSE_UNAUTHENTICATED and send every phone back to the join card. Found in the
        # first manual pass, where it reads as "the phone crashed when I loaded the agents".
        #
        # Guarded on both attributes because the first call happens during __init__, where
        # the BattleMap does not exist yet: the roster loads, and its ownership cache fills
        # on the first _load_agents. That first call is also never "the same table", since
        # there is no roster yet to keep.
        _same_table = (_new_session == getattr(self, "_session_path", None))
        self._session_path  = _new_session
        if getattr(self, "roster", None) is not None and not _same_table:
            self.roster = SessionRoster.load(self._session_path)
            # A new roster means a new prompt_lookup hook to fill (M1).
            if getattr(self, "prompts", None) is not None:
                self.prompts.bind_roster(self.roster)
            # …and a new table for the player server to authenticate against (M4). The
            # roster is REPLACED here, not mutated, so a server holding the old one would
            # keep answering for the previous encounter.
            if getattr(self, "_net", None) is not None:
                self._net.set_roster(self.roster)
                self.session_log.add("The DM opened another table. Everyone joins again.")
                # The startup "[net] join code" line now names the old table's code, so
                # say the new one (DM-only in the log: a code is never sent to players).
                code = self.roster.join_code
                self.session_log.add(f"Join code for this table: {code}", dm_only=True)
                print(f"[net] join code: {code}")
                self._flash_status(f"Another table: join code {code}")
            if getattr(self, "bm", None) is not None:
                self._sync_roster_tokens()

    def _page_agents_path(self, page: MapPage) -> str:
        return app_dungeon_pages.page_agents_path(self, page)


    @staticmethod
    def _nearest_unoccupied(col, row, size, occupied, cols, rows):
        """Nearest (col, row) to the given one where a size×size footprint misses every
        cell in ``occupied`` and stays on a cols×rows grid (unbounded when 0). Used for
        pages that are not showing, whose terrain is not loaded."""
        def ok(c, r):
            if c < 0 or r < 0 or (cols and c + size > cols) or (rows and r + size > rows):
                return False
            return all((c + dc, r + dr) not in occupied
                       for dc in range(size) for dr in range(size))
        if ok(col, row):
            return col, row
        for radius in range(1, max(cols, rows, 64) + 1):
            for dc in range(-radius, radius + 1):
                for dr in range(-radius, radius + 1):
                    if max(abs(dc), abs(dr)) == radius and ok(col + dc, row + dr):
                        return col + dc, row + dr
        return None

    @staticmethod
    def _clear_page_mobs(doc: dict, incoming_names: set) -> int:
        """Load Encounter replaces a page's mobs: drop every NPC from the page's creature
        ``doc``, plus any creature sharing a name with one the file brings (a PC saved in
        the encounter replaces its copy instead of doubling). Other PCs stay. Conditions
        on a dropped creature, or cast by one, go with it; the rest are re-indexed.
        Returns how many creatures were dropped."""
        agents = doc.get("agents") or []
        keep = [i for i, a in enumerate(agents)
                if not (isinstance(a, dict) and (a.get("is_npc") or a.get("name") in incoming_names))]
        remap = {old: new for new, old in enumerate(keep)}
        conds = []
        for cd in doc.get("active_conditions") or []:
            if not isinstance(cd, dict):
                continue
            target = remap.get(int(cd.get("agent_idx", -1)))
            caster = int(cd.get("caster_idx", -1))
            if target is None or (caster >= 0 and caster not in remap):
                continue
            cd = dict(cd)
            cd["agent_idx"] = target
            if caster >= 0:
                cd["caster_idx"] = remap[caster]
            conds.append(cd)
        doc["agents"] = [agents[i] for i in keep]
        doc["active_conditions"] = conds
        return len(agents) - len(keep)


    def _apply_page_origin(self, page: MapPage):
        return app_dungeon_pages.apply_page_origin(self, page)

    def _switch_to_page(self, page: MapPage, drop_cell=None, carry=None, force=False):
        return app_dungeon_pages.switch_to_page(self, page, drop_cell, carry, force)


    def _page_step(self, direction: str):
        return app_dungeon_pages.page_step(self, direction)

    def _floor_step(self, delta: int):
        return app_dungeon_pages.floor_step(self, delta)


    def _clear_agents(self):
        """Remove every placed agent (plus their spell terrain effects and any
        ground items) — the agent-scoped clear that used to be the Clear All
        button. The panel's Clear All now wipes the whole scene via _clear_all."""
        self.bm.clear_agents()
        self.bm.clear_terrain_effects()
        restore_design = placed_items.keep_design_items(self.bm)
        self.bm.clear_items()
        restore_design()            # DM-placed items belong to the map, not the agents
        self.pending_configs.clear()
        self.pending_mob_stats.clear()
        # Index-keyed per-agent metadata would bleed onto whatever agents land at
        # those indices next (same gotcha as _load_agents) — drop it with them.
        self._spell_metadata.clear()
        self._agent_meta.clear()
        self._xp_awarded_agents.clear()
        self.selected_idx        = -1
        self.drag_idx            = -1
        self._attack_cells_melee = []
        self._attack_cells_rnorm = []
        self._attack_cells_rlong = []

    def _clear_all(self):
        """Panel "Clear All": wipe the whole scene — agents, terrain AND lighting —
        back to a blank map (same state as a fresh startup)."""
        self._clear_agents()
        self._clear_terrain()
        app_lighting.clear_lighting(self)
        self._flash_status("Cleared agents, terrain and lighting.")

    def _open_load_agents_browser(self):
        """Open the encounter Load browser. No name_pattern: show ALL .json so
        encounters saved with custom names (not just *_agents.json) are visible."""
        start = os.path.dirname(self._save_path) or self._map_dir
        self.file_browser.open(
            start, self._on_load_path_chosen,
            save_mode=False,
            extensions=JSON_EXTS,
            title="Load Encounter",
        )

    def _open_save_agents_browser(self):
        start = os.path.dirname(self._save_path) or self._map_dir
        self.file_browser.open(
            start, self._on_save_path_chosen,
            save_mode=True,
            extensions=JSON_EXTS,
            default_filename=os.path.basename(self._save_path),
            name_pattern="_agents.json",
            title="Save Encounter As",
        )

    def _pcs_dir(self) -> str:
        """Where Load PCs / Save PC open: a campaign's pcs/ folder, else the encounters/
        folder beside maps/, else the encounter's own folder."""
        start = os.path.dirname(self._save_path) or self._map_dir
        encounters = os.path.join(os.path.dirname(self._map_dir), save_layout.ENCOUNTERS_DIR)
        if os.path.isdir(encounters):
            start = encounters
        if isinstance(self.store, CampaignStore) and os.path.isdir(self.store.campaign.pcs_dir):
            start = self.store.campaign.pcs_dir
        return start

    def _open_save_pc_browser(self, idx: int):
        """Save one agent as a single-PC file (the bare-record shape Load PCs reads), so
        a PC's sheet can be updated on its own. Defaults to pcs/<slug>.json."""
        name = self.bm.placed_agents[idx].name
        self.file_browser.open(
            self._pcs_dir(), lambda path: self._confirm_overwrite(
                [path], "Save PC", lambda: self._save_pc(idx, path)),
            save_mode=True,
            extensions=JSON_EXTS,
            default_filename=save_layout.slugify(name) + ".json",
            title=f"Save PC: {name}",
        )

    def _save_pc(self, idx: int, path: str):
        records = app_dungeon_pages.read_agent_records(self, [idx])
        if not records:
            self._flash_status("Could not save PC")
            return
        try:
            with open(path, "w") as f:
                json.dump(records[0], f, indent=2)
        except OSError as e:
            self._flash_status(f"Could not save {os.path.basename(path)}: {e}")
            return
        self._flash_status(f"Saved {records[0].get('name', 'PC')} to {os.path.basename(path)}")

    def _open_load_pcs_browser(self):
        """Load PCs ADDITIVELY onto the current scene, so they drop onto an
        already-loaded dungeon without wiping its monsters. Multi-select: tick any
        mix of party files (*_pc_agents.json) and single-PC files (a campaign's
        pcs/<name>.json). It opens on the encounters/ folder beside maps/; in a
        campaign, on its pcs/ folder."""
        self.file_browser.open(
            self._pcs_dir(), self._on_load_pcs_chosen,
            save_mode=False,
            extensions=JSON_EXTS,
            title="Load PCs",
            multi_select=True,
        )


    def _open_terrain_editor(self):
        # The terrain editor works on the fit-scale map_surf (its regions are stored in
        # fit-scale px) and zooms/pans with a view of its own, so hand it fit scale and
        # open that view where the map's was.
        view = (self.view_zoom, (self.pan_x, self.pan_y))
        self._reset_zoom()
        # The editor edits self._ladders in place; snapshot it so the close can pair the
        # ladders placed / removed this session with their other ends (_pair_ladders).
        self._ladders_at_open = [self._ladder_key(lad) for lad in self._ladders]
        # The Staircase tool edits the manifest's staircases in place; the close writes the
        # manifest if they changed.
        self._stairs_at_open = app_dungeon_pages.staircases_snapshot(self)
        # The Edge tool edits the overrides in place and re-detects after each edit.
        # First visit to a floor of a dungeon: start from the nearest edited floor's edges
        # and flag where this image disagrees (blue). Saves the page if it carried.
        self._maybe_carry_edges()
        if self._edge_overrides is None:
            self._edge_overrides = {"add": [], "remove": []}
        if self._edge_review is None:
            self._edge_review = []
        self._edges_at_open = json.dumps([self._edge_overrides, self._edge_review],
                                         sort_keys=True)
        self._doors_at_open = self._door_layout()
        # After the snapshot, so a list saved before the pruning rule is re-saved pruned.
        self._prune_edge_review()
        drawn = self._walls_enabled and (self._detection or {}).get("mode") == "dark_fraction"
        self.terrain_editor.open(self.map_surf, self._terrain_regions, self.bm,
                                 ladders=self._ladders, door_links=self._door_links,
                                 on_regions_changed=self._preview_floor_regions,
                                 edge_overrides=self._edge_overrides, edges_enabled=drawn,
                                 on_edges_changed=lambda: self._redetect_walls(
                                     self.terrain_editor.terrain_regions),
                                 edge_review=self._edge_review,
                                 edge_review_source=", ".join(self._edges_carried_from or []),
                                 dungeon=self.dungeon,
                                 page_id=self.dungeon_page.id if self.dungeon_page else None,
                                 ask_text=lambda text, commit, title, allow_empty:
                                     self.name_prompt.show(text, commit, title=title,
                                                           allow_empty=allow_empty),
                                 ask_menu=lambda title, pairs, anchor:
                                     self._ask_dm("action", title, pairs, anchor=anchor),
                                 on_stair_goto=self._editor_stair_goto,
                                 grid_scale=self.base_map_scale,
                                 ghost_loader=(lambda z: load_floor_ghosts(self, z))
                                 if self.dungeon is not None else None)
        self.terrain_editor.set_view(*view)

    def _editor_stair_goto(self, sid: int, end_index: int):
        """Staircase tool → Go to linked end: close the editor as Esc does (asking before
        overwriting the terrain file), switch to that end's floor, and reopen the editor
        there with the Staircase tool on and that end selected."""
        def go():
            self._close_terrain_editor()
            if not app_dungeon_pages.staircase_goto(self, sid, end_index):
                return
            self._open_terrain_editor()
            self.terrain_editor.selected_type = "Staircase"
            self.terrain_editor.stair_selected = (sid, end_index)
        self._confirm_overwrite([self._terrain_path], "Go to the other end", go)

    def _close_terrain_editor(self):
        """Esc in the terrain editor: take its edits, save them, give new / removed
        ladders their other ends, and re-apply terrain to the engine."""
        floors_before = [r for r in self._terrain_regions if r.get("type") == "Floor"]
        self._terrain_regions = self.terrain_editor.terrain_regions
        edges_changed = json.dumps([self._edge_overrides, self._edge_review],
                                   sort_keys=True) != getattr(self, "_edges_at_open", None)
        if self._edge_overrides is not None and not (self._edge_overrides.get("add")
                                                     or self._edge_overrides.get("remove")):
            self._edge_overrides = None
        if not self._edge_review:
            self._edge_review = None
        if edges_changed or self._door_layout() != getattr(self, "_doors_at_open", None) or \
                [r for r in self._terrain_regions if r.get("type") == "Floor"] != floors_before:
            self._redetect_walls()
            self._build_overlay()
        self._ladders = self.terrain_editor.ladders
        self._door_links = self.terrain_editor.door_links
        self._save_terrain()
        self._pair_ladders(getattr(self, "_ladders_at_open", []))
        if app_dungeon_pages.staircases_snapshot(self) != getattr(self, "_stairs_at_open", None):
            app_dungeon_pages.dungeon_save_manifest(self)
        self._apply_terrain_to_battle_map()
        self.terrain_editor.close()
        # The map comes back where the editor's view left it.
        self._apply_zoom(self.terrain_editor.view_zoom)
        self.pan_x, self.pan_y = self.terrain_editor.view_pan
        self._clamp_pan()
        # Recalculate reach and attack overlays if an agent is selected
        if self.selected_idx >= 0:
            self._update_reach()
            self._update_attack_overlay()

    def _door_layout(self):
        """Where the doors are (not their state): the outside flood depends on it."""
        return sorted((sorted((c.col, c.row) for c in d.cells),
                       sorted((e.cell.col, e.cell.row, int(e.side)) for e in d.edges))
                      for d in self.bm.doors)

    def _toggle_show_terrain(self):
        self.show_terrain = not self.show_terrain

    def _open_save_terrain_browser(self):
        """Save Terrain (file picker — lets terrain be saved before combat and
        reused across maps/encounters, independent of the agents save)."""
        start = os.path.dirname(self._terrain_path) or self._map_dir
        self.file_browser.open(
            start, self._on_save_terrain_chosen,
            save_mode=True,
            extensions=JSON_EXTS,
            default_filename=os.path.basename(self._terrain_path),
            name_pattern="_terrain.json",
            title="Save Terrain As",
        )

    def _open_load_terrain_browser(self):
        """Open the terrain Load browser. No name_pattern: show ALL .json so
        terrain saved with custom names (not just *_terrain.json) shows."""
        start = os.path.dirname(self._terrain_path) or self._map_dir
        self.file_browser.open(
            start, self._on_load_terrain_chosen,
            save_mode=False,
            extensions=JSON_EXTS,
            title="Load Terrain",
        )

    def _clear_terrain(self):
        """Reset the scene's terrain to a blank slate: painted regions, doors,
        ladders, generator room metadata and engine terrain effects all go.
        Auto-detected walls and the manual grid are left alone (the Walls toggle
        and Set Grid… own those)."""
        self._terrain_regions = []
        self._terrain_rooms = []
        self._staging_cells = None
        self._ladders = []
        self._door_links = {}
        for d in list(self.bm.doors):
            self.bm.remove_door(d.id)
        self.bm.reset_terrain_multipliers()
        self._apply_terrain_to_battle_map()   # reverts painted Wall/Chasm/Water cells
        self.bm.clear_terrain_effects()
        self._build_overlay()
        self._mark_fog_dirty()
        if self.selected_idx >= 0:
            self._update_reach()
            self._update_attack_overlay()
        self._flash_status("Terrain cleared.")


    def _open_lighting_editor(self):
        return app_lighting.open_lighting_editor(self)

    def _open_load_lighting_browser(self):
        start = os.path.dirname(self._lighting_path) or self._map_dir
        self.file_browser.open(
            start, self._on_load_lighting_chosen,
            save_mode=False,
            extensions=JSON_EXTS,
            title="Load Lighting",
        )

    def _toggle_lighting_overlay(self):
        self.show_lighting_overlay = not self.show_lighting_overlay


    def _grid_size(self) -> tuple[int, int]:
        return (int(getattr(self.bm, "grid_cols", 0) or 0),
                int(getattr(self.bm, "grid_rows", 0) or 0))

    def _dungeon_new(self, anchor=None):
        return app_dungeon_pages.dungeon_new(self, anchor)


    def _open_campaign(self, anchor=None):
        return app_dungeon_pages.open_campaign(self, anchor)


    def _dungeon_new_loose(self):
        return app_dungeon_pages.dungeon_new_loose(self)


    # ── Confirm before overwriting ───────────────────────────────────────────
    def _confirm_overwrite(self, paths, what: str, proceed, *, anchor=None, on_cancel=None):
        """Run ``proceed()`` now if none of ``paths`` exists yet (or confirmation is
        off); otherwise ask the DM first — "Overwrite" runs it, Cancel runs
        ``on_cancel`` and writes nothing."""
        existing = sorted({p for p in paths if p and os.path.exists(p)})
        if not existing or not self.confirm_overwrites:
            proceed()
            return
        names = ", ".join(os.path.basename(p) for p in existing[:3])
        if len(existing) > 3:
            names += f" and {len(existing) - 3} more"
        cancel = on_cancel or (lambda: None)
        self._ask_dm("action", f"{what}: overwrite {names}?",
                     [("Overwrite", proceed), ("Cancel", cancel)],
                     anchor=anchor or pygame.mouse.get_pos(), on_cancel=cancel,
                     render="titled")

    def _request_quit(self, anchor=None):
        """Quit button / window close. Quitting strips temporary terrain and saves the
        terrain file; when that file exists, ask first (save, don't save, or stay)."""
        if self._quit_requested is not None:
            return
        if not (self.confirm_overwrites and os.path.exists(self._terrain_path)):
            self._quit_requested = "save"
            return

        def choose(v):
            def _set():
                self._quit_requested = v
            return _set
        self._ask_dm("action", f"Quit: save terrain to {os.path.basename(self._terrain_path)}?",
                     [("Save and quit", choose("save")),
                      ("Quit without saving", choose("nosave")),
                      ("Cancel", lambda: None)],
                     anchor=anchor or pygame.mouse.get_pos(), render="titled")

    def _dungeon_save_confirmed(self, anchor=None):
        return app_dungeon_pages.dungeon_save_confirmed(self, anchor)

    def _dungeon_save(self):
        return app_dungeon_pages.dungeon_save(self)

    def _dungeon_save_manifest(self) -> bool:
        return app_dungeon_pages.dungeon_save_manifest(self)

    def _dungeon_open_browser(self):
        return app_dungeon_pages.dungeon_open_browser(self)

    def _on_open_dungeon_chosen(self, path: str):
        return app_dungeon_pages.on_open_dungeon_chosen(self, path)

    def _open_campaign_dungeon(self, manifest: str, run_name: str = save_layout.DEFAULT_RUN):
        return app_dungeon_pages.open_campaign_dungeon(self, manifest, run_name)


    def _dungeon_close(self):
        return app_dungeon_pages.dungeon_close(self)


    def _dungeon_pages_overview(self):
        return app_dungeon_pages.dungeon_pages_overview(self)

    def _modal_dungeon_pages(self) -> "MapPage | None":
        return app_dungeon_pages.modal_dungeon_pages(self)

    def _draw_floor_overview(self, rect: pygame.Rect, z: int, sel_id=None) -> dict:
        return app_dungeon_pages.draw_floor_overview(self, rect, z, sel_id)

    def _flash_status(self, msg: str, secs: float = 2.5):
        """Show a transient confirmation message in the panel for `secs` seconds."""
        self._status_msg = msg
        self._status_msg_until = pygame.time.get_ticks() + int(secs * 1000)

    def _spawn_flash(self, agent_idx, text: str, color, secs: float = 1.5,
                     stream: bool = True):
        """Spawn a short-lived floating text flash above an agent's token (e.g.
        "Hit (12)" / "Miss" / "Saved" / "Failed"). Session-only visual state; drawn
        each frame by _draw_floating_texts until it expires.

        It is also an `outcome` on the event stream (M4b B-2), with `hp_after: -1`: the
        human-driven path has already changed the state, so there is no timed drop to
        play. NPC playback passes `stream=False`, because its outcomes reached the stream
        from the engine's own buffer and a second copy is a double flash."""
        if agent_idx is None or agent_idx < 0:
            return
        if stream:
            self.events.append(net_outcome(agent_idx, text, good=color != FLASH_BAD,
                                           crit=color == FLASH_CRIT))
        # Stagger multiple flashes on the same agent (e.g. multiattack) so they
        # rise from different heights rather than overlapping.
        rise = sum(20 for f in self._floating_texts if f["agent_idx"] == agent_idx)
        self._floating_texts.append({
            "agent_idx": agent_idx, "text": text, "color": color,
            "spawn_ms": pygame.time.get_ticks(), "dur_ms": int(secs * 1000),
            "rise": rise,
        })

    def _draw_floating_texts(self):
        return app_board_render.draw_floating_texts(self)

    # ─────────────────────────────────────────────────────────────────────
    #  NPC turn playback (animated automated turns)
    # ─────────────────────────────────────────────────────────────────────
    # run_npc_turn resolves an automated turn atomically in C++, but the engine records a
    # visual event stream (rpg.NpcVisualEvent: Move paths / Announce text / Outcomes) which
    # the GUI replays here over several frames. While a playback is active the board renders
    # DISPLAY OVERRIDES — positions, HP values and alive-flags snapshotted BEFORE the turn
    # ran — and each played event advances them: the token slides along its actual route,
    # the action text typewriter-scrolls above the actor, and damage flashes / HP-bar drops
    # land when their moment arrives instead of teleport-and-done. _advance_turn (or the
    # parked reaction menu) is DEFERRED until the queue drains. Any click or keypress
    # fast-forwards (see _handle_events).

    _NPC_EV_MOVE, _NPC_EV_ANNOUNCE, _NPC_EV_OUTCOME = 0, 1, 2   # NpcVisualEvent.Kind values

    def _npc_anim_snapshot(self):
        """Pre-turn display state: origin / HP / alive of every in-play agent, captured
        BEFORE run_npc_turn mutates the world. Seeds the playback's display overrides."""
        snap = {}
        for i, pt in enumerate(self.bm.placed_agents):
            if pt.removed_from_play:
                continue
            snap[i] = {"pos": (float(pt.origin.col), float(pt.origin.row)),
                       "hp": pt.stats.hp_cur,
                       "was_alive": not pt.conditions.dead}
        return snap

    def _npc_anim_start(self, events, snapshot, on_done):
        """Begin replaying an automated turn's event stream. on_done runs when it drains
        (advance the turn, or open the parked reaction menu the turn suspended on)."""
        self._npc_anim = {
            "events":  events,
            "ei":      0,                          # current event index
            "t0":      pygame.time.get_ticks(),    # ms the current event started
            "applied": False,                      # current Outcome's one-shot side effects done
            "pos":     {i: s["pos"] for i, s in snapshot.items()},   # {idx: (fcol, frow)}
            "hp":      {i: s["hp"] for i, s in snapshot.items()},    # {idx: displayed hp_cur}
            # Agents alive at snapshot keep drawing even if the turn killed them — the corpse
            # (and its killing-blow flash) vanish together when the playback drains.
            "draw_dead": {i for i, s in snapshot.items() if s["was_alive"]},
            "on_done": on_done,
        }

    # ── Display-override accessors (rendering reads these) ───────────────
    def _npc_anim_display_pos(self, idx):
        """(fcol, frow) the token should be drawn at during playback, else None."""
        a = self._npc_anim
        return a["pos"].get(idx) if a is not None else None

    def _npc_anim_hp(self, idx):
        """HP value the token's bar should show during playback, else None (= live)."""
        a = self._npc_anim
        return a["hp"].get(idx) if a is not None else None

    def _npc_anim_defers(self):
        """True while a playback holds back a continuation (an NPC turn's advance, or its
        parked reaction menu). A human move's slide (on_done=None) defers nothing, so the
        player's offer and prompts stay up through it."""
        a = self._npc_anim
        return a is not None and a.get("on_done") is not None

    def _npc_anim_draws_dead(self, idx):
        """True while playback holds a now-dead token on screen (alive at snapshot)."""
        a = self._npc_anim
        return a is not None and idx in a["draw_dead"]

    # ── Per-frame advance (called from the main loop) ─────────────────────
    def _advance_npc_playback(self):
        """Advance the active playback one frame. Instant events chain within the frame;
        timed events (a sliding move, a scrolling announce, an outcome beat) return with
        their overrides set for this frame's draw."""
        a = self._npc_anim
        if a is None:
            return
        now = pygame.time.get_ticks()
        while True:
            if a["ei"] >= len(a["events"]):
                self._npc_anim_finish()
                return
            ev = a["events"][a["ei"]]
            el = (now - a["t0"]) * self._npc_anim_speed
            if ev.kind == self._NPC_EV_MOVE:
                path  = ev.path
                steps = len(path) - 1
                if steps <= 0 or not self.animate_moves or self._agent_fogged(ev.agent_idx):
                    if steps > 0:   # fogged mover, or Animate: OFF: land it, skip the slide
                        a["pos"][ev.agent_idx] = (float(path[-1].col), float(path[-1].row))
                    self._npc_anim_next(now)
                    continue
                dur = steps / NPC_ANIM_CELLS_PER_SEC * 1000.0
                if el >= dur:
                    a["pos"][ev.agent_idx] = (float(path[-1].col), float(path[-1].row))
                    self._npc_anim_next(now)
                    continue
                p = el / dur * steps                 # fractional path progress in cells
                i = min(int(p), steps - 1)
                f = p - i
                c0, c1 = path[i], path[i + 1]
                a["pos"][ev.agent_idx] = (c0.col + f * (c1.col - c0.col),
                                          c0.row + f * (c1.row - c0.row))
                return
            if ev.kind == self._NPC_EV_ANNOUNCE:
                if self._agent_fogged(ev.agent_idx):
                    self._npc_anim_next(now)
                    continue
                dur = len(ev.text) / NPC_TYPEWRITER_CPS * 1000.0 + NPC_ANNOUNCE_HOLD_MS
                if el >= dur:
                    self._npc_anim_next(now)
                    continue
                return   # _draw_npc_announcement renders the typewriter reveal from ev + t0
            # Outcome: one-shot side effects (flash + HP override), then a short beat so
            # consecutive swings of a multiattack read as separate hits.
            if not a["applied"]:
                a["applied"] = True
                self._npc_anim_apply_outcome(ev)
            if el >= NPC_OUTCOME_BEAT_MS:
                self._npc_anim_next(now)
                continue
            return

    def _play_human_moves(self):
        """M4b B-6: drain a committed human move from the engine buffer (record_moves) into
        the players' stream, and slide it on this screen too.

        The move is already committed and the menus already open, so the playback has no
        continuation (on_done=None): it changes only what is drawn. If a playback is already
        running, the move joins its queue, so that playback keeps its own continuation.

        Called only from _after_move_committed, never straight after submit_decision: while
        an NPC turn is parked for a human reaction, the buffer holds that turn's events, and
        they belong to the run_npc_turn drain _resume_npc_turn leads to (the B-2 trap)."""
        events = self.combat.take_npc_visual_events()
        if not events:
            return
        self.events.extend_npc(events)
        self._trace_events(events)
        a = self._npc_anim
        if a is None:
            self._npc_anim_start(events, {}, on_done=None)
            a = self._npc_anim
        else:
            a["events"] = list(a["events"]) + list(events)
        # Hold each mover at its route's start until its slide begins. Only movers are held:
        # every other agent, and every HP bar, is drawn live.
        for ev in events:
            if ev.kind == self._NPC_EV_MOVE and len(ev.path) > 1:
                a["pos"].setdefault(ev.agent_idx,
                                    (float(ev.path[0].col), float(ev.path[0].row)))

    def _npc_anim_next(self, now):
        a = self._npc_anim
        a["ei"]      += 1
        a["t0"]       = now
        a["applied"]  = False

    def _npc_anim_apply_outcome(self, ev):
        """One-shot side effects of an Outcome event: the floating flash and the synced
        HP-bar override. (A killed token keeps drawing until the playback drains — see
        draw_dead — so the killing-blow flash isn't orphaned over an empty square.)"""
        self._spawn_flash(ev.agent_idx, ev.text, FLASH_GOOD if ev.good else FLASH_BAD,
                          stream=False)   # already on the stream, from the engine's buffer
        if ev.hp_after >= 0:
            self._npc_anim["hp"][ev.agent_idx] = ev.hp_after

    def _npc_anim_fast_forward(self):
        """Skip control (any click/keypress): apply everything left instantly and finish."""
        a = self._npc_anim
        if a is None:
            return
        first = True
        for ev in a["events"][a["ei"]:]:
            if ev.kind == self._NPC_EV_MOVE and len(ev.path) > 1:
                a["pos"][ev.agent_idx] = (float(ev.path[-1].col), float(ev.path[-1].row))
            elif ev.kind == self._NPC_EV_OUTCOME and not (first and a["applied"]):
                self._npc_anim_apply_outcome(ev)
            first = False
        a["ei"] = len(a["events"])
        self._npc_anim_finish()

    def _npc_anim_finish(self):
        """Queue drained: drop every display override (live state shows — including corpse
        removal for anything killed this turn) and run the deferred continuation."""
        a = self._npc_anim
        self._npc_anim = None
        cb = a.get("on_done")
        if cb:
            cb()

    def _draw_npc_announcement(self):
        return app_board_render.draw_npc_announcement(self)

    def _on_load_lighting_chosen(self, path: str):
        return app_lighting.on_load_lighting_chosen(self, path)

    def _merge_free_cell(self, col: int, row: int, size: int,
                         reserved: set[tuple[int, int]]):
        """Nearest cell to (col,row) where a size×size agent fits, respecting live
        terrain + already-placed agents (via _can_place) AND the cells already
        claimed by PCs merged in this same pass (`reserved`). Returns an rpg.Cell or
        None if nowhere on the map is free. Prefers the PC's own saved cell."""
        def ok(c) -> bool:
            if not (0 <= c.col < self.bm.grid_cols and 0 <= c.row < self.bm.grid_rows):
                return False
            if not self._can_place(c, size):
                return False
            return all((c.col + dc, c.row + dr) not in reserved
                       for dc in range(size) for dr in range(size))
        home = rpg.Cell(col, row)
        if ok(home):
            return home
        for radius in range(1, max(self.bm.grid_cols, self.bm.grid_rows) + 1):
            for dc in range(-radius, radius + 1):
                for dr in range(-radius, radius + 1):
                    if max(abs(dc), abs(dr)) != radius:
                        continue                     # only the ring at this radius
                    c = rpg.Cell(col + dc, row + dr)
                    if ok(c):
                        return c
        return None

    def _place_in_room(self, size: int, room_cells: list[tuple[int, int]],
                       reserved: set[tuple[int, int]]) -> rpg.Cell | None:
        """Find a size×size placement within the given room's floor cells, respecting
        terrain and reserved cells. Returns an rpg.Cell or None if no space fits."""
        def ok(c) -> bool:
            if not (0 <= c.col < self.bm.grid_cols and 0 <= c.row < self.bm.grid_rows):
                return False
            if not self._can_place(c, size):
                return False
            return all((c.col + dc, c.row + dr) not in reserved
                       for dc in range(size) for dr in range(size))

        # Try cells in the room (shuffled for variety)
        candidates = [rpg.Cell(c, r) for c, r in room_cells]
        random.shuffle(candidates)
        for c in candidates:
            if ok(c):
                return c
        return None

    def _merge_pcs_here(self, pcs, room_cells=None, on_deck: bool = False):
        """Add PC records to the current scene and reload it: each on a free footprint
        in ``room_cells`` when given, else at the nearest free cell to its own. With
        ``on_deck`` and no room, they arrive in reserve. Returns ``(added, dropped,
        skipped)``: a PC already in the scene is named in ``skipped``, not added twice."""
        # Persist current placements, then merge the PCs into that saved doc and reload.
        self._save_agents()
        try:
            doc = self.store.creatures() or {"agents": [], "map_items": []}
        except ValueError:
            doc = {"agents": [], "map_items": []}
        agents = doc.setdefault("agents", [])

        reserved: set[tuple[int, int]] = set()
        added = dropped = 0
        # A PC already in this scene keeps its record (and its tracked HP, slots, …):
        # loading it again used to add a second copy beside the first.
        here = {a.get("name") for a in agents
                if isinstance(a, dict) and not self._saved_is_npc(a)}
        skipped: list[str] = []
        for src in pcs:
            if src.get("name") in here:
                skipped.append(src.get("name"))
                continue
            here.add(src.get("name"))
            pc = dict(src)                           # don't mutate the source file's dict
            pc["faction"] = PC_FACTION               # whole party fights as the blue team
            size = int(pc.get("size", 1))

            # If we have room 0's cells, try to place the PC there; else default placement
            if room_cells:
                spot = self._place_in_room(size, room_cells, reserved)
            else:
                spot = self._merge_free_cell(int(pc.get("col", 0)), int(pc.get("row", 0)),
                                             size, reserved)

            if spot is None:
                dropped += 1                         # no free footprint
                continue
            pc["col"], pc["row"] = spot.col, spot.row
            pc.pop("land_near", None)
            if on_deck and not room_cells:
                pc["on_deck"] = True
            for dc in range(size):
                for dr in range(size):
                    reserved.add((spot.col + dc, spot.row + dr))
            agents.append(pc)
            added += 1
        doc.setdefault("map_items", [])
        self.store.write_creatures(doc)
        self._load_agents()
        return added, dropped, skipped

    def _staging_room(self):
        """The cells of the room a generated dungeon leaves empty for the party, or None
        when this dungeon/map has none; False when switching to it failed. Load PCs,
        D&D Beyond import and New PC all arrive there.

        The showing page's staging room wins. Else, in a dungeon, the entry (floor 0)
        page is switched to first so the party always starts there. Else the
        loaded map's own: ``_staging_cells`` — the exact (post-filter) cells of
        results[0] recorded by Generate Dungeon, from the terrain sidecar.

        We must NOT re-derive "room 0" as min(path_index): build_dungeon filters rooms
        with too few placeable cells before choosing results[0], so raw path_index 0 can
        be a DIFFERENT (e.g. top-left) room than the one actually left empty.
        `_staging_cells` sidesteps that. The path_index heuristic is only a fallback for
        older saves."""
        page = self.dungeon_page if self.dungeon is not None else None
        if page is not None and page.staging_cells:
            return page.staging_cells
        if page is not None:
            entry = self.dungeon.entry_page()
            if entry is not None and entry.id != page.id:
                if not app_dungeon_pages.switch_to_page(self, entry):
                    return False
                if entry.staging_cells:
                    return entry.staging_cells
        cells = getattr(self, "_staging_cells", None)
        if cells:
            return cells
        dict_rooms = [m for m in (getattr(self, "_terrain_rooms", None) or [])
                      if isinstance(m, dict)]
        if dict_rooms:
            return min(dict_rooms, key=lambda m: m.get("path_index", 0)).get("cells")
        return None

    def _on_load_pcs_chosen(self, paths):
        """Load PCs from one or more files ADDITIVELY onto the current scene, so the
        PCs drop onto an already-loaded dungeon without the destructive full-scene
        reload wiping the placed monsters. Mirrors the D&D Beyond import merge:
        persist the current agents, append each PC (relocated off any occupied or
        blocked cell), then reload the combined file. Every PC is forced onto the
        blue team (PC_FACTION) so the whole party fights the red encounter mobs as
        one side, regardless of what faction the party file stored. Each PC keeps its
        loadout from the party file. In a generated dungeon the PCs start in room 0 on
        floor 0 (the generator leaves that room empty for them).

        Each file is either a party ({"agents": [...]}) or one bare PC, the shape a
        campaign's pcs/<name>.json holds."""
        if isinstance(paths, str):
            paths = [paths]
        pcs = []
        for path in paths:
            try:
                with open(path) as f:
                    pc_doc = json.load(f)
            except Exception as e:                   # noqa: BLE001 — surface read/parse errors
                self._flash_status(f"Could not read {os.path.basename(path)}: {e}")
                return
            if isinstance(pc_doc, dict) and isinstance(pc_doc.get("agents"), list):
                pcs.extend(a for a in pc_doc["agents"] if isinstance(a, dict))
            elif isinstance(pc_doc, dict) and "stats" in pc_doc:
                pcs.append(pc_doc)
        if not pcs:
            names = ", ".join(os.path.basename(p) for p in paths)
            self._flash_status(f"No PCs in {names}")
            return
        if self.combat_active:
            self._flash_status("Finish combat before loading PCs")
            return

        room0_cells = self._staging_room()
        if room0_cells is False:
            self._flash_status("Could not switch to floor 0 to place PCs.")
            return

        added, dropped, skipped = self._merge_pcs_here(pcs, room0_cells)

        src = (os.path.basename(paths[0]) if len(paths) == 1
               else f"{len(paths)} files")
        msg = f"Loaded {added} PC(s) from {src}"
        if dropped:
            msg += f" ({dropped} didn't fit)"
        if room0_cells:
            msg += " in room 0"
        if skipped:
            msg += f"; already here: {', '.join(skipped)}"
        self._flash_status(msg)

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
            "items":      list(self.combat.get_agent_items(self.bm, idx)),
            "armor":      list(self.combat.get_agent_armor(self.bm, idx)),
            "meta":       dict(self._agent_meta.get(idx, {})),
            # Spell rendering metadata for this agent, keyed by spell index.
            "spell_meta": {sp_idx: m for (a_idx, sp_idx), m in self._spell_metadata.items()
                           if a_idx == idx},
            # NPC automation flags, so a copied automated NPC pastes ready to self-drive.
            "npc_automated":   self.bm.is_agent_npc_automated(idx),
            "npc_auto_diff":   self.bm.get_agent_npc_automation_difficulty(idx),
            "npc_auto_strat":  self.bm.get_agent_npc_automation_strategy(idx),
            # Team, so a pasted mob fights on its source's side.
            "faction":         self.bm.get_agent_faction(idx),
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
        self.combat.set_agent_items(self.bm, new_idx, clip.get("items", []))
        self.combat.set_agent_armor(self.bm, new_idx, clip["armor"])
        self._sync_item_spells(new_idx)

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

        self.bm.set_agent_faction(new_idx, int(clip.get("faction", 0)))

        # Carry over NPC automation flags so the copy self-drives like its source.
        if clip.get("npc_automated"):
            self.bm.set_agent_npc_automated(new_idx, True)
            self.bm.set_agent_npc_automation_difficulty(new_idx, clip.get("npc_auto_diff", 0))
            strat = clip.get("npc_auto_strat")
            if strat is not None:
                self.bm.set_agent_npc_automation_strategy(new_idx, strat)

        self.sprites.clear()
        self.selected_idx = new_idx
        self._mark_fog_dirty()   # a pasted token may be a party member with its own vision
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
        # A concealed token must not paint its movement range where it is undrawn —
        # the overlay would betray its position.
        if self._concealed_on_screen(idx, pt):
            return
        self._reach_walk   = self.reachable_for(idx, rpg.MovementType.Walk)
        self._reach_fly    = self.reachable_for(idx, rpg.MovementType.Fly)
        self._reach_swim   = self.reachable_for(idx, rpg.MovementType.Swim)
        self._reach_burrow = self.reachable_for(idx, rpg.MovementType.Burrow)

        # Drag validity uses only the selected movement type's reach.
        _reach_by_type = {
            rpg.MovementType.Walk:   self._reach_walk,
            rpg.MovementType.Fly:    self._reach_fly,
            rpg.MovementType.Swim:   self._reach_swim,
            rpg.MovementType.Burrow: self._reach_burrow,
        }
        self._reach_set = {(c.col, c.row)
                           for c in _reach_by_type.get(self.move_type, [])}

    def move_remaining(self, idx: int, move_type) -> int:
        """Feet agent `idx` has left this turn by `move_type`: the placed agent's own budget
        (exhaustion already taken off), seeded by `_reset_movement` and spent by its moves.
        0 for an index with no agent."""
        if not 0 <= idx < len(self.bm.placed_agents):
            return 0
        ag = self.bm.placed_agents[idx]
        return {rpg.MovementType.Walk:   ag.walk_remaining,
                rpg.MovementType.Fly:    ag.fly_remaining,
                rpg.MovementType.Swim:   ag.swim_remaining,
                rpg.MovementType.Burrow: ag.burrow_remaining}.get(move_type, 0)

    def move_budget(self, idx: int, move_type) -> int:
        """Feet agent `idx` may still move by `move_type`, as the overlay and the drag use it.

        In combat the budget is the agent's own `*_remaining` (`move_remaining`); the turn's
        effects (Steady Aim, Dragon Wings) write it there. Outside combat it is the stat speed.
        Dragging a grappled creature costs double per foot (BattleMap::moveAgent), so the
        agent can only reach half as far, and the budget is halved to match enforcement.
        """
        if self.combat_active:
            ft = self.move_remaining(idx, move_type)
        else:
            stats = self.combat.get_agent_stats(self.bm, idx)
            ft = {rpg.MovementType.Walk:   stats.speed_walk,
                  rpg.MovementType.Fly:    stats.speed_fly,
                  rpg.MovementType.Swim:   stats.speed_swim,
                  rpg.MovementType.Burrow: stats.speed_burrow}.get(move_type, 0)
        if any(o.conditions.grappled and o.conditions.grappler_idx == idx
               for j, o in enumerate(self.bm.placed_agents) if j != idx):
            ft //= 2
        return ft

    def reachable_for(self, idx: int, move_type) -> list:
        """The cells agent `idx` can end a `move_type` move on, from `move_budget`.

        The one computation behind the DM's drag overlay (`_update_reach`) and a player's
        Move prompt (D-M5-4), so the two cannot disagree. Passes idx so faction-spared
        difficult terrain (e.g. the agent's own / an ally's Spirit Guardians) does not
        shrink the reach."""
        if not 0 <= idx < len(self.bm.placed_agents):
            return []
        ft = self.move_budget(idx, move_type)
        if ft <= 0:
            return []
        pt = self.bm.placed_agents[idx]
        return self.bm.reachable_cells(pt.origin, pt.size, ft, move_type, idx)

    # Origin feats the GUI can assign (must mirror StatsDialog.ORIGIN_FEATS minus "NONE").
    _ORIGIN_FEATS = app_char_setup.ORIGIN_FEATS

    @staticmethod
    def _set_origin_feat(stats, new_feat: str, char_level: int, second_feat: str = "NONE"):
        return app_char_setup.set_origin_feat(stats, new_feat, char_level, second_feat)

    @staticmethod
    def _set_general_feats(stats, names):
        return app_char_setup.set_general_feats(stats, names)

    @staticmethod
    def _saved_is_npc(t: dict) -> bool:
        """A saved agent's NPC flag: the stats sub-dict's, else the older top-level one."""
        sd = t.get("stats") or {}
        return bool(sd["is_npc"] if "is_npc" in sd else t.get("is_npc", False))

    def _remove_placed_agent(self, idx: int) -> None:
        """Remove a placed agent and re-key the index-keyed metadata past it. Left alone, those
        entries land on whichever agent slides down into the index: a monster's _agent_meta on
        the next PC saved that PC as an NPC."""
        self.bm.remove_agent(idx)
        self._agent_meta = {(i - 1 if i > idx else i): m
                            for i, m in self._agent_meta.items() if i != idx}
        self._spell_metadata = {((a - 1 if a > idx else a), sp): m
                                for (a, sp), m in self._spell_metadata.items() if a != idx}

    def _delete_placed_agent(self, idx: int) -> None:
        """The DM deletes a placed agent out of combat: remove it and drop the selection and
        overlays, which index the old agent list. Weapon data lives in C++ and goes with it."""
        self._remove_placed_agent(idx)
        self._sync_roster_tokens()
        self._mark_fog_dirty()   # roster changed (a party member may be gone)
        self.selected_idx        = -1
        self.drag_idx            = -1
        self._reach_walk         = []
        self._reach_fly          = []
        self._reach_set          = set()
        self._attack_cells_melee = []
        self._attack_cells_rnorm = []
        self._attack_cells_rlong = []

    def _remove_downed_mob(self, idx: int) -> None:
        """Delete a downed mob for good, out of combat. Removal shifts every later index, so
        unlike _clear_mob's tombstone it can't run while the initiative list is live."""
        if not self.combat_active and self._mob_clearable(idx):
            self._delete_placed_agent(idx)

    def _on_stats_ok(self, agent_idx: int, steppers: dict, prof_flags: dict, class_name: str='None', char_level: int=1, npc_data: dict=None, subclass_name: str='NONE', eldritch_invocations: list=None, blessed_strike_name: str='NONE', origin_feat: str='NONE', general_feats: list=None, elemental_adept_types: list=None, hunter_prey_name: str='NONE', defensive_tactics_name: str='NONE', draconic_affinity_type: int=-1, metamagic_options: list=None, irresistible_offense_ability: int=0, class_levels: dict=None, subclasses: dict=None, species: str=None, arcane_shot_options: list=None, species_option: str=None, species_size: str=None, species_spell_ability: int=None, species_skill: str=None, versatile_feat: str='NONE'):
        return app_char_setup.on_stats_ok(self, agent_idx, steppers, prof_flags, class_name, char_level, npc_data, subclass_name, eldritch_invocations, blessed_strike_name, origin_feat, general_feats, elemental_adept_types, hunter_prey_name, defensive_tactics_name, draconic_affinity_type, metamagic_options, irresistible_offense_ability, class_levels, subclasses, species, arcane_shot_options, species_option, species_size, species_spell_ability, species_skill, versatile_feat)

    # ── Weapon callbacks & overlays ───────────────────────────────────────────

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
        # Same leak-guard as _update_reach: no attack-range paint for a concealed token.
        if self._concealed_on_screen(idx, pt):
            return
        melee_cells:  set[tuple[int, int]] = set()
        rnorm_cells:  set[tuple[int, int]] = set()
        rlongx_cells: set[tuple[int, int]] = set()  # long-range-only

        long_limbed = app_attacks.long_limbed_ft(self, idx)   # Bugbear, own turn (D12)
        for w in weapons:
            if w.type == rpg.WeaponType.Melee:
                for c in self.bm.attack_target_cells(
                        pt.origin, pt.size, w.reach_ft + long_limbed):
                    melee_cells.add((c.col, c.row))
                # A Thrown melee weapon (javelin, handaxe, dagger) also reaches everything a
                # ranged weapon would: targeting past its reach hurls it (see app_attacks.attack_is_a_throw),
                # so paint the throw's normal/long bands or the DM can't see where it can land.
                if w.thrown and w.quantity > 0:
                    for c in self.bm.attack_target_cells(
                            pt.origin, pt.size, w.normal_range_ft):
                        rnorm_cells.add((c.col, c.row))
                    for c in self.bm.attack_target_cells(
                            pt.origin, pt.size, w.long_range_ft):
                        if (c.col, c.row) not in rnorm_cells:
                            rlongx_cells.add((c.col, c.row))
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
            # Aura of Alacrity (Paladin Oath of Glory L7): +10 ft Speed while in a Glory paladin's aura
            # (the paladin itself always qualifies). Seed the agent's own budget so real moves get it.
            if self.combat.has_aura_of_alacrity(self.bm, agent_idx):
                walk += 10
            # Gloom Stalker Ambusher's Leap: +10 ft on the first turn of each combat (begin_turn sets it).
            if cond.ambushers_leap:
                walk += 10
            # World Tree Branches of the Tree: a failed save zeroes the target's Speed until end of turn
            # (canAgentMove also blocks the move); reflect it in the budget/overlay so the UI agrees.
            # Forcecage traps the creature in place the same way (it can still act, just not walk out).
            if cond.branches_speed_zeroed or cond.forcecaged:
                walk = fly = swim = burrow = 0
            # Pass base speeds to init_movement; C++ getWalkRemaining() applies exhaustion penalty
            agent.init_movement(walk, fly, swim, burrow)
        # Default to Walk; fall back to first available type if walk speed is 0.
        if self.move_remaining(agent_idx, rpg.MovementType.Walk) > 0:
            self.move_type = rpg.MovementType.Walk
        elif self.move_remaining(agent_idx, rpg.MovementType.Fly) > 0:
            self.move_type = rpg.MovementType.Fly
        elif self.move_remaining(agent_idx, rpg.MovementType.Swim) > 0:
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
        return app_initiative.start_combat(self)

    def _begin_encounter(self):
        return app_initiative.begin_encounter(self)

    def _tracker_rows(self) -> list:
        return app_initiative.tracker_rows(self)

    def _tracker_roll(self, agent_idx: int) -> int:
        return app_initiative.tracker_roll(self, agent_idx)

    def _tracker_start(self):
        return app_initiative.tracker_start(self)

    def _tracker_step(self, delta: int):
        return app_initiative.tracker_step(self, delta)

    @staticmethod
    def _tracker_total_ok(s: str) -> bool:
        return app_initiative.tracker_total_ok(s)

    def _tracker_handle_event(self, event) -> bool:
        return app_initiative.tracker_handle_event(self, event)

    def _tracker_hp_shown(self, agent_idx: int) -> bool:
        return app_initiative.tracker_hp_shown(self, agent_idx)

    def _mirror_tracker(self):
        return app_initiative.mirror_tracker(self)

    def _begin_combat(self):
        return app_initiative.begin_combat(self)

    def _award_encounter_xp(self):
        return app_initiative.award_encounter_xp(self)

    def _end_combat(self, award_xp: bool=True):
        return app_initiative.end_combat(self, award_xp)

    def _on_deck_groups(self):
        return app_initiative.on_deck_groups(self)

    def _deploy_on_deck_idxs(self, idxs, label):
        return app_initiative.deploy_on_deck_idxs(self, idxs, label)

    def _mob_clearable(self, idx: int) -> bool:
        return app_initiative.mob_clearable(self, idx)

    def _clear_mob(self, idx: int):
        return app_initiative.clear_mob(self, idx)

    def _advance_turn(self):
        return app_initiative.advance_turn(self)

    def resolve_pick(self, cell, anchor=None) -> bool:
        """Resolve a click on `cell` against the pick in progress (D-M5-3).

        This is the chain the DM's map click ran inline, moved here unchanged so that a remote
        submit and the DM's click cannot disagree: it computes `hit` itself, from `_agent_at`,
        so a hidden creature is resolved by the engine's perception rules and never by what a
        client could see. Returns True when a branch took the click. On the DM console, False
        falls through to doors, ladders and the drag, exactly as it did before the extraction.
        `anchor` only places a popup (Dispel Magic's picker).
        """
        hit = self._agent_at(cell)
        # Arcane Charge (EK L15): teleport up to 30 ft after Action Surge.
        if self._picking("arcane_charge"):
            self._resolve_arcane_charge(cell)
        # Shadowy Dodge (Gloom Stalker L15): the teleport cell, inside a parked AfterAttack window.
        elif self._picking("shadowy_dodge_cell"):
            self._resolve_shadowy_dodge_cell(cell)
        # Arcane Archer: Masterful Shots (L18) / Indomitable Teleport (L15) cells, in a parked window.
        elif self._picking("masterful_shots_cell"):
            self._resolve_reaction_cell(cell)
        elif self._picking("indomitable_teleport_cell"):
            self._resolve_reaction_cell(cell)
        # Blink Steps (Boon of Dimensional Travel): teleport up to 30 ft after the action.
        elif self._picking("blink_steps"):
            self._resolve_blink_steps(cell)
        elif self._picking("clouds_jaunt"):
            self._resolve_clouds_jaunt(cell)
        # Psychic Teleportation (Soulknife L9): teleport up to 10×die ft.
        elif self._picking("psychic_teleport"):
            self._resolve_psychic_teleport(cell)
        elif self._picking("shadow_step"):
            self._resolve_shadow_step(cell)
        elif self._picking("misty_wanderer"):
            self._resolve_misty_wanderer(cell)
        elif self._picking("steps_of_fey"):
            self._resolve_steps_of_fey(cell)
        elif self._picking("misty_escape"):
            self._resolve_misty_escape(cell)
        elif self._picking("bewitching_misty"):
            self._resolve_bewitching_misty(cell)
        elif self._picking("wild_magic_teleport"):
            self._resolve_wild_magic_teleport(cell)
        elif self._picking("warping_implosion"):
            self._resolve_warping_implosion(cell)
        elif self._picking("shadow_darkness"):
            self._resolve_shadow_darkness(cell)
        elif self._pick_data("elemental_burst") >= 0:
            self._resolve_elemental_burst(cell)
        # Arcane Archer Piercing Shot: the line's direction (AA3).
        elif self._picking("piercing_shot"):
            app_attacks.resolve_piercing_shot(self, cell)
        # Trickery Cleric — Invoke Duplicity placement / movement / multi-dup swap.
        elif self._picking("invoke_duplicity"):
            self._resolve_invoke_duplicity(cell)
        elif self._picking("move_duplicity"):
            app_summons.resolve_move_duplicity(self, cell)
        elif self._picking("swap_duplicity"):
            app_summons.resolve_swap_duplicity(self, cell)
        # Pending attack: resolve against the clicked agent.
        elif self._pick_data("cleave") is not None and hit >= 0:
            self._resolve_cleave(hit)
        elif self._pick_data("sweep") is not None and hit >= 0:
            app_attacks.resolve_sweep(self, hit)
        elif self._pick_data("rally") is not None and hit >= 0:
            self._resolve_rally(hit)
        elif self._pick_data("feint") is not None and hit >= 0:
            self._resolve_feint(hit)
        elif self._picking("mantle") and hit >= 0:
            # Collecting Mantle of Inspiration recipients: each click adds one.
            self._mantle_add_target(hit)
        elif self._picking("beguiling") and hit >= 0:
            # Beguiling Magic: the clicked creature must make a WIS save (then pick Charmed/Frightened).
            features.beguiling_pick_target(self, hit)
        elif self._picking("clairvoyant") and hit >= 0:
            # Clairvoyant Combatant: the clicked enemy makes a WIS save against the GOO warlock.
            self._resolve_clairvoyant_combatant(hit)
        elif self._picking("vow_of_enmity") and hit >= 0:
            # Vow of Enmity: the clicked enemy becomes the Vengeance paladin's sworn foe.
            self._resolve_vow_of_enmity(hit)
        elif self._picking("path_to_the_grave") and hit >= 0:
            # Path to the Grave: the clicked creature is cursed by the Grave cleric.
            self._resolve_path_to_the_grave(hit)
        elif self._picking("move_hunters_mark") and hit >= 0:
            # Hunter's Mark / Hex: the clicked creature takes over the mark.
            self._resolve_move_hunters_mark(hit)
        elif self._picking("inspiring_smite") and hit >= 0:
            # Inspiring Smite: the clicked creature (within 30 ft) gains temp HP.
            self._resolve_inspiring_smite(hit)
        elif self._picking("legendary_target") and hit >= 0:
            app_initiative.resolve_legendary_attack(self, hit)
        elif self._pick_data("legendary_spell"):
            self._resolve_legendary_spell(hit, cell)
        elif self._pick_data("lair"):
            lair.resolve_click(self, hit, cell, anchor)
        elif self._armed(pending.Attack) and hit >= 0:
            features.confirm_friendly_harm(self, hit, lambda h=hit: self._resolve_combat_attack(h))
        elif self._armed(pending.Summon):
            self._resolve_summon(cell)
        elif self._picking("chromatic") and self._armed(pending.Spell):
            # Collecting Chromatic Orb's leap chain: each click adds a hop.
            app_spells.chromatic_add_leap(self, hit)
        elif self._armed(pending.Spell):
            if self._pending_spell_targets_corpse():
                # Raise Dead / Revivify / Animate Dead: click a true-dead body
                # (invisible to _agent_at). Routed through _corpse_at.
                self._resolve_corpse_spell(cell)
            elif self._pending_spell_binds_creature() and hit >= 0:
                # Planar Binding: click a living creature to bind to the caster's
                # team on a failed Charisma save (control transfer, no damage).
                app_spells.resolve_planar_binding(self, hit)
            elif self._pending_spell_opens_doors() and self._door_index_at(cell, anchor) >= 0:
                # Knock targets a doorway cell (no creature). Route through the
                # cell path so the engine reads aoe_col/aoe_row for the door.
                self._resolve_spell_cast_aoe(self._knock_cell(self._door_index_at(cell, anchor), cell))
            elif self._pending_spell_opens_doors() and self.bm.chest_at(cell) >= 0:
                # Knock on a chest: the engine finds it at aoe_col/aoe_row (no door there).
                self._resolve_spell_cast_aoe(cell)
            elif self._pending_spell_dispels_magic():
                # Dispel Magic: open a picker for the ongoing spells at the clicked
                # creature and/or cell (buff vs debuff, or one of several AoEs) — the
                # chosen effect is cast via _cast_dispel_selection.
                features.begin_dispel_pick(self, hit, cell, anchor)
            elif self.pending.is_aoe:
                if self._pending_spell_is_wall():
                    if self.spell_anchor_cell is None:
                        # First click: anchor the wall (must be in range).
                        if app_spells.wall_anchor_in_range(self, cell):
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
                    c_cond = self.combat.get_agent_conditions(self.bm, caster_idx)
                    t_cond = self.combat.get_agent_conditions(self.bm, hit)
                    if c_cond.untouchable != t_cond.untouchable:
                        self._combat_log_add("Untouchable: that creature is out of reach — no spell crosses.")
                    elif not self.bm.has_line_of_sight(caster.origin, caster.size, target.origin, target.size):
                        self._combat_log_add("No line of sight to target!")
                    elif not self.combat.can_perceive_target(self.bm, caster_idx, hit):
                        self._combat_log_add("Cannot perceive target (invisible or in magical darkness)!")
                    elif getattr(c_cond, "forcecage_sealed", False) != getattr(t_cond, "forcecage_sealed", False):
                        # Forcecage Box: a solid wall between the occupant and the outside — no spell crosses.
                        self._combat_log_add("A Forcecage wall blocks that — no spell crosses it.")
                    elif app_spells.is_chromatic_pending(self):
                        # Chromatic Orb: the primary target opens leap-chain selection
                        # instead of casting immediately (confirm friendly harm first).
                        features.confirm_friendly_harm(self, hit, lambda h=hit: app_spells.enter_chromatic_chain(self, h))
                    elif app_spells.pending_spell_is_harm(self):
                        # Faction rule 4: confirm before a harmful spell on a teammate.
                        features.confirm_friendly_harm(self, hit, lambda h=hit: self._resolve_spell_cast(h))
                    else:
                        self._resolve_spell_cast(hit)
                else:
                    self._resolve_spell_cast(hit)
            else:
                # Single-target spell armed, but the click landed on no
                # creature (hit < 0) — previously a totally silent no-op,
                # which read as "targeting is broken." Tell the user so a
                # near-miss on a big creature's footprint is obvious.
                self._combat_log_add(
                    f"No creature on that cell to target — click directly on the "
                    f"target (cell {cell.col},{cell.row}).")
        elif self._armed(pending.Shove) and hit >= 0:
            app_attacks.resolve_shove(self, hit)
        elif self._armed(pending.Unarmed) and hit >= 0:
            app_attacks.resolve_unarmed_option(self, hit)
        elif self._picking("heal_light") and hit >= 0:
            self._resolve_healing_light(hit)
        elif self._picking("lay_on_hands") and hit >= 0:
            self._resolve_lay_on_hands(hit)
        elif self._picking("bastion_of_law") and hit >= 0:
            self._resolve_bastion_of_law(hit)
        elif self._picking("hand_of_healing") and hit >= 0:
            self._resolve_hand_of_healing(hit)
        elif self._pick_data("use_item") >= 0 and hit >= 0:
            self._resolve_use_item(hit)
        elif self._picking("escape_net") and hit >= 0:
            self._resolve_escape_net(hit)
        elif self._picking("seeking_shot") and hit >= 0:
            app_attacks.resolve_seeking_shot(self, hit)
        elif self._picking("grant_inspiration") and hit >= 0:
            self._resolve_grant_inspiration(hit)
        elif self._picking("telekinetic") and hit >= 0:
            self._resolve_telekinetic(hit)
        elif self._picking("flurry_target") and hit >= 0:
            app_attacks.resolve_flurry_target(self, hit)
        elif self._picking("vitality_target") and hit >= 0:
            self._resolve_vitality_target(hit)
        else:
            return False
        self._attack_arm_snapshot = None   # a pick resolved: the arm is no longer undoable
        return True

    def _clear_pending_target_picks(self):
        """Reset EVERY 'awaiting a map click' target-pick flag to its idle value.

        Each of these flags arms a one-shot handler that swallows the next map click (an ally/enemy
        token or a destination cell). If the player opens one of these offers but never completes it
        (no valid click, no Esc), the flag stays armed and leaks into a later turn — where it hijacks
        the next click into the stale handler ("the offer shows up on my next action"). This is the
        single defensive clear called at every turn boundary (turn start, combat start, combat end),
        so no single-feature clear has to be maintained per-site (fixes L36)."""
        # Every click pick (pending.py) but Chromatic Orb's leap chain, which the turn boundary
        # has never reset: it rides on its spell arm, and the spell arm is not reset here either.
        if self.pick is not None and self.pick.kind != "chromatic":
            self.pick = None
        # Their companion state.
        self.pending_beguiling_bard      = -1
        self.move_duplicity_idx          = -1
        self._vitality_option_index      = -1
        self.pending_flurry_atk_idx      = -1
        self.pending_flurry_rider_option = -1
        self.pending_bastion_sp          = 0
        self.pending_duplicity_remaining = 0
        self._duplicity_cd_pending       = False
        self.pending_mantle_targets      = []
        # The summon placement (F-M5e-4). Left armed, the next combatant's click would spawn
        # it with them as the caster, from the previous caster's spell index. The other base
        # modes (attack, spell, shove, unarmed) are not reset here.
        self._disarm(pending.Summon)
        self.cast_setup.fey_reinforcements = False
        self.summon_hover_cell           = None
        self._aoe_aim                    = None   # M5e E-8: an unconfirmed aim
        self._di_wish_free               = False  # F-M5e-12: an unused Greater DI Wish
        self.pending_horde_breaker_targets = []   # rides along with the Attack arm
        self.pending_sudden_strike_targets = []   # rides along with the Attack arm
        self.pending_beasts_strike_targets = []   # rides along with the Attack arm
        self._beasts_strike_paid_now     = False

    # Besides `self.pick` (any armed pick holds the offer back), the arms `_target_pick_armed`
    # reads, with the idle value each rests at. Every field `_clear_pending_target_picks`
    # resets is `pick`, one of these, or in `_TARGET_PICK_COMPANIONS`; tests/test_offer.py
    # holds the lists to that function's body.
    _TARGET_PICK_ARMS = (
        ("pending_beguiling_bard", -1),
        # Not reset at a turn boundary, but armed the same way: the jump overlay.
        ("jump_overlay_active", False),
    )
    # The base modes (`self.pending`) that hold the offer back too. The turn boundary disarms
    # only the Summon; the others are not reset there. An armed Unarmed option never held
    # the offer back, and still does not.
    _TARGET_PICK_MODES = (pending.Summon, pending.Attack, pending.Shove, pending.Spell)
    # Reset beside the arms, but state that rides along with one rather than arming a
    # click itself. Some of them can rest off their idle value after the pick resolves,
    # which is why they must not hold the offer back.
    _TARGET_PICK_COMPANIONS = (
        "move_duplicity_idx", "_vitality_option_index", "pending_flurry_atk_idx",
        "pending_flurry_rider_option", "pending_bastion_sp", "pending_duplicity_remaining",
        "_duplicity_cd_pending", "pending_mantle_targets", "summon_hover_cell",
        "_aoe_aim", "_di_wish_free", "pending_horde_breaker_targets",
        "pending_sudden_strike_targets", "pending_beasts_strike_targets", "_beasts_strike_paid_now",
    )

    def _target_pick_armed(self) -> bool:
        """True while the next map click belongs to a pick in progress (D-M5-2).

        The action offer is held back while one is armed: offering another action mid-pick
        would let it run over the armed one. A wired arm reaches its player as a target
        prompt instead (net/picks.py, M5d); any other is resolved by the DM on the map, or
        cleared by the turn boundary's `_clear_pending_target_picks()`."""
        return (self.pick is not None
                or self._armed(*self._TARGET_PICK_MODES) is not None
                or any(getattr(self, name, idle) != idle for name, idle in self._TARGET_PICK_ARMS))

    # ── The base mode in progress (pending.py), under any click pick.
    def _armed(self, *modes):
        """The armed base mode if it is one of `modes` (pending.Attack, …), else None."""
        return self.pending if isinstance(self.pending, modes) else None

    def _armed_slot(self, mode) -> str:
        """The armed `mode`'s slot ("action" | "bonus"), or "" while none is armed: the value
        its old `pending_*_slot` field rested at."""
        return self.pending.slot if isinstance(self.pending, mode) else ""

    def _disarm(self, *modes):
        """Disarm the base mode if it is one of `modes`. Another mode is left alone."""
        if isinstance(self.pending, modes):
            self.pending = None

    # ── The click pick in progress (pending.py). `kind` names the arm; see its docstring.
    def _picking(self, kind: str) -> bool:
        return self.pick is not None and self.pick.kind == kind

    def _pick_data(self, kind: str):
        """What the arm holds while `kind` is armed, else the idle value its old field rested at."""
        return self.pick.data if self._picking(kind) else pending.idle(kind)

    def _arm_pick(self, kind: str, data=True):
        self.pick = pending.Pick(kind, data)

    def _drop_pick(self, kind: str):
        """Disarm `kind`. A different pick, if one is armed, is left alone."""
        if self._picking(kind):
            self.pick = None

    def _set_pick(self, kind: str, value):
        """Arm `kind` with `value`, or disarm it when `value` is its idle value."""
        if value == pending.idle(kind):
            self._drop_pick(kind)
        else:
            self._arm_pick(kind, value)

    def _reset_turn_economy(self):
        """The action economy and the half-finished action picks, as a turn starts them.
        Shared by the turn start and the autosave restore (M6.4), which lands on a top of
        turn and must not inherit what the abandoned turn had armed."""
        self.action_used           = False
        self.bonus_used            = False
        self.attack_seq.remaining  = 0
        self.attack_seq.slot       = ""
        self.hew_paused_action_seq = None
        self.attack_action_taken   = False   # this turn's action was the Attack action
        self.grapple_bite_used     = False   # a vampire's Bite (grappled/charmed), once a turn
        # Every base mode but a Summon, which the turn boundary's clear disarms.
        self._disarm(pending.Attack, pending.Spell, pending.Shove, pending.Unarmed)
        self._reaction_mover_idx       = -1
        self._attack_arm_snapshot      = None

    def _proceed_to_new_turn(self):
        return app_initiative.proceed_to_new_turn(self)

    def _legendary_action_names_for(self, idx: int, st) -> list:
        return app_initiative.legendary_action_names_for(self, idx, st)

    def _pass_legendary(self):
        return app_initiative.pass_legendary(self)

    def _choose_legendary_action(self, action_name: str):
        return app_initiative.choose_legendary_action(self, action_name)

    def _resolve_legendary_spell(self, hit: int, cell):
        return app_initiative.resolve_legendary_spell(self, hit, cell)

    def _finish_turn_start(self):
        return app_initiative.finish_turn_start(self)

    def _offer_keeper_of_souls_if_pending(self):
        """Grave Cleric Keeper of Souls (L17). The engine flags keeper_of_souls_pending on the cleric when
        an enemy dies within 60 ft, from whatever killed it (attack, spell, aura, ongoing damage). Polled
        once per frame and offered only when nothing else is waiting on an answer, so it never cuts into
        a parked reaction, a rider prompt or an NPC playback. The prompt belongs to the cleric."""
        if not self.combat_active or self._npc_anim is not None or self.prompts.live is not None:
            return
        if self.combat.pending_decision().active:
            return
        agents = self.bm.placed_agents
        for c in range(len(agents)):
            cond = self.combat.get_agent_conditions(self.bm, c)
            if not cond.keeper_of_souls_pending:
                continue
            if not self.combat.can_keeper_of_souls(self.bm, c):
                cond.keeper_of_souls_pending = False
                self.combat.set_agent_conditions(self.bm, c, cond)
                continue
            self._offer_keeper_of_souls(c)
            return

    def _offer_beguiling_twist_if_pending(self):
        """Fey Wanderer Beguiling Twist (L7), the human half. The engine queues (reactor, saver) when a
        save against Charmed/Frightened succeeds and the Ranger who may react is not automated (an
        automated one reacted already). Drained every frame, offered one at a time when nothing else is
        waiting on an answer; an offer whose Reaction or target is gone by then is dropped."""
        if not self.combat_active:
            self._beguiling_twist_queue = []
            self.combat.take_beguiling_twist_offers()
            return
        self._beguiling_twist_queue.extend(self.combat.take_beguiling_twist_offers())
        if not self._beguiling_twist_queue:
            return
        if self._npc_anim is not None or self.prompts.live is not None:
            return
        if self.combat.pending_decision().active:
            return
        while self._beguiling_twist_queue:
            reactor, saver = self._beguiling_twist_queue.pop(0)
            if self.combat.can_beguiling_twist(self.bm, reactor, saver):
                self._offer_beguiling_twist(reactor, saver)
                return

    def _offer_beguiling_twist(self, reactor: int, saver: int):
        agents = self.bm.placed_agents

        def _twist(t, frightened):
            if not self.combat.apply_beguiling_twist(self.bm, reactor, saver, t, frightened):
                self._combat_log_add("Beguiling Twist unavailable.")
            self._flush_combat_log()

        def _skip():
            self._combat_log_add(f"{agents[reactor].name}: Beguiling Twist not used.")

        options = []
        for t in self.combat.beguiling_twist_targets(self.bm, reactor, saver):
            options.append((f"Frighten {agents[t].name}", (lambda tt=t: _twist(tt, True))))
            options.append((f"Charm {agents[t].name}", (lambda tt=t: _twist(tt, False))))
        options.append(("Don't use Beguiling Twist", _skip))
        who = "you" if saver == reactor else agents[saver].name
        self._ask_actor(reactor, "reaction",
                        f"{agents[reactor].name}: {who} shook off a charm/fear — Beguiling Twist?",
                        options, on_cancel=_skip)

    def _offer_keeper_of_souls(self, cleric_idx: int):
        agents = self.bm.placed_agents
        stats = self.combat.get_agent_stats(self.bm, cleric_idx)
        res = stats.resources.get("Keeper of Souls")
        slot = 0 if (res is not None and res.current > 0) else self.combat.keeper_of_souls_slot(stats)
        cost = "" if slot == 0 else f" — spend a level {slot} slot"
        amount = 2 * stats.class_level(rpg.CharacterClass.Cleric)

        def _clear():
            c = self.combat.get_agent_conditions(self.bm, cleric_idx)
            c.keeper_of_souls_pending = False
            self.combat.set_agent_conditions(self.bm, cleric_idx, c)

        def _heal(t):
            if self.combat.use_keeper_of_souls(self.bm, cleric_idx, t, slot) < 0:
                self._combat_log_add("Keeper of Souls unavailable.")
            _clear()
            self._flush_combat_log()
            self._update_attack_overlay()

        def _skip():
            _clear()
            self._combat_log_add(f"{agents[cleric_idx].name}: Keeper of Souls not used.")

        options = []
        for t in self.combat.keeper_of_souls_targets(self.bm, cleric_idx):
            ts = self.combat.get_agent_stats(self.bm, t)
            options.append((f"Heal {agents[t].name} +{amount} ({ts.hp_cur}/{ts.hp_max}){cost}",
                            (lambda tt=t: _heal(tt))))
        options.append(("Don't use Keeper of Souls", _skip))
        self._ask_actor(cleric_idx, "reaction",
                        f"{agents[cleric_idx].name}: an enemy died — Keeper of Souls?",
                        options, on_cancel=_skip)

    def _drive_npc_turn_if_pending(self):
        """Drive ONE automated NPC turn step this frame (NPC_AUTOMATION_PLAN Step 2). Called once per
        frame from the main loop. The C++ engine's run_npc_turn does all the deciding via the combat
        resolution primitives; Python snapshots display state first, then REPLAYS the turn's recorded
        visual events as an animation (see _npc_anim_start) before advancing the turn or relaying a
        parked human reaction/counter window. Never recurses through _finish_turn_start, so a run of
        automated NPCs renders one at a time and stays watchable."""
        if self._npc_anim is not None:
            return   # a playback is still running — its continuation advances the turn
        if self._npc_drive_idx < 0:
            return
        idx = self._npc_drive_idx
        self._npc_drive_idx = -1
        # The agent may have died / been removed between its turn-start and this frame.
        # Tracker mode never automates: the table runs every creature.
        if (not self.combat_active or self.tracker_mode
                or idx < 0 or idx >= len(self.bm.placed_agents)):
            return
        # Fey Wanderer Summon Fey (Ranger R3): a Python-side cast that spends the whole turn.
        fresh, self._npc_fresh_turn = self._npc_fresh_turn, False
        if fresh and self._auto_summon_fey(idx) >= 0:
            self._mark_fog_dirty()
            self._flush_combat_log()
            self._advance_turn()
            return
        snapshot = self._npc_anim_snapshot()   # display state BEFORE the turn mutates the world
        status = self.combat.run_npc_turn(self.bm, idx)
        self._mark_fog_dirty()   # the automated turn moved tokens / opened doors / placed lights
        self._flush_combat_log()
        # Hidden-agent detection after the automated move (mirrors _after_move_committed's
        # check for manual moves — the C++ driver moves without the GUI move path). Without
        # this, a concealed automated NPC could walk into plain sight and stay undrawn
        # forever, since only attacking would ever clear its Hidden condition.
        if idx < len(self.bm.placed_agents) and self.bm.placed_agents[idx].conditions.hidden:
            detection_msg = self.combat.check_hidden_agent_detection(self.bm, idx, True)
            if detection_msg:
                self._combat_log_add(detection_msg)
        events = self.combat.take_npc_visual_events()
        self.events.extend_npc(events)   # M4b B-2: the players' copy of what plays below
        t = self._sim_trace_live()
        if t is not None:
            t.set_decision(self.combat.last_npc_decision())
        self._trace_events(events)
        if status == rpg.FlowStatus.AwaitingDecision and self.combat.pending_decision().active:
            # The NPC attempted an action; a human gets a reaction/counter window. When it closes,
            # re-arm the driver so run_npc_turn resumes next frame (one step per frame, still watchable).
            self._reaction_finish = lambda i=idx: self._resume_npc_turn(i)
            # Play what already happened FIRST — the human must SEE the provoking move/attack
            # before being asked to react to it — then open the parked reaction menu.
            if events:
                self._npc_anim_start(events, snapshot, on_done=self._show_pending_reaction_menu)
            else:
                self._show_pending_reaction_menu()
            return
        if events:
            self._npc_anim_start(events, snapshot, on_done=self._advance_turn)
        else:
            self._advance_turn()

    def _resume_npc_turn(self, idx: int):
        """Re-arm the NPC driver after a parked human reaction window closed mid-automated-turn."""
        self._npc_drive_idx = idx
        self._npc_fresh_turn = False

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


    # ── Target-pick hint (L35) ──────────────────────────────────────────────
    # ~15 target-pick flows (Flurry of Blows, Lay on Hands, Bardic Inspiration, Hand of Healing,
    # Telekinetic Movement, …) armed a pick and set `self.hint = "click a target…"` for direction —
    # but nothing ever rendered `hint`, so those flows left the player with no prompt at all. Rather
    # than add a second parallel renderer, `hint` is now a write-only property that forwards to the
    # ONE prompt mechanism the rest of the GUI already uses: the scrolling combat log. Every existing
    # `self.hint = "…"` site therefore emits a real prompt with no per-site change. (Sites that also
    # called `_combat_log_add` explicitly had that redundant call removed so the prompt shows once.)
    @property
    def hint(self) -> str:
        return getattr(self, "_hint", "")

    @hint.setter
    def hint(self, msg: str):
        self._hint = msg or ""
        if not msg:
            return
        text = str(msg)
        if not text.rstrip().endswith((".", "!", "?", "…", ":")):
            text += "."
        self._combat_log_add(text)

    def _combat_log_add(self, msg: str):
        self.combat_log.insert(0, msg)
        if len(self.combat_log) > 10:
            self.combat_log.pop()
        # The player views' copy: uncapped by the DM panel's 10, oldest first.
        self.combat_log_wire.append(msg)
        # Print to console
        print(msg)
        self._trace_log(msg)
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

    # ── Simulation trace (NPC_LEARNING_PLAN.md Step 1) ──────────────────────
    # Every fight writes SIM_TRACE_FILE beside replay_log.txt: the agents, then per turn the
    # display snapshot, the visual events and the log lines. Playback (Step 2) reads it.
    SIM_TRACE_FILE = "sim_trace.jsonl"

    def _open_sim_trace(self, resumed: bool):
        """Start this fight's trace. ``resumed``: a fight restored from a save, opened
        lazily by the first thing it records, so its first turn may be part-played."""
        if self._sim_trace is not None:
            self._sim_trace.close({"reason": "superseded"})
        agents = self._trace_agents_doc()
        self._sim_trace_nagents = len(self.bm.placed_agents)
        names = self.bm.placed_agents
        self._sim_trace = sim_trace.TraceWriter(
            self.SIM_TRACE_FILE, map_path=getattr(self, "_map_path", "") or "", agents=agents,
            seed=self.combat_seed, npc_policy="gui", pc_mode="Human",
            initiative=[(e.agent_idx, names[e.agent_idx].name, e.total)
                        for e in self.initiative_order
                        if 0 <= e.agent_idx < len(names)],
            resumed=resumed, extra={"tracker_mode": bool(self.tracker_mode),
                                    # Playback rebuilds the board from the PNG; a page
                                    # calibrated by hand needs its grid back (Step 2).
                                    "manual_grid": self._manual_grid})

    def _trace_agents_doc(self):
        """The agents file's document in the raw index basis the events are keyed by
        (summons and tombstones kept), or None if it could not be built."""
        tmp = self.SIM_TRACE_FILE + ".agents.tmp"
        try:
            self._save_agents(tmp, raw=True)
            with open(tmp) as f:
                doc = json.load(f)
            os.remove(tmp)
            return doc
        except Exception as e:   # the trace is diagnostic; never let it stop a fight
            print(f"[SIM TRACE] agents not recorded: {e}")
            return None

    def _sim_trace_live(self):
        """The open writer, opening one for a fight restored from a save; else None."""
        if not self.combat_active:
            return None
        if self._sim_trace is None:
            self._open_sim_trace(resumed=True)
        return self._sim_trace if self._sim_trace.active else None

    def _trace_begin_turn(self, idx: int):
        t = self._sim_trace_live()
        if t is None:
            return
        automated = (not self.tracker_mode) and self.bm.is_agent_npc_automated(idx)
        spawned = []
        n = len(self.bm.placed_agents)
        if n > self._sim_trace_nagents:   # summons / reinforcements since the last record
            doc = self._trace_agents_doc()
            if doc is not None:
                spawned = doc["agents"][self._sim_trace_nagents:]
            self._sim_trace_nagents = n
        t.begin_turn(round_num=self.round_num, actor=idx,
                     actor_name=self.bm.placed_agents[idx].name,
                     driver=sim_trace.DRIVER_NPC if automated else sim_trace.DRIVER_HUMAN,
                     snapshot=self._npc_anim_snapshot(), spawned=spawned)

    def _trace_events(self, events):
        t = self._sim_trace_live()
        if t is not None and events:
            t.add_events(events)

    def _trace_log(self, msg: str):
        t = self._sim_trace_live()
        if t is not None:
            t.add_log(msg)

    def _close_sim_trace(self, reason: str):
        """Footer: who is still standing, by faction. ``winner`` is the one faction left
        with living creatures in play, else None."""
        if self._sim_trace is None:
            return
        alive = {}
        for pt in self.bm.placed_agents:
            if pt.removed_from_play or pt.conditions.dead:
                continue
            key = str(pt.faction)
            alive[key] = alive.get(key, 0) + 1
        self._sim_trace.close({"reason": reason, "rounds": self.round_num,
                               "alive_by_faction": alive,
                               "winner": next(iter(alive)) if len(alive) == 1 else None})
        self._sim_trace = None

    # FLAG: Move to C++
    def _drop_weapon(self, slot_idx: int):
        return app_char_setup.drop_weapon(self, slot_idx)


    def _pickup_item(self, item, agent_idx: int):
        return app_char_setup.pickup_item(self, item, agent_idx)


    def _delete_item(self, item):
        """Remove an item from the map entirely (a DM-placed one from the design too)."""
        if item.pid >= 0:
            items_play.remove_design_item(self, item.pid)
        else:
            self.bm.remove_item(item.id)
        self._combat_log_add(f"Removed {item.name or 'item'} from the map.")

    # ── Doors ─────────────────────────────────────────────────────────────────
    def _cell_adjacent_to_agent(self, agent, cell) -> bool:
        """True if `cell` is within 5 ft (Chebyshev 1) of the agent's footprint."""
        dc = max(agent.origin.col - cell.col,
                 cell.col - (agent.origin.col + agent.size - 1), 0)
        dr = max(agent.origin.row - cell.row,
                 cell.row - (agent.origin.row + agent.size - 1), 0)
        return max(dc, dr) <= 1


    def _use_ladder(self, ladder_idx: int, actor_idx: int, party: bool = False):
        """Resolve a ladder's global target to a page + local cell and switch to it,
        carrying the acting creature (``party``: the whole party, as a staircase's
        "Party:" row does). No-ops with a flash if the dungeon isn't loaded or the
        target lands on no page. Returns True when the party moved."""
        if ladder_idx < 0 or ladder_idx >= len(self._ladders):
            return
        if self.dungeon is None:
            self._flash_status("Ladders need a dungeon manifest (open a .dungeon.json).")
            return
        X, Y, Z = self._ladders[ladder_idx]["target"]
        page = self.dungeon.page_at_global(X, Y, Z)
        if page is None:
            self._flash_status("The ladder leads nowhere (no map on that floor).")
            return
        local = page.global_to_local(X, Y, Z)
        if local is None:
            self._flash_status("The ladder's exit is off the target map.")
            return
        if party:
            carry = app_dungeon_pages.party_carry(self, actor_idx) or None
        else:
            carry = [actor_idx] if actor_idx is not None and actor_idx >= 0 else None
        verb = self._ladder_verb(Z)
        if app_dungeon_pages.switch_to_page(self, page, drop_cell=local, carry=carry):
            who = f"The party {verb.lower()}ed" if party else f"{verb}ed"
            self._flash_status(f"{who} the ladder to floor {Z}: {page.id}")
            return True
        return False

    def _ladder_verb(self, target_z) -> str:
        """"Ascend" or "Descend": the ladder's target floor against this page's."""
        here = self.dungeon_page.z if self.dungeon_page is not None else 0
        return "Descend" if int(target_z) < here else "Ascend"

    # ── Staircases (manifest portals; plans/STAIRCASES_PLAN.md) ──────────────
    def _staircase_ends_here(self):
        """Every ``(staircase, end_index)`` with an end on the active page; [] without a
        dungeon. Unfinished staircases are included (they draw, but cannot be used)."""
        if self.dungeon is None or self.dungeon_page is None:
            return []
        return self.dungeon.staircase_ends_on(self.dungeon_page.id)

    def _staircases_at(self, cell):
        return app_dungeon_pages.staircases_at(self, cell)

    def _staircase_option_label(self, st, end_index) -> str | None:
        return app_dungeon_pages.staircase_option_label(self, st, end_index)


    def _use_staircase(self, sid: int, end_index: int, actor_idx: int, party: bool = False):
        return app_dungeon_pages.use_staircase(self, sid, end_index, actor_idx, party)


    def _staircase_summary(self, st) -> str:
        return app_dungeon_pages.staircase_summary(self, st)

    def _staircase_goto(self, sid: int, end_index: int) -> bool:
        return app_dungeon_pages.staircase_goto(self, sid, end_index)

    def _staircase_set_text(self, sid: int, field: str, text: str) -> bool:
        return app_dungeon_pages.staircase_set_text(self, sid, field, text)

    def _staircase_prompt(self, sid: int, field: str):
        return app_dungeon_pages.staircase_prompt(self, sid, field)

    def _staircase_delete(self, sid: int) -> bool:
        return app_dungeon_pages.staircase_delete(self, sid)

    @staticmethod
    def _ladder_key(lad) -> tuple:
        """Hashable identity of a ladder record: its cells and its global target."""
        return (tuple((int(c[0]), int(c[1])) for c in lad["cells"]),
                tuple(int(v) for v in lad["target"]))

    def _page_png_path(self, page: MapPage) -> str:
        return app_dungeon_pages.page_png_path(self, page)

    def _page_terrain_path(self, page: MapPage) -> str:
        return app_dungeon_pages.page_terrain_path(self, page)

    def _pair_ladders(self, before):
        """Give every ladder the terrain editor added this session a return ladder on the
        page it leads to, and take the return ladder away with any it removed.

        ``before`` is the list of _ladder_key()s at editor open. A ladder's other end lives
        in another page's _terrain.json (a different floor, never the page on screen), so
        it is edited on disk; the page reads it the next time it is switched to. The return
        ladder stands on the landing cell and targets this ladder's own global cell. A
        landing cell that already holds a ladder is left alone, and a removal only deletes
        a return ladder that still points back here. Without a dungeon there is no other
        page, so nothing is paired."""
        if self.dungeon is None or self.dungeon_page is None:
            return
        here = self.dungeon_page
        after = [self._ladder_key(lad) for lad in self._ladders]
        added = [k for k in after if k not in before]
        removed = [k for k in before if k not in after]
        notes = []
        for key, adding in [(k, True) for k in added] + [(k, False) for k in removed]:
            cells, target = key
            page = self.dungeon.page_at_global(*target)
            local = page.global_to_local(*target) if page is not None else None
            if local is None or page.id == here.id:
                if adding:
                    notes.append(f"no map at {list(target)}; ladder is one-way")
                continue
            back = list(here.local_to_global(*cells[0]))
            try:
                doc = self.store.terrain(page) or {"regions": [], "walls_enabled": True}
            except ValueError as e:
                notes.append(f"could not read '{page.id}' terrain: {e}")
                continue
            ladders = doc.setdefault("ladders", [])
            on_landing = [i for i, lad in enumerate(ladders)
                          if any(int(c[0]) == local[0] and int(c[1]) == local[1]
                                 for c in lad.get("cells", []))]
            if adding:
                if on_landing:
                    notes.append(f"'{page.id}' already has a ladder at {list(local)}")
                    continue
                ladders.append({"cells": [list(local)], "target": back})
                notes.append(f"return ladder on '{page.id}' at {list(local)}")
            else:
                mine = [i for i in on_landing
                        if [int(v) for v in ladders[i].get("target", [])] == back]
                if not mine:
                    continue
                for i in reversed(mine):
                    ladders.pop(i)
                notes.append(f"removed return ladder on '{page.id}'")
            try:
                self.store.write_terrain(doc, page)
            except OSError as e:
                notes.append(f"could not write '{page.id}' terrain: {e}")
        if notes:
            self._flash_status("Ladders: " + "; ".join(notes))

    def _door_by_id(self, door_id: int):
        """The rpg.Door with ``id == door_id`` on the active map, or None."""
        for d in self.bm.doors:
            if d.id == door_id:
                return d
        return None

    def _door_link_at(self, door):
        """The global ``[X, Y, Z]`` cross-map target for ``door`` (an rpg.Door), or None
        for an ordinary in-map door. Looked up by the door's cell footprint."""
        if not door.cells:
            # An edge door links only on the page's outer line, derived from where it is.
            return border_door_target(self.bm, door)
        return self._door_links.get(door_link_key(door.cells))

    # Extra screen px around an edge door's drawn slab that still counts as a click on it,
    # so a thin bar at low zoom stays easy to hit.
    EDGE_DOOR_PICK_PAD = 4

    def _door_visible(self, door) -> bool:
        """True when ``door`` is drawn: no fog, or the party has seen one of its cells
        (either side of an edge door). Same rule as _draw_doors."""
        return not self._fog_conceals() or self._any_explored(
            [(c.col, c.row) for c in (door.cells or door_touch_cells(door))])

    def _edge_door_at_pos(self, pos):
        """Index into bm.doors of the visible edge door whose drawn slab is under screen
        ``pos``, or -1. The slab is what the DM sees, so it is what a click picks."""
        cpx = int(self.bm.cell_pixel_size * self.map_scale)
        pad = self.EDGE_DOOR_PICK_PAD
        for i, door in enumerate(self.bm.doors):
            if not door.edges or not self._door_visible(door):
                continue
            x, y, w, h = edge_door_rect(door, self._cell_to_screen, cpx,
                                        grid=(self.bm.grid_cols, self.bm.grid_rows))
            if pygame.Rect(x - pad, y - pad, w + 2 * pad, h + 2 * pad).collidepoint(pos):
                return i
        return -1

    def _knock_cell(self, di, cell):
        """The cell to aim Knock at so the engine finds door ``di``: ``cell`` for a cell
        door, else a cell beside the edge door from which it is the first one found."""
        door = self.bm.doors[di]
        if not door.edges:
            return cell
        for c in [cell] + door_touch_cells(door):
            if self._door_index_at(c) == di:
                return c
        return cell

    def _door_index_at(self, cell, pos=None):
        """Index into bm.doors for the door a click at screen ``pos`` in ``cell`` means:
        a door on the cell, else the edge door whose drawn slab is under the click.
        -1 when there is none.

        With no ``pos`` (a remote pick), the first edge door on the cell's east, south,
        west or north side, which is the door the engine's Knock finds from that cell."""
        di = self.bm.door_at(cell)
        if di >= 0:
            return di
        c, r = cell.col, cell.row
        if pos is None:
            for ec, er, side in ((c, r, rpg.EdgeSide.East), (c, r, rpg.EdgeSide.South),
                                 (c - 1, r, rpg.EdgeSide.East), (c, r - 1, rpg.EdgeSide.South)):
                di = self.bm.door_at_edge(rpg.Cell(ec, er), side)
                if di >= 0:
                    return di
            return -1
        return self._edge_door_at_pos(pos)

    def _use_door_link(self, door_id: int, actor_idx: int, party: bool = False):
        """Step through a linked door to the abutting page, carrying the acting (or
        selected) creature (``party``: the whole party, as a ladder's "Party:" row
        does), landing just inside the matching door there. Mirrors _use_ladder:
        resolve the global target to a page + local cell via the dungeon manifest and
        switch. No-ops with a flash if the dungeon isn't loaded or the target lands on no
        page. Returns True when the crossing happened."""
        if self.dungeon is None:
            self._flash_status("Door links need a dungeon manifest (open a .dungeon.json).")
            return
        door = self._door_by_id(door_id)
        if door is None:
            return
        link = self._door_link_at(door)
        if link is None:
            return
        X, Y, Z = link
        page = self.dungeon.page_at_global(X, Y, Z)
        if page is None:
            self._flash_status("The door leads nowhere (no map on that floor).")
            return
        local = page.global_to_local(X, Y, Z)
        if local is None:
            self._flash_status("The door's exit is off the target map.")
            return
        if party:
            carry = app_dungeon_pages.party_carry(self, actor_idx) or None
        else:
            carry = [actor_idx] if actor_idx is not None and actor_idx >= 0 else None
        if app_dungeon_pages.switch_to_page(self, page, drop_cell=local, carry=carry):
            who = "The party stepped" if party else "Stepped"
            self._flash_status(f"{who} through to {page.id} (floor {Z}).")
            return True
        return False

    def _send_pages(self) -> list:
        return app_dungeon_pages.send_pages(self)

    def _send_to_page(self, idx: int, page) -> bool:
        return app_dungeon_pages.send_to_page(self, idx, page)

    def _after_door_change(self):
        """Refresh movement/attack overlays after a door's open state (and thus LOS and
        passability) changed."""
        self._mark_fog_dirty()   # a door opening/closing changes party LOS through it
        if self.selected_idx >= 0:
            self._update_reach()
            self._update_attack_overlay()

    def _door_open(self, door_id: int):
        if self.bm.open_door(door_id):
            self._combat_log_add("The door opens.")
        else:
            self._combat_log_add("The door is locked.")
        self._after_door_change()

    def _door_close(self, door_id: int):
        self.bm.close_door(door_id)
        self._combat_log_add("The door closes.")
        self._after_door_change()

    def _door_set_hidden(self, door_id: int, hidden: bool):
        """DM: reveal a secret door (an ordinary closed door from now on) or hide it
        again. Play state: the map's design is unchanged, and a reset hides it again."""
        if not self.bm.set_door_hidden(door_id, hidden):
            return
        self._combat_log_add("The secret door is hidden again." if hidden
                             else "A secret door is revealed!")
        self._after_door_change()
        self._build_overlay()

    def _door_set_secret(self, door_id: int, secret: bool):
        """DM: make a door secret (hidden, a wall to everyone) or ordinary. Design: it is
        saved into the map, as the terrain editor's Secret toggle is."""
        if not self.bm.set_door_secret(door_id, secret):
            self._flash_status("A broken door can't be made secret.")
            return
        self._combat_log_add("The door is now a secret door (hidden)." if secret
                             else "The door is now an ordinary door.")
        self._after_door_change()
        self._build_overlay()
        self._save_terrain()

    def _door_pick_lock(self, actor_idx: int, door_id: int):
        if actor_idx < 0:
            self._combat_log_add("No creature selected to pick the lock.")
            return
        if self.combat_active and self.action_used:
            self._combat_log_add("Action already used this turn — cannot pick the lock.")
            return
        res = self.combat.attempt_pick_lock(self.bm, actor_idx, door_id)
        if not res.valid:
            self._combat_log_add("Cannot pick this lock.")
            return
        self._combat_log_add(res.log_message)
        if self.combat_active:
            self.action_used = True
        self._after_door_change()
        if not res.success and res.roll > 0:
            self._offer_past_life(actor_idx, lambda: self._door_check_retry(
                self.combat.attempt_pick_lock(self.bm, actor_idx, door_id)))

    def _door_check_retry(self, res):
        """A door check re-evaluated with Knowledge from a Past Life (D10): report it."""
        self._combat_log_add(res.log_message)
        self._after_door_change()

    def _offer_past_life(self, idx: int, retry, decline=None) -> bool:
        return app_attacks.offer_past_life(self, idx, retry, decline)

    def _door_break_down(self, actor_idx: int, door_id: int):
        """Force a door with a Strength (Athletics) check (an action). On a success the
        door is smashed off its frame (permanently open); on a failure the action is
        still spent. Mirrors _door_pick_lock's action-economy handling."""
        if actor_idx < 0:
            self._combat_log_add("No creature selected to force the door.")
            return
        if self.combat_active and self.action_used:
            self._combat_log_add("Action already used this turn — cannot force the door.")
            return
        res = self.combat.attempt_break_door(self.bm, actor_idx, door_id)
        if not res.valid:
            self._combat_log_add("Cannot force this door.")
            return
        self._combat_log_add(res.log_message)
        # A no-op attempt (roll made) still spends the action; an invalid one does not.
        if self.combat_active and (res.success or res.roll > 0):
            self.action_used = True
        self._after_door_change()
        if not res.success and res.roll > 0:
            self._offer_past_life(actor_idx, lambda: self._door_check_retry(
                self.combat.attempt_break_door(self.bm, actor_idx, door_id)))

    def _pending_spell_opens_doors(self) -> bool:
        return app_spells.pending_spell_opens_doors(self)

    def _pending_spell_dispels_magic(self) -> bool:
        return app_spells.pending_spell_dispels_magic(self)


    def _cast_dispel_selection(self, candidate, hit, cell):
        return app_spells.cast_dispel_selection(self, candidate, hit, cell)

    def _begin_item_drag(self, item):
        """Grab a dropped weapon for dragging. The release decides move vs. pickup."""
        self.drag_item_id     = item.id
        self.drag_item        = item
        self.drag_item_origin = rpg.Cell(item.cell.col, item.cell.row)
        self.drag_item_cell   = rpg.Cell(item.cell.col, item.cell.row)

    def _drop_dragged_item(self, cell):
        """Relocate the dragged weapon to `cell` (remove + re-place, keeping its sprite)."""
        item = self.drag_item
        if item is None or cell is None:
            return
        name = item.name or "item"
        if self.bm.chest_at(cell) >= 0:
            # Onto a chest: a DM-placed item becomes one of its contents.
            cid = self.bm.chests[self.bm.chest_at(cell)].id
            if item.pid >= 0 and items_play.floor_item_into_chest(self, item.pid, cid):
                self._combat_log_add(f"Put {name} in Chest {cid}.")
            else:
                self._flash_status("Only a placed item goes into a chest; Edit the chest to add one.")
            return
        if item.kind == rpg.MapItemKind.Weapon and not item.sprite_path:
            item.sprite_path = self.weapon_name_to_dict.get(item.weapon.name, {}).get("sprite_path", "")
        self.bm.remove_item(item.id)
        item.cell = cell
        self.bm.place_map_item(item)
        if item.pid >= 0:
            items_play.move_design_item(self, item.pid, cell)
        self._combat_log_add(f"Moved {name} to ({cell.col}, {cell.row}).")

    def _clear_item_drag(self):
        self.drag_item_id     = -1
        self.drag_item        = None
        self.drag_item_origin = None
        self.drag_item_cell   = None

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
                    rpg.VisibilityLevel.HeavilyObscured: "Heavily Obscured (fog)",
                    rpg.VisibilityLevel.Blocked: "Blocked",
                    rpg.VisibilityLevel.Sunlight: "Sunlight"
                }.get(vis_level, "Unknown")
                tgt_team = faction_name(self.bm.get_agent_faction(target_idx))
                visibility_info += f"  • {agent.name} ({vis_name}, {tgt_team} team)\n"

        if visible_count == 0:
            visibility_info += "  (no visible targets)"

        self._combat_log_add(visibility_info)

    # FLAG: Move to C++
    def _continue_attack_sequence_after_rider(self, atk_idx: int):
        return app_attacks.continue_attack_sequence_after_rider(self, atk_idx)

    @staticmethod
    def _weapon_usable(w) -> bool:
        return app_attacks.weapon_usable(w)

    def _start_attack(self, slot: str):
        return app_attacks.start_attack(self, slot)

    def _damage_breakdown_str(self, result) -> str:
        return app_attacks.damage_breakdown_str(self, result)

    def _start_extra_attack(self, weapon_idx=0, offhand=False, resource=None, label='Extra attack', slot='bonus'):
        return app_attacks.start_extra_attack(self, weapon_idx, offhand, resource, label, slot)

    def _offhand_bonus_available(self, idx: int) -> bool:
        return app_attacks.offhand_bonus_available(self, idx)

    def _nick_offhand_idx(self, idx: int) -> int:
        return app_attacks.nick_offhand_idx(self, idx)

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

    def _pending_spell_targets_corpse(self) -> bool:
        return app_spells.pending_spell_targets_corpse(self)

    def _pending_spell_binds_creature(self) -> bool:
        return app_spells.pending_spell_binds_creature(self)


    def _resolve_combat_attack(self, target_idx: int):
        return app_attacks.resolve_combat_attack(self, target_idx)

    def _apply_chaos_staff_rider(self, atk_idx: int, target_idx: int, weapon_idx: int, tgt_name: str):
        return app_attacks.apply_chaos_staff_rider(self, atk_idx, target_idx, weapon_idx, tgt_name)

    def _finish_attack(self):
        return app_attacks.finish_attack(self)

    def _cleave_valid_targets(self, atk: int, first: int, weapon_idx: int) -> list:
        return app_attacks.cleave_valid_targets(self, atk, first, weapon_idx)


    def _cancel_cleave(self):
        return app_attacks.cancel_cleave(self)

    def _resolve_cleave(self, second_target: int):
        return app_attacks.resolve_cleave(self, second_target)

    def _start_gwm_hew(self, atk_idx: int):
        return app_attacks.start_gwm_hew(self, atk_idx)


    def _eligible_guided_clerics(self, atk_idx):
        return app_attacks.eligible_guided_clerics(self, atk_idx)


    def _eligible_restore_balance_clockworks(self, atk_idx, result):
        return app_attacks.eligible_restore_balance_clockworks(self, atk_idx, result)


    def _execute_flurry(self, atk_idx, rider_option):
        return app_attacks.execute_flurry(self, atk_idx, rider_option)

    def _quivering_palm_option(self, atk_idx, target_idx, tgt_name, continuation):
        return app_attacks.quivering_palm_option(self, atk_idx, target_idx, tgt_name, continuation)


    def _can_homing_strike(self, atk_idx, action):
        """Soulknife L9+ holding a Psionic Energy Die, whose missed attack used a Psychic Blade."""
        if not (0 <= atk_idx < len(self.bm.placed_agents)):
            return False
        stats = self.combat.get_agent_stats(self.bm, atk_idx)
        if (stats.character_class != rpg.CharacterClass.Rogue or
                stats.rogue_subclass != rpg.RogueSubclass.Soulknife or stats.char_level < 9):
            return False
        ped = stats.get_resource("Psionic Energy")
        if not (ped and ped.current > 0):
            return False
        weapons = self.combat.get_agent_weapons(self.bm, atk_idx)
        wi = action.weapon_idx
        return 0 <= wi < len(weapons) and weapons[wi].psychic_blade

    def _has_psychic_blade(self, atk_idx):
        if not (0 <= atk_idx < len(self.bm.placed_agents)):
            return False
        return any(w.psychic_blade for w in self.combat.get_agent_weapons(self.bm, atk_idx))


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
        if self.bm.is_agent_on_deck(target_idx):   # On Deck reserves take no reactions until deployed
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


    def _create_monk_unarmed_weapon(self):
        return app_char_setup.create_monk_unarmed_weapon(self)

    def _create_alter_self_claws_weapon(self):
        return app_char_setup.create_alter_self_claws_weapon(self)

    def _bond_pact_weapon(self, weapons):
        return app_char_setup.bond_pact_weapon(self, weapons)

    def _apply_psychic_blades(self, stats, weapons):
        return app_char_setup.apply_psychic_blades(self, stats, weapons)


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


    def _start_vampiric_bite(self, empower: int):
        return app_attacks.start_vampiric_bite(self, empower)

    def _start_unarmed_punch(self, unarmed=None):
        return app_attacks.start_unarmed_punch(self, unarmed)

    def _start_unarmed_grapple(self):
        return app_attacks.start_unarmed_grapple(self)

    def _start_unarmed_push(self):
        return app_attacks.start_unarmed_push(self)

    def _resolve_healing_light(self, target_idx: int):
        """Celestial Warlock Healing Light: spend max(1, CHA mod) d6 on the clicked target."""
        self._drop_pick("heal_light")
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


    def _resolve_rally(self, target_idx: int):
        """Resolve a pending Rally against the clicked creature (within 30 ft)."""
        fighter = self._pick_data("rally")
        agents = self.bm.placed_agents
        if fighter is None or not (0 <= target_idx < len(agents)):
            self._drop_pick("rally")
            return
        fo, to = agents[fighter].origin, agents[target_idx].origin
        if max(abs(fo.col - to.col), abs(fo.row - to.row)) > 6:   # 30 ft = 6 cells (Chebyshev)
            # Refused like an empty square: the pick stays armed, and the player is asked again.
            self._combat_log_add("Rally: the target must be within 30 ft — pick a closer creature.")
            self._flush_combat_log()
            return
        self._drop_pick("rally")
        amount = self.combat.apply_rally(self.bm, fighter, target_idx)
        if amount > 0:
            self.bonus_used = True
        self._flush_combat_log()
        self._update_attack_overlay()

    def _resolve_feint(self, target_idx: int):
        """Resolve a pending Feinting Attack against the clicked creature (within 5 ft)."""
        fighter = self._pick_data("feint")
        agents = self.bm.placed_agents
        if fighter is None or not (0 <= target_idx < len(agents)):
            self._drop_pick("feint")
            return
        # Refused like an empty square: the pick stays armed, and the player is asked again.
        if target_idx == fighter:
            self._combat_log_add("Feinting Attack: pick another creature, not yourself.")
            self._flush_combat_log()
            return
        fo, to = agents[fighter].origin, agents[target_idx].origin
        if max(abs(fo.col - to.col), abs(fo.row - to.row)) > 1:    # 5 ft = adjacent
            self._combat_log_add("Feinting Attack: the target must be within 5 ft — pick an adjacent creature.")
            self._flush_combat_log()
            return
        self._drop_pick("feint")
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

    def _fey_reinforcements_level(self, agent_idx: int) -> bool:
        """Fey Wanderer Ranger L11+: Summon Fey may skip Concentration (Fey Reinforcements)."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return False
        st = self.combat.get_agent_stats(self.bm, agent_idx)
        return (st.ranger_subclass == rpg.RangerSubclass.FeyWanderer
                and st.class_level(rpg.CharacterClass.Ranger) >= 11)

    def _start_fey_reinforcements(self, agent_idx: int):
        """Fey Wanderer L11 Fey Reinforcements: cast Summon Fey once without a spell slot (at its
        base level, 3rd). The cast runs through the normal summon flow; _resolve_summon spends
        the "Fey Reinforcements" use when the spirit is placed."""
        spells = self.combat.get_agent_spells(self.bm, agent_idx)
        si = next((i for i, sp in enumerate(spells) if sp.name == "Summon Fey"), -1)
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        fr = stats.get_resource("Fey Reinforcements")
        if si < 0 or not (fr and fr.current > 0):
            self._combat_log_add(f"{self.bm.placed_agents[agent_idx].name}: no Fey Reinforcements use.")
            return
        self.cast_setup.fey_reinforcements = True
        self._activate_spell("action", si, spells[si].level, agent_idx, spells, stats, free_cast=True)

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

    def _use_psychic_veil(self, agent_idx: int):
        """Soulknife L13 Psychic Veil: Magic action → Invisible. Free use first, then a Psionic die."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return
        if self.combat.activate_psychic_veil(self.bm, agent_idx):
            self._flush_combat_log()
            self.action_used = True
        else:
            self._combat_log_add(
                f"{self.bm.placed_agents[agent_idx].name}: cannot use Psychic Veil (no use or dice).")

    def _resolve_psychic_teleport(self, cell):
        """Soulknife L9 Psychic Teleportation: roll a Psionic die, teleport up to 10×roll ft to the
        clicked cell. Click your own cell to cancel. Engine validates range/legality + spends the die."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("psychic_teleport")
            return
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self._drop_pick("psychic_teleport")
            self._combat_log_add("Psychic Teleportation cancelled.")
            return
        if self.combat.psychic_teleportation(self.bm, idx, cell.col, cell.row):
            self._drop_pick("psychic_teleport")
            self._flush_combat_log()
            self.bonus_used = True
            self._reset_movement(idx)
            self._update_reach()
            self._update_attack_overlay()
        else:
            # Out of (rolled) range or illegal cell — keep the prompt up so the player can retry closer.
            self._flush_combat_log()
            self._combat_log_add("Psychic Teleportation: out of range or blocked — pick a closer cell.")

    def _resolve_shadow_step(self, cell):
        """Warrior of Shadow L6+ Shadow Step: teleport up to 30 ft to the clicked cell.
        L6 requires dim/dark light; L11+ works from any light. Click your own cell to cancel."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("shadow_step")
            return
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self._drop_pick("shadow_step")
            self._combat_log_add("Shadow Step cancelled.")
            return
        if self.combat.shadow_step_teleport(self.bm, idx, cell.col, cell.row):
            self._drop_pick("shadow_step")
            self._flush_combat_log()
            self.bonus_used = True
            self._reset_movement(idx)
            self._update_reach()
            self._update_attack_overlay()
        else:
            # Out of range, blocked, or light-level gate failed — keep the prompt up for retry.
            self._flush_combat_log()
            self._combat_log_add("Shadow Step: out of range, blocked, or light requirement not met — pick a closer cell.")

    def _resolve_misty_wanderer(self, cell):
        """Fey Wanderer L15 Misty Wanderer: a slotless Bonus-Action Misty Step (30 ft). With a
        willing creature within 5 ft, ask who comes along; the engine lands them in the first free
        space beside the destination. Click your own cell to cancel."""
        idx = self._current_agent_idx()
        self._drop_pick("misty_wanderer")
        if idx < 0:
            return
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self._combat_log_add("Misty Wanderer cancelled.")
            return

        def _go(ally=-1):
            if self.combat.misty_wanderer(self.bm, idx, cell.col, cell.row, ally, -1, -1):
                self._flush_combat_log()
                self.bonus_used = True
                self._reset_movement(idx)
                self._update_reach()
                self._update_attack_overlay()
                self.sprites.clear()
            else:
                self._flush_combat_log()
                self._combat_log_add("Misty Wanderer: can't go there — pick another cell.")
                self._arm_pick("misty_wanderer")

        dest = rpg.Cell(cell.col, cell.row)
        allies = [a for a in self.combat.misty_wanderer_allies(self.bm, idx)
                  if self.combat.misty_wanderer_ally_cell(self.bm, a, idx, dest).col >= 0]
        if not allies:
            _go()
            return
        items = [(f"Bring {self.bm.placed_agents[a].name}", (lambda a=a: _go(a))) for a in allies]
        items.append(("Go alone", lambda: _go()))
        self._ask_actor(idx, "action", "Misty Wanderer: bring a willing creature?", items,
                        render="picker", on_cancel=lambda: _go())

    def _resolve_steps_of_fey(self, cell):
        """Archfey L3+ Steps of the Fey: a Bonus-Action Misty Step (30 ft) with the selected rider.
        Click your own cell to cancel."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("steps_of_fey")
            return
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self._drop_pick("steps_of_fey")
            self._combat_log_add("Steps of the Fey cancelled.")
            return
        if self.combat.steps_of_the_fey(self.bm, idx, cell.col, cell.row, self.steps_of_fey_effect, False):
            self._drop_pick("steps_of_fey")
            self._flush_combat_log()
            self.bonus_used = True
            self._reset_movement(idx)
            self._update_reach()
            self._update_attack_overlay()
        else:
            self._flush_combat_log()
            self._combat_log_add("Steps of the Fey: out of range or no use — pick a closer cell.")

    def _resolve_misty_escape(self, cell):
        """Archfey L6+ Misty Escape: the same Misty Step, spending the Reaction instead of a Bonus
        Action. Click your own cell to cancel."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("misty_escape")
            return
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self._drop_pick("misty_escape")
            self._combat_log_add("Misty Escape cancelled.")
            return
        if self.combat.steps_of_the_fey(self.bm, idx, cell.col, cell.row, self.steps_of_fey_effect, True):
            self._drop_pick("misty_escape")
            self._flush_combat_log()
            self._reset_movement(idx)
            self._update_reach()
            self._update_attack_overlay()
        else:
            self._flush_combat_log()
            self._combat_log_add("Misty Escape: out of range, no reaction, or no use — pick a closer cell.")

    def _resolve_bewitching_misty(self, cell):
        """Archfey L14 Bewitching Magic: a free Misty Step (no slot/use/action) offered right after an
        Enchantment/Illusion action-cast. Click your own cell to decline."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("bewitching_misty")
            return
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self._drop_pick("bewitching_misty")
            self._combat_log_add("Bewitching Magic Misty Step declined.")
            return
        if self.combat.bewitching_misty_step(self.bm, idx, cell.col, cell.row, self.steps_of_fey_effect):
            self._drop_pick("bewitching_misty")
            self._flush_combat_log()
            self._reset_movement(idx)
            self._update_reach()
            self._update_attack_overlay()
        else:
            self._flush_combat_log()
            self._combat_log_add("Bewitching Magic: out of range — pick a closer cell (or click yourself to decline).")

    def _resolve_wild_magic_teleport(self, cell):
        """Wild Magic Sorcerer: teleport up to 20 ft to the clicked cell (uses wild_magic_teleport_bonus_turns).
        Click your own cell to cancel."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("wild_magic_teleport")
            return
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self._drop_pick("wild_magic_teleport")
            self._combat_log_add("Wild Magic Teleport cancelled.")
            return
        # Validate 20-ft range (4 cells at 5-ft scale).
        dc = abs(cell.col - origin.col)
        dr = abs(cell.row - origin.row)
        dist_ft = max(dc, dr) * 5  # Chebyshev grid distance
        if dist_ft > 20:
            self._combat_log_add("Wild Magic Teleport: destination must be within 20 ft — pick a closer cell.")
            return
        if self.combat.teleport_agent(self.bm, idx, cell.col, cell.row):
            self._drop_pick("wild_magic_teleport")
            stats = self.combat.get_agent_stats(self.bm, idx)
            stats.wild_magic_teleport_bonus_turns = max(0, stats.wild_magic_teleport_bonus_turns - 1)
            self.combat.set_agent_stats(self.bm, idx, stats)
            self.bonus_used = True
            self._reset_movement(idx)
            self._update_reach()
            self._update_attack_overlay()
            self._flush_combat_log()
            self._combat_log_add(
                f"{self.bm.placed_agents[idx].name}: Wild Magic Teleport — moved up to 20 ft!")
        else:
            self._flush_combat_log()
            self._combat_log_add("Wild Magic Teleport: destination blocked — pick another cell.")

    def _resolve_warping_implosion(self, cell):
        """Aberrant L18 Warping Implosion: teleport up to 120 ft to the clicked cell, then every other
        creature within 30 ft of the space left makes a DEX save (3d10 Force, half on a success). The
        engine validates range/cost. Click your own cell to cancel."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("warping_implosion")
            return
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self._drop_pick("warping_implosion")
            self._combat_log_add("Warping Implosion cancelled.")
            return
        dist_ft = max(abs(cell.col - origin.col), abs(cell.row - origin.row)) * 5
        if dist_ft > 120:
            self._combat_log_add("Warping Implosion: destination must be within 120 ft — pick a closer cell.")
            return
        affected = self.combat.warping_implosion(self.bm, idx, cell.col, cell.row)
        if affected >= 0:
            self._drop_pick("warping_implosion")
            self.action_used = True
            self._reset_movement(idx)
            self._update_reach()
            self._update_attack_overlay()
            self._flush_combat_log()
            self._sync_spell_effect_cache()
            self._combat_log_add(
                f"{self.bm.placed_agents[idx].name}: Warping Implosion — {affected} creature(s) caught in the implosion!")
        else:
            self._flush_combat_log()
            self._combat_log_add("Warping Implosion: blocked or out of range — pick another cell.")

    def _resolve_shadow_darkness(self, cell):
        """Warrior of Shadow L3 Shadow Arts: Darkness — fill a 15-ft Sphere centered on the clicked
        cell with magical Darkness (1 Focus, Magic action). Click your own cell to cancel."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("shadow_darkness")
            return
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self._drop_pick("shadow_darkness")
            self._combat_log_add("Shadow Arts: Darkness cancelled.")
            return
        if self.combat.shadow_arts_darkness(self.bm, idx, cell.col, cell.row) >= 0:
            self._drop_pick("shadow_darkness")
            self._flush_combat_log()
            self.action_used = True
            self._update_attack_overlay()
        else:
            self._flush_combat_log()
            self._combat_log_add("Shadow Arts: Darkness: requires the Warrior of Shadow subclass (L3) and 1 Focus Point.")

    def _resolve_elemental_burst(self, cell):
        """Warrior of the Elements L6 Elemental Burst — a 20-ft Sphere of the chosen element centered on
        the clicked cell (2 Focus, Magic action). Click your own cell to cancel."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("elemental_burst")
            return
        element = self._pick_data("elemental_burst")
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self._drop_pick("elemental_burst")
            self._combat_log_add("Elemental Burst cancelled.")
            return
        if self.combat.elemental_burst(self.bm, idx, cell.col, cell.row, element):
            self._drop_pick("elemental_burst")
            self._flush_combat_log()
            self.action_used = True
            self._update_attack_overlay()
        else:
            self._flush_combat_log()
            self._combat_log_add("Elemental Burst: requires the Warrior of the Elements subclass (L6) and 2 Focus Points.")

    def _quivering_palm_id_for(self, idx):
        return app_attacks.quivering_palm_id_for(self, idx)

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
            self._arm_pick("arcane_charge")
            self._combat_log_add(
                "Arcane Charge: click a destination within 30 ft to teleport (or click yourself to skip).")

    def _resolve_arcane_charge(self, cell):
        """Eldritch Knight L15 Arcane Charge: teleport the EK up to 30 ft to the clicked cell.
        Validation + the teleport live in C++ (apply_arcane_charge); this only handles the
        skip gesture (click your own cell) and maps the engine's status code to a message."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("arcane_charge")
            return
        origin = self.bm.placed_agents[idx].origin
        if cell.col == origin.col and cell.row == origin.row:
            self._drop_pick("arcane_charge")
            self._combat_log_add("Arcane Charge skipped.")
            return
        feet = self.combat.apply_arcane_charge(self.bm, idx, cell.col, cell.row)
        if feet >= 0:
            self._drop_pick("arcane_charge")
            self._flush_combat_log()  # surface the engine's teleport log line
        elif feet == -2:
            self._combat_log_add("Arcane Charge: out of range (max 30 ft) — pick a closer cell.")
        else:  # -3 blocked (or -1 ineligible, which shouldn't reach here)
            self._combat_log_add("Arcane Charge: destination is blocked — pick another cell.")

    def _resolve_blink_steps(self, cell):
        """Boon of Dimensional Travel — Blink Steps: teleport the actor up to 30 ft to the clicked cell,
        an unoccupied space it can see. Reuses the existing teleport primitives (is_valid_teleport_
        destination + has_line_of_sight + _agent_at occupancy + teleport_agent) rather than a bespoke
        engine path; clears the blink_steps_available arming on success or on the skip gesture."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("blink_steps")
            return
        pt = self.bm.placed_agents[idx]
        origin = pt.origin
        # Click your own cell to skip.
        if cell.col == origin.col and cell.row == origin.row:
            self._drop_pick("blink_steps")
            self._clear_blink_steps_arm(idx)
            self._combat_log_add("Blink Steps skipped.")
            return
        dist_ft = ((cell.col - origin.col) ** 2 + (cell.row - origin.row) ** 2) ** 0.5 * 5
        if dist_ft > 30 + 1e-6:
            self._combat_log_add("Blink Steps: out of range (max 30 ft) — pick a closer cell.")
            return
        if self._agent_at(cell) >= 0 or not self.combat.is_valid_teleport_destination(self.bm, cell.col, cell.row):
            self._combat_log_add("Blink Steps: destination is blocked — pick another cell.")
            return
        if not self.bm.has_line_of_sight(origin, pt.size, cell, 1):
            self._combat_log_add("Blink Steps: no line of sight to that cell — pick a visible one.")
            return
        if self.combat.teleport_agent(self.bm, idx, cell.col, cell.row):
            self._drop_pick("blink_steps")
            self._clear_blink_steps_arm(idx)
            self._mark_fog_dirty()   # the teleport moved the token; explored mask + overlays need a refresh
            self._combat_log_add(
                f"{pt.name}: Blink Steps — teleports {int(dist_ft + 0.5)} ft to ({cell.col}, {cell.row}).")
            self._flush_combat_log()
        else:
            self._combat_log_add("Blink Steps: destination is blocked — pick another cell.")

    def _arm_blink_steps(self, idx: int):
        """Boon of Dimensional Travel: arm Blink Steps right after this agent's Attack/Magic action so the
        ✦ Blink Steps button (a free ≤30-ft teleport) appears. No-op unless the agent holds the boon."""
        if not (0 <= idx < len(self.bm.placed_agents)):
            return
        if not self.combat.get_agent_stats(self.bm, idx).has_feat("Boon of Dimensional Travel"):
            return
        conds = self.combat.get_agent_conditions(self.bm, idx)
        if not conds.blink_steps_available:
            conds.blink_steps_available = True
            self.combat.set_agent_conditions(self.bm, idx, conds)

    def _clear_blink_steps_arm(self, idx: int):
        """Consume the Blink Steps arming (blink_steps_available) after a teleport or a skip."""
        if not (0 <= idx < len(self.bm.placed_agents)):
            return
        conds = self.combat.get_agent_conditions(self.bm, idx)
        if conds.blink_steps_available:
            conds.blink_steps_available = False
            self.combat.set_agent_conditions(self.bm, idx, conds)

    def _blink_steps_ready(self, idx: int) -> bool:
        """True iff idx holds Boon of Dimensional Travel and has an armed Blink Steps this turn."""
        if not (0 <= idx < len(self.bm.placed_agents)):
            return False
        if not self.combat.get_agent_stats(self.bm, idx).has_feat("Boon of Dimensional Travel"):
            return False
        return self.combat.get_agent_conditions(self.bm, idx).blink_steps_available

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

    def _use_avenging_angel(self, agent_idx: int):
        """Paladin Oath of Vengeance (L20) Avenging Angel: Bonus Action, 10 minutes — Fly 60 (hover)
        and a Frightful Aura in the Aura of Protection. 1/long rest, or a level-5 slot when exhausted."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return
        ok = self.combat.activate_avenging_angel(self.bm, agent_idx)
        name = self.bm.placed_agents[agent_idx].name
        if not ok:
            self._combat_log_add(f"{name}: Cannot use Avenging Angel (needs Oath of Vengeance L20, a use or level-5 slot, and a bonus action).")
            self._flush_combat_log()
            return
        self.bonus_used = True
        self._flush_combat_log()

    def _use_living_legend(self, agent_idx: int):
        """Paladin Oath of Glory (L20) Living Legend: Bonus Action, 10 minutes — a reaction to reroll a
        failed save and once-per-turn Unerring Strike (weapon miss→hit). 1/long rest, or a level-5 slot."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return
        ok = self.combat.activate_living_legend(self.bm, agent_idx)
        name = self.bm.placed_agents[agent_idx].name
        if not ok:
            self._combat_log_add(f"{name}: Cannot use Living Legend (needs Oath of Glory L20, a use or level-5 slot, and a bonus action).")
            self._flush_combat_log()
            return
        self.bonus_used = True
        self._flush_combat_log()

    def _use_elder_champion(self, agent_idx: int):
        """Paladin Oath of the Ancients (L20) Elder Champion: Bonus Action, 1 minute — regain 10 HP each
        turn and enemies in the Aura of Protection have Disadvantage on saves vs your spells/Channel Oath.
        1/long rest, or a level-5 slot when exhausted."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return
        ok = self.combat.activate_elder_champion(self.bm, agent_idx)
        name = self.bm.placed_agents[agent_idx].name
        if not ok:
            self._combat_log_add(f"{name}: Cannot use Elder Champion (needs Oath of the Ancients L20, a use or level-5 slot, and a bonus action).")
            self._flush_combat_log()
            return
        self.bonus_used = True
        self._flush_combat_log()

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
        self._drop_pick("telekinetic")
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

    def _resolve_clairvoyant_combatant(self, target_idx: int):
        """Great Old One Warlock Clairvoyant Combatant: the clicked enemy makes a WIS save against the
        warlock; on a failure the warlock gains Advantage vs it and it has Disadvantage vs the warlock
        until the warlock's next turn. Spends a use (or a Pact slot) and the bonus action on success."""
        self._drop_pick("clairvoyant")
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)) or not (0 <= target_idx < len(self.bm.placed_agents)):
            return
        if target_idx == idx:
            self._combat_log_add("Clairvoyant Combatant: pick an enemy, not yourself.")
            return
        if self.combat.activate_clairvoyant_combatant(self.bm, idx, target_idx):
            self._flush_combat_log()
            self.bonus_used = True
        else:
            self._flush_combat_log()
            self._combat_log_add("Clairvoyant Combatant unavailable.")

    def _resolve_vow_of_enmity(self, target_idx: int):
        """Paladin Oath of Vengeance Vow of Enmity: the clicked enemy becomes the sworn foe — the
        paladin gains Advantage on attacks against it for 1 minute. Spends one Channel Oath use."""
        self._drop_pick("vow_of_enmity")
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)) or not (0 <= target_idx < len(self.bm.placed_agents)):
            return
        if target_idx == idx:
            self._combat_log_add("Vow of Enmity: pick an enemy, not yourself.")
            return
        if self.combat.activate_vow_of_enmity(self.bm, idx, target_idx):
            self._flush_combat_log()
        else:
            self._flush_combat_log()
            self._combat_log_add("Vow of Enmity unavailable (needs Oath of Vengeance, a Channel Oath use, and a target within 30 ft).")

    def _resolve_path_to_the_grave(self, target_idx: int):
        """Grave Cleric Path to the Grave: curse the clicked creature (within 30 ft, seen) until the
        start of the cleric's next turn. The engine spends the Channel Divinity use and the Bonus Action."""
        self._drop_pick("path_to_the_grave")
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)) or not (0 <= target_idx < len(self.bm.placed_agents)):
            return
        if target_idx == idx:
            self._combat_log_add("Path to the Grave: pick another creature, not yourself.")
            return
        ok = self.combat.use_path_to_the_grave(self.bm, idx, target_idx)
        self._flush_combat_log()
        if not ok:
            self._combat_log_add("Path to the Grave unavailable (needs a Channel Divinity use, the "
                                 "Bonus Action, and a creature you can see within 30 ft).")

    def _resolve_move_hunters_mark(self, target_idx: int):
        """Hunter's Mark / Hex: the marked creature dropped to 0 HP, so move the mark to the clicked
        creature (seen, within 90 ft). The engine spends the Bonus Action."""
        self._drop_pick("move_hunters_mark")
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)) or not (0 <= target_idx < len(self.bm.placed_agents)):
            return
        ok = self.combat.move_hunters_mark(self.bm, idx, target_idx)
        self._flush_combat_log()
        if not ok:
            self._combat_log_add("Move Hunter's Mark: pick another living creature you can see "
                                 "within 90 ft.")

    def _resolve_inspiring_smite(self, target_idx: int):
        """Paladin Oath of Glory Inspiring Smite: grant the clicked creature (within 30 ft, may be self)
        2d8 + Paladin level temporary HP. Spends one Channel Oath use; only right after a Divine Smite."""
        self._drop_pick("inspiring_smite")
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)) or not (0 <= target_idx < len(self.bm.placed_agents)):
            return
        thp = self.combat.activate_inspiring_smite(self.bm, idx, target_idx)
        if thp >= 0:
            self._flush_combat_log()
        else:
            self._flush_combat_log()
            self._combat_log_add("Inspiring Smite unavailable (needs Oath of Glory, a Divine Smite this turn, a Channel Oath use, and a target within 30 ft).")

    def _resolve_lay_on_hands(self, target_idx: int):
        """Paladin Lay on Hands: spend from pool, heal target."""
        self._drop_pick("lay_on_hands")
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
            # Refused like an empty square: the pick stays armed, so the player is asked
            # again and the DM can click someone else or Esc out.
            self._arm_pick("lay_on_hands")
            self._combat_log_add(f"{self.bm.placed_agents[target_idx].name}: Already at full HP. "
                                 "Choose another creature, or cancel.")
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

    def _resolve_bastion_of_law(self, target_idx: int):
        """Clockwork Sorcerer L6 Bastion of Law: spend the chosen Sorcery Points (1-5) to ward the
        clicked target (self or a creature within 30 ft) with a pre-rolled (sp)d8 absorption pool."""
        self._drop_pick("bastion_of_law")
        sp = self.pending_bastion_sp
        self.pending_bastion_sp = 0
        caster_idx = self._current_agent_idx()
        if not (0 <= caster_idx < len(self.bm.placed_agents)):
            return
        if not (0 <= target_idx < len(self.bm.placed_agents)):
            return
        ward = self.combat.activate_bastion_of_law(self.bm, caster_idx, target_idx, sp)
        if ward >= 0:
            self.action_used = True  # Bastion of Law is a Magic Action
        else:
            self._combat_log_add("Bastion of Law: not available (range / Sorcery Points / subclass/level)")
        self._flush_combat_log()
        self._update_attack_overlay()

    def _resolve_hand_of_healing(self, target_idx: int):
        """Monk Warrior of Mercy Hand of Healing: spend a bonus action + 1 Focus Point to heal the
        clicked target (Martial Arts die + WIS). At L6 (Physician's Touch) it also ends a condition."""
        self._drop_pick("hand_of_healing")
        healer_idx = self._current_agent_idx()
        if not (0 <= healer_idx < len(self.bm.placed_agents)):
            return
        if not (0 <= target_idx < len(self.bm.placed_agents)):
            return

        res = self.combat.hand_of_healing(self.bm, healer_idx, target_idx)
        if not res.valid:
            self._combat_log_add(f"{self.bm.placed_agents[healer_idx].name}: Hand of Healing unavailable.")
            return

        healer_name = self.bm.placed_agents[healer_idx].name
        tgt_name = self.bm.placed_agents[target_idx].name
        msg = f"{healer_name}: Hand of Healing restores {res.amount_healed} HP to {tgt_name}"
        if res.condition_cleared:
            msg += f" and ends {res.cleared_condition}"
        self._combat_log_add(msg + ".")
        self.bonus_used = True
        self._update_attack_overlay()

    @staticmethod
    def _item_menu_dice(it) -> str:
        """'2d4+2' for a potion, '2d6 Acid' for a thrown flask, 'Restrained' for a Net —
        whatever the DM is actually picking the item by."""
        if it.type == rpg.ItemType.Thrown:
            if it.damage.num_dice > 0:
                dice = f"{it.damage.num_dice}d{it.damage.die_size} {it.damage.type.name}"
                return f"{dice}, {it.condition_applied}" if it.condition_applied else dice
            return it.condition_applied or "no damage"
        return f"{it.healing.num_dice}d{it.healing.die_size}+{it.healing.bonus}"

    def _can_replace_attack(self, idx: int) -> bool:
        return app_attacks.can_replace_attack(self, idx)

    def _resolve_use_item(self, target_idx: int):
        """Use the armed inventory slot on the clicked target (which may be the user itself).
        The engine owns the rules — range, the heal/save rolls, the condition riders, and spending
        the charge — so a rejected use (out of reach, no bonus action left) costs nothing. The
        action economy is charged here, on the GUI's budgets."""
        slot = self._pick_data("use_item")
        self._drop_pick("use_item")
        user_idx = self._current_agent_idx()
        if not (0 <= user_idx < len(self.bm.placed_agents)):
            return
        if not (0 <= target_idx < len(self.bm.placed_agents)):
            return

        items = self.combat.get_agent_items(self.bm, user_idx)
        if not (0 <= slot < len(items)):
            return
        item     = items[slot]
        is_throw = (item.action_type == rpg.ItemAction.AttackReplacement)

        # A thrown flask replaces one of the Attack action's swings, so make sure there IS one to
        # replace before the engine spends the flask.
        if is_throw and not self._can_replace_attack(user_idx):
            self._combat_log_add(
                f"{self.bm.placed_agents[user_idx].name}: no attack left to replace "
                f"(a thrown {item.name} costs one attack of the Attack action).")
            self._update_attack_overlay()
            return

        # Healing is clamped to the target's max HP, so a potion drunk at full health rolls its
        # dice, restores nothing, and still burns the charge and the Bonus Action. Refuse it here
        # rather than let the engine silently eat it ("regains 0 HP"). A potion that also grants
        # Temporary HP or a condition (Potion of Heroism, RAVENLOFT M11) is worth drinking anyway.
        if (item.type == rpg.ItemType.Heal and item.temp_hp <= 0
                and not item.applies_condition):
            tgt = self.combat.get_agent_stats(self.bm, target_idx)
            if tgt.hp_cur >= tgt.hp_max - tgt.available_hit_points:
                self._combat_log_add(
                    f"{self.bm.placed_agents[target_idx].name} is already at full HP — "
                    f"{item.name} not used.")
                self._update_attack_overlay()
                return

        res = self.combat.use_item(self.bm, user_idx, slot, target_idx)
        if not res.valid:
            self._combat_log_add(
                f"{self.bm.placed_agents[user_idx].name}: can't use that item "
                f"(out of reach, no bonus action left, or none carried).")
            self._update_attack_overlay()
            return

        # The engine already narrates the use (the drink and the HP regained; a throw's save roll,
        # damage and condition), so just flush its lines — re-stating them here printed every use
        # twice. Only the charge count is the GUI's to report.
        self._flush_combat_log()
        if res.consumed:
            self._combat_log_add(
                f"{self.bm.placed_agents[user_idx].name}: that was the last {res.item_name}.")

        if is_throw:
            app_attacks.consume_attack_replacement(self, user_idx)
        elif item.action_type == rpg.ItemAction.Action:
            self.action_used = True
        elif item.action_type == rpg.ItemAction.BonusAction:
            self.bonus_used = True
        self._update_attack_overlay()

    def _resolve_extinguish(self):
        """Put out a Burning actor: an action to drop Prone and roll on the ground."""
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)):
            return
        if not self.combat.extinguish_burning(self.bm, idx):
            return
        self._combat_log_add(
            f"{self.bm.placed_agents[idx].name} drops and rolls, putting out the flames "
            f"(now Prone, no longer Burning).")
        self._flush_combat_log()
        self.action_used = True
        self._update_attack_overlay()

    def _netted_within_reach(self, actor_idx: int) -> list:
        """Netted (or Grasping-Shot) creatures this actor could free: itself, plus anything within 5 ft."""
        out = []
        for i in range(len(self.bm.placed_agents)):
            # A Grasping Shot (Arcane Archer) frees the same way, against the archer's DC.
            if not (self.combat.get_agent_conditions(self.bm, i).netted
                    or self.combat.held_by_grasping_shot(i)):
                continue
            if i == actor_idx or (0 <= self._footprint_dist_ft(actor_idx, i) <= 5
                                  and self._can_reach_through(actor_idx, i)):
                out.append(i)
        return out

    def _begin_escape_net(self):
        """Free from Net: cut yourself loose right away, or arm a click for a netted neighbour."""
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)):
            return
        freeable = self._netted_within_reach(idx)
        if not freeable:
            return                       # nothing tangled here (a stale button rect)
        if idx in freeable:
            self._resolve_escape_net(idx)          # cut yourself loose
        elif len(freeable) == 1:
            self._resolve_escape_net(freeable[0])  # only one neighbour to free — no click needed
        else:
            self._arm_pick("escape_net")
            self.hint = "Click the netted creature to free (within 5 ft)"

    def _resolve_escape_net(self, target_idx: int):
        """Free a netted creature (self, or one within 5 ft) with a DC 10 STR check — an action.
        A creature held by a Grasping Shot frees the same way, against the archer's DC."""
        self._drop_pick("escape_net")
        actor_idx = self._current_agent_idx()
        if not (0 <= actor_idx < len(self.bm.placed_agents)):
            return
        if not (0 <= target_idx < len(self.bm.placed_agents)):
            return

        netted = self.combat.get_agent_conditions(self.bm, target_idx).netted
        what = "the Net" if netted else "the Grasping Shot"
        res = (self.combat.escape_net(self.bm, actor_idx, target_idx) if netted
               else self.combat.escape_grasping_shot(self.bm, actor_idx, target_idx))
        if not res.valid:
            self._combat_log_add(
                f"{self.bm.placed_agents[actor_idx].name}: can't free that creature "
                f"(it is not netted, or it is out of reach).")
            self._update_attack_overlay()
            return

        who = "itself" if target_idx == actor_idx else self.bm.placed_agents[target_idx].name

        def _report(r):
            self._combat_log_add(
                f"{self.bm.placed_agents[actor_idx].name}: STR check {r.total} vs DC {r.dc} to free "
                f"{who} from {what} — {'FREED' if r.freed else 'still tangled'}.")
            self._flush_combat_log()
            self._update_attack_overlay()
        _report(res)
        self.action_used = True
        if not res.freed:
            self._offer_past_life(actor_idx, lambda: _report(
                self.combat.escape_net(self.bm, actor_idx, target_idx) if netted
                else self.combat.escape_grasping_shot(self.bm, actor_idx, target_idx)))

    def _resolve_grant_inspiration(self, target_idx: int):
        """Bard Grant Inspiration (bonus action): spend a Bardic Inspiration use to give
        an ally a Bardic Inspiration die of the bard's current size."""
        self._drop_pick("grant_inspiration")
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

    def _mantle_cha_cap(self, bard_idx: int) -> int:
        """Max recipients for Mantle of Inspiration = the bard's CHA modifier (min 1)."""
        stats = self.combat.get_agent_stats(self.bm, bard_idx)
        return max(1, (stats.cha - 10) // 2)

    def _start_mantle(self, bard_idx: int):
        """College of Glamour Mantle of Inspiration (bonus action): begin collecting up to
        CHA-mod other creatures within 60 ft. Enter confirms / Esc cancels."""
        stats = self.combat.get_agent_stats(self.bm, bard_idx)
        bi = stats.get_resource("Bardic Inspiration")
        if not (bi and bi.current > 0):
            self._combat_log_add(f"{self.bm.placed_agents[bard_idx].name}: no Bardic Inspiration uses left.")
            self._flush_combat_log()
            return
        self._arm_pick("mantle")
        self.pending_mantle_targets = []
        cap = self._mantle_cha_cap(bard_idx)
        self._combat_log_add(
            f"Mantle of Inspiration — click up to {cap} creature(s) within 60 ft, then Enter "
            f"(Esc cancels).")
        self._flush_combat_log()

    def _mantle_add_target(self, hit: int):
        """Add a clicked creature to the Mantle recipient list (within 60 ft, not the bard,
        not already chosen, capped to CHA mod)."""
        bard_idx = self._current_agent_idx()
        agents = self.bm.placed_agents
        if not (0 <= hit < len(agents)) or not (0 <= bard_idx < len(agents)):
            return
        if hit == bard_idx:
            self._combat_log_add("Mantle of Inspiration affects other creatures, not yourself.")
            self._flush_combat_log()
            return
        if hit in self.pending_mantle_targets:
            return
        cap = self._mantle_cha_cap(bard_idx)
        if len(self.pending_mantle_targets) >= cap:
            self._combat_log_add(f"Mantle of Inspiration: already chose {cap} creature(s) — Enter to confirm.")
            self._flush_combat_log()
            return
        if self._footprint_dist_ft(bard_idx, hit) > 60:
            self._combat_log_add("Mantle of Inspiration: that creature is more than 60 ft away.")
            self._flush_combat_log()
            return
        self.pending_mantle_targets.append(hit)
        self._combat_log_add(
            f"  Mantle target {len(self.pending_mantle_targets)}/{cap} → {agents[hit].name}")
        self._flush_combat_log()

    def _finalize_mantle(self):
        """Resolve Mantle of Inspiration on the collected recipients."""
        bard_idx = self._current_agent_idx()
        targets  = list(self.pending_mantle_targets)
        self._drop_pick("mantle")
        self.pending_mantle_targets = []
        if not (0 <= bard_idx < len(self.bm.placed_agents)) or not targets:
            self._combat_log_add("Mantle of Inspiration cancelled (no targets).")
            self._flush_combat_log()
            return
        thp = self.combat.apply_mantle_of_inspiration(self.bm, bard_idx, targets)
        self._flush_combat_log()
        if thp > 0:
            self.bonus_used = True
            bi = self.combat.get_agent_stats(self.bm, bard_idx).get_resource("Bardic Inspiration")
            remaining = bi.current if bi else 0
            self._combat_log_add(
                f"{self.bm.placed_agents[bard_idx].name}: Mantle of Inspiration grants {thp} "
                f"Temporary HP to {len(targets)} creature(s) ({remaining} uses left).")
        self._update_attack_overlay()

    def _cancel_mantle(self):
        """Esc out of Mantle of Inspiration without spending the Bardic Inspiration use."""
        self._drop_pick("mantle")
        self.pending_mantle_targets = []
        self._combat_log_add("Mantle of Inspiration cancelled.")
        self._flush_combat_log()


    def _start_unbreakable_majesty(self, bard_idx: int):
        """College of Glamour Unbreakable Majesty (bonus action, L14+). Spend the once/long-rest resource
        to open a 1-minute Concentration window of "majestic presence": melee attacks against the bard
        trigger Psychic damage and a CHA save (no reaction). While the window is active the button is
        just a display (clicking does nothing, since the feature runs automatically)."""
        if self.bonus_used:
            self._combat_log_add("Bonus action already used this turn.")
            self._flush_combat_log()
            return
        stats = self.combat.get_agent_stats(self.bm, bard_idx)
        if not (stats.bard_subclass == rpg.BardCollege.Glamour and stats.char_level >= 14):
            return
        window_active = stats.majestic_presence_turns > 0
        if window_active:
            # Already active — button is just informational (the feature runs automatically)
            self._combat_log_add(f"{self.bm.placed_agents[bard_idx].name}'s majestic presence is already active.")
            self._flush_combat_log()
            return
        um = stats.get_resource("Unbreakable Majesty")
        if not (um and um.current > 0):
            self._combat_log_add(
                f"{self.bm.placed_agents[bard_idx].name}: no Unbreakable Majesty use left.")
            self._flush_combat_log()
            return
        if not self.combat.activate_unbreakable_majesty(self.bm, bard_idx):
            self._flush_combat_log()
            return
        self.bonus_used = True
        self._combat_log_add(f"{self.bm.placed_agents[bard_idx].name} takes on a majestic presence (Unbreakable Majesty).")
        self._flush_combat_log()

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

    # FLAG: Move to C++
    # ── Enspelled items E3 (plans/ENSPELLED_ITEMS_PLAN.md) ─────────────────────
    def _sync_item_spells(self, agent_idx: int):
        return app_char_setup.sync_item_spells(self, agent_idx)

    def _sync_all_item_spells(self):
        return app_char_setup.sync_all_item_spells(self)

    def _carried_item_spells(self, agent_idx: int) -> list:
        """(row, ItemSpells) for every carried item, weapon and worn armor piece (D9) that
        has spells or passive bonuses (RAVENLOFT M1), attuned or not."""
        rows = (list(self.combat.get_agent_items(self.bm, agent_idx))
                + list(self.combat.get_agent_weapons(self.bm, agent_idx))
                + list(self.combat.get_agent_armor(self.bm, agent_idx)))
        return [(r, r.item_spells) for r in rows
                if r.name and (not r.item_spells.empty() or r.item_spells.bonuses.any())]

    def _on_spell_done(self, agent_idx: int, spells: list[dict]):
        return app_spells.on_spell_done(self, agent_idx, spells)

    def _grant_class_features(self, agent_idx: int, cpp_spells: list):
        return app_char_setup.grant_class_features(self, agent_idx, cpp_spells)

    # Always-prepared Bard college spells by college and Bard level (2024 PHB).
    _BARD_SUBCLASS_SPELLS = {
        "Glamour": {3: ["Charm Person", "Mirror Image"], 6: ["Command"]},
    }

    # Always-prepared Sorcerer subclass spells by subclass and Sorcerer level (2024 PHB).
    _SORCERER_SUBCLASS_SPELLS = {
        "Aberrant": {
            1: ["Arms of Hadar", "Dissonant Whispers", "Mind Sliver"],
            3: ["Hunger of Hadar", "Phantasmal Force"],
            5: ["Clairvoyance", "Slow"],
            7: ["Dominate Beast", "Black Tentacles"],
            9: ["Dominate Person", "Telekinesis"],
        },
        # Clockwork Soul (2024 PHB) — Clockwork Spells, always prepared by Sorcerer level. The
        # subclass-key uses SorcererSubclass.name ("Clockwork"). All ten exist in spells.json.
        "Clockwork": {
            3: ["Aid", "Alarm", "Lesser Restoration", "Protection from Evil and Good"],
            5: ["Dispel Magic", "Protection from Energy"],
            7: ["Freedom of Movement", "Summon Construct"],
            9: ["Greater Restoration", "Wall of Force"],
        },
    }

    # Always-prepared Warlock patron spells by subclass and Warlock level (2024 PHB). The
    # Archfey Steps of the Fey rider names, indexed by effect code (0-4). Effects 3/4 (Disappearing /
    # Dreadful) are Warlock L6+ only — the effect selector caps the cycle at 3 options below L6.
    _FEY_EFFECT_NAMES = ["None", "Refreshing", "Taunting", "Disappearing", "Dreadful"]

    # subclass-key uses WarlockSubclass.name ("Archfey"/"Celestial"/"Fiend"/"GreatOldOne").
    # Names not in spells.json are skipped gracefully by _grant_class_features.
    _WARLOCK_SUBCLASS_SPELLS = {
        "Archfey": {
            3: ["Calm Emotions", "Faerie Fire", "Misty Step", "Phantasmal Force"],
            5: ["Blink", "Plant Growth"],
            7: ["Dominate Beast", "Greater Invisibility"],
            9: ["Dominate Person", "Seeming"],
        },
        "Celestial": {
            3: ["Aid", "Cure Wounds", "Guiding Bolt", "Lesser Restoration"],
            5: ["Daylight", "Revivify"],
            7: ["Guardian of Faith", "Wall of Fire"],
            9: ["Greater Restoration", "Summon Celestial"],
        },
        "Fiend": {
            3: ["Burning Hands", "Command", "Scorching Ray", "Suggestion"],
            5: ["Fireball", "Stinking Cloud"],
            7: ["Fire Shield", "Wall of Fire"],
            9: ["Geas", "Insect Plague"],
        },
        "GreatOldOne": {
            3: ["Detect Thoughts", "Dissonant Whispers", "Hideous Laughter", "Phantasmal Force"],
            5: ["Clairvoyance", "Hunger of Hadar"],
            7: ["Confusion", "Summon Aberration"],
            9: ["Modify Memory", "Telekinesis"],
        },
    }

    # Flat set of all Aberrant Mind psionic spell names (from every level bucket above).
    # Used by _start_cast_spell to decide which slots can be replaced by SP (Psionic Sorcery L3+).
    _PSIONIC_SPELL_NAMES = frozenset(
        name
        for lvl_spells in _SORCERER_SUBCLASS_SPELLS["Aberrant"].values()
        for name in lvl_spells
    )

    # Always-prepared Ranger subclass spells by subclass and Ranger level (2024 PHB).
    _RANGER_SUBCLASS_SPELLS = {
        "GloomStalker": {
            3: ["Disguise Self"],
            5: ["Rope Trick"],
            9: ["Fear"],
            13: ["Greater Invisibility"],
            17: ["Seeming"],
        },
        "FeyWanderer": {
            3: ["Charm Person"],
            5: ["Misty Step"],
            9: ["Summon Fey"],
            13: ["Dimension Door"],
            17: ["Mislead"],
        },
    }

    # Always-prepared Paladin oath spells by oath and Paladin level (2024 PHB). Keyed by
    # PaladinOath.name. Combat-relevant spells only — all listed here exist in spells.json;
    # pure-utility oath spells (Scrying, Commune with Nature, Speak with Animals, Tree Stride,
    # Legend Lore, Yolande's Regal Presence) are omitted per combat-sim scope (see known_limitations).
    _PALADIN_OATH_SPELLS = {
        "OathOfVengeance": {
            3:  ["Bane", "Hunter's Mark"],
            5:  ["Hold Person", "Misty Step"],
            9:  ["Haste", "Protection from Energy"],
            13: ["Banishment", "Dimension Door"],
            17: ["Hold Monster"],
        },
        "OathOfAncients": {
            3:  ["Ensnaring Strike"],                       # Speak with Animals (utility) omitted
            5:  ["Misty Step", "Moonbeam"],
            9:  ["Plant Growth", "Protection from Energy"],
            13: ["Ice Storm", "Stoneskin"],
            # 17: Commune with Nature, Tree Stride — utility, omitted
        },
        "OathOfGlory": {
            3:  ["Guiding Bolt", "Heroism"],
            5:  ["Enhance Ability", "Magic Weapon"],
            9:  ["Haste", "Protection from Energy"],
            13: ["Compulsion"],                             # Freedom of Movement (utility) omitted
            # 17: Legend Lore, Yolande's Regal Presence — utility / not in spells.json, omitted
        },
    }

    # Always-prepared Cleric domain spells by domain and Cleric level (2024 PHB).
    _DOMAIN_SPELLS = {
        "LifeDomain": {
            3: ["Bless", "Cure Wounds", "Aid", "Lesser Restoration"],
            5: ["Mass Healing Word", "Revivify"],
            7: ["Aura of Life", "Death Ward"],
            9: ["Greater Restoration", "Mass Cure Wounds"],
        },
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
        "TrickeryDomain": {
            # Pass Without Trace (L3) isn't in spells.json yet — skipped gracefully.
            3: ["Charm Person", "Disguise Self", "Invisibility", "Pass Without Trace"],
            5: ["Hypnotic Pattern", "Nondetection"],
            7: ["Confusion", "Dimension Door"],
            9: ["Dominate Person", "Modify Memory"],
        },
        # Grave Domain (Ravenloft: The Horrors Within).
        "GraveDomain": {
            3: ["Detect Evil and Good", "False Life", "Gentle Repose", "Ray of Enfeeblement",
                "Spare the Dying"],
            5: ["Revivify", "Vampiric Touch"],
            7: ["Blight", "Death Ward"],
            9: ["Dispel Evil and Good", "Raise Dead"],
        },
    }

    def _activate_spell(self, s, si_, slot_level_, idx, spells, stats, free_cast=False,
                        use_grant=False):
        return app_spells.activate_spell(self, s, si_, slot_level_, idx, spells, stats, free_cast,
                                         use_grant)

    def _on_wish_duplicate(self, caster_idx: int, slot: str, wish_slot_level: int, spell_dict: dict):
        return app_spells.on_wish_duplicate(self, caster_idx, slot, wish_slot_level, spell_dict)

    def _drop_di_wish_free(self):
        return app_spells.drop_di_wish_free(self)

    def _ask_ward_types(self, idx, spell_name, chosen, on_done):
        return app_spells.ask_ward_types(self, idx, spell_name, chosen, on_done)

    # FLAG: Move to C++
    def _start_cast_spell(self, slot: str):
        return app_spells.start_cast_spell(self, slot)

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
            # Reset NPC spell uses: copy uses_max back to uses_remaining, clear recharge.
            if idx in self._agent_meta:
                spells = self.combat.get_agent_spells(self.bm, idx)
                spells_changed = False
                for spell in spells:
                    if spell.uses_max > 0:
                        spell.uses_remaining = spell.uses_max
                        spells_changed = True
                    if spell.expended:
                        spell.expended = False
                        spells_changed = True
                if spells_changed:
                    self.combat.set_agent_spells(self.bm, idx, spells)
                # Reset NPC weapon uses + recharge state.
                weapons = self.combat.get_agent_weapons(self.bm, idx)
                weapons_changed = False
                for w in weapons:
                    if w.uses_max > 0 and w.uses_remaining != w.uses_max:
                        w.uses_remaining = w.uses_max
                        weapons_changed = True
                    if w.expended:
                        w.expended = False
                        weapons_changed = True
                if weapons_changed:
                    self.combat.set_agent_weapons(self.bm, idx, weapons)
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
        # The window's own sentence is both the combat-log line and the prompt's title
        # (Step 0.5's `title` field) — one string, composed once, so a remote renderer
        # says exactly what the DM's log says.
        title = "Reaction"
        if 0 <= ctx.reactor_idx < len(agents) and 0 <= ctx.source_idx < len(agents):
            if ctx.window == rpg.ReactionWindow.OnDeclareCast:
                title = (
                    f"{agents[ctx.reactor_idx].name} may react to {agents[ctx.source_idx].name}'s spell!")
            elif ctx.window == rpg.ReactionWindow.OnHit:
                kind = "spell attack" if ctx.spell_idx >= 0 else "attack"
                # The OnHit defender window may offer Shield (negate) and/or Uncanny Dodge (halve).
                feats = [o.feature for o in ctx.options
                         if o.kind == rpg.ReactionOptionKind.Feature]
                names = {"Shield": "Shield", "UncannyDodge": "Uncanny Dodge",
                         "SuperiorHuntersDefense": "Superior Hunter's Defense",
                         "DeflectAttacks": "Deflect Attacks",
                         "DefensiveDuelist": "Defensive Duelist", "Parry": "Parry",
                         "StonesEndurance": "Stone's Endurance",
                         "StormsThunder": "Storm's Thunder", "HellishRebuke": "Hellish Rebuke",
                         "GloriousDefense": "Glorious Defense",
                         "SentinelAtDeathsDoor": "Sentinel at Death's Door"}
                choices = " / ".join(names.get(f, f) for f in feats) or "Shield"
                title = (
                    f"{agents[ctx.reactor_idx].name} may react ({choices}) vs "
                    f"{agents[ctx.source_idx].name}'s {kind}!")
            elif ctx.window == rpg.ReactionWindow.OnAttackDeclared:
                title = (
                    f"{agents[ctx.reactor_idx].name} may react before {agents[ctx.source_idx].name}'s "
                    f"attack roll — Shadowy Dodge!")
            elif ctx.window == rpg.ReactionWindow.AfterAttack:
                if any(o.feature.startswith("MasterfulShots") for o in ctx.options):
                    title = (
                        f"{agents[ctx.reactor_idx].name} may react to {agents[ctx.source_idx].name}'s "
                        f"miss — Masterful Shots!")
                else:
                    title = (
                        f"{agents[ctx.reactor_idx].name}: Shadowy Dodge — teleport up to 30 ft?")
            elif ctx.window == rpg.ReactionWindow.AfterSave:
                title = (
                    f"{agents[ctx.reactor_idx].name}: Indomitable Teleport — teleport up to 60 ft?")
            elif ctx.window == rpg.ReactionWindow.OnD20Seen:
                feats = [o.feature for o in ctx.options
                         if o.kind == rpg.ReactionOptionKind.Feature]
                names = {"BendLuck": "Bend Luck", "CuttingWords": "Cutting Words",
                         "SilveryBarbs": "Silvery Barbs", "WardingFlare": "Warding Flare",
                         "RestoreBalance": "Restore Balance"}
                choices = " / ".join(names.get(f, f) for f in feats) or "react"
                title = (
                    f"{agents[ctx.reactor_idx].name} may alter {agents[ctx.source_idx].name}'s "
                    f"attack roll ({ctx.d20_value}) — {choices}!")
            elif ctx.window == rpg.ReactionWindow.OnSaveFail:
                who = ("their own" if ctx.reactor_idx == ctx.source_idx
                       else f"{agents[ctx.source_idx].name}'s")
                names = {"Countercharm": "Countercharm", "Indomitable": "Indomitable",
                         "LegendaryResistance": "Legendary Resistance",
                         "WarGodsBlessing": "War God's Blessing",
                         "DarkOnesOwnLuck": "Dark One's Own Luck",
                         "LivingLegend": "Living Legend",
                         "HeroicInspiration": "Heroic Inspiration"}
                feats = [o.feature for o in ctx.options
                         if o.kind == rpg.ReactionOptionKind.Feature]
                choices = " / ".join(names.get(f, f) for f in feats) or "react"
                title = (
                    f"{agents[ctx.reactor_idx].name} may aid {who} failed save "
                    f"({ctx.d20_value}) — {choices}!")
            elif ctx.window == rpg.ReactionWindow.OnTurnStartNearby:
                if ctx.reactor_idx == ctx.source_idx:
                    # Self-option: the World Tree Barbarian may grant temp HP at its own turn start.
                    title = (
                        f"{agents[ctx.source_idx].name} may grant a creature within 10 ft "
                        f"temp HP — Vitality of the Tree!")
                else:
                    title = (
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
                    title = (
                        f"{agents[ctx.reactor_idx].name} gets a Sentinel opportunity attack vs "
                        f"{agents[ctx.source_idx].name} (a hit stops it — speed → 0)!")
                else:
                    title = (
                        f"{agents[ctx.reactor_idx].name} gets an opportunity attack vs {agents[ctx.source_idx].name}!")
            self._combat_log_add(title)
        def _make_cb(i, feature):
            # Vitality of the Tree needs a target pick before submitting; everything else submits at once.
            if feature == "VitalityOfTheTree":
                return lambda i=i: self._begin_vitality_target_pick(i)
            if feature == "ShadowyDodgeTeleportPick":
                return lambda i=i: self._begin_shadowy_dodge_pick(i)
            if feature in ("MasterfulShotsPick", "IndomitableTeleportPick"):
                return lambda i=i, f=feature: self._begin_reaction_cell_pick(i, f)
            return lambda i=i: self._submit_reaction(i)
        # The first prompt on the bus (M1 Step 2). The owner is the REACTOR's controller,
        # not the actor's: an opportunity attack belongs to the creature taking it, which
        # is why `owner` is load-bearing from the very first conversion (Step 0.2).
        owner = self._prompt_owner(ctx.reactor_idx)
        self.prompts.ask(
            actor_idx=ctx.reactor_idx,
            owner=owner,
            kind="reaction",
            title=title,
            options=options_from_pairs(
                (opt.label, _make_cb(i, opt.feature)) for i, opt in enumerate(ctx.options)),
            # D-M5-7: a player's window is skipped when the DM's timer runs out, through
            # the same on_cancel a click-away runs.
            deadline=self._reaction_deadline("reaction", owner, self._submit_reaction_skip),
            anchor=self._agent_screen_pos(ctx.reactor_idx),
            # Dismissing the popup must still resolve the parked window, or a queued
            # following reactor never gets its own (Branches after Vitality of the Tree).
            on_cancel=self._submit_reaction_skip)

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

    def _submit_reaction_skip(self):
        """Decline the parked reaction window when its popup is dismissed without choosing an
        option (click-away / right-click). Every reaction window appends an explicit Skip option;
        we submit it so the flow advances to the *next* queued reactor instead of staying parked.

        This is what unblocks Branches of the Tree after Vitality of the Tree: the engine queues
        both as OnTurnStartNearby reactors (Vitality first), so dismissing the Vitality popup must
        still resolve its window for the Branches popup to ever appear."""
        pd = self.combat.pending_decision()
        if not pd.active:
            return
        skip_idx = next((i for i, opt in enumerate(pd.ctx.options)
                         if opt.kind == rpg.ReactionOptionKind.Skip), -1)
        self._submit_reaction(skip_idx)

    def _begin_vitality_target_pick(self, option_index: int):
        """World Tree Vitality of the Tree (turn-start self-option): the player picked the option;
        now arm a target click so they choose which creature within 10 ft gets the temp HP. The
        OnTurnStartNearby window stays parked until _resolve_vitality_target submits the response."""
        self._vitality_option_index = option_index
        self._arm_pick("vitality_target")
        pd = self.combat.pending_decision()
        src = pd.ctx.source_idx if pd.active else -1
        agents = self.bm.placed_agents
        name = agents[src].name if 0 <= src < len(agents) else "?"
        print(f"[VITALITY] armed target-pick: opt={option_index}, pd.active={pd.active}, "
              f"src={src} ({name}), window={pd.ctx.window if pd.active else 'n/a'}")
        self._combat_log_add(f"{name}: click a creature within 10 ft to grant temporary HP (Vitality of the Tree).")
        self._flush_combat_log()

    def _begin_shadowy_dodge_pick(self, option_index: int):
        """Shadowy Dodge (Gloom Stalker L15): the player chose to pick the teleport cell. The
        AfterAttack window stays parked until _resolve_shadowy_dodge_cell submits it."""
        self._shadowy_dodge_option_index = option_index
        self._arm_pick("shadowy_dodge_cell")
        pd = self.combat.pending_decision()
        idx = pd.ctx.reactor_idx if pd.active else -1
        agents = self.bm.placed_agents
        name = agents[idx].name if 0 <= idx < len(agents) else "?"
        self._combat_log_add(f"{name}: click an unoccupied cell you can see within 30 ft "
                             f"(your own cell to stay put) — Shadowy Dodge.")
        self._flush_combat_log()

    # Arcane Archer cell picks inside a parked window: (pick kind, engine validator, prompt, error).
    # Masterful Shots' own cell shoots without moving; Indomitable Teleport's own cell stays put.
    _REACTION_CELL_PICKS = {
        "MasterfulShotsPick": (
            "masterful_shots_cell",
            lambda self, pd, cell: self.combat.is_masterful_shots_destination(
                self.bm, pd.ctx.reactor_idx, pd.ctx.source_idx, cell),
            "click a cell up to half your Speed away from the attacker (your own cell to shoot "
            "without moving) — Masterful Shots.",
            "Masterful Shots: pick an unoccupied cell within half your Speed, farther from the attacker."),
        "IndomitableTeleportPick": (
            "indomitable_teleport_cell",
            lambda self, pd, cell: self.combat.is_indomitable_teleport_destination(
                self.bm, pd.ctx.reactor_idx, cell),
            "click an unoccupied cell you can see within 60 ft (your own cell to stay put) — "
            "Indomitable Teleport.",
            "Indomitable Teleport: pick an unoccupied cell you can see within 60 ft."),
    }

    def _begin_reaction_cell_pick(self, option_index: int, feature: str):
        """Masterful Shots / Indomitable Teleport: the player chose to pick the cell. The parked
        window stays parked until _resolve_reaction_cell submits it."""
        kind, _, prompt, _ = self._REACTION_CELL_PICKS[feature]
        self._reaction_cell_option_index = option_index
        self._arm_pick(kind, feature)
        pd = self.combat.pending_decision()
        idx = pd.ctx.reactor_idx if pd.active else -1
        agents = self.bm.placed_agents
        name = agents[idx].name if 0 <= idx < len(agents) else "?"
        self._combat_log_add(f"{name}: {prompt}")
        self._flush_combat_log()

    def _resolve_reaction_cell(self, cell):
        """Submit the parked Masterful Shots / Indomitable Teleport window with the clicked cell. An
        illegal cell re-prompts; the archer's own cell shoots in place (Masterful Shots) or stays put
        (Indomitable Teleport)."""
        kind = ("masterful_shots_cell" if self._picking("masterful_shots_cell")
                else "indomitable_teleport_cell")
        feature = self._pick_data(kind)
        pd = self.combat.pending_decision()
        if (feature not in self._REACTION_CELL_PICKS or not pd.active or
                pd.ctx.window not in (rpg.ReactionWindow.AfterAttack, rpg.ReactionWindow.AfterSave)):
            self._drop_pick(kind)   # stale arm: the window is gone
            self._reaction_cell_option_index = -1
            return
        _, valid, _, error = self._REACTION_CELL_PICKS[feature]
        origin = self.bm.placed_agents[pd.ctx.reactor_idx].origin
        own = cell.col == origin.col and cell.row == origin.row
        resp = rpg.ReactionResponse()
        if own and feature == "IndomitableTeleportPick":
            resp.option = next((i for i, o in enumerate(pd.ctx.options)
                                if o.kind == rpg.ReactionOptionKind.Skip), -1)
        elif not valid(self, pd, cell):
            self._combat_log_add(error)
            self._flush_combat_log()
            return   # keep the pick armed
        else:
            resp.option = self._reaction_cell_option_index
            resp.cell_col, resp.cell_row = cell.col, cell.row
        self._drop_pick(kind)
        self._reaction_cell_option_index = -1
        status = self.combat.submit_decision(self.bm, resp)
        self._flush_combat_log()
        self._mark_fog_dirty()   # the archer moved
        self._sync_spell_effect_cache()
        self._update_attack_overlay()
        if status == rpg.FlowStatus.AwaitingDecision:
            self._show_pending_reaction_menu()
        else:
            self._reaction_finish()

    def _resolve_shadowy_dodge_cell(self, cell):
        """Submit the parked Shadowy Dodge teleport with the clicked cell. A click on the Ranger's own
        cell stays put; an illegal cell re-prompts."""
        pd = self.combat.pending_decision()
        if not pd.active or pd.ctx.window != rpg.ReactionWindow.AfterAttack:
            self._drop_pick("shadowy_dodge_cell")   # stale arm: the window is gone
            self._shadowy_dodge_option_index = -1
            return
        idx = pd.ctx.reactor_idx
        origin = self.bm.placed_agents[idx].origin
        resp = rpg.ReactionResponse()
        if cell.col == origin.col and cell.row == origin.row:
            resp.option = next((i for i, o in enumerate(pd.ctx.options)
                                if o.kind == rpg.ReactionOptionKind.Skip), -1)
        elif not self.combat.is_shadowy_dodge_destination(self.bm, idx, cell):
            self._combat_log_add("Shadowy Dodge: pick an unoccupied cell you can see within 30 ft.")
            self._flush_combat_log()
            return   # keep the pick armed
        else:
            resp.option = self._shadowy_dodge_option_index
            resp.cell_col, resp.cell_row = cell.col, cell.row
        self._drop_pick("shadowy_dodge_cell")
        self._shadowy_dodge_option_index = -1
        status = self.combat.submit_decision(self.bm, resp)
        self._flush_combat_log()
        self._mark_fog_dirty()   # the teleport moved the token
        self._sync_spell_effect_cache()
        self._update_attack_overlay()
        if status == rpg.FlowStatus.AwaitingDecision:
            self._show_pending_reaction_menu()
        else:
            self._reaction_finish()

    def _vitality_in_range(self, src: int, target: int) -> bool:
        """10 ft (2-cell) footprint Chebyshev check, mirroring C++ threateningAgents(src, 2)."""
        if not (0 <= src < len(self.bm.placed_agents)) or src == target:
            return False
        d = self._footprint_dist_ft(src, target)
        return 0 <= d <= 10

    def _resolve_vitality_target(self, target_idx: int):
        """Submit the parked Vitality of the Tree response with the clicked target, then resume the
        turn-start flow (which completes the window). Re-prompts on an invalid/out-of-range pick so
        the once-per-turn grant isn't wasted."""
        pd = self.combat.pending_decision()
        src = pd.ctx.source_idx if pd.active else -1
        agents = self.bm.placed_agents
        print(f"[VITALITY] resolve target={target_idx}, pd.active={pd.active}, src={src}, "
              f"window={pd.ctx.window if pd.active else 'n/a'}, "
              f"in_range={self._vitality_in_range(src, target_idx)}")
        # If the parked window is gone (turn moved on / resolved elsewhere), this flag is stale —
        # disarm instead of re-prompting forever. The turn-start reset is the primary guard; this
        # catches a stale click mid-turn before the next turn starts.
        if not pd.active or pd.ctx.window != rpg.ReactionWindow.OnTurnStartNearby or src < 0:
            print("[VITALITY] no live OnTurnStartNearby window — disarming stale target-pick")
            self._drop_pick("vitality_target")
            self._vitality_option_index  = -1
            return
        if (target_idx == src or not self._vitality_in_range(src, target_idx)
                or not (0 <= target_idx < len(agents))
                or self.combat.get_agent_stats(self.bm, target_idx).hp_cur <= 0):
            self._combat_log_add("Pick a living creature within 10 ft (or choose Skip).")
            self._flush_combat_log()
            return  # keep the vitality_target pick armed for another click
        self._drop_pick("vitality_target")
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

    def _ask_actor(self, actor_idx, kind, title, pairs, *, owner=None, render=None,
                   parent=None, anchor=None, on_cancel=None, cancellable=True):
        """Open a prompt on the bus, anchored at a token and owned by its controller.

        This is M1 Step 3's mechanical replacement for the two lines every call site
        used to end with: an ``_agent_screen_pos`` anchor, then a direct ``show`` on the
        shared ``ContextMenu`` widget with the options list and the screen size.

        The popup is the same widget at the same anchor with the same rows in the same
        order — ``ContextMenuRenderer`` rebuilds exactly that items list. What changes is
        that the choice now has an id, an owner and a wire projection, and the click goes
        ``ContextMenu.handle -> bus.choose -> authorize -> the same callback``.

        ``owner`` is the one field that needs thought per site (Step 0.2): it defaults to
        the actor's controller, which is right for every prompt the acting creature
        answers itself, and is passed explicitly where it is not — the defender
        reactions of G3, and the DM-authoring menus, which take ``DM_PRINCIPAL_ID``.

        ``cancellable`` is Envelope 4's display hint, passed through: False tells a
        remote client not to draw Cancel. The DM console ignores it.
        """
        owner = self._prompt_owner(actor_idx) if owner is None else owner
        return self.prompts.ask(
            actor_idx=actor_idx,
            owner=owner,
            kind=kind,
            title=title,
            options=options_from_pairs(pairs),
            deadline=self._reaction_deadline(kind, owner, on_cancel),
            parent=parent,
            render=render,
            anchor=self._agent_screen_pos(actor_idx) if anchor is None else anchor,
            cancellable=cancellable,
            on_cancel=on_cancel)

    def _reaction_deadline(self, kind, owner, on_cancel):
        """The ``deadline`` a new prompt carries: D-M5-7's rule, in one place.

        A deadline goes only on a ``reaction`` prompt that a player owns. Action and target
        prompts never get one, because expiry must never end a player's turn and the DM is
        the timeout there. The DM's own reactions never get one either, because the DM is
        sitting at the console the prompt is drawn on.

        Expiry runs ``on_cancel`` (`PromptBus.expire`), so a prompt with no ``on_cancel``
        gets no deadline: skipping it would run nothing, and a prompt that waits for the DM
        is better than one that vanishes and leaves the attack it interrupted parked.
        """
        if (kind != "reaction" or owner == DM_PRINCIPAL_ID or on_cancel is None
                or self.reaction_timeout_s is None):
            return None
        return time.monotonic() + self.reaction_timeout_s

    def _cycle_reaction_timeout(self):
        """The session row's timer button: the next of `REACTION_TIMEOUT_CHOICES_S`.

        It applies to the next reaction prompt. One already live keeps the deadline it was
        asked with, which its owner has already been shown."""
        choices = REACTION_TIMEOUT_CHOICES_S
        cur = self.reaction_timeout_s
        i = choices.index(cur) if cur in choices else choices.index(REACTION_TIMEOUT_DEFAULT_S)
        self.reaction_timeout_s = choices[(i + 1) % len(choices)]

    def _ask_dm(self, kind, title, pairs, *, anchor=None, actor_idx=-1,
                parent=None, on_cancel=None, render=None):
        """``_ask_actor`` for a menu only the DM may ever answer.

        Step 0.2 marks the map right-click and top-bar menus DM-authoring and never
        remoted; they go on the bus anyway, because the bus — not the widget — is what
        ``authorize()`` reads, and because a scripted test drives them the same way it
        drives a combat prompt. ``owner`` is pinned to ``DM_PRINCIPAL_ID`` rather than
        derived, so seating a player on a token can never hand them the authoring tools.

        ``render="titled"`` draws the title as a header row. A confirm whose options
        are bare verbs ("Overwrite" / "Cancel") needs it, or the DM sees the buttons
        without the question.
        """
        return self._ask_actor(actor_idx, kind, title, pairs, owner=DM_PRINCIPAL_ID,
                               parent=parent, anchor=anchor or (100, 100),
                               on_cancel=on_cancel, render=render)

    def _agent_name(self, agent_idx: int) -> str:
        """Display name for a token index, used by prompt titles. A remote player sees only
        the title, so every prompt names its creature; out of range folds to "?" rather than
        raising, because composing a title must never be what breaks a turn."""
        agents = self.bm.placed_agents
        return agents[agent_idx].name if 0 <= agent_idx < len(agents) else "?"

    def _agent_screen_pos(self, agent_idx: int) -> tuple:
        """Screen position of a token's cell centre — the anchor every prompt opens at.

        It has to agree with what the map draws, so it goes through `_cell_to_screen`
        (real grid-line positions, `map_scale`, pan) and takes the midpoint of the cell's
        own two corners rather than half a nominal `cell_pixel_size`: that is the drawn
        centre even where the detected grid is uneven, and it inherits `_cell_to_screen`'s
        clamp for a token saved outside the current grid.

        The old form multiplied the cell index by `cell_pixel_size` and ignored scale and
        pan entirely, which put all 82 `_ask_actor`/`_ask_dm` popups at an unpanned,
        unzoomed position — off by a whole cell at this map's fit-to-window scale alone.
        """
        agents = self.bm.placed_agents
        if not (0 <= agent_idx < len(agents)):
            return (100, 100)
        o = agents[agent_idx].origin
        x0, y0 = self._cell_to_screen(o.col, o.row)
        x1, y1 = self._cell_to_screen(o.col + 1, o.row + 1)
        return ((x0 + x1) // 2, (y0 + y1) // 2)


    def commit_move(self, idx: int, cell, move_type, principal: str) -> bool:
        """Move agent `idx` to `cell` by `move_type`, as `principal` (D-M5-4).

        The one place a combat move starts. The DM's drag release reaches it with
        `DM_PRINCIPAL_ID`; a player's Move prompt reaches it with the player's id. It asks
        `authorize(CONTROL_TOKEN)` over the mover, as `perform` does for actions, and
        refuses a creature whose Speed is 0. Otherwise the engine's `begin_move` runs, so
        opportunity attacks park and resume through `_show_pending_reaction_menu` exactly
        as they always have. Reachability is the caller's check: the drag validates
        against `_reach_set`, the Move prompt against its own `cells`.

        Returns False when the move was refused or failed, True once it has started.
        """
        if not self.roster.authorize(self.roster.get(principal),
                                     net_roster.Action.CONTROL_TOKEN,
                                     net_roster.TokenTarget(idx)):
            return False
        # Calculate Manhattan distance moved (for running jump qualification)
        ag_old = self.bm.placed_agents[idx]
        dist_moved = abs(cell.col - ag_old.origin.col) + abs(cell.row - ag_old.origin.row)
        dist_moved *= 5  # Each cell = 5 feet

        # Compute Chebyshev distance (D&D 5e diagonal = 5 ft).
        print(f"[Movement] Attempting to move agent {idx} to ({cell.col},{cell.row}) using {move_type}")
        # Debug: check terrain types along the path
        print(f"[Movement] Terrain at dest: {self.bm.get_terrain_type(cell)}")

        # Check if agent can move at all (Speed = 0 check)
        agents = self.bm.placed_agents
        moving_agent = agents[idx]
        can_move = self.combat.can_agent_move(self.bm, idx)

        if not can_move:
            # Speed = 0, no movement possible, no OA
            move_success = False
            print(f"[Movement] Move result: {move_success}")
            self._combat_log_add(f"{moving_agent.name}: movement blocked — Speed = 0")
            self._update_reach()
            self._update_attack_overlay()
            return False
        # In combat, the C++ engine owns Opportunity-Attack detection AND
        # resolution via the flow-checkpoint API (begin_move -> pending_decision
        # -> submit_decision). It does per-creature /
        # per-step provoke and commits the move itself. Out of combat, just move.
        self._reaction_mover_idx  = idx
        self._reaction_dist_moved = dist_moved
        self._reaction_finish     = lambda: self._after_move_committed(self._reaction_mover_idx)
        if self.combat_active:
            status = self.combat.begin_move(self.bm, idx, cell, move_type)
            self._flush_combat_log()
            if status == rpg.FlowStatus.AwaitingDecision:
                # Engine parked at an OA checkpoint — render the menu; the click
                # routes back through submit_decision, which resumes the move.
                self._show_pending_reaction_menu()
            else:
                self._after_move_committed(idx)
            return True
        move_success = self.combat.move_agent(self.bm, idx, cell, move_type)
        print(f"[Movement] Move result: {move_success}")
        self._flush_combat_log()
        if move_success:
            self._after_move_committed(idx)
            return True
        print(f"[Movement] Move failed - likely blocked by terrain")
        self.selected_idx = idx
        self._update_reach()
        self._update_attack_overlay()
        return False

    def _after_move_committed(self, idx: int):
        """Refresh GUI state after the engine commits a (possibly OA-interrupted) move.

        The engine (begin_move/submit_decision) has already performed the actual movement and
        resolved any opportunity attacks; this only syncs render caches, budgets, slip/hidden,
        and overlays. Replaces the old _complete_pending_move."""
        agents = self.bm.placed_agents
        if idx < 0 or idx >= len(agents):
            return
        ag = agents[idx]
        self._play_human_moves()   # M4b B-6: slide it, and stream it to the players
        self._mark_fog_dirty()   # any creature moving can change what the party sees
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
        self.last_movement_dist    = getattr(self, "_reaction_dist_moved", 0)
        self.selected_idx          = idx
        self._update_reach()
        self._update_attack_overlay()
        # A committed legendary Dash resolves that action; re-offer the creature (it may Dash again
        # or pass) and resume draining the legendary-action queue.
        if self._legendary_move_active and idx == self._legendary_actor:
            self._legendary_move_active = False
            app_initiative.after_legendary_action(self, idx)

    # FLAG: Move to C++
    def _consume_cast_slot(self, slot: str, caster_idx: int, spell=None):
        return app_spells.consume_cast_slot(self, slot, caster_idx, spell)

    def _choose_summon_form(self, spell_name: str, block: dict):
        return app_summons.choose_summon_form(self, spell_name, block)

    def _resolve_summon(self, cell):
        return app_summons.resolve_summon(self, cell)

    def _spawn_summon(self, caster_idx: int, sp, monster: str, spirit, slot_level: int, cell,
                      no_conc: bool = False) -> int:
        return app_summons.spawn_summon(self, caster_idx, sp, monster, spirit, slot_level, cell, no_conc)

    def _auto_summon_fey(self, idx: int) -> int:
        return app_summons.auto_summon_fey(self, idx)

    def _my_duplicates(self, idx: int) -> list:
        return app_summons.my_duplicates(self, idx)

    def _resolve_invoke_duplicity(self, cell):
        return app_summons.resolve_invoke_duplicity(self, cell)

    # ── Beast Master: Primal Companion (L3) ─────────────────────────────────
    def _find_companion_idx(self, ranger_idx: int) -> int:
        return app_summons.find_companion_idx(self, ranger_idx)

    def _dismiss_companion(self, ranger_idx: int, companion_idx: int):
        return app_summons.dismiss_companion(self, ranger_idx, companion_idx)

    def _summon_companion(self, ranger_idx: int, form: str):
        return app_summons.summon_companion(self, ranger_idx, form)

    # ── Pact of the Chain (Warlock invocation 18): attacking familiar ──────────
    def _find_familiar_idx(self, warlock_idx: int) -> int:
        return app_summons.find_familiar_idx(self, warlock_idx)

    def _dismiss_familiar(self, warlock_idx: int, familiar_idx: int):
        return app_summons.dismiss_familiar(self, warlock_idx, familiar_idx)

    def _summon_familiar(self, warlock_idx: int, form: str):
        return app_summons.summon_familiar(self, warlock_idx, form)

    # ── Chromatic Orb leap chain (GUI picker) ──────────────────────────────────
    def _footprint_dist_ft(self, a_idx: int, b_idx: int) -> int:
        """Chebyshev footprint distance in feet (5 ft / cell), or -1 for bad indices.

        Delegates to the engine's rpg.footprint_distance so adjacency/reach math is
        computed in exactly ONE place (combat_internal.hpp). It measures the gap over
        ALL cells in both footprints, so a large creature counts as adjacent whenever
        ANY of its occupied cells is (e.g. Cleave vs a Large+ target). Do not re-derive
        the formula here — that parallel copy drifted from the engine and broke Cleave."""
        agents = self.bm.placed_agents
        if not (0 <= a_idx < len(agents) and 0 <= b_idx < len(agents)):
            return -1
        s = agents[a_idx]; o = agents[b_idx]
        return rpg.footprint_distance(s.origin, s.size, o.origin, o.size) * 5

    def _can_reach_through(self, a_idx: int, b_idx: int) -> bool:
        """True when nothing solid stands between two creatures: the engine's line of sight,
        which an edge wall on a drawn map blocks even between adjacent cells. Pair it with
        _footprint_dist_ft for anything that physically reaches the other creature."""
        agents = self.bm.placed_agents
        if not (0 <= a_idx < len(agents) and 0 <= b_idx < len(agents)):
            return False
        s = agents[a_idx]; o = agents[b_idx]
        return self.bm.has_line_of_sight(s.origin, s.size, o.origin, o.size)

    def _finalize_chromatic_cast(self):
        return app_spells.finalize_chromatic_cast(self)

    def _cancel_chromatic_chain(self):
        return app_spells.cancel_chromatic_chain(self)

    @staticmethod
    def _grave_return_to_life(stats) -> bool:
        """Grave Domain Circle of Mortality (L3): Spare the Dying can be cast as a Bonus Action."""
        return (stats.has_class(rpg.CharacterClass.Cleric)
                and stats.cleric_subclass == rpg.ClericSubclass.GraveDomain
                and stats.class_level(rpg.CharacterClass.Cleric) >= 3)

    def _twinned_single_armed(self, sp, caster_idx: int) -> bool:
        return app_spells.twinned_single_armed(self, sp, caster_idx)

    def _resolve_corpse_spell(self, cell):
        return app_spells.resolve_corpse_spell(self, cell)


    def _finish_animate_dead(self, caster_idx, corpse_idx, cell, undead, slot, slot_level, free_cast):
        return app_spells.finish_animate_dead(self, caster_idx, corpse_idx, cell, undead, slot, slot_level, free_cast)

    def _multi_target_finishable(self) -> bool:
        return app_spells.multi_target_finishable(self)

    def _finish_multi_target_spell(self):
        return app_spells.finish_multi_target_spell(self)

    def _resolve_spell_cast(self, target_idx: int | None):
        return app_spells.resolve_spell_cast(self, target_idx)

    def _finish_cast(self):
        return app_spells.finish_cast(self)


    def _resolve_wild_magic_surge(self, caster_idx: int, effect: int, tides_expended: bool):
        return app_spells.resolve_wild_magic_surge(self, caster_idx, effect, tides_expended)


    def _arm_bewitching_misty(self, caster_idx: int):
        return app_spells.arm_bewitching_misty(self, caster_idx)

    def _decline_bewitching_offer(self):
        return app_spells.decline_bewitching_offer(self)

    def _arm_beguiling_target_pick(self, caster_idx: int):
        return app_spells.arm_beguiling_target_pick(self, caster_idx)

    def _decline_beguiling_offer(self):
        return app_spells.decline_beguiling_offer(self)


    def _cancel_beguiling(self):
        return app_spells.cancel_beguiling(self)

    def _pending_spell(self):
        return app_spells.pending_spell(self)

    def _pending_spell_is_wall(self) -> bool:
        return app_spells.pending_spell_is_wall(self)

    # FLAG: Move to C++
    def _resolve_spell_cast_aoe(self, cell):
        return app_spells.resolve_spell_cast_aoe(self, cell)

    # FLAG: Move to C++

    # FLAG: Move to C++
    def _area_template(self, caster_idx: int, sp, center) -> list:
        return app_spells.area_template(self, caster_idx, sp, center)

    def _spell_to_dict(self, agent_idx: int, spell_idx: int, s) -> dict:
        """Convert C++ Spell object to dict, including metadata."""
        geo = s.geometry.name
        uses_radius = geo in ("Sphere", "Cone")
        # Line, Square and Rectangle all store their extent in width/length. A
        # narrow `geo == "Line"` test dropped them for Square/Rectangle, so a
        # saved Square reloaded with the width=5/length=30 defaults — a 1-cell
        # line (this is how Hypnotic Pattern silently became a line on reload).
        uses_line   = geo in ("Line", "Square", "Rectangle")
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
            cond_dict = {
                "condition_name": cond.condition_name,
                "condition_duration": cond.condition_duration,
                "save_repeat_turns": cond.save_repeat_turns,
                "save_ability": cond.save_ability.name,
                "save_dc_ability": cond.save_dc_ability.name,
                "on_damage": _on_dmg_name.get(cond.on_damage),
            }
            # Hold Person / Hold Monster: end-of-turn save timing must survive a save/reload
            # (hasattr-guarded so an older compiled module still serializes cleanly).
            if getattr(cond, "save_at_end_of_turn", False):
                cond_dict["save_at_end_of_turn"] = True
            conditions.append(cond_dict)

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
            "cantrip_dice_per_tier": s.cantrip_dice_per_tier,
            "requires_concentration": s.requires_concentration,
            "requires_los":          s.requires_los,
            "check_los_on_center":   s.check_los_on_center,
            "opens_doors":           s.opens_doors,
            "dispels_magic":         getattr(s, "dispels_magic", False),
            "requires_sight":        s.requires_sight,
            "moves_with_caster":     s.moves_with_caster,
            "grants_advantage_aura": s.grants_advantage_aura,
            "selective_targeting":   s.selective_targeting,
            "excludes_caster":       s.excludes_caster,
            "effects_on_begin_turn": s.effects_on_begin_turn,
            "effects_on_end_turn":   s.effects_on_end_turn,
            "effects_on_enter":      s.effects_on_enter,
            "resource_name":         s.resource_name or None,
            "resource_cost":         s.resource_cost,
            "teleportation_spell":   s.teleportation_spell,
            "max_teleport_targets":  s.max_teleport_targets,
            "teleport_range_ft":     s.teleport_range_ft,
            "revives_dead":          getattr(s, "revives_dead", False),
            "animates_dead":         getattr(s, "animates_dead", False),
            "binds_creature":        getattr(s, "binds_creature", False),
            "ward_blocks_living":    getattr(s, "ward_blocks_living", False),
            "creates_wall_terrain":  getattr(s, "creates_wall_terrain", False),
            "conditions":            conditions,
            # N/day + Recharge (breath weapons). See helpers._dict_to_spell.
            "uses_max":              s.uses_max,
            "uses_remaining":        s.uses_remaining,
            "recharge_min":          s.recharge_min,
            "expended":              s.expended,
        }

    # NOTE: dict -> rpg.Spell conversion lives in helpers._dict_to_spell (imported above)
    # as the single source of truth. There used to be a near-identical copy here; new
    # spell fields were only ever added to one side, which silently dropped `school` and
    # later `light_level` from the other. All callers use the free function directly.

    def _sync_page_size(self):
        """Write the live grid's size onto the showing dungeon page (and the manifest)
        when they differ, so a re-gridded map's footprint isn't the old grid's."""
        page = self.dungeon_page
        if not (isinstance(self.store, CampaignStore) and page is not None
                and self._dungeon_manifest_path):
            return
        cols = int(getattr(self.bm, "grid_cols", 0) or 0)
        rows = int(getattr(self.bm, "grid_rows", 0) or 0)
        if cols and rows and (page.cols, page.rows) != (cols, rows):
            page.cols, page.rows = cols, rows
            self.dungeon.save(self._dungeon_manifest_path)

    def _open_cell_near(self, col: int, row: int, size: int,
                        taken: set[tuple[int, int]] | None = None) -> tuple[int, int]:
        """(col, row) itself when a size×size token fits there terrain-wise, else the nearest
        cell (Chebyshev rings) that does; the original cell when the map has none. A cell
        off the grid searches from the nearest edge cell, so a far-off save still lands.
        ``taken`` cells (other creatures' footprints) are avoided too."""
        cols, rows = self.bm.grid_cols, self.bm.grid_rows
        taken = taken or set()

        def ok(c, r):
            return (0 <= c <= cols - size and 0 <= r <= rows - size
                    and not self.bm.is_blocked(rpg.Cell(c, r), size)
                    and all((c + dc, r + dr) not in taken
                            for dc in range(size) for dr in range(size)))
        if ok(col, row):
            return col, row
        col = min(max(col, 0), max(0, cols - size))
        row = min(max(row, 0), max(0, rows - size))
        if ok(col, row):
            return col, row
        for ring in range(1, max(cols, rows) + 1):
            for r in range(row - ring, row + ring + 1):
                for c in range(col - ring, col + ring + 1):
                    if max(abs(c - col), abs(r - row)) == ring and ok(c, r):
                        return c, r
        return col, row

    def _placeable_cell(self, size: int) -> tuple[int, int]:
        """The first cell (row-major) an agent of `size` could be placed on, for a raw save
        of a tombstone (see `_save_agents`). (0, 0) on a map with none, which the load
        would skip; the snapshot's basis check then refuses the resume rather than
        misapplying it."""
        for r in range(self.bm.grid_rows - size + 1):
            for c in range(self.bm.grid_cols - size + 1):
                if not self.bm.is_blocked(rpg.Cell(c, r), size):
                    return c, r
        return 0, 0

    # ── Dungeon generation and import (gui/app_dungeon_gen.py, APP_REFACTOR_PLAN A5) ──
    def _import_ddb_character(self):
        return app_dungeon_gen.import_ddb_character(self)

    def _on_generate_terrain(self):
        return app_dungeon_gen.on_generate_terrain(self)

    def _generation_targets(self, params, *, multi: bool, agents_path=None) -> list:
        return app_dungeon_gen.generation_targets(self, params, multi=multi, agents_path=agents_path)

    def _generated_base(self) -> str:
        return app_dungeon_gen.generated_base(self)

    def _modal_generate_terrain(self) -> dict | None:
        return app_dungeon_gen.modal_generate_terrain(self)

    def _modal_select_items(self, title: str, items: list[str], selection: set[str] | list, multi_select: bool=True) -> None:
        return app_dungeon_gen.modal_select_items(self, title, items, selection, multi_select)

    def _modal_generate_dungeon(self, populate: bool = False,
                                generate: bool = False) -> dict | None:
        return app_dungeon_gen.modal_generate_dungeon(self, populate=populate,
                                                      generate=generate)

    def _modal_pick_mobs(self, bestiary, cr, types, languages, boss_on, excluded: set, boss: list) -> dict | None:
        return app_dungeon_gen.modal_pick_mobs(self, bestiary, cr, types, languages, boss_on, excluded, boss)

    def _mob_picker_layout(self) -> dict:
        return app_dungeon_gen.mob_picker_layout(self)

    def _modal_text_prompt(self, title: str, prompt: str, ok_label: str = "Import") -> str | None:
        """Blocking single-line text prompt. Returns the entered text, or None on cancel."""
        sw, sh = self.screen.get_size()
        W, H = min(560, sw - 80), 180
        box = pygame.Rect((sw - W) // 2, (sh - H) // 2, W, H)
        inp = TextInput(pygame.Rect(box.x + 20, box.y + 86, W - 40, 32), font=self.font_md)
        inp.active = True
        ok = Button(pygame.Rect(box.right - 210, box.bottom - 46, 90, 32), ok_label,
                    (60, 110, 70), (80, 140, 90), font=self.font_md)
        cancel = Button(pygame.Rect(box.right - 110, box.bottom - 46, 90, 32), "Cancel",
                        (110, 60, 60), (150, 80, 80), font=self.font_md)
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        while True:
            self._pump_net()      # D-M4-3: a modal is not a quiescent point, and must not stall the queue
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
            self._pump_net()      # D-M4-3: a modal is not a quiescent point, and must not stall the queue
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    return
                if ok.clicked(event):
                    return
            render()
            self.clock.tick(60)

    def _ladder_at(self, cell):
        """Index of the ladder occupying ``cell`` (an rpg.Cell), or -1."""
        col, row = cell.col, cell.row
        for i, lad in enumerate(self._ladders):
            if any(c[0] == col and c[1] == row for c in lad["cells"]):
                return i
        return -1

    def _toggle_grid_sample_mode(self):
        """Enter/leave 'sample a tile' mode for defining a manual uniform grid.

        While active, the next left-drag on the map outlines a single tile; on
        release the grid is rebuilt from that tile's size (square) and corner.
        """
        if self.combat_active and not self._grid_sample_mode:
            self._flash_status("Finish combat before setting a new grid.")
            return
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
        last_ft = int((self._manual_grid or {}).get("square_ft", 5))
        self._grid_span_dialog.show(self._on_grid_span, square_ft=last_ft)

    def _on_grid_span(self, result):
        """Callback from GridSpanDialog: result is (cols, rows, square_ft), or None.

        Divides the sampled box by the spanned square count to get the drawn square's
        size, then by the map scale (square_ft / 5) to get the engine cell, which is
        always 5 ft: a 10-ft-per-square map gets 2×2 cells per drawn square. Then rebuilds
        the grid. Replaces auto-detection, so wall auto-detect is forced off and old
        (now-misindexed) terrain regions are dropped.
        """
        box = self._pending_grid_box
        self._pending_grid_box = None
        if result is None or box is None:
            self._combat_log_add("Grid sample cancelled.")
            return

        cols_spanned, rows_spanned, square_ft = result
        x0, y0, w, h = box
        square_px = (w / cols_spanned + h / rows_spanned) / 2.0           # drawn square
        per_side  = square_ft // 5                                        # cells per side
        cell_px   = int(round(square_px / per_side))                      # 5-ft cell
        anchor_x = int(round(x0))
        anchor_y = int(round(y0))
        if cell_px <= 0:
            self._combat_log_add("Grid sample too small — cancelled.")
            return
        # A new grid drops every terrain region and rewrites the terrain file; the
        # creatures are saved too, to bring any the new grid leaves off it back on.
        self._confirm_overwrite(
            [self._save_path, self._terrain_path], "Set grid",
            lambda: self._apply_grid_span(cell_px, anchor_x, anchor_y, square_ft, square_px,
                                          per_side),
            on_cancel=lambda: self._combat_log_add("Grid sample cancelled."))

    def _apply_grid_span(self, cell_px, anchor_x, anchor_y, square_ft, square_px, per_side):
        """_on_grid_span once any overwrite is confirmed."""
        # Persist the creatures before the grid changes: the reload below puts any the
        # new grid no longer covers back on it (see _load_agents) instead of leaving
        # them stranded off the map.
        self._save_agents()
        try:
            self.bm.set_uniform_grid(cell_px, anchor_x, anchor_y)
        except Exception as e:
            self._combat_log_add(f"Grid sample failed: {e}")
            return

        self._manual_grid = {"cell_px": cell_px, "anchor": [anchor_x, anchor_y],
                             "square_ft": square_ft}
        self._terrain_regions = []
        self._walls_enabled = False
        self.btn_toggle_walls.text = self._walls_label()
        # Seeds and edge overrides name cells, so they don't survive a new grid.
        dropped = bool((self._detection or {}).get("outside_seeds")) or bool(self._edge_overrides)
        if self._detection:
            self._detection["outside_seeds"] = []
        self._edge_overrides = None
        self._edge_review = None
        self._edges_carried_from = None   # the cells were renumbered: carry again next time
        self._build_overlay()
        self._save_terrain()
        self._sync_page_size()
        self._load_agents()
        self._save_agents()
        if dropped:
            self._flash_status("New grid: outside seeds and edge overrides cleared.")
        scale = f" (1 square = {square_ft} ft → {per_side}×{per_side} cells)" if per_side > 1 else ""
        self._combat_log_add(
            f"Manual grid set: {self.bm.grid_cols}×{self.bm.grid_rows} cells, "
            f"{cell_px}px/cell{scale}.")
        # The engine's cell size is a whole pixel count, so a drawn square that doesn't
        # divide evenly (e.g. 50px at 15 ft → 16.67px) leaves the grid drifting off the
        # drawn lines across the map. Say how far, so the DM can re-sample if it matters.
        drift = abs(cell_px * per_side - square_px) / per_side * self.bm.grid_cols
        if drift >= cell_px / 4:
            self._combat_log_add(
                f"Grid note: {square_px:.1f}px ÷ {per_side} isn't a whole pixel; the grid "
                f"drifts ~{drift:.0f}px off the drawn lines across the map.")

    # ── Terrain… → Rescale Image to Grid… ──────────────────────────────────
    def _rescale_image_to_grid(self):
        """Measure the drawn squares against the manual grid and offer to re-render the
        map image so they are whole pixels (see gui/grid_rescale.py). The cell size stays
        an integer; the image changes instead, and every cell keeps its index."""
        if self.combat_active:
            self._flash_status("Finish combat before rescaling the map.")
            return
        if not self._manual_grid:
            self._flash_status("Rescale needs a manual grid: Set Grid… first.")
            return
        # Measuring saves the live agents + terrain first: ask before overwriting them.
        self._confirm_overwrite([self._save_path, self._terrain_path], "Rescale image",
                                self._rescale_image_measured,
                                anchor=(self.btn_terrain.rect.x, self.btn_terrain.rect.y))

    def _rescale_image_measured(self):
        """_rescale_image_to_grid once any overwrite is confirmed."""
        # The image and terrain are rewritten from disk and reloaded: save what's live.
        self._save_agents()
        self._save_terrain()
        try:
            p = grid_rescale.plan(self._map_path, self._terrain_path)
        except Exception as e:                      # noqa: BLE001 — report, keep the map
            self._flash_status(f"Couldn't measure the grid: {e}")
            return
        if "skip" in p:
            self._flash_status(f"Rescale: {p['skip']}.")
            return
        (px, py), (dx, dy) = p["period"], p["drift"]
        measured = (f"Squares {px:.2f}×{py:.2f}px (want {p['nominal']}): "
                    f"grid drifts {dx:.0f}×{dy:.0f}px across the map")
        self._combat_log_add(measured + ".")
        if not p["needed"]:
            self._flash_status(measured + " — already fits.")
            return
        sx, sy = p["scale"]
        self._ask_dm("action", measured, [
            (f"Rescale image ×{sx:.4f} × {sy:.4f}", lambda: self._apply_rescale(p)),
            ("Cancel", lambda: None),
        ], anchor=(self.btn_terrain.rect.x, self.btn_terrain.rect.y), render="titled")

    def _apply_rescale(self, p):
        """Rewrite the image + terrain (backups in pre_rescale/), then reload the page."""
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(p["png"])), "pre_rescale")
        page = self.dungeon_page if self.dungeon is not None else None
        try:
            if page is not None and self._dungeon_manifest_path:
                grid_rescale._backup(self._dungeon_manifest_path, backup_dir)
            r = grid_rescale.apply(p, backup_dir)
        except Exception as e:                      # noqa: BLE001
            self._flash_status(f"Rescale failed: {e}")
            return
        if page is not None:
            page.cols, page.rows = r["cols"], r["rows"]
            if self._dungeon_manifest_path:
                self.dungeon.save(self._dungeon_manifest_path)
            self.dungeon_page = None                # don't write the old scene back
            app_dungeon_pages.switch_to_page(self, page, force=True)
        else:
            self._load_map_png(self._map_path)
            self._load_terrain()
            self._load_lighting()
            self._load_spell_effects()
            self._load_agents()
            self._mark_fog_dirty()
        self._build_overlay()
        src = os.path.basename(r["source"])
        self._flash_status(f"Rescaled from {src} to {r['size'][0]}×{r['size'][1]} "
                           f"({r['cols']}×{r['rows']} cells). Old files in pre_rescale/.")

    def _apply_detection_params(self):
        """Point the engine's detector at this page's settings. Without a "detection"
        block, or with mode "mean", it is today's detector exactly; the drawn-map fields,
        the outside seeds and the edge overrides are then not read."""
        self._fill_detection_params(self.bm.params, self._detection, self._edge_overrides)

    @classmethod
    def _fill_detection_params(cls, p, detection, edge_overrides):
        """Write a terrain file's "detection" and "edge_overrides" into engine params
        ``p``. Shared by the live page and the reference floor of _maybe_carry_edges."""
        det = detection or {}
        if det.get("mode") != "dark_fraction":
            p.mode = rpg.DetectionMode.Mean
            p.outside_seeds, p.edge_add, p.edge_remove = [], [], []
            return
        p.mode = rpg.DetectionMode.DarkFraction
        p.dark_level = int(det.get("dark_level", 100))
        p.dark_fraction = float(det.get("dark_fraction", 1.0))
        p.edge_walls = bool(det.get("edge_walls", True))
        p.edge_fraction = float(det.get("edge_fraction", 0.3))
        p.edge_halfwidth_px = int(det.get("edge_halfwidth_px", 4))
        p.outside_seeds = [rpg.Cell(int(c[0]), int(c[1])) for c in det.get("outside_seeds", [])]
        ov = edge_overrides or {}
        p.edge_add = cls._parse_edges(ov.get("add", []))
        p.edge_remove = cls._parse_edges(ov.get("remove", []))

    # ── Carrying edges between floors ─────────────────────────────────────
    # The floors of one dungeon are drawn in the same style and sit on one global grid,
    # so a floor's outer walls and shafts mostly stack on the floor next to it. The first
    # time the terrain editor opens on a floor, it starts from the nearest edited floor's
    # final edges and marks the edges where this image's own detection disagrees.

    @staticmethod
    def _edge_set(bm):
        """The engine's static edge walls as {(c, r, "E"|"S")}."""
        return {(e.cell.col, e.cell.row, "E" if e.side == rpg.EdgeSide.East else "S")
                for e in bm.edge_walls}

    @staticmethod
    def _edge_in_grid(key, cols, rows):
        c, r, s = key
        if s == "E":
            return 0 <= c < cols - 1 and 0 <= r < rows
        return 0 <= c < cols and 0 <= r < rows - 1

    @staticmethod
    def _carry_ready(data):
        """True when a page's terrain file has what carrying needs: a manual grid,
        walls on, the Drawn detector and some edge edits of its own."""
        ov = data.get("edge_overrides") or {}
        return bool(data.get("manual_grid") and data.get("walls_enabled", True)
                    and (data.get("detection") or {}).get("mode") == "dark_fraction"
                    and (ov.get("add") or ov.get("remove")))

    def _carry_reference_pages(self, page):
        """[(page, terrain data)] for the nearest edited floor toward the entry floor:
        the pages on it that overlap ``page`` on the global grid and are _carry_ready.
        Floors with nothing edited are skipped; the entry floor itself has no reference."""
        entry = self.dungeon.entry_page() if self.dungeon else None
        if entry is None or page.z == entry.z:
            return []
        step = 1 if entry.z > page.z else -1
        z = page.z
        while z != entry.z:
            z += step
            found = []
            for p in self.dungeon.pages:
                if p.z != z or p.id == page.id:
                    continue
                if p.cols and page.cols and p.rows and page.rows and not (
                        p.gx < page.gx + page.cols and page.gx < p.gx + p.cols
                        and p.gy < page.gy + page.rows and page.gy < p.gy + p.rows):
                    continue
                try:
                    data = self.store.terrain(p)
                except ValueError:
                    continue
                if data is None:
                    continue
                if self._carry_ready(data):
                    found.append((p, data))
            if found:
                return found
        return []

    def _page_final_edges(self, page, data):
        """A page's final edge walls (detection + its overrides) in GLOBAL (X, Y),
        computed on a throwaway engine map of its own image so the live map is untouched.
        Floor regions are not applied (they only clear detected edges)."""
        png = page.png if os.path.isabs(page.png) else os.path.join(app_dungeon_pages.dungeon_dir(self), page.png)
        ref = rpg.BattleMap(png)
        mg = data["manual_grid"]
        ref.set_uniform_grid(int(mg["cell_px"]), int(mg["anchor"][0]), int(mg["anchor"][1]))
        self._fill_detection_params(ref.params, data.get("detection"),
                                    data.get("edge_overrides"))
        ref.detect_walls()
        return {(c + page.gx, r + page.gy, s) for (c, r, s) in self._edge_set(ref)}

    def _prune_edge_review(self):
        """Drop review edges with a blocked cell on BOTH sides (inside a thick wall, or
        outside the building): whether they are walls changes no movement or sight, so
        they aren't worth the DM's time. Their overrides are kept as carried."""
        if not self._edge_review:
            return
        blocked = {(c.col, c.row) for c in self.bm.disallowed_cells}

        def matters(e):
            c, r, s = int(e[0]), int(e[1]), e[2]
            other = (c + 1, r) if s == "E" else (c, r + 1)
            return not ((c, r) in blocked and other in blocked)

        self._edge_review[:] = [e for e in self._edge_review if matters(e)]

    def _maybe_carry_edges(self):
        """On a dungeon floor's first terrain edit, start from the nearest edited floor's
        edges (see _carry_reference_pages), moved through the page origins.

        The page keeps its own grid and runs its own detection; the carried edges become
        its edge overrides (added where detection missed them, removed where detection
        found an edge the reference floor doesn't have), and those disagreements become
        the blue review list. Runs once per page: ``edges_carried_from`` is saved.

        It never overwrites work already on the page: a page with edge edits of its own
        is skipped, and a page's own detection settings and Walls choice are kept. Only a
        page with no detection block at all borrows the reference's. The reference
        floors are only read. Before the first write the page's terrain file is copied to
        ``<file>.before_carry``."""
        page = self.dungeon_page
        if self.dungeon is None or page is None or self._edges_carried_from:
            return
        ov = self._edge_overrides or {}
        if ov.get("add") or ov.get("remove"):
            return                          # this floor already has edits of its own
        if not self._manual_grid:
            return                          # cells aren't fixed until Set Grid
        refs = self._carry_reference_pages(page)
        if not refs:
            return
        carried_global = set()
        for p, data in refs:
            try:
                carried_global |= self._page_final_edges(p, data)
            except Exception as e:          # noqa: BLE001 — a bad reference must not block editing
                self._flash_status(f"Couldn't read floor '{p.id}' edges: {e}")
                return
        cols, rows = self.bm.grid_cols, self.bm.grid_rows
        carried = {(X - page.gx, Y - page.gy, s) for (X, Y, s) in carried_global}
        carried = {k for k in carried if self._edge_in_grid(k, cols, rows)}

        # This floor needs Walls ON and the Drawn detector for edges. A floor that has
        # chosen otherwise keeps its choice (no carry); one with no detection block yet
        # borrows the reference's settings, its outside seeds moved through the origins.
        own = self._detection is not None
        if own and (not self._walls_enabled or self._detection.get("mode") != "dark_fraction"):
            self._flash_status("Edges not carried: this floor's own settings aren't Walls ON "
                               "+ Drawn (Terrain… → Wall Detection…).")
            return
        if not own:
            p0, data0 = refs[0]
            det = json.loads(json.dumps(data0["detection"]))
            seeds = [[c + p0.gx - page.gx, r + p0.gy - page.gy]
                     for c, r in det.get("outside_seeds", [])]
            det["outside_seeds"] = [s for s in seeds if 0 <= s[0] < cols and 0 <= s[1] < rows]
            self._detection = det
            self._walls_enabled = True
            self.btn_toggle_walls.text = self._walls_label()

        if os.path.exists(self._terrain_path):
            try:
                shutil.copyfile(self._terrain_path, self._terrain_path + ".before_carry")
            except OSError:
                pass
        self._edge_overrides = {"add": [], "remove": []}
        self._redetect_walls()
        detected = {k for k in self._edge_set(self.bm) if self._edge_in_grid(k, cols, rows)}
        add = sorted(carried - detected)
        remove = sorted(detected - carried)
        self._edge_overrides = {"add": [list(k) for k in add],
                                "remove": [list(k) for k in remove]}
        self._edge_review = [list(k) for k in sorted(set(add) | set(remove))]
        self._edges_carried_from = [p.id for p, _ in refs]
        self._redetect_walls()
        self._prune_edge_review()
        self._build_overlay()
        self._save_terrain()
        self._flash_status(
            f"Edges from {', '.join(self._edges_carried_from)}: {len(carried)} carried, "
            f"{len(self._edge_review)} differ from this image (blue).")

    @staticmethod
    def _parse_edges(raw):
        """[[c, r, "E"|"S"], ...] from the terrain file → rpg.Edge list; skips bad entries."""
        out = []
        for e in raw or []:
            try:
                side = {"E": rpg.EdgeSide.East, "S": rpg.EdgeSide.South}[e[2]]
                out.append(rpg.Edge(rpg.Cell(int(e[0]), int(e[1])), side))
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        return out

    def _apply_floor_regions(self, regions=None):
        """Floor regions (the Floor brush) reopen the detected wall cells under them. They
        also clear an edge wall with Floor on both sides, and one between a Floor cell and a
        wall cell: that edge only repeats the wall cell, so a cleared staircase isn't left
        fenced in by its own rim. They run after detection and the outside flood, so a
        hand-cleared cell stays open across reload and re-detect. An edge the DM added
        with the Edge tool is kept: Floor clears what was detected, not what was drawn."""
        floor = set()
        for region in self._terrain_regions if regions is None else regions:
            if region.get("type") != "Floor":
                continue
            if region.get("width", 0) <= 0 or region.get("height", 0) <= 0:
                continue
            rng = self._pixel_rect_to_cells(region.get("x", 0), region.get("y", 0),
                                            region["width"], region["height"])
            if rng is None:
                continue
            c0, r0, c1, r1 = rng
            floor.update((c, r) for c in range(c0, c1 + 1) for r in range(r0, r1 + 1))
        if not floor:
            return
        for col, row in floor:
            self.bm.allow_cell(rpg.Cell(col, row))
        walls = {(c.col, c.row) for c in self.bm.disallowed_cells}
        added = set()
        if (self._detection or {}).get("mode") == "dark_fraction":
            added = {(int(e[0]), int(e[1]), e[2])
                     for e in (self._edge_overrides or {}).get("add", [])}
        for col, row in floor:
            for nb, cell, side in (((col + 1, row), (col, row), rpg.EdgeSide.East),
                                   ((col, row + 1), (col, row), rpg.EdgeSide.South),
                                   ((col - 1, row), (col - 1, row), rpg.EdgeSide.East),
                                   ((col, row - 1), (col, row - 1), rpg.EdgeSide.South)):
                key = (cell[0], cell[1], "E" if side == rpg.EdgeSide.East else "S")
                if (nb in floor or nb in walls) and key not in added:
                    self.bm.set_edge_wall(rpg.Cell(*cell), side, False)

    def _preview_floor_regions(self, regions):
        """Terrain editor callback: re-detect with the editor's (unsaved) regions, so a
        Floor box shows its effect while the editor is still open."""
        if any(r.get("type") == "Floor" for r in regions) or \
                any(r.get("type") == "Floor" for r in self._terrain_regions):
            self._redetect_walls(regions)

    def _redetect_walls(self, regions=None):
        """Re-run wall detection from a clean slate, in the terrain file's order: dark
        cells, edge walls, edge overrides, the outside flood (all in the engine), then
        Floor regions. Painted Wall/Chasm/Water terrain and doors are separate and kept.
        With walls off, every detected wall goes and the settings are kept unapplied."""
        self.bm.clear_walls()
        if not self._walls_enabled:
            return
        self._apply_detection_params()
        self.bm.detect_walls()
        self._apply_floor_regions(regions)

    def _open_wall_detection(self):
        """Terrain… → Wall Detection… (offered while Walls is ON). Every change in the
        dialog re-detects and redraws at once; Cancel puts the page's settings back."""
        original = dict(self._detection) if self._detection else None
        if original is not None:
            original["outside_seeds"] = [list(c) for c in original.get("outside_seeds", [])]

        def on_change(settings):
            self._detection = settings
            self._redetect_walls()
            self._build_overlay()

        def on_map_click(pos):
            if pos[0] >= self._panel_x():
                return
            cell = self._screen_to_cell(*pos)
            if cell is not None:
                self._wall_detect_dialog.toggle_seed(cell.col, cell.row)

        def on_close(settings):
            if settings is not None:
                # Saving writes the terrain file: ask first; Cancel puts the page back
                # as the dialog's own Cancel does.
                self._confirm_overwrite([self._terrain_path], "Wall detection",
                                        lambda: finish(settings),
                                        on_cancel=lambda: finish(None))
            else:
                finish(None)

        def finish(settings):
            if settings is None:
                self._detection = original
            elif original is None and settings.get("mode") != "dark_fraction":
                self._detection = None      # nothing was switched on: the file stays as it was
            else:
                self._detection = settings
            self._redetect_walls()
            self._build_overlay()
            if settings is not None:
                self._save_terrain()
                self._combat_log_add(
                    f"Wall detection saved ({len(self.bm.disallowed_cells)} blocked cells, "
                    f"{len(self.bm.edge_walls)} wall edges).")
            if self.selected_idx >= 0:
                self._update_reach()

        self._wall_detect_dialog.show(self._detection, on_change, on_map_click, on_close,
                                      self._panel_rect())
        self._build_overlay()       # seed markers

    def _walls_label(self) -> str:
        if not self._walls_enabled:
            return "Walls: OFF"
        return "Walls: ON" if self._walls_shown else "Walls: HIDDEN"

    def _toggle_walls(self):
        """Cycle auto-detected walls/obstacles ON → HIDDEN → OFF → ON.

        The detector occasionally mis-reads a map (the "janky walls" bug). Toggling
        OFF discards every auto-detected obstacle so only explicit terrain blocks
        movement; toggling ON re-runs detection from a clean slate. HIDDEN keeps the
        walls exactly as ON does (they block, the fog respects them) but draws no red
        wall lines. The choice is persisted in the terrain JSON so it survives a reload.
        """
        if self._walls_enabled and self._walls_shown:        # ON → HIDDEN: nothing re-detects
            self._walls_shown = False
            state = "hidden (still blocking)"
        else:                                                # HIDDEN → OFF, OFF → ON
            self._walls_enabled = not self._walls_enabled
            self._walls_shown = True
            self._redetect_walls()
            state = "on" if self._walls_enabled else "off"
        self.btn_toggle_walls.text = self._walls_label()
        self._build_overlay()       # redraw blocked/wall cells
        self._save_terrain()        # persist the preference
        n = len(self.bm.disallowed_cells)
        self._combat_log_add(f"Wall auto-detection turned {state} ({n} blocked cells).")

    def _load_spell_effects(self, path: str | None = None):
        """Load spell effect data from JSON file if it exists."""
        path = path or self._effects_path
        if os.path.exists(path):
            try:
                rpg.apply_spell_effect_configuration(self.bm, path)
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

    def _load_lighting(self, path: str | None = None):
        return app_lighting.load_lighting(self, path)

    def _lighting_done(self, editor):
        return app_lighting.lighting_done(self, editor)

    @staticmethod
    def _parse_light_level(s: str) -> 'rpg.VisibilityLevel':
        return app_lighting.parse_light_level(s)

    def _set_fog(self, on: bool):
        """Turn the fog-of-war render toggle on/off, keeping the button label in sync.

        Single entry point for anything that flips fog programmatically (Generate
        Dungeon turns it on) as well as the FOG button's menu."""
        self.show_fog = on
        self.btn_fog.text = self._fog_label()
        self._mark_fog_dirty()   # ensure the mask is current the moment fog turns on

    def _set_fog_opacity(self, pct: int):
        """Set how opaque the DM's screen draws the fog (percent). Players unaffected."""
        self.fog_opacity = max(0, min(100, int(pct)))
        self.btn_fog.text = self._fog_label()

    def _fog_label(self) -> str:
        if not self.show_fog:
            return "Fog: OFF"
        return "Fog: ON" if self.fog_opacity >= 100 else f"Fog: ON ({self.fog_opacity}%)"

    def _set_animate_moves(self, on: bool):
        """M4b B-7: switch move slides on/off, keeping the button label in sync. Read by
        _advance_npc_playback; announces, flashes and HP timing play either way."""
        self.animate_moves = on
        self.btn_toggle_animate.text = "Animate: ON" if on else "Animate: OFF"

    def _mark_fog_dirty(self):
        """Flag the fog-of-war explored mask as stale.

        Called from every event that can change party vision (movement, doors,
        lights, turn/combat boundaries, terrain reload). The actual reveal is
        deferred to the next _refresh_fog() so we never recompute on the hot path
        or multiple times per frame. Reveal is monotonic, so an extra mark is
        harmless — the flag only exists to skip work, never for correctness."""
        self._fog_dirty = True

    def _refresh_fog(self):
        """Re-run the PC-party fog reveal if the mask has been marked stale.

        Monotonic OR of every cell any living party member can currently see into
        the persistent C++ explored mask. No-op unless a trigger set _fog_dirty."""
        if not self._fog_dirty:
            return
        # No reveal while the map has no walls at all (auto-detect OFF and nothing painted):
        # the explored mask is monotonic and persisted, so a wall-blind reveal (a box through
        # every wall) would outlive that window. Carved/painted dungeons switch auto-detect
        # off on purpose but keep painted Wall cells, so they still reveal. The flag stays
        # set, so the reveal catches up as soon as walls are back.
        if not self._walls_enabled and not self._painted_terrain_cells:
            return
        self._fog_dirty = False
        try:
            self.bm.reveal_fog_for_faction(PC_FACTION)
        except Exception:
            # Never let a fog refresh take down the render loop.
            pass
        else:
            # A freshly-uncovered room wakes its lurking reserves: any on-deck enemy
            # standing in a room the party has now at least partially seen deploys off
            # deck. Runs right after the reveal so it's driven by the same trigger set.
            self._deploy_fog_revealed_enemies()

    def _deploy_fog_revealed_enemies(self):
        """Bring on-deck enemies off deck once the party uncovers their room.

        The user rule: "all enemies in a room with the fog at least partially cleared
        come off deck." What counts as the room is `_agents_in_revealed_rooms`.
        No-op unless the DM is running fog."""
        if not self.show_fog:
            return
        bm = self.bm
        # On-deck enemies only — nothing to do if there are no reserves in play.
        reserves = [i for i, pt in enumerate(bm.placed_agents)
                    if not pt.removed_from_play and pt.faction != PC_FACTION
                    and bm.is_agent_on_deck(i)]
        if not reserves:
            return
        to_deploy = self._agents_in_revealed_rooms(reserves)
        if not to_deploy:
            return
        # Group by name so same-type reserves share one initiative and the log reads well.
        by_name: dict[str, list[int]] = {}
        for i in to_deploy:
            by_name.setdefault(bm.placed_agents[i].name, []).append(i)
        for name, idxs in by_name.items():
            self._deploy_on_deck_idxs(idxs, name)

    def _bench_unrevealed_enemies(self):
        """At Begin Combat under fog, put every non-party creature whose room the party
        has not seen any of On Deck, so it rolls no initiative now and joins when its room
        is revealed (`_deploy_fog_revealed_enemies`). The user rule: "combat should only
        begin when the door is opened into a room". Encounters that start their enemies
        On Deck never reach this; it covers the ones that don't."""
        if not self.show_fog:
            return
        bm = self.bm
        live = [i for i, pt in enumerate(bm.placed_agents)
                if not pt.removed_from_play and pt.faction != PC_FACTION
                and not bm.is_agent_on_deck(i)
                and self.combat.get_agent_stats(bm, i).hp_cur > 0]
        if not live:
            return
        seen = set(self._agents_in_revealed_rooms(live))
        for i in live:
            if i not in seen:
                bm.set_agent_on_deck(i, True)

    def _agents_in_revealed_rooms(self, idxs):
        """The subset of `idxs` standing in a room the party has seen any of.

        Rooms come from the carved terrain metadata (`_terrain_rooms`, cells as [c, r]);
        an agent in a room with ANY explored cell counts. An agent on a cell no carved
        room claims (a drawn map) uses the engine's room flood, bounded by walls, edge
        walls and doors; only where that flood finds no closed room does it fall back to
        the agent's own footprint."""
        bm = self.bm
        Cell = rpg.Cell
        rooms = getattr(self, "_terrain_rooms", None) or []
        # cell -> room index, so each enemy finds its room in O(footprint).
        cell_room: dict[tuple[int, int], int] = {}
        for ri, m in enumerate(rooms):
            if isinstance(m, dict):
                for c in m.get("cells", []):
                    cell_room[(int(c[0]), int(c[1]))] = ri
        room_seen: dict[int, bool] = {}   # memoize each room's explored test

        def _room_revealed(ri: int) -> bool:
            if ri not in room_seen:
                room_seen[ri] = any(
                    bm.is_explored(Cell(int(c[0]), int(c[1])))
                    for c in rooms[ri].get("cells", []))
            return room_seen[ri]

        # Maps with no carved room metadata (drawn maps: Ravenloft's edge walls and edge
        # doors) get their rooms from the engine's room flood, which stops at wall cells,
        # wall edges and doors of either kind. Only the room's floor counts as "seen": the
        # flood also returns the blocking cells round it, and a wall cell the party saw
        # from the corridor outside says nothing about what is behind it.
        flood_room: dict[tuple[int, int], int] = {}     # floor cell -> flood id
        flood_seen: list[bool] = []

        def _flood_revealed(cell) -> bool | None:
            """Whether the drawn room around `cell` has an explored floor cell; None when
            the flood finds no closed room (capped), so the caller uses the footprint."""
            if cell in flood_room:
                return flood_seen[flood_room[cell]]
            cells = bm.room_cells(Cell(*cell), _ROOM_FLOOD_CAP)
            if len(cells) >= _ROOM_FLOOD_CAP:
                return None
            floor = [c for c in cells
                     if bm.door_at(c) < 0 and not bm.is_blocked(c, 1)]
            fid = len(flood_seen)
            flood_seen.append(any(bm.is_explored(c) for c in floor))
            for c in floor:
                flood_room[(c.col, c.row)] = fid
            return flood_seen[fid]

        out = []
        for i in idxs:
            pt = bm.placed_agents[i]
            fp = [(pt.origin.col + dc, pt.origin.row + dr)
                  for dc in range(pt.size) for dr in range(pt.size)]
            ri = next((cell_room[cell] for cell in fp if cell in cell_room), None)
            if ri is not None:
                revealed = _room_revealed(ri)
            else:
                flooded = [_flood_revealed(cell) for cell in fp]
                if any(f is not None for f in flooded):
                    revealed = any(flooded)
                else:
                    revealed = any(bm.is_explored(Cell(c, r)) for c, r in fp)
            if revealed:
                out.append(i)
        return out

    def _fog_active(self) -> bool:
        """True when the fog overlay + enemy-hide gate should be applied.

        Suppressed while a map-authoring modal (lighting / terrain editor) is open so
        the DM can see the whole map they're editing, and off entirely unless the DM
        has toggled fog on (btn_fog). DM view (D1, `dm_view`) lifts it too: drawing
        only, never the reveal, which keys on `show_fog` and the explored mask."""
        return (self.show_fog
                and not self.dm_view
                and not self.lighting_editor.active
                and not self.terrain_editor.active)

    def _fog_conceals(self) -> bool:
        """True when the DM screen's fog hides what is under it — tokens, doors, chests,
        ladders, stairs. Translucent fog (FOG → Opacity below 100%) is drawn but conceals
        nothing, since the DM is looking through it on purpose."""
        return self._fog_active() and self.fog_opacity >= 100

    def _party_fog_active(self) -> bool:
        """True when the party's fog is up — the gate for anything that leaves the process.

        `_fog_active()` is the DM *screen's* gate: an open terrain or lighting editor lifts
        it so the DM can see what they are editing. That must never lift a player's fog
        (MULTIPLAYER_PLAN.md D-M7-1), so every net reader asks this instead."""
        return bool(self.show_fog)

    def _agent_fogged(self, idx: int, pt=None, party: bool = False) -> bool:
        """True when a non-party token's whole footprint sits in never-explored fog.

        The single home of the fog-of-war reveal gate. It used to be written out three
        times — the draw pass, the hover tooltip and NPC playback — and MULTIPLAYER_PLAN
        D-M3-2 collapsed them here before `GameView` became a fourth copy, because a
        projection that drifts from what the DM's screen draws is a state leak rather
        than a cosmetic bug.

        Party-faction tokens are never fogged. `pt` is accepted so a caller already
        holding the record does not pay for a second lookup; it must be `placed_agents[idx]`.

        Callers rely on the consequences differing: the draw pass skips the sprite, the
        hover tooltip withholds the name, and playback resolves the token's Move/Announce
        events instantly and silently — no info leak, and no dead air spent staring at an
        apparently empty map.

        `party=True` is the net readers' form (D-M7-1): it ignores an open editor, which
        un-fogs only the DM's own screen.
        """
        if not (self._party_fog_active() if party else self._fog_conceals()):
            return False
        agents = self.bm.placed_agents
        if idx < 0 or idx >= len(agents):
            return False
        if pt is None:
            pt = agents[idx]
        if pt.faction == PC_FACTION:
            return False
        fp = [rpg.Cell(pt.origin.col + dc, pt.origin.row + dr)
              for dc in range(pt.size) for dr in range(pt.size)]
        return bool(fp) and all(not self.bm.is_explored(c) for c in fp)

    def _npc_concealed_from_party(self, idx: int, pt) -> bool:
        """True when a non-party token is one the party can't perceive (Hidden, or
        Invisible with no sense that pierces it), so player screens must not show it.

        Scope: every non-party creature, automated or manually driven. The DM console
        still draws it, translucent and labeled (see _concealed_on_screen); only
        player-facing views drop it. It reappears through the usual mechanics:
          · Hidden clears through check_hidden_agent_detection / attacking, so the
            flag itself is authoritative — hidden ⇒ concealed.
          · Invisible is per-viewer: concealed unless some living party member
            pierces it (Truesight/Blindsight/Blind Fighting/Skulker, via the C++
            can_perceive_target — the same gate targeting uses)."""
        if pt.faction == PC_FACTION:
            return False
        cond = pt.conditions
        if cond.hidden or cond.untouchable:   # Untouchable: out of reach (phased, ethereal)
            return True
        if not cond.invisible:
            return False
        for j, viewer in enumerate(self.bm.placed_agents):
            if viewer.faction != PC_FACTION or viewer.removed_from_play:
                continue
            if (viewer.conditions.dead or viewer.conditions.incapacitated
                    or viewer.stats.hp_cur <= 0):
                continue   # mirrors the engine's observer gate in hide detection
            if self.combat.can_perceive_target(self.bm, j, idx):
                return False
        return True

    def _concealed_on_screen(self, idx: int, pt) -> bool:
        """True when this pygame screen must not show a concealed token. The DM
        console always shows Hidden/Invisible creatures (dimmed, labeled); only
        tracker mode's table view — which the players look at — drops them."""
        return (self.tracker_mode and not self.dm_view
                and self._npc_concealed_from_party(idx, pt))

    def _draw_fog_overlay(self):
        return app_board_render.draw_fog_overlay(self)

    def _clear_temporary_terrain(self):
        """Remove spell-created temporary terrain (regions with 'source' field)."""
        self._terrain_regions = [r for r in self._terrain_regions if "source" not in r]

    def _apply_terrain_to_battle_map(self):
        """Apply terrain regions to the C++ battle map: Difficult Terrain becomes a movement
        multiplier; Wall/Chasm/Water paint actual terrain types so the C++ movement engine
        (isBlocked → reachableCells / move_agent, used by both player drags and NPC automation)
        treats them as impassable. Without this, painted walls were drawn but never blocked moves."""
        self.bm.reset_terrain_multipliers()

        # Revert the cells we painted last time back to Standard before re-applying, so removing
        # a wall region in the editor frees those cells. Skip cells a door owns (doors manage their
        # own Wall terrain via the C++ door state and aren't re-applied on a plain editor close).
        door_cells = {(c.col, c.row) for d in self.bm.doors for c in d.cells}
        for (col, row) in self._painted_terrain_cells:
            if (col, row) not in door_cells:
                self.bm.set_terrain_type(rpg.Cell(col, row), rpg.TerrainType.Standard)
        self._painted_terrain_cells = []

        type_map = {
            "Wall":  rpg.TerrainType.Wall,
            "Chasm": rpg.TerrainType.Chasm,
            "Water": rpg.TerrainType.Water,
        }
        for region in self._terrain_regions:
            terrain_type = region.get("type", "Difficult Terrain")
            px = region.get("x", 0)
            py = region.get("y", 0)
            pw = region.get("width", 0)
            ph = region.get("height", 0)
            if pw <= 0 or ph <= 0:
                continue
            if terrain_type == "Difficult Terrain":
                mult = region.get("multiplier", 0.5)
                self._apply_pixel_terrain(px, py, pw, ph, mult)
            elif terrain_type in type_map:
                self._apply_pixel_terrain_type(px, py, pw, ph, type_map[terrain_type])

    def _pixel_rect_to_cells(self, px, py, pw, ph):
        """Convert a pixel rectangle to an inclusive grid cell range (c_start, r_start,
        c_end, r_end), or None if the grid isn't analyzed yet. Shared by the multiplier and
        terrain-type appliers so both map pixels to cells identically."""
        import bisect
        # Regions are stored in fit-scale px (the terrain editor works at fit scale), so
        # divide by the fit scale, not the zoomed map_scale — a terrain load while zoomed
        # would otherwise paint the wrong cells.
        s = self.base_map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        if not raw_v or not raw_h:
            return None

        # Convert pixel coords (fit-scale) to original image coords
        ix, iy = px / s, py / s
        iw, ih = pw / s, ph / s

        # Find grid cell range using binary search. Start edges use bisect_right so a
        # cell owns its top/left grid line; end edges use bisect_left so a region whose
        # bottom/right edge falls *exactly* on a grid line does NOT pull in the next cell
        # (which only starts at that line). Regions built from cell rects have their far
        # edge exactly on a grid line — bisect_right there over-included one extra row/col.
        # Saved regions are whole fit-scale px, so on a map shown below 1:1 an edge drawn on
        # a grid line comes back up to one fit px short of it (Blank.png: x=202 → 279.1,
        # the line is 280). Nudge each edge inward by one fit px so that rounding cannot
        # pull in an invisible extra row/col of wall.
        tol = 1.0 / s
        c_start = max(0, bisect.bisect_right(raw_v, ix + tol) - 1)
        r_start = max(0, bisect.bisect_right(raw_h, iy + tol) - 1)
        c_end = min(self.bm.grid_cols - 1, bisect.bisect_left(raw_v, ix + iw - tol) - 1)
        r_end = min(self.bm.grid_rows - 1, bisect.bisect_left(raw_h, iy + ih - tol) - 1)
        c_end = max(c_start, c_end)
        r_end = max(r_start, r_end)
        return c_start, r_start, c_end, r_end

    def _apply_pixel_terrain(self, px, py, pw, ph, mult):
        """Convert pixel coordinates to grid and apply multiplier."""
        rng = self._pixel_rect_to_cells(px, py, pw, ph)
        if rng is None:
            return
        c_start, r_start, c_end, r_end = rng
        width = max(1, c_end - c_start + 1)
        height = max(1, r_end - r_start + 1)
        self.bm.set_terrain_multiplier_rect(rpg.Cell(c_start, r_start), width, height, mult)

    def _apply_pixel_terrain_type(self, px, py, pw, ph, terrain_type):
        """Paint a pixel rectangle's grid cells with a blocking TerrainType (Wall/Chasm/Water)
        so the C++ movement engine routes around them. Records each cell in
        _painted_terrain_cells so a later re-apply can revert it to Standard."""
        rng = self._pixel_rect_to_cells(px, py, pw, ph)
        if rng is None:
            return
        c_start, r_start, c_end, r_end = rng
        for col in range(c_start, c_end + 1):
            for row in range(r_start, r_end + 1):
                self.bm.set_terrain_type(rpg.Cell(col, row), terrain_type)
                self._painted_terrain_cells.append((col, row))

    # ─────────────────────────────────────────────────────────────────────
    #  Drawing
    # ─────────────────────────────────────────────────────────────────────
    def _draw_map(self):
        return app_board_render.draw_map(self)

    def _draw_hover_cursor(self):
        return app_board_render.draw_hover_cursor(self)

    def _draw_agent_hover_name(self):
        return app_board_render.draw_agent_hover_name(self)

    def _draw_concentration_terrain(self, cpx: int):
        return app_board_render.draw_concentration_terrain(self, cpx)

        # Concentration/spell terrain now renders via _draw_temp_terrain_overlays
        # (reads bm.active_terrain_effects); only static DM-painted terrain is drawn above.

    def _draw_doors(self, cpx: int):
        return app_board_render.draw_doors(self, cpx)

    def _any_explored(self, cells) -> bool:
        """True when the party has explored at least one of ``cells`` ((col, row) pairs)."""
        is_explored, Cell = self.bm.is_explored, rpg.Cell
        return any(is_explored(Cell(int(c), int(r))) for c, r in cells)

    def _draw_ladders(self, cpx: int):
        return app_board_render.draw_ladders(self, cpx)

    def _staircase_cells_here(self):
        """The active page's staircase ends grouped by cell, fog applied the same way as
        ladders: ``{(col, row): [(staircase, end_index), ...]}``."""
        fog = self._fog_conceals()
        out = {}
        for st, i in self._staircase_ends_here():
            c = st.ends[i].cell
            if fog and not self._any_explored([c]):
                continue                                  # never seen: hidden like the floor under it
            out.setdefault(c, []).append((st, i))
        return out

    def _draw_staircases(self, cpx: int):
        return app_board_render.draw_staircases(self, cpx)

    def _draw_staircase_hover(self):
        return app_board_render.draw_staircase_hover(self)

    # ── Room labels: the DM's room keys ("K10"), from the manifest page's "rooms" ──
    def _room_labels_here(self) -> list:
        """The active dungeon page's room labels; [] without a dungeon."""
        if self.dungeon is None or self.dungeon_page is None:
            return []
        return list(getattr(self.dungeon_page, "rooms", None) or [])

    def _toggle_room_labels(self):
        self.show_room_labels = not self.show_room_labels
        if self.show_room_labels and not self._room_labels_here():
            self._flash_status("This page has no room labels")

    def _draw_room_labels(self, cpx: int):
        return app_board_render.draw_room_labels(self, cpx)

    def _room_label_at(self, pos):
        """The room label whose text is under ``pos``, the last-drawn one on an overlap."""
        for rect, room in reversed(self._room_label_hits):
            if rect.collidepoint(pos):
                return room
        return None

    def _room_label_tooltip(self, pos):
        """The tooltip for a pointer at ``pos`` ("K10. Dining Hall"), or None: off the
        map, not over a key, or over a token or staircase, which keep their own."""
        if not self.show_room_labels or pos[0] >= self._panel_x():
            return None
        room = self._room_label_at(pos)
        if room is None:
            return None
        cell = self._screen_to_cell(*pos)
        if cell is not None and (self._agent_at(cell) >= 0
                                 or self._staircase_cells_here().get((cell.col, cell.row))):
            return None
        return room.title

    def _draw_room_label_hover(self):
        return app_board_render.draw_room_label_hover(self)

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
        return app_board_render.draw_safe_target_highlights(self)

    def _draw_map_overlays(self):
        return app_board_render.draw_map_overlays(self)

    def _draw_agents(self):
        return app_board_render.draw_agents(self)

    def _summon_cell_valid(self, cell, size) -> bool:
        return app_summons.summon_cell_valid(self, cell, size)

    def _action_clicked(self, action_id: str, event) -> bool:
        """True when `event` is a click on an action the panel is actually offering.

        Dispatch is by id and gated on `self._action_menu` — the offer the panel last
        drew — so for the converted sections the stale-rect guard is no longer what
        keeps an unoffered option from firing. It still is for every other button,
        which is why the guard stays until M2e.
        """
        act = self._action_menu.get(action_id)
        return act is not None and act.enabled and panel.cbt_btn(self, action_id).clicked(event)

    def perform(self, action_id: str, principal: str, anchor=None) -> bool:
        """Run one combat-panel action by id, for `principal` (D-M5-1).

        This is the one place an action runs. The DM's click reaches it from
        `_handle_events` with `DM_PRINCIPAL_ID` and the click position; a remote submit
        reaches it with the player's id and no anchor. Either way it is refused, and
        returns False, unless both hold:

          · the offer names it: `self._action_menu` has the id and it is `enabled`.
            This is the menu the panel LAST DREW, on purpose. The panel rebuilds it
            every frame before events and submits are drained, so it is never more
            than a frame old, and what the DM sees is what may run. The handler
            guards below (`action_used`, `bonus_used`, End Turn's pause) remain the
            backstop within a frame, exactly as they were at the click site.
          · `authorize()` allows it. Always asked, for the DM too (NN6 forbids a call
            site that branches on who is asking): the DM tools ask `DM_COMMAND`, and
            every other id asks `CONTROL_TOKEN` over the creature whose turn it is.

        `anchor` only places a popup; it defaults to the actor's token, as
        `_ask_actor` does.
        """
        act = self._action_menu.get(action_id)
        if act is None or not act.enabled:
            return False
        actor = self._current_agent_idx()
        if act.group == GROUP_SESSION or action_id == "place_terrain":
            verb, target = net_roster.Action.DM_COMMAND, None
        else:
            verb, target = net_roster.Action.CONTROL_TOKEN, net_roster.TokenTarget(actor)
        if not self.roster.authorize(self.roster.get(principal), verb, target):
            return False
        # While an Attack is chosen and unswung, the snapshot already holds the state from
        # before it; re-taking it here would make the arm look like the baseline.
        unswung = self._attack_unswung()
        if not unswung:
            self._snapshot_attack_arm(actor)
        elif action_id in self._ARMS_A_SPELL:
            # F-M5e-5: a spell arms beside the attack, and the attack is first in the click
            # chain, so the spell's click would swing the weapon. Nothing has swung, so the
            # Attack is undone here, before the spell, from the snapshot; choosing it again
            # later costs nothing. D3's undo below cannot catch this: the spell spends the
            # Action only when it resolves, long after `perform` has returned.
            net_picks.cancel_attack(self)
            unswung = False
        self._perform_action(action_id, self._agent_screen_pos(actor) if anchor is None else anchor)
        # D3 (MULTIPLAYER_PLAN.md, M5d handoff): the Action went to something else before
        # the attack swung, so the attack is abandoned, as Cancel abandons it. Without
        # this, Dash then a full Attack was a free Action. A row paid out of the Attack's
        # own swings (Bite) swings inside its handler, and is not an abandonment.
        if unswung and self.action_used and act.economy != ECONOMY_ATTACK:
            net_picks.cancel_attack(self)
        return True

    # The rows that can arm a `pending.Spell` (F-M5e-5). The Bonus Action ones are here
    # too: the chain order that lets the attack take the spell's click is the same.
    _ARMS_A_SPELL = frozenset({"spell_action", "spell_bonus", "divine_intervention",
                               "mantle_majesty", "wild_magic_bonus_cast"})

    def _attack_unswung(self) -> bool:
        """An Attack action is chosen and nothing has swung: its sequence is seeded for the
        Action, the Action is unspent (the first swing spends it), and the snapshot from
        before the Attack is held (a resolved pick drops it)."""
        return (self._attack_arm_snapshot is not None
                and self.attack_seq.slot == "action"
                and self.attack_seq.remaining > 0 and not self.action_used)

    def _snapshot_attack_arm(self, actor: int) -> None:
        """Keep what an attack arm may change, for `net/picks.cancel_attack` (M5d Step 0)."""
        hew = False
        if 0 <= actor < len(self.bm.placed_agents):
            hew = bool(self.combat.get_agent_conditions(self.bm, actor).gwm_hew_available)
        self._attack_arm_snapshot = (actor, self.attack_seq.remaining, self.attack_seq.slot,
                                     self.attack_seq.offhand, self.attack_seq.resource,
                                     self.attack_seq.weapon_idx, hew)

    def _toggle_draconic_flight(self):
        """Start Draconic Flight (pays the Bonus Action) or end it (free), and reset this
        turn's fly budget: the new fly Speed less what was already walked, none once it ends."""
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)):
            return
        starting = self.combat.get_agent_stats(self.bm, idx).draconic_flight_rounds == 0
        if not self.combat.toggle_draconic_flight(self.bm, idx):
            self._combat_log_add("Draconic Flight unavailable.")
            return
        self._flush_combat_log()
        st = self.combat.get_agent_stats(self.bm, idx)
        w, _f, sw, bu = self.bm.placed_agents[idx].raw_movement
        fly = max(0, st.speed_fly - (st.speed_walk - w)) if st.draconic_flight_rounds else 0
        self.bm.placed_agents[idx].init_movement(w, fly, sw, bu)
        self._update_reach()
        if starting:
            self.bonus_used = True

    def _toggle_large_form(self):
        """Goliath Large Form: start it (pays the Bonus Action; the engine grows the token to
        2×2 and adds the +10 ft to this turn's walk) or end it (free)."""
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)):
            return
        starting = self.combat.get_agent_stats(self.bm, idx).large_form_rounds == 0
        ok = self.combat.toggle_large_form(self.bm, idx)
        self._flush_combat_log()
        if not ok:
            if not starting:
                self._combat_log_add("Large Form unavailable.")
            return
        self._mark_fog_dirty()
        self._update_reach()
        if starting:
            self.bonus_used = True

    def _resolve_clouds_jaunt(self, cell):
        """Goliath Cloud's Jaunt: teleport up to 30 ft to an unoccupied space the Goliath can see.
        The engine validates the cell and spends the Giant Ancestry use; this pays the Bonus Action.
        Click yourself to cancel (nothing spent)."""
        idx = self._current_agent_idx()
        if idx < 0:
            self._drop_pick("clouds_jaunt")
            return
        pt = self.bm.placed_agents[idx]
        if cell.col == pt.origin.col and cell.row == pt.origin.row:
            self._drop_pick("clouds_jaunt")
            self._combat_log_add("Cloud's Jaunt cancelled.")
            return
        if self.combat.clouds_jaunt(self.bm, idx, cell.col, cell.row):
            self._drop_pick("clouds_jaunt")
            self.bonus_used = True
            self._mark_fog_dirty()
            self._flush_combat_log()
            self._update_reach()
        else:
            self._combat_log_add("Cloud's Jaunt: pick an unoccupied cell within 30 ft you can see.")

    def _perform_action(self, action_id: str, anchor):
        """`perform`'s dispatch: the bodies that stood under `_action_clicked` in
        `_handle_events` until D-M5-1, moved verbatim with their guards. Only one id
        matches, so each `if` is the branch that used to test the click. `anchor`
        replaces `event.pos` / `pygame.mouse.get_pos()`, which were only ever popup
        positions."""
        _ev_idx = self._current_agent_idx()
        # §4 and §6 dispatch by action id: the weapon test, the mid-sequence
        # test and Nick's own three-part guard are all `ActionMenu._action`'s
        # now, and `_action_clicked` consults the offer the panel drew.
        if action_id == "atk_action":
            self._start_attack("action")
        # Nick: relocate the off-hand attack into the Attack action (frees the bonus action).
        if action_id == "nick":
            self._start_extra_attack(weapon_idx=self._nick_offhand_idx(_ev_idx),
                                     offhand=True, slot="action",
                                     label="Nick: off-hand attack (part of Attack action)")
        # Unarmed Strike (Punch/Grapple/Push) is part of the Attack action, so it also
        # resumes mid-sequence (Extra Attack: grapple, then strike, or vice versa).
        if action_id == "unarmed":
            features.show_unarmed_menu(self, anchor)
        if action_id == "vampiric_bite":
            features.show_vampiric_bite_menu(self, anchor)
        # D-M2-4: these five are DRAWN mid-sequence (the band stays open for
        # the swings still owed) and refused here, exactly as End Turn is
        # refused while paused. The gate is a handler rule, not availability —
        # moving it into the menu would make the row vanish mid-attack.
        if not self.action_used:
            if action_id == "dash":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    agent = self.bm.placed_agents[idx]
                    self.bm.apply_dash(idx)
                    self._combat_log_add(f"{agent.name}: Dashing (+{self.combat.get_agent_stats(self.bm, idx).speed_walk}ft)")
                    self._update_reach()
                self.action_used = True
            if action_id == "dodge":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self.bm.placed_agents[idx].dodge()
                    self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Dodging")
                self.action_used = True
            if action_id == "disengage":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self.bm.placed_agents[idx].disengage()
                    self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Disengaging")
                self.action_used = True
            if action_id == "hide":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    in_combat = len(self.initiative_order) > 0
                    result = self.combat.check_hide(self.bm, idx, in_combat)
                    if result.hidden:
                        self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Hide (stealth {result.stealth_total})")
                    else:
                        self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Hide failed - {result.log_message}")
                self.action_used = True
            if action_id == "prone":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self.combat.apply_prone(self.bm, idx)
                    self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Going prone")
                    self._update_reach()
                    self._update_attack_overlay()
                self.action_used = True
            if action_id == "spell_action":
                self._start_cast_spell("action")
        # Long Jump costs a Bonus Action (and movement) — available regardless of the
        # Action, but only while the bonus action is unspent.
        if action_id == "long_jump":
            if not self._armed_slot(pending.Spell):  # Don't allow jump while casting spell
                self._toggle_jump_overlay()
        # Stand up doesn't use an action, so it's available regardless of action_used
        if action_id == "standup":
            idx = self._current_agent_idx()
            if 0 <= idx < len(self.bm.placed_agents):
                self.combat.standup(self.bm, idx)
                agent = self.bm.placed_agents[idx]
                self._combat_log_add(f"{agent.name}: Standing up")
                self._update_reach()
                self._update_attack_overlay()
        if action_id == "use_portent":
            features.show_portent_dice_menu(self, anchor)
        if action_id == "grapple_drop":
            app_attacks.execute_grapple_drop(self)
        # Use Item is NOT gated on the bonus action: a potion is a Bonus Action, but a
        # thrown flask or Net replaces one attack of the Attack action instead.
        if action_id == "use_item":
            features.show_use_item_menu(self, anchor)
        if action_id == "extinguish":
            self._resolve_extinguish()
        if action_id == "escape_net":
            self._begin_escape_net()
        # F14, closed: the bonus band's attack header is the mirror of
        # `atk_action` above and is dispatched the same way — ungated, on the
        # offer the panel drew. `bonus_used` is already True while an off-hand
        # or Flurry sequence is parked in the bonus slot, so the header the menu
        # labels "⚔ Bonus (N)" used to be a button that counted the swings it
        # could not take; `_start_attack` re-arms the parked sequence rather
        # than seeding a new one (`attack_seq.remaining != 0` skips the seed).
        if action_id == "atk_bonus":
            self._start_attack("bonus")
        # Action Surge costs no Bonus Action (`_BONUS_ECONOMY` marks it free, and the menu
        # offers it with the Bonus Action spent), so its handler is outside the gate too.
        if action_id == "action_surge":
            idx = self._current_agent_idx()
            if 0 <= idx < len(self.bm.placed_agents):
                self._use_action_surge(idx)
        # Ending Draconic Flight is free (SPECIES_PLAN.md D8), so it is outside the gate too.
        if action_id == "draconic_flight_end":
            self._toggle_draconic_flight()
        if action_id == "large_form_end":
            self._toggle_large_form()
        if not self.bonus_used:
            # `spell_bonus` stays behind the gate, and that is D-M2-4 rather
            # than F14: it is `spell_action`'s mirror, drawn mid-sequence with
            # the band and refused here, because a Bonus Action spell cannot be
            # cast with the Bonus Action already spent on the sequence.
            if action_id == "spell_bonus":
                self._start_cast_spell("bonus")
            if action_id == "shove_push":
                app_attacks.start_shove(self, "push")
            if action_id == "shove_prone":
                app_attacks.start_shove(self, "prone")
            if action_id == "grapple_esc":
                app_attacks.execute_grapple_escape(self)
            if action_id == "telekinetic_feat":
                app_attacks.start_telekinetic_shove(self)
            if action_id == "hide_bonus":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    in_combat = len(self.initiative_order) > 0
                    result = self.combat.check_hide(self.bm, idx, in_combat)
                    if result.hidden:
                        self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Hide (Cunning Action, stealth {result.stealth_total})")
                    else:
                        self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Hide failed - {result.log_message}")
                self.bonus_used = True
            if action_id == "dash_bonus" and not self.context_menu.visible:
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    agent = self.bm.placed_agents[idx]
                    self.bm.apply_dash(idx)
                    self._combat_log_add(f"{agent.name}: Dashing (Cunning Action, +{self.combat.get_agent_stats(self.bm, idx).speed_walk}ft)")
                    self._update_reach()
                self.bonus_used = True
            if action_id == "disengage_bonus":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self.bm.placed_agents[idx].disengage()
                    self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Disengaging (Cunning Action)")
                self.bonus_used = True
            if action_id == "patient_defense":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    stats = self.combat.get_agent_stats(self.bm, idx)
                    fp = stats.get_resource("Focus Points")
                    if fp and fp.current > 0:
                        self.combat.spend_resource(self.bm, idx, "Focus Points")
                        self.bm.placed_agents[idx].dodge()
                        self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Patient Defense (dodging)")
                    self.bonus_used = True
            if action_id == "wholeness_of_body":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    healed = self.combat.wholeness_of_body(self.bm, idx)
                    agent = self.bm.placed_agents[idx]
                    if healed > 0:
                        self._combat_log_add(f"{agent.name}: Wholeness of Body — {healed} HP restored")
                        self.bonus_used = True
                    else:
                        self._combat_log_add(f"{agent.name}: Wholeness of Body unavailable.")
            if action_id == "hand_of_healing":
                self._arm_pick("hand_of_healing")
                self.hint = "Click target for Hand of Healing"
            if action_id == "rage":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self.combat.activate_rage(self.bm, idx)
                    agent = self.bm.placed_agents[idx]
                    self._combat_log_add(f"{agent.name}: Enters a rage!")
                self.bonus_used = True
            if action_id == "intimidating_presence":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.use_intimidating_presence(self.bm, idx):
                        self._flush_combat_log()
                        self.bonus_used = True
                    else:
                        self._combat_log_add("Intimidating Presence unavailable.")
            if action_id == "zealous_presence":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.use_zealous_presence(self.bm, idx):
                        self._flush_combat_log()
                        self.bonus_used = True
                    else:
                        self._combat_log_add("Zealous Presence unavailable.")
            if action_id == "clairvoyant_combatant":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("clairvoyant")
                    self._combat_log_add("Clairvoyant Combatant: click an enemy within 60 ft to target.")
            if action_id == "path_to_the_grave":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("path_to_the_grave")
                    self._combat_log_add("Path to the Grave: click a creature within 30 ft to curse it.")
            if action_id == "vow_of_enmity":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("vow_of_enmity")
                    self._combat_log_add("Vow of Enmity: click an enemy within 30 ft to swear enmity against it.")
            if action_id == "inspiring_smite":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("inspiring_smite")
                    self._combat_log_add("Inspiring Smite: click a creature within 30 ft (including yourself) to grant temp HP.")
            if action_id == "avenging_angel":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._use_avenging_angel(idx)
            if action_id == "elder_champion":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._use_elder_champion(idx)
            if action_id == "living_legend":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._use_living_legend(idx)
            if action_id == "adrenaline_rush":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.use_adrenaline_rush(self.bm, idx):
                        self._flush_combat_log()
                        self._update_reach()
                        self.bonus_used = True
                    else:
                        self._combat_log_add("Adrenaline Rush unavailable.")
            if action_id == "draconic_flight":
                self._toggle_draconic_flight()
            if action_id == "large_form":
                self._toggle_large_form()
            if action_id == "clouds_jaunt":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents) and self.combat.can_clouds_jaunt(self.bm, idx):
                    self._arm_pick("clouds_jaunt")
                    self._combat_log_add(
                        "Cloud's Jaunt: click a destination within 30 ft you can see "
                        "(or click yourself to cancel).")
            if action_id == "magical_cunning":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.use_magical_cunning(self.bm, idx):
                        self._flush_combat_log()
                    else:
                        self._combat_log_add("Magical Cunning unavailable.")
            if action_id == "healing_light":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("heal_light")
                    self._combat_log_add("Healing Light — click an ally (or self) to heal.")
            if action_id == "turn_undead":
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
            if action_id == "divine_intervention":
                app_spells.start_divine_intervention(self)
            if action_id == "radiance":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    spells = self.combat.get_agent_spells(self.bm, idx)
                    ridx = next((i for i, sp in enumerate(spells)
                                 if sp.name == "Radiance of the Dawn"), -1)
                    if ridx >= 0:
                        self.pending = pending.Spell("action", ridx, 0)
                        origin = self.bm.placed_agents[idx].origin
                        self._resolve_spell_cast_aoe(rpg.Cell(origin.col, origin.row))
                    else:
                        self._combat_log_add("Radiance of the Dawn is not prepared.")
            if action_id == "preserve_life":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    agents = self.bm.placed_agents
                    origin = agents[idx].origin
                    # Auto-distribute to the most-wounded allies (and self) within 30 ft that are
                    # below half their HP max — most wounded first (matches Preserve Life's intent).
                    cands = []
                    for i in range(len(agents)):
                        if i != idx and not self._are_allies(idx, i):
                            continue
                        s = self.combat.get_agent_stats(self.bm, i)
                        if s.is_undead or s.hp_max <= 0 or s.hp_cur >= s.hp_max // 2:
                            continue
                        o = agents[i].origin
                        if ((o.col - origin.col) ** 2 + (o.row - origin.row) ** 2) ** 0.5 * 5 > 30:
                            continue
                        cands.append((s.hp_cur, i))
                    targets = [i for _, i in sorted(cands)]
                    res = self.combat.use_preserve_life(self.bm, idx, targets)
                    self._flush_combat_log()
                    if res.valid:
                        self._combat_log_add(
                            f"Preserve Life ({res.pool} HP pool): restored {res.spent} HP "
                            f"to {len(list(res.healed))} creature(s).")
                        self.action_used = True
                    else:
                        self._combat_log_add("Preserve Life unavailable.")
            if action_id == "invoke_duplicity":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    stats = self.combat.get_agent_stats(self.bm, idx)
                    # Improved Duplicity (L17) creates up to four illusions; otherwise just one.
                    self._arm_pick("invoke_duplicity")
                    self.pending_duplicity_remaining = 4 if stats.char_level >= 17 else 1
                    self._duplicity_cd_pending      = True
                    self.move_duplicity_idx         = -1
                    self._combat_log_add(
                        "Invoke Duplicity — click an empty cell within 30 ft to place "
                        + ("a duplicate." if self.pending_duplicity_remaining == 1
                           else f"the first of {self.pending_duplicity_remaining} duplicates."))
            if action_id == "move_duplicity":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    dups = self._my_duplicates(idx)
                    if not dups:
                        self._combat_log_add("No active duplicate to move.")
                    else:
                        self._arm_pick("move_duplicity")
                        # Lone duplicate: pre-select it so the next click is its destination.
                        self.move_duplicity_idx = dups[0] if len(dups) == 1 else -1
                        self._combat_log_add(
                            "Move Duplicate — click a destination within 30 ft." if len(dups) == 1
                            else "Move Duplicate — click one of your duplicates, then its destination.")
            if action_id == "swap_duplicity":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    dups = self._my_duplicates(idx)
                    if not dups:
                        self._combat_log_add("No active duplicate to swap with.")
                    elif len(dups) == 1:
                        app_summons.do_swap_duplicity(self, idx, dups[0])
                    else:
                        self._arm_pick("swap_duplicity")
                        self._combat_log_add("Swap — click the duplicate to trade places with.")
            if action_id == "steady_aim":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    cond = self.combat.get_agent_conditions(self.bm, idx)
                    cond.steady_aim = True
                    self.combat.set_agent_conditions(self.bm, idx, cond)
                    # Steady Aim sets your Speed to 0 for the rest of the turn.
                    self.bm.placed_agents[idx].init_movement(0, 0, 0, 0)
                    self._update_reach()
                    self.bonus_used = True
                    self._combat_log_add(
                        f"{self.bm.placed_agents[idx].name}: Steady Aim — advantage on next attack (Speed 0).")
            if action_id == "war_priest":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._start_extra_attack(weapon_idx=0, offhand=False,
                                             resource="War Priest", label="War Priest")
            if action_id == "bite_grappled":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    wslot, victim = self.combat.pending_auto_grapple_strike(self.bm, idx)
                    if wslot >= 0 and victim >= 0 and not self.grapple_bite_used:
                        # "Makes two attacks and uses Bite": the Bite rides along with the
                        # Attack action without spending one of its swings. Route it through
                        # the normal Attack dispatch (so forceAutoHit / save_for_damage / the
                        # HP-max drain fire unchanged) with ONE extra swing added to the
                        # sequence, which the dispatch then spends — so the weapon swings
                        # left over are exactly what they were before the Bite.
                        seq = self.attack_seq
                        if seq.slot == "action" and seq.remaining > 0:
                            seq.remaining += 1                       # mid-sequence
                        else:
                            fresh = not self.action_used
                            seq.remaining = (app_attacks.attack_action_budget(self, idx)
                                             if fresh else 0) + 1
                            seq.slot = "action"
                            seq.offhand = None
                            seq.resource = None
                        self.grapple_bite_used = True
                        seq.weapon_idx = wslot
                        self.pending = pending.Attack("action")
                        self._combat_log_add("🧛 Bite (grappled)")
                        self._resolve_combat_attack(victim)
            if action_id == "gwm_hew":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._start_gwm_hew(idx)
            if action_id == "horde_breaker":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    app_attacks.start_horde_breaker(self, idx)
            if action_id == "sudden_strike":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    app_attacks.start_sudden_strike(self, idx)
            if action_id == "beasts_strike":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    app_attacks.start_beasts_strike(self, idx)
            if action_id == "blink_steps":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents) and self._blink_steps_ready(idx):
                    self._arm_pick("blink_steps")
                    self._combat_log_add(
                        "Blink Steps: click a destination within 30 ft you can see "
                        "(or click yourself to skip).")
            if action_id == "martial_arts":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._start_extra_attack(weapon_idx=0, offhand=False,
                                             resource=None, label="Martial Arts")
            if action_id == "flurry_of_blows":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    stats = self.combat.get_agent_stats(self.bm, idx)
                    fp = stats.get_resource("Focus Points")
                    if fp and fp.current > 0:
                        # Show Open Hand rider menu if Way of the Open Hand
                        if stats.monk_subclass == rpg.MonkSubclass.WarriorOfTheOpenHand:
                            riders.show_flurry_rider_menu(self, idx)
                        else:
                            # No rider options, execute with no rider
                            self._execute_flurry(idx, -1)
            if action_id == "second_wind":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._use_second_wind(idx)
            if action_id == "bm_maneuver":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    riders.offer_bonus_maneuver(self, idx)
            if action_id == "one_with_shadows":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.apply_one_with_shadows(self.bm, idx):
                        self._combat_log_add(f"{self.bm.placed_agents[idx].name}: One with Shadows — now invisible.")
                    else:
                        self._combat_log_add("One with Shadows requires standing in Dim Light or Darkness.")
            if action_id == "merge_shadows":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.apply_merge_with_shadows(self.bm, idx):
                        self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Merge with Shadows — now invisible.")
                    else:
                        self._combat_log_add("Merge with Shadows requires standing in Dim Light or Darkness.")
            if action_id == "lay_on_hands":
                self._arm_pick("lay_on_hands")
                self.hint = "Click target for Lay on Hands healing"
            if action_id == "grant_inspiration":
                self._arm_pick("grant_inspiration")
                self.hint = "Click an ally to grant a Bardic Inspiration die"
            if action_id == "mantle":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._start_mantle(idx)
                    self.hint = "Mantle of Inspiration: click recipients (≤CHA mod), Enter to confirm"
            if action_id == "mantle_majesty":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    features.start_mantle_majesty(self, idx)
            if action_id == "unbreakable_majesty":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._start_unbreakable_majesty(idx)
            if action_id == "beguiling_restore":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    app_spells.restore_beguiling_magic(self, idx)
            if action_id == "use_inspiration":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._use_inspiration_die(idx)
            if action_id == "sacred_weapon":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._use_sacred_weapon(idx)
            if action_id == "corona":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._use_corona_of_light(idx)
            if action_id == "telekinetic_psi":
                self._arm_pick("telekinetic")
                self.hint = "Click a creature to move with Telekinetic Movement"
            if action_id == "tireless":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._use_tireless(idx)
            if action_id == "fey_reinforcements":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._start_fey_reinforcements(idx)
            if action_id == "natures_veil":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._use_natures_veil(idx)
            if action_id == "psychic_veil":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._use_psychic_veil(idx)
            if action_id == "psychic_teleport":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("psychic_teleport")
                    self._combat_log_add(
                        "Psychic Teleportation: click a destination (or click yourself to cancel).")
            if action_id == "shadow_step":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("shadow_step")
                    self._combat_log_add(
                        "Shadow Step: click a destination (or click yourself to cancel).")
            if action_id == "cloak_of_shadows":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.cloak_of_shadows(self.bm, idx):
                        self.bonus_used = True
                        self._combat_log_add(
                            f"{self.bm.placed_agents[idx].name}: Cloak of Shadows activated.")
                    else:
                        self._combat_log_add(
                            f"{self.bm.placed_agents[idx].name}: cannot use Cloak of Shadows (not in dim/dark light).")
            if action_id == "shadow_arts_darkness":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("shadow_darkness")
                    self._combat_log_add(
                        "Shadow Arts: Darkness: click a center cell (or click yourself to cancel).")
            if action_id == "fey_effect":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    stats = self.combat.get_agent_stats(self.bm, idx)
                    n_effects = 5 if stats.char_level >= 6 else 3
                    self.steps_of_fey_effect = (self.steps_of_fey_effect + 1) % n_effects
                    self._combat_log_add(
                        f"Steps of the Fey rider: {self._FEY_EFFECT_NAMES[self.steps_of_fey_effect]}")
            if action_id == "misty_wanderer":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("misty_wanderer")
                    self._combat_log_add(
                        "Misty Wanderer: click a destination (or click yourself to cancel).")
            if action_id == "move_hunters_mark":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("move_hunters_mark")
                    self._combat_log_add("Move Hunter's Mark: click a creature within 90 ft.")
            if action_id == "steps_of_fey":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("steps_of_fey")
                    self._combat_log_add(
                        "Steps of the Fey: click a destination (or click yourself to cancel).")
            if action_id == "misty_escape":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("misty_escape")
                    self._combat_log_add(
                        "Misty Escape: click a destination (or click yourself to cancel).")
            if action_id == "elemental_attunement":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    features.show_elemental_attunement_menu(self, idx)
            if action_id == "elemental_burst":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    features.show_elemental_burst_menu(self, idx)
            if action_id == "quivering_palm":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    app_attacks.detonate_quivering_palm(self, idx)
            if action_id == "dragon_wings":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.activate_dragon_wings(self.bm, idx):
                        stats = self.combat.get_agent_stats(self.bm, idx)
                        if stats.dragon_wings_active:
                            self._combat_log_add(
                                f"{self.bm.placed_agents[idx].name}: Dragon Wings extended (fly {stats.speed_walk} ft)")
                        else:
                            self._combat_log_add(
                                f"{self.bm.placed_agents[idx].name}: Dragon Wings retracted")
                            # Retracting removes the fly budget left this turn; the rest stay.
                            w, _f, sw, bu = self.bm.placed_agents[idx].raw_movement
                            self.bm.placed_agents[idx].init_movement(w, 0, sw, bu)
            if action_id == "draconic_resistance":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.activate_draconic_resistance(self.bm, idx):
                        stats = self.combat.get_agent_stats(self.bm, idx)
                        elem_name = features._DAMAGE_TYPE_NAMES.get(stats.draconic_affinity_type, str(stats.draconic_affinity_type))
                        self._combat_log_add(
                            f"{self.bm.placed_agents[idx].name}: Draconic Resistance — "
                            f"{elem_name} resistance for 1 hour (1 SP spent)")
                    else:
                        self._combat_log_add("Draconic Resistance: not eligible")
                    bonus_used = True
            if action_id == "bend_luck":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    features.show_bend_luck_menu(self, idx, anchor)
            if action_id == "boon_of_fate":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    features.show_boon_of_fate_menu(self, idx, anchor)
            if action_id == "tides_of_chaos":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.activate_tides_of_chaos(self.bm, idx):
                        self._flush_combat_log()
                    else:
                        self._combat_log_add("Tides of Chaos: not available (no use left / wrong subclass/level)")
                        self._flush_combat_log()
                    self._update_attack_overlay()
            # Sorcerer Innate Sorcery (Bonus Action). At L7 (Sorcery Incarnate) a caster
            # out of uses can still pay 2 SP for it — the engine picks the payment.
            if action_id == "innate_sorcery":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.activate_innate_sorcery(self.bm, idx):
                        self.bonus_used = True  # Innate Sorcery costs a Bonus Action
                        self._flush_combat_log()
                    else:
                        self._combat_log_add(
                            "Innate Sorcery: not available (no use left / not enough SP / wrong class)")
                        self._flush_combat_log()
                    self._update_attack_overlay()
            # NOTE: the Metamagic arm-toggle click handler was moved OUT of this
            # `not self.bonus_used` block (see below, next to the Haste handler) so the
            # toggles stay clickable after the Bonus Action is spent — they are spell
            # qualifiers, not Bonus Actions.
            if action_id == "trance_of_order":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.activate_trance_of_order(self.bm, idx):
                        self.bonus_used = True  # Trance of Order costs a Bonus Action
                        self._flush_combat_log()
                    else:
                        self._combat_log_add("Trance of Order: not available (no use/5 SP, wrong subclass/level)")
                        self._flush_combat_log()
                    self._update_attack_overlay()
            if action_id == "bastion_of_law":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    features.show_bastion_of_law_menu(self, idx, anchor)
            if action_id == "clockwork_cavalcade":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.clockwork_cavalcade(self.bm, idx) >= 0:
                        self.action_used = True  # Clockwork Cavalcade is a Magic Action
                        self._flush_combat_log()
                    else:
                        self._combat_log_add("Clockwork Cavalcade: not available (no use/7 SP, wrong subclass/level)")
                        self._flush_combat_log()
                    self._update_attack_overlay()
            if action_id == "revelation_in_flesh":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    if self.combat.activate_revelation_in_flesh(self.bm, idx):
                        self.bonus_used = True  # Revelation in Flesh is a Bonus Action
                        stats = self.combat.get_agent_stats(self.bm, idx)
                        self._combat_log_add(
                            f"{self.bm.placed_agents[idx].name}: Revelation in Flesh — fly {stats.speed_fly} ft, "
                            f"truesight 60 ft (1 SP)")
                        self._flush_combat_log()
                    else:
                        self._combat_log_add("Revelation in Flesh: not available (no SP, already active, wrong subclass/level)")
                        self._flush_combat_log()
                    self._update_attack_overlay()
            if action_id == "warping_implosion":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("warping_implosion")
                    self._combat_log_add(
                        "Warping Implosion: click a destination within 120 ft (each creature within "
                        "30 ft of where you stand makes a DEX save vs 3d10 Force). Click yourself to cancel.")
                    self._flush_combat_log()
            if action_id == "wild_magic_extra_action":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    stats = self.combat.get_agent_stats(self.bm, idx)
                    stats.wild_magic_extra_action = False
                    self.combat.set_agent_stats(self.bm, idx, stats)
                    self.action_used = False  # grant the extra action
                    self._combat_log_add(
                        f"{self.bm.placed_agents[idx].name}: Wild Magic extra action granted!")
            if action_id == "wild_magic_bonus_cast":
                self._start_cast_spell("bonus")  # allow action-level spell as bonus
            if action_id == "wild_magic_teleport":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self._arm_pick("wild_magic_teleport")
                    self._combat_log_add("Wild Magic Teleport: click a destination cell.")
            if action_id == "companion":
                features.show_companion_menu(self, anchor)
            if action_id == "command_companion":
                idx = self._current_agent_idx()
                if 0 <= idx < len(self.bm.placed_agents):
                    self.combat.command_companion(self.bm, idx)
                    self._flush_combat_log()
            if action_id == "familiar":
                features.show_familiar_menu(self, anchor)
            if action_id == "charge_arcane_ward":
                features.show_arcane_ward_menu(self, anchor)
            if action_id == "wild_shape":
                features.show_wild_shape_menu(self, anchor)
        # F11, closed: Open Hand L11 Fleet Step is the one option in the band that
        # needs the Bonus Action to be GONE — it is a free Step of the Wind precisely
        # because it rides alongside another Bonus Action. Dispatched outside the gate
        # for that reason; the menu offers `step_of_wind` on the spent side only when
        # `_fleet_step_ready` says so, and the focus-paying arm below still refuses to
        # run with the Bonus Action spent (`fleet_step` is False, `bonus_used` True).
        if action_id == "step_of_wind":
            idx = self._current_agent_idx()
            if 0 <= idx < len(self.bm.placed_agents):
                stats = self.combat.get_agent_stats(self.bm, idx)
                conds = self.combat.get_agent_conditions(self.bm, idx)
                # Warrior of the Open Hand L11 Fleet Step: once per turn, Step of the Wind
                # is free (no Focus Point, no Bonus Action) when it rides alongside another
                # Bonus Action (i.e., the Bonus Action has already been spent this turn).
                fp = stats.get_resource("Focus Points")
                fleet_step = (stats.character_class == rpg.CharacterClass.Monk and
                              stats.monk_subclass == rpg.MonkSubclass.WarriorOfTheOpenHand and
                              stats.char_level >= 11 and not conds.fleet_step_used and
                              self.bonus_used)
                can_pay_focus = bool(fp and fp.current > 0)
                if fleet_step:
                    conds.fleet_step_used = True
                    self.combat.set_agent_conditions(self.bm, idx, conds)
                    agent = self.bm.placed_agents[idx]
                    agent.disengage()
                    self.bm.apply_dash(idx)
                    self._combat_log_add(f"{agent.name}: Fleet Step — free Step of the Wind (disengaging and dashing)")
                    self._update_reach()
                elif can_pay_focus:
                    self.combat.spend_resource(self.bm, idx, "Focus Points")
                    agent = self.bm.placed_agents[idx]
                    agent.disengage()
                    self.bm.apply_dash(idx)
                    self._combat_log_add(f"{agent.name}: Step of the Wind (disengaging and dashing)")
                    self._update_reach()
                    self.bonus_used = True
        # Sorcerer Metamagic arm-toggles — handled OUTSIDE the `not self.bonus_used` block
        # above (they are spell qualifiers, not Bonus Actions), so spending the Bonus Action
        # doesn't dead-key them. Radio-select (arming one clears the others; clicking the
        # armed one disarms). Seeking toggles independently (it stacks). Under Sorcery
        # Incarnate (L7 + Innate Sorcery active) a second option fills slot 2. Quickened is
        # skipped once the Bonus Action is spent — it casts the spell AS a Bonus Action.
        for _mm_id, opt in METAMAGIC_VALUE_BY_ID.items():
            if _mm_id != action_id:
                continue
            # The Quickened/`bonus_used` re-check that used to stand here is
            # gone with the rest of Step 0.3's F4: dispatch is by id against the
            # offer the panel drew, so an option whose Sorcery Points have since
            # been spent below its cost is no longer clickable either.
            name = METAMAGIC_NAME_BY_VALUE.get(int(opt), "Metamagic")
            cost = rpg.CombatEngine.metamagic_sp_cost(opt)
            incarnate = app_spells.sorcery_incarnate_active(self, self._current_agent_idx())
            if not incarnate:
                self.armed_metamagic2 = rpg.MetamagicOption.NONE
            if opt == rpg.MetamagicOption.Seeking:
                self.armed_seeking = not self.armed_seeking
                self._combat_log_add(
                    f"Metamagic {name} {'ARMED' if self.armed_seeking else 'disarmed'} "
                    f"({cost} SP on next cast).")
            elif self.armed_metamagic == opt:
                # Disarming slot 1 promotes slot 2 (if any) so the armed set stays packed.
                self.armed_metamagic = self.armed_metamagic2
                self.armed_metamagic2 = rpg.MetamagicOption.NONE
                self._combat_log_add(f"Metamagic {name} disarmed.")
            elif incarnate and self.armed_metamagic2 == opt:
                self.armed_metamagic2 = rpg.MetamagicOption.NONE
                self._combat_log_add(f"Metamagic {name} disarmed.")
            else:
                if incarnate and self.armed_metamagic != rpg.MetamagicOption.NONE:
                    # Sorcery Incarnate: keep the first option, add this one alongside it
                    # (a third click replaces slot 2 — the engine takes at most two).
                    self.armed_metamagic2 = opt
                    self._combat_log_add(
                        f"Metamagic {name} ARMED as the 2nd option ({cost} SP on next "
                        f"cast — Sorcery Incarnate).")
                else:
                    self.armed_metamagic = opt
                    self._combat_log_add(f"Metamagic {name} ARMED ({cost} SP on next cast).")
                # Transmuted needs a replacement damage type chosen at arm time.
                if opt == rpg.MetamagicOption.Transmuted:
                    features.show_metamagic_transmute_menu(self)
            self._flush_combat_log()
            break
        # Haste's extra action is an ACTION, not a bonus action — handle it OUTSIDE the
        # `not self.bonus_used` block above so spending a bonus action first doesn't dead-key it.
        if action_id == "haste_action":
            idx = self._current_agent_idx()
            if 0 <= idx < len(self.bm.placed_agents):
                stats = self.combat.get_agent_stats(self.bm, idx)
                stats.haste_action_available = False  # spend the extra action for this turn
                self.combat.set_agent_stats(self.bm, idx, stats)
                self.action_used = False  # grant the extra action
                self._combat_log_add(
                    f"{self.bm.placed_agents[idx].name}: Haste action granted (Attack ×1 / Dash / "
                    "Disengage / Hide / Utilize only).")
        if action_id == "place_terrain":
            self._reset_zoom()   # dialog blits map at (0,0); fit scale first
            self.terrain_placement_dialog.open(self.map_surf, self.bm, self)
        if action_id == "pause_resume":
            self.combat_paused = not self.combat_paused
            self.session_log.add("The DM paused the game." if self.combat_paused
                                 else "The DM resumed the game.")
            if not self.combat_paused:
                # A paused drag selects the dragged token; hand the highlight back to whoever's
                # turn it is.
                self.selected_idx = self._current_agent_idx()
                self._update_reach()
                self._update_attack_overlay()
        if action_id == "reaction_timer":
            self._cycle_reaction_timeout()
        if action_id == "table":
            dm.show_table_menu(self, anchor=(self.btn_cbt_table.rect.x,
                                             self.btn_cbt_table.rect.y))
        if action_id == "end_turn":
            if self._picking("beguiling"):
                # Don't let End Turn silently waste an armed Beguiling Magic offer — make the
                # DM resolve (click a creature) or decline (Esc) it first.
                self._combat_log_add(
                    "Resolve Beguiling Magic first — click a creature within 60 ft, "
                    "or press Esc to decline.")
                self._flush_combat_log()
            elif not self.combat_paused:
                if lair.on_lair_turn(self):
                    lair.finish(self)     # passes: drops any armed lair pick, then advances
                elif app_initiative.in_legendary_phase(self):
                    app_initiative.end_turn_legendary(self)   # passes the legendary creature
                else:
                    self._advance_turn()
                self._flush_combat_log()
        if action_id == "lair_actions":
            lair.cancel_pick(self)        # reopen the Lair menu; a half-made pick is dropped
        if action_id == "legendary_actions":
            app_initiative.reopen_legendary_menu(self)   # a half-made pick is dropped
        if action_id == "end_combat":
            self._end_combat()
        if action_id == "drop_concentration":
            self._drop_concentration()
        if action_id == "drop_weapon_main":
            self._drop_weapon(0)
        if action_id == "drop_weapon_off":
            self._drop_weapon(1)
        if action_id == "drop_weapon_rng":
            self._drop_weapon(2)
        # Ravenloft items (M6 / M10).
        if action_id == "use_luck":
            idx = self._current_agent_idx()
            if self.combat.spend_luck_for_advantage(self.bm, idx):
                self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Luck — "
                                     "Advantage on the next D20 Test")
        if action_id == "regain_slot" and not self.action_used:
            idx = self._current_agent_idx()
            level = self.combat.regain_slot_from_item(self.bm, idx)
            if level:
                self.action_used = True
                self._combat_log_add(f"{self.bm.placed_agents[idx].name} regains a level "
                                     f"{level} spell slot (Magic action)")

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
                self._wall_detect_dialog.visible or self._npc_auto_dialog.visible or
                self.dungeon_wizard.visible or self.floor_checklist.visible or
                self.weapon_selection_dialog.visible or
                self.armor_selection_dialog.visible or
                self.spell_selection_dialog.visible or
                self.item_selection_dialog.visible or self.items_dialog.active or
                self.mob_dialog.visible or self.context_menu.visible or
                self.spell_grid_menu.visible or
                self._grid_span_dialog.visible or self.name_prompt.visible or
                self.team_dialog.visible)

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if self.playback is not None:   # quit asks about the DM's scene, not the trace's
                    self.playback.exit()
                self._request_quit()
                continue

            # Playback mode (playback.py): a read-only board, so it takes every event but a
            # resize, ahead of the any-click fast-forward below (its own Step does that).
            if self.playback is not None and self.playback.handle_event(event):
                continue

            # NPC turn playback: any click or keypress fast-forwards the animation. The event
            # is CONSUMED — while the board shows deferred (snapshot) display state nothing
            # else may react to it (the parked reaction menu only opens once playback drains).
            if self._npc_anim is not None and event.type in (pygame.MOUSEBUTTONDOWN,
                                                             pygame.KEYDOWN):
                self._npc_anim_fast_forward()
                continue

            # Map-level pan input (wheel / arrow keys) is suppressed while any
            # menu is open, so scrolling a dialog doesn't also pan the map.
            map_input_allowed = not self._modal_active()

            # ── Tracker mode's initiative sheet: its rows, buttons and the field being
            # typed into, ahead of the arrow/zoom keys a digit or '-' would otherwise hit.
            if map_input_allowed and self._tracker_handle_event(event):
                continue

            # ── Dungeon paging overlay (Phase 3): the on-map nav buttons take
            # priority over map/agent clicks so paging never places an agent. ──
            if (map_input_allowed and self.dungeon is not None
                    and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                    and self._dungeon_nav_rects):
                nav_hit = next((k for k, r in self._dungeon_nav_rects.items()
                                if r.collidepoint(event.pos)), None)
                if nav_hit is not None:
                    if nav_hit == "floor_up":
                        app_dungeon_pages.floor_step(self, +1)
                    elif nav_hit == "floor_down":
                        app_dungeon_pages.floor_step(self, -1)
                    else:
                        app_dungeon_pages.page_step(self, nav_hit)
                    continue

            # ── Align Floor: arrows nudge the page, Tab flips floors, Enter/Esc end ──
            if (self.floor_align.active and map_input_allowed
                    and self.floor_align.handle_key(self, event)):
                continue

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

            # ── Mouse wheel: check for initiative tracker scrolling first ────
            mouse_pos = pygame.mouse.get_pos()
            over_initiative = (hasattr(self, 'initiative_scroll_region') and
                              self.initiative_scroll_region.collidepoint(mouse_pos))

            if over_initiative and event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 4:  # Scroll up
                    self.initiative_scroll_offset = max(0, self.initiative_scroll_offset - 1)
                elif event.button == 5:  # Scroll down
                    max_scroll = max(0, len(self.initiative_order) - 8)
                    self.initiative_scroll_offset = min(self.initiative_scroll_offset + 1, max_scroll)
            elif over_initiative and hasattr(pygame, 'MOUSEWHEEL') and event.type == pygame.MOUSEWHEEL:
                if event.y > 0:  # Scroll up
                    self.initiative_scroll_offset = max(0, self.initiative_scroll_offset - 1)
                elif event.y < 0:  # Scroll down
                    max_scroll = max(0, len(self.initiative_order) - 8)
                    self.initiative_scroll_offset = min(self.initiative_scroll_offset + 1, max_scroll)

            # ── Mouse wheel over the right panel: scroll the panel (not the map) ──
            # Applies to both panels; in combat it drives combat_panel_scroll, out of
            # combat panel_scroll. The initiative list keeps its own wheel region.
            over_panel = (mouse_pos[0] >= self._panel_x()
                          and not self._pc_name_input
                          and not self.placement_mode_active)
            panel_max = (self._combat_panel_max_scroll if self.combat_active
                         else self._panel_max_scroll)
            if over_panel and panel_max > 0 and not over_initiative:
                d = None
                if event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
                    d = -30 if event.button == 4 else 30
                elif hasattr(pygame, 'MOUSEWHEEL') and event.type == pygame.MOUSEWHEEL:
                    d = -event.y * 30
                if d is not None:
                    if self.combat_active:
                        self.combat_panel_scroll = min(max(0, self.combat_panel_scroll + d),
                                                       panel_max)
                    else:
                        self.panel_scroll = min(max(0, self.panel_scroll + d), panel_max)
                    continue

            # ── Mouse wheel over the map: zoom at the cursor (the player screen's way) ──
            if (map_input_allowed and not over_initiative and not over_panel
                    and self._wheel_zoom(event, mouse_pos)):
                continue

            # ── On-map zoom control, and drag-to-pan once a press has armed it ──
            if map_input_allowed and self._handle_zoom_control(event):
                continue
            if self._handle_pan_drag(event):
                continue

            # ── Keyboard panning (arrow keys) + zoom (+/-/0) ──────────────
            # Suppressed while an inline text field is capturing keystrokes (its
            # arrows move the caret).
            if map_input_allowed and event.type == pygame.KEYDOWN and not self._pc_name_input:
                if event.key == pygame.K_UP:
                    self._pan_by(0, 30)
                elif event.key == pygame.K_DOWN:
                    self._pan_by(0, -30)
                elif event.key == pygame.K_LEFT:
                    self._pan_by(30, 0)
                elif event.key == pygame.K_RIGHT:
                    self._pan_by(-30, 0)
                # Zoom in: '+' / '=' (main and numpad). Zoom out: '-'. Reset: '0'.
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    self._zoom_by(self.ZOOM_STEP)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    self._zoom_by(1.0 / self.ZOOM_STEP)
                elif event.key == pygame.K_0:
                    self._reset_zoom()

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

            # ── Automate NPCs dialog: docked over the panel, modal ──
            if self._npc_auto_dialog.visible:
                self._npc_auto_dialog.handle(event)
                continue

            # ── New Dungeon wizard: docked over the panel, the map stays live (from
            # Set Grid on, the map view is its sheet). Its file browser and its popups
            # (the library list, the Discard confirm) take events first. ──
            if self.dungeon_wizard.visible:
                if self.file_browser.active:            # its Pick an image step
                    self.file_browser.handle(event, self.screen)
                elif self.context_menu.visible:
                    if self.context_menu.handle(event):
                        self.prompts.renderer_dismissed()
                elif not self.dungeon_wizard.handle(event):
                    self._handle_map_view_event(event)
                continue

            # ── Floors… checklist: docked over the panel, the map stays live ──
            if self.floor_checklist.visible:
                if not self.floor_checklist.handle(event):
                    self._handle_map_view_event(event)
                continue

            # ── Wall Detection dialog: docked over the panel, the map stays live ──
            if self._wall_detect_dialog.visible:
                if not self._wall_detect_dialog.handle(event):
                    self._handle_map_view_event(event)
                continue

            # ── Name prompt is a top modal: consume events while open. Ahead of the
            # terrain editor, whose Staircase tool opens it for a rename / label. ──────
            if self.name_prompt.visible:
                self.name_prompt.handle(event)
                continue

            # ── A popup raised over an editor (closing it asks before overwriting
            # a file) takes events ahead of the editor. ───────────────────────
            if self.context_menu.visible and (self.terrain_editor.active
                                              or self.lighting_editor.active):
                if self.context_menu.handle(event):
                    self.prompts.renderer_dismissed()
                continue

            # ── Terrain editor gets first pick when open ──────────────────
            if self.terrain_editor.active:
                self.terrain_editor.handle(event)
                # Handle close/save for terrain editor
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self._confirm_overwrite([self._terrain_path], "Close terrain editor",
                                            self._close_terrain_editor)
                continue

            # ── Lighting editor gets priority when open ──────────────────
            # It draws over the live map, so what it does not consume may still
            # zoom / pan that map (the modal guard above shuts the usual handlers off).
            if self.lighting_editor.active:
                if not self.lighting_editor.handle(event):
                    self._handle_map_view_event(event)
                continue

            # ── Cast-time element picker is a top modal: consume events while open ──
            if self._element_dialog.visible:
                self._element_dialog.handle(event)
                # Same report the popup makes below: the picker commits on dismiss with
                # nothing selected, the renderer drops that empty commit, and the bus
                # turns it into the cancel it actually was.
                self.prompts.renderer_dismissed()
                continue

            # ── Grid-span picker is a top modal: consume events while open ─────────
            if self._grid_span_dialog.visible:
                self._grid_span_dialog.handle(event)
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
                    # Esc or a click outside closes it with no spell chosen. When it is
                    # drawing a bus prompt (Wish, Divine Intervention), that is a cancel.
                    self.prompts.renderer_dismissed()
                    continue
            if self.item_selection_dialog.visible:
                if self.item_selection_dialog.handle(event):
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
            if self.items_dialog.active:
                self.items_dialog.handle(event, self.screen)
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
                    self._place_in_staging()    # a generated dungeon's empty room, if any
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
                    self._commit_placement()
                    continue
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    # Cancel placement
                    self.placement_mode_active = False
                    self._pending_import_agent = None
                    self.placement_config = None
                    self.placement_cell = None
                    self._pc_name_input = None
                    continue

            # Spell grid popup sits above normal map events but below modals.
            if self.spell_grid_menu.visible:
                if self.spell_grid_menu.handle(event):
                    self.prompts.renderer_dismissed()
                    continue

            # Context menu sits above normal map events but below modals.
            if self.context_menu.visible:
                if self.context_menu.handle(event):
                    # A popup dismissed by clicking away / right-click (no option chosen)
                    # is a cancellation, and the bus runs whatever that prompt's cancel
                    # path is — for a reaction window, submitting its Skip so a queued
                    # following reactor still gets its popup (Branches of the Tree after
                    # Vitality of the Tree) instead of the turn freezing. Choosing an
                    # option already resolved the prompt, so nothing fires here —
                    # including "Vitality of the Tree", which answers the prompt and then
                    # arms a target-pick, and which the old flag guard existed to spare.
                    self.prompts.renderer_dismissed()
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
                # Esc cancels an in-progress dropped-weapon drag (item snaps back, nothing changes).
                if event.key == pygame.K_ESCAPE and self.drag_item_id >= 0:
                    self._clear_item_drag()
                    self._combat_log_add("Move item cancelled.")
                    continue
                # Esc cancels a pending summon placement (no slot/action spent yet).
                if event.key == pygame.K_ESCAPE and self._armed(pending.Summon):
                    net_picks.cancel_summon(self)
                    continue
                # Esc cancels a pending Invoke Duplicity placement / move / swap (no Channel Divinity
                # is spent until a duplicate is actually placed, so cancelling here costs nothing).
                if event.key == pygame.K_ESCAPE and (self._picking("invoke_duplicity") or
                        self._picking("move_duplicity") or self._picking("swap_duplicity")):
                    net_picks.cancel_duplicity(self)
                    continue
                # Enter casts Chromatic Orb with the leap chain collected so far (may be empty —
                # the orb still leaps to the nearest foe on a match). Esc cancels the whole cast.
                if self._picking("chromatic") and self._armed_slot(pending.Spell) \
                        and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._finalize_chromatic_cast()
                    continue
                if self._picking("chromatic") and self._armed_slot(pending.Spell) \
                        and event.key == pygame.K_ESCAPE:
                    self._cancel_chromatic_chain()
                    continue
                # Enter casts a multi-target spell (Mass Suggestion, Bless, …) on the targets picked
                # so far, short of its maximum.
                if self._armed_slot(pending.Spell) and self._multi_target_finishable() \
                        and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._finish_multi_target_spell()
                    continue
                # Esc cancels a pending Cleave second-target pick (refunds the use this turn).
                if event.key == pygame.K_ESCAPE and self._pick_data("cleave") is not None:
                    self._cancel_cleave()
                    continue
                # Mantle of Inspiration: Enter resolves on the collected recipients, Esc cancels
                # (without spending the Bardic Inspiration use).
                if self._picking("mantle") \
                        and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._finalize_mantle()
                    continue
                # Lair Doors: Enter applies the chosen doors; Esc backs out of any lair pick.
                if self._pick_data("lair") == "doors" \
                        and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    lair.apply_doors(self)
                    continue
                if self._pick_data("lair") and event.key == pygame.K_ESCAPE:
                    lair.cancel_pick(self)
                    continue
                if event.key == pygame.K_ESCAPE and (self._picking("legendary_target")
                                                     or self._pick_data("legendary_spell")):
                    app_initiative.reopen_legendary_menu(self)
                    continue
                if self._picking("mantle") and event.key == pygame.K_ESCAPE:
                    self._cancel_mantle()
                    continue
                # Beguiling Magic: Esc declines the rider (the spell was already cast normally).
                if self._picking("beguiling") and event.key == pygame.K_ESCAPE:
                    self._cancel_beguiling()
                    continue
                # Esc cancels a pending Clairvoyant Combatant target pick (nothing spent until resolve).
                if self._picking("clairvoyant") and event.key == pygame.K_ESCAPE:
                    net_picks.cancel_clairvoyant(self)
                    continue
                if self._picking("vow_of_enmity") and event.key == pygame.K_ESCAPE:
                    net_picks.cancel_vow_of_enmity(self)
                    continue
                if self._picking("path_to_the_grave") and event.key == pygame.K_ESCAPE:
                    net_picks.cancel_path_to_the_grave(self)
                    continue
                if self._picking("move_hunters_mark") and event.key == pygame.K_ESCAPE:
                    net_picks.cancel_move_hunters_mark(self)
                    continue
                if self._picking("inspiring_smite") and event.key == pygame.K_ESCAPE:
                    net_picks.cancel_inspiring_smite(self)
                    continue
                # Esc cancels a pending spell cast. For an anchored wall, the first
                # Esc drops back to anchor selection; a second Esc cancels the cast. The
                # body is the spell arm's cancel, the one a player's remote cancel runs.
                if event.key == pygame.K_ESCAPE and self._armed_slot(pending.Spell):
                    net_picks.cancel_spell(self)
                    continue
                # M5d: every other armed pick cancels through its arm's own cancel, the one a
                # player's remote cancel runs (net/picks.py). Before M5d these had no Esc.
                if event.key == pygame.K_ESCAPE and self.combat_active and net_picks.cancel(self):
                    continue
                # Delete / Backspace removes the selected placed agent,
                # but ONLY when not in combat.
                if event.key in (pygame.K_DELETE, pygame.K_BACKSPACE) \
                        and not self.combat_active:
                    if self.selected_idx >= 0:
                        self._delete_placed_agent(self.selected_idx)

            if event.type == pygame.VIDEORESIZE:
                self._reposition_panel()

            # ── Map area: drag-and-drop ───────────────────────────────────
            on_map = not self._panel_rect().collidepoint(
                *getattr(event, 'pos', (-1, -1)))

            # Items… placement (plans/ITEMS_AND_CHESTS_PLAN.md I4): while armed, a left
            # click on the map places one; a right click or Esc stops.
            if self._item_placing is not None and not self.context_menu.visible:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    items_play.disarm_placement(self)
                    self._flash_status("Stopped placing.")
                    continue
                if event.type == pygame.MOUSEBUTTONDOWN and on_map and event.button in (1, 3):
                    if event.button == 3:
                        items_play.disarm_placement(self)
                        self._flash_status("Stopped placing.")
                    else:
                        items_play.place_at(self, self._screen_to_cell(*event.pos))
                    continue

            # Right-click a door during combat → door menu, even from the acting creature's
            # own square. An edge door borders the cell the creature stands in, so a left
            # click on its line would land on the token and start a drag; the right button
            # keeps left-drag free for moving through and out of doorways. Ahead of the
            # other right-click menus, which skip once this one is up.
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and on_map \
                    and self.combat_active and not self.context_menu.visible \
                    and not self._target_pick_armed():
                cell = self._screen_to_cell(*event.pos)
                if cell is not None and self._door_index_at(cell, event.pos) >= 0:
                    dm.show_door_menu(self, cell, event.pos)
                elif cell is not None and self.bm.chest_at(cell) >= 0:
                    items_play.show_chest_menu(self, cell, event.pos)

            # Right-click a chest out of combat → the DM's chest editor.
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and on_map \
                    and not self.combat_active and not self.context_menu.visible:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None and self.bm.chest_at(cell) >= 0:
                    items_play.show_chest_dm_menu(self, cell, event.pos)

            # Right-click on a placed agent → context menu (disabled during combat). A corpse
            # is skipped by _agent_at, so a downed mob's body gets its own Remove menu.
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and on_map \
                    and not self.combat_active:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    hit = self._agent_at(cell)
                    if hit >= 0:
                        board.show_agent_menu(self, hit, event.pos)
                    elif self._mob_clearable(self._corpse_at(cell)):
                        board.show_remove_mob_menu(self, self._corpse_at(cell), event.pos)

            # During combat, right-click an On Deck reserve to recall (deploy) just that one
            # mob — the per-mob counterpart to the On Deck section's group Deploy rows. The
            # full agent menu above is disabled mid-combat; reserves sit outside initiative,
            # so recalling one never disturbs the current actor's turn.
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and on_map \
                    and self.combat_active and not self.context_menu.visible:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    hit = self._agent_at(cell)
                    if hit >= 0 and self.bm.is_agent_on_deck(hit) \
                            and not self.bm.is_agent_removed_from_play(hit):
                        board.show_on_deck_recall_menu(self, hit, event.pos)

            # During combat, right-click a creature in the fight → the DM's condition toggles
            # (Prone, Invisible, …). The full agent menu is out of combat only; a downed mob
            # gets Clear mob below instead.
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and on_map \
                    and self.combat_active and not self.context_menu.visible \
                    and not self._target_pick_armed():
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    hit = self._agent_at(cell)
                    if hit >= 0 and not self.bm.is_agent_on_deck(hit) \
                            and not self.bm.is_agent_removed_from_play(hit) \
                            and not self._mob_clearable(hit):
                        board.show_conditions_menu(self, hit, event.pos)

            # During combat, right-click a downed mob (0 HP, dying or a corpse) → Clear mob,
            # so a PC can take its square. A corpse is skipped by _agent_at, and a live
            # creature may stand on one, so fall back to the body under the cursor.
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and on_map \
                    and self.combat_active and not self.context_menu.visible \
                    and not self._target_pick_armed():
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    hit = self._agent_at(cell)
                    if not self._mob_clearable(hit):
                        hit = self._corpse_at(cell)
                    if self._mob_clearable(hit):
                        board.show_clear_mob_menu(self, hit, event.pos)

            # Right-click a dropped weapon (no agent on the cell) → DM delete menu.
            # Works during combat too, so the DM can clean up the battlefield.
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and on_map \
                    and not self.context_menu.visible:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None and self._agent_at(cell) < 0:
                    items_at_cell = self.bm.get_items_at_cell(cell)
                    if items_at_cell:
                        dm.show_item_context_menu(self, cell, items_at_cell, event.pos)

            # Right-click an empty map cell (no agent, no items) → DM fog-of-war menu.
            # Manual overrides on the persistent explored mask: reveal everything, or
            # reset back to fully fogged. Only offered while fog is toggled on.
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and on_map \
                    and self.show_fog and not self.context_menu.visible:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None and self._agent_at(cell) < 0 \
                        and not self.bm.get_items_at_cell(cell):
                    board.show_fog_menu(self, event.pos)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and on_map:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    hit = self._agent_at(cell)
                    # Begin dragging a dropped weapon: only when no agent sits on the cell and
                    # no targeting/editing flow is active. The release decides move vs. pickup.
                    if hit < 0 and self.drag_item_id < 0 and not self.context_menu.visible \
                            and self.safe_target_edit_idx < 0 \
                            and not self._armed_slot(pending.Attack) and not self._armed_slot(pending.Spell) \
                            and not self._armed(pending.Shove) \
                            and not self._pick_data("cleave") and not self._pick_data("sweep") \
                            and not self._pick_data("rally") and not self._pick_data("feint"):
                        items_here = self.bm.get_items_at_cell(cell)
                        if items_here:
                            self._begin_item_drag(items_here[-1])
                            continue
                    if self.safe_target_edit_idx >= 0 and not self.combat_active:
                        # Evoker safe-target editing: clicking an ally toggles it; empty/self finishes.
                        self._toggle_safe_target(hit)
                    elif self.combat_active:
                        # M5d Step 0.6: the DM's click during a player's target prompt takes
                        # the turn over. The pick stays armed, so this click resolves it.
                        if net_picks.is_pick_prompt(self, self.prompts.live):
                            net_offer.take_over(self)
                        if not self.resolve_pick(cell, event.pos):
                            if self._edge_door_at_pos(event.pos) >= 0 or (
                                    hit < 0 and self._door_index_at(cell, event.pos) >= 0):
                                # No pending action and a click on a door (an edge door's
                                # slab wins over the creature beside it): door interaction.
                                dm.show_door_menu(self, cell, event.pos)
                            elif hit < 0 and self.bm.chest_at(cell) >= 0:
                                items_play.show_chest_menu(self, cell, event.pos)
                            elif hit < 0 and self._ladder_at(cell) >= 0:
                                dm.show_ladder_menu(self, cell, event.pos)
                            elif hit < 0 and app_dungeon_pages.staircases_at(self, cell):
                                dm.show_staircase_menu(self, cell, event.pos)
                            else:
                                # When paused, allow dragging any agent; otherwise only the current
                                # combatant — or the legendary creature performing an out-of-turn Dash.
                                # Tracker mode drags like a pause (T5): any token, any time.
                                cur = self._current_agent_idx()
                                free = self.combat_paused or self.tracker_mode
                                allow_drag = (hit >= 0) and (
                                    free or hit == cur
                                    or (self._legendary_move_active and hit == self._legendary_actor))
                                if allow_drag:
                                    pt = self.bm.placed_agents[hit]
                                    self.drag_idx    = hit
                                    self.drag_origin = rpg.Cell(pt.origin.col, pt.origin.row)
                                    self.drag_offset = (cell.col - pt.origin.col,
                                                        cell.row - pt.origin.row)
                                    self.drag_cell   = rpg.Cell(pt.origin.col, pt.origin.row)
                                    self.drag_valid  = True
                                    # During pause, allow selecting other agents; otherwise keep on current.
                                    if free:
                                        self.selected_idx = hit
                                    if self.tracker_mode:
                                        app_initiative.tracker_select(self, hit)     # ▶ to it + its HP box
                                else:
                                    self._arm_pan_drag(event.pos)
                    else:
                        # Normal mode: door interaction, drag any agent, or deselect.
                        # But disable dragging if jump overlay is active (use jump instead)
                        if self._edge_door_at_pos(event.pos) >= 0 or (
                                hit < 0 and self._door_index_at(cell, event.pos) >= 0):
                            dm.show_door_menu(self, cell, event.pos)
                        elif hit < 0 and self.bm.chest_at(cell) >= 0:
                            items_play.show_chest_menu(self, cell, event.pos)
                        elif hit < 0 and self._ladder_at(cell) >= 0:
                            dm.show_ladder_menu(self, cell, event.pos)
                        elif hit < 0 and app_dungeon_pages.staircases_at(self, cell):
                            dm.show_staircase_menu(self, cell, event.pos)
                        elif hit >= 0 and not self.jump_overlay_active:
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
                            # A downed mob's corpse selects (for Delete) but doesn't drag.
                            corpse = -1
                            if not self.placement_mode_active and not self.jump_overlay_active \
                                    and self._mob_clearable(self._corpse_at(cell)):
                                corpse = self._corpse_at(cell)
                            if corpse < 0 and not self.placement_mode_active:
                                self._arm_pan_drag(event.pos)
                            self.selected_idx        = corpse
                            self._reach_walk         = []
                            self._reach_fly          = []
                            self._reach_set          = set()
                            self._attack_cells_melee = []
                            self._attack_cells_rnorm = []
                            self._attack_cells_rlong = []

            if event.type == pygame.MOUSEMOTION and self._armed(pending.Spell) and self.pending.is_aoe:
                if on_map:
                    self.spell_hover_cell = self._screen_to_cell(*event.pos)
                else:
                    self.spell_hover_cell = None

            if event.type == pygame.MOUSEMOTION and self._armed(pending.Summon):
                self.summon_hover_cell = self._screen_to_cell(*event.pos) if on_map else None

            # Dragging a dropped weapon: track the cursor cell for the ghost icon.
            if event.type == pygame.MOUSEMOTION and self.drag_item_id >= 0:
                if on_map:
                    c = self._screen_to_cell(*event.pos)
                    if c is not None:
                        self.drag_item_cell = c

            if event.type == pygame.MOUSEMOTION and self.drag_idx >= 0:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    pt   = self.bm.placed_agents[self.drag_idx]
                    tcol = cell.col - self.drag_offset[0]
                    trow = cell.row - self.drag_offset[1]
                    self.drag_cell  = rpg.Cell(tcol, trow)
                    self.drag_valid = self._can_place(
                        self.drag_cell, pt.size, exclude_idx=self.drag_idx)
                    # The movement-range clamp applies only in active combat (not paused).
                    # Before combat or when paused, the agent can be repositioned anywhere it
                    # legally fits (DM free placement); placement validity was checked above.
                    # Tracker mode has no budgets (T5), so it never clamps either.
                    if self.drag_valid and self.combat_active and not self.combat_paused \
                            and not self.tracker_mode:
                        if self._reach_set:
                            self.drag_valid = (
                                self.drag_cell.col, self.drag_cell.row
                            ) in self._reach_set
                        else:
                            self.drag_valid = False   # movement exhausted

            # Release a dragged dropped-weapon: a real drag relocates it; an in-place
            # release is treated as a click → offer pickup to an adjacent eligible agent.
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.drag_item_id >= 0:
                rel_cell = self._screen_to_cell(*event.pos) if on_map else None
                item   = self.drag_item
                origin = self.drag_item_origin
                moved  = (rel_cell is not None and origin is not None
                          and (rel_cell.col != origin.col or rel_cell.row != origin.row))
                if moved:
                    self._drop_dragged_item(rel_cell)
                elif item is not None and origin is not None:
                    items_at_cell = self.bm.get_items_at_cell(origin)
                    if items_at_cell:
                        cur_idx = self._current_agent_idx() if self.combat_active else self.selected_idx
                        if cur_idx >= 0:
                            agent = self.bm.placed_agents[cur_idx]
                            if not agent.conditions.dead:
                                dc = max(agent.origin.col - origin.col,
                                         origin.col - (agent.origin.col + agent.size - 1), 0)
                                dr = max(agent.origin.row - origin.row,
                                         origin.row - (agent.origin.row + agent.size - 1), 0)
                                if max(dc, dr) <= 1:
                                    dm.show_item_pickup_menu(self, origin, items_at_cell, cur_idx, event.pos)
                self._clear_item_drag()
                continue

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if self.drag_idx >= 0:
                    if self.drag_valid and self.drag_cell is not None and (
                            not self.combat_active or self.combat_paused or self.tracker_mode):
                        # Free pre-combat repositioning, paused DM repositioning, or any tracker
                        # mode drag (T5): placement validity was already checked (_can_place),
                        # so bypass the movement rules (speed / range / pathing, opportunity
                        # attacks) entirely and set the agent's position directly.
                        if self.bm.set_agent_position(self.drag_idx, self.drag_cell):
                            self.selected_idx = self.drag_idx
                            self._mark_fog_dirty()   # DM/pre-combat reposition moves a token
                            # Its Spirit Guardians (any anchored Emanation) comes along.
                            self.combat.recenter_anchored_effects(self.bm, self.drag_idx)
                        self._update_reach()
                        self._update_attack_overlay()
                    elif self.drag_valid and self.drag_cell is not None:
                        # A DM drag during a player's turn takes that turn over (D-M5-4.6).
                        net_offer.take_over(self)
                        if not self.commit_move(self.drag_idx, self.drag_cell, self.move_type,
                                                DM_PRINCIPAL_ID):
                            self.drag_valid = False
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
                            if net_picks.is_pick_prompt(self, self.prompts.live):
                                net_offer.take_over(self)     # M5d Step 0.6
                            self._execute_jump(idx, cell)

            # ── Mob selection dialog ──────────────────────────────────────
            if not self.combat_active:
                if self.mob_dialog.handle(event):
                    pass  # Event was consumed by dialog

                # ── Panel widgets ─────────────────────────────────────────────
                # First match wins: a click belongs to exactly one panel widget.
                # Several handlers block in a modal and then re-anchor every panel rect
                # (app_dungeon_gen.on_generate_dungeon → _switch_to_page → _load_map_png →
                # _reposition_panel), so without this latch the same MOUSEBUTTONDOWN
                # would keep being tested against the buttons below at their NEW
                # positions — that is how one click on Generate Dungeon also fired
                # Load Lighting and opened the file browser.
                _claimed = False

                def _hit(btn) -> bool:
                    nonlocal _claimed
                    if _claimed or not btn.clicked(event):
                        return False
                    _claimed = True
                    return True

                # Agents… — encounter save/load, Import DDB, Load PCs, Create Mob/PC
                if _hit(self.btn_agents):
                    dm.show_agents_menu(self)

                # Clear All — full scene wipe (agents + terrain + lighting);
                # the agents-only clear lives in the Agents… menu.
                if _hit(self.btn_clear):
                    self._clear_all()

                # Long Rest — reset all spell slots
                if _hit(self.btn_long_rest):
                    self._on_long_rest()

                # Short Rest — restore short-rest resources (Warlock pact slots, Monk Focus Points, …)
                if _hit(self.btn_short_rest):
                    self._on_short_rest()

                # Remove pending agent by clicking ✕ (rect-based, so it takes the same
                # first-match-wins latch as the buttons)
                if not _claimed and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    list_y = self.btn_clear.rect.bottom + 20 + 18
                    px_rm = self._panel_x()
                    for i in range(len(self.pending_configs)):
                        rx = px_rm + PANEL_W - 22
                        rb = pygame.Rect(rx, list_y + i*18 - 1, 16, 16)
                        if rb.collidepoint(event.pos):
                            self.pending_configs.pop(i)
                            _claimed = True
                            break

                # Begin Combat
                if _hit(self.btn_begin_combat):
                    if self.tracker_mode:
                        self._begin_encounter()
                    else:
                        self._start_combat()

                # Restore Autosave… — the active encounter's ring, newest first
                if _hit(self.btn_restore_autosave):
                    dm.show_restore_autosave_menu(self)

                # Table… — join code, players, lock, rewind, session log (D-M7-5)
                if _hit(self.btn_table):
                    dm.show_table_menu(self)

                if _hit(self.btn_reset_dungeon):
                    run_control.ask_reset(self, anchor=(self.btn_reset_dungeon.rect.x,
                                                        self.btn_reset_dungeon.rect.y))

                if _hit(self.btn_undo_reset):
                    run_control.ask_undo_reset(self, anchor=(self.btn_undo_reset.rect.x,
                                                             self.btn_undo_reset.rect.y))

                if _hit(self.btn_load_save):
                    dm.show_load_save_menu(self)

                # Terrain… — edit / load / save / generate / show-hide / clear
                if _hit(self.btn_terrain):
                    dm.show_terrain_menu(self)

                # Lighting… — edit / load / show-hide overlay
                if _hit(self.btn_lighting):
                    dm.show_lighting_menu(self)

                # Items… — place catalog items, keys and chests; edit chests
                if _hit(self.btn_items):
                    items_play.show_items_menu(self, anchor=(self.btn_items.rect.x,
                                                             self.btn_items.rect.y))

                # Dungeon… — New / Open / Floors… / Populate Floor… and the rest
                if _hit(self.btn_dungeon):
                    dm.show_dungeon_menu(self)

                # Toggle Wall Auto-Detection
                if _hit(self.btn_toggle_walls):
                    self._confirm_overwrite([self._terrain_path], "Toggle walls",
                                            self._toggle_walls, anchor=event.pos)

                # FOG menu: on/off, DM-screen opacity, reset (asks to confirm)
                if _hit(self.btn_fog):
                    board.show_fog_button_menu(self, event.pos)

                # Toggle move animation: off lands moves at once (M4b B-7)
                if _hit(self.btn_toggle_animate):
                    self._set_animate_moves(not self.animate_moves)

                # Set Grid (sample a tile to define a uniform grid)
                if _hit(self.btn_set_grid):
                    self._toggle_grid_sample_mode()

                # Quit (asks before overwriting the terrain file)
                if _hit(self.btn_quit):
                    self._request_quit(event.pos)

            else:
                # ── On Deck deploy click detection (checked before initiative) ─
                _deployed_click = False
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for item_rect, group_name in self.on_deck_item_rects:
                        if item_rect.collidepoint(event.pos):
                            app_initiative.deploy_on_deck_group(self, group_name)
                            _deployed_click = True
                            break

                # ── Initiative list click detection ────────────────────────────
                if not _deployed_click and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for item_rect, agent_idx in self.initiative_item_rects:
                        if item_rect.collidepoint(event.pos):
                            # Show conditions dialog for clicked agent
                            if 0 <= agent_idx < len(self.bm.placed_agents):
                                agent = self.bm.placed_agents[agent_idx]
                                cond = self.combat.get_agent_conditions(self.bm, agent_idx)
                                self.conditions_dialog.open(agent.name, cond, agent_idx)
                            break

                # ── Combat panel buttons ───────────────────────────────────
                # D-M5-1: a click names an action id and `perform` runs it; the bodies
                # live there now, so a remote submit runs exactly what this click does.
                # One widget per id (F10) and one click per event: the first offered id
                # under the pointer is the only one.
                _clicked = next((a for a in self._action_menu
                                 if self._action_clicked(a, event)), None)
                if _clicked is not None:
                    # D-M5-7: the DM acts; the player's offer ends. A DM tool that does
                    # not act on the turn leaves the offer up: the reaction timer, Pause
                    # (whose gate withdraws the offer quietly, as nobody took it over),
                    # and the Table menu (D-M7-5). Otherwise the table would read "the DM
                    # took over Kira's turn" for a pause.
                    if _clicked not in net_offer.NOT_A_TAKEOVER:
                        net_offer.take_over(self)
                    self.perform(_clicked, DM_PRINCIPAL_ID, event.pos)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for mv_mt, mv_rect in self._move_type_btns.items():
                        if mv_rect.collidepoint(event.pos):
                            self.move_type = mv_mt
                            self._update_reach()
                            break
                if self.btn_show_terrain.clicked(event):
                    self.show_terrain = not self.show_terrain
                if self.btn_show_spell_effects.clicked(event):
                    self.show_spell_effects = not self.show_spell_effects
                if self.btn_show_visible_targets.clicked(event):
                    self._show_visible_targets_popup()
                # Item pickup: click a cell with items
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and on_map \
                        and not self.context_menu.visible \
                        and not self._armed_slot(pending.Attack) and not self._armed_slot(pending.Spell) \
                        and not self._armed(pending.Shove) \
                        and not self._pick_data("cleave") and not self._pick_data("sweep") \
                        and not self._pick_data("rally") and not self._pick_data("feint"):
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
                                dm.show_item_pickup_menu(self, cell, items_at_cell, cur_idx, event.pos)

        return True

    # ─────────────────────────────────────────────────────────────────────
    #  Floor-nav block (docked in the config panel, not over the map)
    # ─────────────────────────────────────────────────────────────────────
    _FLOOR_NAV_HDR   = 16   # header ("Floor z — id") line height
    _FLOOR_NAV_BH    = 24   # nav button height
    _FLOOR_NAV_VGAP  = 4    # vertical gap between header/rows


    def _draw_panel_floor_nav(self, px, lx, W):
        return app_dungeon_pages.draw_panel_floor_nav(self, px, lx, W)

    # ─────────────────────────────────────────────────────────────────────
    #  The net thread's turn on this thread
    # ─────────────────────────────────────────────────────────────────────
    def _pump_net(self):
        """Run what the net thread has queued (D-M4-3, MULTIPLAYER_PLAN.md M4d).

        One line, and it exists because there are seven callers: the frame loop, and the
        six blocking modals that would otherwise stall the queue for as long as a DM
        reads a dialog. The plan has called it `_pump_net()` since Step 0.7's spike; this
        is where the name stops being a convention.

        **It pumps the command queue and nothing that redraws.** That is the whole of
        D-M4-3, and it is what makes the six call sites safe: state may advance while a
        modal owns the screen, but nothing draws underneath one.

        Placement inside those loops is first-in-the-body, above `pygame.event.get()`, so
        a command queued while the modal was opening runs on the first iteration instead
        of losing a race to an event that returns out of the loop.

        Not inside *work* — only inside a loop that is waiting for input (D-M4d-3). The
        terrain carve and the dungeon build run after their dialogs close, and a command
        is `build_view`, which reads `app.bm`; pumping one mid-rebuild is a read of the
        `BattleMap` while it is being rewritten, which is the C++ invariant NN1's
        tightening is about. So M4d bounds the 503 window rather than removing it.

        **Reentrancy is refused, and that is D-M4d-4 with teeth.** A command that opened a
        modal would enter that modal's loop from inside a pump, and the loop's own first
        line would pump again — re-entering `pygame.event.get()` at a depth the outer loop
        does not know about. The guard turns that into an exception on the first line of
        the nested loop, before it draws anything, which `CommandQueue.pump` then carries
        to the future (rule 2) and the route turns into a status. The frame loop survives,
        which is the only outcome that matters.
        """
        if self._net_pumping:
            raise RuntimeError("a command may not open a modal or pump the queue (D-M4d-4)")
        self._net_pumping = True
        try:
            return net_link.pump_commands(self)
        finally:
            self._net_pumping = False

    # ─────────────────────────────────────────────────────────────────────
    #  Main loop
    # ─────────────────────────────────────────────────────────────────────
    def run(self):
        # Startup, in the sense the frozen user procedure means it: the join code and the
        # URL are printed before the first frame, by the one entry point that is a running
        # app rather than a constructed one.
        net_link.start_player_server(self)
        self.confirm_overwrites = True
        running = True
        while running:
            running = self._handle_events() and self._quit_requested is None
            self.floor_checklist.tick(self)     # W7: back to Floors… once its tool closes
            # Playback (playback.py) shows a trace's board in place of the DM's scene: nothing
            # may act on it, and nothing about it may reach the players. Their submits and
            # reads wait, and are answered from the DM's scene once Playback closes.
            pb = self.playback
            if pb is None:
                net_link.pump_submits(self)     # M5a: remote answers, decided where clicks are; D-M5-7 expiry
                self._drive_npc_turn_if_pending()   # NPC automation: one engine-driven turn per frame
                self._offer_keeper_of_souls_if_pending()   # Grave Cleric L17: an enemy died nearby
                self._offer_beguiling_twist_if_pending()   # Fey Wanderer L7: a Charm/Fear save succeeded
            else:
                pb.tick()                       # Playback: start the next recorded turn
            self._advance_npc_playback()        # NPC turn playback: animate the recorded turn
            if pb is None:
                self._refresh_fog()             # fog of war: monotonic reveal when marked stale
                self._pump_net()                # M4c: answer what the net thread asked for
                net_link.push_cycle(self)       # M4: publish the party's page image to the net thread
            self.screen.fill(COL_BG)
            app_board_render.draw_map(self)
            app_board_render.draw_map_overlays(self)           # terrain, spell and light areas (under the fog)
            app_board_render.draw_fog_overlay(self)            # fog of war: grey never-seen cells (above map, below agents)
            self.floor_align.draw(self)         # Align Floor: the other floor's ghost pages
            app_board_render.draw_agents(self)
            app_board_render.draw_floating_texts(self)                     # transient outcome flashes above tokens
            app_board_render.draw_npc_announcement(self)                   # NPC playback: typewriter action text
            app_board_render.draw_safe_target_highlights(self)
            app_board_render.draw_hover_cursor(self)                       # always-on map cursor (in & out of combat)
            app_board_render.draw_agent_hover_name(self)                   # token name shown only under the pointer
            if pb is not None:
                pb.draw_map_layer()                         # Playback: actor ring + HUD line
                pb.draw_panel()                             # Playback: its controls, in the panel
            else:
                app_board_render.draw_staircase_hover(self)                # staircase name/label/destination
                app_board_render.draw_room_label_hover(self)               # "K10. Dining Hall" under the pointer
                app_board_render.draw_dm_view_banner(self)                 # D1: "DM VIEW" while it is on
                app_board_render.draw_zoom_control(self)                   # − 100% + Fit, bottom-right of the map
                self._draw_panel()                          # config panel (hosts the Floor-nav block)
                net_offer.ensure(self)                      # D-M5-2: the offer, from the menu just built
                app_panel_render.draw_cursor_cell_info(self)               # debug: cell under cursor
                app_panel_render.draw_xp_total(self)                       # running party-XP scoreboard (bottom-right)
            self.terrain_editor.draw(self.screen)          # modal — always on top
            self.lighting_editor.draw(self.screen)         # modal — always on top
            self._wall_detect_dialog.draw(self.screen)     # docked over the panel
            self.dungeon_wizard.draw(self.screen)          # docked over the panel
            self.floor_checklist.draw(self.screen)         # docked over the panel
            self._npc_auto_dialog.draw(self.screen)        # docked over the panel
            self.terrain_placement_dialog.draw(self.screen)  # modal — always on top
            self.file_browser.draw(self.screen)     # modal — always on top
            self.stats_dialog.draw(self.screen)    # modal — always on top
            self.weapon_dialog.draw(self.screen)   # modal — always on top
            self.armor_dialog.draw(self.screen)    # modal — always on top
            self.weapons_dialog.draw(self.screen)  # modal — always on top
            self.items_dialog.draw(self.screen)    # modal — always on top
            self.spell_dialog.draw(self.screen)    # modal — always on top
            self.spell_selection_dialog.draw(self.screen)  # modal — always on top
            self.armor_selection_dialog.draw(self.screen)  # modal — always on top
            self.weapon_selection_dialog.draw(self.screen)  # modal — always on top
            self.item_selection_dialog.draw(self.screen)   # modal — always on top (over ItemsDialog)
            self.mob_dialog.draw(self.screen)      # modal — always on top
            self.conditions_dialog.draw(self.screen)  # modal — always on top
            self.context_menu.draw(self.screen)    # popup — topmost
            self.spell_grid_menu.draw(self.screen) # multi-column spell grid — topmost popup
            self._element_dialog.draw(self.screen) # cast-time element picker — topmost modal
            self._grid_span_dialog.draw(self.screen) # grid-span picker — topmost modal
            self.team_dialog.draw(self.screen)     # team picker — topmost modal
            self.name_prompt.draw(self.screen)     # rename prompt — topmost modal
            pygame.display.flip()
            self.clock.tick(60)
        if self.playback is not None:       # the save below is the DM's scene's
            self.playback.exit()
        # Clean up temporary terrain effects before quitting
        self.bm.clear_terrain_effects()
        self._clear_temporary_terrain()
        if self._quit_requested != "nosave":
            self._save_terrain()
        if self._net is not None:
            self._net.stop()                # release 6081 before the process goes
        pygame.quit()


# ─────────────────────────────────────────────────────────────────────────────
STANDALONE_SUBDIR = "standalone"


def standalone_encounter_base(png_path: str) -> str:
    """The agents path a PNG opened on its own reads and writes its encounter under.

    Normally ``<dir>/<stem>_agents.json`` (and so ``<stem>_terrain.json`` etc.). But a
    dungeon page in the same folder may already own that base for a DIFFERENT image —
    e.g. Castle Ravenloft's main floor uses ``main_floor_ravenloft_agents.json`` with
    ``main_floor_ravenloft_32px.png``. Opening ``main_floor_ravenloft.png`` directly
    would then load and overwrite that page's grid and edge walls on a drawing of
    another size, so every cell index lands in the wrong place.

    In that case the PNG gets its own sidecars in ``<dir>/standalone/`` instead, and
    the dungeon's files are left alone. A PNG that IS the page's image keeps sharing
    them, since its grid matches.
    """
    map_dir = os.path.dirname(os.path.abspath(png_path))
    stem = os.path.splitext(os.path.basename(png_path))[0]
    default = os.path.join(map_dir, stem + "_agents.json")
    me = os.path.realpath(png_path)
    try:
        names = os.listdir(map_dir)
    except OSError:
        return default
    for fn in sorted(names):
        if not fn.endswith(".dungeon.json"):
            continue
        manifest = os.path.join(map_dir, fn)
        try:
            dungeon = Dungeon.load(manifest)
        except Exception:                        # noqa: BLE001 — a bad manifest owns nothing
            continue
        for page in dungeon.pages:
            def _res(p):
                return p if (not p or os.path.isabs(p)) else os.path.join(map_dir, p)
            if not page.encounter_base or not page.png:
                continue
            if os.path.abspath(_res(page.encounter_base)) != default:
                continue
            if os.path.realpath(_res(page.png)) == me:
                return default                   # same image: sharing is correct
            alt_dir = os.path.join(map_dir, STANDALONE_SUBDIR)
            os.makedirs(alt_dir, exist_ok=True)
            print(f"[*] {os.path.basename(png_path)}: '{stem}_*' files belong to dungeon "
                  f"page '{page.id}' ({page.png}) in {fn}; using "
                  f"{STANDALONE_SUBDIR}/{stem}_* for this image instead.")
            return os.path.join(alt_dir, stem + "_agents.json")
    return default


def _campaign_start(path: str, camp_root: str):
    """``(image, dungeon.json)`` for a path in a campaign: a ``dungeon.json``, a folder at
    or inside a dungeon, or the campaign folder itself when it holds exactly one dungeon.
    The image is that of the map the dungeon's run was last on, else its entry map."""
    camp = save_layout.Campaign(camp_root)
    d = path if os.path.isdir(path) else os.path.dirname(path)
    manifest = None
    while d.startswith(camp_root) and d != camp_root:
        if os.path.isfile(os.path.join(d, save_layout.DUNGEON_FILE)):
            manifest = os.path.join(d, save_layout.DUNGEON_FILE)
            break
        d = os.path.dirname(d)
    if manifest is None:
        names = camp.list_dungeons()
        if len(names) != 1:
            raise ValueError(f"{camp.name}: open one of its dungeons: "
                             + (", ".join(names) or "(it has none)"))
        manifest = camp.dungeon(names[0]).manifest_path
    layout = camp.dungeon(os.path.basename(os.path.dirname(manifest)))
    try:
        dungeon = Dungeon.load(manifest)
    except Exception as e:                       # noqa: BLE001 — report any bad file
        raise ValueError(f"Not a dungeon: {manifest} ({e})") from e
    current = None
    if os.path.exists(layout.run_path()):
        try:
            with open(layout.run_path()) as f:
                current = json.load(f).get("current_map")
        except (OSError, ValueError):
            current = None
    page = dungeon.page_by_id(current) or dungeon.entry_page()
    if page is None:
        raise ValueError(f"Dungeon has no maps: {manifest}")
    png = layout.image(page.id)
    if not png:
        raise ValueError(f"Map '{page.id}': no image in {layout.name}/maps or the library")
    return png, manifest


def resolve_start_path(path: str):
    """Work out what to open from the command-line argument.

    ``path`` is a map image, a ``.dungeon.json`` manifest, or a campaign path (a
    campaign or dungeon folder, or a ``dungeon.json``; see ``_campaign_start``). Returns
    ``(png_path, manifest_path)``: for an image, ``(path, None)``; for a manifest, the
    entry page's PNG (resolved against the manifest's folder) and the manifest's
    absolute path. Raises ``ValueError`` with a readable message if the manifest is
    unreadable, has no pages, or its entry PNG is missing.

    Opening a floor through its manifest always uses the PNG the manifest names, so
    its grid and edge walls land on the image they were drawn on.
    """
    camp_root = save_layout.find_campaign(path)
    if camp_root is not None and (os.path.isdir(path)
                                  or os.path.basename(path) == save_layout.DUNGEON_FILE):
        return _campaign_start(os.path.abspath(path), camp_root)
    if not path.lower().endswith(".json"):
        return path, None
    manifest = os.path.abspath(path)
    try:
        dungeon = Dungeon.load(manifest)
    except Exception as e:                       # noqa: BLE001 — report any bad file
        raise ValueError(f"Not a dungeon manifest: {path} ({e})") from e
    entry = dungeon.entry_page()
    if entry is None:
        raise ValueError(f"Dungeon manifest has no pages: {path}")
    png = entry.png
    if not os.path.isabs(png):
        png = os.path.join(os.path.dirname(manifest), png)
    if not os.path.exists(png):
        raise ValueError(f"Entry page '{entry.id}': map image not found ({entry.png})")
    return png, manifest


if __name__ == "__main__":
    # Positional: map image OR a .dungeon.json manifest. Optional: --seed N to fix the combat RNG for
    # reproducible live play (0/any int; omitted ⇒ time-based random seed).
    args = sys.argv[1:]
    seed = None
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--seed":
            if i + 1 >= len(args):
                sys.exit("--seed requires an integer value")
            seed = int(args[i + 1]); i += 2
        elif a.startswith("--seed="):
            seed = int(a.split("=", 1)[1]); i += 1
        else:
            positional.append(a); i += 1
    if not positional:
        # Default to the bundled blank map (maps/Blank.png: a plain 30×20 grid, no
        # walls) so the app launches with a map to build onto.
        default_map = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "maps", "Blank.png"))
        if not os.path.exists(default_map):
            sys.exit("Usage: python main.py <map_image.png | dungeon.json> [--seed N]")
        positional.append(default_map)
    try:
        start_png, start_manifest = resolve_start_path(positional[0])
    except ValueError as e:
        sys.exit(str(e))
    app = App(start_png, seed=seed)
    if start_manifest is not None:
        # Same path as Dungeon → Open Dungeon…: loads the entry page's encounter.
        app._on_open_dungeon_chosen(start_manifest)
    app.run()
