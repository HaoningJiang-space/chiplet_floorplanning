// Interval cover of the six relative CPU centre coordinates, in units of 1/8 mm.
// Python supplies conservative physical kernels and the exact pin-bundle cost tables.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <queue>
#include <stdexcept>
#include <vector>

constexpr int range = 512, nwire = 2 * range + 1, nr = 257;
constexpr int pair_i[6] = {0, 0, 0, 1, 1, 2}, pair_j[6] = {1, 2, 3, 2, 3, 3};
constexpr int ring[4] = {0, 1, 4, 5};
struct Model {
    double cap, self, offset[4][2], carrier[6][2], separation[6][2];
    double pin[4][2][2][nwire], mutual[6][nr][nr];
};
static_assert(sizeof(Model) == sizeof(double) * (2 + 8 + 24 + 4 * 2 * 2 * nwire + 6 * nr * nr));
struct Box {
    std::array<short, 6> lo, hi;
    double lower;
    bool operator<(const Box &other) const { return lower > other.lower; }
};

double wire_axis(const Model &m, int e, int axis, int lo, int hi) {
    if (lo > hi)
        return 1e10;
    return std::max(m.pin[e][axis][0][lo + range], m.pin[e][axis][1][hi + range]);
}

double lower(const Model &m, Box &box) {
    int upper[2][4][4] = {};
    for (int ax = 0; ax < 2; ++ax)
        for (int e = 0; e < 6; ++e) {
            int i = pair_i[e], j = pair_j[e], jlo = box.lo[2 * (j - 1) + ax],
                jhi = box.hi[2 * (j - 1) + ax];
            int ilo = i ? box.lo[2 * (i - 1) + ax] : 0, ihi = i ? box.hi[2 * (i - 1) + ax] : 0;
            int maxsep = static_cast<int>(m.carrier[e][ax]);
            upper[ax][i][j] = std::min(maxsep, jhi - ilo);
            upper[ax][j][i] = std::min(maxsep, ihi - jlo);
        }
    for (int e = 0; e < 6; ++e) {
        int i = pair_i[e], j = pair_j[e];
        bool possible = false;
        for (int ax = 0; ax < 2; ++ax) {
            if (-upper[ax][j][i] > upper[ax][i][j])
                return INFINITY;
            possible |= std::max(upper[ax][i][j], upper[ax][j][i]) >= m.separation[e][ax];
        }
        if (!possible)
            return INFINITY;
    }
    double cost[4], total = 0.;
    // For each bundle at least one axis must separate its two rectangles.
    for (int r = 0; r < 4; ++r) {
        int e = ring[r], i = pair_i[e], j = pair_j[e];
        double uncon[2], separate[2];
        for (int ax = 0; ax < 2; ++ax) {
            int lo = -upper[ax][j][i], hi = upper[ax][i][j],
                gap = static_cast<int>(m.separation[e][ax]);
            uncon[ax] = wire_axis(m, r, ax, lo, hi);
            separate[ax] = std::min(wire_axis(m, r, ax, lo, std::min(hi, -gap)),
                                    wire_axis(m, r, ax, std::max(lo, gap), hi));
        }
        cost[r] = std::min(uncon[0] + separate[1], uncon[1] + separate[0]);
        total += cost[r];
    }
    if (total > m.cap)
        return INFINITY;
    // Reserve every other bundle's minimum. The displacement of the mean pin
    // offsets in each axis must fit the remaining average length of this bundle.
    for (int r = 0; r < 4; ++r) {
        int e = ring[r], i = pair_i[e], j = pair_j[e];
        double budget = m.cap - (total - cost[r]);
        for (int ax = 0; ax < 2; ++ax) {
            int b = 1 - ax;
            double used = std::max(
                {0., -upper[b][j][i] / 8. - m.offset[r][b], m.offset[r][b] - upper[b][i][j] / 8.});
            double slack = budget - used + 1e-8;
            if (slack < 0.)
                return INFINITY;
            upper[ax][i][j] =
                std::min(upper[ax][i][j], int(std::ceil(8 * (m.offset[r][ax] + slack))));
            upper[ax][j][i] =
                std::min(upper[ax][j][i], int(std::ceil(8 * (-m.offset[r][ax] + slack))));
        }
    }
    // Signed differences share endpoints. Compose upper bounds along all paths.
    for (int ax = 0; ax < 2; ++ax) {
        auto &u = upper[ax];
        for (int k = 0; k < 4; ++k)
            for (int i = 0; i < 4; ++i)
                for (int j = 0; j < 4; ++j)
                    u[i][j] = std::min(u[i][j], u[i][k] + u[k][j]);
        for (int i = 0; i < 4; ++i)
            if (u[i][i] < 0)
                return INFINITY;
        for (int i = 1; i < 4; ++i) {
            box.lo[2 * (i - 1) + ax] = -u[i][0];
            box.hi[2 * (i - 1) + ax] = u[0][i];
        }
    }
    double all = 0., incident[4] = {}, largest = 0.;
    for (int e = 0; e < 6; ++e) {
        int i = pair_i[e], j = pair_j[e];
        int x = std::max(upper[0][i][j], upper[0][j][i]);
        int y = std::max(upper[1][i][j], upper[1][j][i]);
        if (x < m.separation[e][0] && y < m.separation[e][1])
            return INFINITY;
        if (x < 0 || y < 0 || x >= nr || y >= nr)
            throw std::runtime_error("distance outside table");
        double k = m.mutual[e][x][y];
        all += k;
        incident[i] += k;
        incident[j] += k;
        largest = std::max(largest, k); // Two-die test
    }
    largest = std::max(largest, all / 2);
    for (auto x : incident)
        largest = std::max(largest, 2 * (all - x) / 3);
    return 45. + m.self + 150. * largest - 1e-6;
}

int main(int argc, char **argv) {
    if (argc != 2)
        return 2;
    auto m = new Model();
    if (!std::cin.read(reinterpret_cast<char *>(m), sizeof(Model)))
        return 3;
    std::priority_queue<Box> open;
    Box root{};
    root.lo.fill(-256);
    root.hi.fill(256);
    root.lower = lower(*m, root);
    if (std::isfinite(root.lower))
        open.push(root);
    std::uint64_t expanded = 0, limit = std::strtoull(argv[1], nullptr, 10);
    double terminal = INFINITY;
    while (!open.empty() && expanded < limit && open.top().lower < terminal) {
        Box b = open.top();
        open.pop();
        int axis = 0;
        for (int a = 1; a < 6; ++a)
            if (b.hi[a] - b.lo[a] > b.hi[axis] - b.lo[axis])
                axis = a;
        if (b.hi[axis] - b.lo[axis] <= 1) {
            terminal = std::min(terminal, b.lower);
            continue;
        }
        int mid = b.lo[axis] + (b.hi[axis] - b.lo[axis]) / 2;
        for (int side = 0; side < 2; ++side) {
            Box child = b;
            if (side)
                child.lo[axis] = mid;
            else
                child.hi[axis] = mid;
            child.lower = std::max(b.lower, lower(*m, child));
            if (std::isfinite(child.lower) && child.lower < terminal)
                open.push(child);
        }
        ++expanded;
    }
    double bound = std::min(terminal, open.empty() ? double(INFINITY) : open.top().lower);
    std::cout << std::setprecision(15) << (std::isfinite(bound) ? bound : -1.) << " " << expanded
              << " " << open.size() << " " << (std::isfinite(terminal) ? terminal : -1.) << "\n";
    delete m;
}
