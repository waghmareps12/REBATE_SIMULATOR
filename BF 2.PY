import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import optuna
from optuna.samplers import TPESampler
from optuna.pruners import SuccessiveHalvingPruner
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
from pathlib import Path
import time

# Set random seed for reproducibility
np.random.seed(42)


@dataclass
class BinConfig:
    """Configuration for volume and growth bins"""
    volume_bins: List[Tuple[float, float]]
    growth_bins: List[Tuple[float, float]]
    name: str = ""


@dataclass
class OptimizationParams:
    """Optimization parameters with sensible defaults"""
    min_rate: float = 0.01
    max_rate: float = 0.15
    output_dir: str = "grids"
    seed: int = 42


class RebateGridGenerator:
    """Generates monotonic rebate grids with proper constraints"""
    
    def __init__(self, config: BinConfig, params: OptimizationParams):
        self.config = config
        self.params = params
        self.n_vol = len(config.volume_bins)
        self.n_growth = len(config.growth_bins)
        self.volume_labels = [f"V{i+1}" for i in range(self.n_vol)]
        self.growth_labels = [f"G{i+1}" for i in range(self.n_growth)]
        
    def generate_grid(self, fixed_rates: Optional[np.ndarray] = None) -> pd.DataFrame:
        """
        Generate grid where rebate rates increase monotonically.
        If fixed_rates provided, use them instead of random generation.
        """
        if fixed_rates is not None:
            return self._to_dataframe(fixed_rates)
            
        grid = np.zeros((self.n_vol, self.n_growth))
        
        # Eligible positions (growth > 0.08)
        eligible_positions = [
            (i, j) for i in range(self.n_vol)
            for j, (g_low, g_high) in enumerate(self.config.growth_bins)
            if g_high > 0.08
        ]
        
        if not eligible_positions:
            return self._to_dataframe(grid)
        
        # Sort for monotonic processing
        eligible_positions.sort()
        
        # Pre-generate random increments
        increments = np.random.uniform(0.01, 0.04, size=len(eligible_positions))
        
        current_rate = self.params.min_rate
        
        for idx, (i, j) in enumerate(eligible_positions):
            # Enforce monotonicity from previous tiers
            prev_rates = []
            if i > 0:
                prev_rates.append(grid[i-1, j])
            if j > 0:
                prev_rates.append(grid[i, j-1])
            
            base_rate = max(self.params.min_rate, *prev_rates, current_rate)
            new_rate = min(base_rate + increments[idx], self.params.max_rate)
            
            # Ensure meaningful spread in highest tier
            if j == self.n_growth - 1 and j > 0:
                new_rate = min(max(grid[i, j-1] + 0.02, new_rate), self.params.max_rate)
            
            grid[i, j] = round(new_rate, 4)
            current_rate = new_rate
        
        return self._to_dataframe(grid)
    
    def _to_dataframe(self, grid: np.ndarray) -> pd.DataFrame:
        """Convert numpy grid to formatted DataFrame"""
        growth_cols = [
            f"{g[0]:.2f}-{g[1]:.2f}" if g[1] != np.inf else f"{g[0]:.2f}+"
            for g in self.config.growth_bins
        ]
        volume_index = [
            f"{int(v[0]):,}-{int(v[1]):,}" if v[1] != np.inf else f"{int(v[0]):,}+"
            for v in self.config.volume_bins
        ]
        
        return pd.DataFrame(grid, columns=growth_cols, index=volume_index).reset_index().rename(columns={"index": "Volume Bin"})


class RebateCalculator:
    """Fast rebate calculation using vectorized operations"""
    
    def __init__(self, data: pd.DataFrame):
        self.data = data.copy()
        if 'growth' not in self.data.columns:
            self.data['growth'] = np.where(
                self.data['prevyr_rev'] > 0,
                (self.data['curryr_rev'] - self.data['prevyr_rev']) / self.data['prevyr_rev'],
                0
            )
    
    def assign_tiers(self, config: BinConfig) -> pd.DataFrame:
        """Vectorized tier assignment with NaN handling"""
        df = self.data.copy()
        
        # Create bin edges
        vol_edges = [b[0] for b in config.volume_bins] + [config.volume_bins[-1][1]]
        growth_edges = [b[0] for b in config.growth_bins] + [config.growth_bins[-1][1]]
        
        # Ensure edges cover all data
        vol_edges[0] = min(df['curryr_rev'].min(), vol_edges[0])
        vol_edges[-1] = max(df['curryr_rev'].max(), vol_edges[-1]) if vol_edges[-1] != np.inf else np.inf
        growth_edges[0] = min(df['growth'].min(), growth_edges[0])
        growth_edges[-1] = max(df['growth'].max(), growth_edges[-1]) if growth_edges[-1] != np.inf else np.inf
        
        vol_labels = [f"V{i+1}" for i in range(len(config.volume_bins))]
        growth_labels = [f"G{i+1}" for i in range(len(config.growth_bins))]
        
        # Assign tiers
        df["volume_tier"] = pd.cut(
            df["curryr_rev"], 
            bins=vol_edges, 
            labels=vol_labels, 
            right=True, 
            include_lowest=True
        )
        df["growth_tier"] = pd.cut(
            df["growth"], 
            bins=growth_edges, 
            labels=growth_labels, 
            right=False, 
            include_lowest=True
        )
        
        # Fill any remaining NaN (edge cases)
        df["volume_tier"] = df["volume_tier"].fillna("V1")
        df["growth_tier"] = df["growth_tier"].fillna("G1")
        
        return df
    
    def calculate_rebates(self, df: pd.DataFrame, grid_df: pd.DataFrame) -> pd.DataFrame:
        """Optimal calculation using numpy indexing with NaN protection"""
        result = df.copy()
        grid_array = grid_df.iloc[:, 1:].values
        
        # Create tier mapping for faster lookup
        vol_mapping = {f"V{i+1}": i for i in range(grid_array.shape[0])}
        growth_mapping = {f"G{i+1}": i for i in range(grid_array.shape[1])}
        
        # Map tier strings to integer indices
        vol_idx = result['volume_tier'].map(vol_mapping).fillna(0).astype(int)
        growth_idx = result['growth_tier'].map(growth_mapping).fillna(0).astype(int)
        
        # Clip indices to valid range
        vol_idx = np.clip(vol_idx, 0, grid_array.shape[0] - 1)
        growth_idx = np.clip(growth_idx, 0, grid_array.shape[1] - 1)
        
        # Vectorized rate lookup
        result['rebate_rate'] = grid_array[vol_idx, growth_idx]
        result['rebate'] = result['rebate_rate'] * result['curryr_rev']
        
        return result


class HybridOptimizer:
    """Jointly optimizes bin configurations AND rebate rates using Optuna"""
    
    def __init__(self, data: pd.DataFrame, params: OptimizationParams):
        self.data = data
        self.params = params
        self.calculator = RebateCalculator(data)
        
    def objective(self, trial: optuna.Trial) -> float:
        """Unified objective for joint optimization"""
        
        # === STEP 1: Propose Bin Configuration ===
        
        # Volume bin boundaries (monotonic)
        vol1 = trial.suggest_int("vol_boundary_1", 7000, 20000)
        vol2 = trial.suggest_int("vol_boundary_2", vol1 + 3000, 40000)
        vol3 = trial.suggest_int("vol_boundary_3", vol2 + 3000, 70000)
        
        # Growth bin boundaries (first fixed at 0.08)
        grow1 = 0.08
        grow2 = trial.suggest_float("growth_boundary_2", 0.10, 0.18, step=0.01)
        grow3 = trial.suggest_float("growth_boundary_3", max(grow2 + 0.03, 0.16), 0.28, step=0.01)
        
        # Construct bins
        config = BinConfig(
            name=f"trial_{trial.number}",
            volume_bins=[
                (5000, vol1),
                (vol1, vol2),
                (vol2, vol3),
                (vol3, np.inf)
            ],
            growth_bins=[
                (0.00, grow1),
                (grow1, grow2),
                (grow2, grow3),
                (grow3, np.inf)
            ]
        )
        
        # === STEP 2: Assign tiers ===
        df_tiers = self.calculator.assign_tiers(config)
        
        # Check for assignment failures
        if df_tiers['volume_tier'].isna().any() or df_tiers['growth_tier'].isna().any():
            return -1e9  # Invalid configuration
        
        # === STEP 3: Propose Rebate Rates with PROPER Monotonic Constraints ===
        
        grid = np.zeros((4, 4))
        
        for i in range(4):
            for j in range(4):
                # No rebate for growth <=8%
                if config.growth_bins[j][1] <= 0.08:
                    grid[i, j] = 0.0
                else:
                    # Calculate minimum allowed rate from monotonic constraints
                    min_allowed = self.params.min_rate
                    
                    # Must be >= previous volume tier at same growth
                    if i > 0:
                        min_allowed = max(min_allowed, grid[i-1, j])
                    
                    # Must be >= previous growth tier at same volume
                    if j > 0:
                        min_allowed = max(min_allowed, grid[i, j-1])
                    
                    # Add small epsilon to encourage exploration
                    min_allowed = min(min_allowed + 0.005, self.params.max_rate)
                    
                    # Let Optuna explore freely from min_allowed to max_rate
                    # NO step constraint to allow full exploration
                    grid[i, j] = trial.suggest_float(
                        f"rate_V{i+1}_G{j+1}",
                        min_allowed,
                        self.params.max_rate
                    )
        
        # === STEP 4: Evaluate Revenue ===
        
        grid_df = RebateGridGenerator(config, self.params)._to_dataframe(grid)
        df_results = self.calculator.calculate_rebates(df_tiers, grid_df)
        
        net_revenue = df_results['curryr_rev'].sum() - df_results['rebate'].sum()
        
        # Store for later retrieval
        trial.set_user_attr("config", config.__dict__)
        trial.set_user_attr("grid", grid_df.to_dict())
        
        return net_revenue
    
    def optimize(self, n_trials: int = 500, timeout: Optional[int] = None) -> Dict:
        """Run joint optimization"""
        
        study = optuna.create_study(
            direction="maximize",
            sampler=TPESampler(
                seed=self.params.seed,
                multivariate=True,
                n_startup_trials=100  # More random exploration initially
            ),
            pruner=SuccessiveHalvingPruner(
                min_resource=30,
                reduction_factor=4
            ),
            study_name="rebate_optimization"
        )
        
        study.optimize(
            self.objective, 
            n_trials=n_trials,
            timeout=timeout,
            show_progress_bar=True,
            n_jobs=1
        )
        
        return {
            'best_value': study.best_value,
            'best_params': study.best_params,
            'best_trial': study.best_trial,
            'study': study
        }


def extract_config_from_params(params: Dict) -> BinConfig:
    """Convert Optuna parameters to BinConfig object"""
    vol1 = params['vol_boundary_1']
    vol2 = params['vol_boundary_2']
    vol3 = params['vol_boundary_3']
    grow2 = params['growth_boundary_2']
    grow3 = params['growth_boundary_3']
    
    return BinConfig(
        name="OPTIMAL_CONFIG",
        volume_bins=[
            (5000, vol1),
            (vol1, vol2),
            (vol2, vol3),
            (vol3, np.inf)
        ],
        growth_bins=[
            (0.00, 0.08),
            (0.08, grow2),
            (grow2, grow3),
            (grow3, np.inf)
        ]
    )


def extract_grid_from_params(params: Dict, config: BinConfig) -> pd.DataFrame:
    """Extract grid rates from Optuna parameters"""
    grid = np.zeros((4, 4))
    
    for i in range(4):
        for j in range(4):
            param_name = f"rate_V{i+1}_G{j+1}"
            if param_name in params:
                grid[i, j] = params[param_name]
    
    return RebateGridGenerator(config, OptimizationParams())._to_dataframe(grid)


def visualize_optuna_results(study: optuna.Study):
    """Create comprehensive Optuna visualizations"""
    try:
        fig = optuna.visualization.plot_optimization_history(study)
        fig.show()
        fig = optuna.visualization.plot_param_importances(study)
        fig.show()
        fig = optuna.visualization.plot_parallel_coordinate(study)
        fig.show()
        fig = optuna.visualization.plot_slice(study)
        fig.show()
    except Exception as e:
        print(f"⚠️  Visualization failed: {e}")


def main():
    """Main execution with hybrid optimization"""
    
    DATA_FILE = "DummyDataGpot2.csv"
    OUTPUT_DIR = "grids"
    
    Path(OUTPUT_DIR).mkdir(exist_ok=True, parents=True)
    
    try:
        df = pd.read_csv(DATA_FILE).rename(columns=str.lower)
        print(f"📂 Loaded {len(df):,} records from {DATA_FILE}")
        print(f"💰 Total Revenue: ${df['curryr_rev'].sum():,.2f}")
    except FileNotFoundError:
        print(f"❌ Error: {DATA_FILE} not found")
        return
    
    # Clean data
    df = df.dropna(subset=['curryr_rev', 'prevyr_rev'])
    df = df[df['prevyr_rev'] > 0]
    df = df[df['curryr_rev'] >= 0]
    
    params = OptimizationParams(
        min_rate=0.01,
        max_rate=0.15,
        output_dir=OUTPUT_DIR,
        seed=42
    )
    
    print("\n🚀 Starting Hybrid Optimization...")
    print(f"   Target trials: 500 (this may take 5-10 minutes)")
    print("─" * 70)
    
    optimizer = HybridOptimizer(df, params)
    
    start_time = time.time()
    result = optimizer.optimize(n_trials=500, timeout=3600)
    
    best_config = extract_config_from_params(result['best_params'])
    best_grid = extract_grid_from_params(result['best_params'], best_config)
    best_revenue = result['best_value']
    
    print("\n" + "═" * 70)
    print("🏆 OPTIMAL SOLUTION FOUND")
    print("═" * 70)
    print(f"💰 Max Net Revenue: ${best_revenue:,.2f}")
    
    baseline_revenue = df['curryr_rev'].sum()
    improvement = ((best_revenue / baseline_revenue) - 1) * 100 if baseline_revenue > 0 else 0
    print(f"📈 Improvement: {improvement:.2f}% over baseline")
    print(f"⏱️  Optimization Time: {time.time() - start_time:.2f}s")
    
    print("\n📦 OPTIMAL VOLUME BINS:")
    for i, (low, high) in enumerate(best_config.volume_bins, 1):
        high_str = f"{int(high):,}" if high != np.inf else "∞"
        print(f"   V{i}: ${int(low):,} - ${high_str}")
    
    print("\n📊 OPTIMAL GROWTH BINS:")
    for i, (low, high) in enumerate(best_config.growth_bins, 1):
        high_str = f"{high:.1%}" if high != np.inf else "∞"
        print(f"   G{i}: {low:.1%} - {high_str}")
    
    print("\n🎯 OPTIMAL REBATE GRID:")
    print(best_grid.to_string(index=False))
    
    best_grid.to_csv(f"{OUTPUT_DIR}/OPTIMAL_GRID.csv", index=False)
    
    # Heatmap
    plt.figure(figsize=(12, 8))
    plt.suptitle('Rebate Rate Heatmap (Optimal Configuration)', fontsize=16, fontweight='bold')
    
    grid_values = best_grid.iloc[:, 1:].values
    growth_labels = best_grid.columns[1:]
    volume_labels = best_grid['Volume Bin']
    
    im = plt.imshow(grid_values, cmap='RdYlGn', aspect='auto', vmin=0, vmax=0.15)
    
    for i in range(len(volume_labels)):
        for j in range(len(growth_labels)):
            text = plt.text(j, i, f"{grid_values[i, j]:.1%}",
                           ha="center", va="center", color="black", fontweight='bold')
    
    plt.colorbar(im, label='Rebate Rate').set_ticks([0, 0.05, 0.10, 0.15])
    plt.xticks(range(len(growth_labels)), growth_labels, rotation=45, ha='right')
    plt.yticks(range(len(volume_labels)), volume_labels)
    plt.xlabel('Growth Tier', fontweight='bold')
    plt.ylabel('Volume Tier', fontweight='bold')
    plt.tight_layout()
    plt.show()
    
    try:
        print("\n📊 Generating Optuna visualizations...")
        visualize_optuna_results(result['study'])
    except Exception as e:
        print(f"⚠️  Could not generate Optuna visualizations: {e}")
    
    print("\n✅ Optimization complete. Best grid saved to:", f"{OUTPUT_DIR}/OPTIMAL_GRID.csv")


if __name__ == "__main__":
    main()