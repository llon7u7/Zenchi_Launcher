# Implementación de UsageStats - Seguimiento de tiempo por app

## Resumen
Se ha implementado el sistema de monitoreo de uso de aplicaciones mediante la API `UsageStatsManager` de Android. Este es el siguiente paso lógico después de tener el listado de apps y la funcionalidad de launcher.

**ACTUALIZACIÓN IMPORTANTE**: Se refactorizó el código para usar directamente UsageStatsManager en lugar del contador manual de Kivy, que fallaba porque el hilo principal se pausa cuando Zenchi pasa a segundo plano. Ahora el tiempo real se obtiene consultando la API nativa de Android cada vez que el usuario regresa al launcher (evento `on_resume`).

## Archivos Creados/Modificados

### 1. `/workspace/bridge/usage_stats.py` (MODIFICADO)
Módulo completo para monitorear el uso de aplicaciones con las siguientes funciones:

#### Funciones Principales:
- `obtener_permiso_usage_stats()`: Verifica si la app tiene permiso para acceder a estadísticas de uso
- `solicitar_permiso_usage_stats()`: Abre la pantalla de ajustes para que el usuario conceda el permiso
- **`verificar_y_solicitar_permiso_usage_stats()` (NUEVA)**: Verifica el permiso y lo solicita automáticamente si no está concedido
- `obtener_estadisticas_uso(rango_horas)`: Obtiene historial de uso de todas las apps
- `detectar_app_en_primer_plano()`: Detecta qué app está actualmente en uso
- **`obtener_tiempo_uso_app(paquete, rango_segundos)` (NUEVA)**: Obtiene el tiempo REAL en primer plano desde UsageStatsManager
- **`obtener_tiempos_uso_apps(paquetes, rango_segundos)` (NUEVA)**: Obtiene tiempos reales para múltiples apps de una vez
- `acumular_tiempo_sesion(paquete, segundos, cache)`: Acumula tiempo durante la sesión actual
- `formatear_tiempo(ms)`: Utilidad para mostrar tiempos en formato HH:MM:SS

#### Clases de Datos:
- `EstadisticaUso`: Contiene paquete, nombre, tiempo total, última vez usado
- `AppState`: Estado actual de la app en primer plano

### 2. `/workspace/main.py` (MODIFICADO)
Se integró el sistema de monitoreo con la interfaz:

#### Nuevas Propiedades:
- `app_en_primer_plano`: Paquete de la app actualmente en uso
- `tiempo_app_actual`: Tiempo acumulado en la app actual
- `tiene_permiso_usage_stats`: Estado del permiso
- `cache_tiempos_por_app`: Diccionario con tiempos acumulados por paquete
- `paquete_restringido_actual`: App que excedió límite y debe restringirse

#### Métodos Modificados:
- `_verificar_permiso_usage_stats()`: Ahora usa `verificar_y_solicitar_permiso_usage_stats()` para solicitud automática
- **`on_resume()` (REFACTORIZADO)**: Ahora consulta UsageStatsManager para obtener el tiempo real de la app recién cerrada, eliminando la dependencia del contador manual de Kivy

#### Nueva UI:
- Etiqueta que muestra app activa y tiempo acumulado
- Botón "Verificar permiso UsageStats"

### 3. `/workspace/buildozer.spec` (VERIFICADO)
Los permisos ya están configurados correctamente:
```ini
android.permissions = SYSTEM_ALERT_WINDOW,PACKAGE_USAGE_STATS,QUERY_ALL_PACKAGES,POST_NOTIFICATIONS,FOREGROUND_SERVICE,FOREGROUND_SERVICE_SPECIAL_USE
```

### 4. `/workspace/android_src/AndroidManifest.xml` (EXISTENTE)
El permiso ya está agregado:
```xml
<uses-permission android:name="android.permission.PACKAGE_USAGE_STATS" 
    tools:ignore="ProtectedPermissions" />
```

## Cómo Funciona

### Problema Original Solucionado:
El contador manual de Kivy marcaba 0 segundos porque cuando el usuario abría una app desde el launcher, la Activity de Kivy pasaba a segundo plano y su `Clock` se pausaba. Esto rompía completamente la lógica de conteo.

### Solución Implementada:
En lugar de depender del loop de Kivy (que se pausa), ahora:

1. **Al abrir una app**: Se guarda el paquete en `ultima_app_abierta`
2. **Mientras la app está abierta**: El Service nativo (`ZenchiMonitorService`) vigila en segundo plano
3. **Al regresar al launcher (on_resume)**: 
   - Se verifica/solicita automáticamente el permiso PACKAGE_USAGE_STATS
   - Se consulta `UsageStatsManager.queryUsageStats()` para obtener el tiempo REAL que la app estuvo en primer plano
   - Se actualiza el cache con el tiempo obtenido
   - Se verifica si se superó el límite y se bloquea si es necesario

### Flujo de Uso Refactorizado:
1. **Inicio**: Usuario abre una app desde Zenchi
2. **Monitoreo en Segundo Plano**: `ZenchiMonitorService` (Java nativo) vigila el uso mientras Zenchi está pausado
3. **Regreso al Launcher**: Cuando el usuario cierra la app o es bloqueado:
   - Se dispara `on_resume()` en Kivy
   - Se llama a `verificar_y_solicitar_permiso_usage_stats()` automáticamente
   - Se consulta `obtener_tiempo_uso_app()` para obtener el tiempo real desde UsageStatsManager
   - Se actualiza el estado con los datos reales obtenidos
4. **Bloqueo si corresponde**: Si el tiempo real supera el límite, se marca la app como bloqueada

### Ejemplo de Integración en on_resume():
```python
def on_resume(self):
    # Verificar y solicitar permiso automáticamente
    verificar_y_solicitar_permiso_usage_stats()
    
    # Obtener tiempo REAL desde UsageStatsManager
    if self.ultima_app_abierta:
        tiempo_real = obtener_tiempo_uso_app(
            paquete=self.ultima_app_abierta,
            rango_segundos=300
        )
        
        if tiempo_real > 0:
            # Actualizar cache con tiempo real (no estimado)
            self.cache_tiempos_por_app[self.ultima_app_abierta] += tiempo_real
            self._guardar_estado_diario()
            
            # Verificar límite
            if self.cache_tiempos_por_app[self.ultima_app_abierta] >= limite_app:
                self.apps_bloqueadas_hoy.add(self.ultima_app_abierta)
                self._cerrar_app_actual()
```

## Pruebas Realizadas

### Test de Módulos:
```bash
# Todos los módulos importan correctamente
python -c "from bridge.usage_stats import *; ..."

# Sintaxis validada en main.py y usage_stats.py
```

## Permisos Requeridos

### En buildozer.spec (YA CONFIGURADO):
```ini
android.permissions = SYSTEM_ALERT_WINDOW,PACKAGE_USAGE_STATS,QUERY_ALL_PACKAGES,POST_NOTIFICATIONS,FOREGROUND_SERVICE,FOREGROUND_SERVICE_SPECIAL_USE
```

### Permiso de Runtime:
El usuario debe otorgar manualmente el permiso `PACKAGE_USAGE_STATS` desde:
**Ajustes > Acceso especial > Uso de datos > Zenchi**

**MEJORA**: Ahora este permiso se solicita automáticamente al regresar al launcher si no está concedido, usando `verificar_y_solicitar_permiso_usage_stats()`.

## Notas Importantes

### Compatibilidad Android:
- Android 5.0+ (API 21+): Funciona con UsageStatsManager
- Android 10+ (API 29+): Usa RoleManager para launcher
- El código incluye fallbacks para versiones antiguas

### Modo Desktop:
El sistema incluye mocks para desarrollo en escritorio, mostrando datos simulados cuando no hay Android disponible.

### Ventajas de esta Implementación:
1. **Precisión**: Usa datos reales del sistema Android, no estimaciones
2. **Confiabilidad**: No depende del ciclo de vida de Kivy
3. **Automatización**: Solicita permisos automáticamente sin intervención del usuario
4. **Integración**: Funciona junto con `ZenchiMonitorService` para vigilancia completa
