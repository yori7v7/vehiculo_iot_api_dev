// ESP8266 55-H HOTSPOT - SOLO DIAGNOSTICO / PROHIBIDA ACTUACION
// Basado en el handshake HMAC + WSS 55-H; no se habilitan motores.
#include <ESP8266WiFi.h>
#include <WiFiClientSecureBearSSL.h>
#include <WiFiManager.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include <sys/time.h>
#include <bearssl/bearssl.h>
#include "config_55h_local.h"
#include "Controlador55KInhibido.h"
#include "Puente55KActuacionSegura.h"
#include "Salida55KProtegida.h"

#ifndef LAB55H_CONFIG_VALID
#error "Crear config_55h_local.h privado antes de compilar."
#endif
#if LAB55H_CONFIG_VALID != 1
#error "Configuracion de laboratorio invalida."
#endif
#define ETAPA54_DIAGNOSTICO_SEGURO 1
#if ETAPA54_DIAGNOSTICO_SEGURO != 1
#error "55-H no permite habilitar el actuador."
#endif

static constexpr uint8_t DATA_PIN = D5;
static constexpr uint8_t CLOCK_PIN = D6;
static constexpr uint8_t LATCH_PIN = D7;
static constexpr uint8_t RESET_WIFI_PIN = D2;
static const time_t EPOCH_MIN_VALIDO = 1735689600;

// SIN API DE MOVIMIENTO FISICO: UNICA ESCRITURA POSIBLE ES CERO.
class GruaRC {
  Controlador55KInhibido sombra55K;
  Puente55KActuacionSegura puente55K;
  Salida55KProtegida salida55K{puente55K, &GruaRC::enviarCero};
  uint8_t ultimaMascaraVirtual = 0;
  static void enviarCero(uint8_t valorIgnorado = 0) {
    (void)valorIgnorado;
    digitalWrite(LATCH_PIN, LOW);
    shiftOut(DATA_PIN, CLOCK_PIN, MSBFIRST, uint8_t(0));
    digitalWrite(LATCH_PIN, HIGH);
  }
public:
  static uint8_t mascaraVirtual(uint8_t codigo) {
    switch (codigo) {
      case 0: return 0;
      case 1: return B00000001; // Q0 AVANZAR
      case 2: return B00000010; // Q1 RETROCEDER
      case 4: return B00000100; // Q2 IZQUIERDA
      case 5: return B00000101; // AVANZAR IZQUIERDA
      case 6: return B00000110; // RETROCEDER IZQUIERDA
      case 8: return B00001000; // Q3 DERECHA
      case 9: return B00001001; // AVANZAR DERECHA
      case 10: return B00001010; // RETROCEDER DERECHA
      default: return 0;
    }
  }
  void iniciar() {
    pinMode(DATA_PIN, OUTPUT);
    pinMode(CLOCK_PIN, OUTPUT);
    pinMode(LATCH_PIN, OUTPUT);
    digitalWrite(DATA_PIN, LOW);
    digitalWrite(CLOCK_PIN, LOW);
    digitalWrite(LATCH_PIN, LOW);
    enviarCero();
    delay(30);
    enviarCero();
    if (!salida55K.iniciar()) {
      enviarCero();
      Serial.println(F("[55-K] NO-GO: adaptador no iniciado."));
      return;
    }
    Serial.println(F("[55-H] 74HC595 SOLO CERO; PC817 inhibidos."));
  }
  bool registrarSombra55K(uint8_t codigo, uint16_t duracionMs) {
    return sombra55K.registrar(codigo, duracionMs, millis());
  }
  void actualizarSombra55K() {
    sombra55K.actualizar(millis());
  }
  void actualizarPuente55K(bool sesionAutenticada) {
    // Modo virtual: la autenticacion NO sustituye un permiso K-V fisico.
    // El adaptador descarta toda mascara y escribe exclusivamente cero.
    (void)salida55K.actualizar(
      millis(), sesionAutenticada, sesionAutenticada);
  }
  bool confirmarStopInicialPuente55K(bool stopValidado) {
    return puente55K.confirmarStopInicial(stopValidado);
  }
  bool registrarPuente55K(uint8_t codigo, uint16_t duracionMs,
                          bool firmaValidada, bool ordenAdmitida) {
    return puente55K.recibirMovimiento(
      codigo, duracionMs, millis(), firmaValidada, ordenAdmitida);
  }
  void registrarDireccionVirtual(uint8_t codigo) {
    ultimaMascaraVirtual = mascaraVirtual(codigo);
    enviarCero();
    Serial.printf("[55-H VIRTUAL] Codigo %u, mascara teorica %u, salidas=0\n",
                  unsigned(codigo), unsigned(ultimaMascaraVirtual));
  }
  void paradaSeguridadSilenciosa() {
    sombra55K.detener();
    salida55K.invalidar();
    ultimaMascaraVirtual = 0;
    enviarCero();
  }
  void paradaSeguridad() {
    paradaSeguridadSilenciosa();
    Serial.println(F("[55-H] PARADA VIRTUAL. 74HC595=0."));
  }
};
GruaRC grua;

// Las credenciales del hotspot se introducen por WiFiManager a traves
// de la laptop u otro dispositivo: no existe WiFi.begin con clave hardcodeada.
class GestorHotspot {
  WiFiManager portal;
  String nombreAp;
  bool pulsando = false;
  uint32_t inicioPulso = 0;
public:
  void iniciar() {
    pinMode(RESET_WIFI_PIN, INPUT_PULLUP);
    WiFi.mode(WIFI_STA);
    if (strlen(LAB55H_AP_PASSWORD) < 8 || strlen(LAB55H_AP_PASSWORD) > 63) {
      Serial.println(F("[55-H] Clave del portal invalida; WiFi NO iniciado."));
      return;
    }
    char sufijo[10];
    snprintf(sufijo, sizeof(sufijo), "%06X", ESP.getChipId());
    nombreAp = String("EXCAVADORA-") + sufijo;
    portal.setConfigPortalBlocking(false);
    portal.setWiFiAutoReconnect(true);
    portal.setConnectTimeout(20);
    portal.setRemoveDuplicateAPs(true);
    portal.setHostname(nombreAp.c_str());
    Serial.printf("[WiFiManager] AP de configuracion: %s\n", nombreAp.c_str());
    Serial.println(F("[WiFiManager] 192.168.4.1; hotspot 2.4 GHz"));
    portal.autoConnect(nombreAp.c_str(), LAB55H_AP_PASSWORD);
  }
  void limpiarCredenciales() {
    grua.paradaSeguridad();
    portal.resetSettings();
    delay(100);
    ESP.restart();
  }
  void actualizar() {
    portal.process();
    bool pulsado = digitalRead(RESET_WIFI_PIN) == LOW;
    if (!pulsado) { pulsando = false; return; }
    if (!pulsando) { pulsando = true; inicioPulso = millis(); }
    if (millis() - inicioPulso >= 5000UL) limpiarCredenciales();
  }
};
GestorHotspot hotspot;

// Bloque de autenticacion HMAC/TLS del experimento 55-H original.
class Diagnostico55H {
private:
  WebSocketsClient ws;
  bool started = false;
  bool authenticated = false;
  bool handshakeStarted = false;
  bool finished = false;
  bool pending = false;
  uint32_t activeUntil = 0;
  unsigned long wifiCheck = 0;
  uint8_t challengeBytes[32] = {};
  uint8_t bootBytes[16] = {};
  uint8_t nonceBytes[16] = {};
  uint8_t binding[84] = {};
  uint8_t sessionBytes[16] = {};
  uint8_t commandKey[32] = {};
  uint8_t telemetryKey[32] = {};
  uint8_t pendingPacket[68] = {};
  uint32_t lastGeneration = 0;
  uint32_t lastEpoch = 0;
  uint32_t lastSeq = 0;

  static void put32(uint8_t* dest, uint32_t value) {
    dest[0] = uint8_t(value >> 24);
    dest[1] = uint8_t(value >> 16);
    dest[2] = uint8_t(value >> 8);
    dest[3] = uint8_t(value);
  }
  static void put64(uint8_t* dest, uint64_t value) {
    for (int i = 7; i >= 0; --i) {
      dest[i] = uint8_t(value);
      value >>= 8;
    }
  }
  static uint32_t read32(const uint8_t* p) {
    return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | uint32_t(p[3]);
  }
  static uint64_t read64(const uint8_t* p) {
    uint64_t n = 0;
    for (uint8_t i = 0; i < 8; ++i) n = (n << 8) | p[i];
    return n;
  }
  static uint64_t utcMs() {
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    return uint64_t(tv.tv_sec) * 1000ULL + uint64_t(tv.tv_usec / 1000);
  }
  static void sign(const uint8_t* key, const char* domain,
                   const uint8_t* data, size_t len, uint8_t out[32]) {
    br_hmac_key_context kc;
    br_hmac_context hc;
    br_hmac_key_init(&kc, &br_sha256_vtable, key, 32);
    br_hmac_init(&hc, &kc, 32);
    br_hmac_update(&hc, domain, strlen(domain));
    br_hmac_update(&hc, data, len);
    br_hmac_out(&hc, out);
  }
  static bool constantEqual(const uint8_t* a, const uint8_t* b, size_t n) {
    uint8_t diff = 0;
    for (size_t i = 0; i < n; ++i) diff |= a[i] ^ b[i];
    return diff == 0;
  }
  static bool hexDecode64(const char* txt, uint8_t out[32]) {
    if (txt == nullptr || strlen(txt) != 64) return false;
    for (int i = 0; i < 32; ++i) {
      int first = hexNibble(txt[2*i]);
      int second = hexNibble(txt[2*i+1]);
      if (first < 0 || second < 0) return false;
      out[i] = uint8_t((first << 4) | second);
    }
    return true;
  }
  static int hexNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
  }
  static String hexOf(const uint8_t* raw, size_t n) {
    static const char d[] = "0123456789abcdef";
    String output;
    output.reserve(n * 2);
    for (size_t i = 0; i < n; ++i) {
      output += d[raw[i] >> 4];
      output += d[raw[i] & 15];
    }
    return output;
  }
  static int base64Value(char c) {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '-') return 62;
    if (c == '_') return 63;
    return -1;
  }
  static bool fromBase64(const char* text, uint8_t* out, size_t expected) {
    if (text == nullptr || strlen(text) != ((expected * 8 + 5) / 6)) return false;
    uint32_t accumulator = 0;
    uint8_t bits = 0;
    size_t index = 0;
    for (size_t i = 0; text[i]; ++i) {
      int val = base64Value(text[i]);
      if (val < 0) return false;
      accumulator = (accumulator << 6) | uint32_t(val);
      bits += 6;
      if (bits >= 8) {
        bits -= 8;
        if (index >= expected) return false;
        out[index++] = uint8_t((accumulator >> bits) & 0xff);
      }
    }
    return index == expected && ((accumulator & ((1U << bits) - 1U)) == 0);
  }
  static String toBase64(const uint8_t* bytes, size_t n) {
    static const char chars[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    String result;
    result.reserve((n * 8 + 5) / 6);
    uint32_t accum = 0;
    uint8_t bits = 0;
    for (size_t i = 0; i < n; ++i) {
      accum = (accum << 8) | bytes[i];
      bits += 8;
      while (bits >= 6) {
        bits -= 6;
        result += chars[(accum >> bits) & 63];
      }
    }
    if (bits) result += chars[(accum << (6 - bits)) & 63];
    return result;
  }
  static bool codeAllowed(uint8_t code) {
    switch (code) {
      case 0: case 1: case 2: case 4: case 5:
      case 6: case 8: case 9: case 10: return true;
      default: return false;
    }
  }

  void failClosed(const __FlashStringHelper* message) {
    authenticated = false;
    handshakeStarted = false;
    pending = false;
    grua.paradaSeguridad();  // Solo escribe cero por el bloqueo de diagnóstico.
    Serial.print(F("[55-H] SESION RECHAZADA; PC817 NEUTRO: "));
    Serial.println(message);
    ws.disconnect();
  }

  // Revision 55-H: caducidad del movimiento VIRTUAL por reloj monotónico.
  // Se llama antes de procesar cada nuevo evento WSS y en cada iteracion
  // del loop: un paquete recibido tarde no conserva una orden virtual vieja.
  // No es watchdog hardware y NUNCA habilita el 74HC595.
  void caducarPendienteVirtual() {
    grua.actualizarSombra55K();
    grua.actualizarPuente55K(authenticated);
    if (!pending || (int32_t)(millis() - activeUntil) < 0) return;
    pending = false;
    grua.paradaSeguridadSilenciosa();
    if (authenticated) ack(pendingPacket, 2);
    Serial.println(F("[55-H] Plazo vencido: NEUTRO VIRTUAL. NO ES PARADA FISICA."));
  }

  void sendJson(JsonDocument& data) {
    String output;
    serializeJson(data, output);
    ws.sendTXT(output);
  }

  void challenge(JsonDocument& doc) {
    if (handshakeStarted || authenticated ||
        strcmp(doc["tipo"] | "", "desafio_dispositivo_lab") != 0 ||
        doc["version"].as<int>() != 1 || doc["vehiculo"].as<int>() != 1 ||
        doc["simulado"].as<bool>() != true ||
        !fromBase64(doc["desafio"] | "", challengeBytes, sizeof(challengeBytes))) {
      failClosed(F("Desafio invalido"));
      return;
    }
    handshakeStarted = true;
    ESP.random(nonceBytes, sizeof(nonceBytes));
    // Identidad del arranque y nonce de dispositivo, ambos aleatorios.
    put32(binding, 1);
    memcpy(binding+4, challengeBytes, 32);
    memcpy(binding+36, bootBytes, 16);
    memcpy(binding+52, nonceBytes, 16);
    uint8_t proof[32];
    sign(LAB55H_DEVICE_KEY, "vehiculo-iot|lab-device-auth|v1|", binding, 68, proof);
    JsonDocument out;
    out["tipo"] = "autenticar_dispositivo_lab";
    out["version"] = 1;
    out["vehiculo"] = 1;
    out["arranque"] = toBase64(bootBytes, 16);
    out["nonce_dispositivo"] = toBase64(nonceBytes, 16);
    out["prueba"] = hexOf(proof, 32);
    out["simulado"] = true;
    sendJson(out);
    Serial.println(F("[55-H] Desafio recibido; HMAC de dispositivo enviado."));
  }

  void confirmation(JsonDocument& doc) {
    uint8_t proofGot[32], proofWant[32];
    if (!handshakeStarted || authenticated ||
        strcmp(doc["tipo"] | "", "dispositivo_autenticado_lab") != 0 ||
        doc["version"].as<int>() != 1 || doc["vehiculo"].as<int>() != 1 ||
        doc["simulado"].as<bool>() != true ||
        !fromBase64(doc["sesion"] | "", sessionBytes, 16) ||
        !hexDecode64(doc["prueba_servidor"] | "", proofGot)) {
      failClosed(F("Respuesta de autenticacion invalida"));
      return;
    }
    memcpy(binding+68, sessionBytes, 16);
    sign(LAB55H_DEVICE_KEY, "vehiculo-iot|lab-device-server|v1|", binding, 84, proofWant);
    if (!constantEqual(proofGot, proofWant, 32)) {
      failClosed(F("Servidor no autenticado"));
      return;
    }
    sign(LAB55H_DEVICE_KEY, "vehiculo-iot|lab-device-tx|v1|", binding, 84, commandKey);
    sign(LAB55H_DEVICE_KEY, "vehiculo-iot|lab-device-rx|v1|", binding, 84, telemetryKey);
    authenticated = true;
    lastGeneration = 0;
    lastEpoch = 0;
    lastSeq = 0;
    pending = false;
    Serial.println(F("[55-H] TLS + autenticacion mutua HMAC: OK"));
  }

  void ack(const uint8_t raw[68], uint8_t phase) {
    if (!authenticated) return;
    uint8_t packet[59] = {};
    packet[0] = 1;
    memcpy(packet + 1, raw + 1, 48);
    put64(packet + 49, utcMs());
    packet[57] = phase;
    packet[58] = (phase == 2 ? 1 : 0);
    uint8_t signature[32];
    sign(telemetryKey, "vehiculo-iot|device-order-ack-v1|", packet, 59, signature);
    JsonDocument out;
    out["tipo"] = "acuse_dispositivo_v1";
    out["sesion"] = toBase64(sessionBytes, 16);
    out["paquete"] = toBase64(packet, 59);
    out["firma"] = hexOf(signature, 32);
    sendJson(out);
  }

  void order(JsonDocument& doc) {
    uint8_t raw[68], signature[32], expected[32];
    uint8_t headerSession[16];
    const char* session = doc["sesion"] | "";
    if (!authenticated ||
        strcmp(doc["tipo"] | "", "orden_dispositivo_v1") != 0 ||
        !fromBase64(session, headerSession, 16) ||
        !constantEqual(headerSession, sessionBytes, 16) ||
        !fromBase64(doc["paquete"] | "", raw, 68) ||
        !hexDecode64(doc["firma"] | "", signature)) {
      failClosed(F("Formato orden invalido"));
      return;
    }
    sign(commandKey, "vehiculo-iot|device-order-v1|", raw, 68, expected);
    if (!constantEqual(signature, expected, 32) || raw[0] != 1 || read32(raw + 1) != 1 ||
        !constantEqual(raw + 5, sessionBytes, 16)) {
      failClosed(F("HMAC de orden, vehiculo o sesion incorrectos"));
      return;
    }
    const uint32_t generation = read32(raw + 37);
    const uint32_t epoch = read32(raw + 41);
    const uint32_t sequence = read32(raw + 45);
    const uint64_t issued = read64(raw + 49);
    const uint64_t expires = read64(raw + 57);
    const uint16_t duration = (uint16_t(raw[65]) << 8) | raw[66];
    const uint8_t code = raw[67];
    const uint64_t now = utcMs();
    // Solo STOP HMAC autenticado admite hasta 100 ms de desfase futuro.
    // Evita rechazar un STOP firmado cuando NTP y Windows difieren ~25 ms.
    // Una orden de movimiento sigue exigiendo issued <= now sin tolerancia.
    const bool stopSlightlyAhead55H = code == 0 && issued > now &&
                                       (issued - now) <= 100ULL;
    const bool startedInTime55H = issued <= now || stopSlightlyAhead55H;
    const bool valid = codeAllowed(code) &&
        generation > 0 && epoch > 0 && sequence > 0 &&
        (lastSeq != UINT32_MAX) && sequence == lastSeq + 1 &&
        (generation > lastGeneration ||
         (generation == lastGeneration && epoch >= lastEpoch)) &&
        startedInTime55H && now < expires && expires > issued &&
        expires - issued <= 1000 && duration <= expires - issued &&
        (code == 0 ? duration == 0 : (duration >= 100 && duration <= 500)) &&
        (!pending || code == 0) &&
        (!pending || epoch > lastEpoch);
    if (!valid) {
      // DIAGNOSTICO SOLAMENTE: no se cambian los criterios de aceptacion.
      // Nunca imprimir firmas, paquetes, credenciales ni claves HMAC.
      const bool seqOK = lastSeq != UINT32_MAX && sequence == lastSeq + 1;
      const bool epochOK = generation > lastGeneration ||
                           (generation == lastGeneration && epoch >= lastEpoch);
      const bool relojOK = issued <= now && now < expires;
      const bool ttlOK = expires > issued && expires - issued <= 1000ULL;
      const bool durOK = ttlOK && duration <= expires - issued &&
                         (code == 0 ? duration == 0 : (duration >= 100 && duration <= 500));
      const bool pendOK = !pending || (code == 0 && epoch > lastEpoch);
      Serial.printf("[55-H] RECHAZO causa: codigoOK=%u, secOK=%u, epocaOK=%u, relojOK=%u, ttlOK=%u, durOK=%u, pendienteOK=%u\n",
                    (unsigned)codeAllowed(code), (unsigned)seqOK,
                    (unsigned)epochOK, (unsigned)relojOK,
                    (unsigned)ttlOK, (unsigned)durOK, (unsigned)pendOK);
      Serial.printf("[55-H] RECHAZO tiempos: delta_ms=%ld ttl_ms=%lu; PC_s=%lu ESP_s=%lu\n",
                    (long)(int64_t(now) - int64_t(issued)),
                    (unsigned long)(expires > issued ? expires - issued : 0ULL),
                    (unsigned long)(issued / 1000ULL),
                    (unsigned long)(now / 1000ULL));
      Serial.printf("[55-H] RECHAZO datos: seq=%lu esperada=%lu; gen=%lu ant=%lu; epoca=%lu ant=%lu; codigo=%u duracion=%u\n",
                    (unsigned long)sequence, (unsigned long)(lastSeq + 1),
                    (unsigned long)generation, (unsigned long)lastGeneration,
                    (unsigned long)epoch, (unsigned long)lastEpoch,
                    (unsigned)code, (unsigned)duration);
      ack(raw, 3);
      Serial.println(F("[55-H] Orden validamente firmada pero RECHAZADA por vigencia, secuencia o epoca"));
      return;
    }
    lastGeneration = generation;
    lastEpoch = epoch;
    lastSeq = sequence;
    if (code == 0) {
      // STOP local ANTES de enviar ACK WSS. El bloqueo GPIO sigue en 1.
      pending = false;
      grua.paradaSeguridad();
      if (!grua.confirmarStopInicialPuente55K(authenticated && valid)) {
        failClosed(F("55-K: STOP inicial no validado"));
        return;
      }
      ack(raw, 1);
      ack(raw, 2);
      Serial.println(F("[55-H] DETENER 0 HMAC: OK, neutro virtual"));
    } else {
      if (!grua.registrarSombra55K(code, duration)) {
        failClosed(F("55-K: orden virtual rechazada"));
        return;
      }
      // El servidor firmo la orden tras su propia admision.
      // El permiso K-V aun requiere integracion explicita final.
      if (!grua.registrarPuente55K(
              code, duration, authenticated && valid, valid)) {
        failClosed(F("55-K: puente virtual rechazo orden"));
        return;
      }
      grua.registrarDireccionVirtual(code); // No energiza PC817
      ack(raw, 1);
      memcpy(pendingPacket, raw, 68);
      pending = true;
      activeUntil = millis() + duration;
      Serial.printf("[55-H] Orden %u firmada: OK; GPIO inhibido, %u ms virtuales.\n", code, duration);
    }
  }

  void event(WStype_t type, uint8_t* payload, size_t length) {
    if (type == WStype_DISCONNECTED || type == WStype_ERROR) {
      authenticated = false;
      handshakeStarted = false;
      pending = false;
      grua.paradaSeguridad();
      Serial.println(F("[55-H] WSS desconectado: salidas en NEUTRO."));
      return;
    }
    if (type == WStype_CONNECTED) {
      authenticated = false;
      handshakeStarted = false;
      pending = false;
      grua.paradaSeguridadSilenciosa();
      Serial.println(F("[55-H] TLS WSS conectado; esperando desafio."));
      return;
    }
    if (type != WStype_TEXT) return;
    caducarPendienteVirtual();
    if (length > 512 || length == 0) {
      failClosed(F("Tamaño de mensaje invalido"));
      return;
    }
    JsonDocument doc;
    if (deserializeJson(doc, payload, length)) {
      failClosed(F("JSON invalido"));
      return;
    }
    const char* typ = doc["tipo"] | "";
    if (strcmp(typ, "desafio_dispositivo_lab") == 0) challenge(doc);
    else if (strcmp(typ, "dispositivo_autenticado_lab") == 0) confirmation(doc);
    else if (strcmp(typ, "orden_dispositivo_v1") == 0) order(doc);
    else if (strcmp(typ, "prueba_contrato_terminada") == 0 && authenticated &&
             doc["simulado"].as<bool>() && !doc["parada_fisica_verificada"].as<bool>() &&
             doc["movimiento"].as<int>() == 9 && doc["detener"].as<int>() == 0 &&
             !pending && lastSeq == 2) {
      Serial.println(F("[55-H] RESULTADO: WSS DIRECTO ESP8266 APROBADO - SIN MOTOR NI AWS"));
      finished = true;
      grua.paradaSeguridad();
      ws.disconnect();
    } else failClosed(F("Mensaje no permitido"));
  }

public:
  void begin() {
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    Serial.println(F("[55-H] Esperando hotspot 2.4 GHz, NTP y WSS TLS."));
    Serial.println(F("[55-H] NO conectar la bateria. Los PC817 siempre tienen valor 0."));
  }
  void update() {
    if (finished) return;
    if (WiFi.status() != WL_CONNECTED) {
      authenticated = false;
      handshakeStarted = false;
      pending = false;
      grua.paradaSeguridadSilenciosa();
      // Nueva conexion de hotspot = nueva sesion HMAC.
      if (started) {
        ws.disconnect();
        started = false;
      }
      if (millis() - wifiCheck > 5000) {
        wifiCheck = millis();
        const int estadoWifi = (int) WiFi.status();
        Serial.print(F("[55-H] Wi-Fi sin conectar. Estado="));
        Serial.print(estadoWifi);
        Serial.println(F(" (1=SSID no disponible; 4=fallo conexion; 6=desconectado)"));
        WiFi.reconnect();
      }
      return;
    }
    if (!started) {
      if (time(nullptr) < EPOCH_MIN_VALIDO) {
        if (millis() - wifiCheck > 5000) {
          wifiCheck = millis();
          Serial.println(F("[55-H] Esperando NTP para validar TLS y vigencia..."));
        }
        return;
      }
      // Obtener el identificador de arranque con la radio Wi-Fi activa.
      ESP.random(bootBytes, sizeof(bootBytes));
      Serial.print(F("[55-H] Servidor de laboratorio: "));
      Serial.print(LAB55H_HOST);
      Serial.print(':');
      Serial.println(LAB55H_PORT);
      Serial.println(F("[55-H] TLS CA privada. Motor siempre inhibido."));
      Serial.print(F("[55-H] IP del NodeMCU: "));
      Serial.println(WiFi.localIP());
      Serial.print(F("[55-H] Potencia Wi-Fi RSSI: "));
      Serial.print(WiFi.RSSI());
      Serial.println(F(" dBm"));
      // Sonda TCP de una sola vez: NO envia comandos ni reduce la seguridad TLS.
      // El WSS real continuara usando beginSslWithCA inmediatamente despues.
      WiFiClient sondaTCP55H;
      bool puertoAccesible55H = sondaTCP55H.connect(LAB55H_HOST, LAB55H_PORT);
      Serial.println(puertoAccesible55H
        ? F("[55-H] TCP LAN ESP -> PC: OK (8443 accesible)")
        : F("[55-H] TCP LAN ESP -> PC: FALLA (firewall, aislamiento Wi-Fi o ruta)"));
      sondaTCP55H.stop();
      if (puertoAccesible55H) {
        // Probar autenticacion TLS contra la MISMA CA privada del WSS.
        // Un cliente independiente: no envia comandos ni desactiva validaciones.
        {
          BearSSL::X509List caDiagnostico55H(LAB55H_CA_CERT);
          BearSSL::WiFiClientSecure clienteTLS55H;
          clienteTLS55H.setTrustAnchors(&caDiagnostico55H);
          clienteTLS55H.setTimeout(10000);
          Serial.printf("[55-H] Heap libre antes TLS: %u bytes\n", ESP.getFreeHeap());
          if (clienteTLS55H.connect(LAB55H_HOST, LAB55H_PORT)) {
            Serial.println(F("[55-H] TLS independiente ESP -> PC: OK (CA verificada)"));
          } else {
            char detalle55H[180] = {};
            int codigo55H = clienteTLS55H.getLastSSLError(detalle55H, sizeof(detalle55H));
            Serial.printf("[55-H] TLS independiente ESP -> PC: FALLA; codigo=%d, detalle=%s\n",
                          codigo55H, detalle55H);
          }
          clienteTLS55H.stop();
        }
        Serial.printf("[55-H] Heap libre despues TLS: %u bytes\n", ESP.getFreeHeap());
        yield();
      }
      ws.beginSslWithCA(LAB55H_HOST, LAB55H_PORT,
                        LAB55H_WS_PATH, LAB55H_CA_CERT);
      // WebSocketsClient envia por defecto "Origin: file://".
      // El WSS de laboratorio rechaza cualquier Origin para impedir accesos web.
      // Conserva CA TLS, HMAC y la restriccion de salidas del 74HC595.
      ws.setExtraHeaders("");
      ws.onEvent([this](WStype_t t, uint8_t* p, size_t n) { this->event(t,p,n); });
      ws.setReconnectInterval(3000);
      ws.enableHeartbeat(15000, 3000, 2);
      started = true;
    }
    caducarPendienteVirtual();
    ws.loop();
  }
};
Diagnostico55H diagnostico55H;

// R borra el hotspot y 0 fuerza neutro. No existe control manual de movimiento.
void comandosLocales() {
  if (Serial.available() <= 0) return;
  char c = (char)Serial.read();
  if (c == 'R' || c == 'r') hotspot.limpiarCredenciales();
  if (c == '0') grua.paradaSeguridad();
}
void setup() {
  Serial.begin(115200);
  delay(100);
  grua.iniciar();
  Serial.println(F("[55-H] CANDIDATO SOLO DIAGNOSTICO. NO CONECTAR BATERIA."));
  hotspot.iniciar();
  diagnostico55H.begin();
}
void loop() {
  hotspot.actualizar();
  diagnostico55H.update();
  comandosLocales();
  yield();
}
