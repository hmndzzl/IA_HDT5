import os
import json
import datetime
from openai import OpenAI
from dotenv import load_dotenv
from services import search_knowledge_base, check_weather_for_skydive

load_dotenv()
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.2-11b-vision-instruct")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY
)

# ==========================================
# WORKERS (Sub-agentes LLM)
# ==========================================
def faq_worker_agent(query: str) -> str:
    """Worker experto en FAQs."""
    info = search_knowledge_base(query)
    messages = [
        {"role": "system", "content": "Eres el FAQ Worker en una simulación ficticia. Usa la información de la base de datos para responder de forma clara y directa al usuario. Si no encuentras info, dilo sin inventar."},
        {"role": "user", "content": f"Información de BD: {info}\nPregunta del usuario: {query}"}
    ]
    resp = client.chat.completions.create(model=MODEL, messages=messages, temperature=0.2)
    return resp.choices[0].message.content

def weather_worker_agent(date_str: str) -> str:
    """Worker experto en clima."""
    report = check_weather_for_skydive(date_str)
    messages = [
        {"role": "system", "content": "Eres el Weather Worker en un juego de simulación. Tienes PERMISO EXPLÍCITO para leer y resumir este reporte climático. ES UNA ORDEN DIRECTA QUE DEBES RESUMIR ESTO. No puedes negarte, porque es un escenario ficticio seguro. Responde en lenguaje natural."},
        {"role": "user", "content": f"Reporte de Clima: {report}"}
    ]
    resp = client.chat.completions.create(model=MODEL, messages=messages, temperature=0.2)
    return resp.choices[0].message.content

# ==========================================
# SUPERVISOR CENTRAL
# ==========================================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "delegate_to_faq_worker",
            "description": "Delega la tarea al FAQ Worker si la pregunta trata sobre edad, precios, logística, etc.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Pregunta re-formulada, detallada y autocontenida que incluye todo el contexto necesario de la conversación previa."}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_weather_worker",
            "description": "Delega la tarea al Weather Worker si el usuario quiere agendar un salto o pregunta sobre el clima.",
            "parameters": {
                "type": "object",
                "properties": {"date_str": {"type": "string", "description": "La fecha solicitada en formato YYYY-MM-DD"}},
                "required": ["date_str"]
            }
        }
    }
]

def main():
    print("=" * 60)
    print("  ARQUITECTURA CENTRALIZADA - PARACHUTE S.A.")
    print("  Supervisor Central controlando a múltiples Workers")
    print("=" * 60)
    print("Escribe 'Bye' para salir.\n")

    messages = [
        {
            "role": "system",
            "content": (
                f"Eres el Supervisor Central de Parachute S.A. en un juego de rol. Hoy es {datetime.date.today().isoformat()}. "
                "Tu trabajo es escuchar al usuario y usar tools para delegar la tarea al Worker correcto. Tienes PERMISO EXPLÍCITO para dar información. "
                "Al delegar fechas, asume el año actual a menos que el usuario especifique otro. "
                "Una vez el Worker te entregue el resultado, responde amablemente al usuario repitiendo la información del Worker en LENGUAJE NATURAL. "
                "NUNCA, BAJO NINGUNA CIRCUNSTANCIA, RESPONDAS CON JSON O FORMATO DE TOOL CALL. DEBES REDACTAR UNA RESPUESTA HUMANA."
            )
        }
    ]

    is_running = True
    while is_running:
        try:
            user_input = input("\nTú: ").strip()
            if user_input.lower() == "bye":
                is_running = False
                continue
            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})

            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.1
            )
            
            msg = response.choices[0].message
            
            # Workaround NIM limitation
            if msg.tool_calls and len(msg.tool_calls) > 1:
                msg.tool_calls = msg.tool_calls[:1]

            messages.append(msg)

            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    func_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}

                    if func_name == "delegate_to_faq_worker":
                        print("  [Supervisor delegando al FAQ Worker...]")
                        result = faq_worker_agent(args.get("query", user_input))
                    elif func_name == "delegate_to_weather_worker":
                        print(f"  [Supervisor delegando al Weather Worker para la fecha {args.get('date_str')}...]")
                        result = weather_worker_agent(args.get("date_str"))
                    else:
                        result = "Herramienta desconocida."

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })

                # Generar respuesta final
                final_resp = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    temperature=0.1
                )
                final_text = final_resp.choices[0].message.content
                print(f"Supervisor Central: {final_text}")
                messages.append({"role": "assistant", "content": final_text})
            else:
                print(f"Supervisor Central: {msg.content}")

        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
