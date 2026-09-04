"""Prove the lottery does what the README claims.

Three independent legs, which must all agree:

  1. CLOSED FORM   -- algebra done by hand. A veteran holds slot v exactly when
                      neither newcomer reaches v or better, so the answer is
                      (1 - G_v)**2 where G_v is the cumulative landing odds.
  2. ENUMERATION   -- every reachable outcome, summed exactly. No sampling,
                      so no sampling error.
  3. MONTE CARLO   -- the shipped sampler, run millions of times, compared
                      against leg 2 in standard errors.

Legs 1 and 2 agreeing proves the math is right. Leg 3 agreeing with them
proves the code actually implements that math.

    python verify.py
    python verify.py --trials 5000000
"""

import argparse
import math
import random
import sys
from collections import Counter

import lottery

RULE = "=" * 78
THIN = "-" * 78

# chi-square upper-tail critical values at alpha = 0.001, by degrees of freedom
CHI2_001 = {1: 10.83, 4: 18.47, 5: 20.52}


def section(title):
    print()
    print(RULE)
    print("  " + title)
    print(RULE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify the lottery's probabilities.")
    ap.add_argument("--trials", type=int, default=1_000_000, help="Monte Carlo trials (default 1e6)")
    ap.add_argument("--seed", default="verification", help="seed phrase for the Monte Carlo")
    ap.add_argument("--league", default=str(lottery.DEFAULT_LEAGUE))
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    league = lottery.load_league(args.league)
    slots, vets, newcomers = league.slots, league.veteran_seats, league.newcomer_seats
    targets = league.targets
    odds = lottery.promotion_ladder(targets)
    failures = []

    def check(label, ok, detail=""):
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", label, ("  " + detail) if detail else ""))
        if not ok:
            failures.append(label)

    names = {r["slot"]: (r["manager"] or "seat %d" % r["slot"]) for r in league.standings}

    # ------------------------------------------------------------------
    section("1. THE PROMOTION LADDER")
    print()
    print("  Each newcomer rolls once in [0, 1), independently of the other:")
    print()
    cum = 0.0
    for bound, slot in odds.cutoffs:
        print("      %-15s  ->  pick %d      (%.4f%% per newcomer)"
              % ("roll < %.6f" % bound, slot, odds.landing[slot] * 100))
        cum = bound
    print("      %-15s  ->  no promotion  (%.4f%% per newcomer)" % ("otherwise", odds.stay * 100))
    print()
    print("  A veteran keeps their slot when NEITHER newcomer reaches it. Two")
    print("  independent rolls, so the advertised number is the square of one roll:")
    print()
    print("  slot   advertised   1 - G_v (one newcomer misses)   squared      target?")
    closed = {}
    for v in vets:
        g = 1.0 - sum(odds.landing[u] for u in vets if u <= v)
        closed[v] = g * g
        print("   %-4d     %4.0f%%              %.9f            %.9f   %s"
              % (v, targets[v] * 100, g, closed[v],
                 "yes" if abs(closed[v] - targets[v]) < 1e-12 else "NO"))
    print()
    r_closed = max(abs(closed[v] - targets[v]) for v in vets)
    check("closed form hits every target", r_closed < 1e-12, "max residual %.2e" % r_closed)
    check("ladder is a probability distribution",
          abs(sum(odds.landing.values()) + odds.stay - 1.0) < 1e-12,
          "sums to %.15f" % (sum(odds.landing.values()) + odds.stay))
    check("no negative landing odds", min(odds.landing.values()) > 0)

    # ------------------------------------------------------------------
    section("2. EXACT DISTRIBUTION  (seat -> final pick, by exhaustive enumeration)")
    exact = lottery.exact_distribution(odds, league)
    ev = lottery.expected_slots(exact)
    print()
    print("  %-10s" % "" + "".join("%9s" % ("-> %d" % d) for d in slots) + "     E[pick]")
    for s in slots:
        row = "".join("%8.4f%%" % (exact[s][d] * 100) for d in slots)
        print("  %-8s%s     %7.4f" % (names[s][:8], row, ev[s]))
    print()

    r_exact = max(abs(exact[v][v] - targets[v]) for v in vets)
    r_agree = max(abs(closed[v] - exact[v][v]) for v in vets)
    check("enumeration hits every target", r_exact < 1e-12, "max residual %.2e" % r_exact)
    check("closed form == enumeration", r_agree < 1e-12, "max gap %.2e" % r_agree)

    rows_ok = max(abs(sum(exact[s].values()) - 1.0) for s in slots)
    cols_ok = max(abs(sum(exact[s][d] for s in slots) - 1.0) for d in slots)
    check("every row sums to 1 (everyone lands somewhere)", rows_ok < 1e-12, "max dev %.2e" % rows_ok)
    check("every column sums to 1 (every pick filled exactly once)", cols_ok < 1e-12,
          "max dev %.2e" % cols_ok)
    check("no negative probabilities", min(exact[a][b] for a in slots for b in slots) >= 0.0)

    # The whole point of the rule change:
    climb = [(v, d) for v in vets for d in slots if d < v and exact[v][d] > 0]
    check("no returning manager can EVER move up", not climb,
          "checked all %d veteran/pick pairs" % (len(vets) * len(slots)))
    top_newcomer = min(d for s in newcomers for d in slots if exact[s][d] > 0)
    check("newcomers cap out at pick %d" % min(slots), top_newcomer == min(slots),
          "best reachable pick is %d" % top_newcomer)

    # Both newcomers must have identical promotion odds -- the coin flip on a
    # collision is what makes this true.
    asym = max(abs(exact[newcomers[0]][v] - exact[newcomers[1]][v]) for v in vets)
    check("both newcomers have identical odds on every promotion pick", asym < 1e-12,
          "max gap %.2e" % asym)

    print()
    print("  P(neither promoted, board unchanged)   %.4f%%" % (odds.stay ** 2 * 100))
    print("  P(exactly one promoted)                %.4f%%"
          % (2 * odds.stay * (1 - odds.stay) * 100))
    print("  P(both promoted)                       %.4f%%" % ((1 - odds.stay) ** 2 * 100))
    print("  P(both roll the same pick, coin flip)  %.4f%%"
          % (sum(p * p for p in odds.landing.values()) * 100))

    # ------------------------------------------------------------------
    section("3. MONTE CARLO  (%s trials of the shipped sampler)" % f"{args.trials:,}")
    rng = random.Random(lottery.seed_from_text(args.seed))
    counts = {s: Counter() for s in slots}
    ladder_counts = Counter()
    order_violations = 0

    n = args.trials
    for _ in range(n):
        o = lottery.draw_lottery(rng, odds, league)
        for s, d in o.mapping.items():
            counts[s][d] += 1
        for d in o.draws:
            ladder_counts[d.slot] += 1
        # veterans must stay in their original relative order, every single time
        finals = [o.mapping[v] for v in vets]
        if finals != sorted(finals):
            order_violations += 1

    print()
    print("  observed minus exact, in standard errors (|z| > 5 would be alarming):")
    print()
    print("  %-10s" % "" + "".join("%9s" % ("-> %d" % d) for d in slots))
    max_z = 0.0
    for s in slots:
        cells = []
        for d in slots:
            p = exact[s][d]
            if p == 0.0:
                cells.append("       . ")
                continue
            se = math.sqrt(p * (1 - p) / n)
            z = (counts[s][d] / n - p) / se
            max_z = max(max_z, abs(z))
            cells.append("%+8.2f " % z)
        print("  %-8s%s" % (names[s][:8], "".join(cells)))
    print()
    check("Monte Carlo agrees with the exact enumeration", max_z < 5.0,
          "max |z| = %.2f" % max_z)
    check("returning managers never changed order, in any trial", order_violations == 0,
          "%d violations in %d trials" % (order_violations, n))

    # goodness of fit on the raw ladder itself
    total_draws = sum(ladder_counts.values())
    expected = {v: odds.landing[v] * total_draws for v in vets}
    expected[lottery.STAY] = odds.stay * total_draws
    chi2 = sum((ladder_counts[k] - e) ** 2 / e for k, e in expected.items())
    df = len(expected) - 1
    check("ladder rolls match their advertised odds (chi-square, df=%d)" % df,
          chi2 < CHI2_001[df],
          "chi2 = %.2f, critical value at p=0.001 is %.2f" % (chi2, CHI2_001[df]))

    # dice fairness
    dice_trials = min(n, 200_000)
    wins = 0
    for _ in range(dice_trials):
        a = lottery.assign_teams(rng, league.replacements, newcomers)
        if a.assigned[newcomers[0]] == league.replacements[0]:
            wins += 1
    p_hat = wins / dice_trials
    z = (p_hat - 0.5) / math.sqrt(0.25 / dice_trials)
    check("2d6 assignment is a coin flip", abs(z) < 5.0,
          "%s takes seat %d %.3f%% of the time (z = %+.2f)"
          % (league.replacements[0], newcomers[0], p_hat * 100, z))

    # ------------------------------------------------------------------
    section("RESULT")
    print()
    if failures:
        print("  %d CHECK(S) FAILED: %s" % (len(failures), "; ".join(failures)))
        return 1
    print("  All checks passed. The advertised numbers are the real numbers.")
    print()
    for v in vets:
        print("    %-8s keeps pick %d exactly %.0f%% of the time."
              % (names[v], v, targets[v] * 100))
    print()
    print("    No returning manager can ever move up, and they never pass each")
    print("    other. Only the two replacements can climb.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
