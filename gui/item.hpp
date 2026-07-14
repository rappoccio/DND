#pragma once
#include "weapon.hpp"
#include "cell.hpp"
#include "damage.hpp"

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Item — a carried, usable piece of gear (potions today; scrolls/grenades later).
//
//  Data-driven from items.json exactly the way spells come from spells.json: the
//  catalog is authored as JSON, the GUI turns a record into one of these (see
//  helpers._dict_to_item), and the engine resolves it (CombatEngine::useItem).
//  Distinct from MapItem below, which is a *weapon lying on the floor*.
// ─────────────────────────────────────────────────────────────────────────────
struct Item {
    // What using the item does. Only Heal is resolved today; the enum exists so
    // useItem can branch as new kinds land (Damage grenades, Buff oils, …).
    enum ItemType_t   { Heal = 0, NumItemType_t };
    // Action economy cost of using it. NoAction = free (e.g. an always-on trinket).
    enum ItemAction_t { Action = 0, BonusAction, NoAction, NumItemAction_t };

    std::string  name{"Unnamed Item"};
    std::string  description{};
    ItemType_t   type{Heal};
    ItemAction_t action_type{BonusAction};

    // Reach, in feet, for administering the item to *another* creature. 0 = self only.
    // A Potion of Healing is 5 ft ("drink it or administer it to another creature").
    int         range{5};
    HealingRoll healing{};   // Heal items: dice + flat bonus (2d4+2 for a Potion of Healing)

    int  quantity{1};        // how many are carried; each use decrements it
    bool consumable{true};   // false ⇒ reusable: quantity never drops
    std::string sprite_path{};
};

struct MapItem {
    int         id          = -1;
    Cell        cell;
    Weapon      weapon;
    std::string sprite_path = "";
};

}  // namespace rpg
