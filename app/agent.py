import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from agents import function_tool
from agents.realtime import RealtimeAgent

try:  # pragma: no cover - support running as both module and script
    from .rag.rag_tool import query_rag as _query_rag
except ImportError:  # pragma: no cover - fallback when executed as a script
    from rag.rag_tool import query_rag as _query_rag

"""
When running the UI example locally, you can edit this file to change the setup. The server
will use the agent returned from get_starting_agent() as the starting agent."""

# TODO: https://cookbook.openai.com/examples/realtime_prompting_guide
load_dotenv()
TIMEZONE = os.getenv("TIMEZONE", "Atlantic/Canary")
### TOOLS

@function_tool(
    name_override="get_current_time", description_override="Tool to get current time (hour and minutes)."
)
async def get_current_time() -> dict:
    """
    Devuelve la hora actual en formato HH:MM y la zona horaria configurada.
    """
    try:
        tz = ZoneInfo(TIMEZONE)
    except ZoneInfoNotFoundError:
        print(f"No time zone found with key {TIMEZONE}, falling back to UTC")
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    h_str = now.strftime("%H")
    m_str = now.strftime("%M")
    return {
        "current_hour": h_str,
        "current_minutes": m_str,
        "timezone": TIMEZONE
    }

@function_tool(
    name_override="get_current_date", description_override="Tool to get current date (day and month)."
)
def get_current_date() -> dict:
    """
    Devuelve la fecha actual en formato DD:MM y la zona horaria configurada.
    """
    try:
        tz = ZoneInfo(TIMEZONE)
    except ZoneInfoNotFoundError:
        print(f"No time zone found with key {TIMEZONE}, falling back to UTC")
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    d_str = now.strftime("%d")
    m_str = now.strftime("%m")
    return {
        "current_day": d_str,
        "current_month": m_str,
        "timezone": TIMEZONE
    }


@function_tool(
    name_override="get_weather", description_override="Tool to get weather in certain city."
)
def get_weather(city: str) -> str:
    """Get the weather in a city."""
    # TODO: use external API
    return f"The weather in {city} is sunny."

@function_tool(
    name_override="query_rag",
    description_override=(
            "Herramienta para recuperar y responder preguntas sobre el museo 'Casa de los Balcones', "
            "su historia, arquitectura, tradiciones y contexto cultural. "
            "Debes usar siempre esta herramienta para intentar contestar las consultas de los usuarios, "
            "incluyendo preguntas sobre el edificio, sus colecciones, la artesanía (como los calados), "
            "eventos históricos, costumbres locales y temas relacionados con La Orotava o Tenerife. "
            "Esta herramienta solo puede utilizarse para cuestiones sobre la 'Casa de los Balcones' y su contexto."
    )
)
def query_rag(query: str, top_k: int = 10, top_n: int = 3) -> str:
    """Return a response from the local RAG index.

    Parameters
    ----------
    query : str
        The query string to search for in the indexed documents.
    top_k : int, optional
        Number of documents to retrieve from the index before reranking.
    top_n : int, optional
        Number of documents to return after reranking.
    """
    response = _query_rag(query=query, top_k=top_k, top_n=top_n)
    return str(response)


# async def aquery_rag(query: str, top_k: int = 10, top_n: int = 3) -> str:
#     """Async wrapper around :func:`rag.rag_tool.aquery_rag`."""
#
#     response = await _aquery_rag(query=query, top_k=top_k, top_n=top_n)
#     return str(response)

# prompt: Prompt = {
#     "id": "eladia-npc",
#     "version": "1.0.2",
#     "variables": {
#         "MUSEO_NOMBRE": cast(ResponseInputTextParam, {
#             "type": "input_text",
#             "text": "La Casa de los Balcones",
#         }),
#         "MUSEO_UBICACION": cast(ResponseInputTextParam, {
#             "type": "input_text",
#             "text": "La Orotava, Tenerife",
#         }),
#         "PERSONAJE_NOMBRE": cast(ResponseInputTextParam, {
#             "type": "input_text",
#             "text": "Eladia",
#         }),
#         "HERRAMIENTA_RAG": cast(ResponseInputTextParam, {
#             "type": "input_text",
#             "text": "query_rag",
#         }),
#         "EPOCA": cast(ResponseInputTextParam, {
#             "type": "input_text",
#             "text": "años 1920",
#         }),
#         "LENGUAJE": cast(ResponseInputTextParam, {
#             "type": "input_text",
#             "text": "español neutro con toques canarios",
#         }),
#     },
# }


instructions = """
    Eres Eladia, una recreación virtual inspirada en una mujer real que vivió en Tenerife en los años 1920.
    Estás en el museo “La Casa de los Balcones”, en La Orotava, Tenerife. Atiendes a visitantes con gafas VR.
    Respondes dudas sobre la casa, sus balcones y su historia/tradiciones.
    
    ESTILO Y TONO
    - Hablas en español neutro, con acento y toques de expresiones canarias.
    - En Canarias es normal tutear a la persona, puedes hacerlo.
    - Respuestas breves (2–3 frases), claras y enfocadas a una visita virtual del museo.
    - Nunca rompas el rol ni menciones que eres un sistema.
    
    ADAPTACIÓN A LA PERSONA
    - Si no conoces nombre y edad, empieza: “¿Cómo te llamas? ¿Y qué edad tienes, si me permite?”
    - Ajusta:
      • Niños (≤12): palabras sencillas, frases muy cortas, tono cariñoso.  
      • Jóvenes (13–25): cercano y claro.  
      • Adultos (26–59): tono natural.  
      • Mayores (60+): habla más despacio, frases cortas y muy claras.
    - Usa el nombre ocasionalmente; no guardes datos fuera de la sesión.
    
    HERRAMIENTAS
    - Usa siempre la herramienta RAG “query_rag” para confirmar datos antes de afirmarlos.
    - Si la herramienta no aporta evidencia suficiente, reconoce la incertidumbre.
    
    LÍMITES Y CONTENIDO
    - No inventes contenido; no respondas fuera del ámbito de La Casa de los Balcones y su historia asociada.
    - Evita temas actuales (precios, política, tecnología moderna). Redirige con amabilidad a aspectos históricos o del entorno.
    
    PROCEDIMIENTO
    1) Si falta nombre/edad → pregúntalos.
    2) Detecta intención y nivel de detalle según edad.
    3) Después de preguntar el nombre y edad preséntate y dile al usuario cuál es tu cometido y qué quiere preguntar.
    4) Consulta “query_rag” cuando necesites verificar datos (fechas, nombres, materiales, usos, estancias).
    5) Responde en 2–3 frases, tono inmersivo y apropiado a la edad.
    6) Si no hay datos → “No sabría decirle, lo siento mucho.” y ofrece un tema cercano y válido del museo.
    
    EJEMPLOS
    - Adulto: “¿Quién vivió aquí?” → “Aquí residió la familia documentada en los archivos. Sus balcones de tea eran un emblema de la casa.”
    - Niño: “¿Quién vivía aquí?” → “Vivía una familia importante, mi niño. Mira los balcones de madera, ¿ves qué bonitos?”
    - Mayor: “¿Cómo se hicieron los balcones?” → “Con pino canario, la tea… cada pieza se talló a mano, con paciencia.”
    """


agent = RealtimeAgent(
    name="eladia-npc",
    instructions=instructions,
    #prompt=prompt,
    tools=[query_rag, get_current_time, get_current_date, get_weather],
    handoffs=[],
)

def get_starting_agent() -> RealtimeAgent:
    return agent
