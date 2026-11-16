#pragma once
#include <stdint.h>
#include "Puente55KActuacionSegura.h"

// Este candidato permanece inhibido deliberadamente.
// No puede habilitar movimiento fisico accidentalmente.
#ifndef ETAPA55K_SALIDA_FISICA
#define ETAPA55K_SALIDA_FISICA 0
#endif

#if ETAPA55K_SALIDA_FISICA != 0
#error "55-K: actuacion fisica requiere revision y autorizacion."
#endif

class Salida55KProtegida final {
public:
    typedef void (*Escritor)(uint8_t);

private:
    Puente55KActuacionSegura& puente_;
    Escritor escribir_;
    bool iniciada_ = false;

public:
    Salida55KProtegida(
        Puente55KActuacionSegura& puente,
        Escritor escribir
    ) : puente_(puente), escribir_(escribir) {}

    bool iniciar() {
        puente_.invalidarCanal();

        if (escribir_ == nullptr) {
            iniciada_ = false;
            return false;
        }

        escribir_(0);
        iniciada_ = true;
        return true;
    }

    void invalidar() {
        puente_.invalidarCanal();

        if (escribir_ != nullptr) {
            escribir_(0);
        }
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

        // Obtiene la mascara autorizada y temporizada.
        const uint8_t mascara = puente_.obtenerMascara(
            ahoraMs, conexionVigente, permisoVigente
        );

        // En esta etapa no se aplica fisicamente.
        (void)mascara;
        escribir_(0);

        return 0;
    }
};