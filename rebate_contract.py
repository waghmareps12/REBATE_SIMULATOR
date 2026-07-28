"""Constraint-based rebate contract design and optimization.

The module deliberately separates:
1. account-period preparation,
2. published contract rules,
3. business-supplied response scenarios, and
4. the discrete grid optimizer.

No causal response is learned from the observational rebate column.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from itertools import product
from pathlib import Path
from typing import Iterable, Literal, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix


PayoutBasis = Literal["incremental", "all_revenue"]


@dataclass(frozen=True)
class ProgramConfig:
    """Published contract rules for one candidate grid."""

    name: str
    volume_milestones: tuple[float, ...]
    growth_milestones: tuple[float, ...]
    period: str = "quarterly"
    baseline_rule: str = "same_quarter_prior_year"
    payout_basis: PayoutBasis = "incremental"
    min_rate: float = 0.01
    max_rate: float = 0.15
    rate_step: float = 0.01
    min_increment: float = 0.01
    min_accounts_per_cell: int = 30
    min_revenue_share_per_cell: float = 0.01
    budget: float | None = None
    max_migration_net_impact: float = 0.05

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.growth_milestones), len(self.volume_milestones)

    @property
    def allowed_rates(self) -> np.ndarray:
        count = int(round((self.max_rate - self.min_rate) / self.rate_step))
        return np.round(self.min_rate + np.arange(count + 1) * self.rate_step, 10)

    def validate(self) -> None:
        if len(self.volume_milestones) < 2 or len(self.growth_milestones) < 2:
            raise ValueError("At least two volume and growth milestones are required.")
        for label, values in (
            ("volume", self.volume_milestones),
            ("growth", self.growth_milestones),
        ):
            arr = np.asarray(values, dtype=float)
            if not np.all(np.isfinite(arr)) or not np.all(np.diff(arr) > 0):
                raise ValueError(f"{label.title()} milestones must be finite and strictly increasing.")
        if self.min_rate < 0 or self.max_rate <= self.min_rate:
            raise ValueError("Rate bounds must satisfy 0 <= min_rate < max_rate.")
        if self.rate_step <= 0 or self.min_increment < 0:
            raise ValueError("Rate step must be positive and minimum increment cannot be negative.")
        rate_intervals = (self.max_rate - self.min_rate) / self.rate_step
        if not np.isclose(rate_intervals, round(rate_intervals)):
            raise ValueError("Rate bounds must be exactly divisible by the rate step.")
        if not np.isclose(self.min_increment / self.rate_step, round(self.min_increment / self.rate_step)):
            raise ValueError("Minimum increment must be a whole multiple of the rate step.")
        longest_path = (len(self.volume_milestones) - 1) + (
            len(self.growth_milestones) - 1
        )
        if longest_path * self.min_increment > self.max_rate - self.min_rate + 1e-10:
            raise ValueError(
                "Rate bounds cannot support the required increments across this grid."
            )
        if self.min_accounts_per_cell < 1:
            raise ValueError("Minimum accounts per cell must be at least 1.")
        if not 0 <= self.min_revenue_share_per_cell <= 1:
            raise ValueError("Minimum revenue share must be between 0 and 1.")
        if self.payout_basis not in ("incremental", "all_revenue"):
            raise ValueError("Payout basis must be 'incremental' or 'all_revenue'.")
        if self.budget is not None and self.budget < 0:
            raise ValueError("Budget cannot be negative.")
        if self.max_migration_net_impact < 0 or self.max_migration_net_impact > 1:
            raise ValueError("Maximum migration net impact must be between 0 and 1.")


@dataclass(frozen=True)
class ScenarioSet:
    """Low/base/high segment elasticities supplied by the business."""

    low: float | Sequence[Sequence[float]] = 0.5
    base: float | Sequence[Sequence[float]] = 1.5
    high: float | Sequence[Sequence[float]] = 2.5

    def matrices(self, shape: tuple[int, int]) -> dict[str, np.ndarray]:
        result = {}
        for name in ("low", "base", "high"):
            value = getattr(self, name)
            arr = np.asarray(value, dtype=float)
            if arr.ndim == 0:
                arr = np.full(shape, float(arr))
            if arr.shape != shape:
                raise ValueError(f"{name.title()} elasticity must be a scalar or have shape {shape}.")
            if not np.all(np.isfinite(arr)) or np.any(arr < 0):
                raise ValueError(f"{name.title()} elasticity values must be finite and non-negative.")
            result[name] = arr
        if np.any(result["low"] > result["base"]) or np.any(result["base"] > result["high"]):
            raise ValueError("Elasticities must satisfy low <= base <= high in every cell.")
        return result


@dataclass
class AccountPeriodData:
    """Validated account-period records and source reconciliation."""

    accounts: pd.DataFrame
    source_rows: int
    invalid_identifier_rows: int
    invalid_revenue_rows: int

    @classmethod
    def from_csv(cls, path: str | Path) -> "AccountPeriodData":
        return cls.from_frame(pd.read_csv(path))

    @classmethod
    def from_frame(cls, source: pd.DataFrame) -> "AccountPeriodData":
        required = {"rfp_name", "rfp_group", "prevyr_rev", "curryr_rev"}
        missing = sorted(required - set(source.columns))
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

        frame = source.copy()
        invalid_ids = frame[["rfp_name", "rfp_group"]].isna().any(axis=1)
        frame["baseline_revenue"] = pd.to_numeric(frame["prevyr_rev"], errors="coerce")
        frame["forecast_revenue"] = pd.to_numeric(frame["curryr_rev"], errors="coerce")
        invalid_revenue = frame[["baseline_revenue", "forecast_revenue"]].isna().any(axis=1)

        valid = frame.loc[~invalid_ids & ~invalid_revenue].copy()
        accounts = (
            valid.groupby(["rfp_name", "rfp_group"], as_index=False, dropna=False)[
                ["baseline_revenue", "forecast_revenue"]
            ]
            .sum()
            .reset_index(drop=True)
        )
        accounts["growth"] = np.full(len(accounts), np.nan)
        positive_baseline = accounts["baseline_revenue"] > 0
        accounts.loc[positive_baseline, "growth"] = (
            accounts.loc[positive_baseline, "forecast_revenue"]
            - accounts.loc[positive_baseline, "baseline_revenue"]
        ) / accounts.loc[positive_baseline, "baseline_revenue"]
        return cls(
            accounts=accounts,
            source_rows=len(frame),
            invalid_identifier_rows=int(invalid_ids.sum()),
            invalid_revenue_rows=int((invalid_revenue & ~invalid_ids).sum()),
        )

    def reconciliation(self) -> dict[str, int]:
        return {
            "source_rows": self.source_rows,
            "aggregated_accounts": len(self.accounts),
            "invalid_identifier_rows": self.invalid_identifier_rows,
            "invalid_revenue_rows": self.invalid_revenue_rows,
        }


@dataclass
class CandidateAssessment:
    name: str
    accepted: bool
    reasons: list[str]
    cell_counts: list[list[int]]
    cell_revenue: list[list[float]]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OptimizationResult:
    config: ProgramConfig
    rates: np.ndarray
    scenarios: dict[str, dict[str, float]]
    cell_counts: np.ndarray
    cell_revenue: np.ndarray
    exclusion_counts: dict[str, int]
    reconciliation: dict[str, int]
    constraint_checks: dict[str, bool]
    migration: dict[str, float | bool | str]
    candidate_assessments: list[CandidateAssessment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "program": {
                **asdict(self.config),
                "volume_milestones": list(self.config.volume_milestones),
                "growth_milestones": list(self.config.growth_milestones),
            },
            "rates": self.rates.tolist(),
            "scenarios": self.scenarios,
            "cell_counts": self.cell_counts.astype(int).tolist(),
            "cell_revenue": self.cell_revenue.tolist(),
            "exclusion_counts": self.exclusion_counts,
            "reconciliation": self.reconciliation,
            "constraint_checks": self.constraint_checks,
            "migration": self.migration,
            "candidate_assessments": [item.to_dict() for item in self.candidate_assessments],
            "warnings": self.warnings,
            "contract": contract_language(self.config),
        }


def contract_language(config: ProgramConfig) -> list[str]:
    basis = (
        "incremental eligible revenue above the frozen baseline"
        if config.payout_basis == "incremental"
        else "all eligible quarterly revenue"
    )
    return [
        "Measurement period: calendar quarter.",
        "Baseline: the same eligible account revenue from the corresponding prior-year quarter.",
        "The highest volume and growth milestones achieved determine the earned rebate cell.",
        "Accounts below either minimum milestone earn 0%. Exact thresholds are inclusive.",
        f"The earned rate applies to {basis}.",
        "Accounts with a zero or negative baseline are handled outside this renewal grid.",
    ]


def evaluate_actual_grid(
    data: AccountPeriodData,
    config: ProgramConfig,
    rates: Sequence[Sequence[float]],
) -> dict[str, float | dict[str, int]]:
    """Apply a published grid to observed account-period results."""

    rate_grid = np.asarray(rates, dtype=float)
    if rate_grid.shape != config.shape:
        raise ValueError(f"Rate grid must have shape {config.shape}.")
    if not np.all(np.isfinite(rate_grid)) or np.any(rate_grid < 0):
        raise ValueError("Rate grid values must be finite and non-negative.")

    accounts = data.accounts
    vi, gi, eligible, exclusions = assign_cells(accounts, config)
    applied_rates = np.zeros(len(accounts))
    applied_rates[eligible] = rate_grid[gi[eligible], vi[eligible]]
    actual = accounts["forecast_revenue"].clip(lower=0).to_numpy(dtype=float)
    baseline = accounts["baseline_revenue"].to_numpy(dtype=float)
    payout_base = (
        np.maximum(actual - baseline, 0.0)
        if config.payout_basis == "incremental"
        else actual
    )
    payouts = applied_rates * payout_base
    eligible_revenue = float(actual[eligible].sum())
    return {
        "total_revenue": float(actual.sum()),
        "eligible_revenue": eligible_revenue,
        "total_payout": float(payouts.sum()),
        "effective_rate": float(
            payouts.sum() / eligible_revenue if eligible_revenue else 0.0
        ),
        "eligible_accounts": int(eligible.sum()),
        "exclusion_counts": exclusions,
    }


def _round_strict(values: Iterable[float], step: float) -> tuple[float, ...]:
    rounded: list[float] = []
    for value in values:
        candidate = round(float(value) / step) * step
        if rounded and candidate <= rounded[-1]:
            candidate = rounded[-1] + step
        rounded.append(round(candidate, 10))
    return tuple(rounded)


def generate_threshold_candidates(
    data: AccountPeriodData,
    template: ProgramConfig,
) -> list[ProgramConfig]:
    """Create a small, deterministic set of rounded, interpretable candidates."""

    usable = data.accounts[
        (data.accounts["baseline_revenue"] > 0)
        & (data.accounts["forecast_revenue"] >= 0)
        & np.isfinite(data.accounts["growth"])
        & (data.accounts["growth"] >= 0)
    ]
    if usable.empty:
        return []

    n_volume = len(template.volume_milestones)
    n_growth = len(template.growth_milestones)
    if (n_volume, n_growth) == (3, 4):
        profiles = [
            ("auto_broad", (0.20, 0.50, 0.80), (0.10, 0.30, 0.55, 0.80)),
            ("auto_balanced", (0.35, 0.65, 0.85), (0.20, 0.40, 0.60, 0.80)),
            ("auto_inclusive", (0.10, 0.35, 0.65), (0.05, 0.20, 0.45, 0.75)),
        ]
    else:
        profiles = [
            (
                "auto_balanced",
                tuple(np.linspace(0.15, 0.85, n_volume)),
                tuple(np.linspace(0.10, 0.85, n_growth)),
            )
        ]

    candidates = []
    clipped_growth = usable["growth"].clip(upper=2.0)
    for name, volume_quantiles, growth_quantiles in profiles:
        volumes = _round_strict(
            usable["forecast_revenue"].quantile(list(volume_quantiles)).to_numpy(),
            500.0,
        )
        growth = _round_strict(
            clipped_growth.quantile(list(growth_quantiles)).to_numpy(),
            0.01,
        )
        candidates.append(
            replace(
                template,
                name=name,
                volume_milestones=volumes,
                growth_milestones=growth,
            )
        )
    return candidates


def assign_cells(
    accounts: pd.DataFrame,
    config: ProgramConfig,
    revenue_column: str = "forecast_revenue",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, int]]:
    """Assign the highest attained inclusive milestone on each axis."""

    baseline = accounts["baseline_revenue"].to_numpy(dtype=float)
    revenue = accounts[revenue_column].to_numpy(dtype=float)
    growth = np.full(len(accounts), np.nan)
    np.divide(
        revenue - baseline,
        baseline,
        out=growth,
        where=baseline > 0,
    )
    volume_idx = np.searchsorted(config.volume_milestones, revenue, side="right") - 1
    growth_idx = np.searchsorted(config.growth_milestones, growth, side="right") - 1

    valid_baseline = np.isfinite(baseline) & (baseline > 0)
    valid_forecast = np.isfinite(revenue) & (revenue >= 0)
    eligible = valid_baseline & valid_forecast & (volume_idx >= 0) & (growth_idx >= 0)

    exclusions = {
        "new_or_nonpositive_baseline": int((~valid_baseline).sum()),
        "negative_or_invalid_forecast": int((valid_baseline & ~valid_forecast).sum()),
        "below_volume_milestone": int(
            (valid_baseline & valid_forecast & (volume_idx < 0)).sum()
        ),
        "below_growth_milestone": int(
            (valid_baseline & valid_forecast & (volume_idx >= 0) & (growth_idx < 0)).sum()
        ),
        "eligible": int(eligible.sum()),
    }
    return volume_idx, growth_idx, eligible, exclusions


def assess_candidate(data: AccountPeriodData, config: ProgramConfig) -> CandidateAssessment:
    config.validate()
    accounts = data.accounts
    vi, gi, eligible, _ = assign_cells(accounts, config)
    rows, cols = config.shape
    counts = np.zeros((rows, cols), dtype=int)
    revenue = np.zeros((rows, cols), dtype=float)
    forecast = accounts["forecast_revenue"].to_numpy(dtype=float)
    for g, v in product(range(rows), range(cols)):
        mask = eligible & (gi == g) & (vi == v)
        counts[g, v] = int(mask.sum())
        revenue[g, v] = float(forecast[mask].sum())

    reasons: list[str] = []
    total_eligible_revenue = revenue.sum()
    for g, v in product(range(rows), range(cols)):
        if counts[g, v] < config.min_accounts_per_cell:
            reasons.append(
                f"Growth row {g + 1}, volume column {v + 1} has "
                f"{counts[g, v]} accounts; minimum is {config.min_accounts_per_cell}."
            )
        share = revenue[g, v] / total_eligible_revenue if total_eligible_revenue else 0
        if share < config.min_revenue_share_per_cell:
            reasons.append(
                f"Growth row {g + 1}, volume column {v + 1} has "
                f"{share:.2%} of eligible revenue; minimum is "
                f"{config.min_revenue_share_per_cell:.2%}."
            )
    return CandidateAssessment(
        name=config.name,
        accepted=not reasons,
        reasons=reasons,
        cell_counts=counts.tolist(),
        cell_revenue=revenue.tolist(),
    )


def _payout(
    projected: np.ndarray,
    baseline: np.ndarray,
    rate: float,
    basis: PayoutBasis,
) -> np.ndarray:
    if basis == "incremental":
        return rate * np.maximum(projected - baseline, 0.0)
    return rate * projected


def _cell_options(
    accounts: pd.DataFrame,
    config: ProgramConfig,
    scenarios: ScenarioSet,
    vi: np.ndarray,
    gi: np.ndarray,
    eligible: np.ndarray,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], np.ndarray, np.ndarray]:
    rows, cols = config.shape
    rates = config.allowed_rates
    elasticities = scenarios.matrices(config.shape)
    option_net = {
        name: np.zeros((rows, cols, len(rates))) for name in elasticities
    }
    option_payout = {
        name: np.zeros((rows, cols, len(rates))) for name in elasticities
    }
    counts = np.zeros((rows, cols), dtype=int)
    cell_revenue = np.zeros((rows, cols), dtype=float)

    forecast = accounts["forecast_revenue"].to_numpy(dtype=float)
    baseline = accounts["baseline_revenue"].to_numpy(dtype=float)
    for g, v in product(range(rows), range(cols)):
        mask = eligible & (gi == g) & (vi == v)
        cell_forecast = forecast[mask]
        cell_baseline = baseline[mask]
        counts[g, v] = int(mask.sum())
        cell_revenue[g, v] = float(cell_forecast.sum())
        for scenario_name, elasticity in elasticities.items():
            for rate_index, rate in enumerate(rates):
                projected = cell_forecast * (1 + elasticity[g, v] * rate)
                payout = _payout(projected, cell_baseline, rate, config.payout_basis)
                option_payout[scenario_name][g, v, rate_index] = payout.sum()
                option_net[scenario_name][g, v, rate_index] = (
                    projected - payout
                ).sum()
    return option_net, option_payout, counts, cell_revenue


def _solve_rates(
    data: AccountPeriodData,
    config: ProgramConfig,
    scenarios: ScenarioSet,
) -> tuple[np.ndarray, dict[str, dict[str, float]], np.ndarray, np.ndarray, dict[str, int]]:
    accounts = data.accounts
    vi, gi, eligible, exclusions = assign_cells(accounts, config)
    option_net, option_payout, counts, cell_revenue = _cell_options(
        accounts, config, scenarios, vi, gi, eligible
    )
    rows, cols = config.shape
    rates = config.allowed_rates
    choices = len(rates)
    cells = rows * cols
    variables = cells * choices

    def var_index(g: int, v: int, k: int) -> int:
        return ((g * cols) + v) * choices + k

    constraints: list[tuple[dict[int, float], float, float]] = []
    for g, v in product(range(rows), range(cols)):
        constraints.append(
            ({var_index(g, v, k): 1.0 for k in range(choices)}, 1.0, 1.0)
        )

    for g in range(rows):
        for v in range(cols - 1):
            coeff: dict[int, float] = {}
            for k, rate in enumerate(rates):
                coeff[var_index(g, v + 1, k)] = rate
                coeff[var_index(g, v, k)] = -rate
            constraints.append((coeff, config.min_increment, np.inf))
    for g in range(rows - 1):
        for v in range(cols):
            coeff = {}
            for k, rate in enumerate(rates):
                coeff[var_index(g + 1, v, k)] = rate
                coeff[var_index(g, v, k)] = -rate
            constraints.append((coeff, config.min_increment, np.inf))

    if config.budget is not None:
        coeff = {}
        for g, v, k in product(range(rows), range(cols), range(choices)):
            coeff[var_index(g, v, k)] = option_payout["base"][g, v, k]
        constraints.append((coeff, -np.inf, config.budget))

    fixed_forecast = float(
        accounts.loc[~eligible & (accounts["forecast_revenue"] >= 0), "forecast_revenue"].sum()
    )
    no_program = float(accounts["forecast_revenue"].clip(lower=0).sum())
    low_required_from_cells = no_program - fixed_forecast
    low_coeff = {}
    for g, v, k in product(range(rows), range(cols), range(choices)):
        low_coeff[var_index(g, v, k)] = option_net["low"][g, v, k]
    constraints.append((low_coeff, low_required_from_cells, np.inf))

    matrix = lil_matrix((len(constraints), variables), dtype=float)
    lower = np.empty(len(constraints))
    upper = np.empty(len(constraints))
    for row_index, (coefficients, lb, ub) in enumerate(constraints):
        for column, coefficient in coefficients.items():
            matrix[row_index, column] = coefficient
        lower[row_index] = lb
        upper[row_index] = ub

    objective = np.zeros(variables)
    for g, v, k in product(range(rows), range(cols), range(choices)):
        objective[var_index(g, v, k)] = -option_net["base"][g, v, k]

    result = milp(
        c=objective,
        integrality=np.ones(variables),
        bounds=Bounds(np.zeros(variables), np.ones(variables)),
        constraints=LinearConstraint(matrix.tocsr(), lower, upper),
        options={"time_limit": 30.0},
    )
    if not result.success or result.x is None:
        raise ValueError(f"No feasible rebate grid: {result.message}")

    selected = result.x.reshape(rows, cols, choices).argmax(axis=2)
    grid = rates[selected]
    scenario_results: dict[str, dict[str, float]] = {}
    for name in ("low", "base", "high"):
        net_from_cells = sum(
            option_net[name][g, v, selected[g, v]]
            for g, v in product(range(rows), range(cols))
        )
        payout = sum(
            option_payout[name][g, v, selected[g, v]]
            for g, v in product(range(rows), range(cols))
        )
        projected = net_from_cells + payout + fixed_forecast
        net = net_from_cells + fixed_forecast
        scenario_results[name] = {
            "projected_revenue": float(projected),
            "payout": float(payout),
            "net_revenue": float(net),
            "uplift_vs_no_program": float(net - no_program),
        }
    scenario_results["no_program"] = {
        "projected_revenue": no_program,
        "payout": 0.0,
        "net_revenue": no_program,
        "uplift_vs_no_program": 0.0,
    }
    return grid, scenario_results, counts, cell_revenue, exclusions


def _migration_stress(
    data: AccountPeriodData,
    config: ProgramConfig,
    scenarios: ScenarioSet,
    rates: np.ndarray,
) -> dict[str, float | bool | str]:
    accounts = data.accounts
    vi, gi, eligible, _ = assign_cells(accounts, config)
    original_cell = np.where(eligible, gi * config.shape[1] + vi, -1)
    state = original_cell.copy()
    seen: set[bytes] = set()
    elasticity = scenarios.matrices(config.shape)["base"]
    forecast = accounts["forecast_revenue"].to_numpy(dtype=float)
    baseline = accounts["baseline_revenue"].to_numpy(dtype=float)

    def state_metrics(cell_state: np.ndarray) -> tuple[np.ndarray, float]:
        applied_rate = np.zeros(len(accounts))
        applied_elasticity = np.zeros(len(accounts))
        active = cell_state >= 0
        state_g = np.where(active, cell_state // config.shape[1], 0)
        state_v = np.where(active, cell_state % config.shape[1], 0)
        applied_rate[active] = rates[state_g[active], state_v[active]]
        applied_elasticity[active] = elasticity[state_g[active], state_v[active]]
        projected = np.maximum(forecast, 0) * (1 + applied_elasticity * applied_rate)
        payout = _payout(projected, baseline, 1.0, config.payout_basis) * applied_rate
        return projected, float((projected - payout).sum())

    _, fixed_net = state_metrics(original_cell)
    for iteration in range(1, 11):
        key = state.tobytes()
        if key in seen:
            return {
                "stable": False,
                "cycle_detected": True,
                "iterations": iteration,
                "migrated_share": 1.0,
                "reason": "Projected tier assignment cycles between cells.",
            }
        seen.add(key)
        projected, stable_net = state_metrics(state)
        projected_frame = accounts.assign(projected_revenue=projected)
        next_vi, next_gi, next_eligible, _ = assign_cells(
            projected_frame, config, revenue_column="projected_revenue"
        )
        next_state = np.where(
            next_eligible, next_gi * config.shape[1] + next_vi, -1
        )
        if np.array_equal(next_state, state):
            original_active = original_cell >= 0
            migrated = (
                np.mean(next_state[original_active] != original_cell[original_active])
                if original_active.any()
                else 0.0
            )
            net_impact = (
                abs(stable_net - fixed_net) / abs(fixed_net) if fixed_net else 0.0
            )
            stable = bool(net_impact <= config.max_migration_net_impact)
            return {
                "stable": stable,
                "cycle_detected": False,
                "iterations": iteration,
                "migrated_share": float(migrated),
                "net_impact_share": float(net_impact),
                "reason": (
                    "Stable within the configured financial-impact tolerance."
                    if stable
                    else "Stable, but reclassification changes projected net revenue materially."
                ),
            }
        state = next_state
    return {
        "stable": False,
        "cycle_detected": False,
        "iterations": 10,
        "migrated_share": 1.0,
        "reason": "Projected tier assignment did not stabilize within 10 iterations.",
    }


def _constraint_checks(
    config: ProgramConfig,
    rates: np.ndarray,
    scenarios: dict[str, dict[str, float]],
) -> dict[str, bool]:
    tolerance = 1e-8
    checks = {
        "rate_bounds": bool(
            np.all(rates >= config.min_rate - tolerance)
            and np.all(rates <= config.max_rate + tolerance)
        ),
        "discrete_rates": bool(
            np.allclose(
                (rates - config.min_rate) / config.rate_step,
                np.round((rates - config.min_rate) / config.rate_step),
                atol=tolerance,
            )
        ),
        "volume_monotonicity": bool(
            np.all(np.diff(rates, axis=1) >= config.min_increment - tolerance)
        ),
        "growth_monotonicity": bool(
            np.all(np.diff(rates, axis=0) >= config.min_increment - tolerance)
        ),
        "budget": bool(
            config.budget is None
            or scenarios["base"]["payout"] <= config.budget + tolerance
        ),
        "low_scenario_guard": bool(
            scenarios["low"]["net_revenue"]
            >= scenarios["no_program"]["net_revenue"] - tolerance
        ),
    }
    return checks


def optimize_program(
    data: AccountPeriodData,
    candidates: Sequence[ProgramConfig],
    scenarios: ScenarioSet,
) -> OptimizationResult:
    """Assess candidates, solve feasible grids, and choose base-case net revenue."""

    if not candidates:
        raise ValueError("At least one threshold candidate is required.")
    assessments: list[CandidateAssessment] = []
    solved: list[OptimizationResult] = []
    solve_errors: list[str] = []

    seen: set[tuple[tuple[float, ...], tuple[float, ...]]] = set()
    for config in candidates:
        key = (config.volume_milestones, config.growth_milestones)
        if key in seen:
            continue
        seen.add(key)
        assessment = assess_candidate(data, config)
        assessments.append(assessment)
        if not assessment.accepted:
            continue
        try:
            rates, scenario_results, counts, revenue, exclusions = _solve_rates(
                data, config, scenarios
            )
        except ValueError as exc:
            assessment.accepted = False
            assessment.reasons.append(str(exc))
            solve_errors.append(f"{config.name}: {exc}")
            continue

        migration = _migration_stress(data, config, scenarios, rates)
        if not migration["stable"]:
            assessment.accepted = False
            assessment.reasons.append(str(migration["reason"]))
            continue
        checks = _constraint_checks(config, rates, scenario_results)
        if not all(checks.values()):
            assessment.accepted = False
            assessment.reasons.append("The solved grid failed a post-solve constraint check.")
            continue

        solved.append(
            OptimizationResult(
                config=config,
                rates=rates,
                scenarios=scenario_results,
                cell_counts=counts,
                cell_revenue=revenue,
                exclusion_counts=exclusions,
                reconciliation=data.reconciliation(),
                constraint_checks=checks,
                migration=migration,
            )
        )

    if not solved:
        details = [
            f"{item.name}: {'; '.join(item.reasons[:3])}"
            for item in assessments
            if item.reasons
        ]
        details.extend(solve_errors)
        raise ValueError(
            "No candidate satisfied the contract guardrails. " + " | ".join(details)
        )

    best = max(solved, key=lambda item: item.scenarios["base"]["net_revenue"])
    best.candidate_assessments = assessments
    if best.config.budget is None:
        best.warnings.append("No payout budget was supplied; rate bounds limit exposure.")
    return best


def default_program_config(
    *,
    budget: float | None = None,
    payout_basis: PayoutBasis = "incremental",
) -> ProgramConfig:
    return ProgramConfig(
        name="example_grid",
        volume_milestones=(6_500.0, 25_000.0, 50_000.0),
        growth_milestones=(0.06, 0.10, 0.15, 0.20),
        budget=budget,
        payout_basis=payout_basis,
    )


def legacy_program_config(template: ProgramConfig | None = None) -> ProgramConfig:
    """The paid portion of the legacy script's 4-volume by 3-growth grid."""

    base = template or default_program_config()
    return replace(
        base,
        name="legacy_current_grid",
        volume_milestones=(5_000.0, 15_000.0, 30_000.0, 50_000.0),
        growth_milestones=(0.08, 0.15, 0.20),
    )


def optimize_default_program(
    data: AccountPeriodData,
    scenarios: ScenarioSet | None = None,
    *,
    budget: float | None = None,
    payout_basis: PayoutBasis = "incremental",
    include_auto_candidates: bool = True,
) -> OptimizationResult:
    template = default_program_config(budget=budget, payout_basis=payout_basis)
    candidates = [template, legacy_program_config(template)]
    if include_auto_candidates:
        candidates.extend(generate_threshold_candidates(data, template))
    return optimize_program(data, candidates, scenarios or ScenarioSet())
