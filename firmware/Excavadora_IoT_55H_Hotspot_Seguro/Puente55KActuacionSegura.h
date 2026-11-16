#pragma once
#include <stdint.h>
#include "Controlador55KInhibido.h"

// Candidato aislado: no utiliza GPIO ni activa motores.
// La integracion fisica requiere autorizacion posterior.
class Puente55KActuacionSegura final {
private:
    Controlador55KInhibido controlador;
    bool canalPreparado = false;

public:
    void detener() {
        controlador.detener();
    }

    void invalidarCanal() {
        detener();
        canalPreparado = false;
    }

    bool confirmarStopInicial(bool stopValidado) {
        invalidarCanal();

        if (!stopValidado) {
            return false;
        }

        canalPreparado = true;
        return true;
    }

    bool recibirMovimiento(
        uint8_t codigo,
        uint16_t duracionMs,
        uint32_t ahoraMs,
        bool firmaValida,
        bool permisoVigente
    ) {
        if (!canalPreparado ||
            !firmaValida ||
            !permisoVigente) {
            invalidarCanal();
            return false;
        }

        if (codigo == 0) {
            detener();
            return true;
        }

        if (!controlador.registrar(
                codigo, duracionMs, ahoraMs)) {
            detener();
            return false;
        }

        return true;
    }

    uint8_t obtenerMascara(
        uint32_t ahoraMs,
        bool conexionVigente,
        bool permisoVigente
    ) {
        if (!conexionVigente) {
            invalidarCanal();
            return 0;
        }

        if (!permisoVigente) {
            invalidarCanal();
            return 0;
        }

        if (!canalPreparado) {
            return 0;
        }

        controlador.actualizar(ahoraMs);
        return controlador.mascaraVirtualActiva();
    }

    bool preparado() const {
        return canalPreparado;
    }
};