"""Run the SPT fantasy draft-order lottery once and narrate the result.

    python run_lottery.py                        # fresh random seed, printed for replay
    python run_lottery.py --seed "<phrase>"      # replay / use a pre-committed phrase
    python run_lottery.py --commit "<phrase>"    # print only the hash, run nothing

Every run is fully determined by its seed phrase, so anyone in the league can
reproduce it exactly. See the README for the commit-reveal scheme.
"""

import argparse
import json
import random
import secrets
import sys
from datetime import datetime

import lottery

RESULTS_DIR = lottery.REPO_ROOT / "results"
RULE = "=" * 74
THIN = "-" * 74


def emit(lines, text=""):
    print(text)
    lines.append(text)


def build_roster(league, assigned):
    """slot -> {team, manager, orphaned_from} with the vacated teams filled in."""
    roster = {}
    for row in league.standings:
        slot = row["slot"]
        roster[slot] = {
            "team": row["team"],
            "manager": row["manager"] or assigned[slot],
            "orphaned_from": row.get("vacated_by"),
            "locked": bool(row.get("locked")),
        }
    return roster


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the draft-order lottery.")
    ap.add_argument("--seed", help="seed phrase; anything at all. Omit for a fresh random one.")
    ap.add_argument("--commit", metavar="PHRASE",
                    help="print the SHA-256 of a seed phrase and exit, so you can post the "
                         "hash to the league before the draft and reveal the phrase after.")
    ap.add_argument("--league", default=str(lottery.DEFAULT_LEAGUE), help="path to league.json")
    ap.add_argument("--no-write", action="store_true", help="print only; do not write results/")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.commit:
        print("seed phrase committed. Post this hash to the league BEFORE the draft:")
        print()
        print("    SHA-256  %s" % lottery.commit_hash(args.commit))
        print()
        print("Keep the phrase secret until after the run, then reveal it. Anyone can")
        print("hash the revealed phrase, match it to the line above, and replay the draw.")
        return 0

    league = lottery.load_league(args.league)
    phrase = args.seed if args.seed is not None else secrets.token_hex(16)
    rng = random.Random(lottery.seed_from_text(phrase))

    odds = lottery.promotion_ladder(league.targets)
    dist = lottery.exact_distribution(odds, league)
    ev = lottery.expected_slots(dist)

    out = []
    now = datetime.now()

    emit(out, RULE)
    emit(out, "  %s %s -- DRAFT ORDER LOTTERY" % (league.name.upper(), league.season))
    emit(out, RULE)
    emit(out, "  seed phrase  %s" % phrase)
    emit(out, "  SHA-256      %s" % lottery.commit_hash(phrase))
    emit(out, "  run at       %s" % now.strftime("%Y-%m-%d %H:%M:%S"))
    emit(out, '  replay       python run_lottery.py --seed "%s"' % phrase)
    emit(out, RULE)
    emit(out)

    # ---------------- Stage 1: the dice ----------------
    emit(out, "STAGE 1 -- WHO INHERITS WHICH ORPHANED TEAM")
    emit(out, THIN)
    newcomers = league.newcomer_seats
    for slot in newcomers:
        row = league.row(slot)
        emit(out, "  seat %-2d  %-28s (orphaned by %s)" % (slot, row["team"], row["vacated_by"]))
    emit(out)
    emit(out, "  %s each roll 2d6. Eleven possible totals, 2 through 12."
         % " and ".join(league.replacements))
    emit(out, "  High total takes seat %d, low total takes seat %d. A tie means both re-roll."
         % (newcomers[0], newcomers[-1]))
    emit(out)

    assignment = lottery.assign_teams(rng, league.replacements, newcomers)
    for i, rnd in enumerate(assignment.rounds, start=1):
        tag = "Round %d" % i
        for mgr in league.replacements:
            d1, d2, tot = rnd[mgr]
            emit(out, "  %-9s %-8s rolls [%d][%d] = %2d" % (tag, mgr, d1, d2, tot))
            tag = ""
        if i <= assignment.ties:
            emit(out, "           tie. The dice demand a rematch.")
        emit(out)

    if assignment.ties:
        emit(out, "  %d tied round(s) before the dice committed to anything." % assignment.ties)
    for slot in newcomers:
        row = league.row(slot)
        emit(out, "  -> %-8s inherits %-28s (%s's), seat %d"
             % (assignment.assigned[slot], row["team"], row["vacated_by"], slot))
    emit(out)

    hi, lo = newcomers[0], newcomers[-1]
    emit(out, "  This one matters: seat %d is worth %.3f expected draft slots and seat %d is"
         % (hi, ev[hi], lo))
    emit(out, "  worth %.3f, so that roll was worth %.2f of a draft pick."
         % (ev[lo], abs(ev[hi] - ev[lo])))
    emit(out)

    roster = build_roster(league, assignment.assigned)

    # ---------------- Stage 2: the promotion rolls ----------------
    emit(out, "STAGE 2 -- THE PROMOTION ROLLS")
    emit(out, THIN)
    emit(out, "  Only %s can move. The four returning managers never climb and never"
         % " and ".join(league.replacements))
    emit(out, "  pass each other -- they only slide down if somebody is inserted above them.")
    emit(out)
    emit(out, "  Each newcomer rolls once in [0, 1), independently:")
    emit(out)
    for bound, slot in odds.cutoffs:
        emit(out, "      %-15s   ->   pick %d" % ("roll < %.6f" % bound, slot))
    emit(out, "      %-15s   ->   stay in the bottom block  (%.4f%%)"
         % ("otherwise", odds.stay * 100))
    emit(out)

    outcome = lottery.draw_lottery(rng, odds, league)
    emit(out, "  seat  manager    rolled     result")
    for d in outcome.draws:
        verdict = "no promotion" if d.slot is lottery.STAY else "PROMOTED to pick %d" % d.slot
        emit(out, "   %-4d %-10s %.6f   %s" % (d.seat, roster[d.seat]["manager"], d.roll, verdict))
    emit(out)

    if outcome.collision:
        slot, winner, flip = outcome.collision
        loser = [s for s in newcomers if s != winner][0]
        emit(out, "  COLLISION. Both rolled pick %d. Coin flip: %.6f -> %s takes it, %s"
             % (slot, flip, roster[winner]["manager"], roster[loser]["manager"]))
        emit(out, "  takes pick %d." % outcome.promotions[loser])
        emit(out)

    # ---------------- Stage 3: the board ----------------
    final = {}
    for slot, info in roster.items():
        final[outcome.mapping.get(slot, slot)] = dict(info, was=slot)

    emit(out, "STAGE 3 -- THE BOARD")
    emit(out, THIN)
    if not outcome.promotions:
        emit(out, "  Neither newcomer was promoted. The board is unchanged.")
        emit(out, "  This happens %.2f%% of the time." % (odds.stay ** 2 * 100))
    else:
        for seat in sorted(outcome.promotions, key=lambda s: outcome.promotions[s]):
            emit(out, "  %s is inserted at pick %d."
                 % (roster[seat]["manager"], outcome.promotions[seat]))
        slid = [(s, outcome.mapping[s]) for s in league.veteran_seats if outcome.mapping[s] != s]
        if slid:
            emit(out, "  Sliding down: %s."
                 % ", ".join("%s %d->%d" % (roster[s]["manager"], s, d) for s, d in slid))
        bumped = [s for s in newcomers if s not in outcome.promotions and outcome.mapping[s] != s]
        for s in bumped:
            emit(out, "  %s was not promoted and slides %d->%d."
                 % (roster[s]["manager"], s, outcome.mapping[s]))
    emit(out)

    emit(out, "FINAL %d DRAFT ORDER" % league.season)
    emit(out, THIN)
    emit(out, "  pick  team                          manager    was   move")
    for pick in sorted(final):
        info = final[pick]
        delta = info["was"] - pick
        if info["locked"]:
            move = "locked"
        elif delta == 0:
            move = "held"
        else:
            move = "UP %d" % delta if delta > 0 else "DOWN %d" % -delta
        emit(out, "   %-4d  %-28s  %-9s  %-4d  %s" % (pick, info["team"], info["manager"], info["was"], move))
    emit(out)
    emit(out, THIN)
    emit(out, "  Slots %s never entered the lottery. Only %s could move up, and"
         % (", ".join(str(s) for s in league.locked), " and ".join(league.replacements)))
    emit(out, "  the returning four kept their order from last season.")
    emit(out, "  Verify the odds:  python verify.py")
    emit(out, '  Replay this run:  python run_lottery.py --seed "%s"' % phrase)
    emit(out, RULE)

    if args.no_write:
        return 0

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    md_path = RESULTS_DIR / ("%s-draft-order.md" % stamp)
    json_path = RESULTS_DIR / ("%s-draft-order.json" % stamp)

    md_path.write_text(
        "# %s %s draft order\n\n"
        "Generated %s from seed phrase `%s`.\n\n"
        "```\n%s\n```\n" % (league.name, league.season, now.strftime("%Y-%m-%d %H:%M:%S"),
                            phrase, "\n".join(out)),
        encoding="utf-8",
    )
    json_path.write_text(json.dumps({
        "league": league.name,
        "season": league.season,
        "generated_at": now.isoformat(timespec="seconds"),
        "seed_phrase": phrase,
        "seed_sha256": lottery.commit_hash(phrase),
        "veteran_hold_targets": {str(k): v for k, v in league.targets.items()},
        "promotion_ladder": {
            "landing": {str(k): v for k, v in odds.landing.items()},
            "stay": odds.stay,
        },
        "dice": {
            "rounds": [{m: list(v) for m, v in rnd.items()} for rnd in assignment.rounds],
            "ties": assignment.ties,
            "assigned": {str(k): v for k, v in assignment.assigned.items()},
        },
        "promotion_rolls": [
            {"seat": d.seat, "roll": d.roll,
             "landed": (None if d.slot is lottery.STAY else d.slot)}
            for d in outcome.draws
        ],
        "collision": (None if not outcome.collision else {
            "slot": outcome.collision[0], "winner_seat": outcome.collision[1],
            "flip": outcome.collision[2],
        }),
        "promotions": {str(k): v for k, v in outcome.promotions.items()},
        "seat_to_slot": {str(k): v for k, v in outcome.mapping.items()},
        "final_order": [
            {"pick": p, "team": final[p]["team"], "manager": final[p]["manager"],
             "was": final[p]["was"], "locked": final[p]["locked"]}
            for p in sorted(final)
        ],
    }, indent=2), encoding="utf-8")

    print("wrote %s" % md_path.relative_to(lottery.REPO_ROOT))
    print("wrote %s" % json_path.relative_to(lottery.REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
