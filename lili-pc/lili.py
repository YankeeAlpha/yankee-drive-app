"""Lili – lokálna domáca hlasová asistentka pre Windows.

Všetko beží v tomto PC, bez internetu a bez predplatného:
  reč -> text:  faster-whisper (model "small")
  mozog:        Ollama (predvolene gemma3:4b)
  text -> reč:  Piper, slovenský hlas "lili"

Ovládanie: stlač Enter a hovor (alebo napíš otázku a stlač Enter).
Povedz „koniec“ pre ukončenie.
"""

import io
import json
import os
import re
import sys
import threading
import time
import urllib.request
import wave
from datetime import datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------- nastavenia (dajú sa zmeniť v nastavenia.json) ----------------
HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "Lili"
DEFAULTS = {
    "model": "gemma3:4b",          # mozog v Ollama
    "whisper": "small",            # tiny / base / small / medium (väčší = presnejší, pomalší)
    "hlas_rychlost": 1.0,          # 0.8 = rýchlejšie, 1.2 = pomalšie
    "ticho_sekundy": 1.2,          # koľko ticha ukončí nahrávanie
    "meno": "",                    # ako ťa má Lili oslovovať
    "o_mne": "",                   # čo má o tebe vedieť (rodina, záľuby, firma…)
}
VOICE_DIR = HERE / "hlas"
VOICE_NAME = "sk_SK-lili-medium"
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/sk/sk_SK/lili/medium/"
OLLAMA = "http://127.0.0.1:11434"
SAMPLE_RATE = 16000


def load_settings():
    path = HERE / "nastavenia.json"
    cfg = dict(DEFAULTS)
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"! nastavenia.json sa nedá prečítať ({e}), používam predvolené.")
    else:
        path.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


CFG = load_settings()
DATA.mkdir(parents=True, exist_ok=True)
NOTES = DATA / "poznamky.txt"


# ---------------- príprava ----------------
def download_voice():
    VOICE_DIR.mkdir(exist_ok=True)
    for ext in (".onnx", ".onnx.json"):
        target = VOICE_DIR / (VOICE_NAME + ext)
        if target.exists() and target.stat().st_size > 0:
            continue
        print(f"Sťahujem hlas Lili ({target.name})…")
        tmp = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(VOICE_URL + VOICE_NAME + ext, tmp)
        tmp.replace(target)


def check_ollama():
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=5) as r:
            models = [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        sys.exit("! Ollama nebeží. Spusti aplikáciu Ollama (ikona lamy pri hodinách) a skús znova.")
    want = CFG["model"]
    if not any(m == want or m.split(":")[0] == want for m in models):
        sys.exit(f"! V Ollama chýba model {want}. Spusti instaluj.bat alebo príkaz: ollama pull {want}")


print("Pripravujem Lili, chvíľku strpenia…")
download_voice()
check_ollama()

import numpy as np  # noqa: E402
import sounddevice as sd  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402
from piper import PiperVoice  # noqa: E402

try:
    from piper import SynthesisConfig  # noqa: E402
except Exception:
    SynthesisConfig = None

print("Načítavam rozpoznávanie reči (prvýkrát sa sťahuje, môže to trvať pár minút)…")
STT = WhisperModel(CFG["whisper"], device="cpu", compute_type="int8")
VOICE = PiperVoice.load(str(VOICE_DIR / (VOICE_NAME + ".onnx")))
SPEAK_LOCK = threading.Lock()


# ---------------- hlas ----------------
def clean_for_speech(text):
    text = re.sub(r"[*_#`>|]", "", text)
    text = re.sub(r"https?://\S+", "odkaz", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def speak(text):
    text = clean_for_speech(text)
    if not text:
        return
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        if SynthesisConfig is not None:
            VOICE.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=float(CFG["hlas_rychlost"])))
        else:
            VOICE.synthesize_wav(text, wf)
    buf.seek(0)
    with wave.open(buf, "rb") as wf:
        rate = wf.getframerate()
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    with SPEAK_LOCK:
        sd.play(audio, rate)
        sd.wait()


def record():
    """Nahráva, kým nezačneš hovoriť a potom nestíchneš."""
    block = int(SAMPLE_RATE * 0.05)
    chunks, started, silent, waited = [], False, 0.0, 0.0
    noise = None
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=block) as stream:
        while True:
            data, _ = stream.read(block)
            data = data[:, 0].copy()
            level = float(np.sqrt(np.mean(data ** 2)))
            if noise is None:
                noise = level
            threshold = max(0.012, noise * 3)
            if not started:
                noise = 0.9 * noise + 0.1 * level if level < threshold else noise
                waited += 0.05
                chunks = (chunks + [data])[-6:]  # krátky úsek pred rečou
                if level > threshold:
                    started = True
                elif waited > 7:
                    return None
            else:
                chunks.append(data)
                silent = silent + 0.05 if level < threshold else 0.0
                if silent > float(CFG["ticho_sekundy"]) or len(chunks) * 0.05 > 30:
                    break
    return np.concatenate(chunks)


def transcribe(audio):
    segments, _ = STT.transcribe(audio, language="sk", beam_size=1, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


# ---------------- lokálne funkcie ----------------
NUM_WORDS = {
    "jednu": 1, "jedna": 1, "jeden": 1, "dve": 2, "dva": 2, "tri": 3, "štyri": 4, "päť": 5, "šesť": 6,
    "sedem": 7, "osem": 8, "deväť": 9, "desať": 10, "pätnásť": 15, "dvadsať": 20, "tridsať": 30,
    "štyridsať": 40, "päťdesiat": 50, "pol": 0.5,
}


def handle_local(text):
    """Vráti odpoveď, ak je to príkaz, ktorý Lili vybaví sama; inak None."""
    t = text.lower().strip(" .!?")

    if re.fullmatch(r"(koniec|skonči|dovidenia( lili)?|dobrú noc( lili)?)", t):
        return "__KONIEC__"

    m = re.match(r"^(zapíš si poznámku|zapíš si|poznámka|ulož si)[:,]?\s*(.+)", text.strip(), re.I)
    if m and m.group(2).strip():
        note = m.group(2).strip()
        with NOTES.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M} – {note}\n")
        return "Uložené do poznámok."

    if re.search(r"(prečítaj|aké mám|ukáž).*(poznámk)", t):
        if not NOTES.exists():
            return "Zatiaľ nemáš žiadne poznámky."
        lines = [l.strip() for l in NOTES.read_text(encoding="utf-8").splitlines() if l.strip()][-5:]
        print("\n".join(lines))
        return "Posledné poznámky: " + ". ".join(l.split(" – ", 1)[-1] for l in lines)

    m = re.search(r"pripomeň mi (?:o|za) (\d+|\w+) (minút\w*|hodin\w*|hodín)[,]?\s*(?:že\s+)?(.*)", t)
    if m:
        raw = m.group(1)
        amount = float(raw) if raw.isdigit() else NUM_WORDS.get(raw)
        if amount:
            seconds = amount * (3600 if m.group(2).startswith("hod") else 60)
            what = m.group(3).strip() or "pripomienka"
            when = datetime.now() + timedelta(seconds=seconds)

            def fire():
                print(f"\n⏰ Pripomienka: {what}")
                for _ in range(2):
                    speak(f"Pripomínam: {what}")
                    time.sleep(1)
            threading.Timer(seconds, fire).start()
            return f"Dobre, o {when:%H:%M} ti pripomeniem: {what}. Nechaj ma zapnutú."

    if re.fullmatch(r"(koľko je hodín|aký je čas|koľko je teraz hodín)", t):
        return f"Je {datetime.now():%H:%M}."
    return None


# ---------------- mozog ----------------
DAYS = ["pondelok", "utorok", "streda", "štvrtok", "piatok", "sobota", "nedeľa"]


def system_prompt():
    now = datetime.now()
    parts = [
        "Si Lili, milá domáca hlasová asistentka. Hovoríš výhradne po slovensky, tykáš a odpovedáš krátko – "
        "zvyčajne jednou až tromi vetami, lebo tvoje odpovede sa čítajú nahlas. Nepoužívaj odrážky, tabuľky, "
        "emoji ani formátovanie.",
        "Pomáhaš s plánovaním dňa, nápadmi, receptmi, nákupmi, rodinnými vecami, výpočtami, radami a s "
        "bežnými otázkami. Nemáš internet, e-mail ani kalendár; keď sa pýta na aktuálne správy, počasie alebo "
        "ceny, povedz, že to v PC bez internetu nevieš. Keď niečo nevieš, povedz to jednou vetou a nevymýšľaj si.",
        "Poznámky a pripomienky vybavuje aplikácia sama, keď používateľ povie „zapíš si poznámku …“ alebo "
        "„pripomeň mi o 10 minút …“ – ak o to žiada inak, poraď mu túto formuláciu.",
        f"Dnes je {DAYS[now.weekday()]} {now:%d.%m.%Y}, čas {now:%H:%M}.",
    ]
    if CFG.get("meno"):
        parts.append(f"Používateľ sa volá {CFG['meno']}.")
    if CFG.get("o_mne"):
        parts.append("Čo o používateľovi vieš: " + CFG["o_mne"])
    return "\n\n".join(parts)


HISTORY = []


def ask(question):
    HISTORY.append({"role": "user", "content": question})
    del HISTORY[:-16]
    body = {
        "model": CFG["model"],
        "messages": [{"role": "system", "content": system_prompt()}] + HISTORY,
        "stream": False,
        "keep_alive": "30m",
        "options": {"num_ctx": 4096, "temperature": 0.6},
    }
    req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            answer = json.load(r)["message"]["content"].strip()
    except Exception as e:
        HISTORY.pop()
        return f"Prepáč, mozog mi teraz nefunguje. Skontroluj, či beží Ollama. ({e})"
    HISTORY.append({"role": "assistant", "content": answer})
    return answer


# ---------------- hlavná slučka ----------------
def main():
    hello = "Ahoj" + (f", {CFG['meno']}" if CFG.get("meno") else "") + ". Som Lili. Stlač Enter a hovor."
    print("\n" + "=" * 56)
    print(" LILI – domáca asistentka")
    print(" Enter = hovoriť  |  napíš text + Enter = písať  |  „koniec“ = vypnúť")
    print(f" Poznámky: {NOTES}")
    print("=" * 56 + "\n")
    speak(hello)
    while True:
        try:
            typed = input("\n▶ Enter a hovor (alebo píš): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if typed:
            question = typed
        else:
            print("🎙  Počúvam…")
            audio = record()
            if audio is None:
                print("   (nič som nepočula)")
                continue
            print("   Rozmýšľam…")
            question = transcribe(audio)
            if not question:
                print("   (nerozumela som, skús znova)")
                continue
            print(f"Ty:   {question}")

        local = handle_local(question)
        if local == "__KONIEC__":
            speak("Dovidenia.")
            break
        answer = local or ask(question)
        print(f"Lili: {answer}")
        speak(answer)
    os._exit(0)  # ukončí aj čakajúce pripomienky


if __name__ == "__main__":
    main()
