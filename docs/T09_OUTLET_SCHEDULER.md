# T09 — Scheduler, recovery dan Absent outlet

**Tanggal:** 15 Oktober 2026  
**Status:** backend selesai. **Readiness dan mode outlet tetap nonaktif. T10 belum dimulai.**

## Cakupan

```text
custom_hr/overrides/shift_type.py
custom_hr/services/outlet_scheduler.py
custom_hr/services/test_outlet_scheduler.py
custom_hr/overrides/employee_checkin.py
custom_hr/services/outlet_attendance.py  # pembaruan docstring integrasi
custom_hr/hooks.py
```

Tidak mengubah core HRMS, schema, fixtures, frontend, atau geofence. Tidak melakukan commit/push Git.

## Registrasi dan deployment

Hooks mendaftarkan:

- Override `Shift Type` → `custom_hr.overrides.shift_type.CustomShiftType`.
- Event `hourly` → `custom_hr.services.outlet_scheduler.run_outlet_attendance_scheduler`.

Pada `development.localhost`, hanya event tersebut didaftarkan melalui helper native `insert_single_event("Hourly", method)`. Pemanggilan diulang dua kali, hasil tetap **satu Scheduled Job Type**, frequency Hourly. Tidak menjalankan `sync_jobs()` yang dapat menghapus event lain, tidak migrate schema, dan tidak mengubah enablement scheduler site.

Cache site dibersihkan; controller pada proses baru terverifikasi memakai `CustomShiftType`. Proses server/worker lama tetap memerlukan reload normal saat deployment agar class/module cache di memorinya diperbarui. Tidak merestart service atau mengklaim semua worker hangat sudah memuat kode baru pada T09. Sebelum aktivasi, lakukan deployment/reload dan UAT runtime sesuai task terkait.

Pendaftaran job adalah perubahan konfigurasi **yang disengaja dan dipertahankan**, bukan data uji. Semua transaksi verifikasi memakai baseline setelah pendaftaran itu.

## Pemisahan dari native

`CustomShiftType` mempertahankan perilaku native untuk sumber non-Outlet, termasuk NULL/empty source pada data lama:

1. `get_employee_checkins()` menghapus nama log yang sumber DB-nya Outlet dari hasil native.
2. `_process(logs)` memeriksa lagi provenansi DB, termasuk bila menerima daftar queued/cached tanpa custom fields.
3. `get_dates_for_attendance()` menghapus tanggal yang dikelola outlet dari auto-Absent berbasis assignment/default shift.
4. Jalur `mark_absent_for_half_day_dates()` tidak menyelesaikan half-day leave outlet melalui assignment lama. Algoritme native dipertahankan untuk tanggal unmanaged.
5. Job realtime native `process_shift_attendance_now()` hanya memakai log non-Outlet untuk pending-IN dan penentuan sync. Log outlet sendiri tidak bisa memajukan `last_sync_of_checkin`.

Tidak mematikan Shift Type bersama secara global. Dua outlet dapat merujuk Shift Type yang sama; sumber outlet dan native tetap terpisah. Processor native masih dapat menjalankan perilaku shift-wide/commit aslinya untuk **data native**; processor/recovery outlet tidak memanggilnya.

Guard auto-Absent native memakai current locking reads di bawah Employee lock. Provenansi sesi/Attendance Outlet, termasuk Attendance dibatalkan, tetap melindungi tanggal setelah transfer/mode-off. Orphan log Outlet dengan work date kosong juga dilindungi melalui tanggal shift atau waktu log yang tersedia.

Tanpa provenansi sesi, effective-from Outlet yang tersimpan menjadi batas konservatif native:

- Mode aktif: tanggal sejak effective date tidak di-Absent-kan melalui assignment native.
- Mode off: tanggal sejak effective date sampai tanggal modifikasi terakhir Outlet tetap dilindungi karena riwayat toggle tidak tersedia.
- Tanggal native setelah batas mode-off tersebut tetap dapat memakai auto-Absent native.

Ini bukan rekonstruksi seluruh riwayat membership/toggle. Tanggal historis tanpa provenansi yang tidak dapat dibuktikan memerlukan koreksi/rekonsiliasi HR, bukan asumsi assignment lama.

## Recovery sesi

Scheduler selalu menjalankan recovery, termasuk ketika readiness off atau mode/current outlet sudah berubah:

- Cari IN `attendance_source=Outlet`, tidak skip/offshift, dengan tautan Attendance IN kosong atau OUT pasangannya belum tertaut.
- Discovery memakai keyset pagination berdasarkan nama IN, bukan offset.
- Ukuran halaman teknis dapat diatur lewat site config `outlet_scheduler_batch_size`, default 200. Ini bukan toleransi bisnis.
- Pasangan lengkap dikirim ke job T08 dengan kedua identitas IN–OUT.
- IN tanpa OUT baru masuk antrean setelah waktu server **lebih besar** dari deadline tersimpan.
- Job memakai `enqueue_after_commit=True`, identitas deduplikasi stabil per sesi/jenis pasangan, dan `deduplicate=True`.
- Snapshot/deadline invalid dicatat dengan referensi IN; discovery berikutnya tidak kelaparan karena satu sesi rusak.

Discovery bersifat advisory. Worker T08 membaca ulang di bawah Employee lock, memastikan tidak ada OUT ganda/asing, dan menghormati Attendance resmi/cancelled. Jika OUT muncul setelah discovery IN-only, worker tidak mengarang fallback; pemulihan berikutnya menggunakan pasangan lengkap.

Normal antrean OUT T08 dan recovery dapat datang bersamaan. Deduplikasi antrean mengurangi pekerjaan ulang; **jaminan tidak duplikat tetap berasal dari locking/current reads worker**, bukan hanya job ID.

### Tidak OUT

Worker T08 menyimpan:

```text
status perhitungan = Present
missing_checkout = 1
working_hours = durasi jadwal snapshot
working_hours_source = Locked Shift Allocation
in_time = IN aktual
out_time / source_checkout = kosong
early_exit = 0
actual_overtime_duration = 0
```

Late Entry memakai IN aktual dan toleransi snapshot. Kebijakan holiday/cuti/Attendance resmi T08 tetap berlaku. Tidak membuat OUT otomatis dan tidak memakai jam pulang fiktif.

Tepat pada deadline, sesi tetap terbuka. Pengambilan waktu server dan penguncian worker menjaga finalisasi tidak mendahului keputusan OUT yang sah.

## Absent tanpa IN maupun OUT

Bagian ini hanya berjalan ketika readiness siap dan Outlet secara eksplisit aktif/mode on. Scheduler mengantrekan job per Employee aktif di outlet opt-in; tidak mencari Shift Assignment.

Job mengevaluasi tanggal lampau yang eligible, memangkas tanggal yang sudah memiliki hasil resmi/draft/cancelled, dan tetap memeriksa ulang setiap tanggal yang diproses di bawah Employee lock. Pending half-day leave tetap masuk evaluasi.

### Batas tanggal yang dapat dipastikan

Belum ada ledger riwayat Employee→Outlet atau versi jadwal per tanggal. Karena itu, **jangan backfill Absent dari konfigurasi terbaru untuk masa sebelum mutasi/perubahan**.

Tanggal pertama eligible adalah maksimum dari:

- Hari penuh sejak `outlet_auto_shift_effective_from`.
- Hari penuh setelah modifikasi terakhir Employee dan Outlet.
- Tanggal mulai bekerja/creation bila DOJ tidak tersedia.

Worker juga menolak tanggal sebelum hari penuh setelah modifikasi terakhir Shift Type aktif yang dipakai outlet. Perubahan tepat tengah malam dapat berlaku pada tanggal tersebut; perubahan selain tengah malam baru dianggap stabil mulai hari berikutnya. Relieving Date dan status aktif tetap diperiksa.

Tradeoff yang disengaja: perubahan Employee yang tidak berkaitan dengan outlet juga dapat membuat backfill hari sebelumnya dilewati. Ini lebih aman daripada menandai Absent dengan membership/jadwal yang tidak dapat dibuktikan. Pemulihan sesi yang memiliki snapshot **tidak** dibatasi aturan ini. Kebutuhan backfill historis tanpa log harus diputuskan HR atau ditopang ledger historis tersendiri, bukan membuka batas secara diam-diam.

### Kapan tanggal ditutup

Tanpa IN, tidak ada shift yang dapat dipilih secara sah. Worker membaca seluruh jendela shift aktif untuk tanggal kerja itu dan menunggu **batas OUT paling akhir** di antaranya.

Jika ada pilihan shift malam tanggal 15 yang selesai tanggal 16, tanggal kerja 15 baru ditutup setelah 16 pukul 23.59.59, bukan saat shift siang berakhir. Kandidat IN ambigu lintas tanggal tidak dipakai untuk memilih shift Absent; worker hanya membutuhkan konfigurasi jadwal yang valid dan batas penutupan teraman.

### Hasil per kondisi

| Kondisi | Perilaku |
|---|---|
| Ada log IN, OUT, atau keduanya untuk work date | Jangan jalankan no-log Absent; sesi/masalah log ditangani jalur tersendiri |
| OUT-only/orphan log | Tidak membuat IN atau Attendance Absent; field hilang tetap kosong. Bukan fitur self-service OUT tanpa IN |
| Tidak ada log, hari masih terbuka | Skip |
| Full holiday Outlet | Skip Absent, terlepas dari flag marking kehadiran pada hari libur |
| Full approved leave | Skip Absent; pertahankan alur cuti resmi |
| Half-day holiday tanpa cuti | Masih ada separuh hari kerja; tanpa log dapat Absent |
| Half-day leave approved | Half Day dengan `half_day_status=Absent` untuk separuh kerja |
| Half-day leave pending sudah punya Attendance | Lengkapi hanya status separuh kerja, pertahankan ref cuti/shift/metrics resmi |
| Half-day leave + half-day holiday | Skip untuk HR: tidak ada data yang membuktikan cakupan separuh hari yang sama atau berbeda |
| Attendance resmi/draft/cancelled sudah ada | Jangan menimpa/menggandakan/membuat ulang |
| Beberapa Attendance aktif/cuti approved atau konfigurasi invalid | Error dengan referensi Employee/tanggal, bukan memilih sembarang |

Tanggal log mengikuti `shift_work_date` jika tersedia, lalu shift start, lalu tanggal timestamp bila konteks shift juga kosong. OUT shift malam yang memiliki work date tidak dipindahkan ke tanggal kalender pulang.

Attendance no-log baru menyimpan `attendance_source=Outlet` dan outlet yang dievaluasi, tetapi **shift, IN, OUT, source check-in/out, dan working-hours source tetap kosong**. Jam kerja 0, tidak ada late/early/missing-OUT buatan. Audit Comment menjelaskan evaluasi tanpa log dan batas harinya. Tidak dibuat satu Attendance untuk setiap shift yang tidak dipilih.

Holiday berasal dari Holiday List Outlet; daftar libur individual tidak digunakan untuk keputusan ini. Insert/submit Attendance baru tetap menjalankan validasi native, termasuk cuti.

## Koreksi resmi dan pembatalan

- Attendance Request native dapat memperbarui status fallback yang cocok shift/tanggalnya, dengan referensi request dan audit Comment.
- Pengujian benar-benar melakukan insert/submit Attendance Request, lalu memastikan retry tidak menimpa hasil koreksi atau membuat Attendance aktif tambahan.
- Attendance Request native bukan form koreksi timestamp/jam kerja; untuk koreksi jam gunakan jalur administratif Attendance/cancel-amend yang sesuai dengan audit. Jangan mengubah snapshot/log IN asli atau menciptakan OUT fiktif.
- Metadata `Locked Shift Allocation` tetap mencatat sumber fallback asli; status hasil koreksi resmi tidak membuat sumber tersebut menjadi jam log aktual.
- Cancellation tetap dihormati oleh worker T08 dan evaluasi no-log. Recovery mungkin menemukan kembali log yang telah di-unlink native cancellation, tetapi worker tidak membuat ulang Attendance cancelled.
- Amendment/hasil resmi aktif diprioritaskan; draft tidak disubmit otomatis oleh recovery.

Setiap evaluasi tanggal memiliki savepoint. Error rollback perubahan tanggal, menulis deferred Error Log dengan Employee/tanggal dan traceback, lalu re-raise. Validation error satu tanggal tidak menghalangi tanggal berikutnya; kegagalan DB/deadlock tetap dibawa ke penanganan worker. Tidak melakukan commit manual di helper outlet.

## Bukti pengujian

- **52 test baru T09**, total suite T03–T09 **314 test lulus**.
- Parsing AST enam file Python lulus; `git diff --check` lulus selain warning konversi LF/CRLF. Ruff tidak tersedia dan tidak memasang dependency baru.
- **32 pemeriksaan transaksi nyata** pada `development.localhost`.

Cakupan nyata: registrasi/controller, no-log Absent dan retry, batas hari/shift malam, partial activation, stabilitas Employee/Outlet/Shift Type, full/half holiday, full/half leave, cakupan half-day yang ambigu, IN-only/OUT-only/orphan, recovery pasangan dan Tidak OUT, mode-off/mutasi/readiness-off, cancellation, Attendance Request yang benar-benar disubmit, sumber native/outlet pada satu dan dua outlet yang berbagi shift, native sync/half-day guard, rentang tanggal/pruning, serta kegagalan atomik dengan referensi Employee/tanggal.

Verifier memanggil worker/recovery secara langsung dan menangkap dispatch antrean. Tidak menjalankan RQ/HTTP/browser dan tidak mengklaim committed concurrent-worker UAT; UAT tersebut tetap T15. Employee-lock serialization telah diuji dua koneksi pada T05–T06/T08. Approved leave menggunakan row fixture rollback-only, bukan pengujian approval/ledger cuti penuh. Logger kegagalan disengaja di-mock agar tidak meninggalkan deferred Error Log uji.

Fingerprint **18 tabel** sama sebelum/sesudah transaksi verifikasi: 17 tabel T08 ditambah Scheduled Job Type. Baseline sudah mencakup satu registrasi job T09 yang sengaja dipertahankan. Semua log/Attendance/cuti/request/Comment/master uji di-rollback; **0 outlet** mode otomatis aktif.

Company pilot yang tidak sesuai dan timestamp stabilitas Employee/Outlet/Shift Type hanya disamakan sementara di dalam transaksi verifier, lalu rollback. Data permanen tidak dikoreksi tanpa instruksi.

Bukti lokal, bukan repository:

```text
C:\Users\Ardhan\AppData\Local\Temp\opencode\outlet-t09-verification-20261015-134257.json
```

## Status akhir

**T09 selesai; berhenti sebelum T10.** Readiness tetap `False`, seluruh mode outlet tetap off, kedua Shift Type pilot tidak diaktifkan auto-attendance native, dan frontend/geofence belum diubah. Sesudah T09, pengguna menyetujui Company Employee sebagai sumber Attendance sehingga Company Outlet boleh berbeda; [penyesuaian tersebut sudah diterapkan](EMPLOYEE_COMPANY_SOURCE.md) tanpa mengubah master. Tidak ada aktivasi pilot atau perluasan outlet pada T09 maupun penyesuaian Company.
