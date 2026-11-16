#include <stdint.h>
#include "../firmware/Excavadora_IoT_55H_Hotspot_Seguro/Salida55KCandidata.h"

#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)

static uint8_t salida = 255;
static unsigned escrituras = 0;

static void escribirSimulado(uint8_t mascara) {
    salida = mascara;
    ++escrituras;
}

int main() {
    // Sin escritor no se permite inicializar.
    Puente55KActuacionSegura vacio;
    Salida55KCandidata sinEscritor(vacio, nullptr);
    CHECK(!sinEscritor.iniciar());
    CHECK(!vacio.preparado());

    // Inicio neutro y rechazo sin STOP autenticado.
    Puente55KActuacionSegura inicial;
    Salida55KCandidata salidaInicial(inicial, escribirSimulado);

    CHECK(salidaInicial.iniciar());
    CHECK(salida == 0);
    CHECK(escrituras > 0);
    CHECK(!inicial.preparado());
    CHECK(!inicial.recibirMovimiento(1, 200, 1000, true, true));
    CHECK(salidaInicial.actualizar(1050, true, true) == 0);
    CHECK(salida == 0);

    // Las ocho direcciones permitidas.
    const uint8_t codigos[] = {1, 2, 4, 5, 6, 8, 9, 10};

    for (uint8_t codigo : codigos) {
        Puente55KActuacionSegura puente;
        Salida55KCandidata candidato(puente, escribirSimulado);

        CHECK(candidato.iniciar());
        CHECK(puente.confirmarStopInicial(true));
        CHECK(puente.recibirMovimiento(
            codigo, 100, 1000, true, true
        ));

        CHECK(candidato.actualizar(1050, true, true) == codigo);
        CHECK(salida == codigo);

        // Caducidad exacta: neutro.
        CHECK(candidato.actualizar(1100, true, true) == 0);
        CHECK(salida == 0);
    }

    // Cambio de direccion: intervalo neutro de 30 ms.
    Puente55KActuacionSegura cambio;
    Salida55KCandidata candidato(cambio, escribirSimulado);

    CHECK(candidato.iniciar());
    CHECK(cambio.confirmarStopInicial(true));
    CHECK(cambio.recibirMovimiento(1, 500, 2000, true, true));

    CHECK(candidato.actualizar(2001, true, true) == 1);
    CHECK(salida == 1);

    CHECK(cambio.recibirMovimiento(9, 500, 2010, true, true));

    CHECK(candidato.actualizar(2010, true, true) == 0);
    CHECK(salida == 0);

    CHECK(candidato.actualizar(2039, true, true) == 0);
    CHECK(candidato.actualizar(2040, true, true) == 9);
    CHECK(salida == 9);

    // Revocacion.
    CHECK(candidato.actualizar(2050, true, false) == 0);
    CHECK(salida == 0);
    CHECK(!cambio.preparado());

    // No recuperar movimiento sin nuevo STOP.
    CHECK(!cambio.recibirMovimiento(1, 200, 2060, true, true));
    CHECK(candidato.actualizar(2070, true, true) == 0);

    // Desconexion.
    CHECK(cambio.confirmarStopInicial(true));
    CHECK(cambio.recibirMovimiento(2, 200, 3000, true, true));
    CHECK(candidato.actualizar(3050, true, true) == 2);
    CHECK(candidato.actualizar(3060, false, true) == 0);
    CHECK(salida == 0);
    CHECK(!cambio.preparado());

    // Invalidacion local inmediata.
    CHECK(cambio.confirmarStopInicial(true));
    CHECK(cambio.recibirMovimiento(4, 200, 4000, true, true));
    CHECK(candidato.actualizar(4050, true, true) == 4);

    candidato.invalidar();
    CHECK(salida == 0);
    CHECK(candidato.ultimaSalida() == 0);
    CHECK(!cambio.preparado());

    return 0;
}