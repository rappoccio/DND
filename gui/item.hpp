#pragma once
#include "weapon.hpp"
#include "cell.hpp"
#include "damage.hpp"

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Item — a carried, usable piece of gear: potions and thrown flasks today (Acid,
//  Alchemist's Fire, Holy Water, Net); scrolls later.
//
//  Data-driven from items.json exactly the way spells come from spells.json: the
//  catalog is authored as JSON, the GUI turns a record into one of these (see
//  helpers._dict_to_item), and the engine resolves it (CombatEngine::useItem).
//  Distinct from MapItem below, which is a *weapon lying on the floor*.
// ─────────────────────────────────────────────────────────────────────────────
struct Item {
    // What using the item does. Heal = a potion; Thrown = a flask/vial/Net hurled at a
    // creature, which resolves as a saving throw (see the Thrown block below).
    enum ItemType_t   { Heal = 0, Thrown, NumItemType_t };
    // Action economy cost of using it. NoAction = free (e.g. an always-on trinket).
    // AttackReplacement is the thrown-item cost: "when you take the Attack action, you can
    // replace one of your attacks with throwing this" — so a Fighter with Extra Attack can
    // throw a flask and still swing. The GUI spends it out of the Attack action's swing
    // budget exactly as Eldritch Knight War Magic does; there is no engine-side budget.
    enum ItemAction_t { Action = 0, BonusAction, NoAction, AttackReplacement, NumItemAction_t };

    std::string  name{"Unnamed Item"};
    std::string  description{};
    ItemType_t   type{Heal};
    ItemAction_t action_type{BonusAction};

    // Reach, in feet. For a Heal item this is how far you can reach to administer it to
    // *another* creature (0 = self only); a Potion of Healing is 5 ft ("drink it or
    // administer it to another creature"). For a Thrown item it is the throwing range
    // (20 ft for the flasks, 15 ft for a Net).
    int         range{5};
    HealingRoll healing{};   // Heal items: dice + flat bonus (2d4+2 for a Potion of Healing)

    // ── Thrown items (Acid, Alchemist's Fire, Holy Water, Net) ──────────────────────────
    //  "Target one creature you can see within <range> feet. The target must succeed on a
    //   Dexterity saving throw (DC 8 plus your Dexterity modifier and Proficiency Bonus) or
    //   <take damage / gain a condition>."
    //  The DC comes from the THROWER's ability + PB, so it is derived at use time rather
    //  than authored in items.json. A miss (successful save) does nothing — these items
    //  have no half-damage-on-a-save.
    MagicDamageRoll damage{Acid, 0, 6, 0};  // num_dice 0 ⇒ deals no damage (a Net)
    SaveAbility_t   save_ability{SaveDex};

    // Condition applied on a failed save: "Burning" (Alchemist's Fire) or "Restrained"
    // (Net). Empty ⇒ damage only. Anything else is ignored by useItem.
    std::string condition_applied{};

    // Holy Water: "…or take 2d8 Radiant damage IF IT IS a Fiend or an Undead." Anything
    // else is simply splashed and unharmed (no save is even rolled).
    bool only_vs_fiend_undead{false};

    // Net: "The target succeeds automatically if it is Huge or larger." Sizes are the
    // agent footprint in cells (1 = Medium/Small, 2 = Large, 3 = Huge), so a Net authors
    // max_target_size 2. 0 ⇒ no size limit.
    int max_target_size{0};
    // Net: "To escape, the target or a creature within 5 feet of it must take an action to
    // make a DC 10 Strength (Athletics) check." 0 ⇒ the condition is not escapable this way.
    int escape_dc{0};

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
