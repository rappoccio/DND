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
#include "message_logger.hpp"

#include <cstdint>
#include <format>
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
enum class VisibilityLevel;  // defined in battle_map.hpp

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
    int  attack_mod   = 0;      // total modifier added to the roll
    int  total_roll   = 0;      // d20 + attack_mod
    int  target_ac    = 0;      // defender's AC we rolled against
    bool critical     = false;  // natural 20 → double damage dice
    bool fumble       = false;  // natural 1  → automatic miss
    bool disadvantage = false;  // roll was made at disadvantage (long range etc.)
    bool hit          = false;

    // ── Damage (only meaningful when hit == true) ─────────────────────────
    std::vector<int> dice_results;  // individual die values (doubled on crit)
    int  damage_mod   = 0;          // ability-score modifier added to damage
    int  total_damage = 0;          // max(0, sum(dice) + damage_mod)
    std::vector<MagicDamage_t>    magic_damage_types;
    std::vector<PhysicalDamage_t> physical_damage_types;
    // Per-source damage breakdown, e.g. [("weapon",4),("rage",3)]. Sums to total_damage.
    std::vector<std::pair<std::string,int>> damage_breakdown;

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

// Result of the Topple weapon-mastery prone save.
struct ToppleResult {
    bool valid = false;   // topple_available was set on the attacker (a qualifying hit had occurred)
    int  save_dc = 0;     // CON save DC = 8 + attacker's attack ability mod + prof bonus
    int  save_roll = 0;   // target's d20 + CON save mod
    bool toppled = false; // target failed the save and is now Prone
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
struct OACtx           { int attacker_idx; int target_idx; };

struct CombatDecider {
    virtual ~CombatDecider() = default;
    virtual std::vector<int> chooseBrutalStrike(const BrutalStrikeCtx&) { return {}; }
    virtual bool             chooseReckless(const RecklessCtx&)          { return false; }
    virtual int              chooseOAResponse(const OACtx&)              { return -1; }
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
    static int damageAgent(BattleMap& bm, int idx, int amount) noexcept;
    static int healAgent  (BattleMap& bm, int idx, int amount) noexcept;

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
    // Rogue Cunning Strike rider application (save + condition): Poison/Trip/Withdraw/KnockOut/Obscure.
    // Internal helper called by applyCunningStrikeEffect after the Sneak Attack dice are spent.
    void applyCunningStrikeRiders(BattleMap& bm, int attacker_idx, int target_idx,
                                  const std::vector<int>& effects) noexcept;
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
    // Remove a condition by id.
    void removeAgentCondition(int condition_id) noexcept;

    [[nodiscard]] std::array<Weapon, 3> getAgentWeapons(const BattleMap& bm, int idx) const noexcept;
    void setAgentWeapons(BattleMap& bm, int idx, std::array<Weapon, 3> weapons) noexcept;

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
    bool checkConcentrationOnDamage(BattleMap& bm, int target_idx, int damage) noexcept;

    // ── Visibility and Line of Sight ───────────────────────────────────────
    // Compute visibility from one agent to all others on the map.
    // Respects perception range (based on stats + lighting modifiers),
    // line-of-sight, and obscuration effects.
    // Caches results in visibilityMap_ for use by spells/attacks.
    void computeVisibility(BattleMap& bm, int agent_idx) noexcept;

    // Get the cached visibility level between two agents (from last computeVisibility call).
    // Returns Blocked if visibility hasn't been computed for this pair.
    [[nodiscard]] VisibilityLevel getVisibility(int source_idx, int target_idx) const noexcept;

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
    int roll(int sides);            // 1dN  (result 1…sides)
    int rollAdvantage(int sides);   // 2dN, keep higher
    int rollDisadvantage(int sides); // 2dN, keep lower

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

    // Barbarian Rage lifecycle methods
    // Activate Rage: set raging=true, apply BPS resistance (0.5x multiplier)
    void activateRage(BattleMap& bm, int idx);

    // Extend Rage: reset duration_remaining on Rage resource
    void extendRage(BattleMap& bm, int idx);

    // End Rage: set raging=false, clear BPS resistance (restore 1.0x multiplier)
    void endRage(BattleMap& bm, int idx);

    // Apply Brutal Strike effects: damage + chosen effects (Forceful/Hamstring/Staggering/Sundering)
    // effects: vector of effect indices (0=Forceful, 1=Hamstring, 2=Staggering, 3=Sundering)
    void applyBrutalStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                const std::vector<int>& effects, AttackResult& result) noexcept;

    // Apply Rogue Sneak Attack + optional Cunning Strike riders out of band, after a qualifying hit
    // (cunning_strike_available). Rolls (sneak_dice − rider cost)d6, adds it to result/damage and the
    // target's HP, marks Sneak Attack used, then applies any rider conditions. effects: rider codes
    // (0=Poison 1=Trip 2=Withdraw 4=KnockOut 5=Obscure); empty = full Sneak Attack with no rider.
    // Invalid/over-budget rider sets are ignored (full Sneak Attack still applies, no rider).
    void applyCunningStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                  const std::vector<int>& effects, AttackResult& result) noexcept;

    // Cleric Blessed Strikes — Divine Strike: out-of-band rider after a qualifying weapon hit
    // (divine_strike_available). Rolls 1d8 (2d8 at L14) Radiant or Necrotic (radiant flag), adds it
    // to result/damage and the target's HP, marks Divine Strike used for the turn. Mirrors
    // applyBrutalStrikeEffect / applyCunningStrikeEffect.
    void applyDivineStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                 bool radiant, AttackResult& result) noexcept;

    // War Domain — Guided Strike: a War Cleric L3+ (the attacker, or an ally within 30 ft who also
    // spends a Reaction) expends Channel Divinity to add +10 to a missed attack roll (result), turning
    // it into a hit when it now meets AC — in which case weapon damage is rolled and applied here.
    void applyGuidedStrike(BattleMap& bm, const Attack& action, int cleric_idx, AttackResult& result) noexcept;

    // Weapon Mastery — Push: a qualifying hit (push_available) shoves the target 10 ft straight
    // away from the attacker (Large or smaller). Clears the flag. Returns feet actually moved.
    int applyPush(BattleMap& bm, int attacker_idx, int target_idx) noexcept;

    // Weapon Mastery — Topple: a qualifying hit (topple_available) forces the target to make a
    // CON save (DC 8 + attacker's attack ability mod + prof bonus) or be knocked Prone. Clears
    // the flag. weapon_idx identifies the striking weapon (for the save DC's ability).
    ToppleResult applyTopple(BattleMap& bm, int attacker_idx, int target_idx, int weapon_idx) noexcept;

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

    // ── Initiative ────────────────────────────────────────────────────────
    //
    // Roll initiative for every living agent in the BattleMap (hp_cur > 0).
    // Each roll is d20 + DEX modifier [+ prof_bonus if initiative_prof].
    // Returns entries sorted descending by total; ties broken by modifier
    // then by agent_idx.  Call once at combat start; reuse the order for
    // all subsequent runRound() calls.
    std::vector<InitiativeEntry> rollInitiative(const BattleMap& bm);

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

    // Spend a named class resource (e.g. "War Priest", "Superiority Dice"). Returns true if the
    // agent had >= amount and it was spent. Generic so any feature (War Priest bonus attack, Battle
    // Master maneuvers, …) can pay its cost; the actual attack goes through executeAction.
    bool spendResource(BattleMap& bm, int idx, const std::string& name, int amount = 1) noexcept;

    // Tick the given agent's terrain at the start of their turn. Decrements durations,
    // removes expired effects, and clears concentration if a concentration terrain expired.
    [[nodiscard]] TerrainTickResult tickTerrainForTurn(BattleMap& bm, int agent_idx);

    // Execute a shove attempt (bonus action, contested Athletics check).
    // Attacker vs target Athletics/Acrobatics (target chooses higher).
    // On success: either push 5ft or knock prone based on knock_prone flag.
    [[nodiscard]] ShoveResult executeShove(BattleMap& bm,
                                           const ShoveAction& action);

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
    std::unordered_map<int, int> agent_portent_round_used_;  // track which round each agent last used portent

    MessageLogger* logger_{nullptr};
    CombatDecider* decider_{nullptr};  // nullptr = built-in defaults (RL/headless)
    std::unordered_map<int, std::vector<int>> safeTargets_;  // caster_idx -> indices excluded from its AoEs

    // Persistent-zone "once per turn" tracking. turnCounter_ increments on each beginTurn;
    // zoneAppliedTurn_ maps (effect_id, agent_idx) -> the turnCounter_ value when last applied.
    int turnCounter_{0};
    std::unordered_map<int64_t, int> zoneAppliedTurn_;

    // Emit a message to the logger (if attached).
    template<typename... Args>
    void log_(std::format_string<Args...> fmt, Args&&... args) {
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

    // Post-damage hook: call after an agent takes > 0 damage from any source. Resolves
    // on-damage condition behavior — ends conditions flagged End, and re-rolls the save (at
    // Advantage) for those flagged RepeatSave, ending them on success.
    void processDamageTaken(BattleMap& bm, int idx, int amount) noexcept;

    // Clear the Agent::Conditions flag(s) that a spell-applied condition set (Charmed, Stunned, …).
    void clearSpellConditionEffect(BattleMap& bm, const ActiveAgentCondition& cond) noexcept;

    // Check for slipping terrain (ice/grease) and trigger saves/prone as needed.
    void checkSlippingTerrain(BattleMap& bm, int agent_idx, Cell oldOrigin, Cell newOrigin) noexcept;
};

} // namespace rpg
