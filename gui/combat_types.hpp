#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  combat_types.hpp  –  Result/action/state structs for the combat engine
//
//  Extracted from combat.hpp (R2 of COMBAT_REFACTOR_PLAN.md): these are pure data
//  types with no CombatEngine dependency, so they can be included by TUs (bindings,
//  future rules code) that only need to read/build these structs without pulling in
//  the ~3,400-line CombatEngine class declaration.
// ─────────────────────────────────────────────────────────────────────────────

#include "weapon.hpp"
#include "spell.hpp"
#include "agent.hpp"
#include "cell.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace rpg {

// Forward declarations (avoid pulling in the whole BattleMap header here).
enum class MovementType;  // defined in battle_map.hpp

struct HideResult {
    bool valid{false};           // agent exists and is out of LOS of all enemies
    int  stealth_d20{0};         // raw d20 roll for stealth check
    int  stealth_total{0};       // stealth roll + modifier
    bool hidden{false};          // successfully hidden after contest
    std::string log_message;     // diagnostic/contest details
};

// ─────────────────────────────────────────────────────────────────────────────
//  Attack result
// ─────────────────────────────────────────────────────────────────────────────
struct AttackResult {
    // ── Validity ──────────────────────────────────────────────────────────
    bool valid        = false;  // false → action was illegal (out of range, bad index…)

    // ── Attack roll ───────────────────────────────────────────────────────
    int  d20          = 0;      // raw die (1–20); natural 20 = crit, 1 = fumble
    int  d20_primary  = 0;      // the FIRST die rolled (== d20 when no adv/dis); the natural roll
                                // before the advantage/disadvantage die. Clockwork Restore Balance
                                // reverts r.d20 to this to cancel advantage/disadvantage.
    int  attack_mod   = 0;      // total modifier added to the roll
    int  total_roll   = 0;      // d20 + attack_mod
    int  target_ac    = 0;      // defender's AC we rolled against
    bool critical     = false;  // natural 20 → double damage dice
    bool fumble       = false;  // natural 1  → automatic miss
    bool disadvantage = false;  // roll was made at disadvantage (long range etc.)
    bool advantage    = false;  // roll was made at advantage (reckless, hidden, invisible, etc.)
    bool hit          = false;

    // ── Damage (only meaningful when hit == true) ─────────────────────────
    std::vector<int> dice_results;  // individual die values (doubled on crit)
    int  damage_mod   = 0;          // ability-score modifier added to damage
    int  total_damage = 0;          // max(0, sum(dice) + damage_mod)
    std::vector<MagicDamage_t>    magic_damage_types;
    std::vector<PhysicalDamage_t> physical_damage_types;
    // Per-source damage breakdown, e.g. [("weapon",4),("rage",3)]. Sums to total_damage.
    std::vector<std::pair<std::string,int>> damage_breakdown;
    // Per-magic-type damage actually dealt (after the target's resistance/immunity multiplier),
    // indexed by MagicDamage_t. Read by on-hit riders that key off a specific type — e.g. the
    // vampiric "reduceHPMax" rider drains the HP maximum by the Necrotic damage dealt.
    std::array<int, NumMagicDamage_t> magic_damage_dealt{};

    // ── Target outcome ────────────────────────────────────────────────────
    int  hp_before    = 0;
    int  hp_after     = 0;
    bool target_down  = false;  // hp_after <= 0

    // ── Forced movement (push/knockback) ──────────────────────────────────
    int  push_ft_applied = 0;   // feet the target was actually pushed

    // ── Thrown weapon (Attack::thrown) ────────────────────────────────────
    // This attack was resolved as a THROW. Set on a hit AND a miss — a thrown weapon leaves the
    // hand either way. thrown_item_id is the MapItem the weapon became where it landed; it stays
    // -1 for a weapon that comes back (Weapon::returns_after_throw — a Psychic Blade), which is
    // also the one case where no copy is spent.
    bool weapon_thrown  = false;
    int  thrown_item_id = -1;
};

// ─────────────────────────────────────────────────────────────────────────────
//  Discrete weapon attack (attacker / target / weapon triple)
//  One concrete element of the RL action space; SpellAction is the other.
// ─────────────────────────────────────────────────────────────────────────────
struct Attack {
    int  attacker_idx = -1;    // index into BattleMap::placedAgents()
    int  target_idx   = -1;
    int  weapon_idx   =  0;    // index into attacker's weapons list
    bool is_offhand   = false; // off-hand attack: proficiency bonus not added to hit
    bool no_ability_damage = false; // Cleave: do not add a positive ability modifier to damage
    std::string attack_slot = "";   // "action" or "bonus" — set by Python to indicate attack type
    bool opportunity = false;       // this attack is an Opportunity Attack (set on the OA path) —
                                    // a Speedy target imposes Disadvantage on it
    // THROW this weapon instead of swinging it (requires Weapon::thrown). The attack reaches
    // long_range_ft rather than reach_ft, and the weapon LEAVES THE THROWER'S HAND: one copy is
    // spent and lands on the ground as a MapItem at the target's cell (applyAttackResult), where
    // anyone may pick it up. Set by the GUI when the DM targets beyond the weapon's melee reach —
    // an attack that would otherwise be illegal, so a normal melee swing is never turned into a
    // throw by accident. NPC automation leaves this false, so no monster throws its weapon away.
    bool thrown = false;
};

// ─────────────────────────────────────────────────────────────────────────────
//  Spell action — used in TurnActions and as the RL spell action space
// ─────────────────────────────────────────────────────────────────────────────
struct SpellAction {
    int  caster_idx  = -1;   // index into BattleMap::placedAgents()
    int  spell_idx   =  0;   // index into caster's spells list
    int  slot_level  =  0;   // for player upcasting: slot level (1-9); 0 = base level / NPC mode
    // For Single geometry, only target_indices[0] is used.
    // For Line/Cone/Sphere, target_indices lists all cells/agents in the area.
    std::vector<int> target_indices;
    // Explicit target cell for area-of-effect origin (Line/Cone/Sphere).
    // Ignored for Single geometry.
    int  aoe_col = 0;
    int  aoe_row = 0;
    // Second aim point for oriented Rectangle "wall" spells (e.g. Wall of Fire):
    // the wall runs from (aoe_col,aoe_row) toward this endpoint, clamped to the
    // spell's length. -1 = unset → engine falls back to a centered box.
    int  aoe_col2 = -1;
    int  aoe_row2 = -1;
    // Sorcerer Metamagic applied to this cast (MetamagicNone = none). The SP cost is
    // deducted in executeSpell. Implemented: Careful, Distant, Empowered, Extended, Heightened,
    // Quickened, Seeking, Transmuted, Twinned. Subtle = flavor only.
    MetamagicOption metamagic = MetamagicNone;
    // Second Metamagic option on the same cast. Only honored when the caster may use two options:
    // either one of the pair is Seeking (the option that stacks with another, SRD p.66) or the
    // caster has Sorcery Incarnate (Sorcerer L7 with Innate Sorcery active — see
    // sorceryIncarnateActive). Otherwise executeSpell logs and ignores it (no SP spent). A duplicate
    // of `metamagic` is ignored too, so an option is never paid for twice.
    MetamagicOption metamagic2 = MetamagicNone;
    // Metamagic parameter data — only read for the matching option:
    std::vector<int> careful_targets;     // Careful: allies excluded from this spell's area, Sculpt-style
                                          // (honored up to the caster's CHA modifier).
    int transmuted_damage_type = -1;      // Transmuted: MagicDamage_t to convert the spell's elemental
                                          // damage into (Acid/Cold/Fire/Lightning/Poison/Thunder); -1 = none.
    // Cast-time element choice for spells whose damage type is chosen on each cast
    // (Chromatic Orb, Sorcerous Burst). When >= 0, executeSpell rewrites every
    // magic_damage_roll's type to this MagicDamage_t for this cast only (no persistent
    // mutation). Independent of Transmuted metamagic. -1 = use the spell's stored type.
    int damage_type_override = -1;
    // Chromatic Orb leap chain (GUI picker): ordered creatures the player wants the orb to
    // leap to, consumed one per leap as matching d8s occur. Each pick is still validated at
    // its hop (within 30 ft of the previous target, a living non-ally, not already hit). When
    // the list is empty/exhausted or a pick is invalid, the engine auto-selects the nearest
    // eligible enemy — so NPC, RL and headless casts (which have no picker) still leap.
    std::vector<int> chromatic_leap_targets;
    // Free cast (no spell slot expended). Set by features that grant a slot-free cast
    // (Bard College of Glamour — Mantle of Majesty casts Command without a slot). When true,
    // executeSpell skips the player slot decrement. The action economy (action/bonus) is still
    // charged by the caller.
    bool free_cast = false;
    // Command spell word choice (only read when the cast is the Command spell): 0=Drop, 1=Flee,
    // 2=Grovel, 3=Halt, 4=Approach. -1 = caller did not specify → engine defaults to Halt. Applied
    // to each target that fails the save (see applyCommandEffect).
    int  command_word = -1;
    // Vistani Curse sub-choice (only read when the cast is a curse spell, curse_kind>0).
    // Meaning depends on the spell's curse_kind: vulnerability → encoded damage type
    // (0..NumMagicDamage_t-1 = magic, 100+i = physical); weakness → SaveAbility_t;
    // affliction → 0=Blinded, 1=Deafened, 2=Both. -1 = caller did not specify.
    int  curse_choice = -1;
    // Overchannel (Evoker Wizard L14): when true, request maximum damage on this cast. The engine
    // honors it only for an Evoker L14+ casting a damaging spell of effective level 1–5; otherwise
    // it is ignored. The first use per Long Rest is free; each later use inflicts escalating
    // Necrotic damage on the caster (see executeSpell / Agent::Stats::overchannel_uses).
    bool overchannel = false;
    // Dispel Magic selection (the GUI's dispel picker): when a dispels_magic cast should end only
    // SPECIFIC ongoing effects the DM chose — rather than everything on the aimed creature/cell —
    // these carry the chosen structure ids (ActiveAgentCondition::condition_id / ActiveSpellEffect::
    // effect_id / ActiveTerrainEffect::id). All three empty = "dispel everything at the target" (the
    // pre-picker behavior, still used by NPCs, RL and tests). See CombatEngine::dispelSelected.
    std::vector<int> dispel_condition_ids;
    std::vector<int> dispel_spell_effect_ids;
    std::vector<int> dispel_terrain_ids;
    // Magic Circle / Hallow (only read when the cast's spell has creates_movement_ward). The
    // creature types this cast wards (an OR of Agent::CreatureTypeBit values, chosen in the GUI)
    // and the direction: ward_traps == false keeps the warded types OUT of the zone, true keeps
    // them IN (reverse Magic Circle). mask 0 = no ward placed (defensive; the GUI supplies a mask).
    uint32_t ward_creature_mask = 0;
    bool     ward_traps = false;
    // Forcecage (only read when casting Forcecage). false = the Cage form (20-ft barred cube): the
    // occupant is trapped but attacks/spells still pass through the bars both ways. true = the Box
    // form (10-ft solid cube): a two-way seal — the occupant can't attack or cast at anything outside
    // (only a CHA-saved teleport escapes), and nothing outside can attack, target, or reach into the
    // box either. Rides onto the applied Forcecaged condition's forcecage_sealed flag.
    bool     forcecage_sealed = false;
};

// ─────────────────────────────────────────────────────────────────────────────
//  Dispel Magic: one dispellable ongoing spell aimed at a creature or cell
// ─────────────────────────────────────────────────────────────────────────────
// Structures created by the same cast group into one candidate (Hunger of Hadar's damage zone +
// its difficult terrain = one entry, one roll). The GUI enumerates these for its dispel picker so
// the DM ends exactly the right effect (a buff on an ally vs a debuff on an enemy, or one of several
// overlapping AoEs on a cell), then casts back the candidate's structure ids in SpellAction.
struct DispelCandidate {
    std::string      label;                 // spell/condition name shown in the picker
    int              owner_idx     = -1;    // caster who created the effect (-1 = unknown)
    int              level         = 1;     // effective level (auto-end if <= slot, else DC 10+level)
    bool             owner_is_ally = false; // owner is an ally of the dispel caster (buff-on-ally hint)
    int              spell_key     = -1;    // grouping spell_idx (for concentration cleanup); -1 = none
    std::vector<int> condition_ids;         // ActiveAgentCondition ids this candidate covers
    std::vector<int> spell_effect_ids;      // ActiveSpellEffect ids
    std::vector<int> terrain_ids;           // ActiveTerrainEffect ids
};

// ─────────────────────────────────────────────────────────────────────────────
//  Per-target outcome for a single spell application
// ─────────────────────────────────────────────────────────────────────────────
struct SpellTargetResult {
    int  target_idx   = -1;
    bool saved        = false;  // true → target passed saving throw (half damage)
    bool hit          = false;  // for AttackRoll spells: whether the roll succeeded
    int  d20          = 0;
    int  attack_mod   = 0;
    int  total_roll   = 0;
    int  target_ac    = 0;
    bool critical     = false;
    std::vector<int> dice_results;
    int  damage_mod   = 0;
    int  total_damage = 0;    // 0 for heals (see healing field)
    int  total_healing = 0;   // 0 for harm spells
    int  hp_before    = 0;
    int  hp_after     = 0;
    bool target_down  = false;
    int  save_d20     = 0;   // d20 rolled on a Save
    int  save_mod     = 0;   // total save modifier used (ability + prof + auras)
    int  save_dc      = 0;   // spell save DC the target rolled against
    std::string log_message;   // formatted log message for this target
    bool concentration_checked = false;  // whether concentration save was checked
    bool concentration_lost = false;     // whether target lost concentration
    int  push_ft_applied = 0;            // feet the target was actually pushed
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of dropping concentration
// ─────────────────────────────────────────────────────────────────────────────
struct DropConcentrationResult {
    bool dropped = false;
    std::string spell_name;
    std::vector<int> removed_terrain_ids;
    std::vector<int> removed_spell_effect_ids;
    std::vector<int> removed_condition_ids;
    std::vector<int> dismissed_summons;      // indices of summons tombstoned (removed_from_play) by this drop
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of Cleric Turn Undead (Channel Divinity)
// ─────────────────────────────────────────────────────────────────────────────
struct TurnUndeadResult {
    bool valid = false;            // caster was a Cleric L2+ with Channel Divinity available
    int  save_dc = 0;              // WIS save DC the undead rolled against
    int  sear_damage = 0;          // Radiant dealt to each failed undead (Sear Undead, L5+; 0 otherwise)
    std::vector<int> turned;       // undead that failed → Frightened + Incapacitated (ends on damage)
    std::vector<int> resisted;     // undead that made the save
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of Life Domain Preserve Life (Channel Divinity, L3+)
// ─────────────────────────────────────────────────────────────────────────────
struct PreserveLifeResult {
    bool valid = false;            // caster was a Life Cleric L3+ with Channel Divinity available
    int  pool  = 0;                // total HP to distribute (5 × cleric level)
    int  spent = 0;                // HP actually restored across all targets
    std::vector<int> healed;       // agent indices that received healing (parallel to amounts)
    std::vector<int> amounts;      // HP restored to each healed index
};

// Result of the Topple weapon-mastery prone save.
struct ToppleResult {
    bool valid = false;   // topple_available was set on the attacker (a qualifying hit had occurred)
    int  save_dc = 0;     // CON save DC = 8 + attacker's attack ability mod + prof bonus
    int  save_roll = 0;   // target's d20 + CON save mod
    bool toppled = false; // target failed the save and is now Prone
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of Monk Stunning Strike: CON save or Stunned
// ─────────────────────────────────────────────────────────────────────────────
struct StunningStrikeResult {
    bool valid = false;     // stunning_strike_available was set on the attacker
    int  save_dc = 0;       // CON save DC = 8 + attacker's DEX mod + prof bonus
    int  save_roll = 0;     // target's d20 + CON save mod
    bool stunned = false;   // target failed the save and is now Stunned
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of Monk Warrior of the Open Hand rider (Knockdown, Push, or Deny Reaction)
// ─────────────────────────────────────────────────────────────────────────────
struct OpenHandRiderResult {
    bool valid = false;        // open_hand_rider_available was set on the attacker
    int  option = -1;          // 0=Knockdown, 1=Push, 2=DenyReaction
    // Knockdown fields
    int  knockdown_save_dc = 0;   // STR save DC for Knockdown
    int  knockdown_save_roll = 0; // target's d20 + STR save mod
    bool target_knocked_prone = false;
    // Push fields
    int  push_distance = 0;       // feet pushed (depends on implementation)
    // Deny Reaction field
    bool reaction_denied = false; // reaction_used was set on target
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of Monk Warrior of Mercy — Hand of Healing (a Bonus Action heal)
// ─────────────────────────────────────────────────────────────────────────────
struct HandOfHealingResult {
    bool valid = false;                 // gate passed (Mercy Monk L3+, Focus Point, Bonus Action)
    int  amount_healed = 0;             // HP actually restored to the target
    bool condition_cleared = false;     // L6 Physician's Touch: a condition was also ended
    std::string cleared_condition = {}; // name of the condition ended (empty if none)
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of using a carried Item (potion, thrown flask, Net) — CombatEngine::useItem
// ─────────────────────────────────────────────────────────────────────────────
struct UseItemResult {
    bool valid = false;         // gate passed (item in the pack, target in range, action available)
    int  amount_healed = 0;     // HP actually restored (Heal items)
    std::string item_name = {}; // what was used (the row may be gone by the time we return)
    bool consumed = false;      // the last charge went — the item left the inventory

    // ── Thrown items (Acid, Alchemist's Fire, Holy Water, Net) ───────────────
    // The flask is spent whether it lands or not, so a thrown use with valid == true and
    // saved == true is a *successful throw that did nothing* — not a rejected action.
    int  save_dc     = 0;       // 8 + thrower's DEX modifier + Proficiency Bonus
    int  save_roll   = 0;       // target's DEX save total (0 when no save was rolled)
    bool saved       = false;   // target made the save (or auto-succeeded — a Huge+ creature vs a Net)
    int  damage_dealt = 0;      // damage after the target's Resistance/Immunity multiplier
    bool no_effect   = false;   // splashed harmlessly: Holy Water on anything but a Fiend/Undead
    std::string condition_applied = {};  // "Burning" / "Restrained", when the save failed
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of a Net escape attempt — see CombatEngine::escapeNet
// ─────────────────────────────────────────────────────────────────────────────
struct EscapeNetResult {
    bool valid   = false;   // gate passed (target is netted, actor is the target or within 5 ft)
    int  dc      = 0;       // DC 10 for a standard Net (Conditions::net_escape_dc)
    int  d20     = 0;       // raw die
    int  total   = 0;       // d20 + STR modifier
    bool freed   = false;   // check succeeded — the Net is cut away and Restrained ends
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of a Battle Master Maneuver (Trip, Menacing, Pushing)
// ─────────────────────────────────────────────────────────────────────────────
struct ManeuverResult {
    bool valid = false;             // maneuver_available was set on the attacker
    int  maneuver_type = -1;        // 0=Trip, 1=Menacing, 2=Pushing, 3=Goading, 4=Distracting, 5=Disarming, 6=Sweeping
    int  save_dc = 0;               // save DC for Trip/Menacing/Goading/Disarming
    int  save_roll = 0;             // target's d20 + save modifier
    bool condition_applied = false; // true if the effect landed (save failed / condition applied / sweep hit)
    int  push_distance = 0;         // feet pushed (Pushing maneuver only)
    int  extra_damage = 0;          // superiority-die damage dealt to the 2nd creature (Sweeping only)
    bool extra_target_down = false; // the 2nd creature dropped to 0 HP (Sweeping only)
};

// ─────────────────────────────────────────────────────────────────────────────
//  Flurry of Blows result (Monk: two bonus attacks with optional Open Hand rider)
// ─────────────────────────────────────────────────────────────────────────────
struct FlurryResult {
    AttackResult attack1;              // first unarmed strike
    AttackResult attack2;              // second unarmed strike
    AttackResult attack3;              // third unarmed strike (Monk L10 Heightened Focus)
    OpenHandRiderResult rider1;        // rider applied on first hit (if Way of Open Hand)
    OpenHandRiderResult rider2;        // rider applied on second hit (if Way of Open Hand)
    OpenHandRiderResult rider3;        // rider applied on third hit (if Way of Open Hand)
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of ticking an agent's terrain at the start of their turn
// ─────────────────────────────────────────────────────────────────────────────
struct TerrainTickResult {
    std::vector<int>        expired_terrain_ids;  // terrain effects that ran out this turn
    DropConcentrationResult concentration;        // populated if a concentration terrain expired
};

// ─────────────────────────────────────────────────────────────────────────────
//  Full result for a spell cast
// ─────────────────────────────────────────────────────────────────────────────
struct SpellResult {
    bool valid = false;
    int  spell_idx = -1;
    std::string spell_name;
    Spell::SpellAttack_t attack_type{Spell::AttackRoll};
    std::vector<SpellTargetResult> target_results;
    bool        concentration_replaced     = false;   // caster dropped previous concentration
    std::string prev_concentration_spell   = {};      // name of dropped spell
    std::vector<int> terrain_effect_ids    = {};      // ids of new terrain effects placed by this spell
    std::vector<int> light_effect_ids      = {};      // ids of new light effects placed by this spell
    bool cast_as_bonus_action              = false;   // Metamagic Quickened: cast as a Bonus Action this turn
};

// ─────────────────────────────────────────────────────────────────────────────
//  Shove action — bonus action to push or knock prone a nearby target
// ─────────────────────────────────────────────────────────────────────────────
struct ShoveAction {
    int  attacker_idx = -1;    // index into BattleMap::placedAgents()
    int  target_idx   = -1;
    bool knock_prone  = false;  // true = knock prone; false = push 5ft
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of a shove attempt
// ─────────────────────────────────────────────────────────────────────────────
struct ShoveResult {
    bool valid        = false;
    bool success      = false;
    int  attacker_roll = 0;   // Athletics check total
    int  defender_roll = 0;   // Athletics or Acrobatics (whichever higher)
    int  push_ft_applied = 0; // feet actually pushed (0 if knocked prone)
    bool knocked_prone  = false;
    std::string log_message;
};

// ─────────────────────────────────────────────────────────────────────────────
//  Pick-lock attempt — Sleight of Hand check vs a door's lock DC
// ─────────────────────────────────────────────────────────────────────────────
struct PickLockResult {
    bool valid   = false;   // false if the agent/door index was invalid
    bool success = false;   // true if the lock was opened
    int  roll    = 0;       // the raw d20
    int  total   = 0;       // d20 + Sleight of Hand bonus
    int  dc      = 0;       // the door's lock_dc
    std::string log_message;
};

// ─────────────────────────────────────────────────────────────────────────────
//  Break-door attempt — Strength (Athletics) check vs a door's break DC
// ─────────────────────────────────────────────────────────────────────────────
struct BreakDoorResult {
    bool valid   = false;   // false if the agent/door index was invalid or nothing to break
    bool success = false;   // true if the door was smashed open
    int  roll    = 0;       // the raw d20
    int  total   = 0;       // d20 + Athletics (STR) bonus
    int  dc      = 0;       // effective break DC (door break_dc, +10 for an active Arcane Lock)
    std::string log_message;
};

// ─────────────────────────────────────────────────────────────────────────────
//  Grapple action — initiate a grapple (contested Athletics check)
// ─────────────────────────────────────────────────────────────────────────────
struct GrappleAction {
    int  attacker_idx = -1;    // index into BattleMap::placedAgents()
    int  target_idx   = -1;
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of a grapple attempt
// ─────────────────────────────────────────────────────────────────────────────
struct GrappleResult {
    bool valid        = false;
    bool success      = false;
    int  attacker_roll = 0;   // Athletics check total
    int  defender_roll = 0;   // Athletics or Acrobatics (whichever higher)
    int  escape_dc    = 0;    // DC for target to escape later (10 + attacker's Athletics)
    std::string log_message;
};

// ─────────────────────────────────────────────────────────────────────────────
//  Result of a grapple escape attempt
// ─────────────────────────────────────────────────────────────────────────────
struct GrappleEscapeResult {
    bool valid        = false;
    bool success      = false;
    int  escape_roll  = 0;    // best of STR (Athletics) or DEX (Acrobatics) rolls
    int  escape_dc    = 0;    // DC attempted against
    std::string log_message;
};

// ─────────────────────────────────────────────────────────────────────────────
//  Concentration saving throw result (triggered when a concentrating agent takes damage)
// ─────────────────────────────────────────────────────────────────────────────
struct ConcentrationSaveResult {
    bool checked            = false;   // save was needed (agent was concentrating)
    int  save_d20           = 0;
    int  save_dc            = 0;
    int  con_mod            = 0;
    bool passed             = false;
    bool concentration_lost = false;
    std::string spell_name  = {};      // spell that was being concentrated on
};

// ─────────────────────────────────────────────────────────────────────────────
//  Active persistent effect (duration > 1 turn)
// ─────────────────────────────────────────────────────────────────────────────
struct ActiveEffect {
    int  caster_idx  = -1;
    int  target_idx  = -1;
    Spell spell;               // copy of the spell that created this effect
    int  turns_remaining = 0;  // decremented each time tickEffects() is called
};

// ─────────────────────────────────────────────────────────────────────────────
//  Initiative entry — one per agent, produced by CombatEngine::rollInitiative.
//
//  Sorted descending by total (highest acts first).  Ties broken by:
//    1. Higher initiative modifier (higher DEX acts first — passive tiebreaker).
//    2. Lower agent_idx (stable, deterministic).
// ─────────────────────────────────────────────────────────────────────────────
struct InitiativeEntry {
    int agent_idx = -1;
    int d20       =  0;   // raw die result (1–20)
    int modifier  =  0;   // DEX mod [+ prof_bonus if initiative_prof]
    int total     =  0;   // d20 + modifier
};

// ─────────────────────────────────────────────────────────────────────────────
//  One agent's choices for a single turn within a round.
//
//  Walk and fly are always triggered; the caller only specifies whether the
//  action and bonus action are weapon attacks (optional).  Non-attack uses
//  of the action or bonus action (e.g. dash, disengage) are represented by
//  leaving the corresponding field empty — the action/bonusAction hook on
//  the Agent still fires, signalling that the slot was consumed.
// ─────────────────────────────────────────────────────────────────────────────
struct TurnActions {
    int agent_idx = -1;

    // One or more weapon attacks for the Action slot (Extra Attack fills this
    // with multiple entries).  Empty means the action slot is used for
    // something else (dash, disengage, etc.).
    std::vector<Attack> attacks;

    // Weapon attacks for the Bonus Action slot (typically at most one,
    // e.g. off-hand TWF attack).
    std::vector<Attack> bonus_attacks;

    // One or more spell casts for the Action slot.
    std::vector<SpellAction> spell_actions;

    // Spell casts for the Bonus Action slot.
    std::vector<SpellAction> bonus_spells;
};

// ─────────────────────────────────────────────────────────────────────────────
//  TurnStartResult — outcome of beginTurn (paralysis save, etc.)
// ─────────────────────────────────────────────────────────────────────────────
struct TurnStartResult {
    bool turn_skipped = false;          // true if agent's turn should be skipped (e.g., paralyzed save failed)
    std::string skip_reason;            // reason for skip (e.g., "Hold Person (save failed)")
    std::string save_roll_message;      // log message from save roll (if any)
};

// ─────────────────────────────────────────────────────────────────────────────
//  CombatDecider interface — decision points for GUI (Python callback) vs RL/headless (default policy)
// ─────────────────────────────────────────────────────────────────────────────
struct BrutalStrikeCtx { int attacker_idx; int target_idx; int level; };
struct RecklessCtx     { int attacker_idx; };

// ── Reaction system ────────────────────────────
// A "window" is WHEN in resolution a reaction may fire. This pass wires only
// LeftReach (Opportunity Attacks); the rest are reserved for future consumers.
enum class ReactionWindow {
    LeftReach,          // a creature moved out of this reactor's reach (Opportunity Attack)
    OnHit, OnMiss,      // an attack resolved (future)
    OnDeclareCast,      // a spell was declared, not yet resolved (future, Counterspell)
    OnD20Seen,          // a d20 Test is visible pre-commit (future)
    OnSaveFail,         // a saving throw just failed (future, Countercharm)
    OnTurnStartNearby,  // a creature started its turn within range (future)
    OnAllyAttacked      // an adjacent enemy attacked someone other than the reactor (Sentinel Guardian)
};

// One legal thing the reactor may do, ENUMERATED BY THE ENGINE so it is guaranteed
// legal (in range, resource available, right weapon category). The decider picks one
// of these rather than inventing an action — cheap validation + a discrete RL space.
struct ReactionOption {
    enum Kind { Skip, Weapon, Spell, Feature } kind{Skip};
    int  index{-1};        // weapon_idx or spell_idx into the reactor's loadout (-1 = Skip/Feature)
    std::string label;     // human-facing menu text (e.g. "[Weapon] Longsword")
    std::string feature;   // for Feature kind: a named reaction the engine resolves via a dedicated
                           // apply method ("Shield", later "Counterspell"/"ProtectiveField"/"Riposte")
};

// "ctx" = the full CONTEXT of one pending reaction decision. The engine fills it and
// hands it to the decider (auto path) or exposes it via pendingDecision() (GUI path).
// Generalizes the old OA-only ctx; window-specific payload fields stay default when unused.
struct ReactionCtx {
    ReactionWindow window{ReactionWindow::LeftReach};
    int reactor_idx{-1};   // who is being asked to spend their reaction
    int source_idx{-1};    // who triggered the window (the mover for an OA; for OnTurnStartNearby, the
                           // creature whose turn just started; for OnSaveFail, the creature that failed)
    std::vector<ReactionOption> options;   // engine-vetted legal choices (always incl. Skip)
    Cell source_cell{};    // LeftReach: the cell the source is leaving (mover stands here for the OA)
    int  d20_value{-1};    // OnD20Seen payload (future)
    int  spell_idx{-1};    // OnDeclareCast payload (future)
    int  damage{0};        // OnHit payload (future)
};

// The decider's answer: an intent struct (not a bare index) so it can carry parameters
// (sub-target, slot level, die) as richer reactions arrive. For an OA it is just
// {option = picked index}. The engine re-validates before applying.
struct ReactionResponse {
    int option{-1};        // index into ctx.options; -1 (or the Skip option) = no reaction
    int target_idx{-1};    // sub-target when needed (OA: leave -1 → defaults to source_idx)
};

struct CombatDecider {
    virtual ~CombatDecider() = default;
    virtual std::vector<int> chooseBrutalStrike(const BrutalStrikeCtx&) { return {}; }
    virtual bool             chooseReckless(const RecklessCtx&)          { return false; }
    // The general reaction decision. Default = no reaction (correct headless fallback
    // until a real policy is provided). Replaces the old chooseOAResponse/OACtx.
    virtual ReactionResponse chooseReaction(const ReactionCtx&)          { return {}; }
};

// Flow-checkpoint transport: interactive flows (e.g. a move
// that provokes OAs) suspend at a decision point instead of blocking. The GUI polls
// pendingDecision(), draws the menu async, and routes the click back via submitDecision().
enum class FlowStatus { Completed, AwaitingDecision };

// What the engine is currently parked on. active=false when not parked.
struct PendingDecision { bool active{false}; ReactionCtx ctx; };

// One detected OA trigger along a move: `reactor` provokes because the mover leaves its
// reach; `left_cell` is the last cell still within reach (the mover stands there for the OA);
// `step` is the path index of that cell (events resolve in path order for stop-on-down).
struct ProvokeEvent { int reactor{-1}; Cell left_cell{}; int step{0}; };

// The result of one spell attack roll (analog of the weapon AttackResult's to-hit fields). Produced
// by rollSpellAttack; consumed by executeSpell's AttackRoll branch and carried across the OnHit Shield
// window for a single-target attack spell so the same roll the player saw is the one that lands.
struct SpellToHit {
    int  d20{0};
    int  attack_mod{0};
    int  total_roll{0};
    int  target_ac{0};
    bool critical{false};
    bool hit{false};
};

// The result of one spell saving throw (analog of SpellToHit). Produced by rollSpellSave; consumed by
// executeSpell's Save branch and carried across the OnSaveFail window so the same
// (possibly rerolled) save the player saw is the one that lands. Pass/fail vs DC only — no nat-1/nat-20
// auto rule on saves. A reaction (Countercharm / Indomitable) can only RAISE a failure → success.
struct SpellSave {
    int           target_idx{-1};   // who rolled this save (-1 = no preroll present)
    int           d20{0};           // the natural d20 (may be re-rolled by a reaction)
    int           save_mod{0};      // ability mod + (prof ? prof_bonus : 0); fixed across a reroll
    int           bonus{0};         // post-roll additive (Indomitable adds the Fighter level here); 0 normally
    int           total{0};         // d20 + save_mod + bonus
    int           dc{0};            // the spell save DC this roll was compared against
    bool          saved{false};     // total >= dc
    bool          auto_fail{false}; // paralyzed/stunned/unconscious vs STR/DEX → can't be helped; skip window
    SaveAbility_t ability{SaveStr}; // which save (for the menu label)
};

// Resumable state for one in-flight spell cast that may be interrupted at the OnDeclareCast window
// beginCast wraps executeSpell with this pre-resolution window: reactors
// (this pass: Magic Missile targets that can cast Shield) react before the cast resolves. A
// single-target AttackRoll spell additionally opens an OnHit Shield window after the to-hit roll
// (the spell analog of beginAttack's OnHit window — see rollSpellAttack/maybeDefenderShieldInlineSpell).
struct InFlightCast {
    bool active{false};
    bool interactive{false};        // GUI suspends at checkpoints; auto driver resolves inline
    SpellAction action;             // the declared cast (resolved by executeSpell once the window closes)
    std::vector<int> reactors;      // eligible OnDeclareCast reactors, in order
    std::size_t cursor{0};
    bool countered{false};          // set by a successful Counterspell (step 2) → cast fizzles, slot kept
    SpellResult result;             // filled when the cast resolves
    // ── single-target spell-attack OnHit Shield window (GUI suspend) ──
    bool       has_preroll{false};      // the to-hit was rolled in advanceCast; executeSpell consumes it
    int        preroll_target{-1};      // the target the pre-rolled to-hit applies to
    SpellToHit preroll{};               // the pre-rolled to-hit (updated by applyCastReaction if Shielded)
    bool       attack_window_done{false}; // the OnHit Shield window was offered once (don't re-open on resume)
    // ── OnSaveFail window (nearby creatures may reroll a FAILED save → possible success) ──
    // A Save-type spell pre-rolls every target's save here so executeSpell's Save branch consumes the
    // (possibly Countercharm/Indomitable-rerolled) result instead of rolling fresh. Mutually exclusive
    // with the attack window above (a spell is either AttackRoll or Save), so the phases never interleave.
    bool                            has_save_preroll{false};  // save_prerolls populated; executeSpell consumes them
    std::vector<SpellSave>          save_prerolls;            // one per target of the Save-type spell (target_idx-keyed)
    bool                            save_window_built{false}; // failed-save reactor pairs computed once (after the rolls)
    std::vector<std::pair<int,int>> savefail_pairs;          // (failed-save target_idx, eligible reactor_idx), in order
    std::size_t                     savefail_cursor{0};       // next pair to offer
    // ── Counterspell-as-cast: a nested cast whose effect is a deferred CON
    //    save against counter_target_caster, resolved at pop time so a deeper Counterspell can negate it. ──
    bool is_counterspell{false};     // this in-flight cast is a Counterspell reaction (no AttackRoll/Save phase)
    int  counter_target_caster{-1};  // the caster whose spell this Counterspell would counter (= parent's caster)
};

// Resumable state for one in-flight move that may provoke OAs.
struct InFlightMove {
    bool active{false};
    bool interactive{false};        // true = GUI (suspend at checkpoints); false = auto driver
    int  mover_idx{-1};
    Cell origin{};                  // where the mover started (restored before the real move)
    Cell dest{};
    MovementType type{};            // value-init (0 = Walk); set in beginMove/resolveMove. Enumerator
                                    // names aren't visible here (MovementType is only fwd-declared).
    std::vector<ProvokeEvent> provokes;
    std::size_t cursor{0};          // next provoke to resolve
    bool mover_down{false};         // an OA dropped the mover → stop where it fell
    bool mover_halted{false};       // a Sentinel OA hit → speed becomes 0; stop at halt_cell, no further move
    Cell halt_cell{};               // the cell the Sentinel OA stopped the mover at (the provoke cell)
    std::vector<AttackResult> results;
};

// Resumable state for one in-flight attack that may open a defender reaction window between the
// attack roll and damage. determineAdvantage fills the pre-roll state
// + snapshots; the caller rolls (resolveAttack) into r; applyAttackResult finalizes (riders/damage/
// concentration). beginAttack parks here at the OnHit Shield window and submitDecision resumes (3b).
struct InFlightAttack {
    bool active{false};
    bool interactive{false};        // GUI suspends at the OnHit window; auto/RL resolves inline
    Attack action{};                // the declared attack
    Weapon w{};                     // resolved weapon (off-hand proficiency already applied)
    AttackResult r{};               // the rolled result (filled by resolveAttack between the phases)
    bool adv{false};
    bool dis{false};
    bool auto_hit{false};           // this attack auto-hits (vampire Bite vs a creature it has Grappled);
                                    // forced after the roll, before the defender windows (a nat 20 still crits)
    bool unerring_fired{false};     // Oath of Glory L20 Unerring Strike promoted this attack's miss → hit;
                                    // the once-per-turn flag is committed as the LAST attacker-conditions
                                    // write in applyAttackResult (a mid-attack write would be clobbered)
    bool peerless_fired{false};     // Boon of Combat Prowess (Peerless Aim) promoted this NPC's miss → hit;
                                    // peerless_aim_used committed as a late attacker-conditions write (as above)
    bool onhit_offered{false};      // the OnHit defender window (Shield / Uncanny Dodge) has been opened once
    // ── OnD20Seen window (nearby creatures may LOWER this attack roll → possible miss) ──
    std::vector<int> d20_reactors;        // eligible OnD20Seen reactors (Bend Luck / Cutting Words / Silvery Barbs)
    std::size_t      d20_cursor{0};       // next reactor to offer
    bool             d20_window_built{false}; // reactor list computed once, after the roll (before Shield)
    // Pre-roll snapshots applyAttackResult needs (taken before this attack's own effects mutate state):
    bool can_use_brutal_strike{false};
    bool tgt_incapacitated_at_attack{false};
    bool tgt_unconscious_at_attack{false};
    bool consume_vex{false};
    bool consume_sap{false};
    bool consume_distracted{false}; // Distracting Strike: this attack used the target's distracted_by Advantage
    bool attacker_was_hidden{false};
    int  atk_sz{1};
    int  tgt_sz{1};
    // This attack is a THROW (Attack::thrown AND the resolved weapon really has the Thrown property —
    // a Disarmed attacker swinging an improvised Unarmed Strike throws nothing). Decided in
    // determineAdvantage; applyAttackResult spends the copy and lays it on the ground.
    bool was_thrown{false};
};

// Resumable state for one in-flight TURN START that may open the OnTurnStartNearby window
// beginTurnFlow runs the synchronous beginTurn body, stores its result,
// then offers nearby creatures a reaction (Sentinel melee strike / Branches of the Tree grapple)
// against the creature whose turn just started. Unlike the cast/attack windows there is no pre-roll to
// consume — the reaction is a post-effect interrupt that does not alter the TurnStartResult.
struct InFlightTurn {
    bool             active{false};
    bool             interactive{false};  // GUI suspends at each reactor; auto driver resolves inline
    int              agent_idx{-1};        // the creature whose turn started (the window's "source")
    TurnStartResult  result{};             // the beginTurn outcome (GUI reads it after the flow finishes)
    std::vector<int> reactors;             // eligible OnTurnStartNearby reactors, in order
    std::size_t      cursor{0};            // next reactor to offer
    bool             window_built{false};  // reactor list computed once
};

// Resumable state for one in-flight NPC-automation turn (NPC_AUTOMATION_PLAN.md Step 3). runNpcTurn
// can park mid-turn whenever an action it attempts (a move that provokes an OA, an attack that opens a
// defender/OnD20 window) suspends for a human reaction. The GUI driver resolves the window via
// submitDecision and then re-calls run_npc_turn, which must RESUME this turn — not restart targeting.
// This struct is the saved resume point: which target/weapon, how many attacks are left, and which
// phase the turn is in. active+agent_idx gate a resume vs a fresh turn.
struct NpcTurnState {
    bool active{false};
    int  agent_idx{-1};
    int  target_idx{-1};
    int  weapon_idx{0};          // slot 0..2 into the agent's weapons
    int  attacks_remaining{0};   // swings left in the Attack action (decremented BEFORE beginAttack so a
                                 // park-then-resume never repeats the swing that already resolved)
    enum Phase { PickAndMove, Attacking, Conceal, Done } phase{PickAndMove};
    // Single-cast turns (PreferAOE Step 6 + PreferControl/Heal/Support Steps 8-10): set TRUE immediately
    // before the single beginCast so a park-then-resume of the OnDeclareCast window does NOT re-cast —
    // submitDecision resolves the parked cast, then re-calls run_npc_turn, which sees this flag and simply
    // ends the turn (the spell already resolved). Shared by runAoeTurn and runCasterTurn.
    bool cast_launched{false};
    // Cast-turn approach: TRUE while a caster is MOVING to bring its spell into range before casting (an
    // out-of-range cast must never fall back to melee while a worthwhile spell is held). If that approach
    // move parks on an OA, the resume re-enters the same executor, sees this flag, and re-plans + casts
    // from the new cell (no second move). Shared by runAoeTurn (enemy approach) and runCasterTurn.
    bool cast_moving{false};
    // Multiattack recipe segments pending AFTER the current (weapon_idx, attacks_remaining) one.
    // Each is (weapon_slot, count). Empty ⇒ legacy single-weapon multiattack.
    std::vector<std::pair<int,int>> pending_segments;
    // PreferHide (Step 7): the Conceal tail phase runs after the attack loop when policy.conceal is set.
    // These cache the chosen conceal route + spell and gate the parkable primitives on resume (mirrors
    // cast_launched / cast_moving) so a park→resume does not re-move or re-cast.
    int  conceal_route{0};                // cached A/B/C/D route (NpcConcealRoute) so a resume is stable
    int  conceal_spell_idx{-1};           // chosen invis spell (route A bonus / route C action); -1 = none
    bool conceal_move_launched{false};    // post-attack cover move started (resume: don't re-move)
    bool conceal_act_launched{false};     // Hide/cast started (resume after Counterspell: don't re-cast)
    // Command (Flee): a commanded creature spends its whole turn running away by the fastest route and
    // takes no action. Set TRUE the moment the flee move is launched so a park→resume (an OA fired on the
    // way out) simply ends the turn instead of re-fleeing. Mirrors cast_moving / conceal_move_launched.
    bool flee_move_launched{false};
    // Difficulty resolver park-safety: the strategy resolveStrategy chose when THIS turn launched, stamped
    // by runNpcTurn whenever the turn parks. The dynamic Level-4 resolution is state-dependent (it probes
    // the live planners), so a park→resume must reuse the strategy that launched the turn — re-resolving
    // after the game state changed mid-park could route the resume into the wrong executor and re-cast.
    // -1 = not stamped (fresh turn → resolve normally). Holds a NpcAutomationStrategy as int.
    int resolved_strategy{-1};
};

// One entry in the NPC-turn visual event stream. While runNpcTurn drives an automated turn the
// engine records what happens — moves with the actual route walked, action announcements, and
// attack/save outcomes — so the GUI can PLAY the turn BACK as an animation: the token slides
// along `path`, `text` typewriter-scrolls above the actor, and outcome flashes / HP-bar drops /
// corpse removal land in narrative order instead of teleport-and-done. Headless callers never
// drain the buffer (a fresh turn clears it, so it stays bounded). Drained — moved out and
// cleared — via CombatEngine::takeNpcVisualEvents().
struct NpcVisualEvent {
    enum Kind { Move = 0, Announce = 1, Outcome = 2 };
    int  kind{Move};
    int  agent_idx{-1};      // Move/Announce: the acting agent; Outcome: the AFFECTED target (flash anchor)
    int  target_idx{-1};     // Announce only: the action's target (-1 = none / area)
    std::vector<Cell> path;  // Move only: the route actually taken (origin → … → dest, inclusive)
    std::string text;        // Announce: "X attacks Y with Z!"; Outcome: "Hit (7)" / "Miss" / "Saved" / "Failed"
    bool good{false};        // Outcome only: green flash (Hit/Saved) vs red (Miss/Failed) — the GUI's
                             // established FLASH_GOOD/FLASH_BAD convention
    int  hp_after{-1};       // Outcome only: target's hp_cur AFTER the action applied (synced HP-bar update)
    bool died{false};        // Outcome only: target died/was removed by this action (corpse removal waits for this)
};

// How an NPC strategy ranks candidate targets (NPC_AUTOMATION_PLAN.md Steps 3-5).
enum class NpcTargetPriority {
    Nearest,    // closest by footprint distance, ties → lowest HP (Simple / PreferTargetCaster)
    LowestHp,   // lowest current HP, ties → closest (PreferRange focus-fires the weakest enemy)
};

// PreferHide (NPC_AUTOMATION_PLAN.md Step 7) conceal routes, in preference order (PREFER_HIDE_PLAN.md).
//   RouteA — bonus-action self-Invisibility: attack (action) → retreat → bonus-cast invis. Best.
//   RouteB — cunning-action Hide: attack (action) → move to no-LoS cover → bonus-action Hide.
//   RouteC — action self-Invisibility (alternates cast/attack across rounds).
//   RouteD — no stealth tools: plain PreferRange kite (never idle).
enum class NpcConcealRoute { RouteA=0, RouteB, RouteC, RouteD };

// Combat role an agent plays, derived from its weapons + spells (NPC_AUTOMATION_PLAN.md "Difficulty-level
// → strategy mapping"). The difficulty resolver maps role + level → strategy. Caster = knows at least one
// COMBAT-RELEVANT spell (the classification_ignore_spells config list filters out flavor/utility spells
// like Speak with Animals so a Centaur Warden doesn't classify as a caster); else Ranged = owns a ranged
// weapon; else Melee. Classification rules are deliberately coarse — refinement is a planned follow-up.
enum class NpcRole { Melee = 0, Ranged, Caster };

// The behavioural knobs that distinguish one NPC strategy from another, fed to the single shared
// turn executor runWeaponTurn. Each runNpcTurn dispatch case builds one of these from a strategy enum
// value; the executor itself is strategy-agnostic. Defaults reproduce the Simple (preferMelee) strategy.
struct NpcStrategyPolicy {
    bool prefer_caster      = false;   // restrict targets to enemy spellcasters when any are attackable (Step 4)
    bool prefer_ranged      = false;   // pick the best RANGED weapon (else fall back to best melee) (Step 5)
    bool kite               = false;   // position to MAXIMISE distance from enemies among in-range cells (Step 5)
    bool conceal            = false;   // after attacking, run the Conceal tail phase: hide/go-invisible each turn (Step 7)
    NpcTargetPriority priority = NpcTargetPriority::Nearest;
};

// The chosen AoE cast for a PreferAOE turn (NPC_AUTOMATION_PLAN.md Step 6): which spell to cast and the
// aim cell that maximizes the net enemies caught in its area. spell_idx == -1 means no AoE was worth
// casting (no available area spell catches at least one net enemy) → the turn falls back to weapons.
struct NpcAoePlan {
    int  spell_idx   = -1;   // index into the caster's spells list (== SpellAction.spell_idx)
    Cell aim{0, 0};          // aoe_col / aoe_row aim point
    int  net_enemies = 0;    // enemies caught minus allies caught (friendly-fire aware; 0 when spell_idx<0)
};

// Which family of caster turn is being driven (NPC_AUTOMATION_PLAN.md Steps 8-10). Selects the planner
// runCasterTurn calls; the executor itself (approach + single parkable cast + weapon fallback) is intent-
// agnostic, mirroring how NpcStrategyPolicy parameterizes the one shared runWeaponTurn.
enum class CasterIntent { Control, Heal, Support };

// Pre-attack probability analysis for one NPC-automation attack (reported to the combat log just
// before the swing). An ESTIMATE mirroring the engine's core to-hit math (attackModifier + bonus_hit,
// Sacred Weapon, exhaustion, Bless d4, crit threshold, nat-1 fumble, target base_ac) and the dominant
// condition-driven advantage/disadvantage sources of performAttack; exotic feat/subclass riders
// (Vex/Sap carries, Battle Master marks, flanking summons, …) are not folded in. Drop chance is the
// exact damage distribution (dice ⊗ target resist/vuln/immune multipliers + scaled flat mod, crit
// weighted) against hp_cur + temp_hp.
struct NpcAttackAnalysis {
    double p_hit{0.0};            // chance the attack hits (crit auto-hit and nat-1 auto-miss included)
    double p_drop_given_hit{0.0}; // chance a HIT drops the target to 0 HP
    bool   advantage{false};      // estimated roll state the probabilities were computed with
    bool   disadvantage{false};
};

// The chosen spell cast for a caster turn (PreferControl/Heal/Support), generalizing NpcAoePlan. A planner
// returns the best cast it can make FROM THE CURRENT CELL (range + LoS gated, like npcPlanAoeCast):
//   · spell_idx >= 0            → cast spell_idx at target_indices / aim this turn.
//   · spell_idx < 0, approach>=0 → nothing castable from here, but a worthwhile spell exists and could reach
//                                  agent[approach_target] by closing distance → runCasterTurn moves + re-plans.
//   · spell_idx < 0, approach<0  → no relevant spell at all → runCasterTurn falls back to a weapon turn.
struct NpcCastPlan {
    int  spell_idx = -1;              // index into the caster's spells list (== SpellAction.spell_idx)
    std::vector<int> target_indices; // chosen targets (Single: one; Multiple: up to num_targets)
    Cell aim{0, 0};                  // aoe_col / aoe_row aim point (area control spells; == target cell for Single)
    double score = 0.0;              // planner ranking score (net enemies / missing HP / buff count); 0 when spell_idx<0
    int  approach_target = -1;       // ally/enemy to close on when spell_idx<0 but a relevant spell is held; -1 = none
};

// ── Wild Magic Surge (College of Wild Magic) ─────────────────────────────────
// The engine ROLLS d100 on the curated surge table and classifies the effect band
// (1-10); applying the effect is the caller's job (effects range from a simple heal
// to harder cases — see known_limitations.md). effect == 0 means no surge happened
// (the caller was not a L3+ Wild Magic Sorcerer).
struct WildMagicSurgeResult {
    int d100_roll = 0;   // 1-100 rolled (0 = no surge)
    int effect    = 0;   // 1-10 table band (0 = no surge)
    std::string description;
};

// Result of offering a Wild Magic Surge (the trigger + roll phase, BEFORE the effect is applied).
// Lets the GUI present a choice for Controlled Chaos (L14: two rolled bands) and Tamed Surge (L18:
// any band). For a plain L3-13 surge `options` holds one band; resolveWildMagicSurge() then applies.
struct WildMagicSurgeOffer {
    bool surged          = false;  // did a surge actually trigger this cast?
    std::vector<int> options;      // candidate bands 1-10 (1 normally; 2 with Controlled Chaos)
    bool can_choose_any  = false;  // Tamed Surge (L18): caller may pick ANY band 1-10
    bool tides_expended  = false;  // pass back to resolveWildMagicSurge so it recharges Tides
};

// Central reaction-eligibility predicate: true iff this creature may still spend its Reaction right
// now. Unifies the three blockers scattered across ~40 gate sites — the reaction is spent
// (reaction_used), the creature is Incapacitated, or its reactions have been denied outright (Balor
// Lightning Blade → reactions_denied, which unlike reaction_used survives the target's own turn
// reset). A namespace-scope free function so both CombatEngine members and the file-local reaction
// helpers (d20ReactorBase, …) can call it. New reaction windows must gate through this so
// DenyReactions blocks them too.
[[nodiscard]] inline bool canTakeReaction(const Agent::Conditions& c) noexcept {
    return !c.reaction_used && !c.incapacitated && !c.reactions_denied;
}


}  // namespace rpg
