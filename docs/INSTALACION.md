# Instalación y parámetros por equipo

## Antes de comenzar

Se requiere Ubuntu ARM64 o x86_64 con Python 3, acceso administrativo, Internet y el Gateway VXG ya instalado en Docker. Comprueba los nombres de las interfaces con `ip -4 addr` y los contenedores con `sudo docker ps`.

Si el equipo parte de cero, completa primero [la instalación de VXG](INSTALACION-VXG.md). El módulo `vxg` funciona sin perfil VPN y utiliza credenciales locales del registro del proveedor.

En FortiGate debe existir un túnel con la identidad, clave compartida y selectores de este equipo. Las rutas y políticas deben permitir el tráfico de FortiClient hacia la red de administración del Gateway y de regreso. Se usa salida UDP 500 y 4500 para IPsec; SSH requiere TCP 22 y Cockpit TCP 9090 dentro de la VPN.

## Perfil

```bash
cp config/equipo.example.json config/equipo.json
nano config/equipo.json
```

| Campo | Dónde se utiliza | Regla |
| --- | --- | --- |
| `vpn_id` | Identidad IPsec y selección de la clave | Valor autorizado en FortiGate, sin `@` |
| `vpn_local_subnet` | Selector local IPsec | Red propia de este Gateway |
| `vpn_admin_ip` | Dirección interna `/32` y escucha de Cockpit | IP de host libre dentro de la red anterior |
| `vpn_server` | Destino de la negociación IPsec | Dirección IPv4 del FortiGate central |
| `vpn_remote_subnet` | Selector remoto IPsec | Red central protegida |
| `lan_interface` | Prueba de observación | Interfaz física, por ejemplo `eth0` |
| `compose_project` | Detección de contenedores por etiqueta | Por defecto `camera_agent_gateway` |
| `overview_overlay` | Tarjetas en Vista global | `true` para instalar la adaptación; `false` para usar solo paneles separados |

Los valores de ejemplo son ficticios. No escribas la PSK ni contraseñas en el JSON; el validador rechaza campos adicionales. La PSK se solicita sin mostrarla y se guarda localmente con permisos restringidos. Su representación hexadecimal sigue siendo un secreto.

## Vista previa y aplicación

```bash
python3 scripts/install.py todo --config config/equipo.json --dry-run
sudo python3 scripts/install.py todo --config config/equipo.json
```

La instalación copia el perfil sin secretos a `/etc/vsaas-gateway/config.json`. La inspección de salud utiliza `compose_project` desde ese archivo. No cambia usuarios ni contraseñas existentes.

Para instalar por partes, sustituye `todo` por `vpn`, `ssh`, `cockpit` o `paneles`. `resumen` requiere primero `paneles`; `observacion` requiere Docker y se ejecuta aparte.

## Comprobaciones de aceptación

1. VPN: `sudo swanctl --list-sas` debe mostrar `ESTABLISHED` e `INSTALLED`.
2. SSH: desde una computadora con FortiClient, ejecuta `ssh USUARIO@IP_ADMIN`.
3. Cockpit: abre `https://IP_ADMIN:9090` e inicia sesión con un usuario de Ubuntu.
4. Paneles: cierra sesión y vuelve a entrar. Revisa Escáner de red, Tráfico de red y Salud Vsaas.
5. Escáner: selecciona la interfaz de cámaras y confirma que encuentra equipos.
6. Tráfico: pulsa Iniciar y comprueba las dos direcciones. Detener o salir del panel debe finalizar la lectura.
7. Salud: pulsa Comprobar ahora y revisa las señales; el estado de la nube seguirá separado.
8. Reinicio y reconexión: confirma que VPN, SSH, Cockpit y VXG vuelven a estar disponibles y que las cámaras siguen transmitiendo.

Registra el resultado de estas pruebas en el inventario interno del equipo, separado del código.

## Receta VPN

La receta conserva IKEv1 agresivo con PSK; fase 1 AES-256/SHA-256/DH 5 y fase 2 AES-256/SHA-1/PFS DH 5. Solo sirve para un FortiGate configurado con parámetros equivalentes. No convierte automáticamente otros perfiles VPN ni modifica el FortiGate.

El instalador guarda respaldos de los archivos que sustituye. Para reconfigurar un equipo ya usado, revisa también si queda una dirección anterior en `lo`; no reutilices una identidad activa de otro Gateway.
