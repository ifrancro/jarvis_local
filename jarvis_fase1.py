import os
import json
import speech_recognition as sr
import pyttsx3
from openai import OpenAI

from dotenv import load_dotenv
load_dotenv()  # ← Carga las variables desde .env

# 🔑 CONFIGURACIÓN
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")  # Configura esta variable en tu sistema o ponla aquí (no recomendado para producción)
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# 📁 ARCHIVO DE MEMORIA
MEMORY_FILE = "jarvis_memory.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"name": "Usuario", "preferences": [], "notes": []}

def save_memory(data):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 🎙️ VOZ: ESCUCHAR
def listen():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("🎙️ Escuchando... (habla ahora)")
        r.adjust_for_ambient_noise(source, duration=0.5)
        audio = r.listen(source, timeout=5, phrase_time_limit=10)
    try:
        text = r.recognize_google(audio, language="es-ES")
        print(f"👤 Tú: {text}")
        return text
    except sr.UnknownValueError:
        print("🔇 No entendí nada.")
        return ""
    except sr.RequestError:
        print("❌ Error con el servicio de reconocimiento de voz.")
        return ""

# 🔊 VOZ: HABLAR
def speak(text):
    print(f"🤖 JARVIS: {text}")
    engine = pyttsx3.init()
    engine.setProperty("rate", 160)  # Velocidad de habla
    # Forzar voz en español (Windows)
    voices = engine.getProperty("voices")
    for v in voices:
        if "spanish" in v.name.lower() or "español" in v.name.lower():
            engine.setProperty("voice", v.id)
            break
    engine.say(text)
    engine.runAndWait()

# 🧠 MEMORIA + CONTEXTO
history = []  # Historial de conversación actual
max_context = 8  # Mantener últimas 8 interacciones para no gastar tokens

def get_ai_response(user_input, memory):
    # Construir prompt del sistema con memoria
    system_prompt = f"""Eres JARVIS, un asistente personal inteligente, leal y eficiente. 
Información sobre tu usuario:
- Nombre: {memory['name']}
- Gustos/Preferencias: {', '.join(memory['preferences']) if memory['preferences'] else 'Aún no compartidos'}
- Notas importantes: {', '.join(memory['notes']) if memory['notes'] else 'Ninguna'}

Responde en español, de forma clara y natural. Si el usuario dice algo como 'recuerda que...' o 'guérdate que...', extráelo mentalmente pero NO lo digas explícitamente a menos que te lo pida."""

    # Preparar mensajes para la API
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-max_context:])  # Contexto reciente
    messages.append({"role": "user", "content": user_input})

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.7,
        max_tokens=512
    )
    return response.choices[0].message.content.strip()

def update_memory_from_input(user_input, memory):
    """Actualización manual simple. En fases avanzadas usaremos IA para extraer datos automáticamente."""
    text = user_input.lower()
    if "me llamo" in text or "mi nombre es" in text:
        name = text.split("llamo")[-1].split("nombre es")[-1].strip().rstrip(".")
        memory["name"] = name.capitalize()
        print(f"💾 Guardado: Nombre = {memory['name']}")
    elif "me gusta" in text or "prefiero" in text:
        pref = text.split("me gusta")[-1].split("prefiero")[-1].strip().rstrip(".")
        if pref not in memory["preferences"]:
            memory["preferences"].append(pref)
            print(f"💾 Guardado: Gusto añadido = {pref}")
    save_memory(memory)
    return memory

# 🔄 BUCLE PRINCIPAL
def main():
    memory = load_memory()
    speak(f"Hola, {memory['name']}. Soy JARVIS. ¿En qué puedo ayudarte hoy?")
    
    while True:
        user_input = listen()
        if not user_input:
            continue
        if any(word in user_input.lower() for word in ["adiós", "chao", "apágate", "sleep"]):
            speak("Hasta pronto. Estaré aquí cuando me necesites.")
            break
            
        # Actualizar memoria si detecta comandos simples
        memory = update_memory_from_input(user_input, memory)
        
        # Obtener respuesta
        try:
            ai_response = get_ai_response(user_input, memory)
        except Exception as e:
            ai_response = "Lo siento, tuve un problema conectando con mi cerebro. Intenta de nuevo."
            print(f"❌ Error API: {e}")
            
        # Guardar en historial
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": ai_response})
        
        # Hablar respuesta
        speak(ai_response)

if __name__ == "__main__":
    main()