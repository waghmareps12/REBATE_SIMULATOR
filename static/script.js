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

    // --- Tab Switching ---
    const tabs = document.querySelectorAll('.tab-btn');
    const contents = document.querySelectorAll('.tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Remove active class
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));

            // Add active class
            tab.classList.add('active');
            document.getElementById(tab.dataset.tab).classList.add('active');
        });
    });

    // --- Static Calculator Logic ---
    const generateGridBtn = document.getElementById('generate-grid-btn');
    const calcStaticBtn = document.getElementById('calc-static-btn');
    const inputGridTable = document.getElementById('input-grid-table');

    generateGridBtn.addEventListener('click', () => {
        // Parse bins
        let volumeBins, growthBins;
        try {
            volumeBins = parseBins(volBinsInput.value, true);
            growthBins = parseBins(growthBinsInput.value, false);
        } catch (e) {
            alert("Invalid Bin Inputs");
            return;
        }

        // Render Input Table
        const thead = inputGridTable.querySelector('thead');
        const tbody = inputGridTable.querySelector('tbody');
        thead.innerHTML = '';
        tbody.innerHTML = '';

        // Header
        const headerRow = document.createElement('tr');
        const cornerTh = document.createElement('th');
        cornerTh.textContent = "Volume \\ Growth";
        headerRow.appendChild(cornerTh);

        growthBins.forEach(bin => {
            const th = document.createElement('th');
            const lower = (bin[0] * 100).toFixed(0);
            const upper = bin[1] === 'inf' ? '+' : (bin[1] * 100).toFixed(0) + '%';
            th.textContent = `${lower}% - ${upper}`;
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);

        // Rows
        volumeBins.forEach((vBin, rIdx) => {
            const tr = document.createElement('tr');
            const th = document.createElement('th');
            const lower = vBin[0].toLocaleString();
            const upper = vBin[1] === 'inf' ? '+' : vBin[1].toLocaleString();
            th.textContent = `${lower} - ${upper}`;
            tr.appendChild(th);

            growthBins.forEach((gBin, cIdx) => {
                const td = document.createElement('td');
                const input = document.createElement('input');
                input.type = "text";
                input.placeholder = "0%";
                input.dataset.r = rIdx;
                input.dataset.c = cIdx;
                td.appendChild(input);
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
    });

    calcStaticBtn.addEventListener('click', async () => {
        // Gather Inputs
        let volumeBins, growthBins;
        try {
            volumeBins = parseBins(volBinsInput.value, true);
            growthBins = parseBins(growthBinsInput.value, false);
        } catch (e) {
            alert("Invalid Bin Inputs");
            return;
        }

        // Gather Grid Data
        const inputs = inputGridTable.querySelectorAll('input');
        if (inputs.length === 0) {
            alert("Please generate the grid first.");
            return;
        }

        const rows = volumeBins.length;
        const cols = growthBins.length;
        const grid = Array(rows).fill().map(() => Array(cols).fill(0));

        inputs.forEach(input => {
            const r = parseInt(input.dataset.r);
            const c = parseInt(input.dataset.c);
            let val = input.value.trim();
            if (val.includes('%')) {
                val = parseFloat(val.replace('%', '')) / 100;
            } else {
                val = parseFloat(val);
            }
            if (isNaN(val)) val = 0;
            grid[r][c] = val;
        });

        // Send to Backend
        calcStaticBtn.textContent = "Calculating...";
        calcStaticBtn.disabled = true;

        try {
            const response = await fetch('/calculate_static', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    volume_bins: volumeBins,
                    growth_bins: growthBins,
                    rebate_grid: grid
                })
            });

            const data = await response.json();

            if (response.ok) {
                document.getElementById('static-revenue').textContent = formatCurrency(data.total_revenue);
                document.getElementById('static-cost').textContent = formatCurrency(data.total_rebate);
                document.getElementById('static-avg-rate').textContent = (data.avg_rate * 100).toFixed(2) + '%';
            } else {
                alert("Error: " + data.error);
            }

        } catch (e) {
            console.error(e);
            alert("Network Error");
        } finally {
            calcStaticBtn.textContent = "Calculate Cost";
            calcStaticBtn.disabled = false;
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
