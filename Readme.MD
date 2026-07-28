# Constraint-Based Rebate Contract Designer

This project turns a customer-facing rebate grid into a prospective quarterly
contract that can be tested against commercial guardrails before it is offered.
The grid stays simple for the customer—growth milestones on one axis, volume
milestones on the other, and an earned rebate at the intersection—while the
engine behind it makes the assumptions, economics, eligibility, and risk visible.

> **Decision principle:** optimize and pilot a controlled contract, not a
> historical correlation. The response elasticities in this version are business
> scenarios; they are not presented as causal estimates.

The stakeholder proposal is available in
[`Rebate_Contract_Stakeholder_Proposal.pptx`](Rebate_Contract_Stakeholder_Proposal.pptx).

## What the project delivers

- A reusable contract and optimization core in `rebate_contract.py`.
- A Flask application with an optimizer and a hand-entered static calculator.
- A discrete, monotone 4×3 rate-grid optimizer with optional payout budgeting.
- Low/base/high response scenarios and a low-case downside guard.
- Cell population, revenue coverage, exclusions, migration, and constraint checks.
- A validation notebook that imports the shared engine instead of copying formulas.
- Automated tests for contract boundaries, reconciliation, optimization, and APIs.

## Why the original approaches were not reliable

The legacy files remain in the repository for comparison, but they are not the
production pricing path.

### `Brute_Force_Optimizer.ipynb`

The notebook draws only 50 random combinations, so it is random search rather
than brute force. More importantly, its objective is effectively:

```text
objective = current revenue - rebate payout
```

The model includes a cost for increasing the rebate but no benefit from customer
response. Therefore, the mathematically preferred answer is always the lowest
feasible rate. More samples would not repair that objective.

### `Optimized_Rebate_Simulator.py`

The legacy script uses one elasticity value for every segment and behaves like:

```text
projected revenue = Base × (1 + e × r)
net revenue       = Base × (1 + e × r) × (1 - r)
```

Differentiating the rate-dependent term gives an unconstrained optimum of:

```text
r* = (e - 1) / (2e)
```

At the script's default `e = 2.0`, `r* = 25%`. Because the configured cap is
15%, the optimizer is pushed toward that cap. The resulting 10%–15% staircase is
largely the consequence of the cap plus the one-point adjacency constraints, not
evidence that those rates are commercially correct.

### Observational “ML elasticity”

Historical rebate recipients were not randomly assigned. Their observed growth
can reflect account selection, seasonality, sales activity, customer mix, or
other confounding factors. The earlier prototype also transformed predictions in
a way that did not match its fitted linear model. It must not be used as a causal
contract-pricing model.

## Contract definition

The default contract is prospective and quarterly.

| Rule | Definition |
| --- | --- |
| Account | Composite key `(rfp_name, rfp_group)` |
| Baseline | Eligible revenue in the same quarter of the prior year |
| Growth | `(eligible quarterly revenue − baseline) / baseline` |
| Volume tier | Highest inclusive volume milestone achieved |
| Growth tier | Highest inclusive growth milestone achieved |
| Earned cell | Intersection of the two highest achieved milestones |
| Below a minimum | 0% rebate |
| New/nonpositive baseline | Excluded for a separate acquisition schedule |
| Default payout | Rate × positive revenue above baseline |

All eligible transactions are aggregated to the composite account before growth
or tier assignment. Milestones are inclusive: exactly $25,000 qualifies for a
$25,000 tier, and exactly 10% growth qualifies for a 10% row.

## Calculation walkthrough

For account \(i\), let:

- \(B_i\) = frozen prior-year same-quarter baseline;
- \(F_i\) = no-program quarterly forecast;
- \(e_{s,i}\) = response elasticity in scenario \(s\);
- \(r_i\) = rate from the account's assigned grid cell;
- \(P_{s,i}\) = projected revenue under the program;
- \(C_{s,i}\) = rebate payout; and
- \(N_{s,i}\) = net revenue after payout.

### 1. Qualification growth

```text
growth = (F - B) / B
```

Growth is defined only for a positive baseline. The account is assigned using
its no-program forecast so that the population remains fixed while rates are
optimized.

### 2. Projected response

```text
P = F × (1 + e × r)
```

This is a scenario calculation, not a causal claim. Low, base, and high
elasticities are supplied by the business and may be scalars or cell-specific
matrices.

### 3. Incremental-revenue payout (default)

```text
C = r × max(P - B, 0)
```

This limits threshold cliffs because the rate is paid only on revenue above the
frozen baseline.

For comparison, a retroactive all-revenue contract would calculate:

```text
C_all = r × P
```

That basis is supported for exposure analysis but is not the default.

### 4. Net revenue and uplift

```text
N      = P - C
uplift = N - F
```

### Worked example

Assume:

```text
Baseline B                = $100,000
No-program forecast F     = $120,000
Base elasticity e         = 1.5
Earned rate r             = 10%
```

Then:

```text
Qualification growth      = ($120,000 - $100,000) / $100,000 = 20%
Projected revenue P       = $120,000 × (1 + 1.5 × 10%)       = $138,000
Incremental payout C      = 10% × ($138,000 - $100,000)      =   $3,800
Net revenue N             = $138,000 - $3,800                = $134,200
Uplift vs. no program     = $134,200 - $120,000              =  $14,200
```

If the same 10% rate were paid on all revenue, payout would be $13,800 and net
revenue would be $124,200. This is why payout basis must be contractually explicit.

## How accounts are assigned to the grid

For each axis, the engine:

1. Sorts milestones in ascending order.
2. Treats each milestone as inclusive.
3. Selects the highest milestone less than or equal to the account result.
4. Assigns 0% when either axis is below its first milestone.
5. Uses the intersection of the two selected tiers as the paid cell.

Example: with growth rows `[6%, 10%, 15%, 20%]` and volume columns
`[$6,500, $25,000, $50,000]`, an account at exactly 15% growth and $31,000
volume earns the 15% / $25,000 cell.

## Threshold candidate design

The optimizer does not search unrestricted continuous thresholds. It compares a
small, auditable candidate set:

- the customer-facing example grid;
- the legacy project grid; and
- broad, balanced, and inclusive candidates derived from revenue and growth
  quantiles.

Generated volume thresholds are rounded to business-friendly $500 increments,
and growth thresholds are rounded to whole percentage points. A candidate is
rejected before rate optimization when any paid cell contains:

- fewer than 30 accounts; or
- less than 1% of eligible revenue.

This prevents a visually attractive grid from being supported by only a handful
of accounts. On the supplied data, the screenshot-style candidate is rejected:
several cells contain 25, 10, 14, 24, 6, or 18 accounts, below the default
minimum of 30.

## Rate optimization

For each accepted threshold candidate, account populations are fixed using the
no-program forecast. The optimizer then solves a one-hot mixed-integer model:

- each cell chooses exactly one allowed rate;
- rates are whole percentage points from 1% through 15% by default;
- every paid cell is at least one percentage point above its adjacent lower
  growth and lower volume cells;
- total payout respects the optional budget;
- low-scenario net revenue must be no worse than no-program net revenue; and
- the objective maximizes base-scenario net revenue.

After solving all feasible candidates, the engine selects the candidate with the
highest base-scenario net revenue.

## Post-optimization migration stress test

The optimization deliberately fixes account populations to avoid making rate
selection depend on self-induced tier crossings. After a grid is selected, the
engine reassigns accounts using the projected results until:

- tiers stabilize;
- a repeated state identifies a cycle; or
- the iteration limit is reached.

The grid is rejected if migration cycles, fails to stabilize, or changes net
revenue by more than the configured tolerance (5% by default). Both migrated
account share and financial impact are reported because many accounts can cross a
threshold while the economic result remains comparatively stable.

## Current default run: illustrative, not a rate recommendation

With the supplied dataset, default guardrails, incremental payout, no budget, and
scenario elasticities of 0.5 / 1.5 / 2.5, the deterministic example run selects:

```text
Candidate             auto_broad
Volume milestones     $2,000 / $5,500 / $13,000
Growth milestones     3% / 12% / 28% / 64%
Rates                 10%–15% monotone staircase
Eligible accounts     2,607
```

| Scenario | Projected revenue | Payout | Net revenue | Uplift vs. no program |
| --- | ---: | ---: | ---: | ---: |
| No program | $67,262,338 | $0 | $67,262,338 | $0 |
| Low | $69,102,588 | $997,763 | $68,104,826 | $842,487 |
| Base | $72,783,088 | $1,463,961 | $71,319,127 | $4,056,788 |
| High | $76,463,588 | $1,930,160 | $74,533,428 | $7,271,089 |

Important interpretation:

- No payout budget was supplied, so only the rate bounds limit exposure.
- The base/high response assumptions make larger rates attractive.
- Therefore, the 10%–15% solution is a scenario result to challenge and pilot,
  not a recommended customer offer.
- The migration test stabilized in four iterations. Although 76.68% of initially
  eligible accounts changed a tier, the modeled net-revenue impact was 0.42%,
  below the configured 5% threshold.

## Data reconciliation

The default run reconciles every supplied row:

| Classification | Count |
| --- | ---: |
| Source rows | 9,802 |
| Aggregated accounts | 9,802 |
| Invalid identifier rows | 0 |
| Invalid revenue rows | 0 |
| New or nonpositive baseline | 1,461 |
| Negative or invalid forecast | 19 |
| Below volume minimum | 2,350 |
| Below growth minimum | 3,365 |
| Eligible | 2,607 |

The five eligibility outcomes total 9,802. There is no silent record loss.

## Using the application

Install dependencies and start the Flask server:

```powershell
python -m pip install -r requirements.txt
python optimized_app.py
```

Open <http://127.0.0.1:5000>.

### Optimizer

The optimizer screen accepts:

- volume and growth milestones;
- low/base/high elasticities;
- payout basis;
- rate bounds, rate step, and minimum adjacency increase;
- minimum account and revenue coverage per cell;
- optional payout budget; and
- migration-impact tolerance.

It reports the selected contract, optimized grid, scenario economics, cell
coverage, candidate rejections, exclusions, migration diagnostics, and constraint
checks.

### Static calculator

The static calculator evaluates a user-entered grid against actual data without
optimizing its rates. Use it to validate a proposed contract, reproduce a
hand-calculated example, or compare incremental and all-revenue payout exposure.

## API walkthrough

### Optimize

`POST /optimize`

```json
{
  "volume_milestones": [6500, 25000, 50000],
  "growth_milestones": [0.06, 0.10, 0.15, 0.20],
  "payout_basis": "incremental",
  "min_rate": 0.01,
  "max_rate": 0.15,
  "rate_step": 0.01,
  "min_increment": 0.01,
  "min_accounts_per_cell": 30,
  "min_revenue_share_per_cell": 0.01,
  "budget": 1500000,
  "max_migration_net_impact": 0.05,
  "include_auto_candidates": true,
  "scenarios": {
    "low": 0.5,
    "base": 1.5,
    "high": 2.5
  }
}
```

The response contains `program`, `rates`, `scenarios`, `cell_counts`,
`cell_revenue`, `exclusion_counts`, `reconciliation`, `constraint_checks`,
`migration`, `candidate_assessments`, `warnings`, and contract wording.
Infeasible configurations return HTTP 400 with actionable rejection reasons.

### Evaluate a static grid

`POST /calculate_static`

Use the same contract fields plus a rate matrix whose shape matches the growth
rows and volume columns:

```json
{
  "volume_milestones": [6500, 25000, 50000],
  "growth_milestones": [0.06, 0.10, 0.15, 0.20],
  "payout_basis": "incremental",
  "rates": [
    [0.03, 0.04, 0.05],
    [0.05, 0.06, 0.07],
    [0.06, 0.08, 0.09],
    [0.09, 0.10, 0.11]
  ]
}
```

### Health and reconciliation

`GET /health` returns service status and source-row reconciliation.

## Validation

Run the automated suite:

```powershell
python -m unittest discover -s tests -v
```

The tests cover:

- exact-threshold inclusivity and highest-earned-cell behavior;
- incremental and all-revenue payout calculations;
- zero/negative baselines, new accounts, returns, and missing values;
- composite-account aggregation and complete reconciliation;
- rate bounds, discreteness, two-axis monotonicity, budget, and cell coverage;
- actionable infeasibility;
- mixed-integer optimality versus exhaustive enumeration on a small grid;
- deterministic full-data execution and scenario sensitivity;
- migration stability and API payload validation;
- static-calculator agreement with hand calculations; and
- regression demonstrations of the legacy objectives' degeneracy.

The notebook `Constraint_Based_Rebate_Walkthrough.ipynb` provides an interactive
validation walkthrough while calling the same production functions.

## Recommended stakeholder path

1. **Calibrate:** Finance and Commercial owners provide defensible low/base/high
   response scenarios, an incremental-payout ceiling, eligible product rules, and
   return/cancellation treatment.
2. **Simulate:** Compare candidate thresholds, coverage, payout exposure,
   low-case protection, and migration sensitivity.
3. **Pilot:** Use a limited customer cohort with a holdout or other credible
   counterfactual, pre-agreed success metrics, and monitoring.
4. **Re-estimate:** Replace assumed scenarios only when pilot evidence supports a
   better response model.
5. **Launch:** Publish rates and contract wording only after Finance, Legal, and
   Commercial approval.

## Project structure

- `rebate_contract.py` — shared contract, data, scenario, simulation, migration,
  and mixed-integer optimization engine.
- `optimized_app.py` — thin Flask API and application entry point.
- `templates/index.html`, `static/` — contract configuration and result diagnostics.
- `Constraint_Based_Rebate_Walkthrough.ipynb` — validation walkthrough using the
  shared engine.
- `tests/` — unit, optimization, regression, and API tests.
- `Rebate_Contract_Stakeholder_Proposal.pptx` — four-slide stakeholder proposal.
- `Optimized_Rebate_Simulator.py`, `ML_Rebate_Optimizer.py`, and
  `Brute_Force_Optimizer.ipynb` — legacy experiments retained for comparison only.

The untracked `CC/` directory is intentionally preserved and excluded from the
production implementation and release commit.
