(() => {
    const $ = (id) => document.getElementById(id);
    function logClientDiagnostic(error, { targetId = "", operationType = "", localState = "", sourceFile = "", sourceLine = 0, sourceColumn = 0 } = {}) {
        const frames = String(error?.stack || "").split("\n");
        const frame = frames.find((line) => /asistencia\.js:\d+:\d+/.test(line)
            && !/logClientDiagnostic|setText|setStatus/.test(line));
        const match = frame?.match(/(?:\(|\s)((?:https?:\/\/[^ )]+\/)?(?:static\/js\/)?asistencia\.js):(\d+):(\d+)/);
        const rawFile = sourceFile || match?.[1] || "static/js/asistencia.js";
        const file = rawFile.includes("/static/") ? rawFile.slice(rawFile.indexOf("/static/") + 1).split(/[?#]/)[0] : rawFile.split(/[?#]/)[0];
        const line = Number(sourceLine || match?.[2] || 0);
        const column = Number(sourceColumn || match?.[3] || 0);
        console.error("[ACT06] Error de interfaz", {
            file, line, column,
            targetId: targetId || undefined,
            operationType: operationType || undefined,
            localState: localState || undefined,
            errorType: error?.name || "Error",
        });
    }

    function setText(target, value) {
        const element = typeof target === "string" ? $(target) : target;
        if (!element) {
            const targetId = typeof target === "string" ? target : "elemento DOM sin referencia";
            const error = new TypeError(`No existe el elemento requerido para actualizar textContent (${targetId}).`);
            logClientDiagnostic(error, { targetId });
            throw error;
        }
        try {
            element.textContent = value;
        } catch (error) {
            logClientDiagnostic(error, {
                targetId: typeof target === "string" ? target : (element.id || "elemento DOM"),
            });
            throw error;
        }
    }

    const requiredIds = [
        "flow-choice", "cot-flow", "scanner-flow", "visit-flow", "offline-flow", "camera-preview",
        "cot-form", "cot", "proyecto", "project-context", "worker-card",
        "manual-id-form", "manual-id", "identification-status", "camera-status", "scanner-title",
        "scanner-description", "camera-placeholder", "start-camera", "worker-name", "worker-detail",
        "open-attendance-detail", "confirm-attendance", "continue-offline", "attendance-result", "scan-next",
        "visit-coordinator-confirmation", "register-visit", "identify-visit-coordinator", "visit-status",
        "visit-project-form", "visit-project", "visit-identification-stage", "visit-project-context",
        "visit-coordinator-id-form", "visit-coordinator-id", "visit-coordinator-id-status",
        "visit-participants-stage", "visit-worker-confirmation", "scan-visit-worker", "visit-worker-id-form",
        "visit-worker-id", "visit-worker-id-status", "clear-visit-worker",
    ];
    const missingIds = requiredIds.filter((id) => !$(id));
    if (missingIds.length) {
        const error = new Error("La plantilla de asistencia no cumple el contrato DOM requerido.");
        logClientDiagnostic(error, { targetId: missingIds.join(",") });
        throw error;
    }
    window.addEventListener("error", (event) => logClientDiagnostic(event.error || new Error("Error JavaScript no controlado."), {
        sourceFile: event.filename || "", sourceLine: event.lineno || 0, sourceColumn: event.colno || 0,
    }));
    window.addEventListener("unhandledrejection", (event) => logClientDiagnostic(event.reason || new Error("Promesa JavaScript rechazada.")));
    const sections = [$("flow-choice"), $("cot-flow"), $("scanner-flow"), $("visit-flow"), $("offline-flow")];
    const camera = $("camera-preview");
    const cameraStatus = $("camera-status");
    let mediaStream = null;
    let scanLoopActive = false;
    let detector = null;
    let qrScanner = null;
    let selectedQr = "";
    let selectedWorkerId = null;
    let selectedAction = "";
    let selectedOffline = false;
    let pendingAttendanceOperationId = null;
    let contextCot = "";
    let contextProject = "";
    let scanPurpose = "attendance";
    let coordinatorQr = "";
    let visitProject = "";
    let visitCoordinatorId = null;
    let visitWorkerId = null;
    let visitWorkerName = "";
    let visitOfflineChoice = false;
    let pendingVisitOperation = null;
    let lastVisitOperationId = null;
    let retryAttempt = 0;
    let retryTimer = null;
    let csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const dbReady = new Promise((resolve, reject) => {
        const request = indexedDB.open("asistencia-act06", 1);
        request.onupgradeneeded = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains("queue")) db.createObjectStore("queue", { keyPath: "operacion_id" });
            if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta", { keyPath: "key" });
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
    let fieldDirectory = null;
    let syncing = false;

    async function dbAction(storeName, mode, action) {
        const db = await dbReady;
        return new Promise((resolve, reject) => {
            const tx = db.transaction(storeName, mode);
            const store = tx.objectStore(storeName);
            const request = action(store);
            let result;
            request.onsuccess = () => { result = request.result; };
            tx.oncomplete = () => resolve(result);
            tx.onerror = () => reject(tx.error || request.error);
            tx.onabort = () => reject(tx.error || new Error("No se pudo conservar la operación localmente."));
        });
    }

    const queueAll = () => dbAction("queue", "readonly", (store) => store.getAll());
    const queuePut = (item) => dbAction("queue", "readwrite", (store) => store.put(item));
    const metaGet = (key) => dbAction("meta", "readonly", (store) => store.get(key));
    const metaPut = (item) => dbAction("meta", "readwrite", (store) => store.put(item));

    function createIdempotencyKey() {
        if (crypto.randomUUID) return crypto.randomUUID();
        const bytes = new Uint8Array(16);
        crypto.getRandomValues(bytes);
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
        return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
    }

    function updateConnectionStatus() {
        setText("connection-status", navigator.onLine ? "Con conexión" : "Sin conexión · puedes guardar operaciones pendientes");
    }

    function isConnectivityError(error, { treat503AsServer = false } = {}) {
        return error?.kind === "network"
            || error?.status === 408 || [502, 504].includes(error?.status)
            || (!treat503AsServer && error?.status === 503);
    }

    async function fetchFromServer(url, options) {
        try {
            return await fetch(url, options);
        } catch (cause) {
            const error = new Error("No se pudo establecer conexión con el servidor.");
            error.kind = "network";
            error.cause = cause;
            throw error;
        }
    }

    function scheduleRetry() {
        if (!navigator.onLine || retryTimer) return;
        const delay = Math.min(2000 * (2 ** retryAttempt), 120000);
        retryAttempt += 1;
        retryTimer = window.setTimeout(() => {
            retryTimer = null;
            void syncPending();
        }, delay);
    }

    async function requestBackgroundSync() {
        if (!("serviceWorker" in navigator)) return;
        try {
            const registration = await navigator.serviceWorker.ready;
            if (registration.sync) await registration.sync.register("act06-sync");
        } catch (_) {
            // Online, pageshow y reintentos temporizados son el respaldo.
        }
    }

    async function loadCachedDirectory() {
        const cached = await metaGet("directory");
        fieldDirectory = cached?.value || null;
        renderDirectoryStatus();
    }

    function renderDirectoryStatus() {
        const status = $("directory-status");
        if (!fieldDirectory) {
            setText(status, "Directorio de operarios no descargado; conéctate antes de salir a campo.");
            return;
        }
        const date = new Date(fieldDirectory.actualizado_en);
        const total = fieldDirectory.trabajadores?.length || 0;
        setText(status, `Directorio local: ${total} operarios activos · descargado ${formatDate(date.toISOString())}. La vigencia se vuelve a comprobar al sincronizar.`);
    }

    async function refreshDirectory() {
        const button = $("refresh-directory");
        button.disabled = true;
        try {
            const response = await fetchFromServer("/api/asistencia/directorio-offline", { credentials: "same-origin", headers: { Accept: "application/json" } });
            const result = await response.json();
            if (!response.ok) throw Object.assign(new Error(result.error || "No se pudo actualizar el directorio."), { status: response.status });
            await metaPut({ key: "directory", value: result });
            fieldDirectory = result;
            renderDirectoryStatus();
            setStatus("queue-status", "Directorio de operarios actualizado en este dispositivo.", "success");
        } catch (error) {
            setStatus("queue-status", error.message || "Sin conexión; se conserva el directorio descargado anteriormente.", "error");
        } finally {
            button.disabled = false;
        }
    }

    function cachedWorkerByQr(qr) {
        return fieldDirectory?.trabajadores?.find((worker) => worker.qr && worker.qr === qr)
            || (fieldDirectory?.coordinador?.qr === qr ? fieldDirectory.coordinador : null);
    }

    function cachedWorkerByIdentification(value) {
        const normalized = String(value || "").trim();
        return fieldDirectory?.trabajadores?.find((worker) => String(worker.identificacion || "").trim() === normalized) || null;
    }

    function derivedOpenShift(worker) {
        let open = worker.registro_abierto || null;
        const operations = fieldDirectory?.localOperations || [];
        for (const item of operations) {
            if (Number(item.trabajador_id) !== Number(worker.id) || item.estado === "confirmada") continue;
            if (item.tipo === "entrada") open = { fecha_entrada: item.ocurrio_en, cot: item.cot, proyecto: item.proyecto, local: true };
            if (item.tipo === "salida") open = null;
        }
        return open;
    }

    async function renderQueue() {
        const all = (await queueAll()).sort((a, b) => a.ocurrio_en.localeCompare(b.ocurrio_en));
        const pendientes = all.filter((item) => item.estado !== "confirmada");
        // La cola es el dato principal; los nodos del panel son opcionales porque
        // esa pantalla puede no estar presente en un HTML servido desde caché.
        const count = $("pending-count");
        if (count) setText(count, String(pendientes.length));
        const list = $("pending-operations");
        if (!list) return all;
        list.replaceChildren();
        for (const item of all.slice(-12).reverse()) {
            const li = document.createElement("li");
            const worker = fieldDirectory?.trabajadores?.find((row) => Number(row.id) === Number(item.trabajador_id));
            const person = item.tipo === "visita" ? "Visita técnica" : (worker?.nombre || `Operario #${item.trabajador_id}`);
            const labels = { pendiente: "Pendiente de validación", sincronizando: "Sincronizando", necesita_revision: "Pendiente · servidor requiere revisión", confirmada: "Confirmada en Supabase" };
            li.className = item.estado === "necesita_revision" ? "queue-conflict" : (item.estado === "confirmada" ? "queue-confirmed" : "");
            setText(li, `${person} · ${item.tipo} · ${formatDate(item.ocurrio_en)} · ${labels[item.estado] || "Pendiente"}${item.mensaje ? ` · ${item.mensaje}` : ""}`);
            list.appendChild(li);
        }
        return all;
    }

    async function refreshActiveAttendanceStatus() {
        if (!pendingAttendanceOperationId) return;
        const item = (await queueAll()).find((row) => row.operacion_id === pendingAttendanceOperationId);
        if (!item) return;
        if (item.estado === "confirmada") {
            setStatus("attendance-result", `${item.tipo === "entrada" ? "Entrada" : "Salida"} confirmada en Supabase.`, "success");
            $("continue-offline").hidden = true;
            $("scan-next").hidden = false;
        } else if (item.estado === "necesita_revision") {
            setStatus("attendance-result", `${item.mensaje} La operación sigue visible para revisión; no está confirmada.`, "error");
            $("continue-offline").hidden = true;
        }
    }

    async function savePending(operation, message = "Esperando conexión para validar en el servidor.") {
        await queuePut({ ...operation, estado: "pendiente", mensaje: message, creado_local_en: new Date().toISOString() });
        await renderQueue();
        void requestBackgroundSync();
    }

    async function obtainCsrfToken() {
        const response = await fetchFromServer("/api/asistencia/csrf", { credentials: "same-origin", headers: { Accept: "application/json" } });
        let result;
        try { result = await response.json(); }
        catch (_) { throw Object.assign(new Error("El servidor respondió en un formato inesperado."), { status: response.status }); }
        if (!response.ok || !result.csrf_token) throw Object.assign(new Error(result.error || "Inicia sesión como coordinador para sincronizar."), { status: response.status });
        csrfToken = result.csrf_token;
    }

    async function syncPending() {
        if (syncing) return;
        if (!navigator.onLine) {
            setStatus("queue-status", "Sin conexión. Las operaciones se conservan en este dispositivo.", "error");
            return { ok: false, network: true };
        }
        syncing = true;
        const button = $("sync-pending");
        button.disabled = true;
        try {
            await obtainCsrfToken();
            const pending = (await queueAll()).filter((item) => ["pendiente", "sincronizando", "necesita_revision"].includes(item.estado)).sort((a, b) => a.ocurrio_en.localeCompare(b.ocurrio_en));
            let hadPendingFailure = false;
            let hadConnectionFailure = false;
            let hadReview = false;
            for (const item of pending) {
                item.estado = "sincronizando";
                item.mensaje = "El servidor está validando la operación.";
                await queuePut(item);
                await renderQueue();
                const endpoint = item.tipo === "visita" ? "/api/visitas-tecnicas" : `/api/asistencia/${item.tipo}`;
                const payload = { ...item.payload, operacion_id: item.operacion_id };
                try {
                    const result = await sendJson(endpoint, payload);
                    if (result.operacion_id !== item.operacion_id || !result.registro) {
                        throw new Error("El servidor no confirmó esta operación. Se mantiene pendiente.");
                    }
                    item.estado = "confirmada";
                    item.mensaje = "Confirmada en Supabase.";
                    item.confirmada_en = new Date().toISOString();
                    await queuePut(item);
                } catch (error) {
                    const networkFailure = isConnectivityError(error, { treat503AsServer: item.tipo === "visita" });
                    if (!networkFailure && error.status && error.status >= 400 && error.status < 500 && error.status !== 429) {
                        item.estado = "necesita_revision";
                        item.mensaje = error.message;
                        item.causa = "validacion_servidor";
                        hadReview = true;
                    } else {
                        item.estado = "pendiente";
                        item.mensaje = networkFailure
                            ? "Conexión interrumpida. No se confirmó en Supabase; se reintentará con el mismo identificador."
                            : "El servidor no confirmó la operación. Sigue pendiente; revisa el servicio y reintenta.";
                        item.causa = networkFailure ? "conectividad" : "servidor";
                    }
                    await queuePut(item);
                    if (item.estado === "pendiente") {
                        hadPendingFailure = true;
                        hadConnectionFailure = item.causa === "conectividad";
                        scheduleRetry();
                        break;
                    }
                }
            }
            await renderQueue();
            await refreshActiveAttendanceStatus();
            if (hadPendingFailure) {
                setStatus("queue-status", "Hay operaciones sin confirmación; siguen pendientes y no están guardadas en Supabase.", "error");
            } else if (hadReview) {
                setStatus("queue-status", "Algunas operaciones requieren revisión del servidor; permanecen en la cola.", "error");
            } else {
                setStatus("queue-status", "Sincronización revisada. Solo las respuestas confirmadas se marcan como sincronizadas.", "success");
            }
            if (!hadPendingFailure) retryAttempt = 0;
            return { ok: !hadPendingFailure, network: hadConnectionFailure };
        } catch (error) {
            const network = isConnectivityError(error);
            const trackedId = pendingAttendanceOperationId || lastVisitOperationId;
            const trackedOperation = trackedId
                ? (await queueAll()).find((item) => item.operacion_id === trackedId)
                : null;
            logClientDiagnostic(error, {
                targetId: "queue-status",
                operationType: trackedOperation?.tipo,
                localState: trackedOperation?.estado || "sin_operacion_local",
            });
            setStatus("queue-status", network
                ? `${error.message} La cola sigue guardada en este dispositivo; no se confirmó el envío.`
                : `Error de aplicación al actualizar o validar la cola: ${error.message}. No se clasificó como falta de conexión.`, "error");
            if (network) scheduleRetry();
            return { ok: false, network, error };
        } finally {
            syncing = false;
            button.disabled = false;
            await renderQueue();
            await refreshActiveAttendanceStatus();
        }
    }

    async function localOpenShift(workerId) {
        const worker = fieldDirectory?.trabajadores?.find((row) => Number(row.id) === Number(workerId))
            || (Number(fieldDirectory?.coordinador?.id) === Number(workerId) ? fieldDirectory.coordinador : null);
        let open = worker?.registro_abierto || null;
        const operations = (await queueAll()).filter((item) => Number(item.trabajador_id) === Number(workerId) && item.estado !== "confirmada")
            .sort((a, b) => a.ocurrio_en.localeCompare(b.ocurrio_en));
        for (const item of operations) {
            if (item.tipo === "entrada") open = { fecha_entrada: item.ocurrio_en, cot: item.payload.cot, proyecto: item.payload.proyecto, local: true };
            if (item.tipo === "salida") open = null;
        }
        return open;
    }

    function showSection(id) {
        stopCamera();
        sections.forEach((section) => { section.hidden = section.id !== id; });
    }

    function stopCamera() {
        scanLoopActive = false;
        if (qrScanner) {
            try { qrScanner.stop(); } catch (_) { /* liberar también las pistas directamente */ }
            try { qrScanner.destroy(); } catch (_) { /* el recurso ya pudo estar liberado */ }
            qrScanner = null;
        }
        if (mediaStream) {
            mediaStream.getTracks().forEach((track) => track.stop());
            mediaStream = null;
        }
        if (camera) camera.srcObject = null;
        if (camera) camera.hidden = true;
        const placeholder = $("camera-placeholder");
        if (placeholder) placeholder.hidden = false;
    }

    const QR_SCANNER_INTEGRITY = "sha512-a/IwksuXdv0Q60tVkQpwMk5qY+6cJ0FJgi33lrrIddoFItTRiRfSdU1qogP3uYjgHfrGY7+AC+4LU4J+b9HcgQ==";
    const QR_SCANNER_FALLBACKS = [
        "https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner.umd.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/qr-scanner/1.4.2/qr-scanner.umd.min.js",
    ];

    function loadQrScannerScript(src) {
        return new Promise((resolve, reject) => {
            const script = document.createElement("script");
            script.src = src;
            script.integrity = QR_SCANNER_INTEGRITY;
            script.crossOrigin = "anonymous";
            script.referrerPolicy = "no-referrer";
            script.onload = () => window.QrScanner
                ? resolve()
                : reject(new Error("El recurso QR cargó, pero no registró la API QrScanner."));
            script.onerror = () => reject(new Error("Falló la descarga o verificación SRI del recurso QR."));
            document.head.appendChild(script);
        });
    }

    async function ensureVisitQrScanner() {
        if (window.QrScanner) return;
        const failures = [];
        for (const src of QR_SCANNER_FALLBACKS) {
            try {
                await loadQrScannerScript(src);
                return;
            } catch (error) {
                failures.push(error);
            }
        }
        const proveedores = failures.map((error, index) => `${QR_SCANNER_FALLBACKS[index].split("/")[2]}: ${error.message}`);
        throw new Error(`No se pudo cargar el lector QR desde los dos CDN. ${proveedores.join(" | ")} Revisa conexión, política del navegador o integridad SRI.`);
    }

    function setStatus(element, message, kind = "") {
        const target = typeof element === "string" ? $(element) : element;
        const targetId = typeof element === "string" ? element : (element?.id || "elemento de estado");
        if (!target) {
            const error = new TypeError(`No existe el elemento de estado requerido (${targetId}).`);
            logClientDiagnostic(error, { targetId });
            throw error;
        }
        setText(target, message);
        target.classList.toggle("is-error", kind === "error");
        target.classList.toggle("is-success", kind === "success");
    }

    async function sendJson(url, body) {
        const response = await fetchFromServer(url, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-CSRF-Token": csrfToken,
            },
            body: JSON.stringify(body),
        });
        let result;
        try { result = await response.json(); }
        catch (_) { throw Object.assign(new Error("El servidor respondió en un formato inesperado."), { status: response.status }); }
        if (!response.ok) throw Object.assign(new Error(result.error || "No se pudo completar el registro."), { status: response.status });
        return result;
    }

    function formatDate(value) {
        if (!value) return "fecha no disponible";
        return new Intl.DateTimeFormat("es-CO", {
            dateStyle: "medium", timeStyle: "short", timeZone: "America/Bogota",
        }).format(new Date(value));
    }

    function locationOptional() {
        return new Promise((resolve) => {
            if (!navigator.geolocation) return resolve({ ubicacion_estado: "no_disponible" });
            navigator.geolocation.getCurrentPosition(
                ({ coords }) => resolve({
                    ubicacion_estado: "obtenida", latitud: coords.latitude,
                    longitud: coords.longitude, precision_m: coords.accuracy,
                }),
                () => resolve({ ubicacion_estado: "no_disponible" }),
                { enableHighAccuracy: true, timeout: 4500, maximumAge: 0 },
            );
        });
    }

    function showAttendanceTarget(worker, open, isCoordinator, notice, offlineChoice = false) {
        pendingAttendanceOperationId = null;
        selectedAction = open ? "salida" : "entrada";
        selectedOffline = offlineChoice;
        selectedWorkerId = isCoordinator ? null : worker.id;
        selectedQr = isCoordinator ? (worker.qr || "") : "";
        setText("worker-name", worker.nombre || "Coordinador");
        setText("worker-detail", worker.cargo || (isCoordinator ? "Coordinador" : "Operario"));
        const openDetail = $("open-attendance-detail");
        if (open) {
            setText(openDetail, `Entrada abierta: ${open.cot || "COT pendiente"} · ${open.proyecto || "Proyecto pendiente"} · ${formatDate(open.fecha_entrada)}`);
            openDetail.hidden = false;
        } else {
            openDetail.hidden = true;
        }
        setText("confirm-attendance", offlineChoice
            ? "Continuar sin conexión"
            : (selectedAction === "entrada" ? "Confirmar entrada" : "Confirmar salida"));
        $("confirm-attendance").disabled = false;
        $("continue-offline").hidden = true;
        setText("attendance-result", notice || "");
        $("scan-next").hidden = true;
        $("worker-card").hidden = false;
    }

    updateConnectionStatus();
    if ("serviceWorker" in navigator) {
        navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(() => {
            setStatus("queue-status", "El navegador no permitió preparar la pantalla offline; mantén abierta la pantalla actual en campo.", "error");
        });
        navigator.serviceWorker.addEventListener("message", (event) => {
            if (event.data?.type === "ACT06_SYNC_COMPLETE") {
                void renderQueue();
                void refreshActiveAttendanceStatus();
            }
        });
    }
    window.addEventListener("online", () => {
        updateConnectionStatus();
        retryAttempt = 0;
        if (retryTimer) window.clearTimeout(retryTimer);
        retryTimer = null;
        if (!pendingVisitOperation) {
            visitOfflineChoice = false;
            if (visitCoordinatorId) setText("register-visit", "Registrar visita");
        }
        if (!$("worker-card").hidden && $("continue-offline").hidden) {
            selectedOffline = false;
        }
        void refreshDirectory();
        void syncPending();
    });
    window.addEventListener("offline", () => {
        updateConnectionStatus();
        if (!$("worker-card").hidden) {
            selectedOffline = true;
            setText("confirm-attendance", "Continuar sin conexión");
        }
        if (visitCoordinatorId && !pendingVisitOperation) {
            visitOfflineChoice = true;
            setText("register-visit", "Continuar sin conexión");
        }
    });
    window.addEventListener("pageshow", () => { updateConnectionStatus(); if (navigator.onLine) void syncPending(); });
    document.addEventListener("visibilitychange", () => {
        updateConnectionStatus();
        if (document.visibilityState === "visible" && navigator.onLine) void syncPending();
    });
    $("refresh-directory").addEventListener("click", refreshDirectory);
    $("sync-pending").addEventListener("click", syncPending);
    void loadCachedDirectory().then(async () => {
        await renderQueue();
        if (navigator.onLine) void syncPending();
    }).catch(() => setStatus("queue-status", "No fue posible abrir el almacenamiento local seguro del flujo.", "error"));
    if (navigator.onLine) void refreshDirectory();

    document.querySelectorAll("[data-show]").forEach((button) => {
        button.addEventListener("click", () => {
            scanPurpose = "attendance";
            showSection(button.dataset.show);
        });
    });
    document.querySelectorAll("[data-back]").forEach((button) => {
        button.addEventListener("click", () => {
            if (scanPurpose.startsWith("visit-")) {
                stopCamera();
                showSection("visit-flow");
            } else {
                showSection("flow-choice");
            }
        });
    });
    document.querySelectorAll("[data-open-offline]").forEach((button) => {
        button.addEventListener("click", () => showSection("offline-flow"));
    });

    $("cot-form").addEventListener("submit", (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        contextCot = String(form.get("cot") || "").trim();
        contextProject = String(form.get("proyecto") || "").trim();
        if (!contextCot || !contextProject) return;
        setText("project-context", `${contextCot} | ${contextProject}`);
        $("worker-card").hidden = true;
        showSection("scanner-flow");
        $("manual-id-form").hidden = false;
        setText("scanner-title", "Escanea el QR del trabajador o tu QR de coordinador");
        setText("scanner-description", "El coordinador solo puede registrar su propia asistencia; el personal debe estar activo para iniciar un turno.");
    });

    async function findWorker(qr) {
        if (scanPurpose === "visit-coordinator") {
            setStatus(cameraStatus, "Validando el QR de coordinador con la sesión…");
            try {
                const result = await sendJson("/api/visitas-tecnicas/verificar-coordinador", { qr });
                coordinatorQr = qr;
                visitCoordinatorId = Number(result.coordinador.id || fieldDirectory?.coordinador?.id);
                visitOfflineChoice = false;
                pendingVisitOperation = null;
                setText("visit-coordinator-confirmation", `Coordinador identificado: ${result.coordinador.nombre}.`);
                $("visit-coordinator-confirmation").classList.remove("is-error");
                $("visit-coordinator-confirmation").classList.add("is-success");
                $("register-visit").disabled = false;
                $("visit-participants-stage").hidden = false;
                showSection("visit-flow");
            } catch (error) {
                const cached = cachedWorkerByQr(qr);
                if (isConnectivityError(error)
                    && cached && Number(cached.id) === Number(fieldDirectory?.coordinador?.id)) {
                    coordinatorQr = qr;
                    visitCoordinatorId = Number(cached.id);
                    visitOfflineChoice = true;
                    setText("register-visit", "Continuar sin conexión");
                    setText("visit-coordinator-confirmation", "No se pudo contactar con el servidor. El QR coincide con el coordinador guardado; pulsa «Continuar sin conexión». Se validará al sincronizar.");
                    $("register-visit").disabled = false;
                    $("visit-participants-stage").hidden = false;
                    showSection("visit-flow");
                } else {
                    coordinatorQr = "";
                    visitOfflineChoice = false;
                    $("register-visit").disabled = true;
                    setStatus(cameraStatus, isConnectivityError(error)
                        ? "No se pudo contactar con el servidor y no hay una coincidencia local autorizada. Conéctate y vuelve a intentarlo."
                        : error.message, "error");
                }
            }
            return;
        }
        if (scanPurpose === "visit-worker") {
            setStatus(cameraStatus, "Validando que el QR pertenezca a un operario activo…");
            try {
                const result = await sendJson("/api/visitas-tecnicas/buscar-operario", { qr });
                visitWorkerId = Number(result.operario.id);
                visitWorkerName = result.operario.nombre;
                setText("visit-worker-confirmation", `Operario seleccionado: ${visitWorkerName}.`);
                $("clear-visit-worker").hidden = false;
                setStatus("visit-worker-id-status", "Operario activo agregado a la visita.", "success");
                showSection("visit-flow");
            } catch (error) {
                setStatus(cameraStatus, error.message, "error");
            }
            return;
        }
        selectedQr = qr;
        $("worker-card").hidden = true;
        setStatus(cameraStatus, "Consultando el QR con el servidor…");
        try {
            const result = await sendJson("/api/asistencia/qr", { qr });
            const isCoordinator = result.trabajador.perfil === "coordinador";
            showAttendanceTarget({ ...result.trabajador, qr }, result.registro_abierto, isCoordinator);
            setStatus(cameraStatus, "Código encontrado. Revisa el nombre y confirma la acción.", "success");
        } catch (error) {
            const cached = cachedWorkerByQr(qr);
            if (isConnectivityError(error) && cached) {
                const open = await localOpenShift(cached.id);
                showAttendanceTarget(cached, open, cached.id === fieldDirectory?.coordinador?.id,
                    "El QR coincide con el directorio local. Pulsa «Continuar sin conexión»; el servidor comprobará estado y turno al sincronizar.", true);
                setStatus(cameraStatus, "No se pudo consultar el servidor por falta de conexión. Puedes continuar con el directorio local.", "error");
            } else {
                setStatus(cameraStatus, isConnectivityError(error)
                    ? "No se pudo contactar con el servidor y el QR no está en el directorio local. Conéctate para identificar a esta persona."
                    : error.message, "error");
            }
        }
    }

    async function startCamera() {
        stopCamera();
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            setStatus(cameraStatus, "Este navegador no permite abrir la cámara aquí. Prueba con HTTPS; para operarios también puedes buscar por identificación.", "error");
            return;
        }
        try {
            if (typeof window.BarcodeDetector === "function") {
                const formats = await window.BarcodeDetector.getSupportedFormats();
                if (formats.includes("qr_code")) {
                    detector = new window.BarcodeDetector({ formats: ["qr_code"] });
                    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: "environment" } } });
                    camera.srcObject = mediaStream;
                    camera.hidden = false;
                    $("camera-placeholder").hidden = true;
                    await camera.play();
                    scanLoopActive = true;
                    setStatus(cameraStatus, "Cámara activa. Centra el QR dentro de la imagen.");
                    const scanFrame = async () => {
                        if (!scanLoopActive) return;
                        try {
                            const codes = await detector.detect(camera);
                            if (codes.length && codes[0].rawValue) {
                                const qr = codes[0].rawValue;
                                stopCamera();
                                await findWorker(qr);
                                return;
                            }
                        } catch (_) { /* se intenta con el siguiente cuadro */ }
                        if (scanLoopActive) window.requestAnimationFrame(scanFrame);
                    };
                    window.requestAnimationFrame(scanFrame);
                    return;
                }
            }

            // qr-scanner es un decodificador alternativo a BarcodeDetector. Se
            // carga desde una versión fijada y protegida por SRI en la plantilla.
            if (!window.QrScanner) throw new Error("No se cargó el lector QR compatible. Comprueba la conexión y vuelve a intentarlo.");
            camera.hidden = false;
            $("camera-placeholder").hidden = true;
            qrScanner = new window.QrScanner(camera, async (result) => {
                const qr = typeof result === "string" ? result : result?.data;
                if (!qr || !qrScanner) return;
                stopCamera();
                await findWorker(qr);
            }, { preferredCamera: "environment", returnDetailedScanResult: true });
            await qrScanner.start();
            setStatus(cameraStatus, "Cámara activa. Centra el QR dentro de la imagen.");
        } catch (error) {
            stopCamera();
            setStatus(cameraStatus, error.name === "NotAllowedError"
                ? `No se concedió permiso para usar la cámara. Habilítalo en el navegador; ${scanPurpose === "attendance" ? "para operarios también puedes buscar por identificación." : "regresa a Visita técnica e inténtalo después de habilitarlo."}`
                : (error.message || "No fue posible abrir la cámara. Usa HTTPS y permite el acceso a la cámara."), "error");
        }
    }

    $("start-camera").addEventListener("click", startCamera);
    $("identify-visit-coordinator").addEventListener("click", () => {
        scanPurpose = "visit-coordinator";
        setText("scanner-title", "Identifica al coordinador");
        setText("scanner-description", "El QR debe pertenecer a la cuenta de coordinador que inició esta sesión.");
        // La cédula sirve únicamente para trabajadores y no es un método
        // alternativo de identificación del coordinador para una visita.
        $("manual-id-form").hidden = true;
        setStatus(cameraStatus, "Activa la cámara para escanear tu QR de coordinador.");
        showSection("scanner-flow");
        if (typeof window.BarcodeDetector === "function" || window.QrScanner) {
            void startCamera();
        } else {
            setStatus(cameraStatus, "Preparando lector QR…");
            void ensureVisitQrScanner().then(startCamera).catch((error) => {
                setStatus(cameraStatus, error.message, "error");
            });
        }
    });
    $("visit-project-form").addEventListener("submit", (event) => {
        event.preventDefault();
        visitProject = String(new FormData(event.currentTarget).get("proyecto") || "").trim();
        if (!visitProject || visitProject.length > 300) return;
        setText("visit-project-context", `Proyecto o lugar: ${visitProject}`);
        $("visit-project-form").hidden = true;
        $("visit-identification-stage").hidden = false;
    });
    $("visit-coordinator-id-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const identificacion = String(new FormData(event.currentTarget).get("identificacion") || "").trim();
        setStatus("visit-coordinator-id-status", "Comprobando la identificación contra la sesión…");
        try {
            const result = await sendJson("/api/visitas-tecnicas/verificar-coordinador-identificacion", { identificacion });
            coordinatorQr = "";
            visitCoordinatorId = Number(result.coordinador.id);
            visitOfflineChoice = false;
            pendingVisitOperation = null;
            setText("visit-coordinator-confirmation", `Coordinador identificado: ${result.coordinador.nombre}.`);
            $("visit-coordinator-confirmation").classList.remove("is-error");
            $("visit-coordinator-confirmation").classList.add("is-success");
            $("visit-participants-stage").hidden = false;
            $("register-visit").disabled = false;
            setStatus("visit-coordinator-id-status", "Identificación verificada contra la sesión autenticada.", "success");
        } catch (error) {
            visitCoordinatorId = null;
            $("register-visit").disabled = true;
            setStatus("visit-coordinator-id-status", error.message, "error");
        }
    });
    $("scan-visit-worker").addEventListener("click", () => {
        scanPurpose = "visit-worker";
        setText("scanner-title", "Escanea el QR del operario");
        setText("scanner-description", "El servidor comprobará que sea un operario activo.");
        $("manual-id-form").hidden = true;
        showSection("scanner-flow");
        if (typeof window.BarcodeDetector === "function" || window.QrScanner) void startCamera();
        else void ensureVisitQrScanner().then(startCamera).catch((error) => setStatus(cameraStatus, error.message, "error"));
    });
    $("visit-worker-id-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const identificacion = String(new FormData(event.currentTarget).get("identificacion") || "").trim();
        setStatus("visit-worker-id-status", "Buscando operario activo…");
        try {
            const result = await sendJson("/api/visitas-tecnicas/buscar-operario", { identificacion });
            visitWorkerId = Number(result.operario.id);
            visitWorkerName = result.operario.nombre;
            setText("visit-worker-confirmation", `Operario seleccionado: ${visitWorkerName}.`);
            $("clear-visit-worker").hidden = false;
            setStatus("visit-worker-id-status", "Operario activo agregado a la visita.", "success");
        } catch (error) {
            setStatus("visit-worker-id-status", error.message, "error");
        }
    });
    $("clear-visit-worker").addEventListener("click", () => {
        visitWorkerId = null;
        visitWorkerName = "";
        setText("visit-worker-confirmation", "La visita puede realizarla solo el coordinador.");
        $("clear-visit-worker").hidden = true;
        $("visit-worker-id").value = "";
        setStatus("visit-worker-id-status", "Se quitó el operario de la visita.", "success");
    });
    $("manual-id-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        if (scanPurpose !== "attendance") {
            setStatus("identification-status", "La identificación solo permite buscar trabajadores para asistencia; no autentica al coordinador. Escanea el QR asociado a tu sesión.", "error");
            return;
        }
        const identificacion = String(new FormData(event.currentTarget).get("identificacion") || "").trim();
        const status = $("identification-status");
        setStatus(status, "Buscando trabajador activo…");
        try {
            const result = await sendJson("/api/asistencia/buscar-identificacion", { identificacion });
            showAttendanceTarget(result.trabajador, result.registro_abierto, false);
            setStatus(status, "Trabajador activo encontrado. Confirma la operación.", "success");
        } catch (error) {
            const cached = cachedWorkerByIdentification(identificacion);
            if (isConnectivityError(error) && cached) {
                const open = await localOpenShift(cached.id);
                showAttendanceTarget(cached, open, false,
                    "La identificación coincide con el directorio local. Pulsa «Continuar sin conexión»; el servidor validará vigencia y turno al sincronizar.", true);
                setStatus(status, "No se pudo contactar con el servidor: coincidencia local encontrada. La cédula no autentica ni sustituye tu sesión.", "error");
            } else {
                setStatus(status, isConnectivityError(error)
                    ? "No se pudo contactar con el servidor y esa identificación no está en el directorio local. Conéctate para buscarla."
                    : error.message, "error");
            }
        }
    });

    $("confirm-attendance").addEventListener("click", async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        $("continue-offline").hidden = true;
        try {
            let operation = pendingAttendanceOperationId
                ? (await queueAll()).find((item) => item.operacion_id === pendingAttendanceOperationId)
                : null;
            if (operation?.estado === "confirmada") {
                setStatus("attendance-result", `${operation.tipo === "entrada" ? "Entrada" : "Salida"} confirmada en Supabase.`, "success");
                $("scan-next").hidden = false;
                return;
            }
            if (operation?.estado === "necesita_revision") {
                setStatus("attendance-result", `${operation.mensaje} La operación requiere revisión y no se reenviará automáticamente.`, "error");
                return;
            }
            if (!operation) {
                const ocurrio = new Date().toISOString();
                setStatus("attendance-result", "Obteniendo GPS; si no está disponible, continuarás sin ubicación…");
                const ubicacion = await locationOptional();
                const payload = {
                    ...(selectedWorkerId !== null ? { trabajador_id: selectedWorkerId } : { qr: selectedQr }),
                    ocurrio_en: ocurrio, ...ubicacion,
                };
                if (selectedAction === "entrada") {
                    payload.cot = contextCot;
                    payload.proyecto = contextProject;
                }
                operation = {
                    operacion_id: createIdempotencyKey(),
                    tipo: selectedAction,
                    trabajador_id: selectedWorkerId ?? fieldDirectory?.coordinador?.id,
                    cot: payload.cot || "",
                    proyecto: payload.proyecto || "",
                    ocurrio_en: ocurrio,
                    payload,
                    estado: "pendiente",
                };
                pendingAttendanceOperationId = operation.operacion_id;
                await savePending(operation, "Guardada en este dispositivo; pendiente de validación en Supabase.");
            }
            if (selectedOffline) {
                setStatus("attendance-result", `Operación ${operation.operacion_id} pendiente en este dispositivo. Aún no está guardada en Supabase.`, "success");
                $("scan-next").hidden = false;
                return;
            }
            if (!navigator.onLine) {
                setStatus("attendance-result", `Se perdió la conexión. La operación ${operation.operacion_id} quedó pendiente localmente y no está guardada en Supabase.`, "error");
                $("continue-offline").hidden = false;
                return;
            }
            const syncResult = await syncPending();
            const saved = (await queueAll()).find((item) => item.operacion_id === operation.operacion_id);
            if (saved?.estado === "confirmada") {
                const action = selectedAction === "entrada" ? "Entrada" : "Salida";
                setStatus("attendance-result", `${action} confirmada en Supabase.`, "success");
                $("scan-next").hidden = false;
            } else if (saved?.estado === "necesita_revision") {
                setStatus("attendance-result", `${saved.mensaje} La operación permanece visible para revisión; no está confirmada en Supabase.`, "error");
            } else if (syncResult?.network || saved?.causa === "conectividad") {
                setStatus("attendance-result", `Falló la conexión durante el registro. La operación ${operation.operacion_id} quedó pendiente localmente. Pulsa «Continuar sin conexión» para seguir; se reintentará automáticamente.`, "error");
                $("continue-offline").hidden = false;
            } else if (saved?.causa === "servidor") {
                setStatus("attendance-result", "El servidor no confirmó el registro por un error temporal. Sigue pendiente y no está guardado en Supabase; se reintentará automáticamente.", "error");
            } else {
                setStatus("attendance-result", syncResult?.error?.message
                    ? `${syncResult.error.message} La operación permanece pendiente; no está guardada en Supabase.`
                    : "El servidor no confirmó el registro. La operación sigue pendiente y no se considera guardada en Supabase.", "error");
            }
        } catch (error) {
            button.disabled = false;
            const saved = pendingAttendanceOperationId
                ? (await queueAll()).find((item) => item.operacion_id === pendingAttendanceOperationId)
                : null;
            logClientDiagnostic(error, {
                targetId: "attendance-result",
                operationType: selectedAction,
                localState: saved?.estado || "sin_registro_local",
            });
            if (saved?.estado === "confirmada") {
                setStatus("attendance-result", `${selectedAction === "entrada" ? "Entrada" : "Salida"} confirmada en Supabase.`, "success");
                $("continue-offline").hidden = true;
                $("scan-next").hidden = false;
            } else if (isConnectivityError(error) && saved) {
                setStatus("attendance-result", `Se perdió la conexión. La operación ${saved.operacion_id} sigue pendiente localmente; pulsa «Continuar sin conexión».`, "error");
                $("continue-offline").hidden = false;
            } else {
                const savedMessage = saved
                    ? `La operación está en IndexedDB con estado «${saved.estado}»; no se considera confirmada en Supabase.`
                    : "No se encontró un registro local de esta operación.";
                setStatus("attendance-result", `${error.message} ${savedMessage} No se clasificó como caída de red.`, "error");
            }
        }
    });

    $("continue-offline").addEventListener("click", () => {
        $("continue-offline").hidden = true;
        $("scan-next").hidden = false;
        setStatus("attendance-result", "Continuando sin conexión. La operación permanece pendiente y se enviará al servidor cuando vuelva la conexión.", "success");
    });

    $("scan-next").addEventListener("click", () => {
        selectedQr = "";
        selectedWorkerId = null;
        selectedOffline = false;
        pendingAttendanceOperationId = null;
        $("worker-card").hidden = true;
        startCamera();
    });

    const visitButton = $("register-visit");
    visitButton.addEventListener("click", async () => {
        const status = $("visit-status");
        if (pendingVisitOperation) {
            pendingVisitOperation = null;
            lastVisitOperationId = null;
            visitOfflineChoice = false;
            setText(visitButton, "Registrar visita");
            setStatus(status, "La visita sigue pendiente en este dispositivo. No está confirmada en Supabase y se reintentará al recuperar conexión.", "success");
            return;
        }
        if (!visitCoordinatorId || !visitProject) {
            setStatus(status, "Completa el proyecto e identifica al coordinador de la sesión antes de registrar.", "error");
            return;
        }
        visitButton.disabled = true;
        try {
            let operation = lastVisitOperationId
                ? (await queueAll()).find((item) => item.operacion_id === lastVisitOperationId)
                : null;
            if (operation?.estado === "confirmada") {
                setStatus(status, "Visita confirmada en Supabase.", "success");
                lastVisitOperationId = null;
                setText(visitButton, "Registrar otra visita");
                return;
            }
            if (operation?.estado === "necesita_revision") {
                setStatus(status, `${operation.mensaje} La visita requiere revisión; no se reenviará automáticamente.`, "error");
                return;
            }
            if (!operation) {
                const ocurrio = new Date().toISOString();
                setStatus(status, "Obteniendo GPS; si no está disponible, la visita se guardará sin coordenadas…");
                const ubicacion = await locationOptional();
                operation = {
                    operacion_id: createIdempotencyKey(), tipo: "visita", trabajador_id: null,
                    ocurrio_en: ocurrio, payload: {
                        ...(coordinatorQr ? { qr: coordinatorQr } : {}),
                        coordinador_id: visitCoordinatorId,
                        proyecto: visitProject,
                        trabajador_id: visitWorkerId,
                        ocurrio_en: ocurrio,
                        ...ubicacion,
                    },
                    estado: "pendiente",
                };
                lastVisitOperationId = operation.operacion_id;
                await savePending(operation, "Visita guardada en este dispositivo; pendiente de validación en Supabase.");
            }
            if (visitOfflineChoice) {
                setStatus(status, `Visita ${operation.operacion_id} pendiente en este dispositivo. GPS: ${operation.payload.ubicacion_estado}. Aún no está guardada en Supabase.`, "success");
                setText(visitButton, "Registrar otra visita");
                lastVisitOperationId = null;
                visitOfflineChoice = false;
                return;
            }
            if (!navigator.onLine) {
                pendingVisitOperation = operation;
                visitOfflineChoice = true;
                setText(visitButton, "Continuar sin conexión");
                setStatus(status, `La conexión se perdió. La visita ${operation.operacion_id} quedó pendiente localmente y no está guardada en Supabase. Pulsa «Continuar sin conexión».`, "error");
                return;
            }
            const syncResult = await syncPending();
            const saved = (await queueAll()).find((item) => item.operacion_id === operation.operacion_id);
            if (saved?.estado === "confirmada") {
                setStatus(status, "Visita confirmada en Supabase.", "success");
                lastVisitOperationId = null;
                setText(visitButton, "Registrar otra visita");
            } else if (saved?.estado === "necesita_revision") {
                setStatus(status, `${saved.mensaje} La visita permanece en la cola para revisión; no está confirmada.`, "error");
                setText(visitButton, "Registrar otra visita");
            } else if (syncResult?.network || saved?.causa === "conectividad") {
                pendingVisitOperation = operation;
                visitOfflineChoice = true;
                setText(visitButton, "Continuar sin conexión");
                setStatus(status, `Se perdió la conexión. La visita ${operation.operacion_id} quedó pendiente y no está guardada en Supabase. Pulsa «Continuar sin conexión» para seguir.`, "error");
            } else {
                const serverMessage = saved?.causa === "servidor" && saved.mensaje
                    ? `El servidor respondió: ${saved.mensaje}`
                    : (syncResult?.error?.message || "El servidor no confirmó la visita.");
                setStatus(status, `${serverMessage} La operación sigue pendiente en el dispositivo y no está confirmada en Supabase.`, "error");
                setText(visitButton, "Reintentar visita pendiente");
            }
        } catch (error) {
            const saved = lastVisitOperationId
                ? (await queueAll()).find((item) => item.operacion_id === lastVisitOperationId)
                : null;
            logClientDiagnostic(error, {
                targetId: "visit-status",
                operationType: "visita",
                localState: saved?.estado || "sin_registro_local",
            });
            if (saved?.estado === "confirmada") {
                setStatus(status, "Visita confirmada en Supabase.", "success");
                lastVisitOperationId = null;
                setText(visitButton, "Registrar otra visita");
            } else if (isConnectivityError(error) && saved) {
                pendingVisitOperation = saved;
                visitOfflineChoice = true;
                setText(visitButton, "Continuar sin conexión");
                setStatus(status, `La visita ${saved.operacion_id} sigue pendiente localmente.`, "error");
            } else {
                const savedMessage = saved
                    ? `La visita está en IndexedDB con estado «${saved.estado}»; no se considera confirmada en Supabase.`
                    : "No se encontró un registro local de esta visita.";
                setStatus(status, `${error.message || "No se pudo conservar la visita localmente."} ${savedMessage} No se clasificó como caída de red.`, "error");
            }
        } finally {
            visitButton.disabled = false;
        }
    });

    window.addEventListener("pagehide", stopCamera);
    window.addEventListener("beforeunload", stopCamera);
})();
