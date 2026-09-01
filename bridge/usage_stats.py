"""
Módulo para monitorear el uso de aplicaciones en Android mediante UsageStats.

Este módulo proporciona funciones para:
1. Obtener estadísticas de uso de cada app instalada
2. Detectar qué app está en primer plano actualmente
3. Acumular tiempo de uso por paquete durante la sesión de enfoque

Para que funcione correctamente, el usuario debe otorgar el permiso
PACKAGE_USAGE_STATS desde Ajustes > Acceso especial > Uso de datos.

ACTUALIZACIÓN (fix "tiempo sigue avanzando en segundo plano"):
`detectar_app_en_primer_plano()` usaba `getRunningAppProcesses()` con
`importancia <= 200` como señal de "app activa". El problema es que
`IMPORTANCE_FOREGROUND_SERVICE = 125` también es <= 200, así que una app
con un servicio en primer plano (reproduciendo audio/video, con una
notificación persistente, etc.) seguía siendo detectada como "en pantalla"
aunque el usuario ya hubiera vuelto al launcher. Ahora:

1. `UsageEvents` (MOVE_TO_FOREGROUND / MOVE_TO_BACKGROUND) es la fuente
   PRIMARIA y más confiable — se consulta primero.
2. `RunningTasks`/`RunningAppProcesses` sólo se usan como respaldo, y el
   segundo exige `importance == IMPORTANCE_FOREGROUND` (exactamente 100),
   no un rango amplio.
3. Cualquier detección que coincida con el paquete del launcher/home se
   trata como "sin app en primer plano" (None), en todos los caminos, no
   solo en el último fallback.

IMPORTANTE — limitación de arquitectura: esta función solo puede ejecutarse
mientras el proceso de Python está vivo y su Clock corriendo, es decir,
mientras la Activity de Zenchi está en primer plano (visible). En cuanto el
usuario abre otra app, Android pausa la Activity y Kivy detiene su loop, así
que este módulo NO puede vigilar ni bloquear apps mientras el usuario está
dentro de ellas. Para eso se necesita un Service nativo de Android
(ver `android_src/.../ZenchiMonitorService.java` y `bridge/estado_compartido.py`).
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


def _obtener_paquete_home(actividad) -> Optional[str]:
    """Devuelve el paquete que resuelve como HOME (debería ser el propio Zenchi)."""
    try:
        PackageManager = autoclass("android.content.pm.PackageManager")
        Intent = autoclass("android.content.Intent")
        pm = actividad.getPackageManager()
        home_intent = Intent(Intent.ACTION_MAIN)
        home_intent.addCategory(Intent.CATEGORY_HOME)
        home_resolve = pm.resolveActivity(home_intent, PackageManager.MATCH_DEFAULT_ONLY)
        if home_resolve is None:
            return None
        return str(home_resolve.activityInfo.packageName)
    except Exception:
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
    
    # NUEVO: Esta función ahora se llama automáticamente si el permiso no está concedido.
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


def verificar_y_solicitar_permiso_usage_stats() -> bool:
    """Verifica si el permiso PACKAGE_USAGE_STATS está concedido y, si no,
    abre automáticamente la pantalla de ajustes para que el usuario lo otorgue.
    
    Returns:
        True si el permiso ya estaba concedido, False si se tuvo que abrir la pantalla.
    
    # NUEVA FUNCIÓN: Reemplaza la verificación manual con solicitud automática.
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

        mode = app_ops.checkOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS,
            actividad.getApplicationInfo().uid,
            actividad.getPackageName()
        )

        tiene_permiso = (mode == AppOpsManager.MODE_ALLOWED)

        if not tiene_permiso:
            print("[WARNING] No hay permiso PACKAGE_USAGE_STATS, abriendo ajustes automáticamente")
            # NUEVO: Solicitar automáticamente sin esperar acción del usuario
            solicitar_permiso_usage_stats()
        else:
            print("[DEBUG] Permiso PACKAGE_USAGE_STATS concedido")

        return tiene_permiso

    except Exception as e:
        print(f"[ERROR] Error al verificar permiso UsageStats: {e}")
        return False


def obtener_estadisticas_uso(rango_horas: int = 24) -> list[EstadisticaUso]:
    """Obtiene estadísticas de uso de todas las apps en las últimas N horas."""
    actividad = _obtener_actividad()

    if actividad is None:
        print("[DEBUG] Modo desktop: devolviendo estadísticas mock")
        return [
            EstadisticaUso(
                paquete="com.instagram.android",
                nombre_app="Instagram",
                tiempo_total_ms=3600000,
                ultima_vez_usado=int(datetime.now().timestamp() * 1000),
                tiempo_en_primer_plano_ms=1800000
            ),
            EstadisticaUso(
                paquete="com.google.android.youtube",
                nombre_app="YouTube",
                tiempo_total_ms=2700000,
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

        ahora_ms = int(datetime.now().timestamp() * 1000)
        inicio_ms = ahora_ms - (rango_horas * 60 * 60 * 1000)

        stats = usage_stats_manager.queryUsageStats(
            UsageStatsManager.INTERVAL_DAILY,
            inicio_ms,
            ahora_ms
        )

        if stats is None or stats.size() == 0:
            print("[DEBUG] No hay estadísticas de uso disponibles")
            return []

        pm = actividad.getPackageManager()

        resultados: list[EstadisticaUso] = []

        for i in range(stats.size()):
            usage_stat = stats.get(i)
            paquete = str(usage_stat.getPackageName())
            tiempo_total = int(usage_stat.getTotalTimeInForeground())
            ultima_vez = int(usage_stat.getLastTimeUsed())

            try:
                app_info = pm.getApplicationInfo(paquete, 0)
                nombre_app = str(pm.getApplicationLabel(app_info))
            except Exception:
                nombre_app = paquete

            if tiempo_total > 0:
                resultados.append(
                    EstadisticaUso(
                        paquete=paquete,
                        nombre_app=nombre_app,
                        tiempo_total_ms=tiempo_total,
                        ultima_vez_usado=ultima_vez,
                        tiempo_en_primer_plano_ms=tiempo_total
                    )
                )

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

    Orden de confiabilidad (de mayor a menor):
    1. UsageEvents (MOVE_TO_FOREGROUND / MOVE_TO_BACKGROUND) — refleja
       exactamente lo que el sistema considera "en pantalla", sin verse
       afectado por servicios en primer plano de otras apps.
    2. RunningTasks(1).topActivity — sirve como respaldo si por algún
       motivo el stream de eventos viene vacío.
    3. RunningAppProcesses con `importance == IMPORTANCE_FOREGROUND` (100)
       EXACTO — antes se usaba `<= 200`, lo cual también incluía
       `IMPORTANCE_FOREGROUND_SERVICE` (125) y causaba falsos positivos
       con apps que solo tienen un servicio corriendo (música, video, etc.)
       pero ya no están en pantalla.
    4. Último recurso: última app usada según queryUsageStats.

    En cualquiera de los caminos, si el paquete detectado es el propio
    launcher/home, se considera que NO hay app en primer plano (None).
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
    paquete_zenchi = str(actividad.getPackageName())
    paquete_home = _obtener_paquete_home(actividad) or paquete_zenchi

    def _es_home(paquete: Optional[str]) -> bool:
        return paquete is not None and (paquete == paquete_home or paquete == paquete_zenchi)

    try:
        Context = autoclass("android.content.Context")
        ActivityManager = autoclass("android.app.ActivityManager")
        UsageStatsManager = autoclass("android.app.usage.UsageStatsManager")
        UsageEvents = autoclass("android.app.usage.UsageEvents")

        usage_stats_manager = cast(
            "android.app.usage.UsageStatsManager",
            actividad.getSystemService(Context.USAGE_STATS_SERVICE),
        )

        inicio_ms = ahora_ms - (10 * 60 * 1000)  # ventana de 10 minutos es suficiente

        # --- 1) Fuente primaria: UsageEvents ---
        try:
            eventos = usage_stats_manager.queryEvents(inicio_ms, ahora_ms)
            if eventos is not None:
                evento = UsageEvents.Event()
                paquete_activo = None
                ultimo_timestamp = 0
                ultimo_tipo = None
                while eventos.hasNextEvent():
                    eventos.getNextEvent(evento)
                    tipo_evento = evento.getEventType()
                    if tipo_evento in (
                        UsageEvents.Event.MOVE_TO_FOREGROUND,
                        UsageEvents.Event.MOVE_TO_BACKGROUND,
                    ):
                        paquete = str(evento.getPackageName())
                        tiempo = int(evento.getTimeStamp())
                        if paquete:
                            ultimo_timestamp = tiempo
                            paquete_activo = paquete
                            ultimo_tipo = tipo_evento

                if paquete_activo is not None:
                    if ultimo_tipo == UsageEvents.Event.MOVE_TO_BACKGROUND or _es_home(paquete_activo):
                        print(f"[DEBUG] UsageEvents -> sin app activa (último: {paquete_activo})")
                        return AppState(
                            paquete_en_primer_plano=None,
                            tiempo_desde_ultimo_cambio_ms=ahora_ms - ultimo_timestamp,
                            timestamp_ultimo_cambio=ultimo_timestamp,
                        )
                    print(f"[DEBUG] UsageEvents -> {paquete_activo}")
                    return AppState(
                        paquete_en_primer_plano=paquete_activo,
                        tiempo_desde_ultimo_cambio_ms=ahora_ms - ultimo_timestamp,
                        timestamp_ultimo_cambio=ultimo_timestamp,
                    )
        except Exception:
            pass

        # --- 2) Respaldo: RunningTasks ---
        activity_manager = cast(
            "android.app.ActivityManager",
            actividad.getSystemService(Context.ACTIVITY_SERVICE),
        )
        try:
            tareas = activity_manager.getRunningTasks(1)
            if tareas is not None and tareas.size() > 0:
                tarea_superior = tareas.get(0)
                componente = getattr(tarea_superior, "topActivity", None)
                if componente is not None:
                    paquete_activo = str(componente.getPackageName())
                    if paquete_activo and not _es_home(paquete_activo):
                        print(f"[DEBUG] RunningTasks -> {paquete_activo}")
                        return AppState(
                            paquete_en_primer_plano=paquete_activo,
                            tiempo_desde_ultimo_cambio_ms=0,
                            timestamp_ultimo_cambio=ahora_ms,
                        )
                    if paquete_activo and _es_home(paquete_activo):
                        return AppState(
                            paquete_en_primer_plano=None,
                            tiempo_desde_ultimo_cambio_ms=0,
                            timestamp_ultimo_cambio=ahora_ms,
                        )
        except Exception:
            pass

        # --- 3) Respaldo estricto: solo IMPORTANCE_FOREGROUND exacto ---
        try:
            procesos = activity_manager.getRunningAppProcesses()
            if procesos is not None:
                for proceso in procesos:
                    pkg_list = getattr(proceso, "pkgList", None)
                    if not pkg_list:
                        continue
                    importancia = getattr(proceso, "importance", None)
                    if importancia != ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND:
                        continue
                    for paquete in pkg_list:
                        nombre_pkg = str(paquete)
                        if nombre_pkg and not _es_home(nombre_pkg):
                            print(f"[DEBUG] RunningAppProcesses (IMPORTANCE_FOREGROUND exacto) -> {nombre_pkg}")
                            return AppState(
                                paquete_en_primer_plano=nombre_pkg,
                                tiempo_desde_ultimo_cambio_ms=0,
                                timestamp_ultimo_cambio=ahora_ms,
                            )
        except Exception:
            pass

        # --- 4) Último recurso: queryUsageStats por última vez usada ---
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
                if ultima_vez > ultimo_timestamp and paquete and not _es_home(paquete):
                    ultimo_timestamp = ultima_vez
                    paquete_activo = paquete

            # Si esa "última vez usada" es muy vieja (más de 15s), no es
            # confiable como señal de "está en pantalla ahora mismo".
            if paquete_activo and (ahora_ms - ultimo_timestamp) <= 15000:
                print(f"[DEBUG] UsoStats fallback -> {paquete_activo}")
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
    """Acumula tiempo de uso para una app específica durante la sesión."""
    if paquete not in cache_tiempos:
        cache_tiempos[paquete] = 0

    cache_tiempos[paquete] += segundos_a_acumular

    print(f"[DEBUG] Acumulando {segundos_a_acumular}s para {paquete}: total={cache_tiempos[paquete]}s")

    return cache_tiempos


def obtener_top_apps_uso(
    estadisticas: list[EstadisticaUso],
    top_n: int = 5
) -> list[EstadisticaUso]:
    """Obtiene las N apps más usadas de la lista de estadísticas."""
    if not estadisticas:
        return []

    return estadisticas[:top_n]


def formatear_tiempo(ms: int) -> str:
    """Convierte milisegundos a formato legible HH:MM:SS."""
    segundos = ms // 1000
    horas = segundos // 3600
    minutos = (segundos % 3600) // 60
    segs_restantes = segundos % 60

    return f"{horas:02d}:{minutos:02d}:{segs_restantes:02d}"


def obtener_tiempo_uso_app(paquete: str, rango_segundos: int = 900) -> int:
    """Obtiene el tiempo REAL en primer plano que una app específica tuvo
    durante los últimos N segundos usando UsageStatsManager.queryEvents.
    
    Esto reemplaza el contador manual que fallaba porque Kivy se pausa cuando
    Zenchi pasa a segundo plano. Ahora consultamos directamente la API nativa
    de Android que lleva la cuenta precisa del tiempo en primer plano.
    
    Args:
        paquete: El nombre del paquete de la app (ej. "com.instagram.android")
        rango_segundos: Ventana de tiempo hacia atrás para consultar. 
                        Por defecto 900s (15 min) para asegurar que UsageStats
                        haya consolidado los datos. Si el tiempo sigue en 0,
                        aumentar a 1800 (30 min) o 3600 (1 hora).
    
    Returns:
        Tiempo en primer plano en SEGUNDOS para esa app en la ventana especificada.
        Retorna 0 si no hay datos o si no hay permiso.
    
    # NUEVA FUNCIÓN: Usa UsageStatsManager nativo para obtener tiempo real sin
    # depender del loop de Kivy. Se llama desde on_resume() para saber cuánto
    # tiempo estuvo abierta la app que el usuario acaba de cerrar.
    
    # FIX (tiempo = 0s): Se aumentó el rango por defecto de 60s a 900s (15 min)
    # porque UsageStatsManager.consolidar datos con latencia. Con 60s, Android
    # aún no había procesado las estadísticas y devolvía 0. Ahora usamos
    # queryEvents() que es más preciso y en tiempo real que queryUsageStats().
    """
    actividad = _obtener_actividad()

    if actividad is None:
        print(f"[DEBUG] Modo desktop: simulando tiempo de uso para {paquete}")
        return 30  # Mock para pruebas en escritorio

    if not obtener_permiso_usage_stats():
        print(f"[WARNING] Sin permiso UsageStats, no se puede obtener tiempo para {paquete}")
        return 0

    try:
        Context = autoclass("android.content.Context")
        UsageStatsManager = autoclass("android.app.usage.UsageStatsManager")
        UsageEvents = autoclass("android.app.usage.UsageEvents")

        usage_stats_manager = cast(
            "android.app.usage.UsageStatsManager",
            actividad.getSystemService(Context.USAGE_STATS_SERVICE)
        )

        ahora_ms = int(datetime.now().timestamp() * 1000)
        inicio_ms = ahora_ms - (rango_segundos * 1000)

        # --- MÉTODO PRIMARIO: queryEvents() es más preciso y en tiempo real ---
        # queryUsageStats() tiene latencia de consolidación (puede tardar minutos
        # en actualizar getTotalTimeInForeground()). queryEvents() devuelve los
        # eventos crudos MOVE_TO_FOREGROUND / MOVE_TO_BACKGROUND inmediatamente.
        try:
            eventos = usage_stats_manager.queryEvents(inicio_ms, ahora_ms)
            if eventos is not None and eventos.hasNextEvent():
                evento = UsageEvents.Event()
                ultimo_foreground_ms = None
                ultimo_background_ms = None
                
                # Iterar todos los eventos para encontrar el último par FOREGROUND/BACKGROUND
                while eventos.hasNextEvent():
                    eventos.getNextEvent(evento)
                    tipo_evento = evento.getEventType()
                    evento_paquete = str(evento.getPackageName())
                    evento_tiempo = int(evento.getTimeStamp())
                    
                    if evento_paquete == paquete:
                        if tipo_evento == UsageEvents.Event.MOVE_TO_FOREGROUND:
                            ultimo_foreground_ms = evento_tiempo
                        elif tipo_evento == UsageEvents.Event.MOVE_TO_BACKGROUND:
                            ultimo_background_ms = evento_tiempo
                
                # Calcular tiempo basado en los eventos encontrados
                if ultimo_foreground_ms is not None:
                    if ultimo_background_ms is not None and ultimo_background_ms > ultimo_foreground_ms:
                        # La app fue cerrada (evento BACKGROUND recibido)
                        tiempo_ms = ultimo_background_ms - ultimo_foreground_ms
                        tiempo_segundos = max(0, tiempo_ms // 1000)
                        print(f"[DEBUG] QueryEvents -> {paquete}: {tiempo_segundos}s (FOREGROUND@{ultimo_foreground_ms} -> BACKGROUND@{ultimo_background_ms})")
                        return tiempo_segundos
                    else:
                        # La app sigue abierta o no hubo evento BACKGROUND
                        # Calcular desde último FOREGROUND hasta AHORA
                        tiempo_ms = ahora_ms - ultimo_foreground_ms
                        tiempo_segundos = max(0, tiempo_ms // 1000)
                        print(f"[DEBUG] QueryEvents -> {paquete}: {tiempo_segundos}s (FOREGROUND@{ultimo_foreground_ms} -> AHORA, sin BACKGROUND)")
                        return tiempo_segundos
                        
        except Exception as e:
            print(f"[WARNING] Error en queryEvents: {e}, fallback a queryUsageStats")

        # --- FALLBACK: queryUsageStats() si queryEvents falla o no encuentra nada ---
        stats = usage_stats_manager.queryUsageStats(
            UsageStatsManager.INTERVAL_BEST,
            inicio_ms,
            ahora_ms
        )

        if stats is None or stats.size() == 0:
            print(f"[DEBUG] No hay estadísticas de uso disponibles para {paquete}")
            return 0

        for i in range(stats.size()):
            usage_stat = stats.get(i)
            stat_paquete = str(usage_stat.getPackageName())
            
            if stat_paquete == paquete:
                # getTotalTimeInForeground devuelve milisegundos
                # NOTA: Este valor puede tener latencia de consolidación
                tiempo_ms = int(usage_stat.getTotalTimeInForeground())
                tiempo_segundos = tiempo_ms // 1000
                print(f"[DEBUG] UsageStats (fallback) -> {paquete}: {tiempo_segundos}s en primer plano (últimos {rango_segundos}s)")
                return tiempo_segundos

        print(f"[DEBUG] {paquete} no aparece en UsageStats para la ventana consultada ({rango_segundos}s)")
        return 0

    except Exception as e:
        print(f"[ERROR] Error al obtener tiempo de uso para {paquete}: {e}")
        import traceback
        traceback.print_exc()
        return 0


def obtener_tiempos_uso_apps(paquetes: list[str], rango_segundos: int = 60) -> dict[str, int]:
    """Obtiene los tiempos reales de uso en primer plano para MÚLTIPLES apps.
    
    Es más eficiente que llamar obtener_tiempo_uso_app() individualmente
    porque hace una sola consulta a UsageStatsManager y filtra los resultados.
    
    Args:
        paquetes: Lista de nombres de paquetes a consultar
        rango_segundos: Ventana de tiempo hacia atrás para consultar
    
    Returns:
        Diccionario {paquete: segundos_en_primer_plano}
    
    # NUEVA FUNCIÓN: Optimizada para consultar múltiples apps de una vez.
    """
    actividad = _obtener_actividad()

    if actividad is None:
        print("[DEBUG] Modo desktop: devolviendo tiempos mock")
        return {p: 30 for p in paquetes}

    if not obtener_permiso_usage_stats():
        print("[WARNING] Sin permiso UsageStats, retornando diccionario vacío")
        return {}

    try:
        Context = autoclass("android.content.Context")
        UsageStatsManager = autoclass("android.app.usage.UsageStatsManager")

        usage_stats_manager = cast(
            "android.app.usage.UsageStatsManager",
            actividad.getSystemService(Context.USAGE_STATS_SERVICE)
        )

        ahora_ms = int(datetime.now().timestamp() * 1000)
        inicio_ms = ahora_ms - (rango_segundos * 1000)

        stats = usage_stats_manager.queryUsageStats(
            UsageStatsManager.INTERVAL_BEST,
            inicio_ms,
            ahora_ms
        )

        if stats is None or stats.size() == 0:
            print("[DEBUG] No hay estadísticas de uso disponibles")
            return {}

        resultados = {}
        paquetes_set = set(paquetes)

        for i in range(stats.size()):
            usage_stat = stats.get(i)
            stat_paquete = str(usage_stat.getPackageName())
            
            if stat_paquete in paquetes_set:
                tiempo_ms = int(usage_stat.getTotalTimeInForeground())
                tiempo_segundos = tiempo_ms // 1000
                resultados[stat_paquete] = tiempo_segundos
                print(f"[DEBUG] UsageStats -> {stat_paquete}: {tiempo_segundos}s en primer plano")

        # Para paquetes que no aparecen en los resultados, poner 0
        for paquete in paquetes:
            if paquete not in resultados:
                resultados[paquete] = 0

        return resultados

    except Exception as e:
        print(f"[ERROR] Error al obtener tiempos de uso: {e}")
        import traceback
        traceback.print_exc()
        return {}


# Demo rápida para probar en consola
if __name__ == "__main__":
    print("=== Demo UsageStats ===")

    stats = obtener_estadisticas_uso()
    print(f"\nApps encontradas: {len(stats)}")
    for stat in stats:
        print(f"  - {stat.nombre_app}: {formatear_tiempo(stat.tiempo_total_ms)}")

    estado = detectar_app_en_primer_plano()
    print(f"\nApp en primer plano: {estado.paquete_en_primer_plano}")

    cache = {}
    cache = acumular_tiempo_sesion("com.test.app", 60, cache)
    cache = acumular_tiempo_sesion("com.test.app", 120, cache)
    print(f"\nCache acumulado: {cache}")