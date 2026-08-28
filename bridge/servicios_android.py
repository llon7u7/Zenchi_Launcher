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
            return actividad
            
        # Si mActivity es None, intentar con mInstance como fallback
        if hasattr(PythonActivity, 'mInstance') and PythonActivity.mInstance is not None:
            return PythonActivity.mInstance
            
    except Exception as e:
        print(f"[ERROR] No se pudo obtener actividad (método 1): {e}")
        
    try:
        # Fallback: intentar acceder desde el módulo android
        from android import python_act
        if python_act is not None:
            return python_act
    except Exception as e:
        print(f"[ERROR] No se pudo obtener actividad (método 2): {e}")
    
    # Si todo falla, retornar None
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
        print("[demo escritorio] Aquí se abriría el diálogo de 'ser launcher predeterminado'.")
        return

    Context = autoclass("android.content.Context")
    Version = autoclass("android.os.Build$VERSION")

    if Version.SDK_INT >= 29:
        RoleManager = autoclass("android.app.role.RoleManager")
        gestor_roles = cast(
            "android.app.role.RoleManager",
            actividad.getSystemService(Context.ROLE_SERVICE),
        )
        if gestor_roles.isRoleAvailable(RoleManager.ROLE_HOME) and not gestor_roles.isRoleHeld(
            RoleManager.ROLE_HOME
        ):
            intent = gestor_roles.createRequestRoleIntent(RoleManager.ROLE_HOME)
            actividad.startActivityForResult(intent, 1001)
        else:
            print("Zenchi ya es (o no puede ser) el launcher predeterminado en este equipo.")
    else:
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
        return False

    Context = autoclass("android.content.Context")
    Version = autoclass("android.os.Build$VERSION")

    if Version.SDK_INT >= 29:
        RoleManager = autoclass("android.app.role.RoleManager")
        gestor_roles = cast(
            "android.app.role.RoleManager",
            actividad.getSystemService(Context.ROLE_SERVICE),
        )
        return bool(gestor_roles.isRoleHeld(RoleManager.ROLE_HOME))

    # Camino viejo (antes de Android 10): comparar quién resuelve CATEGORY_HOME.
    Intent = autoclass("android.content.Intent")
    intent = Intent(Intent.ACTION_MAIN)
    intent.addCategory(Intent.CATEGORY_HOME)
    resolucion = actividad.getPackageManager().resolveActivity(intent, 0)
    if resolucion is None:
        return False
    return str(resolucion.activityInfo.packageName) == str(actividad.getPackageName())


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

        # Usar FLAG_ACTIVITY_NEW_TASK para evitar problemas
        flags = autoclass("android.content.Intent").FLAG_ACTIVITY_NEW_TASK
        intent.setFlags(flags)

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
