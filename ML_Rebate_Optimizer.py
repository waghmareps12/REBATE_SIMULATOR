import pandas as pd
import numpy as np
from scipy.optimize import minimize, LinearConstraint
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import make_pipeline

class MLRebateOptimizer:
    def __init__(self, data_path):
        """
        Initialize the optimizer with data and train the ML model.
        """
        self.data_path = data_path
        self.df_base = pd.read_csv(data_path).rename(columns=str.lower)
        
        # Train ML Model
        self.model = self._train_model()
        
        self.volume_bins = None
        self.growth_bins = None
        self.df_processed = None
        self.agg_data = None

    def _train_model(self):
        """
        Train a Linear Regression model to predict Growth based on Rebate Rate.
        We use a simple model: Growth ~ Rebate Rate
        """
        # Prepare training data
        # We assume the input CSV has historical 'rebate_rate' and resulting 'growth'
        # If 'growth' isn't there, we calculate it
        df = self.df_base.copy()
        
        # Ensure numeric
        df['curryr_rev'] = pd.to_numeric(df['curryr_rev'], errors='coerce').fillna(0)
        df['prevyr_rev'] = pd.to_numeric(df['prevyr_rev'], errors='coerce').fillna(0)
        df['rebate_rate'] = pd.to_numeric(df['rebate_rate'], errors='coerce').fillna(0)
        
        # Calculate growth
        df['growth'] = (df['curryr_rev'] - df['prevyr_rev']) / df['prevyr_rev']
        df.replace([np.inf, -np.inf], 0, inplace=True)
        df['growth'] = df['growth'].fillna(0)
        
        # Filter outliers for better training
        df = df[(df['growth'] > -0.5) & (df['growth'] < 0.5)]
        
        X = df[['rebate_rate']]
        y = df['growth']
        
        # We force the intercept to be the average organic growth (when rebate is 0)
        # But for simplicity, we'll let the model learn it.
        # We use a simple Linear Regression: Growth = Alpha + Beta * Rebate
        model = LinearRegression()
        model.fit(X, y)
        
        print(f"ML Model Trained. Coefficient (Elasticity Proxy): {model.coef_[0]:.4f}, Intercept: {model.intercept_:.4f}")
        return model

    def set_bins(self, volume_bins, growth_bins):
        """
        Set the bin configurations and pre-process the dataframe indices.
        """
        self.volume_bins = volume_bins
        self.growth_bins = growth_bins
        
        # Create bin edges
        v_edges = [b[0] for b in volume_bins] + [volume_bins[-1][1]]
        g_edges = [g[0] for g in growth_bins] + [growth_bins[-1][1]]
        
        # Assign indices
        self.df_processed = self.df_base.copy()
        self.df_processed["growth_val"] = (self.df_processed["curryr_rev"] - self.df_processed["prevyr_rev"]) / self.df_processed["prevyr_rev"]
        
        self.df_processed["v_idx"] = pd.cut(self.df_processed["curryr_rev"], bins=v_edges, right=True).cat.codes
        self.df_processed["g_idx"] = pd.cut(self.df_processed["growth_val"], bins=g_edges, right=False).cat.codes
        
        # Filter valid bins
        self.df_processed = self.df_processed[(self.df_processed["v_idx"] >= 0) & (self.df_processed["g_idx"] >= 0)]
        
        # Pre-aggregate data: We need sum of prevyr_rev to project new revenue
        self.agg_data = self.df_processed.groupby(['v_idx', 'g_idx'])['prevyr_rev'].sum().reset_index()

    def objective_function(self, flat_rates):
        """
        Objective function to MINIMIZE (negative Net Revenue).
        """
        rows = len(self.volume_bins)
        cols = len(self.growth_bins)
        rates_grid = flat_rates.reshape((rows, cols))
        
        # Map rates to aggregated data
        applied_rates = rates_grid[self.agg_data['v_idx'], self.agg_data['g_idx']]
        
        # Predict Growth using ML Model
        # X_pred must match training features: [['rebate_rate']]
        X_pred = pd.DataFrame({'rebate_rate': applied_rates})
        predicted_growth = self.model.predict(X_pred)
        
        # Project Revenue
        base_revenue = self.agg_data['prevyr_rev']
        projected_revenue = base_revenue * (1 + predicted_growth)
        
        # Calculate Costs
        rebate_cost = projected_revenue * applied_rates
        net_revenue = projected_revenue - rebate_cost
        
        return -np.sum(net_revenue)

    def get_constraints(self, min_increment=0.01):
        """
        Generate monotonicity constraints using LinearConstraint.
        """
        rows = len(self.volume_bins)
        cols = len(self.growth_bins)
        num_vars = rows * cols
        
        A_rows = []
        lb = []
        ub = []
        
        def idx(r, c):
            return r * cols + c
        
        # Volume Monotonicity (Downwards)
        for r in range(1, rows):
            for c in range(cols):
                if self.growth_bins[c][1] <= 0.08: continue
                
                row = np.zeros(num_vars)
                row[idx(r, c)] = 1
                row[idx(r-1, c)] = -1
                A_rows.append(row)
                lb.append(min_increment)
                ub.append(np.inf)
                
        # Growth Monotonicity (Rightwards)
        for r in range(rows):
            for c in range(1, cols):
                if self.growth_bins[c][1] <= 0.08: continue
                if self.growth_bins[c-1][1] <= 0.08: continue
                
                row = np.zeros(num_vars)
                row[idx(r, c)] = 1
                row[idx(r, c-1)] = -1
                A_rows.append(row)
                lb.append(min_increment)
                ub.append(np.inf)
                
        if not A_rows: return None
        return LinearConstraint(A_rows, lb, ub)

    def optimize(self):
        """
        Run the optimization.
        """
        rows = len(self.volume_bins)
        cols = len(self.growth_bins)
        
        bounds = []
        initial_guess = []
        
        for r in range(rows):
            for c in range(cols):
                if self.growth_bins[c][1] <= 0.08:
                    bounds.append((0.0, 1e-9))
                    initial_guess.append(0.0)
                else:
                    bounds.append((0.01, 0.15))
                    initial_guess.append(0.01 + (r + c) * 0.01)
        
        initial_guess = np.array(initial_guess)
        cons = self.get_constraints(min_increment=0.01)
        constraints_arg = [cons] if cons else []
        
        print(f"Starting ML-based optimization...")
        
        result = minimize(
            self.objective_function,
            initial_guess,
            method='trust-constr',
            bounds=bounds,
            constraints=constraints_arg,
            options={'verbose': 1, 'maxiter': 1000}
        )
        
        if result.success:
            best_grid = result.x.reshape((rows, cols))
            return best_grid, -result.fun
        else:
            print("Optimization Failed:", result.message)
            best_grid = result.x.reshape((rows, cols))
            return best_grid, -result.fun

if __name__ == "__main__":
    # Test Run
    DATA_FILE = "DummyDataGpot2.csv"
    volume_bins = [(5000, 15000), (15000, 30000), (30000, 50000), (50000, np.inf)]
    growth_bins = [(0.00, 0.08), (0.08, 0.15), (0.15, 0.20), (0.20, np.inf)]
    
    optimizer = MLRebateOptimizer(DATA_FILE)
    optimizer.set_bins(volume_bins, growth_bins)
    
    best_grid, max_rev = optimizer.optimize()
    
    if best_grid is not None:
        print(f"\n🏆 ML Optimized Max Net Revenue: ${max_rev:,.2f}")
        print(np.round(best_grid, 2))
