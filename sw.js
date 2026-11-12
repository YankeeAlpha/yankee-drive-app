// Yankee Drive – service worker pre offline režim.
// HTML: najprv sieť (aby sa vždy načítala nová verzia), pri výpadku z cache.
// Knižnice, ikony a obrázky: najprv cache.
// Požiadavky na Firebase/Google (iný pôvod) sa NEcachujú – údaje zákazníkov
// sa neukladajú do cache service workera.
const CACHE = "yd-app-v3";
const PRECACHE = [
  "./",
  "./index.html",
  "./vernostny-klub.html",
  "./poradna.html",
  "./manifest.json",
  "./icon.svg",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/icon-maskable-512.png",
  "./icons/apple-touch-icon-180.png",
  "./logo_yd_small.webp",
  "./js/firebase-config.js?v=3",
  "./vendor/firebase-app-compat.js",
  "./vendor/firebase-auth-compat.js",
  "./vendor/firebase-firestore-compat.js",
  "./vendor/html5-qrcode.min.js",
  "./vendor/qrcode-generator.js"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // Firebase, Google, WhatsApp – bez cache
  if (url.pathname.endsWith(".csv") || (url.pathname.endsWith(".json") && !url.pathname.endsWith("manifest.json"))) return;

  const isPage = req.mode === "navigate" || (req.headers.get("accept") || "").includes("text/html");
  if (isPage) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req, { ignoreSearch: true }).then((r) => r || caches.match("./index.html")))
    );
    return;
  }
  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req).then((res) => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return res;
    }))
  );
});
