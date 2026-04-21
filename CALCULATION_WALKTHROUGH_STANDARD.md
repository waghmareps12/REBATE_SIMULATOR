# Standard Rebate Optimization: Step-by-Step Calculation Walkthrough

This document explains how the **Standard Rebate Optimizer** (`Optimized_Rebate_Simulator.py`) calculates optimal rates using a fixed **Elasticity Factor**.

---

## 1. The Goal
Just like the ML version, the goal is to maximize **Net Revenue**:
$$ \text{Net Revenue} = \text{Projected Revenue} - \text{Rebate Cost} $$

---

## 2. The "Brain": Linear Elasticity
In this version, we don't use a complex ML model. Instead, we use a single number called **Elasticity** (e.g., `2.0`).

This number represents a simple rule:
> *"For every 1% rebate we give, revenue grows by X%."*

$$ \text{Growth} = \text{Elasticity} \times \text{Rebate Rate} $$

**Example:**
If Elasticity = **2.0** and Rebate = **10%** (0.10):
$$ \text{Growth} = 2.0 \times 0.10 = 0.20 \text{ (20\% Growth)} $$

---

## 3. The Calculation Loop
The optimizer tests thousands of rebate grids. Here is the math for a single test:

### Step A: Assign Tiers
We look at a customer's *current* volume and growth.
*   *Example Account*: Revenue = \$100,000.
*   *Assigned Bin*: Volume `50k+`, Growth `15%-20%`.

### Step B: Look up the Proposed Rebate
The optimizer proposes a rebate rate for this bin.
*   *Proposed Rate*: **12%** (0.12).

### Step C: Calculate Growth
We apply the elasticity formula.
$$ \text{Predicted Growth} = \text{Elasticity} \times \text{Rebate Rate} $$
*   *Calculation*: $2.0 \times 0.12 = \mathbf{0.24} \text{ (24\%)}$

### Step D: Project Revenue
We estimate next year's revenue based on that growth.
$$ \text{Projected Revenue} = \text{Base Revenue} \times (1 + \text{Predicted Growth}) $$
*   *Calculation*: $\$100,000 \times (1 + 0.24) = \$124,000$

### Step E: Calculate Cost
We calculate the cost of paying the rebate on that new revenue.
$$ \text{Rebate Cost} = \text{Projected Revenue} \times \text{Rebate Rate} $$
*   *Calculation*: $\$124,000 \times 0.12 = \$14,880$

### Step F: Calculate Net Revenue
$$ \text{Net Revenue} = \text{Projected Revenue} - \text{Rebate Cost} $$
*   *Calculation*: $\$124,000 - \$14,880 = \mathbf{\$109,120}$

---

## 4. The Trade-off
The optimizer keeps increasing the rebate rate as long as the **Profit from Growth** > **Cost of Rebate**.

*   **If Elasticity is High (e.g., 5.0)**: The optimizer will push rebates to the maximum (15%) because the growth is huge.
*   **If Elasticity is Low (e.g., 0.5)**: The optimizer will set rebates to 0% (or the minimum 1%) because the rebate costs more than the growth it generates.

---

## Summary Example (Elasticity = 2.0)

| Step | Value | Formula |
| :--- | :--- | :--- |
| **1. Base Revenue** | \$100,000 | (From Data) |
| **2. Proposed Rebate** | 10% | (Trial Value) |
| **3. Predicted Growth** | +20% | $2.0 \times 0.10$ |
| **4. Projected Revenue** | \$120,000 | $\$100k \times 1.20$ |
| **5. Rebate Cost** | \$12,000 | $\$120k \times 0.10$ |
| **6. Net Revenue** | **\$108,000** | $\$120k - \$12k$ |

*Result*: We made \$8,000 more profit than doing nothing.
