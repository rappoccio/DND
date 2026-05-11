#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include "agent.hpp"

namespace rpg {
    // Forward declare TerrainDifficulty to avoid circular includes
    enum class TerrainDifficulty;

    // Damage type with dice information
    struct MagicDamageRoll {
        MagicDamage_t type{};
        int num_dice{1};
        int die_size{6};
        int bonus{0};  // Fixed damage bonus (e.g., 1d4+1 has bonus=1)
    };

    struct PhysicalDamageRoll {
        PhysicalDamage_t type{};
        int num_dice{1};
        int die_size{6};
        int bonus{0};  // Fixed damage bonus
    };

    struct Spell {
      enum Geometry_t   { Single=0, Line, Cone, Sphere, Multiple, NumGeometry_t };
      enum SpellType_t  { Harm=0, Heal, NumSpellType_t };
      enum SpellAttack_t{ AttackRoll=0, Save, Automatic, NumSpellAttack_t };
      // Which ability the *target* uses for saving throws against this spell.
      enum SaveAbility_t{ SaveStr=0, SaveDex, SaveCon, SaveInt, SaveWis, SaveCha,
                          NumSaveAbility_t };

      // String -> enum map for JSON input (e.g., "Multiple" -> Multiple)
      static const std::unordered_map<std::string, Geometry_t> geometryNameMap;

      std::string    name{"Unnamed Spell"};
      SpellType_t    type{Harm};
      Geometry_t     geometry{Single};
      SpellAttack_t  attack_type{AttackRoll};
      SaveAbility_t  save_ability{SaveDex};

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

      // Terrain effect created by this spell (e.g., Grease, Web, Spike Growth)
      // If terrain_difficulty is Normal (0), no terrain effect is created.
      // The terrain effect duration is the same as the spell's duration (in rounds).
      TerrainDifficulty terrain_difficulty{static_cast<TerrainDifficulty>(0)};  // Normal

      bool requires_concentration{false};  // Caster must maintain concentration; breaks on damage
      bool requires_los{false};            // Spell requires line of sight to target/area
      bool check_los_on_center{true};      // If true, only the spell center needs LOS (user configurable)

      int level{0};              // 0 = cantrip (unlimited); 1-9 = slot level required
      int upcast_dice_bonus{0};  // extra dice per slot level above spell.level

      // N/day usage tracking (for NPCs)
      // uses_max = 0 means unlimited (use slot system); uses_max > 0 means N/day
      int uses_max{0};           // maximum uses per day (0 = use slot system)
      int uses_remaining{0};     // current remaining uses
    };
}
