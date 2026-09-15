import os
import sys
import json
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer

# Cargar variables de entorno
load_dotenv()

# Credenciales de API (NVIDIA NIM compatible con OpenAI SDK)
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.2-11b-vision-instruct")

if not NVIDIA_API_KEY or NVIDIA_API_KEY == "TU_API_KEY_AQUI":
    print("Error: Por favor, configura tu NVIDIA_API_KEY en el archivo .env")
    sys.exit(1)

# Configuración de base de datos PostgreSQL
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "parachute_faqs")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgrespassword")
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Inicializar cliente OpenAI apuntando al endpoint de NVIDIA Build
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY
)

print(f"Cargando modelo local de embeddings '{EMBEDDING_MODEL_NAME}'...")
try:
    embed_model = SentenceTransformer(EMBEDDING_MODEL_NAME, local_files_only=True)
except Exception:
    embed_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

def get_db_connection():
    """Establece conexión con la base de datos PostgreSQL."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        register_vector(conn)
        return conn
    except Exception as e:
        print(f"Error conectando a PostgreSQL: {e}")
        return None

def search_knowledge_base(query: str, limit: int = 3) -> str:
    """Busca preguntas frecuentes en la base de datos vectorial mediante similitud coseno."""
    conn = get_db_connection()
    if not conn:
        return "Error: No se pudo conectar a la base de datos de conocimientos."

    try:
        query_embedding = embed_model.encode(query)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, category, question, answer, 1 - (embedding <=> %s) AS similarity
                FROM faqs
                ORDER BY embedding <=> %s
                LIMIT %s;
            """, (query_embedding, query_embedding, limit))
            results = cur.fetchall()

        conn.close()

        if not results:
            return "No se encontraron registros relevantes en la base de conocimientos."

        # Construir resumen de resultados recuperados
        formatted_results = []
        for r in results:
            faq_id, category, question, answer, similarity = r
            formatted_results.append(
                f"- [Ficha: {faq_id}] (Categoría: {category}, Similitud: {similarity:.2f})\n"
                f"  Pregunta: {question}\n"
                f"  Respuesta oficial: {answer}"
            )

        return "\n\n".join(formatted_results)
    except Exception as e:
        if conn:
            conn.close()
        return f"Error ejecutando búsqueda vectorial: {e}"

# Definición de la herramienta (Tool / Function Call) para el SDK
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Consulta la base de conocimientos vectorial de Parachute S.A. para responder preguntas sobre el evento de paracaidismo (requisitos médicos, límites de peso, edad, logística, precios, ubicación, clima, transporte, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "El término o pregunta clave a buscar en la base de datos de preguntas frecuentes."
                    }
                },
                "required": ["query"]
            }
        }
    }
]

SYSTEM_PROMPT = """Eres el agente inteligente oficial de atención al cliente de Parachute S.A. para el Gran Evento de Paracaidismo Guatemala 2026.
Tu objetivo es brindar respuestas verídicas, claras y profesionales a los usuarios.

REGLAS ESTRICTAS:
1. TIENES LA HERRAMIENTA `search_knowledge_base` a tu disposición. DEBES consultar la base de datos ante cualquier duda o pregunta sobre el evento, logística, normativas, precios, requisitos, etc.
2. DEBES responder ÚNICAMENTE basándote en la información obtenida a través de la herramienta `search_knowledge_base`.
3. Si la consulta del usuario NO puede ser respondida con la información devuelta por la herramienta, o si la pregunta es sobre un tema fuera de Parachute S.A., DEBES admitir amablemente que no posees información sobre ese tema (ejemplo: "Lo siento, no dispongo de información sobre eso en la base de conocimientos de Parachute S.A."). NUNCA inventes o asumas información.
4. Para saludos cordiales o agradecimientos sencillos, puedes responder amablemente sin invocar la herramienta.
5. Mantén un tono formal, amable y conciso.
"""

def main():
    print("=" * 60)
    print("  AGENTE INTELIGENTE DE PREGUNTAS FRECUENTES - PARACHUTE S.A.")
    print(f"  Modelo LLM: {MODEL}")
    print("  Base Vectorial: PostgreSQL + pgvector")
    print("=" * 60)
    print("Escribe 'Bye' para salir, o presiona Ctrl-C.\n")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    is_running = True

    while is_running:
        try:
            user_input = input("\nTú: ").strip()

            if user_input.lower() == "bye":
                print("Agente: ¡Hasta luego! Gracias por contactar a Parachute S.A. Esperamos verte en el evento.")
                is_running = False
                continue

            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})

            # Primera llamada al LLM con soporte para tools
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=1024
            )

            response_message = response.choices[0].message

            # Verificar si el modelo solicitó ejecutar herramientas (Tool Calling)
            if response_message.tool_calls:
                # Guardar el mensaje del asistente con las llamadas a herramientas
                messages.append(response_message)

                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)

                    if function_name == "search_knowledge_base":
                        query = arguments.get("query", user_input)
                        print(f"  [Consultando base de conocimientos para: '{query}'...]")
                        tool_result = search_knowledge_base(query)

                        # Agregar el resultado de la herramienta al historial
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result
                        })

                # Segunda llamada al LLM para generar la respuesta final con la información obtenida
                final_response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=1024
                )

                reply_content = final_response.choices[0].message.content
                print(f"Agente: {reply_content}")
                messages.append({"role": "assistant", "content": reply_content})

            else:
                # Si el modelo respondió directamente (ej. saludos)
                reply_content = response_message.content
                print(f"Agente: {reply_content}")
                messages.append({"role": "assistant", "content": reply_content})

        except KeyboardInterrupt:
            print("\nAgente: Sesión terminada por el usuario (Ctrl-C). ¡Hasta luego!")
            is_running = False
        except EOFError:
            print("\nAgente: Fin de entrada detectado. ¡Hasta luego!")
            is_running = False
        except Exception as e:
            print(f"\n[Error de comunicación]: {e}")
            print("Por favor, intenta tu pregunta nuevamente.")

if __name__ == "__main__":
    main()
