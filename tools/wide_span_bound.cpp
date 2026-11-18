// Lower envelope of all four-CPU arrangements in a continuous, span-limited box.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <queue>
#include <string>
#include <vector>

using Six = std::array<int, 6>;
struct Box {
    Six lo{}, hi{};
    double kelvin = 0;
    bool operator<(const Box &other) const { return kelvin > other.kelvin; }
};
struct Pair {
    int ix, jx, iy, jy;
};
constexpr int extent = 248; // 31 mm centre range, in units of 1/8 mm
constexpr int side = 257;
double kernel[side][side];

bool reduce(Box &box, int budget) {
    // The least restrictive total span is saturated by increasing nonnegative gaps.
    // Each axis still has capacity 31 mm; expansion can only reduce uniform-plane mutual heat.
    for (int pass = 0; pass < 2; ++pass) {
        int lo[2]{}, hi[2]{};
        for (int i = 0; i < 6; ++i) {
            lo[i / 3] += box.lo[i];
            hi[i / 3] += box.hi[i];
        }
        if (lo[0] > extent || lo[1] > extent || lo[0] + lo[1] > budget ||
            std::min(extent, hi[0]) + std::min(extent, hi[1]) < budget)
            return false;
        for (int i = 0; i < 6; ++i) {
            int a = i / 3, b = 1 - a;
            int l = box.lo[i], h = box.hi[i];
            box.hi[i] = std::min(h, std::min(extent, budget - lo[b]) - (lo[a] - l));
            box.lo[i] = std::max(l, budget - std::min(extent, hi[b]) - (hi[a] - h));
            if (box.hi[i] < box.lo[i])
                return false;
        }
    }
    return true;
}

bool evaluate(Box &box, int budget, const std::array<Pair, 6> &pairs, double self_k) {
    if (!reduce(box, budget))
        return false;
    int lower[2][4]{}, upper[2][4]{};
    for (int a = 0; a < 2; ++a)
        for (int i = 0; i < 3; ++i) {
            lower[a][i + 1] = lower[a][i] + box.lo[3 * a + i];
            upper[a][i + 1] = upper[a][i] + box.hi[3 * a + i];
        }
    if (lower[0][3] > extent || lower[1][3] > extent || lower[0][3] + lower[1][3] > budget ||
        std::min(extent, upper[0][3]) + std::min(extent, upper[1][3]) < budget)
        return false;
    auto distance_max = [&](int a, int i, int j) {
        int outside = lower[a][3] - (lower[a][j] - lower[a][i]);
        return std::min(upper[a][j] - upper[a][i],
                        std::min(extent, budget - lower[1 - a][3]) - outside);
    };
    double heat[6];
    for (int e = 0; e < 6; ++e) {
        auto [i, j, k, l] = pairs[e];
        int x = distance_max(0, i, j), y = distance_max(1, k, l);
        if (std::max(x, y) < 64)
            return false; // Even 8 x 8 mm rectangles would intersect.
        heat[e] = kernel[x][y];
    }
    // Every subset's power-weighted mean rise bounds the actual peak from below.
    double total = 0;
    for (double h : heat)
        total += h;
    double strongest = 75 * total;
    for (double h : heat)
        strongest = std::max(strongest, 150 * h);
    for (const auto &t : {std::array<int, 3>{0, 1, 3}, {0, 2, 4}, {1, 2, 5}, {3, 4, 5}})
        strongest = std::max(strongest, 100 * (heat[t[0]] + heat[t[1]] + heat[t[2]]));
    box.kelvin = self_k + strongest - 1e-5;
    return true;
}

int main(int argc, char **argv) {
    if (argc != 5 || !std::cin.read(reinterpret_cast<char *>(kernel), sizeof(kernel)))
        return 2;
    int budget = std::stoi(argv[1]), limit = std::stoi(argv[3]);
    double self = std::stod(argv[2]);
    std::string order = argv[4];
    if (order.size() != 4 || budget > 2 * extent)
        return 2;
    std::array<Pair, 6> pairs;
    int e = 0;
    for (int i = 0; i < 4; ++i)
        for (int j = i + 1; j < 4; ++j) {
            int a = order[i] - '0', b = order[j] - '0';
            pairs[e++] = {i, j, std::min(a, b), std::max(a, b)};
        }
    std::priority_queue<Box> q;
    Box first;
    first.hi.fill(extent);
    if (!evaluate(first, budget, pairs, self))
        return 3;
    q.push(first);
    double terminal = 1e20;
    int expanded = 0, leaves = 0, discarded = 0;
    while (!q.empty() && expanded < limit && q.top().kelvin < terminal) {
        auto parent = q.top();
        q.pop();
        int axis = 0;
        for (int i = 1; i < 6; ++i)
            if (parent.hi[i] - parent.lo[i] > parent.hi[axis] - parent.lo[axis])
                axis = i;
        if (parent.hi[axis] - parent.lo[axis] <= 1) {
            terminal = std::min(terminal, parent.kelvin);
            ++leaves;
            continue;
        }
        ++expanded;
        int mid = (parent.lo[axis] + parent.hi[axis]) / 2;
        for (int h = 0; h < 2; ++h) {
            Box child = parent;
            if (h)
                child.lo[axis] = mid;
            else
                child.hi[axis] = mid;
            if (evaluate(child, budget, pairs, self))
                q.push(child);
            else
                ++discarded;
        }
    }
    const double bound = std::min(q.empty() ? 1e20 : q.top().kelvin, terminal);
    std::cout << std::setprecision(15) << bound << " " << expanded << " " << q.size() << " "
              << leaves << " " << discarded << "\n";
}
