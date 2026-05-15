import os
import json
import time
import threading
import datetime
import numpy as np
import requests
from zoneinfo import ZoneInfo
import speech_recognition as sr
import pyttsx3
import pyaudio
from openai import OpenAI
from dotenv import load_dotenv

# 🔑 Cargar variables
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise ValueError("⚠️ No se encontró DEEPSEEK_API_KEY. Revisa tu archivo .env")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# 📁 CONFIG
MEMORY_FILE = "jarvis_memory.json"
SILENCE_THRESHOLD = 2.0
INTERRUPT_KEYWORDS = ["para", "detente", "espera", "no", "cállate", "silencio"]
DEACTIVATE_PHRASES = ["eso es todo", "descansa", "standby", "duerme", "apágate", "chao", "adiós"]
CLAP_THRESHOLD = 2500
CLAP_WINDOW = 0.8
CLAP_COOLDOWN = 2.0

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return {"name": "Usuario", "preferences": [], "notes": []}

def save_memory(data):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

# 🌍 CONTEXTO EN TIEMPO REAL
def get_realtime_context():
    # Fecha y hora (Santa Cruz, Bolivia)
    try:
        tz = ZoneInfo("America/La_Paz")
        now = datetime.datetime.now(tz)
        fecha = now.strftime("%A %d de %B de %Y")
        hora = now.strftime("%H:%M")
    except:
        fecha = hora = "no disponible"

    # Temperatura (Open-Meteo, gratis, sin API key)
    clima = "no disponible"
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=-17.78&longitude=-63.18&current_weather=true&temperature_unit=celsius"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            temp = res.json()["current_weather"]["temperature"]
            clima = f"{int(temp)}°C"
    except:
        pass

    return f"""
CONTEXTO ACTUAL (SOLO PARA TU USO INTERNO):
- Ubicación: Santa Cruz, Bolivia
- Fecha: {fecha}
- Hora local: {hora}
- Temperatura: {clima}
"""

# 🎙️ DETECTOR DE PALMADAS
class ClapDetector:
    def __init__(self, threshold=CLAP_THRESHOLD, window=CLAP_WINDOW):
        self.threshold = threshold; self.window = window; self.running = False
        self.clap_callback = None; self.last_clap_time = 0; self.cooldown = CLAP_COOLDOWN; self.triggered = False
        
    def start(self, callback):
        self.clap_callback = callback; self.running = True
        threading.Thread(target=self._listen_loop, daemon=True).start()
    def stop(self): self.running = False
        
    def _listen_loop(self):
        try:
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        except Exception as e: print(f"❌ Error micrófono: {e}"); self.running = False; return
        print("👂 Detector de palmadas: ACTIVO"); recent_peaks = []
        while self.running:
            try:
                data = stream.read(1024, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                if len(audio_data) == 0: continue
                energy = np.sqrt(np.mean(np.square(audio_data.astype(np.float32))))
                if np.isnan(energy) or np.isinf(energy): continue
                if energy > self.threshold:
                    now = time.time(); recent_peaks.append(now)
                    recent_peaks = [t for t in recent_peaks if now - t <= self.window]
                    if len(recent_peaks) >= 2 and (now - self.last_clap_time) > self.cooldown:
                        if self.clap_callback: self.clap_callback()
                        self.last_clap_time = now; recent_peaks.clear(); time.sleep(1)
            except: time.sleep(0.1)
        try: stream.stop_stream(); stream.close(); p.terminate()
        except: pass

# 🎙️ ESCUCHAR COMANDO
def listen_command(timeout=5):
    r = sr.Recognizer(); r.pause_threshold = SILENCE_THRESHOLD; r.energy_threshold = 350
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=0.8)
        try:
            audio = r.listen(source, timeout=timeout, phrase_time_limit=10)
            text = r.recognize_google(audio, language="es-ES").lower()
            print(f"👤 Tú: {text}"); return text
        except sr.WaitTimeoutError: return None
        except sr.UnknownValueError: return None
        except sr.RequestError: print("❌ Error reconocimiento de voz"); return None

# 🔊 HABLAR
def speak(text, allow_interrupt=True):
    print(f"🤖 JARVIS: {text}")
    engine = pyttsx3.init(); engine.setProperty("rate", 155)
    for v in engine.getProperty("voices"):
        if "spanish" in v.name.lower() or "español" in v.name.lower():
            engine.setProperty("voice", v.id); break
    def listen_interrupt():
        r = sr.Recognizer(); r.energy_threshold = 450
        with sr.Microphone() as src:
            r.adjust_for_ambient_noise(src, duration=0.3)
            try:
                aud = r.listen(src, timeout=0.5, phrase_time_limit=1)
                phrase = r.recognize_google(aud, language="es-ES").lower()
                if any(k in phrase for k in INTERRUPT_KEYWORDS): print(f"⚠️ Interrupción: '{phrase}'"); engine.stop()
            except: pass
    if allow_interrupt: threading.Thread(target=listen_interrupt, daemon=True).start()
    engine.say(text); engine.runAndWait()
    if allow_interrupt: time.sleep(0.3)

# 🧠 PROMPT + IA + MEMORIA
history = []; max_context = 6
def build_system_prompt(mem):
    context = get_realtime_context()
    return f"""Eres JARVIS, mi asistente personal. 
{context}
SOBRE MÍ: Me llamo {mem['name']}, me gusta {', '.join(mem['preferences']) or 'aún no lo sé'}.

REGLAS DE RESPUESTA:
1. Habla natural, SIN markdown, #, *, ni formato técnico. Usa contracciones y español latino.
2. Sé conciso: 3-4 oraciones máximo para respuestas generales.
3. Si te preguntan por hora, fecha o clima, usa el contexto de arriba para responder de forma fluida. NO digas "según mis datos" ni leas la sección de contexto como un robot.
4. Si no sabes algo, dilo honestamente y ofrece ayudar.
5. Si digo "recuerda que...", actualiza mi memoria sin confirmar a menos que te lo pida."""

def get_ai_response(user_input, mem):
    msgs = [{"role": "system", "content": build_system_prompt(mem)}]
    msgs.extend(history[-max_context:])
    msgs.append({"role": "user", "content": user_input})
    resp = client.chat.completions.create(model="deepseek-chat", messages=msgs, temperature=0.6, max_tokens=400)
    return resp.choices[0].message.content.strip()

def update_memory(user_input, mem):
    txt = user_input.lower(); updated = False
    for p in ["me llamo", "mi nombre es", "soy "]:
        if p in txt:
            val = txt.split(p)[-1].split(",")[0].split(".")[0].strip()
            if val and val not in ["usuario", "jarvis"]: mem["name"] = val.capitalize(); updated=True; break
    for p in ["me gusta", "prefiero", "amo"]:
        if p in txt:
            val = txt.split(p)[-1].split("y")[0].split(",")[0].strip().rstrip(".")
            if val and len(val)>2 and val not in mem["preferences"]: mem["preferences"].append(val); updated=True; break
    for p in ["recuerda que", "guárdate que"]:
        if p in txt:
            val = txt.split(p)[-1].strip().rstrip(".")
            if val and val not in mem["notes"]: mem["notes"].append(val); updated=True; break
    if updated: save_memory(mem)
    return mem

# 🔄 FLUJO PRINCIPAL
def standby_mode(clap_det):
    print("😴 JARVIS: En modo standby. Di 'Jarvis' o da dos palmadas para activar.")
    while True:
        txt = listen_command(timeout=3)
        if txt and "jarvis" in txt: print("✨ Activado por voz"); speak("Sí, dime.", allow_interrupt=False); return True
        if clap_det.triggered:
            clap_det.triggered = False; print("✨ Activado por palmadas")
            speak("Te escucho.", allow_interrupt=False); return True
        time.sleep(0.1)

def conversation_mode(mem):
    global history
    while True:
        ui = listen_command()
        if not ui: continue
        if any(ph in ui for ph in DEACTIVATE_PHRASES):
            speak("Entendido. Volviendo a standby.", allow_interrupt=False); time.sleep(1); return
        mem = update_memory(ui, mem)
        try: resp = get_ai_response(ui, mem)
        except Exception as e: resp = "Tuve un problema de conexión. ¿Reintentamos?"; print(f"❌ {e}")
        history.append({"role": "user", "content": ui})
        history.append({"role": "assistant", "content": resp})
        if len(history) > max_context*2: history = history[-max_context*2:]
        speak(resp, allow_interrupt=True)

def main():
    mem = load_memory()
    clap_det = ClapDetector(threshold=CLAP_THRESHOLD, window=CLAP_WINDOW)
    clap_det.start(callback=lambda: setattr(clap_det, 'triggered', True))
    print(f"🤖 JARVIS iniciado. Usuario: {mem['name']}")
    speak(f"Hola {mem['name']}. Estoy en standby. Di 'Jarvis' o da dos palmadas.", allow_interrupt=False)
    try:
        while True:
            if standby_mode(clap_det): conversation_mode(mem)
    except KeyboardInterrupt: print("\n🔚 Cerrando JARVIS..."); clap_det.stop(); save_memory(mem)

if __name__ == "__main__":
    main()