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


  // 55-K: todas las direcciones caducan exactamente al plazo.
  for (uint8_t codigo : codigos) {
    Controlador55KInhibido prueba;
    assert(prueba.estadoVirtual() ==
           Controlador55KInhibido::NEUTRO);
    assert(prueba.mascaraVirtualActiva() == 0);

    assert(prueba.registrar(codigo, 100, 1000));
    assert(prueba.mascaraVirtualActiva() == codigo);

    prueba.actualizar(1099);
    assert(prueba.mascaraVirtualActiva() == codigo);

    prueba.actualizar(1100);
    assert(prueba.mascaraVirtualActiva() == 0);
    assert(prueba.estadoVirtual() ==
           Controlador55KInhibido::NEUTRO);
  }

  // STOP durante la ventana neutral de 30 ms.
  Controlador55KInhibido paradaTransicion;
  assert(paradaTransicion.registrar(1, 500, 2000));
  assert(paradaTransicion.registrar(9, 500, 2010));
  assert(paradaTransicion.estadoVirtual() ==
         Controlador55KInhibido::TRANSICION);

  paradaTransicion.detener();
  paradaTransicion.actualizar(2100);

  assert(paradaTransicion.estadoVirtual() ==
         Controlador55KInhibido::NEUTRO);
  assert(paradaTransicion.mascaraVirtualActiva() == 0);

  // Una orden invalida neutraliza un estado previo.
  Controlador55KInhibido ordenInvalida;
  assert(ordenInvalida.registrar(1, 250, 3000));
  assert(!ordenInvalida.registrar(16, 250, 3010));
  assert(ordenInvalida.mascaraVirtualActiva() == 0);

  // Limites exactos de duracion.
  Controlador55KInhibido limites;
  assert(!limites.registrar(2, 99, 4000));
  assert(limites.registrar(2, 100, 4100));
  limites.actualizar(4200);
  assert(limites.mascaraVirtualActiva() == 0);

  assert(limites.registrar(6, 500, 4300));
  limites.actualizar(4799);
  assert(limites.mascaraVirtualActiva() == 6);
  limites.actualizar(4800);
  assert(limites.mascaraVirtualActiva() == 0);

  // Orden reiterada: nunca queda activa indefinidamente.
  Controlador55KInhibido reiterada;
  assert(reiterada.registrar(2, 100, 5000));
  assert(reiterada.registrar(2, 100, 5050));
  reiterada.actualizar(5100);
  assert(reiterada.mascaraVirtualActiva() == 2);
  reiterada.actualizar(5150);
  assert(reiterada.mascaraVirtualActiva() == 0);

  // Cambios de direccion: 30 ms completos en neutro.
  Controlador55KInhibido cambios;
  assert(cambios.registrar(1, 500, 6000));
  assert(cambios.registrar(9, 500, 6010));
  assert(cambios.registrar(6, 500, 6020));

  cambios.actualizar(6049);
  assert(cambios.mascaraVirtualActiva() == 0);

  cambios.actualizar(6050);
  assert(cambios.mascaraVirtualActiva() == 6);

  cambios.detener();
  assert(cambios.mascaraVirtualActiva() == 0);

  return 0;
}
