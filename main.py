"""
Punto de entrada de la app Zenchi.

ACTUALIZACIÓN: Forzar refresh de lista de apps después de convertirse en launcher
Este archivo conecta el MOTOR (motor/politica.py) con Kivy.
La parte de INTERFAZ (colores, layout, animaciones, estilo) es responsabilidad
del desarrollador visual. Este backend ya maneja:
- Listado de apps instaladas del usuario
- Funcionalidad básica de launcher
- Control de tiempo de uso con la mascota Zenchi
"""

from datetime import date
import json
from pathlib import Path

from kivy.config import Config; Config.set('graphics', 'width', '360'); Config.set('graphics', 'height', '740')
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from motor.politica import EstadoMascota, InstantaneaUso, MotorZenchi, calcular_limite_dinamico


class AppIconButton(Button):
    def __init__(self, paquete="", nombre="", abrir_callback=None, long_press_callback=None, **kwargs):
        super().__init__(**kwargs)
        self.paquete = paquete
        self.nombre = nombre
        self.abrir_callback = abrir_callback
        self.long_press_callback = long_press_callback
        self.long_press_timer = None
        self.long_press_triggered = False

    def _cancelar_timer(self):
        if self.long_press_timer is not None:
            Clock.unschedule(self.long_press_timer)
            self.long_press_timer = None

    def _trigger_long_press(self, _dt=None):
        self.long_press_triggered = True
        if self.long_press_callback is not None:
            self.long_press_callback(self.paquete, self.nombre)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        self._cancelar_timer()
        self.long_press_timer = Clock.schedule_once(self._trigger_long_press, 0.8)
        touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            if not self.collide_point(*touch.pos):
                self._cancelar_timer()
                touch.ungrab(self)
                return True
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._cancelar_timer()
            if self.long_press_triggered:
                self.long_press_triggered = False
                return True
            if self.collide_point(*touch.pos) and self.abrir_callback is not None:
                self.abrir_callback(self.paquete, self.nombre)
            return True
        return super().on_touch_up(touch)

from bridge.servicios_android import (
    _obtener_actividad,
    abrir_app,
    es_launcher_predeterminado,
    listar_apps_instaladas,
    solicitar_ser_launcher_predeterminado,
)
from bridge.usage_stats import (
    detectar_app_en_primer_plano,
    obtener_permiso_usage_stats,
    solicitar_permiso_usage_stats,
)


class ZenchiApp(App):
    # --- Datos que la interfaz puede leer/mostrar ---
    segundos_usados = NumericProperty(0)
    limite_segundos = NumericProperty(60 * 60)       # límite diario: 1 hora
    limite_segundos_por_app = NumericProperty(30 * 60)
    estado_mascota = StringProperty(EstadoMascota.OCIOSO.value)
    tiempo_acumulado_hoy = 0  # Tiempo total usado hoy (persistente)
    dia_actual = ""
    ultima_app_abierta = None  # Paquete de la última app abierta
    _tiempo_ultima_apertura = None  # Timestamp cuando se abrió la última app
    sesion_activa = True

    # --- Monitoreo de uso por app ---
    app_en_primer_plano = StringProperty("")
    tiempo_app_actual = NumericProperty(0)
    tiene_permiso_usage_stats = False
    cache_tiempos_por_app = {}  # {paquete: segundos_acumulados}
    paquete_restringido_actual = None
    apps_bloqueadas_hoy = set()
    _inicio_tiempo_app_actual = None
    apps_adictivas = {
        "com.instagram.android",
        "com.google.android.youtube",
        "com.tiktok.android",
        "com.twitter.android",
        "com.reddit.frontpage",
        "com.facebook.katana",
    }
    limites_personalizados = {}

    def _ruta_estado_diario(self) -> Path:
        return Path(__file__).resolve().parent / ".zenchi_estado_diario.json"

    def _cargar_estado_diario(self) -> dict:
        ruta = self._ruta_estado_diario()
        if not ruta.exists():
            return {"fecha": date.today().isoformat(), "tiempo_total": 0, "tiempo_por_app": {}, "apps_bloqueadas": []}

        try:
            with ruta.open("r", encoding="utf-8") as archivo:
                datos = json.load(archivo)
                if not isinstance(datos, dict):
                    raise ValueError("Estado inválido")
                return datos
        except Exception:
            return {"fecha": date.today().isoformat(), "tiempo_total": 0, "tiempo_por_app": {}, "apps_bloqueadas": []}

    def _guardar_estado_diario(self) -> None:
        ruta = self._ruta_estado_diario()
        payload = {
            "fecha": self.dia_actual,
            "tiempo_total": int(self.tiempo_acumulado_hoy),
            "tiempo_por_app": {str(k): int(v) for k, v in self.cache_tiempos_por_app.items()},
            "apps_bloqueadas": sorted(self.apps_bloqueadas_hoy),
        }
        with ruta.open("w", encoding="utf-8") as archivo:
            json.dump(payload, archivo, ensure_ascii=False, indent=2)

    def _reiniciar_si_nuevo_dia(self) -> None:
        hoy = date.today().isoformat()
        if self.dia_actual == hoy:
            return

        self.dia_actual = hoy
        self.tiempo_acumulado_hoy = 0
        self.segundos_usados = 0
        self.cache_tiempos_por_app = {}
        self.apps_bloqueadas_hoy = set()
        self.paquete_restringido_actual = None
        self.ultima_app_abierta = None
        self._tiempo_ultima_apertura = None
        self.app_en_primer_plano = ""
        self._inicio_tiempo_app_actual = None
        if hasattr(self, "etiqueta_estado"):
            self.etiqueta_estado.text = "Nuevo día: Zenchi reinició sus límites."
        self._guardar_estado_diario()

    def _finalizar_tiempo_app_actual(self) -> None:
        """Guarda el tiempo real consumido por la app activa antes de cambiar de contexto."""
        if not self.app_en_primer_plano or self._inicio_tiempo_app_actual is None:
            return

        from time import time
        segundos = max(0, int(time() - self._inicio_tiempo_app_actual))
        if segundos > 0:
            self.cache_tiempos_por_app[self.app_en_primer_plano] = self.cache_tiempos_por_app.get(self.app_en_primer_plano, 0) + segundos
            self.tiempo_acumulado_hoy = sum(self.cache_tiempos_por_app.values())
            self.segundos_usados = self.tiempo_acumulado_hoy
            self._guardar_estado_diario()

        self._inicio_tiempo_app_actual = None

    def _ruta_configuracion(self) -> Path:
        return Path(__file__).resolve().parent / ".zenchi_config.json"

    def _cargar_configuracion(self) -> None:
        ruta = self._ruta_configuracion()
        if not ruta.exists():
            self.apps_adictivas = set(self.apps_adictivas)
            self.limites_personalizados = dict(self.limites_personalizados)
            return

        try:
            with ruta.open("r", encoding="utf-8") as archivo:
                datos = json.load(archivo)
            if isinstance(datos, dict):
                self.apps_adictivas = set(datos.get("apps_adictivas", self.apps_adictivas))
                self.limites_personalizados = {str(k): int(v) for k, v in datos.get("limites_personalizados", {}).items()}
        except Exception:
            self.apps_adictivas = set(self.apps_adictivas)
            self.limites_personalizados = dict(self.limites_personalizados)

    def _guardar_configuracion(self) -> None:
        ruta = self._ruta_configuracion()
        payload = {
            "apps_adictivas": sorted(self.apps_adictivas),
            "limites_personalizados": {str(k): int(v) for k, v in self.limites_personalizados.items()},
        }
        with ruta.open("w", encoding="utf-8") as archivo:
            json.dump(payload, archivo, ensure_ascii=False, indent=2)

    def _obtener_limites_dinamicos(self) -> tuple[int, int]:
        """Devuelve el límite diario y por app según la historia del usuario."""
        limite_diario, limite_app = calcular_limite_dinamico(
            tiempo_total_hoy=self.tiempo_acumulado_hoy,
            tiempo_por_app=self.cache_tiempos_por_app,
            paquete_actual=self.app_en_primer_plano or None,
            limite_base_segundos=int(self.limite_segundos),
            limite_base_app_segundos=int(self.limite_segundos_por_app),
            apps_adictivas=set(self.apps_adictivas),
            limites_personalizados=dict(self.limites_personalizados),
        )
        return limite_diario, limite_app

    def _cerrar_app_actual(self) -> None:
        if not self.app_en_primer_plano:
            return

        self.paquete_restringido_actual = self.app_en_primer_plano
        self.apps_bloqueadas_hoy.add(self.app_en_primer_plano)
        if hasattr(self, "etiqueta_estado"):
            self.etiqueta_estado.text = f"{self.app_en_primer_plano} alcanzó su límite y quedó bloqueada hasta mañana."
        self.estado_mascota = EstadoMascota.ENOJADO.value
        if hasattr(self, "etiqueta_mascota"):
            self.etiqueta_mascota.text = f"[ {EstadoMascota.ENOJADO.value} ]"

        try:
            from bridge.servicios_android import _obtener_actividad
            actividad = _obtener_actividad()
            if actividad is not None:
                from jnius import autoclass
                Intent = autoclass("android.content.Intent")
                intent = Intent(Intent.ACTION_MAIN)
                intent.addCategory(Intent.CATEGORY_HOME)
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                actividad.startActivity(intent)
        except Exception as exc:
            print(f"[ERROR] No se pudo devolver al launcher: {exc}")

        self._guardar_estado_diario()

    def build(self):
        self.title = "Zenchi"
        self.motor = MotorZenchi()
        self.dia_actual = date.today().isoformat()

        estado_guardado = self._cargar_estado_diario()
        self.dia_actual = estado_guardado.get("fecha", self.dia_actual)
        self.tiempo_acumulado_hoy = int(estado_guardado.get("tiempo_total", 0))
        self.cache_tiempos_por_app = {str(k): int(v) for k, v in estado_guardado.get("tiempo_por_app", {}).items()}
        self.apps_bloqueadas_hoy = set(estado_guardado.get("apps_bloqueadas", []))
        self._cargar_configuracion()

        self._reiniciar_si_nuevo_dia()

        raiz = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(15))

        self.etiqueta_estado = Label(text="Bienvenido a Zenchi", font_size=sp(16))
        raiz.add_widget(self.etiqueta_estado)

        self.etiqueta_mascota = Label(text=f"[ {self.estado_mascota} ]", font_size=sp(28))
        raiz.add_widget(self.etiqueta_mascota)

        # --- Etiqueta para mostrar app en primer plano y tiempo ---
        self.etiqueta_app_activa = Label(
            text="App activa: --",
            font_size=sp(14),
            size_hint_y=None,
            height=dp(30),
        )
        raiz.add_widget(self.etiqueta_app_activa)

        self.barra_progreso = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(20))
        raiz.add_widget(self.barra_progreso)

        botones = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(50))

        # Botón para verificar permisos UsageStats
        boton_permiso = Button(text="Verificar permiso UsageStats")
        boton_permiso.bind(on_release=self._verificar_permiso_usage_stats)
        botones.add_widget(boton_permiso)

        raiz.add_widget(botones)

        self.sesion_activa = True
        self._reiniciar_si_nuevo_dia()

        # --- Convertirse en launcher predeterminado ---
        self.boton_launcher = Button(
            text="Usar Zenchi como pantalla de inicio",
            size_hint_y=None,
            height=dp(50),
        )
        self.boton_launcher.bind(on_release=self._al_pedir_ser_launcher)
        raiz.add_widget(self.boton_launcher)

        # Cajón de apps del usuario
        self.grilla_apps = GridLayout(cols=3, spacing=dp(8), size_hint_y=None)
        self.grilla_apps.bind(minimum_height=self.grilla_apps.setter("height"))

        contenedor_scroll = ScrollView(size_hint=(1, 1))
        contenedor_scroll.add_widget(self.grilla_apps)
        raiz.add_widget(contenedor_scroll)

        self._refrescar_lista_apps()

        Clock.schedule_interval(self._actualizar, 1)

        return raiz

    def _guardar_limite_para_paquete(self, paquete: str, nombre: str, minutos: int, popup: Popup | None = None) -> None:
        if not paquete:
            return
        try:
            minutos = max(5, int(minutos))
        except (TypeError, ValueError):
            minutos = 30

        self.limites_personalizados[paquete] = minutos * 60
        self._guardar_configuracion()
        self.etiqueta_estado.text = f"Límite ajustado para {nombre}: {minutos} minutos."
        if popup is not None:
            popup.dismiss()

    def _mostrar_menu_limite_app(self, paquete: str, nombre: str) -> None:
        if not paquete:
            return

        contenedor = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(15))
        etiqueta = Label(text=f"Ajustar límite para\n{nombre}", halign="center", valign="middle")
        etiqueta.text_size = (dp(220), None)
        contenedor.add_widget(etiqueta)

        entrada = TextInput(
            text=str(max(5, int((self.limites_personalizados.get(paquete, 0) or self.limite_segundos_por_app) / 60))),
            multiline=False,
            input_filter="int",
            hint_text="Minutos",
            size_hint_y=None,
            height=dp(40),
        )
        contenedor.add_widget(entrada)

        fila_preset = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(40))
        for minutos in (10, 20, 30, 60):
            boton_preset = Button(text=f"{minutos}m")
            boton_preset.bind(on_release=lambda _btn, valor=minutos, popup=None: self._guardar_limite_para_paquete(paquete, nombre, valor, popup))
            fila_preset.add_widget(boton_preset)
        contenedor.add_widget(fila_preset)

        boton_guardar = Button(text="Guardar límite")
        boton_guardar.bind(on_release=lambda _btn: self._guardar_limite_para_paquete(paquete, nombre, entrada.text, popup))
        contenedor.add_widget(boton_guardar)

        boton_cancelar = Button(text="Cancelar")
        boton_cancelar.bind(on_release=lambda _btn: popup.dismiss())
        contenedor.add_widget(boton_cancelar)

        popup = Popup(title="Límite de la app", content=contenedor, size_hint=(0.8, 0.5), auto_dismiss=True)
        boton_guardar.bind(on_release=lambda _btn: self._guardar_limite_para_paquete(paquete, nombre, entrada.text, popup))
        boton_cancelar.bind(on_release=lambda _btn: popup.dismiss())
        for child in fila_preset.children[:]:
            child.bind(on_release=lambda _btn, valor=child.text.rstrip("m"), p=popup: self._guardar_limite_para_paquete(paquete, nombre, valor, p))
        popup.open()

    def _al_pedir_ser_launcher(self, *_args):
        print("[DEBUG] Solicitando ser launcher predeterminado...")
        solicitar_ser_launcher_predeterminado()
        # El resultado del diálogo llega de forma asíncrona (el usuario
        # tiene que confirmar), así que no sabemos el resultado al
        # instante. Revisamos el estado varias veces para capturar el cambio.
        Clock.schedule_once(self._revisar_si_ya_es_launcher, 1)
        Clock.schedule_once(self._revisar_si_ya_es_launcher, 3)
        Clock.schedule_once(self._revisar_si_ya_es_launcher, 5)

    def _revisar_si_ya_es_launcher(self, _dt):
        print("[DEBUG] Revisando si ya es launcher...")
        if es_launcher_predeterminado():
            print("[DEBUG] ¡Confirmado! Zenchi es ahora el launcher predeterminado")
            self.boton_launcher.text = "Zenchi ya es tu pantalla de inicio ✓"
            self.boton_launcher.disabled = True
            # IMPORTANTE: Forzar refresh de la lista de apps ahora que somos launcher
            # Usar Clock.schedule_once para asegurar que el cambio de rol se propagó
            Clock.schedule_once(lambda dt: self._refrescar_lista_apps(), 0.5)
        else:
            print("[DEBUG] Todavía no es launcher predeterminado")

    def _refrescar_lista_apps(self) -> None:
        """Limpia y vuelve a llenar la grilla con las apps instaladas.

        ACTUALIZACIÓN: Agregar logging para debug en Android
        """
        print("[DEBUG] Refrescando lista de apps...")
        self.grilla_apps.clear_widgets()
        apps = listar_apps_instaladas()
        print(f"[DEBUG] Apps encontradas: {len(apps)}")
        for app in apps:
            print(f"[DEBUG] App: {app.nombre} ({app.paquete})")
            boton_app = AppIconButton(
                text=app.nombre,
                size_hint_y=None,
                height=dp(70),
                paquete=app.paquete,
                nombre=app.nombre,
                abrir_callback=self._al_abrir_app,
                long_press_callback=self._mostrar_menu_limite_app,
            )
            self.grilla_apps.add_widget(boton_app)

    def _al_abrir_app(self, paquete: str, nombre: str):
        """Maneja la apertura de apps y el tracking de tiempo de uso."""
        from time import time

        self._reiniciar_si_nuevo_dia()

        limite_diario_actual, limite_app_actual = self._obtener_limites_dinamicos()
        self.limite_segundos = limite_diario_actual
        self.limite_segundos_por_app = limite_app_actual

        if paquete in self.apps_bloqueadas_hoy:
            self.etiqueta_estado.text = f"{nombre} está bloqueada hasta mañana."
            self.estado_mascota = EstadoMascota.ENOJADO.value
            self.etiqueta_mascota.text = f"[ {EstadoMascota.ENOJADO.value} ]"
            return

        # Lista blanca: Zenchi nunca se bloquea a sí mismo
        if paquete == self._obtener_paquete_zenchi():
            print(f"[DEBUG] Volviendo a Zenchi (lista blanca)")
            self.ultima_app_abierta = None
            self._tiempo_ultima_apertura = None
            self.etiqueta_estado.text = "Bienvenido a Zenchi"
            return

        if self.cache_tiempos_por_app.get(paquete, 0) >= limite_app_actual:
            self.etiqueta_estado.text = f"{nombre} ya alcanzó su límite dinámico de hoy."
            self.estado_mascota = EstadoMascota.ENOJADO.value
            self.etiqueta_mascota.text = f"[ {EstadoMascota.ENOJADO.value} ]"
            self.apps_bloqueadas_hoy.add(paquete)
            self._guardar_estado_diario()
            return

        if self.tiempo_acumulado_hoy >= limite_diario_actual:
            self.etiqueta_estado.text = "⚠️ Límite diario alcanzado. No puedes abrir más apps hoy."
            self.estado_mascota = EstadoMascota.ENOJADO.value
            self.etiqueta_mascota.text = f"[ {EstadoMascota.ENOJADO.value} ]"
            self.apps_bloqueadas_hoy.add(paquete)
            self._guardar_estado_diario()
            return

        self.ultima_app_abierta = paquete
        self._tiempo_ultima_apertura = time()
        self.etiqueta_estado.text = f"Abriendo {nombre}..."
        print(f"[DEBUG] Abriendo app: {nombre} ({paquete})")
        print(f"[DEBUG] Tiempo acumulado antes de abrir: {self.tiempo_acumulado_hoy}s")

        abrir_app(paquete)

    def _obtener_paquete_zenchi(self) -> str:
        """Obtiene el nombre del paquete de Zenchi para la lista blanca."""
        actividad = _obtener_actividad()
        if actividad is not None:
            return str(actividad.getPackageName())
        # Fallback para desktop
        return "org.test.zenchi"

    def _al_ver_uso_acumulado(self, *_args):
        """Muestra el tiempo acumulado del día."""
        minutos = self.tiempo_acumulado_hoy // 60
        segundos_restantes = self.tiempo_acumulado_hoy % 60
        limite_minutos = self.limite_segundos // 60
        self.etiqueta_estado.text = f"Uso hoy: {minutos}m {segundos_restantes}s / {limite_minutos}m"

    def _al_iniciar_sesion(self, *_args):
        self.sesion_activa = True
        self._reiniciar_si_nuevo_dia()
        self.etiqueta_estado.text = "Sesión de enfoque activa."
        print("[DEBUG] Sesión de enfoque iniciada")

    def _verificar_permiso_usage_stats(self, *_args):
        """Verifica y solicita permiso UsageStats si es necesario."""
        print("[DEBUG] Verificando permiso UsageStats...")
        self.tiene_permiso_usage_stats = obtener_permiso_usage_stats()

        if not self.tiene_permiso_usage_stats:
            print("[INFO] Solicitando permiso UsageStats al usuario")
            solicitar_permiso_usage_stats()
        else:
            print("[DEBUG] Permiso UsageStats ya concedido")

    def _actualizar_monitoreo_apps(self):
        """Actualiza el estado de la app en primer plano usando timestamps reales."""
        self._reiniciar_si_nuevo_dia()

        from time import time

        estado_app = detectar_app_en_primer_plano()

        if not estado_app.paquete_en_primer_plano:
            if self.app_en_primer_plano:
                self._finalizar_tiempo_app_actual()
                self.app_en_primer_plano = ""
            self.paquete_restringido_actual = None
            self.tiempo_app_actual = 0
            if hasattr(self, "etiqueta_app_activa"):
                self.etiqueta_app_activa.text = "App activa: --"
            return

        paquete = estado_app.paquete_en_primer_plano

        if paquete in self.apps_bloqueadas_hoy:
            self._cerrar_app_actual()
            return

        if self.app_en_primer_plano and self.app_en_primer_plano != paquete:
            self._finalizar_tiempo_app_actual()

        if self.app_en_primer_plano != paquete:
            self.app_en_primer_plano = paquete
            self._inicio_tiempo_app_actual = time()
            self.tiempo_app_actual = 0
            print(f"[DEBUG] Nueva app en primer plano: {self.app_en_primer_plano}")

        if self.app_en_primer_plano == self._obtener_paquete_zenchi():
            self._finalizar_tiempo_app_actual()
            self.app_en_primer_plano = ""
            self.tiempo_app_actual = 0
            if hasattr(self, "etiqueta_app_activa"):
                self.etiqueta_app_activa.text = "App activa: --"
            return

        tiempo_acumulado = self.cache_tiempos_por_app.get(self.app_en_primer_plano, 0)
        if self._inicio_tiempo_app_actual is not None:
            tiempo_acumulado += max(0, int(time() - self._inicio_tiempo_app_actual))

        self.cache_tiempos_por_app[self.app_en_primer_plano] = tiempo_acumulado
        self.tiempo_acumulado_hoy = sum(self.cache_tiempos_por_app.values())
        self.segundos_usados = self.tiempo_acumulado_hoy
        self._guardar_estado_diario()

        if self.cache_tiempos_por_app.get(self.app_en_primer_plano, 0) >= self.limite_segundos_por_app:
            self.apps_bloqueadas_hoy.add(self.app_en_primer_plano)
            self.paquete_restringido_actual = self.app_en_primer_plano
            self._cerrar_app_actual()
            return

        nombre_app = self.app_en_primer_plano.split('.')[-1]
        if hasattr(self, "etiqueta_app_activa"):
            self.etiqueta_app_activa.text = f"App: {nombre_app} | Tiempo: {tiempo_acumulado}s"
        self.tiempo_app_actual = tiempo_acumulado

        if tiempo_acumulado > 300:
            self.paquete_restringido_actual = self.app_en_primer_plano
            print(f"[WARNING] App {self.app_en_primer_plano} superó límite de sesión")
        else:
            self.paquete_restringido_actual = None

    def _actualizar(self, _dt):
        self._reiniciar_si_nuevo_dia()

        if self.sesion_activa:
            self._actualizar_monitoreo_apps()

        limite_diario_actual, limite_app_actual = self._obtener_limites_dinamicos()
        self.limite_segundos = limite_diario_actual
        self.limite_segundos_por_app = limite_app_actual

        uso_total = int(self.tiempo_acumulado_hoy)
        app_actual_segundos = self.cache_tiempos_por_app.get(self.app_en_primer_plano, 0)

        uso = InstantaneaUso(
            uso_total,
            int(self.limite_segundos),
            paquete_restringido=self.paquete_restringido_actual,
            segundos_usados_por_app=app_actual_segundos,
            limite_app_segundos=int(self.limite_segundos_por_app),
        )
        decision = self.motor.decidir(uso)

        self.estado_mascota = decision.estado.value
        self.etiqueta_mascota.text = f"[ {decision.estado.value} ]"
        self.barra_progreso.value = min(100, int(uso.proporcion_uso * 100))

        if decision.bloqueado:
            if decision.motivo == "reflexion_requerida":
                self.etiqueta_estado.text = "Reflexión requerida antes de continuar."
            elif decision.motivo == "limite_app_alcanzado":
                self.etiqueta_estado.text = f"{self.app_en_primer_plano} bloqueada por límite diario."
            elif self.tiempo_acumulado_hoy >= self.limite_segundos:
                self.etiqueta_estado.text = "⚠️ Límite diario alcanzado"
            else:
                self.etiqueta_estado.text = "Acceso bloqueado por la política configurada."

        self._guardar_estado_diario()


if __name__ == "__main__":
    ZenchiApp().run()
