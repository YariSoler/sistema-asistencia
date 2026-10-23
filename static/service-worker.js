const CACHE_NAME = "act06-offline-v7";
const SHELL_URL = "/static/offline-shell.html";
const STATIC_ASSETS = [SHELL_URL, "/static/css/style.css", "/static/js/asistencia.js"];
const QR_ASSETS = [
    "https://cdnjs.cloudflare.com/ajax/libs/qr-scanner/1.4.2/qr-scanner.umd.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/qr-scanner/1.4.2/qr-scanner-worker.min.js",
    "https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner.umd.min.js",
    "https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner-worker.min.js",
];

function openQueueDatabase() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open("asistencia-act06", 1);
        request.onupgradeneeded = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains("queue")) db.createObjectStore("queue", { keyPath: "operacion_id" });
            if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta", { keyPath: "key" });
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

function queueAction(mode, action) {
    return openQueueDatabase().then((db) => new Promise((resolve, reject) => {
        const tx = db.transaction("queue", mode);
        const request = action(tx.objectStore("queue"));
        let result;
        request.onsuccess = () => { result = request.result; };
        tx.oncomplete = () => { db.close(); resolve(result); };
        tx.onerror = () => { db.close(); reject(tx.error || request.error); };
        tx.onabort = () => { db.close(); reject(tx.error || new Error("IndexedDB transaction aborted")); };
    }));
}

async function syncOfflineQueue() {
    const csrfResponse = await fetch("/api/asistencia/csrf", { credentials: "include", headers: { Accept: "application/json" } });
    const csrf = await csrfResponse.json();
    if (!csrfResponse.ok || !csrf.csrf_token) throw new Error("No se pudo validar la sesión para sincronizar.");
    const queue = await queueAction("readonly", (store) => store.getAll());
    const pending = queue.filter((item) => ["pendiente", "sincronizando", "necesita_revision"].includes(item.estado))
        .sort((a, b) => a.ocurrio_en.localeCompare(b.ocurrio_en));
    for (const item of pending) {
        const endpoint = item.tipo === "visita" ? "/api/visitas-tecnicas" : `/api/asistencia/${item.tipo}`;
        try {
            const response = await fetch(endpoint, {
                method: "POST", credentials: "include",
                headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrf.csrf_token },
                body: JSON.stringify({ ...item.payload, operacion_id: item.operacion_id }),
            });
            const result = await response.json();
            if (response.ok && result.operacion_id === item.operacion_id && result.registro) {
                item.estado = "confirmada";
                item.mensaje = "Confirmada en Supabase.";
                item.confirmada_en = new Date().toISOString();
                await queueAction("readwrite", (store) => store.put(item));
                continue;
            }
            if (response.status >= 400 && response.status < 500 && response.status !== 408 && response.status !== 429) {
                item.estado = "necesita_revision";
                item.causa = "validacion_servidor";
                item.mensaje = result.error || "El servidor requiere revisión.";
                await queueAction("readwrite", (store) => store.put(item));
                continue;
            }
            item.estado = "pendiente";
            item.causa = response.status >= 500 ? "servidor" : "conectividad";
            item.mensaje = "Sin confirmación del servidor. Se reintentará con el mismo identificador.";
            await queueAction("readwrite", (store) => store.put(item));
            throw new Error(item.mensaje);
        } catch (error) {
            if (!error?.message?.startsWith("Sin confirmación")) {
                item.estado = "pendiente";
                item.causa = "conectividad";
                item.mensaje = "Conexión interrumpida. Se reintentará con el mismo identificador.";
                await queueAction("readwrite", (store) => store.put(item));
            }
            throw error;
        }
    }
}

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE_NAME)
        .then(async (cache) => {
            await cache.addAll(STATIC_ASSETS);
            // La lectura QR queda disponible sin red si el recurso pudo
            // descargarse durante una visita conectada anterior.
            await Promise.all(QR_ASSETS.map((asset) => cache.add(asset).catch(() => null)));
        })
        .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
    event.waitUntil(caches.keys().then((keys) => Promise.all(
        keys.filter((key) => key.startsWith("act06-offline-") && key !== CACHE_NAME).map((key) => caches.delete(key)),
    )).then(() => self.clients.claim()));
});

self.addEventListener("sync", (event) => {
    if (event.tag === "act06-sync") event.waitUntil(syncOfflineQueue().then(async () => {
        const pages = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
        pages.forEach((page) => page.postMessage({ type: "ACT06_SYNC_COMPLETE" }));
    }));
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    const url = new URL(request.url);
    if (request.method !== "GET") return;

    if (QR_ASSETS.includes(request.url)) {
        event.respondWith(caches.match(request).then((cached) => cached || fetch(request).then(async (response) => {
            if (response.ok) await (await caches.open(CACHE_NAME)).put(request, response.clone());
            return response;
        })));
        return;
    }
    if (url.origin !== self.location.origin) return;

    if (request.mode === "navigate" && url.pathname === "/coordinador/registro") {
        event.respondWith(fetch(request).catch(async () => (
            (await caches.match(SHELL_URL)) || new Response("La pantalla offline no está preparada en este dispositivo.", {
                status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" },
            })
        )));
        return;
    }

    if (STATIC_ASSETS.includes(url.pathname)) {
        // Network first prevents a stale JavaScript bundle from using DOM
        // selectors that do not match the current Flask template.
        event.respondWith(fetch(request).then((response) => {
            if (response.ok) void caches.open(CACHE_NAME).then((cache) => cache.put(request, response.clone()));
            return response;
        }).catch(async () => (await caches.match(request)) || new Response("Recurso no disponible sin conexión.", { status: 503 })));
    }
});
