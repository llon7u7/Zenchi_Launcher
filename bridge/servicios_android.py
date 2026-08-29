"""
Puente hacia las APIs de Android para convertir a Zenchi en el launcher
(pantalla de inicio) y para listar/abrir las apps instaladas del usuario.

ACTUALIZACIÓN: Corregida detección de actividad y manejo de PackageManager para Buildozer
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from jnius import autoclass, cast
    HAY_ANDROID = True
except ModuleNotFoundError:
    HAY_ANDROID = False


@dataclass(frozen=True)
class AppInstalada:
    """Una app que el usuario puede abrir desde el cajón de apps de Zenchi."""
    nombre: str      # lo que se muestra en pantalla, ej. "Instagram"
    paquete: str      # identificador interno de Android, ej. "com.instagram.android"


# ---------------------------------------------------------------------------
# Convertirse en el launcher predeterminado
# ---------------------------------------------------------------------------

def _obtener_actividad():
    """Obtiene la actividad actual de Python en Android para Buildozer."""
    if not HAY_ANDROID:
        return None
    
    try:
        # Método correcto para Buildozer: obtener mActivity de PythonActivity
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        actividad = PythonActivity.mActivity
        
        # Verificar que la actividad no sea None
        if actividad is not None:
            print(f"[DEBUG] _obtener_actividad: Usando PythonActivity.mActivity = {actividad}")
            return actividad
            
        # Si mActivity es None, intentar con mInstance como fallback
        if hasattr(PythonActivity, 'mInstance') and PythonActivity.mInstance is not None:
            print(f"[DEBUG] _obtener_actividad: Usando PythonActivity.mInstance = {PythonActivity.mInstance}")
            return PythonActivity.mInstance
            
    except Exception as e:
        print(f"[ERROR] No se pudo obtener actividad (método 1): {e}")
        
    try:
        # Fallback: intentar acceder desde el módulo android
        from android import python_act
        if python_act is not None:
            print(f"[DEBUG] _obtener_actividad: Usando android.python_act = {python_act}")
            return python_act
    except Exception as e:
        print(f"[ERROR] No se pudo obtener actividad (método 2): {e}")
    
    # Si todo falla, retornar None
    print("[DEBUG] _obtener_actividad: No se pudo obtener ninguna actividad, retornando None")
    return None


def solicitar_ser_launcher_predeterminado() -> None:
    """Abre el diálogo nativo de Android para pedir 'usar Zenchi como
    pantalla de inicio'.

    En Android 10+ usa RoleManager, que muestra un diálogo directo y
    confiable. En versiones más viejas, abre los ajustes generales de
    'App de inicio predeterminada' como alternativa.

    Llama a esta función desde un botón en tu interfaz, por ejemplo:
        boton.bind(on_release=lambda *_: solicitar_ser_launcher_predeterminado())
    """
    actividad = _obtener_actividad()
    
    if actividad is None:
        print("[DEBUG] solicitar_ser_launcher_predeterminado: No hay actividad (modo desktop)")
        print("[demo escritorio] Aquí se abriría el diálogo de 'ser launcher predeterminado'.")
        return

    Context = autoclass("android.content.Context")
    Version = autoclass("android.os.Build$VERSION")

    print(f"[DEBUG] SDK_INT = {Version.SDK_INT}")

    if Version.SDK_INT >= 29:
        RoleManager = autoclass("android.app.role.RoleManager")
        gestor_roles = cast(
            "android.app.role.RoleManager",
            actividad.getSystemService(Context.ROLE_SERVICE),
        )
        disponible = bool(gestor_roles.isRoleAvailable(RoleManager.ROLE_HOME))
        ya_es_holder = bool(gestor_roles.isRoleHeld(RoleManager.ROLE_HOME))
        
        print(f"[DEBUG] solicitar_ser_launcher: SDK={Version.SDK_INT}, disponible={disponible}, ya_es_holder={ya_es_holder}")
        print(f"[DEBUG] Activity package name: {actividad.getPackageName()}")
        
        if disponible and not ya_es_holder:
            intent = gestor_roles.createRequestRoleIntent(RoleManager.ROLE_HOME)
            print("[DEBUG] Iniciando startActivityForResult para ROLE_HOME...")
            print(f"[DEBUG] Usando actividad: {actividad}")
            print(f"[DEBUG] Intent: {intent}")
            actividad.startActivityForResult(intent, 1001)
        elif ya_es_holder:
            print("[DEBUG] Zenchi YA ES el launcher predeterminado (isRoleHeld=true)")
        else:
            print("[DEBUG] El rol HOME no está disponible en este dispositivo")
    else:
        print("[DEBUG] SDK < 29, usando método legacy")
        _abrir_ajustes_launcher_legado(actividad)


def _abrir_ajustes_launcher_legado(actividad) -> None:
    Settings = autoclass("android.provider.Settings")
    Intent = autoclass("android.content.Intent")
    intent = Intent(Settings.ACTION_HOME_SETTINGS)
    actividad.startActivity(intent)


def es_launcher_predeterminado() -> bool:
    """True si Zenchi ya está configurado como pantalla de inicio.

    Útil para, por ejemplo, ocultar el botón de 'hacerme predeterminado'
    una vez que ya se logró.
    """
    actividad = _obtener_actividad()
    
    if actividad is None:
        print("[DEBUG] es_launcher_predeterminado: No hay actividad Android (modo desktop)")
        return False

    Context = autoclass("android.content.Context")
    Version = autoclass("android.os.Build$VERSION")
    paquete_zenchi = str(actividad.getPackageName())
    print(f"[DEBUG] es_launcher_predeterminado: package={paquete_zenchi}, SDK={Version.SDK_INT}")

    if Version.SDK_INT >= 29:
        RoleManager = autoclass("android.app.role.RoleManager")
        gestor_roles = cast(
            "android.app.role.RoleManager",
            actividad.getSystemService(Context.ROLE_SERVICE),
        )
        disponible = bool(gestor_roles.isRoleAvailable(RoleManager.ROLE_HOME))
        es_home = bool(gestor_roles.isRoleHeld(RoleManager.ROLE_HOME))
        print(f"[DEBUG] es_launcher_predeterminado (Android {Version.SDK_INT}): ROLE_HOME disponible={disponible}, held={es_home}")
        return es_home

    # Camino viejo (antes de Android 10): comparar quién resuelve CATEGORY_HOME.
    Intent = autoclass("android.content.Intent")
    intent = Intent(Intent.ACTION_MAIN)
    intent.addCategory(Intent.CATEGORY_HOME)
    resolucion = actividad.getPackageManager().resolveActivity(intent, 0)
    if resolucion is None:
        print("[DEBUG] es_launcher_predeterminado (legacy): resolveActivity = None")
        return False
    paquete_actual = str(resolucion.activityInfo.packageName)
    es_home = paquete_actual == paquete_zenchi
    print(f"[DEBUG] es_launcher_predeterminado (legacy): paquete={paquete_actual}, zenchi={paquete_zenchi}, es_home={es_home}")
    return es_home


# ---------------------------------------------------------------------------
# Cajón de apps: listar y abrir las apps instaladas del usuario
# ---------------------------------------------------------------------------

def listar_apps_instaladas() -> list[AppInstalada]:
    """Devuelve todas las apps que el usuario puede abrir normalmente
    (las que tienen ícono en un launcher cualquiera).

    En escritorio devuelve una lista de ejemplo, para que puedas diseñar
    y probar tu grilla de apps sin necesitar el teléfono conectado.
    """
    actividad = _obtener_actividad()
    
    if actividad is None:
        # Mock para desktop - solo visible durante desarrollo
        print("[INFO] Modo desktop: mostrando apps de ejemplo")
        return [
            AppInstalada("Cámara", "com.ejemplo.camara"),
            AppInstalada("Mensajes", "com.ejemplo.mensajes"),
            AppInstalada("Instagram", "com.instagram.android"),
            AppInstalada("Configuración", "com.android.settings"),
            AppInstalada("YouTube", "com.google.android.youtube"),
            AppInstalada("Correo", "com.ejemplo.correo"),
        ]

    try:
        administrador_paquetes = actividad.getPackageManager()

        Intent = autoclass("android.content.Intent")
        intent = Intent(Intent.ACTION_MAIN)
        intent.addCategory(Intent.CATEGORY_LAUNCHER)

        resultados = administrador_paquetes.queryIntentActivities(intent, 0)

        apps: list[AppInstalada] = []
        for i in range(resultados.size()):
            info_resolucion = resultados.get(i)
            nombre = str(info_resolucion.loadLabel(administrador_paquetes))
            paquete = str(info_resolucion.activityInfo.packageName)
            apps.append(AppInstalada(nombre=nombre, paquete=paquete))

        apps.sort(key=lambda app: app.nombre.lower())
        
        if len(apps) == 0:
            print("[WARNING] No se encontraron apps instaladas")
        else:
            print(f"[INFO] Se encontraron {len(apps)} apps instaladas")
        
        return apps
        
    except Exception as e:
        print(f"[ERROR] Error al listar apps: {e}")
        import traceback
        traceback.print_exc()
        # Fallback a lista vacía en caso de error
        return []


def abrir_app(paquete: str) -> None:
    """Lanza una app instalada por su nombre de paquete.

    Llama a esto cuando el usuario toque un ícono en tu cajón de apps:
        boton_app.bind(on_release=lambda *_: abrir_app(app.paquete))
    """
    actividad = _obtener_actividad()
    
    if actividad is None:
        print(f"[demo escritorio] Aquí se abriría la app: {paquete}")
        return

    administrador_paquetes = actividad.getPackageManager()
    intent = administrador_paquetes.getLaunchIntentForPackage(paquete)
    if intent is not None:
        actividad.startActivity(intent)
