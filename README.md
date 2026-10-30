# Vsaas Gateway Toolkit

Herramientas para preparar y administrar Gateways Ubuntu con VXG: VPN IPsec hacia FortiGate, acceso SSH, Cockpit, escáner de red, tráfico en vivo, Salud Vsaas y pruebas de observación de 24 horas.

El código y los instaladores viven en este repositorio. Los datos de cada equipo se mantienen en un perfil local; la clave compartida de la VPN se introduce directamente en Ubuntu al instalar.

## Instalación en otro equipo

Primero instala Ubuntu y el paquete Docker del Gateway mediante el procedimiento de VXG. El toolkit agrega las funciones de administración a esa instalación.

En Ubuntu, abre la carpeta del proyecto y prepara el perfil:

```bash
cp config/equipo.example.json config/equipo.json
nano config/equipo.json
python3 scripts/install.py todo --config config/equipo.json --dry-run
```

Cambia el identificador autorizado en FortiGate, las subredes, la IP de administración, el servidor VPN y la interfaz física. Después aplica:

```bash
sudo python3 scripts/install.py todo --config config/equipo.json
```

`todo` instala VPN, SSH, Cockpit y paneles. Integra las tarjetas en la vista global solo si `overview_overlay` es `true`. La observación de 24 horas se inicia por separado.

Consulta [la guía de instalación](docs/INSTALACION.md) antes de preparar el primer equipo.

## Módulos disponibles

| Módulo | Resultado |
| --- | --- |
| `vpn` | strongSwan con conexión IPsec y arranque automático |
| `ssh` | Acceso remoto con OpenSSH |
| `cockpit` | Panel web en la IP de administración, puerto 9090 |
| `paneles` | Escáner de red, Tráfico de red y Salud Vsaas |
| `resumen` | Tarjetas resumidas en la vista global nativa de Cockpit |
| `observacion` | Prueba de tráfico, recursos y salud durante 24 horas |

Todos aceptan el mismo perfil. Ejemplo para instalar solo los paneles:

```bash
sudo python3 scripts/install.py paneles --config config/equipo.json
```

## Estructura

```text
config/              Perfil de ejemplo y perfiles locales ignorados por Git
scripts/             Validación y ejecución modular de instaladores
src/cockpit/         Escáner, tráfico, salud y adaptación de Vista global
src/observacion/     Recopilador de 24 horas y su servicio systemd
tools/               Generación de instaladores y pruebas de interfaz
docs/                Instalación, operación y mantenimiento
dist/                Instaladores generados y sumas SHA256
```

## Generar instaladores transportables

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

## Entorno comprobado y límites

- Puesta en marcha original: Ubuntu 26.10 ARM64, Docker, VXG Uplink Gateway 1.0.16 y strongSwan 6.0.7.
- Acceso VPN, SSH, Cockpit, escáner y paneles comprobados en el Gateway de referencia.
- El ciclo del recopilador y sus límites tienen pruebas simuladas. El informe de la primera prueba real de 24 horas queda pendiente de revisión.
- La receta VPN reproduce una configuración heredada IKEv1 de FortiGate. Al cambiar de distribución o versión de strongSwan, comprueba que el paquete incluya ese protocolo y los algoritmos acordados.
- Las tarjetas de Vista global son una adaptación local reversible. Pueden necesitar reaplicarse después de actualizar Cockpit.
- Salud Vsaas separa las señales locales de la confirmación de nube y video. Un proceso activo o un socket TCP no acredita transmisión extremo a extremo.

## Datos por equipo y registros

`config/equipo.json`, perfiles de clientes, claves, tokens, bases de datos, registros y archivos de diagnóstico están excluidos de Git. El perfil de ejemplo no contiene credenciales ni direcciones del equipo de referencia. Cada Gateway necesita una identidad y una red VPN propias.

La prueba de 24 horas continúa en el equipo después de cerrar Cockpit. Sus datos quedan en `/var/log/vsaas-observacion/` y se exportan con `sudo vsaas-observacion exportar`. No subas esos informes al repositorio como parte del código.

## Documentación

- [Instalación y parámetros por equipo](docs/INSTALACION.md)
- [Operación, diagnósticos y prueba de 24 horas](docs/OPERACION.md)
- [Mantenimiento y publicación de versiones](docs/MANTENIMIENTO.md)
- [Fuentes técnicas](docs/FUENTES.md)
