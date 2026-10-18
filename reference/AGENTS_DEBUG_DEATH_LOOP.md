# AGENTS_DEBUG_DEATH_LOOP.md

## Purpose

Dokumen ini adalah **runbook instruksi untuk AI coding/debugging agent** pada proyek `idx-screener`.

Tujuan utama:
1. Menemukan akar error secepat mungkin.
2. **Membunuh death loop**: jangan mengulangi tindakan yang sama ketika menghasilkan error yang sama.
3. Mempertahankan kontrak PRD: idempotent, replayable, fail loud, fallback berlapis, point-in-time, config-as-code, dan auditability.
4. Membuat perubahan sekecil mungkin, lalu membuktikan perubahan tersebut dengan test yang relevan.

**Source of truth:** PRD `Stock Screener BEI` versi `0.2` tanggal `20 September 2026`.

---

## 1. Aturan Mutlak Agent

### 1.1 Jangan menebak kontrak

Sebelum memperbaiki error:
- cari requirement/kontrak terkait di PRD;
- cari implementasi;
- cari test yang sudah ada;
- cocokkan error dengan layer yang gagal.

Jangan mengubah business rule hanya agar test menjadi hijau.

Urutan prioritas:

```text
PRD / requirement
    ↓
existing architecture & interfaces
    ↓
existing tests / fixtures
    ↓
implementation
    ↓
new test for the bug
```

Jika implementasi bertentangan dengan PRD, perlakukan implementasi sebagai kandidat bug, bukan otomatis sebagai source of truth.

### 1.2 Death-loop breaker

Agent **WAJIB berhenti mengulang strategi** bila:

- error message identik muncul ≥ 2 kali setelah patch;
- test yang sama gagal dengan stack trace substantif yang sama ≥ 2 kali;
- patch hanya mengubah nama/format tanpa mengubah penyebab;
- agent sudah melakukan 3 percobaan perbaikan untuk akar masalah yang sama.

Setelah threshold tercapai:

```text
STOP
→ simpan error terakhir
→ bandingkan percobaan sebelumnya
→ identifikasi invariant/kontrak yang dilanggar
→ ubah strategi diagnosis
→ patch baru hanya jika ada hipotesis baru
```

Jangan melakukan:

```text
run test
→ error
→ patch random
→ run test
→ error sama
→ patch random lagi
```

### 1.3 Jangan memperbaiki symptom berulang kali

Bedakan:

- **Root cause:** penyebab teknis pertama yang membuat kontrak gagal.
- **Symptom:** error turunan yang muncul setelah root cause.
- **Noise:** warning/log yang tidak menyebabkan kegagalan.

Cari error paling awal dalam dependency chain.

Contoh:

```text
DB write failed
   ↑
invalid score payload
   ↑
missing feature
   ↑
fundamental source returned empty
```

Perbaiki titik paling awal yang melanggar kontrak, bukan sekadar menangkap exception paling bawah.

---

## 2. Siklus Debug Standar

Gunakan urutan ini setiap kali menerima error:

### Step A — Reproduce

Catat:

```text
command:
date/run_date:
environment:
config/model_version:
input/fixture:
expected:
actual:
exception:
first failing frame:
```

Utamakan reproduksi deterministik.

Untuk pipeline tanggal tertentu:

```bash
screener run daily --date YYYY-MM-DD --dry-run
```

Untuk debugging komponen:

```bash
screener ingest prices --from DATE --to DATE
screener score --date YYYY-MM-DD
screener screen --name quality_value_idx --date YYYY-MM-DD
screener report preview --date YYYY-MM-DD
```

### Step B — Classify

Klasifikasikan error ke satu kategori utama:

| Kategori | Contoh |
|---|---|
| Config | schema YAML salah, parameter missing |
| Data | schema mismatch, stale data, duplicate bar |
| Source | yfinance/IDX timeout/rate limit |
| Storage | unique violation, transaction failure |
| Feature | NaN, division by zero, invalid domain |
| Scoring | normalisasi, gate, missing pillar |
| Numerical | convergence, unstable matrix, invalid probability |
| Actuarial | survival/hazard/Markov inconsistency |
| Backtest | look-ahead, point-in-time leak, cost bug |
| Alert | dedupe/cooldown/hysteresis |
| Telegram | 429, malformed MarkdownV2, message > 4096 |
| Ops | retry, timeout, timezone, scheduler |
| Security | secret leakage, unauthorized chat |

### Step C — Inspect contract

Cari requirement yang relevan, khususnya:

- `FR-DAT-*`
- `FR-QC-*`
- `FR-FEA-*`
- `FR-SCR-*`
- `FR-CAQS-*`
- `FR-STO-*`
- `FR-ACT-*`
- `FR-BT-*`
- `FR-TG-*`
- `FR-CFG-*`
- `FR-OPS-*`
- `NFR-*`

Kemudian cek acceptance criteria Bagian 15.

### Step D — Form one falsifiable hypothesis

Format:

```text
Hypothesis:
X menyebabkan Y karena Z.

Evidence:
...

Test:
...

Expected:
...

If false:
ubah hipotesis; jangan mengulang patch yang sama.
```

Jangan membuat lima hipotesis sekaligus lalu mengubah lima area kode.

### Step E — Minimal patch

Patch harus:
- sesempit mungkin;
- mempertahankan public interface jika tidak perlu diubah;
- tidak menghapus validasi untuk membuat test lolos;
- tidak memindahkan business logic ke tempat acak;
- menambah regression test untuk bug.

### Step F — Verify

Urutan:

```text
targeted unit test
→ targeted integration test
→ affected E2E test
→ full relevant test suite
```

Untuk bug numerik, verifikasi juga invariant matematis.

Untuk bug pipeline, verifikasi idempotensi.

Untuk bug alert, verifikasi dedupe + cooldown + hysteresis.

### Step G — Record

Simpan:
- error awal;
- root cause;
- file/komponen yang berubah;
- test yang membuktikan fix;
- requirement ID terkait.

---

## 3. Invariant yang Tidak Boleh Dirusak

### Data & ingestion

- `low ≤ open, close ≤ high`
- harga > 0
- volume ≥ 0
- data error dikarantina
- source yang menang harus tercatat
- fallback tidak boleh menghilangkan audit trail
- `publish_date` wajib dihormati untuk point-in-time
- raw response disimpan/cache bila diperlukan untuk replay

### Pipeline

- hari non-bursa → `skipped_holiday`
- rerun tanggal yang sama → tidak membuat duplikasi
- key idempotensi:

```text
(job_name, run_date, params_hash)
```

- retry hanya untuk kegagalan yang retryable
- validation error **bukan** target retry
- concurrent run untuk `(job_name, run_date)` harus dicegah
- kegagalan utama harus terlihat oleh admin

### Scoring

- CAQS ∈ [0, 100]
- pillar score ∈ [0, 1]
- bobot valid dan jumlahnya = 1
- missing data menggunakan shrinkage, bukan diam-diam dipalsukan
- `DataConfidence` tetap dihitung
- `model_version` tercatat

### Numerical

- probability ∈ [0, 1]
- survival tidak naik terhadap waktu
- Markov transition row-sum = 1
- state Terminasi absorbing
- Monte Carlo seed harus deterministik
- SE dilaporkan
- MC/PDE/closed-form wajib konsisten dalam toleransi PRD

### Alert

- `dedupe_key` unik
- cooldown harus dihormati
- severity yang naik boleh menembus cooldown
- hysteresis mencegah alert berosilasi
- message > 4096 karakter harus dipecah
- Telegram 429 harus memakai backoff

---

## 4. Retry Matrix

| Error | Retry? | Tindakan |
|---|---:|---|
| Timeout jaringan | Ya | exponential backoff |
| HTTP 429 | Ya | honor retry/backoff |
| Temporary 5xx | Ya | exponential backoff |
| Source kosong tetapi HTTP sukses | Tidak langsung | validasi → fallback source |
| Schema invalid | Tidak | quarantine + fail/degrade |
| Fundamental balance mismatch | Tidak | quarantine + issue |
| Config invalid | Tidak | fail fast |
| Duplicate DB key | Tidak jika bug idempotensi | investigasi |
| Numerical invalid domain | Tidak | fail component + diagnose |
| Telegram malformed payload | Tidak berulang | fix formatter |
| Telegram >4096 chars | Tidak | split message |
| Holiday | Tidak | `skipped_holiday` |
| Job timeout | Retry sesuai retry window | checkpoint/progress dulu |

PRD menetapkan exponential backoff 3 kali untuk kegagalan jaringan:

```text
30 detik
2 menit
10 menit
```

---

## 5. Timeboxing dan Escalation

Gunakan batas percobaan, bukan loop tak terbatas:

```text
Attempt 1 → reproduce + targeted diagnosis
Attempt 2 → new hypothesis + minimal patch
Attempt 3 → alternative strategy / isolate subsystem
```

Jika tetap gagal:

```text
DO NOT:
- menambah retry tanpa batas;
- menonaktifkan validation;
- swallow exception;
- hardcode data agar test lewat;
- mengubah threshold PRD tanpa alasan;
- mematikan test.

DO:
- preserve failing fixture;
- tulis regression test;
- isolate smallest failing component;
- laporkan exact blocker;
- lanjut ke subsystem lain hanya bila dependency memungkinkan.
```

---

## 6. Pola Anti-Death-Loop Berdasarkan Jenis Bug

### Source failure

```text
source A fails
→ validate failure type
→ fallback B
→ fallback C
→ cache/manual only if configured
→ mark degraded
→ notify admin
```

Jangan:

```text
retry source A indefinitely
```

### Pipeline failure

```text
job starts
→ acquire lock
→ checkpoint
→ execute step
→ persist result
→ next step
```

Saat rerun:

```text
read existing successful outputs
→ skip/reuse safe stages
→ recompute only invalid/incomplete stages
```

### Stochastic timeout

PRD mengizinkan degradasi anggun:

```text
stochastic/actuarial fails or exceeds time budget
→ continue with available pillars
→ renormalize weights
→ report SR/AC unavailable
→ notify admin
```

Jangan membuat satu modul mahal menjatuhkan seluruh laporan harian.

### Alert loop

```text
same rule + same ticker
→ compute dedupe_key
→ check cooldown
→ suppress unless severity increases
```

Jangan mengatasi alert storm dengan mematikan seluruh alert engine.

---

## 7. Debug Checklist

```text
[ ] Error direproduksi?
[ ] Run date dan timezone benar?
[ ] Trading calendar benar?
[ ] Config valid?
[ ] Model version benar?
[ ] Input fixture/snapshot dicatat?
[ ] Root cause dibedakan dari symptom?
[ ] Apakah error sudah pernah terjadi dengan stack trace sama?
[ ] Jika ya, strategy sudah diganti?
[ ] Ada regression test?
[ ] Idempotensi masih terjaga?
[ ] Retry hanya pada error retryable?
[ ] Fallback masih aktif?
[ ] Data error masih dikarantina?
[ ] Secret tidak masuk log?
[ ] Admin alert tetap bekerja?
[ ] Requirement ID sudah ditautkan?
```

---

## 8. Output Debug yang Wajib Dihasilkan Agent

Saat selesai memperbaiki bug, format laporan:

```text
BUG:
<ringkasan>

ROOT CAUSE:
<akar masalah>

IMPACT:
<komponen terdampak>

FIX:
<perubahan>

TEST:
<test yang dijalankan>

REGRESSION TEST:
<test baru/yang diperbarui>

PRD CONTRACT:
<FR/NFR/US terkait>

RISK:
<risiko residual, jika ada>
```

---

## 9. Prinsip Terakhir

**Kecepatan debugging berasal dari memperkecil ruang masalah, bukan dari menambah percobaan.**

Prioritaskan:

```text
reproduce
→ isolate
→ hypothesize
→ patch minimally
→ verify
→ record
```

Jangan biarkan agent terjebak:

```text
error → patch → same error → patch → same error → ...
```

Death loop harus diputus dengan perubahan strategi diagnosis.
