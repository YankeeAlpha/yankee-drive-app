// Verejná konfigurácia Firebase webovej aplikácie (nie je to tajomstvo).
// Bezpečnosť zabezpečujú Firestore pravidlá (firestore.rules) a Firebase Authentication.
// Odporúčanie: v Google Cloud Console obmedziť tento API kľúč na doménu
// yankeealpha.github.io (HTTP referrer) a na API Identity Toolkit + Cloud Firestore.
window.YD_FIREBASE_CONFIG = {
  apiKey: "AIzaSyBym7aue9Fy0oIU00YpwcFQ1j20PO6-VMA",
  authDomain: "yankee-drive-loyality-card.firebaseapp.com",
  projectId: "yankee-drive-loyality-card",
  storageBucket: "yankee-drive-loyality-card.firebasestorage.app",
  messagingSenderId: "1071364286187",
  appId: "1:1071364286187:web:f28668685472ad5fbf40ae",
  measurementId: "G-TCWH37NLM3"
};

// Bezpečné vkladanie textu do HTML (ochrana pred XSS).
window.ydEscape = function (value) {
  return String(value === undefined || value === null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
};

// Iba pre lokálne testovanie (http://localhost/...?emulator=1) – na webe sa nikdy nepoužije.
window.YD_USE_EMULATOR = (location.hostname === "localhost" || location.hostname === "127.0.0.1")
  && new URLSearchParams(location.search).get("emulator") === "1";
window.ydConnectEmulators = function (auth, db) {
  if (!window.YD_USE_EMULATOR) return;
  auth.useEmulator("http://127.0.0.1:9099", { disableWarnings: true });
  db.useEmulator("127.0.0.1", 8080);
};
