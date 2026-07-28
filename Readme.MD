# Constraint-Based Rebate Contract Designer

This project designs a prospective quarterly rebate contract using explicit business
assumptions and enforceable grid constraints. It does **not** claim that historical
rebates caused the observed growth.

## Contract model

- Account identity: `(rfp_name, rfp_group)`.
- Baseline: eligible revenue from the same quarter in the prior year.
- Qualification: the highest inclusive volume and growth milestones achieved.
- Default payout: earned rate multiplied by incremental revenue above baseline.
- Below either minimum milestone: 0% rebate.
- New accounts or nonpositive baselines: excluded for a separate acquisition program.

The optimizer maximizes base-scenario net revenue while enforcing:

- rates from 1% through 15% in whole percentage points;
- at least a one-point increase between adjacent paid cells;
- at least 30 accounts and 1% of eligible revenue per cell;
- an optional total payout budget;
- low-scenario net revenue no worse than the no-program baseline; and
- a post-solve tier-migration financial-impact check.

Thresholds entered in the UI are assessed alongside a small set of rounded,
data-supported candidates. Rejected candidates remain visible with their reasons.

## Run

```powershell
python -m pip install -r requirements.txt
python optimized_app.py
```

Open <http://127.0.0.1:5000>.

## Verify

```powershell
python -m unittest discover -s tests -v
```

The suite covers contract boundaries, payout calculations, account aggregation,
exclusion reconciliation, constraint feasibility, MILP-versus-exhaustive optimality,
API validation, deterministic full-data execution, and the degeneracy of the legacy
objectives.

## Project structure

- `rebate_contract.py`: shared contract, data, scenario, simulation, and MILP engine.
- `optimized_app.py`: thin Flask API and application entry point.
- `templates/index.html`, `static/`: contract configuration and result diagnostics.
- `Constraint_Based_Rebate_Walkthrough.ipynb`: validation walkthrough that imports the
  shared engine instead of copying formulas.
- `Optimized_Rebate_Simulator.py`, `ML_Rebate_Optimizer.py`, and
  `Brute_Force_Optimizer.ipynb`: retained as legacy experiments for comparison only.

The untracked `CC/` directory is intentionally untouched.
