#include "spell.hpp"

namespace rpg {

const std::unordered_map<std::string, Spell::Geometry_t> Spell::geometryNameMap {
    {"Single", Spell::Single},
    {"Line", Spell::Line},
    {"Cone", Spell::Cone},
    {"Sphere", Spell::Sphere},
    {"Multiple", Spell::Multiple}
};

const std::unordered_map<std::string, Spell::SpellSchool_t> Spell::schoolNameMap {
    {"abjuration", Spell::Abjuration},
    {"conjuration", Spell::Conjuration},
    {"divination", Spell::Divination},
    {"enchantment", Spell::Enchantment},
    {"evocation", Spell::Evocation},
    {"illusion", Spell::Illusion},
    {"necromancy", Spell::Necromancy},
    {"transmutation", Spell::Transmutation}
};

} // namespace rpg
