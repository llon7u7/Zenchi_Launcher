package org.zenchi;

import android.app.role.RoleManager;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import org.kivy.android.PythonActivity;

public class ZenchiActivity extends PythonActivity {
    private static final String TAG = "ZenchiLauncher";
    private static final int REQUEST_CODE_LAUNCHER = 1001;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        Log.d(TAG, "ZenchiActivity onCreate called");
        super.onCreate(savedInstanceState);
        Log.d(TAG, "ZenchiActivity super.onCreate completed");
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        Log.d(TAG, "onActivityResult called with requestCode=" + requestCode + ", resultCode=" + resultCode);
        super.onActivityResult(requestCode, resultCode, data);
        
        if (requestCode == REQUEST_CODE_LAUNCHER) {
            if (resultCode == RESULT_OK) {
                Log.d(TAG, "User confirmed Zenchi as launcher - RESULT_OK");
            } else if (resultCode == RESULT_CANCELED) {
                Log.d(TAG, "User canceled launcher request - RESULT_CANCELED");
            } else {
                Log.d(TAG, "Launcher request result code: " + resultCode);
            }
            
            // Verificar inmediatamente si somos el launcher
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                RoleManager roleManager = (RoleManager) getSystemService(RoleManager.class);
                boolean isHome = roleManager.isRoleHeld(RoleManager.ROLE_HOME);
                Log.d(TAG, "Is ROLE_HOME held after activity result? " + isHome);
            }
        }
    }
}
