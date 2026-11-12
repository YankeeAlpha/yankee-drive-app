# Návod: zapnutie bezpečnostných opráv (Firebase Auth + Firestore pravidlá)

Všetko je **zadarmo** (Firebase plán Spark, GitHub Pages, GitHub Actions). Kartu ani platený plán netreba.

> ⚠️ **Dôležité poradie.** Kroky 1–6 sprav **pred** zlúčením (merge) PR. Krok 8 (pravidlá) sprav **hneď po** merge.
> Ak by si pravidlá zapol skôr, stará verzia aplikácie a vernostného klubu prestane fungovať. Ak by si mergol bez krokov 1–5, nikto sa do aplikácie neprihlási.

Firebase konzola: https://console.firebase.google.com → projekt **yankee-drive-loyality-card**.

## 1. Zapnúť prihlasovanie (Firebase Authentication)
1. V ľavom menu **Build → Authentication** → **Get started**.
2. Karta **Sign-in method**:
   - **Email/Password** → Enable → (prepínač „Email link (passwordless)“ nechaj **vypnutý**) → Save.
   - **Google** → Enable → *Project support email*: `servis@yankeedrive.sk` → Save.
3. Karta **Settings → Authorized domains** → **Add domain** → `yankeealpha.github.io`.
4. Karta **Templates** → ikona ceruzky / **Template language** → **Slovak** (e-maily na overenie a zmenu hesla budú po slovensky).

## 2. Vytvoriť účty obsluhy
Pre každého pracovníka (aj pre seba):
1. **Authentication → Users → Add user**.
2. E-mail (napr. `servis@yankeedrive.sk` alebo osobný e-mail pracovníka) a **silné heslo** (aspoň 12 znakov). Heslo mu odovzdaj osobne.
3. V zozname používateľov skopíruj jeho **User UID** (dlhý reťazec).

## 3. Označiť účty ako obsluhu
1. **Build → Firestore Database → Data** → **+ Start collection**.
2. Collection ID: `staff` → Next.
3. Document ID: vlož **User UID** z kroku 2.
4. Pole: `name` (string) = meno pracovníka (napr. `Ján`) → Save.
5. Pre ďalšieho pracovníka: v kolekcii `staff` → **Add document** → rovnako.

Zrušenie prístupu pracovníka: zmaž jeho dokument v `staff` a v Authentication ho **Disable**.

## 4. Servisný účet pre denný export z Welcomio (GitHub Actions)
1. Ozubené koliesko → **Project settings → Service accounts** → **Generate new private key** → stiahne sa súbor JSON.
2. GitHub: repo **yankee-drive-app → Settings → Secrets and variables → Actions → New repository secret**.
3. Name: `FIREBASE_SERVICE_ACCOUNT`, Secret: vlož **celý obsah** stiahnutého JSON súboru → Add secret.
4. Súbor JSON potom **zmaž z počítača** (aj z koša). Nikdy ho nedávaj do repa.

## 5. Zamknúť prázdnu Realtime Database
**Build → Realtime Database → Rules** → nahraď obsah:
```json
{ "rules": { ".read": false, ".write": false } }
```
→ **Publish**. (Databáza sa nepoužíva a doteraz bola verejne čitateľná.)

## 6. (Odporúčané) Obmedziť API kľúč
Google Cloud Console → projekt yankee-drive-loyality-card → **APIs & Services → Credentials** → kľúč „Browser key (auto created by Firebase)“:
- *Application restrictions*: **Websites** → pridaj `https://yankeealpha.github.io/*` a `https://yankee-drive-loyality-card.firebaseapp.com/*`.
- *API restrictions*: **Restrict key** → vyber **Identity Toolkit API**, **Token Service API**, **Cloud Firestore API** → Save.
Ak by potom prihlasovanie hlásilo chybu, dočasne vráť „Don't restrict key“ a daj mi vedieť.

## 7. Zlúčiť Pull Request
GitHub → **Pull requests** → „Bezpečnostné opravy…“ → **Merge pull request**. GitHub Pages nasadí novú verziu do 1–2 minút.

## 8. Nasadiť Firestore pravidlá (hneď po merge)
1. **Firestore Database → Rules**.
2. Zmaž celý obsah a vlož obsah súboru [`firestore.rules`](../firestore.rules) z repa.
3. **Publish**.
4. (Voliteľne) karta **Rules Playground**: *get* na `customers/niekto@gmail.com` bez prihlásenia musí byť **Denied**.

## 9. Overiť
- Otvor https://yankeealpha.github.io/yankee-drive-app/ → prihlás sa účtom obsluhy → zobrazia sa zákazníci.
- Otvor vernostný klub → prihlás sa Google účtom zákazníka (alebo si vytvor testovací účet e-mail + heslo a potvrď e-mail).
- Nainštalovaná aplikácia v Chrome sa aktualizuje sama (prípadne ju raz zatvor a otvor).

## 10. Vymazať osobné údaje z histórie repa (spúšťaš sám, je to nevratné)
Súbory s údajmi zákazníkov sú síce zo stromu odstránené, ale **zostávajú v histórii commitov** (a v starších verziách `index.html`). Repo je verejné, preto ich treba z histórie vymazať.

**a) Najprv zmaž staré behy GitHub Actions** – starý export vypisoval celý zoznam zákazníkov do logov, ktoré sú pri verejnom repe verejné:
GitHub → **Actions** → workflow „Yankee Drive – Denný Report…“ → pri každom behu **⋯ → Delete workflow run**. Alebo cez GitHub CLI:
```bash
gh run list -R YankeeAlpha/yankee-drive-app --limit 500 --json databaseId -q '.[].databaseId' \
  | xargs -I{} gh run delete {} -R YankeeAlpha/yankee-drive-app
```

**b) Prepísať históriu (git filter-repo + force push)** – až PO zlúčení PR:
```bash
pip install git-filter-repo
git clone --mirror https://github.com/YankeeAlpha/yankee-drive-app.git
cd yankee-drive-app.git

# 1) odstrániť súbory s osobnými údajmi zo všetkých commitov
git filter-repo --force --invert-paths \
  --path customers_data.json \
  --path yankee_drive_zakaznici.csv \
  --path yankee_drive_objednavky.csv

# 2) vymazať mená, e-maily a telefóny zákazníkov zo starších verzií index.html
#    Vytvor súbor ../vyrazy.txt (MIMO repa) – jeden riadok na každý údaj, napr.:
#      meno.zakaznika@gmail.com==>***
#      +421 9xx xxx xxx==>***
#      Meno Priezvisko==>***
#    (zoznam údajov ti pošle Teo súkromne – do repa ho nedávaj)
git filter-repo --force --replace-text ../vyrazy.txt

# 3) nahrať prepísanú históriu (prepíše GitHub!)
git push --force --mirror origin
```
Potom:
- Na GitHube zmaž vetvu `bezpecnostne-opravy` (už je zlúčená).
- GitHub si staré commity ešte drží v odkazoch Pull Requestov a v cache. Na úplné odstránenie pošli bezplatnú žiadosť na **GitHub Support** (https://support.github.com → „Remove sensitive data“), uveď repo a že ide o osobné údaje.
- Ak má niekto repo naklonované, musí si ho naklonovať nanovo.

## 11. GDPR
Údaje 3 zákazníkov boli niekoľko dní verejne dostupné. Odporúčam poradiť sa (napr. s účtovníkom/právnikom), či treba incident ohlásiť Úradu na ochranu osobných údajov SR (lehota 72 hodín od zistenia) a informovať dotknutých zákazníkov.

---

### Čo sa mení pre obsluhu
- Namiesto PIN-u sa prihlasuje **e-mailom a heslom** (raz na zariadení, prihlásenie si zariadenie pamätá). Tlačidlo „Odhlásiť“ odhlási.
- Zákazníci a objednávky sa načítavajú **z databázy** (potrebný internet). Bez internetu fungujú kalkulačka a šablóny správ.
- Ručne pridaní zákazníci sa ukladajú do databázy (vidia ich všetky zariadenia), nie len do jedného prehliadača.
- Poukazy zákazníkov sa **overujú a označujú ako použité** v aplikácii (karta QR & Zákazníci → „Overenie poukazu“). Staré poukazy vydané pred touto zmenou v systéme nie sú – over ich ručne.
- Režim „Obsluha“ vo vernostnom klube bol zrušený – body sa pripisujú iba v internej aplikácii.

### Čo sa mení pre zákazníkov
- Do vernostného klubu sa prihlasujú **Google účtom** alebo **e-mailom a heslom** (s potvrdením e-mailu). Zadanie cudzieho e-mailu/telefónu/mena už nefunguje.
- Kartu uvidia, len ak sa prihlásia **rovnakým e-mailom**, aký použili pri objednávke. Ak má zákazník iný e-mail, obsluha mu môže body preniesť (pripísať na nový e-mail a na starom odpočítať).
- QR kód karty sa generuje priamo v telefóne (e-mail už neodchádza cudzej službe).

### Lokálne testovanie (pre vývojára)
Pravidlá sa dajú otestovať v emulátore bez zásahu do živej databázy:
`firebase emulators:start --only auth,firestore --project demo-yd` a stránku otvoriť ako `http://localhost:8000/index.html?emulator=1`.
