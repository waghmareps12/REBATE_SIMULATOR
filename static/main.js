document.addEventListener('DOMContentLoaded', () => {
    // File inputs
    const gridFileInput = document.getElementById('grid-file');
    const accountsFileInput = document.getElementById('accounts-file');

    // Buttons
    const addRowBtn = document.getElementById('add-row');
    const removeRowBtn = document.getElementById('remove-row');
    const addColBtn = document.getElementById('add-col');
    const removeColBtn = document.getElementById('remove-col');

    // Data stores
    let gridData = null;
    let accountsData = null;

    // Event Listeners
    gridFileInput.addEventListener('change', (event) => handleFileSelect(event, 'grid'));
    accountsFileInput.addEventListener('change', (event) => handleFileSelect(event, 'accounts'));
    addRowBtn.addEventListener('click', addRow);
    removeRowBtn.addEventListener('click', removeRow);
    addColBtn.addEventListener('click', addCol);
    removeColBtn.addEventListener('click', removeCol);

    function handleFileSelect(event, type) {
        const file = event.target.files[0];
        if (!file) return;

        Papa.parse(file, {
            header: false,
            skipEmptyLines: true,
            complete: (results) => {
                if (type === 'grid') {
                    gridData = results.data;
                    displayGrid(gridData);
                } else {
                    accountsData = results.data;
                }
                
                if (gridData && accountsData) {
                    calculateRebates();
                }
            }
        });
    }

    function displayGrid(data) {
        if (!data) return;
        const displayDiv = document.getElementById('grid-display');
        let table = '<table class="table table-bordered table-sm"><tbody>';
        data.forEach((row, rowIndex) => {
            table += '<tr>';
            row.forEach((cell, cellIndex) => {
                table += `<td><input type="text" class="form-control form-control-sm" value="${cell}" data-row="${rowIndex}" data-col="${cellIndex}"></td>`;
            });
            table += '</tr>';
        });
        table += '</tbody></table>';
        displayDiv.innerHTML = table;

        // Add event listeners to new input fields
        const inputs = displayDiv.querySelectorAll('input');
        inputs.forEach(input => {
            input.addEventListener('change', handleGridEdit);
        });
    }

    function handleGridEdit(event) {
        const input = event.target;
        const rowIndex = parseInt(input.dataset.row, 10);
        const colIndex = parseInt(input.dataset.col, 10);
        gridData[rowIndex][colIndex] = input.value;

        if (gridData && accountsData) {
            calculateRebates();
        } else if (!accountsData) {
            alert("Please upload the accounts CSV file to see calculations.");
        }
    }

    function addRow() {
        if (!gridData) {
            alert("Please upload a grid file first.");
            return;
        }
        const numCols = gridData[0].length;
        const newRow = ['New-Volume-Bin', ...Array(numCols - 1).fill('0')];
        gridData.push(newRow);
        displayGrid(gridData);
        if (accountsData) calculateRebates();
    }

    function removeRow() {
        if (!gridData || gridData.length <= 2) {
            alert("Cannot remove header or last data row.");
            return;
        }
        gridData.pop();
        displayGrid(gridData);
        if (accountsData) calculateRebates();
    }

    function addCol() {
        if (!gridData) {
            alert("Please upload a grid file first.");
            return;
        }
        gridData.forEach((row, index) => {
            row.push(index === 0 ? 'New-Growth-Bin' : '0');
        });
        displayGrid(gridData);
        if (accountsData) calculateRebates();
    }

    function removeCol() {
        if (!gridData || gridData[0].length <= 2) {
            alert("Cannot remove volume bin or last data column.");
            return;
        }
        gridData.forEach(row => row.pop());
        displayGrid(gridData);
        if (accountsData) calculateRebates();
    }

    async function calculateRebates() {
        if (!gridData || !accountsData) return;

        try {
            const response = await fetch('/calculate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ grid: gridData, accounts: accountsData })
            });

            const results = await response.json();
            if (!response.ok) {
                throw new Error(results.error || 'Calculation failed');
            }
            
            displayResults(results);

        } catch (error) {
            console.error('Error:', error);
            alert(`An error occurred during calculation: ${error.message}`);
        }
    }

    function displayResults(results) {
        if (!results) return;

        // Total Rebate
        const totalRebateDiv = document.getElementById('total-rebate-display');
        totalRebateDiv.innerHTML = `Total Cost: <strong>$${(results.total_rebate || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</strong>`;

        // Results Table
        const resultsTableDiv = document.getElementById('results-table');
        if (!results.table || results.table.length === 0) {
            resultsTableDiv.innerHTML = '<div class="alert alert-warning">No rebate data to display. Check your grid and account data.</div>';
        } else {
            let tableHtml = '<table class="table table-striped table-hover table-sm"><thead><tr>';
            const headers = Object.keys(results.table[0]);
            headers.forEach(h => tableHtml += `<th>${h}</th>`);
            tableHtml += '</tr></thead><tbody>';
            results.table.forEach(row => {
                tableHtml += '<tr>';
                headers.forEach(h => {
                    let val = row[h];
                    if (h === 'rebate' || h === 'curryr_rev' || h === 'prevyr_rev') {
                        val = (val || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    } else if (h === 'growth') {
                         val = `${((val || 0) * 100).toFixed(1)}%`;
                    }
                    tableHtml += `<td>${val}</td>`;
                });
                tableHtml += '</tr>';
            });
            tableHtml += '</tbody></table>';
            resultsTableDiv.innerHTML = tableHtml;
        }

        // Summary Table
        const summaryTableDiv = document.getElementById('summary-table');
        if (!results.summary || results.summary.length === 0) {
            summaryTableDiv.innerHTML = '<div class="alert alert-info">No summary data available.</div>';
        } else {
            let summaryHtml = '<table class="table table-bordered table-sm"><thead><tr>';
            const summaryHeaders = Object.keys(results.summary[0]);
            summaryHeaders.forEach(h => summaryHtml += `<th>${h}</th>`);
            summaryHtml += '</tr></thead><tbody>';
            results.summary.forEach(row => {
                summaryHtml += '<tr>';
                summaryHeaders.forEach(h => {
                    let val = row[h];
                    if (h === 'sum') {
                        val = (val || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    }
                    summaryHtml += `<td>${val}</td>`;
                });
                summaryHtml += '</tr>';
            });
            summaryHtml += '</tbody></table>';
            summaryTableDiv.innerHTML = summaryHtml;
        }
    }
});