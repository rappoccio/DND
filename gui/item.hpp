#pragma once
#include "weapon.hpp"
#include "cell.hpp"

namespace rpg {

struct MapItem {
    int         id          = -1;
    Cell        cell;
    Weapon      weapon;
    std::string sprite_path = "";
};

}  // namespace rpg
