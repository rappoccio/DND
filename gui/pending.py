"""The click pick in progress (APP_REFACTOR_PLAN.md D4, amended 2026-11-18: two slots).

An action that wants a creature or a place on the map arms a pick, and the next map click
(`App.resolve_pick`) or a player's submit (`net/picks.py`) resolves it. `app.pick` holds at
most one: a `Pick` naming the arm, or None when nothing is armed. It replaces the
one-flag-per-feature `pending_*` arms (`pending_shadow_step`, `pending_cleave`, …), which
were never armed two at a time (checked over the whole suite before the move).

The action being built underneath a pick (an attack, a spell, a shove, a summon) is the
other slot, `app.pending` (A2b, the dataclasses at the end of this file). A pick can sit on top of one: Chromatic Orb's leap chain
over its spell, Cleave over the next Extra Attack.

`data` is what the old field held while armed: True for a plain flag, the Cleave/Sweep info
dict, the Rally/Feint creature, the Elemental Burst element, the Use Item slot, the
legendary spell's or the lair's pick shape. `idle(kind)` is the value the old field rested
at, which `App._pick_data` returns while that kind is not armed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The kinds, with the field each replaces and what it awaits:
#   arcane_charge        arcane_charge_pending          Eldritch Knight L15: teleport after Action Surge
#   blink_steps          blink_steps_pending            Boon of Dimensional Travel: teleport (≤30 ft)
#   clouds_jaunt         (new, SP6)                     Goliath Cloud's Jaunt: teleport (≤30 ft)
#   psychic_teleport     pending_psychic_teleport       Soulknife L9: destination
#   shadow_step          pending_shadow_step            Warrior of Shadow L6+: destination
#   wild_magic_teleport  pending_wild_magic_teleport    Wild Magic Sorcerer: destination (20 ft)
#   warping_implosion    pending_warping_implosion      Aberrant L18: destination (120 ft)
#   shadow_darkness      pending_shadow_darkness        Warrior of Shadow L3: Darkness center cell
#   steps_of_fey         pending_steps_of_fey           Archfey L3+: destination (Bonus)
#   misty_wanderer       pending_misty_wanderer         Fey Wanderer L15: destination (Bonus)
#   misty_escape         pending_misty_escape           Archfey L6+: destination (Reaction)
#   bewitching_misty     pending_bewitching_misty       Archfey L14: free Misty Step destination
#   elemental_burst      pending_elemental_burst        Warrior of the Elements L6: center cell; data = element
#   invoke_duplicity     pending_invoke_duplicity       Trickery Cleric: a cell for a duplicate
#   move_duplicity       pending_move_duplicity         ...a duplicate's destination
#   swap_duplicity       pending_swap_duplicity         ...which duplicate to swap with
#   cleave               pending_cleave                 Cleave mastery: 2nd target; data = {"attacker","first","weapon","valid"}
#   sweep                pending_sweep                  Sweeping Attack: 2nd target; data = info dict
#   rally                pending_rally                  Rally: ally; data = the Battle Master
#   feint                pending_feint                  Feinting Attack: target; data = the Battle Master
#   mantle               pending_mantle_active          Mantle of Inspiration: recipients, one per click
#   beguiling            pending_beguiling              Beguiling Magic: target
#   clairvoyant          pending_clairvoyant            Clairvoyant Combatant: enemy
#   vow_of_enmity        pending_vow_of_enmity          Vow of Enmity: enemy
#   path_to_the_grave    pending_path_to_the_grave      Path to the Grave: creature
#   move_hunters_mark    pending_move_hunters_mark      Hunter's Mark / Hex: the mark's new creature
#   inspiring_smite      pending_inspiring_smite        Inspiring Smite: temp-HP recipient
#   legendary_target     _legendary_target_pick         a legendary attack's target
#   legendary_spell      _legendary_spell_pick          a legendary spell's target; data = "creature" | "cell"
#   lair                 _lair_pick                     a lair action; data = "doors" | "apparition" | "shadow"
#   chromatic            pending_chromatic_active       Chromatic Orb: the leap chain, over its spell arm
#   heal_light           pending_heal_light             Healing Light: target
#   lay_on_hands         pending_lay_on_hands           Lay on Hands: target
#   bastion_of_law       pending_bastion_of_law         Bastion of Law: ward target
#   hand_of_healing      pending_hand_of_healing        Hand of Healing: target
#   use_item             pending_use_item               Use Item: target; data = inventory slot
#   escape_net           pending_escape_net             Free from Net: the netted creature
#   piercing_shot        (new, AA3)                     Arcane Archer Piercing Shot: aim cell; data = {"weapon"}
#   seeking_shot         (new, AA3)                     Arcane Archer Seeking Shot: target; data = {"weapon"}
#   grant_inspiration    pending_grant_inspiration      Bardic Inspiration: ally
#   telekinetic          pending_telekinetic            Telekinetic Movement: target
#   flurry_target        pending_flurry_target          Flurry of Blows: target
#   vitality_target      pending_vitality_target        Vitality of the Tree: target, in a parked window
#   shadowy_dodge_cell   pending_shadowy_dodge_cell     Shadowy Dodge: teleport cell, in a parked window
#   masterful_shots_cell (new, AA5)                     Masterful Shots: move cell, in a parked window; data = feature
#   indomitable_teleport_cell (new, AA5)                Indomitable Teleport: cell, in a parked window; data = feature
# Companion state (pending_mantle_targets, pending_bastion_sp, …) stays on the app for now.

# The kinds whose old field rested at something other than False.
_IDLE = {
    "elemental_burst": -1, "use_item": -1,
    "cleave": None, "sweep": None, "rally": None, "feint": None,
    "legendary_spell": "", "lair": "",
}


def idle(kind: str):
    return _IDLE.get(kind, False)


@dataclass
class Pick:
    kind: str
    data: object = True


# ── The base modes: `app.pending` (A2b) ──────────────────────────────────────────────────
# At most one is armed (checked over the whole suite before the move), and `app.pending` is
# None when none is. Each replaces the `pending_*` fields named beside it, field for field.

@dataclass
class Attack:
    """A weapon attack awaiting its target. Was `pending_attack_slot`."""
    slot: str                                   # "action" | "bonus"


@dataclass
class Spell:
    """A spell awaiting its target(s) or place. Was `pending_spell_slot` and companions."""
    slot: str                                   # "action" | "bonus"
    idx: int = 0                                # the caster's spell index
    slot_level: int = 0                         # slot level chosen for this cast
    is_aoe: bool = False
    num_targets: int = 0                        # Multiple geometry: the targets to collect
    targets: list = field(default_factory=list) # Multiple geometry: those collected


@dataclass
class Shove:
    """A Shove awaiting its creature. Was `pending_shove_slot` / `pending_shove_type`."""
    slot: str                                   # "bonus"
    type: str                                   # "push" | "prone" | "telekinetic"


@dataclass
class Unarmed:
    """An Unarmed Strike option awaiting its creature. Was `pending_unarmed_type`. The
    Damage option goes through `Attack` instead."""
    type: str                                   # "grapple" | "push"


@dataclass
class Summon:
    """A summon awaiting the cell it appears in. Was `pending_summon_*`."""
    slot: str                                   # "action" | "bonus"
    idx: int = 0                                # spell index of the summon spell
    slot_level: int = 0
    monster: str = ""                           # monster-JSON key to spawn
    spirit: object = None                       # scaling spirit block (summons.json) or None
    free_cast: bool = False                     # Wish-duplicated: charge no slot of its own
    no_conc: bool = False                       # Fey Wanderer L11: Summon Fey without Concentration


# ── State beside `app.pending`, which outlives a single arm ──────────────────────────────

@dataclass
class AttackSequence:
    """The Attack action's sequence across its swings (`app.attack_seq`). It outlives each
    `Attack` arm: `cancel_attack` restores it from the arm's snapshot while nothing is armed.
    Was `attacks_remaining`, `_attack_sequence_slot`, `pending_weapon_idx`,
    `pending_attack_offhand` and `pending_attack_resource`. Saves keep the old two names."""
    remaining: int = 0                          # attacks left in the sequence
    slot: str = ""                              # "action" | "bonus" | "" — the sequence's slot
    weapon_idx: int = 0
    offhand: object = None                      # None = derive from slot; True/False overrides
    resource: object = None                     # resource spent on a valid attack ("War Priest")


@dataclass
class CastSetup:
    """Choices the cast menu makes before the `Spell` or `Summon` arms, read when it resolves
    (`app.cast_setup`). Was `pending_spell_damage_type`, `_free_cast`, `_command_word`,
    `_curse_choice`, `pending_forcecage_sealed` and `pending_summon_fey_reinforcements`."""
    damage_type: int = -1                       # Chromatic Orb / Sorcerous Burst; -1 = stored type
    free_cast: bool = False                     # Mantle of Majesty Command, Wish: no slot
    use_grant: bool = False                     # granted spell (SPECIES D3): a free cast, no slot
    command_word: int = -1                      # Command word (0=Drop..4=Approach); -1 = n/a
    curse_choice: int = -1                      # Vistani Curse sub-choice; -1 = n/a
    forcecage_sealed: bool = False              # Forcecage: False = Cage, True = Box
    enlarge: bool = False                       # Enlarge/Reduce: False = Reduce, True = Enlarge
    fey_reinforcements: bool = False            # the slotless Summon Fey spends "Fey Reinforcements"
