#pragma once

#include "agent.hpp"
#include <iostream>

namespace rpg {

// ── Example concrete agent: a player character ────────────────────────────
class PlayerAgent final : public Agent {
public:
    PlayerAgent(int x, int y, int z, std::filesystem::path sprite)
        : Agent{x, y, z, /*size=*/1, std::move(sprite)}
    {}

    std::string_view name() const noexcept override { return "Player"; }

    void takeTurn() override {
        conditions_.dashing = conditions_.disengaging = conditions_.dodging = false; 
        std::cout << "[" << name() << "] awaiting player input...\n";
    }
    void action() override {
        std::cout << "[" << name() << "] takes an Action\n";
    }
    void attack()    override { std::cout << "[" << name() << "] attacks\n"; }
    void dash()      override { conditions_.dashing = true;      std::cout << "[" << name() << "] dashes\n"; }
    void disengage() override { conditions_.disengaging = true;  std::cout << "[" << name() << "] disengages\n"; }
    void dodge()     override { conditions_.dodging = true;      std::cout << "[" << name() << "] dodges\n"; }

    void bonusAction() override {
        std::cout << "[" << name() << "] takes a Bonus Action\n";
    }

    void walk() override {
        std::cout << "[" << name() << "] walks\n";
    }
    void fly() override {
        std::cout << "[" << name() << "] cannot fly\n";
    }

    void reaction() override {
        std::cout << "[" << name() << "] reacts\n";
    }
};

// ── Example: a large monster (3x3 footprint) ──────────────────────────────
class DragonAgent final : public Agent {
public:
    DragonAgent(int x, int y, int z, std::filesystem::path sprite)
        : Agent{x, y, z, /*size=*/3, std::move(sprite)}
    {}

    std::string_view name() const noexcept override { return "Dragon"; }

    void takeTurn()    override { std::cout << "[Dragon] awaiting AI input...\n"; }
    void action()      override { std::cout << "[Dragon] breathes fire!\n"; }
    void attack()      override { std::cout << "[Dragon] bites!\n"; }
    void dash()        override { conditions_.dashing = true;     std::cout << "[Dragon] dashes\n"; }
    void disengage()   override { conditions_.disengaging = true; std::cout << "[Dragon] disengages\n"; }
    void dodge()       override { conditions_.dodging = true;     std::cout << "[Dragon] dodges\n"; }
    void bonusAction() override { std::cout << "[Dragon] uses Legendary Resistance\n"; }
    void walk() override { std::cout << "[Dragon] walks 40 ft\n"; }
    void fly()  override { std::cout << "[Dragon] flies 80 ft\n"; }
    void reaction()    override { std::cout << "[Dragon] snaps at the attacker\n"; }
};

// ── Compile-time verification that both types satisfy AgentLike ───────────
static_assert(AgentLike<PlayerAgent>);
static_assert(AgentLike<DragonAgent>);

} // namespace rpg
