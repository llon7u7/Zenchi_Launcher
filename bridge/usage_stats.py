"""
Módulo para monitorear el uso de aplicaciones en Android mediante UsageStats.

Este módulo proporciona funciones para:
1. Obtener estadísticas de uso de cada app instalada
2. Detectar qué app está en primer plano actualmente
3. Acumular tiempo de uso por paquete durante la sesión de enfoque

Para que funcione correctamente, el usuario debe otorgar el permiso
PACKAGE_USAGE_STATS desde Ajustes > Acceso especial > Uso de datos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

try:
    from jnius import autoclass, cast
    HAY_ANDROID = True
except ModuleNotFoundError:
    HAY_ANDROID = False


@dataclass(frozen=True)
class EstadisticaUso:
    """Estadísticas de uso de una aplicación específica."""
    paquete: str
    nombre_app: str
    tiempo_total_ms: int  # tiempo total de uso en milisegundos
    ultima_vez_usado: int  # timestamp de la última vez que se usó
    tiempo_en_primer_plano_ms: int = 0  # tiempo estimado en primer plano
    
    @property
    def tiempo_total_segundos(self) -> int:
        """Tiempo total de uso en segundos."""
        return self.tiempo_total_ms // 1000
    
    @property
    def tiempo_en_primer_plano_segundos(self) -> int:
        """Tiempo en primer plano en segundos."""
        return self.tiempo_en_primer_plano_ms // 1000


@dataclass(frozen=True)
class AppState:
    """Estado actual del sistema de apps."""
    paquete_en_primer_plano: Optional[str]
    tiempo_desde_ultimo_cambio_ms: int
    timestamp_ultimo_cambio: int


def _obtener_actividad():
    """Obtiene la actividad actual de Python en Android para Buildozer."""
    if not HAY_ANDROID:
        return None
    
    try:
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        actividad = PythonActivity.mActivity
        
        if actividad is not None:
            return actividad
            
        if hasattr(PythonActivity, 'mInstance') and PythonActivity.mInstance is not None:
            return PythonActivity.mInstance
            
    except Exception as e:
        print(f"[ERROR] No se pudo obtener actividad: {e}")
        
    try:
        from android import python_act
        if python_act is not None:
            return python_act
    except Exception as e:
        print(f"[ERROR] No se pudo obtener actividad (método 2): {e}")
    
    return None


def obtener_permiso_usage_stats() -> bool:
    """Verifica si la app tiene permiso para acceder a UsageStats.
    
    Returns:
        True si ya tiene permiso, False si necesita solicitarlo al usuario.
    """
    actividad = _obtener_actividad()
    
    if actividad is None:
        print("[DEBUG] Modo desktop: simulando permiso de UsageStats concedido")
        return True
    
    try:
        Context = autoclass("android.content.Context")
        AppOpsManager = autoclass("android.app.AppOpsManager")
        
        app_ops = cast(
            "android.app.AppOpsManager",
            actividad.getSystemService(Context.APP_OPS_SERVICE)
        )
        
        # Verificar modo de operación para PACKAGE_USAGE_STATS
        mode = app_ops.checkOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS,
            actividad.getApplicationInfo().uid,
            actividad.getPackageName()
        )
        
        tiene_permiso = (mode == AppOpsManager.MODE_ALLOWED)
        
        if not tiene_permiso:
            print("[WARNING] No hay permiso PACKAGE_USAGE_STATS")
            print("[INFO] El usuario debe habilitarlo en: Ajustes > Acceso especial > Uso de datos")
        else:
            print("[DEBUG] Permiso PACKAGE_USAGE_STATS concedido")
            
        return tiene_permiso
        
    except Exception as e:
        print(f"[ERROR] Error al verificar permiso UsageStats: {e}")
        return False


def solicitar_permiso_usage_stats() -> None:
    """Abre la pantalla de ajustes para que el usuario conceda el permiso UsageStats.
    
    Debe llamarse desde la interfaz cuando se detecta que no hay permiso.
    Ejemplo:
        boton.bind(on_release=lambda *_: solicitar_permiso_usage_stats())
    """
    actividad = _obtener_actividad()
    
    if actividad is None:
        print("[demo escritorio] Aquí se abriría la pantalla de permisos UsageStats")
        return
    
    try:
        Settings = autoclass("android.provider.Settings")
        Intent = autoclass("android.content.Intent")
        
        intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
        actividad.startActivity(intent)
        
        print("[INFO] Abriendo pantalla de permisos UsageStats")
        
    except Exception as e:
        print(f"[ERROR] Error al abrir ajustes UsageStats: {e}")


def obtener_estadisticas_uso(rango_horas: int = 24) -> list[EstadisticaUso]:
    """Obtiene estadísticas de uso de todas las apps en las últimas N horas.
    
    Args:
        rango_horas: Ventana de tiempo hacia atrás para consultar estadísticas.
        
    Returns:
        Lista de EstadisticaUso ordenada por tiempo de uso (mayor a menor).
    """
    actividad = _obtener_actividad()
    
    if actividad is None:
        print("[DEBUG] Modo desktop: devolviendo estadísticas mock")
        return [
            EstadisticaUso(
                paquete="com.instagram.android",
                nombre_app="Instagram",
                tiempo_total_ms=3600000,  # 1 hora
                ultima_vez_usado=int(datetime.now().timestamp() * 1000),
                tiempo_en_primer_plano_ms=1800000
            ),
            EstadisticaUso(
                paquete="com.google.android.youtube",
                nombre_app="YouTube",
                tiempo_total_ms=2700000,  # 45 min
                ultima_vez_usado=int((datetime.now() - timedelta(minutes=30)).timestamp() * 1000),
                tiempo_en_primer_plano_ms=900000
            ),
        ]
    
    if not obtener_permiso_usage_stats():
        print("[WARNING] Sin permiso UsageStats, retornando lista vacía")
        return []
    
    try:
        Context = autoclass("android.content.Context")
        UsageStatsManager = autoclass("android.app.usage.UsageStatsManager")
        
        usage_stats_manager = cast(
            "android.app.usage.UsageStatsManager",
            actividad.getSystemService(Context.USAGE_STATS_SERVICE)
        )
        
        # Calcular ventana de tiempo
        ahora_ms = int(datetime.now().timestamp() * 1000)
        inicio_ms = ahora_ms - (rango_horas * 60 * 60 * 1000)
        
        # Obtener estadísticas de uso
        stats = usage_stats_manager.queryUsageStats(
            UsageStatsManager.INTERVAL_DAILY,
            inicio_ms,
            ahora_ms
        )
        
        if stats is None or stats.size() == 0:
            print("[DEBUG] No hay estadísticas de uso disponibles")
            return []
        
        PackageManager = autoclass("android.content.pm.PackageManager")
        pm = actividad.getPackageManager()
        
        resultados: list[EstadisticaUso] = []
        
        for i in range(stats.size()):
            usage_stat = stats.get(i)
            paquete = str(usage_stat.getPackageName())
            tiempo_total = int(usage_stat.getTotalTimeInForeground())
            ultima_vez = int(usage_stat.getLastTimeUsed())
            
            # Obtener nombre legible de la app
            try:
                app_info = pm.getApplicationInfo(paquete, 0)
                nombre_app = str(pm.getApplicationLabel(app_info))
            except Exception:
                nombre_app = paquete
            
            # Solo incluir apps con tiempo de uso significativo (> 0)
            if tiempo_total > 0:
                resultados.append(
                    EstadisticaUso(
                        paquete=paquete,
                        nombre_app=nombre_app,
                        tiempo_total_ms=tiempo_total,
                        ultima_vez_usado=ultima_vez,
                        tiempo_en_primer_plano_ms=tiempo_total  # Simplificación inicial
                    )
                )
        
        # Ordenar por tiempo de uso (mayor primero)
        resultados.sort(key=lambda x: x.tiempo_total_ms, reverse=True)
        
        print(f"[INFO] Se obtuvieron {len(resultados)} apps con estadísticas de uso")
        return resultados
        
    except Exception as e:
        print(f"[ERROR] Error al obtener estadísticas de uso: {e}")
        import traceback
        traceback.print_exc()
        return []


def detectar_app_en_primer_plano() -> AppState:
    """Detecta qué aplicación está realmente en primer plano.

    Primero intenta ActivityManager y procesos activos. Si el sistema no devuelve
    un resultado fiable, usa UsageStats para buscar la app más reciente en primer
    plano. Esto evita que la UI quede en "--" cuando el launcher no responde
    bien a getRunningTasks() en versiones modernas de Android.
    """
    actividad = _obtener_actividad()

    if actividad is None:
        print("[DEBUG] Modo desktop: simulando app en primer plano")
        return AppState(
            paquete_en_primer_plano="com.instagram.android",
            tiempo_desde_ultimo_cambio_ms=300000,
            timestamp_ultimo_cambio=int(datetime.now().timestamp() * 1000) - 300000,
        )

    ahora_ms = int(datetime.now().timestamp() * 1000)

    try:
        Context = autoclass("android.content.Context")
        ActivityManager = autoclass("android.app.ActivityManager")
        UsageStatsManager = autoclass("android.app.usage.UsageStatsManager")
        UsageEvents = autoclass("android.app.usage.UsageEvents")
        PackageManager = autoclass("android.content.pm.PackageManager")
        Intent = autoclass("android.content.Intent")

        activity_manager = cast(
            "android.app.ActivityManager",
            actividad.getSystemService(Context.ACTIVITY_SERVICE),
        )
        pm = actividad.getPackageManager()

        home_intent = Intent(Intent.ACTION_MAIN)
        home_intent.addCategory(Intent.CATEGORY_HOME)
        home_resolve = pm.resolveActivity(home_intent, PackageManager.MATCH_DEFAULT_ONLY)
        paquete_home = None if home_resolve is None else str(home_resolve.activityInfo.packageName)

        try:
            procesos = activity_manager.getRunningAppProcesses()
            if procesos is not None:
                for proceso in procesos:
                    pkg_list = getattr(proceso, "pkgList", None)
                    if not pkg_list:
                        continue
                    for paquete in pkg_list:
                        nombre_pkg = str(paquete)
                        if not nombre_pkg:
                            continue
                        if paquete_home and nombre_pkg == paquete_home:
                            continue
                        importancia = getattr(proceso, "importance", None)
                        if importancia is not None and importancia <= 200:
                            print(f"[DEBUG] App en primer plano (RunningAppProcesses): {nombre_pkg}")
                            return AppState(
                                paquete_en_primer_plano=nombre_pkg,
                                tiempo_desde_ultimo_cambio_ms=0,
                                timestamp_ultimo_cambio=ahora_ms,
                            )
        except Exception:
            pass

        try:
            tareas = activity_manager.getRunningTasks(1)
            if tareas is not None and tareas.size() > 0:
                tarea_superior = tareas.get(0)
                componente = getattr(tarea_superior, "topActivity", None)
                if componente is not None:
                    paquete_activo = str(componente.getPackageName())
                    if paquete_activo and (paquete_home is None or paquete_activo != paquete_home):
                        print(f"[DEBUG] App en primer plano (RunningTasks): {paquete_activo}")
                        return AppState(
                            paquete_en_primer_plano=paquete_activo,
                            tiempo_desde_ultimo_cambio_ms=0,
                            timestamp_ultimo_cambio=ahora_ms,
                        )
        except Exception:
            pass

        usage_stats_manager = cast(
            "android.app.usage.UsageStatsManager",
            actividad.getSystemService(Context.USAGE_STATS_SERVICE),
        )

        inicio_ms = ahora_ms - (24 * 60 * 60 * 1000)

        try:
            eventos = usage_stats_manager.queryEvents(inicio_ms, ahora_ms)
            if eventos is not None:
                ultimo_evento = UsageEvents.Event()
                paquete_activo = None
                ultimo_timestamp = 0
                while eventos.hasNextEvent():
                    eventos.getNextEvent(ultimo_evento)
                    if ultimo_evento.getEventType() == UsageEvents.Event.MOVE_TO_FOREGROUND:
                        paquete = str(ultimo_evento.getPackageName())
                        tiempo = int(ultimo_evento.getTimeStamp())
                        if paquete and (paquete_home is None or paquete != paquete_home):
                            ultimo_timestamp = tiempo
                            paquete_activo = paquete
                if paquete_activo:
                    print(f"[DEBUG] UsoStats events -> {paquete_activo} (último evento: {ultimo_timestamp})")
                    return AppState(
                        paquete_en_primer_plano=paquete_activo,
                        tiempo_desde_ultimo_cambio_ms=ahora_ms - ultimo_timestamp,
                        timestamp_ultimo_cambio=ultimo_timestamp,
                    )
        except Exception:
            pass

        stats = usage_stats_manager.queryUsageStats(
            UsageStatsManager.INTERVAL_BEST,
            inicio_ms,
            ahora_ms,
        )

        if stats is not None and stats.size() > 0:
            ultimo_timestamp = 0
            paquete_activo = None

            for i in range(stats.size()):
                usage_stat = stats.get(i)
                ultima_vez = int(usage_stat.getLastTimeUsed())
                paquete = str(usage_stat.getPackageName())
                if ultima_vez > ultimo_timestamp and paquete and (paquete_home is None or paquete != paquete_home):
                    ultimo_timestamp = ultima_vez
                    paquete_activo = paquete

            if paquete_activo:
                print(f"[DEBUG] UsoStats fallback -> {paquete_activo} (último uso hace {ahora_ms - ultimo_timestamp}ms)")
                return AppState(
                    paquete_en_primer_plano=paquete_activo,
                    tiempo_desde_ultimo_cambio_ms=ahora_ms - ultimo_timestamp,
                    timestamp_ultimo_cambio=ultimo_timestamp,
                )

        print("[DEBUG] No se pudo determinar app en primer plano")
        return AppState(
            paquete_en_primer_plano=None,
            tiempo_desde_ultimo_cambio_ms=0,
            timestamp_ultimo_cambio=ahora_ms,
        )

    except Exception as e:
        print(f"[ERROR] Error al detectar app en primer plano: {e}")
        import traceback
        traceback.print_exc()

        return AppState(
            paquete_en_primer_plano=None,
            tiempo_desde_ultimo_cambio_ms=0,
            timestamp_ultimo_cambio=ahora_ms,
        )


def acumular_tiempo_sesion(
    paquete: str,
    segundos_a_acumular: int,
    cache_tiempos: dict[str, int]
) -> dict[str, int]:
    """Acumula tiempo de uso para una app específica durante la sesión.
    
    Args:
        paquete: Nombre del paquete de la app.
        segundos_a_acumular: Segundos a añadir al contador.
        cache_tiempos: Diccionario que mantiene el estado acumulado por paquete.
        
    Returns:
        El mismo diccionario actualizado con el nuevo tiempo acumulado.
    """
    if paquete not in cache_tiempos:
        cache_tiempos[paquete] = 0
    
    cache_tiempos[paquete] += segundos_a_acumular
    
    print(f"[DEBUG] Acumulando {segundos_a_acumular}s para {paquete}: total={cache_tiempos[paquete]}s")
    
    return cache_tiempos


def obtener_top_apps_uso(
    estadisticas: list[EstadisticaUso],
    top_n: int = 5
) -> list[EstadisticaUso]:
    """Obtiene las N apps más usadas de la lista de estadísticas.
    
    Args:
        estadisticas: Lista completa de estadísticas de uso.
        top_n: Cantidad de apps a retornar.
        
    Returns:
        Lista con las top N apps ordenadas por tiempo de uso.
    """
    if not estadisticas:
        return []
    
    # Ya están ordenadas por defecto de obtener_estadisticas_uso
    return estadisticas[:top_n]


def formatear_tiempo(ms: int) -> str:
    """Convierte milisegundos a formato legible HH:MM:SS.
    
    Args:
        ms: Tiempo en milisegundos.
        
    Returns:
        String formateado como "HH:MM:SS".
    """
    segundos = ms // 1000
    horas = segundos // 3600
    minutos = (segundos % 3600) // 60
    segs_restantes = segundos % 60
    
    return f"{horas:02d}:{minutos:02d}:{segs_restantes:02d}"


# Demo rápida para probar en consola
if __name__ == "__main__":
    print("=== Demo UsageStats ===")
    
    # Simular desktop
    stats = obtener_estadisticas_uso()
    print(f"\nApps encontradas: {len(stats)}")
    for stat in stats:
        print(f"  - {stat.nombre_app}: {formatear_tiempo(stat.tiempo_total_ms)}")
    
    estado = detectar_app_en_primer_plano()
    print(f"\nApp en primer plano: {estado.paquete_en_primer_plano}")
    
    # Test de acumulación
    cache = {}
    cache = acumular_tiempo_sesion("com.test.app", 60, cache)
    cache = acumular_tiempo_sesion("com.test.app", 120, cache)
    print(f"\nCache acumulado: {cache}")
