# Implementación de UsageStats - Seguimiento de tiempo por app

## Resumen
Se ha implementado el sistema de monitoreo de uso de aplicaciones mediante la API `UsageStatsManager` de Android. Este es el siguiente paso lógico después de tener el listado de apps y la funcionalidad de launcher.

## Archivos Creados/Modificados

### 1. `/workspace/bridge/usage_stats.py` (NUEVO)
Módulo completo para monitorear el uso de aplicaciones con las siguientes funciones:

#### Funciones Principales:
- `obtener_permiso_usage_stats()`: Verifica si la app tiene permiso para acceder a estadísticas de uso
- `solicitar_permiso_usage_stats()`: Abre la pantalla de ajustes para que el usuario conceda el permiso
- `obtener_estadisticas_uso(rango_horas)`: Obtiene historial de uso de todas las apps
- `detectar_app_en_primer_plano()`: Detecta qué app está actualmente en uso
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

#### Nuevos Métodos:
- `_verificar_permiso_usage_stats()`: Botón para verificar/solicitar permisos
- `_actualizar_monitoreo_apps()`: Detecta app activa y acumula tiempo cada segundo
- `_actualizar()`: Actualizado para integrar monitoreo con el motor de decisiones

#### Nueva UI:
- Etiqueta que muestra app activa y tiempo acumulado
- Botón "Verificar permiso UsageStats"

### 3. `/workspace/android_src/AndroidManifest.xml` (MODIFICADO)
Se agregó el permiso necesario:
```xml
<uses-permission android:name="android.permission.PACKAGE_USAGE_STATS" 
    tools:ignore="ProtectedPermissions" />
```

## Cómo Funciona

### Flujo de Uso:
1. **Inicio de Sesión**: Usuario presiona "Iniciar sesión de enfoque"
2. **Verificación de Permisos**: Sistema verifica si tiene acceso a UsageStats
3. **Monitoreo Continuo**: Cada segundo:
   - Detecta qué app está en primer plano
   - Acumula tiempo para esa app específica
   - Actualiza la interfaz con el tiempo transcurrido
   - Verifica si se excedió algún límite por app
4. **Restricción Automática**: Si una app supera el límite (ej: 5 min), se marca como restringida
5. **Integración con Motor**: El motor considera apps restringidas para bloquear acceso

### Ejemplo de Política por App:
```python
# En _actualizar_monitoreo_apps():
if tiempo_acumulado > 300:  # 5 minutos
    self.paquete_restringido_actual = self.app_en_primer_plano
```

Esto activa el estado "enojado" de la mascota y requiere reflexión.

## Pruebas Realizadas

### Test de Módulos:
```bash
# ✓ Todos los módulos importan correctamente
python -c "from bridge.usage_stats import *; ..."

# ✓ Funciones de estadísticas funcionan en modo desktop
 Apps encontradas: 2
  - Instagram: 01:00:00
  - YouTube: 00:45:00

# ✓ Acumulación de tiempo funciona correctamente
Cache final: {'com.instagram.android': 180, 'com.youtube.android': 45}
```

## Próximos Pasos Sugeridos

1. **Políticas Configurables por App**: Permitir al usuario establecer límites específicos por aplicación
2. **Historial Persistente**: Guardar estadísticas entre sesiones para mostrar tendencias
3. **Notificaciones Push**: Alertar cuando se acerca al límite de una app
4. **Refinamiento de Detección**: Mejorar la precisión de detección de app en primer plano
5. **Excepciones**: Lista blanca de apps que no cuentan (teléfono, mensajes urgentes)

## Notas Importantes

### Permisos Requeridos:
El usuario debe otorgar manualmente el permiso `PACKAGE_USAGE_STATS` desde:
**Ajustes > Acceso especial > Uso de datos > Zenchi**

### Compatibilidad Android:
- Android 5.0+: Funciona con UsageStatsManager
- Android 10+: Usa RoleManager para launcher
- El código incluye fallbacks para versiones antiguas

### Modo Desktop:
El sistema incluye mocks para desarrollo en escritorio, mostrando datos simulados cuando no hay Android disponible.
