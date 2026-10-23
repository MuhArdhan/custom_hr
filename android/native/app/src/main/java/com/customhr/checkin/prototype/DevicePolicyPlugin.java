package com.customhr.checkin.prototype;

import android.content.Intent;
import android.provider.Settings;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/** Local policy only: this is not device attestation or mock-location detection. */
@CapacitorPlugin(name = "DevicePolicy")
public class DevicePolicyPlugin extends Plugin {
    @PluginMethod
    public void getStatus(PluginCall call) {
        try {
            // No default: missing/unreadable settings must not silently pass.
            int enabled = Settings.Global.getInt(
                getContext().getContentResolver(),
                Settings.Global.DEVELOPMENT_SETTINGS_ENABLED
            );
            JSObject result = new JSObject();
            result.put("developerOptionsEnabled", enabled != 0);
            call.resolve(result);
        } catch (Settings.SettingNotFoundException | SecurityException exception) {
            call.reject("Tidak dapat membaca status Opsi Pengembang. Check-in diblokir.");
        }
    }

    @PluginMethod
    public void openSettings(PluginCall call) {
        try {
            Intent intent = new Intent(Settings.ACTION_SETTINGS);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
            call.resolve();
        } catch (RuntimeException exception) {
            call.reject("Tidak dapat membuka pengaturan. Buka pengaturan Android secara manual.");
        }
    }
}
