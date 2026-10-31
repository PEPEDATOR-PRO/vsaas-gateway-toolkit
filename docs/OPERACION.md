# Operación y diagnóstico

## Acceso habitual

Conecta FortiClient y utiliza la IP de administración del perfil:

- Gateway: `http://IP_ADMIN`
- Cockpit: `https://IP_ADMIN:9090`
- SSH: `ssh USUARIO@IP_ADMIN`

Escáner y tráfico trabajan sobre la red seleccionada del Gateway. No dependen de que esa red sea accesible directamente desde la computadora del administrador.

## Salud Vsaas

Consulta bajo demanda, con actualización cada 30 segundos opcional. Comprueba contenedores y HEALTHCHECK, reinicios, políticas Docker, recursos, interfaz HTTP, CSS, procesos Uplink, sockets TCP 443 de los proxies, conteos de cámaras en SQLite, persistencia y señales resumidas de registros.

Las cámaras configuradas o habilitadas no equivalen a cámaras online. Los mensajes históricos de WebSocket establecido tampoco prueban una conexión actual. Para confirmar video y estado en nube hace falta comprobar la plataforma VXG por separado.

## Prueba de 24 horas

Inicia esta prueba cuando las cámaras estén transmitiendo y quieras medir tráfico y carga:

```bash
sudo python3 scripts/install.py observacion --config config/equipo.json
```

El recopilador registra tráfico y recursos cada 5 segundos y salud cada 60 segundos. Se ejecuta como `vsaas-observacion.service`, continúa sin navegador y reanuda hasta la fecha final original tras un reinicio. La sesión se detiene al terminar o si alcanza el límite de almacenamiento.

```bash
sudo vsaas-observacion estado
sudo systemctl status vsaas-observacion --no-pager
```

Límites por prueba: 128 MiB de registros, memoria del grupo de procesos limitada a 192 MiB y detención si quedan menos de 512 MiB libres. La memoria observada incluye caché de archivos; el límite no es una estimación de consumo. El archivo comprimido de exportación ocupa espacio adicional.

Los registros son `trafico-recursos.jsonl`, `salud.jsonl`, `eventos.jsonl` cuando corresponde, y `resumen.json`. Este último contiene medias, picos, reinicios, tamaño real de JSONL, proyección de almacenamiento y notas sobre lo que mide cada indicador.

```bash
# Detener antes, conservando los registros
sudo systemctl stop vsaas-observacion

# Exportar preferiblemente después de finalizar
sudo vsaas-observacion exportar
```

El exportador indica la ruta y el tamaño del archivo. Las consultas internas a Docker se contabilizan en los contenedores, mientras que el grupo del recopilador contabiliza sus propios procesos. Las variaciones de CPU no prueban por sí solas que el monitor las cause; compara con otra prueba de carga equivalente para estimar el impacto.

## Errores conocidos

| Síntoma | Acción |
| --- | --- |
| VPN `AUTH_FAILED` | Comprobar PSK y selección de Peer ID en FortiGate; no cambiar cifrados al azar |
| Panel nuevo no aparece | Cerrar sesión, abrir de nuevo y consultar `cockpit-bridge --packages` |
| Lista de red vacía | Confirmar IPv4 y revisar el resultado del lector `interfaces` |
| SSH no responde | Revisar `ssh.socket`, escucha TCP 22 y políticas de la VPN |
| Aviso `fwupd-refresh` | Consultar su registro; actualizar metadatos y volver a ejecutar el servicio si corresponde |
| VXG activo pero sin video | Revisar señales locales, cámaras y plataforma; un contenedor en marcha no basta |

## Recuperar estilos del Gateway

En el caso diagnosticado, `/vol/static/css/styles.css` estaba vacío y `/code/server/static/css/styles.css` conservaba una copia válida. Comprueba ambas condiciones antes de copiar:

```bash
sudo docker exec camera_agent_gateway-app-1 sh -c 'ls -l /vol/static/css/styles.css /code/server/static/css/styles.css'
```

Tras confirmar el archivo vacío y la copia válida:

```bash
sudo docker exec camera_agent_gateway-app-1 sh -c 'cp -p /vol/static/css/styles.css /vol/static/css/styles.css.bak && cp /code/server/static/css/styles.css /vol/static/css/styles.css'
```

Actualiza el navegador sin caché. Ajusta el nombre del contenedor si el proyecto Compose tiene otro nombre.

## Fallo de actualización de metadatos de firmware

El servicio `fwupd-refresh` actualiza el catálogo de firmware y los avisos de inicio de sesión; es independiente del servicio VXG. En el fallo diagnosticado se resolvió reintentando el catálogo y volviendo a ejecutar la unidad:

```bash
sudo journalctl -u fwupd-refresh.service -b -n 60 --no-pager
sudo fwupdmgr refresh --force
sudo systemctl restart fwupd-refresh.service
sudo systemctl status fwupd-refresh.service --no-pager -l
```

`refresh` descarga metadatos; no instala firmware. Un servicio de ejecución puntual puede quedar `inactive (dead)` después de terminar correctamente. Comprueba las líneas `Finished` o `Deactivated successfully` y no solo el código numérico. Si la descarga muestra otro error, diagnostícalo antes de deshabilitar el servicio.

## Salud de la VPN

En **Salud Vsaas**, pulsa **Comprobar ahora**. La sección VPN muestra servicio strongSwan, IKE establecido, túnel `administracion` instalado, tiempo de sesión IKE y contadores IPsec recibidos/enviados. Vista global incluye el estado al actualizar el resumen. Se consulta `swanctl --list-sas --ike gateway --raw` con tiempo límite y solo se exportan campos resumidos; no se leen archivos de claves.

Conectada requiere IKE establecido y un CHILD SA de administración instalado. Un servicio activo por sí solo no confirma el túnel. Cero bytes recibidos no implica un fallo; los contadores no son un histórico y pueden cambiar al renovar asociaciones. Estas señales tampoco prueban acceso desde FortiClient ni transmisión de cámaras.

La consulta es bajo demanda; la opción de 30 segundos se detiene al ocultar Salud Vsaas. No se instala un recolector permanente nuevo. Sin permisos, configuración o una respuesta válida, aparece sin confirmar.

## Credenciales y acceso web de cámaras

En **Escáner de red**, busca equipos y utiliza las acciones de la fila correspondiente:

- **Probar credenciales**: elige protocolo, puerto y ONVIF o HTTP Basic/Digest. Introduce una sola combinación y pulsa Probar. El Gateway consulta `/onvif/device_service` o `/` desde la red local. ONVIF usa GetDeviceInformation con UsernameToken digest y admite un desafío HTTP. Solo confirma credenciales si el servicio primero exige autenticación y después acepta la petición. Una página pública, un formulario web o una respuesta incompatible quedan sin confirmar. El usuario ONVIF puede ser diferente del administrador web; permisos y reloj de la cámara también pueden causar rechazo. Esta prueba no verifica RTSP ni video.
- **Acceder a su web**: elige el puerto de la cámara, usuario Ubuntu del Gateway y un puerto libre en tu computadora. Pulsa Preparar acceso SSH. Copia el comando mostrado y ejecútalo en PowerShell o una terminal **de tu computadora**, con FortiClient conectado. Introduce la contraseña de Ubuntu cuando SSH la solicite; después abre el enlace local. Mantén la terminal abierta. Ctrl+C cierra el túnel. Para dos cámaras simultáneas utiliza puertos locales distintos.

Si SSH no está instalado en el Gateway:

```bash
cd ~/vsaas-gateway-toolkit
sudo python3 scripts/install.py ssh
```

FortiGate debe permitir TCP 22 desde tu VPN hasta el Gateway y el servidor SSH debe permitir reenvío TCP. La herramienta prepara un comando; no ejecuta SSH en tu computadora ni declara el túnel abierto. El puerto se enlaza exclusivamente a `127.0.0.1` en tu equipo. Si el puerto está ocupado, elige otro. Algunas webs de cámara usan redirecciones, URLs absolutas o puertos adicionales y pueden necesitar ajustes específicos; no se reescriben sus páginas. HTTPS conserva el certificado de la cámara, que puede no coincidir con localhost.

Las pruebas se limitan a la red local seleccionada, excluyen el propio Gateway, no siguen redirecciones HTTP y no desactivan la validación TLS. Las credenciales se envían por la entrada estándar del proceso, nunca en argumentos ni archivos, y no se incluyen en resultados, CSV ni diagnóstico de salud. La contraseña se borra del formulario al enviar o cerrar. Cerrar el panel o salir cancela la prueba; no se crea un servicio permanente. Los archivos de claves de la VPN no se consultan. HTTP Basic sobre HTTP puede enviar credenciales sin cifrado en el tramo local hacia la cámara. No repitas intentos con datos incorrectos porque la cámara puede bloquear la cuenta.

Referencias del protocolo: [ONVIF Security Configuration](https://onvif.org/specs/srv/security/ONVIF-Security-Service-Spec.pdf), [entrada de procesos en Cockpit](https://cockpit-project.org/guide/latest/cockpit-spawn.html) y [reenvío local OpenSSH](https://man.openbsd.org/ssh#L).
