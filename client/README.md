# Unity Realtime Client

Este ejemplo muestra cómo conectarse al servidor de FastAPI ubicado en `server.py` desde un proyecto de Unity utilizando WebSockets.

## Uso

1. Asegúrate de que el servidor esté en ejecución:
   ```bash
   cd examples/realtime/unity
   uv run python server.py
   ```
2. Copia `RealtimeUnityClient.cs` en tu proyecto de Unity y asígnalo a un `GameObject`.
3. Ejecuta la escena. El cliente se conectará automáticamente y registrará los mensajes recibidos.
4. Llama a `SendText("hola")` o `SendAudio(muestras)` para enviar datos al servidor.

El script utiliza `System.Net.WebSockets` disponible en las versiones modernas de Unity.

## Ejecutar el servidor con Docker

1. Construye la imagen desde la raíz del repositorio para que el contenedor tenga acceso al código del servidor y al SDK:
   ```bash
   docker build -f examples/realtime/unity/client/Dockerfile -t unity-realtime-server .
   ```
2. Inicia el contenedor exponiendo el puerto 8000 (ajusta la variable `OPENAI_API_KEY` con tu clave):
   ```bash
   docker run --rm -p 8000:8000 -e OPENAI_API_KEY=tu_clave unity-realtime-server
   ```
3. Accede a http://localhost:8000 para usar la interfaz web y prueba tu cliente de Unity apuntando al mismo endpoint.
