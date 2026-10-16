package com.customhr.checkin.prototype;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(DevicePolicyPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
