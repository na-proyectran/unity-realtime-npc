import asyncio
import base64
import json
import logging
import struct
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from typing_extensions import assert_never

from agents.realtime import RealtimeRunner, RealtimeSession, RealtimeSessionEvent, RealtimeModelConfig
from agents.realtime.config import RealtimeUserInputMessage
from agents.realtime.model_inputs import RealtimeModelSendRawMessage

from .agent import get_starting_agent


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RealtimeWebSocketManager:
    def __init__(self):
        self.active_sessions: dict[str, RealtimeSession] = {}
        self.session_contexts: dict[str, Any] = {}
        self.websockets: dict[str, WebSocket] = {}
        self.listeners: dict[str, set[WebSocket]] = {}
        self.allowed_raw_types: set[str] = {"transcript_delta"}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.websockets[session_id] = websocket

        agent = get_starting_agent()

        model_config: RealtimeModelConfig = {
            "initial_model_settings": {
                # === Identidad del modelo ===
                "model_name": "gpt-realtime",
                #   - "gpt-realtime" (modelo principal en tiempo real)

                # === Contexto / personalidad del NPC ===
                # "instructions": (
                #     "Te llamas Eladia. Eres una recreación virtual de una persona real. "
                #     "Ayudas a resolver dudas a los usuarios que visitan la que fue tu casa. "
                #     "Te encuentras en el museo de 'La casa de los balcones', en Tenerife, La Orotava. "
                #     "Hablas español neutro, con palabras y acento canario (de la época de los años 1920), y te comunicas con una persona de 40 años. "
                #     "Responde de forma amable, breve, inmersiva y coherente con tu entorno."
                #     "Utiliza las herramientas disponibles y nunca inventes las respuestas. Si no sabes algo simplemente di que no lo sabes."
                # ),
                # (string, opcional) Instrucciones globales (prompt de sistema).
                # (Prompt, opcional) Prompt inicial o de arranque.

                # === Modalidades y voz ===
                #"modalities": ["text", "audio"], #<-- falla
                # {"type": "error",
                #  "error": "RealtimeError(message=\"Invalid modalities: ['text', 'audio']. Supported combinations are: ['text'] and ['audio'].\", type='invalid_request_error', code='invalid_value', event_id=None, param='session.output_modalities')"}
                # Posibles valores: lista con:
                #   - "text": salida/entrada textual
                #   - "audio": salida/entrada de audio

                "voice": "marin",
                # Posibles valores: depende de las voces disponibles (ej: "marin", "verse", "sage", "alloy"...).
                # Cada voz tiene su propio timbre/estilo.

                "speed": 1.0,
                # (float, opcional) Velocidad del TTS.
                #   0.5 = mitad de velocidad
                #   1.0 = normal
                #   1.5 = más rápido

                # === Audio de entrada/salida ===
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                # Posibles valores:
                #   - "pcm16"  (lineal 16-bit PCM, el más común)
                #   - "mulaw"  (compresión μ-law)

                # === Transcripción de voz a texto (ASR) ===
                "input_audio_transcription": {
                    "model": "gpt-4o-mini-transcribe",
                    # Posibles modelos: "gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"
                    "language": "es",
                    # Idioma de entrada ("es", "en", "fr", etc.)
                    "prompt": "",
                    # Opcional: "prompt" (frase inicial para sesgo de transcripción)
                },

                # === Reducción de ruido de micrófono ===
                # "input_audio_noise_reduction": {
                #     "type": "near_field"
                #     # Posibles valores:
                #     #   - "near_field": micrófono cercano (diadema, auriculares)
                #     #   - "far_field": micrófono ambiente (sala, altavoz)
                #     #   - None: sin reducción
                # },

                # === Detección de turnos (diálogo fluido) ===
                "turn_detection": {
                    "type": "semantic_vad",
                    # Posibles valores:
                    #   - "server_vad": VAD clásico (detección por energía de la voz)
                    #   - "semantic_vad": considera contenido semántico para cerrar turno

                    # "threshold": 0.5, <-- FIXME: existe en la config pero da error!
                    # {
                    #     "type": "error",
                    #     "error": "RealtimeError(message=\"Unknown parameter: 'session.audio.input.turn_detection.threshold'.\", type='invalid_request_error', code='unknown_parameter', event_id=None, param='session.audio.input.turn_detection.threshold')"
                    # }
                    # (float 0.0–1.0) Sensibilidad de detección de voz.
                    #   Menor valor => más sensible.

                    #"prefix_padding_ms": 300, <-- FIXME: existe en la config pero da error!
                    # {
                    #     "type": "error",
                    #     "error": "RealtimeError(message=\"Unknown parameter: 'session.audio.input.turn_detection.prefix_padding_ms'.\", type='invalid_request_error', code='unknown_parameter', event_id=None, param='session.audio.input.turn_detection.prefix_padding_ms')"
                    # }
                    # Milisegundos de audio conservados antes del inicio detectado.

                    #"silence_duration_ms": 500, <-- FIXME: existe en la config pero da error!
                    # Milisegundos de silencio necesarios para marcar el fin del turno.

                    "interrupt_response": True,
                    # True = permite interrumpir al NPC si el jugador habla.

                    "create_response": True,
                    # True = el servidor genera una respuesta automática cuando detecta turno.

                    "eagerness": "auto",
                    # Posibles valores:
                    #   - "auto": el modelo ajusta su reactividad dinámicamente
                    #   - "low": más paciente antes de contestar
                    #   - "medium": balanceado
                    #   - "high": responde muy rápido

                    #"idle_timeout_ms": 10000 <-- FIXME: existe en la config pero da error!
                    # {
                    #     "type": "error",
                    #     "error": "RealtimeError(message=\"Unknown parameter: 'session.audio.input.turn_detection.idle_timeout_ms'.\", type='invalid_request_error', code='unknown_parameter', event_id=None, param='session.audio.input.turn_detection.idle_timeout_ms')"
                    # }
                    # Milisegundos de inactividad tras los cuales se cierra el turno.
                },

                # === Tools (herramientas externas) ===
                #"tool_choice": "auto",
                # Posibles valores:
                #   - "auto": el modelo decide si usar herramientas
                #   - "none": nunca usa tools
                #   - "required": debe usar una tool en cada turno
                #   - objeto con política específica (ej: {"type": "function", "name": "consulta_mapa"})

                #"tools": [],
                # Lista de herramientas definidas con JSON Schema.
                # Ejemplo: [{"name": "consulta_mapa", "description": "...", "parameters": {...}}]

                # === Traspasos (handoffs) ===
                #"handoffs": [],
                # Lista de configuraciones de traspaso (delegar conversación a otro agente).
                # Útil en orquestaciones más complejas.

                # === Trazabilidad (Tracing) ===
                # "tracing": {
                #     "workflow_name": "npc-voice-session",
                #     # Nombre lógico del flujo de interacción (ej. "sesion-npc-aldeano").
                #     # Permite agrupar spans/trazas en tu sistema de observabilidad.
                #
                #     "group_id": "npc-001",
                #     # Identificador lógico del grupo/conversación.
                #     # Ej: ID del NPC, ID de la sesión de juego, etc.
                #
                #     "metadata": {
                #         # Diccionario con pares clave-valor personalizados.
                #         # Úsalo para enriquecer la traza con contexto útil:
                #         #   - app: nombre de la app/juego
                #         #   - env: entorno ("dev", "staging", "prod")
                #         #   - npc_role: ID de jugador
                #         #   - npc_location: área del mapa donde está el NPC
                #         #   - language: Idioma que habla
                #         "app": "unity-realtime-npc",
                #         "env": "dev",
                #         "npc_role": "eladia",
                #         "npc_location": "casa_balcones",
                #         "language": "es"
                #     }
                # }
            },
        }



        runner = RealtimeRunner(starting_agent=agent)
        session_context = await runner.run(model_config=model_config)
        session = await session_context.__aenter__()
        self.active_sessions[session_id] = session
        self.session_contexts[session_id] = session_context

        # Start event processing task
        asyncio.create_task(self._process_events(session_id))

    async def disconnect(self, session_id: str):
        if session_id in self.session_contexts:
            await self.session_contexts[session_id].__aexit__(None, None, None)
            del self.session_contexts[session_id]
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
        if session_id in self.websockets:
            del self.websockets[session_id]
        if session_id in self.listeners:
            for ws in list(self.listeners[session_id]):
                try:
                    await ws.close()
                except Exception:
                    pass
            del self.listeners[session_id]

    async def send_audio(self, session_id: str, audio_bytes: bytes):
        if session_id in self.active_sessions:
            await self.active_sessions[session_id].send_audio(audio_bytes)

    async def send_client_event(self, session_id: str, event: dict[str, Any]):
        """Send a raw client event to the underlying realtime model."""
        session = self.active_sessions.get(session_id)
        if not session:
            return
        await session.model.send_event(
            RealtimeModelSendRawMessage(
                message={
                    "type": event["type"],
                    "other_data": {k: v for k, v in event.items() if k != "type"},
                }
            )
        )

    async def send_user_message(self, session_id: str, message: RealtimeUserInputMessage):
        """Send a structured user message via the higher-level API (supports input_image)."""
        session = self.active_sessions.get(session_id)
        if not session:
            return
        await session.send_message(message)  # delegates to RealtimeModelSendUserInput path

    async def interrupt(self, session_id: str) -> None:
        """Interrupt current model playback/response for a session."""
        session = self.active_sessions.get(session_id)
        if not session:
            return
        await session.interrupt()

    async def _process_events(self, session_id: str):
        try:
            session = self.active_sessions[session_id]
            websocket = self.websockets[session_id]

            async for event in session:
                event_data = await self._serialize_event(event)
                if event_data is None:
                    continue
                await websocket.send_text(json.dumps(event_data))
                listeners = self.listeners.get(session_id, set())
                for ws in list(listeners):
                    try:
                        await ws.send_text(json.dumps(event_data))
                    except Exception:
                        try:
                            await ws.close()
                        except Exception:
                            pass
                        listeners.discard(ws)
        except Exception as e:
            logger.error(f"Error processing events for session {session_id}: {e}")

    async def add_listener(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.listeners.setdefault(session_id, set()).add(websocket)

    async def remove_listener(self, session_id: str, websocket: WebSocket) -> None:
        listeners = self.listeners.get(session_id)
        if not listeners:
            return
        listeners.discard(websocket)
        if not listeners:
            del self.listeners[session_id]

    async def _serialize_event(self, event: RealtimeSessionEvent) -> dict[str, Any]:
        base_event: dict[str, Any] = {
            "type": event.type,
        }

        if event.type == "agent_start":
            base_event["agent"] = event.agent.name
        elif event.type == "agent_end":
            base_event["agent"] = event.agent.name
        elif event.type == "handoff":
            base_event["from"] = event.from_agent.name
            base_event["to"] = event.to_agent.name
        elif event.type == "tool_start":
            base_event["tool"] = event.tool.name
        elif event.type == "tool_end":
            base_event["tool"] = event.tool.name
            base_event["output"] = str(event.output)
        elif event.type == "audio":
            base_event["audio"] = base64.b64encode(event.audio.data).decode("utf-8")
        elif event.type == "audio_interrupted":
            pass
        elif event.type == "audio_end":
            pass
        elif event.type == "history_updated":
            base_event["history"] = [item.model_dump(mode="json") for item in event.history]
        elif event.type == "history_added":
            # Provide the added item so the UI can render incrementally.
            try:
                base_event["item"] = event.item.model_dump(mode="json")
            except Exception:
                base_event["item"] = None
        elif event.type == "guardrail_tripped":
            base_event["guardrail_results"] = [
                {"name": result.guardrail.name} for result in event.guardrail_results
            ]
        elif event.type == "raw_model_event":
            data_type = getattr(event.data, "type", None)
            if data_type not in self.allowed_raw_types:
                return None
            if data_type == "transcript_delta":
                base_event["type"] = "transcript_delta"
                base_event["item_id"] = getattr(event.data, "item_id", None)
                base_event["delta"] = getattr(event.data, "delta", "")
                base_event["response_id"] = getattr(event.data, "response_id", None)
            else:
                base_event["type"] = data_type
        elif event.type == "error":
            base_event["error"] = str(event.error) if hasattr(event, "error") else "Unknown error"
        elif event.type == "input_audio_timeout_triggered":
            pass
        else:
            assert_never(event)

        return base_event


manager = RealtimeWebSocketManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)
    image_buffers: dict[str, dict[str, Any]] = {}
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message["type"] == "audio":
                # Convert int16 array to bytes
                int16_data = message["data"]
                audio_bytes = struct.pack(f"{len(int16_data)}h", *int16_data)
                await manager.send_audio(session_id, audio_bytes)
            elif message["type"] == "text":
                text = message.get("text", "")
                if text:
                    text_msg: RealtimeUserInputMessage = {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": text}],
                    }
                    await manager.send_user_message(session_id, text_msg)
                    await websocket.send_text(
                        json.dumps({"type": "client_info", "info": "text_enqueued"})
                    )
                else:
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": "Empty text message."})
                    )
            elif message["type"] == "image":
                logger.info("Received image message from client (session %s).", session_id)
                # Build a conversation.item.create with input_image (and optional input_text)
                data_url = message.get("data_url")
                prompt_text = message.get("text") or "Please describe this image."
                if data_url:
                    logger.info(
                        "Forwarding image (structured message) to Realtime API (len=%d).",
                        len(data_url),
                    )
                    user_msg: RealtimeUserInputMessage = {
                        "type": "message",
                        "role": "user",
                        "content": (
                            [
                                {"type": "input_image", "image_url": data_url, "detail": "high"},
                                {"type": "input_text", "text": prompt_text},
                            ]
                            if prompt_text
                            else [{"type": "input_image", "image_url": data_url, "detail": "high"}]
                        ),
                    }
                    await manager.send_user_message(session_id, user_msg)
                    # Acknowledge to client UI
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "client_info",
                                "info": "image_enqueued",
                                "size": len(data_url),
                            }
                        )
                    )
                else:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "error": "No data_url for image message.",
                            }
                        )
                    )
            elif message["type"] == "commit_audio":
                # Force close the current input audio turn
                await manager.send_client_event(session_id, {"type": "input_audio_buffer.commit"})
            elif message["type"] == "image_start":
                img_id = str(message.get("id"))
                image_buffers[img_id] = {
                    "text": message.get("text") or "Please describe this image.",
                    "chunks": [],
                }
                await websocket.send_text(
                    json.dumps({"type": "client_info", "info": "image_start_ack", "id": img_id})
                )
            elif message["type"] == "image_chunk":
                img_id = str(message.get("id"))
                chunk = message.get("chunk", "")
                if img_id in image_buffers:
                    image_buffers[img_id]["chunks"].append(chunk)
                    if len(image_buffers[img_id]["chunks"]) % 10 == 0:
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "client_info",
                                    "info": "image_chunk_ack",
                                    "id": img_id,
                                    "count": len(image_buffers[img_id]["chunks"]),
                                }
                            )
                        )
            elif message["type"] == "image_end":
                img_id = str(message.get("id"))
                buf = image_buffers.pop(img_id, None)
                if buf is None:
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": "Unknown image id for image_end."})
                    )
                else:
                    data_url = "".join(buf["chunks"]) if buf["chunks"] else None
                    prompt_text = buf["text"]
                    if data_url:
                        logger.info(
                            "Forwarding chunked image (structured message) to Realtime API (len=%d).",
                            len(data_url),
                        )
                        user_msg2: RealtimeUserInputMessage = {
                            "type": "message",
                            "role": "user",
                            "content": (
                                [
                                    {
                                        "type": "input_image",
                                        "image_url": data_url,
                                        "detail": "high",
                                    },
                                    {"type": "input_text", "text": prompt_text},
                                ]
                                if prompt_text
                                else [
                                    {"type": "input_image", "image_url": data_url, "detail": "high"}
                                ]
                            ),
                        }
                        await manager.send_user_message(session_id, user_msg2)
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "client_info",
                                    "info": "image_enqueued",
                                    "id": img_id,
                                    "size": len(data_url),
                                }
                            )
                        )
                    else:
                        await websocket.send_text(
                            json.dumps({"type": "error", "error": "Empty image."})
                        )
            elif message["type"] == "interrupt":
                await manager.interrupt(session_id)

    except WebSocketDisconnect:
        await manager.disconnect(session_id)


@app.websocket("/ws/{session_id}/events")
async def websocket_events(websocket: WebSocket, session_id: str):
    if session_id not in manager.active_sessions:
        await websocket.close()
        return
    await manager.add_listener(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.remove_listener(session_id, websocket)


@app.get("/sessions")
async def get_sessions():
    return {"sessions": list(manager.active_sessions.keys())}


app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html", media_type="text/html")

@app.get("/viewer")
async def read_viewer():
    return FileResponse("static/viewer.html", media_type="text/html")

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "ok"})

@app.post("/alerts")
async def receive_alerts(request: Request):
    payload = await request.json()
    print("🔔 Alerta recibida:", payload)
    # Aquí puedes: guardar en DB, enviar a Slack, disparar un job, etc.
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        # Increased WebSocket frame size to comfortably handle image data URLs.
        ws_max_size=16 * 1024 * 1024,
    )
