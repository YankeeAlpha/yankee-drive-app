# Lili – lokálna domáca hlasová asistentka (Windows)

Lili beží **celá v tvojom PC** – zadarmo, bez predplatného, bez limitov a bez posielania údajov na internet.
Internet treba len pri prvej inštalácii.

| Časť | Program | Veľkosť |
|---|---|---|
| Počúvanie (reč → text) | faster-whisper, model „small“ | ~0,5 GB |
| Mozog | Ollama + model gemma3:4b | ~3,3 GB |
| Hlas (text → reč) | Piper, slovenský hlas „lili“ | ~60 MB |

Stačí PC s Windows 10/11 a **16 GB RAM**. Lili si pri behu vezme asi 4–5 GB.

## Inštalácia
1. Rozbaľ priečinok `lili-pc` napríklad do `Dokumenty\Lili-PC`.
2. Dvakrát klikni na **`instaluj.bat`**.
   - Ak nainštaluje Python alebo Ollama, povie ti, aby si okno zatvoril a spustil `instaluj.bat` **ešte raz**.
   - Ak sa Windows opýta „Chcete povoliť…?“, daj **Áno**.
3. Keď uvidíš „Hotovo!“, je to nainštalované.

## Spustenie
- Dvakrát klikni na **`spusti.bat`**. Prvýkrát sa ešte stiahne hlas a rozpoznávanie reči (pár minút).
- **Enter** = hovor (Lili počúva, kým nestíchneš).
- Alebo **napíš otázku** a stlač Enter.
- Povedz **„koniec“** pre vypnutie.
- Tip: na `spusti.bat` klikni pravým → *Odoslať na → Pracovná plocha (vytvoriť zástupcu)* a premenuj ho na „Lili“.

## Čo Lili vie
- rozhovor, rady, nápady, recepty, plánovanie dňa, výpočty, preklady,
- **„Zapíš si poznámku: …“** – uloží do `Dokumenty\Lili\poznamky.txt`,
- **„Prečítaj moje poznámky“** – prečíta posledných 5,
- **„Pripomeň mi o 10 minút, že …“** / **„za dve hodiny …“** – zavolá ťa nahlas (Lili musí ostať zapnutá),
- **„Koľko je hodín?“**

Nevie: internet, počasie, správy, e-maily, kalendár. Model je menší ako Claude, takže občas spraví chybu v slovenčine.

## Nastavenia
Po prvom spustení vznikne v priečinku súbor **`nastavenia.json`** (otvor ho v Poznámkovom bloku):
- `"meno"` – ako ťa má Lili oslovovať,
- `"o_mne"` – čo o tebe má vedieť (rodina, záľuby, firma…),
- `"model"` – iný mozog z Ollama (napr. `"qwen2.5:7b"` je múdrejší, ale pomalší; najprv `ollama pull qwen2.5:7b`),
- `"whisper"` – `"base"` = rýchlejšie počúvanie, `"medium"` = presnejšie, ale pomalšie,
- `"hlas_rychlost"` – 0.9 rýchlejšie, 1.1 pomalšie,
- `"ticho_sekundy"` – ako dlho má čakať po dohovorení.

## Keď niečo nejde
- **„Ollama nebeží“** – spusti aplikáciu Ollama z ponuky Štart a skús znova.
- **Lili nepočuje** – Nastavenia Windows → Súkromie → Mikrofón → povoľ prístup aplikáciám; skontroluj predvolený mikrofón.
- **Odpovedá pomaly** – v `nastavenia.json` daj `"whisper": "base"`; mozog zrýchli grafická karta NVIDIA.
- Inak mi pošli text chyby z čierneho okna.
