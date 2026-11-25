"""Spell casting: the spell lifecycle. Starting and activating a cast (`start_cast_spell`,
`activate_spell`, the geometry dispatch, the spell browser and ward-type prompts), resolving
it (single / AoE / teleport / corpse / Animate Dead / Planar Binding / multi-target, the
finish, Wild Magic Surge), paying for it (slot, Pact slot level, Action + Bonus costs),
logging its results, the aiming reads (`pending_spell*`, `aoe_cells`, `area_template`,
range / line-of-sight filtering, wall anchors), and the spell-specific flows: the Chromatic
Orb chain, armed Metamagic, Dispel Magic, Wish / Divine Intervention, and Beguiling /
Bewitching Magic.

Moved out of `App` in APP_REFACTOR_PLAN.md A4, the same way as `app_attacks.py` (A2c):
module-level functions taking the app. The arm itself is `app.pending` (`pending.Spell`)
and `app.cast_setup`; `combat`, `bm` and the turn state stay on `app` (D3).

`App` keeps a one-line forwarder for each function here that is reached by name from
outside `main.py` (`net/picks.py`, `menus/features.py`, `menus/board.py`, `prompts.py`,
`app_attacks.py`, `app_board_render.py`, tests) or bound as a callback (`_on_wish_duplicate`,
`_drop_di_wish_free`, `_finish_cast`, `_finish_multi_target_spell`). Calls between those go
through the forwarder (`app._finish_cast()`), so a test that wraps one on the instance still
sees every call; the rest are called directly.

The spell-only option tables that used to sit at the top of `main.py` live here too;
`main.py` imports back the one it still reads (`CLERIC_DI_SPELL_NAMES`). The summon registry
(`SUMMON_SPELL_TO_SPIRIT`, `SUMMON_SPELL_TO_MONSTER`) lives in `app_summons.py` (A4b).
"""

import math

import pygame

import rpg_battle_map as rpg

import pending
from constants import FLASH_BAD, FLASH_GOOD
from helpers import _INT_TO_ABILITY, _dict_to_spell, is_item_spell, item_spell_label
from menus import features
from net import picks as net_picks
from app_summons import SUMMON_SPELL_TO_MONSTER, SUMMON_SPELL_TO_SPIRIT
from prompts import SPELL_BROWSER_RENDER


# Multi-target spells whose darts / rays / beams may each pick the same creature again.
_REPEAT_TARGET_SPELLS = frozenset({"Magic Missile", "Scorching Ray", "Eldritch Blast"})


# Spells whose damage type is chosen per cast (not fixed in spells.json). Each maps to the
# ElementPickerDialog option list (label, MagicDamage_t int) of the legal types. The choice is
# stored as SpellAction.damage_type_override and rewrites the cast's damage type in executeSpell.
# MagicDamage_t: Acid=0, Cold=1, Fire=2, Lightning=4, Poison=6, Psychic=7, Thunder=9.
ELEMENT_CHOICE_SPELLS = {
    "Chromatic Orb":   [("Acid", 0), ("Cold", 1), ("Fire", 2), ("Lightning", 4), ("Poison", 6), ("Thunder", 9)],
    "Sorcerous Burst": [("Acid", 0), ("Cold", 1), ("Fire", 2), ("Lightning", 4), ("Poison", 6), ("Psychic", 7), ("Thunder", 9)],
}


# Magic Circle / Hallow movement ward (D4): the creature types a caster may ward, plus a "Reverse"
# toggle. Each type value is a rpg.CreatureType bit (int); the caster toggles any subset and
# optionally Reverse. The OR of the checked type bits becomes SpellAction.ward_creature_mask; the
# Reverse sentinel sets ward_traps=True (keep the warded types INSIDE instead of out). Asked as a
# toggle loop of plain choice prompts (App._ask_ward_types, M5e E-6). RAW Magic Circle offers the
# five non-Aberration types.
WARD_REVERSE_SENTINEL = 1 << 30
MAGIC_CIRCLE_TYPE_OPTIONS = [
    ("Celestials", int(rpg.CreatureType.Celestial)),
    ("Elementals", int(rpg.CreatureType.Elemental)),
    ("Fey",        int(rpg.CreatureType.Fey)),
    ("Fiends",     int(rpg.CreatureType.Fiend)),
    ("Undead",     int(rpg.CreatureType.Undead)),
    ("↺ Reverse (trap them inside)", WARD_REVERSE_SENTINEL),
]

# Divine Intervention (Cleric L10): the explicit set of Cleric spells (levels 0-5) the DI picker
# may offer. spells.json has no reliable per-spell class list, so scope by name. None of these is
# Reaction-cast, so the SRD "doesn't require a Reaction" clause is automatically satisfied. The L20
# Greater-DI Wish option is added separately when building the picker.
CLERIC_DI_SPELL_NAMES = {
    # cantrips
    "Guidance", "Light", "Mending", "Resistance", "Sacred Flame", "Spare the Dying", "Thaumaturgy",
    "Toll the Dead",
    # 1
    "Bane", "Bless", "Command", "Create or Destroy Water", "Cure Wounds", "Detect Evil and Good",
    "Detect Magic", "Detect Poison and Disease", "Guiding Bolt", "Healing Word", "Inflict Wounds",
    "Protection from Evil and Good", "Purify Food and Drink", "Sanctuary", "Shield of Faith",
    # 2
    "Aid", "Augury", "Blindness/Deafness", "Calm Emotions", "Continual Flame", "Enhance Ability",
    "Find Traps", "Gentle Repose", "Hold Person", "Lesser Restoration", "Locate Object",
    "Prayer of Healing", "Protection from Poison", "Silence", "Spiritual Weapon", "Warding Bond",
    "Zone of Truth",
    # 3
    "Animate Dead", "Beacon of Hope", "Bestow Curse", "Clairvoyance", "Create Food and Water",
    "Daylight", "Dispel Magic", "Glyph of Warding", "Magic Circle", "Mass Healing Word",
    "Meld into Stone", "Protection from Energy", "Remove Curse", "Revivify", "Sending",
    "Speak with Dead", "Spirit Guardians", "Tongues", "Water Walk",
    # 4
    "Aura of Life", "Banishment", "Control Water", "Death Ward", "Divination", "Freedom of Movement",
    "Guardian of Faith", "Locate Creature", "Stone Shape",
    # 5
    "Commune", "Contagion", "Dispel Evil and Good", "Flame Strike", "Geas", "Greater Restoration",
    "Hallow", "Insect Plague", "Legend Lore", "Mass Cure Wounds", "Planar Binding", "Raise Dead", "Scrying",
}

# Vistani Curse sub-choices, reused via the ElementPickerDialog. Each maps to
# SpellAction.curse_choice, decoded in executeSpell's condition chokepoint:
#   Vulnerability → damage type: 0..9 = MagicDamage_t, 100+i = PhysicalDamage_t i.
#   Weakness      → SaveAbility_t: Str=0, Dex=1, Con=2, Int=3, Wis=4, Cha=5.
#   Affliction    → 0=Blinded, 1=Deafened, 2=Both.
CURSE_VULNERABILITY_OPTIONS = [
    ("Acid", 0), ("Cold", 1), ("Fire", 2), ("Force", 3), ("Lightning", 4),
    ("Necrotic", 5), ("Poison", 6), ("Psychic", 7), ("Radiant", 8), ("Thunder", 9),
    ("Bludgeoning", 100), ("Piercing", 101), ("Slashing", 102),
]
CURSE_WEAKNESS_OPTIONS = [
    ("Strength", 0), ("Dexterity", 1), ("Constitution", 2),
    ("Intelligence", 3), ("Wisdom", 4), ("Charisma", 5),
]
CURSE_AFFLICTION_OPTIONS = [("Blinded", 0), ("Deafened", 1), ("Both", 2)]
CURSE_CHOICE_SPELLS = {
    "Curse of Vulnerability": CURSE_VULNERABILITY_OPTIONS,
    "Curse of Weakness":      CURSE_WEAKNESS_OPTIONS,
    "Curse of Affliction":    CURSE_AFFLICTION_OPTIONS,
}


BREATH_WEAPON_POOL = "Breath Weapon"


def is_breath_weapon(sp) -> bool:
    """A Dragonborn Breath Weapon shape (Cone / Line): paid from the species pool."""
    return sp.resource_name == BREATH_WEAPON_POOL


def start_cast_spell(app, slot: str):
    app.jump_overlay_active = False  # Close jump overlay when casting spell
    app.jump_reachable_cells = []
    idx = app._current_agent_idx()
    if idx < 0:
        return

    # Get castable spells from C++ layer (respects both NPC and player rules). War Magic has
    # its own engine-side eligibility list (action-cantrips L7+, level 1-5 action spells L18+).
    if slot == "war_magic":
        available_indices = app.combat.available_war_magic_spells(app.bm, idx)
    else:
        available_indices = app.combat.available_castable_spells(app.bm, idx)
    # Dragonborn Breath Weapon (SPECIES_PLAN.md D7) replaces one attack of the Attack action:
    # the "breath" slot lists only its two shapes, and the plain cast menus never list them.
    _all = app.combat.get_agent_spells(app.bm, idx)
    available_indices = [i for i in available_indices
                         if is_breath_weapon(_all[i]) == (slot == "breath")]
    if not available_indices:
        # Nothing was cast, so nothing is spent: the Action and its attacks remain available.
        app._combat_log_add("No available spells!")
        return

    spells = app.combat.get_agent_spells(app.bm, idx)
    stats = app.combat.get_agent_stats(app.bm, idx)

    # Thin wrapper so the menu builders below keep their simple (slot, spell_idx, level)
    # signature. The real dispatch lives in _activate_spell so the Wish flow can reuse the
    # full element/curse/summon/geometry handling for a duplicated spell.
    def _activate(s, si_, slot_level_=0, use_grant=False):
        app._activate_spell(s, si_, slot_level_, idx, spells, stats, use_grant=use_grant)

    def _ordinal(n):
        return {1:"1st",2:"2nd",3:"3rd"}.get(n, f"{n}th")

    def _show_level_menu(name, subs):
        # Second popup: pick the slot level for one already-chosen spell. Shown at the
        # mouse so it appears next to the click that selected the spell.
        app._ask_actor(idx, "action",
                        f"{app._agent_name(idx)}: {name} — at which slot level?",
                        [(f"{name} {lbl}", cb) for lbl, cb in subs],
                        anchor=pygame.mouse.get_pos())

    # Quickened Spell (Sorcerer Metamagic) lets an Action-cast spell be cast as a Bonus
    # Action. When it is armed, the bonus menu also offers Action-cast spells — the engine
    # folds in Quickened and spends the 2 SP on cast (_apply_armed_metamagic).
    quickened_armed = (slot == "bonus" and
                       rpg.MetamagicOption.Quickened in armed_metamagic_options(app, idx))
    # Wild Magic Surge band 6 does the same for its 1-minute window, at no SP cost.
    wild_bonus_cast = (slot == "bonus" and
                       app.combat.get_agent_stats(app.bm, idx).wild_magic_bonus_cast_turns > 0)

    # Build spell menu from available spells. Each spell contributes ONE top-level row;
    # leveled player spells with more than one castable level open a follow-up popup to
    # pick the slot level, instead of flooding this list with one row per spell per level.
    options = []
    for si in available_indices:
        # Spells injected by a past Wish or Divine Intervention live in the caster's list only so
        # the engine can cast them by index; they must never reappear as normal slot-castable options.
        if si in app._wish_temp_spells or si in app._di_temp_spells:
            continue
        sp = spells[si]
        sp_level = sp.level

        # Filter by casting_time based on which action button was clicked. (War Magic's list is
        # already filtered engine-side by available_war_magic_spells, so no extra filter here.)
        if sp.casting_time == rpg.CastingTime.Reaction:
            continue  # a Reaction spell (Hellish Rebuke) is offered in its reaction window
        if slot == "action" and sp.casting_time == rpg.CastingTime.BonusAction:
            continue  # Skip bonus-action spells from the action menu
        elif slot == "bonus" and sp.casting_time != rpg.CastingTime.BonusAction:
            # The bonus menu normally shows only Bonus-Action spells; with Quickened armed it
            # also offers Action-cast spells (which then cast as a Bonus Action via Quickened),
            # and so does a Wild Magic bonus-cast surge.
            if not ((quickened_armed or wild_bonus_cast)
                    and sp.casting_time == rpg.CastingTime.Action) and not (
                    sp.name == "Spare the Dying" and app._grave_return_to_life(stats)):
                continue  # Skip non-bonus-action spells from the bonus menu

        # An Action + Bonus Action spell needs the Action slot and an unspent Bonus Action, so
        # Quickened, a Wild Magic bonus cast and War Magic can't carry it.
        if spell_costs_action_and_bonus(app, sp) and (slot != "action" or app.bonus_used):
            continue

        if is_item_spell(sp):
            # Enspelled item: the item pays, at the spell's base level (E2, D6) — no slot
            # to pick. Labelled with the item and its uses, at will, or charges (E4).
            def _pick_item(s=slot, si_=si, lvl=sp_level):
                _activate(s, si_, lvl)
            options.append((item_spell_label(app.combat, app.bm, idx, sp), _pick_item))
        elif sp_level == 0:
            # Cantrip - always available, no level to pick
            def _pick_cantrip(s=slot, si_=si):
                _activate(s, si_, 0)
            label = (f"{sp.name} ({stats.breath_weapon_remaining()} left)"
                     if is_breath_weapon(sp) else f"{sp.name} ∞")
            options.append((label, _pick_cantrip))
        elif stats.is_npc:
            # NPC: just add the spell (availability already checked by available_castable_spells)
            def _pick_npc(s=slot, si_=si):
                _activate(s, si_, 0)
            options.append((sp.name, _pick_npc))
        else:
            # Player leveled spell: gather every castable level into a per-spell sub-list.
            level_options = []
            # Granted spell (SPECIES_PLAN.md D3): its free casts per Long Rest come first, at
            # the spell's base level and with no slot; the slot rows follow as usual.
            free_left = stats.granted_free_left(sp.name)
            if free_left > 0:
                def _pick_free(s=slot, si_=si, lvl=sp_level):
                    _activate(s, si_, lvl, use_grant=True)
                level_options.append((f"free ×{free_left}", _pick_free))
            # A granted spell is listed for its free cast even after this turn's slot spell,
            # so its slot rows still honour the one-slot-spell-per-turn rule.
            slots_ok = free_left == 0 or stats.can_cast_leveled_spell()
            for lvl in range(sp_level, 10):
                remaining = stats.spell_slots_remaining[lvl - 1]
                if remaining > 0 and slots_ok:
                    label = f"@ {_ordinal(lvl)} ({remaining} slot{'s' if remaining != 1 else ''})"
                    def _pick_slot(s=slot, si_=si, sl=lvl):
                        _activate(s, si_, sl)
                    level_options.append((label, _pick_slot))

            # Aberrant Mind L3+ Psionic Sorcery: offer SP-spend option for psionic spells
            # even when no regular slots are available (or in addition to slots).
            if (sp.name in app._PSIONIC_SPELL_NAMES and
                    stats.character_class == rpg.CharacterClass.Sorcerer and
                    stats.sorcerer_subclass == rpg.SorcererSubclass.Aberrant and
                    stats.char_level >= 3):
                sp_res = stats.get_resource("Sorcery Points")
                if sp_res:
                    for psi_lvl in range(sp_level, 6):  # Psionic Sorcery caps at L5
                        if sp_res.current >= psi_lvl:
                            def _pick_psionic(s=slot, si_=si, sl=psi_lvl):
                                ok = app.combat.spend_sorcery_points_for_spell(app.bm, idx, sl)
                                if ok:
                                    _activate(s, si_, sl)
                                    app.cast_setup.free_cast = True
                            level_options.append(
                                (f"@ {_ordinal(psi_lvl)} — {psi_lvl} SP (no slot)", _pick_psionic))

            if not level_options:
                continue

            if len(level_options) == 1:
                # Only one castable level — cast directly, no second popup needed.
                options.append((f"{sp.name} {level_options[0][0]}", level_options[0][1]))
            else:
                def _open_levels(name=sp.name, subs=level_options):
                    _show_level_menu(name, subs)
                options.append((f"{sp.name} ▸", _open_levels))

    if not options:
        # Nothing was cast, so nothing is spent: the Action and its attacks remain available.
        app._combat_log_add("No available spells!")
        return

    if len(options) == 1:
        options[0][1]()  # Call the action directly
    else:
        # Multi-column grid of clickable buttons — the spell list can hold dozens
        # of entries, far more than a single vertical column can show on-screen.
        slot_label = {"action": "Cast a spell", "bonus": "Bonus-action spell",
                      "war_magic": "War Magic spell",
                      "breath": "Breath Weapon"}.get(slot, "Cast a spell")
        # `slot_label` is the widget's own title strip, so it is the prompt title too:
        # a fuller sentence here would change what the DM sees. The wire's `actor`
        # field is what names the caster for a remote renderer.
        app._ask_actor(idx, "action", slot_label, options, render="grid")


def activate_spell(app, s, si_, slot_level_, idx, spells, stats, free_cast=False,
                   use_grant=False):
    """Set up targeting for a chosen spell and dispatch by its special-case / geometry.

    Shared by the normal cast menu (via the _activate wrapper in _start_cast_spell) and by
    the Wish duplication flow (_on_wish_duplicate), which passes free_cast=True so the
    duplicated spell consumes no slot of its own — Wish already charged its 9th-level slot.
    ``idx`` is the caster, ``spells``/``stats`` its current spell list and stats."""
    sp_ = spells[si_]
    # Cleared for every fresh cast; only the element-choice branch below sets it. free_cast is
    # normally False (a normal cast expends a slot); the Wish flow passes True.
    app.cast_setup.damage_type = -1
    app.cast_setup.free_cast    = free_cast
    # Granted spell (SPECIES_PLAN.md D3): the menu's "free" row pays with a free cast, no slot.
    app.cast_setup.use_grant    = use_grant
    app.cast_setup.command_word = -1
    app.cast_setup.curse_choice = -1
    app.cast_setup.forcecage_sealed   = False   # Forcecage form: False = Cage (20 ft), True = Box (10 ft)
    app.cast_setup.enlarge            = False   # Enlarge/Reduce mode: False = Reduce
    # A new cast always starts with no leftover Chromatic Orb leap chain (e.g. if a prior
    # chain was abandoned by a turn change), so stale hops can't hijack this cast's clicks.
    app._drop_pick("chromatic")
    app.pending_chromatic_primary = -1
    app.pending_chromatic_chain   = []

    # Wish (primary use): duplicate any spell of level ≤ 8. Open the spell picker; the chosen
    # spell is cast for free (Wish pays its own slot). Guard on free_cast so a Wish DUPLICATED
    # via another Wish can't recurse. See _on_wish_duplicate.
    if sp_.name == "Wish" and not free_cast:
        wish_slot = max(slot_level_, sp_.level)   # the slot Wish itself is cast from (9)
        ask_spell_browser(app, 
            idx, "Wish — duplicate a spell (≤ 8th level)",
            # A spell paid from a feature's pool (Breath Weapon) is not a spell Wish copies.
            [d for d in app.all_spells if d.get("level", 0) <= 8 and not d.get("resource_name")],
            lambda d, s=s, wl=wish_slot: app._on_wish_duplicate(idx, s, wl, d),
            # Greater DI's free Wish ends with its list: left set, the caster's next
            # real Wish would cost no slot (F-M5e-12). DI's use stays spent (F-M5e-2).
            on_cancel=app._drop_di_wish_free)
        app._combat_log_add("Wish — choose a spell of level 8 or lower to duplicate.")
        return

    # Cast-time element choice (Chromatic Orb, Sorcerous Burst): pick one damage type via
    # the ElementPickerDialog, store it as the SpellAction override, then continue to the
    # normal Single-target selection. Both spells are Single geometry, so the callback sets
    # up single-target pending state directly.
    elem_opts = ELEMENT_CHOICE_SPELLS.get(sp_.name)
    if elem_opts is not None:
        def _on_elem(chosen, s=s, si_=si_, sp_=sp_, slot_level_=slot_level_, elem_opts=elem_opts):
            app.cast_setup.damage_type = chosen[0] if chosen else -1
            app.pending = pending.Spell(s, si_, slot_level_)
            type_name = next((lbl for lbl, val in elem_opts
                              if val == app.cast_setup.damage_type), "?")
            app._combat_log_add(f"Casting {sp_.name} ({type_name}) — click a target.")
        # Cancel here casts with the default (F-M5e-3), so a remote client is told not to
        # draw a Cancel that would cast the spell (E-3). The same holds for the curse,
        # Command-word and Forcecage pickers below, and Mantle of Majesty's word.
        app._ask_actor(idx, "action", f"{sp_.name}: damage type",
                        [(lbl, (lambda v=val: _on_elem([v]))) for lbl, val in elem_opts],
                        render="picker", on_cancel=lambda: _on_elem([]),
                        cancellable=False)
        return

    # Vistani Curse sub-choice (Curse of Vulnerability / Weakness / Affliction): pick the
    # damage type / ability / blind-vs-deafen via the ElementPickerDialog, store it as
    # SpellAction.curse_choice, then continue to Single-target selection (all curses are
    # Single geometry). Mirrors the Chromatic Orb element-choice flow above.
    curse_opts = CURSE_CHOICE_SPELLS.get(sp_.name)
    if curse_opts is not None:
        def _on_curse(chosen, s=s, si_=si_, sp_=sp_, slot_level_=slot_level_, curse_opts=curse_opts):
            app.cast_setup.curse_choice = chosen[0] if chosen else -1
            app.pending = pending.Spell(s, si_, slot_level_)
            choice_name = next((lbl for lbl, val in curse_opts
                                if val == app.cast_setup.curse_choice), "?")
            app._combat_log_add(f"Casting {sp_.name} ({choice_name}) — click a target.")
        app._ask_actor(idx, "action", f"{sp_.name}: choose",
                        [(lbl, (lambda v=val: _on_curse([v]))) for lbl, val in curse_opts],
                        render="picker", on_cancel=lambda: _on_curse([]),
                        cancellable=False)
        return

    # Cast-time word choice (Command): pick the command word via the ElementPickerDialog
    # (same options Mantle of Majesty uses), store it as the SpellAction.command_word, then
    # fall through to the SHARED engine-driven targeting dispatch. Command is Multiple
    # geometry, so target count + upcast expansion are owned by the C++ engine (no
    # Command-specific target math here).
    if sp_.name == "Command":
        def _on_word(chosen, s=s, si_=si_, sp_=sp_, slot_level_=slot_level_):
            word = chosen[0] if chosen else 3   # default Halt (matches applyCommandEffect)
            app.cast_setup.command_word = word
            word_name = next((lbl for lbl, val in features.COMMAND_WORD_OPTIONS if val == word), "?")
            app._combat_log_add(f"Command word: {word_name}.")
            dispatch_spell_geometry(app, s, si_, sp_, slot_level_, idx)
        app._ask_actor(idx, "action", "Command: choose a word",
                        [(lbl, (lambda v=val: _on_word([v]))) for lbl, val in features.COMMAND_WORD_OPTIONS],
                        render="picker", on_cancel=lambda: _on_word([]),
                        cancellable=False)
        return

    # Cast-time mode choice (Enlarge/Reduce, MORE_SPECIES_PLAN.md MS2): Enlarge applies Enlarged
    # (no save on the caster or an ally); Reduce keeps the stored CON-save path. Rides on
    # SpellAction.enlarge; Single geometry, so it falls through to the normal target dispatch.
    if sp_.name == "Enlarge/Reduce":
        size_opts = [("Enlarge (+1d4 weapon damage, Adv. on STR saves)", 1),
                     ("Reduce (−1d4 weapon damage; CON save)", 0)]
        def _on_size(chosen, s=s, si_=si_, sp_=sp_, slot_level_=slot_level_):
            app.cast_setup.enlarge = bool(chosen and chosen[0] == 1)
            app._combat_log_add(
                f"Enlarge/Reduce: {'Enlarge' if app.cast_setup.enlarge else 'Reduce'} — click a target.")
            dispatch_spell_geometry(app, s, si_, sp_, slot_level_, idx)
        app._ask_actor(idx, "action", "Enlarge/Reduce: choose",
                        [(lbl, (lambda v=val: _on_size([v]))) for lbl, val in size_opts],
                        render="picker", on_cancel=lambda: _on_size([]),
                        cancellable=False)
        return

    # Cast-time form choice (Forcecage): Cage (20-ft barred cube — the occupant is trapped but
    # attacks and spells still pass through the bars both ways) vs Box (10-ft solid cube — a
    # two-way seal: the occupant can't act out and can't be targeted from outside; its only exit
    # is a CHA-saved teleport). The choice rides on SpellAction.forcecage_sealed. Single geometry,
    # so it falls through to the normal "click a target" dispatch afterward.
    if sp_.name == "Forcecage":
        forcecage_opts = [
            ("Cage — 20 ft (barred: attacks & spells pass through)", 0),
            ("Box — 10 ft (solid: sealed in; only a teleport escapes)", 1),
        ]
        def _on_forcecage(chosen, s=s, si_=si_, sp_=sp_, slot_level_=slot_level_):
            app.cast_setup.forcecage_sealed = bool(chosen and chosen[0] == 1)
            app._combat_log_add(
                f"Forcecage form: {'Box (10 ft, sealed)' if app.cast_setup.forcecage_sealed else 'Cage (20 ft)'}"
                " — click a target.")
            dispatch_spell_geometry(app, s, si_, sp_, slot_level_, idx)
        app._ask_actor(idx, "action", "Forcecage: choose a form",
                        [(lbl, (lambda v=val: _on_forcecage([v]))) for lbl, val in forcecage_opts],
                        render="picker", on_cancel=lambda: _on_forcecage([]),
                        cancellable=False)
        return

    # Summon spells: pick an empty cell within range to manifest the creature, rather than
    # targeting a creature or placing an AoE. Routed here BEFORE the
    # geometry branches because Summon Dragon is Single geometry ("click a target").
    # Scaling spirits (summons.json) take precedence and first prompt for a FORM.
    spirit_forms = SUMMON_SPELL_TO_SPIRIT.get(sp_.name)
    monster      = SUMMON_SPELL_TO_MONSTER.get(sp_.name)
    if spirit_forms:
        # Fey Wanderer L11 Fey Reinforcements: any Summon Fey may be cast without
        # Concentration (1 minute). Ask first, then come back here for the form.
        if (sp_.name == "Summon Fey" and app._fey_reinforcements_level(idx)
                and not app._summon_conc_chosen):
            def _on_conc(no_conc, s=s, si_=si_, slot_level_=slot_level_, idx=idx):
                # Re-enter this branch past the question; the form prompt it opens
                # leaves the placement armed, and the choice rides along with it.
                app._summon_conc_chosen = True
                try:
                    app._activate_spell(s, si_, slot_level_, idx, spells, stats,
                                         free_cast=free_cast, use_grant=use_grant)
                finally:
                    app._summon_conc_chosen = False
                if app._armed(pending.Summon):
                    app.pending.no_conc = no_conc
            app._ask_actor(idx, "action", "Summon Fey: Concentration?",
                            [("Concentration (1 hour)", lambda: _on_conc(False)),
                             ("No Concentration (1 minute)", lambda: _on_conc(True))],
                            render="picker",
                            on_cancel=lambda: net_picks.cancel_summon(app))
            return
        app.pending = pending.Summon(s, si_, slot_level_, free_cast=free_cast)
        items = [(f"✨ {form}",
                  lambda b=block, n=sp_.name: app._choose_summon_form(n, b))
                 for form, block in spirit_forms.items()]
        # The summon is armed before its form is chosen, so cancelling the form menu
        # must disarm it, or the arm swallows every map click with no creature (F-M5e-4).
        app._ask_actor(idx, "action",
                        f"{app._agent_name(idx)}: casting {sp_.name} — choose a form",
                        items, anchor=pygame.mouse.get_pos(),
                        on_cancel=lambda: net_picks.cancel_summon(app))
        app._combat_log_add(f"Casting {sp_.name} — choose a form.")
        return
    if monster:
        app.pending = pending.Summon(s, si_, slot_level_, monster=monster, free_cast=free_cast)
        app._combat_log_add(
            f"Casting {sp_.name} — click an empty cell within range to place the {monster}.")
        return

    # Magic Circle / Hallow (D4): pick the warded creature types + direction (keep-out vs
    # trap-inside) through the toggle loop (_ask_ward_types), stash them for the SpellAction,
    # then fall through to the normal Sphere AoE placement (click a center point). Mirrors
    # Command's word-choice flow. reset to a clean ward each cast so a prior pick can't leak
    # through.
    app.pending_ward_mask  = 0
    app.pending_ward_traps = False
    if getattr(sp_, "creates_movement_ward", False):
        def _on_ward(chosen, s=s, si_=si_, sp_=sp_, slot_level_=slot_level_, idx=idx):
            mask, traps = 0, False
            for v in chosen:
                if v == WARD_REVERSE_SENTINEL:
                    traps = True
                else:
                    mask |= v
            if mask == 0:  # nothing picked → ward every offered type (RAW allows "one or more")
                mask = (int(rpg.CreatureType.Celestial) | int(rpg.CreatureType.Elemental) |
                        int(rpg.CreatureType.Fey) | int(rpg.CreatureType.Fiend) |
                        int(rpg.CreatureType.Undead))
            app.pending_ward_mask  = mask
            app.pending_ward_traps = traps
            names = [lbl for lbl, val in MAGIC_CIRCLE_TYPE_OPTIONS
                     if val != WARD_REVERSE_SENTINEL and (val & mask)]
            app._combat_log_add(
                f"{sp_.name}: warding {', '.join(names)} "
                f"({'trapped inside' if traps else 'kept out'}).")
            dispatch_spell_geometry(app, s, si_, sp_, slot_level_, idx)
        app._ask_ward_types(idx, sp_.name, frozenset(), _on_ward)
        return

    # Emanation (a moves_with_caster Sphere) is always centered on the caster,
    # so there is no placement to choose — cast immediately on the caster's cell.
    if getattr(sp_, "moves_with_caster", False) and sp_.geometry == rpg.SpellGeometry.Sphere:
        app.pending = pending.Spell(s, si_, slot_level_)
        ci = app._current_agent_idx()
        origin = app.bm.placed_agents[ci].origin
        app._combat_log_add(f"Casting {sp_.name} — centered on caster.")
        app._resolve_spell_cast_aoe(rpg.Cell(origin.col, origin.row))
        return

    # Teleportation spells: select a destination, then optionally select additional targets
    if getattr(sp_, "teleportation_spell", False):
        app.pending = pending.Spell(s, si_, slot_level_, is_aoe=True)
        hint = f"click a destination ({sp_.teleport_range_ft} ft away)"
        app._combat_log_add(f"Casting {sp_.name} — {hint}.")
        return

    dispatch_spell_geometry(app, s, si_, sp_, slot_level_, idx)


def dispatch_spell_geometry(app, s, si_, sp_, slot_level_, idx):
    # Generic, engine-driven targeting setup shared by the normal cast path and by
    # cast-time-choice spells (e.g. Command's word pick) that need to fall through here
    # AFTER their choice. The target count for Multiple geometry comes from the C++
    # engine (get_num_targets_for_spell), which is also the authority that caps the list
    # at resolution — so no spell-specific target math lives here.
    num_targets = 0
    if sp_.geometry == rpg.SpellGeometry.Single:
        is_aoe = False
        # Twinned Spell (Sorcerer Metamagic): a Single-geometry spell gets one ADDITIONAL
        # target. Collect two clicks (like Multiple geometry). The engine still validates
        # affordability and only actually hits the 2nd target if it pays the SP.
        if app._twinned_single_armed(sp_, idx):
            num_targets = 2
            hint = "click 2 targets (0/2) — Twinned"
        elif enhanced_necromancy_armed_for(app, sp_, idx, slot_level_):
            # Enhanced Necromancy (Grave Cleric L17): the same 2-click collection as Twinned;
            # the engine spends the Channel Divinity use only if the 2nd target lands.
            num_targets = 2
            hint = "click 2 targets (0/2) — Enhanced Necromancy"
        elif getattr(sp_, "revives_dead", False):
            # Raise Dead / Revivify: the target is a corpse, picked via _corpse_at.
            num_targets = 0
            hint = "click a dead body within range"
        elif getattr(sp_, "animates_dead", False):
            # Animate Dead: the target is a corpse to raise as an undead — same corpse-pick.
            num_targets = 0
            hint = "click a corpse within range to animate"
        else:
            num_targets = 0
            hint = "click a target"
    elif sp_.geometry == rpg.SpellGeometry.Multiple:
        # Multiple geometry: collect N independent targets
        caster_level_ = app.combat.get_agent_stats(app.bm, idx).char_level
        # Twinned Spell raises the effective level by 1: one more creature for a spell that
        # targets an additional creature per upcast level (Hold Person, Hold Monster, …).
        twin_ = (rpg.MetamagicOption.Twinned in armed_metamagic_options(app, idx)
                 and rpg.CombatEngine.twinnable_spell(sp_))
        num_targets = app.combat.get_num_targets_for_spell(sp_, slot_level_, caster_level_,
                                                           twin_)
        is_aoe = False   # the targets are collected one click at a time
        hint = f"click {num_targets} target{'s' if num_targets != 1 else ''} ({0}/{num_targets})"
        if twin_:
            hint += " — Twinned"
        if num_targets > 1:
            hint += ", or Enter to cast on fewer"
    else:
        # AoE (Line, Cone, Sphere, Square, Rectangle)
        is_aoe = True
        app.spell_anchor_cell    = None
        if sp_.geometry == rpg.SpellGeometry.Rectangle:
            # Oriented wall: click an anchor, then click again to set
            # direction/length (up to the spell's max length).
            hint = "click the wall's start point"
        else:
            hint = "click a map location"

    app.pending = pending.Spell(s, si_, slot_level_, is_aoe=is_aoe, num_targets=num_targets)
    app._combat_log_add(f"Casting {sp_.name} — {hint}.")


def ask_spell_browser(app, idx, title, spells, on_pick, on_cancel=None):
    """Ask the caster's controller for one spell out of ``spells`` (D-M1-12c, E-5).

    One ``choice`` prompt, an option per spell labelled with its name, in catalogue
    order. The DM console draws it as ``SpellSelectionDialog`` (tabs and a search);
    a browser draws a list with a filter box. ``on_pick`` gets the spell's dict.
    Cancelling spends nothing, because Wish and Divine Intervention pay on the pick.
    ``on_cancel`` undoes what the caller armed before asking, if anything.
    """
    app._ask_actor(idx, "action", title,
                    [(d["name"], (lambda d=d: on_pick(d))) for d in spells],
                    render=SPELL_BROWSER_RENDER, on_cancel=on_cancel)


def ask_ward_types(app, idx, spell_name, chosen, on_done):
    """Ask the caster's controller which creature types a Magic Circle / Hallow wards
    (M5e E-6): a toggle loop of plain ``choice`` prompts, not a multi-select.

    Each row of ``MAGIC_CIRCLE_TYPE_OPTIONS`` is an option, marked ✓ when it is in
    ``chosen``; picking one re-posts the prompt with it toggled. Done calls ``on_done``
    with the chosen values, sorted, as the multi-select widget's commit did. A cancel
    abandons the cast: nothing is armed or spent before the center is placed.
    """
    def _toggle(v):
        app._ask_ward_types(idx, spell_name, chosen ^ {v}, on_done)
    n = sum(1 for v in chosen if v != WARD_REVERSE_SENTINEL)
    pairs = [(("✓ " if val in chosen else "") + lbl, (lambda v=val: _toggle(v)))
             for lbl, val in MAGIC_CIRCLE_TYPE_OPTIONS]
    pairs.append((f"Done ({n} chosen)" if n else "Done (ward every type)",
                  lambda: on_done(sorted(chosen))))
    app._ask_actor(idx, "action", f"{spell_name}: choose warded types", pairs)


def on_spell_done(app, agent_idx: int, spells: list[dict]):
    # The Spells dialog lists the creature's own spells only (item entries are derived);
    # drop any item entries before the dialog's list replaces them, then re-grant.
    for j in [j for (a, j) in app._spell_metadata if a == agent_idx]:
        del app._spell_metadata[(agent_idx, j)]
    cpp_spells = []
    for j, d in enumerate(spells):
        cpp_spells.append(_dict_to_spell(d))
        # Store all metadata for this spell (terrain, level, upcast)
        meta = {
            "terrain_effect": d.get("terrain_effect"),
            "hatch_pattern": d.get("hatch_pattern"),
            "terrain_color": d.get("terrain_color"),
            "level": d.get("level", 0),
            "upcast_dice_bonus": d.get("upcast_dice_bonus", 0),
        }
        app._spell_metadata[(agent_idx, j)] = meta
    app._grant_class_features(agent_idx, cpp_spells)
    app.combat.set_agent_spells(app.bm, agent_idx, cpp_spells)
    app._sync_item_spells(agent_idx)


def resolve_spell_cast(app, target_idx: int | None):
    """`target_idx` None finishes a multi-target collection early (see
    `_finish_multi_target_spell`)."""
    ps = app._armed(pending.Spell)
    caster_idx = app._current_agent_idx()
    slot       = ps.slot if ps else ""
    if caster_idx < 0 or not slot:
        return

    spells_orig = app.combat.get_agent_spells(app.bm, caster_idx)
    sp = spells_orig[ps.idx]

    # Multiple-geometry spells (and a Twinned Single-geometry spell) collect several targets
    # across successive clicks before the cast resolves.
    multi_target = (sp.geometry == rpg.SpellGeometry.Multiple or
                    app._twinned_single_armed(sp, caster_idx) or
                    enhanced_necromancy_armed_for(app, sp, caster_idx,
                                                        ps.slot_level))
    if multi_target and target_idx is None:
        if not ps.targets:
            return
        # Finishing early: cast on the targets collected so far.
    elif target_idx is None:
        return
    elif multi_target:
        # Only darts, rays and beams may land on one creature more than once; every other
        # multi-target spell (Bless, Bane, Hold Person, a Twinned spell, …) needs distinct ones.
        if (target_idx in ps.targets
                and sp.name not in _REPEAT_TARGET_SPELLS):
            app._combat_log_add(
                f"{app.bm.placed_agents[target_idx].name} is already a target of "
                f"{sp.name} — choose a different creature.")
            return
        ps.targets.append(target_idx)

        targets_collected = len(ps.targets)
        targets_needed = ps.num_targets

        if targets_collected < targets_needed:
            # Still collecting targets
            app._combat_log_add(f"Target selected ({targets_collected}/{targets_needed}) "
                                 f"— Enter to cast on these.")
            return
        # else: we have all targets, fall through to execute

    action = rpg.SpellAction()
    action.caster_idx     = caster_idx
    action.spell_idx      = ps.idx
    action.slot_level     = ps.slot_level
    action.target_indices = ps.targets if multi_target else [target_idx]
    action.damage_type_override = app.cast_setup.damage_type  # cast-time element choice (-1 = none)
    # Mantle of Majesty: free Command cast (no slot) + the chosen Command word.
    action.free_cast      = app.cast_setup.free_cast
    action.use_grant      = app.cast_setup.use_grant   # granted spell's free cast (D3)
    action.command_word   = app.cast_setup.command_word
    action.curse_choice   = app.cast_setup.curse_choice  # Vistani Curse sub-choice (-1 = n/a)
    action.forcecage_sealed = app.cast_setup.forcecage_sealed   # Forcecage form (Box seals the occupant)
    action.enlarge        = app.cast_setup.enlarge     # Enlarge/Reduce mode (MS2)
    # Chromatic Orb's player-chosen leap chain (empty for every other spell / an un-chained cast).
    action.chromatic_leap_targets = list(app.pending_chromatic_chain)
    action.overchannel   = app.overchannel_armed  # Evoker L14 (engine ignores if ineligible)
    action.enhanced_necromancy = app.enhanced_necromancy_armed  # Grave L17 (paid only if eligible)
    apply_dispel_selection(app, action)  # Dispel Magic picker (no-op when nothing was picked)
    apply_armed_metamagic(app, action, caster_idx)  # Sorcerer Metamagic (engine no-ops if inapplicable)
    apply_pact_slot_level(app, caster_idx, sp, action)

    # Cast through the OnDeclareCast window (begin_cast): a targeted creature may react before the
    # spell resolves (Shield vs Magic Missile). begin_cast resolves inline when no reaction is
    # offered (Completed) or parks at the reaction checkpoint (AwaitingDecision); _finish_cast does
    # the post-resolution logging in both cases.
    # (Beast Master L15 Share Spells is the engine's: executeSpell adds the companion as a target.)
    app._cast_post = dict(caster_idx=caster_idx, slot=slot, spell_idx=ps.idx,
                           aoe=False,
                           slot_level=ps.slot_level,
                           free_cast=action.free_cast or action.use_grant)
    app._reaction_finish = app._finish_cast

    app._disarm(pending.Spell)
    app.cast_setup.damage_type = -1
    app.cast_setup.free_cast   = False
    app.cast_setup.use_grant   = False
    app.cast_setup.command_word = -1
    app.cast_setup.curse_choice = -1
    app.spell_hover_cell          = None
    app._drop_pick("chromatic")
    app.pending_chromatic_primary = -1
    app.pending_chromatic_chain   = []

    status = app.combat.begin_cast(app.bm, action)
    app._flush_combat_log()
    if status == rpg.FlowStatus.AwaitingDecision:
        app._show_pending_reaction_menu()
    else:
        app._finish_cast()


def resolve_spell_cast_aoe(app, cell):
    ps = app._armed(pending.Spell)
    caster_idx = app._current_agent_idx()
    slot       = ps.slot if ps else ""
    if caster_idx < 0 or not slot:
        return

    spells_orig = app.combat.get_agent_spells(app.bm, caster_idx)
    sp = spells_orig[ps.idx]

    # Handle teleportation spells separately
    if getattr(sp, "teleportation_spell", False):
        resolve_teleport_spell(app, cell)
        return

    action = rpg.SpellAction()
    action.caster_idx     = caster_idx
    action.spell_idx      = ps.idx
    action.slot_level     = ps.slot_level
    action.target_indices = []
    action.free_cast      = app.cast_setup.free_cast  # Wish-duplicated AoE: no slot of its own
    action.use_grant      = app.cast_setup.use_grant  # granted spell's free cast (D3)
    action.overchannel    = app.overchannel_armed  # Evoker L14 (engine ignores if ineligible)
    apply_dispel_selection(app, action)  # Dispel Magic picker (cell-aimed dispel of an AoE)
    apply_armed_metamagic(app, action, caster_idx)  # Sorcerer Metamagic (engine no-ops if inapplicable)
    if getattr(sp, "creates_movement_ward", False):
        # Magic Circle / Hallow: the warded types + direction chosen at cast time (see _activate_spell).
        action.ward_creature_mask = getattr(app, "pending_ward_mask", 0)
        action.ward_traps         = getattr(app, "pending_ward_traps", False)
    if sp.geometry == rpg.SpellGeometry.Rectangle and app.spell_anchor_cell is not None:
        # Oriented wall: anchor is the first click, `cell` is the endpoint.
        action.aoe_col  = app.spell_anchor_cell.col
        action.aoe_row  = app.spell_anchor_cell.row
        action.aoe_col2 = cell.col
        action.aoe_row2 = cell.row
    else:
        action.aoe_col  = cell.col
        action.aoe_row  = cell.row
    apply_pact_slot_level(app, caster_idx, sp, action)

    # Cast through the OnDeclareCast window (begin_cast) so a targeted creature can react before
    # the spell resolves; _finish_cast does the post-resolution logging (incl. AoE no-targets and
    # slip handling) whether the cast resolves inline or after a parked reaction.
    app._cast_post = dict(caster_idx=caster_idx, slot=slot, spell_idx=ps.idx,
                           aoe=True, free_cast=action.free_cast or action.use_grant,
                           slot_level=ps.slot_level)
    app._reaction_finish = app._finish_cast

    app._disarm(pending.Spell)
    app.cast_setup.free_cast  = False
    app.cast_setup.use_grant  = False
    app.spell_hover_cell         = None
    app.spell_anchor_cell        = None

    status = app.combat.begin_cast(app.bm, action)
    app._flush_combat_log()
    if status == rpg.FlowStatus.AwaitingDecision:
        app._show_pending_reaction_menu()
    else:
        app._finish_cast()


def resolve_teleport_spell(app, destination_cell):
    """Handle teleportation spell casting. Teleports caster + additional targets to destination."""
    ps = app._armed(pending.Spell)
    caster_idx = app._current_agent_idx()
    slot       = ps.slot if ps else ""
    if caster_idx < 0 or not slot:
        return

    spells_orig = app.combat.get_agent_spells(app.bm, caster_idx)
    sp = spells_orig[ps.idx]

    # Validate destination is in range and not blocked
    if not app.combat.is_valid_teleport_destination(app.bm, destination_cell.col, destination_cell.row):
        app._combat_log_add("Cannot teleport there — destination is blocked or out of range.")
        return

    # For now, teleport only the caster. In Phase 3B, add multi-target support.
    agents_to_teleport = [caster_idx]

    # Place teleported agents
    placed_count = app.combat.place_teleported_agents(
        app.bm, agents_to_teleport, destination_cell.col, destination_cell.row
    )

    if placed_count == 0:
        # A Forcecaged caster that just failed its Charisma save to teleport out: the attempt is
        # spent (RAW), so consume the slot/action instead of letting the player retry for free.
        # The engine already logged the failed CHA save inside teleport_agent.
        caster_cond = app.combat.get_agent_conditions(app.bm, caster_idx)
        if getattr(caster_cond, "forcecaged", False):
            cast_name = (app.bm.placed_agents[caster_idx].name
                         if caster_idx < len(app.bm.placed_agents) else "?")
            app._combat_log_add(
                f"{cast_name}'s {sp.name} fails to breach the Forcecage — the spell is wasted.")
            _pay_teleport(app, caster_idx, ps)
            app._disarm(pending.Spell)
            app.spell_hover_cell          = None
            app._consume_cast_slot(slot, caster_idx)
            return
        app._combat_log_add("Failed to teleport — no valid destination.")
        return

    # Log successful teleportation
    agents = app.bm.placed_agents
    cast_name = agents[caster_idx].name if caster_idx < len(agents) else "?"
    app._combat_log_add(f"{cast_name} casts {sp.name} and teleports to ({destination_cell.col}, {destination_cell.row}).")

    # Pay for it: the slot, a granted free cast (D3), an item charge or an N/day use.
    used_grant = app.cast_setup.use_grant
    _pay_teleport(app, caster_idx, ps)

    # Clean up pending spell state
    app._disarm(pending.Spell)
    app.spell_hover_cell          = None

    # Mark action/bonus as used
    app._consume_cast_slot(slot, caster_idx)
    # Wild Magic Surge: a teleport spell (e.g. Misty Step) cast with a spell slot triggers a surge.
    # `ps` was taken before the disarm above, so its slot level is still the cast's.
    if ps.slot_level >= 1 and not used_grant:
        features.maybe_wild_magic_surge(app, caster_idx)


def _pay_teleport(app, caster_idx, ps):
    """Charge a teleportation spell's cost: it resolves outside execute_spell, so the engine's
    pay_teleport_cast does what execute_spell would (slot, free cast, item, uses). A Wish-
    duplicated cast (free_cast) pays nothing of its own."""
    if not app.cast_setup.free_cast:
        sp = app.combat.get_agent_spells(app.bm, caster_idx)[ps.idx]
        slot_level = ps.slot_level
        if sp.level >= 1:
            cs = app.combat.get_agent_stats(app.bm, caster_idx)
            if cs.character_class == rpg.CharacterClass.Warlock and cs.pact_slot_level() > 0:
                slot_level = cs.pact_slot_level()   # as apply_pact_slot_level
        app.combat.pay_teleport_cast(app.bm, caster_idx, ps.idx, slot_level,
                                     app.cast_setup.use_grant)
    app.cast_setup.use_grant = False
    app.cast_setup.free_cast = False


def resolve_corpse_spell(app, cell):
    """Resolve a revives_dead spell (Raise Dead / Revivify) aimed at the clicked cell.

    A corpse is invisible to _agent_at, so a revive spell picks its target through
    _corpse_at instead. Validate that a true-dead body sits under the click and lies
    within the spell's range, then hand the corpse index to the normal cast path — the
    engine's revives_dead heal clears the `dead` condition and restores the creature."""
    ps = app._armed(pending.Spell)
    caster_idx = app._current_agent_idx()
    if caster_idx < 0 or ps is None:
        return
    corpse = app._corpse_at(cell)
    if corpse < 0:
        app._combat_log_add("No corpse there — click a dead body within range.")
        return
    spells = app.combat.get_agent_spells(app.bm, caster_idx)
    sp = spells[ps.idx]
    dist_ft = app._footprint_dist_ft(caster_idx, corpse)
    if dist_ft < 0 or dist_ft > sp.range:
        app._combat_log_add(
            f"{app.bm.placed_agents[corpse].name} is out of range ({sp.range} ft).")
        return
    if getattr(sp, "animates_dead", False):
        # Animate Dead: raise an undead servant from the corpse rather than revive it.
        features.resolve_animate_dead(app, corpse)
    else:
        app._resolve_spell_cast(corpse)


def finish_animate_dead(app, caster_idx, corpse_idx, cell, undead,
                         slot, slot_level, free_cast):
    """Spawn the chosen undead (Skeleton/Zombie) where the corpse lay, on the caster's
    team, then spend the slot (unless a free Divine-Intervention cast) and the action.
    Mirrors the non-spirit branch of _resolve_summon."""
    if caster_idx < 0 or not (0 <= corpse_idx < len(app.bm.placed_agents)):
        return
    mob_stats = app.mob_stats_json.get(undead)
    if not mob_stats:
        app._combat_log_add(f"Animate Dead failed: missing '{undead}' stat block.")
        return
    size = app._size_category_to_grid_size(mob_stats.get("size", "Medium"))

    # Consume the corpse — it transforms into the undead — then spawn on its (now
    # passable, §10) square. Roll the tombstone back if placement fails.
    app.bm.set_agent_removed_from_play(corpse_idx, True)
    # A dead body's square is passable, so a living creature may be standing on it — only
    # raise the undead if the freed square is actually clear (corpse excluded via exclude_idx).
    if not app._can_place(cell, size, exclude_idx=corpse_idx):
        app.bm.set_agent_removed_from_play(corpse_idx, False)
        app._combat_log_add("Animate Dead failed: the corpse's square is occupied.")
        return
    cfg = rpg.AgentConfig()
    cfg.name        = undead
    cfg.sprite_path = app._get_mob_sprite_path(undead)
    cfg.size        = size
    cfg.start_col   = cell.col
    cfg.start_row   = cell.row
    new_idx = app.bm.spawn_agent(cfg)
    if new_idx < 0:
        app.bm.set_agent_removed_from_play(corpse_idx, False)
        app._combat_log_add("Animate Dead failed: could not place the undead.")
        return

    # Stats + auto-weapons + innate spells from the bestiary (same path as summons).
    app.combat.set_agent_stats(app.bm, new_idx, app._mob_stats_to_d_d_stats(mob_stats))
    weapons = list(app.combat.get_agent_weapons(app.bm, new_idx))
    if not app._has_real_weapons(weapons):
        for i, w in enumerate(app._auto_weapons_from_mob_stats(mob_stats)[:3]):
            weapons[i] = w
        app.combat.set_agent_weapons(app.bm, new_idx, weapons)
    app._load_npc_spells_from_record(new_idx, mob_stats)

    # Inherit the caster's team (allied undead servant). No summoner_idx (see docstring).
    app.bm.set_agent_faction(new_idx, app.bm.get_agent_faction(caster_idx))

    # Insert into initiative immediately after the caster (acts on the caster's count).
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

    caster = app.bm.placed_agents[caster_idx]
    app._combat_log_add(f"{caster.name} animates a {undead} from the fallen!")

    # Spend the spell slot (PC slots only; a free Divine-Intervention cast pays none),
    # then consume the action economy and clear the pending-spell state.
    cstats = app.combat.get_agent_stats(app.bm, caster_idx)
    if not cstats.is_npc and slot_level >= 1 and not free_cast:
        slots = list(cstats.spell_slots_remaining)
        if slots[slot_level - 1] > 0:
            slots[slot_level - 1] -= 1
            cstats.spell_slots_remaining = slots
            app.combat.set_agent_stats(app.bm, caster_idx, cstats)
    app._disarm(pending.Spell)
    app.cast_setup.free_cast = False
    app._consume_cast_slot(slot, caster_idx)


def resolve_planar_binding(app, target_idx):
    """Planar Binding (Divine Intervention D3): attempt to bind the clicked creature to
    the caster's service. On a failed Charisma save (vs the caster's spell save DC) the
    target is transferred to the caster's team — a lasting control transfer (this engine
    has no timed team-revert; it holds until re-factioned or the encounter ends). No
    summoner_idx is set (Planar Binding is not Concentration), and is_npc_automated is
    cleared so the player controls the bound creature."""
    ps = app._armed(pending.Spell)
    caster_idx = app._current_agent_idx()
    if caster_idx < 0 or ps is None:
        return
    if not (0 <= target_idx < len(app.bm.placed_agents)):
        return
    spells = app.combat.get_agent_spells(app.bm, caster_idx)
    sp = spells[ps.idx]
    dist_ft = app._footprint_dist_ft(caster_idx, target_idx)
    if dist_ft < 0 or dist_ft > sp.range:
        app._combat_log_add(
            f"{app.bm.placed_agents[target_idx].name} is out of range ({sp.range} ft).")
        return

    caster = app.bm.placed_agents[caster_idx]
    target = app.bm.placed_agents[target_idx]
    cstats = app.combat.get_agent_stats(app.bm, caster_idx)
    ab_name = _INT_TO_ABILITY.get(cstats.spellcasting_ability, "cha")
    dc_by_ability = {
        "str": cstats.spell_save_dc_str,   "dex":   cstats.spell_save_dc_dex,
        "con": cstats.spell_save_dc_con,   "intel": cstats.spell_save_dc_intel,
        "wis": cstats.spell_save_dc_wis,   "cha":   cstats.spell_save_dc_cha,
    }
    dc = dc_by_ability.get(ab_name, cstats.spell_save_dc_cha) + cstats.spell_dc_bonus
    save_mod = app.combat.save_mod_for(app.bm, target_idx, rpg.SaveAbility.SaveCha)
    roll = app.combat.roll(20, save_mod)
    if roll >= dc:
        app._combat_log_add(
            f"{target.name} succeeds on the Charisma save ({roll} vs DC {dc}) — "
            f"Planar Binding fails.")
    else:
        app.bm.set_agent_faction(target_idx, app.bm.get_agent_faction(caster_idx))
        app.bm.set_agent_npc_automated(target_idx, False)
        app._combat_log_add(
            f"{target.name} fails the Charisma save ({roll} vs DC {dc}) — "
            f"bound to {caster.name}'s service!")

    # Spend the slot (PC only, non-free) and the action, then clear pending state.
    if not cstats.is_npc and sp.level >= 1 and not app.cast_setup.free_cast:
        slot_level = ps.slot_level
        slots = list(cstats.spell_slots_remaining)
        if 1 <= slot_level <= len(slots) and slots[slot_level - 1] > 0:
            slots[slot_level - 1] -= 1
            cstats.spell_slots_remaining = slots
            app.combat.set_agent_stats(app.bm, caster_idx, cstats)
    slot = ps.slot if ps else ""
    app._disarm(pending.Spell)
    app.cast_setup.free_cast = False
    app._consume_cast_slot(slot, caster_idx)


def multi_target_finishable(app) -> bool:
    """A multi-target spell with at least one target picked can be cast early (Enter / Done)
    on fewer than its maximum — Mass Suggestion need not find all twelve."""
    ps = app._armed(pending.Spell)
    sp = app._pending_spell()
    return (sp is not None and not ps.is_aoe
            and ps.num_targets > 0
            and 0 < len(ps.targets) < ps.num_targets)


def finish_multi_target_spell(app):
    """Cast the armed multi-target spell on the targets collected so far."""
    if app._multi_target_finishable():
        app._resolve_spell_cast(None)


def finish_cast(app):
    """Post-resolution handling once a begin_cast flow completes (immediately or after the
    OnDeclareCast reaction window). Reads the result from last_cast_result() and logs/consumes the
    slot using the context captured in self._cast_post."""
    ctx        = app._cast_post
    caster_idx = ctx["caster_idx"]
    result     = app.combat.last_cast_result()
    app._flush_combat_log()
    cast_spell = app.combat.get_agent_spells(app.bm, caster_idx)[ctx["spell_idx"]]

    agents    = app.bm.placed_agents
    cast_name = agents[caster_idx].name if caster_idx < len(agents) else "?"
    # A Counterspell fizzled the cast before it resolved: the action is still spent (wasted), but
    # the engine never ran executeSpell, so the slot is retained (2024 rules). Report it cleanly
    # rather than as "invalid" (the Counterspell save is already in the combat log).
    if app.combat.last_cast_countered():
        app._combat_log_add(f"{cast_name}'s spell was countered!")
        app._sync_spell_effect_cache()
        app._consume_cast_slot(ctx["slot"], caster_idx, cast_spell)
        return
    if not result.valid:
        app._combat_log_add(f"{cast_name}: spell failed (invalid)")
        # If the agent slipped and can't act, auto-advance their turn (AoE cast path).
        if ctx.get("aoe") and 0 <= caster_idx < len(agents) and agents[caster_idx].conditions.slipped_this_turn:
            app._combat_log_add(f"{cast_name} slipped and cannot act — turn ends.")
            app._advance_turn()
        return
    if ctx.get("aoe") and not result.target_results:
        app._combat_log_add(f"{cast_name}: {result.spell_name} — no targets in area")
    else:
        log_spell_results(app, result, cast_name, caster_idx, ctx["spell_idx"])
    # Clear spell effect cache entries for any removed effects (e.g., from concentration loss)
    app._sync_spell_effect_cache()
    app._consume_cast_slot(ctx["slot"], caster_idx, cast_spell)
    # Boon of Dimensional Travel — arm Blink Steps: casting a spell is the Magic action.
    app._arm_blink_steps(caster_idx)
    # College of Glamour Beguiling Magic: offer the once/long-rest rider after a slot-fueled
    # Enchantment/Illusion cast (a free Mantle-of-Majesty Command uses no slot, so it's excluded).
    if not ctx.get("free_cast"):
        features.maybe_offer_beguiling_magic(app, caster_idx, ctx["spell_idx"])
        # Archfey Bewitching Magic (L14): a free Misty Step after a slot-fueled Enchantment/Illusion.
        features.maybe_offer_bewitching_magic(app, caster_idx, ctx["spell_idx"])
    # Wild Magic Surge: a Wild Magic Sorcerer who just cast a spell WITH A SPELL SLOT (level ≥ 1,
    # not a free cast) checks for a surge (natural 20, or forced if Tides of Chaos is expended).
    if not ctx.get("free_cast") and ctx.get("slot_level", 0) >= 1:
        features.maybe_wild_magic_surge(app, caster_idx)
    # A spell scroll just cast is spent: drop it now, not at the next turn start, so it also
    # goes out of combat (SPELL_SCROLLS SS3; kept while its spell is live, A1).
    if cast_spell.item_source == rpg.SpellItemSource.FromItem:   # idempotent for any other item
        app._sync_item_spells(caster_idx)
        app._flush_combat_log()


def resolve_wild_magic_surge(app, caster_idx: int, effect: int, tides_expended: bool):
    """Apply a chosen Wild Magic Surge band (from offer_wild_magic_surge) and relay the log."""
    if not (0 <= caster_idx < len(app.bm.placed_agents)):
        return
    res = app.combat.resolve_wild_magic_surge(app.bm, caster_idx, effect, tides_expended)
    app._flush_combat_log()
    if res.effect > 0:
        name = app.bm.placed_agents[caster_idx].name
        app._combat_log_add(f"⚡ {name} — Wild Magic Surge! {res.description}")
        app._flush_combat_log()
        app._sync_spell_effect_cache()       # band 1 (Plant Growth) places a terrain effect
    app._update_attack_overlay()


def consume_cast_slot(app, slot: str, caster_idx: int, spell=None):
    """Charge the action economy for a resolved cast. Normally a cast consumes the whole
    action (or bonus action), and `spell`, when flagged, the bonus action as well. War Magic
    (slot=='war_magic') instead replaces ONE weapon attack inside the Attack action: mark the
    once-per-Attack-action gate, spend one attack, and either re-prompt for the remaining
    attack(s) or end the action."""
    if slot == "breath":
        # Breath Weapon replaced one attack of the Attack action (D7).
        from app_attacks import consume_attack_replacement
        consume_attack_replacement(app, caster_idx)
    elif slot == "war_magic":
        app.combat.mark_war_magic_used(app.bm, caster_idx)
        app.attack_seq.remaining -= 1
        if app.attack_seq.remaining > 0:
            # War Magic replaced one attack; DISARM between attacks so the player can move. The
            # standing "⚔ Attack (N)" button resumes the remaining attack(s) — count preserved,
            # and war_magic_used stays set (only a fresh Attack-action seed clears it) so the
            # substitution option won't reappear.
            app._disarm(pending.Attack)
            rem = app.attack_seq.remaining
            nm = (app.bm.placed_agents[caster_idx].name
                  if 0 <= caster_idx < len(app.bm.placed_agents) else "?")
            app._combat_log_add(
                f"{nm}: {rem} attack{'s' if rem != 1 else ''} remaining — "
                f"move if you wish, then click Attack to continue.")
        else:
            app.attack_seq.remaining     = 0
            app.action_used           = True
            app.attack_seq.slot = ""
    elif slot == "action":
        app.action_used = True
        if spell is not None and spell_costs_action_and_bonus(app, spell) and not app.bonus_used:
            app.bonus_used = True
    else:
        app.bonus_used = True


def apply_pact_slot_level(app, caster_idx: int, sp, action):
    """Warlocks cast leveled spells at their single Pact Magic slot level (and consume
    that slot). Cantrips (level 0) are unaffected."""
    if sp.level >= 1:
        cs = app.combat.get_agent_stats(app.bm, caster_idx)
        if cs.character_class == rpg.CharacterClass.Warlock:
            pl = cs.pact_slot_level()
            if pl > 0:
                action.slot_level = pl


def spell_costs_action_and_bonus(app, sp) -> bool:
    """Does the catalog flag this spell as taking both the Action and the Bonus Action?"""
    si = app.spell_name_to_idx.get(sp.name)
    return si is not None and bool(app.all_spells[si].get("costs_action_and_bonus"))


def log_spell_results(app, result, cast_name: str, caster_idx: int = -1, spell_idx: int = -1):
    agents = app.bm.placed_agents
    spell = None
    if caster_idx >= 0 and spell_idx >= 0 and caster_idx < len(agents) and spell_idx < len(agents[caster_idx].spells):
        spell = agents[caster_idx].spells[spell_idx]

    for tr in result.target_results:
        tgt_name = agents[tr.target_idx].name if 0 <= tr.target_idx < len(agents) else "?"
        tgt_agent = agents[tr.target_idx] if 0 <= tr.target_idx < len(agents) else None

        if result.attack_type == rpg.SpellAttack.AttackRoll:
            # Check for damage modifiers in AttackRoll spells
            immunity_msg = app._get_immunity_message(spell, tgt_agent, tr)
            vuln_msg = app._get_vulnerability_message(spell, tgt_agent, tr)
            resist_msg = app._get_resistance_message(spell, tgt_agent, tr)

            modifier_suffix = ""
            if immunity_msg:
                modifier_suffix = f" ({immunity_msg})"
            elif vuln_msg:
                modifier_suffix = f" (Vulnerable to {', '.join(app._get_damage_modifier_names(spell, tgt_agent)['vulnerable'])})"
            elif resist_msg:
                modifier_suffix = f" (Resistant to {', '.join(app._get_damage_modifier_names(spell, tgt_agent)['resistant'])})"

            msg = f"{cast_name}→{tgt_name}: {result.spell_name} {tr.log_message}{modifier_suffix}"
        elif result.attack_type == rpg.SpellAttack.Save:
            # On-map outcome flash above the saving agent's token (per target for AoE).
            # Hoisted out of the spell/tgt_agent gate below so it fires even when the
            # spell-metadata lookup fails (e.g. NPC innate spells).
            app._spawn_flash(tr.target_idx, "Saved" if tr.saved else "Failed",
                              FLASH_GOOD if tr.saved else FLASH_BAD)
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
                aura_bonus = app.combat.aura_save_bonus(app.bm, tr.target_idx)
                aura_note = f" (incl. +{aura_bonus} Aura of Protection)" if aura_bonus > 0 else ""

                result_str = "SAVED" if tr.saved else "FAILED"
                dmg_str = f"{tr.total_healing} heal" if tr.total_healing else f"{tr.total_damage} dmg"
                # The engine already halved tr.total_damage on a successful save (and applied
                # that halved amount to HP) — just label it, don't halve a second time.
                if tr.saved and tr.total_damage > 0:
                    dmg_str = f"{tr.total_damage} dmg (half)"

                # Check for damage modifiers (immunity > vulnerability > resistance > normal)
                immunity_msg = app._get_immunity_message(spell, tgt_agent, tr)
                if immunity_msg:
                    dmg_str = immunity_msg
                else:
                    vuln_msg = app._get_vulnerability_message(spell, tgt_agent, tr)
                    if vuln_msg:
                        dmg_str = vuln_msg
                    else:
                        resist_msg = app._get_resistance_message(spell, tgt_agent, tr)
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
                    immunity_msg = app._get_immunity_message(spell, tgt_agent, tr)
                    if immunity_msg:
                        dmg_text = immunity_msg
                    else:
                        vuln_msg = app._get_vulnerability_message(spell, tgt_agent, tr)
                        if vuln_msg:
                            dmg_text = f"{vuln_msg}{saved_str}"
                        else:
                            resist_msg = app._get_resistance_message(spell, tgt_agent, tr)
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
            elif tr.log_message:
                # Weapon-attack cantrips (Booming Blade, True Strike) and blocked casts carry
                # their own outcome line (roll vs AC, hit/miss, damage).
                msg = f"{cast_name}→{tgt_name}: {result.spell_name} {tr.log_message}"
            else:
                # Check for damage modifiers (immunity > vulnerability > resistance > normal)
                immunity_msg = app._get_immunity_message(spell, tgt_agent, tr)
                if immunity_msg:
                    dmg_text = immunity_msg
                else:
                    vuln_msg = app._get_vulnerability_message(spell, tgt_agent, tr)
                    if vuln_msg:
                        dmg_text = vuln_msg
                    else:
                        resist_msg = app._get_resistance_message(spell, tgt_agent, tr)
                        if resist_msg:
                            dmg_text = resist_msg
                        else:
                            dmg_text = f"{tr.total_damage} dmg"
                msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                       f"{dmg_text}"
                       f"{' — DOWN' if tr.target_down else ''}")
        app._combat_log_add(msg)


def pending_spell(app):
    """The Spell object currently being aimed, or None."""
    ps = app._armed(pending.Spell)
    caster_idx = app._current_agent_idx()
    if caster_idx < 0 or ps is None:
        return None
    spells = app.combat.get_agent_spells(app.bm, caster_idx)
    if 0 <= ps.idx < len(spells):
        return spells[ps.idx]
    return None


def pending_spell_obj(app):
    """The rpg.Spell currently being aimed (pending single-target cast), or None."""
    ps = app._armed(pending.Spell)
    if ps is None or ps.is_aoe:
        return None
    ci = app._current_agent_idx()
    if ci < 0:
        return None
    spells = app.combat.get_agent_spells(app.bm, ci)
    if not (0 <= ps.idx < len(spells)):
        return None
    return spells[ps.idx]


def pending_spell_is_wall(app) -> bool:
    """True when the pending AoE spell is an oriented Rectangle 'wall'."""
    sp = app._pending_spell()
    return sp is not None and sp.geometry == rpg.SpellGeometry.Rectangle


def pending_spell_is_harm(app) -> bool:
    """True if the spell currently being aimed is a Harm spell (so a friendly-fire
    confirm is warranted). Heal/Transport spells return False — healing an ally
    must never prompt."""
    ps = app._armed(pending.Spell)
    if ps is None:
        return False
    ci = app._current_agent_idx()
    if ci < 0:
        return False
    spells = app.combat.get_agent_spells(app.bm, ci)
    if not (0 <= ps.idx < len(spells)):
        return False
    return spells[ps.idx].type == rpg.SpellType.Harm


def pending_spell_targets_corpse(app) -> bool:
    """True if the spell currently being aimed selects a true-dead body — either a revive
    (revives_dead — Raise Dead / Revivify) or Animate Dead (animates_dead, which raises an
    undead from the corpse). Both route their click through _corpse_at instead of _agent_at,
    since a corpse isn't reachable by the normal path."""
    sp = pending_spell_obj(app)
    return bool(sp and (getattr(sp, "revives_dead", False) or
                        getattr(sp, "animates_dead", False)))


def pending_spell_binds_creature(app) -> bool:
    """True if the spell currently being aimed binds a living creature to the caster's
    service (Planar Binding, binds_creature). Routes the single-target click through the
    control-transfer resolve instead of the ordinary damage/heal cast path."""
    sp = pending_spell_obj(app)
    return bool(sp and getattr(sp, "binds_creature", False))


def pending_spell_opens_doors(app) -> bool:
    """True if the spell currently pending a target is a door-opener (Knock).

    Knock is a Single-geometry spell, but it targets a doorway CELL (no creature),
    so the cast must route through the cell-targeting path instead of requiring a hit."""
    ps = app._armed(pending.Spell)
    if ps is None:
        return False
    ci = app._current_agent_idx()
    if ci < 0:
        return False
    try:
        sp = app.combat.get_agent_spells(app.bm, ci)[ps.idx]
        return getattr(sp, "opens_doors", False)
    except Exception:
        return False


def pending_spell_dispels_magic(app) -> bool:
    """True if the spell pending a target is a Dispel-Magic effect (dispels_magic flag).

    Dispel Magic is a Single-geometry spell that normally targets a creature, but it can
    also be aimed at a map CELL holding an ongoing area effect (Hunger of Hadar, Web, …) —
    that cell cast routes through the aoe path so the engine reads aoe_col/aoe_row."""
    ps = app._armed(pending.Spell)
    if ps is None:
        return False
    ci = app._current_agent_idx()
    if ci < 0:
        return False
    try:
        sp = app.combat.get_agent_spells(app.bm, ci)[ps.idx]
        return getattr(sp, "dispels_magic", False)
    except Exception:
        return False


def aoe_cells(app, center_cell, spell) -> list:
    """Return list of rpg.Cell objects covered by the spell AoE (1 cell = 5 ft)."""
    import math
    geo   = spell.geometry
    cols  = app.bm.grid_cols
    rows  = app.bm.grid_rows
    cells = []
    ax = float(center_cell.col)
    ay = float(center_cell.row)

    # Emanation: a Sphere whose center follows the caster — preview it on the caster.
    if getattr(spell, "moves_with_caster", False) and geo == rpg.SpellGeometry.Sphere:
        caster_idx = app._current_agent_idx()
        if caster_idx >= 0:
            cp = app.bm.placed_agents[caster_idx].origin
            ax, ay = float(cp.col), float(cp.row)

    if geo == rpg.SpellGeometry.Sphere:
        r_cells = spell.radius / 5.0
        for c in range(cols):
            for r in range(rows):
                dx, dy = c - ax, r - ay
                if math.sqrt(dx*dx + dy*dy) <= r_cells:
                    cells.append(rpg.Cell(c, r))

    elif geo == rpg.SpellGeometry.Cone:
        caster_idx = app._current_agent_idx()
        if caster_idx < 0:
            return cells
        pa = app.bm.placed_agents[caster_idx]
        cp = pa.origin
        csize = pa.size
        # Apex = cell on the caster's NxN footprint nearest the aim point, so a
        # Large+ creature's cone emanates from the facing edge, not its top-left.
        cx = float(min(max(center_cell.col, cp.col), cp.col + csize - 1))
        cy = float(min(max(center_cell.row, cp.row), cp.row + csize - 1))
        dx, dy = ax - cx, ay - cy
        ln = math.sqrt(dx*dx + dy*dy)
        if ln < 0.001:
            return cells
        ux, uy = dx/ln, dy/ln
        r_cells = spell.radius / 5.0
        footprint = {(cp.col + i, cp.row + j)
                     for i in range(csize) for j in range(csize)}
        for c in range(cols):
            for r in range(rows):
                if (c, r) in footprint:
                    continue  # the cone never covers the caster's own space
                px, py = c - cx, r - cy
                plen = math.sqrt(px*px + py*py)
                if plen < 0.001:
                    continue
                dot = px*ux + py*uy
                if dot > 0 and plen <= r_cells and (dot/plen) >= 0.866:
                    cells.append(rpg.Cell(c, r))

    elif geo == rpg.SpellGeometry.Line:
        caster_idx = app._current_agent_idx()
        if caster_idx < 0:
            return cells
        pa = app.bm.placed_agents[caster_idx]
        cp = pa.origin
        csize = pa.size
        # Apex = cell on the caster's footprint nearest the aim point (see Cone).
        cx = float(min(max(center_cell.col, cp.col), cp.col + csize - 1))
        cy = float(min(max(center_cell.row, cp.row), cp.row + csize - 1))
        dx, dy = ax - cx, ay - cy
        ln = math.sqrt(dx*dx + dy*dy)
        if ln < 0.001:
            return cells
        ux, uy = dx/ln, dy/ln
        footprint = {(cp.col + i, cp.row + j)
                     for i in range(csize) for j in range(csize)}
        l_cells = spell.length / 5.0
        w_cells = spell.width  / 5.0
        for c in range(cols):
            for r in range(rows):
                if (c, r) in footprint:
                    continue  # the line never covers the caster's own space
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


def area_template(app, caster_idx: int, sp, center) -> list:
    """The cells an area spell centred on `center` would cover, cut by its range and
    line of sight. The hover preview draws it, and a remote caster's confirm sends it
    as `you.aoe` (M5e E-8), so the two cannot disagree."""
    return filter_spell_cells_by_range_and_los(app, 
        aoe_cells(app, center, sp), caster_idx, sp, center_cell=center)


def filter_spell_cells_by_range_and_los(app, cells: list, caster_idx: int, spell, center_cell=None) -> list:
    """Filter cells using C++ method that respects spell's requires_los and check_los_on_center flags."""
    if caster_idx < 0 or caster_idx >= len(app.bm.placed_agents):
        return cells
    if not center_cell:
        return cells

    caster = app.bm.placed_agents[caster_idx]
    return app.bm.filter_spell_cells(cells, caster.origin, caster.size, spell, center_cell)


def wall_anchor_in_range(app, cell) -> bool:
    """The wall's start point must lie within the spell's range of the caster."""
    sp = app._pending_spell()
    caster_idx = app._current_agent_idx()
    if sp is None or caster_idx < 0:
        return True
    origin = app.bm.placed_agents[caster_idx].origin
    dist_cells = math.hypot(cell.col - origin.col, cell.row - origin.row)
    return dist_cells * 5.0 <= sp.range + 1e-6


def is_chromatic_pending(app) -> bool:
    """True when the spell currently being aimed is Chromatic Orb."""
    sp = app._pending_spell()
    return sp is not None and sp.name == "Chromatic Orb"


def chromatic_last_hop(app) -> int:
    """The creature the next leap would spring from (primary, or the last chained hop)."""
    return app.pending_chromatic_chain[-1] if app.pending_chromatic_chain \
        else app.pending_chromatic_primary


def enter_chromatic_chain(app, primary_idx: int):
    """Primary target chosen — switch to leap-chain collection mode (no cast yet)."""
    app._arm_pick("chromatic")
    app.pending_chromatic_primary = primary_idx
    app.pending_chromatic_chain   = []
    name = app.bm.placed_agents[primary_idx].name
    app._combat_log_add(
        f"Chromatic Orb → {name}. Click leap targets in order (≤30 ft each hop); "
        f"Enter to cast, Esc to cancel.")


def chromatic_add_leap(app, hit: int):
    """Validate and append a clicked creature to the leap chain (or explain the rejection)."""
    if hit < 0:
        return
    caster_idx = app._current_agent_idx()
    if hit == caster_idx:
        app._combat_log_add("The orb can't leap to its caster.")
        return
    if hit == app.pending_chromatic_primary or hit in app.pending_chromatic_chain:
        app._combat_log_add("That creature is already in the chain.")
        return
    if app._are_allies(caster_idx, hit):
        app._combat_log_add("The orb leaps to foes, not allies.")
        return
    if app.combat.get_agent_stats(app.bm, hit).hp_cur <= 0:
        app._combat_log_add("That creature is already down.")
        return
    prev = chromatic_last_hop(app)
    dist = app._footprint_dist_ft(prev, hit)
    if dist < 0 or dist > 30:
        app._combat_log_add(
            f"Too far — {app.bm.placed_agents[hit].name} is {dist} ft from the previous hop (max 30).")
        return
    app.pending_chromatic_chain.append(hit)
    app._combat_log_add(
        f"  leap {len(app.pending_chromatic_chain)} → {app.bm.placed_agents[hit].name} ({dist} ft)")


def finalize_chromatic_cast(app):
    """Enter pressed — cast Chromatic Orb with the collected leap chain."""
    primary = app.pending_chromatic_primary
    if primary < 0:
        return
    app._drop_pick("chromatic")
    # _resolve_spell_cast reads pending_chromatic_chain and clears the chain state.
    app._resolve_spell_cast(primary)


def cancel_chromatic_chain(app):
    app._drop_pick("chromatic")
    app.pending_chromatic_primary = -1
    app.pending_chromatic_chain   = []
    app._disarm(pending.Spell)
    app.spell_hover_cell          = None
    app._combat_log_add("Chromatic Orb cancelled.")


def careful_ally_targets(app, caster_idx: int) -> list:
    """Living party allies of the caster, to shield from a Careful Spell's area.
    The engine caps the shielded set at the caster's CHA modifier and only excludes
    those actually in the area, so passing all living allies is safe."""
    out = []
    for i in range(len(app.bm.placed_agents)):
        if i == caster_idx or not app._are_allies(caster_idx, i):
            continue
        if app.combat.get_agent_stats(app.bm, i).hp_cur > 0:
            out.append(i)
    return out


def sorcery_incarnate_active(app, idx: int) -> bool:
    """Sorcery Incarnate (Sorcerer L7): while Innate Sorcery is running, this caster may put
    TWO Metamagic options on one spell. Single source of truth is the engine predicate."""
    if not (0 <= idx < len(app.bm.placed_agents)):
        return False
    return rpg.CombatEngine.sorcery_incarnate_active(app.combat.get_agent_stats(app.bm, idx))


def armed_metamagic_options(app, caster_idx: int) -> list:
    """The Metamagic options the sidebar currently has armed for this caster, in the order the
    engine should apply them (at most 2 — the engine's slot count). The radio option leads;
    a second option rides along only under Sorcery Incarnate; Seeking (the one option that
    stacks with another, SRD p.66) fills a free slot without needing Sorcery Incarnate."""
    opts = []
    if app.armed_metamagic != rpg.MetamagicOption.NONE:
        opts.append(app.armed_metamagic)
    if (app.armed_metamagic2 != rpg.MetamagicOption.NONE and
            app.armed_metamagic2 not in opts and
            sorcery_incarnate_active(app, caster_idx)):
        opts.append(app.armed_metamagic2)
    if app.armed_seeking and rpg.MetamagicOption.Seeking not in opts:
        opts.append(rpg.MetamagicOption.Seeking)
    return opts[:2]


def enhanced_necromancy_armed_for(app, sp, caster_idx: int, slot_level: int = 0) -> bool:
    """True when Enhanced Necromancy is armed and this single-target spell qualifies (a
    Necromancy spell of level 5 or lower, or a Grave Domain spell) and a Channel Divinity use
    is left. Corpse-targeted spells (Revivify, Raise Dead) keep their own one-corpse pick."""
    if not app.enhanced_necromancy_armed or sp.geometry != rpg.SpellGeometry.Single:
        return False
    if getattr(sp, "revives_dead", False) or getattr(sp, "animates_dead", False):
        return False
    stats = app.combat.get_agent_stats(app.bm, caster_idx)
    return app.combat.can_enhanced_necromancy(stats, sp, slot_level)


def twinned_single_armed(app, sp, caster_idx: int) -> bool:
    """True when Twinned Spell is armed for a Single-geometry (single-target) spell, so the
    cast should collect one extra target. Twinned only augments spells that otherwise hit a
    single creature; AoE/Multiple geometries manage their own target counts. Affordability is
    re-checked by the engine at cast time — a short-on-SP Twinned simply drops the 2nd target."""
    return (rpg.MetamagicOption.Twinned in armed_metamagic_options(app, caster_idx) and
            sp.geometry == rpg.SpellGeometry.Single)


def apply_armed_metamagic(app, action, caster_idx: int) -> None:
    """Fold the sidebar-armed Metamagic option(s) into a player SpellAction. The engine
    validates applicability BEFORE spending Sorcery Points and no-ops (logged) on a
    mismatch, so a wrong armed toggle costs nothing. Up to two options ride along — the
    engine gates the second on Seeking (which stacks) or Sorcery Incarnate (L7 + Innate
    Sorcery active), and drops it unpaid otherwise."""
    opts = armed_metamagic_options(app, caster_idx)
    # Quickened only makes sense on a Bonus-Action cast (it IS the bonus-action cast). If the
    # spell is going out with the Action, drop Quickened so it neither spends Sorcery Points
    # nor mislabels the economy — the player simply casts it normally with their Action.
    if app._armed_slot(pending.Spell) != "bonus":
        opts = [o for o in opts if o != rpg.MetamagicOption.Quickened]
    if not opts:
        return
    action.metamagic = opts[0]
    if len(opts) > 1:
        action.metamagic2 = opts[1]
    # Parameter data is per-option, not per-slot: fill it if the option rides in EITHER slot.
    if rpg.MetamagicOption.Transmuted in opts:
        action.transmuted_damage_type = app.pending_metamagic_transmute_type
    if rpg.MetamagicOption.Careful in opts:
        action.careful_targets = careful_ally_targets(app, caster_idx)


def cast_dispel_selection(app, candidate, hit, cell):
    """Commit the picked Dispel Magic target: stash its structure ids and route through the
    normal cast path (which spends the slot once and runs the OnDeclareCast reaction window).
    execute_spell reads the selection and ends only that spell (dispelSelected)."""
    app.pending_dispel_selection = dict(
        condition_ids    = list(candidate.condition_ids),
        spell_effect_ids = list(candidate.spell_effect_ids),
        terrain_ids      = list(candidate.terrain_ids),
    )
    if hit is not None and hit >= 0:
        app._resolve_spell_cast(hit)
    elif cell is not None:
        app._resolve_spell_cast_aoe(cell)
    else:
        app.pending_dispel_selection = None


def apply_dispel_selection(app, action):
    """Copy the Dispel Magic picker's chosen structure ids onto `action`, then clear the pending
    selection. A no-op for every other spell (and for a whole-target dispel), so it is safe to
    call on every cast. execute_spell ends only the chosen effects when these are set."""
    sel = app.pending_dispel_selection
    if not sel:
        return
    action.dispel_condition_ids    = sel["condition_ids"]
    action.dispel_spell_effect_ids = sel["spell_effect_ids"]
    action.dispel_terrain_ids      = sel["terrain_ids"]
    app.pending_dispel_selection  = None


def on_wish_duplicate(app, caster_idx: int, slot: str, wish_slot_level: int, spell_dict: dict):
    """A spell was chosen from the Wish picker. Charge Wish's own slot, inject the duplicated
    spell onto the caster (the engine casts by index), and run it through the normal dispatch
    as a free cast at its base level. The injected spell is kept in the caster's list (its
    index is remembered in _wish_temp_spells so the cast menu skips it) — never removed,
    because ongoing concentration/dispel bookkeeping re-reads spells[spell_idx]."""
    if caster_idx < 0:
        return
    # Charge Wish's own slot (normally 9th). If the caster somehow lacks it, abort cleanly.
    # Exception: a Greater-DI (L20) Wish is already paid for by Divine Intervention's 2d4
    # recharge lock, so skip the slot charge (the _di_wish_free flag is a one-shot).
    if app._di_wish_free:
        app._di_wish_free = False
    elif not app.combat.spend_spell_slot(app.bm, caster_idx, wish_slot_level):
        app._combat_log_add("Wish fizzles — no spell slot to power it.")
        return
    spell = _dict_to_spell(spell_dict)
    app.combat.add_spell_to_agent(app.bm, caster_idx, spell)
    spells = app.combat.get_agent_spells(app.bm, caster_idx)
    new_idx = len(spells) - 1
    app._wish_temp_spells.add(new_idx)
    stats = app.combat.get_agent_stats(app.bm, caster_idx)
    app._combat_log_add(f"Wish duplicates {spell.name}!")
    # Cast the duplicate at its base level, for free, through the full dispatch (element
    # choice, summon placement, AoE, single-target — all handled as usual).
    app._activate_spell(slot, new_idx, spell.level, caster_idx, spells, stats, free_cast=True)


def start_divine_intervention(app):
    """Divine Intervention (Cleric L10): open the Cleric-≤5 picker (Wish added at L20). Mirrors
    the Wish flow — the chosen spell is injected and free-cast; the DI resource is the cost."""
    idx = app._current_agent_idx()
    if idx < 0 or not app.combat.can_use_divine_intervention(app.bm, idx):
        return
    stats = app.combat.get_agent_stats(app.bm, idx)
    greater = stats.class_level(rpg.CharacterClass.Cleric) >= 20
    # The cap is on the Cleric spells only: Greater DI's Wish is 9th level, and capping
    # it with them hid it at 20th level too (F-M5e-12).
    ask_spell_browser(app, 
        idx, "Divine Intervention — choose a Cleric spell (≤ 5th level"
             + (", or Wish)" if greater else ")"),
        [d for d in app.all_spells
         if (d.get("level", 0) <= 5 and d.get("name") in CLERIC_DI_SPELL_NAMES)
         or (greater and d.get("name") == "Wish")],
        lambda d, i=idx, g=greater: on_divine_intervention_pick(app, i, g, d))
    app._combat_log_add("Divine Intervention — choose a Cleric spell of level 5 or lower.")


def drop_di_wish_free(app):
    app._di_wish_free = False


def on_divine_intervention_pick(app, caster_idx: int, greater: bool, spell_dict: dict):
    """A spell was chosen from the DI picker. Spend the DI use, inject the spell, and free-cast
    it. If the pick is Wish (Greater DI, L20) route through the normal Wish duplicate flow but
    skip its slot charge (DI's 2d4 lock is the cost — see _on_wish_duplicate / _di_wish_free)."""
    if caster_idx < 0:
        return
    chose_wish = spell_dict.get("name") == "Wish"
    if not app.combat.use_divine_intervention(app.bm, caster_idx, chose_wish):
        app._combat_log_add("Divine Intervention is unavailable.")
        return
    spell = _dict_to_spell(spell_dict)
    app.combat.add_spell_to_agent(app.bm, caster_idx, spell)
    spells = app.combat.get_agent_spells(app.bm, caster_idx)
    new_idx = len(spells) - 1
    app._di_temp_spells.add(new_idx)     # skip in the cast menu, like _wish_temp_spells
    stats = app.combat.get_agent_stats(app.bm, caster_idx)
    app.action_used = True               # DI is a Magic action
    if chose_wish:
        # Greater DI: run Wish's own duplicate picker for free (free_cast=False so the Wish
        # branch in _activate_spell fires; _di_wish_free suppresses the 9th-slot charge).
        app._di_wish_free = True
        app._combat_log_add("Greater Divine Intervention: casting Wish for free!")
        app._activate_spell("action", new_idx, spell.level, caster_idx, spells, stats, free_cast=False)
    else:
        app._combat_log_add(f"Divine Intervention: casting {spell.name} for free!")
        app._activate_spell("action", new_idx, spell.level, caster_idx, spells, stats, free_cast=True)


def arm_bewitching_misty(app, caster_idx: int):
    """DM accepted Bewitching Magic — arm the free Misty Step destination pick (with the currently
    selected Steps of the Fey rider)."""
    app._arm_pick("bewitching_misty")
    app._combat_log_add(
        "Bewitching Magic — click a destination within 30 ft (or click yourself to decline).")
    app._flush_combat_log()


def decline_bewitching_offer(app):
    """DM declined the free Bewitching Magic Misty Step."""
    app._drop_pick("bewitching_misty")
    app._combat_log_add("Bewitching Magic not used.")
    app._flush_combat_log()


def arm_beguiling_target_pick(app, caster_idx: int):
    """DM accepted the Beguiling Magic offer — arm the click-a-creature target pick (a following
    creature click routes to _beguiling_pick_target for the WIS save + Charmed/Frightened pick)."""
    app._arm_pick("beguiling")
    app.pending_beguiling_bard = caster_idx
    app._combat_log_add(
        "Beguiling Magic — click a creature within 60 ft to force a WIS save (Esc declines).")
    app._flush_combat_log()


def decline_beguiling_offer(app):
    """DM declined the Beguiling Magic offer — spend nothing, disarm."""
    app._drop_pick("beguiling")
    app.pending_beguiling_bard = -1
    app._combat_log_add("Beguiling Magic not used.")
    app._flush_combat_log()


def cancel_beguiling(app):
    """Esc out of Beguiling Magic without using it (the spell was already cast normally)."""
    app._drop_pick("beguiling")
    app.pending_beguiling_bard = -1
    app._combat_log_add("Beguiling Magic declined.")
    app._flush_combat_log()


def restore_beguiling_magic(app, bard_idx: int):
    """College of Glamour: spend one Bardic Inspiration use (no action) to regain the expended
    Beguiling Magic use."""
    new_cur = app.combat.bard_restore_beguiling_magic(app.bm, bard_idx)
    app._flush_combat_log()
    if new_cur < 0:
        app._combat_log_add("Cannot restore Beguiling Magic (no Bardic Inspiration use, or already full).")
        app._flush_combat_log()
    app._update_attack_overlay()
