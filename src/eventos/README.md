# Colector de eventos integrado

Adaptación para Ubuntu ARM64/x64 del colector ONVIF, RTSP y HTTP desarrollado previamente en el proyecto de cámaras. `PROCEDENCIA.json` registra hashes de los archivos de origen. Se importó solo el código de ejecución y pruebas locales; el fixture de atributos IA se construyó con datos sintéticos.

El módulo del toolkit se instala con `sudo python3 scripts/install.py eventos`. No ejecutes los supervisores de Windows ni compartas el panel por ngrok para este despliegue. El acceso previsto es por la VPN del Gateway, puerto 8081, con llaves propias y un volumen Docker separado.

Consulta [instalación, operación y límites](../../docs/COLECTOR-EVENTOS.md). Las adaptaciones incluyen límite local de 2 GB con retención circular y envío JSON configurable, aviso de espacio en el panel, recursos limitados por Compose y pausa de consultas del navegador cuando está oculto. El servicio de captura continúa aunque el navegador se cierre.
