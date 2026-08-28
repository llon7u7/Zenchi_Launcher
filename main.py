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

from kivy.config import Config; Config.set('graphics', 'width', '360'); Config.set('graphics', 'height', '740')
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView

from motor.politica import EstadoMascota, InstantaneaUso, MotorZenchi
from bridge.servicios_android import (
    abrir_app,
    es_launcher_predeterminado,
    listar_apps_instaladas,
    solicitar_ser_launcher_predeterminado,
)


class ZenchiApp(App):
    # --- Datos que la interfaz puede leer/mostrar ---
    segundos_usados = NumericProperty(0)
    limite_segundos = NumericProperty(60 * 60)       # límite diario: 1 hora
    estado_mascota = StringProperty(EstadoMascota.OCIOSO.value)
    sesion_activa = False

    def build(self):
        self.title = "Zenchi"
        self.motor = MotorZenchi()

        raiz = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(15))

        self.etiqueta_estado = Label(text="Bienvenido a Zenchi", font_size=sp(16))
        raiz.add_widget(self.etiqueta_estado)

        self.etiqueta_mascota = Label(text=f"[ {self.estado_mascota} ]", font_size=sp(28))
        raiz.add_widget(self.etiqueta_mascota)

        self.barra_progreso = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(20))
        raiz.add_widget(self.barra_progreso)

        botones = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(50))
        boton_iniciar = Button(text="Iniciar sesión de enfoque")
        boton_iniciar.bind(on_release=self._al_iniciar_sesion)
        botones.add_widget(boton_iniciar)
        raiz.add_widget(botones)

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
            boton_app = Button(
                text=app.nombre,
                size_hint_y=None,
                height=dp(70),
            )
            boton_app.bind(
                on_release=lambda _boton, paquete=app.paquete: abrir_app(paquete)
            )
            self.grilla_apps.add_widget(boton_app)

    def _al_iniciar_sesion(self, *_args):
        self.sesion_activa = True
        self.etiqueta_estado.text = "Sesión de enfoque activa."

    def _actualizar(self, _dt):
        if not self.sesion_activa:
            return

        # 1. Avanza el tiempo usado
        self.segundos_usados = min(self.segundos_usados + 1, self.limite_segundos)

        # 2. Le preguntas al MOTOR qué debe pasar
        uso = InstantaneaUso(int(self.segundos_usados), int(self.limite_segundos))
        decision = self.motor.decidir(uso)

        # 3. La interfaz solo se encarga de MOSTRAR lo que el motor decidió.
        self.estado_mascota = decision.estado.value
        self.etiqueta_mascota.text = f"[ {decision.estado.value} ]"
        self.barra_progreso.value = min(100, int(uso.proporcion_uso * 100))

        if decision.bloqueado:
            self.etiqueta_estado.text = "Acceso bloqueado por la política configurada."


if __name__ == "__main__":
    ZenchiApp().run()