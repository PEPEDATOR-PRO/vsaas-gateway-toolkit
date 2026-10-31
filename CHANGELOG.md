# Cambios

## Próxima actualización

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
