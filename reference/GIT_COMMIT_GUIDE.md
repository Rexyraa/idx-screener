# GIT_COMMIT_GUIDE.md

## Purpose

Panduan commit untuk proyek `idx-screener` agar riwayat Git:
- mudah dibaca;
- mudah direview;
- mudah di-revert;
- mudah dicari saat debugging;
- terhubung jelas ke requirement PRD.

**Source of truth:** PRD Stock Screener BEI v0.2, 20 September 2026.

---

## 1. Format Utama

Gunakan gaya **Conventional Commits**:

```text
<type>(<scope>): <imperative summary>
```

Contoh:

```text
feat(ingest): add layered EOD price fallback
fix(alerts): prevent duplicate events during cooldown
test(e2e): cover degraded daily pipeline
refactor(store): isolate idempotent upsert logic
docs(runbook): document source failure recovery
```

---

## 2. Allowed Types

| Type | Kapan digunakan |
|---|---|
| `feat` | fitur baru / capability baru |
| `fix` | memperbaiki bug |
| `test` | menambah/memperbaiki test tanpa perubahan production behavior |
| `refactor` | restrukturisasi kode tanpa perubahan behavior yang disengaja |
| `perf` | optimasi performa |
| `docs` | dokumentasi |
| `build` | dependency/build/package |
| `ci` | GitHub Actions / CI pipeline |
| `chore` | maintenance non-production |
| `revert` | membatalkan commit sebelumnya |

Gunakan `fix` untuk bug behavior.

Jangan memakai `feat` hanya karena perubahan besar.

---

## 3. Scope yang Disarankan

Scope mengikuti domain repository:

```text
config
ingest
qc
features
screening
scoring
stochastic
actuarial
backtest
alerts
notify
telegram
ops
store
cli
models
market
calendar
tests
e2e
ci
docs
```

Pilih scope yang paling dekat dengan akar perubahan.

Contoh:

```text
fix(ingest): fallback when yfinance response is empty
```

lebih baik daripada:

```text
fix(backend): fix bug
```

---

## 4. Subject Rules

Subject:
- gunakan bahasa Inggris konsisten di Git;
- imperative;
- singkat dan spesifik;
- idealnya ≤ 72 karakter;
- tanpa titik di akhir;
- jelaskan perubahan, bukan proses.

### Good

```text
fix(ops): stop retrying validation failures
feat(alerts): add severity-aware cooldown bypass
test(e2e): cover holiday pipeline skip
refactor(store): make daily writes idempotent
```

### Bad

```text
fix: fixed stuff
update code
minor changes
debugging
final fix
final final fix
try again
```

---

## 5. Commit Harus Atomic

Satu commit sebaiknya menjawab satu pertanyaan:

```text
What changed?
Why?
How is it verified?
```

Contoh:

```text
fix(ingest): stop retry loop on invalid schema
```

Isi commit:
- ubah retry classifier;
- tambahkan unit/regression test;
- dokumentasikan behavior bila perlu.

Jangan sekaligus:
- refactor 20 file;
- ubah konfigurasi;
- ubah UI;
- rename seluruh repository.

Bila memang diperlukan, pecah menjadi beberapa commit.

---

## 6. Commit Body

Gunakan body jika alasan perubahan tidak jelas dari subject.

Format:

```text
fix(alerts): suppress repeated events during cooldown

An identical rule/ticker pair could be emitted repeatedly when the
pipeline was rerun within the cooldown window.

Use dedupe_key=(rule_id,ticker) and allow a resend only when severity
increases.

Tests:
- cooldown suppresses same-severity event
- higher severity bypasses cooldown
- rerun remains idempotent

PRD: FR-TG-05, FR-OPS-02
```

Body sebaiknya menjelaskan:
- problem;
- root cause;
- solution;
- verification;
- requirement reference.

---

## 7. PRD Traceability

Untuk perubahan yang terkait requirement, tambahkan footer:

```text
PRD: FR-OPS-02, FR-OPS-03
```

Untuk NFR:

```text
NFR: NFR-05, NFR-09
```

Untuk user story:

```text
US: US-01, US-09
```

Contoh:

```text
feat(ops): add heartbeat failure detection

Detect missing daily notification and send an admin alert.

Tests:
- report sent → heartbeat passes
- report missing → admin alert emitted

PRD: FR-OPS-04, FR-TG-08
NFR: NFR-03, NFR-05
US: US-01, US-09
```

---

## 8. Commit untuk Bug / Debugging

### 8.1 Jangan commit "trial patches"

Hindari:

```text
fix: try another retry
fix: temporary fix
fix: debug
fix: workaround
fix: final fix
```

Kecuali memang sebuah workaround resmi dan sengaja dipertahankan.

### 8.2 Commit harus membawa regression test

Untuk bug:

```text
fix(...)
```

idealnya selalu berpasangan dengan:

```text
test(...)
```

Tetapi jika production fix + regression test aman dalam satu atomic commit, boleh satu commit:

```text
fix(alerts): prevent duplicate cooldown events
```

dengan test di commit yang sama.

### 8.3 Jangan menutupi failure

Dilarang sebagai "fix":

```python
try:
    ...
except Exception:
    pass
```

atau:

```python
retry_forever(...)
```

atau:

```python
assert False
```

semata-mata untuk mengubah CI result.

---

## 9. Death-Loop Related Commits

Saat memperbaiki death loop, gunakan commit yang menjelaskan boundary baru.

Contoh:

```text
fix(ops): cap transient retry attempts
```

Body:

```text
Limit network retries to three attempts with exponential backoff.

Validation failures are now classified as non-retryable and fail fast.

Tests:
- timeout retries three times
- schema failure retries zero times
- successful third attempt completes the job

PRD: FR-OPS-03
```

Untuk alert loop:

```text
fix(alerts): enforce dedupe key before cooldown check
```

Untuk rerun loop:

```text
fix(store): make daily upserts idempotent
```

---

## 10. Commit Sequencing yang Disarankan

Untuk fitur pipeline:

```text
1. feat(config): add configuration schema
2. feat(ingest): add source adapter
3. feat(ingest): add fallback chain
4. feat(qc): validate ingested prices
5. feat(store): persist validated prices
6. test(e2e): cover daily ingestion path
7. docs(runbook): document source failure recovery
```

Untuk bug:

```text
1. test(alerts): reproduce duplicate notification
2. fix(alerts): enforce dedupe before send
3. test(e2e): cover rerun notification behavior
```

Jangan memaksa urutan ini bila atomic change membutuhkan gabungan berbeda.

---

## 11. Commit Setelah Test

Sebelum commit:

```bash
ruff check .
mypy src
pytest tests/unit
pytest tests/integration
pytest tests/e2e
```

Sesuaikan command dengan project configuration.

Minimal tulis verification di commit body:

```text
Tests:
- pytest tests/unit/test_alerts.py
- pytest tests/e2e/test_daily_pipeline.py
```

Untuk perubahan numerical:

```text
Tests:
- pytest tests/unit/test_gbm.py
- pytest tests/unit/test_barrier.py
- pytest tests/e2e/test_stochastic_pipeline.py
```

---

## 12. Do Not Mix Generated Noise

Jangan masukkan ke commit aplikasi:
- `.env`;
- Telegram token;
- DB credentials;
- local cache besar;
- raw private dumps;
- generated reports yang bukan artifact repository;
- secrets di fixture.

PRD secara eksplisit mengharuskan secret scanning dan tidak ada kredensial dalam Git history.

---

## 13. Breaking Changes

Jika public CLI/config/data contract berubah, tambahkan footer:

```text
BREAKING CHANGE: <jelaskan perubahan dan migration path>
```

Contoh:

```text
feat(config): version market parameter schema

BREAKING CHANGE: `price_limits` now requires effective dates.
Existing configs must migrate to the versioned list format.

PRD: FR-CFG-03
```

Jangan menyamarkan breaking change sebagai refactor.

---

## 14. Revert

Jika sebuah commit terbukti merusak behavior:

```bash
git revert <commit>
```

Lebih baik revert dengan commit jelas daripada mengedit history bersama-sama setelah commit sudah dibagikan.

Contoh:

```text
revert(stochastic): disable unstable PDE optimization
```

Body:

```text
Revert the optimization because it violates the numerical consistency
tolerance against the closed-form GBM barrier result.

PRD: NFR-08
```

---

## 15. Pull Request / Merge Description

Format yang disarankan:

```text
## What changed
- ...

## Why
- ...

## PRD traceability
- FR-...
- NFR-...
- US-...

## Tests
- ...

## Operational impact
- retries:
- idempotency:
- fallback:
- Telegram:
- database migration:

## Risk
- ...

## Rollback
- ...
```

---

## 16. Commit Naming Cheat Sheet

```text
feat(ingest): add IDX fundamental fallback
feat(screening): add quality value preset
feat(scoring): add CAQS component decomposition
feat(stochastic): add deterministic GBM Monte Carlo
feat(actuarial): add Kaplan-Meier survival estimator
feat(backtest): add point-in-time feature filtering
feat(alerts): add severity-aware cooldown
feat(telegram): add daily report template

fix(ingest): reject malformed OHLCV rows
fix(store): prevent duplicate daily writes
fix(ops): stop retrying non-retryable validation errors
fix(scoring): normalize active CAQS weights
fix(backtest): prevent future fundamental leakage
fix(alerts): suppress duplicate cooldown events
fix(telegram): split messages above Telegram limit
fix(calendar): skip non-trading days correctly

test(e2e): cover degraded daily pipeline
test(backtest): add look-ahead regression case
test(alerts): cover cooldown and hysteresis
test(store): verify rerun idempotency

perf(stochastic): batch Monte Carlo paths
perf(ingest): cache source responses

refactor(ops): isolate retry classification
refactor(store): centralize upsert keys

ci: run e2e suite on fixed snapshots
docs(runbook): document recovery after source failure
```

---

## 17. Definition of a Good Commit

A good commit is:

```text
small
+
atomic
+
traceable
+
tested
+
reversible
+
free from secrets
```

A reviewer should be able to understand:

```text
problem
→ change
→ evidence
→ PRD requirement
```

tanpa harus membaca seluruh repository.
