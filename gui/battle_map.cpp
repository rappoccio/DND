// ─────────────────────────────────────────────────────────────────────────────
//  battle_map.cpp  –  OpenCV grid/wall analysis core (no rendering)
// ─────────────────────────────────────────────────────────────────────────────

#include "battle_map.hpp"
#include "configured_agent.hpp"
#include <opencv2/opencv.hpp>

#include <algorithm>
#include <cassert>
#include <cmath>
#include <format>
#include <queue>
#include <ranges>
#include <stdexcept>
#include <string_view>
#include <unordered_map>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
BattleMap::BattleMap(std::filesystem::path p) : mapImagePath_{std::move(p)}
{
    if (!std::filesystem::exists(mapImagePath_))
        throw std::runtime_error{
            std::format("BattleMap: image not found: {}", mapImagePath_.string())};
}

BattleMap::~BattleMap() = default;

// ─────────────────────────────────────────────────────────────────────────────
//  Grid detection
// ─────────────────────────────────────────────────────────────────────────────
static std::vector<int> clusterLines(std::vector<int> pos, int tol = 8)
{
    if (pos.empty()) return {};
    std::ranges::sort(pos);
    std::vector<int> out;
    int gs = pos[0], gsum = pos[0], gc = 1;
    for (std::size_t i = 1; i < pos.size(); ++i) {
        if (pos[i] - gs <= tol) { gsum += pos[i]; ++gc; }
        else { out.push_back(gsum / gc); gs = pos[i]; gsum = pos[i]; gc = 1; }
    }
    out.push_back(gsum / gc);
    return out;
}

static void detectGridLines(const cv::Mat& gray,
                             std::vector<int>& outH,
                             std::vector<int>& outV,
                             const BattleMap::DetectionParams& params)
{
    cv::Mat edges;
    cv::Canny(gray, edges, params.cannyLow, params.cannyHigh);

    std::vector<cv::Vec4i> segs;
    cv::HoughLinesP(edges, segs,
                    1, CV_PI / 180,
                    params.houghThreshold,
                    params.minLineLength,
                    params.maxLineGap);

    std::vector<int> rawH, rawV;
    for (const auto& s : segs) {
        int dx = std::abs(s[2] - s[0]), dy = std::abs(s[3] - s[1]);
        if (dy < dx / 4) rawH.push_back((s[1] + s[3]) / 2);
        else if (dx < dy / 4) rawV.push_back((s[0] + s[2]) / 2);
    }
    outH = clusterLines(rawH);
    outV = clusterLines(rawV);
    std::cout << std::format("[BattleMap] {} h-lines, {} v-lines detected\n",
                 outH.size(), outV.size());
}

void BattleMap::analyzeGrid()
{
    cv::Mat img = cv::imread(mapImagePath_.string());
    if (img.empty())
        throw std::runtime_error{"BattleMap::analyzeGrid – cv::imread failed"};

    cv::Mat gray;
    cv::cvtColor(img, gray, cv::COLOR_BGR2GRAY);
    detectGridLines(gray, hLines_, vLines_, params);

    rows_ = static_cast<int>(hLines_.size()) - 1;
    cols_ = static_cast<int>(vLines_.size()) - 1;
    if (rows_ <= 0 || cols_ <= 0)
        throw std::runtime_error{"BattleMap::analyzeGrid – no valid grid found"};

    auto medianGap = [](const std::vector<int>& v) {
        std::vector<int> g;
        for (std::size_t i = 1; i < v.size(); ++i) g.push_back(v[i] - v[i-1]);
        std::ranges::sort(g);
        return g[g.size() / 2];
    };
    int hg = (hLines_.size() > 1) ? medianGap(hLines_) : img.rows;
    int vg = (vLines_.size() > 1) ? medianGap(vLines_) : img.cols;
    cellPx_ = (hg + vg) / 2;

    // Initialize terrain multipliers (default 1.0)
    terrainMult_.assign(static_cast<std::size_t>(rows_ * cols_), 1.0);

    // Initialize terrain types (default Standard)
    terrainType_.assign(static_cast<std::size_t>(rows_ * cols_), TerrainType::Standard);

    // Initialize temporary terrain difficulty overlay (default Normal)
    tempTerrainDiff_.assign(static_cast<std::size_t>(rows_ * cols_), TerrainDifficulty::Normal);

    // Initialize base and computed light levels (default BrightLight)
    baseVisibilityLevel_.assign(static_cast<std::size_t>(rows_ * cols_), VisibilityLevel::Clear);
    lightLevel_.assign(static_cast<std::size_t>(rows_ * cols_), VisibilityLevel::Clear);

    std::cout << std::format("[BattleMap] Grid {}×{}, ~{}px/cell\n", cols_, rows_, cellPx_);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Wall detection
// ─────────────────────────────────────────────────────────────────────────────

// Primary method: sample the interior of each cell.
// Cells whose mean brightness is below darkThreshold are flagged as blocked.
static void detectDarkCells(const cv::Mat& gray,
                              int rows, int cols,
                              const std::vector<int>& hLines,
                              const std::vector<int>& vLines,
                              double darkThreshold,
                              CellSet& blocked)
{
    const int margin = 2;   // inset from cell edge to avoid grid-line pixels
    int count = 0;
    for (int r = 0; r < rows; ++r) {
        for (int c = 0; c < cols; ++c) {
            int x0 = vLines[c]   + margin;
            int y0 = hLines[r]   + margin;
            int x1 = vLines[c+1] - margin;
            int y1 = hLines[r+1] - margin;
            if (x1 <= x0 || y1 <= y0) continue;

            cv::Rect roi(x0, y0, x1 - x0, y1 - y0);
            double mean = cv::mean(gray(roi))[0];
            if (mean < darkThreshold) {
                blocked.insert({c, r});
                ++count;
            }
        }
    }
    std::cout << std::format("[BattleMap] {} dark (wall) cells detected (threshold={})\n",
                 count, darkThreshold);
}

// Secondary method: edge-based detection for maps that use thick lines
// between cells rather than filled black cells.
static bool isWallStrip(const cv::Mat& mask, int pos, bool horiz,
                         int s0, int s1, int minPx)
{
    int count = 0, area = 0;
    for (int d = -minPx; d <= minPx; ++d) {
        int p = pos + d;
        if (p < 0) continue;
        if (horiz  && p >= mask.rows) break;
        if (!horiz && p >= mask.cols) break;
        for (int s = s0; s < s1; ++s) {
            uchar v = horiz ? mask.at<uchar>(p, s) : mask.at<uchar>(s, p);
            count += (v > 128); ++area;
        }
    }
    return area > 0 && static_cast<float>(count) / static_cast<float>(area) > 0.25f;
}

static void detectEdgeWalls(const cv::Mat& gray,
                              int rows, int cols,
                              const std::vector<int>& hLines,
                              const std::vector<int>& vLines,
                              int wallMinPx,
                              std::vector<Wall>& walls)
{
    cv::Mat bin;
    cv::adaptiveThreshold(gray, bin, 255,
                          cv::ADAPTIVE_THRESH_GAUSSIAN_C,
                          cv::THRESH_BINARY_INV, 15, 4);

    for (int r = 0; r < rows; ++r)
        for (int c = 0; c < cols; ++c)
            if (isWallStrip(bin, hLines[r+1], true,
                             vLines[c], vLines[c+1], wallMinPx))
                walls.push_back({{c,r},{c,r+1}});

    for (int c = 0; c < cols; ++c)
        for (int r = 0; r < rows; ++r)
            if (isWallStrip(bin, vLines[c+1], false,
                             hLines[r], hLines[r+1], wallMinPx))
                walls.push_back({{c,r},{c+1,r}});

    std::cout << std::format("[BattleMap] {} edge walls detected\n", walls.size());
}

void BattleMap::floodFillPassable()
{
    auto wallKey = [](Cell a, Cell b) -> std::size_t {
        return (std::size_t(a.col)<<48)|(std::size_t(a.row)<<32)
              |(std::size_t(b.col)<<16)| std::size_t(b.row);
    };
    std::unordered_set<std::size_t> wset;
    for (auto& w : walls_) {
        wset.insert(wallKey(w.a, w.b));
        wset.insert(wallKey(w.b, w.a));
    }

    auto inBounds = [&](Cell c){ return c.col>=0&&c.row>=0&&c.col<cols_&&c.row<rows_; };
    CellSet passable;
    std::queue<Cell> q;
    if (inBounds(params.floodSeed)) { q.push(params.floodSeed); passable.insert(params.floodSeed); }

    const std::array<Cell,4> dirs{{{0,-1},{0,1},{-1,0},{1,0}}};
    while (!q.empty()) {
        Cell cur = q.front(); q.pop();
        for (auto& d : dirs) {
            Cell nb{cur.col+d.col, cur.row+d.row};
            if (!inBounds(nb)||passable.contains(nb)||wset.contains(wallKey(cur,nb))) continue;
            passable.insert(nb); q.push(nb);
        }
    }

    for (int r=0;r<rows_;++r)
        for (int c=0;c<cols_;++c) {
            Cell cell{c,r};
            if (!passable.contains(cell)) disallowed_.insert(cell);
        }
    std::cout << std::format("[BattleMap] {} disallowed cells\n", disallowed_.size());
}

void BattleMap::detectWalls()
{
    assert(cols_ > 0 && "Call analyzeGrid() before detectWalls()");
    cv::Mat img = cv::imread(mapImagePath_.string());
    cv::Mat gray;
    cv::cvtColor(img, gray, cv::COLOR_BGR2GRAY);

    // Primary: any cell whose interior is darker than the threshold is a wall/obstacle.
    // Results go directly into disallowed_ so they block token placement.
    detectDarkCells(gray, rows_, cols_, hLines_, vLines_,
                    params.darkCellThreshold, disallowed_);

    // Secondary (opt-in): detect thick lines drawn *between* cells as walls.
    // Only needed for maps that draw explicit wall strokes rather than black cells.
    if (params.detectEdgeWalls)
        detectEdgeWalls(gray, rows_, cols_, hLines_, vLines_,
                        params.wallMinPx, walls_);

    // Flood fill from the seed cell to mark everything unreachable as disallowed.
    if (params.floodFill) floodFillPassable();
}

// ─────────────────────────────────────────────────────────────────────────────
//  Passability
// ─────────────────────────────────────────────────────────────────────────────
bool BattleMap::isBlocked(Cell origin, int size, MovementType mt) const noexcept
{
    for (int dc=0;dc<size;++dc) {
        for (int dr=0;dr<size;++dr) {
            Cell c{origin.col+dc, origin.row+dr};

            // Check if cell is in disallowed_ (auto-detected walls)
            if (disallowed_.contains(c)) {
                // Walls are passable only to burrowers
                if (mt != MovementType::Burrow) return true;
                continue;
            }

            // Check terrain type against passability table
            auto isPassable = [&]() -> bool {
                switch (terrainType_[c.row * cols_ + c.col]) {
                    case TerrainType::Standard:
                        return mt != MovementType::Swim;
                    case TerrainType::Water:
                        return mt == MovementType::Fly || mt == MovementType::Swim || mt == MovementType::Jump;
                    case TerrainType::Wall:
                        return mt == MovementType::Burrow;
                    case TerrainType::Chasm:
                        return mt == MovementType::Fly || mt == MovementType::Jump;
                }
                return true;
            }();

            if (!isPassable) return true;
        }
    }
    return false;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Agent management
// ─────────────────────────────────────────────────────────────────────────────
void BattleMap::addAgentConfig(AgentConfig cfg) { agentConfigs_.push_back(std::move(cfg)); }

void BattleMap::applyAgentConfigs()
{
    placedAgents_.clear();
    for (const auto& cfg : agentConfigs_) {
        Cell origin{cfg.startCol, cfg.startRow};
        if (isBlocked(origin, cfg.size)) {
            std::cout << std::format("[BattleMap] '{}' skipped – blocked\n", cfg.name);
            continue;
        }
        auto tok = std::make_shared<ConfiguredAgent>(
            cfg.name, cfg.startCol, cfg.startRow, cfg.size, cfg.spritePath);
        placedAgents_.push_back({std::move(tok), origin, {}, {}, {}, {}});
    }
    std::cout << std::format("[BattleMap] {} agents placed\n", placedAgents_.size());
}

void BattleMap::clearAgents() { placedAgents_.clear(); agentConfigs_.clear(); }

std::span<const PlacedAgent> BattleMap::placedAgents() const noexcept
{
    return placedAgents_;
}

bool BattleMap::moveAgent(int idx, Cell newOrigin, MovementType type) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return false;
    auto& pa = placedAgents_[idx];

    // For fly movement, check if destination is in reachable set (respects walls)
    if (type == MovementType::Fly) {
        int remaining = pa.agent->getFlyRemaining();
        if (remaining <= 0)
            return false;

        // Use reachableCells to validate destination (respects wall terrain)
        CellSet reachable = reachableCells(pa.origin, pa.agent->getSize(), remaining, MovementType::Fly);
        std::fprintf(stderr, "[C++ FLY] Origin: (%d,%d), Dest: (%d,%d), Reachable size: %zu\n",
            pa.origin.col, pa.origin.row, newOrigin.col, newOrigin.row, reachable.size());

        // Print first 20 reachable cells for debugging
        int count = 0;
        for (const auto& c : reachable) {
            if (count++ < 20) {
                std::fprintf(stderr, "  [%d,%d]", c.col, c.row);
            } else {
                std::fprintf(stderr, "  ...");
                break;
            }
        }
        std::fprintf(stderr, "\n");

        if (reachable.find(newOrigin) == reachable.end()) {
            std::fprintf(stderr, "[C++ FLY] Destination blocked!\n");
            return false;
        }

        std::fprintf(stderr, "[C++ FLY] Move allowed\n");
        pa.agent->flyTo(newOrigin.col, newOrigin.row);
        pa.origin = newOrigin;
        return true;
    }

    // For walk/swim/burrow, calculate actual path cost using Dijkstra
    // Find the cheapest path cost from origin to newOrigin
    using PQItem = std::pair<int, Cell>;
    auto cmp = [](const PQItem& a, const PQItem& b) { return a.first > b.first; };
    std::priority_queue<PQItem, std::vector<PQItem>, decltype(cmp)> pq(cmp);
    std::unordered_map<Cell, int, CellHash> dist;

    dist[pa.origin] = 0;
    pq.push({0, pa.origin});

    int actual_cost = -1;  // -1 means unreachable
    while (!pq.empty()) {
        auto [cost, cell] = pq.top();
        pq.pop();

        if (cell == newOrigin) {
            actual_cost = cost;
            break;
        }

        if (dist.count(cell) && dist[cell] < cost) continue;

        for (int dr = -1; dr <= 1; ++dr) {
            for (int dc = -1; dc <= 1; ++dc) {
                if (dr == 0 && dc == 0) continue;
                Cell next{cell.col + dc, cell.row + dr};

                if (!inBounds(next, pa.agent->getSize())) continue;
                if (isBlocked(next, pa.agent->getSize(), type)) continue;

                int step_cost = (dr != 0 && dc != 0) ? 10 : 5;

                // Apply crawling penalty if prone (2x cost in normal terrain, 3x in difficult)
                if (pa.agent->getConditions().prone) {
                    double terrain_mult = getTerrainMultiplier(next, type);
                    if (terrain_mult < 1.0) {  // difficult terrain (multiplier < 1)
                        step_cost = static_cast<int>(step_cost * 3);
                    } else {
                        step_cost = step_cost * 2;
                    }
                }

                double terrain_mult = getTerrainMultiplier(next, type);
                int new_cost = cost + static_cast<int>(step_cost / terrain_mult);

                if (!dist.count(next) || dist[next] > new_cost) {
                    dist[next] = new_cost;
                    pq.push({new_cost, next});
                }
            }
        }
    }

    if (actual_cost < 0 || actual_cost > 200)  // 200 is practical max
        return false;

    // Check movement budget based on type
    int remaining = 0;
    switch (type) {
        case MovementType::Walk:   remaining = pa.agent->getWalkRemaining(); break;
        case MovementType::Swim:   remaining = pa.agent->getSwimRemaining(); break;
        case MovementType::Burrow: remaining = pa.agent->getBurrowRemaining(); break;
        default: return false;
    }

    if (actual_cost > remaining)
        return false;

    // Deduct the actual cost
    pa.agent->addMovement(
        (type == MovementType::Walk ? -actual_cost : 0),
        0,
        (type == MovementType::Swim ? -actual_cost : 0),
        (type == MovementType::Burrow ? -actual_cost : 0)
    );

    pa.origin = newOrigin;
    return true;
}

bool BattleMap::jumpAgent(int idx, Cell newOrigin, bool is_running) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return false;
    auto& pa = placedAgents_[idx];

    // Calculate jump distance in feet (Manhattan distance)
    int jump_dist_cells = std::abs(newOrigin.col - pa.origin.col) +
                          std::abs(newOrigin.row - pa.origin.row);
    int jump_dist_ft = jump_dist_cells * 5;

    // Determine max jump distance based on strength and running/standing
    int strength = pa.stats.str;
    int max_jump_ft = is_running ? strength : (strength / 2);

    // Check if jump is within range
    if (jump_dist_ft > max_jump_ft)
        return false;

    // Check if agent has enough walk movement budget (jumping uses walk budget)
    if (pa.agent->getWalkRemaining() < jump_dist_ft)
        return false;

    // Move using flyTo to ignore walls (this deducts from fly_remaining)
    bool moved = pa.agent->flyTo(newOrigin.col, newOrigin.row);
    if (!moved)
        return false;

    // Adjust movement budgets: refund fly and deduct from walk
    // addMovement with negative values will subtract from the budgets
    pa.agent->addMovement(-jump_dist_ft,  // deduct from walk
                          jump_dist_ft,    // refund fly
                          0, 0);

    pa.origin = newOrigin;
    return true;
}

int BattleMap::forceMoveAgent(int idx, Cell push_from, int push_ft) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return 0;
    auto& pa = placedAgents_[idx];
    int agent_size = pa.agent->getSize();

    // Compute direction: away from push_from toward target
    int dir_col = 0, dir_row = 0;
    if (pa.origin.col != push_from.col)
        dir_col = (pa.origin.col > push_from.col) ? 1 : -1;
    if (pa.origin.row != push_from.row)
        dir_row = (pa.origin.row > push_from.row) ? 1 : -1;

    // Move cell-by-cell for push_ft/5 cells
    int max_cells = push_ft / 5;
    int cells_moved = 0;

    for (int i = 0; i < max_cells; ++i) {
        Cell next{pa.origin.col + dir_col, pa.origin.row + dir_row};

        // Check bounds
        if (!inBounds(next, agent_size))
            break;

        // Check if blocked (use Walk movement type — can't push through walls)
        if (isBlocked(next, agent_size, MovementType::Walk))
            break;

        // Move to next cell
        pa.origin = next;
        pa.agent->setPosition(next.col, next.row);
        cells_moved++;
    }

    // If diagonal movement was blocked, try orthogonal fallback
    if (cells_moved == 0 && dir_col != 0 && dir_row != 0) {
        // Try horizontal first
        for (int i = 0; i < max_cells; ++i) {
            Cell next{pa.origin.col + dir_col, pa.origin.row};
            if (!inBounds(next, agent_size) || isBlocked(next, agent_size, MovementType::Walk))
                break;
            pa.origin = next;
            pa.agent->setPosition(next.col, next.row);
            cells_moved++;
        }
        // Then try vertical if horizontal didn't work
        if (cells_moved == 0) {
            for (int i = 0; i < max_cells; ++i) {
                Cell next{pa.origin.col, pa.origin.row + dir_row};
                if (!inBounds(next, agent_size) || isBlocked(next, agent_size, MovementType::Walk))
                    break;
                pa.origin = next;
                pa.agent->setPosition(next.col, next.row);
                cells_moved++;
            }
        }
    }

    return cells_moved;
}

bool BattleMap::setAgentPosition(int idx, Cell newOrigin) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return false;
    auto& pa = placedAgents_[idx];
    int agent_size = pa.agent->getSize();

    if (!inBounds(newOrigin, agent_size)) return false;

    pa.origin = newOrigin;
    pa.agent->setPosition(newOrigin.col, newOrigin.row);
    return true;
}

void BattleMap::removeAgent(int idx) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_.erase(placedAgents_.begin() + idx);
}

Agent::Stats BattleMap::getAgentStats(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return {};
    return placedAgents_[idx].stats;
}

void BattleMap::setAgentStats(int idx, Agent::Stats s) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[idx].stats = s;
}

Agent::Conditions BattleMap::getAgentConditions(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return {};
    return placedAgents_[idx].agent->getConditions();
}

void BattleMap::setAgentConditions(int idx, const Agent::Conditions& c) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[idx].agent->setConditions(c);
}

void BattleMap::applyDash(int idx) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    auto& pa = placedAgents_[idx];
    pa.agent->dash();
    pa.agent->addMovement(pa.stats.speed_walk, pa.stats.speed_fly,
                          pa.stats.speed_swim, pa.stats.speed_burrow);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Movement helpers
// ─────────────────────────────────────────────────────────────────────────────

bool BattleMap::inBounds(Cell origin, int size) const noexcept
{
    return origin.col >= 0
        && origin.row >= 0
        && origin.col + size <= cols_
        && origin.row + size <= rows_;
}

// Helper: Dijkstra pathfinding for path-based movement (Walk, Swim, Burrow, Jump)
CellSet BattleMap::pathfindMovement(Cell origin, int tokenSize,
                                     int speedFt, MovementType type) const
{
    CellSet result;
    using PQItem = std::pair<int, Cell>;
    auto cmp = [](const PQItem& a, const PQItem& b) { return a.first > b.first; };
    std::priority_queue<PQItem, std::vector<PQItem>, decltype(cmp)> pq(cmp);
    std::unordered_map<Cell, int, CellHash> dist;

    dist[origin] = 0;
    pq.push({0, origin});

    while (!pq.empty()) {
        auto [cost, cell] = pq.top();
        pq.pop();

        if (dist.count(cell) && dist[cell] < cost) continue;

        result.insert(cell);

        for (int dr = -1; dr <= 1; ++dr) {
            for (int dc = -1; dc <= 1; ++dc) {
                if (dr == 0 && dc == 0) continue;
                Cell next{cell.col + dc, cell.row + dr};

                if (!inBounds(next, tokenSize))  continue;
                if (isBlocked(next, tokenSize, type))  continue;

                // Orthogonal: 5 ft; Diagonal: 10 ft
                int step_cost = (dr != 0 && dc != 0) ? 10 : 5;
                double terrain_mult = getTerrainMultiplier(next, type);
                int new_cost = cost + static_cast<int>(step_cost / terrain_mult);
                if (new_cost > speedFt) continue;

                if (!dist.count(next) || dist[next] > new_cost) {
                    dist[next] = new_cost;
                    pq.push({new_cost, next});
                }
            }
        }
    }
    return result;
}

CellSet BattleMap::reachableCells(Cell origin, int tokenSize,
                                   int speedFt, MovementType type) const
{
    CellSet result;
    if (speedFt <= 0 || !inBounds(origin, tokenSize)) return result;

    // All movement types use Dijkstra pathfinding (respects terrain/walls)
    return pathfindMovement(origin, tokenSize, speedFt, type);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Weapon accessors
// ─────────────────────────────────────────────────────────────────────────────

std::array<Weapon, 3> BattleMap::getAgentWeapons(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return {};
    return placedAgents_[static_cast<std::size_t>(idx)].weapons;
}

void BattleMap::setAgentWeapons(int idx, std::array<Weapon, 3> weapons) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].weapons = std::move(weapons);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Armor accessors
// ─────────────────────────────────────────────────────────────────────────────

std::array<Armor, 6> BattleMap::getAgentArmor(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) {
        return std::array<Armor, 6>{};
    }
    return placedAgents_[static_cast<std::size_t>(idx)].armor;
}

void BattleMap::setAgentArmor(int idx, std::array<Armor, 6> armor) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].armor = std::move(armor);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Spell accessors
// ─────────────────────────────────────────────────────────────────────────────

std::vector<Spell> BattleMap::getAgentSpells(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return {};
    return placedAgents_[static_cast<std::size_t>(idx)].spells;
}

void BattleMap::setAgentSpells(int idx, std::vector<Spell> spells) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].spells = std::move(spells);
}

void BattleMap::addSpellToAgent(int idx, Spell s) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].spells.push_back(std::move(s));
}

void BattleMap::removeSpellFromAgent(int idx, int spell_idx) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    auto& sv = placedAgents_[static_cast<std::size_t>(idx)].spells;
    if (spell_idx < 0 || spell_idx >= static_cast<int>(sv.size())) return;
    sv.erase(sv.begin() + spell_idx);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Line-of-sight (Bresenham) and attack range
// ─────────────────────────────────────────────────────────────────────────────

// hasLineOfSight uses a floating-point DDA traversal (see implementation).
// attackTargetCells calls hasLineOfSight for each candidate cell.

bool BattleMap::hasLineOfSight(Cell from, int fromSize,
                                Cell to,   int toSize) const noexcept
{
    // D&D 5e rule: LoS exists if ANY cell of the attacker's footprint has
    // an unobstructed straight line to ANY cell of the target's footprint.
    // Checking cell-to-cell (1×1 → 1×1) instead of centroid-to-centroid
    // avoids the sub-grid bias that affects even-sized tokens (2×2, 4×4…).
    //
    // Inner Bresenham:
    //   Works in the 2× sub-grid so that 1×1 cell centres land at odd
    //   coordinates (2c+1, 2r+1).  When the walk lands on an even-even
    //   corner point (junction of 4 cells) it applies the D&D corner rule:
    //   block only if BOTH cells flanking the path are walls.
    //   The flanking pair is determined from the floating-point direction so
    //   the result is symmetric regardless of ray direction.

    // Returns true if grid cell (c,r) is a wall that is inside neither
    // footprint.  Both footprints are always excluded — not just the
    // specific from/to cells being tested — so a large token can never
    // block its own LoS.
    auto wallCell = [&](int c, int r) -> bool {
        if (c < 0 || r < 0 || c >= cols_ || r >= rows_) return false;
        const bool inF = (c >= from.col && c < from.col + fromSize &&
                          r >= from.row && r < from.row + fromSize);
        const bool inT = (c >= to.col   && c < to.col   + toSize   &&
                          r >= to.row   && r < to.row   + toSize);
        if (inF || inT) return false;
        // Check both auto-detected walls and manually-set Wall terrain
        if (disallowed_.contains({c, r})) return true;
        return terrainType_[r * cols_ + c] == TerrainType::Wall;
    };

    // Test a single 1×1 pair (fc,fr) → (tc,tr).
    auto los1x1 = [&](int fc, int fr, int tc, int tr) -> bool {
        const int x0 = 2 * fc + 1, y0 = 2 * fr + 1;   // always odd
        const int x1 = 2 * tc + 1, y1 = 2 * tr + 1;   // always odd
        const int dx  = std::abs(x1 - x0);
        const int dy  = std::abs(y1 - y0);
        const int sx  = (x0 < x1) ? 1 : -1;
        const int sy  = (y0 < y1) ? 1 : -1;
        // Float direction used only to identify which cell pair to check at
        // corners — computed once, no per-step accumulation of error.
        const double fdx = static_cast<double>(x1 - x0);
        const double fdy = static_cast<double>(y1 - y0);
        int err = dx - dy, cx = x0, cy = y0;
        for (;;) {
            if (cx >= 0 && cy >= 0 && cx < 2 * cols_ && cy < 2 * rows_) {
                if (cx % 2 == 0 && cy % 2 == 0) {
                    // Corner: line clips the junction of 4 cells.
                    // Block only when BOTH flanking cells are walls.
                    // Flank pair depends on direction:
                    //   ↗/↙ (fdx·fdy < 0): (cx/2, cy/2-1) and (cx/2-1, cy/2)
                    //   ↘/↖ (fdx·fdy > 0): (cx/2-1,cy/2-1) and (cx/2, cy/2)
                    int gc1, gr1, gc2, gr2;
                    if (fdx * fdy < 0.0) {
                        gc1 = cx/2;   gr1 = cy/2 - 1;
                        gc2 = cx/2-1; gr2 = cy/2;
                    } else {
                        gc1 = cx/2-1; gr1 = cy/2 - 1;
                        gc2 = cx/2;   gr2 = cy/2;
                    }
                    if (wallCell(gc1, gr1) && wallCell(gc2, gr2)) return false;
                } else {
                    // Interior sub-grid point: the line passes through exactly
                    // one cell.  Apply a directional bias (±½ in the travel
                    // direction) before the ÷2 so that an even sub-grid
                    // coordinate (which sits on a grid-line boundary) maps to
                    // the cell being *entered*, not the one being *left*.
                    // For odd coordinates the ±½ shift does not change the
                    // floor result, so the formula is safe to apply uniformly.
                    const int gc = static_cast<int>(
                        std::floor((cx + sx * 0.5) / 2.0));
                    const int gr = static_cast<int>(
                        std::floor((cy + sy * 0.5) / 2.0));
                    if (wallCell(gc, gr)) return false;
                }
            }
            if (cx == x1 && cy == y1) break;
            const int e2 = 2 * err;
            if (e2 > -dy) { err -= dy; cx += sx; }
            if (e2 <  dx) { err += dx; cy += sy; }
        }
        return true;
    };

    // Any cell in from-footprint that can see any cell in to-footprint.
    for (int fc = from.col; fc < from.col + fromSize; ++fc)
        for (int fr = from.row; fr < from.row + fromSize; ++fr)
            for (int tc = to.col; tc < to.col + toSize; ++tc)
                for (int tr = to.row; tr < to.row + toSize; ++tr)
                    if (los1x1(fc, fr, tc, tr))
                        return true;
    return false;
}

std::vector<Cell> BattleMap::attackTargetCells(Cell origin, int tokenSize,
                                                int rangeFt) const
{
    const int rangeCells = rangeFt / 5;
    std::vector<Cell> result;

    // Search rectangle: bounding box of token extended by rangeCells on every side.
    int minC = std::max(0,       origin.col - rangeCells);
    int maxC = std::min(cols_-1, origin.col + tokenSize - 1 + rangeCells);
    int minR = std::max(0,       origin.row - rangeCells);
    int maxR = std::min(rows_-1, origin.row + tokenSize - 1 + rangeCells);

    for (int r = minR; r <= maxR; ++r) {
        for (int c = minC; c <= maxC; ++c) {
            // Chebyshev distance from (c,r) to the nearest cell of the token footprint.
            // dc = how many columns outside the [origin.col, origin.col+size) range.
            int dc = std::max({origin.col - c,
                               c - (origin.col + tokenSize - 1),
                               0});
            int dr = std::max({origin.row - r,
                               r - (origin.row + tokenSize - 1),
                               0});
            int dist = std::max(dc, dr);

            if (dist == 0)           continue;   // inside the attacker's own footprint
            if (dist > rangeCells)   continue;   // outside weapon range

            if (hasLineOfSight(origin, tokenSize, {c, r}, 1))
                result.push_back({c, r});
        }
    }
    return result;
}

std::vector<Cell> BattleMap::filterSpellCells(const std::vector<Cell>& cells,
                                              Cell casterOrigin, int casterSize,
                                              const Spell& spell, Cell centerCell) const
{
    std::vector<Cell> result;
    const int rangeCells = spell.range / 5;

    // Check if centerCell has LOS (if required)
    if (spell.requires_los && spell.check_los_on_center) {
        if (!hasLineOfSight(casterOrigin, casterSize, centerCell, 1)) {
            return result;  // Center blocked, no cells can be affected
        }
    }

    for (const auto& cell : cells) {
        // Check distance (Chebyshev from caster edge to target cell)
        int dc = std::max({casterOrigin.col - cell.col,
                          cell.col - (casterOrigin.col + casterSize - 1),
                          0});
        int dr = std::max({casterOrigin.row - cell.row,
                          cell.row - (casterOrigin.row + casterSize - 1),
                          0});
        int dist = std::max(dc, dr);

        if (dist > rangeCells)
            continue;  // Out of range

        // If check_los_on_center, we already validated center above, so include all range cells
        if (spell.check_los_on_center && spell.requires_los) {
            result.push_back(cell);
        } else if (spell.requires_los) {
            // Check LOS for each individual cell (rare case)
            if (hasLineOfSight(casterOrigin, casterSize, cell, 1)) {
                result.push_back(cell);
            }
        } else {
            // No LOS requirement, just add it
            result.push_back(cell);
        }
    }
    return result;
}

// ── Terrain multipliers ────────────────────────────────────────────────────
double BattleMap::getTerrainMultiplier(Cell c, MovementType mt) const noexcept {
    (void)mt;  // mt parameter included for API consistency; cost multipliers are movement-type-independent
    if (c.col < 0 || c.col >= cols_ || c.row < 0 || c.row >= rows_)
        return 1.0;

    int idx = c.row * cols_ + c.col;
    double staticMult = terrainMult_[idx];

    // Convert temporary terrain difficulty to multiplier
    double dynamicMult = 1.0;
    switch (tempTerrainDiff_[idx]) {
        case TerrainDifficulty::Halved:    dynamicMult = 0.5;  break;
        case TerrainDifficulty::Quartered: dynamicMult = 0.25; break;
        case TerrainDifficulty::Slipping:  dynamicMult = 1.0;  break;  // Slipping doesn't affect movement speed, only triggers saves
        case TerrainDifficulty::Normal:    dynamicMult = 1.0;  break;
    }

    // Most restrictive wins: take the minimum multiplier
    return std::min(staticMult, dynamicMult);
}

void BattleMap::setTerrainMultiplier(Cell c, double mult) noexcept {
    if (c.col < 0 || c.col >= cols_ || c.row < 0 || c.row >= rows_)
        return;
    terrainMult_[c.row * cols_ + c.col] = mult;
}

void BattleMap::setTerrainMultiplierRect(Cell topLeft, int width, int height, double mult) noexcept {
    for (int r = topLeft.row; r < topLeft.row + height; ++r) {
        for (int c = topLeft.col; c < topLeft.col + width; ++c) {
            if (c >= 0 && c < cols_ && r >= 0 && r < rows_) {
                terrainMult_[r * cols_ + c] = mult;
            }
        }
    }
}

void BattleMap::resetTerrainMultipliers() noexcept {
    std::fill(terrainMult_.begin(), terrainMult_.end(), 1.0);
}

TerrainType BattleMap::getTerrainType(Cell c) const noexcept {
    if (c.col < 0 || c.col >= cols_ || c.row < 0 || c.row >= rows_)
        return TerrainType::Standard;
    return terrainType_[c.row * cols_ + c.col];
}

void BattleMap::setTerrainType(Cell c, TerrainType t) noexcept {
    if (c.col < 0 || c.col >= cols_ || c.row < 0 || c.row >= rows_)
        return;
    terrainType_[c.row * cols_ + c.col] = t;
}

// ── Light levels (visibility & darkvision) ────────────────────────────────────
VisibilityLevel BattleMap::getLightLevel(Cell c) const noexcept {
    if (c.col < 0 || c.col >= cols_ || c.row < 0 || c.row >= rows_)
        return VisibilityLevel::Clear;  // out-of-bounds is bright
    return lightLevel_[c.row * cols_ + c.col];
}

void BattleMap::setLightLevel(Cell c, VisibilityLevel lvl) noexcept {
    if (c.col < 0 || c.col >= cols_ || c.row < 0 || c.row >= rows_)
        return;
    lightLevel_[c.row * cols_ + c.col] = lvl;
}

void BattleMap::resetLightLevels() noexcept {
    std::fill(lightLevel_.begin(), lightLevel_.end(), VisibilityLevel::Clear);
}

bool BattleMap::canSee(Cell obs_origin, int obs_size,
                       int darkvision_ft, int truesight_ft, int devilssight_ft,
                       Cell tgt_origin, int tgt_size) const noexcept {
    // LOS check first
    if (!hasLineOfSight(obs_origin, obs_size, tgt_origin, tgt_size))
        return false;

    // Find minimum Chebyshev distance between observer and target footprints
    int min_dist = INT_MAX;
    for (int dr = 0; dr < obs_size; ++dr) {
        for (int dc = 0; dc < obs_size; ++dc) {
            for (int tr = 0; tr < tgt_size; ++tr) {
                for (int tc = 0; tc < tgt_size; ++tc) {
                    int obs_r = obs_origin.row + dr;
                    int obs_c = obs_origin.col + dc;
                    int tgt_r = tgt_origin.row + tr;
                    int tgt_c = tgt_origin.col + tc;
                    int dist = std::max(std::abs(obs_r - tgt_r), std::abs(obs_c - tgt_c));
                    min_dist = std::min(min_dist, dist);
                }
            }
        }
    }
    int dist_ft = min_dist * 5;  // 1 cell = 5 feet

    // Find darkest (most restrictive) light level at target's footprint
    VisibilityLevel effective_light = VisibilityLevel::Clear;
    for (int tr = 0; tr < tgt_size; ++tr) {
        for (int tc = 0; tc < tgt_size; ++tc) {
            Cell c{tgt_origin.col + tc, tgt_origin.row + tr};
            VisibilityLevel cell_light = getLightLevel(c);
            if (static_cast<int>(cell_light) > static_cast<int>(effective_light)) {
                effective_light = cell_light;
            }
        }
    }

    // Apply D&D 5e visibility rules
    // Truesight: sees through all conditions
    if (truesight_ft > 0 && dist_ft <= truesight_ft)
        return true;

    // Devil's Sight: sees in darkness and magical darkness (120ft max normally, but respecting range)
    if (devilssight_ft > 0 && dist_ft <= devilssight_ft &&
        effective_light != VisibilityLevel::Clear && effective_light != VisibilityLevel::Dim)
        return true;

    // Normal visibility by light condition
    switch (effective_light) {
        case VisibilityLevel::Clear:
            return true;  // always visible
        case VisibilityLevel::Dim:
            return true;  // lightly obscured but visible (disadvantage handled separately)
        case VisibilityLevel::LightlyObscured:
            return true;  // fog/shadows but visible (disadvantage handled separately)
        case VisibilityLevel::Dark:
            // visible only with darkvision within range
            return darkvision_ft > 0 && dist_ft <= darkvision_ft;
        case VisibilityLevel::MagicalDark:
            return false;  // magical darkness blocks darkvision
        case VisibilityLevel::Blocked:
            return false;  // cannot see through walls/obstacles
    }
    return false;
}

bool BattleMap::perceptionDisadvantage(Cell obs_origin, int obs_size,
                                       int darkvision_ft, int truesight_ft, int devilssight_ft,
                                       Cell tgt_origin, int tgt_size) const noexcept {
    // Truesight never has disadvantage
    if (truesight_ft > 0) {
        int min_dist = INT_MAX;
        for (int dr = 0; dr < obs_size; ++dr) {
            for (int dc = 0; dc < obs_size; ++dc) {
                for (int tr = 0; tr < tgt_size; ++tr) {
                    for (int tc = 0; tc < tgt_size; ++tc) {
                        int dist = std::max(std::abs((obs_origin.row + dr) - (tgt_origin.row + tr)),
                                          std::abs((obs_origin.col + dc) - (tgt_origin.col + tc)));
                        min_dist = std::min(min_dist, dist);
                    }
                }
            }
        }
        if (min_dist * 5 <= truesight_ft)
            return false;
    }

    // Find effective light at target
    VisibilityLevel effective_light = VisibilityLevel::Clear;
    for (int tr = 0; tr < tgt_size; ++tr) {
        for (int tc = 0; tc < tgt_size; ++tc) {
            Cell c{tgt_origin.col + tc, tgt_origin.row + tr};
            VisibilityLevel cell_light = getLightLevel(c);
            if (static_cast<int>(cell_light) > static_cast<int>(effective_light)) {
                effective_light = cell_light;
            }
        }
    }

    // DimLight: disadvantage with normal or devil's sight
    if (effective_light == VisibilityLevel::Dim) {
        return darkvision_ft == 0 && devilssight_ft == 0;  // no advantage from dark-only senses
    }

    // Darkness: disadvantage with darkvision
    if (effective_light == VisibilityLevel::Dark) {
        return darkvision_ft > 0 && truesight_ft == 0;  // darkvision has disadvantage
    }

    // All other cases: no disadvantage
    return false;
}

PlacedAgent& BattleMap::placedAgentMut(int idx) noexcept {
    static PlacedAgent dummy;
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size()))
        return dummy;
    return placedAgents_[static_cast<std::size_t>(idx)];
}

void BattleMap::initNpcSpellGroups(int agent_idx,
                                    const std::map<int, std::vector<std::string>>& groups) noexcept {
    if (agent_idx < 0 || agent_idx >= static_cast<int>(placedAgents_.size()))
        return;

    PlacedAgent& pa = placedAgents_[static_cast<std::size_t>(agent_idx)];
    pa.stats.is_npc = true;

    // Initialize uses_max and uses_remaining for each spell based on its group
    for (auto& spell : pa.spells) {
        for (const auto& [uses_per_day, spell_names] : groups) {
            // Check if this spell is in this group
            if (std::find(spell_names.begin(), spell_names.end(), spell.name) != spell_names.end()) {
                spell.uses_max = uses_per_day;
                spell.uses_remaining = uses_per_day;
                break;
            }
        }
    }
}

// ── Temporary terrain effects ──────────────────────────────────────────────────
void BattleMap::updateTerrain() {
    // Reset to Normal (no effect)
    std::fill(tempTerrainDiff_.begin(), tempTerrainDiff_.end(), TerrainDifficulty::Normal);

    // Apply all active effects, keeping the most restrictive per cell
    for (const auto& effect : activeTerrainEffects_) {
        for (int idx : effect.cell_indices) {
            if (idx >= 0 && static_cast<std::size_t>(idx) < tempTerrainDiff_.size()) {
                tempTerrainDiff_[idx] = std::max(tempTerrainDiff_[idx], effect.difficulty);
            }
        }
    }
}

int BattleMap::placeTerrainEffect(std::string name,
                                   std::vector<Cell> cells,
                                   TerrainDifficulty difficulty,
                                   int turns_remaining,
                                   int source_agent_idx,
                                   int slip_save_dc,
                                   int slip_distance_feet) {
    // Convert Cell list to flat indices
    std::vector<int> indices;
    for (const auto& cell : cells) {
        if (cell.col >= 0 && cell.col < cols_ && cell.row >= 0 && cell.row < rows_) {
            indices.push_back(cell.row * cols_ + cell.col);
        }
    }

    if (indices.empty())
        return -1;  // No valid cells

    // Create the effect with a unique id
    int id = nextEffectId_++;
    ActiveTerrainEffect effect{
        id,
        std::move(name),
        std::move(indices),
        difficulty,
        turns_remaining,
        source_agent_idx,
        slip_save_dc,
        slip_distance_feet
    };
    activeTerrainEffects_.push_back(effect);

    updateTerrain();
    return id;
}

std::vector<int> BattleMap::tickTerrainEffects(int source_agent_idx) {
    std::vector<int> expired;

    // Decrement turns_remaining for effects from this source
    std::erase_if(activeTerrainEffects_, [&](ActiveTerrainEffect& effect) {
        if (effect.source_agent_idx != source_agent_idx)
            return false;

        if (effect.turns_remaining < 0)  // -1 = permanent
            return false;

        --effect.turns_remaining;
        if (effect.turns_remaining <= 0) {
            expired.push_back(effect.id);
            return true;
        }
        return false;
    });

    if (!expired.empty())
        updateTerrain();

    return expired;
}

std::vector<int> BattleMap::tickDMTerrainEffects() {
    std::vector<int> expired;

    // Decrement turns_remaining for DM-placed effects (source_agent_idx == -1)
    std::erase_if(activeTerrainEffects_, [&](ActiveTerrainEffect& effect) {
        if (effect.source_agent_idx != -1)
            return false;

        if (effect.turns_remaining < 0)  // -1 = permanent
            return false;

        --effect.turns_remaining;
        if (effect.turns_remaining <= 0) {
            expired.push_back(effect.id);
            return true;
        }
        return false;
    });

    if (!expired.empty())
        updateTerrain();

    return expired;
}

std::vector<int> BattleMap::removeTerrainEffectsBySource(int source_agent_idx) {
    std::vector<int> removed;

    std::erase_if(activeTerrainEffects_, [&](const ActiveTerrainEffect& effect) {
        if (effect.source_agent_idx == source_agent_idx) {
            removed.push_back(effect.id);
            return true;
        }
        return false;
    });

    if (!removed.empty())
        updateTerrain();

    return removed;
}

void BattleMap::removeTerrainEffect(int effect_id) {
    std::erase_if(activeTerrainEffects_, [effect_id](const ActiveTerrainEffect& effect) {
        return effect.id == effect_id;
    });
    updateTerrain();
}

void BattleMap::clearTerrainEffects() noexcept {
    activeTerrainEffects_.clear();
    std::fill(tempTerrainDiff_.begin(), tempTerrainDiff_.end(), TerrainDifficulty::Normal);
}

std::vector<ActiveTerrainEffect> BattleMap::activeTerrainEffects() const {
    return activeTerrainEffects_;
}

bool BattleMap::hasActiveTerrainEffects() const noexcept {
    return !activeTerrainEffects_.empty();
}

// ── Lighting system ────────────────────────────────────────────────────────
void BattleMap::applyBaseLighting(VisibilityLevel default_light,
                                   const std::vector<std::tuple<int, int, int, int>>& sources) noexcept {
    // Initialize base lighting to default
    baseVisibilityLevel_.assign(static_cast<std::size_t>(rows_) * cols_, default_light);

    if (vLines_.empty() || hLines_.empty())
        return;  // Grid not yet analyzed

    // Apply each light source
    for (const auto& [px, py, bright_radius_ft, dim_radius_ft] : sources) {
        // Find grid cell containing pixel (px, py)
        // Grid lines define cell boundaries: cells are between consecutive grid lines
        int grid_c = -1, grid_r = -1;

        // Find column (between vertical grid lines)
        for (int c = 0; c < static_cast<int>(vLines_.size()) - 1; ++c) {
            if (px >= vLines_[c] && px < vLines_[c + 1]) {
                grid_c = c;
                break;
            }
        }

        // Find row (between horizontal grid lines)
        for (int r = 0; r < static_cast<int>(hLines_.size()) - 1; ++r) {
            if (py >= hLines_[r] && py < hLines_[r + 1]) {
                grid_r = r;
                break;
            }
        }

        if (grid_c < 0 || grid_r < 0)
            continue;  // Source outside grid

        // Convert feet to cell units (5 ft per cell)
        int bright_cells = bright_radius_ft / 5;
        int dim_cells = dim_radius_ft / 5;

        // Apply bright light (Chebyshev distance)
        for (int r = 0; r < rows_; ++r) {
            for (int c = 0; c < cols_; ++c) {
                int dist = std::max(std::abs(r - grid_r), std::abs(c - grid_c));
                if (dist <= bright_cells) {
                    int idx = r * cols_ + c;
                    baseVisibilityLevel_[static_cast<std::size_t>(idx)] =
                        std::min(baseVisibilityLevel_[static_cast<std::size_t>(idx)], VisibilityLevel::Clear);
                } else if (dist <= dim_cells) {
                    int idx = r * cols_ + c;
                    baseVisibilityLevel_[static_cast<std::size_t>(idx)] =
                        std::min(baseVisibilityLevel_[static_cast<std::size_t>(idx)], VisibilityLevel::Dim);
                }
            }
        }
    }

    updateLighting();
}

void BattleMap::updateLighting() noexcept {
    // Step 1: reset computed lighting to base
    lightLevel_ = baseVisibilityLevel_;

    // Step 2: apply normal light effects (brightest wins = std::min)
    for (const auto& eff : activeLightEffects_) {
        if (eff.light_level == VisibilityLevel::MagicalDark)
            continue;  // Handle magical darkness in step 3
        for (int idx : eff.cell_indices) {
            if (idx >= 0 && static_cast<std::size_t>(idx) < lightLevel_.size()) {
                lightLevel_[static_cast<std::size_t>(idx)] =
                    std::min(lightLevel_[static_cast<std::size_t>(idx)], eff.light_level);
            }
        }
    }

    // Step 3: apply magical darkness (always wins = override)
    for (const auto& eff : activeLightEffects_) {
        if (eff.light_level != VisibilityLevel::MagicalDark)
            continue;
        for (int idx : eff.cell_indices) {
            if (idx >= 0 && static_cast<std::size_t>(idx) < lightLevel_.size()) {
                lightLevel_[static_cast<std::size_t>(idx)] = VisibilityLevel::MagicalDark;
            }
        }
    }
}

int BattleMap::placeLightEffect(std::string name, std::vector<Cell> cells,
                                 VisibilityLevel level, int turns_remaining,
                                 int source_agent_idx) noexcept {
    // Convert Cell list to flat indices
    std::vector<int> indices;
    for (const auto& cell : cells) {
        if (cell.col >= 0 && cell.col < cols_ && cell.row >= 0 && cell.row < rows_) {
            indices.push_back(cell.row * cols_ + cell.col);
        }
    }

    if (indices.empty())
        return -1;  // No valid cells

    // Create the effect with a unique id
    int id = nextLightEffectId_++;
    activeLightEffects_.push_back({
        id,
        std::move(name),
        std::move(indices),
        level,
        turns_remaining,
        source_agent_idx
    });

    updateLighting();
    return id;
}

std::vector<int> BattleMap::tickLightEffects(int source_agent_idx) noexcept {
    std::vector<int> expired;

    // Decrement turns_remaining for effects from this source
    std::erase_if(activeLightEffects_, [&](ActiveLightEffect& effect) {
        if (effect.source_agent_idx != source_agent_idx)
            return false;

        if (effect.turns_remaining < 0)  // -1 = permanent
            return false;

        --effect.turns_remaining;
        if (effect.turns_remaining == 0) {
            expired.push_back(effect.id);
            return true;  // erase this effect
        }
        return false;
    });

    if (!expired.empty())
        updateLighting();
    return expired;
}

std::vector<int> BattleMap::tickDmLightEffects() noexcept {
    return tickLightEffects(-1);  // -1 = DM-placed effects
}

std::vector<int> BattleMap::removeLightEffectsBySource(int source_agent_idx) noexcept {
    std::vector<int> removed;
    std::erase_if(activeLightEffects_, [&](const ActiveLightEffect& effect) {
        if (effect.source_agent_idx == source_agent_idx) {
            removed.push_back(effect.id);
            return true;
        }
        return false;
    });
    if (!removed.empty())
        updateLighting();
    return removed;
}

void BattleMap::removeLightEffect(int id) noexcept {
    std::erase_if(activeLightEffects_, [id](const ActiveLightEffect& effect) {
        return effect.id == id;
    });
    updateLighting();
}

void BattleMap::clearLightEffects() noexcept {
    activeLightEffects_.clear();
    updateLighting();
}

bool BattleMap::hasActiveLightEffects() const noexcept {
    return !activeLightEffects_.empty();
}

const std::vector<ActiveLightEffect>& BattleMap::activeLightEffects() const noexcept {
    return activeLightEffects_;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Persistent AoE Spell Effects
// ─────────────────────────────────────────────────────────────────────────────

int BattleMap::addSpellEffect(ActiveSpellEffect effect) noexcept {
    effect.effect_id = nextSpellEffectId_++;
    activeSpellEffects_.push_back(effect);
    return effect.effect_id;
}

void BattleMap::removeSpellEffect(int effect_id) noexcept {
    auto it = std::find_if(activeSpellEffects_.begin(), activeSpellEffects_.end(),
        [effect_id](const ActiveSpellEffect& e) { return e.effect_id == effect_id; });
    if (it != activeSpellEffects_.end()) {
        activeSpellEffects_.erase(it);
    }
}

const std::vector<ActiveSpellEffect>& BattleMap::activeSpellEffects() const noexcept {
    return activeSpellEffects_;
}

std::vector<int> BattleMap::tickSpellEffects(int source_agent_idx) noexcept {
    std::vector<int> removed_ids;
    std::vector<ActiveSpellEffect> remaining;
    for (auto& effect : activeSpellEffects_) {
        if (effect.caster_idx != source_agent_idx)
            remaining.push_back(effect);
        else if (--effect.turns_remaining <= 0)
            removed_ids.push_back(effect.effect_id);
        else
            remaining.push_back(effect);
    }
    activeSpellEffects_ = remaining;
    return removed_ids;
}

void BattleMap::clearSpellEffects() noexcept {
    activeSpellEffects_.clear();
    nextSpellEffectId_ = 0;
}

int BattleMap::addObscurationEffect(ActiveObscurationEffect effect) noexcept {
    effect.id = nextObscurationEffectId_++;
    activeObscurationEffects_.push_back(effect);
    return effect.id;
}

void BattleMap::removeObscurationEffect(int effect_id) noexcept {
    auto it = std::find_if(activeObscurationEffects_.begin(), activeObscurationEffects_.end(),
        [effect_id](const ActiveObscurationEffect& e) { return e.id == effect_id; });
    if (it != activeObscurationEffects_.end()) {
        activeObscurationEffects_.erase(it);
    }
}

const std::vector<ActiveObscurationEffect>& BattleMap::activeObscurationEffects() const noexcept {
    return activeObscurationEffects_;
}

VisibilityLevel BattleMap::getObscurationAtCell(const Cell& c) const noexcept {
    // Check all obscuration effects to find the highest obscuration level at this cell
    VisibilityLevel highest = VisibilityLevel::Clear;

    for (const auto& effect : activeObscurationEffects_) {
        // Check if this cell is in the effect
        if (std::find(effect.cells.begin(), effect.cells.end(), c) != effect.cells.end()) {
            // MagicalDarkness is highest priority (most obscuring)
            if (effect.obscuration_level == VisibilityLevel::MagicalDark) {
                return VisibilityLevel::MagicalDark;
            }
            // PartiallyObscured is next
            if (effect.obscuration_level == VisibilityLevel::LightlyObscured &&
                highest != VisibilityLevel::MagicalDark) {
                highest = VisibilityLevel::LightlyObscured;
            }
        }
    }

    return highest;
}

std::vector<int> BattleMap::tickObscurationEffects() noexcept {
    std::vector<int> removed_ids;
    std::vector<ActiveObscurationEffect> remaining;

    for (auto& effect : activeObscurationEffects_) {
        if (effect.turns_remaining == -1) {
            // Permanent effect (e.g., concentration-based)
            remaining.push_back(effect);
        } else if (--effect.turns_remaining <= 0) {
            removed_ids.push_back(effect.id);
        } else {
            remaining.push_back(effect);
        }
    }

    activeObscurationEffects_ = remaining;
    return removed_ids;
}

void BattleMap::clearObscurationEffects() noexcept {
    activeObscurationEffects_.clear();
    nextObscurationEffectId_ = 0;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Map items (weapons on the ground)
// ─────────────────────────────────────────────────────────────────────────────

int BattleMap::placeItem(Cell cell, Weapon weapon, std::string sprite_path) {
    int id = nextItemId_++;
    mapItems_.push_back(MapItem{id, cell, std::move(weapon), std::move(sprite_path)});
    return id;
}

void BattleMap::removeItem(int item_id) noexcept {
    mapItems_.erase(
        std::remove_if(mapItems_.begin(), mapItems_.end(),
                       [item_id](const MapItem& m){ return m.id == item_id; }),
        mapItems_.end());
}

std::vector<MapItem> BattleMap::getItemsAtCell(Cell cell) const noexcept {
    std::vector<MapItem> result;
    for (const auto& m : mapItems_)
        if (m.cell.col == cell.col && m.cell.row == cell.row)
            result.push_back(m);
    return result;
}

std::vector<MapItem> BattleMap::getAllItems() const noexcept {
    return mapItems_;
}

void BattleMap::clearItems() noexcept {
    mapItems_.clear();
    nextItemId_ = 0;
}

} // namespace rpg
