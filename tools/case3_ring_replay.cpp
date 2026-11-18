// Independent yes/no check by dyadic subdivision of six continuous coordinates.
// Each node is checked directly against the geometry, pin and heating tables.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <memory>

struct Inputs {
    double cap, self, offset[4][2], carrier[6][2], separation[6][2];
    double cost[4][2][2][1025], kernel[6][257][257];
};
struct Counts {
    std::uint64_t visits = 0, geometry = 0, wire = 0, heat = 0, unknown = 0;
};
struct Interval {
    int lo = -256, hi = 256;
};
const int endpoints[6][2] = {{0, 1}, {0, 2}, {0, 3}, {1, 2}, {1, 3}, {2, 3}};
const int rid[6] = {0, 1, -1, -1, 2, 3};

void visit(const Inputs &in, std::array<Interval, 6> &coords, double target, Counts &c) {
    ++c.visits;
    if (c.visits > 60000000) {
        ++c.unknown;
        return;
    }
    double wire = 0., thermal[6];
    for (int e = 0; e < 6; ++e) {
        int a = endpoints[e][0], b = endpoints[e][1], mx[2];
        double low0[2] = {}, loSeparated[2] = {};
        bool separate = false;
        for (int h = 0; h < 2; ++h) {
            Interval source = a ? coords[2 * (a - 1) + h] : Interval{0, 0};
            Interval dest = coords[2 * (b - 1) + h];
            int span = static_cast<int>(in.carrier[e][h]);
            int lo = std::max(-span, dest.lo - source.hi), hi = std::min(span, dest.hi - source.lo);
            if (lo > hi) {
                ++c.geometry;
                return;
            }
            mx[h] = std::max(std::abs(lo), std::abs(hi));
            int sep = static_cast<int>(in.separation[e][h]);
            separate |= mx[h] >= sep;
            if (rid[e] >= 0) {
                const auto &one = in.cost[rid[e]][h];
                auto axis_cost = [&](int low, int high) {
                    return low > high ? 1e12 : std::max(one[0][512 + low], one[1][512 + high]);
                };
                low0[h] = axis_cost(lo, hi);
                loSeparated[h] =
                    std::min(axis_cost(lo, std::min(hi, -sep)), axis_cost(std::max(lo, sep), hi));
            }
        }
        if (!separate) {
            ++c.geometry;
            return;
        }
        if (rid[e] >= 0)
            wire += std::min(loSeparated[0] + low0[1], low0[0] + loSeparated[1]);
        thermal[e] = in.kernel[e][mx[0]][mx[1]];
    }
    if (wire > in.cap + 1e-7) {
        ++c.wire;
        return;
    }
    // Enumerate each subset of equally powered CPUs directly.
    for (int mask : {15, 7, 11, 13, 14, 3, 5, 9, 6, 10, 12}) {
        int count = 0;
        double sum = 0.;
        for (int i = 0; i < 4; ++i)
            count += (mask >> i) & 1;
        for (int e = 0; e < 6; ++e)
            if ((mask & (1 << endpoints[e][0])) && (mask & (1 << endpoints[e][1])))
                sum += thermal[e];
        if (45. + in.self + 300. * sum / count - 1e-5 >= target) {
            ++c.heat;
            return;
        }
    }
    int axis = 0;
    for (int i = 1; i < 6; ++i)
        if (coords[i].hi - coords[i].lo > coords[axis].hi - coords[axis].lo)
            axis = i;
    Interval initial = coords[axis];
    if (initial.hi - initial.lo <= 1) {
        ++c.unknown;
        return;
    }
    int mid = (initial.lo + initial.hi) / 2;
    coords[axis] = {initial.lo, mid};
    visit(in, coords, target, c);
    coords[axis] = {mid, initial.hi};
    visit(in, coords, target, c);
    coords[axis] = initial;
}

int main(int argc, char **argv) {
    if (argc != 2)
        return 2;
    auto p = std::make_unique<Inputs>();
    if (!std::cin.read(reinterpret_cast<char *>(p.get()), sizeof(Inputs)))
        return 3;
    Counts counts;
    std::array<Interval, 6> coords{};
    visit(*p, coords, std::stod(argv[1]), counts);
    std::cout << counts.visits << " " << counts.geometry << " " << counts.wire << " " << counts.heat
              << " " << counts.unknown << "\n";
}
