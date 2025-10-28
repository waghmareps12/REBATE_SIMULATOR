from flask import Flask, render_template, request, jsonify
import pandas as pd
import numpy as np
import re
import io

app = Flask(__name__)

# --- Helper Functions from original script ---

def parse_grid(grid_data):
    """Parses the grid data to extract bins and rates, ignoring errors."""
    if not grid_data or len(grid_data) < 2:
        return [], [], {}

    grid_df = pd.DataFrame(grid_data[1:], columns=grid_data[0])

    # Extract volume bins from first column
    volume_bins = []
    for row in grid_df.iloc[:, 0]:
        try:
            if "+" in str(row):
                lower = float(re.findall(r'\d+\.?\d*', str(row))[0])
                volume_bins.append((lower, np.inf))
            else:
                nums = re.findall(r'\d+\.?\d*', str(row))
                if len(nums) == 2:
                    lower, upper = map(float, nums)
                    volume_bins.append((lower, upper))
        except (ValueError, IndexError):
            continue # Ignore rows that can't be parsed

    # Extract growth bins from column headers
    growth_bins = []
    for x in grid_df.columns[1:]:
        try:
            growth_bins.append(float(x))
        except ValueError:
            continue # Ignore columns that can't be parsed
    growth_bins.sort()
    growth_bins.append(np.inf)

    # Build rate dictionary
    volume_labels = [f"V{i+1}" for i in range(len(volume_bins))]
    growth_labels = [f"G{i+1}" for i in range(len(growth_bins)-1)]

    rebate_rates = {}
    for i, v_label in enumerate(volume_labels):
        for j, g_label in enumerate(growth_labels):
            rate_str = str(grid_df.iloc[i, j+1]).strip()
            try:
                if '%' in rate_str:
                    rate = float(rate_str.replace('%', '')) / 100.0
                else:
                    rate_val = float(rate_str)
                    if rate_val > 1.0:
                        rate = rate_val / 100.0
                    else:
                        rate = rate_val
                rebate_rates[(v_label, g_label)] = rate
            except (ValueError, IndexError):
                rebate_rates[(v_label, g_label)] = 0

    return volume_bins, growth_bins, rebate_rates

def assign_tiers_from_bins(df, volume_bins, growth_bins):
    """Assigns volume and growth tiers to the account data."""
    v_edges = [b[0] for b in volume_bins] + [volume_bins[-1][1]]
    v_labels = [f"V{i+1}" for i in range(len(volume_bins))]
    g_labels = [f"G{i+1}" for i in range(len(growth_bins)-1)]

    df = df.copy()
    # Ensure revenue columns are numeric
    df["curryr_rev"] = pd.to_numeric(df["curryr_rev"], errors='coerce')
    df["prevyr_rev"] = pd.to_numeric(df["prevyr_rev"], errors='coerce')

    # Calculate growth, handle division by zero
    df["growth"] = (df["curryr_rev"] - df["prevyr_rev"]) / df["prevyr_rev"]
    df["growth"].replace([np.inf, -np.inf], 0, inplace=True) # Replace inf with 0
    df["growth"].fillna(0, inplace=True) # Fill NaN with 0 for accounts with 0 prevyr_rev

    df["volume_tier"] = pd.cut(df["curryr_rev"], bins=v_edges, labels=v_labels, right=False, include_lowest=True)
    df["growth_tier"] = pd.cut(df["growth"], bins=growth_bins, labels=g_labels, right=False, include_lowest=True)

    return df

def compute_rebate(row, rebate_rates):
    """Computes the rebate for a single row."""
    tier_tuple = (row["volume_tier"], row["growth_tier"])
    rate = rebate_rates.get(tier_tuple, 0)
    return rate * row["curryr_rev"]

# --- Flask Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/calculate', methods=['POST'])
def calculate():
    data = request.get_json()
    grid_data = data.get('grid')
    accounts_data = data.get('accounts')

    if not grid_data or not accounts_data:
        return jsonify({"error": "Grid and accounts data are required."}), 400

    try:
        # Create DataFrame for accounts
        accounts_df = pd.DataFrame(accounts_data[1:], columns=accounts_data[0])
        
        # Parse grid and get rates/bins
        volume_bins, growth_bins, rebate_rates = parse_grid(grid_data)

        # Assign tiers
        accounts_df = assign_tiers_from_bins(accounts_df, volume_bins, growth_bins)

        # Compute rebates
        accounts_df["rebate"] = accounts_df.apply(lambda row: compute_rebate(row, rebate_rates), axis=1)
        
        # Prepare results
        total_rebate = accounts_df["rebate"].sum()
        
        # Convert tiers to string for JSON serialization
        accounts_df['volume_tier'] = accounts_df['volume_tier'].astype(str)
        accounts_df['growth_tier'] = accounts_df['growth_tier'].astype(str)

        summary = accounts_df.groupby(["volume_tier", "growth_tier"])["rebate"].agg(["count", "sum"]).reset_index()

        results = {
            "table": accounts_df.to_dict(orient='records'),
            "total_rebate": total_rebate,
            "summary": summary.to_dict(orient='records')
        }
        
        return jsonify(results)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
