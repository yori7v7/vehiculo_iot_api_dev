#include <stdint.h>
#include "../firmware/Excavadora_IoT_55H_Hotspot_Seguro/Puente55KActuacionSegura.h"

#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)

int main() {
    Puente55KActuacionSegura inicial;

    CHECK(inicial.obtenerMascara(1000, true, true) == 0);
    CHECK(!inicial.preparado());
    CHECK(!inicial.recibirMovimiento(1, 200, 1000, true, true));
    CHECK(!inicial.confirmarStopInicial(false));
    CHECK(!inicial.preparado());

    const uint8_t direcciones[] = {1, 2, 4, 5, 6, 8, 9, 10};

    for (uint8_t codigo : direcciones) {
        Puente55KActuacionSegura p;

        CHECK(p.confirmarStopInicial(true));
        CHECK(p.recibirMovimiento(codigo, 100, 1000, true, true));
        CHECK(p.obtenerMascara(1099, true, true) == codigo);
        CHECK(p.obtenerMascara(1100, true, true) == 0);
    }

    Puente55KActuacionSegura cambio;

    CHECK(cambio.confirmarStopInicial(true));
    CHECK(cambio.recibirMovimiento(1, 500, 2000, true, true));
    CHECK(cambio.recibirMovimiento(9, 500, 2010, true, true));
    CHECK(cambio.obtenerMascara(2039, true, true) == 0);
    CHECK(cambio.obtenerMascara(2040, true, true) == 9);

    CHECK(cambio.recibirMovimiento(0, 0, 2050, true, true));
    CHECK(cambio.obtenerMascara(2050, true, true) == 0);

    Puente55KActuacionSegura firma;

    CHECK(firma.confirmarStopInicial(true));
    CHECK(firma.recibirMovimiento(1, 200, 1000, true, true));
    CHECK(!firma.recibirMovimiento(9, 200, 1010, false, true));
    CHECK(!firma.preparado());
    CHECK(firma.obtenerMascara(1020, true, true) == 0);
    CHECK(!firma.recibirMovimiento(1, 200, 1030, true, true));

    Puente55KActuacionSegura permiso;

    CHECK(permiso.confirmarStopInicial(true));
    CHECK(permiso.recibirMovimiento(2, 200, 1000, true, true));
    CHECK(permiso.obtenerMascara(1050, true, false) == 0);
    CHECK(!permiso.preparado());
    CHECK(!permiso.recibirMovimiento(2, 200, 1060, true, true));

    Puente55KActuacionSegura conexion;

    CHECK(conexion.confirmarStopInicial(true));
    CHECK(conexion.recibirMovimiento(4, 200, 1000, true, true));
    CHECK(conexion.obtenerMascara(1050, false, true) == 0);
    CHECK(!conexion.preparado());

    Puente55KActuacionSegura invalido;

    CHECK(invalido.confirmarStopInicial(true));
    CHECK(!invalido.recibirMovimiento(128, 200, 1000, true, true));
    CHECK(invalido.obtenerMascara(1000, true, true) == 0);

    Puente55KActuacionSegura plazo;

    CHECK(plazo.confirmarStopInicial(true));
    CHECK(!plazo.recibirMovimiento(1, 501, 1000, true, true));
    CHECK(plazo.obtenerMascara(1000, true, true) == 0);

    return 0;
}