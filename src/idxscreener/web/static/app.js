// ── Theme management ────────────────────────────────────────────────────────
function getStoredTheme() {
    return localStorage.getItem("theme") || "dark";
}

function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
    const btn = document.getElementById("theme-toggle-btn");
    if (btn) {
        btn.textContent = theme === "dark" ? "☀️" : "🌙";
        btn.title = theme === "dark" ? "Ubah ke Mode Terang (Light Mode)" : "Ubah ke Mode Gelap (Dark Mode)";
    }
    if (window._currentStockPrices && window._currentStockPrices.length) {
        drawPriceChart(window._currentStockPrices);
    }
}

function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
}

// ── API helpers ──────────────────────────────────────────────────────────────
async function api(method, url, body) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(url, opts);
    const data = await r.json().catch(() => null);
    if (!r.ok) {
        const detail = data?.error || data?.detail;
        throw new Error(`HTTP ${r.status}: ${typeof detail === 'string' ? detail : r.statusText || 'Request failed'}`);
    }
    if (data === null) throw new Error("Respons JSON tidak valid");
    return data;
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[char]);
}

// ── Score badge ──────────────────────────────────────────────────────────────
function scoreBadge(score, label) {
    if (!Number.isFinite(score)) return `<span class="badge badge-na">tidak tersedia</span>`;
    const cls = score >= 70 ? "badge-high" : score >= 50 ? "badge-mid" : "badge-low";
    return `<span class="badge ${cls}">${score.toFixed(1)}</span>`;
}

function scoreLabel(label) {
    if (!label) return "";
    return `<span class="badge badge-na">${escapeHtml(label)}</span>`;
}

// ── Screener table ───────────────────────────────────────────────────────────
let _sortBy = "score", _sortDir = "desc", _filters = {};

async function loadScreenerResults() {
    const tbody = document.getElementById("screener-tbody");
    if (!tbody) return;
    try {
        const params = new URLSearchParams({ sort_by: _sortBy, sort_dir: _sortDir });
        if (_filters.min_score) params.set("min_score", _filters.min_score);
        if (_filters.sector) params.set("sector", _filters.sector);
        if (_filters.search) params.set("search", _filters.search);
        const data = await api("GET", `/api/runs/latest/results?${params}`);
        if (!Array.isArray(data)) throw new Error("Format hasil screening tidak valid");
        tbody.innerHTML = data.map(r => {
            const isPos = (r.change_1m || 0) >= 0;
            const colorVar = isPos ? 'var(--positive)' : 'var(--negative)';
            return `
        <tr>
          <td><a href="/stocks/${escapeHtml(encodeURIComponent(r.ticker))}" class="ticker-link">${escapeHtml(r.ticker)}</a></td>
          <td style="font-weight:500">${escapeHtml(r.name)}</td>
          <td><span style="color:var(--text-muted);font-size:0.8rem">${escapeHtml(r.sector)}</span></td>
          <td class="num">${Number.isFinite(r.price) ? r.price.toFixed(0) : "—"}</td>
          <td class="num">${scoreBadge(r.score, r.label)}</td>
          <td>${scoreLabel(r.label)}</td>
          <td class="num" style="color:${colorVar}">${Number.isFinite(r.change_1m) ? (isPos ? '+' : '') + r.change_1m.toFixed(2) + "%" : "—"}</td>
        </tr>
      `;
        }).join("") || '<tr><td colspan="7">Belum ada saham lolos filter.</td></tr>';
        const count = document.getElementById("result-count");
        if (count) count.textContent = `${data.length} saham`;
    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="7" role="alert">Gagal memuat hasil: ${escapeHtml(error.message)}</td></tr>`;
        const count = document.getElementById("result-count");
        if (count) count.textContent = "tidak tersedia";
    }
}

function setupScreener() {
    const tbody = document.getElementById("screener-tbody");
    if (!tbody) return;
    document.querySelectorAll("th[data-sort]").forEach(th => {
        th.addEventListener("click", () => {
            const col = th.dataset.sort;
            if (_sortBy === col) _sortDir = _sortDir === "asc" ? "desc" : "asc";
            else { _sortBy = col; _sortDir = "desc"; }
            loadScreenerResults();
        });
    });
    document.getElementById("filter-min-score")?.addEventListener("input", e => {
        _filters.min_score = parseFloat(e.target.value) || 0;
        document.getElementById("min-score-val").textContent = _filters.min_score;
        loadScreenerResults();
    });
    document.getElementById("filter-sector")?.addEventListener("change", e => {
        _filters.sector = e.target.value; loadScreenerResults();
    });
    document.getElementById("filter-search")?.addEventListener("input", e => {
        _filters.search = e.target.value; loadScreenerResults();
    });
    document.getElementById("btn-export-csv")?.addEventListener("click", () => {
        const params = new URLSearchParams({ sort_by: _sortBy, sort_dir: _sortDir });
        if (_filters.min_score) params.set("min_score", _filters.min_score);
        if (_filters.sector) params.set("sector", _filters.sector);
        if (_filters.search) params.set("search", _filters.search);
        window.open(`/api/runs/latest/results?${params}&format=csv`, "_blank");
    });
    loadScreenerResults();
}

// ── Run screening with progress ──────────────────────────────────────────────
async function startScreening() {
    const btn = document.getElementById("btn-run-screening");
    if (!btn || btn.disabled) return;
    const originalText = btn.textContent;
    const bar = document.getElementById("run-progress");
    const status = document.getElementById("run-status");
    if (bar) bar.style.display = "block";
    if (status) status.textContent = "Memulai refresh harga riil…";
    btn.disabled = true; btn.textContent = "Memulai...";
    try {
        const { run_id } = await api("POST", "/api/runs", {});
        if (typeof run_id !== "string" || !run_id) throw new Error("Run ID tidak tersedia");
        await pollRunStatus(run_id);
    } catch (error) {
        if (status) status.textContent = `Refresh dihentikan: ${error.message}`;
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

async function pollRunStatus(runId) {
    const bar = document.getElementById("run-progress");
    const status = document.getElementById("run-status");
    if (bar) bar.style.display = "block";
    // ponytail: poll only while this page is open; add persisted resume if needed.
    while (true) {
        const job = await api("GET", `/api/runs/${encodeURIComponent(runId)}`);
        if (bar) {
            const pct = Number.isFinite(job.total) && job.total > 0 && Number.isFinite(job.progress)
                ? Math.max(0, Math.min(100, (job.progress / job.total) * 100)) : 0;
            bar.querySelector("div").style.width = pct + "%";
        }
        if (status) status.textContent = `${job.status} (${job.progress || 0}/${job.total || 0})`;
        if (job.status === "success") {
            location.reload();
            return;
        }
        if (job.status === "failed") throw new Error(job.error || "Refresh gagal; snapshot terakhir dipertahankan");
        if (!["queued", "running"].includes(job.status)) throw new Error("Status refresh tidak dikenal");
        await new Promise(resolve => setTimeout(resolve, 800));
    }
}

// ── Watchlist ─────────────────────────────────────────────────────────────────
async function toggleWatchlist(ticker) {
    const btn = document.getElementById("btn-watchlist");
    if (!btn || btn.disabled) return;
    try {
        if (btn.dataset.active === "true") {
            await api("DELETE", "/api/watchlist", { ticker });
            btn.dataset.active = "false";
            btn.textContent = "+ Tambah ke Watchlist";
            btn.className = "btn btn-secondary btn-sm";
        } else {
            await api("POST", "/api/watchlist", { ticker });
            btn.dataset.active = "true";
            btn.textContent = "✓ Hapus dari Watchlist";
            btn.className = "btn btn-danger btn-sm";
        }
    } catch (error) {
        alert(`Watchlist tidak diubah: ${error.message}`);
    }
}

// ── Weights sliders ──────────────────────────────────────────────────────────
function setupWeights() {
    const sliders = document.querySelectorAll(".weight-slider");
    if (!sliders.length) return;
    const totalEl = document.getElementById("weight-total");
    const normalizeBtn = document.getElementById("btn-normalize");

    function updateTotal() {
        let total = 0;
        sliders.forEach(s => total += parseFloat(s.value));
        if (totalEl) totalEl.textContent = total.toFixed(2);
        totalEl.style.color = Math.abs(total - 1.0) < 0.001 ? "var(--positive)" : "var(--negative)";
    }
    sliders.forEach(s => s.addEventListener("input", updateTotal));
    normalizeBtn?.addEventListener("click", () => {
        let total = 0;
        sliders.forEach(s => total += parseFloat(s.value));
        if (total > 0) sliders.forEach(s => s.value = (parseFloat(s.value) / total).toFixed(4));
        updateTotal();
    });
    document.getElementById("btn-save-weights")?.addEventListener("click", async () => {
        if (document.getElementById("btn-save-weights").disabled) return;
        const weights = {};
        sliders.forEach(s => weights[s.dataset.key] = parseFloat(s.value));
        try {
            const result = await api("PUT", "/api/weights", weights);
            alert("Bobot tersimpan: " + JSON.stringify(result));
        } catch (error) {
            alert(`Bobot tidak tersimpan: ${error.message}`);
        }
    });
    updateTotal();
}

// ── Stock detail chart (Adaptive Cyan/Azure) ────────────────────────────────
function drawPriceChart(prices) {
    window._currentStockPrices = prices;
    const canvas = document.getElementById("price-chart");
    if (!canvas || !prices.length) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.offsetWidth * dpr;
    canvas.height = canvas.offsetHeight * dpr;
    ctx.scale(dpr, dpr);
    const w = canvas.offsetWidth, h = canvas.offsetHeight;

    const isDark = (document.documentElement.getAttribute("data-theme") || "dark") === "dark";
    const lineColor = isDark ? "#00D2FF" : "#0284C7";
    const gridColor = isDark ? "rgba(255, 255, 255, 0.05)" : "rgba(15, 23, 42, 0.06)";
    const textColor = isDark ? "#8A99AC" : "#64748B";

    const data = prices.slice().reverse();
    const closes = data.map(d => d.close).filter(v => v != null);
    if (!closes.length) return;
    const minP = Math.min(...closes), maxP = Math.max(...closes);
    const pad = 50, padR = 20, padT = 20, padB = 25;
    const chartW = w - pad - padR, chartH = h - padT - padB;
    const xStep = chartW / Math.max(data.length - 1, 1);
    const yScale = chartH / Math.max(maxP - minP, 0.01);

    // Subtle Grid lines
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = padT + (chartH / 4) * i;
        ctx.beginPath();
        ctx.moveTo(pad, y);
        ctx.lineTo(w - padR, y);
        ctx.stroke();
    }

    // Gradient fill under the curve
    const gradient = ctx.createLinearGradient(0, padT, 0, h - padB);
    gradient.addColorStop(0, isDark ? "rgba(0, 210, 255, 0.22)" : "rgba(2, 132, 199, 0.16)");
    gradient.addColorStop(1, isDark ? "rgba(0, 210, 255, 0.0)" : "rgba(2, 132, 199, 0.0)");

    ctx.beginPath();
    data.forEach((d, i) => {
        const x = pad + i * xStep;
        const y = padT + (maxP - d.close) * yScale;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.lineTo(pad + (data.length - 1) * xStep, h - padB);
    ctx.lineTo(pad, h - padB);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Line stroke with glow
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 2;
    ctx.shadowColor = isDark ? "rgba(0, 210, 255, 0.5)" : "rgba(2, 132, 199, 0.35)";
    ctx.shadowBlur = 8;
    ctx.beginPath();
    data.forEach((d, i) => {
        const x = pad + i * xStep;
        const y = padT + (maxP - d.close) * yScale;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Price labels
    ctx.fillStyle = textColor;
    ctx.font = "11px 'JetBrains Mono', monospace";
    ctx.fillText("Rp " + maxP.toFixed(0), 4, padT + 4);
    ctx.fillText("Rp " + minP.toFixed(0), 4, h - padB + 4);
}

// ── Backtest form ─────────────────────────────────────────────────────────────
function setupBacktest() {
    const btn = document.getElementById("btn-run-backtest");
    if (!btn) return;
    btn.addEventListener("click", async () => {
        if (btn.disabled) return;
        const params = {
            period: document.getElementById("bt-period")?.value,
            rebalance: document.getElementById("bt-rebalance")?.value,
            top_n: parseInt(document.getElementById("bt-topn")?.value || "10"),
            cost: parseFloat(document.getElementById("bt-cost")?.value || "0.15"),
        };
        btn.disabled = true; btn.textContent = "Menjalankan...";
        const out = document.getElementById("backtest-output");
        try {
            const result = await api("POST", "/api/backtests", params);
            if (out) out.textContent = result.message || "Selesai";
        } catch (error) {
            if (out) out.textContent = `Backtest gagal: ${error.message}`;
        } finally {
            btn.disabled = false; btn.textContent = "Jalankan Backtest";
        }
    });
}

// ── Init ─────────────────────────────────────────────────────────────────────
if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", () => {
    applyTheme(getStoredTheme());
    setupScreener();
    setupWeights();
    setupBacktest();
});

// Runnable boundary check: node app.js (no browser or dependencies needed).
if (typeof module !== "undefined" && require.main === module) {
    const assert = require("node:assert/strict");
    assert.equal(escapeHtml(`<a title="x">&'</a>`), '&lt;a title=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
    assert.equal(escapeHtml(null), "");
    assert.ok(!scoreLabel('<img src=x onerror="alert(1)">').includes('<img'));
    assert.ok(scoreBadge("<script>").includes("tidak tersedia"));
}
