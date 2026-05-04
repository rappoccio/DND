// ─────────────────────────────────────────────────────────────────────────────
//  main.cpp  –  Entry point for the RPG Battle Map viewer
//
//  Usage:  ./rpg_map  <map_image_path>
//
//  The window shows the map with the grid and walls overlaid.
//  An ImGui panel (Agent Configuration) lets you add agents live.
// ─────────────────────────────────────────────────────────────────────────────

#include "battle_map.hpp"

#include <SFML/Graphics.hpp>
#include <imgui.h>
#include <imgui-SFML.h>

#include <cstdlib>
#include <filesystem>
#include <print>

int main(int argc, char* argv[])
{
    if (argc < 2) {
        std::println(stderr, "Usage: {} <map_image_path>", argv[0]);
        return EXIT_FAILURE;
    }

    // ── Analyse the map before opening the window ─────────────────────────
    rpg::BattleMap battleMap{std::filesystem::path{argv[1]}};

    try {
        battleMap.analyzeGrid();
        battleMap.detectWalls();
    } catch (const std::exception& e) {
        std::println(stderr, "Error analysing map: {}", e.what());
        return EXIT_FAILURE;
    }

    // ── Create SFML window ────────────────────────────────────────────────
    const auto& tex = battleMap;   // just for readable sizing
    sf::VideoMode mode{800, 600};  // default; adjust to map texture size
    sf::RenderWindow window{mode, "RPG Battle Map", sf::Style::Default};
    window.setFramerateLimit(60);

    // ── ImGui ─────────────────────────────────────────────────────────────
    ImGui::SFML::Init(window);
    ImGui::GetIO().FontGlobalScale = 1.2f;

    sf::Clock deltaClock;

    while (window.isOpen()) {
        // ── Events ────────────────────────────────────────────────────────
        sf::Event event{};
        while (window.pollEvent(event)) {
            ImGui::SFML::ProcessEvent(window, event);
            if (event.type == sf::Event::Closed)
                window.close();
            if (event.type == sf::Event::KeyPressed &&
                event.key.code == sf::Keyboard::Escape)
                window.close();
        }

        // ── ImGui frame ───────────────────────────────────────────────────
        ImGui::SFML::Update(window, deltaClock.restart());
        battleMap.showConfigGUI();   // draws the token configuration panel

        // ── Render ────────────────────────────────────────────────────────
        window.clear(sf::Color{30, 30, 30});
        battleMap.draw(window);
        ImGui::SFML::Render(window);
        window.display();
    }

    ImGui::SFML::Shutdown();
    return EXIT_SUCCESS;
}
