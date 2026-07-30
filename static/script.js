document.addEventListener('DOMContentLoaded', () => {
    const $ = (selector) => document.querySelector(selector);
    const runButton = $('#run-btn');
    const status = $('#status-indicator');
    const errorPanel = $('#error-panel');
    const warningPanel = $('#warning-panel');

    function parseNumberList(value, divisor = 1) {
        const numbers = value.split(',')
            .map((item) => Number(item.trim()) / divisor)
            .filter(Number.isFinite);
        if (!numbers.length || numbers.some((item, index) => index > 0 && item <= numbers[index - 1])) {
            throw new Error('Milestones must be comma-separated numbers in increasing order.');
        }
        return numbers;
    }

    function requestPayload() {
        const budgetText = $('#budget').value.trim();
        return {
            volume_milestones: parseNumberList($('#vol-milestones').value),
            growth_milestones: parseNumberList($('#growth-milestones').value, 100),
            payout_basis: $('#payout-basis').value,
            budget: budgetText ? Number(budgetText.replace(/[$,]/g, '')) : null,
            include_auto_candidates: $('#auto-candidates').checked,
            scenarios: {
                low: Number($('#elasticity-low').value),
                base: Number($('#elasticity-base').value),
                high: Number($('#elasticity-high').value),
            },
        };
    }

    function money(value) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            maximumFractionDigits: 0,
        }).format(value);
    }

    function percent(value, digits = 1) {
        return `${(value * 100).toFixed(digits)}%`;
    }

    function milestoneLabels(values, formatter) {
        return values.map((value, index) => {
            const upper = values[index + 1];
            return upper === undefined
                ? `${formatter(value)}+`
                : `${formatter(value)}–${formatter(upper)}`;
        });
    }

    function clearMessage(panel) {
        panel.classList.add('hidden');
        panel.textContent = '';
    }

    function showMessage(panel, messages) {
        if (!messages || !messages.length) return clearMessage(panel);
        panel.textContent = messages.join(' ');
        panel.classList.remove('hidden');
    }

    function renderGrid(data) {
        const headers = milestoneLabels(data.program.volume_milestones, (value) => money(value));
        const rowLabels = milestoneLabels(data.program.growth_milestones, (value) => percent(value, 0));
        const head = $('#results-table thead');
        const body = $('#results-table tbody');
        head.innerHTML = `<tr><th>Growth \\ Volume</th>${headers.map((h) => `<th>${h}</th>`).join('')}</tr>`;
        body.innerHTML = data.rates.map((row, rowIndex) => (
            `<tr><th>${rowLabels[rowIndex]}</th>${row.map((rate) => `<td class="rate-cell">${percent(rate, 0)}</td>`).join('')}</tr>`
        )).join('');
    }

    function renderCoverage(data) {
        const headers = milestoneLabels(data.program.volume_milestones, (value) => money(value));
        const rowLabels = milestoneLabels(data.program.growth_milestones, (value) => percent(value, 0));
        $('#coverage-table thead').innerHTML =
            `<tr><th>Growth \\ Volume</th>${headers.map((h) => `<th>${h}</th>`).join('')}</tr>`;
        $('#coverage-table tbody').innerHTML = data.cell_counts.map((row, g) => (
            `<tr><th>${rowLabels[g]}</th>${row.map((count, v) => (
                `<td><strong>${count.toLocaleString()} accounts</strong><br><span class="muted">${money(data.cell_revenue[g][v])}</span></td>`
            )).join('')}</tr>`
        )).join('');
    }

    function renderScenarios(data) {
        const order = ['no_program', 'low', 'base', 'high'];
        $('#scenario-table tbody').innerHTML = order.map((name) => {
            const item = data.scenarios[name];
            const label = name.replace('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
            return `<tr>
                <th>${label}</th>
                <td>${money(item.projected_revenue)}</td>
                <td>${money(item.payout)}</td>
                <td>${money(item.net_revenue)}</td>
                <td class="${item.uplift_vs_no_program >= 0 ? 'positive' : 'negative'}">${money(item.uplift_vs_no_program)}</td>
            </tr>`;
        }).join('');
    }

    function renderCandidates(data) {
        $('#candidate-list').innerHTML = data.candidate_assessments.map((candidate) => {
            const detail = candidate.accepted
                ? 'Passed coverage, solver, and stability checks.'
                : candidate.reasons.slice(0, 2).join(' ');
            return `<article class="candidate-row">
                <span class="candidate-state ${candidate.accepted ? 'pass' : 'fail'}">${candidate.accepted ? 'Pass' : 'Rejected'}</span>
                <div><strong>${candidate.name.replaceAll('_', ' ')}</strong><p>${detail}</p></div>
            </article>`;
        }).join('');
    }

    function renderReconciliation(data) {
        const items = {
            'Source rows': data.reconciliation.source_rows,
            'Aggregated accounts': data.reconciliation.aggregated_accounts,
            'Invalid identifier rows': data.reconciliation.invalid_identifier_rows,
            'Invalid revenue rows': data.reconciliation.invalid_revenue_rows,
            'Eligible accounts': data.exclusion_counts.eligible,
            'New / nonpositive baseline': data.exclusion_counts.new_or_nonpositive_baseline,
            'Negative / invalid forecast': data.exclusion_counts.negative_or_invalid_forecast,
            'Below volume minimum': data.exclusion_counts.below_volume_milestone,
            'Below growth minimum': data.exclusion_counts.below_growth_milestone,
        };
        $('#reconciliation').innerHTML = Object.entries(items)
            .map(([label, value]) => `<div><span>${label}</span><strong>${Number(value).toLocaleString()}</strong></div>`)
            .join('');
    }

    function renderResult(data) {
        const base = data.scenarios.base;
        $('#base-net').textContent = money(base.net_revenue);
        $('#base-uplift').textContent = money(base.uplift_vs_no_program);
        $('#base-payout').textContent = money(base.payout);
        $('#eligible-accounts').textContent = data.exclusion_counts.eligible.toLocaleString();
        $('#coverage-subtitle').textContent = `${data.reconciliation.source_rows.toLocaleString()} source rows reconciled`;
        $('#selected-candidate').textContent = data.program.name.replaceAll('_', ' ');
        $('#migration-badge').textContent =
            `${percent(data.migration.migrated_share)} moved · ${percent(data.migration.net_impact_share || 0)} net impact`;
        $('#contract-list').innerHTML = data.contract.map((line) => `<li>${line}</li>`).join('');
        showMessage(warningPanel, data.warnings);
        renderGrid(data);
        renderCoverage(data);
        renderScenarios(data);
        renderCandidates(data);
        renderReconciliation(data);
    }

    runButton.addEventListener('click', async () => {
        clearMessage(errorPanel);
        clearMessage(warningPanel);
        runButton.disabled = true;
        runButton.textContent = 'Designing…';
        status.textContent = 'Validating candidates and solving rates…';
        try {
            const response = await fetch('/optimize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestPayload()),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Optimization failed.');
            renderResult(data);
            status.textContent = 'Contract design complete';
        } catch (error) {
            showMessage(errorPanel, [error.message]);
            status.textContent = 'Could not produce a feasible contract';
        } finally {
            runButton.disabled = false;
            runButton.textContent = 'Design contract';
        }
    });

    document.querySelectorAll('.tab-btn').forEach((button) => {
        button.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach((item) => item.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach((item) => item.classList.remove('active'));
            button.classList.add('active');
            $(`#${button.dataset.tab}`).classList.add('active');
        });
    });

    function buildManualGrid() {
        const volume = parseNumberList($('#vol-milestones').value);
        const growth = parseNumberList($('#growth-milestones').value, 100);
        const volumeLabels = milestoneLabels(volume, (value) => money(value));
        const growthLabels = milestoneLabels(growth, (value) => percent(value, 0));
        $('#input-grid-table thead').innerHTML =
            `<tr><th>Growth \\ Volume</th>${volumeLabels.map((label) => `<th>${label}</th>`).join('')}</tr>`;
        $('#input-grid-table tbody').innerHTML = growthLabels.map((label, g) => (
            `<tr><th>${label}</th>${volume.map((_, v) => (
                `<td><input class="rate-input" type="number" min="0" max="100" step="1" value="0" data-g="${g}" data-v="${v}" aria-label="${label}, ${volumeLabels[v]} rebate percent"></td>`
            )).join('')}</tr>`
        )).join('');
    }

    $('#generate-grid-btn').addEventListener('click', () => {
        try {
            buildManualGrid();
        } catch (error) {
            window.alert(error.message);
        }
    });

    $('#calc-static-btn').addEventListener('click', async () => {
        try {
            const payload = requestPayload();
            const growthCount = payload.growth_milestones.length;
            const volumeCount = payload.volume_milestones.length;
            const inputs = [...document.querySelectorAll('.rate-input')];
            if (inputs.length !== growthCount * volumeCount) {
                throw new Error('Generate the manual grid first.');
            }
            const rates = Array.from({ length: growthCount }, () => Array(volumeCount).fill(0));
            inputs.forEach((input) => {
                rates[Number(input.dataset.g)][Number(input.dataset.v)] = Number(input.value) / 100;
            });
            const response = await fetch('/calculate_static', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...payload, rates }),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Calculation failed.');
            $('#static-revenue').textContent = money(data.total_revenue);
            $('#static-eligible-revenue').textContent = money(data.eligible_revenue);
            $('#static-cost').textContent = money(data.total_payout);
            $('#static-avg-rate').textContent = percent(data.effective_rate, 2);
        } catch (error) {
            window.alert(error.message);
        }
    });

    buildManualGrid();
});
