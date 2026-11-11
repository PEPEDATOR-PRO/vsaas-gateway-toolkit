# Telemetría de salud y colector de Gateways

Este módulo opcional envía JSON desde Ubuntu hacia uno o varios colectores. Incluye un colector ligero para Windows/Linux y un panel visual. Los avisos de ausencia de reportes y recuperación aparecen únicamente en ese panel; no se envían correos ni Telegram.

## Qué significa cada señal

- **Con reportes**: el colector recibió un reporte autenticado dentro del tiempo configurado.
- **Sin reportes · revisar**: pasó ese tiempo sin recepción. Puede ser un equipo apagado, pérdida de Internet/VPN, agente detenido, firewall, laptop suspendida o ruta interrumpida. No prueba por sí solo que el Gateway esté apagado.
- **Esperando primer reporte**: se registró el equipo pero aún no reporta; también genera aviso si supera su umbral.
- **Salud Vsaas/VPN**: resultado de las comprobaciones locales existentes. Una respuesta HTTP o un contenedor activo no confirman nube ni transmisión de video.

No usa ICMP ni el TTL de los paquetes como estado de salud. Usa un reporte periódico (heartbeat) y un tiempo máximo sin recepción. El colector calcula ese tiempo con su propia recepción; no confía en la fecha del Gateway. Mientras el proceso está activo utiliza tiempo monotónico para detectar la ausencia; tras reiniciarse reconstruye la edad desde los registros de recepción y el reloj de la laptop.

## 1. Instalar el emisor en Ubuntu

Con Cockpit ya instalado:

```bash
cd ~/vsaas-gateway-toolkit
git pull --ff-only
python3 scripts/install.py telemetria --dry-run
sudo python3 scripts/install.py telemetria
```

No necesita `config/equipo.json`. No modifica Docker, cámaras ni la VPN. Genera un ID único del equipo y guarda sus destinos en `/etc/vsaas-gateway/telemetria.json` con permisos restringidos. El servicio `vsaas-telemetria` arranca automáticamente, pero una instalación nueva queda **sin destinos y con envío desactivado**. Las actualizaciones conservan configuración y llaves.

Cierra sesión en Cockpit y vuelve a entrar. Abre **Herramientas → Telemetría de salud**, activa acceso administrativo, pulsa **Consultar configuración** y copia el ID del Gateway. Este ID es independiente del leftid de IPsec.

## 2. Iniciar el colector en la laptop

Requiere Python 3.10 o posterior. No necesita Docker ni instalar paquetes de Python. En PowerShell de Windows, desde una copia del repositorio:

```powershell
cd C:\RUTA\vsaas-gateway-toolkit
git pull --ff-only
py -3 src\telemetria\collector.py --listen 127.0.0.1 --port 8082
```

Esto permite revisar el panel localmente en `http://127.0.0.1:8082`, pero todavía no recibe conexiones desde un Gateway. Para recibirlos, detén con Ctrl+C y sustituye la dirección de escucha por la **IP de esta laptop alcanzable desde los Gateways**:

```powershell
py -3 src\telemetria\collector.py --listen IP_DE_LA_LAPTOP --port 8082
```

En una instalación con FortiClient debe ser normalmente la IP asignada a la laptop por esa VPN. Mantén FortiClient conectado. Confirma en FortiGate que el tráfico iniciado desde el segmento de los Gateways hacia esa IP/puerto está permitido; que puedas abrir Cockpit no confirma que la política permita el sentido inverso. Para una primera prueba en la misma LAN puede usarse la IP LAN de la laptop. No uses como destino la IP del Gateway ni `127.0.0.1`.

La escucha es explícita en una sola IP. Si cambia al reconectar FortiClient, detén/reinicia el colector con la nueva IP y actualiza los destinos. No instala ngrok ni abre puertos en routers. HTTP está previsto para una LAN/VPN de confianza; **este servidor local no debe publicarse directamente en Internet**. Para alojamiento público usa un servidor preparado para producción detrás de HTTPS; los emisores admiten HTTPS y verifican certificados.

Si el Firewall de Windows bloquea las conexiones, permite TCP 8082 únicamente desde la subred VPN autorizada. Ejemplo en PowerShell como administrador, sustituyendo ambos valores:

```powershell
New-NetFirewallRule -DisplayName "Vsaas Salud VPN" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8082 -LocalAddress IP_DE_LA_LAPTOP -RemoteAddress SUBRED_VPN_DE_GATEWAYS
```

No desactives todo el firewall. Revisa también el firewall/políticas del FortiGate. Para retirar esta regla: `Remove-NetFirewallRule -DisplayName "Vsaas Salud VPN"`.

## 3. Entrar al panel y registrar el equipo

En otra ventana PowerShell obtiene la llave administrativa local:

```powershell
py -3 src\telemetria\collector.py --show-key
```

Abre `http://IP_DE_LA_LAPTOP:8082`, pega esa llave y pulsa **Conectar**. No la pongas en URLs, capturas ni archivos del repositorio. La página mantiene la llave solo en memoria; al recargar hay que entrar de nuevo.

En **Registrar un Gateway** introduce su ID, un nombre de sitio y el umbral sin reportes. Se sugieren **120 segundos** para envíos cada **30 segundos**. El panel genera una **llave de envío por equipo**; cópiala en el destino del Gateway. La llave administrativa del panel y la de envío son diferentes. La llave de envío se muestra al crearla o renovarla; no se puede recuperar su texto desde la base. **Renovar llave** invalida la anterior y exige cambiarla en el Gateway.

## 4. Configurar uno o varios destinos desde Cockpit

En **Telemetría de salud → Consultar configuración**:

1. Asigna un nombre al Gateway/sitio y conserva 30 s como intervalo inicial.
2. Pulsa **Agregar destino** y escribe un nombre descriptivo.
3. En URL introduce protocolo, IP/host, puerto y path completos: `http://IP_DE_LA_LAPTOP:8082/api/heartbeat`.
4. Pega la llave de envío de ese equipo generada por ese colector.
5. Activa ese destino y el envío periódico general. Pulsa **Guardar configuración**.
6. Espera un ciclo y vuelve a **Consultar configuración** para comprobar la confirmación HTTP. Comprueba también la tarjeta en el colector.

Para un segundo colector repite el registro del **mismo ID** en ese otro colector y agrega otro destino con su propia llave. Se admiten hasta ocho destinos. Cada uno se intenta independientemente: un destino caído no impide entregar a los demás. Puedes desactivar un destino, quitarlo o editarlo. Dejar su llave vacía conserva la existente solo si la URL sigue siendo idéntica; cambiar la URL exige pegar la llave otra vez. Los cambios se aplican al siguiente ciclo, sin reiniciar Ubuntu.

### IP de origen para IPsec

Si existe `/etc/vsaas-gateway/config.json`, el emisor intenta usar la IP administrativa del Gateway como origen cuando el destino pertenece a la subred remota configurada. También puedes indicar explícitamente **IP de origen opcional** en el destino: debe ser la IP VPN ya asignada a ese Gateway. Es útil en instalaciones antiguas sin perfil, cuando el tráfico saliente usa por defecto la IP LAN y no coincide con los selectores IPsec. No escribe rutas, asigna direcciones ni modifica IPsec. Déjalo vacío para rutas normales o destinos externos que no deben usar esa IP.

## Valores disponibles

| Valor | Alcance |
| --- | --- |
| CPU | Media del host entre dos muestras; primera lectura sin confirmar |
| Memoria | Uso a partir de MemAvailable de Ubuntu |
| Disco | Uso del sistema de archivos raíz; no equivale al tamaño de registros del colector |
| Temperatura | Sensor térmico cuando está disponible |
| Tiempo encendido / boot ID | Ayuda a reconocer reinicios del sistema |
| IP y tráfico por interfaz | IPv4 y contadores de interfaces locales; Mb/s medios entre lecturas, sin captura de paquetes |
| Salud Vsaas | Resultado local, contenedores y conteos configuradas/habilitadas; no confirma cámaras online |
| VPN | Señales de strongSwan/IKE/CHILD_SA del módulo Salud Vsaas |
| Última recepción / ausencia | Tiempo observado por este colector y umbral por equipo |

En un equipo sin reportes se conserva la última lectura, visualmente atenuada. No representa valores actuales. Un fallo de acceso al propio colector muestra un aviso de panel desactualizado.

## Almacenamiento y consumo

- El Gateway mantiene configuración y **un solo estado de ciclo**, sobrescrito. No guarda reportes pendientes ni un historial de salud nuevo. Si un destino falla, el siguiente ciclo envía una muestra nueva, evitando marcar como actual un lote antiguo.
- Por defecto inicia un ciclo cada 30 s; las consultas y entregas tienen límites, pero DNS, carga o problemas de red pueden retrasarlo. No es un monitor de tiempo real estricto. El servicio tiene límites de CPU (20% de un núcleo) y memoria (160 MiB); estos son topes configurados, **no medidas de consumo real**. Si una consulta falla se reporta Sin confirmar.
- En la laptop se guarda `%USERPROFILE%\.vsaas-salud\health.sqlite3` y `admin.token`. El directorio es privado del usuario; no lo compartas ni versiones. En Windows usa una cuenta y permisos de carpeta adecuados.
- Se conservan hasta **7 días o 10 000 muestras en total**, lo que se alcance antes, hasta 1 000 avisos y la última muestra de cada equipo (hasta 500 equipos). Con un Gateway cada 30 s, 10 000 muestras equivalen aproximadamente a 3,47 días; con más equipos, el histórico es menor.
- La base tiene un límite de **256 MiB**, con posible diario temporal de hasta otro tanto. SQLite reutiliza páginas: borrar muestras no implica que el archivo se reduzca. El panel muestra el tamaño actual y número de muestras. Ante falta de capacidad no se confirma la recepción, permitiendo detectar ausencia.
- Cerrar Cockpit no detiene al agente. Cerrar la terminal del colector o suspender la laptop impide la vigilancia. Esta primera versión de laptop se inicia manualmente; para monitoreo permanente conviene un equipo siempre encendido. No instala una tarea automática de Windows.

## Prueba controlada de alertas

Con el Gateway reportando, detén **solo el emisor**:

```bash
sudo systemctl stop vsaas-telemetria
```

Espera el umbral del equipo más hasta unos 5 s de revisión del colector. Debe aparecer **Sin reportes** y un aviso. Las cámaras/VXG continúan funcionando. Después:

```bash
sudo systemctl start vsaas-telemetria
```

El siguiente reporte cambia a Con reportes y registra recuperación. Esta prueba no mide un apagado real ni interrupción de video.

## Diagnóstico y retirada

```bash
sudo systemctl status vsaas-telemetria --no-pager -l
sudo journalctl -u vsaas-telemetria -n 30 --no-pager
sudo python3 /usr/local/libexec/vsaas-telemetria/agent.py config
```

El último comando muestra destinos y confirmaciones, sin llaves. HTTP 401 indica llave incorrecta/no registrada; 404 suele indicar path erróneo; falta de respuesta requiere revisar escucha, VPN, firewall y origen IPsec. No copies el archivo privado de configuración para pedir soporte.

Para detenerlo y quitar el arranque automático sin perder configuración:

```bash
sudo systemctl disable --now vsaas-telemetria
```

El colector se detiene con Ctrl+C. Su base puede copiarse como respaldo con el proceso detenido. No mezclar este historial con el colector de eventos ONVIF, su cola de 2 GB o la observación de 24 horas: son módulos independientes.

## API del colector

`POST /api/heartbeat` recibe un objeto JSON con `schema: 1`, ID y campos permitidos, autenticado mediante `Authorization: Bearer LLAVE_DE_ENVIO`. Los campos desconocidos se descartan; no se transfieren PSK, contraseñas de cámaras ni registros crudos de VXG. La respuesta 200 confirma almacenamiento de ese reporte. Los redirects no se siguen, no se usan proxies del entorno y HTTPS valida certificados. Las otras rutas `/api/status`, `/api/devices`, `/api/device-settings` y `/api/rotate` requieren la llave administrativa. El panel no habilita CORS ni envía llaves en la URL.

El colector de laptop usa [http.server de Python](https://docs.python.org/3/library/http.server.html), destinado aquí a una LAN/VPN privada, con autenticación, tamaño de solicitud limitado y concurrencia acotada. No sustituye un servidor web preparado para exposición pública.
