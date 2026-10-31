#include <ESP8266WiFi.h>
#include <WiFiManager.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <time.h>

// =====================================================
// CONFIGURACION GENERAL
// =====================================================

// 74HC595
const uint8_t DATA_PIN  = D5;
const uint8_t CLOCK_PIN = D6;
const uint8_t LATCH_PIN = D7;

// Reset Wi-Fi
const uint8_t RESET_WIFI_PIN = D2;

// IMPORTANTE:
// Configurar localmente antes de compilar.
// No subir la contraseña real al repositorio.
const char* AP_PASSWORD = "CONFIGURAR_LOCALMENTE";

const unsigned long RESET_HOLD_TIME = 5000;
const unsigned long RECONNECT_INTERVAL = 10000;

// =====================================================
// AWS / WEBSOCKET
// =====================================================

const char* AWS_HOST = "100-30-4-62.nip.io";
const uint16_t AWS_PORT = 443;
const char* AWS_WS_PATH = "/ws/vehiculos/1";

const int ID_VEHICULO = 1;

// =====================================================
// NTP / VALIDACION DE TIEMPO TLS
// =====================================================

const char* NTP_SERVER_1 = "pool.ntp.org";
const char* NTP_SERVER_2 = "time.google.com";

// 1 enero 2025.
const time_t EPOCH_MIN_VALIDO = 1735689600;

// =====================================================
// CERTIFICADOS RAIZ DE CONFIANZA
// =====================================================

static const char TLS_CA_BUNDLE[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw
TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh
cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4
WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu
ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY
MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc
h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+
0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U
A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW
T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH
B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC
B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv
KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn
OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn
jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw
qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI
rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV
HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq
hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL
ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ
3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK
NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5
ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur
TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC
jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc
oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq
4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA
mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d
emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIF3jCCA8agAwIBAgIQAf1tMPyjylGoG7xkDjUDLTANBgkqhkiG9w0BAQwFADCB
iDELMAkGA1UEBhMCVVMxEzARBgNVBAgTCk5ldyBKZXJzZXkxFDASBgNVBAcTC0pl
cnNleSBDaXR5MR4wHAYDVQQKExVUaGUgVVNFUlRSVVNUIE5ldHdvcmsxLjAsBgNV
BAMTJVVTRVJUcnVzdCBSU0EgQ2VydGlmaWNhdGlvbiBBdXRob3JpdHkwHhcNMTAw
MjAxMDAwMDAwWhcNMzgwMTE4MjM1OTU5WjCBiDELMAkGA1UEBhMCVVMxEzARBgNV
BAgTCk5ldyBKZXJzZXkxFDASBgNVBAcTC0plcnNleSBDaXR5MR4wHAYDVQQKExVU
aGUgVVNFUlRSVVNUIE5ldHdvcmsxLjAsBgNVBAMTJVVTRVJUcnVzdCBSU0EgQ2Vy
dGlmaWNhdGlvbiBBdXRob3JpdHkwggIiMA0GCSqGSIb3DQEBAQUAA4ICDwAwggIK
AoICAQCAEmUXNg7D2wiz0KxXDXbtzSfTTK1Qg2HiqiBNCS1kCdzOiZ/MPans9s/B
3PHTsdZ7NygRK0faOca8Ohm0X6a9fZ2jY0K2dvKpOyuR+OJv0OwWIJAJPuLodMkY
tJHUYmTbf6MG8YgYapAiPLz+E/CHFHv25B+O1ORRxhFnRghRy4YUVD+8M/5+bJz/
Fp0YvVGONaanZshyZ9shZrHUm3gDwFA66Mzw3LyeTP6vBZY1H1dat//O+T23LLb2
VN3I5xI6Ta5MirdcmrS3ID3KfyI0rn47aGYBROcBTkZTmzNg95S+UzeQc0PzMsNT
79uq/nROacdrjGCT3sTHDN/hMq7MkztReJVni+49Vv4M0GkPGw/zJSZrM233bkf6
c0Plfg6lZrEpfDKEY1WJxA3Bk1QwGROs0303p+tdOmw1XNtB1xLaqUkL39iAigmT
Yo61Zs8liM2EuLE/pDkP2QKe6xJMlXzzawWpXhaDzLhn4ugTncxbgtNMs+1b/97l
c6wjOy0AvzVVdAlJ2ElYGn+SNuZRkg7zJn0cTRe8yexDJtC/QV9AqURE9JnnV4ee
UB9XVKg+/XRjL7FQZQnmWEIuQxpMtPAlR1n6BB6T1CZGSlCBst6+eLf8ZxXhyVeE
Hg9j1uliutZfVS7qXMYoCAQlObgOK6nyTJccBz8NUvXt7y+CDwIDAQABo0IwQDAd
BgNVHQ4EFgQUU3m/WqorSs9UgOHYm8Cd8rIDZsswDgYDVR0PAQH/BAQDAgEGMA8G
A1UdEwEB/wQFMAMBAf8wDQYJKoZIhvcNAQEMBQADggIBAFzUfA3P9wF9QZllDHPF
Up/L+M+ZBn8b2kMVn54CVVeWFPFSPCeHlCjtHzoBN6J2/FNQwISbxmtOuowhT6KO
VWKR82kV2LyI48SqC/3vqOlLVSoGIG1VeCkZ7l8wXEskEVX/JJpuXior7gtNn3/3
ATiUFJVDBwn7YKnuHKsSjKCaXqeYalltiz8I+8jRRa8YFWSQEg9zKC7F4iRO/Fjs
8PRF/iKz6y+O0tlFYQXBl2+odnKPi4w2r78NBc5xjeambx9spnFixdjQg3IM8WcR
iQycE0xyNN+81XHfqnHd4blsjDwSXWXavVcStkNr/+XeTWYRUc+ZruwXtuhxkYze
Sf7dNXGiFSeUHM9h4ya7b6NnJSFd5t0dCy5oGzuCr+yDZ4XUmFF0sbmZgIn/f3gZ
XHlKYC6SQK5MNyosycdiyA5d9zZbyuAlJQG03RoHnHcAP9Dc1ew91Pq7P8yF1m9/
qS3fuQL39ZeatTXaw2ewh0qpKJ4jjv9cJ2vhsE/zB+4ALtRZh8tSQZXq9EfX7mRB
VXyNWQKV3WKdwrnuWih0hKWbt5DHDAff9Yk2dDLWKMGwsAvgnEzDHNb842m1R0aB
L6KCq9NjRHDEjf8tM7qtj3u1cIiuPhnPQCjY/MiQu12ZIvVS5ljFH4gxQ+6IHdfG
jjxDah2nGN59PRbxYvnKkKj9
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIICjzCCAhWgAwIBAgIQXIuZxVqUxdJxVt7NiYDMJjAKBggqhkjOPQQDAzCBiDEL
MAkGA1UEBhMCVVMxEzARBgNVBAgTCk5ldyBKZXJzZXkxFDASBgNVBAcTC0plcnNl
eSBDaXR5MR4wHAYDVQQKExVUaGUgVVNFUlRSVVNUIE5ldHdvcmsxLjAsBgNVBAMT
JVVTRVJUcnVzdCBFQ0MgQ2VydGlmaWNhdGlvbiBBdXRob3JpdHkwHhcNMTAwMjAx
MDAwMDAwWhcNMzgwMTE4MjM1OTU5WjCBiDELMAkGA1UEBhMCVVMxEzARBgNVBAgT
Ck5ldyBKZXJzZXkxFDASBgNVBAcTC0plcnNleSBDaXR5MR4wHAYDVQQKExVUaGUg
VVNFUlRSVVNUIE5ldHdvcmsxLjAsBgNVBAMTJVVTRVJUcnVzdCBFQ0MgQ2VydGlm
aWNhdGlvbiBBdXRob3JpdHkwdjAQBgcqhkjOPQIBBgUrgQQAIgNiAAQarFRaqflo
I+d61SRvU8Za2EurxtW20eZzca7dnNYMYf3boIkDuAUU7FfO7l0/4iGzzvfUinng
o4N+LZfQYcTxmdwlkWOrfzCjtHDix6EznPO/LlxTsV+zfTJ/ijTjeXmjQjBAMB0G
A1UdDgQWBBQ64QmG1M8ZwpZ2dEl23OA1xmNjmjAOBgNVHQ8BAf8EBAMCAQYwDwYD
VR0TAQH/BAUwAwEB/zAKBggqhkjOPQQDAwNoADBlAjA2Z6EWCNzklwBBHU6+4WMB
zzuqQhFkoJ2UOQIReVx7Hfpkue4WQrO/isIJxOzksU0CMQDpKmFHjFJKS04YcPbW
RNZu9YO6bVi9JNlWSOrvxKJGgYhqOkbRqZtNyWHa0V1Xahg=
-----END CERTIFICATE-----
)EOF";

class GruaRC {
private:
  uint8_t dataPin;
  uint8_t clockPin;
  uint8_t latchPin;

  static constexpr uint8_t Q0_AVANZAR       = B00000001;
  static constexpr uint8_t Q1_RETROCEDER    = B00000010;
  static constexpr uint8_t Q2_IZQUIERDA     = B00000100;
  static constexpr uint8_t Q3_DERECHA       = B00001000;
  static constexpr uint8_t Q4_LUCES         = B00010000;
  static constexpr uint8_t Q5_VELOCIDAD     = B00100000;
  static constexpr uint8_t Q6_DEMO_ORIGINAL = B01000000;
  static constexpr uint8_t Q7_CLAXON        = B10000000;

  void enviar(uint8_t valor) {
    digitalWrite(latchPin, LOW);
    shiftOut(dataPin, clockPin, MSBFIRST, valor);
    digitalWrite(latchPin, HIGH);
  }

  void detener() { enviar(B00000000); }
  void avanzar() { enviar(Q0_AVANZAR); }
  void retroceder() { enviar(Q1_RETROCEDER); }
  void izquierda() { enviar(Q2_IZQUIERDA); }
  void derecha() { enviar(Q3_DERECHA); }

  void retrocederIzquierda() {
    enviar(Q1_RETROCEDER | Q2_IZQUIERDA);
  }

  void avanzarDerecha() {
    enviar(Q0_AVANZAR | Q3_DERECHA);
  }

  void luces() {
    enviar(Q4_LUCES);
    delay(300);
    detener();
  }

  void velocidad() {
    enviar(Q5_VELOCIDAD);
    delay(300);
    detener();
  }

  void demoOriginal() {
    enviar(Q6_DEMO_ORIGINAL);
    delay(300);
    detener();
  }

  void claxon() {
    enviar(Q7_CLAXON);
    delay(300);
    detener();
  }

public:
  GruaRC(uint8_t data, uint8_t clock, uint8_t latch)
    : dataPin(data), clockPin(clock), latchPin(latch) {}

  void iniciar() {
    pinMode(dataPin, OUTPUT);
    pinMode(clockPin, OUTPUT);
    pinMode(latchPin, OUTPUT);

    digitalWrite(dataPin, LOW);
    digitalWrite(clockPin, LOW);
    digitalWrite(latchPin, LOW);

    detener();
    delay(50);
    detener();

    Serial.println();
    Serial.println("========================================");
    Serial.println("       CONTROL FISICO INICIALIZADO");
    Serial.println("========================================");
    Serial.println("W = Avanzar");
    Serial.println("S = Retroceder");
    Serial.println("A = Izquierda");
    Serial.println("F = Derecha");
    Serial.println("H = Luces");
    Serial.println("V = Velocidad");
    Serial.println("C = Claxon");
    Serial.println("L = Demo original");
    Serial.println("0 = Detener");
    Serial.println("R = Reset Wi-Fi");
    Serial.println("========================================");
  }

  void procesarComandoManual(char comando) {
    switch (comando) {
      case 'W': avanzar(); Serial.println("[GRUA] AVANZANDO"); break;
      case 'S': retroceder(); Serial.println("[GRUA] RETROCEDIENDO"); break;
      case 'A': izquierda(); Serial.println("[GRUA] IZQUIERDA"); break;
      case 'F': derecha(); Serial.println("[GRUA] DERECHA"); break;
      case 'H': luces(); Serial.println("[GRUA] LUCES"); break;
      case 'V': velocidad(); Serial.println("[GRUA] VELOCIDAD"); break;
      case 'C': claxon(); Serial.println("[GRUA] CLAXON"); break;
      case 'L': demoOriginal(); Serial.println("[GRUA] DEMO ORIGINAL"); break;
      case '0': detener(); Serial.println("[GRUA] DETENIDO"); break;
      default: break;
    }
  }

  void ejecutarCodigoAWS(int codigo) {
    switch (codigo) {
      case 0: detener(); Serial.println("[GRUA/AWS] DETENIDO - codigo 0"); break;
      case 1: avanzar(); Serial.println("[GRUA/AWS] AVANZANDO - codigo 1"); break;
      case 2: retroceder(); Serial.println("[GRUA/AWS] RETROCEDIENDO - codigo 2"); break;
      case 4: izquierda(); Serial.println("[GRUA/AWS] IZQUIERDA - codigo 4"); break;
      case 6: retrocederIzquierda(); Serial.println("[GRUA/AWS] RETROCEDER + IZQUIERDA - codigo 6"); break;
      case 8: derecha(); Serial.println("[GRUA/AWS] DERECHA - codigo 8"); break;
      case 9: avanzarDerecha(); Serial.println("[GRUA/AWS] AVANZAR + DERECHA - codigo 9"); break;
      case 16: luces(); Serial.println("[GRUA/AWS] LUCES - codigo 16"); break;
      case 32: velocidad(); Serial.println("[GRUA/AWS] VELOCIDAD - codigo 32"); break;
      case 64: demoOriginal(); Serial.println("[GRUA/AWS] DEMO ORIGINAL - codigo 64"); break;
      case 128: claxon(); Serial.println("[GRUA/AWS] CLAXON - codigo 128"); break;
      default:
        Serial.print("[GRUA/AWS] Codigo desconocido: ");
        Serial.println(codigo);
        detener();
        break;
    }
  }

  void activarCodigoDemo(int codigo) {
    switch (codigo) {
      case 0: enviar(B00000000); break;
      case 1: enviar(Q0_AVANZAR); break;
      case 2: enviar(Q1_RETROCEDER); break;
      case 4: enviar(Q2_IZQUIERDA); break;
      case 6: enviar(Q1_RETROCEDER | Q2_IZQUIERDA); break;
      case 8: enviar(Q3_DERECHA); break;
      case 9: enviar(Q0_AVANZAR | Q3_DERECHA); break;
      case 16: enviar(Q4_LUCES); break;
      case 32: enviar(Q5_VELOCIDAD); break;
      case 64: enviar(Q6_DEMO_ORIGINAL); break;
      case 128: enviar(Q7_CLAXON); break;
      default:
        detener();
        Serial.print("[GRUA/DEMO] Codigo desconocido: ");
        Serial.println(codigo);
        break;
    }
  }

  void detenerPasoDemo() {
    detener();
    Serial.println("[GRUA/DEMO] Salidas detenidas.");
  }

  void paradaSeguridad() {
    detener();
    Serial.println("[SEGURIDAD] Vehiculo detenido.");
  }
};

class GestorWiFi {
private:
  WiFiManager wifiManager;
  uint8_t resetPin;
  String nombreDispositivo;
  bool resetGPIOActivo = false;
  unsigned long inicioResetGPIO = 0;
  unsigned long ultimoIntentoReconexion = 0;
  wl_status_t ultimoEstadoWiFi = WL_IDLE_STATUS;

  String generarNombreDispositivo() {
    uint8_t mac[6];
    WiFi.macAddress(mac);
    char sufijo[7];
    snprintf(sufijo, sizeof(sufijo), "%02X%02X%02X", mac[3], mac[4], mac[5]);
    return "EXCAVADORA-" + String(sufijo);
  }

  void mostrarInformacionWiFi() {
    Serial.println();
    Serial.println("========================================");
    Serial.println("       CONEXION WIFI ESTABLECIDA");
    Serial.println("========================================");
    Serial.print("Dispositivo: "); Serial.println(nombreDispositivo);
    Serial.print("MAC: "); Serial.println(WiFi.macAddress());
    Serial.print("SSID: "); Serial.println(WiFi.SSID());
    Serial.print("IPv4: "); Serial.println(WiFi.localIP());
    Serial.print("Mascara: "); Serial.println(WiFi.subnetMask());
    Serial.print("Gateway: "); Serial.println(WiFi.gatewayIP());
    Serial.print("RSSI: "); Serial.print(WiFi.RSSI()); Serial.println(" dBm");
    Serial.println("========================================");
    Serial.println();
  }

  static void portalConfiguracionIniciado(WiFiManager* wm) {
    Serial.println();
    Serial.println("========================================");
    Serial.println("      MODO CONFIGURACION WIFI");
    Serial.println("========================================");
    Serial.print("Punto de acceso: "); Serial.println(wm->getConfigPortalSSID());
    Serial.print("IP portal: "); Serial.println(WiFi.softAPIP());
    Serial.println("Portal: http://192.168.4.1");
    Serial.println("Password del AP oculta por seguridad.");
    Serial.println("========================================");
  }

  void revisarResetGPIO() {
    bool pulsado = digitalRead(resetPin) == LOW;

    if (pulsado && !resetGPIOActivo) {
      resetGPIOActivo = true;
      inicioResetGPIO = millis();
      Serial.println("[WIFI] D2 conectado a GND.");
      Serial.println("[WIFI] Mantener 5 segundos.");
    }

    if (pulsado && resetGPIOActivo) {
      unsigned long tiempo = millis() - inicioResetGPIO;
      if (tiempo >= RESET_HOLD_TIME) {
        borrarCredencialesYReiniciar("Reset fisico D2");
      }
    }

    if (!pulsado && resetGPIOActivo) {
      resetGPIOActivo = false;
      Serial.println("[WIFI] Reset cancelado.");
    }
  }

  void revisarEstadoWiFi() {
    wl_status_t estadoActual = WiFi.status();

    if (estadoActual != ultimoEstadoWiFi) {
      ultimoEstadoWiFi = estadoActual;

      if (estadoActual == WL_CONNECTED) {
        Serial.println("[WIFI] Conexion establecida.");
        mostrarInformacionWiFi();
      } else {
        Serial.println("[WIFI] Conexion perdida.");
      }
    }

    if (estadoActual != WL_CONNECTED) {
      unsigned long ahora = millis();
      if (ahora - ultimoIntentoReconexion >= RECONNECT_INTERVAL) {
        ultimoIntentoReconexion = ahora;
        Serial.println("[WIFI] Intentando reconexion...");
        WiFi.reconnect();
      }
    }
  }

public:
  explicit GestorWiFi(uint8_t pinReset) : resetPin(pinReset) {}

  void iniciar() {
    pinMode(resetPin, INPUT_PULLUP);
    WiFi.mode(WIFI_STA);

    nombreDispositivo = generarNombreDispositivo();

    Serial.println();
    Serial.println("========================================");
    Serial.println("       SISTEMA WIFI INICIALIZANDO");
    Serial.println("========================================");
    Serial.print("Dispositivo: "); Serial.println(nombreDispositivo);
    Serial.print("MAC: "); Serial.println(WiFi.macAddress());

    wifiManager.setAPCallback(portalConfiguracionIniciado);
    wifiManager.setConfigPortalBlocking(false);
    wifiManager.setWiFiAutoReconnect(true);
    wifiManager.setConnectTimeout(20);
    wifiManager.setRemoveDuplicateAPs(true);
    wifiManager.setHostname(nombreDispositivo);

    Serial.println("[WIFI] Buscando credenciales almacenadas...");

    bool conectado = wifiManager.autoConnect(
      nombreDispositivo.c_str(),
      AP_PASSWORD
    );

    if (conectado) {
      Serial.println("[WIFI] Conexion automatica correcta.");
      mostrarInformacionWiFi();
    } else {
      Serial.println("[WIFI] Portal de configuracion activo.");
      Serial.print("[WIFI] Red temporal: "); Serial.println(nombreDispositivo);
      Serial.println("[WIFI] Portal: http://192.168.4.1");
    }

    ultimoEstadoWiFi = WiFi.status();
  }

  void actualizar() {
    wifiManager.process();
    revisarResetGPIO();
    revisarEstadoWiFi();
  }

  void borrarCredencialesYReiniciar(const char* motivo) {
    Serial.println();
    Serial.println("========================================");
    Serial.println("      RESTABLECIMIENTO DE WIFI");
    Serial.println("========================================");
    Serial.print("Motivo: "); Serial.println(motivo);
    wifiManager.resetSettings();
    Serial.println("Credenciales eliminadas.");
    Serial.println("Reiniciando ESP8266...");
    delay(300);
    ESP.restart();
  }

  bool conectado() {
    return WiFi.status() == WL_CONNECTED;
  }
};

class ClienteAWS {
private:
  WebSocketsClient webSocket;
  GruaRC& grua;

  bool iniciado = false;
  bool websocketConectado = false;
  bool paradaDesconexionAplicada = false;

  bool horaSincronizada = false;
  unsigned long ultimoIntentoNTP = 0;

  bool demoActiva = false;
  bool pasoDemoActivo = false;
  unsigned long inicioPasoDemo = 0;
  unsigned long duracionPasoDemo = 0;
  unsigned long pausaPasoDemo = 0;
  int codigoPasoDemo = 0;

  bool sincronizarHora() {
    time_t ahoraUnix = time(nullptr);

    if (ahoraUnix >= EPOCH_MIN_VALIDO) {
      horaSincronizada = true;
      return true;
    }

    unsigned long ahoraMillis = millis();
    if (ultimoIntentoNTP != 0 && ahoraMillis - ultimoIntentoNTP < 30000) {
      return false;
    }

    ultimoIntentoNTP = ahoraMillis;

    Serial.println();
    Serial.println("========================================");
    Serial.println("       SINCRONIZANDO HORA NTP");
    Serial.println("========================================");

    configTime(0, 0, NTP_SERVER_1, NTP_SERVER_2);

    unsigned long inicio = millis();
    while (time(nullptr) < EPOCH_MIN_VALIDO && millis() - inicio < 15000) {
      delay(250);
      yield();
    }

    ahoraUnix = time(nullptr);

    if (ahoraUnix >= EPOCH_MIN_VALIDO) {
      horaSincronizada = true;
      Serial.println("[TLS] Hora NTP sincronizada.");
      Serial.print("[TLS] Unix time: "); Serial.println((unsigned long)ahoraUnix);
      Serial.println("[TLS] Validacion X.509 habilitada.");
      Serial.println("========================================");
      return true;
    }

    horaSincronizada = false;
    Serial.println("[TLS] No fue posible obtener hora valida.");
    Serial.println("[TLS] WSS NO se abrira de forma insegura.");
    Serial.println("[TLS] Se reintentara automaticamente.");
    Serial.println("========================================");
    return false;
  }

  void actualizarDemo() {
    if (!pasoDemoActivo) return;

    unsigned long ahora = millis();
    if (ahora - inicioPasoDemo >= duracionPasoDemo) {
      pasoDemoActivo = false;
      grua.detenerPasoDemo();
      Serial.print("[AWS/DEMO] Duracion terminada. Pausa esperada desde AWS: ");
      Serial.print(pausaPasoDemo);
      Serial.println(" ms");
    }
  }

  void finalizarDemoLocal() {
    pasoDemoActivo = false;
    demoActiva = false;
    codigoPasoDemo = 0;
    duracionPasoDemo = 0;
    pausaPasoDemo = 0;
    grua.paradaSeguridad();
  }

  void procesarJSON(uint8_t* payload, size_t longitud) {
    JsonDocument documento;
    DeserializationError error = deserializeJson(documento, payload, longitud);

    if (error) {
      Serial.print("[AWS] Error interpretando JSON: ");
      Serial.println(error.c_str());
      return;
    }

    const char* tipoEvento = documento["tipo_evento"];
    if (tipoEvento == nullptr) {
      Serial.println("[AWS] Evento sin tipo_evento.");
      return;
    }

    int idVehiculo = documento["id_vehiculo"] | -1;
    if (idVehiculo != ID_VEHICULO) {
      Serial.print("[AWS] Evento de otro vehiculo ignorado: ");
      Serial.println(idVehiculo);
      return;
    }

    if (strcmp(tipoEvento, "estado_actual") == 0) {
      Serial.println("[AWS] estado_actual recibido.");
      Serial.println("[AWS] Se ignora como orden fisica por seguridad.");
      return;
    }

    if (strcmp(tipoEvento, "movimiento") == 0) {
      if (!documento["codigo"].is<int>()) {
        Serial.println("[AWS] Movimiento sin codigo valido.");
        return;
      }

      int codigo = documento["codigo"].as<int>();
      const char* comando = documento["comando"] | "DESCONOCIDO";
      int idComando = documento["id_comando"] | -1;

      Serial.println();
      Serial.println("========================================");
      Serial.println("       ORDEN AWS VALIDADA");
      Serial.println("========================================");
      Serial.print("[AWS] id_comando: "); Serial.println(idComando);
      Serial.print("[AWS] Comando: "); Serial.println(comando);
      Serial.print("[AWS] Codigo: "); Serial.println(codigo);
      Serial.println("========================================");

      grua.ejecutarCodigoAWS(codigo);
      return;
    }

    if (strcmp(tipoEvento, "demo_inicio") == 0) {
      demoActiva = true;
      pasoDemoActivo = false;
      grua.detenerPasoDemo();

      Serial.println();
      Serial.println("========================================");
      Serial.println("       DEMO AWS INICIADA");
      Serial.println("========================================");
      Serial.print("[AWS/DEMO] id_demo: "); Serial.println(documento["id_demo"] | -1);
      Serial.print("[AWS/DEMO] Nombre: "); Serial.println(documento["nombre_demo"] | "SIN_NOMBRE");
      Serial.println("========================================");
      return;
    }

    if (strcmp(tipoEvento, "demo_movimiento") == 0) {
      if (
        !documento["codigo"].is<int>() ||
        !documento["duracion_ms"].is<int>() ||
        !documento["pausa_ms"].is<int>()
      ) {
        Serial.println("[AWS/DEMO] Paso invalido.");
        finalizarDemoLocal();
        return;
      }

      demoActiva = true;
      codigoPasoDemo = documento["codigo"].as<int>();
      long duracionRecibida = documento["duracion_ms"].as<long>();
      long pausaRecibida = documento["pausa_ms"].as<long>();

      if (duracionRecibida < 0 || pausaRecibida < 0) {
        Serial.println("[AWS/DEMO] Tiempos invalidos.");
        finalizarDemoLocal();
        return;
      }

      duracionPasoDemo = (unsigned long)duracionRecibida;
      pausaPasoDemo = (unsigned long)pausaRecibida;

      const char* comando = documento["comando"] | "DESCONOCIDO";
      int orden = documento["orden"] | -1;

      Serial.println();
      Serial.println("========================================");
      Serial.println("       PASO DEMO AWS");
      Serial.println("========================================");
      Serial.print("[AWS/DEMO] Orden: "); Serial.println(orden);
      Serial.print("[AWS/DEMO] Comando: "); Serial.println(comando);
      Serial.print("[AWS/DEMO] Codigo: "); Serial.println(codigoPasoDemo);
      Serial.print("[AWS/DEMO] Duracion: "); Serial.print(duracionPasoDemo); Serial.println(" ms");
      Serial.print("[AWS/DEMO] Pausa: "); Serial.print(pausaPasoDemo); Serial.println(" ms");
      Serial.println("========================================");

      grua.activarCodigoDemo(codigoPasoDemo);
      inicioPasoDemo = millis();

      if (duracionPasoDemo == 0) {
        pasoDemoActivo = false;
        grua.detenerPasoDemo();
      } else {
        pasoDemoActivo = true;
      }

      return;
    }

    if (strcmp(tipoEvento, "demo_fin") == 0) {
      Serial.println();
      Serial.println("========================================");
      Serial.println("       DEMO AWS TERMINADA");
      Serial.println("========================================");
      finalizarDemoLocal();
      return;
    }

    if (strcmp(tipoEvento, "demo_cancelada") == 0) {
      Serial.println("[AWS/DEMO] DEMO CANCELADA");
      finalizarDemoLocal();
      return;
    }

    if (strcmp(tipoEvento, "demo_error") == 0) {
      Serial.println("[AWS/DEMO] ERROR EN DEMO");
      finalizarDemoLocal();
      return;
    }

    Serial.print("[AWS] Tipo de evento desconocido: ");
    Serial.println(tipoEvento);
  }

  void manejarEvento(WStype_t tipo, uint8_t* payload, size_t longitud) {
    switch (tipo) {
      case WStype_DISCONNECTED:
        websocketConectado = false;
        demoActiva = false;
        pasoDemoActivo = false;
        Serial.println();
        Serial.println("[AWS] WSS DESCONECTADO");

        if (!paradaDesconexionAplicada) {
          grua.paradaSeguridad();
          paradaDesconexionAplicada = true;
        }
        break;

      case WStype_CONNECTED:
        websocketConectado = true;
        paradaDesconexionAplicada = false;
        Serial.println();
        Serial.println("========================================");
        Serial.println("       AWS WSS CONECTADO");
        Serial.println("========================================");
        Serial.println("[TLS] Certificado del servidor VALIDADO.");
        Serial.print("[AWS] Endpoint: wss://");
        Serial.print(AWS_HOST);
        Serial.println(AWS_WS_PATH);
        Serial.println();
        break;

      case WStype_TEXT:
        Serial.println();
        Serial.println("========================================");
        Serial.println("       EVENTO RECIBIDO DESDE AWS");
        Serial.println("========================================");
        Serial.print("[AWS] JSON: ");
        Serial.write(payload, longitud);
        Serial.println();
        Serial.println("========================================");
        procesarJSON(payload, longitud);
        break;

      case WStype_PING:
      case WStype_PONG:
        break;

      case WStype_ERROR:
        Serial.println("[AWS] Error WebSocket/TLS.");
        break;

      default:
        break;
    }
  }

  void conectar() {
    Serial.println();
    Serial.println("========================================");
    Serial.println("       CONECTANDO CON AWS WSS");
    Serial.println("========================================");
    Serial.print("[AWS] Host: "); Serial.println(AWS_HOST);
    Serial.print("[AWS] Puerto: "); Serial.println(AWS_PORT);
    Serial.print("[AWS] Ruta: "); Serial.println(AWS_WS_PATH);
    Serial.println("[TLS] Validacion CA: ACTIVADA");
    Serial.println();

    webSocket.onEvent(
      [this](WStype_t tipo, uint8_t* payload, size_t longitud) {
        this->manejarEvento(tipo, payload, longitud);
      }
    );

    webSocket.beginSslWithCA(
      AWS_HOST,
      AWS_PORT,
      AWS_WS_PATH,
      TLS_CA_BUNDLE
    );

    webSocket.setReconnectInterval(5000);
    iniciado = true;
  }

public:
  explicit ClienteAWS(GruaRC& referenciaGrua)
    : grua(referenciaGrua) {}

  void actualizar(bool wifiConectado) {
    if (!wifiConectado) {
      demoActiva = false;
      pasoDemoActivo = false;

      if (!paradaDesconexionAplicada) {
        Serial.println("[SEGURIDAD] Wi-Fi no disponible.");
        grua.paradaSeguridad();
        paradaDesconexionAplicada = true;
      }
      return;
    }

    if (!horaSincronizada) {
      if (!sincronizarHora()) return;
    }

    if (!iniciado) conectar();

    webSocket.loop();
    actualizarDemo();
  }

  bool conectado() {
    return websocketConectado;
  }
};

GruaRC grua(DATA_PIN, CLOCK_PIN, LATCH_PIN);
GestorWiFi gestorWiFi(RESET_WIFI_PIN);
ClienteAWS clienteAWS(grua);

void procesarSerial() {
  if (Serial.available() <= 0) return;

  char comando = Serial.read();

  if (comando == '\n' || comando == '\r') return;

  if (comando >= 'a' && comando <= 'z') {
    comando = comando - 32;
  }

  if (comando == 'R') {
    grua.paradaSeguridad();
    gestorWiFi.borrarCredencialesYReiniciar(
      "Comando R desde Monitor Serie"
    );
    return;
  }

  grua.procesarComandoManual(comando);
}

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println();
  Serial.println();
  Serial.println("========================================");
  Serial.println("       EXCAVADORA IoT - AWS");
  Serial.println("========================================");

  grua.iniciar();
  gestorWiFi.iniciar();

  Serial.println();
  Serial.println("========================================");
  Serial.println("       SISTEMA INICIALIZADO");
  Serial.println("========================================");
  Serial.println("Control fisico: ACTIVO");
  Serial.println("WiFiManager: ACTIVO");
  Serial.println("AWS/WSS: ACTIVO");
  Serial.println("ArduinoJson: ACTIVO");
  Serial.println("DEMO dinamica AWS: ACTIVA");
  Serial.println("Fail-safe Wi-Fi/WSS: ACTIVO");
  Serial.println("TLS X.509: VALIDACION CA ACTIVADA");
  Serial.println("========================================");
  Serial.println();
}

void loop() {
  gestorWiFi.actualizar();
  clienteAWS.actualizar(gestorWiFi.conectado());
  procesarSerial();
  yield();
}
