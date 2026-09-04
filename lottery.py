"""Core probability model for the SPT fantasy draft-order lottery.

Pure standard library. Importing this module has no side effects and consumes
no randomness -- every stochastic function takes an explicit ``random.Random``
so that a run is fully reproducible from its seed.

The lottery
-----------
Slots 1-3 and 10 are locked. Of the remaining six:

  * slots 4-7 belong to returning managers (Brandon, Chris, Ben, Isaac),
  * slots 8-9 belong to the two replacement managers.

**Only the replacements can move up.** The returning four never climb, and
never change position relative to each other -- they only slide down when a
newcomer is inserted above them.

Each newcomer independently rolls once on the promotion ladder. A roll either
lands on one of the veteran slots 4-7, or leaves them in the bottom block.
Whoever is promoted is inserted at that slot; everyone from there down to the
newcomer's old seat shifts down exactly one. Veterans then fill whatever slots
are left, in their original order.

The ladder
----------
Let ``t_v`` be the advertised probability that the veteran in slot ``v`` keeps
it. That veteran holds exactly when *neither* newcomer reaches slot ``v`` or
better. The two rolls are independent, so if a single newcomer fails to reach
``v`` with probability ``s_v``, then

    t_v = s_v ** 2          =>      s_v = sqrt(t_v)

The square root is simply "two shots at it". One newcomer therefore reaches
slot ``v`` or better with probability ``1 - sqrt(t_v)``, and differencing that
cumulative gives the per-slot landing odds:

    g_v = sqrt(t_{v-1}) - sqrt(t_v)        (with t_3 defined as 1)
    P(stay in the bottom block) = sqrt(t_7)

No calibration, no fixed-point solving -- the advertised numbers are exact by
construction. Collisions (both newcomers rolling the same slot) are settled by
a coin flip, which cannot disturb any ``t_v``: see ``resolve_collision``.
"""

import hashlib
import json
from dataclasses import dataclass
from itertools import product
from math import sqrt
from pathlib import Path

__all__ = [
    "League", "PromotionOdds", "Draw", "LotteryOutcome", "Assignment",
    "load_league", "promotion_ladder", "draw_lottery", "place",
    "exact_distribution", "expected_slots",
    "roll_2d6", "assign_teams", "seed_from_text", "commit_hash",
]

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_LEAGUE = REPO_ROOT / "league.json"

STAY = None          # sentinel: this newcomer was not promoted


# --------------------------------------------------------------------------
# League configuration
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class League:
    name: str
    season: int
    standings: list          # list of dicts straight from league.json
    replacements: list       # ["Ryan", "Daniel"]
    slots: list              # every slot in play, ascending: [4..9]
    targets: dict            # {veteran slot: probability they keep it}

    @property
    def locked(self):
        return [r["slot"] for r in self.standings if r.get("locked")]

    def row(self, slot):
        for r in self.standings:
            if r["slot"] == slot:
                return r
        raise KeyError("no team at slot %s" % slot)

    @property
    def newcomer_seats(self):
        """Slots whose manager left, ascending. These get filled by dice."""
        return sorted(r["slot"] for r in self.standings if r.get("manager") is None)

    @property
    def veteran_seats(self):
        """Slots in play held by returning managers, ascending."""
        return [s for s in self.slots if s not in set(self.newcomer_seats)]


def load_league(path=DEFAULT_LEAGUE):
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    league = League(
        name=raw["league"],
        season=raw["season"],
        standings=raw["standings"],
        replacements=list(raw["replacement_managers"]),
        slots=sorted(raw["lottery_slots"]),
        targets={int(k): float(v) for k, v in raw["veteran_hold_targets"].items()},
    )
    _validate(league)
    return league


def _validate(league):
    slots = [r["slot"] for r in league.standings]
    if sorted(slots) != list(range(1, len(slots) + 1)):
        raise ValueError("standings slots must be 1..N with no gaps, got %s" % sorted(slots))
    if not set(league.slots) <= set(slots):
        raise ValueError("lottery slots must exist in the standings")
    stray = set(league.slots) & set(league.locked)
    if stray:
        raise ValueError("slots cannot be both locked and in the lottery: %s" % sorted(stray))
    if league.slots != list(range(min(league.slots), max(league.slots) + 1)):
        raise ValueError("lottery slots must be contiguous, got %s" % league.slots)

    vets, newcomers = league.veteran_seats, league.newcomer_seats
    if sorted(league.targets) != vets:
        raise ValueError("need one hold target per veteran slot %s, got %s"
                         % (vets, sorted(league.targets)))
    if newcomers != league.slots[len(vets):]:
        raise ValueError("the replacement managers must start in the bottom slots of the "
                         "lottery range; got %s inside %s" % (newcomers, league.slots))
    if len(newcomers) != len(league.replacements):
        raise ValueError("%d vacant slots but %d replacement managers"
                         % (len(newcomers), len(league.replacements)))
    for v in vets:
        if not 0.0 < league.targets[v] < 1.0:
            raise ValueError("target for slot %s must be strictly between 0 and 1" % v)
    for a, b in zip(vets, vets[1:]):
        if league.targets[a] <= league.targets[b]:
            raise ValueError(
                "hold targets must strictly decrease down the board, but slot %d (%.2f) "
                "is not above slot %d (%.2f)" % (a, league.targets[a], b, league.targets[b])
            )


# --------------------------------------------------------------------------
# The promotion ladder
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PromotionOdds:
    landing: dict        # {slot: probability ONE newcomer lands there}
    stay: float          # probability ONE newcomer is not promoted
    cutoffs: list        # [(upper bound on the roll, slot)], ascending

    def slot_for(self, roll):
        """Where a roll in [0, 1) lands. Returns STAY if it is not a promotion."""
        for bound, slot in self.cutoffs:
            if roll < bound:
                return slot
        return STAY


def promotion_ladder(targets):
    """Per-newcomer landing odds that make every advertised target exact.

    P(one newcomer does not reach slot v or better) = sqrt(t_v), so two
    independent newcomers both fail with probability t_v, which is precisely
    what slot v was promised.
    """
    slots = sorted(targets)
    landing, cutoffs = {}, []
    prev = 1.0
    for v in slots:
        t = targets[v]
        landing[v] = sqrt(prev) - sqrt(t)
        cutoffs.append((1.0 - sqrt(t), v))
        prev = t
    stay = sqrt(prev)

    total = sum(landing.values()) + stay
    if abs(total - 1.0) > 1e-12:
        raise RuntimeError("promotion ladder does not sum to 1 (got %.15f)" % total)
    if any(p < 0.0 for p in landing.values()):
        raise RuntimeError("negative landing probability; targets must strictly decrease")
    return PromotionOdds(landing=landing, stay=stay, cutoffs=cutoffs)


# --------------------------------------------------------------------------
# Turning draws into a board
# --------------------------------------------------------------------------

def resolve_collision(draws, newcomer_seats, winner_first):
    """Both newcomers rolled the same slot. One takes it, the other takes the
    slot immediately below. ``winner_first`` says whether the higher-seeded
    newcomer wins the flip.

    This cannot disturb any veteran's advertised rate. Slot v's target depends
    only on whether *some* newcomer reaches v or better; pushing the loser from
    m to m+1 leaves that unchanged for every v, because the winner is still
    sitting at m.
    """
    hi, lo = newcomer_seats
    m = draws[hi]
    winner, loser = (hi, lo) if winner_first else (lo, hi)
    return {winner: m, loser: m + 1}


def place(promotions, slots, veteran_seats, newcomer_seats):
    """Final slot for every manager in play.

    Promoted newcomers sit where they landed. Newcomers who were not promoted
    take the bottom-most remaining slots, keeping their relative order. The
    veterans then fill everything left over in their original order, which is
    what guarantees they never climb and never pass each other.
    """
    taken = dict(promotions)
    free = [s for s in slots if s not in set(taken.values())]

    unpromoted = [s for s in newcomer_seats if s not in taken]
    tail = free[len(free) - len(unpromoted):] if unpromoted else []
    for seat, slot in zip(unpromoted, tail):
        taken[seat] = slot

    remaining = [s for s in free if s not in set(tail)]
    for seat, slot in zip(veteran_seats, remaining):
        taken[seat] = slot

    if sorted(taken.values()) != list(slots):
        raise RuntimeError("placement did not produce a permutation: %s" % taken)
    return taken


# --------------------------------------------------------------------------
# The actual draw
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Draw:
    seat: int
    roll: float
    slot: object         # int slot, or STAY


@dataclass(frozen=True)
class LotteryOutcome:
    draws: list                    # list[Draw], in seat order
    promotions: dict               # seat -> slot, promoted newcomers only
    mapping: dict                  # seat -> final slot, everyone
    collision: tuple = None        # (slot, winning seat, flip roll) or None

    @property
    def moved(self):
        return sorted(s for s, d in self.mapping.items() if s != d)


def draw_lottery(rng, odds, league):
    """Run one lottery. Returns a LotteryOutcome; consumes rng deterministically."""
    newcomers = league.newcomer_seats

    draws = []
    for seat in newcomers:
        roll = rng.random()
        draws.append(Draw(seat=seat, roll=roll, slot=odds.slot_for(roll)))

    promotions = {d.seat: d.slot for d in draws if d.slot is not STAY}

    collision = None
    if len(promotions) == len(newcomers) == 2 and len(set(promotions.values())) == 1:
        flip = rng.random()
        promotions = resolve_collision(
            {d.seat: d.slot for d in draws}, newcomers, winner_first=flip < 0.5
        )
        winner = min(promotions, key=lambda s: promotions[s])
        collision = (draws[0].slot, winner, flip)

    mapping = place(promotions, league.slots, league.veteran_seats, newcomers)
    return LotteryOutcome(draws=draws, promotions=promotions, mapping=mapping, collision=collision)


# --------------------------------------------------------------------------
# Exact distribution -- exhaustive enumeration, not simulation
# --------------------------------------------------------------------------

def exact_distribution(odds, league):
    """The full seat -> final-slot probability matrix, computed exactly.

    Enumerates every pair of independent draws, splitting collisions into both
    coin-flip branches. That is 25 combinations plus 4 extra branches for this
    league -- small enough to sum exactly, so there is zero sampling error.
    """
    slots, vets, newcomers = league.slots, league.veteran_seats, league.newcomer_seats
    dist = {s: {d: 0.0 for d in slots} for s in slots}

    options = [(odds.landing[v], v) for v in sorted(odds.landing)] + [(odds.stay, STAY)]

    for (p_hi, slot_hi), (p_lo, slot_lo) in product(options, repeat=2):
        weight = p_hi * p_lo
        if weight == 0.0:
            continue
        draws = {newcomers[0]: slot_hi, newcomers[1]: slot_lo}
        promoted = {s: v for s, v in draws.items() if v is not STAY}

        if len(promoted) == 2 and slot_hi == slot_lo:
            branches = [(0.5, resolve_collision(draws, newcomers, True)),
                        (0.5, resolve_collision(draws, newcomers, False))]
        else:
            branches = [(1.0, promoted)]

        for share, promotions in branches:
            mapping = place(promotions, slots, vets, newcomers)
            for seat, slot in mapping.items():
                dist[seat][slot] += weight * share

    return dist


def expected_slots(dist):
    return {s: sum(d * p for d, p in row.items()) for s, row in dist.items()}


# --------------------------------------------------------------------------
# Dice: which replacement manager inherits which vacated team
# --------------------------------------------------------------------------

def roll_2d6(rng):
    a, b = rng.randint(1, 6), rng.randint(1, 6)
    return a, b, a + b


@dataclass(frozen=True)
class Assignment:
    rounds: list                      # list of {manager: (d1, d2, total)}, one per round
    assigned: dict                    # slot -> manager
    ties: int


def assign_teams(rng, managers, slots, max_rounds=1000):
    """Each manager rolls 2d6. Highest total takes the lowest-numbered (better)
    vacated slot, and so on down. Any tie forces a complete re-roll.
    """
    managers = list(managers)
    slots = sorted(slots)
    if len(managers) != len(slots):
        raise ValueError("need exactly one replacement manager per vacated slot")

    rounds = []
    for _ in range(max_rounds):
        this = {m: roll_2d6(rng) for m in managers}
        rounds.append(this)
        totals = [v[2] for v in this.values()]
        if len(set(totals)) == len(totals):
            ranked = sorted(managers, key=lambda m: this[m][2], reverse=True)
            return Assignment(rounds=rounds, assigned=dict(zip(slots, ranked)), ties=len(rounds) - 1)
    raise RuntimeError("dice refused to break the tie")  # pragma: no cover


# --------------------------------------------------------------------------
# Seeding and commit-reveal
# --------------------------------------------------------------------------

def commit_hash(text):
    """SHA-256 of the seed phrase, as hex. Publish this BEFORE the draft; reveal
    the phrase after. Anyone can then check the hash and replay the exact run,
    which proves the commissioner did not re-roll until they liked the result."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seed_from_text(text):
    """Deterministic 256-bit RNG seed from any string, so a seed can be
    published in advance (or derived from a public event) and checked later."""
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest(), "big")
