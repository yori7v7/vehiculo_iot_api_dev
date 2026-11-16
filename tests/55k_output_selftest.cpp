#include <stdint.h>
#include "../firmware/Excavadora_IoT_55H_Hotspot_Seguro/Salida55KProtegida.h"

static uint8_t salida = 255;
static unsigned escrituras = 0;

static void escribir(uint8_t valor) {
    salida = valor;
    ++escrituras;
}

#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)

int main() {
    Puente55KActuacionSegura puente;
    Salida55KProtegida adaptador(puente, escribir);

    CHECK(adaptador.iniciar());
    CHECK(salida == 0);
    CHECK(escrituras > 0);
    CHECK(!puente.preparado());

    CHECK(puente.confirmarStopInicial(true));

    const uint8_t codigos[] = {1, 2, 4, 5, 6, 8, 9, 10};

    for (uint8_t codigo : codigos) {
        CHECK(puente.recibirMovimiento(
            codigo, 100, 1000, true, true
        ));
        CHECK(adaptador.actualizar(1050, true, true) == 0);
        CHECK(salida == 0);
        puente.detener();
    }

    CHECK(puente.recibirMovimiento(9, 200, 2000, true, true));
    CHECK(adaptador.actualizar(2050, true, false) == 0);
    CHECK(!puente.preparado());
    CHECK(salida == 0);

    CHECK(puente.confirmarStopInicial(true));
    CHECK(puente.recibirMovimiento(1, 200, 3000, true, true));
    CHECK(adaptador.actualizar(3050, false, true) == 0);
    CHECK(!puente.preparado());
    CHECK(salida == 0);

    adaptador.invalidar();
    CHECK(salida == 0);

    return 0;
}