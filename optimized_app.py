from flask import Flask, render_template, request, jsonify
import pandas as pd
import numpy as np
from Optimized_Rebate_Simulator import RebateOptimizer

app = Flask(__name__)

# Global Optimizer Instance (Lazy loaded)
optimizer = None
DATA_FILE = "DummyDataGpot2.csv"

def get_optimizer():
    global optimizer
    if optimizer is None:
        # Default elasticity, can be overridden per request
        optimizer = RebateOptimizer(DATA_FILE, elasticity=2.0)
    return optimizer

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/optimize', methods=['POST'])
def optimize():
    try:
        data = request.get_json()
        
        # Extract parameters
        elasticity = float(data.get('elasticity', 2.0))
        
        # Parse bins from frontend
        # Expected format: volume_bins=[[5000, 15000], ...], growth_bins=[[0, 0.08], ...]
        vol_bins_raw = data.get('volume_bins')
        growth_bins_raw = data.get('growth_bins')
        
        # Convert to tuples/inf
        volume_bins = []
        for b in vol_bins_raw:
            upper = np.inf if b[1] == 'inf' or b[1] is None else float(b[1])
            volume_bins.append((float(b[0]), upper))
            
        growth_bins = []
        for b in growth_bins_raw:
            upper = np.inf if b[1] == 'inf' or b[1] is None else float(b[1])
            growth_bins.append((float(b[0]), upper))
            
        # Run Optimization
        opt = get_optimizer()
        opt.elasticity = elasticity
        opt.set_bins(volume_bins, growth_bins)
        
        best_grid, max_revenue = opt.optimize()
        
        if best_grid is None:
            return jsonify({"error": "Optimization failed to converge."}), 500
            
        # Format results
        # Round to 2 decimal places (whole percentages)
        best_grid = np.round(best_grid, 2)
        
        # Calculate baseline revenue for comparison
        baseline_rev = opt.agg_data['curryr_rev'].sum()
        uplift = max_revenue - baseline_rev
        
        # Create grid representation for frontend
        grid_data = []
        rows, cols = best_grid.shape
        
        # Header row
        headers = ["Volume \\ Growth"] + [f"{g[0]*100:.0f}% - {g[1]*100:.0f}%" if g[1] != np.inf else f"{g[0]*100:.0f}%+" for g in growth_bins]
        
        # Data rows
        grid_rows = []
        for r in range(rows):
            v_label = f"{int(volume_bins[r][0]):,} - {int(volume_bins[r][1]):,}" if volume_bins[r][1] != np.inf else f"{int(volume_bins[r][0]):,}+"
            row_data = [v_label] + [f"{val*100:.0f}%" for val in best_grid[r]]
            grid_rows.append(row_data)
            
        return jsonify({
            "max_revenue": max_revenue,
            "baseline_revenue": baseline_rev,
            "uplift": uplift,
            "grid_headers": headers,
            "grid_rows": grid_rows
        })

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/calculate_static', methods=['POST'])
def calculate_static():
    try:
        data = request.get_json()
        volume_bins = data.get('volume_bins')
        growth_bins = data.get('growth_bins')
        rebate_grid = data.get('rebate_grid') # List of lists matching the grid dimensions

        if not volume_bins or not growth_bins or not rebate_grid:
            return jsonify({"error": "Missing configuration"}), 400

        # Use the optimizer's data loading logic to get a fresh copy
        opt = get_optimizer()
        df = opt.df_base.copy()
        
        # Ensure numeric
        df['curryr_rev'] = pd.to_numeric(df['curryr_rev'], errors='coerce').fillna(0)
        df['prevyr_rev'] = pd.to_numeric(df['prevyr_rev'], errors='coerce').fillna(0)
        
        # Calculate growth
        df['growth'] = (df['curryr_rev'] - df['prevyr_rev']) / df['prevyr_rev']
        df.replace([np.inf, -np.inf], 0, inplace=True)
        df['growth'] = df['growth'].fillna(0)

        # Create Bin Edges
        # Convert frontend bins (lists) to edges
        # volume_bins: [[5000, 15000], ...]
        v_edges = [float(b[0]) for b in volume_bins]
        last_v = volume_bins[-1][1]
        v_edges.append(np.inf if last_v == 'inf' or last_v is None else float(last_v))
        
        g_edges = [float(b[0]) for b in growth_bins]
        last_g = growth_bins[-1][1]
        g_edges.append(np.inf if last_g == 'inf' or last_g is None else float(last_g))
        
        # Assign Tiers (Indices)
        # We use pd.cut to get the index of the bin
        df['v_idx'] = pd.cut(df['curryr_rev'], bins=v_edges, right=True, labels=False)
        df['g_idx'] = pd.cut(df['growth'], bins=g_edges, right=False, labels=False)
        
        # Filter out records that don't fit in any bin (if any)
        df = df.dropna(subset=['v_idx', 'g_idx'])
        df['v_idx'] = df['v_idx'].astype(int)
        df['g_idx'] = df['g_idx'].astype(int)

        # Calculate Rebate
        # rebate_grid is a list of lists: grid[row][col] -> grid[v_idx][g_idx]
        # We can map it efficiently
        
        def get_rate(row):
            try:
                # rebate_grid is row-major: grid[v_idx][g_idx]
                val = rebate_grid[row['v_idx']][row['g_idx']]
                # Handle string percentage input if necessary, but frontend should send floats
                if isinstance(val, str):
                    val = float(val.replace('%', '')) / 100.0
                return float(val)
            except:
                return 0.0

        df['rate'] = df.apply(get_rate, axis=1)
        df['rebate_cost'] = df['curryr_rev'] * df['rate']
        
        total_revenue = df['curryr_rev'].sum()
        total_rebate = df['rebate_cost'].sum()
        avg_rate = (total_rebate / total_revenue) if total_revenue > 0 else 0
        
        return jsonify({
            "total_revenue": total_revenue,
            "total_rebate": total_rebate,
            "avg_rate": avg_rate,
            "message": "Calculation Successful"
        })

    except Exception as e:
        print(f"Static Calc Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
