#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include "agent.hpp"
#include "condition.hpp"
#include "damage.hpp"

namespace rpg {
    // Forward declare TerrainDifficulty to avoid circular includes
    enum class TerrainDifficulty;

    struct Spell {
      enum Geometry_t   { Single=0, Line, Cone, Sphere, Square, Rectangle, Multiple, NumGeometry_t };
      // Help = beneficial buff/protection spells that neither heal nor damage; they apply
      //        conditions (e.g. Sanctuary's ward) and target allies like Heal spells do.
      enum SpellType_t  { Harm=0, Heal, Transport, Help, NumSpellType_t };
      enum SpellAttack_t{ AttackRoll=0, Save, Automatic, NumSpellAttack_t };
      enum SpellSchool_t{ SchoolNone=0, Abjuration, Conjuration, Divination, Enchantment, Evocation, Illusion, Necromancy, Transmutation, NumSpellSchool_t };
      enum CastingTime_t{ Action=0, BonusAction, Reaction, NumCastingTime_t };

      // String -> enum maps for JSON input (e.g., "Multiple" -> Multiple, "evocation" -> Evocation)
      static const std::unordered_map<std::string, Geometry_t> geometryNameMap;
      static const std::unordered_map<std::string, SpellSchool_t> schoolNameMap;

      std::string    name{"Unnamed Spell"};
      SpellType_t    type{Harm};
      Geometry_t     geometry{Single};
      SpellAttack_t  attack_type{AttackRoll};
      SaveAbility_t  save_ability{SaveDex};
      SpellSchool_t  school{SchoolNone};
      CastingTime_t  casting_time{Action};  // Action, BonusAction, or Reaction

      int range{30};    // range in feet to the target or area origin
      int radius{10};   // radius in feet (Cone, Sphere)
      int width{5};     // width in feet (Line)
      int length{30};   // length in feet (Line)
      int duration{1};  // turns the effect persists (1 = instantaneous)

      // For Multiple geometry: number of independent targets/projectiles
      int  num_targets{1};              // base number of targets at spell level
      int  targets_per_upcast_level{0}; // +1 target per upcast level (0 if doesn't scale)

      std::vector<MagicDamageRoll>    magic_damage_rolls;
      std::vector<PhysicalDamageRoll> physical_damage_rolls;
      HealingRoll                     healing_type{};  // Healing dice (for Heal spells)

      // Terrain effect created by this spell (e.g., Grease, Web, Spike Growth)
      // If terrain_difficulty is Normal (0), no terrain effect is created.
      // The terrain effect duration is the same as the spell's duration (in rounds).
      TerrainDifficulty terrain_difficulty{static_cast<TerrainDifficulty>(0)};  // Normal
      int slip_save_dc{10};       // Slipping terrain: DEX save DC
      int slip_distance_feet{5};  // Slipping terrain: feet moved before a save is required

      // Light effect created by this spell (e.g., Daylight, Light, Darkness)
      // If light_level is -1, no light effect is created.
      // The light effect duration is the same as the spell's duration (in rounds).
      int light_level{-1};  // VisibilityLevel enum value (-1 = none)

      bool requires_concentration{false};  // Caster must maintain concentration; breaks on damage
      // Sphere whose center follows the caster (D&D 2024 "Emanation"). The persistent
      // effect re-centers on the caster each turn / whenever the caster moves.
      bool moves_with_caster{false};
      // NOTE: neither flag is what makes a spell respect walls. Every area of effect is blocked by
      // Total Cover unconditionally — the engine refuses to place an aimed area behind a wall, and
      // prunes each area to the cells its point of origin can actually reach (BattleMap::areaOrigin
      // / pruneBlockedCells). These two flags are inferred from spell text and are false for most of
      // spells.json, so nothing load-bearing may depend on them.
      bool requires_los{false};            // Spell text explicitly demands a visible target ("one creature you can see")
      bool check_los_on_center{true};      // Legacy/no-op: wall pruning is now per-cell and unconditional
      bool requires_sight{false};          // Spell requires target to be visible (not blocked/heavily obscured)
      // "Creatures of your choosing" — a Harm AoE that intrinsically spares chosen creatures
      // (e.g. Radiance of the Dawn). When true, the caster's allies (same faction + claimed
      // neutrals) are auto-excluded from this spell's area without any Evoker/Careful feature.
      // Heal spells already restrict to allies via faction, so this flag is meaningful on Harm.
      bool selective_targeting{false};

      // Advantage emanation (data-driven). While this spell's persistent area is active, the
      // caster and its same-faction allies within `radius` ft of the caster have Advantage on
      // attack rolls and saving throws — a continuous, caster-following emanation. Evaluated at
      // roll time (CombatEngine::hasAdvantageAura) from the anchored ActiveSpellEffect, so it
      // follows the caster and ends automatically when that effect is removed (concentration
      // drop / duration expiry). Put it on a Sphere + moves_with_caster + duration>1 spell.
      bool grants_advantage_aura{false};

      int level{0};              // 0 = cantrip (unlimited); 1-9 = slot level required
      int upcast_dice_bonus{0};  // extra dice per slot level above spell.level

      // N/day usage tracking (for NPCs)
      // uses_max = 0 means unlimited (use slot system); uses_max > 0 means N/day
      int uses_max{0};           // maximum uses per day (0 = use slot system)
      int uses_remaining{0};     // current remaining uses

      // Recharge (Monster-Manual breath weapons): recharge_min == 0 ⇒ no recharge;
      // recharge_min > 0 ⇒ once cast the spell is `expended` until, at the owner's turn
      // start, a d6 ≥ recharge_min restores it. Independent of N/day uses (a pure-recharge
      // breath weapon uses uses_max = 1 + recharge_min = 5 or 6).
      int recharge_min{0};       // 0 = no recharge; 5 ⇒ (Recharge 5–6); 6 ⇒ (Recharge 6)
      bool expended{false};      // spent and waiting on a recharge roll

      // Class-feature casting: if non-empty, casting this "spell" spends the named
      // resource (e.g. "Channel Divinity") instead of a spell slot / N/day use.
      // Used by classfeatures.json entries (Divine Spark, Radiance of the Dawn, …).
      std::string resource_name{};
      int resource_cost{1};

      // Door interaction (Knock): opens/unlocks a door at the target cell. Detected
      // by this flag, not by spell name. Suppresses Arcane Lock for a few turns.
      bool opens_doors{false};

      // Dispel Magic: ends ongoing spells/conditions/effects on the target. Detected by
      // this flag, not by spell name (mirrors opens_doors). Dispatched to
      // CombatEngine::dispelMagic from executeSpell.
      bool dispels_magic{false};

      // Power Word Kill: a creature whose current Hit Points are <= this threshold
      // dies outright when the spell resolves (no damage roll, no death saves). Above
      // the threshold the spell falls through to its normal damage (12d12 Psychic).
      // 0 = disabled (no instant-kill gate).
      int instant_kill_threshold{0};

      // Power Word Stun: the spell's conditions take hold only if the target's current
      // Hit Points are <= this threshold. 0 = no gate (conditions always apply).
      int condition_hp_threshold{0};

      // Power Word Fortify / Mass Heal: a shared pool of Hit Points distributed among
      // every affected creature instead of rolling per-target healing dice. Mass Heal
      // fills each creature toward its HP maximum; Power Word Fortify hands out an even
      // share as Temporary HP. 0 = disabled (roll healing_type per target as usual).
      int hp_pool{0};
      // When true the pool grants Temporary HP (Power Word Fortify) rather than
      // restoring current HP (Mass Heal).
      bool pool_is_temp_hp{false};

      // Power Word Heal: the target regains all its Hit Points (healed to its HP
      // maximum) instead of rolling healing_type dice. false = roll dice as usual.
      bool heal_to_full{false};

      // Raise Dead / Revivify: this heal can restore a true-dead corpse (conditions.dead).
      // When true, applying the heal clears the target's `dead` condition before reviving,
      // so a corpse returns to life at the healed HP (RAW 1 HP). It also drives the GUI's
      // corpse-pick targeting mode (a dead body is not clickable via the normal path).
      bool revives_dead{false};

      // Divine Intervention D3 — Animate Dead: this spell targets a CORPSE (conditions.dead)
      // and raises an undead servant (Skeleton/Zombie) from it, rather than reviving the
      // original creature. The engine does nothing with this flag; it only drives the GUI's
      // corpse-pick targeting mode (shared with revives_dead) and the spawn-an-undead resolve.
      bool animates_dead{false};

      // Divine Intervention D4 — Magic Circle / Hallow: places a creature-type movement ward
      // (a timed emanation the chosen creature types can't cross). The types warded and the
      // direction (keep-out vs trap-inside) are chosen per cast and ride on the SpellAction
      // (ward_creature_mask / ward_traps); this flag only tells executeSpell to place the ward
      // zone (a Normal-difficulty terrain effect carrying the ward mask) at the aimed center.
      // Radius comes from `radius`; treat as a timed zone (non-concentration).
      bool creates_movement_ward{false};

      // Antilife Shell — a 10-ft emanation the caster carries that no living creature can cross
      // (only Undead and Constructs may pass). Reuses the movement-ward chokepoint, but instead of
      // a creature-type mask it wards by "is this creature alive?": the placed terrain effect gets
      // ward_all_living = true, and BattleMap::movementWardBlocks blocks any mover that is not
      // Undead (Construct is not modeled as a distinct type, so only Undead are exempt). The zone
      // is anchored to the caster (anchor_agent_idx) so it follows them like any emanation.
      bool ward_blocks_living{false};

      // Divine Intervention D3 — Planar Binding: on a failed Charisma save the targeted
      // creature is bound to the caster's service (transferred to the caster's team). The
      // engine does nothing with this flag; it only routes the GUI's single-target click to
      // the control-transfer resolve instead of the ordinary damage/heal cast path.
      bool binds_creature{false};

      // Restorative Heal: condition names ended on each (healed) target when the spell
      // resolves — e.g. Power Word Heal ends Charmed / Frightened / Paralyzed / Poisoned
      // / Stunned. Empty for ordinary heals. Each ends via removeAgentCondition so the
      // normal onConditionEnded teardown runs.
      std::vector<std::string> ends_conditions;

      // Teleportation spell (Misty Step, Dimension Door, Teleport)
      bool teleportation_spell{false};     // spell enables teleporting agents
      int max_teleport_targets{0};         // max number of agents (incl. caster) that can teleport (0 = not a teleport spell)
      int teleport_range_ft{0};            // range in feet for teleportation destination

      // Persistent AoE spell effect timing
      // Apply effects to agents in this spell's area at the START of their turn
      bool effects_on_begin_turn{true};
      // Apply effects to agents in this spell's area at the END of their turn
      bool effects_on_end_turn{false};

      // Condition application (e.g., Hold Person applies "Paralyzed")
      // Each condition can have its own duration and save rules
      std::vector<AttackCondition> conditions;  // Conditions applied to targets
    };
}
