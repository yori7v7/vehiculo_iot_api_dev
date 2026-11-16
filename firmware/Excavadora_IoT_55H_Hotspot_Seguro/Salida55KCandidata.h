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
    uint8_t auxiliar_ = 0;
    uint32_t auxiliarDesde_ = 0;
    uint32_t auxiliarHasta_ = 0;

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
        auxiliar_ = 0;
        auxiliarDesde_ = 0;
        auxiliarHasta_ = 0;

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
        auxiliar_ = 0;
        auxiliarDesde_ = 0;
        auxiliarHasta_ = 0;
        puente_.invalidarCanal();
    }

    // Pulsos auxiliares: luces, velocidad y claxon.
    // DEMO_ORIGINAL=64 permanece excluida porque su movimiento
    // autonomo no se cancela necesariamente liberando el 74HC595.
    bool registrarAuxiliar(
        uint8_t codigo,
        uint16_t duracionMs,
        uint32_t ahoraMs,
        bool firmaValida,
        bool permisoVigente,
        bool funcionAutorizada,
        bool conexionVigente
    ) {
        const bool codigoAuxiliar =
            codigo == 16 || codigo == 32 || codigo == 128;

        if (!iniciada_ || escribir_ == nullptr ||
            !puente_.preparado() ||
            !firmaValida || !permisoVigente ||
            !funcionAutorizada || !conexionVigente ||
            !codigoAuxiliar ||
            duracionMs < 100 || duracionMs > 300) {
            invalidar();
            return false;
        }

        // Se neutraliza cualquier direccion previa.
        // Ningun accesorio comparte mascara con un movimiento.
        puente_.detener();
        escribir_(0);
        ultima_ = 0;

        auxiliar_ = codigo;
        auxiliarDesde_ = ahoraMs + 30UL;
        auxiliarHasta_ = ahoraMs + duracionMs;
        return true;
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

        if (!conexionVigente || !permisoVigente ||
            !puente_.preparado()) {
            invalidar();
            return 0;
        }

        if (auxiliar_ != 0) {
            // Dos acciones simultaneas son un fallo cerrado.
            if (mascara != 0) {
                invalidar();
                return 0;
            }

            uint8_t deseada = 0;

            if (static_cast<int32_t>(
                    ahoraMs - auxiliarHasta_) >= 0) {
                auxiliar_ = 0;
            } else if (static_cast<int32_t>(
                    ahoraMs - auxiliarDesde_) >= 0) {
                deseada = auxiliar_;
            }

            if (ultima_ != deseada || deseada == 0) {
                escribir_(deseada);
                ultima_ = deseada;
            }

            return deseada;
        }

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