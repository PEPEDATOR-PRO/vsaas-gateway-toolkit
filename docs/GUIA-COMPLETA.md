# Implementación completa de Vsaas Gateway Toolkit

Guía paso a paso para un equipo nuevo, desde Ubuntu hasta el Gateway Vsaas basado en VXG, la administración remota y la observación de 24 horas. Revisada el 3 de noviembre de 2026.

El repositorio es público y se descarga sin cuenta de GitHub. Las imágenes VXG y la conexión con una plataforma Vsaas siguen requiriendo los accesos de tu proveedor. La VPN requiere un FortiGate configurado por tu organización; el toolkit no crea túneles ni políticas en el firewall central.

## 1. Preparar lo necesario

La puesta en marcha de referencia se realizó en Raspberry Pi 5, Ubuntu 26.10 ARM64, VXG Uplink Gateway 1.0.16 y strongSwan 6.0.7. El instalador VXG también contempla x64; otras combinaciones deben validarse antes de desplegarse. Usa un usuario de Ubuntu con `sudo`, conexión a Internet, almacenamiento disponible y una fuente de alimentación adecuada al equipo.

Antes de comenzar, reúne estos datos:

| Dato | Quién lo proporciona | Dónde se utiliza |
| --- | --- | --- |
| Usuario y contraseña de Ubuntu | Administrador del equipo | `sudo`, SSH y Cockpit |
| Usuario y token del registro VXG | Proveedor de Vsaas/VXG | Descargar imágenes Docker |
| `VXG_API_HOST` | Proveedor de Vsaas | Dominio o IP de la plataforma, sin `https://` ni rutas |
| Servidor VPN y subred remota | Administrador de FortiGate | Parámetros comunes de la organización |
| `leftid`, subred propia y PSK | Administrador de FortiGate | Valores únicos del Gateway |
| Usuario ONVIF y contraseña de las cámaras | Administrador de cámaras | Registrar cámaras o probar autenticación |

No reutilices una identidad VPN ni una subred ya asignadas a otro Gateway activo. Los ejemplos de esta guía son ficticios: no proporcionan una VPN ni una plataforma funcionales.

## 2. Distinguir las terminales

Los bloques **Ubuntu** se ejecutan en la Raspberry, en una consola local o por SSH. Su indicador se parece a `ubuntu@ubuntu:~$`.

Los bloques **PowerShell — tu computadora** se ejecutan en Windows, fuera de la sesión SSH. Su indicador se parece a `PS C:\Users\usuario>`. Si estás conectado por SSH, escribe `exit` o abre otra pestaña de PowerShell para ejecutar allí los comandos de descarga y túneles.

## 3. Comprobar Ubuntu, red y reloj

**Ubuntu:**

```bash
cat /etc/os-release
uname -m
ip -4 addr
ip -4 route
timedatectl status
df -h /
```

En Raspberry Pi 5 con Ubuntu de 64 bits debe aparecer `aarch64`. Identifica la interfaz cableada, habitualmente `eth0`, su dirección local y la ruta de salida a Internet. Conecta el Gateway al segmento donde están las cámaras. El escáner ARP solo descubre el segmento local; no atraviesa routers o VLAN distintas.

Comprueba que la fecha sea correcta y que el reloj esté sincronizado antes de medir tiempos o iniciar ONVIF/VPN. Si NTP está desactivado, puedes habilitar el servicio disponible con `sudo timedatectl set-ntp true` y volver a consultar el estado. No cambies manualmente el reloj mientras corre una prueba.

## 4. Instalar dependencias y descargar el repositorio público

**Ubuntu:**

```bash
sudo apt update
sudo apt install -y python3 git nano ca-certificates docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo docker compose version
sudo docker run --rm hello-world
```

Estos son los paquetes utilizados en el Ubuntu de referencia. Si tu distribución no los ofrece, resuelve la instalación de Docker y Compose compatible con ella antes de continuar. No mezcles una instalación existente de Docker con otra sin revisarla.

Para una copia nueva:

```bash
cd ~
git clone https://github.com/PEPEDATOR-PRO/vsaas-gateway-toolkit.git
cd ~/vsaas-gateway-toolkit
git rev-parse --short HEAD
```

Si la carpeta ya existe, usa estos comandos en lugar de clonar de nuevo:

```bash
cd ~/vsaas-gateway-toolkit
git status --short
git pull --ff-only
```

No hace falta `gh auth login`. Si Git solicita autenticación, revisa que `git remote -v` muestre la URL HTTPS pública anterior. Si `git pull` detecta cambios locales en archivos versionados, revísalos antes de actualizar; no los descartes a ciegas.

## 5. Instalar el Gateway Vsaas basado en VXG

Este paso es para un equipo sin un Gateway previo. Si ya funciona, omítelo y continúa con la administración. El módulo `vxg` rechaza un proyecto o directorio existente para evitar reemplazar cámaras y datos; no es un actualizador.

**Ubuntu:**

```bash
cd ~/vsaas-gateway-toolkit
python3 scripts/install.py vxg --dry-run
sudo python3 scripts/install.py vxg
```

El instalador pide el host API de tu plataforma, el usuario/token del registro del proveedor y una contraseña nueva para el administrador del Gateway. La contraseña nueva debe tener al menos 12 caracteres; esta versión no admite comillas simples ni barras invertidas. La cuenta web creada es `admin`; no es la cuenta de Ubuntu.

Si dispones del `.env` original del proveedor, puedes guardarlo fuera del repositorio como `~/vxg-registry.env` y usar la alternativa siguiente **en vez del comando interactivo anterior**:

```bash
chmod 600 ~/vxg-registry.env
sudo python3 scripts/install.py vxg --vxg-env ~/vxg-registry.env
```

Debe incluir las credenciales del registro y el `VXG_API_HOST` correcto. La plantilla pública deja vacíos esos datos; no sirve como credencial. El token se usa por entrada estándar y en una configuración temporal de Docker. No se agrega al entorno de la aplicación. Si entregas un archivo privado, el instalador lo conserva.

El módulo selecciona la versión `1.0.16-arm64` o `1.0.16-x64`. El despliegue se guarda en `/opt/vsaas-gateway/vxg/1.0.16/`. Su `.env` privado contiene las claves de la aplicación y la contraseña de administrador; no lo publiques ni lo pegues en diagnósticos.

## 6. Validar el servicio principal y las cámaras

**Ubuntu:**

```bash
sudo docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Deben aparecer los servicios `app` y `nginx` del proyecto `camera_agent_gateway`. Abre en el navegador `http://` seguido de la IP local del Gateway. Inicia sesión con `admin` y la contraseña elegida. Verifica que la interfaz y sus estilos carguen correctamente.

Registra el Gateway en tu plataforma Vsaas y añade las cámaras siguiendo el procedimiento de tu proveedor. Confirma el video desde la nube antes de continuar con las pruebas de carga. El toolkit no asigna licencias, cuentas o cámaras automáticamente.

Para revisar un arranque fallido sin borrar datos:

```bash
sudo docker logs --tail 80 camera_agent_gateway-app-1
sudo docker logs --tail 80 camera_agent_gateway-nginx-1
```

Estos nombres suponen el proyecto por defecto. Los logs pueden contener información operativa: revísalos antes de compartirlos. No ejecutes `docker compose down -v` para solucionar un error de instalación: eliminaría los volúmenes de datos.

## 7. Preparar la VPN central, una vez por organización

Antes de configurar el Gateway, FortiGate debe tener el túnel y permitir acceso desde los usuarios remotos a la subred asignada, con rutas de retorno. La receta incluida reproduce IKEv1 agresivo con PSK, fase 1 AES-256/SHA-256/DH 5 y fase 2 AES-256/SHA-1/PFS DH 5. No sirve automáticamente para cualquier VPN IPsec, IKEv2, SSL-VPN u OpenVPN. Acuerda los parámetros con el administrador de FortiGate.

**Ubuntu:**

```bash
cd ~/vsaas-gateway-toolkit
cp config/vpn-central.example.json config/vpn-central.json
nano config/vpn-central.json
```

Sustituye los dos valores por los de tu organización:

```json
{
  "vpn_server": "203.0.113.10",
  "vpn_remote_subnet": "172.20.0.0/16"
}
```

`203.0.113.10` es una dirección de documentación y el asistente la rechaza. No la uses para instalar. La red remota es el selector central protegido, no necesariamente la dirección asignada a tu computadora por FortiClient. Este archivo local está ignorado por Git y no lleva PSK.

En equipos previamente configurados, el asistente puede reutilizar los parámetros centrales de `config/equipo.json` si no existe `vpn-central.json`. Actualizar el repositorio no modifica por sí solo el túnel en funcionamiento.

## 8. Configurar los tres datos únicos de cada Gateway

**Ubuntu:**

```bash
sudo python3 scripts/install.py vpn --interactive
```

Introduce:

1. `leftid` autorizado en FortiGate, sin el prefijo `@`.
2. Dirección de **red** y prefijo, por ejemplo `10.254.0.0/29`.
3. Clave compartida del túnel, que no se muestra al escribir.

El asistente calcula el primer host como IP de administración. En el ejemplo sería `10.254.0.1`; ese host debe estar reservado para este Gateway. Guarda los parámetros sin PSK en `config/equipo.json` y en `/etc/vsaas-gateway/config.json`. La PSK se guarda separadamente en un archivo de strongSwan con permisos restringidos; su representación hexadecimal también es secreta.

Para otra IP de administración o parámetros avanzados, utiliza el [perfil manual](INSTALACION.md) y ejecuta `sudo python3 scripts/install.py vpn --config config/equipo.json`, sin `--interactive`.

Verifica el túnel:

```bash
sudo swanctl --list-sas
sudo systemctl status strongswan --no-pager -l
```

Busca `ESTABLISHED` para IKE e `INSTALLED` para el túnel `administracion`. Un servicio activo por sí solo no confirma conectividad. Si falla:

```bash
sudo journalctl -u strongswan -n 60 --no-pager
```

La salida a Internet debe permitir IPsec UDP 500/4500. Las reglas centrales deben permitir los servicios que quieras administrar, como SSH TCP 22, Cockpit TCP 9090 y la web del Gateway TCP 80. No se necesita redirigir puertos públicos del router del cliente para el flujo de conexión saliente previsto.

## 9. Revisar el perfil del equipo

**Ubuntu:**

```bash
sudo nano config/equipo.json
```

Revisa `lan_interface` (`eth0` u otra interfaz física de cámaras), `compose_project` (`camera_agent_gateway` por defecto) y `overview_overlay` (`true` si deseas que una futura ejecución de `todo` incluya Vista global). No cambies los datos VPN por los de otro equipo.

| Campo | Qué debes personalizar |
| --- | --- |
| `vpn_id` | Identidad única autorizada |
| `vpn_local_subnet` | Subred exclusiva del Gateway |
| `vpn_admin_ip` | Host reservado dentro de esa subred |
| `vpn_server` | FortiGate de tu organización |
| `vpn_remote_subnet` | Red central protegida |
| `lan_interface` | Interfaz física que se observará |
| `compose_project` | Proyecto de Docker que Salud Vsaas inspeccionará |
| `overview_overlay` | Integración en Vista global al usar `todo` |

## 10. Instalar SSH

**Ubuntu:**

```bash
sudo python3 scripts/install.py ssh
sudo systemctl status ssh.socket --no-pager
```

El módulo instala OpenSSH y activa su socket. No restringe por sí mismo SSH exclusivamente a la VPN ni modifica reglas de FortiGate/UFW; revisa las reglas de acceso de tu organización.

Conecta FortiClient en tu computadora y prueba:

**PowerShell — tu computadora:**

```powershell
$gatewayAddress = Read-Host "IP de administracion VPN del Gateway"
$gatewayUser = Read-Host "Usuario de Ubuntu del Gateway"
ssh "${gatewayUser}@${gatewayAddress}"
```

Verifica la identidad del servidor al establecer la primera conexión. Inicia sesión con la cuenta de Ubuntu, no con `admin` de VXG. Escribe `exit` para regresar a PowerShell.

## 11. Instalar Cockpit y las herramientas base

**Ubuntu:**

```bash
cd ~/vsaas-gateway-toolkit
sudo python3 scripts/install.py cockpit
sudo systemctl status cockpit.socket --no-pager -l
sudo ss -lntp 'sport = :9090'
```

El instalador incluye Cockpit, `nmap`, `arp-scan` y `htop`. Cockpit escucha en la IP de administración VPN, puerto 9090. Para imprimir la URL correspondiente a tu perfil:

```bash
python3 -c 'import json; d=json.load(open("config/equipo.json")); print("https://"+d["vpn_admin_ip"]+":9090")'
```

Abre esa URL desde tu computadora conectada a la VPN. Usa **HTTPS**. Si aparece un certificado local no confiable, verifica que estás accediendo al Gateway esperado antes de continuar. Inicia sesión con tu cuenta de Ubuntu y activa el acceso administrativo de Cockpit para las comprobaciones que lo requieran.

## 12. Instalar Escáner, Tráfico de red y Salud Vsaas

**Ubuntu:**

```bash
sudo python3 scripts/install.py paneles
```

Cierra sesión en Cockpit y vuelve a entrar. Si el navegador conserva una vista anterior, recarga con Ctrl+Shift+R.

| Panel | Prueba de aceptación |
| --- | --- |
| Escáner de red | Selecciona la interfaz de cámaras y pulsa Buscar equipos; luego Comprobar servicios |
| Tráfico de red | Pulsa Iniciar; comprueba recepción/envío y que Detener finaliza la medición |
| Salud Vsaas | Pulsa Comprobar ahora; revisa contenedores, web, CSS, procesos, recursos y VPN |

Los puertos abiertos son pistas, no identifican por sí solos una cámara. Las cámaras configuradas no equivalen a cámaras online. VPN conectada requiere IKE y túnel instalados; los contadores IPsec pueden reiniciarse al renovar asociaciones y cero tráfico no implica desconexión. Salud Vsaas no confirma video extremo a extremo.

## 13. Probar credenciales y abrir la web de una cámara

En Escáner de red, usa los botones de la fila de la cámara:

**Probar credenciales:** elige protocolo, puerto y ONVIF o autenticación HTTP Basic/Digest. Introduce el usuario de cámara y su contraseña. El resultado puede ser aceptado, rechazado o sin confirmar. Un formulario web o un servicio público no validan automáticamente una contraseña; ONVIF puede necesitar un usuario habilitado y el reloj sincronizado. La herramienta no guarda las credenciales ni las exporta a CSV. No repitas intentos con datos incorrectos porque la cámara puede bloquear la cuenta. HTTP Basic sin HTTPS no cifra la clave en el segmento local.

**Acceder a su web:** selecciona el puerto de la cámara, tu usuario Ubuntu y un puerto local libre, por ejemplo 18080. Pulsa Preparar acceso SSH. Ejecuta el comando generado en **PowerShell de tu computadora**, con FortiClient conectado, e introduce la contraseña de Ubuntu. Mantén esa terminal abierta y abre el enlace local que muestra el panel. Ctrl+C termina el túnel. Para otra cámara simultánea, usa otro puerto local.

El panel prepara el comando; no puede ejecutarlo por ti en Windows. El servidor SSH debe permitir reenvío TCP. Algunas cámaras usan redirecciones, direcciones absolutas o puertos adicionales y pueden no funcionar con un único túnel. Consulta [operación y límites](OPERACION.md#credenciales-y-acceso-web-de-cámaras).

## 14. Agregar el resumen a Vista global

**Ubuntu:**

```bash
sudo python3 scripts/install.py resumen
```

Este módulo actualiza también los archivos de los paneles y reaplica la adaptación de Vista global. No basta con ejecutar una copia antigua de `install-overview-overlay.py`: eso conservaría los recursos anteriores.

Cierra sesión en Cockpit y vuelve a entrar. En **Vista global** deben verse:

- **Salud Vsaas**, con estado local, cámaras y VPN; pulsa Actualizar resumen.
- **Tráfico de red**, con interfaz seleccionable, botón Iniciar/Detener, fondo, cuadrícula, áreas de recepción/envío y escala en Mb/s.

La gráfica conserva hasta 60 segundos y se llena conforme llegan muestras; no crea un historial permanente. Detener o salir de la vista finaliza la lectura. No hace falta reiniciar Ubuntu, Docker ni la VPN para actualizar las tarjetas.

## 15. Verificar reinicio y reconexión automática

En una ventana de mantenimiento, con acceso local disponible y las cámaras autorizadas para la prueba, puedes hacer un reinicio ordenado:

**Ubuntu:**

```bash
sudo reboot
```

La sesión SSH se desconectará. Tras arrancar, verifica que el Gateway Vsaas, strongSwan, SSH y Cockpit vuelven a estar disponibles y que el video regresa en la plataforma. No extrapoles el tiempo de recuperación de un equipo a todos los despliegues. Las comprobaciones locales periódicas no proporcionan el tiempo exacto de interrupción de video.

## 16. Iniciar la prueba de observación de 24 horas

Con las cámaras transmitiendo, confirma primero la interfaz del perfil y el reloj. **Este paso inicia una prueba nueva**; no lo repitas para consultar una sesión existente.

**Ubuntu:**

```bash
cd ~/vsaas-gateway-toolkit
timedatectl status
sudo python3 scripts/install.py observacion
sudo vsaas-observacion estado
sudo systemctl status vsaas-observacion --no-pager -l
```

El recolector continúa al cerrar Cockpit o SSH. Registra tráfico/recursos cada 5 segundos y salud cada 60 segundos. Después de un reinicio intenta continuar hasta el final original; no inicia automáticamente otras 24 horas. Se detiene al finalizar, alcanzar el límite de registros o quedar poco espacio libre.

Límites: 128 MiB de registros por prueba, 192 MiB de memoria del grupo y al menos 512 MiB libres para continuar. La exportación comprimida ocupa espacio adicional. Los registros se guardan en `/var/log/vsaas-observacion/`; cerrar el navegador no los borra.

## 17. Consultar, finalizar y exportar la prueba

Para una prueba que ya está corriendo o terminó:

**Ubuntu:**

```bash
sudo vsaas-observacion estado
sudo systemctl status vsaas-observacion --no-pager -l
```

Un servicio `inactive (dead)` con salida satisfactoria puede corresponder a una prueba completada. Confirma el estado del informe; no lo reinicies solo porque aparece inactivo.

Para detener antes del plazo conservando los registros, usa **solo si deseas interrumpirla**:

```bash
sudo systemctl stop vsaas-observacion
```

Después de finalizar, exporta:

```bash
sudo vsaas-observacion exportar
```

Anota la ruta exacta y el tamaño que imprime. El archivo se crea en el directorio personal del usuario que ejecutó `sudo`, con nombre `sesion-...-vsaas.tar.gz`. No escribas literalmente `NOMBRE_DEL_ARCHIVO`. Si ya existe una exportación con ese nombre, el comando no la sobrescribe.

## 18. Descargar el informe a Windows

Abre PowerShell en tu computadora; **no ejecutes este bloque en `ubuntu@ubuntu:~$`**. Con FortiClient conectado:

```powershell
$gatewayAddress = Read-Host "IP de administracion VPN del Gateway"
$gatewayUser = Read-Host "Usuario de Ubuntu del Gateway"
$gatewayReport = Read-Host "Ruta completa del archivo exportado en Ubuntu"
scp "${gatewayUser}@${gatewayAddress}:$gatewayReport" "$HOME\Downloads\"
```

Como ruta proporciona la que imprimió el exportador, por ejemplo `/home/ubuntu/sesion-...-vsaas.tar.gz`, con el nombre real completo. Introduce la contraseña de Ubuntu. El archivo quedará en Descargas de Windows. Conserva informes operativos fuera del repositorio público.

## 19. Interpretar los resultados

El archivo contiene `resumen.json`, `sesion.json`, `trafico-recursos.jsonl`, `salud.jsonl` y, si se produjeron, `eventos.jsonl`. Revisa duración realmente medida, medias/picos de CPU y RAM, tráfico total del puerto, reinicios, estado local, errores y tamaño de los archivos.

La CPU del monitor se expresa sobre la capacidad total del equipo; Docker usa otra escala y puede superar 100% al utilizar varios núcleos. La memoria del grupo incluye procesos y caché. Las consultas ejecutadas dentro de Docker se contabilizan allí. Para atribuir impacto al monitor, compara otra prueba de carga equivalente sin él.

En una prueba de referencia con dos cámaras se observaron aproximadamente 0.17% de CPU del monitor sobre el total y 12.53 MB de registros sin comprimir. Fue un resultado de ese entorno, no una garantía ni una medida de disponibilidad de video. Hubo un cambio manual de alimentación: la primera comprobación local saludable llegó aproximadamente 1 min 58 s después de la última muestra normal; el tráfico volvió a ser comparable al anterior unos 2 min 25 s después. No debe documentarse como una interrupción de video confirmada de menos de dos minutos.

Si el reloj salta tras un reinicio, compara tiempos de actividad y registros monotónicos; no restes fechas inconsistentes para calcular la interrupción. Un archivo con líneas dañadas debe conservarse para análisis; no ocultes esas muestras ni declares disponibilidad perfecta.

## 20. Actualizar módulos sin repetir toda la instalación

**Ubuntu:**

```bash
cd ~/vsaas-gateway-toolkit
git status --short
git pull --ff-only
sudo python3 scripts/install.py paneles
sudo python3 scripts/install.py resumen
```

Cierra sesión en Cockpit y vuelve a entrar. El módulo `resumen` ya incluye la actualización de recursos, por lo que ejecutarlo solo también sirve para renovar las tarjetas. Los perfiles locales no se sustituyen al descargar el código.

No ejecutes `todo` para una actualización visual: también aplica VPN, SSH y Cockpit. No repitas `vxg` sobre un Gateway en uso. No reinstales el recolector durante una sesión que deseas conservar; exporta y revisa primero el estado.

## 21. Solución rápida de problemas

| Síntoma | Comprobación |
| --- | --- |
| Git pide usuario en un repositorio público | `git remote -v`; comprueba URL y visibilidad; no requiere `gh` |
| VPN no conecta | `sudo swanctl --list-sas` y `sudo journalctl -u strongswan -n 60 --no-pager` |
| Puerto 9090 no abre | Instala `cockpit`; consulta `cockpit.socket`, `ss` y las políticas de FortiGate; usa HTTPS |
| Paneles o gráfica antiguos | `git pull --ff-only`, reinstalar `resumen`, cerrar sesión y volver a entrar |
| Escáner sin interfaces | `ip -4 addr`; necesita una interfaz LAN activa con IPv4 |
| Credenciales sin confirmar | Verifica puerto, usuario ONVIF, reloj y método; usa acceso web para formularios |
| Túnel SSH no abre cámara | SSH activo, TCP 22 permitido, reenvío TCP habilitado, puerto local libre y cámara alcanzable desde Ubuntu |
| `scp` da `/home/ubuntu\Downloads` | Estás en Ubuntu; ejecuta la descarga en PowerShell de Windows |
| Observación inactiva | Consulta `vsaas-observacion estado`; puede haber completado la ventana |

## 22. Referencia de módulos y archivos

| Módulo | Instalación / propósito |
| --- | --- |
| `vxg` | Gateway Vsaas basado en VXG; solo instalación inicial |
| `vpn` | IPsec de administración hacia FortiGate |
| `ssh` | Administración por OpenSSH y base para túneles web |
| `cockpit` | Panel HTTPS y utilidades base |
| `paneles` | Escáner, credenciales, acceso web, tráfico y Salud Vsaas |
| `resumen` | Recursos actualizados y tarjetas en Vista global |
| `observacion` | Sesión nueva de 24 horas, independiente del navegador |
| `todo` | VPN, SSH, Cockpit, paneles y resumen si lo pide el perfil; no instala VXG ni inicia observación |

`config/equipo.json` y `config/vpn-central.json` son archivos locales ignorados por Git. Los datos de cámaras permanecen en los volúmenes de Docker. La adaptación de Cockpit está en `/usr/local/share/cockpit/vsaas_system`; los recursos del toolkit en `/usr/local/share/cockpit/gateway_scanner`. La retirada reversible de las tarjetas y los respaldos están descritos en [mantenimiento](MANTENIMIENTO.md).

Las imágenes y los componentes del proveedor conservan sus condiciones y requieren los accesos correspondientes. Hacer público el toolkit no entrega tokens, PSK, una cuenta de nube ni acceso a una VPN. Consulta también [instalación detallada de VXG](INSTALACION-VXG.md), [operación](OPERACION.md) y [fuentes técnicas](FUENTES.md).
