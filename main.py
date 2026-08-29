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
    _obtener_actividad,
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
    tiempo_acumulado_hoy = 0  # Tiempo total usado hoy (persistente)
    ultima_app_abierta = None  # Paquete de la última app abierta
    _tiempo_ultima_apertura = None  # Timestamp cuando se abrió la última app

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
            # Al abrir una app, se empieza a acumular tiempo automáticamente
            boton_app.bind(
                on_release=lambda _boton, paquete=app.paquete, nombre=app.nombre: self._al_abrir_app(paquete, nombre)
            )
            self.grilla_apps.add_widget(boton_app)

    def _al_abrir_app(self, paquete: str, nombre: str):
        """Maneja la apertura de apps y el tracking de tiempo de uso."""
        from time import time
        
        # Lista blanca: Zenchi nunca se bloquea a sí mismo
        if paquete == self._obtener_paquete_zenchi():
            print(f"[DEBUG] Volviendo a Zenchi (lista blanca)")
            # Cuando vuelves a Zenchi, calcular el tiempo usado en la app anterior
            if self.ultima_app_abierta and self._tiempo_ultima_apertura:
                tiempo_usado = int(time() - self._tiempo_ultima_apertura)
                self.tiempo_acumulado_hoy += tiempo_usado
                print(f"[DEBUG] Tiempo usado en {self.ultima_app_abierta}: {tiempo_usado}s")
                print(f"[DEBUG] Nuevo acumulado: {self.tiempo_acumulado_hoy}s")
            
            # Resetear estado
            self.ultima_app_abierta = None
            self._tiempo_ultima_apertura = None
            self.etiqueta_estado.text = "Bienvenido a Zenchi"
            return
        
        # Verificar si ya alcanzó el límite antes de permitir abrir otras apps
        if self.tiempo_acumulado_hoy >= self.limite_segundos:
            self.etiqueta_estado.text = "⚠️ Límite diario alcanzado. No puedes abrir más apps hoy."
            self.estado_mascota = EstadoMascota.ENOJADO.value
            self.etiqueta_mascota.text = f"[ {EstadoMascota.ENOJADO.value} ]"
            return
        
        # Registrar el momento de apertura y comenzar a trackear
        self.ultima_app_abierta = paquete
        self._tiempo_ultima_apertura = time()
        self.etiqueta_estado.text = f"Abriendo {nombre}..."
        print(f"[DEBUG] Abriendo app: {nombre} ({paquete})")
        print(f"[DEBUG] Tiempo acumulado antes de abrir: {self.tiempo_acumulado_hoy}s")
        
        # Abrir la app real
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

    def _actualizar(self, _dt):
        # Actualizar estado de la mascota basado en el uso acumulado
        uso = InstantaneaUso(int(self.tiempo_acumulado_hoy), int(self.limite_segundos))
        decision = self.motor.decidir(uso)
        
        self.estado_mascota = decision.estado.value
        self.etiqueta_mascota.text = f"[ {decision.estado.value} ]"
        
        # Verificar si alcanzó el límite y mostrar mensaje
        if self.tiempo_acumulado_hoy >= self.limite_segundos:
            self.etiqueta_estado.text = "⚠️ Límite diario alcanzado"


if __name__ == "__main__":
    ZenchiApp().run()