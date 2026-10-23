# Custom HR — prototipe APK check-in

Proyek Capacitor 7 terpisah dari frontend web. Source UI ada di `src/`;
proyek Android Studio ada di `native/`. Tidak mengubah backend atau build web.

## Fitur

- Koneksi HTTPS ke API Frappe menggunakan API key/secret **pengguna sendiri**.
- Membaca `Settings.Global.DEVELOPMENT_SETTINGS_ENABLED` melalui plugin Java
  `DevicePolicy`. Check-in ditolak jika aktif atau status gagal dibaca.
- Mengambil GPS foreground dengan izin lokasi Android.
- Memakai API `get_checkin_context`, `validate_checkin_location`, dan
  `submit_checkin` yang sudah ada. Hanya mengirim `IN`, bukan `OUT`.
- Memakai lifecycle `CheckinSubmission` dari frontend web untuk UUID idempoten.
  ID permintaan belum pasti disimpan lokal per server/karyawan, bukan token/GPS.
  Hasil jaringan yang belum pasti dicek melalui `get_checkin_request_result`;
  prototipe tidak otomatis mengirim ulang atau membuat ID baru.

## Persiapan

- Node.js 22 LTS dan npm.
- Android Studio, JDK 21, Android SDK Platform 35 dan SDK Build Tools.
- Perangkat Android minimal Android 6 (API 23).
- Server Frappe dapat diakses perangkat melalui HTTPS dengan sertifikat valid.
- Akun uji terhubung ke Employee aktif, izin HR yang sesuai, serta konfigurasi
  jadwal/outlet/lokasi server yang valid. Buat API key/secret melalui pengelola
  akun Frappe. **Jangan gunakan token Administrator atau akun bersama.**

## Build

Jalankan dari direktori ini pada lingkungan yang sama dengan Android SDK:

```bash
npm ci
npm test
npm run sync
npm run open
```

Di Android Studio, tunggu Gradle sync lalu jalankan ke perangkat atau pilih
menu build APK. Untuk CLI Linux/WSL yang sudah memiliki JDK/SDK:

```bash
cd native
./gradlew assembleDebug
```

Output: `native/app/build/outputs/apk/debug/app-debug.apk`.
Pada Windows gunakan `gradlew.bat assembleDebug`. Jika source disimpan di WSL
tetapi Android Studio/SDK ada di Windows, lebih mudah salin/clone proyek
`custom_hr` ke filesystem Windows, kemudian jalankan `npm ci` dan
`npm run sync` di sana; jangan memakai `node_modules` Linux pada Windows.
Jangan commit `local.properties`, kredensial, atau signing keystore.

## Uji pada perangkat

1. Pasang debug APK, masukkan origin server (contoh `https://hr.example.com`)
   dan API key/secret pengguna uji, lalu tekan **Hubungkan**.
2. Dengan Opsi Pengembang aktif, tekan **Periksa perangkat** atau **Check-in**:
   operasi harus diblokir sebelum mengirim absensi.
3. Matikan sakelar utama Opsi Pengembang melalui pengaturan Android. Mematikan
   USB debugging saja tidak cukup. Debugger/ADB bisa terputus; buka APK manual.
4. Tekan **Check-in**, izinkan lokasi, pastikan GPS aktif. Jika aturan server
   mengizinkan, aplikasi menampilkan nama Employee Checkin dan waktu server.
5. Tekan sekali lagi: server sudah meminta OUT, jadi prototipe harus menolak IN.
6. Uji izin GPS ditolak, server offline, token salah, di luar radius, dan
   perpindahan ke pengaturan saat proses berlangsung. Tidak boleh ada bypass.
7. Jika koneksi terputus saat submit, sambungkan ulang akun yang sama dan tekan
   **Check-in** untuk memeriksa hasil UUID sebelumnya. Bila belum ditemukan,
   tunggu/periksa dengan HR; jangan hapus data aplikasi untuk memaksa IN baru.

`npm run dev` hanya untuk pratinjau UI. Pemeriksaan Android dan check-in sengaja
tidak tersedia di browser; tidak ada fallback yang menganggap perangkat aman.

## Batasan penting

- Ini **prototipe**, bukan aplikasi produksi. API secret hanya disimpan dalam
  memori, tidak di localStorage, source code, atau log. Setelah restart harus
  diisi lagi. Login username/password/SSO belum diimplementasikan.
- Token yang dimasukkan memberikan akses sesuai izin akun. Hanya hubungkan
  ke server tepercaya; gunakan akun uji dengan izin minimum.
- Check-in benar-benar tercatat di server. Tidak ada dummy attendance.
- Aturan radius, shift, sesi, dan verifikasi wajah tetap berlaku. Jika server
  mewajibkan wajah, API akan menolak; prototipe belum memiliki fitur selfie
  dan tidak mengubah aturan tersebut agar bisa lolos.
- Developer Options aktif bukan bukti mock location. Status ini bisa berbeda
  pada ROM tertentu dan dapat dimanipulasi di perangkat root/aplikasi modifikasi.
  Belum ada deteksi mock GPS atau Play Integrity; pemeriksaan lokal tidak
  membuktikan keaslian perangkat/lokasi kepada backend. Klien lain tetap dapat
  memanggil API sesuai aksesnya; ini bukan kebijakan wajib di sisi server.
- Tidak ada background tracking, check-out, push notification, atau absensi
  offline. APK debug bukan APK rilis bertanda tangan untuk distribusi.

## Status verifikasi awal

Frontend build dan unit test bisa dijalankan dengan Node.js. Native Gradle
build dan uji perangkat memerlukan JDK/SDK; keduanya belum diverifikasi di
lingkungan pengembangan awal yang belum memiliki Java.
