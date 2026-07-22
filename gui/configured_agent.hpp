#include "agent.hpp"
#include <iostream>

namespace rpg{

// Diagnostic verbosity gate (defined in battle_map.cpp). The ConfiguredAgent action stubs below
// print "[name] …" traces to stdout; those are silenced in headless/test runs when this is false.
bool battleMapVerbose() noexcept;


// ─────────────────────────────────────────────────────────────────────────────
//  ConfiguredAgent class
// ─────────────────────────────────────────────────────────────────────────────
class ConfiguredAgent final : public Agent {
public:
    ConfiguredAgent(std::string name, int col, int row, int size,
                    std::filesystem::path sprite)
        : Agent{col, row, 0, size, std::move(sprite)}
        , name_{std::move(name)}
    {}

  ConfiguredAgent( std::string name,
		   std::string source,
		   std::string mob_size,
		   std::string mob_type,
		   std::string moral_alignment,
		   std::string habitat,
		   std::string treasure,
		   std::string languages,
		   int col, int row, int size,
		   std::filesystem::path sprite)
        : Agent{col, row, 0, size, std::move(sprite)}
        , name_           {std::move(name)}
	, source_         {std::move(source)}
	, mob_size_       {std::move(mob_size)}
	, mob_type_       {std::move(mob_type)}
	, moral_alignment_{std::move(moral_alignment)}
	, habitat_        {std::move(habitat)}
	, treasure_       {std::move(treasure)}
	, languages_      {std::move(languages)}
    {}

  
    std::string_view name()             const noexcept override { return name_; }
    void setName(std::string name)            noexcept override { name_ = std::move(name); }
    std::string_view source()           const noexcept override { return source_; }
    std::string_view mob_size()         const noexcept override { return mob_size_; }
    std::string_view mob_type()         const noexcept override { return mob_type_; }
    std::string_view moral_alignment()  const noexcept override { return moral_alignment_; }
    std::string_view habitat()          const noexcept override { return habitat_; }
    std::string_view treasure()         const noexcept override { return treasure_; }
    std::string_view languages()        const noexcept override { return languages_; }
  
    void takeTurn()    override { if (battleMapVerbose()) std::cout << "[" << name_ << "] awaiting input...\n"; }
    void action()      override { if (battleMapVerbose()) std::cout << "[" << name_ << "] action\n"; }
    void attack()      override { if (battleMapVerbose()) std::cout << "[" << name_ << "] attack\n"; }
    void dash()        override { conditions_.dashing = true;  if (battleMapVerbose()) std::cout << "[" << name_ << "] dash\n"; }
    void disengage()   override { conditions_.disengaging = true; if (battleMapVerbose()) std::cout << "[" << name_ << "] disengage\n"; }
    void dodge()       override { conditions_.dodging = true;  if (battleMapVerbose()) std::cout << "[" << name_ << "] dodge\n"; }
    void hide()        override { conditions_.hidden  = true;  if (battleMapVerbose()) std::cout << "[" << name_ << "] hide\n"; }
    void bonusAction() override { if (battleMapVerbose()) std::cout << "[" << name_ << "] bonusAction\n"; }
    void walk()        override { if (battleMapVerbose()) std::cout << "[" << name_ << "] walk\n"; }
    void fly()         override { if (battleMapVerbose()) std::cout << "[" << name_ << "] fly\n"; }
    void reaction()    override { if (battleMapVerbose()) std::cout << "[" << name_ << "] reaction\n"; }

private:
    std::string name_;
    std::string source_;
    std::string mob_size_;
    std::string mob_type_;
    std::string moral_alignment_;
    std::string habitat_;
    std::string treasure_;
    std::string languages_;
};
  
}
