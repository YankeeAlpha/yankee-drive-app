# yankee-drive-app
Yankee Drive – interná mobilná a webová aplikácia (PWA) pre obsluhu + vernostný klub pre zákazníkov.

- `index.html` – interná aplikácia (prihlásenie účtom obsluhy cez Firebase Authentication)
- `vernostny-klub.html` – vernostný klub (prihlásenie zákazníka cez Google alebo e-mail + heslo)
- `poradna.html` – zákaznícka poradňa
- `firestore.rules` – pravidlá databázy (nasadzujú sa vo Firebase konzole)
- `sw.js`, `manifest.json`, `icons/` – PWA a offline režim
- `vendor/` – knižnice (Firebase 13.3.0 compat, html5-qrcode 2.3.8, qrcode-generator 2.0.4)
- `tools/` – skripty pre denný report a synchronizáciu z Welcomio (bežia v GitHub Actions)

**Do repa nikdy nedávaj osobné údaje zákazníkov ani tajné kľúče** – repo je verejné. Pozri `.gitignore` a [docs/NAVOD-BEZPECNOST.md](docs/NAVOD-BEZPECNOST.md).
