package org.zenchi;

import android.app.ActivityManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;

/**
 * Service nativo que vigila qué app está en primer plano y aplica el
 * bloqueo en tiempo real, INCLUSO cuando la Activity de Kivy (Zenchi)
 * está en segundo plano y su Clock está pausado.
 *
 * ¿Por qué es necesario? Kivy detiene su loop de render (y por lo tanto
 * `Clock.schedule_interval`) en cuanto la Activity recibe onPause(), es
 * decir, en cuanto el usuario abre otra app. Un Service corre en el
 * mismo proceso pero de forma independiente de la Activity, así que
 * sigue vivo (mientras sea foreground service) mientras el usuario está
 * dentro de Instagram, YouTube, etc.
 *
 * El Service NO reimplementa toda la lógica de `motor/politica.py`
 * (el algoritmo de límite dinámico se queda en Python, que es donde el
 * usuario ve la mascota y las estadísticas). Este Service solo hace lo
 * mínimo indispensable para poder EXPULSAR al usuario a tiempo:
 *   1. Detecta qué app está en primer plano cada `INTERVALO_MS`.
 *   2. Si esa app ya está en `apps_bloqueadas_hoy` -> la cierra ya mismo.
 *   3. Si no, acumula tiempo para esa app y lo compara contra su límite
 *      (personalizado o el límite por defecto). Si se cumple, la agrega
 *      a `apps_bloqueadas_hoy`, guarda el estado y la cierra.
 *   4. Escribe todo en SharedPreferences para que Python (al volver a
 *      primer plano) se entere y mantenga sus estadísticas consistentes
 *      (ver bridge/estado_compartido.py).
 *
 * Limitación conocida: como no porta el algoritmo de límite dinámico
 * completo, mientras el usuario está DENTRO de una app este Service usa
 * el límite personalizado de esa app (si existe) o el límite por app
 * por defecto, sin el ajuste dinámico basado en proporción de uso total
 * del día. Es una aproximación razonable: lo importante es que el corte
 * ocurra a tiempo; el ajuste fino de límites se sigue viendo reflejado
 * la próxima vez que Python recalcula (por ejemplo, al abrir Zenchi).
 */
public class ZenchiMonitorService extends Service {

    private static final String TAG = "ZenchiMonitorService";
    private static final String CANAL_ID = "zenchi_monitor_channel";
    private static final int NOTIF_ID = 2001;
    private static final long INTERVALO_MS = 1500L; // cada 1.5s revisa foreground

    private static final String PREFS_NOMBRE = "ZenchiPrefsCompartidas";
    private static final String CLAVE_FECHA = "fecha";
    private static final String CLAVE_CACHE_TIEMPOS = "cache_tiempos_por_app";
    private static final String CLAVE_APPS_BLOQUEADAS = "apps_bloqueadas_hoy";
    private static final String CLAVE_LIMITES_PERSONALIZADOS = "limites_personalizados";
    private static final String CLAVE_APPS_ADICTIVAS = "apps_adictivas";
    private static final String CLAVE_LIMITE_APP_DEFECTO = "limite_app_defecto";

    private static final int LIMITE_APP_DEFECTO_SEGUNDOS = 30 * 60;

    private Handler handler;
    private Runnable tarea;

    private String ultimoPaqueteVisto = null;
    private long marcaDeTiempoUltimaMedicion = 0L;

    private View overlayActivo = null;
    private WindowManager windowManager = null;

    @Override
    public void onCreate() {
        super.onCreate();
        crearCanalNotificacion();
        startForeground(NOTIF_ID, construirNotificacion("Vigilando el uso de tus apps"));

        handler = new Handler(Looper.getMainLooper());
        tarea = new Runnable() {
            @Override
            public void run() {
                try {
                    revisarForeground();
                } catch (Exception e) {
                    Log.e(TAG, "Error en ciclo de vigilancia", e);
                }
                handler.postDelayed(this, INTERVALO_MS);
            }
        };
        handler.post(tarea);
        Log.d(TAG, "ZenchiMonitorService creado y vigilando");
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // START_STICKY: si Android mata el proceso por memoria, intenta
        // recrear el Service (sin el intent original).
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        if (handler != null && tarea != null) {
            handler.removeCallbacks(tarea);
        }
        quitarOverlaySiExiste();
        Log.d(TAG, "ZenchiMonitorService destruido");
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // -----------------------------------------------------------------
    // Notificación obligatoria del foreground service
    // -----------------------------------------------------------------

    private void crearCanalNotificacion() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager manager = getSystemService(NotificationManager.class);
            NotificationChannel canal = new NotificationChannel(
                    CANAL_ID, "Zenchi - Vigilancia", NotificationManager.IMPORTANCE_LOW);
            canal.setDescription("Mantiene activo el control de tiempo de Zenchi");
            manager.createNotificationChannel(canal);
        }
    }

    private Notification construirNotificacion(String texto) {
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CANAL_ID);
        } else {
            builder = new Notification.Builder(this);
        }
        builder.setContentTitle("Zenchi")
                .setContentText(texto)
                .setSmallIcon(android.R.drawable.ic_lock_idle_lock)
                .setOngoing(true)
                .setPriority(Notification.PRIORITY_LOW);
        return builder.build();
    }

    // -----------------------------------------------------------------
    // Lógica principal de vigilancia
    // -----------------------------------------------------------------

    private void revisarForeground() {
        SharedPreferences prefs = getSharedPreferences(PREFS_NOMBRE, Context.MODE_PRIVATE);

        String paqueteHome = obtenerPaqueteHome();
        String paqueteZenchi = getPackageName();

        DeteccionForeground deteccion = detectarPaqueteEnPrimerPlano(paqueteHome, paqueteZenchi);
        String paqueteActual = deteccion == null ? null : deteccion.paquete;

        if (paqueteActual == null || paqueteActual.equals(paqueteZenchi) || paqueteActual.equals(paqueteHome)) {
            // Usuario está en Zenchi/Home o no se pudo determinar nada:
            // no hay nada que vigilar/bloquear en este ciclo.
            ultimoPaqueteVisto = null;
            quitarOverlaySiExiste();
            return;
        }

        Set<String> bloqueadas = leerConjunto(prefs, CLAVE_APPS_BLOQUEADAS);

        if (bloqueadas.contains(paqueteActual)) {
            Log.d(TAG, "App ya bloqueada detectada en primer plano: " + paqueteActual);
            expulsarYBloquear(paqueteActual);
            return;
        }

        long ahora = System.currentTimeMillis();

        if (!paqueteActual.equals(ultimoPaqueteVisto)) {
            // ARREGLO: antes, en este primer ciclo solo se "armaba" el
            // cronómetro con `marcaDeTiempoUltimaMedicion = ahora` y se
            // salía sin sumar nada — el usuario tenía que esperar a que
            // pasara un ciclo COMPLETO (INTERVALO_MS) antes de que el
            // tiempo empezara a contar, y encima ese punto de partida no
            // correspondía al momento real de apertura.
            //
            // Ahora usamos el timestamp real del evento MOVE_TO_FOREGROUND
            // (deteccion.timestampCambio) como punto de partida, y
            // contabilizamos el tiempo transcurrido desde ese instante
            // real ya en este mismo ciclo. Así el conteo "arranca
            // automáticamente" en cuanto el Service detecta la app,
            // reflejando el tiempo real que ya lleva abierta, en vez de
            // perder el primer ciclo entero.
            ultimoPaqueteVisto = paqueteActual;

            long puntoDePartida = deteccion.timestampCambio;
            // Clamp de seguridad: si el evento es viejo/atípico (p. ej. el
            // Service se acaba de reiniciar y hay un evento de hace rato),
            // no queremos sumar minutos de golpe. Limitamos el "tiempo ya
            // transcurrido" a como máximo un intervalo de sondeo extra.
            long maximoRazonable = ahora - INTERVALO_MS;
            if (puntoDePartida < maximoRazonable) {
                puntoDePartida = maximoRazonable;
            }
            if (puntoDePartida > ahora) {
                puntoDePartida = ahora;
            }

            marcaDeTiempoUltimaMedicion = puntoDePartida;
            quitarOverlaySiExiste();
            // No hacemos `return` aquí: seguimos abajo para sumar el
            // tiempo ya transcurrido desde `puntoDePartida` en este mismo
            // ciclo, en vez de esperar al siguiente.
        }

        long segundosTranscurridos = Math.max(0L, (ahora - marcaDeTiempoUltimaMedicion) / 1000L);
        marcaDeTiempoUltimaMedicion = ahora;

        if (segundosTranscurridos <= 0) {
            return;
        }

        JSONObject cacheTiempos = leerObjeto(prefs, CLAVE_CACHE_TIEMPOS);
        int tiempoAcumulado = cacheTiempos.optInt(paqueteActual, 0) + (int) segundosTranscurridos;

        try {
            cacheTiempos.put(paqueteActual, tiempoAcumulado);
        } catch (Exception e) {
            Log.e(TAG, "No se pudo actualizar cache de tiempos", e);
        }

        int limite = obtenerLimiteParaPaquete(prefs, paqueteActual);

        prefs.edit().putString(CLAVE_CACHE_TIEMPOS, cacheTiempos.toString()).apply();

        if (tiempoAcumulado >= limite) {
            Log.d(TAG, paqueteActual + " alcanzó su límite (" + tiempoAcumulado + "s / " + limite + "s)");
            bloqueadas.add(paqueteActual);
            guardarConjunto(prefs, CLAVE_APPS_BLOQUEADAS, bloqueadas);
            expulsarYBloquear(paqueteActual);
        }
    }

    private int obtenerLimiteParaPaquete(SharedPreferences prefs, String paquete) {
        JSONObject limitesPersonalizados = leerObjeto(prefs, CLAVE_LIMITES_PERSONALIZADOS);
        if (limitesPersonalizados.has(paquete)) {
            return limitesPersonalizados.optInt(paquete, LIMITE_APP_DEFECTO_SEGUNDOS);
        }
        int limiteDefecto = prefs.getInt(CLAVE_LIMITE_APP_DEFECTO, LIMITE_APP_DEFECTO_SEGUNDOS);
        return limiteDefecto > 0 ? limiteDefecto : LIMITE_APP_DEFECTO_SEGUNDOS;
    }

    // -----------------------------------------------------------------
    // Detección de app en primer plano (misma prioridad que el lado
    // Python: UsageEvents primero, RunningTasks como respaldo)
    // -----------------------------------------------------------------

    /** Resultado de detección: el paquete y el instante real (según el
     * propio sistema, no nuestro reloj de sondeo) en que pasó a primer
     * plano. Ese timestamp es la clave para que el cronómetro arranque
     * desde el momento real de apertura, no desde que lo "notamos". */
    private static final class DeteccionForeground {
        final String paquete;
        final long timestampCambio;

        DeteccionForeground(String paquete, long timestampCambio) {
            this.paquete = paquete;
            this.timestampCambio = timestampCambio;
        }
    }

    private DeteccionForeground detectarPaqueteEnPrimerPlano(String paqueteHome, String paqueteZenchi) {
        // Declarada aquí (no dentro del try) porque el bloque de respaldo
        // de más abajo (RunningTasks) también la necesita.
        long ahora = System.currentTimeMillis();

        try {
            UsageStatsManager usageStatsManager =
                    (UsageStatsManager) getSystemService(Context.USAGE_STATS_SERVICE);
            long inicio = ahora - (10 * 60 * 1000L);

            UsageEvents eventos = usageStatsManager.queryEvents(inicio, ahora);
            if (eventos != null) {
                UsageEvents.Event evento = new UsageEvents.Event();
                String paqueteActivo = null;
                int ultimoTipo = -1;
                long timestampUltimoEvento = ahora;

                while (eventos.hasNextEvent()) {
                    eventos.getNextEvent(evento);
                    int tipo = evento.getEventType();
                    if (tipo == UsageEvents.Event.MOVE_TO_FOREGROUND
                            || tipo == UsageEvents.Event.MOVE_TO_BACKGROUND) {
                        paqueteActivo = evento.getPackageName();
                        ultimoTipo = tipo;
                        // Clave para el fix: guardamos el instante REAL en
                        // que el sistema registró este cambio, no el
                        // instante en que nosotros lo detectamos al
                        // sondear (que siempre llega tarde por el
                        // intervalo de polling).
                        timestampUltimoEvento = evento.getTimeStamp();
                    }
                }

                if (paqueteActivo != null) {
                    if (ultimoTipo == UsageEvents.Event.MOVE_TO_BACKGROUND) {
                        return null;
                    }
                    return new DeteccionForeground(paqueteActivo, timestampUltimoEvento);
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "Error consultando UsageEvents", e);
        }

        // Respaldo: RunningTasks (requiere que el Service tenga permisos
        // suficientes; en la práctica puede devolver el propio proceso).
        // Aquí no tenemos un timestamp real del sistema, así que usamos
        // "ahora" — el clamp de seguridad en revisarForeground() evita que
        // esto cuente de más.
        try {
            ActivityManager am = (ActivityManager) getSystemService(Context.ACTIVITY_SERVICE);
            java.util.List<ActivityManager.RunningTaskInfo> tareas = am.getRunningTasks(1);
            if (tareas != null && !tareas.isEmpty()) {
                String paquete = tareas.get(0).topActivity.getPackageName();
                return new DeteccionForeground(paquete, ahora);
            }
        } catch (Exception e) {
            // getRunningTasks está deprecado/restringido en versiones nuevas;
            // si falla, simplemente no hay respaldo disponible este ciclo.
        }

        return null;
    }

    private String obtenerPaqueteHome() {
        try {
            Intent intentHome = new Intent(Intent.ACTION_MAIN);
            intentHome.addCategory(Intent.CATEGORY_HOME);
            ResolveInfo resolve = getPackageManager().resolveActivity(
                    intentHome, PackageManager.MATCH_DEFAULT_ONLY);
            if (resolve != null && resolve.activityInfo != null) {
                return resolve.activityInfo.packageName;
            }
        } catch (Exception e) {
            Log.e(TAG, "No se pudo resolver el paquete home", e);
        }
        return getPackageName();
    }

    // -----------------------------------------------------------------
    // Expulsión + overlay de bloqueo
    // -----------------------------------------------------------------

    private void expulsarYBloquear(String paqueteBloqueado) {
        // 1) Manda al usuario al Home inmediatamente.
        try {
            Intent irAHome = new Intent(Intent.ACTION_MAIN);
            irAHome.addCategory(Intent.CATEGORY_HOME);
            irAHome.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(irAHome);
        } catch (Exception e) {
            Log.e(TAG, "No se pudo regresar al Home", e);
        }

        // 2) Muestra un overlay breve confirmando el bloqueo (requiere
        // permiso SYSTEM_ALERT_WINDOW, ya declarado en el manifest).
        mostrarOverlayBloqueo(paqueteBloqueado);

        ultimoPaqueteVisto = null;
    }

    private void mostrarOverlayBloqueo(String paqueteBloqueado) {
        if (!tienePermisoOverlay()) {
            Log.w(TAG, "Sin permiso de overlay; se omite la pantalla de bloqueo visual");
            return;
        }

        quitarOverlaySiExiste();

        handler.post(new Runnable() {
            @Override
            public void run() {
                try {
                    if (windowManager == null) {
                        windowManager = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
                    }

                    LinearLayout contenedor = new LinearLayout(ZenchiMonitorService.this);
                    contenedor.setOrientation(LinearLayout.VERTICAL);
                    contenedor.setGravity(Gravity.CENTER);
                    contenedor.setBackgroundColor(Color.parseColor("#CC10161C"));
                    contenedor.setPadding(60, 60, 60, 60);

                    TextView titulo = new TextView(ZenchiMonitorService.this);
                    titulo.setText("Zenchi bloqueó esta app");
                    titulo.setTextColor(Color.WHITE);
                    titulo.setTextSize(20f);
                    titulo.setGravity(Gravity.CENTER);
                    contenedor.addView(titulo);

                    TextView subtitulo = new TextView(ZenchiMonitorService.this);
                    subtitulo.setText(nombreLegible(paqueteBloqueado) + " alcanzó su límite de hoy.");
                    subtitulo.setTextColor(Color.parseColor("#CCCCCC"));
                    subtitulo.setTextSize(14f);
                    subtitulo.setGravity(Gravity.CENTER);
                    subtitulo.setPadding(0, 20, 0, 40);
                    contenedor.addView(subtitulo);

                    Button botonCerrar = new Button(ZenchiMonitorService.this);
                    botonCerrar.setText("Volver a Zenchi");
                    botonCerrar.setOnClickListener(new View.OnClickListener() {
                        @Override
                        public void onClick(View v) {
                            quitarOverlaySiExiste();
                        }
                    });
                    contenedor.addView(botonCerrar);

                    int tipoOverlay = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                            ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                            : WindowManager.LayoutParams.TYPE_PHONE;

                    WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                            WindowManager.LayoutParams.MATCH_PARENT,
                            WindowManager.LayoutParams.MATCH_PARENT,
                            tipoOverlay,
                            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                                    | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                            PixelFormat.TRANSLUCENT);
                    // Quitamos FLAG_NOT_FOCUSABLE para que el botón sea tocable:
                    params.flags = WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN;

                    windowManager.addView(contenedor, params);
                    overlayActivo = contenedor;

                    // Auto-remover a los 4 segundos si el usuario no toca el botón.
                    handler.postDelayed(new Runnable() {
                        @Override
                        public void run() {
                            quitarOverlaySiExiste();
                        }
                    }, 4000L);

                } catch (Exception e) {
                    Log.e(TAG, "No se pudo mostrar overlay de bloqueo", e);
                }
            }
        });
    }

    private void quitarOverlaySiExiste() {
        if (overlayActivo != null && windowManager != null) {
            try {
                windowManager.removeView(overlayActivo);
            } catch (Exception e) {
                // Puede que ya se haya removido; ignorar.
            } finally {
                overlayActivo = null;
            }
        }
    }

    private boolean tienePermisoOverlay() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            return Settings.canDrawOverlays(this);
        }
        return true;
    }

    private String nombreLegible(String paquete) {
        try {
            PackageManager pm = getPackageManager();
            return String.valueOf(pm.getApplicationLabel(pm.getApplicationInfo(paquete, 0)));
        } catch (Exception e) {
            return paquete;
        }
    }

    // -----------------------------------------------------------------
    // Helpers de SharedPreferences <-> JSON
    // -----------------------------------------------------------------

    private JSONObject leerObjeto(SharedPreferences prefs, String clave) {
        try {
            return new JSONObject(prefs.getString(clave, "{}"));
        } catch (Exception e) {
            return new JSONObject();
        }
    }

    private Set<String> leerConjunto(SharedPreferences prefs, String clave) {
        Set<String> resultado = new HashSet<>();
        try {
            JSONArray arreglo = new JSONArray(prefs.getString(clave, "[]"));
            for (int i = 0; i < arreglo.length(); i++) {
                resultado.add(arreglo.getString(i));
            }
        } catch (Exception e) {
            Log.e(TAG, "No se pudo leer conjunto para " + clave, e);
        }
        return resultado;
    }

    private void guardarConjunto(SharedPreferences prefs, String clave, Set<String> valores) {
        JSONArray arreglo = new JSONArray();
        Iterator<String> it = valores.iterator();
        while (it.hasNext()) {
            arreglo.put(it.next());
        }
        prefs.edit().putString(clave, arreglo.toString()).apply();
    }
}