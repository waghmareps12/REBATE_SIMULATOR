# Rebate Optimization: Step-by-Step Calculation Walkthrough

This document explains exactly how the **ML-Based Rebate Optimizer** calculates the optimal rebate rates and projects revenue.

---

## 1. The Goal
The goal is to find a **Rebate Grid** (a matrix of rebate rates based on Volume and Growth) that maximizes **Net Revenue**.

$$ \text{Net Revenue} = \text{Projected Revenue} - \text{Rebate Cost} $$

---

## 2. The "Brain": ML Elasticity Model
Before optimization begins, the system trains a Machine Learning model (Linear Regression) on your historical data.

*   **Input ($X$)**: Historical Rebate Rates given to customers.
*   **Target ($y$)**: The Year-over-Year Growth those customers achieved.
*   **The Learned Logic**: The model calculates a coefficient (elasticity) that represents:
    > *"For every 1% increase in rebate, how much additional growth do we get?"*

**Example:**
If the model learns a coefficient of **5.0**, it means a **1% rebate increase** leads to **5% extra growth**.

---

## 3. The Calculation Loop
The optimizer tries thousands of different rebate grids. For each grid, it performs the following calculation step-by-step:

### Step A: Assign Tiers
Every customer account is assigned to a **Volume Tier** and a **Growth Tier** based on their *current* performance.
*   *Example Account*: Revenue = \$20,000, Growth = 10%.
*   *Assigned Bin*: Volume `15k-30k`, Growth `8%-15%`.

### Step B: Look up the Proposed Rebate
The optimizer proposes a rebate rate for that bin.
*   *Proposed Rate*: **11%** (0.11).

### Step C: Predict Growth (The ML Part)
The system asks the ML model: *"If we give this account 11%, what will their growth be?"*
$$ \text{Predicted Growth} = \text{Model}(\text{Rebate} = 0.11) $$
*   *Let's say the model predicts*: **56% Growth** (0.56).

### Step D: Project Revenue
We calculate what the customer's revenue *would be* next year with that growth.
$$ \text{Projected Revenue} = \text{Base Revenue} \times (1 + \text{Predicted Growth}) $$
*   *Calculation*: $\$20,000 \times (1 + 0.56) = \$31,200$

### Step E: Calculate Cost
We calculate how much we have to pay back in rebates on that *new* revenue.
$$ \text{Rebate Cost} = \text{Projected Revenue} \times \text{Rebate Rate} $$
*   *Calculation*: $\$31,200 \times 0.11 = \$3,432$

### Step F: Calculate Net Revenue
This is the final number the optimizer cares about.
$$ \text{Net Revenue} = \text{Projected Revenue} - \text{Rebate Cost} $$
*   *Calculation*: $\$31,200 - \$3,432 = \mathbf{\$27,768}$

---

## 4. The Decision
The optimizer sums up this **Net Revenue** for *all* accounts.
*   If increasing a rebate rate leads to enough growth to cover the cost, the optimizer **keeps** the higher rate.
*   If the cost outweighs the growth, the optimizer **lowers** the rate.

## 5. Constraints (The Rules)
While doing this, the optimizer strictly follows your business rules:
1.  **0% for Low Growth**: Accounts with <8% growth get $0 rebate, no matter what.
2.  **Monotonicity**: A higher tier must *always* have a rebate $\ge$ the tier below it + 1%.
3.  **Bounds**: Rates must be between 1% and 15%.

---

## Summary Example
| Step | Value | Formula |
| :--- | :--- | :--- |
| **1. Base Revenue** | \$100,000 | (From Data) |
| **2. Proposed Rebate** | 10% | (Trial Value) |
| **3. Predicted Growth** | +50% | (ML Prediction) |
| **4. Projected Revenue** | \$150,000 | $\$100k \times (1 + 0.50)$ |
| **5. Rebate Cost** | \$15,000 | $\$150k \times 0.10$ |
| **6. Net Revenue** | **\$135,000** | $\$150k - \$15k$ |

*Compared to doing nothing (0% rebate, 0% growth):*
*   *Base Net*: \$100,000
*   *Optimized Net*: \$135,000
*   **Uplift**: +\$35,000 ✅ (This is a good rebate!)
