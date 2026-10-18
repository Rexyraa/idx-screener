# E2E_TEST_REFERENCE.md

## Purpose

Dokumen referensi **End-to-End (E2E) testing** untuk agent dan developer proyek `idx-screener`.

E2E harus memverifikasi sistem sebagai satu alur dari scheduler/CLI → ingestion → validation → storage → feature → scoring → screening → stochastic/actuarial → alert/report → Telegram sandbox → observability.

**Source of truth:** PRD `Stock Screener BEI` versi `0.2`, 20 September 2026.

---

## 1. Prinsip E2E

### 1.1 E2E bukan pengganti unit test

Gunakan:

```text
Unit          → rumus & fungsi kecil
Contract      → schema/data invariants
Integration   → batas antar-komponen
E2E           → user flow / pipeline lengkap
Operational   → failure & recovery
```

PRD menetapkan E2E menggunakan **snapshot data tetap**, `dry-run`, dan **chat Telegram uji**.

### 1.2 Determinisme

E2E wajib sebisa mungkin deterministik:

- fixture/snapshot data dipin;
- `run_date` eksplisit;
- seed model eksplisit;
- config version/hash eksplisit;
- model version eksplisit;
- tidak memakai live market data pada happy-path CI;
- Telegram production tidak digunakan;
- external source live hanya untuk test kontrak terisolasi.

Target PRD NFR-09:

```text
same data + same config + same seed
→ identical score
→ Monte Carlo identical within 1e-9
```

---

## 2. Environment Test

Minimum fixture:

```text
tests/
├─ fixtures/
│  ├─ market_snapshot/
│  ├─ fundamentals_snapshot/
│  ├─ calendar/
│  ├─ corporate_actions/
│  ├─ config/
│  └─ expected/
├─ integration/
└─ e2e/
```

Gunakan:
- PostgreSQL test container / isolated database;
- raw-cache fixture;
- Telegram sandbox/mock transport;
- deterministic clocks bila dibutuhkan;
- isolated schema/database per run.

Jangan pernah mengirim E2E CI ke `chat_id` production.

---

## 3. E2E Scenario Matrix

| ID | Scenario | Expected result |
|---|---|---|
| E2E-001 | Hari bursa normal | pipeline lengkap sampai report |
| E2E-002 | Hari libur BEI | job selesai dengan `skipped_holiday`; tidak ada laporan pasar |
| E2E-003 | Harga yfinance sukses | price ingestion + validation + upsert |
| E2E-004 | yfinance gagal | fallback source digunakan dan dicatat |
| E2E-005 | Semua source harga gagal | fallback/manual/cache sesuai konfigurasi; pipeline degraded/fail loud |
| E2E-006 | Coverage < 98% | retry window / degraded path + admin notification |
| E2E-007 | Fundamental invalid | data dikarantina; tidak masuk scoring |
| E2E-008 | Fundamental point-in-time | data hanya digunakan bila `publish_date ≤ run_date` |
| E2E-009 | Rerun tanggal sama | tidak ada duplicate rows/events |
| E2E-010 | Concurrent same job/date | satu eksekusi memperoleh lock; eksekusi lain tidak merusak state |
| E2E-011 | Feature + CAQS | skor dan `score_components` konsisten |
| E2E-012 | Gate failure | saham tersimpan tetapi tidak diberi label kandidat |
| E2E-013 | Missing metrics | shrinkage + confidence penalty, bukan crash |
| E2E-014 | Stochastic timeout | pipeline tetap menghasilkan report degraded |
| E2E-015 | Actuarial failure | AC/SR unavailable sesuai kondisi; laporan tetap menandai degradasi |
| E2E-016 | Alert trigger | `alert_event` dibuat dan pesan dikirim |
| E2E-017 | Duplicate alert | cooldown/dedupe mencegah kirim ulang |
| E2E-018 | Severity naik saat cooldown | alert dapat dikirim ulang |
| E2E-019 | Message > 4096 chars | pesan terpecah dengan aman |
| E2E-020 | Telegram 429 | backoff, tidak infinite retry |
| E2E-021 | Daily report | report dikirim setelah pipeline selesai |
| E2E-022 | Report gagal dikirim | `notifications_log` gagal + heartbeat/admin alert |
| E2E-023 | Stale data | freshness alert/admin notification |
| E2E-024 | CLI dry-run | tidak mengubah production state |
| E2E-025 | Backfill rerun | idempotent dan tidak menduplikasi |
| E2E-026 | Timezone boundary | timestamp disimpan UTC, ditampilkan WIB |
| E2E-027 | Config invalid | fail fast dengan pesan jelas |
| E2E-028 | Secret missing | fail fast tanpa menulis secret ke log |
| E2E-029 | Model result reproducibility | run kedua sama dengan run pertama |
| E2E-030 | Job failure | `job_runs` merekam status/durasi dan admin diberi tahu |

---

## 4. Golden Happy Path

Scenario utama yang wajib hidup di CI:

```text
E2E-001
```

### Input

- fixed `run_date`;
- fixed trading calendar;
- fixed price snapshot;
- fixed fundamental snapshot;
- fixed config;
- fixed model version;
- fixed seed;
- Telegram sandbox.

### Flow

```text
CLI / scheduled entry
   ↓
trading-day guard
   ↓
ingest price
   ↓
quality checks
   ↓
data confidence
   ↓
features
   ↓
CAQS preliminary
   ↓
stochastic
   ↓
actuarial
   ↓
CAQS final
   ↓
screen
   ↓
alert evaluation
   ↓
daily report
   ↓
Telegram sandbox
   ↓
job_runs + notifications_log
```

### Assertions minimum

```text
job_runs.status = success atau degraded
price coverage >= configured threshold
invalid records quarantined
scores_daily exists
score_components exists
screen_results exists
alert_events consistent
notifications_log contains report
Telegram sandbox received expected message(s)
all required run metadata persisted
```

---

## 5. Failure Path yang Wajib Diuji

### 5.1 Fallback source

Inject failure:

```text
yfinance = timeout
IDX snapshot = valid
```

Assert:

```text
source = IDX
fallback used = true/logged
pipeline continues
data quality issue recorded if relevant
```

### 5.2 Bad data

Inject:

```text
low > close
negative volume
duplicate bar
missing trade date
fundamental balance mismatch
```

Assert:

```text
severity=error
record quarantined
record excluded from scoring
job tidak silently sukses
```

### 5.3 Retry

Inject transient failures:

```text
attempt 1 → timeout
attempt 2 → timeout
attempt 3 → success
```

Assert:

```text
finite retries
backoff applied
final state success
no duplicate data
```

Do not test indefinite retry because PRD secara eksplisit menetapkan retry terbatas.

### 5.4 Non-retryable validation failure

```text
schema invalid
```

Assert:

```text
retry = false
error recorded
fallback only if fallback source is semantically valid
otherwise fail/degrade
```

---

## 6. Idempotency E2E

Run:

```bash
screener run daily --date 2026-09-21
screener run daily --date 2026-09-21
```

Bandingkan:

```text
row counts
primary/unique keys
scores
components
screen results
alert events
notifications
job summaries
```

Expected:

```text
no duplicate logical records
same deterministic outputs
no duplicate alert/report caused solely by rerun
```

Idempotency key:

```text
(job_name, run_date, params_hash)
```

---

## 7. Telegram E2E Contract

### Daily report

Verify:
- report contains market summary;
- Top-N CAQS tersedia;
- score movement tersedia;
- alert summary tersedia;
- watchlist tersedia bila dikonfigurasi;
- risk summary tersedia jika modul tersedia;
- data-health summary tersedia;
- disclaimer tetap ada.

### Alert

Verify:
- category;
- ticker;
- CAQS/label/confidence bila tersedia;
- price/volume information bila rule membutuhkannya;
- risk information bila kategori risk;
- cooldown indicator bila template menggunakannya.

### Admin

Simulasikan:

```text
coverage < threshold
stale data
job failure
stochastic timeout
heartbeat missing
```

Expected: admin notification diterima dan tercatat.

---

## 8. Alert Deduplication Matrix

Gunakan minimal tiga run:

```text
Run 1: condition true, severity=medium
Run 2: same condition, within cooldown, severity=medium
Run 3: same condition, within cooldown, severity=high
```

Expected:

```text
Run 1 → send
Run 2 → suppress
Run 3 → send because severity increased
```

Hysteresis:

```text
price > threshold
→ trigger

price bergerak sedikit di sekitar threshold
→ jangan spam

cross back past hysteresis boundary
→ trigger hanya jika rule kembali valid
```

---

## 9. Operational E2E

### Heartbeat

Flow:

```text
daily pipeline succeeds
→ report sends
→ heartbeat checks notification state
→ no admin failure alert
```

Failure:

```text
report not sent
→ heartbeat detects missing delivery
→ admin alert
```

### Timeout

Flow:

```text
component exceeds time budget
→ component terminated safely
→ partial progress persisted where supported
→ pipeline degraded
→ report marks unavailable modules
```

PRD mengharuskan graceful degradation pada stochastic/actuarial failure atau timeout.

---

## 10. Data Freshness E2E

Inject:
- price last update older than 1 trading day;
- fundamental older than 2 quarters;
- missing market day.

Assert:
- freshness factor turun;
- data issue terdeteksi;
- confidence berubah sesuai kontrak;
- admin alert bila melewati threshold;
- stale data tidak diperlakukan sebagai fresh.

---

## 11. PIT / Anti-Leakage E2E

### Test

Buat dua snapshot:

```text
T0 = informasi yang tersedia pada tanggal T
T1 = informasi yang baru publish setelah T
```

Run score/backtest pada T.

Assert:

```text
T1 tidak boleh masuk
```

Regression test:
- ubah `publish_date` ke masa depan;
- hasil historis tidak boleh memakai nilai tersebut.

Ini wajib karena PRD menekankan point-in-time data dan risiko look-ahead bias.

---

## 12. Numerical E2E

Minimal:

### Monte Carlo

Verify:
- deterministic seed;
- probability [0,1];
- quantiles ordered;
- VaR/ES valid;
- SE ≤ target setelah adaptive N.

### Barrier

Cross-check:

```text
Monte Carlo
vs
Crank–Nicolson
vs
closed-form GBM
```

Toleransi PRD:

```text
difference ≤ 3 × SE
```

### Markov

Verify:
```text
rows(P(t)) sum to 1
P(0)=I
absorbing termination state unchanged
expm result matches RK4 within test tolerance
```

---

## 13. Phase Acceptance

### MVP

Wajib lulus:
- 10 hari bursa berturut-turut daily report;
- price coverage ≥ 98%;
- unit tests green;
- admin alert teruji via simulated failure.

### 1.0-a

- anti-look-ahead pass;
- alert duplication tidak terjadi selama test window.

### 1.0-b

- convergence pass;
- MC/PDE/closed-form consistent;
- VaR backtest sesuai acceptance rule.

### 1.0-c

- KM separation diagnostic sesuai acceptance;
- probability calibration lebih baik dari baseline sesuai PRD.

### 1.0 final

- NFR utama terpenuhi;
- runbook lengkap;
- model documentation lengkap.

---

## 14. E2E Exit Checklist

```text
[ ] Fixed fixture/snapshot tersedia
[ ] Trading calendar deterministic
[ ] run_date eksplisit
[ ] config hash tercatat
[ ] model_version tercatat
[ ] seed tercatat
[ ] Telegram menggunakan sandbox
[ ] Database isolated
[ ] Fallback path teruji
[ ] Validation/quarantine teruji
[ ] Retry finite teruji
[ ] Idempotency teruji
[ ] Concurrency/lock teruji
[ ] Graceful degradation teruji
[ ] Alert dedupe/cooldown/hysteresis teruji
[ ] Heartbeat teruji
[ ] Freshness teruji
[ ] PIT/anti-leakage teruji
[ ] Numerical invariants teruji
[ ] job_runs tercatat
[ ] notifications_log tercatat
[ ] Tidak ada secret di log
```

---

## 15. Mapping User Story → E2E

| User Story | E2E coverage |
|---|---|
| US-01 daily report | E2E-001, 021, 022, 030 |
| US-02 alert | E2E-016–020 |
| US-03 configurable screen | E2E-027 + screen happy path |
| US-04 CAQS explanation | E2E-011 |
| US-05 confidence | E2E-007, 013, 023 |
| US-06 backtest | PIT + anti-bias scenarios |
| US-07 stochastic | E2E-014 + numerical E2E |
| US-08 actuarial | E2E-015 + Markov/KM checks |
| US-09 pipeline failure/stale | E2E-006, 022, 023, 030 |
| US-10 export | CLI/integration test; not required for MVP E2E |
| US-11 Telegram command | v1.1; separate webhook E2E |

---

## 16. Rule untuk AI Agent

Saat menambah fitur:

```text
1. Cari user story.
2. Cari FR.
3. Tambahkan/ubah unit test bila rumus berubah.
4. Tambahkan integration test bila boundary berubah.
5. Tambahkan E2E scenario bila user journey / pipeline berubah.
6. Jangan menghapus E2E yang gagal hanya karena implementasi baru belum siap.
7. Simpan fixture kecil, deterministik, dan mudah direproduksi.
8. Untuk bug produksi, tambahkan regression case ke E2E bila bug menembus beberapa layer.
```

E2E harus menjawab pertanyaan:

> "Apakah pengguna masih bisa mendapatkan hasil yang dijanjikan PRD setelah seluruh sistem dijalankan dari ujung ke ujung?"
