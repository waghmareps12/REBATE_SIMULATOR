import pandas as pd
import numpy as np
from scipy.optimize import minimize, LinearConstraint
from sklearn.ensemble import RandomForestRegressor

class RobustRebateOptimizer:
    def __init__(self, data_path, assumed_elasticity=0.5):
        self.data_path = data_path
        self.assumed_elasticity = assumed_elasticity
        self.volume_bins = [(9000, 15000), (15000, 22500), (22500, 44999), (45000, np.inf)]
        self.growth_bins = [(0.00, 0.08), (0.08, 0.15), (0.15, 0.20), (0.20, np.inf)]
        
        # Load and aggressively clean data
        self._load_and_clean_data()
        self.original_grid = self._build_original_grid()
        self.baseline_model = self._train_baseline_model()
        
    def _load_and_clean_data(self):
        """Load data with aggressive cleaning to prevent log1p warnings"""
        print(f"Loading and cleaning data from {self.data_path}...")
        
        # Load with dtype specification to catch issues early
        self.df = pd.read_csv(self.data_path, dtype={'prevyr_rev': float, 'curryr_rev': float})
        
        # CRITICAL: Ensure revenue values are valid
        # Replace negative or missing values with small positive number
        self.df['prevyr_rev'] = pd.to_numeric(self.df['prevyr_rev'], errors='coerce')
        self.df['curryr_rev'] = pd.to_numeric(self.df['curryr_rev'], errors='coerce')
        
        # Replace NaN and negative values with $100 (minimum viable revenue)
        self.df['prevyr_rev'] = self.df['prevyr_rev'].fillna(100.0)
        self.df['curryr_rev'] = self.df['curryr_rev'].fillna(100.0)
        
        # Ensure no negative values (log1p cannot handle negatives)
        self.df['prevyr_rev'] = np.maximum(self.df['prevyr_rev'], 100.0)
        self.df['curryr_rev'] = np.maximum(self.df['curryr_rev'], 100.0)
        
        # Calculate growth with bounds
        self.df['growth_val'] = (self.df['curryr_rev'] - self.df['prevyr_rev']) / self.df['prevyr_rev']
        self.df['growth_val'] = self.df['growth_val'].replace([np.inf, -np.inf], np.nan).fillna(0)
        
        print(f"✓ Cleaned {len(self.df)} records (no negative/NaN revenue values)")
        
    def _build_original_grid(self):
        """Build the original deterministic grid as a numpy array"""
        grid_mapping = {
            (0, 0): 0.01, (0, 1): 0.03, (0, 2): 0.05, (0, 3): 0.05,
            (1, 0): 0.04, (1, 1): 0.05, (1, 2): 0.07, (1, 3): 0.07,
            (2, 0): 0.03, (2, 1): 0.05, (2, 2): 0.07, (2, 3): 0.07,
            (3, 0): 0.05, (3, 1): 0.07, (3, 2): 0.11, (3, 3): 0.11,
        }
        grid_array = np.zeros((4, 4))
        for (r, c), rate in grid_mapping.items():
            grid_array[r, c] = rate
        return grid_array
    
    def get_segment_indices(self, volume, growth_rate=0):
        """Fast lookup of segment indices"""
        if pd.isna(volume) or volume < 0:
            volume = 100.0
        
        v_idx = np.searchsorted([15000, 22500, 45000], volume, side='right')
        v_idx = min(v_idx, 3)
        
        if pd.isna(growth_rate):
            growth_rate = 0
        
        g_idx = np.searchsorted([0.08, 0.15, 0.20], growth_rate, side='right')
        g_idx = min(g_idx, 3)
        
        return v_idx, g_idx
    
    def get_original_rebate(self, volume, growth_rate=0):
        v_idx, g_idx = self.get_segment_indices(volume, growth_rate)
        return self.original_grid[v_idx, g_idx]
    
    def _train_baseline_model(self):
        print("Training baseline growth model...")
        
        # Build feature matrix safely
        X = pd.DataFrame()
        
        # Use np.log1p with safe values
        X['log_prev_rev'] = np.log1p(self.df['prevyr_rev'].values)  # Already cleaned
        
        # Add industry dummies if available
        if 'industry_code' in self.df.columns:
            self.df['industry_code'] = self.df['industry_code'].fillna(999)
            industry_dummies = pd.get_dummies(self.df['industry_code'], prefix='ind')
            X = pd.concat([X, industry_dummies], axis=1)
        
        # Add volume tier dummies
        v_indices = [self.get_segment_indices(rev, 0)[0] for rev in self.df['prevyr_rev']]
        volume_dummies = pd.get_dummies(v_indices, prefix='vol')
        X = pd.concat([X, volume_dummies], axis=1)
        
        # Ensure no NaN in features
        X = X.fillna(0)
        
        # Target variable
        y = self.df['growth_val'].clip(-0.5, 2.0)
        
        # Train model
        model = RandomForestRegressor(n_estimators=200, max_depth=6, min_samples_leaf=20, random_state=42)
        model.fit(X, y)
        
        self.feature_names = X.columns.tolist()
        print(f"✓ Model trained: R² = {model.score(X, y):.3f}")
        return model
    
    def _build_features_for_prediction(self, row):
        """Construct feature vector with defensive validation"""
        features = {}
        
        # CRITICAL FIX: Validate revenue before log1p
        prev_rev = row['prevyr_rev']
        
        # Handle missing or invalid values
        if pd.isna(prev_rev) or prev_rev < 0:
            prev_rev = 100.0  # Safe default
        
        # This line should NEVER warn now
        features['log_prev_rev'] = np.log1p(prev_rev)
        
        # Industry dummies
        for col in self.feature_names:
            if col.startswith('ind_'):
                features[col] = 1.0 if row.get('industry_code') == int(col.split('_')[1]) else 0.0
        
        # Volume tier dummies
        v_idx, _ = self.get_segment_indices(row['prevyr_rev'], 0)
        for i in range(4):
            features[f'vol_{i}'] = 1.0 if v_idx == i else 0.0
        
        # Build DataFrame and ensure all columns exist
        feature_df = pd.DataFrame([features])
        for col in self.feature_names:
            if col not in feature_df:
                feature_df[col] = 0
        
        return feature_df[self.feature_names]
    
    def simulate_counterfactual(self, proposed_grid, row):
        old_rebate = self.get_original_rebate(row['prevyr_rev'], row['growth_val'])
        v_idx, g_idx = self.get_segment_indices(row['prevyr_rev'], row['growth_val'])
        new_rebate = proposed_grid[v_idx, g_idx]
        
        features = self._build_features_for_prediction(row)
        baseline_growth = self.baseline_model.predict(features)[0]
        
        # Apply rebate effect
        if old_rebate > 0:
            growth_multiplier = ((1 + new_rebate) / (1 + old_rebate)) ** self.assumed_elasticity
        else:
            growth_multiplier = (1 + new_rebate) ** self.assumed_elasticity
            
        adjusted_growth = baseline_growth * growth_multiplier
        adjusted_growth = np.clip(adjusted_growth, -0.3, 0.5)
        
        return adjusted_growth, new_rebate
    
    def objective_function(self, flat_rates):
        rows, cols = len(self.volume_bins), len(self.growth_bins)
        proposed_grid = flat_rates.reshape((rows, cols))
        
        total_net_revenue = 0
        
        for _, row in self.df.iterrows():
            # Skip rows with truly invalid data (shouldn't happen after cleaning)
            if row['prevyr_rev'] <= 0:
                continue
                
            cf_growth, new_rebate = self.simulate_counterfactual(proposed_grid, row)
            
            base_rev = row['prevyr_rev']
            projected_rev = base_rev * (1 + cf_growth)
            rebate_cost = projected_rev * new_rebate
            net_rev = projected_rev - rebate_cost
            
            total_net_revenue += net_rev
        
        return -total_net_revenue
    
    def get_constraints(self):
        rows, cols = len(self.volume_bins), len(self.growth_bins)
        num_vars = rows * cols
        
        def idx(r, c):
            return r * cols + c
        
        A_rows = []
        lb = []
        ub = []
        
        # Volume monotonicity
        for r in range(1, rows):
            for c in range(cols):
                row = np.zeros(num_vars)
                row[idx(r, c)] = 1
                row[idx(r-1, c)] = -1
                A_rows.append(row)
                lb.append(0.0)
                ub.append(np.inf)
        
        # Growth monotonicity
        for r in range(rows):
            for c in range(1, cols):
                row = np.zeros(num_vars)
                row[idx(r, c)] = 1
                row[idx(r, c-1)] = -1
                A_rows.append(row)
                lb.append(0.0)
                ub.append(np.inf)
        
        if not A_rows:
            return None
        
        return LinearConstraint(np.array(A_rows), lb, ub)
    
    def get_bounds(self):
        bounds = []
        for r in range(len(self.volume_bins)):
            for c in range(len(self.growth_bins)):
                orig = self.original_grid[r, c]
                lower = max(0.005, orig * 0.5)
                upper = min(0.15, orig * 1.5)
                bounds.append((lower, upper))
        return bounds
    
    def optimize_grid(self):
        rows, cols = len(self.volume_bins), len(self.growth_bins)
        
        x0 = self.original_grid.flatten()
        constraints = self.get_constraints()
        bounds = self.get_bounds()
        
        print(f"\n{'='*60}")
        print(f"Optimization Parameters:")
        print(f"  Assumed elasticity: {self.assumed_elasticity}")
        print(f"  Initial revenue: ${-self.objective_function(x0):,.2f}")
        print(f"{'='*60}\n")
        
        result = minimize(
            self.objective_function,
            x0,
            method='trust-constr',
            bounds=bounds,
            constraints=[constraints] if constraints else [],
            options={'verbose': 2, 'maxiter': 5000, 'gtol': 1e-4}
        )
        
        if result.success:
            new_grid = result.x.reshape((rows, cols))
            new_revenue = -result.fun
            original_revenue = -self.objective_function(x0)
            improvement = new_revenue - original_revenue
            
            print(f"\n✅ Optimization successful!")
            print(f"  New revenue: ${new_revenue:,.2f}")
            print(f"  Improvement: ${improvement:,.2f} ({improvement/original_revenue*100:.3f}%)")
            return new_grid, new_revenue
        else:
            print(f"\n❌ Optimization failed: {result.message}")
            return None, None
    
    def validate_proposed_grid(self, grid):
        print("\n" + "="*70)
        print("VALIDATION: Proposed Rebate Grid vs Original")
        print("="*70)
        
        header = f"{'Segment':<15} {'Original':<12} {'Proposed':<12} {'Change':<12}"
        print(header)
        print("-"*70)
        
        for r in range(4):
            print(f"\nVolume Tier {r}: {self.volume_bins[r]}")
            for c in range(4):
                orig_rate = self.original_grid[r, c]
                new_rate = grid[r, c]
                change_pct = (new_rate - orig_rate) / orig_rate * 100
                print(f"  Growth {c}: {orig_rate:>8.2%}    {new_rate:>8.2%}    {change_pct:>+7.1f}%")
        
        # Summary
        avg_change = np.mean((grid - self.original_grid) / self.original_grid * 100)
        max_change = np.max(np.abs((grid - self.original_grid) / self.original_grid * 100))
        
        print(f"\nSummary:")
        print(f"  Average rate change: {avg_change:+.2f}%")
        print(f"  Maximum rate change: {max_change:.2f}%")
        
        # Constraint checks
        vol_mono = all(grid[r, c] >= grid[r-1, c] - 0.0001 for r in range(1, 4) for c in range(4))
        grow_mono = all(grid[r, c] >= grid[r, c-1] - 0.0001 for r in range(4) for c in range(1, 4))
        bounds_ok = np.all((grid >= 0.005) & (grid <= 0.15))
        
        print(f"\nConstraint Checks:")
        print(f"  ✅ Volume monotonicity: {'PASS' if vol_mono else 'FAIL'}")
        print(f"  ✅ Growth monotonicity: {'PASS' if grow_mono else 'FAIL'}")
        print(f"  ✅ Bounds [0.5%, 15%]: {'PASS' if bounds_ok else 'FAIL'}")
        
        print("="*70)

# Usage
if __name__ == "__main__":
    optimizer = RobustRebateOptimizer(
        data_path="DummyDataGpot2.csv",
        assumed_elasticity=0.5
    )
    
    new_grid, revenue = optimizer.optimize_grid()
    
    if new_grid is not None:
        optimizer.validate_proposed_grid(new_grid)
        print("\n" + "="*70)
        print("FINAL OPTIMIZED GRID")
        print("="*70)
        print(np.round(new_grid, 4))
        print("="*70)