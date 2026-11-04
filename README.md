# Vsaas Gateway Toolkit

Herramientas para preparar y administrar Gateways Ubuntu con VXG: VPN IPsec hacia FortiGate, acceso SSH, Cockpit, escáner de red, tráfico en vivo, Salud Vsaas y pruebas de observación de 24 horas.

El código y los instaladores viven en este repositorio. Los datos de cada equipo se mantienen en un perfil local; la clave compartida de la VPN se introduce directamente en Ubuntu al instalar.

## Guía completa de implementación

Empieza por [Implementación completa, paso a paso](docs/GUIA-COMPLETA.md). Incluye Ubuntu, Docker, Gateway Vsaas basado en VXG, VPN FortiGate, SSH, Cockpit, escáner y credenciales de cámaras, acceso web por túnel SSH, tráfico, Salud Vsaas, Vista global y observación de 24 horas con descarga de informes a Windows.

El repositorio es público: no necesitas iniciar sesión en GitHub para descargarlo.

```bash
git clone https://github.com/PEPEDATOR-PRO/vsaas-gateway-toolkit.git
cd vsaas-gateway-toolkit
```

Cada organización configura localmente su servidor VPN, su red central y su plataforma Vsaas. Para preparar la VPN una vez por organización:

```bash
cp config/vpn-central.example.json config/vpn-central.json
nano config/vpn-central.json
```

Sustituye los valores de ejemplo por los autorizados en tu FortiGate. Después, el asistente solicita únicamente leftid, subred asignada y PSK por Gateway:

```bash
sudo python3 scripts/install.py vpn --interactive
```

El Gateway Vsaas requiere sus propias credenciales de proveedor y se instala con `sudo python3 scripts/install.py vxg` en equipos nuevos, antes de la administración. Sigue la guía completa para instalar las dependencias y validar cada paso. Publicar el código no proporciona una cuenta de nube, un token del registro ni acceso a una VPN.

## Módulos disponibles

| Módulo | Resultado |
| --- | --- |
| `vxg` | Descarga y arranque inicial de VXG 1.0.16 con credenciales locales |
| `vpn` | strongSwan con conexión IPsec y arranque automático |
| `ssh` | Acceso remoto con OpenSSH |
| `cockpit` | Panel web en la IP de administración, puerto 9090 |
| `paneles` | Escáner de red, Tráfico de red y Salud Vsaas |
| `resumen` | Tarjetas resumidas en la vista global nativa de Cockpit |
| `observacion` | Prueba de tráfico, recursos y salud durante 24 horas |
| `eventos` | Colector opcional ONVIF/RTSP/HTTP, cola local de 2 GB, envío JSON y acceso desde Cockpit |

Los módulos de administración reutilizan el perfil local del equipo; `vxg` no requiere perfil VPN. Ejemplo para instalar solo los paneles:

```bash
sudo python3 scripts/install.py paneles --config config/equipo.json
```

## Estructura

```text
config/              Perfil de ejemplo y perfiles locales ignorados por Git
scripts/             Validación y ejecución modular de instaladores
src/cockpit/         Escáner, tráfico, salud y adaptación de Vista global
src/observacion/     Recopilador de 24 horas y su servicio systemd
vendor/vxg-gateway/  Scripts del proveedor y plantilla sin credenciales
tools/               Generación de instaladores y pruebas de interfaz
docs/                Instalación, operación y mantenimiento
dist/                Instaladores generados y sumas SHA256
```

## Generar instaladores transportables

El módulo opcional `eventos` se instala desde una copia completa del repositorio y requiere construir una imagen Docker. Consulta [Colector de eventos](docs/COLECTOR-EVENTOS.md). No se agrega automáticamente con `todo` ni depende de que exista un perfil JSON antiguo si la IP VPN ya está asignada.

```bash
python3 tools/build.py
```

Genera scripts autónomos en `dist/`, con `SHA256SUMS`. Esto permite llevar una versión concreta a equipos que no tengan Git. Los scripts de paneles incluyen el código fuente necesario. Para una instalación completa con perfil, usa `scripts/install.py` desde una copia de este proyecto.

## Pruebas

```bash
python3 -m unittest discover -s src -p 'test_*.py'
python3 -m unittest discover -s scripts -p 'test_*.py'
npm ci
npx playwright install chromium
npm run test:ui
python3 tools/build.py
```

Las pruebas no instalan servicios ni se conectan a cámaras o servidores reales. La automatización de GitHub ejecuta estas comprobaciones al subir cambios.

Para las pruebas HTTP/ONVIF/RTSP del colector opcional, utiliza un entorno Python de desarrollo separado:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r src/eventos/requirements-dev.txt
PYTHONPATH=src/eventos python -m pytest src/eventos/tests -q
```

## Entorno comprobado y límites

- Puesta en marcha original: Ubuntu 26.10 ARM64, Docker, VXG Uplink Gateway 1.0.16 y strongSwan 6.0.7.
- Acceso VPN, SSH, Cockpit, escáner y paneles comprobados en el Gateway de referencia.
- Prueba de referencia de 24 horas con dos cámaras revisada: monitor alrededor de 0.17% de CPU total y 12.53 MB de JSONL. Son datos de ese equipo, no una garantía de rendimiento ni disponibilidad de video.
- La receta VPN reproduce una configuración heredada IKEv1 de FortiGate. Al cambiar de distribución o versión de strongSwan, comprueba que el paquete incluya ese protocolo y los algoritmos acordados.
- Las tarjetas de Vista global son una adaptación local reversible. Pueden necesitar reaplicarse después de actualizar Cockpit.
- Salud Vsaas separa las señales locales de la confirmación de nube y video. Un proceso activo o un socket TCP no acredita transmisión extremo a extremo.

## Datos por equipo y registros

`config/equipo.json`, perfiles de clientes, claves, tokens, bases de datos, registros y archivos de diagnóstico están excluidos de Git. El perfil de ejemplo no contiene credenciales ni direcciones del equipo de referencia. Cada Gateway necesita una identidad y una red VPN propias.

La prueba de 24 horas continúa en el equipo después de cerrar Cockpit. Sus datos quedan en `/var/log/vsaas-observacion/` y se exportan con `sudo vsaas-observacion exportar`. No subas esos informes al repositorio como parte del código.

## Documentación

- [Guía completa de implementación](docs/GUIA-COMPLETA.md)
- [Instalación y parámetros por equipo](docs/INSTALACION.md)
- [Instalación de VXG desde cero](docs/INSTALACION-VXG.md)
- [Operación, diagnósticos y prueba de 24 horas](docs/OPERACION.md)
- [Colector de eventos adicional](docs/COLECTOR-EVENTOS.md)
- [Mantenimiento y publicación de versiones](docs/MANTENIMIENTO.md)
- [Fuentes técnicas](docs/FUENTES.md)
