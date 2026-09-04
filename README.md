# SPT Fantasy 2026 — Draft Order Lottery

We dropped two managers and brought in two temporary replacements for the year. A straight reverse-snake of last season's standings doesn't work anymore: the newcomers would inherit a draft slot they didn't earn, and the returning managers who suuuuucked last year want their reward for sucking. 

So slots **1, 2, 3 and 10 are locked**, and slots **4 through 9 go into a weighted lottery**
where a better slot is harder to lose.

**Only the two new guys can move up.** Everybody who played last year keeps their earned
position relative to each other — they never climb, they never pass each other, and they
only slide down if a newcomer gets inserted above them.

This repo is how it was determined and includes a replayable seed. 

No dependencies. Standard library only, Python 3.14.

---



## The board


| Slot | Team                     | Manager                 | Status          |
| ---- | ------------------------ | ----------------------- | --------------- |
| 1    | Chinga Tu Madre          | Anthony                 | **locked**      |
| 2    | This Schmidt Hurts       | Kaleb                   | **locked**      |
| 3    | Jerriatric Jones         | Logan                   | **locked**      |
| 4    | Mongoose Mob             | Brandon                 | 90% hold        |
| 5    | Fry Town Baconites       | Chris                   | 80% hold        |
| 6    | Austin Doghouses         | Ben                     | 70% hold        |
| 7    | QKV-Softmax-Championship | Isaac                   | 60% hold        |
| 8    | Wrangling Cheesesticks   | *(Zach's — reassigned)* | new guy, can climb |
| 9    | Blue Bell Blitz          | *(Nate's — reassigned)* | new guy, can climb |
| 10   | Da Hood Futbol God       | Fernando                | **locked**      |


Top three picks are untouchable. Fernando is already sitting in his correct spot and doesn't
move either. Everything else is live.

---



## The rules



### Stage 1 — who inherits which orphaned team

Ryan and Daniel each roll **2d6** (eleven possible totals, 2 through 12). High total takes
**Wrangling Cheesesticks** at seat 8; low total takes **Blue Bell Blitz** at seat 9. A tie
means both re-roll from scratch. Every roll, including tied rounds, is printed.

This roll is worth about 0.6 of a draft pick — see [The dice matter](#the-dice-matter).

### Stage 2 — the promotion rolls

Ryan and Daniel each roll once in `[0, 1)`, independently of each other:


| Roll               | Result                   | Odds per newcomer |
| ------------------ | ------------------------ | ----------------- |
| `< 0.051317`       | pick 4                   | 5.1317%           |
| `< 0.105573`       | pick 5                   | 5.4256%           |
| `< 0.163340`       | pick 6                   | 5.7767%           |
| `< 0.225403`       | pick 7                   | 6.2063%           |
| otherwise          | stay in the bottom block | 77.4597%          |


If they both roll the same pick, a coin flip decides who takes it and the loser gets the
next pick down.

### Stage 3 — the board

Anyone promoted is inserted at their pick. Everyone from there down to that newcomer's old
seat shifts down exactly one. The returning four then fill whatever's left **in their
original order**, which is what guarantees they never climb and never pass each other.

---



## The math



Every advertised number is exact by construction. No solving, no fudging, one line of algebra.

### The square root

Brandon keeps pick 4 exactly when **neither** newcomer reaches pick 4. The two rolls are
independent, so if one newcomer misses with probability `s`, both miss with probability `s²`.
That has to equal the advertised 90%, so:

```
t_v = s_v²           =>       s_v = √t_v
```

The square root is just "two shots at it." Which means one newcomer reaches pick `v` or
better with probability `1 - √t_v`, and differencing that cumulative gives each rung of the
ladder:

```
g_v = √t_(v-1) − √t_v            (with t_3 defined as 1)
```


| Pick | Advertised `t_v` | One newcomer misses = `√t_v` | Squared        |
| ---- | ---------------- | ---------------------------- | -------------- |
| 4    | 90%              | 0.948683298                  | **0.900000000** |
| 5    | 80%              | 0.894427191                  | **0.800000000** |
| 6    | 70%              | 0.836660027                  | **0.700000000** |
| 7    | 60%              | 0.774596669                  | **0.600000000** |


Worst residual across all four: **1.1 × 10⁻¹⁶**. That's floating-point noise. The numbers are exact.

**This is why the thresholds in the ladder aren't round.** 5.13% isn't a number anybody
picked — it's `1 − √0.9`, forced by wanting pick 4 to hold at exactly 90%.

### Why the collision coin flip is free

If both newcomers roll the same pick, one takes it and the other drops one. That can't
disturb anybody's advertised rate: pick `v`'s number depends only on whether *somebody*
reached `v` or better, and the winner is still standing there either way. Pushing the loser
from `m` to `m+1` changes nothing about that.

It does matter for fairness *between* the two newcomers, though. The flip is what makes their
odds identical — each has exactly a **5.00%** shot at pick 4, not 5.13% and 4.87%.

### The full distribution

Computed by **exhaustive enumeration**, not simulation: all 25 pairs of rolls, with the 4
collision pairs split into both coin-flip branches, for 29 outcomes total. Zero sampling error.


|             | → 4         | → 5          | → 6          | → 7          | → 8          | → 9          | E[pick] |
| ----------- | ----------- | ------------ | ------------ | ------------ | ------------ | ------------ | ------- |
| **Brandon** | **90.0000%** | 9.1798%     | 0.8202%      | —            | —            | —            | 4.1082  |
| **Chris**   | —           | **80.0000%** | 17.6657%     | 2.3343%      | —            | —            | 5.2233  |
| **Ben**     | —           | —            | **70.0000%** | 25.3045%     | 4.6955%      | —            | 6.3470  |
| **Isaac**   | —           | —            | —            | **60.0000%** | 34.9193%     | 5.0807%      | 7.4508  |
| **seat 8**  | 5.0000%     | 5.4101%      | 5.7571%      | 6.1806%      | 60.1926%     | 17.4597%     | 7.6353  |
| **seat 9**  | 5.0000%     | 5.4101%      | 5.7571%      | 6.1806%      | 0.1926%      | 77.4597%     | 8.2353  |


Everything below the diagonal for the returning four is a **hard zero, not a small number**.
Brandon cannot finish above pick 4. Chris cannot finish above 5. That's the rule change, and
`verify.py` checks all 24 of those cells every run.

Other properties, all machine-checked:

1. **Every row sums to 1.** Everybody lands somewhere.
2. **Every column also sums to 1.** Every pick gets exactly one occupant.
3. **The two newcomers' rows are identical across picks 4–7.** Neither seat gets a better
   shot at a promotion than the other. That's the coin flip doing its job.
4. **The returning four never reorder.** Checked exhaustively over all 29 outcomes, and again
   over a million simulated runs.



### How often does nothing happen


|                                          |            |
| ---------------------------------------- | ---------- |
| Neither newcomer promoted, board unchanged | **60.00%** |
| Exactly one promoted                     | 34.92%     |
| Both promoted                            | 5.08%      |
| Both rolled the same pick, coin flip      | 1.28%      |


60% of the time this whole thing produces last year's order. That's not a bug — it's what
90/80/70/60 adds up to when only two people are allowed to move.

### The dice matter

Seat 8 is worth **7.6353** expected draft slots. Seat 9 is worth **8.2353**.

Both seats get an identical shot at every promotion, so the whole gap comes from what happens
when they *aren't* promoted: seat 8 keeps pick 8 unless the other guy jumps over him, while
seat 9 is already at the bottom. The 2d6 roll is worth about **0.6 of a draft pick.**

---



## Running it

```bash
python run_lottery.py
```

That draws a fresh random seed, prints the full narrated run, and writes a timestamped
Markdown + JSON pair into `results/`.

Replay any run — yours or someone else's — from its seed phrase:

```bash
python run_lottery.py --seed "february3rd1984"
```

Check every probability claim on this page:

```bash
python verify.py
```

Run the test suite:

```bash
python -m unittest discover -s tests -t . -v
```

On Windows with the bundled venv, substitute `.venv\Scripts\python.exe` for `python`.

---



## How you know it wasn't rigged



### The run is deterministic

Everything — both dice rolls, both promotion rolls, any coin flip — is driven by one
`random.Random` seeded from the SHA-256 of a text phrase. Same phrase, same draft order,
forever, on any machine. The phrase and its hash are printed at the top of every run and
stored in the results file.

### Commit-reveal

Reproducibility alone doesn't stop a commissioner from running the thing forty times and
publishing the one they liked. So:

```bash
python run_lottery.py --commit "some phrase only I know"
```

That prints **only** the SHA-256 hash and runs nothing. Post the hash to the league *before*  
the draft. Afterward, reveal the phrase. Anyone can hash it, match it against what was posted,  
re-run the lottery, and get the identical board. Publishing the hash in advance commits the  
commissioner to exactly one draw.

### Three independent checks of the math

`verify.py` proves the same numbers three separate ways, and they have to agree:

1. **Closed form** — the square-root algebra above, evaluated directly.
2. **Exhaustive enumeration** — all 29 outcomes summed exactly. Zero sampling error.
3. **Monte Carlo** — the actual shipped sampler run a million times, compared against leg 2
  in standard errors.

Legs 1 and 2 agreeing means the math is right. Leg 3 agreeing with them means the code
implements that math rather than something else. It also confirms the 2d6 assignment is a true
coin flip, runs a chi-square goodness-of-fit on the promotion ladder itself, and verifies that
the returning four never changed order across every single simulated run.

---



## Anticipated objections

**"So last year's standings barely matter?"**
They matter completely. 60% of the time the board is untouched, and the four returning
managers can *never* move up or pass each other. The only thing the lottery does is decide
where two new guys get slotted in.

**"Why can nobody get into the top 3?"** Because the top 3 are very special boys and we don't want to take that away. 

**"I dropped two spots and only one guy got promoted above me."**
Then both of them got promoted above you — that's the 5.08% case. Two insertions, two slides.

**"Why is the pick-4 threshold 5.13% when you said 90%?"**
Because 5.13% is `1 − √0.9`, per newcomer. Two of them roll, both have to miss, and
`0.948683² = 0.90` on the nose. See [The square root](#the-square-root).

**"The new guy landed on pick 4."**
5% each, 10% total. RIP

**"Just re-run it."**
No.

---



## Files


|                         |                                                                                   |
| ----------------------- | --------------------------------------------------------------------------------- |
| `league.json`           | Roster, locked slots, hold targets. All configuration lives here.                 |
| `lottery.py`            | The model: promotion ladder, the sampler, exact enumeration. No side effects on import. |
| `run_lottery.py`        | Runs one lottery and narrates it. Writes `results/`.                              |
| `verify.py`             | The three-legged proof.                                                           |
| `tests/test_lottery.py` | 55 tests.                                                                         |
| `results/`              | Timestamped Markdown + JSON for each run.                                         |
