#pragma once
#include <string>
#include <vector>
#include "agent.hpp"

namespace rpg {
    // Forward declare TerrainDifficulty to avoid circular includes
    enum class TerrainDifficulty;

    // Damage type with dice information
    struct MagicDamageRoll {
        MagicDamage_t type{};
        int num_dice{1};
        int die_size{6};
    };

    struct PhysicalDamageRoll {
        PhysicalDamage_t type{};
        int num_dice{1};
        int die_size{6};
    };

    struct Spell {
      enum Geometry_t   { Single=0, Line, Cone, Sphere, NumGeometry_t };
      enum SpellType_t  { Harm=0, Heal, NumSpellType_t };
      enum SpellAttack_t{ AttackRoll=0, Save, Automatic, NumSpellAttack_t };
      // Which ability the *target* uses for saving throws against this spell.
      enum SaveAbility_t{ SaveStr=0, SaveDex, SaveCon, SaveInt, SaveWis, SaveCha,
                          NumSaveAbility_t };

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

      std::vector<MagicDamageRoll>    magic_damage_rolls;
      std::vector<PhysicalDamageRoll> physical_damage_rolls;

      // Terrain effect created by this spell (e.g., Grease, Web, Spike Growth)
      // If terrain_difficulty is Normal (0), no terrain effect is created.
      // The terrain effect duration is the same as the spell's duration (in rounds).
      TerrainDifficulty terrain_difficulty{static_cast<TerrainDifficulty>(0)};  // Normal

      bool requires_concentration{false};  // Caster must maintain concentration; breaks on damage
    };
}
