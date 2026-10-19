package com.customhr.checkin.prototype;

import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import androidx.appcompat.app.AlertDialog;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebViewClient;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import javax.net.ssl.HttpsURLConnection;

/** Native-only recovery UI: it does not depend on the failed remote frontend. */
final class ServerRecovery {
    private final MainActivity activity;
    private final Bridge bridge;
    private final String serverUrl;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private AlertDialog dialog;
    private AlertDialog trustDialog;
    private boolean running;
    private boolean checking;
    private boolean destroyed;
    private int generation;
    private int failures;

    ServerRecovery(MainActivity activity, Bridge bridge, String serverUrl) {
        this.activity = activity;
        this.bridge = bridge;
        this.serverUrl = serverUrl;
    }

    void install() {
        bridge.setWebViewClient(new BridgeWebViewClient(bridge) {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                super.onReceivedError(view, request, error);
                if (request.isForMainFrame()) show();
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                super.onReceivedHttpError(view, request, response);
                // Login rejection / API, image and iframe failures are not a server disconnect.
                if (request.isForMainFrame() && unavailable(response.getStatusCode())) show();
            }
        });
    }

    private static boolean unavailable(int code) {
        return code == 404 || code == 410 || code == 408 || code >= 500;
    }

    void start() {
        running = true;
        handler.removeCallbacks(poll);
        handler.postDelayed(poll, 15000);
    }

    void stop() {
        running = false;
        generation++;
        handler.removeCallbacks(poll);
    }

    void destroy() {
        destroyed = true;
        stop();
        if (dialog != null) dialog.dismiss();
        if (trustDialog != null) trustDialog.dismiss();
        network.shutdownNow();
    }

    // HRMS is an SPA: a server can disappear without a new top-level navigation.
    // Two consecutive checks avoid opening the form for a single brief failure.
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            if (!running || destroyed) return;
            if (!checking && (dialog == null || !dialog.isShowing())) {
                checking = true;
                final int attemptGeneration = generation;
                network.execute(() -> {
                    boolean reachable = reachable();
                    handler.post(() -> {
                        checking = false;
                        if (destroyed || !running || attemptGeneration != generation) return;
                        failures = reachable ? 0 : failures + 1;
                        if (failures >= 2) show();
                    });
                });
            }
            handler.postDelayed(this, 30000);
        }
    };

    private boolean reachable() {
        HttpsURLConnection connection = null;
        try {
            connection = (HttpsURLConnection) new URL(serverUrl).openConnection();
            connection.setRequestMethod("HEAD");
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(10000);
            connection.setReadTimeout(10000);
            int status = connection.getResponseCode();
            // A login redirect or HEAD-not-supported response means server is reachable.
            return status >= 200 && status < 500 && !unavailable(status);
        } catch (Exception exception) {
            return false;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private void show() {
        if (destroyed || activity.isFinishing() || (dialog != null && dialog.isShowing())) return;
        int padding = Math.round(24 * activity.getResources().getDisplayMetrics().density);
        LinearLayout content = new LinearLayout(activity);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(padding, padding / 2, padding, 0);
        TextView help = new TextView(activity);
        help.setText("Periksa koneksi internet atau masukkan link server HRMS terbaru. URL lama tetap tersimpan sampai Anda menggantinya.");
        content.addView(help);
        EditText input = new EditText(activity);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setSingleLine(true);
        input.setText(serverUrl);
        input.setHint("https://server-anda/hrms");
        input.setContentDescription("URL server HRMS");
        content.addView(input);
        dialog = new AlertDialog.Builder(activity)
            .setTitle("Server HRMS tidak terhubung")
            .setView(content)
            .setPositiveButton("Ganti server", null)
            .setNegativeButton("Coba lagi", (ignored, which) -> {
                failures = 0;
                bridge.getWebView().loadUrl(serverUrl);
            })
            .setNeutralButton("Tutup", (ignored, which) -> { failures = 0; })
            .create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
            final String selected;
            try { selected = ServerUrl.normalize(input.getText().toString()); }
            catch (IllegalArgumentException exception) {
                input.setError(exception.getMessage());
                return;
            }
            if (selected.equals(serverUrl)) {
                dialog.dismiss();
                failures = 0;
                bridge.getWebView().loadUrl(serverUrl);
                return;
            }
            if (trustDialog != null && trustDialog.isShowing()) return;
            trustDialog = new AlertDialog.Builder(activity)
                .setTitle("Percayai server ini?")
                .setMessage(selected + "\n\nHanya gunakan server milik perusahaan Anda. Halaman server ini dapat mengakses fitur native Android dan Anda mungkin perlu login lagi.")
                .setNegativeButton("Batal", null)
                .setPositiveButton("Percayai dan buka", (confirmation, which) -> {
                    // Commit before recreating: rebuild the bridge with exactly the new
                    // origin, not a wildcard. Never copy cookies to the new server.
                    boolean saved = activity.getSharedPreferences("hrms_server", 0).edit().putString("url", selected).commit();
                    if (!saved) {
                        input.setError("URL gagal disimpan. Coba lagi.");
                        return;
                    }
                    dialog.dismiss();
                    activity.recreate();
                }).create();
            trustDialog.show();
        }));
        dialog.show();
    }
}
