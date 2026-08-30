"""
Puente de estado compartido entre Python (Kivy) y el Service nativo de
Android (ZenchiMonitorService.java).

¿Por qué existe esto?
----------------------
Kivy/Python solo se ejecuta mientras la Activity de Zenchi está visible.
En cuanto el usuario abre otra app, Android pausa la Activity y el
`Clock` de Kivy deja de correr — por eso Python NO puede vigilar ni
bloquear apps mientras el usuario está dentro de ellas.

Para resolver esto, `ZenchiMonitorService` corre como un Service nativo
en Java, independiente del ciclo de vida de la Activity. Ese Service
necesita saber los mismos límites y el mismo estado que ve Python
(apps bloqueadas, tiempo acumulado por app, límites personalizados), y
Python necesita enterarse de lo que el Service hizo mientras Zenchi
estaba en segundo plano (p. ej. una app que se bloqueó porque el
usuario se pasó del límite estando dentro de ella).

En vez de compartir el archivo JSON (las rutas de archivos entre el
proceso de p4a/Python y un Service Java pueden no coincidir de forma
confiable), usamos `SharedPreferences`, que ambos lados pueden leer y
escribir sin ambigüedad de rutas.
"""

from __future__ import annotations

import json

try:
    from jnius import autoclass
    HAY_ANDROID = True
except ModuleNotFoundError:
    HAY_ANDROID = False

NOMBRE_PREFS = "ZenchiPrefsCompartidas"

# Claves usadas dentro de SharedPreferences (deben coincidir EXACTO con
# las que lee/escribe ZenchiMonitorService.java)
CLAVE_FECHA = "fecha"
CLAVE_CACHE_TIEMPOS = "cache_tiempos_por_app"       # JSON: {paquete: segundos}
CLAVE_APPS_BLOQUEADAS = "apps_bloqueadas_hoy"       # JSON: [paquete, ...]
CLAVE_LIMITES_PERSONALIZADOS = "limites_personalizados"  # JSON: {paquete: segundos}
CLAVE_APPS_ADICTIVAS = "apps_adictivas"             # JSON: [paquete, ...]
CLAVE_LIMITE_APP_DEFECTO = "limite_app_defecto"     # int segundos
CLAVE_VERSION_ESTADO = "version_estado"             # int, para detectar cambios


def _obtener_actividad():
    if not HAY_ANDROID:
        return None
    try:
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        return PythonActivity.mActivity
    except Exception:
        return None


def _obtener_prefs():
    actividad = _obtener_actividad()
    if actividad is None:
        return None
    try:
        Context = autoclass("android.content.Context")
        return actividad.getSharedPreferences(NOMBRE_PREFS, Context.MODE_PRIVATE)
    except Exception as e:
        print(f"[ERROR] No se pudo obtener SharedPreferences: {e}")
        return None


def publicar_configuracion(
    apps_adictivas: set[str],
    limites_personalizados: dict[str, int],
    limite_app_defecto: int,
) -> None:
    """Python -> Service: le dice al Service qué límites usar.

    Llamar cada vez que cambien los límites personalizados o la lista de
    apps adictivas (por ejemplo, justo después de `_guardar_configuracion`).
    """
    prefs = _obtener_prefs()
    if prefs is None:
        print("[DEBUG] Modo desktop: no hay SharedPreferences que publicar")
        return
    try:
        editor = prefs.edit()
        editor.putString(CLAVE_APPS_ADICTIVAS, json.dumps(sorted(apps_adictivas)))
        editor.putString(CLAVE_LIMITES_PERSONALIZADOS, json.dumps(
            {str(k): int(v) for k, v in limites_personalizados.items()}
        ))
        editor.putInt(CLAVE_LIMITE_APP_DEFECTO, int(limite_app_defecto))
        editor.apply()
    except Exception as e:
        print(f"[ERROR] No se pudo publicar configuración al Service: {e}")


def publicar_estado(
    fecha: str,
    cache_tiempos_por_app: dict[str, int],
    apps_bloqueadas_hoy: set[str],
) -> None:
    """Python -> Service: sincroniza el estado actual (tiempos y bloqueos).

    Llamar junto con `_guardar_estado_diario()`, para que el Service
    arranque su vigilancia con la misma foto de datos que tiene Python.
    """
    prefs = _obtener_prefs()
    if prefs is None:
        return
    try:
        editor = prefs.edit()
        editor.putString(CLAVE_FECHA, fecha)
        editor.putString(CLAVE_CACHE_TIEMPOS, json.dumps(
            {str(k): int(v) for k, v in cache_tiempos_por_app.items()}
        ))
        editor.putString(CLAVE_APPS_BLOQUEADAS, json.dumps(sorted(apps_bloqueadas_hoy)))
        editor.apply()
    except Exception as e:
        print(f"[ERROR] No se pudo publicar estado al Service: {e}")


def leer_estado_del_service() -> dict:
    """Service -> Python: lee lo que el Service haya actualizado mientras
    Zenchi estaba en segundo plano (apps bloqueadas nuevas, tiempo
    acumulado en apps que se usaron mientras Zenchi no estaba visible).

    Llamar en `on_resume()` de la App, para fusionar estos datos con el
    estado en memoria de Python antes de seguir operando.
    """
    prefs = _obtener_prefs()
    if prefs is None:
        return {"fecha": None, "cache_tiempos_por_app": {}, "apps_bloqueadas_hoy": []}

    try:
        fecha = prefs.getString(CLAVE_FECHA, None)
        cache_raw = prefs.getString(CLAVE_CACHE_TIEMPOS, "{}")
        bloqueadas_raw = prefs.getString(CLAVE_APPS_BLOQUEADAS, "[]")

        cache_tiempos_por_app = {
            str(k): int(v) for k, v in json.loads(cache_raw).items()
        }
        apps_bloqueadas_hoy = list(json.loads(bloqueadas_raw))

        return {
            "fecha": fecha,
            "cache_tiempos_por_app": cache_tiempos_por_app,
            "apps_bloqueadas_hoy": apps_bloqueadas_hoy,
        }
    except Exception as e:
        print(f"[ERROR] No se pudo leer estado del Service: {e}")
        return {"fecha": None, "cache_tiempos_por_app": {}, "apps_bloqueadas_hoy": []}


def fusionar_estado_en(app) -> None:
    """Combina lo que el Service vio (mientras Zenchi estaba en segundo
    plano) dentro del estado en memoria de la app Kivy.

    - Si el Service reporta una fecha distinta a la de la app, no se
      fusiona (deja que `_reiniciar_si_nuevo_dia` maneje el cambio de día).
    - El tiempo por app se toma como el MÁXIMO entre lo que ya tenía
      Python y lo que reporta el Service (nunca se resta tiempo).
    - Las apps bloqueadas se unen (nunca se desbloquea automáticamente
      por esta vía).
    """
    estado_service = leer_estado_del_service()

    if estado_service["fecha"] and estado_service["fecha"] != app.dia_actual:
        return

    for paquete, segundos in estado_service["cache_tiempos_por_app"].items():
        actual = app.cache_tiempos_por_app.get(paquete, 0)
        if segundos > actual:
            app.cache_tiempos_por_app[paquete] = segundos

    nuevas_bloqueadas = set(estado_service["apps_bloqueadas_hoy"])
    if nuevas_bloqueadas - app.apps_bloqueadas_hoy:
        app.apps_bloqueadas_hoy |= nuevas_bloqueadas

    app.tiempo_acumulado_hoy = sum(app.cache_tiempos_por_app.values())
    app.segundos_usados = app.tiempo_acumulado_hoy
