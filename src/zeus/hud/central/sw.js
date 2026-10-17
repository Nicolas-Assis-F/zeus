/* Service worker da Central: guarda só o esqueleto estático, para a Central
   abrir sem rede e dizer "sem conexão" em vez de uma página do navegador.
   Dado (/central/api/) nunca vai para o cache. */
const VERSAO = "central-v1";
const ESQUELETO = ["/central/", "/central/central.css", "/central/js/app.js", "/central/js/base.js",
  "/central/js/orbe.js", "/central/js/paleta.js", "/central/js/voz.js", "/central/icone.svg", "/central/manifest.webmanifest"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(VERSAO).then((c) => c.addAll(ESQUELETO))); self.skipWaiting(); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSAO).map((k) => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || !url.pathname.startsWith("/central/") || url.pathname.startsWith("/central/api/")) return;
  // Rede primeiro: o Zeus muda com o código; o cache é só para quando cair.
  e.respondWith(fetch(e.request).then((r) => {
    const copia = r.clone();
    caches.open(VERSAO).then((c) => c.put(e.request, copia));
    return r;
  }).catch(() => caches.match(e.request)));
});
