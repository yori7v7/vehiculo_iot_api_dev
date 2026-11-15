#include <cassert>
#include <cstdint>
#include "../firmware/Excavadora_IoT_55H_Hotspot_Seguro/Controlador55KInhibido.h"

int main() {
  Controlador55KInhibido m;

  const uint8_t codigos[] = {1,2,4,5,6,8,9,10};

  for (uint8_t c : codigos) {
    assert(Controlador55KInhibido::mascara(c) == c);
  }

  assert(Controlador55KInhibido::mascara(128) == 0);

  assert(m.registrar(1, 250, 100));
  assert(m.mascaraVirtualActiva() == 1);

  // Cambiar a diagonal: exigir neutro de 30 ms.
  assert(m.registrar(9, 250, 150));
  assert(m.estadoVirtual() ==
         Controlador55KInhibido::TRANSICION);

  assert(m.mascaraVirtualActiva() == 0);

  m.actualizar(179);
  assert(m.mascaraVirtualActiva() == 0);

  m.actualizar(180);
  assert(m.mascaraVirtualActiva() == 9);

  // Caducidad de la orden.
  m.actualizar(400);
  assert(m.estadoVirtual() ==
         Controlador55KInhibido::NEUTRO);

  // STOP inmediato.
  assert(m.registrar(2, 250, 500));
  m.detener();
  assert(m.mascaraVirtualActiva() == 0);

  // Orden invalida.
  assert(!m.registrar(128, 250, 800));
  assert(m.estadoVirtual() ==
         Controlador55KInhibido::NEUTRO);

  // Duracion excesiva.
  assert(!m.registrar(1, 501, 850));

  // Desbordamiento de millis().
  assert(m.registrar(4, 100, UINT32_MAX - 20));

  m.actualizar(50);
  assert(m.mascaraVirtualActiva() == 4);

  m.actualizar(80);
  assert(m.estadoVirtual() ==
         Controlador55KInhibido::NEUTRO);

  return 0;
}
