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

Selecciona un evento para ver el JSON simplificado o su XML. Puedes descargar un solo JSON simple, todos los visibles o el cuerpo original completo. El historial de SQLite no desaparece al quitar una cámara. Los cuerpos y extensiones del fabricante permanecen en el historial, por lo que las exportaciones pueden incluir datos operativos o personales.

## 10. Recursos y almacenamiento

Los límites iniciales de Compose son:

| Recurso | Configuración |
| --- | --- |
| CPU del contenedor | 0.50 CPU, equivalente a medio núcleo; no es 50% de toda una Raspberry de cuatro núcleos |
| Memoria | 384 MiB, sin swap adicional para ese contenedor |
| Procesos | 128 |
| Logs de Docker | Hasta 3 archivos de 5 MB |
| Presupuesto preventivo de SQLite/WAL | 1 GiB |
| Espacio libre reservado antes de guardar | 512 MiB |

Son límites, no mediciones del consumo ni garantías de recepción para cualquier volumen. El presupuesto de eventos es una comprobación previa a cada lote, no una cuota exacta del sistema de archivos; SQLite y sus índices pueden añadir sobrecarga. El límite de datos no incluye imágenes Docker, respaldos ni otros servicios.

El panel muestra espacio utilizado y disponible. Cuando un lote excedería el presupuesto o la reserva de espacio, se rechaza su escritura, se conserva el historial y la entrada HTTP responde 503. Los trabajadores ONVIF/RTSP mantienen el lote pendiente y reintentan; no prometen conservar mensajes que la cámara produzca mientras están bloqueados. No hay eliminación automática por antigüedad.

Si hace falta ajustar el presupuesto, edita como administrador `/opt/vsaas-gateway/eventos/.env` y cambia `COLLECTOR_MAX_DATA_MB`; los recursos de CPU/memoria están en `compose.yaml` del mismo directorio. Conserva los límites compatibles con el Gateway principal y aplica una ventana de mantenimiento:

```bash
sudo systemctl restart vsaas-eventos
sudo vsaas-eventos estado
```

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
git pull --ff-only
sudo python3 scripts/install.py eventos
```

Conserva el proyecto y volumen existentes. La construcción requiere Internet. Si falla antes de actualizar el servicio, el colector anterior no se detiene. El instalador deja un marcador de directorio propio para permitir reintentar una primera construcción incompleta. Un cambio de IP VPN en un despliegue existente necesita revisión deliberada; no se cambia silenciosamente su escucha.

## 13. Qué probar después de instalar

Comprueba contenedor saludable, acceso desde tu VPN y entrada de Cockpit. Agrega primero una cámara de pruebas, genera eventos, revisa sus horas y descarga un original. Reinicia solo el colector y confirma que las cámaras e historial permanecen. Verifica que VXG y las cámaras principales sigan transmitiendo.

La integración del toolkit se prueba con simulaciones, servidores locales HTTP/ONVIF/RTSP y pruebas del navegador. La construcción ARM64 y la recepción real deben verificarse en el Gateway de destino; estas pruebas no instalan Docker ni contactan cámaras de clientes.
