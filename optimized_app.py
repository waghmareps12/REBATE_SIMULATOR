"""Flask application for constraint-based rebate contract design."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template, request

from rebate_contract import (
    AccountPeriodData,
    ProgramConfig,
    ScenarioSet,
    default_program_config,
    evaluate_actual_grid,
    generate_threshold_candidates,
    legacy_program_config,
    optimize_program,
)


app = Flask(__name__)
DATA_FILE = Path(__file__).with_name("DummyDataGpot2.csv")
_account_data: AccountPeriodData | None = None


def get_account_data() -> AccountPeriodData:
    global _account_data
    if _account_data is None:
        _account_data = AccountPeriodData.from_csv(DATA_FILE)
    return _account_data


def _number_list(payload: dict, key: str, default: tuple[float, ...]) -> tuple[float, ...]:
    value = payload.get(key, default)
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{key} must be a non-empty list.")
    return tuple(float(item) for item in value)


def _optional_float(payload: dict, key: str) -> float | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    return float(value)


def _program_from_payload(payload: dict) -> ProgramConfig:
    defaults = default_program_config()
    config = ProgramConfig(
        name="user_grid",
        volume_milestones=_number_list(
            payload, "volume_milestones", defaults.volume_milestones
        ),
        growth_milestones=_number_list(
            payload, "growth_milestones", defaults.growth_milestones
        ),
        payout_basis=payload.get("payout_basis", "incremental"),
        min_rate=float(payload.get("min_rate", 0.01)),
        max_rate=float(payload.get("max_rate", 0.15)),
        rate_step=float(payload.get("rate_step", 0.01)),
        min_increment=float(payload.get("min_increment", 0.01)),
        min_accounts_per_cell=int(payload.get("min_accounts_per_cell", 30)),
        min_revenue_share_per_cell=float(
            payload.get("min_revenue_share_per_cell", 0.01)
        ),
        budget=_optional_float(payload, "budget"),
        max_migration_net_impact=float(
            payload.get("max_migration_net_impact", 0.05)
        ),
    )
    config.validate()
    return config


def _scenarios_from_payload(payload: dict) -> ScenarioSet:
    scenario_payload = payload.get("scenarios", {})
    if not isinstance(scenario_payload, dict):
        raise ValueError("scenarios must be an object with low, base, and high values.")
    return ScenarioSet(
        low=scenario_payload.get("low", 0.5),
        base=scenario_payload.get("base", 1.5),
        high=scenario_payload.get("high", 2.5),
    )


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/optimize")
def optimize():
    try:
        payload = request.get_json(silent=False)
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        data = get_account_data()
        user_config = _program_from_payload(payload)
        scenarios = _scenarios_from_payload(payload)
        candidates = [user_config, legacy_program_config(user_config)]
        if payload.get("include_auto_candidates", True):
            candidates.extend(generate_threshold_candidates(data, user_config))
        result = optimize_program(data, candidates, scenarios)
        return jsonify(result.to_dict())
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        app.logger.exception("Unexpected optimization failure")
        return jsonify({"error": "Unexpected optimization failure."}), 500


@app.post("/calculate_static")
def calculate_static():
    try:
        payload = request.get_json(silent=False)
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        config = _program_from_payload(
            {
                **payload,
                "min_accounts_per_cell": 1,
                "min_revenue_share_per_cell": 0,
            }
        )
        rates = payload.get("rates")
        if rates is None:
            raise ValueError("rates is required.")
        result = evaluate_actual_grid(get_account_data(), config, rates)
        return jsonify(result)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        app.logger.exception("Unexpected static calculation failure")
        return jsonify({"error": "Unexpected static calculation failure."}), 500


@app.get("/health")
def health():
    data = get_account_data()
    return jsonify({"status": "ok", "reconciliation": data.reconciliation()})


if __name__ == "__main__":
    app.run(debug=True)
