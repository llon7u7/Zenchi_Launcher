from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.politica import Decision, EstadoMascota, InstantaneaUso, MotorZenchi


def crear_motor() -> MotorZenchi:
    return MotorZenchi()


def test_cero_por_ciento_esta_ocioso():
    motor = crear_motor()
    uso = InstantaneaUso(segundos_usados=0, limite_diario_segundos=3600)
    decision = motor.decidir(uso)
    assert decision.estado == EstadoMascota.OCIOSO
    assert decision.bloqueado is False


def test_ochenta_por_ciento_advierte():
    motor = crear_motor()
    uso = InstantaneaUso(segundos_usados=2880, limite_diario_segundos=3600)  # 80%
    decision = motor.decidir(uso)
    assert decision.estado == EstadoMascota.ANGUSTIADO
    assert decision.motivo == "advertencia"


def test_noventa_por_ciento_es_advertencia_fuerte():
    motor = crear_motor()
    uso = InstantaneaUso(segundos_usados=3240, limite_diario_segundos=3600)  # 90%
    decision = motor.decidir(uso)
    assert decision.estado == EstadoMascota.ANGUSTIADO
    assert decision.motivo == "advertencia_fuerte"


def test_cien_por_ciento_bloquea_y_pide_reflexion():
    motor = crear_motor()
    uso = InstantaneaUso(segundos_usados=3600, limite_diario_segundos=3600)
    decision = motor.decidir(uso)
    assert decision.estado == EstadoMascota.ENOJADO
    assert decision.bloqueado is True
    assert decision.requiere_reflexion is True


def test_reinicio_de_medianoche_vuelve_a_ocioso():
    motor = crear_motor()
    ayer = InstantaneaUso(segundos_usados=3600, limite_diario_segundos=3600)
    assert motor.decidir(ayer).bloqueado is True

    hoy = InstantaneaUso(segundos_usados=0, limite_diario_segundos=3600)
    decision = motor.decidir(hoy)
    assert decision.estado == EstadoMascota.OCIOSO


def test_paquete_restringido_bloquea_sin_importar_el_uso():
    motor = crear_motor()
    uso = InstantaneaUso(
        segundos_usados=0,
        limite_diario_segundos=3600,
        paquete_restringido="com.ejemplo.bloqueada",
    )
    decision = motor.decidir(uso)
    assert decision.bloqueado is True
    assert decision.requiere_reflexion is True


def test_reflexion_completa_ya_no_vuelve_a_pedirla():
    motor = crear_motor()
    uso = InstantaneaUso(
        segundos_usados=0,
        limite_diario_segundos=3600,
        paquete_restringido="com.ejemplo.bloqueada",
        reflexion_completa=True,
    )
    decision = motor.decidir(uso)
    assert decision.bloqueado is True
    assert decision.requiere_reflexion is False


def test_limite_de_app_bloquea_cuando_se_alcanza_el_tope():
    motor = crear_motor()
    uso = InstantaneaUso(
        segundos_usados=1800,
        limite_diario_segundos=3600,
        segundos_usados_por_app=900,
        limite_app_segundos=900,
    )
    decision = motor.decidir(uso)
    assert decision.bloqueado is True
    assert decision.requiere_reflexion is True
    assert decision.motivo == "limite_app_alcanzado"


def test_limite_de_app_no_bloquea_si_aun_queda_tiempo():
    motor = crear_motor()
    uso = InstantaneaUso(
        segundos_usados=1800,
        limite_diario_segundos=3600,
        segundos_usados_por_app=600,
        limite_app_segundos=900,
    )
    decision = motor.decidir(uso)
    assert decision.bloqueado is False
    assert decision.requiere_reflexion is False
