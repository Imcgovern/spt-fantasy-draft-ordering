"""Tests for the draft lottery.

Run from the repo root:

    python -m unittest discover -s tests -t . -v
"""

import os
import random
import sys
import unittest
from itertools import product
from math import sqrt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lottery  # noqa: E402
import run_lottery  # noqa: E402

STAY = lottery.STAY


class ScriptedRandom:
    """A stand-in for random.Random that hands back exactly what we queue up."""

    def __init__(self, randoms=(), randints=()):
        self.randoms = list(randoms)
        self.randints = list(randints)

    def random(self):
        return self.randoms.pop(0)

    def randint(self, a, b):
        v = self.randints.pop(0)
        assert a <= v <= b, "scripted randint %s outside [%s, %s]" % (v, a, b)
        return v


def all_outcomes(odds, league):
    """Every reachable (weight, promotions, mapping), collisions split in two."""
    vets, newcomers = league.veteran_seats, league.newcomer_seats
    options = [(odds.landing[v], v) for v in sorted(odds.landing)] + [(odds.stay, STAY)]
    out = []
    for (p_hi, s_hi), (p_lo, s_lo) in product(options, repeat=2):
        draws = {newcomers[0]: s_hi, newcomers[1]: s_lo}
        promoted = {s: v for s, v in draws.items() if v is not STAY}
        if len(promoted) == 2 and s_hi == s_lo:
            branches = [(0.5, lottery.resolve_collision(draws, newcomers, True)),
                        (0.5, lottery.resolve_collision(draws, newcomers, False))]
        else:
            branches = [(1.0, promoted)]
        for share, promos in branches:
            out.append((p_hi * p_lo * share, promos,
                        lottery.place(promos, league.slots, vets, newcomers)))
    return out


class LadderTests(unittest.TestCase):
    def setUp(self):
        self.league = lottery.load_league()
        self.odds = lottery.promotion_ladder(self.league.targets)

    def test_ladder_is_a_distribution(self):
        total = sum(self.odds.landing.values()) + self.odds.stay
        self.assertAlmostEqual(total, 1.0, places=15)

    def test_all_landing_odds_are_positive(self):
        for v, p in self.odds.landing.items():
            self.assertGreater(p, 0.0, "slot %d" % v)

    def test_the_square_root_identity(self):
        """P(one newcomer misses slot v or better) must be exactly sqrt(t_v)."""
        vets = self.league.veteran_seats
        for v in vets:
            miss = 1.0 - sum(self.odds.landing[u] for u in vets if u <= v)
            self.assertAlmostEqual(miss, sqrt(self.league.targets[v]), places=15)
            self.assertAlmostEqual(miss * miss, self.league.targets[v], places=15)

    def test_stay_probability_is_sqrt_of_the_last_target(self):
        last = self.league.veteran_seats[-1]
        self.assertAlmostEqual(self.odds.stay, sqrt(self.league.targets[last]), places=15)

    def test_cutoffs_are_ascending_and_match_the_landing_odds(self):
        bounds = [b for b, _ in self.odds.cutoffs]
        self.assertEqual(bounds, sorted(bounds))
        running = 0.0
        for bound, slot in self.odds.cutoffs:
            running += self.odds.landing[slot]
            self.assertAlmostEqual(bound, running, places=15)

    def test_ladder_is_deterministic(self):
        self.assertEqual(self.odds, lottery.promotion_ladder(self.league.targets))

    def test_rejects_targets_that_do_not_decrease(self):
        with self.assertRaises(RuntimeError):
            lottery.promotion_ladder({4: 0.5, 5: 0.9})


class SlotForTests(unittest.TestCase):
    def setUp(self):
        self.odds = lottery.promotion_ladder(lottery.load_league().targets)

    def test_roll_just_below_a_cutoff_lands_on_that_slot(self):
        for bound, slot in self.odds.cutoffs:
            self.assertEqual(self.odds.slot_for(bound - 1e-12), slot)

    def test_roll_exactly_on_a_cutoff_falls_through(self):
        """The comparison is strict `<`, which is what makes the odds exact."""
        cutoffs = self.odds.cutoffs
        for i, (bound, _) in enumerate(cutoffs):
            expected = cutoffs[i + 1][1] if i + 1 < len(cutoffs) else STAY
            self.assertEqual(self.odds.slot_for(bound), expected)

    def test_high_roll_is_no_promotion(self):
        self.assertIs(self.odds.slot_for(0.999999), STAY)

    def test_zero_roll_takes_the_best_pick(self):
        self.assertEqual(self.odds.slot_for(0.0), self.odds.cutoffs[0][1])


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.league = lottery.load_league()
        self.args = (self.league.slots, self.league.veteran_seats, self.league.newcomer_seats)

    def test_no_promotions_leaves_everything_alone(self):
        self.assertEqual(lottery.place({}, *self.args), {s: s for s in self.league.slots})

    def test_single_promotion_rotates_by_one(self):
        # seat 9 promoted to pick 5: 5,6,7,8 each slide down one
        self.assertEqual(lottery.place({9: 5}, *self.args),
                         {4: 4, 5: 6, 6: 7, 7: 8, 8: 9, 9: 5})
        # seat 8 promoted to pick 5: seat 9 is below the insertion, untouched
        self.assertEqual(lottery.place({8: 5}, *self.args),
                         {4: 4, 5: 6, 6: 7, 7: 8, 8: 5, 9: 9})

    def test_double_promotion(self):
        self.assertEqual(lottery.place({9: 5, 8: 7}, *self.args),
                         {4: 4, 5: 6, 6: 8, 7: 9, 8: 7, 9: 5})

    def test_promotion_to_the_top_pick(self):
        self.assertEqual(lottery.place({8: 4}, *self.args),
                         {4: 5, 5: 6, 6: 7, 7: 8, 8: 4, 9: 9})

    def test_every_reachable_placement_is_a_permutation(self):
        odds = lottery.promotion_ladder(self.league.targets)
        for _, _, mapping in all_outcomes(odds, self.league):
            self.assertEqual(sorted(mapping.values()), self.league.slots)

    def test_veterans_never_climb_and_never_pass_each_other(self):
        """The entire point of the rule. Checked over every reachable outcome."""
        odds = lottery.promotion_ladder(self.league.targets)
        vets = self.league.veteran_seats
        for _, promos, mapping in all_outcomes(odds, self.league):
            finals = [mapping[v] for v in vets]
            self.assertEqual(finals, sorted(finals),
                             "veterans reordered under promotions %s" % promos)
            for v in vets:
                self.assertGreaterEqual(mapping[v], v,
                                        "veteran %d climbed under %s" % (v, promos))

    def test_a_veteran_never_drops_more_than_the_number_of_promotions(self):
        odds = lottery.promotion_ladder(self.league.targets)
        for _, promos, mapping in all_outcomes(odds, self.league):
            for v in self.league.veteran_seats:
                self.assertLessEqual(mapping[v] - v, len(promos))


class CollisionTests(unittest.TestCase):
    def setUp(self):
        self.newcomers = lottery.load_league().newcomer_seats

    def test_winner_takes_the_pick_loser_takes_the_next_one(self):
        draws = {8: 6, 9: 6}
        self.assertEqual(lottery.resolve_collision(draws, self.newcomers, True), {8: 6, 9: 7})
        self.assertEqual(lottery.resolve_collision(draws, self.newcomers, False), {9: 6, 8: 7})

    def test_collision_is_settled_by_a_coin_flip(self):
        league = lottery.load_league()
        odds = lottery.promotion_ladder(league.targets)
        # both roll into the pick-6 band, then the flip decides
        band = odds.cutoffs[1][0] + 1e-9      # just past pick 5's bound -> pick 6
        for flip, expect_hi in ((0.25, 6), (0.75, 7)):
            rng = ScriptedRandom(randoms=[band, band, flip])
            o = lottery.draw_lottery(rng, odds, league)
            self.assertIsNotNone(o.collision)
            self.assertEqual(o.promotions[8], expect_hi)
            self.assertEqual(o.promotions[9], 13 - expect_hi)

    def test_no_collision_when_picks_differ(self):
        league = lottery.load_league()
        odds = lottery.promotion_ladder(league.targets)
        rng = ScriptedRandom(randoms=[0.0, odds.cutoffs[2][0] - 1e-9])
        o = lottery.draw_lottery(rng, odds, league)
        self.assertIsNone(o.collision)
        self.assertEqual(o.promotions, {8: 4, 9: 6})


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.league = lottery.load_league()
        self.odds = lottery.promotion_ladder(self.league.targets)
        self.dist = lottery.exact_distribution(self.odds, self.league)

    def test_hits_every_veteran_target_exactly(self):
        for v, t in self.league.targets.items():
            self.assertAlmostEqual(self.dist[v][v], t, places=13)

    def test_rows_sum_to_one(self):
        for s in self.league.slots:
            self.assertAlmostEqual(sum(self.dist[s].values()), 1.0, places=13)

    def test_columns_sum_to_one(self):
        for d in self.league.slots:
            self.assertAlmostEqual(sum(self.dist[s][d] for s in self.league.slots), 1.0, places=13)

    def test_veterans_have_zero_probability_of_climbing(self):
        for v in self.league.veteran_seats:
            for d in self.league.slots:
                if d < v:
                    self.assertEqual(self.dist[v][d], 0.0)

    def test_both_newcomers_have_identical_promotion_odds(self):
        hi, lo = self.league.newcomer_seats
        for v in self.league.veteran_seats:
            self.assertAlmostEqual(self.dist[hi][v], self.dist[lo][v], places=15)

    def test_newcomers_cannot_beat_the_top_lottery_pick(self):
        top = min(self.league.slots)
        for s in self.league.newcomer_seats:
            self.assertGreater(self.dist[s][top], 0.0)
            self.assertAlmostEqual(self.dist[s][top], 0.05, places=13)

    def test_the_better_seat_really_is_better(self):
        ev = lottery.expected_slots(self.dist)
        hi, lo = self.league.newcomer_seats
        self.assertLess(ev[hi], ev[lo])
        self.assertAlmostEqual(ev[lo] - ev[hi], 0.6, places=4)

    def test_board_is_unchanged_exactly_60_percent_of_the_time(self):
        self.assertAlmostEqual(self.odds.stay ** 2, 0.60, places=13)


class DrawTests(unittest.TestCase):
    def setUp(self):
        self.league = lottery.load_league()
        self.odds = lottery.promotion_ladder(self.league.targets)

    def test_no_promotions_when_both_roll_high(self):
        rng = ScriptedRandom(randoms=[0.99, 0.99])
        o = lottery.draw_lottery(rng, self.odds, self.league)
        self.assertEqual(o.promotions, {})
        self.assertEqual(o.mapping, {s: s for s in self.league.slots})
        self.assertEqual(o.moved, [])

    def test_single_promotion(self):
        rng = ScriptedRandom(randoms=[0.99, 0.0])
        o = lottery.draw_lottery(rng, self.odds, self.league)
        self.assertEqual(o.promotions, {9: 4})
        self.assertEqual(o.mapping[9], 4)
        self.assertEqual(o.mapping[8], 9)          # unpromoted newcomer slides down
        self.assertEqual([o.mapping[v] for v in self.league.veteran_seats], [5, 6, 7, 8])

    def test_draws_are_recorded_for_the_transcript(self):
        rng = ScriptedRandom(randoms=[0.99, 0.0])
        o = lottery.draw_lottery(rng, self.odds, self.league)
        self.assertEqual([d.seat for d in o.draws], self.league.newcomer_seats)
        self.assertIs(o.draws[0].slot, STAY)
        self.assertEqual(o.draws[1].slot, 4)
        self.assertEqual(o.draws[1].roll, 0.0)

    def test_always_a_permutation(self):
        rng = random.Random(lottery.seed_from_text("permutation"))
        for _ in range(5000):
            o = lottery.draw_lottery(rng, self.odds, self.league)
            self.assertEqual(sorted(o.mapping.values()), self.league.slots)

    def test_veterans_never_climb_over_many_draws(self):
        rng = random.Random(lottery.seed_from_text("noclimb"))
        for _ in range(5000):
            o = lottery.draw_lottery(rng, self.odds, self.league)
            finals = [o.mapping[v] for v in self.league.veteran_seats]
            self.assertEqual(finals, sorted(finals))
            for v in self.league.veteran_seats:
                self.assertGreaterEqual(o.mapping[v], v)

    def test_empirical_hold_rates_match_targets(self):
        """Fixed seed, so deterministic -- but it is still the real sampler."""
        rng = random.Random(lottery.seed_from_text("empirical"))
        trials = 150_000
        holds = {v: 0 for v in self.league.veteran_seats}
        for _ in range(trials):
            m = lottery.draw_lottery(rng, self.odds, self.league).mapping
            for v in holds:
                if m[v] == v:
                    holds[v] += 1
        for v, t in self.league.targets.items():
            self.assertAlmostEqual(holds[v] / trials, t, delta=0.01)


class DiceTests(unittest.TestCase):
    def setUp(self):
        self.league = lottery.load_league()

    def test_high_roll_takes_the_better_seat(self):
        rng = ScriptedRandom(randints=[1, 1, 6, 6])   # Ryan 2, Daniel 12
        a = lottery.assign_teams(rng, ["Ryan", "Daniel"], [8, 9])
        self.assertEqual(a.assigned, {8: "Daniel", 9: "Ryan"})
        self.assertEqual(a.ties, 0)

    def test_tie_forces_a_full_reroll(self):
        rng = ScriptedRandom(randints=[3, 3, 2, 4,      # both roll 6 -> tie
                                       1, 1, 6, 6])     # Ryan 2, Daniel 12
        a = lottery.assign_teams(rng, ["Ryan", "Daniel"], [8, 9])
        self.assertEqual(a.ties, 1)
        self.assertEqual(len(a.rounds), 2)
        self.assertEqual(a.assigned, {8: "Daniel", 9: "Ryan"})

    def test_2d6_totals_are_in_range(self):
        rng = random.Random(lottery.seed_from_text("dice"))
        totals = set()
        for _ in range(20000):
            d1, d2, tot = lottery.roll_2d6(rng)
            self.assertEqual(tot, d1 + d2)
            self.assertTrue(1 <= d1 <= 6 and 1 <= d2 <= 6)
            totals.add(tot)
        self.assertEqual(totals, set(range(2, 13)))   # all 11 possible totals

    def test_assignment_is_a_fair_coin(self):
        rng = random.Random(lottery.seed_from_text("fairness"))
        wins, trials = 0, 40000
        for _ in range(trials):
            a = lottery.assign_teams(rng, self.league.replacements, self.league.newcomer_seats)
            if a.assigned[8] == self.league.replacements[0]:
                wins += 1
        self.assertAlmostEqual(wins / trials, 0.5, delta=0.02)

    def test_manager_count_must_match_slot_count(self):
        with self.assertRaises(ValueError):
            lottery.assign_teams(random.Random(0), ["Ryan"], [8, 9])


class SeedTests(unittest.TestCase):
    def test_seed_is_stable_for_a_phrase(self):
        self.assertEqual(lottery.seed_from_text("boxcars"), lottery.seed_from_text("boxcars"))
        self.assertNotEqual(lottery.seed_from_text("boxcars"), lottery.seed_from_text("snake eyes"))

    def test_commit_hash_matches_sha256(self):
        self.assertEqual(
            lottery.commit_hash("boxcars"),
            "47e68d37db615e70766ce2c27e20f3fcb764c210244b49e5c71badd513590ba9",
        )

    def test_same_seed_reproduces_the_whole_run(self):
        league = lottery.load_league()
        odds = lottery.promotion_ladder(league.targets)

        def once():
            rng = random.Random(lottery.seed_from_text("replay me"))
            a = lottery.assign_teams(rng, league.replacements, league.newcomer_seats)
            o = lottery.draw_lottery(rng, odds, league)
            return a.assigned, o.mapping, [d.roll for d in o.draws]

        self.assertEqual(once(), once())

    def test_different_seeds_give_different_runs(self):
        league = lottery.load_league()
        odds = lottery.promotion_ladder(league.targets)
        seen = set()
        for phrase in "abcdefghijklmnop":
            rng = random.Random(lottery.seed_from_text(phrase))
            lottery.assign_teams(rng, league.replacements, league.newcomer_seats)
            seen.add(tuple(sorted(lottery.draw_lottery(rng, odds, league).mapping.items())))
        self.assertGreater(len(seen), 1)


class LeagueConfigTests(unittest.TestCase):
    def setUp(self):
        self.league = lottery.load_league()

    def test_loads_the_real_league(self):
        self.assertEqual(self.league.slots, [4, 5, 6, 7, 8, 9])
        self.assertEqual(self.league.veteran_seats, [4, 5, 6, 7])
        self.assertEqual(self.league.newcomer_seats, [8, 9])
        self.assertEqual(self.league.locked, [1, 2, 3, 10])
        self.assertEqual(self.league.replacements, ["Ryan", "Daniel"])

    def test_locked_and_lottery_slots_partition_the_board(self):
        self.assertEqual(sorted(self.league.locked + self.league.slots), list(range(1, 11)))

    def test_targets_cover_exactly_the_veteran_slots(self):
        self.assertEqual(sorted(self.league.targets), self.league.veteran_seats)

    def _mutate(self, **kw):
        base = dict(name=self.league.name, season=self.league.season,
                    standings=self.league.standings, replacements=self.league.replacements,
                    slots=self.league.slots, targets=self.league.targets)
        base.update(kw)
        return lottery.League(**base)

    def test_rejects_targets_that_do_not_strictly_decrease(self):
        with self.assertRaises(ValueError):
            lottery._validate(self._mutate(targets={4: 0.9, 5: 0.9, 6: 0.7, 7: 0.6}))

    def test_rejects_a_missing_target(self):
        with self.assertRaises(ValueError):
            lottery._validate(self._mutate(targets={4: 0.9, 5: 0.8, 6: 0.7}))

    def test_rejects_non_contiguous_lottery_slots(self):
        with self.assertRaises(ValueError):
            lottery._validate(self._mutate(slots=[4, 5, 7, 8, 9]))

    def test_rejects_a_locked_slot_inside_the_lottery(self):
        with self.assertRaises(ValueError):
            lottery._validate(self._mutate(slots=[1, 4, 5, 6, 7, 8, 9]))


class EndToEndTests(unittest.TestCase):
    def test_locked_slots_never_move_and_veterans_keep_their_order(self):
        league = lottery.load_league()
        odds = lottery.promotion_ladder(league.targets)
        expected_managers = sorted(["Anthony", "Kaleb", "Logan", "Brandon", "Chris",
                                    "Ben", "Isaac", "Ryan", "Daniel", "Fernando"])
        for i in range(400):
            rng = random.Random(lottery.seed_from_text("sweep-%d" % i))
            assignment = lottery.assign_teams(rng, league.replacements, league.newcomer_seats)
            outcome = lottery.draw_lottery(rng, odds, league)
            roster = run_lottery.build_roster(league, assignment.assigned)

            final = {}
            for slot, info in roster.items():
                final[outcome.mapping.get(slot, slot)] = dict(info, was=slot)

            self.assertEqual(sorted(final), list(range(1, 11)))
            for slot in league.locked:
                self.assertEqual(final[slot]["was"], slot, "locked slot %d moved" % slot)
            self.assertEqual(sorted(x["manager"] for x in final.values()), expected_managers)

            picks = {final[p]["manager"]: p for p in final}
            self.assertLess(picks["Brandon"], picks["Chris"])
            self.assertLess(picks["Chris"], picks["Ben"])
            self.assertLess(picks["Ben"], picks["Isaac"])
            for name, start in (("Brandon", 4), ("Chris", 5), ("Ben", 6), ("Isaac", 7)):
                self.assertGreaterEqual(picks[name], start, "%s moved up" % name)

    def test_cli_runs_and_is_reproducible(self):
        import io
        import contextlib

        def capture():
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run_lottery.main(["--seed", "cli-test", "--no-write"])
            return rc, buf.getvalue()

        rc, first = capture()
        self.assertEqual(rc, 0)
        self.assertIn("FINAL 2026 DRAFT ORDER", first)
        self.assertIn("STAGE 2 -- THE PROMOTION ROLLS", first)
        _, second = capture()
        drop = lambda s: "\n".join(l for l in s.splitlines() if "run at" not in l)
        self.assertEqual(drop(first), drop(second))

    def test_cli_narrates_a_collision(self):
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_lottery.main(["--seed", "demo-45", "--no-write"])
        self.assertIn("COLLISION", buf.getvalue())

    def test_commit_mode_prints_a_hash_and_runs_nothing(self):
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run_lottery.main(["--commit", "boxcars"])
        self.assertEqual(rc, 0)
        self.assertIn("47e68d37db615e70766ce2c27e20f3fcb764c210244b49e5c71badd513590ba9",
                      buf.getvalue())
        self.assertNotIn("FINAL", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
