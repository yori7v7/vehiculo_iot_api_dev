#pragma once
#include <stdint.h>

// 55-K: modelo virtual. NO controla GPIO ni motores.
// No demuestra movimiento ni parada fisica.
class Controlador55KInhibido final {
public:
  enum Estado : uint8_t {
    NEUTRO = 0,
    TRANSICION = 1,
    VIRTUAL = 2
  };

  static constexpr uint32_t INTERVALO_NEUTRO_MS = 30UL;

  static uint8_t mascara(uint8_t codigo) {
    switch (codigo) {
      case 1: case 2: case 4: case 5:
      case 6: case 8: case 9: case 10:
        return codigo;
      default:
        return 0;
    }
  }

  void detener() {
    estado_ = NEUTRO;
    activa_ = 0;
    proxima_ = 0;
    habilitarDespues_ = 0;
    caduca_ = 0;
  }

  bool registrar(uint8_t codigo,
                 uint16_t duracionMs,
                 uint32_t ahoraMs) {
    const uint8_t deseada = mascara(codigo);

    if (deseada == 0 ||
        duracionMs < 100 ||
        duracionMs > 500) {
      detener();
      return false;
    }

    actualizar(ahoraMs);

    if (estado_ == VIRTUAL && activa_ != deseada) {
      activa_ = 0;
      proxima_ = deseada;
      habilitarDespues_ = ahoraMs + INTERVALO_NEUTRO_MS;
      estado_ = TRANSICION;
    } else if (estado_ == TRANSICION) {
      proxima_ = deseada;
      habilitarDespues_ = ahoraMs + INTERVALO_NEUTRO_MS;
    } else {
      activa_ = deseada;
      proxima_ = 0;
      estado_ = VIRTUAL;
    }

    caduca_ = ahoraMs + duracionMs;
    return true;
  }

  void actualizar(uint32_t ahoraMs) {
    if (estado_ == NEUTRO) return;

    if (static_cast<int32_t>(ahoraMs - caduca_) >= 0) {
      detener();
      return;
    }

    if (estado_ == TRANSICION &&
        static_cast<int32_t>(
          ahoraMs - habilitarDespues_) >= 0) {
      activa_ = proxima_;
      proxima_ = 0;
      estado_ = VIRTUAL;
    }
  }

  Estado estadoVirtual() const {
    return estado_;
  }

  uint8_t mascaraVirtualActiva() const {
    return activa_;
  }

private:
  Estado estado_ = NEUTRO;
  uint8_t activa_ = 0;
  uint8_t proxima_ = 0;
  uint32_t habilitarDespues_ = 0;
  uint32_t caduca_ = 0;
};
