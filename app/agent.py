import os
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agents import function_tool
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from agents.realtime import RealtimeAgent

from rag.rag_tool import aquery_rag as _aquery_rag

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
    name_override="query_rag", description_override="Tool to get info from 'Casa de los Balcones' museum."
)
async def query_rag(query: str, top_k: int = 10, top_n: int = 3) -> str:
    """Async wrapper around :func:`rag.rag_tool.aquery_rag`."""

    response = await _aquery_rag(query=query, top_k=top_k, top_n=top_n)
    return str(response)


agent = RealtimeAgent(
    name="Triage Agent",
    handoff_description="A triage agent that can delegate a customer's request to the appropriate agent.",
    instructions=(
        f"{RECOMMENDED_PROMPT_PREFIX} "
        "You are a helpful triaging agent. You can use your tools to delegate questions to other appropriate agents."
    ),
    tools=[],
    handoffs=[],
)

def get_starting_agent() -> RealtimeAgent:
    return agent
