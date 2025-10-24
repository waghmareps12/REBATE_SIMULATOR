def fit_elasticity_model(self):
    """Step 4: Elasticity modeling using log-log regression"""
    np.random.seed(42)
    
    # Simulate historical rebate rates (0% to 20%)
    self.df['historical_rebate_rate'] = np.random.uniform(0, 0.2, len(self.df))
    
    # Simulate how rebates drive revenue growth
    # Higher rebates -> higher growth in current year revenue
    growth_impact = 0.4 * self.df['historical_rebate_rate']  # 40% pass-through to growth
    
    # Simulate what current year revenue would have been with rebate-driven growth
    self.df['simulated_curryr_rev'] = (
        self.df[self.growth_col] *  # Start from previous year revenue
        (1 + growth_impact)         # Apply growth driven by rebates
    )
    
    # Log-log regression: log(current_revenue/prev_revenue) ~ log(1 + rebate_rate)
    X = np.log(1 + self.df['historical_rebate_rate']).values.reshape(-1, 1)
    y = np.log(self.df['simulated_curryr_rev'] / self.df[self.growth_col])
    
    self.elasticity_model = LinearRegression()
    self.elasticity_model.fit(X, y)
    self.elasticity_coef = self.elasticity_model.coef_[0]

def calculate_rebates(self, volume_tiers, growth_tiers, rate_grid):
    """Corrected rebate calculation with proper growth-based tiers"""
    df_temp = self.df.copy()
    
    # Calculate actual growth rate (from prev year to current year)
    df_temp['growth_rate'] = (
        (df_temp[self.volume_col] - df_temp[self.growth_col]) 
        / df_temp[self.growth_col]
    ).replace([np.inf, -np.inf], np.nan).fillna(0)
    
    # Assign volume tiers based on CURRENT year revenue
    df_temp['volume_tier'] = pd.cut(
        df_temp[self.volume_col], 
        bins=volume_tiers, 
        labels=range(len(volume_tiers)-1),
        include_lowest=True
    )
    
    # Assign growth tiers based on GROWTH RATE (calculated from prev year)
    df_temp['growth_tier'] = pd.cut(
        df_temp['growth_rate'],
        bins=growth_tiers,
        labels=range(len(growth_tiers)-1),
        include_lowest=True
    )
    
    rebates = []
    adjusted_revenues = []
    
    for _, row in df_temp.iterrows():
        vol_tier = row['volume_tier']
        growth_tier = row['growth_tier']
        
        if pd.notna(vol_tier) and pd.notna(growth_tier):
            rebate_rate = rate_grid[int(vol_tier)][int(growth_tier)]
            
            # Apply elasticity: rebates may drive future revenue growth
            if hasattr(self, 'elasticity_model'):
                # Predict how this rebate rate would affect growth
                predicted_growth_factor = np.exp(
                    self.elasticity_model.predict(
                        np.log(1 + rebate_rate).reshape(1, -1)
                    )[0]
                )
                
                # Estimate what revenue could be with this rebate-driven growth
                # Using previous year as baseline for growth projection
                potential_revenue = row[self.growth_col] * predicted_growth_factor
                
                rebate_amount = rebate_rate * potential_revenue
                adjusted_revenue = potential_revenue  # Revenue after growth effect
            else:
                # Without elasticity, use current revenue
                rebate_amount = rebate_rate * row[self.volume_col]
                adjusted_revenue = row[self.volume_col]
                
            rebates.append(rebate_amount)
            adjusted_revenues.append(adjusted_revenue)
        else:
            rebates.append(0)
            adjusted_revenues.append(row[self.volume_col])
    
    df_temp['rebate_amount'] = rebates
    df_temp['adjusted_revenue'] = adjusted_revenues
    df_temp['net_revenue'] = df_temp['adjusted_revenue'] - df_temp['rebate_amount']
    
    return df_temp

def parse_example_grid(self):
    """Parse your example rebate grid structure"""
    # Your example:
    # Volume Bin,   0.08,   0.15,   0.2
    # 9000-15000,   0.01,   0.03,   0.05
    # 15000-22500,  0.04,   0.05,   0.07  
    # 22500-44999,  0.03,   0.05,   0.07
    # 45000+,       0.05,   0.07,   0.11
    
    example_volume_tiers = [0, 9000, 15000, 22500, 45000, np.inf]
    example_growth_tiers = [-np.inf, 0.08, 0.15, 0.2, np.inf]  # Growth rate boundaries
    
    example_rate_grid = [
        [0.01, 0.03, 0.05],  # Volume tier 0: 0-9000
        [0.04, 0.05, 0.07],  # Volume tier 1: 9000-15000
        [0.03, 0.05, 0.07],  # Volume tier 2: 15000-22500
        [0.05, 0.07, 0.11]   # Volume tier 3: 22500-45000+
    ]
    
    return example_volume_tiers, example_growth_tiers, example_rate_grid

def simulate_with_business_rules(self, n_simulations=500):
    """Enhanced simulation with business rule constraints"""
    print("Computing actual growth rates...")
    self.compute_growth()
    
    print("Fitting elasticity model...")
    self.fit_elasticity_model()
    
    # Get example structure for reference
    example_vol, example_growth, example_rates = self.parse_example_grid()
    
    print("Generating business-rule compliant combinations...")
    sampled_results = []
    
    for i in range(n_simulations):
        if i % 100 == 0:
            print(f"Running simulation {i}/{n_simulations}")
        
        # Generate volume tiers based on revenue distribution
        volume_quantiles = np.quantile(self.df[self.volume_col], [0.25, 0.5, 0.75])
        volume_tiers = [0] + sorted(np.random.choice(volume_quantiles, 3, replace=False)) + [np.inf]
        
        # Generate growth tiers (similar to your example: 0.08, 0.15, 0.2)
        growth_options = [0.05, 0.08, 0.1, 0.15, 0.2, 0.25]
        growth_tiers = [-np.inf] + sorted(np.random.choice(growth_options, 3, replace=False)) + [np.inf]
        
        n_vol_tiers = len(volume_tiers) - 1
        n_growth_tiers = len(growth_tiers) - 1
        
        # Generate rate grid that follows business rules
        rate_grid = self.generate_business_rule_rates(n_vol_tiers, n_growth_tiers)
        
        # Calculate results
        result_df = self.calculate_rebates(volume_tiers, growth_tiers, rate_grid)
        
        total_revenue = result_df['adjusted_revenue'].sum()
        total_rebates = result_df['rebate_amount'].sum()
        net_revenue = result_df['net_revenue'].sum()
        
        sampled_results.append({
            'volume_tiers': volume_tiers,
            'growth_tiers': growth_tiers,
            'rate_grid': rate_grid,
            'total_revenue': total_revenue,
            'total_rebates': total_rebates,
            'net_revenue': net_revenue,
            'rebate_rate': total_rebates / total_revenue if total_revenue > 0 else 0,
            'account_coverage': len(result_df[result_df['rebate_amount'] > 0]) / len(result_df)
        })
    
    self.results = pd.DataFrame(sampled_results)
    return self.results

def generate_business_rule_rates(self, n_vol_tiers, n_growth_tiers, max_rate=0.15):
    """Generate rate grids that follow typical business rules"""
    # Business rules:
    # 1. Rates generally increase with volume tier
    # 2. Rates generally increase with growth tier  
    # 3. Maximum rate cap
    # 4. Reasonable spreads between tiers
    
    base_rates = np.linspace(0.01, max_rate, n_vol_tiers + n_growth_tiers)
    rate_grid = np.zeros((n_vol_tiers, n_growth_tiers))
    
    for i in range(n_vol_tiers):
        for j in range(n_growth_tiers):
            # Base rate increases with both volume and growth
            base = 0.01 + (i * 0.02) + (j * 0.015)
            # Add some randomness
            variation = np.random.uniform(-0.005, 0.01)
            rate = min(max(base + variation, 0.005), max_rate)
            rate_grid[i][j] = rate
    
    # Ensure monotonicity: rates should not decrease in higher tiers
    for i in range(n_vol_tiers-1):
        for j in range(n_growth_tiers):
            if rate_grid[i][j] > rate_grid[i+1][j]:
                rate_grid[i+1][j] = rate_grid[i][j] + 0.005
                
    for j in range(n_growth_tiers-1):
        for i in range(n_vol_tiers):
            if rate_grid[i][j] > rate_grid[i][j+1]:
                rate_grid[i][j+1] = rate_grid[i][j] + 0.005
    
    return rate_grid