from flask import Flask, render_template, request, jsonify
import pandas as pd
import numpy as np
from Optimized_Rebate_Simulator import RebateOptimizer
from ML_Rebate_Optimizer import MLRebateOptimizer

app = Flask(__name__)

# Global Optimizer Instances (Lazy loaded)
optimizer = None
ml_optimizer = None
DATA_FILE = "DummyDataGpot2.csv"

def get_optimizer():
    global optimizer
    if optimizer is None:
        # Default elasticity, can be overridden per request
        optimizer = RebateOptimizer(DATA_FILE, elasticity=2.0)
    return optimizer

def get_ml_optimizer():
    global ml_optimizer
    if ml_optimizer is None:
        ml_optimizer = MLRebateOptimizer(DATA_FILE)
    return ml_optimizer

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/optimize', methods=['POST'])
def optimize():
    try:
        data = request.get_json()
        
        # Extract parameters
        elasticity = float(data.get('elasticity', 2.0))
        use_ml_elasticity = data.get('use_ml_elasticity', False)
        
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
        if use_ml_elasticity:
            opt = get_ml_optimizer()
            # ML optimizer doesn't need explicit elasticity, it uses the model
        else:
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
        # Handle both optimizer types: RebateOptimizer uses 'curryr_rev', MLRebateOptimizer uses 'prevyr_rev'
        if 'curryr_rev' in opt.agg_data.columns:
            baseline_rev = opt.agg_data['curryr_rev'].sum()
        else:
            baseline_rev = opt.agg_data['prevyr_rev'].sum()
        uplift = max_revenue - baseline_rev
        
        # Create grid representation for frontend
        grid_data = []
        rows, cols = best_grid.shape
        
        # Filter out 0% rebate bins (growth <= 8%) from display
        display_cols = [c for c in range(cols) if growth_bins[c][1] > 0.08]
        
        # Header row (only show eligible growth bins)
        headers = ["Volume \\ Growth"] + [
            f"{growth_bins[c][0]*100:.0f}% - {growth_bins[c][1]*100:.0f}%" if growth_bins[c][1] != np.inf 
            else f"{growth_bins[c][0]*100:.0f}%+" 
            for c in display_cols
        ]
        
        # Data rows for Rebate Rates (only show eligible growth bins)
        grid_rows = []
        for r in range(rows):
            v_label = f"{int(volume_bins[r][0]):,} - {int(volume_bins[r][1]):,}" if volume_bins[r][1] != np.inf else f"{int(volume_bins[r][0]):,}+"
            row_data = [v_label] + [f"{best_grid[r, c]*100:.0f}%" for c in display_cols]
            grid_rows.append(row_data)

        # --- Calculate Summary Grid (Counts & Rebate Sums) ---
        
        # Determine which revenue column to use
        rev_col = 'curryr_rev' if 'curryr_rev' in opt.df_processed.columns else 'prevyr_rev'
        
        # Group by indices to get counts and revenue
        summary_stats = opt.df_processed.groupby(['v_idx', 'g_idx']).agg(
            count=(rev_col, 'count'),
            revenue=(rev_col, 'sum')
        ).reset_index()
        
        # Create a dictionary for easy lookup: (v, g) -> (count, revenue)
        stats_map = {}
        for _, row in summary_stats.iterrows():
            stats_map[(int(row['v_idx']), int(row['g_idx']))] = (int(row['count']), row['revenue'])
            
        
        summary_rows = []
        total_rebate = 0  # Track total rebate cost
        for r in range(rows):
            v_label = f"{int(volume_bins[r][0]):,} - {int(volume_bins[r][1]):,}" if volume_bins[r][1] != np.inf else f"{int(volume_bins[r][0]):,}+"
            row_data = [v_label]
            for c in display_cols:  # Only show eligible growth bins
                count, rev = stats_map.get((r, c), (0, 0.0))
                rate = best_grid[r, c]
                rebate_val = rev * rate
                total_rebate += rebate_val  # Accumulate total rebate
                # Format: "Count: 12 | $1.2M"
                # Shorten large numbers
                def fmt_money(val):
                    if val >= 1e6: return f"${val/1e6:.1f}M"
                    if val >= 1e3: return f"${val/1e3:.1f}K"
                    return f"${val:.0f}"
                
                cell_str = f"Cnt: {count} | Reb: {fmt_money(rebate_val)}"
                row_data.append(cell_str)
            summary_rows.append(row_data)
            
        return jsonify({
            "max_revenue": max_revenue,
            "baseline_revenue": baseline_rev,
            "uplift": uplift,
            "total_rebate": total_rebate,
            "grid_headers": headers,
            "grid_rows": grid_rows,
            "summary_rows": summary_rows
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
