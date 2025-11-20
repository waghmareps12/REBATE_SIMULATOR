# %%
import pandas as pd
import numpy as np
import os
import matplotlib.pyplot as plt

# %%


# === Function to generate monotonic grid ===
def generate_monotonic_grid(volume_bins, growth_bins):
    num_volumes = len(volume_bins)
    num_growths = len(growth_bins)
    grid = np.zeros((num_volumes, num_growths))
    
    min_rate = 0.01
    max_rate = 0.15
    
    for i in range(num_volumes):
        for j in range(num_growths):
            if growth_bins[j][1] <= 0.08:  # No rebate tier
                grid[i, j] = 0.00
            else:
                if i == 0 and j == 1:
                    rate = min_rate  # Lowest non-zero rebate
                else:
                    prev_vol_rate = grid[i-1, j] if i > 0 else min_rate
                    prev_growth_rate = grid[i, j-1] if j > 0 else min_rate
                    base_rate = max(prev_vol_rate, prev_growth_rate)
                    rate = min(base_rate + np.random.uniform(0.01, 0.03), max_rate)
                    if j == num_growths - 1:
                        # Ensure last growth tier > previous growth tier
                        rate = min(max(grid[i, j-1] + 0.01, rate), max_rate)
                grid[i, j] = round(rate, 2)
    
    df_grid = pd.DataFrame(
        grid,
        columns=[f"{round(g[0], 2)}-{round(g[1], 2) if g[1] != np.inf else 'inf'}" for g in growth_bins],
        index=[f"{int(v[0])}-{int(v[1])}" if v[1] != np.inf else f"{int(v[0])}+" for v in volume_bins]
    ).reset_index().rename(columns={"index": "Volume Bin"})
    
    return df_grid

# === Assign tiers ===
def assign_tiers_from_bins(df, volume_bins, growth_bins):
    v_edges = [b[0] for b in volume_bins] + [volume_bins[-1][1]]
    g_edges = [g[0] for g in growth_bins] + [growth_bins[-1][1]]
    v_labels = [f"V{i+1}" for i in range(len(volume_bins))]
    g_labels = [f"G{i+1}" for i in range(len(growth_bins))]
    df = df.copy()
    df["growth"] = (df["curryr_rev"] - df["prevyr_rev"]) / df["prevyr_rev"]
    df["volume_tier"] = pd.cut(df["curryr_rev"], bins=v_edges, labels=v_labels, right=True)
    df["growth_tier"] = pd.cut(df["growth"], bins=g_edges, labels=g_labels, right=False)
    return df

# === Compute rebate ===
def compute_rebate(row, rebate_rates):
    return rebate_rates.get((row["volume_tier"], row["growth_tier"]), 0) * row["curryr_rev"]



# %%

# === Multiple bin configurations ===
bin_configs = [
    {
        "volume_bins": [(5000, 15000), (15000, 30000), (30000, 50000), (50000, np.inf)],
        "growth_bins": [(0.00, 0.08), (0.08, 0.15), (0.15, 0.20), (0.20, np.inf)]
    },
    {
        "volume_bins": [(7000, 20000), (20000, 35000), (35000, 50000), (50000, np.inf)],
        "growth_bins": [(0.00, 0.08), (0.08, 0.12), (0.12, 0.18), (0.18, np.inf)]
    },
    {
        "volume_bins": [(10000, 20000), (20000, 40000), (40000, 50000), (50000, np.inf)],
        "growth_bins": [(0.00, 0.08), (0.08, 0.14), (0.14, 0.20), (0.20, np.inf)]
    }
]

# === Simulation parameters ===
num_iterations = 50
overall_best_rev = -np.inf
overall_best_grid = None
overall_best_config = None

# %%
# Paths
os.makedirs("grids", exist_ok=True)
data_file = r"DummyDataGpot2.csv"

# Load base data
df_base = pd.read_csv(data_file).rename(columns=str.lower)

# %%


# === Loop over configs ===
for config_index, config in enumerate(bin_configs, start=1):
    volume_bins = config["volume_bins"]
    growth_bins = config["growth_bins"]
    
    revenues = []
    best_net_revenue = -np.inf
    best_grid_df = None
    best_iter = None
    
    for iteration in range(1, num_iterations + 1):
        grid_df = generate_monotonic_grid(volume_bins, growth_bins)
        grid_path = f"grids/config{config_index}_grid_{iteration}.csv"
        grid_df.to_csv(grid_path, index=False)
        
        volume_labels = [f"V{i+1}" for i in range(len(volume_bins))]
        growth_labels = [f"G{i+1}" for i in range(len(growth_bins))]
        rebate_rates = {(v, g): float(grid_df.iloc[i, j+1]) for i, v in enumerate(volume_labels) for j, g in enumerate(growth_labels)}
        
        df = assign_tiers_from_bins(df_base, volume_bins, growth_bins)
        df["rebate"] = df.apply(lambda row: compute_rebate(row, rebate_rates), axis=1)
        
        net_revenue = df["curryr_rev"].sum() - df["rebate"].sum()
        revenues.append(net_revenue)
        
        if net_revenue > best_net_revenue:
            best_net_revenue = net_revenue
            best_grid_df = grid_df.copy()
            best_iter = iteration
    
    # Plot for this config
    plt.figure(figsize=(8, 5))
    plt.plot(range(1, num_iterations + 1), revenues, marker='o')
    plt.scatter(best_iter, best_net_revenue, color='red', label=f"Max Revenue: {best_net_revenue:,.2f}")
    plt.title(f"Config {config_index} - Net Revenue Across Iterations")
    plt.xlabel("Iteration")
    plt.ylabel("Net Revenue")
    plt.legend()
    plt.grid(True)
    plt.show()
    
    print(f"\n📊 Config {config_index} Max Revenue: {best_net_revenue:,.2f} (Iteration {best_iter})")
    print(best_grid_df)
    
    # Track overall best
    if best_net_revenue > overall_best_rev:
        overall_best_rev = best_net_revenue
        overall_best_grid = best_grid_df.copy()
        overall_best_config = config

# === Show overall best config + grid ===
print("\n🏆 Overall Best Config:")
print(overall_best_config)
print("\n🏅 Overall Best Grid Table:")
print(overall_best_grid)
print(f"\n✅ Overall Max Revenue: {overall_best_rev:,.2f}")


# %% [markdown]
# ![image.png](attachment:image.png)
# 

# %%


# %%


# %%


# %%


# %%


# %%


# %%


# %%


# %%


# %%
# # === Plot Net Revenue per Iteration ===
# import matplotlib.pyplot as plt
# plt.figure(figsize=(10, 6))
# plt.plot(range(1, num_iterations + 1), revenues, marker='o', label="Net Revenue")
# max_iter = revenues.index(best_net_revenue) + 1
# plt.scatter(max_iter, best_net_revenue, color='red', zorder=5, label=f"Max Revenue: {best_net_revenue:,.2f}")
# plt.title("Net Revenue Across Iterations")
# plt.xlabel("Iteration")
# plt.ylabel("Net Revenue")
# plt.legend()
# plt.grid(True)
# plt.show()

# # === Display Best Grid Table ===
# print(f"\n✅ Max Net Revenue: {best_net_revenue:,.2f} at Iteration {max_iter}")
# print(f"📄 Best Grid File: {best_grid_file}")
# print("\n🏆 Best Grid Table:\n")
# print(best_grid_df)


