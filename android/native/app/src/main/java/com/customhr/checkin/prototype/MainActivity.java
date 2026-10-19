package com.customhr.checkin.prototype;

import android.os.Bundle;
import com.getcapacitor.CapConfig;
import com.getcapacitor.BridgeActivity;
import java.io.File;
import java.io.FileOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

public class MainActivity extends BridgeActivity {
    private ServerRecovery recovery;
    private String activeServerUrl;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(DevicePolicyPlugin.class);
        super.onCreate(savedInstanceState);
    }

    @Override
    protected void load() {
        try {
            JSONObject settings;
            try (InputStream input = getAssets().open("capacitor.config.json")) {
                ByteArrayOutputStream output = new ByteArrayOutputStream();
                byte[] buffer = new byte[4096];
                int count;
                while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                settings = new JSONObject(output.toString("UTF-8"));
            }
            JSONObject server = settings.getJSONObject("server");
            activeServerUrl = ServerUrl.normalize(server.getString("url"));
            String saved = getSharedPreferences("hrms_server", MODE_PRIVATE).getString("url", null);
            if (saved != null) {
                try { activeServerUrl = ServerUrl.normalize(saved); }
                catch (IllegalArgumentException ignored) { /* Retain the bundled default. */ }
            }
            server.put("url", activeServerUrl);
            // Preserve all bundled options, including edge-to-edge handling. Only
            // the selected server changes; never broaden allowNavigation.
            File directory = new File(getFilesDir(), "runtime_config");
            if (!directory.isDirectory() && !directory.mkdirs()) throw new java.io.IOException("config directory");
            try (FileOutputStream output = new FileOutputStream(new File(directory, "capacitor.config.json"))) {
                output.write(settings.toString().getBytes(StandardCharsets.UTF_8));
            }
            config = CapConfig.loadFromFile(this, directory.getAbsolutePath());
        } catch (Exception exception) {
            config = CapConfig.loadDefault(this);
            activeServerUrl = config.getServerUrl();
        }
        super.load();
        recovery = new ServerRecovery(this, bridge, activeServerUrl);
        recovery.install();
    }

    @Override
    public void onResume() {
        super.onResume();
        if (recovery != null) recovery.start();
    }

    @Override
    public void onPause() {
        if (recovery != null) recovery.stop();
        super.onPause();
    }

    @Override
    public void onDestroy() {
        if (recovery != null) recovery.destroy();
        super.onDestroy();
    }
}
