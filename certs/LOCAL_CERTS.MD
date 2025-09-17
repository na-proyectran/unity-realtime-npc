# 🔐 Generación y uso de certificados locales

Este documento explica cómo crear certificados **auto-firmados** para
habilitar HTTPS en tu servicio `nginx` dentro del stack Docker.

------------------------------------------------------------------------

## 📦 Requisitos

-   [OpenSSL](https://www.openssl.org/) instalado en tu máquina (viene
    por defecto en la mayoría de sistemas Linux/Mac; en Windows puede
    instalarse con Git Bash o WSL).
-   Carpeta `certs/` en la raíz del proyecto (montada en
    `docker-compose.yml`).

------------------------------------------------------------------------

## 🔧 Pasos para generar certificados auto-firmados

### 1. Crear carpeta para certificados

``` bash
mkdir -p certs
```

### 2. Generar certificado y clave privada

Ejecuta este comando en la raíz del proyecto:

``` bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048   -keyout certs/server.local-key.pem   -out certs/server.local.pem   -subj "/CN=server.local"
```

#### 2.1 Archivos generados

Este comando creará dos archivos en la carpeta `certs/`:

-   `server.local.pem` → el certificado público.
-   `server.local-key.pem` → la clave privada asociada.

#### 2.2 Explicación de parámetros

-   `-x509` → genera un certificado auto-firmado.
-   `-nodes` → no cifra la clave privada (no pide passphrase al usarla).
-   `-days 365` → el certificado será válido por 1 año.
-   `-newkey rsa:2048` → crea una nueva clave RSA de 2048 bits.
-   `-keyout` → ruta donde se guarda la clave privada.
-   `-out` → ruta donde se guarda el certificado.
-   `-subj "/CN=server.local"` → define el Common Name (CN), que debe
    coincidir con el dominio usado (`server.local` en este caso).
