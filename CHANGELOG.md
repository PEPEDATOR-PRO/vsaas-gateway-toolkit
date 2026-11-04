# Cambios

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
