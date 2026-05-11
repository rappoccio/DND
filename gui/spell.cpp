#include "spell.hpp"

namespace rpg {

const std::unordered_map<std::string, Spell::Geometry_t> Spell::geometryNameMap {
    {"Single", Spell::Single},
    {"Line", Spell::Line},
    {"Cone", Spell::Cone},
    {"Sphere", Spell::Sphere},
    {"Multiple", Spell::Multiple}
};

} // namespace rpg
