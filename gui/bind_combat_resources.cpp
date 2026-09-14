// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_resources.cpp  –  pybind11 bindings for CombatEngine (combat_resources.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Class/subclass resource activations (Rage, Lay on Hands, Channel Divinity, …) —
//  the file expected to grow fastest as new classes/subclasses are added.
//
//  Split out of rpg_bindings.cpp (COMBAT_REFACTOR_PLAN.md R1) — mechanical move only,
//  no binding behavior changed. See bindings_internal.hpp for the shared
//  py::class_<CombatEngine> handle each bind_* function adds .def()s to.
//
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>        // std::vector, std::unordered_set → Python list/set
#include <pybind11/functional.h> // std::function ↔ Python callable (NPC render-attack hook)

#include "battle_map.hpp"
#include "combat.hpp"
#include "combat_internal.hpp"   // footprintDistance — shared with the combat_*.cpp TUs
#include "map_configs.hpp"
#include "character_class.hpp"
#include "item.hpp"
#include "bindings_internal.hpp"

namespace py = pybind11;
using namespace rpg;

void bindCombatResources(py::class_<CombatEngine>& engine) {
    engine
        .def_static("heal_agent",
                    &CombatEngine::healAgent,
                    py::arg("battle_map"), py::arg("idx"), py::arg("amount"),
                    "Raise hp_cur of agent[idx] by amount (clamped to hp_max). "
                    "A downed creature healed above 0 HP returns to consciousness. "
                    "Returns new hp_cur.")
        .def_static("lay_on_hands",
                    &CombatEngine::layOnHands,
                    py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"), py::arg("amount"),
                    "Paladin Lay on Hands: spend from caster's pool to heal target. "
                    "Clamps spend to min(pool_remaining, target_hp_deficit). "
                    "Returns actual HP healed (0 if nothing to heal, -1 if invalid).")
        .def("apply_one_with_shadows",
             &CombatEngine::applyOneWithShadows,
             py::arg("battle_map"), py::arg("idx"),
             "One with Shadows (Warlock invocation 8): if standing in Dim Light/Darkness,\n"
             "gain the Invisible condition for free (ends on the Warlock's next attack/cast).\n"
             "Returns True if applied.")
        .def("apply_merge_with_shadows",
             &CombatEngine::applyMergeWithShadows,
             py::arg("battle_map"), py::arg("idx"),
             "Merge with Shadows (Boon of the Night Spirit): if standing in Dim Light/Darkness,\n"
             "gain the Invisible condition as a Bonus Action (ends when you next act).\n"
             "Returns True if applied.")
        .def("activate_sacred_weapon",
             &CombatEngine::activateSacredWeapon,
             py::arg("battle_map"), py::arg("idx"),
             "Paladin Oath of Devotion — Sacred Weapon: spend 1 Channel Oath use to add\n"
             "+CHA mod (min +1) to weapon attack rolls for 1 minute (10 rounds). Requires\n"
             "Oath of Devotion and an available Channel Oath use. Returns the bonus granted,\n"
             "or -1 if it could not be activated.")
        .def("activate_vow_of_enmity",
             &CombatEngine::activateVowOfEnmity,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_idx"),
             "Paladin Oath of Vengeance — Vow of Enmity: spend 1 Channel Oath use to swear\n"
             "enmity against a visible enemy within 30 ft, gaining Advantage on attacks against\n"
             "it for 1 minute (or until used again). The vow auto-transfers to the nearest enemy\n"
             "within 30 ft if the target dies. Returns True on success, False if not eligible.")
        .def("activate_avenging_angel",
             &CombatEngine::activateAvengingAngel,
             py::arg("battle_map"), py::arg("idx"),
             "Paladin Oath of Vengeance — Avenging Angel (L20): Bonus Action, 10 minutes. Grants\n"
             "Fly 60 ft (hover) and a Frightful Aura in the Aura of Protection. Costs one Avenging\n"
             "Angel use per long rest, or a level-5 spell slot when exhausted. Returns True on success.")
        .def("activate_elder_champion",
             &CombatEngine::activateElderChampion,
             py::arg("battle_map"), py::arg("idx"),
             "Paladin Oath of the Ancients — Elder Champion (L20): Bonus Action, 1 minute. Regain 10 HP\n"
             "each turn start and enemies in your Aura of Protection have Disadvantage on saves vs your\n"
             "spells/Channel Oath. Costs one use per long rest, or a level-5 slot. Returns True on success.")
        .def("activate_inspiring_smite",
             &CombatEngine::activateInspiringSmite,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_idx"),
             "Paladin Oath of Glory — Inspiring Smite (L3): immediately after a Divine Smite this turn,\n"
             "spend one Channel Oath use to grant a creature within 30 ft (may be self) 2d8 + Paladin\n"
             "level temporary HP. Once per turn. Returns the temp HP granted, or -1 if not allowed.")
        .def("activate_living_legend",
             &CombatEngine::activateLivingLegend,
             py::arg("battle_map"), py::arg("idx"),
             "Paladin Oath of Glory — Living Legend (L20): Bonus Action, 10 minutes. Grants a save-reroll\n"
             "reaction and once-per-turn Unerring Strike (weapon miss→hit). Costs one use per long rest,\n"
             "or a level-5 spell slot when exhausted. Returns True on success.")
        .def("activate_corona_of_light",
             &CombatEngine::activateCoronaOfLight,
             py::arg("battle_map"), py::arg("idx"),
             "Cleric Light Domain — Corona of Light (L17+): Magic action that, for 1 minute (10 rounds),\n"
             "gives enemies within 60 ft Disadvantage on saves vs this caster's Fire/Radiant spells.\n"
             "Returns True if activated, False if not eligible (wrong class/domain/level).")
        .def("activate_innate_sorcery",
             &CombatEngine::activateInnateSorcery,
             py::arg("battle_map"), py::arg("idx"),
             "Sorcerer Innate Sorcery (L1): Bonus Action, spend 1 use to gain +1 spell save\n"
             "DC and advantage on spell attack rolls for 1 minute (10 rounds). Sorcery Incarnate\n"
             "(L7): with no uses left, 2 Sorcery Points activate it instead. Returns True if\n"
             "activated, False otherwise (not a Sorcerer, or no use / no 2 SP fallback).")
        .def_static("sorcery_incarnate_active",
                    &CombatEngine::sorceryIncarnateActive,
                    py::arg("stats"),
                    "Sorcery Incarnate (Sorcerer L7): True while a level-7+ Sorcerer has Innate\n"
                    "Sorcery running. While it is, a cast may carry TWO Metamagic options\n"
                    "(SpellAction.metamagic + .metamagic2).")
        .def("activate_dragon_wings",
             &CombatEngine::activateDragonWings,
             py::arg("battle_map"), py::arg("idx"),
             "Draconic L14 Dragon Wings: toggle fly speed = walk speed (no concentration).\n"
             "First call extends wings (dragon_wings_active=True, speed_fly=speed_walk).\n"
             "Second call retracts them (dragon_wings_active=False, speed_fly=0).\n"
             "Returns True if the agent is a Draconic Sorcerer L14+, False otherwise.")
        .def("activate_draconic_resistance",
             &CombatEngine::activateDraconicResistance,
             py::arg("battle_map"), py::arg("idx"),
             "Draconic L6 Elemental Affinity — Resistance: spend 1 SP to gain resistance\n"
             "(0.5x multiplier) to the chosen element for 1 hour (600 rounds).\n"
             "Returns True if activated, False if gating fails (wrong class/subclass/level,\n"
             "affinity_type unset, resistance already active, or insufficient SP).")
        .def("activate_trance_of_order",
             &CombatEngine::activateTranceOfOrder,
             py::arg("battle_map"), py::arg("idx"),
             "Trance of Order (Clockwork Sorcerer L14+, Bonus Action): for 1 minute attacks against\n"
             "you can't benefit from Advantage and you treat your own d20 of 9-or-lower as a 10 on\n"
             "D20 Tests. Free 1/long rest (the 'Trance of Order' Resource), else 5 Sorcery Points.\n"
             "Sets trance_of_order_turns=10 and spends the bonus action. Returns True if used.")
        .def("activate_bastion_of_law",
             &CombatEngine::activateBastionOfLaw,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"), py::arg("sp"),
             "Bastion of Law (Clockwork Sorcerer L6+, Magic Action): spend 1-5 Sorcery Points to ward\n"
             "the caster or a creature within 30 ft with a pre-rolled (sp)d8 damage-absorption pool\n"
             "(Stats.bastion_ward), overwriting any prior ward. Returns the ward total rolled, or -1\n"
             "on failure (gating / range / not enough Sorcery Points).")
        .def("clockwork_cavalcade",
             &CombatEngine::clockworkCavalcade,
             py::arg("battle_map"), py::arg("caster_idx"),
             "Clockwork Cavalcade (Clockwork Sorcerer L18+, Magic Action): the caster and each ally\n"
             "within 30 ft regain 100 HP and have their active spell conditions ended. Free 1/long\n"
             "rest (the 'Clockwork Cavalcade' Resource), else 7 Sorcery Points. Returns the number of\n"
             "creatures affected, or -1 on failure.")
        .def("activate_revelation_in_flesh",
             &CombatEngine::activateRevelationInFlesh,
             py::arg("battle_map"), py::arg("idx"),
             "Revelation in Flesh (Aberrant Mind Sorcerer L14+, Bonus Action): spend 1 Sorcery Point to\n"
             "transform for 10 minutes (100 rounds) — fly+hover (speed_fly=walk), swim (speed_swim=walk),\n"
             "and truesight 60 ft (see Invisible). Prior speeds/truesight are restored on expiry / long\n"
             "rest. Returns True if activated (False if gated, already active, or no Sorcery Point).")
        .def("warping_implosion",
             &CombatEngine::warpingImplosion,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("dest_col"), py::arg("dest_row"),
             "Warping Implosion (Aberrant Mind Sorcerer L18+): teleport the caster to (dest_col,dest_row)\n"
             "within 120 ft, then every OTHER creature within 30 ft of the space it left makes a DEX save\n"
             "vs the caster's spell DC, taking 3d10 Force (half on a success). Free 1/long rest (the\n"
             "'Warping Implosion' Resource), else 5 Sorcery Points. Returns the number of creatures\n"
             "damaged, or -1 on failure (gating / range / blocked dest / no use & < 5 SP).")
        .def_static("get_rage_damage_bonus",
                    &CombatEngine::getRageDamageBonus,
                    py::arg("level"),
                    "Get Barbarian Rage damage bonus for a given level.")
        .def("spend_luck_for_advantage",
             &CombatEngine::spendLuckForAdvantage,
             py::arg("battle_map"), py::arg("idx"),
             "Lucky feat: spend one Luck Point to grant the agent Advantage on its next d20\n"
             "Test (consumed by the next d20 roll). Returns False if no points remain.")
        .def("tick_terrain_for_turn",
             &CombatEngine::tickTerrainForTurn,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Tick the agent's terrain at start of turn; clears concentration if a concentration terrain expired.\n"
             "Returns TerrainTickResult(expired_terrain_ids, concentration).")
        .def("tick_light_effects_for_turn",
             &CombatEngine::tickLightEffectsForTurn,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Phase 3: Tick light effects (Darkness, fog spells) at turn start. Expires effects and re-evaluates blinding.")
        .def("use_magical_cunning",
             &CombatEngine::useMagicalCunning,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Warlock Magical Cunning: recover expended Pact Magic slots (ceil(max/2), or all at L20).\n"
             "Returns True if used; False if unavailable or nothing to recover.")
        .def("use_healing_light",
             &CombatEngine::useHealingLight,
             py::arg("battle_map"), py::arg("healer_idx"), py::arg("target_idx"), py::arg("num_dice"),
             "Celestial Warlock Healing Light (L3+): spend d6 healing dice.\n"
             "Validates healer is Celestial L3+, clamps num_dice to min(num_dice, current, chaMod).\n"
             "Spends dice from resource, rolls that many d6, heals target.\n"
             "Returns HP healed (0 if invalid).")
        .def("spend_resource",
             &CombatEngine::spendResource,
             py::arg("battle_map"), py::arg("idx"), py::arg("name"), py::arg("amount") = 1,
             "Spend a named class resource (e.g. 'War Priest', 'Superiority Dice'); returns True if\n"
             "the agent had >= amount and it was spent. Generic cost helper for extra-attack/maneuver\n"
             "features (the attack itself goes through execute_action).")
        .def("use_turn_undead",
             &CombatEngine::useTurnUndead,
             py::arg("battle_map"), py::arg("caster_idx"),
             "Cleric Turn Undead (Channel Divinity, L2+): each Undead within 30 ft makes a WIS save;\n"
             "failures are Frightened + Incapacitated for 1 minute (ends if the undead takes damage).\n"
             "Sear Undead (L5+) deals WIS-mod d8 Radiant (rolled once) to each failed undead.\n"
             "Spends one Channel Divinity use. Returns a TurnUndeadResult.")
        .def("use_preserve_life",
             &CombatEngine::usePreserveLife,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("targets"),
             "Life Domain Preserve Life (Channel Divinity, L3+): distribute 5 x cleric level HP among\n"
             "the chosen creatures within 30 ft (list order = distribution priority), each restored to\n"
             "no more than half its HP maximum. Undead cannot be healed. Supreme Healing does not affect\n"
             "this (no dice). Spends one Channel Divinity use. Returns a PreserveLifeResult.")
        .def("activate_rage",
             &CombatEngine::activateRage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Activate Barbarian Rage: set raging=true, apply 0.5x physical damage multipliers (B/P/S), spend 1 Rage use.")
        .def("extend_rage",
             &CombatEngine::extendRage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Extend active Rage: reset duration_remaining to full duration.")
        .def("end_rage",
             &CombatEngine::endRage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "End Barbarian Rage: set raging=false, restore normal damage multipliers, clear reckless_attack.")
        .def("use_intimidating_presence",
             &CombatEngine::useIntimidatingPresence,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Barbarian Path of the Berserker L14 — Intimidating Presence (Bonus Action):\n"
             "Each creature of the Barbarian's choice within a 30-ft emanation makes a WIS save\n"
             "(DC 8 + STR mod + PB) or is Frightened until the end of the Barbarian's next turn.\n"
             "Usable PB times per long rest, or expend one Rage use. Spends a bonus action.")
        .def("activate_clairvoyant_combatant",
             &CombatEngine::activateClairvoyantCombatant,
             py::arg("battle_map"), py::arg("warlock_idx"), py::arg("target_idx"),
             "Great Old One Warlock L6 — Clairvoyant Combatant (Bonus Action):\n"
             "Make telepathic contact with one creature you can see within 60 ft, forcing a WIS save\n"
             "(DC 8 + CHA mod + PB). On a failure you have Advantage on attack rolls against it and it\n"
             "has Disadvantage on attack rolls against you, until the start of your next turn. Once per\n"
             "short or long rest, or spend a Pact Magic slot to reuse it. Spends a bonus action.\n"
             "Returns True if it activated.")
        .def("use_zealous_presence",
             &CombatEngine::useZealousPresence,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Barbarian Path of the Zealot L10 — Zealous Presence (Bonus Action):\n"
             "Up to 10 creatures of the Barbarian's choice (allies) within 60 ft gain Advantage on\n"
             "attack rolls and saving throws until the start of the Barbarian's next turn.\n"
             "Usable 1 time per long rest, or expend one Rage use. Spends a bonus action.")
        .def("activate_rage_of_the_gods",
             &CombatEngine::activateRageOfTheGods,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Barbarian Path of the Zealot L14 — Rage of the Gods: while raging, assume a divine-warrior\n"
             "form (once per long rest). Grants Fly Speed = Speed (can hover) and Resistance to Necrotic/\n"
             "Psychic/Radiant; enables the Revivification reaction. Ends when Rage ends or at 0 HP.\n"
             "Returns False if not a raging Zealot L14+, or the form was already used this long rest.")
        .def("travel_along_tree",
             &CombatEngine::travelAlongTree,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("target_col"), py::arg("target_row"),
             py::arg("long_range") = false,
             "Barbarian Path of the World Tree L14 — Travel along the Tree (Bonus Action while raging):\n"
             "teleport up to 60 ft (or up to 150 ft once per Rage when long_range=True) to a visible,\n"
             "unoccupied space. Spends a bonus action. Returns False if illegal (out of range, occupied,\n"
             "long-range already used this Rage, not a raging World Tree L14+, or no bonus action).")
        .def("apply_retaliation",
             &CombatEngine::applyRetaliation,
             py::arg("battle_map"), py::arg("defender_idx"),
             "Barbarian Path of the Berserker L10 — Retaliation: spend the reaction to make one melee\n"
             "weapon attack back at the creature that just damaged this Barbarian from within 5 ft\n"
             "(flagged via conditions.retaliation_available / retaliation_target_idx). Returns the\n"
             "AttackResult (default/empty if not eligible).")
        .def("psychic_teleportation",
             &CombatEngine::psychicTeleportation,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             "Soulknife Soul Blades — Psychic Teleportation (L9): spend 1 Psionic Energy Die, roll it, and\n"
             "teleport up to (10 × roll) ft. Returns True on a successful (in-range, legal) teleport.")
        .def("activate_psychic_veil",
             &CombatEngine::activatePsychicVeil,
             py::arg("battle_map"), py::arg("idx"),
             "Soulknife Psychic Veil (L13): Magic action → Invisible. Once/Long Rest or by 1 Psionic Energy Die.")
        .def("shadow_step_teleport",
             &CombatEngine::shadowStepTeleport,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             "Warrior of Shadow Shadow Step (L6+): Bonus Action teleport up to 30 ft in dim/dark (L6) or\n"
             "any light (L11+). Sets Advantage on next attack. Returns True iff teleport succeeds.")
        .def("steps_of_the_fey",
             &CombatEngine::stepsOfTheFey,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             py::arg("effect"), py::arg("as_reaction") = false,
             "Archfey Warlock Steps of the Fey (L3+): Bonus-Action Misty Step (30 ft) with no slot,\n"
             "spending one 'Steps of the Fey' use. effect: 0 None, 1 Refreshing (self 1d10 temp HP),\n"
             "2 Taunting (WIS save near departure or Disadvantage attacking anyone but the warlock),\n"
             "3 Disappearing (L6+, self Invisible), 4 Dreadful (L6+, 2d10 psychic near departure on a\n"
             "failed WIS save). Pass as_reaction=True for Misty Escape (L6+): spend the Reaction instead\n"
             "of a Bonus Action in response to taking damage. Returns True iff the teleport happens.")
        .def("bewitching_misty_step",
             &CombatEngine::bewitchingMistyStep,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             py::arg("effect"),
             "Archfey Warlock Bewitching Magic (L14+): a free Misty Step (30 ft, no slot/use/action)\n"
             "cast right after an Enchantment/Illusion action-cast. effect matches steps_of_the_fey\n"
             "(0 None, 1 Refreshing, 2 Taunting, 3 Disappearing, 4 Dreadful). The GUI enforces the\n"
             "'just cast Enchantment/Illusion' timing. Returns True iff the teleport happens.")
        .def("cloak_of_shadows",
             &CombatEngine::cloakOfShadows,
             py::arg("battle_map"), py::arg("idx"),
             "Warrior of Shadow Cloak of Shadows (L17): Bonus Action → Invisible in dim/dark. Persists\n"
             "through attacks. Expires on turn start if in bright light. Returns True iff activated.")
        .def("move_duplicate",
             &CombatEngine::moveDuplicate,
             py::arg("battle_map"), py::arg("cleric_idx"), py::arg("dup_idx"),
             py::arg("target_col"), py::arg("target_row"),
             "Trickery Cleric Invoke Duplicity: move the illusory duplicate up to 30 ft. Returns True iff moved.")
        .def("swap_with_duplicate",
             &CombatEngine::swapWithDuplicate,
             py::arg("battle_map"), py::arg("cleric_idx"), py::arg("dup_idx"),
             "Trickster's Transposition (L6+): swap the cleric's position with their duplicate. Returns True iff swapped.")
        .def("shadow_arts_darkness",
             &CombatEngine::shadowArtsDarkness,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             "Warrior of Shadow Shadow Arts: Darkness (L3): spend 1 Focus Point to fill a 15-ft-radius\n"
             "Sphere with magical Darkness (1 min). The caster sees through their own Darkness (not\n"
             "Blinded); others inside without Devil's Sight are Blinded. Returns the light-effect id (>=0),\n"
             "or -1 on failure.")
        .def("activate_elemental_attunement",
             &CombatEngine::activateElementalAttunement,
             py::arg("battle_map"), py::arg("idx"), py::arg("element"),
             "Warrior of the Elements Elemental Attunement (L3): Magic action + 1 Focus Point. `element` is\n"
             "a MagicDamage_t (Acid=0/Cold=1/Fire=2/Lightning=4/Thunder=9). Until a short/long rest the Monk's\n"
             "unarmed strikes gain +10 ft reach, deal the chosen element, and can push/pull 10 ft on a hit.\n"
             "Returns True on success.")
        .def("elemental_attunement_move",
             &CombatEngine::elementalAttunementMove,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("pull"),
             "Elemental Attunement push/pull rider: on an unarmed hit while attunement is active, push the\n"
             "target 10 ft away (pull=False) or pull it 10 ft toward the Monk (pull=True). No save. Returns\n"
             "the feet actually moved.")
        .def("elemental_burst",
             &CombatEngine::elementalBurst,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"), py::arg("element"),
             "Warrior of the Elements Elemental Burst (L6): Magic action + 2 Focus Points → a 20-ft-radius\n"
             "Sphere of the chosen element (a MagicDamage_t). Each non-ally creature in the area makes a DEX\n"
             "save vs the Monk's Ki DC (8 + PB + WIS); failure = (Martial Arts die count) × d8, half on a\n"
             "save. Returns True on success.")
        .def("plant_quivering_palm",
             &CombatEngine::plantQuiveringPalm,
             py::arg("battle_map"), py::arg("monk_idx"), py::arg("target_idx"),
             "Monk Way of the Open Hand L17 — Quivering Palm. After an Unarmed Strike hit\n"
             "(conditions.quivering_palm_available), spend 4 Focus Points to plant a delayed-trigger\n"
             "condition on the target (10d12 Force, CON save vs Ki DC for half). Only one creature may\n"
             "be affected at a time. Detonate later with trigger_delayed_effect. Returns True on success.")
        .def("activate_mantle_of_majesty",
             &CombatEngine::activateMantleOfMajesty,
             py::arg("battle_map"), py::arg("bard_idx"),
             "College of Glamour Mantle of Majesty (Bonus Action): spend the once/long-rest 'Mantle of\n"
             "Majesty' use, open a 1-minute (10-round) unearthly-appearance window (stats.mantle_majesty_turns\n"
             "= 10) and start Concentration on 'Mantle of Majesty' (replacing any prior concentration).\n"
             "While active the bard may re-cast Command as a Bonus Action with no slot (SpellAction.free_cast),\n"
             "and a creature Charmed by this bard auto-fails its save vs that Command. The free Command cast\n"
             "is driven separately by the caller. Returns False if not a Glamour Bard L6+ or no use left.")
        .def("bard_restore_mantle_of_majesty_from_slot",
             &CombatEngine::bardRestoreMantleOfMajestyFromSlot,
             py::arg("battle_map"), py::arg("bard_idx"), py::arg("slot_level"),
             "Restore the expended Mantle of Majesty use by spending an unused level 3+ spell slot (no\n"
             "action). Returns the resource's new current count, or -1 (not a Glamour Bard L6+, slot_level\n"
             "< 3, no such slot, or already full).")
        .def("activate_unbreakable_majesty",
             &CombatEngine::activateUnbreakableMajesty,
             py::arg("battle_map"), py::arg("bard_idx"),
             "College of Glamour Unbreakable Majesty (Bonus Action, Bard L14+): spend the once/long-rest\n"
             "'Unbreakable Majesty' use, open a 1-minute (10-round) majestic-presence window\n"
             "(stats.majestic_presence_turns = 10) and start Concentration on 'Unbreakable Majesty'\n"
             "(replacing any prior concentration). While active any melee attack against the bard triggers\n"
             "Psychic damage equal to the bard's CHA modifier (min 1) and forces a CHA save vs the bard's\n"
             "spell save DC; on a failure the attacker gains Disadvantage on the next save vs the bard's\n"
             "spells (TODO: full rider). The Psychic damage is applied automatically (no reaction).\n"
             "Returns False if not a Glamour Bard L14+ or no use left.")
        .def("bard_restore_unbreakable_majesty_from_slot",
             &CombatEngine::bardRestoreUnbreakableMajestyFromSlot,
             py::arg("battle_map"), py::arg("bard_idx"), py::arg("slot_level"),
             "Restore the expended Unbreakable Majesty use by spending an unused level 3+ spell slot (no\n"
             "action). Returns the resource's new current count, or -1 (not a Glamour Bard L14+, slot_level\n"
             "< 3, no such slot, or already full).")
        .def("bard_beguiling_magic",
             &CombatEngine::bardBeguilingMagic,
             py::arg("battle_map"), py::arg("bard_idx"), py::arg("target_idx"), py::arg("use_frightened"),
             "College of Glamour Beguiling Magic (Bard L3+): fire the once/long-rest benefit after the\n"
             "bard casts an Enchantment/Illusion spell with a slot (the caller gates school/slot). Spends\n"
             "the 'Beguiling Magic' resource, then forces a WIS save (vs the bard's spell save DC) on the\n"
             "target within 60 ft; on a failure the target is Charmed (use_frightened=False) or Frightened\n"
             "(True) for 1 minute, repeating the save each of its turns. Returns True if used (resource\n"
             "spent), False if it could not be used (not a L3+ Glamour Bard, no use, bad/out-of-range target).")
        .def("bard_restore_beguiling_magic",
             &CombatEngine::bardRestoreBeguilingMagic,
             py::arg("battle_map"), py::arg("bard_idx"),
             "Restore the expended Beguiling Magic use by spending one Bardic Inspiration use (no action).\n"
             "Returns the resource's new current count, or -1 (not a Glamour Bard L3+, no Bardic Inspiration\n"
             "use, or already full).")
        .def("has_bonus_action",
             &CombatEngine::hasBonusAction,
             py::arg("battle_map"), py::arg("agent_idx"),
             "True if the agent still has a bonus action this turn (bonus_actions_remaining > 0).\n"
             "Gate every Bonus Action feature (off-hand attack, Cunning Action, Rage, Healing\n"
             "Word, Divine Smite, etc.) on this before offering it.")
        .def("spend_bonus_action",
             &CombatEngine::spendBonusAction,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Spend one bonus action if available; returns true if spent, false if none remained.")
        .def("reset_bonus_actions",
             &CombatEngine::resetBonusActions,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Refill bonus_actions_remaining = bonus_actions_max (done automatically each turn).")
        .def("can_use_primal_knowledge",
             &CombatEngine::canUsePrimalKnowledge,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("skill_name"),
             "Check if Barbarian can use STR for a skill (Acrobatics/Stealth) while Raging.\n"
             "Returns true if: L3+ Barbarian, Raging, and skill is Acrobatics or Stealth.")
        .def("use_portent_die",
             &CombatEngine::usePortentDie,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("die_index"), py::arg("current_round"),
             "Use a Portent Die on the next roll (for Diviner Wizards).\n"
             "Validates agent is Diviner, has dice, not used this round.\n"
             "Sets pending_portent_die for CombatEngine::roll() to return.\n"
             "Decrements Portent Dice resource.\n"
             "die_index: 0-based index into agent's portent_dice deque.\n"
             "current_round: for per-round enforcement.\n"
             "Returns true on success, false on validation failure.")
        .def("regenerate_portent_dice",
             &CombatEngine::regeneratePortentDice,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Regenerate Portent Dice pool after long rest (for Diviner Wizards).\n"
             "Rolls new d20s and populates agent's portent_dice deque.")
        .def("grant_bardic_die",
             &CombatEngine::grantBardicDie,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("d") = 8,
             "Grant a Bardic Inspiration die of size d (6/8/10/12) to a creature.\n"
             "Overwrites any die it already holds (one at a time, per RAW).\n"
             "Returns true on success, false if the agent index is invalid.")
        .def("use_bardic_die",
             &CombatEngine::useBardicDie,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Spend the held Bardic Inspiration die: rolls it, folds the result into the\n"
             "agent's NEXT d20 Test (roll / roll_advantage / roll_disadvantage / roll_to_hit),\n"
             "then clears the held die. Returns the rolled value (0 if none held).")
        .def("use_bardic_die_for_damage",
             &CombatEngine::useBardicDieForDamage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Combat Inspiration damage mode (Valor Bard L3+, any held die): rolls the held\n"
             "Bardic Inspiration die and folds it into pending_damage_bonus_ so the NEXT\n"
             "weapon damage roll adds it, then clears the held die. Returns the rolled value\n"
             "(0 if no die held).")
        .def("bard_regain_inspiration_from_slot",
             &CombatEngine::bardRegainInspirationFromSlot,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("slot_level"),
             "Font of Inspiration (Bard L5+): expend a spell slot of slot_level to regain\n"
             "one use of Bardic Inspiration. Returns the new count, or -1 on failure\n"
             "(not a L5+ Bard, no such slot, or already at max).")
        .def("apply_superior_inspiration",
             &CombatEngine::applySuperiorInspiration,
             py::arg("battle_map"),
             "Superior Inspiration (Bard L18+): every qualifying Bard regains Bardic\n"
             "Inspiration up to 2 if it has fewer. RNG-free; call once at combat start.")
        .def("bard_cutting_words",
             &CombatEngine::bardCuttingWords,
             py::arg("battle_map"), py::arg("bard_idx"),
             "Cutting Words (College of Lore, L3+): reaction that expends one Bardic\n"
             "Inspiration use to SUBTRACT the die from the next D20 Test (the target's roll).\n"
             "Returns the amount subtracted, or 0 on failure.")
        .def("apply_long_rest",
             &CombatEngine::applyLongRest,
             py::arg("battle_map"),
             "Apply long rest to all agents: restore spell slots, resources,\n"
             "and regenerate Portent Dice for Diviner Wizards.")
        .def("apply_short_rest",
             &CombatEngine::applyShortRest,
             py::arg("battle_map"),
             "Apply short rest to all agents: restore short-rest resources\n"
             "(Warlock Pact Magic slots, Monk Ki, etc.).")
        .def("use_item",
             &CombatEngine::useItem,
             py::arg("battle_map"), py::arg("user_idx"), py::arg("item_slot"), py::arg("target_idx"),
             "Use the carried item in inventory slot item_slot on target_idx (may be user_idx itself).\n"
             "Enforces the item's range (0 = self only), that the user can act, and its action cost\n"
             "(a BonusAction item spends the user's Bonus Action). A Heal item rolls its dice and heals\n"
             "through heal_agent, so a potion given to a downed ally revives it. Spends one charge and\n"
             "drops the row when the last one is used. Returns a UseItemResult (valid=False = nothing\n"
             "happened and nothing was spent).\n"
             "A Thrown item (Acid, Alchemist's Fire, Holy Water, Net) instead makes the target roll a\n"
             "DEX save vs 8 + the thrower's DEX modifier + PB; on a failure it deals its damage and/or\n"
             "applies its condition. The flask is spent whether or not the target saves, and the caller\n"
             "pays for it out of the Attack action (action_type == AttackReplacement).")
        .def("activate_wild_shape", &CombatEngine::activateWildShape,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("beast_name"), py::arg("weapons"), py::arg("beast_forms_path") = "",
             "Activate Druid Wild Shape: spend 1 use, swap to beast form stats, grant Temp HP.\n"
             "For Circle of the Moon: Temp HP = 3×level, AC = max(beast_ac, 13+WIS).\n"
             "For other circles: Temp HP = 1×level, AC = beast_ac.\n"
             "weapons: list of Weapon objects for the beast form (padded to >=3 internally).\n"
             "Optional beast_forms_path: if provided, use this path to load beast_forms.json; otherwise try standard locations.")
        .def("deactivate_wild_shape", &CombatEngine::deactivateWildShape,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Deactivate Druid Wild Shape: restore original AC, STR, DEX, CON, and weapons.")
        .def("activate_starry_form", &CombatEngine::activateStarryForm,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("constellation"),
             "Activate Druid Starry Form (Circle of the Stars): spend 1 Wild Shape use.\n"
             "constellation: 1=Archer, 2=Chalice, 3=Dragon.\n"
             "Dragon at L10+: add fly speed. L14+: add B/P/S resistance.")
        .def("deactivate_starry_form", &CombatEngine::deactivateStarryForm,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Deactivate Druid Starry Form: restore fly speed and resistances.")
        .def("activate_wrath_of_sea", &CombatEngine::activateWrathOfSea,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Activate Druid Wrath of the Sea (Circle of the Sea): spend 1 Wild Shape use.\n"
             "At L10+: add fly speed and resistances to Cold/Lightning/Thunder.")
        .def("deactivate_wrath_of_sea", &CombatEngine::deactivateWrathOfSea,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Deactivate Druid Wrath of the Sea: restore fly speed and resistances.")
        .def("apply_dragon_min_roll", &CombatEngine::applyDragonMinRoll,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("d20_roll"),
             "Apply Dragon Constellation min-roll-10 for CON concentration saves.\n"
             "Returns max(d20_roll, 10) if conditions met, else returns d20_roll unchanged.")
        ;
}
