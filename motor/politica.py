"""
Motor de decisiones de Zenchi.

Este archivo NO sabe nada de pantallas, botones ni Kivy. Solo responde una
pregunta: "dado el uso actual, ¿qué debe pasar?" Tú te encargas de la
interfaz (main.py); este módulo solo te dice QUÉ mostrar, no CÓMO mostrarlo.

Separar la lógica de la interfaz es justamente lo que se espera en un buen
diseño de app: la interfaz puede cambiar por completo (colores, botones,
animaciones) sin tener que tocar ni una línea de este archivo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EstadoMascota(str, Enum):
    """Los 5 estados posibles de la mascota Zenchi.

    Úsalos en tu interfaz para decidir qué animación/color/texto mostrar,
    por ejemplo: if estado == EstadoMascota.ENOJADO: mostrar_cara_enojada()
    """
    OCIOSO = "ocioso"           # todo tranquilo, uso normal
    FELIZ = "feliz"             # logró una meta o completó una reflexión
    ANGUSTIADO = "angustiado"   # se está acercando al límite (80%+)
    ENOJADO = "enojado"         # llegó al límite o app restringida
    PENSANDO = "pensando"       # generando una reflexión (IA local)


@dataclass(frozen=True)
class InstantaneaUso:
    """Una "foto" del uso del usuario en un momento dado.

    Esto es lo que tú le pasas al motor para que decida qué hacer.
    Es inmutable (frozen=True): una vez creada, no cambia. Si el uso
    avanza, creas una InstantaneaUso nueva con los valores actualizados.
    """
    segundos_usados: int
    limite_diario_segundos: int
    paquete_restringido: str | None = None
    reflexion_completa: bool = False

    @property
    def proporcion_uso(self) -> float:
        """Qué tanto del límite diario ya se usó, como número entre 0 y 1.

        0.0 = no ha usado nada. 1.0 = ya llegó al límite. 1.3 = ya se pasó
        un 30% del límite (puede pasar si el límite se redujo a mitad de
        sesión, por ejemplo).
        """
        if self.limite_diario_segundos <= 0:
            return 1.0
        return self.segundos_usados / self.limite_diario_segundos


@dataclass(frozen=True)
class Decision:
    """Lo que el motor decidió, listo para que la interfaz lo pinte."""
    estado: EstadoMascota
    bloqueado: bool
    requiere_reflexion: bool
    motivo: str  # código corto en inglés, útil para logs/debug: no lo muestres tal cual al usuario


# Umbrales de advertencia, como constantes con nombre para no tener
# "números mágicos" sueltos en el código.
UMBRAL_ADVERTENCIA = 0.8       # a partir de aquí, la mascota se ve angustiada
UMBRAL_ADVERTENCIA_FUERTE = 0.9  # a partir de aquí, el mensaje se intensifica


class MotorZenchi:
    """El "cerebro" que toma la decisión. Sin estado propio: le das una
    InstantaneaUso y te regresa siempre la misma Decision para los mismos
    datos (fácil de probar, fácil de razonar)."""

    def decidir(self, uso: InstantaneaUso) -> Decision:
        proporcion = uso.proporcion_uso
        bloqueado = proporcion >= 1.0 or uso.paquete_restringido is not None
        requiere_reflexion = bloqueado and not uso.reflexion_completa

        if requiere_reflexion:
            return Decision(
                estado=EstadoMascota.ENOJADO,
                bloqueado=True,
                requiere_reflexion=True,
                motivo="reflexion_requerida",
            )

        if bloqueado:
            return Decision(
                estado=EstadoMascota.ENOJADO,
                bloqueado=True,
                requiere_reflexion=False,
                motivo="bloqueo_por_politica",
            )

        if proporcion >= UMBRAL_ADVERTENCIA_FUERTE:
            return Decision(
                estado=EstadoMascota.ANGUSTIADO,
                bloqueado=False,
                requiere_reflexion=False,
                motivo="advertencia_fuerte",
            )

        if proporcion >= UMBRAL_ADVERTENCIA:
            return Decision(
                estado=EstadoMascota.ANGUSTIADO,
                bloqueado=False,
                requiere_reflexion=False,
                motivo="advertencia",
            )

        return Decision(
            estado=EstadoMascota.OCIOSO,
            bloqueado=False,
            requiere_reflexion=False,
            motivo="dentro_del_limite",
        )


def demo_consola() -> None:
    """Prueba rápida sin necesidad de Kivy instalado. Corre este archivo
    directo (python motor/politica.py) para ver el motor funcionando."""
    motor = MotorZenchi()
    for proporcion in (0.35, 0.82, 0.95, 1.0):
        uso = InstantaneaUso(int(3600 * proporcion), 3600)
        decision = motor.decidir(uso)
        print(f"uso={proporcion:.0%}  estado={decision.estado.value}  bloqueado={decision.bloqueado}")


if __name__ == "__main__":
    demo_consola()
