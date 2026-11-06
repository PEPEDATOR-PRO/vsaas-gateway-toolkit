# Colector de eventos como herramienta adicional

Módulo opcional `eventos`, incorporado desde el colector de cámaras desarrollado previamente. Mantiene sus funciones de eventos ONVIF PullPoint, metadatos RTSP/TCP, recepción HTTP, búsqueda, exportación JSON y descarga de originales. Se ejecuta como una aplicación distinta del Gateway Vsaas; no importa sus cámaras, tokens o credenciales.

## 1. Preparar el Gateway

Se necesita Ubuntu de 64 bits, Docker con Compose, la VPN de administración configurada y al menos 2 GiB libres para la instalación. La imagen se construye en el propio Gateway con Python 3.12 y dependencias fijadas. Docker debe poder descargar la imagen base y los paquetes de Python; la primera construcción puede tardar varios minutos. La captura se debe validar con la carga real de cámaras del equipo.

El repositorio público se obtiene sin iniciar sesión en GitHub. En la terminal **Ubuntu del Gateway**:

```bash
cd ~
# Solo si todavía no existe la carpeta:
git clone https://github.com/PEPEDATOR-PRO/vsaas-gateway-toolkit.git
cd ~/vsaas-gateway-toolkit
git pull --ff-only
```

Si la carpeta ya existe, omite `git clone`. No ejecutes una reinstalación de VXG ni de la VPN para agregar este módulo.

## 2. Simular e instalar

```bash
python3 scripts/install.py eventos --dry-run
sudo python3 scripts/install.py eventos
```

No se incluye en `todo`. El módulo reutiliza el perfil si existe; en equipos antiguos también puede identificar la única dirección IPv4 no local asignada a `lo` por la VPN. Si hay varias direcciones o necesitas seleccionarla explícitamente:

```bash
read -r -p 'IP VPN ya asignada a este Gateway: ' gateway_vpn_ip
sudo python3 scripts/install.py eventos --events-ip "$gateway_vpn_ip"
```

La dirección debe estar ya asignada al equipo. El instalador no cambia direcciones ni vuelve a pedir la PSK. Usa puerto 8081 en esa IP VPN y en localhost. Rechaza un puerto ocupado por otro servicio y un proyecto ajeno con el mismo nombre.

El despliegue está en `/opt/vsaas-gateway/eventos`, el proyecto Compose se llama `vsaas_eventos` y el volumen lógico es `collector-data` (normalmente `vsaas_eventos_collector-data`). Las llaves y la base se generan en ese volumen al arrancar. Los datos del colector original de Windows no se copian ni se publican.

## 3. Consultar estado

```bash
sudo systemctl status vsaas-eventos --no-pager -l
sudo vsaas-eventos estado
```

El servicio de systemd puede aparecer `active (exited)` porque inicia un contenedor en segundo plano. Revisa también el estado de Docker y la respuesta local que muestra `vsaas-eventos estado`. Una respuesta HTTP correcta indica que la aplicación responde; no prueba recepción de eventos de las cámaras.

El servicio se ordena después de Docker y strongSwan para que la dirección VPN esté preparada. Compose mantiene `restart: unless-stopped`. Si se reinstala el módulo, primero construye la imagen nueva y luego actualiza solo este servicio; no elimina volúmenes ni opera sobre el proyecto VXG.

## 4. Abrir desde Cockpit o por VPN

Cierra sesión en Cockpit y vuelve a entrar. En las herramientas aparecerá **Colector de eventos**. Pulsa **Consultar estado** y **Abrir panel del colector**. Se abre una pestaña nueva, porque el panel del colector es una aplicación independiente.

La URL es `http://IP_VPN_DEL_GATEWAY:8081`. FortiClient debe estar conectado y FortiGate debe permitir TCP 8081 desde tu acceso administrativo a ese Gateway. Si la web Vsaas o Cockpit funcionan pero este panel no abre, comprueba esa política y `sudo ss -lntp 'sport = :8081'`.

El acceso HTTP utiliza el trayecto VPN previsto; el módulo no crea un certificado HTTPS propio. No publica el puerto en `0.0.0.0` ni en la dirección LAN de cámaras. La entrada HTTP desde una cámara de la LAN necesitaría una ruta y publicación deliberadas; ONVIF PullPoint y RTSP salen desde el colector y no requieren abrir este puerto hacia las cámaras. No se configura ngrok en este módulo.

## 5. Obtener las llaves locales

Para administrar cámaras, en Ubuntu:

```bash
sudo vsaas-eventos llave
```

Copia la salida en **Llave de acceso** del panel y pulsa **Conectar**. La llave pertenece a este colector; no es la contraseña de Ubuntu, de VXG ni la PSK de la VPN. La consulta de estado de Cockpit nunca lee o muestra llaves.

Para compartir solo lectura:

```bash
sudo vsaas-eventos llave-consulta
```

La llave de consulta puede leer el historial y exportar eventos, pero no agregar, quitar ni modificar cámaras. Las llaves no se envían en la URL. Conserva los accesos fuera de Git y no los pegues en capturas o informes públicos.

## 6. Agregar una cámara o NVR por ONVIF

1. Habilita ONVIF y un usuario con permiso de eventos en la cámara o NVR.
2. Sincroniza la hora del Gateway y del dispositivo.
3. En el panel, agrega un nombre, selecciona ONVIF, protocolo HTTP/HTTPS, dirección y puerto ONVIF, usuario y contraseña.
4. Con HTTPS, utiliza un certificado confiable. El panel conserva la opción explícita de certificados propios del colector original.
5. Guarda y revisa el estado. Genera un evento real, como movimiento o una entrada de alarma, y confirma su aparición.

La contraseña de cámara se guarda cifrada con una llave propia del volumen. La API de consulta no la devuelve. El acceso al volumen y a `secret.key` permite recuperar esas credenciales: un respaldo completo debe protegerse.

Se descubren los servicios de eventos y se mantiene una suscripción PullPoint sin un filtro fijo de tipos. Las notificaciones disponibles dependen del modelo, firmware, ajustes y permisos. No se garantiza recuperar eventos producidos mientras la cámara o el colector estaban desconectados.

## 7. Activar metadatos IA por RTSP, si el equipo los ofrece

En la fila del NVR o cámara, pulsa **Metadatos IA** e introduce su URL RTSP de metadatos/canal, sin usuario ni contraseña dentro de la URL. Se reutilizan las credenciales de ese equipo ONVIF y solo se acepta el mismo host registrado.

Un formato de ejemplo, no una dirección real, es:

```text
rtsp://192.0.2.20:554/LiveChannel/0/media.smp
```

La ruta y el puerto cambian por fabricante y configuración. El receptor solicita la pista ONVIF de metadatos, no video ni audio. Su estado aparece separado del de PullPoint. Filtra por `ONVIF/VideoAnalytics/Objects` para revisar objetos y atributos.

Los metadatos continuos pueden generar mucho más volumen que los eventos discretos. Actívalos en pocos equipos al principio y observa el almacenamiento. Deja vacía la URL para desactivar esa recepción. Las clasificaciones del fabricante se preservan como datos; no equivalen a una confirmación de identidad de personas ni a una implementación completa de todo Profile M.

## 8. Entrada HTTP

El modo HTTP crea un identificador y un token exclusivo por cámara. El remitente debe hacer POST a `/ingest/ID` con `Authorization: Bearer TOKEN` o `X-Camera-Token: TOKEN`. El token se muestra al crear esa entrada y no se publica en Git.

Acepta JSON, XML o binario, con un máximo de 8 MiB por mensaje. Solo responde con éxito tras guardar el mensaje. El modo no adapta automáticamente protocolos propietarios que no permiten enviar esos encabezados. Por defecto, el puerto 8081 solo está accesible desde localhost y la VPN; no presupongas que una cámara de otra red puede alcanzar esa URL.

## 9. Explorar, pausar y exportar

El panel carga los eventos más recientes, conserva hasta 500 en la vista y permite filtrar por cámara y tipo. Pausar la vista no detiene la captura; al reanudar recupera los pendientes disponibles. Ocultar la pestaña detiene las consultas periódicas del navegador, mientras la captura sigue en Docker.

Selecciona un evento para ver el JSON simplificado o su XML. Puedes descargar un solo JSON simple, todos los visibles o el cuerpo original completo. Quitar una cámara no borra inmediatamente su cola, que sigue sujeta a envío y retención. Los cuerpos y extensiones del fabricante permanecen en el historial, por lo que las exportaciones pueden incluir datos operativos o personales.

### Consultar capacidades de una cámara

Después de agregar una cámara, con acceso de administración aparece **Consultar capacidades** en su fila. La consulta es bajo demanda y no cambia reglas ni reinicia los lectores de eventos. El informe incluye:

- Resumen del resultado, fabricante, modelo y firmware cuando el equipo los devuelve.
- Tipos de evento y propiedades que anuncia `GetEventProperties`.
- Campos potenciales de la muestra `GetSupportedMetadata`, si se admite.
- Perfiles de medios y, cuando incluyen una configuración analítica, reglas y módulos admitidos de las primeras dos configuraciones.
- Tipos y campos realmente observados en hasta 100 eventos recientes que sigan en la cola local, con un presupuesto de muestras de 2 MiB; se omiten los eventos que no quepan.
- Resultado de cada operación y respuesta XML consultable, con credenciales conocidas ocultas. Las respuestas se recortan a 64 KiB en el informe. Los errores muestran el estado o diagnóstico sin publicar el cuerpo de error.

Puedes **Descargar informe JSON**. El informe se genera al consultar; no se guarda como una nueva fuente de eventos ni se envía automáticamente al destino JSON. En cámaras HTTP se resumen las muestras recibidas, sin efectuar consultas ONVIF. Si no quedan muestras por envío o retención, genera una detección y vuelve a consultar.

La API administrativa es `POST /api/cameras/ID/capabilities`. Permite dos consultas simultáneas, una por cámara; una repetida o con el cupo ocupado devuelve HTTP 409. Las operaciones tienen esperas cortas y se dejan de iniciar consultas tras aproximadamente 65 segundos. No se siguen servicios anunciados en otro host ni redirecciones con las credenciales guardadas.

Una capacidad anunciada no demuestra que esté activada o que se haya recibido en vivo. Una operación fallida tampoco demuestra que el equipo carezca de analíticos. La inspección genérica utiliza ONVIF; no descubre automáticamente las API privadas de todos los fabricantes ni garantiza un inventario completo para cualquier modelo.

## 10. Cola de envío y límite local de 2 GB

El módulo establece `COLLECTOR_MAX_DATA_BYTES=2000000000` y `COLLECTOR_ROLLOVER=1`. Son 2 GB decimales para la base de eventos y su diario SQLite, no 2 GiB. El límite no incluye imágenes Docker, logs de Docker, respaldos ni otros servicios de la Raspberry.

SQLite utiliza un límite de páginas y diario de rollback. Se reserva espacio para que una transacción pueda deshacerse tras un fallo de alimentación: la base dispone de aproximadamente 960 MB y el resto del máximo queda como reserva del diario y su sobrecarga. No significa que esos 2 GB estén ocupados permanentemente. Si una base anterior ya supera el presupuesto de migración, el arranque se detiene conservándola; respalda y revisa su compactación antes de reintentar. No se hace una copia o VACUUM de tamaño ilimitado durante el arranque.

Al alcanzar el límite de la base se eliminan los eventos pendientes más antiguos y se continúa capturando. Esta política puede perder eventos todavía no entregados durante una desconexión prolongada; fue elegida expresamente para priorizar la captura nueva. El contador **Descartados sin enviar** persiste entre reinicios. No se eliminan cámaras, configuración ni llaves. Si todo el disco se queda sin la reserva de 512 MiB, o un solo lote no cabe, se detiene esa escritura y se informa del problema.

Los límites de recursos siguen siendo 0.50 CPU (medio núcleo), 384 MiB de RAM sin swap adicional, 128 procesos y tres archivos de log de Docker de 5 MB. Son límites de ejecución, no una medida de consumo real. El panel muestra espacio ocupado y cola de entrega.

### Configurar el destino JSON

En el panel del colector aparece **Envío de eventos JSON**. Con una llave administrativa configura:

- Protocolo HTTP o HTTPS; HTTPS verifica el certificado.
- IP IPv4 o host, sin protocolo, puerto ni credenciales dentro del campo.
- Puerto y path que comienza con `/`.
- Token Bearer opcional; se guarda cifrado y no se devuelve en la API. Dejarlo vacío conserva el existente solo si no cambian protocolo, host o puerto; al cambiar de servidor no se reenvía automáticamente la credencial del anterior. La casilla correspondiente lo elimina.
- Activar o desactivar el envío automático. Se entrega desactivado hasta que el administrador lo configure.

Guarda primero el destino y pulsa **Probar destino guardado**. Se envía un JSON identificado con `test: true`, sin retirar eventos reales de la cola. El receptor debe aceptar POST con `Content-Type: application/json`. No se usa ngrok, proxy de entorno ni seguimiento de redirecciones. Si configuras un host externo, los eventos saldrán hacia él; no permanecen exclusivamente locales una vez activado el envío.

Cada evento se envía individualmente, por un trabajador secuencial. Valida que la tasa de recepción del servidor supere la de generación; si la cola crece sostenidamente, puede alcanzar el límite aun con el destino disponible. El formato es:

```json
{
  "event_id": "identificador-del-colector:123",
  "type": "camera_event",
  "event": {
    "id": 123,
    "camera_id": "identificador-de-camara",
    "received_at": "2026-01-01T00:00:00Z",
    "source_time": null,
    "topic": "Motion",
    "transport": "onvif",
    "metadata": {"example": true},
    "content_type": "application/soap+xml"
  }
}
```

No se incluyen las contraseñas de cámaras ni `raw_base64`. Sí se envían los metadatos originales interpretados, que pueden contener XML y atributos del fabricante. El receptor responde HTTP 2xx para confirmar aceptación; después se elimina el evento local. Un 2xx acredita aceptación HTTP, no procesamiento completo por el sistema remoto.

Ante fallo de conexión, TLS o respuesta no 2xx, se conserva el evento y se reintenta con espera progresiva hasta 60 segundos. La cola y el destino se conservan al reiniciar. El envío es **al menos una vez**: si el receptor guardó el evento pero la respuesta se perdió, puede recibirlo otra vez. Debe deduplicar usando `event_id`, enviado también como encabezado `Idempotency-Key`. Los pendientes siguen sujetos al descarte por capacidad. Cambiar de destino afecta a toda la cola pendiente; los eventos ya confirmados no se vuelven a enviar al destino nuevo.

La API usa `GET /api/forwarding` para estado, `PUT /api/forwarding` para configurar y `POST /api/forwarding/test` para probar. Solo administración modifica o prueba; una llave de consulta ve el estado sin el token. Cerrar el navegador no detiene el envío. En el panel se muestran pendientes, entregados, descartados y el último resultado.

## 11. Detener, reiniciar y revisar logs

```bash
sudo systemctl stop vsaas-eventos
sudo systemctl start vsaas-eventos
sudo vsaas-eventos estado
sudo vsaas-eventos logs
```

Para desactivar también el arranque automático: `sudo systemctl disable --now vsaas-eventos`. Detener no borra la base ni las llaves. No uses `docker compose down -v` ni elimines el volumen si quieres conservar cámaras, claves e historial.

Para un respaldo consistente, detén la captura en una ventana acordada y respalda **todo** el volumen, incluida la base SQLite, sus archivos auxiliares, `secret.key`, `admin.token` y `viewer.token`; luego vuelve a iniciar el servicio. Las exportaciones de eventos desde el panel son útiles para análisis, pero no sustituyen el respaldo de configuración y llaves.

## 12. Actualizar únicamente esta herramienta

```bash
cd ~/vsaas-gateway-toolkit
git status --short
git pull --ff-only
sudo python3 scripts/install.py eventos
sudo vsaas-eventos estado
sudo systemctl status vsaas-eventos --no-pager -l
```

Conserva el proyecto y volumen existentes. La construcción requiere Internet. Si falla antes de actualizar el servicio, el colector anterior no se detiene. El instalador deja un marcador de directorio propio para permitir reintentar una primera construcción incompleta. Un cambio de IP VPN en un despliegue existente necesita revisión deliberada; no se cambia silenciosamente su escucha.

Estos comandos se ejecutan en la terminal **Ubuntu del Gateway**, dentro de la carpeta del repositorio existente. Si `git status --short` muestra cambios propios, revísalos y consérvalos antes de actualizar; no los descartes para forzar la descarga. Si `git pull --ff-only` falla, detente y resuelve ese aviso antes de ejecutar el instalador.

Para incorporar **Consultar capacidades**, es necesario volver a ejecutar el instalador de `eventos`: descargar el código o reiniciar el contenedor por sí solos no reconstruye la imagen. La actualización conserva el volumen con cámaras, credenciales, llaves y eventos todavía en cola. Hay una interrupción breve de la captura al sustituir el contenedor; la construcción se hace antes de reiniciar el servicio.

Después de actualizar:

1. Recarga el panel del colector con **Ctrl+F5**. Si la entrada de Cockpit no aparece, cierra sesión y vuelve a entrar.
2. Conecta con la llave administrativa existente. Si necesitas consultarla de nuevo, ejecuta `sudo vsaas-eventos llave` en Ubuntu.
3. En una cámara guardada pulsa **Consultar capacidades**. Espera el informe y revisa **Resumen**, los campos anunciados, los recibidos y las respuestas de las consultas. Puedes descargarlo en JSON.
4. Genera una detección y confirma que los eventos siguen llegando. Una respuesta a la consulta de capacidades no confirma por sí sola recepción continua.

Si el servicio no responde, consulta `sudo vsaas-eventos logs`. Para esta actualización utiliza únicamente el módulo `eventos`; no necesitas ejecutar `todo`, `vxg`, `vpn`, `paneles` ni `resumen`.

## 13. Qué probar después de instalar

Comprueba contenedor saludable, acceso desde tu VPN y entrada de Cockpit. Agrega primero una cámara de pruebas, genera eventos, revisa sus horas y descarga un original. Reinicia solo el colector y confirma que las cámaras e historial permanecen. Verifica que VXG y las cámaras principales sigan transmitiendo.

La integración del toolkit se prueba con simulaciones, servidores locales HTTP/ONVIF/RTSP y pruebas del navegador. La construcción ARM64 y la recepción real deben verificarse en el Gateway de destino; estas pruebas no instalan Docker ni contactan cámaras de clientes.
