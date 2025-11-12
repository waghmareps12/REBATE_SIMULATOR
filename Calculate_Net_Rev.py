# %%
import pandas as pd
import numpy as np
import re

# %%
# --- 1. Upload CSV for grid ---
# grid_file = st.file_uploader("Upload Rebate Grid CSV", type=["csv"])
# if grid_file:
    # grid_df = pd.read_csv(grid_file)
    # st.subheader("📋 Uploaded Rebate Grid")
grid_df = pd.read_csv(rf"C:\Users\750040697\OneDrive - Genpact\Documents\REBATE_SIMULATOR\REBATE_SIMULATOR\program_grid.csv")

# --- 2. Parse bins and rates ---
# Extract volume bins from first column
volume_bins = []
for row in grid_df.iloc[:, 0]:
    if "+" in str(row):
        lower = float(re.findall(r'\d+', str(row))[0])
        volume_bins.append((lower, np.inf))
    else:
        nums = re.findall(r'\d+', str(row))
        lower, upper = map(float, nums)
        volume_bins.append((lower, upper))

# Extract growth bins from column headers
growth_bins = [float(x) for x in grid_df.columns[1:]]
growth_bins.append(np.inf)

# Build rate dictionary
volume_labels = [f"V{i+1}" for i in range(len(volume_bins))]
growth_labels = [f"G{i+1}" for i in range(len(growth_bins)-1)]

rebate_rates = {}
for i, v_label in enumerate(volume_labels):
    for j, g_label in enumerate(growth_labels):
        rebate_rates[(v_label, g_label)] = float(grid_df.iloc[i, j+1])

# else:
#     st.warning("Upload a CSV to get started.")
#     st.stop()



# --- 4. Assign tiers dynamically ---
def assign_tiers_from_bins(df, volume_bins, growth_bins):
    v_edges = [b[0] for b in volume_bins] + [volume_bins[-1][1]]  # Build numeric edges
    v_labels = [f"V{i+1}" for i in range(len(volume_bins))]
    g_labels = [f"G{i+1}" for i in range(len(growth_bins)-1)]

    df = df.copy()
    df["growth"] = (df["curryr_rev"] - df["prevyr_rev"]) / df["prevyr_rev"]
    # 3. Assign tiers using curryr_rev for volume and calculated growth for growth
    df["volume_tier"] = pd.cut(df["curryr_rev"], bins=v_edges, labels=v_labels, right=True)
    df["growth_tier"] = pd.cut(df["growth"], bins=growth_bins, labels=g_labels, right=False)
    # 4. Optionally keep rfp_group and rfp_name for downstream grouping
    df = df[["rfp_group", "rfp_name", "curryr_rev", "prevyr_rev", "growth", "volume_tier", "growth_tier"]]
    return df

# %%
df = pd.read_csv(rf"C:\Users\750040697\OneDrive - Genpact\Documents\REBATE_SIMULATOR\REBATE_SIMULATOR\DummyDataGpot2.csv").rename(columns=str.lower)
df = assign_tiers_from_bins(df, volume_bins, growth_bins)

    # --- 5. Compute rebates ---
def compute_rebate_rate(row):
        return rebate_rates.get((row["volume_tier"], row["growth_tier"]), 0) 
def compute_rebate(row):
        return rebate_rates.get((row["volume_tier"], row["growth_tier"]), 0) * row["curryr_rev"]
df["rebate_rate"] = df.apply(compute_rebate_rate, axis=1)
df["rebate"] = df.apply(compute_rebate, axis=1)

# %%
net_revenue =df["curryr_rev"].sum() -  df["rebate"].sum()

# %%
df.to_csv(rf"C:\Users\750040697\OneDrive - Genpact\Documents\REBATE_SIMULATOR\REBATE_SIMULATOR\DummyDataGpot2.csv", index=False )

# %%



