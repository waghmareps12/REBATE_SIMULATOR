# Rebate Optimization System – 0→1 Data Science Initiative

## Problem Context
The client operates multiple rebate programs based on *volume* and *growth tiers*. Each program defines tier boundaries and rebate percentages, which determine payout amounts to accounts. The historical programs are deterministic—rebates are computed strictly based on tier bins—but the client wants to **design new tier grids and rebate rates** that *maximize total revenue net of payouts*.

## Core Objective
Build a **simulation and optimization engine** that:
- Tests hundreds of possible **volume and growth tier combinations**.
- Assigns rebate rates to each (volume, growth) cell.
- Simulates how these programs would affect revenue and payout totals.
- Identifies the optimal grid configuration that maximizes **net revenue** (revenue - rebates).

## Data Inputs
- `rfp_group`, `rfp_name` — account identifiers.
- `curryr_rev`, `prevyr_rev` — current and previous year revenues.
- `growth` = (`curryr_rev` - `prevyr_rev`) / `prevyr_rev`.
- Optional: historical rebate rate or rebate paid.

## Modeling Approach
1. **Deterministic Engine**  
   Compute rebate amounts directly from bins and fixed rates using `pd.cut` for tier assignment.
   ```python
   df["volume_tier"] = pd.cut(df["curryr_rev"], bins=v_edges, labels=v_labels)
   df["growth_tier"] = pd.cut(df["growth"], bins=g_edges, labels=g_labels)
   df["rebate"] = df["rate"] * df["curryr_rev"]
   ```

2. **Elasticity Modeling (Optional)**  
   Estimate how revenue responds to changes in rebate rate using a **log-log OLS** model:  
   \[
   \log(\text{Revenue}_{new}) = \alpha + \beta \log(1 + \text{Rebate Rate})
   \]
   where β represents elasticity.

3. **Simulation Framework**  
   - Generate hundreds of candidate rebate grids:
     - Vary number of tiers, cutpoints, and rate levels.
   - For each grid:
     - Simulate new revenue (using elasticity) and rebate payouts.
     - Compute **net revenue = new revenue − rebates**.
   - Rank programs by expected net revenue and risk.

4. **Optimization**  
   - Either perform **brute-force grid search** or use **Bayesian optimization (Optuna)** to find the most profitable configuration.
   - Optionally, run Monte Carlo draws on residuals to estimate uncertainty.

## Example Output
| Rank | Volume Bins       | Growth Bins    | Avg Rebate % | Net Revenue (Mean) | Risk (5th pct) |
|------|------------------|----------------|--------------|---------------------|----------------|
| 1    | [0, 10k, 30k, ∞] | [0, 8%, 15%, ∞] | 2–6%         | $123.4M             | $118.2M        |
| 2    | [0, 15k, 50k, ∞] | [0, 10%, ∞]     | 1–5%         | $120.7M             | $117.5M        |

## Deliverable
A **Streamlit-based simulation UI** where users can:
- Upload an account-level CSV.
- Edit tier boundaries and rebate rates interactively.
- Run simulations for new program configurations.
- View predicted rebate totals, revenue impact, and optimal program recommendations.

## Key Takeaways
- Transitioned rebate design from static rule-based decisions to a **data-driven optimization framework**.
- Introduced elasticity modeling and Monte Carlo simulations for robust revenue prediction.
- Enabled business users to test "what-if" program scenarios and launch more profitable incentive structures.


Prompt - 

---

## 🤖 **Prompt Summary (for use with LLMs or modeling tools)**

> You are designing a **rebate optimization system** for a client with historical sales data containing account-level revenues (`curryr_rev`, `prevyr_rev`) and rebate information.  
>  
> The business defines programs using **volume** and **growth tiers**, each with fixed **rebate rates**. The goal is to **simulate hundreds of tier and rate combinations** to find the grid that maximizes **net revenue (revenue − rebates)**.  
>  
> Steps:  
> 1. Compute growth = (`curryr_rev` - `prevyr_rev`) / `prevyr_rev`.  
> 2. Assign each account to tiers via `pd.cut`.  
> 3. Calculate rebates = `rate * curryr_rev`.  
> 4. (Optional) Model elasticity between rebate rate and revenue using a log-log regression.  
> 5. Simulate how changing tiers/rates affects revenue and payouts.  
> 6. Iterate over multiple combinations (brute-force or Bayesian optimization).  
> 7. Recommend the grid that yields the highest expected net revenue.  
>  
> Output should include:  
> - Optimal volume/growth tier boundaries.  
> - Recommended rebate rates per cell.  
> - Simulated revenue uplift and rebate cost.  
> - Net impact and confidence intervals.  

---

