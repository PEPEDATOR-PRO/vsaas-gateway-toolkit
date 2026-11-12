# Cambios

## 0.6.3 — 2026-11-12

- Instalaciones de paquetes con espera de hasta 300 s por el bloqueo de dpkg, para convivir con actualizaciones automáticas.
- Mensaje de error del instalador sin traceback ni argumentos privados y guía de recuperación sin eliminar locks.
- Actualización visual documentada con un solo módulo resumen, que también renueva los paneles.

## 0.6.2 — 2026-11-11

- Colector con un solo proceso por directorio de datos y accesos local/VPN compartiendo estado.
- El cálculo de ausencia se actualiza al detectar una recepción nueva en la base, evitando estados desconectados obsoletos tras recuperar reportes.

## 0.6.1 — 2026-11-11

- Confirmación de guardado junto al botón de Telemetría, relectura de configuración y aviso Llave guardada sin exponerla.
- Validación visible de llaves nuevas, conservación al volver a guardar y explicación de ID/llaves administrativas y de envío.

## 0.6.0 — 2026-11-11

- Emisor opcional de telemetría de salud, servicio limitado y configuración de hasta ocho destinos desde Cockpit.
- Colector de laptop LAN/VPN con reportes autenticados por equipo, recursos, red, Vsaas, VPN y avisos de ausencia/recuperación en el panel.
- Histórico acotado, llaves independientes, sin cola de reportes antiguos y guía completa de instalación/pruebas.

## 0.5.1 — 2026-11-05

- Tarjeta Información de red en Vista global: interfaz, MAC, IPv4/prefijo, segmento, gateway, máscara y método DHCP/estático cuando puede verificarse. Consulta manual sin sondeo continuo.

## 0.5.0 — 2026-11-04

- Cola de envío JSON configurable por host, puerto, path y HTTP/HTTPS, con token opcional cifrado, prueba y reintentos persistentes.
- Máximo local de 2 GB incluyendo reserva del diario SQLite; descarte de pendientes más antiguos al alcanzar capacidad y contador persistente de descartes.
- Identificador estable de entrega para deduplicación del receptor; eventos confirmados por HTTP 2xx se retiran de la cola.


## 0.4.0 — 2026-11-04

- Colector de eventos de cámaras importado como módulo opcional `eventos`, sin datos, catálogos, credenciales ni eventos reales del proyecto original.
- Despliegue Docker separado con persistencia, llaves locales, presupuesto preventivo de almacenamiento y límites de recursos.
- Acceso desde una herramienta de Cockpit y por la IP VPN, puerto 8081; recuperación de arranque mediante systemd.
- Pruebas ONVIF/RTSP/HTTP locales, interfaz y guía de instalación/operación.

## 0.3.0 — 2026-11-03

- Guía completa de implementación pública con todos los módulos, Gateway Vsaas, verificación y exportación de informes a Windows.
- Parámetros VPN centrales en archivo local y host API Vsaas proporcionado por el operador; se eliminan los valores de cliente predeterminados del código actual.
- Corrección de `resumen`: actualiza también los archivos instalados y utiliza versiones de recursos para evitar conservar la gráfica anterior en caché.
- Gráfica de Vista global con fondo contrastado, cuadrícula, áreas de recepción/envío, escala visible y referencias de tiempo.
- Prueba manual de credenciales ONVIF/HTTP y preparación de acceso web por túnel SSH desde el escáner, sin guardar credenciales ni abrir un proxy permanente.
- Salud de VPN IPsec en Salud Vsaas y Vista global, con estado IKE/CHILD SA, tiempo de sesión y contadores; consulta de solo lectura bajo demanda.
- Asistente VPN con leftid, subred CIDR y clave compartida local; IP de administración calculada automáticamente y parámetros centrales preconfigurados.
- El perfil generado se reutiliza para SSH, Cockpit y paneles y no guarda la clave compartida.

## 0.2.0

- Importación del paquete de scripts VXG 1.0.16 con hashes de procedencia y exclusión del `.env` original.
- Módulo `vxg` para equipos nuevos, sin depender todavía de la configuración VPN.
- Credenciales de descarga mediante entrada interactiva o archivo privado; autenticación temporal de Docker.
- Guía de instalación desde cero, contraseña local de administrador y pruebas de los límites de credenciales.

## 0.1.0

- Organización inicial del toolkit con configuración por equipo y sin credenciales incluidas.
- VPN IPsec, SSH, Cockpit y herramientas de red.
- Paneles de escáner, tráfico y Salud Vsaas.
- Adaptación reversible de Vista global.
- Recopilación de 24 horas con límites de recursos y almacenamiento.
- Generación de instaladores con sumas SHA256 y pruebas automatizadas.
