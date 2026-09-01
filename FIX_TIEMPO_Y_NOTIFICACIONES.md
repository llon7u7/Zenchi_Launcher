# FIX: Tiempo marca 0s y notificaciones no aparecen

## Problemas Reportados
1. **El tiempo sigue marcando 0s** aunque uses la app por más de un minuto
2. **Las notificaciones no aparecen** para saber si el Service está corriendo

## Causas Raíz Identificadas

### 1. Tiempo = 0s
**Problema:** `queryUsageStats()` tiene latencia de consolidación. Android no actualiza `getTotalTimeInForeground()` inmediatamente; puede tardar varios minutos en procesar las estadísticas. Con una ventana de 60s, los datos aún no estaban disponibles.

**Solución implementada:**
- Cambié el método principal de `queryUsageStats()` a `queryEvents()` que devuelve eventos crudos `MOVE_TO_FOREGROUND` / `MOVE_TO_BACKGROUND` en tiempo real
- Aumenté la ventana por defecto de 60s a **900s (15 min)** para asegurar que haya suficientes datos
- Mantengo `queryUsageStats()` como fallback si `queryEvents()` falla

### 2. Notificaciones no aparecen
**Problema:** En Android 13+ (API 33+), el permiso `POST_NOTIFICATIONS` es de runtime. Si el usuario no lo concede, las notificaciones se silencian sin error visible.

**Solución implementada:**
- Agregué verificación explícita de `notification_manager.areNotificationsEnabled()` antes de mostrar la notificación
- Si las notificaciones están desactivadas, muestro un **Toast** como fallback (no requiere permiso)
- El Toast también sirve como fallback en caso de error al crear la notificación

## Cambios Realizados

### `bridge/usage_stats.py`

```python
# ANTES: rango_segundos=60, solo queryUsageStats()
def obtener_tiempo_uso_app(paquete: str, rango_segundos: int = 60) -> int:
    # ... usa queryUsageStats() con ventana de 60s ...

# AHORA: rango_segundos=900, queryEvents() primario + queryUsageStats() fallback
def obtener_tiempo_uso_app(paquete: str, rango_segundos: int = 900) -> int:
    """
    # FIX (tiempo = 0s): Se aumentó el rango de 60s a 900s (15 min)
    # porque UsageStats consolida datos con latencia.
    # Ahora usamos queryEvents() que es más preciso y en tiempo real.
    """
    # 1. Intenta con queryEvents() - eventos crudos en tiempo real
    eventos = usage_stats_manager.queryEvents(inicio_ms, ahora_ms)
    # Busca eventos MOVE_TO_FOREGROUND y MOVE_TO_BACKGROUND
    # Calcula tiempo directamente desde los timestamps
    
    # 2. Fallback a queryUsageStats() si queryEvents falla
    stats = usage_stats_manager.queryUsageStats(...)
```

### `main.py`

#### 1. on_resume() actualizado
```python
# ANTES: ventana de 300s (5 min)
tiempo_real = obtener_tiempo_uso_app(
    paquete=self.ultima_app_abierta,
    rango_segundos=300
)

# AHORA: ventana de 900s (15 min) para asegurar datos
tiempo_real = obtener_tiempo_uso_app(
    paquete=self.ultima_app_abierta,
    rango_segundos=900  # Ventana de 15 minutos para asegurar datos
)
```

#### 2. Verificación de permisos en build()
```python
# --- FIX: Verificar permiso UsageStats ANTES de iniciar el Service ---
# El Service nativo depende del permiso PACKAGE_USAGE_STATS para funcionar.
# Si no está concedido, el Service arranca pero no puede leer UsageStats.
verificar_y_solicitar_permiso_usage_stats()

iniciar_servicio_monitor()
```

#### 3. Notificaciones con fallback a Toast
```python
def _actualizar_notificacion_uso(self) -> None:
    # Verifica si las notificaciones están habilitadas
    if not notification_manager.areNotificationsEnabled():
        print("[WARNING] Notificaciones DESACTIVADAS para Zenchi")
        # Fallback: mostrar Toast si las notificaciones no están disponibles
        self._mostrar_toast(f"Uso: {self._formatear_tiempo_segundos(...)} hoy")
        return
    
    # ... crea y muestra notificación normal ...

def _mostrar_toast(self, texto: str) -> None:
    """Muestra un Toast Android (no requiere permiso de notificaciones)."""
    handler.post(lambda: Toast.makeText(actividad, texto, Toast.LENGTH_SHORT).show())
```

## Flujo Corregido

### Para el tiempo de uso:
1. Usuario abre app desde Zenchi → Service nativo la vigila en segundo plano
2. Usuario regresa a Zenchi → Se dispara `on_resume()`
3. `on_resume()` llama a `obtener_tiempo_uso_app()` con ventana de 15 min
4. `queryEvents()` busca eventos FOREGROUND/BACKGROUND de esa app
5. Calcula tiempo real: `timestamp_background - timestamp_foreground`
6. Actualiza cache y verifica límites

### Para las notificaciones:
1. Al iniciar, verifica permiso POST_NOTIFICATIONS
2. Si no está concedido → abre pantalla de ajustes
3. Al actualizar notificación:
   - Si notificaciones habilitadas → muestra notificación con progreso
   - Si NO habilitadas → muestra Toast como fallback

## Cómo Probar

### Prueba de tiempo:
1. Abre una app desde Zenchi (ej. Instagram)
2. Úsala por 1-2 minutos
3. Regresa a Zenchi (presiona Home o deja que el Service la cierre)
4. Revisa los logs: deberías ver `[DEBUG] QueryEvents -> com.instagram.android: XXs`
5. El tiempo debería ser cercano al tiempo real que la usaste

### Prueba de notificaciones:
1. Abre Zenchi
2. Si es Android 13+, ve a Ajustes > Apps > Zenchi > Notificaciones y DESACTÍVALAS
3. Abre una app desde Zenchi
4. Deberías ver un **Toast** emergente mostrando el tiempo de uso
5. Si activas las notificaciones, deberías ver la notificación persistente

## Permisos Requeridos (buildozer.spec)

```ini
android.permissions = 
    SYSTEM_ALERT_WINDOW,
    PACKAGE_USAGE_STATS,          # ← CRÍTICO para UsageStatsManager
    QUERY_ALL_PACKAGES,
    POST_NOTIFICATIONS,           # ← Necesario para notificaciones en Android 13+
    FOREGROUND_SERVICE,
    FOREGROUND_SERVICE_SPECIAL_USE
```

## Notas Importantes

1. **UsageStats tiene latencia**: Aunque usemos `queryEvents()`, Android puede tardar unos segundos en registrar los eventos. La ventana de 15 min asegura que siempre haya datos disponibles.

2. **Service nativo es clave**: El monitoreo en tiempo real mientras estás DENTRO de una app lo hace `ZenchiMonitorService.java` (nativo), no Python. Python solo consulta los resultados al regresar.

3. **Toasts son universales**: Los Tosts funcionan en TODAS las versiones de Android sin permisos especiales. Son el fallback perfecto cuando las notificaciones fallan.

4. **Verifica los logs**: Usa `adb logcat | grep -E "(DEBUG|WARNING|TOAST|QueryEvents)"` para ver exactamente qué está pasando.
