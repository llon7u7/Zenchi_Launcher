# 🔧 Fix: Detección de Apps en Segundo Plano

## Problema Detectado
El sistema anterior contaba tiempo de uso incluso cuando una app estaba en **segundo plano** (minimizada o cerrada pero no completamente detenida). Esto ocurría porque:

1. Se usaba `getLastTimeUsed()` que retorna el último momento de uso, aunque la app ya esté en background
2. No había verificación de eventos `MOVE_TO_BACKGROUND`
3. La ventana de tiempo era muy amplia (1 hora)

## Solución Implementada

### Nuevo Algoritmo con `UsageEvents`

Ahora el sistema usa **eventos en tiempo real** para detectar precisamente cuándo una app está en primer plano:

```python
# Método principal: Usar UsageEvents para eventos precisos
events = usage_stats_manager.queryEvents(inicio_ms, ahora_ms)

while events.hasNextEvent():
    event = events.getNextEvent()
    tipo_evento = event.getEventType()
    
    if tipo_evento == UsageStatsManager.EVENT_MOVE_TO_FOREGROUND:
        # App entró a primer plano
        guardar_evento_foreground()
        
    elif tipo_evento == UsageStatsManager.EVENT_MOVE_TO_BACKGROUND:
        # App salió a segundo plano → DEJAR DE CONTAR TIEMPO
        invalidar_evento_foreground()
```

### Características Clave

✅ **Detección precisa de foreground/background**: Solo cuenta tiempo si hay evento `MOVE_TO_FOREGROUND` reciente (< 10 segundos) y NO hay evento `MOVE_TO_BACKGROUND` posterior.

✅ **Ventana de tiempo corta**: Consulta solo los últimos **60 segundos** en lugar de 1 hora, reduciendo falsos positivos.

✅ **Filtro de frescura**: Incluso con el método fallback (`queryUsageStats`), solo considera apps con actividad en los últimos **5 segundos**.

✅ **Fallback robusto**: Mantiene compatibilidad con versiones antiguas de Android usando `ActivityManager` como último recurso.

✅ **Auto-detección de Zenchi**: Si no hay otra app en primer plano, asume que el usuario está en el launcher Zenchi.

## Cambios Técnicos

### Antes ❌
```python
# Ventana de 1 hora → muchos falsos positivos
inicio_ms = ahora_ms - (60 * 60 * 1000)

# Solo verificaba último timestamp, sin importar si estaba en background
if ultima_vez > ultimo_timestamp:
    paquete_activo = paquete
```

### Después ✅
```python
# Ventana de 60 segundos → solo actividad reciente
inicio_ms = ahora_ms - (60 * 1000)

# Verifica eventos MOVE_TO_FOREGROUND y MOVE_TO_BACKGROUND
if tipo_evento == EVENT_MOVE_TO_FOREGROUND:
    guardar_foreground()
elif tipo_evento == EVENT_MOVE_TO_BACKGROUND:
    invalidar_foreground()

# Solo retorna si es muy reciente (< 10 segundos)
if (ahora_ms - timestamp_ultimo_foreground) < 10000:
    return AppState(...)
```

## Testing Recomendado

1. **Abrir Instagram** → Debería detectar `com.instagram.android`
2. **Presionar Home** → Debería dejar de contar tiempo para Instagram
3. **Abrir WhatsApp** → Debería cambiar a `com.whatsapp`
4. **Cerrar WhatsApp** → Debería volver a Zenchi y detener contador

## Archivos Modificados

- `bridge/usage_stats.py`: Función `detectar_app_en_primer_plano()` completamente reescrita
- No requiere cambios en `main.py` ni otros módulos (la interfaz se mantiene igual)

## Notas Importantes

⚠️ **Requiere permiso PACKAGE_USAGE_STATS**: El usuario debe otorgarlo manualmente en Ajustes > Acceso especial > Uso de datos.

⚠️ **Android 5.0+**: Los eventos `UsageEvents` están disponibles desde API 21 (Android 5.0). Para versiones anteriores, usa el fallback con `ActivityManager`.

⚠️ **Precisión**: La precisión depende de la frecuencia de polling. Con un intervalo de 1 segundo, el margen de error es mínimo (< 1 segundo por transición).
