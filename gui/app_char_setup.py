"""Character setup and feature weapons: apply the stats dialog to a creature
(`on_stats_ok`), its origin / general feats (`set_origin_feat`, `set_general_feats`),
an NPC's innate spells from its bestiary record (`load_npc_spells_from_record`), the
always-prepared class features and their level scaling (`grant_class_features`,
`apply_feature_scaling`), item-granted spells (`sync_item_spells`,
`sync_all_item_spells`), the feature weapons (Monk unarmed strike, Alter Self claws, Pact
of the Blade, Soulknife Psychic Blades) and weapon drop / pickup (`drop_weapon`,
`pickup_item`, `find_pickup_slot`).

Moved out of `App` in APP_REFACTOR_PLAN.md A8, the same way as A7: module-level functions
taking the app; all state stays on `app`. `on_weapon_done` has no callers and is moved as
is, not deleted.

`App` keeps a one-line forwarder for every name reached from outside `main.py` (tests,
`menus/board`, `menus/panel`, `items_play`, `app_initiative`, `app_persist`, `app_spells`,
`app_summons`). Calls between moved functions go through the forwarder where one exists,
so an instance patch still sees them; `find_pickup_slot`, `create_pact_blade_weapon`,
`create_psychic_blade_weapon` and `apply_feature_scaling` have no forwarder and are
called directly.
"""

import rpg_battle_map as rpg

import helpers
from helpers import _dict_to_spell, _dict_to_weapon, _weapon_slot_is_empty
from dialogs import GENERAL_FEAT_NAMES, EPIC_BOON_FEAT_NAMES

# Origin feats the GUI can assign (must mirror StatsDialog.ORIGIN_FEATS minus "NONE").
# `App._ORIGIN_FEATS` aliases this (tests read it there).
ORIGIN_FEATS = {"Alert", "Crafter", "Healer", "Lucky", "Magic Initiate", "Musician",
                "Savage Attacker", "Skilled", "Tavern Brawler", "Tough"}


def load_npc_spells_from_record(app, agent_idx: int, mob_record: dict):
    """Auto-populate an NPC's innate spells from its bestiary record.

    Mirrors the saved-agent spell-restore path: the record's `spell_indices`
    (canonical catalog names) become Spell objects via spells.json, then
    `npc_spell_groups` ({uses/day: [names]}) sets each spell's uses_max via
    init_npc_spell_groups. No-op for non-casters."""
    spell_names = mob_record.get("spell_indices", [])
    if not spell_names:
        app._sync_item_spells(agent_idx)     # a non-caster can still carry an enspelled item
        return
    cpp_spells = []
    for spell_name in spell_names:
        idx = app.spell_name_to_idx.get(spell_name)
        if idx is None:
            print(f"WARNING: NPC spell '{spell_name}' not in catalog "
                  f"for {mob_record.get('name', agent_idx)}")
            continue
        spell_dict = app.all_spells[idx]
        app._spell_metadata[(agent_idx, len(cpp_spells))] = {
            "terrain_effect": spell_dict.get("terrain_effect"),
            "hatch_pattern": spell_dict.get("hatch_pattern"),
            "terrain_color": spell_dict.get("terrain_color"),
        }
        cpp_spells.append(_dict_to_spell(spell_dict))

    # Breath weapons / recharge actions: a per-monster {spell_name: recharge_min}
    # map sets the recharge die threshold on the matching catalog Spell (the
    # generic Breath<…> entries ship with recharge_min=0; the actual 5-6/6/4
    # value is monster-specific). uses_max=1 so it's a single charge that the
    # beginTurn d6 roll refills. See NPC_USES_RECHARGE_PLAN.md.
    recharge_map = mob_record.get("npc_spell_recharge", {})
    if recharge_map:
        for j, sp in enumerate(cpp_spells):
            rmin = recharge_map.get(sp.name)
            if rmin:
                sp.recharge_min   = int(rmin)
                sp.uses_max       = max(1, sp.uses_max)
                sp.uses_remaining = sp.uses_max
                sp.expended       = False
    app.combat.set_agent_spells(app.bm, agent_idx, cpp_spells)

    npc_spell_groups = mob_record.get("npc_spell_groups", {})
    if npc_spell_groups or recharge_map:
        groups_dict = {int(k): v for k, v in npc_spell_groups.items()}
        if groups_dict:
            app.combat.init_npc_spell_groups(app.bm, agent_idx, groups_dict)
        app._agent_meta[agent_idx] = {
            "is_npc": True, "npc_spell_groups": npc_spell_groups,
            "npc_spell_recharge": recharge_map}
    app._sync_item_spells(agent_idx)


def set_origin_feat(stats, new_feat: str, char_level: int):
    """Set the agent's single origin feat idempotently.

    The dialog re-edits a live Stats whose hp_max/luck_points already include any prior
    feat's one-time bonus (the HP stepper round-trips the boosted value), so changing or
    re-confirming a feat must STRIP the previous origin feat's effects before applying the
    new one. add_feat() (the C++ source of truth) handles the apply; this only handles the
    inverse for the swap. No-op when the feat is unchanged.
    """
    new_feat = new_feat or "NONE"
    prev = next((f for f in list(stats.feats) if f in ORIGIN_FEATS), None)
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
    stats.feats = [f for f in list(stats.feats) if f not in ORIGIN_FEATS]

    # Apply the newly chosen feat via the engine (applies Tough HP / Alert prof / Lucky points).
    if new_feat != "NONE":
        stats.add_feat(new_feat)


def set_general_feats(stats, names):
    """Set the agent's general feats from the multi-select picker.

    General feats currently carry no one-time stat effects (ASI is not auto-applied —
    edit ability scores via the steppers), so this is a plain replace: drop all general
    feats, then re-add the selected ones. `add_feat` is used so any future general feat
    that gains an addFeat effect still applies on grant. Origin feats are untouched
    (the name-sets are disjoint). Epic boons ride the same picker/list as general feats,
    so they are dropped/re-added here too.
    """
    names = list(names or [])
    stats.feats = [f for f in list(stats.feats)
                   if f not in GENERAL_FEAT_NAMES and f not in EPIC_BOON_FEAT_NAMES]
    for n in names:
        stats.add_feat(n)


def on_stats_ok(app, agent_idx: int, steppers: dict, prof_flags: dict, class_name: str = "None", char_level: int = 1, npc_data: dict = None, subclass_name: str = "NONE", eldritch_invocations: list = None, blessed_strike_name: str = "NONE", origin_feat: str = "NONE", general_feats: list = None, elemental_adept_types: list = None, hunter_prey_name: str = "NONE", defensive_tactics_name: str = "NONE", draconic_affinity_type: int = -1, metamagic_options: list = None, irresistible_offense_ability: int = 0, class_levels: dict = None, subclasses: dict = None, species: str = None, arcane_shot_options: list = None, species_option: str = None, species_size: str = None, species_spell_ability: int = None):
    """Called by StatsDialog when the user clicks OK.

    Multiclassing (MULTICLASSING_PLAN.md Phase 5): `class_levels` ({class:level})
    and `subclasses` ({class:subclass}) carry the full build. `class_name` /
    `char_level` remain the PRIMARY class / TOTAL level for the single-class
    feature logic below; the class/level/subclass/resource application iterates
    the maps. When `class_levels` is absent (legacy callers) it degrades to the
    single {class_name: char_level} build."""
    # Start from current stats so flags not shown in the dialog are preserved.
    stats = app.combat.get_agent_stats(app.bm, agent_idx)
    stats.str        = steppers["str"].value
    stats.dex        = steppers["dex"].value
    stats.con        = steppers["con"].value
    stats.intel      = steppers["intel"].value
    stats.wis        = steppers["wis"].value
    stats.cha        = steppers["cha"].value
    stats.hp_cur     = steppers["hp_cur"].value
    stats.hp_max     = steppers["hp_max"].value
    if "temp_hp" in steppers:       # Edit Stats sets temp HP outright (DM override)
        stats.temp_hp = steppers["temp_hp"].value
    stats.base_ac    = steppers["base_ac"].value
    stats.speed_walk   = steppers["speed_walk"].value
    stats.speed_swim   = steppers["speed_swim"].value
    stats.speed_fly    = steppers["speed_fly"].value
    stats.speed_burrow = steppers["speed_burrow"].value
    stats.prof_bonus   = steppers["prof_bonus"].value
    stats.num_attacks  = steppers["num_attacks"].value
    for key in ("attack_bonus", "spell_attack_bonus", "spell_dc_bonus"):
        if key in steppers:
            setattr(stats, key, steppers[key].value)
    # Saving throw proficiency per ability
    stats.save_prof_str   = prof_flags.get("save_prof_str",   False)
    stats.save_prof_dex   = prof_flags.get("save_prof_dex",   False)
    stats.save_prof_con   = prof_flags.get("save_prof_con",   False)
    stats.save_prof_intel = prof_flags.get("save_prof_intel", False)
    stats.save_prof_wis   = prof_flags.get("save_prof_wis",   False)
    stats.save_prof_cha   = prof_flags.get("save_prof_cha",   False)
    # Skill proficiency: Sleight of Hand (picks door locks)
    stats.sleight_of_hand_prof = prof_flags.get("sleight_of_hand_prof", False)
    # Skill proficiency: Athletics (forces doors off their frame)
    stats.athletics_prof = prof_flags.get("athletics_prof", False)

    # ── Multiclass class / level / subclass / resource application ──────────
    # Resolve the full build. Fall back to the single {primary: total} shape for
    # legacy callers that don't pass class_levels.
    cl_map = {c: int(l) for c, l in (class_levels or {}).items()
              if int(l) > 0 and c not in (None, "None")}
    if not cl_map:
        # No real class in the build → keep the agent's primary as-is. This
        # preserves the "None" sentinel for classless monsters (never invents a
        # Fighter) and degrades gracefully for legacy single-class callers.
        cl_map = {class_name: char_level}
    sub_map = dict(subclasses or {})
    if class_name in cl_map and subclass_name != "NONE" and class_name not in sub_map:
        sub_map[class_name] = subclass_name

    # Apply each membered class's subclass field FIRST (Draconic HP / Aberrant
    # resistance and other resource gates read the subclass in C++).
    subclass_fields = {
        "Barbarian": ("barbarian_subclass", rpg.BarbianSubclass),
        "Fighter":   ("fighter_subclass",   rpg.FighterSubclass),
        "Druid":     ("druid_circle",       rpg.DruidCircle),
        "Monk":      ("monk_subclass",      rpg.MonkSubclass),
        "Paladin":   ("paladin_oath",       rpg.PaladinOath),
        "Wizard":    ("wizard_subclass",    rpg.WizardSubclass),
        "Warlock":   ("warlock_subclass",   rpg.WarlockSubclass),
        "Rogue":     ("rogue_subclass",     rpg.RogueSubclass),
        "Cleric":    ("cleric_subclass",    rpg.ClericSubclass),
        "Bard":      ("bard_subclass",      rpg.BardCollege),
        "Sorcerer":  ("sorcerer_subclass",  rpg.SorcererSubclass),
        "Ranger":    ("ranger_subclass",    rpg.RangerSubclass),
    }
    for cls in cl_map:
        field = subclass_fields.get(cls)
        sub = sub_map.get(cls, "NONE")
        if field and sub not in (None,):
            try:
                setattr(stats, field[0], getattr(field[1], sub))
            except AttributeError:
                pass

    # Set class levels: primary (lowest enum ordinal) as a single-class reset,
    # then the remaining classes additively. Slots recompute via computeMulticlassSlots.
    _members = [(n, int(v)) for n, v in rpg.CharacterClass.__members__.items()]
    order = [n for n, v in sorted(_members, key=lambda kv: kv[1]) if v > 0]
    ordered = sorted(cl_map.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)
    stats.set_class_level(getattr(rpg.CharacterClass, ordered[0][0]), ordered[0][1])
    for cls, lvl in ordered[1:]:
        stats.add_class_level(getattr(rpg.CharacterClass, cls), lvl)

    # Per-class level-dependent side effects.
    # Path of the World Tree L6 — Branches of the Tree (C++ reaction gates on this flag).
    if "Barbarian" in cl_map:
        stats.has_branches_of_the_tree = (
            sub_map.get("Barbarian") == "WorldTree" and cl_map["Barbarian"] >= 6)
    # Ranger Hunter / Beast Master defaults.
    if "Ranger" in cl_map:
        rlvl = cl_map["Ranger"]
        if sub_map.get("Ranger") == "Hunter":
            if hunter_prey_name not in (None, "NONE"):
                stats.hunter_prey = getattr(rpg.HunterPrey, hunter_prey_name)
            elif stats.hunter_prey == rpg.HunterPrey.NONE:
                stats.hunter_prey = rpg.HunterPrey.ColossusSlayer
            if defensive_tactics_name not in (None, "NONE"):
                stats.defensive_tactics = getattr(rpg.DefensiveTactics, defensive_tactics_name)
            elif rlvl >= 7 and stats.defensive_tactics == rpg.DefensiveTactics.NONE:
                stats.defensive_tactics = rpg.DefensiveTactics.EscapeTheHorde
        if sub_map.get("Ranger") == "BeastMaster" and stats.primal_companion == rpg.PrimalCompanion.NONE:
            stats.primal_companion = rpg.PrimalCompanion.Land

    # Cleric Blessed Strikes choice (L7+)
    if "Cleric" in cl_map and blessed_strike_name != "NONE":
        stats.blessed_strike = getattr(rpg.BlessedStrike, blessed_strike_name)

    # Set Warlock invocations
    if "Warlock" in cl_map and eldritch_invocations:
        stats.eldritch_invocations = list(eldritch_invocations)

    # Initialize class resources for ALL classes (Rage, Focus Points, Portent Dice, …).
    # Merges per class and never double-counts Extra Attack. Must come AFTER subclasses
    # are set since resource creation checks them.
    stats.initialize_multiclass_resources()
    # Restore remaining slots to max (set/add + resource init just recomputed them).
    stats.spell_slots_remaining = list(stats.spell_slots_max)

    # Origin feat (one per PC). Applied after stats/level/prof_bonus are set so Tough HP,
    # Alert initiative proficiency, and Lucky points compute from the final values.
    app._set_origin_feat(stats, origin_feat, char_level)
    # General feats (multi-select). Disjoint from origin feats; no ASI auto-apply.
    app._set_general_feats(stats, general_feats)
    # Species (None = a legacy caller that doesn't pass one: leave it as it is). set_species
    # strips the old species' traits and applies the new one's; unchanged is a no-op, so a
    # hand-edited speed survives a re-confirm.
    # The sub-choices (D2) follow it; set_species keeps each valid one and defaults the rest.
    if species is not None:
        stats.set_species("" if species == "NONE" else species, species_option or "")
        if species_size:
            stats.set_species_size(species_size)
        if species_spell_ability is not None:
            stats.set_species_spell_ability(int(species_spell_ability))
    # Dwarven Toughness tracks the level: a level change since the species was set moves the
    # folded-in HP bonus (no-op otherwise, and for every other species).
    stats.sync_species_hp()
    # Elemental Adept's chosen element(s) (set via the element picker). Kept only while the feat
    # is selected; cleared otherwise so a deselect doesn't leave stale types.
    stats.elemental_adept_types = list(elemental_adept_types or []) if stats.has_feat("Elemental Adept") else []
    # Boon of Irresistible Offense: which score Overwhelming Strike reads (0=STR, 1=DEX).
    stats.irresistible_offense_ability = int(irresistible_offense_ability) if stats.has_feat("Boon of Irresistible Offense") else 0
    # Draconic L6: persist the chosen ancestry element (-1 = none/not yet set).
    if "Sorcerer" in cl_map and sub_map.get("Sorcerer") == "Draconic":
        stats.draconic_affinity_type = int(draconic_affinity_type)
    # Sorcerer Metamagic: the learned options (assign the whole list via the property
    # setter — metamagic_options is a bound std::vector<MetamagicOption>; do not mutate
    # elements in place, cf. pybind11_array_copy_gotcha). Cleared for non-Sorcerers.
    stats.metamagic_options = ([rpg.MetamagicOption(int(v)) for v in (metamagic_options or [])]
                               if "Sorcerer" in cl_map else [])
    # Arcane Archer: known Arcane Shot options (D2). None = a caller that doesn't pass the
    # list: keep what the agent has. Capped at the Fighter level's known count; cleared
    # when the agent is no longer an Arcane Archer.
    if sub_map.get("Fighter") == "ArcaneArcher" and "Fighter" in cl_map:
        if arcane_shot_options is not None:
            cap = rpg.Stats.arcane_shot_known_count(cl_map["Fighter"])
            stats.arcane_shot_options = [rpg.ArcaneShotOption(int(v))
                                         for v in arcane_shot_options][:cap]
    else:
        stats.arcane_shot_options = []

    # Initiative: the dialog shows the total modifier. A changed value becomes the flat
    # initiative_bonus on top of what DEX / prof / feats now give; an untouched one keeps
    # the stored bonus, so a DEX or proficiency edit still moves initiative.
    st_init = steppers.get("initiative")
    if st_init is not None and st_init.value != getattr(st_init, "start", st_init.value):
        stats.initiative_bonus = 0
        stats.initiative_bonus = st_init.value - stats.initiative_modifier

    app.combat.set_agent_stats(app.bm, agent_idx, stats)

    # For Monks, replace default "Unarmed" weapon with "MonkUnarmed" (1d8)
    if "Monk" in cl_map:
        current_weapons = list(app.combat.get_agent_weapons(app.bm, agent_idx))
        # Replace the first weapon (default) with MonkUnarmed if it's named "Unarmed"
        if current_weapons and current_weapons[0].name == "Unarmed":
            current_weapons[0] = app._create_monk_unarmed_weapon()
            app.combat.set_agent_weapons(app.bm, agent_idx, current_weapons)

    # Master of Myriad Forms (invocation 12): give the Warlock Alter Self claws
    # (1d6) in place of a bare unarmed strike.
    if "Warlock" in cl_map and 12 in (eldritch_invocations or []):
        current_weapons = list(app.combat.get_agent_weapons(app.bm, agent_idx))
        if current_weapons and current_weapons[0].name == "Unarmed":
            current_weapons[0] = app._create_alter_self_claws_weapon()
            app.combat.set_agent_weapons(app.bm, agent_idx, current_weapons)

    # Pact of the Blade (invocation 13): the MAIN-HAND weapon (slot 0) becomes the pact weapon.
    # pact_weapon=True drives the CHA attack/damage + the pact-weapon rider gates.
    if "Warlock" in cl_map and 13 in (eldritch_invocations or []):
        current_weapons = list(app.combat.get_agent_weapons(app.bm, agent_idx))
        if app._bond_pact_weapon(current_weapons):
            app.combat.set_agent_weapons(app.bm, agent_idx, current_weapons)

    # Soulknife Rogue (L3+): manifest Psychic Blades — a 1d6 Psychic finesse/thrown blade in the
    # main hand and a 1d4 off-hand blade (the bonus second blade). psychic_blade=True identifies
    # them for Homing Strikes / Rend Mind. (Manifesting on the Attack action is simplified to a
    # standing equip, like PactBlade.)
    stats_chk = app.combat.get_agent_stats(app.bm, agent_idx)
    current_weapons = list(app.combat.get_agent_weapons(app.bm, agent_idx))
    current_weapons, blades_changed = app._apply_psychic_blades(stats_chk, current_weapons)
    if blades_changed:
        app.combat.set_agent_weapons(app.bm, agent_idx, current_weapons)
        stats_chk.has_offhand_attack = True
        app.combat.set_agent_stats(app.bm, agent_idx, stats_chk)

    # The dialog's NPC box decides the engine flag, both ways: is_npc is what saves and what
    # picks spells/day over slots, so unticking the box has to clear it here.
    was_npc = stats_chk.is_npc
    stats_chk.is_npc = bool(npc_data)
    app.combat.set_agent_stats(app.bm, agent_idx, stats_chk)

    # Store NPC metadata if provided, and initialize spell uses via C++
    if npc_data:
        app._agent_meta[agent_idx] = npc_data
        # Initialize spell uses_max/uses_remaining in C++ from npc_spell_groups
        npc_spell_groups = npc_data.get("npc_spell_groups", {})
        if npc_spell_groups:
            groups_dict = {int(k): v for k, v in npc_spell_groups.items()}
            app.combat.init_npc_spell_groups(app.bm, agent_idx, groups_dict)
    elif agent_idx in app._agent_meta:
        del app._agent_meta[agent_idx]

    # Always-prepared class features (Divine Spark, Radiance of the Dawn, domain spells) follow
    # from class/level/subclass — re-grant onto the agent's current spells so they show up
    # without needing to reopen the spell picker.
    cpp_spells = list(app.combat.get_agent_spells(app.bm, agent_idx))
    if was_npc and not npc_data:
        # Back to spell slots: drop the N/day and recharge limits the NPC spells carried.
        for sp in cpp_spells:
            sp.uses_max = sp.uses_remaining = sp.recharge_min = 0
            sp.expended = False
    app._grant_class_features(agent_idx, cpp_spells)
    app.combat.set_agent_spells(app.bm, agent_idx, cpp_spells)
    # Species spells (SPECIES D3) follow the species, option and level just set.
    app._sync_item_spells(agent_idx)

    if agent_idx == app.selected_idx:
        app._update_reach()


def on_weapon_done(app, agent_idx: int, weapons: list[dict]):
    """Called by WeaponDialog when the user clicks Done.

    `weapons` is a list of plain dicts (the WeaponDialog's internal format).
    Convert each to an rpg.Weapon and push the list into the C++ layer.
    """
    cpp_weapons = [_dict_to_weapon(d) for d in weapons]
    # Update has_offhand_attack based on whether any weapon is off-hand
    stats = app.combat.get_agent_stats(app.bm, agent_idx)
    offhand = any(d.get("off_hand", False) for d in weapons)
    # Re-manifest a Soulknife's Psychic Blades — the synthetic blade isn't in weapons.json, so the
    # Weapon dialog would otherwise overwrite slots 0/1 with whatever it holds (see _apply_psychic_blades).
    cpp_weapons, blades_changed = app._apply_psychic_blades(stats, cpp_weapons)
    if blades_changed:
        offhand = True
    app.combat.set_agent_weapons(app.bm, agent_idx, cpp_weapons)
    app._sync_item_spells(agent_idx)
    stats.has_offhand_attack = offhand
    app.combat.set_agent_stats(app.bm, agent_idx, stats)
    # Refresh attack overlay if this is the currently selected agent.
    if agent_idx == app.selected_idx:
        app._update_attack_overlay()


def drop_weapon(app, slot_idx: int):
    """Drop the equipped weapon in slot_idx onto the current agent's cell."""
    cur_idx = app._current_agent_idx()
    if cur_idx < 0:
        return
    weapons = list(app.combat.get_agent_weapons(app.bm, cur_idx))
    weapon = weapons[slot_idx]
    if not weapon.name or weapon.name == "Unnamed":
        return
    # Natural/innate attacks (permanently_armed, Unarmed, a generic "Melee (Slashing)"
    # stat-block attack) cannot be dropped.
    if not weapon.droppable():
        app._combat_log_add(f"{app.bm.placed_agents[cur_idx].name} can't drop {weapon.name}.")
        return
    # Sprite: the Weapon now carries its own (so an engine-side drop — a THROW — lands with the
    # right icon too); fall back to the weapons.json catalog for one built before that field.
    wdict = app.weapon_name_to_dict.get(weapon.name, {})
    sprite_path = weapon.sprite_path or wdict.get("sprite_path", "")
    # Place item at agent's current cell
    agent = app.bm.placed_agents[cur_idx]
    print(f"[_drop_weapon] Dropping {weapon.name} from slot {slot_idx} for agent {agent.name} at ({agent.origin.col},{agent.origin.row})")
    print(f"[_drop_weapon DEBUG] weapon.permanently_armed = {weapon.permanently_armed}")
    item_id = app.bm.place_item(agent.origin, weapon, sprite_path)
    # Clear the weapon slot
    weapons[slot_idx] = rpg.Weapon()
    print(f"[_drop_weapon DEBUG] Before set_agent_weapons: weapons[{slot_idx}].name = '{weapons[slot_idx].name}'")
    app.combat.set_agent_weapons(app.bm, cur_idx, weapons)
    # Verify the slot was cleared
    weapons_after = list(app.combat.get_agent_weapons(app.bm, cur_idx))
    print(f"[_drop_weapon DEBUG] After set_agent_weapons: weapons_after[{slot_idx}].name = '{weapons_after[slot_idx].name}'")
    app._sync_item_spells(cur_idx)
    app._combat_log_add(f"{agent.name} drops {weapon.name}.")


def pickup_item(app, item, agent_idx: int):
    """Take a weapon off the ground: pick the slot here, let the engine do the assignment.

    BattleMap::pickUpItem owns what happens to the weapon list — in particular, retrieving a
    thrown weapon you are still carrying re-joins the BUNDLE (pick up one of the javelins you
    threw and you hold 4 again, not two stacks) rather than consuming the slot we suggest. That
    rule lives in exactly one place; don't re-implement it here."""
    weapons = list(app.combat.get_agent_weapons(app.bm, agent_idx))
    agent = app.bm.placed_agents[agent_idx]
    name = item.weapon.name or "weapon"

    slot = find_pickup_slot(app, item.weapon, weapons)
    stats = app.combat.get_agent_stats(app.bm, agent_idx)
    pact = stats.has_class(rpg.CharacterClass.Warlock) and stats.has_invocation(13)
    # Pact of the Blade: the pact weapon goes back in the main hand, dismissing a PactBlade
    # conjured there meanwhile (a reload re-conjures one into the hand the weapon fell from).
    if pact and item.weapon.pact_weapon and weapons and weapons[0].name == "PactBlade":
        slot = 0
    if not app.bm.pick_up_item(item.id, agent_idx, slot):
        app._combat_log_add(f"{agent.name} can't pick up {name}.")
        return
    app._sync_item_spells(agent_idx)

    # A weapon taken into the main hand is the pact weapon again (also repairs items saved
    # before map items kept pact_weapon).
    if slot == 0 and pact:
        weapons = list(app.combat.get_agent_weapons(app.bm, agent_idx))
        if app._bond_pact_weapon(weapons):
            app.combat.set_agent_weapons(app.bm, agent_idx, weapons)

    held = next((w.quantity for w in app.combat.get_agent_weapons(app.bm, agent_idx)
                 if w.name == item.weapon.name and w.thrown), 0)
    if held > 1:
        app._combat_log_add(f"{agent.name} picks up {name} ({held} in hand).")
    else:
        app._combat_log_add(f"{agent.name} picks up {name}.")


def find_pickup_slot(app, weapon, weapons) -> int:
    """Auto-assign weapon to the best available slot. With the variable-length
    weapon list there is always room: an empty compatible slot is reused, else
    the first empty interior slot, else a new appended slot (== len(weapons))."""
    # A slot is empty when it holds the blank-slot sentinel — an empty name, or the bare
    # "Unarmed"/"Unnamed" default (helpers._weapon_slot_is_empty, and what a dropped or
    # fully-thrown slot is reset to). Match it EXACTLY: "MonkUnarmed" is a real weapon, and a
    # substring test let a picked-up longsword overwrite a Monk's unarmed strike.
    EMPTY = lambda w: (not w.name) or w.name in ("Unarmed", "Unnamed")
    # Ranged weapon → prefer the ranged slot (index 2) if empty
    if weapon.type == rpg.WeaponType.Ranged and len(weapons) > 2 and EMPTY(weapons[2]):
        return 2
    # Main hand empty → slot 0
    if len(weapons) > 0 and EMPTY(weapons[0]):
        return 0
    # Off-hand empty → slot 1
    if len(weapons) > 1 and EMPTY(weapons[1]):
        return 1
    # Ranged slot empty as last resort for melee
    if len(weapons) > 2 and EMPTY(weapons[2]):
        return 2
    # Any further empty slot (extra attack slots)
    for i, w in enumerate(weapons):
        if EMPTY(w):
            return i
    return len(weapons)   # no free slot: append a new one


def create_monk_unarmed_weapon(app):
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


def create_alter_self_claws_weapon(app):
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


def bond_pact_weapon(app, weapons):
    """Pact of the Blade (invocation 13): make the main-hand weapon (slot 0) the pact weapon,
    in place. A real melee weapon there is bonded — it keeps its name and dice and gains
    pact_weapon=True (CHA attack/damage, Eldritch Smite, Lifedrinker). With no melee weapon
    there (empty "Unarmed" slot, Alter Self claws, a ranged weapon), the PactBlade is conjured
    into it instead. Returns True if `weapons` changed. Guarding on the flag (not just the
    name) app-heals legacy saves whose "PactBlade" lost pact_weapon=True on round-trip."""
    if not weapons or weapons[0].pact_weapon:
        return False
    w = weapons[0]
    if (not _weapon_slot_is_empty(w) and w.name != "AlterSelfClaws"
            and w.type == rpg.WeaponType.Melee):
        w.pact_weapon = True
    else:
        weapons[0] = create_pact_blade_weapon(app, )
    return True


def create_pact_blade_weapon(app):
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


def create_psychic_blade_weapon(app, die_size=6, off_hand=False):
    """Soulknife Psychic Blade — a Simple Melee finesse/thrown blade dealing die_size Psychic +
    the attack ability mod, with the Vex mastery. The bonus second blade uses a d4. psychic_blade
    identifies it for Homing Strikes / Rend Mind.

    Thrown at 60/120 ft, and it "vanishes after it hits or misses" — i.e. it comes right back
    (returns_after_throw), so throwing it never spends it or leaves it lying on the floor."""
    blade = rpg.Weapon()
    blade.name = "PsychicBlade"
    blade.type = rpg.WeaponType.Melee
    blade.proficient = True
    blade.finesse = True
    blade.thrown = True
    blade.returns_after_throw = True
    blade.psychic_blade = True
    blade.off_hand = off_hand
    blade.reach_ft = 5
    # The engine reads normal_range_ft/long_range_ft for range; range_short/long_feet are the
    # test-only convenience fields, so set both or a thrown blade would use the 80/320 defaults.
    blade.normal_range_ft = 60
    blade.long_range_ft = 120
    blade.range_short_feet = 60
    blade.range_long_feet = 120
    blade.mastery = rpg.WeaponMastery.Vex
    dmg_roll = rpg.MagicDamageRoll()
    dmg_roll.type = rpg.MagicDamage.Psychic
    dmg_roll.num_dice = 1
    dmg_roll.die_size = die_size
    dmg_roll.bonus = 0
    blade.magic_damage_types = [dmg_roll]
    return blade


def apply_psychic_blades(app, stats, weapons):
    """Soulknife Rogue (L3+): ensure slots 0/1 hold Psychic Blades (1d6 main + 1d4 off-hand).

    Pure mutator on the passed weapons list — returns (weapons, changed). Callers that get
    a True must persist the list AND set has_offhand_attack. Mirrors the Pact-of-the-Blade
    re-conjure so the blades survive save/load and a Weapon-dialog round-trip (the synthetic
    blade isn't in weapons.json, so the dialog would otherwise overwrite it)."""
    if (stats.character_class == rpg.CharacterClass.Rogue and
            stats.rogue_subclass == rpg.RogueSubclass.Soulknife and
            stats.char_level >= 3 and
            len(weapons) >= 2 and weapons[0].name != "PsychicBlade"):
        weapons[0] = create_psychic_blade_weapon(app, die_size=6, off_hand=False)
        weapons[1] = create_psychic_blade_weapon(app, die_size=4, off_hand=True)
        return weapons, True
    return weapons, False


def sync_item_spells(app, agent_idx: int):
    """Rebuild one creature's item-granted spells from what it carries now; per-index spell
    metadata follows the entries that moved. Call after anything that changes its items,
    weapons, worn armor or attunement."""
    if not hasattr(app, "_spell_catalog") or len(app._spell_catalog) != len(app.all_spells):
        app._spell_catalog = {d.get("name"): d for d in app.all_spells}
    moved = helpers.sync_item_spells(app.combat, app.bm, agent_idx, app._spell_catalog)
    if moved is None:
        return
    old = {j: m for (a, j), m in app._spell_metadata.items() if a == agent_idx}
    for j in old:
        del app._spell_metadata[(agent_idx, j)]
    spells = app.combat.get_agent_spells(app.bm, agent_idx)
    for new_j, old_j in enumerate(moved):
        if old_j is not None:
            if old_j in old:
                app._spell_metadata[(agent_idx, new_j)] = old[old_j]
            continue
        d = app._spell_catalog.get(spells[new_j].name, {})
        app._spell_metadata[(agent_idx, new_j)] = {
            "terrain_effect": d.get("terrain_effect"),
            "hatch_pattern": d.get("hatch_pattern"),
            "terrain_color": d.get("terrain_color"),
            "level": d.get("level", 0),
            "upcast_dice_bonus": d.get("upcast_dice_bonus", 0),
        }


def sync_all_item_spells(app):
    for i in range(len(app.bm.placed_agents)):
        app._sync_item_spells(i)


def grant_class_features(app, agent_idx: int, cpp_spells: list):
    """Append always-prepared class features (Channel Divinity options, etc.) from
    classfeatures.json that match this agent's class and level, baking scaling dice
    from level. Mutates and returns cpp_spells; skips any already present by name."""
    if not app.all_class_features:
        return cpp_spells
    stats = app.combat.get_agent_stats(app.bm, agent_idx)
    class_name = stats.character_class.name
    level = stats.char_level
    existing = {sp.name for sp in cpp_spells}
    for feat in app.all_class_features:
        if feat.get("class") != class_name:
            continue
        if level < int(feat.get("min_level", 1)):
            continue
        # Subclass-gated features (e.g. Radiance of the Dawn, Nature's Wrath) only for the matching
        # subclass. Map each class to the Stats attribute that names its chosen subclass.
        sub = feat.get("subclass")
        if sub:
            agent_sub = {
                "Cleric": stats.cleric_subclass.name,
                "Paladin": stats.paladin_oath.name,
            }.get(class_name)
            if agent_sub != sub:
                continue
        name = feat.get("name")
        if name in existing:
            continue
        sp = _dict_to_spell(feat)
        apply_feature_scaling(app, sp, feat, level, stats)
        cpp_spells.append(sp)
        existing.add(name)

    # Always-prepared divine domain spells (regular spells from spells.json).
    if class_name == "Cleric":
        domain_table = app._DOMAIN_SPELLS.get(stats.cleric_subclass.name, {})
        for min_lvl, names in domain_table.items():
            if level < min_lvl:
                continue
            for name in names:
                if name in existing:
                    continue
                idx = app.spell_name_to_idx.get(name)
                if idx is None:
                    continue  # not in spells.json — skip gracefully
                cpp_spells.append(_dict_to_spell(app.all_spells[idx]))
                existing.add(name)

    # Always-prepared Ranger subclass spells (regular spells from spells.json).
    if class_name == "Ranger":
        sub_table = app._RANGER_SUBCLASS_SPELLS.get(stats.ranger_subclass.name, {})
        for min_lvl, names in sub_table.items():
            if level < min_lvl:
                continue
            for name in names:
                if name in existing:
                    continue
                idx = app.spell_name_to_idx.get(name)
                if idx is None:
                    continue  # not in spells.json — skip gracefully
                cpp_spells.append(_dict_to_spell(app.all_spells[idx]))
                existing.add(name)

    # Always-prepared Bard college spells (regular spells from spells.json). Glamour L6 has
    # Command always prepared (cast for free via Mantle of Majesty).
    if class_name == "Bard":
        sub_table = app._BARD_SUBCLASS_SPELLS.get(stats.bard_subclass.name, {})
        for min_lvl, names in sub_table.items():
            if level < min_lvl:
                continue
            for name in names:
                if name in existing:
                    continue
                idx = app.spell_name_to_idx.get(name)
                if idx is None:
                    continue  # not in spells.json — skip gracefully
                cpp_spells.append(_dict_to_spell(app.all_spells[idx]))
                existing.add(name)

    # Sorcerer subclass always-prepared lists (Aberrant Mind Psionic Spells, Clockwork Soul
    # Clockwork Spells) — regular spells from spells.json, granted by subclass + level.
    if class_name == "Sorcerer":
        sub_table = app._SORCERER_SUBCLASS_SPELLS.get(stats.sorcerer_subclass.name, {})
        for min_lvl, names in sub_table.items():
            if level < min_lvl:
                continue
            for name in names:
                if name in existing:
                    continue
                idx = app.spell_name_to_idx.get(name)
                if idx is None:
                    continue  # not in spells.json — skip gracefully
                cpp_spells.append(_dict_to_spell(app.all_spells[idx]))
                existing.add(name)

    # Warlock patron always-prepared lists — regular spells from spells.json, granted by
    # subclass + Warlock level (2024 PHB). Uses WarlockSubclass.name as the key.
    if class_name == "Warlock":
        sub_table = app._WARLOCK_SUBCLASS_SPELLS.get(stats.warlock_subclass.name, {})
        for min_lvl, names in sub_table.items():
            if level < min_lvl:
                continue
            for name in names:
                if name in existing:
                    continue
                idx = app.spell_name_to_idx.get(name)
                if idx is None:
                    continue  # not in spells.json — skip gracefully
                cpp_spells.append(_dict_to_spell(app.all_spells[idx]))
                existing.add(name)

    # Paladin oath always-prepared spells — regular spells from spells.json, granted by
    # oath + Paladin level (2024 PHB). Uses PaladinOath.name as the key. Pure-utility oath
    # spells (e.g. Scrying, Commune with Nature) are intentionally omitted — see known_limitations.
    if class_name == "Paladin":
        sub_table = app._PALADIN_OATH_SPELLS.get(stats.paladin_oath.name, {})
        for min_lvl, names in sub_table.items():
            if level < min_lvl:
                continue
            for name in names:
                if name in existing:
                    continue
                idx = app.spell_name_to_idx.get(name)
                if idx is None:
                    continue  # not in spells.json — skip gracefully
                cpp_spells.append(_dict_to_spell(app.all_spells[idx]))
                existing.add(name)
    return cpp_spells


def apply_feature_scaling(app, sp, feat: dict, level: int, stats):
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
