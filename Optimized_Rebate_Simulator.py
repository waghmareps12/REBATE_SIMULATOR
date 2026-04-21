import pandas as pd
import numpy as np
import os
from scipy.optimize import minimize, LinearConstraint

class RebateOptimizer:
    def __init__(self, data_path, elasticity=0.5):
        """
        Initialize the optimizer with data and elasticity assumption.
        
        Args:
            data_path (str): Path to the transaction CSV.
            elasticity (float): % Revenue increase per 1% Rebate increase.
                                e.g., 0.5 means 10% rebate -> 5% revenue growth.
        """
        self.data_path = data_path
        self.elasticity = elasticity
        self.df_base = pd.read_csv(data_path).rename(columns=str.lower)
        self.volume_bins = None
        self.growth_bins = None
        self.df_processed = None
        
    def set_bins(self, volume_bins, growth_bins):
        """
        Set the bin configurations and pre-process the dataframe indices.
        """
        self.volume_bins = volume_bins
        self.growth_bins = growth_bins
        
        # Create bin edges
        v_edges = [b[0] for b in volume_bins] + [volume_bins[-1][1]]
        g_edges = [g[0] for g in growth_bins] + [growth_bins[-1][1]]
        
        # Assign indices (0 to N-1) for fast lookup
        # We use codes instead of labels for direct array indexing
        self.df_processed = self.df_base.copy()
        self.df_processed["growth_val"] = (self.df_processed["curryr_rev"] - self.df_processed["prevyr_rev"]) / self.df_processed["prevyr_rev"]
        
        # pd.cut returns categorical, .cat.codes gives integer indices (-1 for NaN/out of bounds)
        self.df_processed["v_idx"] = pd.cut(self.df_processed["curryr_rev"], bins=v_edges, right=True).cat.codes
        self.df_processed["g_idx"] = pd.cut(self.df_processed["growth_val"], bins=g_edges, right=False).cat.codes
        
        # Filter out rows that didn't fall into any bin (code -1)
        self.df_processed = self.df_processed[(self.df_processed["v_idx"] >= 0) & (self.df_processed["g_idx"] >= 0)]
        
        # Pre-aggregate data for faster optimization
        # We only need the sum of revenue for each (v_idx, g_idx) bucket
        self.agg_data = self.df_processed.groupby(['v_idx', 'g_idx'])['curryr_rev'].sum().reset_index()

    def objective_function(self, flat_rates):
        """
        Objective function to MINIMIZE (negative Net Revenue).
        
        Args:
            flat_rates (np.array): Flattened array of rebate rates.
        """
        # Reshape rates to grid
        rows = len(self.volume_bins)
        cols = len(self.growth_bins)
        rates_grid = flat_rates.reshape((rows, cols))
        
        # Map rates to the aggregated data
        # We can use numpy indexing since v_idx and g_idx are integers
        applied_rates = rates_grid[self.agg_data['v_idx'], self.agg_data['g_idx']]
        
        # Calculate Metrics
        base_revenue = self.agg_data['curryr_rev']
        
        # Elasticity Model: New Rev = Base * (1 + Elasticity * Rate)
        projected_revenue = base_revenue * (1 + self.elasticity * applied_rates)
        
        # Rebate Cost = Projected Rev * Rate
        rebate_cost = projected_revenue * applied_rates
        
        # Net Revenue = Projected Rev - Rebate Cost
        net_revenue = projected_revenue - rebate_cost
        
        # Return negative sum for minimization
        return -np.sum(net_revenue)

    def get_constraints(self, min_increment=0.01):
        """
        Generate monotonicity constraints using LinearConstraint.
        A @ x >= min_increment
        """
        rows = len(self.volume_bins)
        cols = len(self.growth_bins)
        num_vars = rows * cols
        
        # We need to build A matrix and lb vector
        # Each constraint is a row in A
        A_rows = []
        lb = []
        ub = [] # Upper bound for constraint (infinity)
        
        # Helper to get index in flattened array
        def idx(r, c):
            return r * cols + c
        
        # Volume Monotonicity (Downwards)
        for r in range(1, rows):
            for c in range(cols):
                if self.growth_bins[c][1] <= 0.08:
                    continue
                
                # rate[r,c] - rate[r-1,c] >= min_increment
                # 1 * x[curr] + (-1) * x[prev] >= min_increment
                row = np.zeros(num_vars)
                row[idx(r, c)] = 1
                row[idx(r-1, c)] = -1
                A_rows.append(row)
                lb.append(min_increment)
                ub.append(np.inf)
                
        # Growth Monotonicity (Rightwards)
        for r in range(rows):
            for c in range(1, cols):
                if self.growth_bins[c][1] <= 0.08:
                    continue
                
                # Skip if prev was zero bin (handled by bounds)
                if self.growth_bins[c-1][1] <= 0.08:
                    continue
                
                # rate[r,c] - rate[r,c-1] >= min_increment
                row = np.zeros(num_vars)
                row[idx(r, c)] = 1
                row[idx(r, c-1)] = -1
                A_rows.append(row)
                lb.append(min_increment)
                ub.append(np.inf)
                
        if not A_rows:
            return None
            
        return LinearConstraint(A_rows, lb, ub)

    def optimize(self):
        """
        Run the optimization.
        """
        rows = len(self.volume_bins)
        cols = len(self.growth_bins)
        num_vars = rows * cols
        
        # Define Bounds
        bounds = []
        initial_guess = []
        
        for r in range(rows):
            for c in range(cols):
                # Constraint: Growth <= 8% gets 0% rebate
                if self.growth_bins[c][1] <= 0.08:
                    bounds.append((0.0, 1e-9))
                    initial_guess.append(0.0)
                else:
                    # Constraint: Min 1%, Max 15%
                    bounds.append((0.01, 0.15))
                    # Initial guess: slightly increasing to satisfy constraints
                    initial_guess.append(0.01 + (r + c) * 0.01)
        
        initial_guess = np.array(initial_guess)
        
        # Constraints
        cons = self.get_constraints(min_increment=0.01)
        constraints_arg = [cons] if cons else []
        
        print(f"Starting optimization for {rows}x{cols} grid...")
        print("Constraints: Min Increment 1%, Max 15%, 0% for Growth <= 8%")
        
        result = minimize(
            self.objective_function,
            initial_guess,
            method='trust-constr',
            bounds=bounds,
            constraints=constraints_arg,
            options={'verbose': 1, 'maxiter': 1000}
        )
        
        if result.success:
            print("Optimization Successful!")
            best_grid = result.x.reshape((rows, cols))
            return best_grid, -result.fun
        else:
            print("Optimization Failed:", result.message)
            # Even if it fails, trust-constr often gives a feasible point
            best_grid = result.x.reshape((rows, cols))
            return best_grid, -result.fun

    def save_results(self, best_grid, filename="optimized_grid.csv"):
        """
        Save the grid to CSV.
        """
        # Round to nearest whole percentage (0.01)
        best_grid = np.round(best_grid, 2)
        
        df_grid = pd.DataFrame(
            best_grid,
            columns=[f"{g[0]}-{g[1]}" for g in self.growth_bins],
            index=[f"{v[0]}-{v[1]}" for v in self.volume_bins]
        )
        df_grid.to_csv(filename)
        print(f"Grid saved to {filename}")
        return df_grid

# === Main Execution ===
if __name__ == "__main__":
    # Config
    DATA_FILE = "DummyDataGpot2.csv"
    
    # Define Bins (Same as Config 1 from original script)
    volume_bins = [(5000, 15000), (15000, 30000), (30000, 50000), (50000, np.inf)]
    growth_bins = [(0.00, 0.08), (0.08, 0.15), (0.15, 0.20), (0.20, np.inf)]
    
    # Initialize
    optimizer = RebateOptimizer(DATA_FILE, elasticity=2.0)
    optimizer.set_bins(volume_bins, growth_bins)
    
    # Run
    best_grid, max_rev = optimizer.optimize()
    
    if best_grid is not None:
        print(f"\n🏆 Optimized Max Net Revenue: ${max_rev:,.2f}")
        
        # Save and Display
        df_result = optimizer.save_results(best_grid)
        print("\nOptimized Rebate Grid:")
        print(df_result.round(4))
