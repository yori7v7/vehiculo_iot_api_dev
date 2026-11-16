#pragma once
#include <stdint.h>
#include "Puente55KActuacionSegura.h"

// Candidato aislado de actuacion.
// NO incluido en el firmware de diagnostico 55-H.
// El escritor real se conectara solamente despues de revisar
// la cadena de autorizacion y superar las pruebas supervisadas.

class Salida55KCandidata final {
public:
    typedef void (*Escritor)(uint8_t);

private:
    Puente55KActuacionSegura& puente_;
    Escritor escribir_;
    uint8_t ultima_ = 0;
    bool iniciada_ = false;

    static bool mascaraPermitida(uint8_t codigo) {
        switch (codigo) {
            case 0:
            case 1:
            case 2:
            case 4:
            case 5:
            case 6:
            case 8:
            case 9:
            case 10:
                return true;
            default:
                return false;
        }
    }

public:
    Salida55KCandidata(
        Puente55KActuacionSegura& puente,
        Escritor escritor
    ) : puente_(puente), escribir_(escritor) {}

    bool iniciar() {
        iniciada_ = false;
        puente_.invalidarCanal();
        ultima_ = 0;

        if (escribir_ == nullptr) {
            return false;
        }

        escribir_(0);
        iniciada_ = true;
        return true;
    }

    void invalidar() {
        // Neutralizar antes de cualquier otra operacion.
        if (escribir_ != nullptr) {
            escribir_(0);
        }

        ultima_ = 0;
        puente_.invalidarCanal();
    }

    uint8_t actualizar(
        uint32_t ahoraMs,
        bool conexionVigente,
        bool permisoVigente
    ) {
        if (!iniciada_ || escribir_ == nullptr) {
            invalidar();
            return 0;
        }

        const uint8_t mascara = puente_.obtenerMascara(
            ahoraMs,
            conexionVigente,
            permisoVigente
        );

        if (!mascaraPermitida(mascara)) {
            invalidar();
            return 0;
        }

        // El puente gestiona expiracion y transicion neutra.
        // El escritor debe aplicar el valor sin retrasos bloqueantes.
        if (ultima_ != mascara || mascara == 0) {
            escribir_(mascara);
            ultima_ = mascara;
        }

        return mascara;
    }

    uint8_t ultimaSalida() const {
        return ultima_;
    }
};