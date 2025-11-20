document.addEventListener('DOMContentLoaded', () => {
    const elasticityInput = document.getElementById('elasticity');
    const elasticityVal = document.getElementById('elasticity-val');
    const volBinsInput = document.getElementById('vol-bins-input');
    const growthBinsInput = document.getElementById('growth-bins-input');
    const runBtn = document.getElementById('run-btn');
    const statusIndicator = document.getElementById('status-indicator');

    // Update slider value display
    elasticityInput.addEventListener('input', (e) => {
        elasticityVal.textContent = e.target.value;
    });

    // Helper to parse bins from string
    function parseBins(inputStr, isVolume) {
        if (!inputStr) return [];
        const values = inputStr.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
        values.sort((a, b) => a - b);

        const bins = [];

        // Add catch-all for lower bound if needed
        if (values.length > 0) {
            const firstVal = values[0];
            if (isVolume) {
                // For volume, if start > 0, add [0, start]
                if (firstVal > 0) {
                    bins.push([0, firstVal]);
                }
            } else {
                // For growth, always add [-inf, start] to catch low/negative growth
                bins.push(['-inf', firstVal]);
            }
        }

        for (let i = 0; i < values.length; i++) {
            const lower = values[i];
            const upper = (i === values.length - 1) ? 'inf' : values[i + 1];
            bins.push([lower, upper]);
        }
        return bins;
    }

    // Run Optimization
    runBtn.addEventListener('click', async () => {
        const elasticity = parseFloat(elasticityInput.value);

        // Parse Bins
        let volumeBins, growthBins;
        try {
            volumeBins = parseBins(volBinsInput.value, true);
            growthBins = parseBins(growthBinsInput.value, false);

            if (volumeBins.length === 0 || growthBins.length === 0) {
                throw new Error("Invalid bin configuration");
            }
        } catch (e) {
            statusIndicator.textContent = "Error: Invalid Bin Inputs";
            return;
        }

        // UI State: Loading
        runBtn.disabled = true;
        runBtn.textContent = "Optimizing...";
        statusIndicator.textContent = "Running Simulation...";

        try {
            const response = await fetch('/optimize', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    elasticity: elasticity,
                    volume_bins: volumeBins,
                    growth_bins: growthBins
                })
            });

            const data = await response.json();

            if (response.ok) {
                renderResults(data);
                statusIndicator.textContent = "Optimization Complete";
            } else {
                statusIndicator.textContent = "Error: " + data.error;
            }

        } catch (error) {
            console.error('Error:', error);
            statusIndicator.textContent = "Network Error";
        } finally {
            runBtn.disabled = false;
            runBtn.textContent = "Run Optimization";
        }
    });

    function renderResults(data) {
        // Update KPIs
        document.getElementById('max-revenue').textContent = formatCurrency(data.max_revenue);
        document.getElementById('baseline-revenue').textContent = formatCurrency(data.baseline_revenue);
        document.getElementById('revenue-uplift').textContent = "+ " + formatCurrency(data.uplift);

        // Render Table
        const tableHead = document.querySelector('#results-table thead');
        const tableBody = document.querySelector('#results-table tbody');

        // Clear existing
        tableHead.innerHTML = '';
        tableBody.innerHTML = '';

        // Header
        const headerRow = document.createElement('tr');
        data.grid_headers.forEach(text => {
            const th = document.createElement('th');
            th.textContent = text;
            headerRow.appendChild(th);
        });
        tableHead.appendChild(headerRow);

        // Rows
        data.grid_rows.forEach(rowData => {
            const tr = document.createElement('tr');
            rowData.forEach((cellData, index) => {
                const td = document.createElement('td');
                td.textContent = cellData;

                // Add color intensity for rebate cells (skip first column)
                if (index > 0) {
                    const val = parseFloat(cellData.replace('%', ''));
                    if (val > 0) {
                        td.style.color = `rgba(16, 185, 129, ${0.5 + val / 30})`; // Green tint based on value
                    } else {
                        td.style.color = '#94a3b8'; // Gray for 0
                    }
                }

                tr.appendChild(td);
            });
            tableBody.appendChild(tr);
        });
    }

    function formatCurrency(value) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            maximumFractionDigits: 0
        }).format(value);
    }
});
