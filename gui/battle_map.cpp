// ─────────────────────────────────────────────────────────────────────────────
//  battle_map.cpp  –  OpenCV grid/wall analysis core (no rendering)
// ─────────────────────────────────────────────────────────────────────────────

#include "battle_map.hpp"
#include "configured_agent.hpp"
#include <opencv2/opencv.hpp>

#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <format>
#include <iostream>
#include <queue>
#include <ranges>
#include <stdexcept>
#include <string_view>
#include <unordered_map>
#include <utility>

namespace rpg {

// ── Diagnostic verbosity gate (see battle_map.hpp) ─────────────────────────
// -1 = follow the environment (default); 0/1 = explicit override set from Python.
namespace {
int g_verboseOverride = -1;
}

void setBattleMapVerbose(bool on) noexcept { g_verboseOverride = on ? 1 : 0; }

bool battleMapVerbose() noexcept
{
    if (g_verboseOverride >= 0) return g_verboseOverride != 0;
    const char* q = std::getenv("RPG_QUIET");
    return !(q && *q && std::string_view{q} != "0");   // RPG_QUIET set (non-empty, not "0") ⇒ quiet
}

// std::cout-style diagnostic that is silenced unless battleMapVerbose(). Replaces the raw
// `std::cout << std::format(...)` calls throughout this file so all "[BattleMap] …" noise is gated.
template <class... A>
static void bmlog(std::format_string<A...> fmt, A&&... args)
{
    if (battleMapVerbose())
        std::cout << std::format(fmt, std::forward<A>(args)...);
}

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
    bmlog("[BattleMap] {} h-lines, {} v-lines detected\n",
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

    // Reset fog-of-war explored mask (all fogged) for the new grid dimensions.
    explored_.assign(static_cast<std::size_t>(rows_ * cols_), 0);

    bmlog("[BattleMap] Grid {}×{}, ~{}px/cell\n", cols_, rows_, cellPx_);
}

void BattleMap::setUniformGrid(int cellPx, int anchorX, int anchorY)
{
    if (cellPx <= 0)
        throw std::runtime_error{"BattleMap::setUniformGrid – cellPx must be > 0"};

    cv::Mat img = cv::imread(mapImagePath_.string());
    if (img.empty())
        throw std::runtime_error{"BattleMap::setUniformGrid – cv::imread failed"};
    const int W = img.cols, H = img.rows;

    // Phase-align the grid so the sampled tile's corner sits on a cell boundary; the
    // grid then tiles outward from that phase across the whole image.
    auto phase = [cellPx](int anchor) {
        int p = anchor % cellPx;
        return p < 0 ? p + cellPx : p;
    };
    const int px = phase(anchorX);
    const int py = phase(anchorY);

    cols_ = (W - px) / cellPx;   // number of whole cells that fit
    rows_ = (H - py) / cellPx;
    if (cols_ <= 0 || rows_ <= 0)
        throw std::runtime_error{"BattleMap::setUniformGrid – grid would be empty"};

    hLines_.clear();
    vLines_.clear();
    for (int c = 0; c <= cols_; ++c) vLines_.push_back(px + c * cellPx);
    for (int r = 0; r <= rows_; ++r) hLines_.push_back(py + r * cellPx);
    cellPx_ = cellPx;

    const std::size_t n = static_cast<std::size_t>(rows_ * cols_);
    terrainMult_.assign(n, 1.0);
    terrainType_.assign(n, TerrainType::Standard);
    tempTerrainDiff_.assign(n, TerrainDifficulty::Normal);
    baseVisibilityLevel_.assign(n, VisibilityLevel::Clear);
    lightLevel_.assign(n, VisibilityLevel::Clear);
    explored_.assign(n, 0);  // fog-of-war: all fogged on a fresh grid

    clearWalls();

    bmlog("[BattleMap] Manual grid {}×{}, {}px/cell (phase {},{})\n",
                 cols_, rows_, cellPx_, px, py);
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
    bmlog("[BattleMap] {} dark (wall) cells detected (threshold={})\n",
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

    bmlog("[BattleMap] {} edge walls detected\n", walls.size());
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
    bmlog("[BattleMap] {} disallowed cells\n", disallowed_.size());
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
            bmlog("[BattleMap] '{}' skipped – blocked\n", cfg.name);
            continue;
        }
        auto tok = std::make_shared<ConfiguredAgent>(
            cfg.name, cfg.startCol, cfg.startRow, cfg.size, cfg.spritePath);
        // Default-construct, then set the two fields we know: every other member keeps its
        // default member initializer (weapons padded to 3, empty spells/items/armor,
        // summoner_idx -1). Do NOT go back to positional aggregate init — it silently shifted
        // every field's value onto its neighbour whenever PlacedAgent grew a member.
        PlacedAgent pa;
        pa.agent  = std::move(tok);
        pa.origin = origin;
        placedAgents_.push_back(std::move(pa));
    }
    bmlog("[BattleMap] {} agents placed\n", placedAgents_.size());
}

int BattleMap::spawnAgent(const AgentConfig& cfg)
{
    Cell origin{cfg.startCol, cfg.startRow};
    if (isBlocked(origin, cfg.size)) {
        bmlog("[BattleMap] spawn '{}' failed – blocked\n", cfg.name);
        return -1;
    }
    // Reject a cell already occupied by a live agent's footprint (a tombstoned/dismissed
    // summon no longer occupies its cell, and neither does a corpse (conditions.dead) —
    // mirroring agentOccupancy; an unconscious/downed body still blocks). isBlocked only
    // covers walls/terrain, not agents.
    for (const auto& pa : placedAgents_) {
        if (pa.removed_from_play || pa.agent->getConditions().dead) continue;
        int psize = pa.agent->getSize();
        if (origin.col < pa.origin.col + psize && origin.col + cfg.size > pa.origin.col &&
            origin.row < pa.origin.row + psize && origin.row + cfg.size > pa.origin.row) {
            bmlog("[BattleMap] spawn '{}' failed – cell occupied\n", cfg.name);
            return -1;
        }
    }
    auto tok = std::make_shared<ConfiguredAgent>(
        cfg.name, cfg.startCol, cfg.startRow, cfg.size, cfg.spritePath);
    PlacedAgent pa;
    pa.agent  = std::move(tok);
    pa.origin = origin;
    placedAgents_.push_back(std::move(pa));
    return static_cast<int>(placedAgents_.size()) - 1;
}

void BattleMap::clearAgents() { placedAgents_.clear(); agentConfigs_.clear(); }

std::span<const PlacedAgent> BattleMap::placedAgents() const noexcept
{
    return placedAgents_;
}

bool BattleMap::moveAgent(int idx, Cell newOrigin, MovementType type) noexcept
{
    lastMovePath_.clear();   // only a successful move leaves a route behind (see lastMovePath())
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return false;
    auto& pa = placedAgents_[idx];

    // For fly movement, check if destination is in reachable set (respects walls)
    if (type == MovementType::Fly) {
        int remaining = pa.agent->getFlyRemaining();
        if (remaining <= 0)
            return false;

        // Use reachableCells to validate destination (respects wall terrain + other agents)
        CellSet reachable = reachableCells(pa.origin, pa.agent->getSize(), remaining, MovementType::Fly, idx);
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
        lastMovePath_ = {pa.origin, newOrigin};   // straight segment — visually correct for flight
        pa.agent->flyTo(newOrigin.col, newOrigin.row);
        pa.origin = newOrigin;
        return true;
    }

    // Never end a move sharing a square with an ENEMY (always illegal). Ally squares are not
    // rejected here so a forced stop (e.g. a Sentinel OA halt) mid-path through an ally still
    // commits; NPC destination selection already avoids stopping on allies via reachableCells,
    // which excludes every occupied cell from its result set.
    if (agentOccupancy(newOrigin, pa.agent->getSize(), idx) == 2)
        return false;

    // For walk/swim/burrow, calculate actual path cost using Dijkstra
    // Find the cheapest path cost from origin to newOrigin
    using PQItem = std::pair<int, Cell>;
    auto cmp = [](const PQItem& a, const PQItem& b) { return a.first > b.first; };
    std::priority_queue<PQItem, std::vector<PQItem>, decltype(cmp)> pq(cmp);
    std::unordered_map<Cell, int, CellHash> dist;
    std::unordered_map<Cell, Cell, CellHash> prev;   // predecessor map → lastMovePath_ reconstruction

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
                // Enemy footprints block the path; allies may be passed through (but not stopped on,
                // which is enforced by the destination check below).
                if (agentOccupancy(next, pa.agent->getSize(), idx) == 2) continue;
                // Magic Circle / Hallow: a creature-type ward bars this creature from crossing the
                // zone boundary (entering, or leaving in reverse mode). Blocks the directed edge.
                if (movementWardBlocks(idx, cell, next)) continue;

                int step_cost = (dr != 0 && dc != 0) ? 10 : 5;

                // Apply crawling penalty if prone (2x cost in normal terrain, 3x in difficult)
                if (pa.agent->getConditions().prone) {
                    double terrain_mult = getTerrainMultiplierFor(next, type, idx);
                    if (terrain_mult < 1.0) {  // difficult terrain (multiplier < 1)
                        step_cost = static_cast<int>(step_cost * 3);
                    } else {
                        step_cost = step_cost * 2;
                    }
                }

                double terrain_mult = getTerrainMultiplierFor(next, type, idx);
                int new_cost = cost + static_cast<int>(step_cost / terrain_mult);

                if (!dist.count(next) || dist[next] > new_cost) {
                    dist[next] = new_cost;
                    prev[next] = cell;
                    pq.push({new_cost, next});
                }
            }
        }
    }

    if (actual_cost < 0 || actual_cost > 200)  // 200 is practical max
        return false;

    // Grappling a creature doubles the cost of every foot of movement (you drag it along). Charge
    // the double cost against this same (agent) movement budget — the one Dash, exhaustion, and every
    // other speed modifier already flow through — so the surcharge scales with them. (The CombatEngine's
    // separate per-turn walkRemaining_ map is NOT used for this; charging it instead left the surcharge
    // blind to a Dash, which capped a grappler at base speed even after Dashing.)
    bool dragging_grappled = false;
    for (std::size_t i = 0; i < placedAgents_.size(); ++i) {
        if (static_cast<int>(i) == idx) continue;
        const auto& c = placedAgents_[i].agent->getConditions();
        if (c.grappled && c.grappler_idx == idx) { dragging_grappled = true; break; }
    }
    const int charge = dragging_grappled ? actual_cost * 2 : actual_cost;

    // Check movement budget based on type
    int remaining = 0;
    switch (type) {
        case MovementType::Walk:   remaining = pa.agent->getWalkRemaining(); break;
        case MovementType::Swim:   remaining = pa.agent->getSwimRemaining(); break;
        case MovementType::Burrow: remaining = pa.agent->getBurrowRemaining(); break;
        default: return false;
    }

    if (charge > remaining)
        return false;

    // Deduct the (possibly doubled) cost
    pa.agent->addMovement(
        (type == MovementType::Walk ? -charge : 0),
        0,
        (type == MovementType::Swim ? -charge : 0),
        (type == MovementType::Burrow ? -charge : 0)
    );

    // Reconstruct the actual cell route (origin → … → dest, inclusive) for lastMovePath().
    // The GUI's NPC-turn playback animates the token along this route.
    lastMovePath_.push_back(newOrigin);
    for (Cell c = newOrigin; c != pa.origin; ) {
        auto it = prev.find(c);
        if (it == prev.end()) { lastMovePath_.clear(); break; }   // defensive: unreachable if cost resolved
        c = it->second;
        lastMovePath_.push_back(c);
    }
    std::reverse(lastMovePath_.begin(), lastMovePath_.end());

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
    const auto& jstats = pa.agent->getStats();
    int strength = jstats.str;
    int max_jump_ft = is_running ? strength : (strength / 2);

    // Otherworldly Leap invocation (code 10): the Warlock keeps the Jump spell up on
    // itself for free, tripling its jump distance.
    if (jstats.hasClass(CharacterClass::Warlock) && jstats.hasInvocation(10))
        max_jump_ft *= 3;

    // The reach is the Strength SCORE in feet (running) or half (standing). Convert that to whole
    // 5-ft squares rounding UP, so a creature reaches the square its Strength falls within
    // (e.g. Str 8 → 8 ft → 2 squares / 10 ft). Movement is still charged the full grid distance
    // (jump_dist_ft) below.
    int max_jump_cells = (max_jump_ft + 4) / 5;
    if (jump_dist_cells > max_jump_cells)
        return false;

    // Check if agent has enough walk movement budget (jumping uses walk budget)
    if (pa.agent->getWalkRemaining() < jump_dist_ft)
        return false;

    int agent_size = pa.agent->getSize();
    if (!inBounds(newOrigin, agent_size))
        return false;

    // Jumping clears Chasms and Water but NOT walls. MovementType::Jump encodes exactly
    // that in isBlocked (walls/disallowed → blocked; Chasm/Water → passable). Trace the
    // straight line to the landing cell and fail if any step (incl. the landing footprint)
    // is blocked by a wall. (Replaces the old flyTo, which ignored walls entirely.)
    int oc = pa.origin.col, orow = pa.origin.row;
    int steps = std::max(std::abs(newOrigin.col - oc), std::abs(newOrigin.row - orow));
    if (steps == 0)
        return false;
    for (int i = 1; i <= steps; ++i) {
        Cell step{ oc   + (newOrigin.col - oc)   * i / steps,
                   orow + (newOrigin.row - orow) * i / steps };
        if (isBlocked(step, agent_size, MovementType::Jump))
            return false;  // a wall blocks the leap
    }

    // Commit: jumping spends walk budget; move directly to the landing cell.
    pa.agent->addMovement(-jump_dist_ft, 0, 0, 0);
    pa.origin = newOrigin;
    pa.agent->setPosition(newOrigin.col, newOrigin.row);
    return true;
}

int BattleMap::forceMoveAgent(int idx, Cell push_from, int push_ft, bool pull, int from_size) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return 0;
    auto& pa = placedAgents_[idx];
    int agent_size = pa.agent->getSize();

    // Compute direction relative to the puller's whole FOOTPRINT (cols [pc0,pc1], rows [pr0,pr1]),
    // not just its top-left origin cell. A push moves AWAY; a pull reels TOWARD. Using the footprint
    // span means an axis on which the victim is already ALIGNED with the puller contributes 0 — so a
    // reel onto a Large puller pulls the victim STRAIGHT in along the aligned axis (the "pull in one
    // line" case) instead of homing on the origin corner. For a size-1 puller this reduces exactly to
    // the original origin-cell logic.
    const int pc0 = push_from.col, pc1 = push_from.col + from_size - 1;
    const int pr0 = push_from.row, pr1 = push_from.row + from_size - 1;
    const int tc0 = pa.origin.col, tc1 = pa.origin.col + agent_size - 1;
    const int tr0 = pa.origin.row, tr1 = pa.origin.row + agent_size - 1;

    int dir_col = 0, dir_row = 0;
    if (tc0 > pc1)      dir_col = 1;   // victim's footprint lies entirely east of the puller
    else if (tc1 < pc0) dir_col = -1;  // entirely west
    if (tr0 > pr1)      dir_row = 1;   // entirely south
    else if (tr1 < pr0) dir_row = -1;  // entirely north
    // dir_* now points AWAY from the puller (the push direction); a pull reels the opposite way.
    if (pull) { dir_col = -dir_col; dir_row = -dir_row; }

    // A pull reels the agent TOWARD push_from but must stop ONCE ADJACENT to it — never onto,
    // past, or sliding around the puller's footprint. (Agents aren't obstacles in isBlocked, so
    // without this a fixed-direction pull would keep going.) footprintDistance is the engine's
    // single-source adjacency gap: 1 = adjacent, 0 = overlap.
    //   The naive "don't step onto the body" guard (stop only at distance 0) is NOT enough for a
    //   Large puller: a DIAGONAL reel cuts the corner of a 2×2 footprint, holding distance 1 the
    //   whole way while crossing from one side to the other — i.e. it "flies past" the puller.
    //   So we stop as soon as the agent is already adjacent (distance <= 1): a reel ends on contact.
    auto adjacentToPuller = [&](Cell c) {
        return pull && footprintDistance(c, agent_size, push_from, from_size) <= 1;
    };

    // Move cell-by-cell for push_ft/5 cells
    int max_cells = push_ft / 5;
    int cells_moved = 0;

    for (int i = 0; i < max_cells; ++i) {
        // A reel ends the instant the agent is adjacent to the puller — don't take another step
        // that would overlap it or slide around its footprint.
        if (adjacentToPuller(pa.origin))
            break;

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
            if (adjacentToPuller(pa.origin)) break;   // a reel ends adjacent to the puller
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
                if (adjacentToPuller(pa.origin)) break;   // a reel ends adjacent to the puller
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
    return placedAgents_[idx].agent->getStats();
}

void BattleMap::setAgentStats(int idx, Agent::Stats s) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[idx].agent->setStats(s);
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
    pa.agent->addMovement(pa.agent->getStats().speed_walk, pa.agent->getStats().speed_fly,
                          pa.agent->getStats().speed_swim, pa.agent->getStats().speed_burrow);
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

// Faction-aware footprint occupancy test (see header). Other living, in-play agents
// block movement; an enemy footprint is impassable, an ally footprint is pass-through
// only. The mover's own footprint never blocks. mover_idx < 0 disables the check.
int BattleMap::agentOccupancy(Cell origin, int size, int mover_idx) const noexcept
{
    if (mover_idx < 0) return 0;
    const int mover_faction = getAgentFaction(mover_idx);
    int worst = 0;   // 0 free, 1 ally, 2 enemy (enemy dominates)
    for (std::size_t i = 0; i < placedAgents_.size(); ++i) {
        if (static_cast<int>(i) == mover_idx) continue;
        const auto& pa = placedAgents_[i];
        if (pa.removed_from_play || pa.on_deck)   continue;   // tombstoned / reserve: not on the map
        if (pa.agent->getConditions().dead)       continue;   // a corpse frees its square; a downed (unconscious) body still blocks
        const int psize = pa.agent->getSize();
        // Rectangle-overlap of the two footprints.
        if (origin.col < pa.origin.col + psize && origin.col + size > pa.origin.col &&
            origin.row < pa.origin.row + psize && origin.row + size > pa.origin.row) {
            // Same non-zero faction == ally (mirrors CombatEngine::areAllies). Neutral
            // (faction 0) and opposing factions are treated as enemies (impassable).
            const bool ally = mover_faction != 0 && getAgentFaction(static_cast<int>(i)) == mover_faction;
            worst = std::max(worst, ally ? 1 : 2);
            if (worst == 2) return 2;   // can't get worse
        }
    }
    return worst;
}

bool BattleMap::movementWardBlocks(int mover_idx, Cell from, Cell to) const noexcept
{
    if (mover_idx < 0 || mover_idx >= static_cast<int>(placedAgents_.size()))
        return false;
    const auto& mpa = placedAgents_[static_cast<std::size_t>(mover_idx)];
    const uint32_t mover_types = mpa.agent->getStats().creatureTypeMask();
    // Antilife Shell wards by "is this creature alive?", so it must consider typeless movers
    // (Humanoids, Beasts, …) too. Only Undead are exempt (Construct is not a modeled type).
    const bool mover_is_undead = mpa.agent->getStats().is_undead;

    const int size = mpa.agent->getSize();
    // Any-cell-overlap of the token's NxN footprint at `o` with a ward's flat cell set.
    auto footprintInWard = [&](Cell o, const std::vector<int>& cells) -> bool {
        for (int dc = 0; dc < size; ++dc)
            for (int dr = 0; dr < size; ++dr) {
                Cell c{o.col + dc, o.row + dr};
                if (c.col < 0 || c.col >= cols_ || c.row < 0 || c.row >= rows_) continue;
                const int flat = c.row * cols_ + c.col;
                if (std::find(cells.begin(), cells.end(), flat) != cells.end())
                    return true;
            }
        return false;
    };

    for (const auto& te : activeTerrainEffects_) {
        // A ward is either a living-barrier (Antilife Shell) or a creature-type ward (Magic
        // Circle / Hallow). Decide whether this mover is blocked by THIS ward, then apply the
        // shared boundary rule (keep-out vs trap-inside).
        bool warded;
        if (te.ward_all_living) {
            warded = !mover_is_undead;            // living creatures can't cross; Undead pass
        } else if (te.ward_creature_mask != 0) {
            if (mover_types == 0) continue;        // typeless creatures cross a type ward freely
            warded = (te.ward_creature_mask & mover_types) != 0;
        } else {
            continue;                              // not a movement ward
        }
        if (!warded) continue;
        const bool from_in = footprintInWard(from, te.cell_indices);
        const bool to_in   = footprintInWard(to,   te.cell_indices);
        if (te.ward_traps) {
            if (from_in && !to_in) return true;   // reverse Magic Circle: can't leave the zone
        } else {
            if (!from_in && to_in) return true;   // Magic Circle / Antilife: can't enter the zone
        }
    }
    return false;
}

// Helper: Dijkstra pathfinding for path-based movement (Walk, Swim, Burrow, Jump)
CellSet BattleMap::pathfindMovement(Cell origin, int tokenSize,
                                     int speedFt, MovementType type,
                                     int mover_idx) const
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

        // A cell occupied by another agent is reachable to PASS THROUGH (allies only —
        // enemy cells are never enqueued below) but is not a valid place to STOP, so it
        // is expanded for neighbours yet kept out of the returned destination set.
        if (agentOccupancy(cell, tokenSize, mover_idx) == 0)
            result.insert(cell);

        for (int dr = -1; dr <= 1; ++dr) {
            for (int dc = -1; dc <= 1; ++dc) {
                if (dr == 0 && dc == 0) continue;
                Cell next{cell.col + dc, cell.row + dr};

                if (!inBounds(next, tokenSize))  continue;
                if (isBlocked(next, tokenSize, type))  continue;
                // Enemy footprints block the path entirely; allies may be passed through.
                if (agentOccupancy(next, tokenSize, mover_idx) == 2)  continue;
                // Magic Circle / Hallow ward boundary (same rule as moveAgent) so the reachable
                // set — walk highlight and fly-destination validation — never offers a warded step.
                if (movementWardBlocks(mover_idx, cell, next))  continue;

                // Orthogonal: 5 ft; Diagonal: 10 ft
                int step_cost = (dr != 0 && dc != 0) ? 10 : 5;
                double terrain_mult = getTerrainMultiplierFor(next, type, mover_idx);
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
                                   int speedFt, MovementType type, int mover_idx) const
{
    CellSet result;
    if (speedFt <= 0 || !inBounds(origin, tokenSize)) return result;

    // All movement types use Dijkstra pathfinding (respects terrain/walls)
    return pathfindMovement(origin, tokenSize, speedFt, type, mover_idx);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Weapon accessors
// ─────────────────────────────────────────────────────────────────────────────

std::vector<Weapon> BattleMap::getAgentWeapons(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return std::vector<Weapon>(3);
    return placedAgents_[static_cast<std::size_t>(idx)].weapons;
}

void BattleMap::setAgentWeapons(int idx, std::vector<Weapon> weapons) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    // Invariant: pad to ≥3 so the PC path (weapons[0]=Main, [1]=Off, [2]=Ranged) is always valid.
    if (weapons.size() < 3) weapons.resize(3);
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
//  Summon accessors
// ─────────────────────────────────────────────────────────────────────────────

int BattleMap::getAgentSummonerIdx(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return -1;
    return placedAgents_[static_cast<std::size_t>(idx)].summoner_idx;
}

void BattleMap::setAgentSummonerIdx(int idx, int summoner_idx) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].summoner_idx = summoner_idx;
}

int BattleMap::getAgentFaction(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return 0;
    return placedAgents_[static_cast<std::size_t>(idx)].faction;
}

void BattleMap::setAgentFaction(int idx, int faction) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].faction = faction;
}

bool BattleMap::isAgentOnDeck(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return false;
    return placedAgents_[static_cast<std::size_t>(idx)].on_deck;
}

void BattleMap::setAgentOnDeck(int idx, bool on_deck) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].on_deck = on_deck;
}

bool BattleMap::isAgentNpcAutomated(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return false;
    return placedAgents_[static_cast<std::size_t>(idx)].is_npc_automated;
}

void BattleMap::setAgentNpcAutomated(int idx, bool automated) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].is_npc_automated = automated;
}

int BattleMap::getAgentNpcAutomationDifficulty(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return 0;
    return placedAgents_[static_cast<std::size_t>(idx)].npc_automation_difficulty_level;
}

void BattleMap::setAgentNpcAutomationDifficulty(int idx, int level) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].npc_automation_difficulty_level = level;
}

NpcAutomationStrategy BattleMap::getAgentNpcAutomationStrategy(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size()))
        return NpcAutomationStrategy::Simple;
    return placedAgents_[static_cast<std::size_t>(idx)].npc_automation_strategy;
}

void BattleMap::setAgentNpcAutomationStrategy(int idx, NpcAutomationStrategy strategy) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].npc_automation_strategy = strategy;
}

void BattleMap::setAgentName(int idx, std::string name) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    const auto i = static_cast<std::size_t>(idx);
    if (i < agentConfigs_.size()) agentConfigs_[i].name = name;
    placedAgents_[i].agent->setName(std::move(name));
}

void BattleMap::setAgentSprite(int idx, std::string sprite_path) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    const auto i = static_cast<std::size_t>(idx);
    if (i < agentConfigs_.size()) agentConfigs_[i].spritePath = sprite_path;
    placedAgents_[i].agent->setSprite(std::move(sprite_path));
}

std::string BattleMap::getAgentSummonSpell(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return {};
    return placedAgents_[static_cast<std::size_t>(idx)].summon_spell;
}

void BattleMap::setAgentSummonSpell(int idx, std::string spell_name) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].summon_spell = std::move(spell_name);
}

bool BattleMap::isAgentRemovedFromPlay(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return false;
    return placedAgents_[static_cast<std::size_t>(idx)].removed_from_play;
}

void BattleMap::setAgentRemovedFromPlay(int idx, bool removed) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    auto& pa = placedAgents_[static_cast<std::size_t>(idx)];
    pa.removed_from_play = removed;
    if (removed) {
        // Banish the tombstoned summon off-map so its footprint no longer collides with
        // movement, placement, or targeting on the real grid. The index stays valid (we never
        // erase), preserving every caster_idx/agent_idx/initiative reference. Intentionally
        // bypasses the inBounds check in setAgentPosition.
        pa.origin = Cell{-1, -1};
        pa.agent->setPosition(-1, -1);
    }
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
//  Inventory accessors (carried consumables)
// ─────────────────────────────────────────────────────────────────────────────

std::vector<Item> BattleMap::getAgentItems(int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return {};
    return placedAgents_[static_cast<std::size_t>(idx)].items;
}

void BattleMap::setAgentItems(int idx, std::vector<Item> items) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    placedAgents_[static_cast<std::size_t>(idx)].items = std::move(items);
}

void BattleMap::addItemToAgent(int idx, Item it) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    auto& iv = placedAgents_[static_cast<std::size_t>(idx)].items;
    // Stack identical items rather than growing a row per potion.
    for (auto& have : iv) {
        if (have.name == it.name) {
            have.quantity += std::max(1, it.quantity);
            return;
        }
    }
    iv.push_back(std::move(it));
}

void BattleMap::removeItemFromAgent(int idx, int item_idx) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(placedAgents_.size())) return;
    auto& iv = placedAgents_[static_cast<std::size_t>(idx)].items;
    if (item_idx < 0 || item_idx >= static_cast<int>(iv.size())) return;
    iv.erase(iv.begin() + item_idx);
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

std::vector<Cell> BattleMap::wallCells(Cell anchor, Cell endpoint,
                                       int widthFt, int maxLenFt) const {
    std::vector<Cell> cells;
    const double ax = static_cast<double>(anchor.col);
    const double ay = static_cast<double>(anchor.row);
    const double half_w = (widthFt / 5.0) / 2.0;   // half-thickness in cells

    const double dx = endpoint.col - ax, dy = endpoint.row - ay;
    const double len = std::sqrt(dx * dx + dy * dy);

    // Degenerate fallback: no aim vector → centered box (legacy behavior).
    if (endpoint.col < 0 || len < 0.001) {
        const double half_l = (maxLenFt / 5.0) / 2.0;
        for (int c = 0; c < cols_; ++c)
            for (int rr = 0; rr < rows_; ++rr) {
                const double bx = std::abs(c - ax), by = std::abs(rr - ay);
                if (bx <= half_w && by <= half_l) cells.push_back(Cell{c, rr});
            }
        return cells;
    }

    const double ux = dx / len, uy = dy / len;
    const double max_along = std::min(len, maxLenFt / 5.0);
    for (int c = 0; c < cols_; ++c)
        for (int rr = 0; rr < rows_; ++rr) {
            const double px = c - ax, py = rr - ay;
            const double along = px * ux + py * uy;
            const double perp = std::abs(-py * ux + px * uy);
            if (along >= 0.0 && along <= max_along && perp <= half_w)
                cells.push_back(Cell{c, rr});
        }
    return cells;
}

std::vector<Cell> BattleMap::aoeCells(Cell center, const Spell& spell,
                                      Cell casterOrigin, Cell endpoint,
                                      int casterSize) const {
    std::vector<Cell> cells;
    const double ax = static_cast<double>(center.col);
    const double ay = static_cast<double>(center.row);

    // Cone/Line apex: the cell on the caster's footprint nearest the aim point,
    // so a Large+ caster emanates from the facing edge, not its top-left origin.
    const int cs = std::max(1, casterSize);
    const int apexCol = std::clamp(center.col, casterOrigin.col, casterOrigin.col + cs - 1);
    const int apexRow = std::clamp(center.row, casterOrigin.row, casterOrigin.row + cs - 1);
    auto inCasterFootprint = [&](int c, int r) {
        return c >= casterOrigin.col && c < casterOrigin.col + cs &&
               r >= casterOrigin.row && r < casterOrigin.row + cs;
    };

    switch (spell.geometry) {
    case Spell::Sphere: {
        const double r = spell.radius / 5.0;
        for (int c = 0; c < cols_; ++c)
            for (int rr = 0; rr < rows_; ++rr) {
                const double dx = c - ax, dy = rr - ay;
                if (std::sqrt(dx * dx + dy * dy) <= r) cells.push_back(Cell{c, rr});
            }
        break;
    }
    case Spell::Cone: {
        const double cx = apexCol, cy = apexRow;
        const double dx = ax - cx, dy = ay - cy;
        const double ln = std::sqrt(dx * dx + dy * dy);
        if (ln < 0.001) break;
        const double ux = dx / ln, uy = dy / ln;
        const double r = spell.radius / 5.0;
        for (int c = 0; c < cols_; ++c)
            for (int rr = 0; rr < rows_; ++rr) {
                if (inCasterFootprint(c, rr)) continue;
                const double px = c - cx, py = rr - cy;
                const double plen = std::sqrt(px * px + py * py);
                if (plen < 0.001) continue;
                const double dot = px * ux + py * uy;
                if (dot > 0 && plen <= r && (dot / plen) >= 0.866)
                    cells.push_back(Cell{c, rr});
            }
        break;
    }
    case Spell::Line: {
        const double cx = apexCol, cy = apexRow;
        const double dx = ax - cx, dy = ay - cy;
        const double ln = std::sqrt(dx * dx + dy * dy);
        if (ln < 0.001) break;
        const double ux = dx / ln, uy = dy / ln;
        const double lcells = spell.length / 5.0;
        const double wcells = spell.width / 5.0;
        for (int c = 0; c < cols_; ++c)
            for (int rr = 0; rr < rows_; ++rr) {
                if (inCasterFootprint(c, rr)) continue;
                const double px = c - cx, py = rr - cy;
                const double along = px * ux + py * uy;
                const double perp = std::abs(-py * ux + px * uy);
                if (along >= 0.0 && along <= lcells && perp <= wcells / 2.0)
                    cells.push_back(Cell{c, rr});
            }
        break;
    }
    case Spell::Rectangle: {
        // Oriented wall: thick segment from `center` toward `endpoint`, clamped
        // to spell.length. Falls back to a centered box when unaimed.
        cells = wallCells(center, endpoint, spell.width, spell.length);
        break;
    }
    case Spell::Square: {
        const double wcells = spell.width / 5.0;
        const double lcells = spell.length / 5.0;
        for (int c = 0; c < cols_; ++c)
            for (int rr = 0; rr < rows_; ++rr) {
                const double dx = std::abs(c - ax), dy = std::abs(rr - ay);
                if (dx <= wcells / 2.0 && dy <= lcells / 2.0)
                    cells.push_back(Cell{c, rr});
            }
        break;
    }
    default:  // Single, Multiple, NumGeometry_t: no AoE footprint
        break;
    }
    return cells;
}

AreaOrigin BattleMap::areaOrigin(const Spell& spell, Cell casterOrigin, int casterSize,
                                 Cell centerCell) noexcept
{
    const int cs = std::max(1, casterSize);

    // A Cone/Line emanates from the caster: its origin is the cell of the caster's footprint
    // nearest the aim point. An area *placed* at a point (Sphere/Square/Rectangle) originates
    // at that point — unless the point lies on the caster (an Emanation such as Spirit Guardians
    // re-centers on the caster, so its origin is the caster itself).
    const bool from_caster =
        spell.geometry == Spell::Cone || spell.geometry == Spell::Line ||
        (centerCell.col >= casterOrigin.col && centerCell.col < casterOrigin.col + cs &&
         centerCell.row >= casterOrigin.row && centerCell.row < casterOrigin.row + cs);

    // Tracing from the caster's whole footprint (rather than one cell of it) is what keeps a
    // Large+ caster's own body from blocking its spell — hasLineOfSight excludes both endpoint
    // footprints from the wall test.
    if (from_caster) return AreaOrigin{casterOrigin, cs};
    return AreaOrigin{centerCell, 1};
}

std::vector<Cell> BattleMap::pruneBlockedCells(AreaOrigin origin,
                                               const std::vector<Cell>& cells) const
{
    std::vector<Cell> result;
    result.reserve(cells.size());
    for (const Cell& cell : cells)
        if (hasLineOfSight(origin.cell, origin.size, cell, 1))
            result.push_back(cell);
    return result;
}

std::vector<Cell> BattleMap::filterSpellCells(const std::vector<Cell>& cells,
                                              Cell casterOrigin, int casterSize,
                                              const Spell& spell, Cell centerCell) const
{
    // A spell that needs a clear path to its target point gets nothing at all when that point
    // is behind Total Cover. (spell.check_los_on_center no longer gates the per-cell wall test
    // below — an area is blocked by a wall whether or not the caster needed to see the center.)
    if (spell.requires_los && !hasLineOfSight(casterOrigin, casterSize, centerCell, 1))
        return {};

    const int rangeCells = spell.range / 5;
    std::vector<Cell> in_range;
    in_range.reserve(cells.size());
    for (const auto& cell : cells) {
        // Chebyshev distance from the caster's nearest edge to the cell.
        const int dc = std::max({casterOrigin.col - cell.col,
                                 cell.col - (casterOrigin.col + casterSize - 1),
                                 0});
        const int dr = std::max({casterOrigin.row - cell.row,
                                 cell.row - (casterOrigin.row + casterSize - 1),
                                 0});
        if (std::max(dc, dr) <= rangeCells)
            in_range.push_back(cell);
    }

    // The area itself can't reach through a wall, so drop whatever its point of origin can't see.
    return pruneBlockedCells(areaOrigin(spell, casterOrigin, casterSize, centerCell), in_range);
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

double BattleMap::getTerrainMultiplierFor(Cell c, MovementType mt, int mover_idx) const noexcept {
    (void)mt;  // cost multipliers are movement-type-independent (kept for API consistency)
    if (c.col < 0 || c.col >= cols_ || c.row < 0 || c.row >= rows_)
        return 1.0;

    // No mover context → fall back to the faction-blind overlay (e.g. Python preview, DM tools).
    if (mover_idx < 0)
        return getTerrainMultiplier(c, mt);

    const int idx = c.row * cols_ + c.col;
    const int mover_faction = getAgentFaction(mover_idx);

    // Recompute "most restrictive difficulty here" from the live effects, skipping any effect
    // this creature is spared from (its own / an ally's selective_targeting emanation).
    TerrainDifficulty worst = TerrainDifficulty::Normal;
    for (const auto& e : activeTerrainEffects_) {
        if (e.spares_source_allies) {
            const int src = e.source_agent_idx;
            const int src_faction = getAgentFaction(src);
            const bool ally = (src == mover_idx) || (src_faction != 0 && src_faction == mover_faction);
            if (ally) continue;  // source + allies ignore this terrain
        }
        if (std::find(e.cell_indices.begin(), e.cell_indices.end(), idx) != e.cell_indices.end())
            worst = std::max(worst, e.difficulty);
    }

    double dynamicMult = 1.0;
    switch (worst) {
        case TerrainDifficulty::Halved:    dynamicMult = 0.5;  break;
        case TerrainDifficulty::Quartered: dynamicMult = 0.25; break;
        case TerrainDifficulty::Slipping:  dynamicMult = 1.0;  break;
        case TerrainDifficulty::Normal:    dynamicMult = 1.0;  break;
    }
    return std::min(terrainMult_[idx], dynamicMult);
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

// ── Doors ─────────────────────────────────────────────────────────────────────
int BattleMap::doorAt(Cell c) const noexcept {
    for (std::size_t i = 0; i < doors_.size(); ++i)
        for (const Cell& dc : doors_[i].cells)
            if (dc == c) return static_cast<int>(i);
    return -1;
}

// Keep every doorway cell's TerrainType in agreement with the door's open state.
// Open  → Standard (passable + transparent), and the cell is erased from
//         disallowed_ in case auto-detection had marked the doorway as a wall.
// Closed→ Wall (reuses all existing movement + LOS blocking).
void BattleMap::syncDoorTerrain(int idx) noexcept {
    if (idx < 0 || idx >= static_cast<int>(doors_.size())) return;
    const Door& d = doors_[static_cast<std::size_t>(idx)];
    for (const Cell& c : d.cells) {
        if (d.open) {
            setTerrainType(c, TerrainType::Standard);
            disallowed_.erase(c);
        } else {
            setTerrainType(c, TerrainType::Wall);
        }
    }
}

int BattleMap::addDoor(const std::vector<Cell>& cells, bool open, bool locked,
                       int lock_dc, bool arcane_lock) {
    // Replace any existing door overlapping any of these cells rather than stacking.
    // Collect ids first so removeDoor's vector erasure can't shift indices mid-scan.
    std::vector<int> to_remove;
    for (const Cell& c : cells) {
        int existing = doorAt(c);
        if (existing < 0) continue;
        int rid = doors_[static_cast<std::size_t>(existing)].id;
        if (std::find(to_remove.begin(), to_remove.end(), rid) == to_remove.end())
            to_remove.push_back(rid);
    }
    for (int rid : to_remove) removeDoor(rid);

    Door d;
    d.id          = nextDoorId_++;
    d.cells       = cells;
    d.open        = open;
    d.locked      = locked;
    d.lock_dc     = lock_dc;
    d.arcane_lock = arcane_lock;
    doors_.push_back(d);
    syncDoorTerrain(static_cast<int>(doors_.size()) - 1);
    return d.id;
}

int BattleMap::addDoor(Cell c, bool open, bool locked, int lock_dc, bool arcane_lock) {
    return addDoor(std::vector<Cell>{c}, open, locked, lock_dc, arcane_lock);
}

void BattleMap::removeDoor(int id) noexcept {
    for (std::size_t i = 0; i < doors_.size(); ++i) {
        if (doors_[i].id == id) {
            // Restore every doorway cell to passable Standard terrain before erasing.
            for (const Cell& c : doors_[i].cells) {
                setTerrainType(c, TerrainType::Standard);
                disallowed_.erase(c);
            }
            doors_.erase(doors_.begin() + static_cast<std::ptrdiff_t>(i));
            return;
        }
    }
}

bool BattleMap::openDoor(int id) noexcept {
    for (std::size_t i = 0; i < doors_.size(); ++i) {
        if (doors_[i].id == id) {
            // A locked or (un-suppressed) arcane-locked door cannot simply be opened.
            if (doors_[i].locked) return false;
            if (doors_[i].arcane_lock && doors_[i].arcane_suppressed_turns <= 0)
                return false;
            doors_[i].open = true;
            syncDoorTerrain(static_cast<int>(i));
            return true;
        }
    }
    return false;
}

bool BattleMap::closeDoor(int id) noexcept {
    for (std::size_t i = 0; i < doors_.size(); ++i) {
        if (doors_[i].id == id) {
            doors_[i].open = false;
            syncDoorTerrain(static_cast<int>(i));
            return true;
        }
    }
    return false;
}

void BattleMap::lockDoor(int id, int dc) noexcept {
    for (std::size_t i = 0; i < doors_.size(); ++i) {
        if (doors_[i].id == id) {
            doors_[i].locked  = true;
            doors_[i].lock_dc = dc;
            doors_[i].open    = false;
            syncDoorTerrain(static_cast<int>(i));
            return;
        }
    }
}

void BattleMap::unlockDoor(int id) noexcept {
    for (auto& d : doors_) {
        if (d.id == id) { d.locked = false; return; }
    }
}

bool BattleMap::knockDoor(int id, int arcane_suppress_turns) noexcept {
    for (std::size_t i = 0; i < doors_.size(); ++i) {
        if (doors_[i].id != id) continue;
        doors_[i].locked = false;                         // mundane lock removed
        if (doors_[i].arcane_lock)                        // Arcane Lock suppressed, not removed
            doors_[i].arcane_suppressed_turns = arcane_suppress_turns;
        doors_[i].open = true;
        syncDoorTerrain(static_cast<int>(i));
        return true;
    }
    return false;
}

// ── Light levels (visibility & darkvision) ────────────────────────────────────
// Combine two light levels, brightest wins (defined below; forward-declared for getLightLevelFor).
static VisibilityLevel brighter(VisibilityLevel a, VisibilityLevel b) noexcept;

VisibilityLevel BattleMap::getLightLevel(Cell c) const noexcept {
    if (c.col < 0 || c.col >= cols_ || c.row < 0 || c.row >= rows_)
        return VisibilityLevel::Clear;  // out-of-bounds is bright
    return lightLevel_[c.row * cols_ + c.col];
}

VisibilityLevel BattleMap::getLightLevelFor(Cell c, int observer_idx) const noexcept {
    const VisibilityLevel actual = getLightLevel(c);
    // Only magical darkness can be "seen through"; anything else is the same for everyone.
    if (observer_idx < 0 || actual != VisibilityLevel::MagicalDark)
        return actual;
    if (c.col < 0 || c.col >= cols_ || c.row < 0 || c.row >= rows_)
        return actual;

    const int flat = c.row * cols_ + c.col;
    bool darkened_by_other = false;  // a MagicalDark effect here that the observer canNOT see through
    bool sees_through_here = false;  // the observer's own see-through Darkness covers this cell
    for (const auto& eff : activeLightEffects_) {
        if (eff.light_level != VisibilityLevel::MagicalDark) continue;
        if (std::find(eff.cell_indices.begin(), eff.cell_indices.end(), flat) == eff.cell_indices.end())
            continue;
        if (eff.see_through_agent_idx == observer_idx) sees_through_here = true;
        else darkened_by_other = true;
    }
    // If any darkness here is opaque to the observer (or none is see-through), it stays MagicalDark.
    if (darkened_by_other || !sees_through_here)
        return VisibilityLevel::MagicalDark;

    // The only darkness here is the observer's own: recompute the light without the magical-dark
    // layer (base lighting + non-magical effects, brightest wins).
    VisibilityLevel result = baseVisibilityLevel_[static_cast<std::size_t>(flat)];
    for (const auto& eff : activeLightEffects_) {
        if (eff.light_level == VisibilityLevel::MagicalDark) continue;
        if (std::find(eff.cell_indices.begin(), eff.cell_indices.end(), flat) != eff.cell_indices.end())
            result = brighter(result, eff.light_level);
    }
    return result;
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
            // Sunlight is a bright-light category; for vision it behaves exactly like Clear (and must
            // not dominate the "darkest cell wins" max, since its enum value is the highest).
            if (cell_light == VisibilityLevel::Sunlight) cell_light = VisibilityLevel::Clear;
            if (static_cast<int>(cell_light) > static_cast<int>(effective_light)) {
                effective_light = cell_light;
            }
        }
    }

    // Apply D&D 5e visibility rules
    // Truesight: sees through all conditions
    if (truesight_ft > 0 && dist_ft <= truesight_ft)
        return true;

    // Devil's Sight: sees in darkness and magical darkness (120ft max normally, but respecting
    // range). It does NOT pierce HeavilyObscured fog/smoke — that is a physical obscurement, not a
    // darkness, so only Truesight/Blindsight defeats it (Truesight already returned above).
    if (devilssight_ft > 0 && dist_ft <= devilssight_ft &&
        effective_light != VisibilityLevel::Clear && effective_light != VisibilityLevel::Dim &&
        effective_light != VisibilityLevel::HeavilyObscured)
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
        case VisibilityLevel::HeavilyObscured:
            return false;  // fog/smoke: only Truesight/Blindsight sees through (handled above)
        case VisibilityLevel::Blocked:
            return false;  // cannot see through walls/obstacles
        case VisibilityLevel::Sunlight:
            return true;   // bright light (normalized to Clear above; here for switch completeness)
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
            if (cell_light == VisibilityLevel::Sunlight) cell_light = VisibilityLevel::Clear;  // bright = Clear for vision
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

// ── Fog of war (persistent explored mask, PC-party scoped) ─────────────────────
void BattleMap::revealFogForFaction(int faction) noexcept {
    if (explored_.size() != static_cast<std::size_t>(rows_) * static_cast<std::size_t>(cols_))
        return;  // grid not analyzed yet

    for (const PlacedAgent& pa : placedAgents_) {
        if (!pa.agent) continue;
        if (pa.faction != faction) continue;
        if (pa.removed_from_play) continue;

        const Agent::Stats& s = pa.agent->getStats();
        // Only living observers reveal fog (a downed/dead party member has no active senses).
        if (s.hp_cur <= 0 || pa.agent->getConditions().dead) continue;

        const int size = pa.agent->getSize();
        const int dv = s.darkvision_range;
        const int ts = s.truesight_range;
        const int ds = s.devilssight_range;
        // Base perception range (feet): mirrors CombatEngine::computeVisibility's heuristic.
        const int base_perception = std::max(20, (s.wis / 2) * 5);

        // Maximum range this observer could possibly see, in cells, to bound the scan.
        const int max_ft = std::max({base_perception, dv, ts, ds});
        const int reach = max_ft / 5;

        // Scan the bounding box of the observer's footprint expanded by `reach`.
        const int r0 = std::max(0, pa.origin.row - reach);
        const int r1 = std::min(rows_ - 1, pa.origin.row + (size - 1) + reach);
        const int c0 = std::max(0, pa.origin.col - reach);
        const int c1 = std::min(cols_ - 1, pa.origin.col + (size - 1) + reach);

        for (int r = r0; r <= r1; ++r) {
            for (int c = c0; c <= c1; ++c) {
                const std::size_t idx = static_cast<std::size_t>(r) * static_cast<std::size_t>(cols_)
                                      + static_cast<std::size_t>(c);
                if (explored_[idx]) continue;  // monotonic: already revealed
                if (canSee(pa.origin, size, dv, ts, ds, Cell{c, r}, 1))
                    explored_[idx] = 1;
            }
        }
    }
}

bool BattleMap::isExplored(Cell c) const noexcept {
    if (c.col < 0 || c.row < 0 || c.col >= cols_ || c.row >= rows_)
        return false;
    const std::size_t idx = static_cast<std::size_t>(c.row) * static_cast<std::size_t>(cols_)
                          + static_cast<std::size_t>(c.col);
    return idx < explored_.size() && explored_[idx] != 0;
}

std::vector<Cell> BattleMap::exploredCells() const {
    std::vector<Cell> out;
    for (int r = 0; r < rows_; ++r) {
        for (int c = 0; c < cols_; ++c) {
            const std::size_t idx = static_cast<std::size_t>(r) * static_cast<std::size_t>(cols_)
                                  + static_cast<std::size_t>(c);
            if (idx < explored_.size() && explored_[idx])
                out.push_back(Cell{c, r});
        }
    }
    return out;
}

void BattleMap::setExplored(Cell c, bool v) noexcept {
    if (c.col < 0 || c.row < 0 || c.col >= cols_ || c.row >= rows_)
        return;
    const std::size_t idx = static_cast<std::size_t>(c.row) * static_cast<std::size_t>(cols_)
                          + static_cast<std::size_t>(c.col);
    if (idx < explored_.size())
        explored_[idx] = v ? 1 : 0;
}

void BattleMap::setExploredCells(const std::vector<Cell>& cells) noexcept {
    std::fill(explored_.begin(), explored_.end(), static_cast<uint8_t>(0));
    for (const Cell& c : cells)
        setExplored(c, true);
}

void BattleMap::revealAllFog() noexcept {
    std::fill(explored_.begin(), explored_.end(), static_cast<uint8_t>(1));
}

void BattleMap::clearFog() noexcept {
    std::fill(explored_.begin(), explored_.end(), static_cast<uint8_t>(0));
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
    pa.agent->getStats().is_npc = true;

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
                                   int slip_distance_feet,
                                   int spell_idx,
                                   int cast_level,
                                   bool requires_concentration,
                                   int anchor_agent_idx,
                                   int anchor_radius_ft,
                                   bool spares_source_allies,
                                   uint32_t ward_creature_mask,
                                   bool ward_traps,
                                   bool ward_all_living) {
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
        slip_distance_feet,
        spell_idx,
        cast_level,
        requires_concentration,
        anchor_agent_idx,
        anchor_radius_ft,
        spares_source_allies,
        ward_creature_mask,
        ward_traps,
        ward_all_living
    };
    activeTerrainEffects_.push_back(effect);

    updateTerrain();
    return id;
}

void BattleMap::setTerrainEffectCells(int effect_id, std::vector<Cell> cells) noexcept {
    auto it = std::find_if(activeTerrainEffects_.begin(), activeTerrainEffects_.end(),
        [effect_id](const ActiveTerrainEffect& e) { return e.id == effect_id; });
    if (it == activeTerrainEffects_.end())
        return;
    std::vector<int> indices;
    for (const auto& cell : cells)
        if (cell.col >= 0 && cell.col < cols_ && cell.row >= 0 && cell.row < rows_)
            indices.push_back(cell.row * cols_ + cell.col);
    it->cell_indices = std::move(indices);
    updateTerrain();
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
// Return the brighter of two light levels. Sunlight is the brightest category; for every other
// value "brighter" means the smaller enum (Clear < Dim < ... < Blocked), matching std::min. Used
// when light sources/effects raise a cell's light — Sunlight is never dimmed by a normal source.
static VisibilityLevel brighter(VisibilityLevel a, VisibilityLevel b) noexcept {
    if (a == VisibilityLevel::Sunlight || b == VisibilityLevel::Sunlight)
        return VisibilityLevel::Sunlight;
    return std::min(a, b);
}

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
                        brighter(baseVisibilityLevel_[static_cast<std::size_t>(idx)], VisibilityLevel::Clear);
                } else if (dist <= dim_cells) {
                    int idx = r * cols_ + c;
                    baseVisibilityLevel_[static_cast<std::size_t>(idx)] =
                        brighter(baseVisibilityLevel_[static_cast<std::size_t>(idx)], VisibilityLevel::Dim);
                }
            }
        }
    }

    updateLighting();
}

void BattleMap::updateLighting() noexcept {
    // Step 1: reset computed lighting to base
    lightLevel_ = baseVisibilityLevel_;

    // Step 2: apply normal light effects (brightest wins = std::min). MagicalDark and
    // HeavilyObscured are override levels (handled below) — bright light cannot dispel them, so they
    // must not flow through the brighter() combine here.
    for (const auto& eff : activeLightEffects_) {
        if (eff.light_level == VisibilityLevel::MagicalDark ||
            eff.light_level == VisibilityLevel::HeavilyObscured)
            continue;  // Handle overrides in steps 3–4
        for (int idx : eff.cell_indices) {
            if (idx >= 0 && static_cast<std::size_t>(idx) < lightLevel_.size()) {
                lightLevel_[static_cast<std::size_t>(idx)] =
                    brighter(lightLevel_[static_cast<std::size_t>(idx)], eff.light_level);
            }
        }
    }

    // Step 3: apply heavy obscurement / fog (override; survives bright light). Applied before
    // magical darkness so that, where both overlap, MagicalDark (more restrictive — also blocks
    // devil's sight) wins.
    for (const auto& eff : activeLightEffects_) {
        if (eff.light_level != VisibilityLevel::HeavilyObscured)
            continue;
        for (int idx : eff.cell_indices) {
            if (idx >= 0 && static_cast<std::size_t>(idx) < lightLevel_.size()) {
                lightLevel_[static_cast<std::size_t>(idx)] = VisibilityLevel::HeavilyObscured;
            }
        }
    }

    // Step 4: apply magical darkness (always wins = override)
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
                                 int source_agent_idx,
                                 int see_through_agent_idx,
                                 int anchor_agent_idx,
                                 int anchor_radius_ft) noexcept {
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
        source_agent_idx,
        see_through_agent_idx,
        anchor_agent_idx,
        anchor_radius_ft
    });

    updateLighting();
    return id;
}

void BattleMap::setLightEffectCells(int effect_id, std::vector<Cell> cells) noexcept {
    auto it = std::find_if(activeLightEffects_.begin(), activeLightEffects_.end(),
        [effect_id](const ActiveLightEffect& e) { return e.id == effect_id; });
    if (it == activeLightEffects_.end())
        return;
    std::vector<int> indices;
    for (const auto& cell : cells)
        if (cell.col >= 0 && cell.col < cols_ && cell.row >= 0 && cell.row < rows_)
            indices.push_back(cell.row * cols_ + cell.col);
    it->cell_indices = std::move(indices);
    updateLighting();
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

void BattleMap::setSpellEffectCells(int effect_id, std::vector<Cell> cells) noexcept {
    auto it = std::find_if(activeSpellEffects_.begin(), activeSpellEffects_.end(),
        [effect_id](const ActiveSpellEffect& e) { return e.effect_id == effect_id; });
    if (it != activeSpellEffects_.end())
        it->cells = std::move(cells);
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

bool BattleMap::pickUpItem(int item_id, int agent_idx, int slot_idx) noexcept {
    const auto& agents = placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    // Find the item
    auto item_it = std::find_if(mapItems_.begin(), mapItems_.end(),
                                [item_id](const MapItem& m){ return m.id == item_id; });
    if (item_it == mapItems_.end()) return false;

    // Get agent's current weapons
    auto weapons = getAgentWeapons(agent_idx);

    // Picking up a thrown weapon you are still carrying re-joins the BUNDLE rather than taking a
    // slot of its own: retrieve one of the javelins you threw and you hold 4 again, not two stacks
    // of javelins. Checked before any slot logic — a stack always merges, whatever slot was asked
    // for. (This is why a thrown weapon is worth retrieving at all: it was never destroyed.)
    if (item_it->weapon.thrown) {
        for (auto& w : weapons) {
            if (w.thrown && w.name == item_it->weapon.name) {
                w.quantity += std::max(1, item_it->weapon.quantity);
                setAgentWeapons(agent_idx, weapons);
                removeItem(item_id);
                return true;
            }
        }
    }

    // A slot is FREE when it holds no weapon: an empty name, or the bare "Unarmed" default that is
    // this codebase's blank-slot sentinel (helpers._weapon_slot_is_empty; also what a weapon slot
    // is reset to when it is dropped, or when the last copy of a bundle is thrown). "MonkUnarmed"
    // is a real weapon and is deliberately NOT matched here.
    const auto slot_is_free = [](const Weapon& w) {
        return w.name.empty() || w.name == "Unarmed";
    };

    int target_slot = slot_idx;
    if (target_slot < 0) {
        for (std::size_t i = 0; i < weapons.size(); ++i) {
            if (slot_is_free(weapons[i])) {
                target_slot = static_cast<int>(i);
                break;
            }
        }
    }

    if (target_slot < 0) {
        weapons.push_back(item_it->weapon);            // no free slot: append a new attack slot
    } else {
        if (target_slot >= static_cast<int>(weapons.size()))
            weapons.resize(static_cast<std::size_t>(target_slot) + 1);
        weapons[static_cast<std::size_t>(target_slot)] = item_it->weapon;  // replaces what was there
    }
    setAgentWeapons(agent_idx, weapons);

    // Remove the item from the map
    removeItem(item_id);
    return true;
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
