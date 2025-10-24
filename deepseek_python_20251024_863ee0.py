def fit_elasticity_model(self):
    """Step 4: Elasticity modeling using log-log regression"""
    np.random.seed(42)
    
    # Simulate historical rebate rates (0% to 20%)
    self.df['simulated_rebate_rate'] = np.random.uniform(0, 0.2, len(self.df))
    
    # Simulate volume growth driven by rebates (realistic scenario)
    # Higher rebates -> higher volume growth, but with diminishing returns
    volume_growth_effect = 0.5 * self.df['simulated_rebate_rate']  # 50% pass-through
    
    # Simulate the resulting gross revenue (before rebates)
    self.df['simulated_gross_revenue'] = (
        self.df[self.volume_col] * 
        (1 + volume_growth_effect)  # Rebates drive volume growth
    )
    
    # Log-log regression: log(volume_growth) ~ log(1 + rebate_rate)
    X = np.log(1 + self.df['simulated_rebate_rate']).values.reshape(-1, 1)
    y = np.log(1 + volume_growth_effect)  # Log of growth factor
    
    self.elasticity_model = LinearRegression()
    self.elasticity_model.fit(X, y)
    self.elasticity_coef = self.elasticity_model.coef_[0]
    
    print(f"Estimated elasticity coefficient: {self.elasticity_coef:.4f}")

def calculate_rebates(self, volume_tiers, growth_tiers, rate_grid):
    """Corrected rebate calculation with elasticity"""
    df_temp = self.df.copy()
    
    # Assign tiers (same as before)
    df_temp['volume_tier'] = pd.cut(
        df_temp[self.volume_col], 
        bins=volume_tiers, 
        labels=range(len(volume_tiers)-1)
    )
    df_temp['growth_tier'] = pd.cut(
        df_temp['growth_rate'],
        bins=growth_tiers,
        labels=range(len(growth_tiers)-1)
    )
    
    rebates = []
    adjusted_revenues = []
    
    for _, row in df_temp.iterrows():
        vol_tier = row['volume_tier']
        growth_tier = row['growth_tier']
        
        if pd.notna(vol_tier) and pd.notna(growth_tier):
            rate = rate_grid[int(vol_tier)][int(growth_tier)]
            
            # Apply elasticity to predict volume growth from rebate rate
            if hasattr(self, 'elasticity_model'):
                predicted_growth = np.exp(
                    self.elasticity_model.predict(
                        np.log(1 + rate).reshape(1, -1)
                    )[0]
                ) - 1  # Convert back from log to percentage
                
                # Calculate gross revenue after volume growth
                gross_revenue = row[self.volume_col] * (1 + predicted_growth)
                
                # Calculate rebate amount and net revenue
                rebate_amount = rate * gross_revenue
                net_revenue = gross_revenue - rebate_amount
                
            else:
                # Without elasticity model, assume no volume growth
                gross_revenue = row[self.volume_col]
                rebate_amount = rate * gross_revenue
                net_revenue = gross_revenue - rebate_amount
                
            rebates.append(rebate_amount)
            adjusted_revenues.append(gross_revenue)
        else:
            rebates.append(0)
            adjusted_revenues.append(row[self.volume_col])
    
    df_temp['rebate_amount'] = rebates
    df_temp['adjusted_revenue'] = adjusted_revenues
    df_temp['net_revenue'] = df_temp['adjusted_revenue'] - df_temp['rebate_amount']
    
    return df_temp