#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  combat.hpp  –  Self-contained D&D 5e combat engine
//
//  Design goals:
//   • No rendering dependencies — safe to run headlessly for RL training.
//   • Seeded PRNG so simulations are fully reproducible.
//   • Flat observation vector  (getBattleObservation) suitable for NN input.
//   • Discrete action space    (availableAttacks)     suitable for RL agents.
//   • Static helpers           (attackModifier, canAttack …) are pure functions
//     that can be called without instantiating a CombatEngine.
//
//  Typical training-loop usage:
//      rpg::CombatEngine engine{42};   // fixed seed → deterministic rollouts
//
//      while (not done) {
//          auto obs     = engine.getBattleObservation(bm, agent_idx, enemies);
//          auto actions = engine.availableAttacks(bm, agent_idx);
//          int  choice  = agent.selectAction(obs, actions);   // your NN here
//          auto result  = engine.executeAction(bm, actions[choice]);
//          float reward = result.hit ? result.total_damage : 0.f;
//          if (result.target_down) reward += 100.f;
//          agent.update(obs, choice, reward, ...);
//      }
// ─────────────────────────────────────────────────────────────────────────────

#include "weapon.hpp"
#include "spell.hpp"
#include "armor.hpp"
#include "agent.hpp"
#include "cell.hpp"            // Cell — stored by value in the reaction-system structs below
#include "message_logger.hpp"

#include <cstdint>
#include <format>
#include <functional>
#include <optional>
#include <random>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace rpg {

// Forward declarations (avoid pulling in the whole BattleMap header here).
class BattleMap;
struct Cell;
struct AgentConfig;
struct ActiveSpellEffect;
struct ActiveAgentCondition;
enum class MovementType;
enum class VisibilityLevel;        // defined in battle_map.hpp
enum class NpcAutomationStrategy;  // defined in battle_map.hpp (NPC automation turn driver)

// ─────────────────────────────────────────────────────────────────────────────
//  Hide result (Stealth check vs Perception)
// ─────────────────────────────────────────────────────────────────────────────
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
    // deducted in executeSpell. Implemented: Careful, Distant, Extended, Heightened,
    // Quickened, Seeking, Transmuted, Twinned. Deferred: Empowered. Subtle = flavor only.
    MetamagicOption metamagic = MetamagicNone;
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
    // PreferAOE (Step 6): set TRUE immediately before the single beginCast so a park-then-resume of the
    // OnDeclareCast window does NOT re-cast — submitDecision resolves the parked cast, then re-calls
    // run_npc_turn, which sees this flag and simply ends the turn (the blast already resolved).
    bool aoe_cast_launched{false};
    // PreferAOE approach: TRUE while an AoE caster is MOVING to bring enemies into range before casting
    // (an out-of-range AoE spell must never fall back to melee). If that approach move parks on an OA, the
    // resume re-enters runAoeTurn, sees this flag, and re-plans + casts from the new cell (no second move).
    bool aoe_moving{false};
    // Multiattack recipe segments pending AFTER the current (weapon_idx, attacks_remaining) one.
    // Each is (weapon_slot, count). Empty ⇒ legacy single-weapon multiattack.
    std::vector<std::pair<int,int>> pending_segments;
    // PreferHide (Step 7): the Conceal tail phase runs after the attack loop when policy.conceal is set.
    // These cache the chosen conceal route + spell and gate the parkable primitives on resume (mirrors
    // aoe_cast_launched / aoe_moving) so a park→resume does not re-move or re-cast.
    int  conceal_route{0};                // cached A/B/C/D route (NpcConcealRoute) so a resume is stable
    int  conceal_spell_idx{-1};           // chosen invis spell (route A bonus / route C action); -1 = none
    bool conceal_move_launched{false};    // post-attack cover move started (resume: don't re-move)
    bool conceal_act_launched{false};     // Hide/cast started (resume after Counterspell: don't re-cast)
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

// ─────────────────────────────────────────────────────────────────────────────
//  CombatEngine
// ─────────────────────────────────────────────────────────────────────────────
class CombatEngine {
public:
    // Pass seed = 0 to use a non-deterministic seed from std::random_device.
    explicit CombatEngine(uint32_t seed = 0);

    // ── Static / deterministic helpers (no RNG) ───────────────────────────

    // Total attack-roll modifier for a weapon used by a given attacker.
    // Respects finesse, thrown, and proficiency rules.
    [[nodiscard]] static int attackModifier(const Weapon& w,
                                             const Agent::Stats& s) noexcept;

    // Ability modifier that applies to damage rolls for this weapon.
    [[nodiscard]] static int damageAbilityMod(const Weapon& w,
                                               const Agent::Stats& s) noexcept;

    // True iff the weapon can reach at least one cell of the target's footprint
    // AND that cell has line-of-sight from the attacker.
    [[nodiscard]] static bool canAttack(const Weapon& w,
                                         const BattleMap& bm,
                                         Cell atk_origin, int atk_size,
                                         Cell tgt_origin, int tgt_size) noexcept;

    // True iff the attack should be made at disadvantage.
    // Currently: ranged (non-thrown) attacks beyond normal_range_ft.
    [[nodiscard]] static bool hasDisadvantage(const Weapon& w,
                                               const BattleMap& bm,
                                               Cell atk_origin, int atk_size,
                                               Cell tgt_origin, int tgt_size) noexcept;

    // HP modifiers — clamp hp_cur to [0, hp_max] and write back to the map.
    // Return the resulting hp_cur, or 0 for an out-of-range idx.
    // Non-static: the Relentless Rage (Barbarian L11) hook here needs the seeded roll(),
    // log_, saveModFor (auras), and agentName — all instance members.
    int damageAgent(BattleMap& bm, int idx, int amount) noexcept;
    static int healAgent  (BattleMap& bm, int idx, int amount) noexcept;

    // Lay on Hands (Paladin): spends from the "Lay on Hands" pool resource to heal a target.
    // Clamps the spent amount to the min of (pool remaining, target's HP deficit).
    // Returns actual HP healed (0 if nothing to heal, -1 if no pool remaining).
    static int layOnHands (BattleMap& bm, int caster_idx, int target_idx, int amount) noexcept;

    // Lucky (Origin feat) — spend one Luck Point to grant the agent Advantage on its next
    // d20 Test (via grantPendingAdvantage, consumed by the next d20 roll). Returns true if a
    // point was spent, false if the agent has the Lucky feat exhausted / no points remaining.
    bool spendLuckForAdvantage(BattleMap& bm, int idx);

    // One with Shadows (Warlock invocation 8): while in an area of Dim Light or Darkness,
    // cast Invisibility on self for free (no slot). Sets the Invisible condition (ends on the
    // Warlock's next attack/cast, like Invisibility). Returns true if applied, false if the
    // agent isn't an invocation-8 Warlock or isn't standing in dim/dark.
    bool applyOneWithShadows(BattleMap& bm, int idx) noexcept;

    // Sacred Weapon (Paladin Oath of Devotion): Bonus Action, spend 1 Channel Oath use to add
    // +CHA mod (min +1) to weapon attack rolls for 1 minute (10 rounds). Requires Oath of Devotion
    // and an available Channel Oath use. Returns the attack bonus granted, or -1 if it could not
    // be activated (wrong oath, no resource, or already active).
    int activateSacredWeapon(BattleMap& bm, int idx) noexcept;

    // Cleric Light Domain — Corona of Light (L17+): a Magic action that lights a 60-ft radius for 1
    // minute (10 rounds). While active, enemies within 60 ft have Disadvantage on saves vs the
    // caster's Fire/Radiant spells (applied in rollSpellSave). Returns true if activated, false if not
    // eligible (wrong class/domain/level). Sets corona_of_light_turns; ticked down in beginTurn.
    bool activateCoronaOfLight(BattleMap& bm, int idx) noexcept;

    // ── Sorcerer ──────────────────────────────────────────────────────────
    // Innate Sorcery (L1): Bonus Action, spend 1 use to gain +1 spell save DC and
    // advantage on spell attack rolls for 1 minute (10 rounds). Returns true if
    // activated, false otherwise (not a Sorcerer / no uses left).
    bool activateInnateSorcery(BattleMap& bm, int idx) noexcept;

    // Font of Magic (L2): convert a remaining spell slot of slot_level (1-9) into
    // slot_level Sorcery Points (capped at max). Returns new SP total, or -1 if it
    // could not be done (not a Sorcerer / no such slot).
    int convertSlotToSorceryPoints(BattleMap& bm, int idx, int slot_level) noexcept;

    // Font of Magic (L2): spend Sorcery Points to create a temporary spell slot of
    // slot_level (1-5; cost 2/3/5/6/7). The slot is cleared at the next long rest.
    // Returns remaining SP, or -1 if it could not be done (not a Sorcerer / not enough SP).
    int createSpellSlot(BattleMap& bm, int idx, int slot_level) noexcept;

    // Sorcerer Metamagic — Sorcery Point cost per option (2024 PHB).
    static int metamagicSpCost(MetamagicOption opt) noexcept;

    // Draconic L14 — Dragon Wings: grant fly speed = walk speed (persistent, no concentration).
    // Toggle: activating when already active (dragon_wings_active = true) resets fly speed to 0
    // and clears the flag. Returns true if the agent is a Draconic Sorcerer L14+.
    bool activateDragonWings(BattleMap& bm, int idx) noexcept;

    // Draconic L6 Elemental Affinity — resistance half (Bonus Action, 1 SP): spend 1 Sorcery Point
    // to gain resistance (0.5x) to the chosen draconic damage type for 1 hour (600 rounds in the sim).
    // Gate: Draconic L6+, draconic_affinity_type >= 0, >= 1 SP, not already active. Returns true if used.
    bool activateDraconicResistance(BattleMap& bm, int idx) noexcept;

    // Wild Magic — Bend Luck (Sorcerer L6+): spend 1 Sorcery Point to roll 1d4 and apply it
    // as a bonus (boost=true) or penalty (boost=false) to the next D20 Test, via the additive
    // pending_roll_bonus_ path. Returns the 1d4 value rolled, or 0 on failure (not a L6+ Wild
    // Magic Sorcerer, or not enough Sorcery Points).
    int sorcererBendLuck(BattleMap& bm, int idx, bool boost) noexcept;

    // Wild Magic Surge (Sorcerer L3+, College of Wild Magic): roll d100 on the curated surge
    // table and return the classified effect band (1-10) + description. The effect itself is
    // applied by the caller (see known_limitations.md). effect == 0 if the agent is not a
    // L3+ Wild Magic Sorcerer.
    WildMagicSurgeResult rollWildMagicSurge(BattleMap& bm, int idx) noexcept;

    // Curated Wild Magic Surge table text for an effect band (1-10); "" if out of range.
    static std::string wildMagicSurgeDescription(int effect) noexcept;

    // Apply the engine-handled portion of a Wild Magic Surge effect band. Currently only
    // band 1 (Plant Growth — Quartered difficult terrain in a sphere on the caster) is applied
    // here; other bands return false (their application is handled by the caller / not yet
    // wired). Returns true if the engine applied the effect.
    bool applyWildMagicSurgeEffect(BattleMap& bm, int idx, int effect) noexcept;

    // Tides of Chaos (Wild Magic Sorcerer L3+): spend the use to grant the caster Advantage on
    // their next D20 Test (via grantPendingAdvantage). One use, regained on a long rest OR when a
    // Wild Magic Surge fires (see maybeWildMagicSurge). Returns true if the use was spent.
    bool activateTidesOfChaos(BattleMap& bm, int idx) noexcept;

    // Clockwork L14 Trance of Order (Bonus Action). For 1 minute (10 rounds): attacks against this
    // sorcerer can't benefit from Advantage, and they treat their own d20 of 9-or-lower as a 10 on
    // D20 Tests (applyTranceFloor). Free 1/long rest via the "Trance of Order" Resource, else 5
    // Sorcery Points. Sets trance_of_order_turns = 10 and spends the bonus action. Returns true if used.
    bool activateTranceOfOrder(BattleMap& bm, int idx) noexcept;

    // Clockwork L6 Bastion of Law (Magic Action). Spend 1-5 Sorcery Points to ward `target_idx`
    // (self or a creature within 30 ft) with a pre-rolled (sp)d8 absorption pool stored in
    // Stats::bastion_ward. Overwrites any existing ward on the target. Returns the ward total
    // rolled, or -1 on failure (gating / range / not enough Sorcery Points).
    int activateBastionOfLaw(BattleMap& bm, int caster_idx, int target_idx, int sp) noexcept;

    // Bastion of Law absorption: reduce `dmg` by the remaining bastion_ward on `s`, decrementing
    // the ward (caller persists `s`). Returns the post-ward damage. Logs when the ward soaks. Called
    // at each damage-absorption site BEFORE temp HP. No-op when ward == 0 or dmg <= 0.
    int applyBastionWard(BattleMap& bm, int idx, Agent::Stats& s, int dmg) noexcept;

    // Clockwork L18 Clockwork Cavalcade (Magic Action). Each ally within 30 ft of the caster (and the
    // caster) regains 100 HP and has its active spell-applied conditions ended. Free 1/long rest via
    // the "Clockwork Cavalcade" Resource, else 7 Sorcery Points. Returns the number of creatures
    // affected, or -1 on failure (gating / no use & < 7 Sorcery Points).
    int clockworkCavalcade(BattleMap& bm, int caster_idx) noexcept;

    // Aberrant L14 Revelation in Flesh (Bonus Action). Spend 1 Sorcery Point to transform for 10
    // minutes (100 rounds): gain a fly speed (= walk) with hover, a swim speed (= walk), and
    // truesight 60 ft (see Invisible creatures). Snapshots the prior speeds/truesight and reverts them
    // on expiry (beginTurn) / long rest. Gate Sorcerer/AberrantPath/L14+. Returns true if activated.
    bool activateRevelationInFlesh(BattleMap& bm, int idx) noexcept;

    // Aberrant L18 Warping Implosion. Teleport the caster to (dest_col,dest_row) — an unoccupied cell
    // within 120 ft it can see — then every OTHER creature within 30 ft of the space it LEFT makes a
    // Dexterity save vs the sorcerer's spell DC, taking 3d10 Force (half on a success). Free 1/long
    // rest via the "Warping Implosion" Resource, else 5 Sorcery Points. Gate Aberrant L18+. Returns the
    // number of creatures damaged, or -1 on failure (gating / range / occupied dest / no use & < 5 SP).
    int warpingImplosion(BattleMap& bm, int caster_idx, int dest_col, int dest_row) noexcept;

    // Aberrant Mind L3+ Psionic Sorcery: spend `spell_level` Sorcery Points to cast a psionic-list
    // spell without consuming a spell slot. Gate: AberrantPath L3+, spell_level >= 1, >= spell_level SP.
    // Caller must pass free_cast=true on the SpellAction so C++ skips slot consumption. Returns true
    // if the SP were spent (false on gating or insufficient SP).
    bool spendSorceryPointsForSpell(BattleMap& bm, int idx, int spell_level) noexcept;

    // Wild Magic Surge trigger (Sorcerer L3+, Wild Magic). Call immediately after the caster
    // resolves a Sorcerer spell cast with a spell slot (level ≥ 1). Rolls 1d20: on a natural 20
    // — OR automatically if Tides of Chaos is currently expended — it rolls + applies a surge
    // (rollWildMagicSurge + applyWildMagicSurgeEffect) and recharges Tides of Chaos. Returns the
    // applied surge (effect band 1-10), or effect == 0 if no surge occurred / not eligible.
    WildMagicSurgeResult maybeWildMagicSurge(BattleMap& bm, int idx) noexcept;

    // Wild Magic Surge OFFER phase — same trigger logic as maybeWildMagicSurge (nat-20 or an
    // expended Tides of Chaos forces a surge) but it only ROLLS, it does not apply. With Controlled
    // Chaos (L14) it rolls the table twice so the caller can use either result; with Tamed Surge
    // (L18) it sets can_choose_any so the caller may replace the roll with any band 1-10. Pair with
    // resolveWildMagicSurge() to apply the chosen band. surged == false means no surge occurred.
    WildMagicSurgeOffer offerWildMagicSurge(BattleMap& bm, int idx) noexcept;

    // Apply a chosen Wild Magic Surge band (1-10) selected from a WildMagicSurgeOffer:
    // applyWildMagicSurgeEffect + (if tides_expended) recharge Tides of Chaos. Returns the applied
    // WildMagicSurgeResult (effect == 0 if the band is out of range).
    WildMagicSurgeResult resolveWildMagicSurge(BattleMap& bm, int idx, int effect,
                                               bool tides_expended) noexcept;

    // ── Per-agent turn count ──────────────────────────────────────────────
    //
    // The common case is exactly 1 turn per round; only store overrides.
    // Calling setAgentTurns(idx, 1) removes any override (restores default).

    // Number of turns agent[idx] takes each round (default 1).
    [[nodiscard]] int getAgentTurns(int idx) const noexcept;

    // Override the default.  turns must be >= 1.
    void setAgentTurns(int idx, int turns) noexcept;

    // Remove all per-agent overrides (every agent reverts to 1 turn/round).
    void clearAgentTurns() noexcept;

    // Calculate AC for an agent based on base AC, armor, shield, DEX, and conditions.
    [[nodiscard]] int calculateAC(const BattleMap& bm, int agent_idx) const noexcept;

    // True iff the agent is "holding a Shield" — a weapon slot contains a shield (Weapon::is_shield,
    // or the legacy convention of a weapon named "Shield"). Shared gate for Shield Master and the
    // shield-gated Fighting Styles (Interception, Protection, Unarmed Fighting).
    [[nodiscard]] bool isHoldingShield(const BattleMap& bm, int agent_idx) const noexcept;

    // Shield Master — bonus-action Shield Bash gate: the agent has the Shield Master feat, is holding a
    // Shield, and has a Bonus Action free. The shove itself reuses executeShove (no parallel path); the
    // caller is responsible for the "took the Attack action this turn" timing (GUI gates on action_used).
    [[nodiscard]] bool canShieldBash(const BattleMap& bm, int agent_idx) const noexcept;

    // Merge equipped armor damage multipliers into agent stats (most restrictive wins).
    // Call this once at combat start and whenever armor is equipped/removed mid-combat.
    void applyArmorMultipliers(BattleMap& bm, int agent_idx) noexcept;

    // ── Per-agent movement budget (current turn) ──────────────────────────
    //
    // Call beginTurn() when a combatant's turn starts to seed their movement
    // budget from their stats.  The Python GUI then calls spendWalk / spendFly
    // after each drag-and-drop move; getWalkRemaining / getFlyRemaining feed
    // back into BattleMap::reachable_cells() so the reach overlay shrinks
    // correctly as movement is consumed.
    //
    // Distances are always in feet (5 ft = 1 standard grid cell).

    // Remaining walk / fly / swim / burrow movement (feet) for the given agent this turn.
    [[nodiscard]] int getWalkRemaining(int agent_idx) const noexcept;
    [[nodiscard]] int getFlyRemaining (int agent_idx) const noexcept;
    [[nodiscard]] int getSwimRemaining(int agent_idx) const noexcept;
    [[nodiscard]] int getBurrowRemaining(int agent_idx) const noexcept;

    // Deduct feet from the movement budget.  Clamps to 0; never goes
    // negative.  Returns the amount actually spent (≤ feet if budget ran low).
    int spendWalk(int agent_idx, int feet) noexcept;
    int spendFly (int agent_idx, int feet) noexcept;
    int spendSwim(int agent_idx, int feet) noexcept;
    int spendBurrow(int agent_idx, int feet) noexcept;

    // Seed the engine-side movement budgets for an out-of-turn move (legendary Dash / DashHalf).
    // beginTurn normally seeds these; a legendary action grants movement outside the creature's
    // own turn, so the GUI seeds the budgets directly (feet, clamped to >= 0) before the move.
    void seedMoveBudgets(int agent_idx, int walk, int fly, int swim, int burrow) noexcept {
        walkRemaining_  [agent_idx] = std::max(0, walk);
        flyRemaining_   [agent_idx] = std::max(0, fly);
        swimRemaining_  [agent_idx] = std::max(0, swim);
        burrowRemaining_[agent_idx] = std::max(0, burrow);
    }

    // Clear all movement budgets (call at end of combat or start of new round).
    void clearMovement() noexcept;

    // ── Agent movement (checks spell effects on entry) ────────────────────────
    // Check if an agent can move (has Speed > 0, not grappled, etc.)
    // Used to determine if movement would trigger opportunity attacks.
    [[nodiscard]] bool canAgentMove(const BattleMap& bm, int idx) const noexcept;

    // Move an already-placed agent to a new grid origin using the specified movement type.
    // Returns false if the agent lacks sufficient budget or destination is blocked.
    // On successful move, checks for spell effects at destination and applies them.
    bool moveAgent(BattleMap& bm, int idx, Cell newOrigin, MovementType type) noexcept;

    // Jump an agent to a new location (ignores walls, deducts from walk budget).
    // is_running: true for running jump (full strength), false for standing jump (half strength).
    bool jumpAgent(BattleMap& bm, int idx, Cell newOrigin, bool is_running) noexcept;

    // Teleport an agent to a new location (checks that destination is not blocked by terrain).
    // Returns true if successful, false if destination is blocked or out of bounds.
    bool teleportAgent(BattleMap& bm, int idx, int target_col, int target_row) noexcept;

    // ── Reaction system / flow checkpoints ──────────
    // Start a (potentially) provoking move on the GUI/interactive path. Returns
    // Completed if no decision is needed, or AwaitingDecision if it parked at an OA
    // checkpoint — the GUI then polls pendingDecision() and resumes via submitDecision().
    FlowStatus beginMove(BattleMap& bm, int idx, Cell dest, MovementType type);
    // Resume a parked move with the chosen reaction (GUI routes a menu click here).
    FlowStatus submitDecision(BattleMap& bm, const ReactionResponse& resp);
    // Auto driver (RL/tests): run the whole move, resolving each checkpoint inline via the
    // installed CombatDecider (no decider → skip every reaction). Never suspends. Returns
    // the OA AttackResults produced along the way.
    std::vector<AttackResult> resolveMove(BattleMap& bm, int idx, Cell dest, MovementType type);
    // What the engine is parked on (active=false when not parked). GUI polls each frame.
    [[nodiscard]] const PendingDecision& pendingDecision() const noexcept { return pending_decision_; }

    // Interruptible spell cast: opens the OnDeclareCast window before the
    // spell resolves, so reactions (this pass: Shield vs Magic Missile) can change/cancel it.
    // beginCast is the GUI/interactive entry (suspends at a checkpoint); resolveCast is the auto/RL
    // driver (resolves each checkpoint inline via the decider). submitDecision (above) resumes either
    // an in-flight move or an in-flight cast. Returns the SpellResult via lastCastResult()/resolveCast.
    FlowStatus beginCast(BattleMap& bm, const SpellAction& action);
    SpellResult resolveCast(BattleMap& bm, const SpellAction& action);
    [[nodiscard]] const SpellResult& lastCastResult() const noexcept { return last_cast_result_; }
    // True if the most recent begin_cast/resolve_cast was countered (spell fizzled, slot retained).
    [[nodiscard]] bool lastCastCountered() const noexcept { return last_cast_countered_; }

    // Interruptible weapon attack: rolls the attack, then opens the
    // OnHit window so the target may cast Shield (+5 AC) to negate the hit before any damage. beginAttack
    // is the GUI/interactive entry (suspends at the Shield checkpoint); the auto/RL path stays on
    // executeAction (inline defender reaction via maybeDefenderOnHitInline). submitDecision resumes a parked attack
    // just like a move/cast. The finished result is read via lastAttackResult().
    FlowStatus beginAttack(BattleMap& bm, const Attack& action);
    [[nodiscard]] const AttackResult& lastAttackResult() const noexcept { return last_attack_result_; }

    // Shield (reaction): the reactor casts Shield — spend the lowest L1+ slot + its reaction, gain
    // +5 AC until its next turn and Magic Missile immunity. Returns false if it can't (no slot/etc.).
    bool applyShield(BattleMap& bm, int reactor_idx) noexcept;
    // Counterspell (reaction): the counterspeller spends its lowest L3+ slot + reaction; the original
    // caster makes a CON save vs the counterspeller's spell save DC. Returns true iff the cast is
    // countered (save failed) → the in-flight spell fizzles but keeps its slot (2024 rules).
    bool applyCounterspell(BattleMap& bm, int reactor_idx, int caster_idx) noexcept;

    // Check if a destination cell is valid for teleportation (in bounds, not blocked by terrain).
    // Returns true if the cell is valid, false if out of bounds or blocked.
    [[nodiscard]] bool isValidTeleportDestination(const BattleMap& bm, int col, int row) const noexcept;

    // Teleport multiple agents and place them in a circular pattern around the destination.
    // Places the first agent at dest_col, dest_row; subsequent agents are placed in expanding
    // circles around the destination (respecting terrain and bounds). Agents that can't fit
    // are skipped. Returns the number of agents successfully teleported.
    int placeTeleportedAgents(BattleMap& bm, const std::vector<int>& agent_indices,
                              int dest_col, int dest_row) noexcept;

    // ── Turn lifecycle (begin/execute/end) ─────────────────────────────────
    //
    // beginTurn() and endTurn() check which persistent spell effects an agent
    // is standing in, and apply appropriate damage/conditions based on the spell's
    // effects_on_begin_turn / effects_on_end_turn flags.

    // Initialize the agent's turn: seed movement budgets, reset conditions,
    // reset leveled spell cast flag, and apply persistent spell effects.
    // Returns TurnStartResult indicating if the turn should be skipped
    // (e.g., due to failed paralysis save).
    TurnStartResult beginTurn(BattleMap& bm, int agent_idx) noexcept;

    // Interruptible turn start: runs the beginTurn body, then opens the
    // OnTurnStartNearby window so nearby creatures may react (Sentinel strike / Branches of the Tree
    // grapple) to `agent_idx` starting its turn. `interactive=true` is the GUI entry (suspends at each
    // reactor — poll pending_decision(), resume via submit_decision()); `false` is the auto/RL driver
    // (resolves each reactor inline via the installed decider). Read the TurnStartResult via
    // lastTurnStartResult() once the flow Completes. The plain beginTurn() above stays the no-window path.
    FlowStatus beginTurnFlow(BattleMap& bm, int agent_idx, bool interactive);
    [[nodiscard]] const TurnStartResult& lastTurnStartResult() const noexcept { return in_flight_turn_.result; }

    // ── NPC automation turn driver (NPC_AUTOMATION_PLAN.md Step 2) ────────────
    // Drive one automated NPC's turn through the engine instead of requiring manual GUI control.
    // This is the dedicated turn-driver seam (NOT CombatDecider, which is a mid-flow oracle). It uses
    // the C++ resolution primitives (resolveAttack / executeSpell / movement budgets), never main.py's
    // interactive begin_attack / drag-to-move orchestration, so it is callable headless for RL rollouts.
    //
    // Returns FlowStatus: Completed (the NPC's turn fully resolved — the GUI then advances the turn), or
    // AwaitingDecision (parked at a human reaction/counter window — poll pending_decision(), resume via
    // submit_decision(), then call run_npc_turn again to continue). The driver always returns/yields and
    // never blocks in a loop.
    //
    // STEP 2 STUB: this currently no-ops (logs an auto-pass via resolveStrategy and spends nothing), then
    // Completes. Steps 3+ replace the body with per-strategy decision logic dispatched on resolveStrategy.
    FlowStatus runNpcTurn(BattleMap& bm, int agent_idx);

    // Resolve which decision algorithm an automated agent uses THIS turn. The single place the later
    // difficulty-level → role → strategy override will live (NPC_AUTOMATION_PLAN.md "Difficulty is an
    // OVERRIDE"). Today it returns the per-agent npc_automation_strategy field unchanged. runNpcTurn must
    // always go through this, never read the raw field, so the executors stay decoupled from the resolver.
    [[nodiscard]] NpcAutomationStrategy resolveStrategy(const BattleMap& bm, int agent_idx) const noexcept;

    // ── PreferHide conceal helpers (Step 7, PREFER_HIDE_PLAN.md CP1) ───────────────────────────
    // Public so tests / the GUI can query them read-only (bound in rpg_bindings.cpp).
    // Index (into the agent's spell list) of a castable spell that grants the Invisible condition to
    // the caster with casting time `want` (Action / BonusAction); prefers Greater Invisibility (it
    // persists through attacks). -1 if none. Uses availableCastableSpells so slot/uses gating matches.
    [[nodiscard]] int npcFindSelfInvisSpell(const BattleMap& bm, int agent_idx,
                                            Spell::CastingTime_t want) const noexcept;
    // Nearest reachable cell (live walk budget) with NO enemy line of sight to the agent's footprint —
    // "move to cover". Mirrors checkHide's enemy-LoS loop over reachableCells; geometry single-sourced.
    // `out` = the chosen cell; returns false when every reachable cell is exposed. Nearest = fewest steps.
    [[nodiscard]] bool npcFindCoverCell(const BattleMap& bm, int agent_idx, Cell& out) const noexcept;
    // Classify the conceal route (A/B/C/D per PREFER_HIDE_PLAN.md) for agent_idx from its current tools:
    // has_cunning_action, the two invis finders (bonus/action), and whether it is currently Invisible.
    [[nodiscard]] NpcConcealRoute npcClassifyConceal(const BattleMap& bm, int agent_idx) const noexcept;

    // Visualization seam (NPC_AUTOMATION_PLAN.md Step 2e). runNpcTurn calls renderAttack(...) when an NPC
    // action resolves so the GUI can later animate it (highlight attacker + target, ranged arrow, AoE
    // blink-then-resolve). SEAM ONLY — no animation now; headless leaves the hook unset (a no-op). The
    // GUI installs a Python callable via set_render_attack_hook.
    void setRenderAttackHook(std::function<void(int, int)> hook) noexcept { render_attack_hook_ = std::move(hook); }

    // OnTurnStartNearby eligibility + apply (declared public for tests / GUI gating).
    // Mirrors canRiposte's 5 ft reach test plus reaction-free/alive/!incapacitated. (Sentinel is NOT a
    // turn-start reaction — it provokes an OA on Disengage; see detectProvokes / Agent::Stats::has_sentinel.)
    [[nodiscard]] bool canBranchesOfTree(const BattleMap& bm, int reactor, int source) const; // has_branches_of_the_tree
    // Branches: spend the reaction; the source makes a STR save vs the reactor's spell save DC; on a
    // failure it is Grappled (escape DC = the same). Rolls directly → no nested window opens.
    bool         applyBranchesOfTree(BattleMap& bm, int reactor, int source);

    // World Tree "Vitality of the Tree" (Barbarian L3+, OnTurnStartNearby self-option): while raging,
    // at the start of its own turn the Barbarian may grant one creature within 10 ft Xd6 temp HP
    // (X = Rage Damage bonus, min 1). Free (not the reaction) but once per turn. canVitalityOfTheTree
    // gates class/subclass/level/raging/once-per-turn + a valid target in range; applyVitalityOfTheTree
    // rolls and grants to target_idx (tagging rage provenance so endRage clears it).
    [[nodiscard]] bool canVitalityOfTheTree(const BattleMap& bm, int source) const;
    bool               applyVitalityOfTheTree(BattleMap& bm, int source, int target);

    // Called when agent's turn ends: apply persistent spell effects marked
    // for end-of-turn (effects_on_end_turn == true).
    void endTurn(BattleMap& bm, int agent_idx) noexcept;

    // ── Agent stat and equipment management ────────────────────────────────
    //
    // These methods delegate to BattleMap but are logically owned by CombatEngine
    // since they concern agent combat configuration.

    void addAgentConfig(BattleMap& bm, AgentConfig cfg) noexcept;
    void applyAgentConfigs(BattleMap& bm) noexcept;

    [[nodiscard]] Agent::Stats getAgentStats(const BattleMap& bm, int idx) const noexcept;
    void setAgentStats(BattleMap& bm, int idx, Agent::Stats s) noexcept;

    [[nodiscard]] Agent::Conditions getAgentConditions(const BattleMap& bm, int idx) const noexcept;
    void setAgentConditions(BattleMap& bm, int idx, const Agent::Conditions& c) noexcept;

    // Apply paralyzed condition and its effects (incapacitated, speed 0).
    void applyParalyzed(BattleMap& bm, int idx) noexcept;
    void applyBlinded(BattleMap& bm, int idx) noexcept;
    void applyIncapacitated(BattleMap& bm, int idx) noexcept;
    void applyStunned(BattleMap& bm, int idx) noexcept;
    void applyCharmed(BattleMap& bm, int idx) noexcept;
    void dropAgentWeapons(BattleMap& bm, int idx) noexcept;
    void applyFrightened(BattleMap& bm, int idx) noexcept;
    void applyProne(BattleMap& bm, int idx) noexcept;
    void applyGrappled(BattleMap& bm, int target_idx, int grappler_idx, int escape_dc) noexcept;
    void applyHidden(BattleMap& bm, int idx) noexcept;  // set hidden condition
    void applyUnconscious(BattleMap& bm, int idx) noexcept;  // incapacitated, prone, speed 0, auto-fail STR/DEX saves
    // Inverse of going down: a creature that regains HP from 0 returns to consciousness
    // and resets its death saves (D&D 5e). No-op unless the agent is currently downed and
    // not truly dead. Call after any healing so a healed creature isn't skipped in initiative.
    // Static (touches only bm) so the static heal utilities (healAgent/layOnHands) can call it.
    static void reviveOnHeal(BattleMap& bm, int idx) noexcept;
    // Rogue Cunning Strike rider application (save + condition): Poison/Trip/Withdraw/KnockOut/Obscure.
    // Internal helper called by applyCunningStrikeEffect after the Sneak Attack dice are spent. result
    // is forwarded so the Assassin's Envenom Weapons (L13+) bonus 2d6 Poison (on a failed Poison save,
    // ignoring Poison Resistance) folds into the same AttackResult/target HP.
    void applyCunningStrikeRiders(BattleMap& bm, int attacker_idx, int target_idx,
                                  const std::vector<int>& effects, AttackResult& result) noexcept;
    void applyPoisoned(BattleMap& bm, int idx) noexcept;  // disadvantage on attacks and ability checks
    void applyDeafened(BattleMap& bm, int idx) noexcept;  // cannot hear; auto-fail ability checks requiring hearing
    void applyPetrified(BattleMap& bm, int idx) noexcept;  // incapacitated, speed 0, resistance to all damage, immune to poisoned
    void rollDeathSave(BattleMap& bm, int idx) noexcept;  // roll a death save for unconscious agent
    void standup(BattleMap& bm, int idx) noexcept;  // stand up from prone, costs half speed

    // ── Hide action (Stealth check vs Perception) ─────────────────────
    [[nodiscard]] HideResult checkHide(BattleMap& bm, int agent_idx, bool in_combat) noexcept;
    // Check if a hidden agent comes into LOS and gets detected by Perception.
    // Returns empty message if still hidden, or detection message if revealed.
    [[nodiscard]] std::string checkHiddenAgentDetection(BattleMap& bm, int agent_idx, bool in_combat) noexcept;

    // ── Darkness-based blinding ──────────────────────────────────────
    // Apply or remove Blinded condition based on agent's location obscuration.
    // Agents in Darkness without darkvision, or MagicalDarkness without devil's sight, become Blinded.
    void updateDarknessBlinding(BattleMap& bm, int agent_idx) noexcept;

    // ── Spell-Applied Agent Conditions ────────────────────────────────
    // Add an active spell-applied condition (e.g., Paralyzed from Hold Person).
    // Returns the condition ID for later removal.
    [[nodiscard]] int addAgentCondition(BattleMap& bm, ActiveAgentCondition cond) noexcept;
    // Get all active spell-applied conditions.
    [[nodiscard]] const std::vector<ActiveAgentCondition>& activeAgentConditions() const noexcept;
    // Decrement turns_remaining and handle condition expiration.
    // Returns list of removed condition ids.
    [[nodiscard]] std::vector<int> tickAgentConditions(BattleMap& bm) noexcept;
    // Decrement turns_remaining only for conditions cast by the given caster.
    // Duration is counted in the caster's turns, not absolute turns.
    // Returns list of removed condition ids.
    [[nodiscard]] std::vector<int> tickAgentConditionsForCaster(BattleMap& bm, int caster_idx) noexcept;
    // Remove a condition by id. Fires onConditionEnded (caster kickback) before erasing.
    void removeAgentCondition(BattleMap& bm, int condition_id) noexcept;

    // ── Delayed / stored effects (general mechanism) ──────────────────────
    // Detonate a planted delayed-trigger condition by its id: rolls its damage, applies the optional
    // save (delay_requires_save), deals the result to the affected agent, then removes the condition.
    // Powers Quivering Palm and any future stored-effect ability (Delayed Blast Fireball, etc.).
    // Returns the damage dealt, or -1 if the id is not a valid delayed-trigger condition.
    int triggerDelayedEffect(BattleMap& bm, int condition_id) noexcept;

    // Monk Way of the Open Hand L17 — plant Quivering Palm vibrations on target_idx after an Unarmed
    // Strike hit, spending Focus Points. Builds a delayed-trigger condition (10d12 Force, CON save for
    // half) that the monk later detonates via triggerDelayedEffect. Only one creature may be affected
    // at a time, so any prior vibrations this monk planted are ended first. Returns true on success.
    bool plantQuiveringPalm(BattleMap& bm, int monk_idx, int target_idx) noexcept;

    [[nodiscard]] std::vector<Weapon> getAgentWeapons(const BattleMap& bm, int idx) const noexcept;
    void setAgentWeapons(BattleMap& bm, int idx, std::vector<Weapon> weapons) noexcept;

    [[nodiscard]] std::array<Armor, 6> getAgentArmor(const BattleMap& bm, int idx) const noexcept;
    void setAgentArmor(BattleMap& bm, int idx, std::array<Armor, 6> armor) noexcept;

    // Check if armor piece meets STR requirement for the agent.
    // Returns true if armor has no STR requirement or agent meets it.
    [[nodiscard]] bool canEquipArmor(const BattleMap& bm, int agent_idx, const Armor& armor) const noexcept;

    [[nodiscard]] std::vector<Spell> getAgentSpells(const BattleMap& bm, int idx) const noexcept;
    void setAgentSpells(BattleMap& bm, int idx, std::vector<Spell> spells) noexcept;
    void addSpellToAgent(BattleMap& bm, int idx, Spell s) noexcept;
    void removeSpellFromAgent(BattleMap& bm, int idx, int spell_idx) noexcept;

    // Return agent name for logging; "agent[idx]" if idx is out of range.
    [[nodiscard]] std::string agentName(const BattleMap& bm, int idx) const noexcept;

    // NPC spell initialization: set is_npc=true and init uses_max/uses_remaining from spell groups.
    void initNpcSpellGroups(BattleMap& bm, int agent_idx,
                           const std::map<int, std::vector<std::string>>& groups) noexcept;

    // Helper: Check concentration save when target takes damage from a spell.
    // Returns true if concentration was lost, false otherwise.
    // damager_idx (optional): who dealt the damage. When known, a damager with the Mage Slayer feat
    // imposes Disadvantage on the save (Concentration Breaker); the concentrator's own War Caster feat
    // grants Advantage. Pass -1 (default) when the source is environmental / unknown.
    bool checkConcentrationOnDamage(BattleMap& bm, int target_idx, int damage, int damager_idx = -1) noexcept;

    // ── Visibility and Line of Sight ───────────────────────────────────────
    // Compute visibility from one agent to all others on the map.
    // Respects perception range (based on stats + lighting modifiers),
    // line-of-sight, and obscuration effects.
    // Caches results in visibilityMap_ for use by spells/attacks.
    void computeVisibility(BattleMap& bm, int agent_idx) noexcept;

    // Get the cached visibility level between two agents (from last computeVisibility call).
    // Returns Blocked if visibility hasn't been computed for this pair.
    [[nodiscard]] VisibilityLevel getVisibility(int source_idx, int target_idx) const noexcept;

    // True if `viewer` can perceive `target` for targeting purposes: a target with the
    // Invisible condition can only be perceived by a viewer with Truesight or Blindsight
    // whose range reaches it. Non-invisible targets are always perceivable here (geometric
    // line-of-sight is enforced separately). Used by availableAttacks / getBattleObservation
    // so the RL action space and observation agree with the GUI.
    [[nodiscard]] bool canPerceiveTarget(const BattleMap& bm, int viewer_idx, int target_idx) const noexcept;

    // True if two placed agents are allies: same NON-zero faction. Faction 0 is
    // neutral/unassigned — every neutral is its own faction, allied with no one
    // (so neutral-vs-neutral is NOT allied). Drives hide-from-enemies, sparing
    // allies from selective AoEs, and restricting heals to allies.
    [[nodiscard]] bool areAllies(const BattleMap& bm, int a_idx, int b_idx) const noexcept;

    // ── Paladin auras (team-scoped emanations) ─────────────────────────────
    // A Paladin's aura reaches itself and same-team allies within 10 ft (30 ft
    // at L18). The aura is suppressed while the Paladin is unconscious/incapacitated.
    // bestPaladinAura returns the strongest CHA-mod (min 1) bonus from any qualifying
    // Paladin of level >= min_level reaching agent_idx, or 0 if none.
    [[nodiscard]] int bestPaladinAura(const BattleMap& bm, int agent_idx, int min_level) const noexcept;
    // Aura of Protection (L6+): the bonus that agent_idx adds to every saving throw.
    [[nodiscard]] int auraSaveBonus(const BattleMap& bm, int agent_idx) const noexcept;
    // Aura of Courage (L10+): agent_idx can't be Frightened while in an allied Paladin's aura.
    [[nodiscard]] bool hasAuraOfCourage(const BattleMap& bm, int agent_idx) const noexcept;
    // Advantage emanation (data-driven, on Spell::grants_advantage_aura): true if agent_idx is
    // inside an active advantage-granting emanation it benefits from — i.e. it is the caster, or
    // a same-faction ally, within the spell's radius of a conscious caster whose persistent
    // emanation is active. Grants Advantage on attack rolls (determineAdvantage) and saving
    // throws (rollSpellSave). Continuous: re-evaluated at each roll, so it follows the caster
    // and ends when the effect is removed (concentration drop / expiry).
    [[nodiscard]] bool hasAdvantageAura(const BattleMap& bm, int agent_idx) const noexcept;
    // Canonical saving-throw modifier for agent_idx vs ability `ab`: ability modifier +
    // proficiency (if proficient) + aura bonuses. Single source of truth for every save site.
    [[nodiscard]] int saveModFor(const BattleMap& bm, int agent_idx, SaveAbility_t ab) const noexcept;
    // Indomitable Might (Barbarian L18): a STR saving throw total can't be lower than the
    // Barbarian's STR score. Returns the (possibly raised) total.
    [[nodiscard]] int applyIndomitableMight(const BattleMap& bm, int saver_idx, SaveAbility_t ab, int total) const noexcept;

    // Vistani Curse of Weakness: true when agent_idx is under a curse imposing Disadvantage on
    // saving throws tied to ability `ab`. Consulted at the combat-relevant save-roll sites.
    [[nodiscard]] bool curseSaveDisadvantage(const BattleMap& bm, int agent_idx, SaveAbility_t ab) const noexcept;

    // ── Message logging ────────────────────────────────────────────────────
    // Attach a MessageLogger to receive internal narrative messages (dice rolls,
    // reasons for conditions, etc.). Optional; null = silent.
    void setLogger(MessageLogger* logger) noexcept { logger_ = logger; }

    // Set the CombatDecider for decision points (GUI=Python subclass, RL/headless=nullptr).
    void setDecider(CombatDecider* d) noexcept { decider_ = d; }

    // Evoker "safe targets": creatures fully excluded from this caster's AoE spells
    // (no save, no damage, no conditions). Manually selected in the GUI for Evokers now;
    // intended to be auto-populated from the player's party later.
    void setSafeTargets(int caster_idx, std::vector<int> targets) noexcept {
        safeTargets_[caster_idx] = std::move(targets);
    }
    [[nodiscard]] std::vector<int> getSafeTargets(int caster_idx) const {
        auto it = safeTargets_.find(caster_idx);
        return it == safeTargets_.end() ? std::vector<int>{} : it->second;
    }

    // ── Dice rollers ──────────────────────────────────────────────────────
    int roll(int sides, int modifier = 0);            // 1dN + modifier
    int rollAdvantage(int sides, int modifier = 0);   // max(2dN) + modifier
    int rollDisadvantage(int sides, int modifier = 0);// min(2dN) + modifier

    // Grant one-shot advantage (adv=true) or disadvantage (adv=false) on the NEXT D20 Test,
    // via pending_advantage_. General "advantage on your next roll" hook (Tides of Chaos, etc.);
    // it reaches attacks, saves, and checks because they all bottom out in roll(20)/rollToHit.
    void grantPendingAdvantage(bool adv = true) noexcept { pending_advantage_ = adv ? 1 : -1; }

    // ── Core attack mechanics ─────────────────────────────────────────────

    // Check if an attacker is "threatened" (within 10 feet of any other agent).
    // Returns true if the attacker should have disadvantage on ranged attacks.
    [[nodiscard]] bool isThreatened(const BattleMap& bm, int attacker_idx) const noexcept;

    // Returns indices of non-incapacitated agents within reach_cells of target's footprint.
    // Used for opportunity attack detection (reach_cells = 1 for 5-ft melee reach).
    [[nodiscard]] std::vector<int> threateningAgents(const BattleMap& bm, int target_idx, int reach_cells = 1) const;

    // Roll to hit: fills in the attack-roll fields of an AttackResult.
    // Does NOT roll or apply damage.
    [[nodiscard]] AttackResult rollToHit(const Weapon& w,
                                          const Agent::Stats& attacker,
                                          int target_ac,
                                          bool advantage = false,
                                          bool disadvantage = false,
                                          int exhaustion_level = 0);

    // ── G5b feats — caster resistance-ignore / treat-1-as-2 (Elemental Adept + Poisoner) ──
    // effectiveMagicDamageMult: the target's multiplier for `type`, but Resistance (0 < m < 1) is
    // lifted to 1.0 when the caster ignores it — Poisoner (Poison, from any source) or Elemental
    // Adept (its chosen elements, spells only). Immunity (0.0) and Vulnerability are untouched (the
    // feats ignore Resistance only, not Immunity).
    [[nodiscard]] float effectiveMagicDamageMult(const Agent::Stats& caster, const Agent::Stats& target,
                                                 MagicDamage_t type, bool from_spell) const noexcept;
    // rollSpellTypeDamage: roll `num_dice` d`die_size`, applying Elemental Adept's "treat a 1 as a 2"
    // for the caster's chosen elements (spells only). Appends each die to `out_dice`; returns the sum.
    // empower_budget: when non-null and > 0, applies Empowered Spell metamagic (see rollDamageDice).
    int rollSpellTypeDamage(const Agent::Stats& caster, MagicDamage_t type,
                            int num_dice, int die_size, std::vector<int>& out_dice, bool from_spell,
                            int* empower_budget = nullptr) noexcept;

    // rollDamageDice: roll `num_dice` d`die_size`, append each die to `out_dice`, return the sum.
    // boost1to2 treats a rolled 1 as a 2 (Elemental Adept), on both initial and rerolled dice.
    // empower_budget: Sorcerer Empowered Spell — when non-null and > 0, reroll the lowest
    // below-average dice (greedy-optimal for expected value), up to the remaining budget,
    // keeping each new roll and decrementing the budget per die rerolled.
    int rollDamageDice(int num_dice, int die_size, std::vector<int>& out_dice,
                       bool boost1to2, int* empower_budget) noexcept;

    // Roll damage dice and populate the damage fields of an existing result.
    // Applies target's damage multipliers (resistance/vulnerability/immunity).
    // Call only when result.hit == true.
    // suppress_positive_mod: drop a positive ability modifier from damage (Cleave mastery —
    // "don't add your ability modifier unless it is negative"). A negative mod still applies.
    void rollDamage(const Weapon& w,
                    const Agent::Stats& attacker,
                    const Agent::Stats& target,
                    AttackResult& result,
                    bool suppress_positive_mod = false);

    // Resolve a complete attack (roll to hit, roll damage, compute result).
    // Pure with respect to the target: computes total_damage / hp_after but does
    // NOT mutate the target's HP. The caller applies and persists the damage.
    // attacker_conditions: attacker's conditions (used for Rage bonus, etc.)
    [[nodiscard]] AttackResult resolveAttack(const Weapon& w,
                                              const Agent& attacker,
                                              const Agent& target,
                                              bool advantage = false,
                                              bool disadvantage = false,
                                              bool suppress_positive_mod = false);

    // ── Class feature helpers ────────────────────────────────────────────

    // Get Barbarian Rage damage bonus based on level
    static int getRageDamageBonus(int level) noexcept {
        if (level >= 17) return 4;
        if (level >= 9)  return 3;
        return 2;
    }

    // Grant temporary HP with 5e max() semantics (temp HP never stacks — take the higher).
    // src_idx tags the granting Barbarian for rage-sourced THP (World Tree Vitality of the Tree)
    // so endRage can clear exactly it; pass -1 for any other source, which clears the provenance
    // when this grant wins. No-op if amount does not exceed current temp_hp.
    static void grantTempHp(Agent::Stats& s, int amount, int src_idx = -1) noexcept {
        if (amount > s.temp_hp) { s.temp_hp = amount; s.rage_thp_source_idx = src_idx; }
    }

    // Dark One's Blessing (Fiend Warlock L3): when an enemy drops to 0 HP, every conscious Fiend
    // warlock who either personally felled it (killer_idx == warlock) or is an ally of the killer
    // within 10 ft of the fallen enemy gains CHA-mod + Warlock-level temp HP (min 1). Call once
    // per enemy reduced to 0 HP, from any knockdown site (weapon, spell, etc.).
    void grantDarkOnesBlessing(BattleMap& bm, int victim_idx, int killer_idx) noexcept;

    // Barbarian Rage lifecycle methods
    // Activate Rage: set raging=true, apply BPS resistance (0.5x multiplier)
    void activateRage(BattleMap& bm, int idx);

    // Extend Rage: reset duration_remaining on Rage resource
    void extendRage(BattleMap& bm, int idx);

    // End Rage: set raging=false, clear BPS resistance (restore 1.0x multiplier)
    void endRage(BattleMap& bm, int idx);

    // Barbarian Path of the Berserker L10 — Intimidating Presence (Bonus Action):
    // Each creature of the Barbarian's choice within a 30-ft emanation makes a WIS save
    // (DC 8 + STR mod + PB) or is Frightened until the end of the Barbarian's next turn.
    // Usable PB times per long rest, or expend one Rage use. Spends a bonus action.
    bool useIntimidatingPresence(BattleMap& bm, int idx) noexcept;

    // Barbarian Path of the Zealot L10 — Zealous Presence (Bonus Action):
    // Up to 10 creatures of the Barbarian's choice (allies) within 60 ft gain Advantage on attack
    // rolls and saving throws until the start of the Barbarian's next turn.
    // Usable 1 time per long rest, or expend one Rage use. Spends a bonus action.
    bool useZealousPresence(BattleMap& bm, int idx) noexcept;

    // Celestial Warlock L14 — Searing Vengeance: when a Celestial warlock would make a death save at
    // the start of its turn, it may instead spring back to its feet — regaining half its HP maximum,
    // standing up, and searing every enemy within 30 ft for 2d8 + CHA radiant + Blinded (until the end
    // of the warlock's next turn). Once per long rest ("Searing Vengeance" resource). Auto-fires from
    // the start-of-turn death-save site. Returns true if it triggered (skip the normal death save).
    bool triggerSearingVengeance(BattleMap& bm, int idx) noexcept;

    // Great Old One Warlock L6 — Clairvoyant Combatant: as a Bonus Action, a GOO warlock makes telepathic
    // contact with one creature it can see within 60 ft, forcing a WIS save (vs the warlock's CHA spell
    // save DC). On a failure the warlock has Advantage on attack rolls against that creature, and the
    // creature has Disadvantage on attack rolls against the warlock, until the start of the warlock's next
    // turn (a directed "ClairvoyantCombatant" ActiveAgentCondition, caster=warlock, agent=target). Once per
    // short/long rest ("Clairvoyant Combatant" resource); when exhausted, a Pact Magic slot may be spent
    // instead. Returns true if it activated (use surfaced via a GUI bonus-action button).
    bool activateClairvoyantCombatant(BattleMap& bm, int warlock_idx, int target_idx) noexcept;

    // Barbarian Path of the Zealot L14 — Rage of the Gods: while raging, assume a divine-warrior
    // form (once per long rest) — Fly Speed = Speed (can hover), Resistance to Necrotic/Psychic/
    // Radiant. The form ends when Rage ends or the Barbarian drops to 0 HP. While the form is active,
    // the Barbarian may use the Revivification reaction (handled at the drop-to-0 site in applyDamage).
    bool activateRageOfTheGods(BattleMap& bm, int idx) noexcept;

    // Barbarian Path of the World Tree L14 — Travel along the Tree: while raging, teleport up to
    // 60 ft (or up to 150 ft once per Rage when long_range=true) to a visible unoccupied space.
    // Spends a bonus action. (Bringing willing allies on the 150-ft hop is deferred — see notes.)
    bool travelAlongTree(BattleMap& bm, int idx, int target_col, int target_row,
                         bool long_range) noexcept;

    // Barbarian Path of the Berserker L10 — Retaliation: when a creature within 5 ft damages this
    // Barbarian, they may spend their reaction to make one melee weapon attack back. The eligible
    // attacker is recorded in retaliation_target_idx (set in applyAttackResult). Returns the attack.
    AttackResult applyRetaliation(BattleMap& bm, int defender_idx) noexcept;

    // Apply Brutal Strike effects: damage + chosen effects (Forceful/Hamstring/Staggering/Sundering)
    // effects: vector of effect indices (0=Forceful, 1=Hamstring, 2=Staggering, 3=Sundering)
    void applyBrutalStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                const std::vector<int>& effects, AttackResult& result) noexcept;

    // Apply Rogue Sneak Attack + optional Cunning Strike riders out of band, after a qualifying hit
    // (cunning_strike_available). Rolls (sneak_dice − rider cost)d6, adds it to result/damage and the
    // target's HP, marks Sneak Attack used, then applies any rider conditions. effects: rider codes
    // (0=Poison 1=Trip 2=Withdraw 4=KnockOut 5=Obscure); empty = full Sneak Attack with no rider.
    // Invalid/over-budget rider sets are ignored (full Sneak Attack still applies, no rider).
    //
    // round_num (default -1 = caller doesn't track rounds): the current combat round (0 = first
    // round). Drives the Assassin subclass round-1 features folded into this Sneak Attack:
    //   · Assassinate (L3+): +Rogue-level flat damage on a first-round Sneak hit.
    //   · Envenom Weapons (L13+): the Poison rider costs 0 Sneak dice and adds 2d6 Poison ignoring
    //     Resistance (applied in applyCunningStrikeRiders on a failed save).
    //   · Death Strike (L17+): a first-round Sneak hit forces a CON save (DC 8 + DEX + PB); on a
    //     failure the whole attack's damage is doubled.
    void applyCunningStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                  const std::vector<int>& effects, AttackResult& result,
                                  int round_num = -1) noexcept;

    // ── Soulknife Rogue (subclass) ──────────────────────────────────────────
    // Soul Blades — Homing Strikes (L9): after a MISS with a Psychic Blade, spend 1 Psionic Energy
    // Die, roll it and add the result to the attack roll; if that converts the miss to a hit, roll
    // damage and apply it (the die is expended only when it causes a hit). Returns true iff it
    // converted to a hit. v1: a Homing-converted hit does NOT open the Sneak Attack window.
    bool applyHomingStrike(BattleMap& bm, int attacker_idx, int target_idx, int weapon_idx,
                           AttackResult& result) noexcept;

    // Soul Blades — Psychic Teleportation (L9): a Bonus Action; spend 1 Psionic Energy Die, roll it,
    // and teleport up to (10 × roll) feet to the target cell. Returns true on success (in range +
    // unoccupied). Spends the die only on a successful teleport.
    bool psychicTeleportation(BattleMap& bm, int idx, int target_col, int target_row) noexcept;

    // Psychic Veil (L13): a Magic action → gain the Invisible condition. Once per Long Rest, or by
    // expending 1 Psionic Energy Die. Returns true if activated.
    bool activatePsychicVeil(BattleMap& bm, int idx) noexcept;

    // Shadow Step (L6+): a Bonus Action teleport for Warrior of Shadow Monks. L6 requires dim/dark,
    // L11+ works from any light level. Sets shadow_step_advantage flag for next attack. Returns true
    // iff teleport succeeds. The GUI handles target-cell selection (like Psychic Teleportation).
    bool shadowStepTeleport(BattleMap& bm, int idx, int target_col, int target_row) noexcept;

    // Cloak of Shadows (L17): a Bonus Action for Warrior of Shadow Monks. Gain Invisible condition
    // in dim/dark light. Invisibility persists through attacks (doesn't end on action). Returns true
    // iff activated. Expires on turn start if agent moves to bright light.
    bool cloakOfShadows(BattleMap& bm, int idx) noexcept;

    // Trickery Domain Cleric — Invoke Duplicity duplicate movement (Bonus Action, later turns): move
    // the cleric's illusory duplicate (summon_spell == "Invoke Duplicity") up to 30 ft. Returns true
    // iff moved. Creation lives in the GUI (shares the summon-spawn path).
    bool moveDuplicate(BattleMap& bm, int cleric_idx, int dup_idx,
                       int target_col, int target_row) noexcept;

    // Trickster's Transposition (L6+): swap the cleric's position with their duplicate. No resource or
    // action cost (it rides on creating/moving the duplicate). Returns true iff swapped.
    bool swapWithDuplicate(BattleMap& bm, int cleric_idx, int dup_idx) noexcept;

    // Shadow Arts: Darkness (L3): a Warrior of Shadow Monk spends 1 Focus Point to fill a 15-ft-radius
    // Sphere (centered on the chosen point) with magical Darkness for 1 minute. The casting Monk can
    // see through their own Darkness (the light effect is tagged see-through for this Monk), so they
    // are not Blinded by it; other creatures inside without Devil's Sight gain the Blinded condition.
    // Returns the new light-effect id (>= 0) on success, or -1 on failure (wrong class/level/no focus).
    int shadowArtsDarkness(BattleMap& bm, int idx, int target_col, int target_row) noexcept;

    // ── Warrior of the Elements (Phase 3) ───────────────────────────────────────────────────────
    // Elemental Attunement (L3): Magic action + 1 Focus Point → for the rest of the encounter (the sim
    // doesn't track the 10-min duration; reset on a short/long rest) the Monk's unarmed strikes reach
    // +10 ft, deal the chosen element (Acid/Cold/Fire/Lightning/Thunder), and can push/pull the target
    // 10 ft. `element` is a MagicDamage_t value. Returns true on success, false on wrong class/level/no
    // focus / invalid element.
    bool activateElementalAttunement(BattleMap& bm, int idx, int element) noexcept;

    // Elemental Attunement push/pull rider: while attunement is active, an unarmed hit can push the
    // target 10 ft away (pull=false) or pull it 10 ft toward the Monk (pull=true). No save. Returns the
    // feet actually moved (0 if blocked/invalid).
    int elementalAttunementMove(BattleMap& bm, int attacker_idx, int target_idx, bool pull) noexcept;

    // Elemental Burst (L6): Magic action + 2 Focus Points → a 20-ft-radius sphere centered on the chosen
    // point. Each creature there (faction-aware: allies of the caster are spared) makes a DEX save vs the
    // Monk's Ki DC (8 + PB + WIS); on a failure it takes (Martial Arts die count) × d8 of the chosen
    // element, half on a success. `element` is a MagicDamage_t value. Returns true on success.
    bool elementalBurst(BattleMap& bm, int idx, int target_col, int target_row, int element) noexcept;

    // Rend Mind (L17): after a Psychic-Blade Sneak Attack, force a WIS save (DC 8 + DEX + PB) or be
    // Stunned for 1 minute (repeat the save at end of each of its turns). Once per Long Rest, or by
    // expending 3 Psionic Energy Dice. canRendMind gates availability; applyRendMind resolves it and
    // returns true iff the target is Stunned.
    [[nodiscard]] bool canRendMind(const BattleMap& bm, int attacker_idx) const noexcept;
    bool applyRendMind(BattleMap& bm, int attacker_idx, int target_idx) noexcept;

    // Cleric Blessed Strikes — Divine Strike: out-of-band rider after a qualifying weapon hit
    // (divine_strike_available). Rolls 1d8 (2d8 at L14) Radiant or Necrotic (radiant flag), adds it
    // to result/damage and the target's HP, marks Divine Strike used for the turn. Mirrors
    // applyBrutalStrikeEffect / applyCunningStrikeEffect.
    void applyDivineStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                 bool radiant, AttackResult& result) noexcept;

    // Paladin Divine Smite (on a melee/unarmed hit): spend a level-slot_level spell slot as a
    // Bonus Action to add (1 + min(slot_level,5))d8 Radiant, +1d8 vs Undead/Fiend. Requires
    // divine_smite_available, a free bonus action, the chosen slot, and no leveled spell cast
    // this turn; spends the slot + bonus action, sets leveled_spell_cast_this_turn and
    // divine_smite_used. Returns the Radiant damage dealt, or -1 if not allowed.
    int applyDivineSmiteEffect(BattleMap& bm, int attacker_idx, int target_idx,
                               int slot_level, AttackResult& result) noexcept;

    // Warlock Eldritch Smite (invocation 15, L5+, Pact of the Blade): on a pact-weapon hit, expend a
    // Pact Magic spell slot as a Bonus Action to add (slot_level + 1)d8 Force damage, and knock a
    // Huge-or-smaller target Prone. slot_level is the Warlock's pact slot level (pact_slot_level()).
    // Requires eldritch_smite_available, a free bonus action, a pact slot, and no leveled spell cast
    // this turn; spends the pact slot + bonus action, sets leveled_spell_cast_this_turn and
    // eldritch_smite_used. Returns the Force damage dealt, or -1 if not allowed.
    int applyEldritchSmiteEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                 int slot_level, AttackResult& result) noexcept;

    // Eldritch Knight War Magic (L7+): during the Attack action, one weapon attack may be replaced
    // by casting a spell. canUseWarMagic owns the class/subclass/level + once-per-Attack-action gate
    // (the "mid Attack action with attacks left" part is GUI turn-economy state); the spell itself is
    // cast through the normal executeSpell path. markWarMagicUsed sets the once-per gate; the GUI
    // clears war_magic_used when a fresh action-attack sequence seeds (Action Surge → another use).
    [[nodiscard]] bool canUseWarMagic(BattleMap& bm, int idx) const noexcept;
    void markWarMagicUsed(BattleMap& bm, int idx) noexcept;

    // Spell indices an EK may cast via War Magic: action-casting-time cantrips (L7+), plus level
    // 1-5 action spells at L18+ (Improved War Magic). Reuses availableCastableSpells, so the
    // slot / one-leveled-spell-per-turn rules already apply to the leveled case.
    [[nodiscard]] std::vector<int> availableWarMagicSpells(const BattleMap& bm, int idx) const;

    // Eldritch Knight Arcane Charge (L15): teleport up to 30 ft (the optional rider on Action
    // Surge). Validates EK L15+, the 30-ft range, and a clear destination, then teleports.
    // Returns feet moved (>=0) on success, or a negative code: -1 not eligible / invalid,
    // -2 out of range, -3 destination blocked.
    int applyArcaneCharge(BattleMap& bm, int idx, int target_col, int target_row) noexcept;

    // Psi Warrior Psionic Strike (on-hit): spend one Psionic Energy die to add Force damage
    // (die roll + INT mod) to a hit, once per turn. Mirrors applyDivineStrikeEffect. Requires
    // psionic_strike_available; clears it and sets psionic_strike_used.
    void applyPsionicStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx, AttackResult& result) noexcept;

    // Grappler feat — Punch-and-Grab (on-hit): after an Unarmed-Strike hit as part of the Attack action,
    // the attacker may ALSO attempt a Grapple this attack (normally you pick damage OR grapple), once per
    // turn. Routes the grapple through the shared resolveGrapple core (contested check, computed escape
    // DC) — never a parallel path. Requires grappler_punch_grab_available; clears it and sets
    // grappler_punch_grab_used. Returns the GrappleResult (invalid if the flag wasn't set).
    [[nodiscard]] GrappleResult applyPunchAndGrab(BattleMap& bm, int attacker_idx, int target_idx) noexcept;

    // Psi Warrior Protective Field (reaction): spend one Psionic Energy die + the defender's reaction
    // to reduce incoming damage by (die roll + INT mod), capped at damage_taken. Modeled as a post-hit
    // heal-back of the prevented amount. Returns the damage prevented, or -1 if it could not be used.
    int applyProtectiveField(BattleMap& bm, int defender_idx, int damage_taken) noexcept;

    // Psi Warrior Telekinetic Movement: spend the once-per-rest "Telekinetic Movement" use to push a
    // creature up to 30 ft straight away from the Psi Warrior. Returns feet moved, or -1 if unavailable.
    int applyTelekineticMovement(BattleMap& bm, int idx, int target_idx) noexcept;

    // War Domain — Guided Strike: a War Cleric L3+ (the attacker, or an ally within 30 ft who also
    // spends a Reaction) expends Channel Divinity to add +10 to a missed attack roll (result), turning
    // it into a hit when it now meets AC — in which case weapon damage is rolled and applied here.
    void applyGuidedStrike(BattleMap& bm, const Attack& action, int cleric_idx, AttackResult& result) noexcept;

    // Reckless Attack (Barbarian) — post-hoc entry point. After a miss the engine flags
    // reckless_reroll_available; the GUI prompts and calls this to commit Reckless (sets
    // reckless_attack → enemies gain advantage vs you until your next turn) and re-resolve the
    // same attack with advantage. Returns the fresh AttackResult. No-op (invalid result) if the
    // flag isn't set.
    [[nodiscard]] AttackResult applyRecklessReroll(BattleMap& bm, int attacker_idx,
                                                   int target_idx, int weapon_idx) noexcept;

    // Battle Master Riposte (on-miss DEFENDER reaction) — post-hoc entry. After a missing melee
    // attack the engine flags the target's riposte_available; the GUI prompts (or the auto/RL path
    // calls maybeRiposteInline) and invokes this to commit the riposte: spend the reaction + 1
    // Superiority Die, make a melee attack defender→attacker, and on a hit add the Superiority Die to
    // the damage. Returns the riposte AttackResult (invalid if the flag wasn't set / no die / no weapon).
    [[nodiscard]] AttackResult applyRiposte(BattleMap& bm, int defender_idx,
                                            int attacker_idx, int weapon_idx) noexcept;

    // Weapon Mastery — Push: a qualifying hit (push_available) shoves the target 10 ft straight
    // away from the attacker (Large or smaller). Clears the flag. Returns feet actually moved.
    int applyPush(BattleMap& bm, int attacker_idx, int target_idx) noexcept;

    // Weapon Mastery — Topple: a qualifying hit (topple_available) forces the target to make a
    // CON save (DC 8 + attacker's attack ability mod + prof bonus) or be knocked Prone. Clears
    // the flag. weapon_idx identifies the striking weapon (for the save DC's ability).
    ToppleResult applyTopple(BattleMap& bm, int attacker_idx, int target_idx, int weapon_idx) noexcept;

    // Monk Stunning Strike: a qualifying unarmed hit (stunning_strike_available) forces the target to
    // make a CON save (DC 8 + attacker's DEX mod + prof bonus) or be Stunned for 1 turn. Spends
    // 1 Focus Point. Clears the flag and sets stunning_strike_used.
    StunningStrikeResult applyStunningStrike(BattleMap& bm, int attacker_idx, int target_idx) noexcept;

    // Monk Warrior of the Open Hand: a qualifying Flurry hit (open_hand_rider_available) applies one of
    // three riders: Knockdown (STR save or Prone), Push (forceMoveAgent), or Deny Reaction (set reaction_used).
    // Spends 1 Focus Point. Clears the flag and sets open_hand_rider_used.
    OpenHandRiderResult applyOpenHandRider(BattleMap& bm, int attacker_idx, int target_idx, int option) noexcept;

    // Monk Warrior of Mercy — Hand of Healing (L3+): a Bonus Action that spends 1 Focus Point to heal a
    // creature within reach for (Martial Arts die + WIS mod). At L6 (Physician's Touch) it also ends one
    // of Blinded/Deafened/Paralyzed/Poisoned/Stunned on the target. Pass free=true (only honored at L11,
    // Flurry of Healing and Harm) to fold the heal into a Flurry strike: no Focus Point and no Bonus Action.
    HandOfHealingResult handOfHealing(BattleMap& bm, int monk_idx, int target_idx, bool free = false) noexcept;

    // Monk Warrior of Mercy — Hand of Harm (L3+): once per turn, after a qualifying unarmed hit
    // (hand_of_harm_available), spend 1 Focus Point to add (Martial Arts die + WIS mod) Necrotic damage to
    // the AttackResult and the target's HP. At L6 (Physician's Touch) the target also becomes Poisoned. At
    // L11 (Flurry of Healing and Harm) it costs no Focus Point and may be used any number of times per turn,
    // but only once per target. Mirrors applyPsionicStrikeEffect (deferred on-hit rider).
    void applyHandOfHarmEffect(BattleMap& bm, int attacker_idx, int target_idx, AttackResult& result) noexcept;

    // Battle Master Maneuver (on-hit): spend 1 Superiority Die and apply one of three riders:
    // 0=Trip (STR save or Prone), 1=Menacing (WIS save or Frightened), 2=Pushing (15 ft).
    // Clears maneuver_available. Returns a ManeuverResult with save details / push distance.
    ManeuverResult applyManeuverEffect(BattleMap& bm, int attacker_idx, int target_idx, int maneuver_type) noexcept;

    // Battle Master Sweeping Attack (on-hit): spend 1 Superiority Die to splash the same attack onto a
    // 2nd creature within 5 ft of the original target. If the original attack roll (result.total_roll)
    // would hit the 2nd creature's AC, it takes superiority-die damage of the attack's damage type.
    // Clears maneuver_available. action/result are the original (primary) attack.
    ManeuverResult applySweepingAttack(BattleMap& bm, const Attack& action, const AttackResult& result,
                                       int secondary_idx) noexcept;

    // Battle Master bonus-action maneuvers. Each spends 1 Superiority Die (returns false / 0 if none).
    //  · Rally: grant a creature within 30 ft Temporary HP = superiority die + your CHA modifier.
    //    Returns the temp HP granted (0 = could not — no die or bad index).
    int  applyRally(BattleMap& bm, int fighter_idx, int target_idx) noexcept;
    //  · Feinting Attack: feint a creature within 5 ft → Advantage on your next attack vs it this turn
    //    and that hit adds the die to damage (feint_target_idx; consumed in applyAttackResult).
    bool applyFeintingAttack(BattleMap& bm, int fighter_idx, int target_idx) noexcept;
    //  · Quick Toss: arm a superiority-die damage bonus on your next thrown-weapon attack this turn
    //    (quick_toss_die_pending). The GUI then makes the actual thrown attack.
    bool prepareQuickToss(BattleMap& bm, int fighter_idx) noexcept;

    // Battle Master Precision Attack (on-miss): spend 1 Superiority Die, add 1d8/d10 to the
    // attack roll, and recompute the hit (may convert a miss to a hit with full damage).
    // Clears maneuver_precision_available. Mutates result in place (mirrors applyGuidedStrike).
    void applyPrecisionAttackEffect(BattleMap& bm, const Attack& action, AttackResult& result) noexcept;

    // Monk Flurry of Blows: executes two bonus-action unarmed strikes against the same target,
    // optionally applying an Open Hand rider on each hit (option: 0=Knockdown, 1=Push, 2=DenyReaction, -1=None).
    // Spends 1 Focus Point. Returns both attack results and rider results.
    FlurryResult executeFlurryOfBlows(BattleMap& bm, int attacker_idx, int target_idx, int rider_option) noexcept;

    // Bonus-action attack sequence management: decrements bonus_attacks_remaining for an agent.
    // Returns true if more attacks are queued, false if sequence is exhausted.
    // Used by Flurry of Blows, Martial Arts, and other bonus-action multi-attacks.
    bool consumeBonusAttack(BattleMap& bm, int agent_idx) noexcept;

    // ── Bonus-action budget (general action economy) ─────────────────────
    // Every feature with a Bonus Action cost goes through these. The budget refills to
    // bonus_actions_max at the start of each turn (beginTurn + runRound). A feat that
    // grants an extra bonus action simply raises bonus_actions_max.
    [[nodiscard]] bool hasBonusAction(const BattleMap& bm, int agent_idx) const noexcept;
    // Spend one bonus action if available; returns true if spent, false if none remained.
    bool spendBonusAction(BattleMap& bm, int agent_idx) noexcept;
    // Refill bonus_actions_remaining = bonus_actions_max for the agent (start of turn).
    void resetBonusActions(BattleMap& bm, int agent_idx) noexcept;

    // Barbarian Primal Knowledge: check if agent can use STR for Acrobatics/Stealth while Raging
    // Returns true if: Barbarian L3+, Raging, and skill is "Acrobatics" or "Stealth"
    bool canUsePrimalKnowledge(const BattleMap& bm, int idx, const std::string& skill_name) const noexcept;

    // ── Diviner Wizard Portent Dice ──────────────────────────────────────
    // Use a portent die on the next roll: validates agent is Diviner, has dice, and
    // hasn't used portent this round. Sets pending_portent_die which CombatEngine::roll()
    // will return instead of rolling. Decrements the Portent Dice resource.
    // die_index: index into agent's portent_dice deque (0-based)
    // current_round: current round number for per-round limit enforcement
    // Returns true on success, false if agent/die is invalid or already used this round.
    [[nodiscard]] bool usePortentDie(BattleMap& bm, int agent_idx, int die_index, int current_round) noexcept;

    // Regenerate portent dice pool for a Diviner after long rest.
    // Rolls count d20s and populates agent's portent_dice deque.
    void regeneratePortentDice(BattleMap& bm, int agent_idx) noexcept;

    // ── Bardic Inspiration ────────────────────────────────────────────────
    // Grant a Bardic Inspiration die of size d (6/8/10/12) to a creature. Overwrites
    // any die it already holds (RAW: one Bardic Inspiration die at a time). The bard's
    // "Bardic Inspiration" resource is spent separately by the bonus-action caller.
    bool grantBardicDie(BattleMap& bm, int agent_idx, int d = 8) noexcept;

    // Spend the held Bardic Inspiration die: roll it, stash the result in
    // pending_roll_bonus_ so the NEXT d20 Test for that agent adds it, then clear the
    // held die. Returns the rolled value (0 if the agent holds no die).
    int useBardicDie(BattleMap& bm, int agent_idx) noexcept;

    // Combat Inspiration damage mode (Valor Bard L3+, any held die): roll the held Bardic
    // Inspiration die and fold it into pending_damage_bonus_ so the NEXT weapon damage roll
    // adds it, then clear the held die. Returns the rolled value (0 if no die held).
    int useBardicDieForDamage(BattleMap& bm, int agent_idx) noexcept;

    // Combat Inspiration AC mode (Valor Bard L3+, any held die): check if rolling the held
    // die + adding it to the target's AC would flip a hit to a miss. Actor must hold a die,
    // action must have hit, attack is not a crit. Returns true if the die WOULD flip the hit.
    bool canCombatInspirationAC(const BattleMap& bm, const Attack& action, const AttackResult& r) const;

    // Combat Inspiration AC mode apply: roll the held die, consume it, spend the reaction. Returns
    // the rolled value on success, or -1 on failure (no die, reaction already spent). The caller
    // compares the rolled value to the attack roll to determine if the hit is negated.
    int applyCombatInspirationAC(BattleMap& bm, int reactor_idx) noexcept;

    // Font of Inspiration (Bard L5+): expend a spell slot of slot_level (no action) to
    // regain one expended use of Bardic Inspiration. Returns the new Bardic Inspiration
    // count, or -1 on failure (not a L5+ Bard, no such slot, or already at max).
    int bardRegainInspirationFromSlot(BattleMap& bm, int agent_idx, int slot_level) noexcept;

    // Superior Inspiration (Bard L18+): at combat start, every qualifying Bard regains
    // Bardic Inspiration up to 2 if it has fewer. RNG-free; call once after rolling
    // initiative (mirrored in replay.py so checked replays stay in sync).
    void applySuperiorInspiration(BattleMap& bm) noexcept;

    // College of Lore — Cutting Words (Bard L3+): reaction that expends one use of Bardic
    // Inspiration to SUBTRACT the die from a creature's next D20 Test (the negative sibling
    // of useBardicDie — it primes pending_roll_bonus_ with -value). Returns the rolled
    // amount subtracted, or 0 on failure (not a L3+ Lore Bard, or no use left).
    int bardCuttingWords(BattleMap& bm, int bard_idx) noexcept;

    // College of Glamour — Mantle of Inspiration (Bard L3+): Bonus Action that expends one
    // use of Bardic Inspiration and rolls the Bardic Inspiration die ONCE; each chosen creature
    // gains Temporary HP equal to twice the number rolled (max() semantics, non-rage source).
    // The caller (GUI) supplies the chosen targets and validates the 60 ft range per click; this
    // caps the list to the bard's Charisma modifier (min 1) and skips the bard itself (2024 RAW:
    // "other creatures"). Returns the Temporary HP granted to each recipient, or 0 on failure
    // (not a L3+ College of Glamour Bard, or no Bardic Inspiration use left). The 2024 rider that
    // lets each recipient Reaction-move up to its Speed without provoking OAs is not modeled.
    int bardMantleOfInspiration(BattleMap& bm, int bard_idx,
                                const std::vector<int>& targets) noexcept;

    // College of Glamour — Beguiling Magic (Bard L3+): the once/long-rest benefit fired immediately
    // after the bard casts an Enchantment or Illusion spell with a slot (the GUI gates the school/slot
    // condition). Spends the "Beguiling Magic" resource, then forces a WIS save (vs the bard's spell
    // save DC) on the chosen target within 60 ft; on a failure the target gains the Charmed (use_frightened
    // == false) or Frightened (true) condition for 1 minute (10 rounds), repeating the WIS save at the
    // start of each of its turns. Returns true if the benefit was used (resource spent + save attempted),
    // false if it could not be used (not a L3+ Glamour Bard, no use left, bad/own/out-of-range target).
    bool bardBeguilingMagic(BattleMap& bm, int bard_idx, int target_idx, bool use_frightened) noexcept;

    // Restore the expended "Beguiling Magic" use by spending one Bardic Inspiration use (no action).
    // Returns the resource's new current count, or -1 on failure (not a Glamour Bard L3+, no Bardic
    // Inspiration use, or already full).
    int bardRestoreBeguilingMagic(BattleMap& bm, int bard_idx) noexcept;

    // College of Glamour — Mantle of Majesty (Bard L6+): Bonus Action that spends the once/long-rest
    // "Mantle of Majesty" resource, opens a 1-minute (10-round) "unearthly appearance" window
    // (mantle_majesty_turns = 10) and starts Concentration on the literal name "Mantle of Majesty"
    // (replacing any prior concentration). While the window is active the bard may re-cast Command as
    // a Bonus Action with no slot, and a creature Charmed by this bard auto-fails its save vs that
    // Command. The free Command cast itself is driven separately by the caller (SpellAction.free_cast).
    // Returns true on success, false if the agent is not a College of Glamour Bard L6+ or has no use.
    [[nodiscard]] bool activateMantleOfMajesty(BattleMap& bm, int bard_idx) noexcept;

    // Restore the expended "Mantle of Majesty" use by spending an unused level 3+ spell slot (no
    // action). Mirrors bardRegainInspirationFromSlot. Returns the resource's new current count, or
    // -1 on failure (not a Glamour Bard L6+, slot_level < 3, no such slot, or already full).
    int bardRestoreMantleOfMajestyFromSlot(BattleMap& bm, int bard_idx, int slot_level) noexcept;

    // College of Glamour — Unbreakable Majesty (Bard L14): Bonus Action that spends the once/long-rest
    // "Unbreakable Majesty" resource, opens a 1-minute (10-round) "majestic presence" window
    // (majestic_presence_turns = 10) and starts Concentration on the literal name "Unbreakable Majesty"
    // (replacing any prior concentration). While the window is active any creature that hits the bard
    // with a melee attack takes Psychic damage equal to the bard's CHA modifier (min 1) automatically,
    // and must succeed at a CHA save vs the bard's spell save DC or gain Disadvantage on the next save
    // throw vs the bard's spells (TODO: full rider impl). Returns true on success, false if the agent
    // is not a College of Glamour Bard L14+ or has no use.
    [[nodiscard]] bool activateUnbreakableMajesty(BattleMap& bm, int bard_idx) noexcept;

    // Restore the expended "Unbreakable Majesty" use by spending an unused level 3+ spell slot (no
    // action). Mirrors bardRestoreMantleOfMajestyFromSlot. Returns the resource's new current count, or
    // -1 on failure (not a Glamour Bard L14+, slot_level < 3, no such slot, or already full).
    int bardRestoreUnbreakableMajestyFromSlot(BattleMap& bm, int bard_idx, int slot_level) noexcept;

    // Apply the chosen Command word to a target that failed its save vs the Command spell.
    // word: 0=Drop, 1=Flee, 2=Grovel, 3=Halt, 4=Approach (anything else defaults to Halt). Reuses
    // existing mechanics: Drop = drop-weapons + Disarmed (until the bard's next turn); Flee/Approach
    // = a 1-turn movement restriction relative to the bard; Grovel = Prone; Halt = Incapacitated for
    // one turn. The movement/incapacitation conditions are keyed to bard_idx with a 1-turn duration so
    // they expire as the bard's next turn begins (tickAgentConditionsForCaster).
    void applyCommandEffect(BattleMap& bm, int bard_idx, int target_idx, int word) noexcept;

    // ── Abjurer Wizard Arcane Ward ────────────────────────────────────────
    // Expend a spell slot as a bonus action to charge Arcane Ward (L3+).
    // Adds 2 × slot_level HP to the ward (capped at max = 2 × level + INT mod).
    // Returns true on success, false if agent is not an Abjurer L3+ or has no ward.
    [[nodiscard]] bool expendArcaneWardSlot(BattleMap& bm, int agent_idx, int slot_level) noexcept;

    // ── Rest and Recovery ────────────────────────────────────────────────
    // Apply long rest to all agents: restore spell slots, resources, Portent Dice, etc.
    void applyLongRest(BattleMap& bm) noexcept;

    // Apply short rest to all agents: restore short-rest resources (Warlock Pact Magic
    // slots, Monk Ki, etc.). Does not restore long-rest-only resources.
    void applyShortRest(BattleMap& bm) noexcept;

    // ── High-level BattleMap integration ─────────────────────────────────

    // Validate an Attack (range + LoS), then call resolveAttack and
    // write the updated target stats back into the BattleMap.
    // Returns an invalid AttackResult (valid==false) if the action is illegal.
    [[nodiscard]] AttackResult executeAction(BattleMap& bm,
                                              const Attack& action);

    // executeAction is split so a defender reaction (Shield) can fire between the roll and damage:
    //   determineAdvantage → validate the attack + compute advantage/disadvantage + pre-roll snapshots
    //     into `s` (returns false for an illegal/blocked attack; STOPS before the roll — the caller
    //     then does s.r = resolveAttack(...)).
    //   applyAttackResult → phase B: apply the rolled result's consequences (on-hit/on-miss riders,
    //     damage, concentration, conditions, downstate). Re-fetches working stats fresh, so a Shield
    //     cast in the window is reflected. Both are also the building blocks of beginAttack (3b).
    [[nodiscard]] bool determineAdvantage(BattleMap& bm, InFlightAttack& s);
    [[nodiscard]] AttackResult applyAttackResult(BattleMap& bm, InFlightAttack& s);

    // The defender's OnHit reaction options against a just-resolved attack: Shield (negate, if its
    // +5 AC would flip the hit to a miss) and Uncanny Dodge (halve the damage). Both cost the
    // defender's one reaction, so the menu offers at most one effective choice. Shared by the inline
    // (auto/RL) and suspendable (advanceAttack/GUI) paths so they gate identically; always ends with
    // Skip when any real option exists (empty otherwise).
    [[nodiscard]] std::vector<ReactionOption> defenderOnHitOptions(const BattleMap& bm,
                                                                   const Attack& action,
                                                                   const AttackResult& r) const;

    // Defender OnHit reaction vs an attack (Uncanny Dodge folded in).
    // Called right after the attack roll resolves, BEFORE any damage/concentration. If the target can
    // cast Shield (its +5 AC turns the hit into a miss) or use Uncanny Dodge (halve the damage), offer
    // the reaction; on accept, spend the resource+reaction and either negate the hit (Shield → r.hit
    // false, no damage/concentration; per DM ruling a genuine miss) or halve r.total_damage (Uncanny
    // Dodge). Auto/RL path (inline via decider_); the GUI suspend path arrives with beginAttack (3b).
    // Returns true iff a reaction fired (the caller must then re-fetch the target's stats, since this
    // mutates the target's slot/AC/reaction and executeAction re-persists a pre-window snapshot).
    bool maybeDefenderOnHitInline(BattleMap& bm, const Attack& action, AttackResult& r);

    // Rogue Uncanny Dodge (L5+): can this target halve an attack's damage right now (reaction free,
    // not incapacitated, alive)? Eligibility gate for the OnHit defender window.
    [[nodiscard]] bool canUncannyDodge(const BattleMap& bm, int target_idx) const;

    // Apply Uncanny Dodge: halve r.total_damage (round down), spend the reactor's reaction, and record
    // the reduction in r.damage_breakdown (negative). Re-validates canUncannyDodge. Returns true on use.
    bool applyUncannyDodge(BattleMap& bm, int reactor_idx, AttackResult& r);

    // Superior Hunter's Defense (Hunter Ranger L15) — OnHit defender reaction. When the Hunter takes
    // damage it may spend its reaction to resist (halve) that damage. Eligibility + apply mirror
    // Uncanny Dodge; the "Resistance to that type until end of turn" persistence is v1-simplified to
    // the triggering instance (see known_limitations.md).
    [[nodiscard]] bool canSuperiorHunterDefense(const BattleMap& bm, int target_idx) const;
    bool applySuperiorHunterDefense(BattleMap& bm, int reactor_idx, AttackResult& r);

    // Battle Master Parry — OnHit defender reaction. When a melee attack damages the Battle Master, it
    // may spend its reaction + 1 Superiority Die to reduce the damage by (die roll + DEX modifier).
    // canParry gates class/die/reaction/alive; the melee-attack check is applied at the call site.
    [[nodiscard]] bool canParry(const BattleMap& bm, int defender_idx) const;
    bool applyParry(BattleMap& bm, int reactor_idx, AttackResult& r);

    // Monk Deflect Attacks (L3+) — OnHit defender reaction. When hit by an attack that deals
    // Bludgeoning/Piercing/Slashing damage, spend the reaction to reduce that damage by
    // 1d10 + DEX modifier + Monk level. At L13 (Deflect Energy) it applies to an attack of ANY
    // damage type. canDeflectAttacks gates class/level/reaction/alive; the damage-type gate (and the
    // L13 widening) is enforced inside applyDeflectAttacks and at the offer site. No Focus cost for the
    // reduction; the redirect-as-a-ranged-attack clause is deferred (see known_limitations.md).
    [[nodiscard]] bool canDeflectAttacks(const BattleMap& bm, int defender_idx) const;
    bool applyDeflectAttacks(BattleMap& bm, int reactor_idx, AttackResult& r);

    // Defensive Duelist (feat) — OnHit defender reaction. When a creature HITS the target with a MELEE
    // attack and the target wields a Finesse melee weapon, it may add its Proficiency Bonus to AC against
    // that attack, possibly flipping the hit to a miss. Like Shield: offered only on a non-crit hit whose
    // +PB could actually flip the outcome, and only with the reaction free. On accept the caller sets
    // r.hit = false (a genuine miss, per the same DM ruling as Shield).
    [[nodiscard]] bool canDefensiveDuelist(const BattleMap& bm, const Attack& action, const AttackResult& r) const;

    // Apply Defensive Duelist: spend the reactor's reaction. Re-validates nothing (the caller gated via
    // canDefensiveDuelist) beyond the reaction; the caller flips r.hit. Returns true iff the reaction fired.
    bool applyDefensiveDuelist(BattleMap& bm, int reactor_idx) noexcept;

    // War Domain Guided Strike eligibility for one cleric vs a just-missed attack: WarDomain L3+ with a
    // Channel Divinity use, and either the attacker itself or an ally within 30 ft whose reaction is
    // free. The miss must not be a natural 1. Used to set guided_strike_available (GUI) and to enumerate
    // OnMiss reactors (maybeGuidedStrikeInline).
    [[nodiscard]] bool canGuidedStrike(const BattleMap& bm, const Attack& action, int cleric_idx) const;

    // War Domain Guided Strike — the OnMiss sibling of maybeGuidedStrikeInline's Riposte counterpart
    // (auto/RL only; the GUI gets the deferred-flag prompt via guided_strike_available). On a miss,
    // enumerates eligible War Clerics, builds a ReactionCtx{OnMiss} with a Feature("GuidedStrike")
    // option for each, asks decider_->chooseReaction, and on accept calls applyGuidedStrike (+10, may
    // turn the miss into a hit). Called from executeAction AFTER applyAttackResult and BEFORE
    // maybeRiposteInline (a guided hit forecloses the defender's riposte). Returns true iff it fired.
    bool maybeGuidedStrikeInline(BattleMap& bm, const Attack& action, AttackResult& r);

    // Battle Master Riposte — the OnMiss sibling of maybeDefenderOnHitInline (auto/RL only; the GUI,
    // with no decider, gets the deferred-flag prompt via riposte_available). Gated on the defender's
    // riposte_available flag (set by applyAttackResult on a melee miss); builds a ReactionCtx{OnMiss}
    // with a Feature("Riposte") option, asks decider_->chooseReaction, and on accept calls applyRiposte.
    // Called from executeAction AFTER applyAttackResult, so the riposte is a fresh top-level attack
    // (no nesting / decision stack). Returns true iff a riposte was made.
    bool maybeRiposteInline(BattleMap& bm, const Attack& action, AttackResult& r);

    // Sentinel feat (Guardian) eligibility for one bystander vs an attack just made against someone
    // else: the bystander has the Sentinel feat, its reaction is free, it's alive/not incapacitated,
    // it wields a melee weapon, the attacking creature is within its 5 ft reach, and neither the
    // attacker nor the attack's target is itself (RAW: the target must not have the Sentinel feat).
    // Used to set sentinel_guard_available (GUI) and to enumerate OnAllyAttacked reactors
    // (maybeSentinelGuardInline).
    [[nodiscard]] bool canSentinelGuard(const BattleMap& bm, const Attack& action, int sentinel_idx) const;

    // Sentinel Guardian (OnAllyAttacked) — the bystander sibling of maybeRiposteInline (auto/RL only;
    // the GUI gets the deferred-flag prompt via sentinel_guard_available). After an attack resolves,
    // enumerates eligible Sentinels adjacent to the attacker, builds a ReactionCtx{OnAllyAttacked} with
    // a Feature("SentinelGuard") option, asks decider_->chooseReaction, and on accept calls
    // applySentinelGuard (a melee attack back at the attacker). Called from executeAction AFTER the
    // attack fully resolves; resolving_sentinel_guard_ suppresses a guard-of-a-guard (the counter-attack
    // would otherwise re-open this window). Returns true iff a guard was made.
    bool maybeSentinelGuardInline(BattleMap& bm, const Attack& action, AttackResult& r);

    // Apply Sentinel Guardian: the Sentinel makes a melee attack against the attacking creature and
    // spends its reaction. Re-validates the reaction is free. Returns the counter-attack's result.
    [[nodiscard]] AttackResult applySentinelGuard(BattleMap& bm, int sentinel_idx,
                                                  int attacker_idx, int weapon_idx) noexcept;

    // Interception fighting style (OnAllyAttacked bystander damage-reduction). RAW 2024: when a creature
    // you can see hits a target OTHER than you within 5 ft of you with an attack roll, you may use your
    // reaction to reduce that target's damage by 1d10 + PB (min 0); you must be holding a Shield or a
    // Simple/Martial weapon. canIntercept gates one bystander: has the Interception feat, reaction free,
    // alive/not incapacitated, holding a shield-or-weapon, within 5 ft of the (still-standing) target,
    // can perceive the attacker, and != attacker/target. Modeled as a post-hit heal-back (mirrors
    // applyProtectiveField), so v1 cannot save a target dropped to 0 by the hit (see known_limitations).
    [[nodiscard]] bool canIntercept(const BattleMap& bm, const Attack& action,
                                    int interceptor_idx, int damage_taken) const;

    // Apply Interception: roll 1d10 + PB, heal the target back by min(reduction, damage_taken), spend the
    // interceptor's reaction. Re-validates the reaction is free + feat. Returns the damage prevented (or -1).
    int applyInterception(BattleMap& bm, int interceptor_idx, int target_idx, int damage_taken) noexcept;

    // Interception (OnAllyAttacked) — the damage-reduction sibling of maybeSentinelGuardInline (auto/RL
    // only; the GUI scans via can_intercept + _offer_interception). After a hit resolves, enumerates
    // eligible interceptors within 5 ft of the target, offers a ReactionCtx{OnAllyAttacked}, and on accept
    // calls applyInterception. Called from executeAction AFTER the attack applies. Returns true iff used.
    bool maybeInterceptionInline(BattleMap& bm, const Attack& action, AttackResult& r);

    // Spell-attack analog of the weapon to-hit roller. Re-fetches caster/target/agents from `bm`,
    // applies the same advantage/disadvantage conditions executeSpell's AttackRoll branch used, rolls
    // the d20 (+ Seeking reroll if applied_metamagic), and returns the resolved to-hit. Pulled out of
    // executeSpell so a single-target attack spell can roll the to-hit ahead of the OnHit Shield window
    // (advanceCast) and have executeSpell consume the same roll (the spell analog of resolveAttack).
    SpellToHit rollSpellAttack(BattleMap& bm, const SpellAction& action, int tgt_idx,
                               MetamagicOption applied_metamagic);

    // Spell-save analog of rollSpellAttack. Re-fetches caster/target/agents,
    // reproduces executeSpell's Save-branch advantage/disadvantage (target conditions + Heightened +
    // Eldritch Strike [CONSUMES the tag, exactly once] + Danger Sense) and the paralyzed/stunned/
    // unconscious STR/DEX auto-fail, rolls the d20, and returns the resolved SpellSave. Does NOT roll
    // damage or apply conditions. Pulled out of executeSpell so a Save-type spell can pre-roll every
    // target's save ahead of the OnSaveFail window (advanceCast) and have executeSpell consume the same
    // (possibly rerolled) result.
    SpellSave rollSpellSave(BattleMap& bm, const SpellAction& action, int tgt_idx,
                            MetamagicOption applied_metamagic);

    // Would casting Shield flip this spell-attack hit to a miss, and can the target do it right now?
    // Value-based sibling of shouldOfferDefenderShield (which takes a weapon AttackResult).
    [[nodiscard]] bool shouldOfferSpellShield(const BattleMap& bm, int tgt_idx,
                                              const SpellToHit& th) const;

    // Inline defender Shield vs a spell attack (auto/RL path + GUI multi-beam). Mirrors
    // maybeDefenderOnHitInline: if shouldOfferSpellShield, decide via decider_ when one is installed
    // (RL/headless/tests), else AUTO-TAKE the Shield (GUI multi-beam attack spells have no per-beam
    // decision cursor yet — documented in known_limitations.md). On accept, applyShield + recompute
    // th.hit against the new (+5) AC. Returns true iff Shield was cast. NOT used for the single-target
    // GUI case — that suspends at the OnHit window in advanceCast instead.
    bool maybeDefenderShieldInlineSpell(BattleMap& bm, const SpellAction& action, int tgt_idx,
                                        SpellToHit& th);

    // ── Initiative ────────────────────────────────────────────────────────
    //
    // Roll initiative for every living agent in the BattleMap (hp_cur > 0).
    // Each roll is d20 + DEX modifier [+ prof_bonus if initiative_prof].
    // Returns entries sorted descending by total; ties broken by modifier
    // then by agent_idx.  Call once at combat start; reuse the order for
    // all subsequent runRound() calls.
    std::vector<InitiativeEntry> rollInitiative(const BattleMap& bm);
    // Single-agent Initiative roll for deploying on-deck reinforcements (see .cpp).
    InitiativeEntry rollInitiativeFor(const BattleMap& bm, int agent_idx);

    // Alert (Origin feat) — Initiative Swap: immediately after rolling Initiative, swap
    // your Initiative with a willing ally's. Returns a copy of `order` with the two agents'
    // totals exchanged and re-sorted; returns it unchanged if either index is absent.
    // (The willing-ally / not-Incapacitated constraint is left to the caller/GUI.)
    std::vector<InitiativeEntry> swapInitiative(std::vector<InitiativeEntry> order,
                                                int agent_a, int agent_b) const;

    // ── Round execution ───────────────────────────────────────────────────
    //
    // Execute one full combat round from a caller-supplied list of turns.
    //
    // For each TurnActions entry (in the order supplied):
    //   1. Skip the turn entirely if the agent's hp_cur <= 0 (incapacitated).
    //   2. Call agent->action().
    //      If an Attack is attached, resolve it via executeAction().
    //      The targeted agent's reaction() is then triggered.
    //   3. Call agent->bonusAction().
    //      Same: resolve the Attack if present, trigger target's reaction().
    //   4. Call agent->walk().
    //   5. Call agent->fly().
    //
    // Callers are responsible for ordering the turns (initiative) and for
    // repeating an agent's entry when getAgentTurns(idx) > 1.
    //
    // Returns one AttackResult per resolved Attack (hits and misses).
    std::vector<AttackResult> runRound(BattleMap& bm,
                                       const std::vector<TurnActions>& turns);

    // ── Spell mechanics ───────────────────────────────────────────────────

    // Execute a spell cast: validates range/LoS, rolls to hit or saving throw,
    // applies damage/healing to each target, and writes stats back into the map.
    // For duration > 1, also pushes an ActiveEffect (apply per-turn via tickEffects).
    // Returns an invalid SpellResult (valid==false) if the action is illegal.
    [[nodiscard]] SpellResult executeSpell(BattleMap& bm,
                                           const SpellAction& action);

    // Drop concentration for the given agent: removes terrain, spell effects, conditions.
    [[nodiscard]] DropConcentrationResult dropConcentration(BattleMap& bm, int agent_idx);

    // Drop concentration for every concentrating agent (e.g. on End Combat).
    void clearAllConcentration(BattleMap& bm);

    // Warlock Magical Cunning (L2+): recover expended Pact Magic slots up to ceil(max/2)
    // — or all of them at L20 (Eldritch Master) — once per long rest. Returns true if used.
    bool useMagicalCunning(BattleMap& bm, int agent_idx);

    // Celestial Warlock Healing Light (L3+): spend d6 healing dice from the pool.
    // Validates healer is Celestial L3+, clamps num_dice, spends from resource, rolls and heals target.
    // Returns HP healed (0 if invalid).
    int useHealingLight(BattleMap& bm, int healer_idx, int target_idx, int num_dice);

    // Cleric Turn Undead (Channel Divinity, L2+): each Undead within 30 ft makes a WIS save;
    // on a failure it is Frightened + Incapacitated for 1 minute (ends if it takes damage).
    // Sear Undead (L5+) also deals WIS-mod d8 Radiant (rolled once) to each undead that fails.
    // Spends one Channel Divinity use.
    TurnUndeadResult useTurnUndead(BattleMap& bm, int caster_idx);

    // Life Domain Preserve Life (Channel Divinity, L3+): distribute a pool of 5 × cleric level HP
    // among the chosen creatures within 30 ft (order = distribution priority), each restored to no
    // more than half its HP maximum. Undead cannot be healed. Spends one Channel Divinity use.
    PreserveLifeResult usePreserveLife(BattleMap& bm, int caster_idx, const std::vector<int>& targets);

    // Life Domain — Supreme Healing (L17): the cleric maximizes every healing die it rolls.
    [[nodiscard]] bool lifeSupremeHealing(const Agent::Stats& s) const noexcept;

    // Life Domain — Disciple of Life (L3): a slot-level-1+ heal restores an extra 2 + slot level HP
    // to each creature healed. Returns 0 when it does not apply.
    [[nodiscard]] int discipleOfLifeBonus(const Agent::Stats& s, int slot_level) const noexcept;

    // Spend a named class resource (e.g. "War Priest", "Superiority Dice"). Returns true if the
    // agent had >= amount and it was spent. Generic so any feature (War Priest bonus attack, Battle
    // Master maneuvers, …) can pay its cost; the actual attack goes through executeAction.
    bool spendResource(BattleMap& bm, int idx, const std::string& name, int amount = 1) noexcept;

    // Tick the given agent's terrain at the start of their turn. Decrements durations,
    // removes expired effects, and clears concentration if a concentration terrain expired.
    [[nodiscard]] TerrainTickResult tickTerrainForTurn(BattleMap& bm, int agent_idx);

    // Phase 3: Tick light effects (Darkness, fog, etc.) at turn start. Expires effects by turns_remaining,
    // re-evaluates blinding for all agents if any expire.
    void tickLightEffectsForTurn(BattleMap& bm, int agent_idx) noexcept;

    // Execute a shove attempt (bonus action, contested Athletics check).
    // Attacker vs target Athletics/Acrobatics (target chooses higher).
    // On success: either push 5ft or knock prone based on knock_prone flag.
    [[nodiscard]] ShoveResult executeShove(BattleMap& bm,
                                           const ShoveAction& action);

    // Pick a door's lock with a Sleight of Hand check: roll(20) + the agent's
    // sleightOfHand() vs the door's lock_dc. On success the mundane lock is removed
    // via BattleMap::unlockDoor (the door stays closed until opened). An Arcane Lock
    // cannot be picked. door_id is the Door::id (not the doors_ index).
    [[nodiscard]] PickLockResult attemptPickLock(BattleMap& bm, int agent_idx, int door_id);

    // Telekinetic (general feat) — Telekinetic Shove: a Bonus Action that shoves one creature within
    // 30 ft. The target makes a STR save (DC = 8 + caster PB + best of INT/WIS/CHA mod); on a failure
    // it is pushed 5 ft away from the caster (reuses forceMoveAgent, the Thunderwave knockback path).
    // Returns a ShoveResult: attacker_roll = save DC, defender_roll = target's save total,
    // success = the shove landed (save failed and the target moved).
    [[nodiscard]] ShoveResult applyTelekineticShove(BattleMap& bm, int caster_idx, int target_idx) noexcept;

    // Shared grapple core — used by the standalone Grapple Weapon Action
    // (executeGrapple), on-hit weapon grapple riders (combat_attack), and the
    // future Grappler feat. Does NOT check adjacency (callers gate range).
    //   contested          — true: roll attacker Athletics vs target max(Athletics,
    //                        Acrobatics); false: grapple lands automatically.
    //   escape_dc_override  — >0: fixed escape DC; 0: compute 10 + STR mod + prof.
    // On success applies the Grappled condition via applyGrappled().
    GrappleResult resolveGrapple(BattleMap& bm, int attacker_idx, int target_idx,
                                 bool contested, int escape_dc_override) noexcept;

    // Execute a grapple attempt (contested Athletics check).
    // Attacker vs target Athletics/Acrobatics (target chooses higher).
    // On success: target gains Grappled condition with escape DC.
    [[nodiscard]] GrappleResult executeGrapple(BattleMap& bm,
                                               const GrappleAction& action);

    // Execute a grapple escape attempt (action to break free).
    // Target rolls best of STR (Athletics) or DEX (Acrobatics) vs escape DC.
    // On success: clears Grappled condition.
    [[nodiscard]] GrappleEscapeResult executeGrappleEscape(BattleMap& bm,
                                                           int agent_idx);

    // Drop all grapples initiated by an agent (free action — voluntarily end grapples).
    // Iterates through all agents and clears grappled/grappler_idx for those held by agent_idx.
    void dropGrapplesBy(BattleMap& bm, int agent_idx) noexcept;

    // Decrement turns_remaining on all active effects; apply per-tick damage/heal;
    // remove effects whose turns_remaining reaches 0.
    void tickEffects(BattleMap& bm);

    [[nodiscard]] const std::vector<ActiveEffect>& activeEffects() const noexcept;

    void clearEffects() noexcept;

    // Check if concentrating agent must save (on damage). Rolls CON save (DC = max(10, damage/2)).
    // Clears concentration if save is failed. Returns a detailed result.
    [[nodiscard]] ConcentrationSaveResult concentrationSave(
        BattleMap& bm, int agent_idx, int damage_taken);

    // ── RL action space ───────────────────────────────────────────────────

    // Enumerate all legal (weapon, target) pairs for the given attacker.
    [[nodiscard]] std::vector<Attack> availableAttacks(
        const BattleMap& bm, int attacker_idx) const;

    // Enumerate castable spell indices for the given agent this turn.
    // For NPCs: spells where uses_remaining > 0 (leveled spells also need canCastLeveledSpell)
    // For players: spells where slot exists at >= spell.level (leveled spells also need canCastLeveledSpell)
    [[nodiscard]] std::vector<int> availableCastableSpells(
        const BattleMap& bm, int agent_idx) const;

    // Calculate the number of targets for a Multiple geometry spell when cast at a given slot level.
    // Formula: spell.num_targets + (slot_level - spell.level) * spell.targets_per_upcast_level
    // For non-Multiple geometries, returns 1 (Single geometry) or 0 (AoE spells).
    // caster_level: character level for special cases like Eldritch Blast (default -1 means use normal formula)
    [[nodiscard]] int getNumTargetsForSpell(const Spell& sp, int slot_level,
                                            int caster_level = -1) const noexcept;

    // Effective casting range (ft) for a spell as cast by a specific agent, after
    // range-extending invocations. Eldritch Spear (code 2): the chosen damage cantrip's
    // range increases by 30 ft × Warlock level. Returns sp.range unchanged otherwise.
    // (executeSpell applies this to its local copy; the GUI range-gate may also consult it.)
    [[nodiscard]] int effectiveSpellRange(const BattleMap& bm, int caster_idx, const Spell& sp) const noexcept;

    // ── RL observation vector ─────────────────────────────────────────────
    //
    // Returns a fixed-length float vector suitable as NN input.
    //
    // Layout:
    //
    //   Attacker block (12 floats):
    //     col/cols, row/rows, hp_frac, ac/30,
    //     (str−10)/10, (dex−10)/10, (con−10)/10,
    //     (int−10)/10, (wis−10)/10, (cha−10)/10,
    //     speed_walk/60, speed_fly/60
    //
    //   Per target (14 floats, up to max_targets slots; zero-padded):
    //     col/cols, row/rows, hp_frac, ac/30,
    //     (str−10)/10 … (cha−10)/10,
    //     speed_walk/60, speed_fly/60,
    //     chebyshev_dist / max(cols, rows),
    //     has_line_of_sight (0 or 1)
    //
    // Total size: 12 + max_targets × 14
    [[nodiscard]] std::vector<float> getBattleObservation(
        const BattleMap& bm,
        int attacker_idx,
        const std::vector<int>& target_indices,
        int max_targets = 8) const;

    // ── RNG control ───────────────────────────────────────────────────────
    void reseed(uint32_t seed);

    // ── Druid Wild Shape & Starry Form ────────────────────────────────────────
    bool activateWildShape(BattleMap& bm, int idx, const std::string& beast_name, std::vector<Weapon> weapons, const std::string& beast_forms_path = "") noexcept;
    bool deactivateWildShape(BattleMap& bm, int idx) noexcept;
    bool activateStarryForm(BattleMap& bm, int idx, int constellation) noexcept;
    bool deactivateStarryForm(BattleMap& bm, int idx) noexcept;
    bool activateWrathOfSea(BattleMap& bm, int idx) noexcept;
    bool deactivateWrathOfSea(BattleMap& bm, int idx) noexcept;
    int  applyDragonMinRoll(BattleMap& bm, int idx, int d20_roll) noexcept;

private:
    std::mt19937 rng_;

    // Per-agent turn overrides.  Empty = everyone gets exactly 1 turn/round.
    // Only agents with turns != 1 are stored here (optimises the common case).
    std::unordered_map<int, int> agentTurns_;

    // Movement budgets for the current turn.
    // Key = agent_idx; value = remaining feet.
    // Absent entry ≡ 0 remaining (agent hasn't started their turn yet).
    std::unordered_map<int, int> walkRemaining_;
    std::unordered_map<int, int> flyRemaining_;
    std::unordered_map<int, int> swimRemaining_;
    std::unordered_map<int, int> burrowRemaining_;

    // Distance moved on slipping terrain (ice/grease) since last save check.
    // Key = agent_idx; value = feet moved on slipping terrain.
    // Reset to 0 after a successful or failed save.
    std::unordered_map<int, int> slipDistanceMoved_;

    // Active spell-applied conditions (Hold Person, Stun, etc.)
    std::vector<ActiveAgentCondition> activeAgentConditions_;
    int nextConditionId_{0};

    std::vector<ActiveEffect> activeEffects_;

    // Visibility map: (source_idx, target_idx) -> VisibilityLevel
    // Computed at turn start and cached until next turn
    std::unordered_map<int64_t, VisibilityLevel> visibilityMap_;

    // Portent Dice system (Diviner Wizard L3+)
    int pending_portent_die_{-1};    // d20 value to use on next roll (-1 = none pending)
    bool resolving_sentinel_guard_{false};  // true while a Sentinel Guardian counter-attack is resolving (suppresses guard-of-a-guard)
    std::unordered_map<int, int> agent_portent_round_used_;  // track which round each agent last used portent

    // Bardic Inspiration: a flat bonus folded into the NEXT d20 Test (0 = none).
    // Unlike Portent (which replaces the d20), this is additive. Set by useBardicDie.
    int pending_roll_bonus_{0};
    int consumePendingRollBonus() noexcept { int b = pending_roll_bonus_; pending_roll_bonus_ = 0; return b; }

    // Combat Inspiration damage bonus: a flat bonus folded into the NEXT weapon damage roll.
    // Set by useBardicDieForDamage, mirroring pending_roll_bonus_ for the damage roll.
    int pending_damage_bonus_{0};
    int consumePendingDamageBonus() noexcept { int b = pending_damage_bonus_; pending_damage_bonus_ = 0; return b; }

    // One-shot advantage/disadvantage on the NEXT D20 Test (+1 = advantage, -1 = disadvantage,
    // 0 = none). General mechanism for "advantage on your next roll" (Tides of Chaos, etc.);
    // consumed by roll(20)/rollAdvantage/rollDisadvantage/rollToHit. If the roll already has the
    // opposite, the two cancel (5e rule). Only d20 Tests consume it (damage dice ignore it).
    int pending_advantage_{0};
    int consumePendingAdvantage() noexcept { int a = pending_advantage_; pending_advantage_ = 0; return a; }

    MessageLogger* logger_{nullptr};
    CombatDecider* decider_{nullptr};  // nullptr = built-in defaults (RL/headless)

    // NPC-automation visualization hook (Step 2e seam). Unset in headless mode → renderAttack is a no-op.
    std::function<void(int, int)> render_attack_hook_;
    // Notify the GUI (if a hook is installed) that an automated NPC's action from attacker→target
    // resolved, so it can animate. No-op when no hook is installed (headless / tests).
    void renderAttack(int attacker_idx, int target_idx) const {
        if (render_attack_hook_) render_attack_hook_(attacker_idx, target_idx);
    }

    // ── Reaction system internals (combat_movement.cpp) ──────────────────────
    PendingDecision pending_decision_{};   // what the engine is parked on (GUI polls it)
    InFlightMove    in_flight_move_{};      // resumable state of a provoking move
    // Detect which creatures the mover leaves the reach of along origin→dest (per-creature,
    // per-step via the straight-line path). Returns events ordered by path step.
    [[nodiscard]] std::vector<ProvokeEvent> detectProvokes(const BattleMap& bm, int mover_idx,
                                                           Cell origin, Cell dest,
                                                           MovementType type) const;
    // Build the checkpoint ctx for one reactor: enumerate its legal melee weapons +
    // single-target spells + Skip.
    [[nodiscard]] ReactionCtx buildReactionCheckpoint(const BattleMap& bm, ReactionWindow window,
                                                      int reactor_idx, int source_idx,
                                                      Cell source_cell) const;
    // Validate + execute a chosen reaction; consume the reactor's reaction; note stop-on-down.
    void applyReactionResponse(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp);
    // Drive the in-flight move: resolve provokes (inline for auto, suspend for GUI), then commit.
    FlowStatus advanceMove(BattleMap& bm);

    // ── Cast interrupt internals (combat_spells.cpp) — counter-counterspell decision stack
    //    A Counterspell is a genuine nested cast pushed on top of the cast
    //    it targets; the stack lets a deeper Counterspell negate it before it fires. back() = the cast
    //    currently resolving; empty = idle. The bottom (original) cast's outcome is snapshotted into
    //    last_cast_result_/last_cast_countered_ when the stack empties (the GUI accessors read those). ──
    std::vector<InFlightCast> cast_stack_;
    SpellResult last_cast_result_{};
    bool        last_cast_countered_{false};
    [[nodiscard]] bool          castActive() const noexcept { return !cast_stack_.empty(); }
    [[nodiscard]] InFlightCast& topCast()           noexcept { return cast_stack_.back(); }   // precond: castActive()
    [[nodiscard]] const InFlightCast& topCast() const noexcept { return cast_stack_.back(); }
    // OnDeclareCast reactors for a cast: Counterspell casters that can see the caster, plus (for
    // Magic Missile) targets that can cast Shield. advanceCast builds each reactor's options.
    [[nodiscard]] std::vector<int> declareCastReactors(const BattleMap& bm, const SpellAction& action) const;
    // True if `idx` can cast Shield as a reaction now (knows Shield, has an L1+ slot, reaction free).
    [[nodiscard]] bool canCastShield(const BattleMap& bm, int idx) const;
    // True if `idx` can cast Counterspell at `caster_idx` now (knows it, L3+ slot, reaction free, and
    // can see the caster within 60 ft; not the caster itself).
    [[nodiscard]] bool canCastCounterspell(const BattleMap& bm, int idx, int caster_idx) const;
    // True if `idx` (an Arcane Trickster Rogue L17+) can use Spell Thief on `caster_idx`'s spell now:
    // reaction free, not incapacitated, sees the caster within 60 ft, not the caster / an ally. On a
    // failed INT save (applied in applyCastReaction) the cast is countered AND the spell is added to
    // the caster's stolen_spell_names (it can't recast it until a long rest).
    [[nodiscard]] bool canSpellThief(const BattleMap& bm, int idx, int caster_idx) const;
    // Apply one chosen OnDeclareCast reaction (dispatches on ReactionOption.feature, e.g. "Shield").
    void applyCastReaction(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp);
    // Drive the cast stack: step the top cast through its windows; on a Counterspell choice push a
    // nested cast; finalize+pop completed casts; suspend (AwaitingDecision) for the GUI.
    FlowStatus advanceCast(BattleMap& bm);
    // One step of cast_stack_.back() through its OnDeclareCast/OnHit/OnSaveFail windows. Internal
    // result (not the bound FlowStatus): Pushed = a Counterspell went on top (loop to it), Awaiting =
    // suspended for the GUI, Completed = all windows done (caller finalizes+pops).
    enum class CastStep { Completed, Awaiting, Pushed };
    CastStep stepTopCast(BattleMap& bm);
    // Resolve cast_stack_.back() (executeSpell, or a Counterspell's deferred CON save) and pop it;
    // snapshot the bottom cast's result/countered when the stack empties.
    void finalizeAndPop(BattleMap& bm);
    // Counterspell-as-nested-cast:
    //  spendCounterspellCost spends the reactor's payment (NPC innate use, else L3+ slot) + reaction.
    void spendCounterspellCost(BattleMap& bm, int reactor) noexcept;
    //  castCounterspell spends the reactor's L3+ slot + reaction (declaration only — no save yet).
    void castCounterspell(BattleMap& bm, int reactor, int target_caster) noexcept;
    //  pushCounterspell pushes a Counterspell cast targeting target_caster onto cast_stack_.
    void pushCounterspell(BattleMap& bm, int reactor, int target_caster);
    //  resolveCounterspellEffect rolls the deferred CON save (at pop time) and, on a fail, marks the
    //  parent cast (directly below on the stack) countered.
    void resolveCounterspellEffect(BattleMap& bm, InFlightCast& c);
    // Index of a named spell in an agent's spell list (or -1). Used to synthesize a Counterspell cast.
    [[nodiscard]] int agentSpellIndex(const BattleMap& bm, int idx, const std::string& name) const;
    // True if the chosen reaction option is a Counterspell Feature (→ push a nested cast).
    [[nodiscard]] bool isCounterspellChoice(const ReactionCtx& ctx, const ReactionResponse& resp) const;

    // ── NPC automation internals (combat_turn.cpp, NPC_AUTOMATION_PLAN.md Step 3) ─────────────
    NpcTurnState npc_turn_{};   // resume point of an in-flight automated turn (parks at reaction windows)
    // Single shared NPC turn executor (Steps 3-5). It engages an enemy and makes a full Attack action,
    // with target selection, weapon choice, and positioning all driven by `policy` — so Simple (Step 3),
    // PreferTargetCaster (Step 4), and PreferRange (Step 5) are the SAME code with different policies.
    // Resumable: returns AwaitingDecision when a move/attack it attempts parks at a human reaction window;
    // the GUI resolves it and re-calls run_npc_turn to continue (npc_turn_ holds the resume point).
    FlowStatus runWeaponTurn(BattleMap& bm, int agent_idx, const NpcStrategyPolicy& policy);
    // Best attackable enemy of agent_idx by the given priority (Nearest, ties→lowest HP; or LowestHp,
    // ties→nearest), or -1 if none. "Enemy" = any non-ally (areAllies==false) alive, in play, in initiative.
    // prefer_caster (Step 4): restrict the pool to enemy spellcasters if any are attackable, else fall back
    // to the full enemy pool (so PreferTargetCaster degrades to its base priority when no caster is present).
    [[nodiscard]] int  npcSelectTarget(const BattleMap& bm, int agent_idx, bool prefer_caster = false,
                                       NpcTargetPriority priority = NpcTargetPriority::Nearest) const noexcept;
    // True if target_idx is an enemy spellcaster (its known-spell list is non-empty). Drives Step 4 targeting.
    [[nodiscard]] bool npcIsCaster(const BattleMap& bm, int idx) const noexcept;
    // True if target_idx is a currently-valid attack target for agent_idx (alive, in play, in initiative,
    // not an ally). Used to re-acquire mid-multiattack when the current target drops.
    [[nodiscard]] bool npcAttackable(const BattleMap& bm, int agent_idx, int target_idx) const noexcept;
    // Weapon slot (0..2) with the highest average-damage MELEE weapon, or — if the agent has no usable
    // melee weapon — the highest average-damage weapon of any type (Simple / preferMelee).
    [[nodiscard]] int  npcSelectWeapon(const BattleMap& bm, int agent_idx) const noexcept;
    // Weapon slot (0..2) with the highest average-damage RANGED weapon, or — if the agent has no ranged
    // weapon — falls back to npcSelectWeapon so a melee-only creature still acts (PreferRange, Step 5).
    [[nodiscard]] int  npcSelectRangedWeapon(const BattleMap& bm, int agent_idx) const noexcept;

    // PreferAOE turn (Step 6). Picks the available area spell + aim cell that maximizes the net enemies
    // caught (npcPlanAoeCast), casts it once through the parkable beginCast (so a human reaction window
    // surfaces identically to a player cast), then ends the turn. With no worthwhile AoE it falls back to
    // the Simple weapon turn so an AoE caster with nothing to blast still acts. Resumable via npc_turn_.
    FlowStatus runAoeTurn(BattleMap& bm, int agent_idx);
    // Among the caster's currently-castable AoE blast spells (Sphere/Cone/Line/Square, Harm type), and over
    // candidate aim points (each attackable enemy's cell), choose the spell+aim with the most net enemies
    // (enemies caught minus friendly-fire allies caught, unless the spell spares allies). Catchment is
    // counted with resolveAoeTargets — the SAME resolver executeSpell uses — so geometry is single-sourced.
    // Placed areas (Sphere/Square) are range+LoS gated to the aim; self-origin Cone/Line need only LoS.
    [[nodiscard]] NpcAoePlan npcPlanAoeCast(const BattleMap& bm, int agent_idx) const noexcept;
    // True if the agent has ANY currently-castable AoE blast spell (Sphere/Cone/Line/Square, Harm type),
    // regardless of whether an enemy is in range right now. Distinguishes "no AoE to cast → melee" from
    // "has an AoE but must first move into range" so PreferAOE never falls back to melee while it holds one.
    [[nodiscard]] bool npcHasCastableAoeSpell(const BattleMap& bm, int agent_idx) const noexcept;
    // Bucket D: true if the agent has a currently-castable RECHARGE AoE feature (recharge_min > 0, a
    // remaining/un-expended use, and an AoE blast shape). runNpcTurn routes any strategy through runAoeTurn
    // when this holds so a monster spends its breath weapon as often as it recharges — see MULTIATTACK_RECIPES_PLAN.md.
    [[nodiscard]] bool npcHasAvailableRechargeAoe(const BattleMap& bm, int agent_idx) const noexcept;
    // The reachable cell that most reduces footprint distance to the nearest attackable enemy — an AoE
    // caster's "close the gap so the blast can reach" move. Mirrors runWeaponTurn's approach finder.
    [[nodiscard]] bool npcFindAoeApproachCell(const BattleMap& bm, int agent_idx, Cell& out) const noexcept;

    // ── Attack interrupt internals (combat_attack.cpp) ───────────────────────
    InFlightAttack in_flight_attack_{};      // resumable state of a begin_attack flow
    AttackResult   last_attack_result_{};    // result of the most recent begin_attack flow (read by GUI)
    // True iff the target should be offered a Shield reaction vs this just-rolled attack: a non-crit
    // hit whose +5 AC would flip it to a miss, and the target can cast Shield right now. Shared by the
    // inline (maybeDefenderOnHitInline) and suspendable (advanceAttack) paths so they gate identically.
    [[nodiscard]] bool shouldOfferDefenderShield(const BattleMap& bm, const Attack& action,
                                                 const AttackResult& r) const;
    // Riposte eligibility: defender_idx is a Battle Master with a Superiority Die and its reaction
    // free, alive, has a melee weapon, and attacker_idx is within the defender's melee reach. The
    // single eligibility gate, called from applyAttackResult's melee-miss branch to set the flag.
    [[nodiscard]] bool canRiposte(const BattleMap& bm, int defender_idx, int attacker_idx) const;
    // Index of the defender's first melee weapon (the one a Riposte strikes with), or -1 if none.
    [[nodiscard]] int  riposteWeaponIdx(const BattleMap& bm, int idx) const;
    // Apply one chosen OnHit reaction (this pass: the target's Shield → negates the hit on r).
    void applyAttackReaction(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp);
    // Drive the in-flight attack: open the Shield window (suspend for GUI) or finalize via
    // applyAttackResult. Stores the finished result in last_attack_result_.
    FlowStatus advanceAttack(BattleMap& bm);

    // ── OnD20Seen reactions (attack rolls only) ─────────────────────────────────
    // "lowering-only" reactions a nearby creature may use AFTER seeing an attack roll: they can turn a
    // hit into a miss (never a miss into a hit), so the only consequence is r.hit=false — identical to
    // the Shield contract (no post-hoc damage roll needed). Each gate mirrors canCastCounterspell
    // (60 ft + line-of-sight to the roller, reaction free, alive) plus the feature's own requirements.
public:
    [[nodiscard]] bool canBendLuck    (const BattleMap& bm, int reactor, int roller) const; // L6+ WildMagic Sorc, ≥1 SP
    [[nodiscard]] bool canCuttingWords(const BattleMap& bm, int reactor, int roller) const; // L3+ Lore Bard, ≥1 Bardic use
    [[nodiscard]] bool canSilveryBarbs(const BattleMap& bm, int reactor, int roller) const; // knows Silvery Barbs + L1+ slot
    [[nodiscard]] bool canWardingFlare(const BattleMap& bm, int reactor, int roller, int target) const; // L3+ Light Domain Cleric, ≥1 Warding Flare use, within 30ft, target on reactor's team
    // Clockwork Soul Sorcerer (L3+): cancel advantage/disadvantage on a d20 Test within 60 ft, PB uses /
    // long rest, no Sorcery Point cost. In the attack-roll window this fires only when the roll was made
    // at advantage (r.advantage && !r.disadvantage): reverting r.d20 to r.d20_primary is then a LOWERING
    // (it drops max(d1,d2) to d1), which fits the lowering-only window. (The disadvantage-cancel
    // direction would RAISE a missed roll and is deferred — see known_limitations.md.)
    [[nodiscard]] bool canRestoreBalance(const BattleMap& bm, int reactor, int roller, const AttackResult& r) const;
    // Recompute r.hit / r.critical from r.d20 + r.total_roll vs r.target_ac (nat 20 hits/crits, nat 1
    // misses, else total >= AC). Additive reactions leave r.d20 untouched (crit preserved); the
    // Silvery Barbs reroll sets r.d20 to the new die.
    void reevaluateAttackHit(AttackResult& r) const noexcept;
    // Promote a missed roll to a hit when s.auto_hit is set (vampire Bite vs a creature it has
    // Grappled). Runs after resolveAttack, before the defender reaction windows. No-op otherwise.
    void forceAutoHit(BattleMap& bm, InFlightAttack& s);
    // "Auto-use-when-grappling" intent (Vampire Bite auto-offer/auto-attempt). For attacker `atk`,
    // scan its weapons for one flagged auto_use_when_grappling and find a legal victim it is currently
    // Grappling (alive, not tombstoned, in reach of that weapon). Returns {weapon_slot, victim_idx},
    // or {-1,-1} if none. Shared by manual play (CP1) and NPC automation (CP2). See
    // MONSTER_AUTO_EFFECTS_PLAN.md.
    [[nodiscard]] std::pair<int,int> pendingAutoGrappleStrike(const BattleMap& bm, int atk) const;
    // Apply one lowering reaction to the in-flight roll r (spends the resource + the reactor's reaction,
    // mutates r, reevaluates). Return true if r changed. Write to the in-flight r, not pending_roll_bonus_.
    bool applyBendLuckToAttack    (BattleMap& bm, int reactor, AttackResult& r);
    bool applyCuttingWordsToAttack(BattleMap& bm, int reactor, AttackResult& r);
    bool applySilveryBarbsToAttack(BattleMap& bm, int reactor, AttackResult& r);
    bool applyWardingFlareToAttack(BattleMap& bm, int reactor, AttackResult& r); // Disadvantage = reroll, take lower
    bool applyRestoreBalanceToAttack(BattleMap& bm, int reactor, AttackResult& r); // cancel advantage: r.d20 ← r.d20_primary

    // Clockwork Restore Balance — the OnMiss (raising) counterpart of the OnD20Seen advantage-cancel.
    // When a creature (the reactor itself or an ally) attacked AT DISADVANTAGE and missed, a Clockwork
    // Sorcerer L3+ within 60 ft may cancel the Disadvantage by reverting the kept die to the first
    // (primary) die — min(d1,d2) → d1, a RAISING that can flip the miss to a hit. Only offered when
    // r.d20_primary > r.d20 (else the cancel is a no-op). Spends one Restore Balance use + reaction.
    [[nodiscard]] bool canRestoreBalanceMiss(const BattleMap& bm, int reactor, int roller,
                                             const AttackResult& r) const;
    // Cancel disadvantage on the missed attack `action`; if the raised roll now meets AC, the miss
    // becomes a hit and weapon damage is rolled + applied (mirrors applyGuidedStrike). Pass the Attack
    // that missed (for the target + weapon) and its AttackResult.
    bool applyRestoreBalanceMissToAttack(BattleMap& bm, const Attack& action, int reactor, AttackResult& r);
    // Auto/RL OnMiss window for the above (the GUI uses the restore_balance_miss_available flag). Loops
    // eligible Clockwork allies, asks decider_, applies the chosen cancel. Returns true if r changed.
    bool maybeRestoreBalanceMissInline(BattleMap& bm, const Attack& action, AttackResult& r);
private:
    // The creatures (≠ attacker) that may lower this attack roll, in initiative order. Silvery Barbs is
    // only included on a hit (it triggers on a success). Empty when no lowering reaction could change
    // the outcome (parallels shouldOfferDefenderShield: only a hit a worst-case lower could miss).
    [[nodiscard]] std::vector<int> d20SeenReactors(const BattleMap& bm, const Attack& action,
                                                   const AttackResult& r) const;
    // The legal lowering options for one reactor vs this roll, plus a trailing Skip (size 1 == only Skip).
    [[nodiscard]] std::vector<ReactionOption> d20SeenOptions(const BattleMap& bm, int reactor,
                                                             const Attack& action, const AttackResult& r) const;
    // GUI dispatch: route a chosen OnD20Seen option to the matching apply* on in_flight_attack_.r.
    void applyD20SeenReaction(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp);
    // Auto/RL: loop d20SeenReactors, ask decider_, apply the chosen lowering reaction. Called in
    // executeAction between resolveAttack and maybeDefenderOnHitInline. Stops once r becomes a miss.
    bool maybeD20SeenInline(BattleMap& bm, const Attack& action, AttackResult& r);

    // ── OnSaveFail reactions (spell saves only) ────────────────────────────────
    // "raising-only" reactions a creature may use AFTER a spell save FAILS: they reroll the save, which
    // can only turn a failure into a success (less/no damage, no condition) — so executeSpell consuming
    // the corrected save needs no post-hoc undo (mirror of the OnD20Seen lowering-only contract).
public:
    // Bard L7+, reaction free, alive, within 30 ft + line-of-sight of the failed creature, and the
    // offending spell would apply Charmed or Frightened. The reactor MAY be the failed creature itself.
    [[nodiscard]] bool canCountercharm(const BattleMap& bm, int reactor, int save_target,
                                       const SpellAction& action) const;
    // Fighter L9+, ≥1 "Indomitable" use, alive, and reactor == save_target (you reroll your OWN save).
    // No range/LoS test (it's self); does NOT require a free reaction (RAW "no action" — see §6).
    [[nodiscard]] bool canIndomitable(const BattleMap& bm, int reactor, int save_target) const;
    // Fiend Warlock L6+, ≥1 "Dark One's Own Luck" use, alive, and reactor == save_target (you add a
    // d10 to your OWN failed save after seeing the roll). No range/LoS, costs no reaction (RAW).
    [[nodiscard]] bool canDarkOnesOwnLuck(const BattleMap& bm, int reactor, int save_target) const;
    // Creature with Legendary Resistance, ≥1 use remaining, alive, and reactor == save_target.
    // No range/LoS test (it's self); does NOT require a free reaction.
    [[nodiscard]] bool canLegendaryResist(const BattleMap& bm, int reactor, int save_target) const;
    // War Domain — War God's Blessing (L6 Channel Divinity): a War Cleric within 60 ft of the failed
    // creature (itself or an ally) with ≥1 Channel Divinity use and a free reaction. Costs the reaction.
    [[nodiscard]] bool canWarGodsBlessing(const BattleMap& bm, int reactor, int save_target) const;
    // Recompute ss.total / ss.saved from ss.d20 + ss.save_mod + ss.bonus vs ss.dc (pass/fail only).
    void reevaluateSave(SpellSave& ss) const noexcept;
    // Apply one reroll reaction to a pre-rolled save (spends the resource, mutates ss, reevaluates).
    // Return true iff ss changed. Countercharm rerolls WITH ADVANTAGE + spends the bard's reaction;
    // Indomitable rerolls + adds the Fighter level to ss.bonus + spends 1 "Indomitable" use (not the
    // reaction); Legendary Resistance adds +99 to the save to make it succeed + spends 1 use/day.
    // Each rolls its d20 directly (no fresh save → no recursive OnSaveFail).
    bool applyCountercharmToSave(BattleMap& bm, int reactor, SpellSave& ss);
    bool applyIndomitableToSave (BattleMap& bm, int reactor, SpellSave& ss);
    // Dark One's Own Luck adds 1d10 to ss.bonus + spends 1 "Dark One's Own Luck" use (not the reaction).
    bool applyDarkOnesOwnLuckToSave(BattleMap& bm, int reactor, SpellSave& ss);
    bool applyLegendaryResistanceToSave(BattleMap& bm, int reactor, SpellSave& ss);
    // War God's Blessing adds +10 to ss.bonus + spends 1 Channel Divinity use + the cleric's reaction.
    bool applyWarGodsBlessingToSave(BattleMap& bm, int reactor, SpellSave& ss);
private:
    // The creatures eligible for ANY reroll-save reaction vs one FAILED save (ss.saved==false,
    // !ss.auto_fail), in initiative order: the target itself (Indomitable) + bards within 30 ft on a
    // charm/frighten spell (Countercharm). Empty for a passed/auto-fail save (nothing to reroll).
    [[nodiscard]] std::vector<int> saveFailReactors(const BattleMap& bm, const SpellAction& action,
                                                    const SpellSave& ss) const;
    // The legal reroll options (Feature kind) for one reactor vs this failed save, + a trailing Skip
    // (size 1 == only Skip → nothing offered).
    [[nodiscard]] std::vector<ReactionOption> saveFailOptions(const BattleMap& bm, int reactor,
                                                              const SpellAction& action,
                                                              const SpellSave& ss) const;
    // GUI dispatch: route a chosen OnSaveFail option to the matching apply* on the pre-rolled save in
    // topCast().save_prerolls (found by ctx.source_idx == the failed creature).
    void applySaveFailReaction(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp);

    // ── OnTurnStartNearby internals (combat_riders.cpp) ──────────────────
    InFlightTurn in_flight_turn_{};   // resumable state of a begin_turn_flow
    // The creatures (≠ source) eligible for ANY turn-start reaction vs `source`, in order.
    [[nodiscard]] std::vector<int> turnStartReactors(const BattleMap& bm, int source) const;
    // reactor's legal Feature options ("BranchesOfTheTree") vs `source`, + a trailing Skip
    // (size 1 == only Skip → nothing offered).
    [[nodiscard]] std::vector<ReactionOption> turnStartOptions(const BattleMap& bm, int reactor,
                                                               int source) const;
    // GUI dispatch: route a chosen OnTurnStartNearby option to the matching apply*.
    void applyTurnStartReaction(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp);
    // Drive the in-flight turn start: offer each reactor (suspend for GUI, inline for auto), then finish.
    FlowStatus advanceTurnStart(BattleMap& bm);

    std::unordered_map<int, std::vector<int>> safeTargets_;  // caster_idx -> indices excluded from its AoEs

    // Persistent-zone "once per turn" tracking. turnCounter_ increments on each beginTurn;
    // zoneAppliedTurn_ maps (effect_id, agent_idx) -> the turnCounter_ value when last applied.
    int turnCounter_{0};
    std::unordered_map<int64_t, int> zoneAppliedTurn_;

    // Emit a message to the logger (if attached).
    template<typename... Args>
    void log_(std::format_string<Args...> fmt, Args&&... args) const {
        if (logger_) logger_->log(std::format(fmt, std::forward<Args>(args)...));
    }

    // ── Spell helpers ─────────────────────────────────────────────────────
    [[nodiscard]] static int spellAttackMod(const Agent::Stats& s) noexcept;
    [[nodiscard]] static int spellSaveDc(const Agent::Stats& s) noexcept;
    [[nodiscard]] static int spellSaveDcFromAbility(const Agent::Stats& s, SaveAbility_t ability) noexcept;

    // Apply a persistent spell effect (damage) to a target agent.
    void applySpellEffect(BattleMap& bm, const ActiveSpellEffect& effect, int target_idx) noexcept;

    // Re-center persistent Sphere effects anchored to this agent (moving Emanation).
    void recomputeAnchoredEffects(BattleMap& bm, int agent_idx) noexcept;

    // Apply a persistent zone effect to a target at most once per turn (D&D "a creature makes
    // this save only once per turn"). Returns true if applied, false if already applied this turn.
    bool applyZoneIfNewThisTurn(BattleMap& bm, const ActiveSpellEffect& effect, int target_idx) noexcept;

    // True if a target is NOT affected by a persistent zone effect, mirroring the faction
    // rules executeSpell applies at cast time so the ongoing zone behaves the same:
    //   • the caster never triggers their own zone;
    //   • Heal zones only affect the caster's allies (faction rule 3);
    //   • "creatures of your choice" harmful zones (selective_targeting, e.g. Spirit Guardians)
    //     spare the caster's allies (faction rule 2) — plain zones keep friendly fire on;
    //   • the caster's Evoker safe targets are fully excluded.
    [[nodiscard]] bool zoneSparesTarget(const BattleMap& bm, const ActiveSpellEffect& effect,
                                        int target_idx) const noexcept;

    // Post-damage hook: call after an agent takes > 0 damage from any source. Resolves
    // on-damage condition behavior — ends conditions flagged End, and re-rolls the save (at
    // Advantage) for those flagged RepeatSave, ending them on success. `magic_type_mask` is a
    // bitmask over MagicDamage_t (bit t = damage of type t was actually dealt); when it intersects
    // a regenerating creature's regen_interrupt_damage_types, it suppresses that creature's next
    // turn of Regeneration (Troll acid/fire, Vampire radiant). 0 = no magic types / not tracked.
    void processDamageTaken(BattleMap& bm, int idx, int amount, unsigned magic_type_mask = 0u) noexcept;

    // Clear the Agent::Conditions flag(s) that a spell-applied condition set (Charmed, Stunned, …).
    void clearSpellConditionEffect(BattleMap& bm, const ActiveAgentCondition& cond) noexcept;

    // Check for slipping terrain (ice/grease) and trigger saves/prone as needed.
    void checkSlippingTerrain(BattleMap& bm, int agent_idx, Cell oldOrigin, Cell newOrigin) noexcept;

    // Roll + apply a delayed-trigger condition's stored damage to its affected agent (save honored).
    // Shared by triggerDelayedEffect (owner detonates) and tickAgentConditions (auto-on-expire).
    // Returns the damage dealt.
    int resolveDelayedEffect(BattleMap& bm, const ActiveAgentCondition& cond) noexcept;

    // Fire a condition's caster "kickback" (Vistani Curse) when it ends by ANY path: rolls
    // kickback_dice × d(kickback_die_size) of kickback_damage_type onto the CASTER (no save).
    // No-op unless cond.kickback_dice > 0; suppressed when the cursed target has died. Called
    // from removeAgentCondition (save-success / concentration-drop / detonate) and from both
    // tick loops on natural duration expiry (deferred, to keep the container stable).
    void onConditionEnded(BattleMap& bm, const ActiveAgentCondition& cond) noexcept;
};

} // namespace rpg
