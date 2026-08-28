"""

Punto de entrada de la app Zenchi.

Este archivo conecta el MOTOR (motor/politica.py, ya resuelto) con Kivy.
La parte de INTERFAZ (colores, layout, animaciones, estilo) es tu trabajo
para la materia: busca los comentarios "TODO INTERFAZ" para saber dónde
puedes empezar a construir y experimentar.
"""
"""
Punto de entrada de la app Zenchi.

Este archivo conecta el MOTOR (motor/politica.py, ya resuelto) con Kivy.
La parte de INTERFAZ (colores, layout, animaciones, estilo) es tu trabajo
para la materia: busca los comentarios "TODO INTERFAZ" para saber dónde
puedes empezar a construir y experimentar.
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
    segundos_usados = NumericProperty(26 * 60)      # 26 minutos, de ejemplo
    limite_segundos = NumericProperty(60 * 60)       # límite diario: 1 hora
    estado_mascota = StringProperty(EstadoMascota.OCIOSO.value)
    sesion_activa = False

    def build(self):
        self.title = "Zenchi"
        self.motor = MotorZenchi()  # <- aquí vive toda la lógica, ya resuelta

        # TODO INTERFAZ: esta es la pantalla raíz. Aquí decides si usas
        # BoxLayout, GridLayout, FloatLayout, o si mueves todo esto a un
        # archivo .kv (recomendado más adelante para separar diseño de código).
        #
        # IMPORTANTE: usa siempre dp() para tamaños/espaciados y sp() para
        # font_size. Un número "pelón" (ej. padding=20) es píxeles físicos
        # fijos, que se ven distinto en cada pantalla según su densidad —
        # eso es lo que causaba que se viera encimado en tu teléfono.
        raiz = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(15))

        self.etiqueta_estado = Label(text="Zenchi está listo.", font_size=sp(16))
        raiz.add_widget(self.etiqueta_estado)

        # TODO INTERFAZ: reemplaza este texto por tu propio "personaje"
        # (imagen, animación, dibujo con canvas, lo que decidas).
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
        # No es un permiso normal (como cámara o ubicación): Android lo
        # maneja como un "rol". El usuario debe confirmar explícitamente
        # en un diálogo del sistema; nuestra app solo puede pedirlo.
        self.boton_launcher = Button(
            text="Usar Zenchi como pantalla de inicio",
            size_hint_y=None,
            height=dp(50),
        )
        self.boton_launcher.bind(on_release=self._al_pedir_ser_launcher)
        raiz.add_widget(self.boton_launcher)

        # TODO INTERFAZ: esta es la zona donde aparecen las apps del
        # usuario (el "cajón de apps"). Por ahora es una grilla simple de
        # botones con texto; puedes reemplazarla por íconos, categorías,
        # buscador, etc. Los datos ya vienen resueltos desde bridge/.
        self.grilla_apps = GridLayout(cols=3, spacing=dp(8), size_hint_y=None)
        self.grilla_apps.bind(minimum_height=self.grilla_apps.setter("height"))

        contenedor_scroll = ScrollView(size_hint=(1, 1))
        contenedor_scroll.add_widget(self.grilla_apps)
        raiz.add_widget(contenedor_scroll)

        self._refrescar_lista_apps()

        # El "reloj" de Kivy: llama a _actualizar cada 1 segundo mientras
        # la app está abierta. Aquí es donde el tiempo "avanza".
        Clock.schedule_interval(self._actualizar, 1)

        return raiz

    def _al_pedir_ser_launcher(self, *_args):
        solicitar_ser_launcher_predeterminado()
        # El resultado del diálogo llega de forma asíncrona (el usuario
        # tiene que confirmar), así que no sabemos el resultado al
        # instante. Revisamos el estado un par de segundos después.
        Clock.schedule_once(self._revisar_si_ya_es_launcher, 2)

    def _revisar_si_ya_es_launcher(self, _dt):
        if es_launcher_predeterminado():
            self.boton_launcher.text = "Zenchi ya es tu pantalla de inicio ✓"
            self.boton_launcher.disabled = True

    def _refrescar_lista_apps(self) -> None:
        """Limpia y vuelve a llenar la grilla con las apps instaladas."""
        self.grilla_apps.clear_widgets()
        for app in listar_apps_instaladas():
            # TODO INTERFAZ: aquí podrías usar el ícono real de la app en
            # vez de solo texto (más adelante, cuando quieras esa mejora).
            boton_app = Button(
                text=app.nombre,
                size_hint_y=None,
                height=dp(70),
            )
            # OJO con los lambdas dentro de un for: hay que "capturar" el
            # valor de app.paquete con un valor por defecto (paquete=...),
            # si no, todos los botones terminan abriendo la ÚLTIMA app.
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

        # 2. Le preguntas al MOTOR qué debe pasar (tú nunca decides esto
        #    a mano en la interfaz; siempre le preguntas al motor)
        uso = InstantaneaUso(int(self.segundos_usados), int(self.limite_segundos))
        decision = self.motor.decidir(uso)

        # 3. La interfaz solo se encarga de MOSTRAR lo que el motor decidió.
        #    TODO INTERFAZ: aquí es donde puedes lucirte -- cambiar colores,
        #    animaciones o imágenes según decision.estado.
        self.estado_mascota = decision.estado.value
        self.etiqueta_mascota.text = f"[ {decision.estado.value} ]"
        self.barra_progreso.value = min(100, int(uso.proporcion_uso * 100))

        if decision.bloqueado:
            self.etiqueta_estado.text = "Acceso bloqueado por la política configurada."


if __name__ == "__main__":
    ZenchiApp().run()