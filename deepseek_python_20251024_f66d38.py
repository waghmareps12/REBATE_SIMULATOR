import pandas as pd
import numpy as np
from scipy import stats
import itertools
from sklearn.linear_model import LinearRegression
import warnings
warnings.filterwarnings('ignore')

class RebateOptimizer:
    def __init__(self, df, volume_col='curryr_rev', growth_col='prevyr_rev'):
        self.df = df.copy()
        self.volume_col = volume_col
        self.growth_col = growth_col
        self.results = []
        
    def compute_growth(self):
        """Step 1: Compute growth rates"""
        self.df['growth_rate'] = (
            (self.df[self.volume_col] - self.df[self.growth_col]) 
            / self.df[self.growth_col]
        ).replace([np.inf, -np.inf], np.nan).fillna(0)
        
    def fit_elasticity_model(self):
        """Step 4: Optional elasticity modeling using log-log regression"""
        # Simulate historical rebate data (in practice, this would come from historical data)
        np.random.seed(42)
        self.df['simulated_rebate_rate'] = np.random.uniform(0, 0.2, len(self.df))
        self.df['simulated_revenue_response'] = (
            self.df[self.volume_col] * 
            (1 + 0.3 * self.df['simulated_rebate_rate'])  # Simulate positive elasticity
        )
        
        # Log-log regression: log(revenue) ~ log(1 + rebate_rate)
        X = np.log(1 + self.df['simulated_rebate_rate']).values.reshape(-1, 1)
        y = np.log(self.df['simulated_revenue_response'])
        
        self.elasticity_model = LinearRegression()
        self.elasticity_model.fit(X, y)
        self.elasticity_coef = self.elasticity_model.coef_[0]
        
    def calculate_rebates(self, volume_tiers, growth_tiers, rate_grid):
        """Step 2 & 3: Assign tiers and calculate rebates"""
        df_temp = self.df.copy()
        
        # Assign volume tiers
        df_temp['volume_tier'] = pd.cut(
            df_temp[self.volume_col], 
            bins=volume_tiers, 
            labels=range(len(volume_tiers)-1)
        )
        
        # Assign growth tiers  
        df_temp['growth_tier'] = pd.cut(
            df_temp['growth_rate'],
            bins=growth_tiers,
            labels=range(len(growth_tiers)-1)
        )
        
        # Calculate rebates based on tier assignments
        rebates = []
        for _, row in df_temp.iterrows():
            vol_tier = row['volume_tier']
            growth_tier = row['growth_tier']
            if pd.notna(vol_tier) and pd.notna(growth_tier):
                rate = rate_grid[int(vol_tier)][int(growth_tier)]
                # Apply elasticity adjustment if model is fitted
                if hasattr(self, 'elasticity_model'):
                    adjusted_revenue = np.exp(
                        self.elasticity_model.predict(
                            np.log(1 + rate).reshape(1, -1)
                        )[0]
                    )
                    rebate_amount = rate * adjusted_revenue
                else:
                    rebate_amount = rate * row[self.volume_col]
                rebates.append(rebate_amount)
            else:
                rebates.append(0)
                
        df_temp['rebate_amount'] = rebates
        df_temp['net_revenue'] = df_temp[self.volume_col] - df_temp['rebate_amount']
        
        return df_temp
    
    def generate_tier_combinations(self, n_volume_tiers=3, n_growth_tiers=3):
        """Generate tier boundary combinations"""
        volume_quantiles = np.quantile(self.df[self.volume_col], [0.2, 0.4, 0.6, 0.8])
        growth_quantiles = np.quantile(self.df['growth_rate'], [0.2, 0.4, 0.6, 0.8])
        
        volume_combinations = []
        growth_combinations = []
        
        # Generate volume tier boundaries
        for combo in itertools.combinations(volume_quantiles, n_volume_tiers-1):
            tier_boundaries = [0] + sorted(combo) + [self.df[self.volume_col].max() * 1.1]
            volume_combinations.append(tier_boundaries)
            
        # Generate growth tier boundaries  
        for combo in itertools.combinations(growth_quantiles, n_growth_tiers-1):
            tier_boundaries = [self.df['growth_rate'].min() - 0.01] + sorted(combo) + [self.df['growth_rate'].max() + 0.01]
            growth_combinations.append(tier_boundaries)
            
        return volume_combinations, growth_combinations
    
    def generate_rate_combinations(self, n_volume_tiers, n_growth_tiers, min_rate=0, max_rate=0.2):
        """Generate rate grid combinations"""
        rate_levels = np.linspace(min_rate, max_rate, 6)  # 0%, 4%, 8%, 12%, 16%, 20%
        
        # Generate all possible rate grids
        rate_combinations = []
        for combo in itertools.product(rate_levels, repeat=n_volume_tiers * n_growth_tiers):
            rate_grid = np.array(combo).reshape(n_volume_tiers, n_growth_tiers)
            
            # Ensure rates increase with volume and growth (business logic)
            valid = True
            for i in range(n_volume_tiers-1):
                for j in range(n_growth_tiers):
                    if rate_grid[i][j] > rate_grid[i+1][j]:
                        valid = False
                        break
            for j in range(n_growth_tiers-1):
                for i in range(n_volume_tiers):
                    if rate_grid[i][j] > rate_grid[i][j+1]:
                        valid = False
                        break
                        
            if valid:
                rate_combinations.append(rate_grid)
                
        return rate_combinations
    
    def simulate_combinations(self, n_simulations=1000):
        """Step 5 & 6: Simulate multiple tier/rate combinations"""
        print("Computing growth rates...")
        self.compute_growth()
        
        print("Fitting elasticity model...")
        self.fit_elasticity_model()
        
        print("Generating tier combinations...")
        volume_combos, growth_combos = self.generate_tier_combinations()
        
        # Sample combinations for simulation
        np.random.seed(42)
        sampled_results = []
        
        for i in range(n_simulations):
            if i % 100 == 0:
                print(f"Running simulation {i}/{n_simulations}")
                
            # Randomly select tier boundaries
            volume_tiers = np.random.choice(volume_combos)
            growth_tiers = np.random.choice(growth_combos)
            
            n_vol_tiers = len(volume_tiers) - 1
            n_growth_tiers = len(growth_tiers) - 1
            
            # Generate rate grid for these tiers
            rate_combos = self.generate_rate_combinations(n_vol_tiers, n_growth_tiers)
            if not rate_combos:
                continue
                
            rate_grid = np.random.choice(rate_combos)
            
            # Calculate results
            result_df = self.calculate_rebates(volume_tiers, growth_tiers, rate_grid)
            
            total_revenue = result_df[self.volume_col].sum()
            total_rebates = result_df['rebate_amount'].sum()
            net_revenue = result_df['net_revenue'].sum()
            
            sampled_results.append({
                'volume_tiers': volume_tiers,
                'growth_tiers': growth_tiers,
                'rate_grid': rate_grid.tolist(),
                'total_revenue': total_revenue,
                'total_rebates': total_rebates,
                'net_revenue': net_revenue,
                'rebate_rate': total_rebates / total_revenue if total_revenue > 0 else 0
            })
        
        self.results = pd.DataFrame(sampled_results)
        return self.results
    
    def find_optimal_grid(self):
        """Step 7: Find the optimal tier/rate grid"""
        if self.results.empty:
            self.simulate_combinations()
            
        optimal_idx = self.results['net_revenue'].idxmax()
        optimal_config = self.results.loc[optimal_idx].to_dict()
        
        return optimal_config
    
    def calculate_confidence_intervals(self, n_bootstrap=1000):
        """Calculate confidence intervals for the optimal configuration"""
        optimal_config = self.find_optimal_grid()
        
        # Bootstrap the optimal configuration
        bootstrapped_net_revenues = []
        
        for _ in range(n_bootstrap):
            # Sample with replacement
            bootstrap_sample = self.df.sample(n=len(self.df), replace=True)
            
            # Recalculate for optimal configuration
            temp_optimizer = RebateOptimizer(bootstrap_sample)
            temp_optimizer.compute_growth()
            
            result_df = temp_optimizer.calculate_rebates(
                optimal_config['volume_tiers'],
                optimal_config['growth_tiers'], 
                optimal_config['rate_grid']
            )
            
            bootstrapped_net_revenues.append(result_df['net_revenue'].sum())
        
        ci_lower = np.percentile(bootstrapped_net_revenues, 2.5)
        ci_upper = np.percentile(bootstrapped_net_revenues, 97.5)
        
        return {
            'optimal_net_revenue': optimal_config['net_revenue'],
            'confidence_interval': (ci_lower, ci_upper),
            'std_error': np.std(bootstrapped_net_revenues)
        }

# Example usage and demonstration
def create_sample_data(n_accounts=1000):
    """Create sample dataset for demonstration"""
    np.random.seed(42)
    
    data = {
        'account_id': range(1, n_accounts + 1),
        'prevyr_rev': np.random.lognormal(10, 1, n_accounts),
        'curryr_rev': np.random.lognormal(10.5, 0.8, n_accounts)
    }
    
    df = pd.DataFrame(data)
    return df

# Run the optimization
print("Creating sample data...")
sample_df = create_sample_data(1000)

print("Initializing optimizer...")
optimizer = RebateOptimizer(sample_df)

print("Running simulations...")
results = optimizer.simulate_combinations(n_simulations=500)

print("\nFinding optimal configuration...")
optimal_config = optimizer.find_optimal_grid()

print("\nCalculating confidence intervals...")
confidence_intervals = optimizer.calculate_confidence_intervals()

# Display results
print("\n" + "="*60)
print("REBATE OPTIMIZATION RESULTS")
print("="*60)

print(f"\nOPTIMAL TIER STRUCTURE:")
print(f"Volume Tiers: {[f'${x:,.0f}' for x in optimal_config['volume_tiers']]}")
print(f"Growth Tiers: {[f'{x:.1%}' for x in optimal_config['growth_tiers']]}")

print(f"\nOPTIMAL REBATE RATES GRID:")
rate_grid = np.array(optimal_config['rate_grid'])
print("Rows: Volume Tiers (Low to High)")
print("Columns: Growth Tiers (Low to High)")
for i, row in enumerate(rate_grid):
    print(f"Vol Tier {i+1}: {[f'{x:.1%}' for x in row]}")

print(f"\nFINANCIAL IMPACT:")
print(f"Total Revenue: ${optimal_config['total_revenue']:,.2f}")
print(f"Total Rebates: ${optimal_config['total_rebates']:,.2f}")
print(f"Net Revenue: ${optimal_config['net_revenue']:,.2f}")
print(f"Effective Rebate Rate: {optimal_config['rebate_rate']:.2%}")

print(f"\nSTATISTICAL CONFIDENCE:")
print(f"Optimal Net Revenue: ${confidence_intervals['optimal_net_revenue']:,.2f}")
print(f"95% Confidence Interval: (${confidence_intervals['confidence_interval'][0]:,.2f}, ${confidence_intervals['confidence_interval'][1]:,.2f})")
print(f"Standard Error: ${confidence_intervals['std_error']:,.2f}")

# Compare with baseline (no rebates)
baseline_revenue = sample_df['curryr_rev'].sum()
uplift = optimal_config['net_revenue'] - baseline_revenue

print(f"\nVS BASELINE (NO REBATES):")
print(f"Baseline Revenue: ${baseline_revenue:,.2f}")
print(f"Net Uplift: ${uplift:,.2f} ({uplift/baseline_revenue:.2%})")

print(f"\nELASTICITY ANALYSIS:")
print(f"Estimated Elasticity Coefficient: {optimizer.elasticity_coef:.4f}")
print("Interpretation: Positive coefficient suggests rebates drive revenue growth")