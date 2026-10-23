const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const crypto = require("node:crypto").webcrypto;

class Element {
    constructor(id) {
        this.id = id;
        this._textContent = "";
        this.failAttendanceConfirmationOnce = false;
        this.hidden = ["cot-flow", "scanner-flow", "visit-flow", "visit-identification-stage", "visit-participants-stage", "worker-card", "camera-preview", "continue-offline", "scan-next", "clear-visit-worker"].includes(id);
        this.disabled = false;
        this.value = "";
        this.dataset = {};
        this.listeners = {};
        this.children = [];
        this.classList = { add() {}, remove() {}, toggle() {} };
    }
    get textContent() { return this._textContent; }
    set textContent(value) {
        if (this.id === "attendance-result" && this.failAttendanceConfirmationOnce && /confirmada en Supabase/i.test(value)) {
            this.failAttendanceConfirmationOnce = false;
            throw new TypeError("Cannot set properties of null (setting 'textContent')");
        }
        if (this.id === "visit-status" && this.failVisitConfirmationOnce && /confirmada en Supabase/i.test(value)) {
            this.failVisitConfirmationOnce = false;
            throw new TypeError("Cannot set properties of null (setting 'textContent')");
        }
        this._textContent = value;
    }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    async dispatch(name, extra = {}) {
        const callback = this.listeners[name];
        if (!callback) throw new Error(`No listener ${name} on ${this.id}`);
        return callback({ preventDefault() {}, currentTarget: this, ...extra });
    }
    replaceChildren() { this.children = []; }
    appendChild(child) { this.children.push(child); }
    reset() { this.value = ""; this.values = {}; }
    async play() {}
}

function makeQrScannerConstructor(holder) {
    return class TestQrScanner {
        constructor(_video, callback, options) {
            this.callback = callback;
            this.options = options;
            this.stopped = false;
            this.destroyed = false;
            holder.instance = this;
        }
        async start() { holder.started = true; }
        stop() { this.stopped = true; }
        destroy() { this.destroyed = true; }
        async emit(data) { await this.callback({ data }); }
    };
}

function createIndexedDb(seedQueue = [], state = null) {
    const stores = state?.stores || new Map();
    let objectStoreNames = state?.objectStoreNames || new Set();
    return {
        stores,
        state: { stores, get objectStoreNames() { return objectStoreNames; } },
        open() {
            const req = {};
            queueMicrotask(() => {
                const db = {
                    get objectStoreNames() { return { contains: (name) => objectStoreNames.has(name) }; },
                    createObjectStore(name) {
                        objectStoreNames.add(name);
                        stores.set(name, new Map(name === "queue" ? seedQueue.map((item) => [item.operacion_id, item]) : []));
                    },
                    transaction(name) {
                        const tx = { objectStore() {
                            const data = stores.get(name);
                            return {
                                getAll() { return requestFor([...data.values()], tx); },
                                get(key) { return requestFor(data.get(key), tx); },
                                put(value) { data.set(value.operacion_id || value.key, value); return requestFor(value, tx); },
                            };
                        } };
                        return tx;
                    },
                };
                req.result = db;
                req.onupgradeneeded?.();
                req.onsuccess?.();
            });
            return req;
        },
    };
}

function requestFor(value, tx) {
    const req = {};
    req.transaction = tx;
    queueMicrotask(() => {
        req.result = value;
        req.onsuccess?.();
        req.transaction?.oncomplete?.();
    });
    return req;
}

function createHarness(harnessOptions = {}) {
    const ids = [
        "flow-choice", "cot-flow", "scanner-flow", "visit-flow", "offline-flow", "camera-preview", "connection-status", "directory-status",
        "refresh-directory", "queue-status", "pending-count", "pending-operations", "sync-pending", "cot-form", "cot",
        "proyecto", "project-context", "worker-card", "manual-id-form", "manual-id", "identification-status", "camera-status",
        "scanner-title", "scanner-description", "camera-placeholder", "start-camera", "worker-name", "worker-detail",
        "open-attendance-detail", "confirm-attendance", "continue-offline", "attendance-result", "scan-next",
        "visit-coordinator-confirmation", "register-visit", "identify-visit-coordinator", "visit-status",
        "visit-project-form", "visit-project", "visit-identification-stage", "visit-project-context",
        "visit-coordinator-id-form", "visit-coordinator-id", "visit-coordinator-id-status", "visit-participants-stage",
        "visit-worker-confirmation", "scan-visit-worker", "visit-worker-id-form", "visit-worker-id", "visit-worker-id-status", "clear-visit-worker",
    ];
    const elements = new Map(ids.map((id) => [id, new Element(id)]));
    elements.get("register-visit").disabled = true;
    for (const id of harnessOptions.missingIds || []) elements.delete(id);
    if (harnessOptions.failAttendanceConfirmationOnce) {
        elements.get("attendance-result").failAttendanceConfirmationOnce = true;
    }
    if (harnessOptions.failVisitConfirmationOnce) elements.get("visit-status").failVisitConfirmationOnce = true;
    const windowEvents = {};
    const documentEvents = {};
    const requests = [];
    const opIdFromBody = [];
    const retryDelays = [];
    const retryTimers = [];
    const diagnostics = [];
    let entryAttempts = 0;
    let exitAttempts = 0;
    let visitAttempts = 0;
    const directory = {
        actualizado_en: "2026-10-23T12:00:00Z",
        trabajadores: [{ id: 15, identificacion: "12345", nombre: "Ana Prueba", cargo: "Operario", qr: "qr-15", registro_abierto: null }],
        coordinador: { id: 7, nombre: "Coordinador", qr: "qr-7", registro_abierto: null },
    };
    const fetch = async (url, requestOptions = {}) => {
        requests.push({ url, options: requestOptions });
        if (url === "/api/asistencia/directorio-offline") return response(200, directory);
        if (url === "/api/asistencia/buscar-identificacion") return harnessOptions.identificationResponse || response(200, {
            trabajador: { id: 15, nombre: "Ana Prueba", cargo: "Operario" }, accion: "entrada", registro_abierto: null,
        });
        if (url === "/api/asistencia/csrf") return response(200, { csrf_token: "csrf-test" });
        if (url === "/api/visitas-tecnicas/verificar-coordinador") return harnessOptions.coordinatorQrResponse || response(200, { coordinador: { id: 7, nombre: "Coordinador" } });
        if (url === "/api/visitas-tecnicas/verificar-coordinador-identificacion") return harnessOptions.coordinatorIdResponse || response(200, { coordinador: { id: 7, nombre: "Coordinador" } });
        if (url === "/api/visitas-tecnicas/buscar-operario") return harnessOptions.visitWorkerResponse || response(200, { operario: { id: 15, nombre: "Ana Prueba", cargo: "Operario" } });
        if (url === "/api/visitas-tecnicas") {
            visitAttempts += 1;
            const body = JSON.parse(requestOptions.body);
            opIdFromBody.push(body.operacion_id);
            return harnessOptions.visitRegisterResponse || response(201, { operacion_id: body.operacion_id, registro: { id: 109, coordinador_id: 7 } });
        }
        if (url === "/api/asistencia/entrada") {
            entryAttempts += 1;
            const body = JSON.parse(requestOptions.body);
            opIdFromBody.push(body.operacion_id);
            if (entryAttempts <= (harnessOptions.failEntryAttempts ?? 2)) throw new TypeError("Failed to fetch");
            return harnessOptions.entryResponse || response(201, { operacion_id: body.operacion_id, registro: { id: 99, trabajador_id: 15 } });
        }
        if (url === "/api/asistencia/salida") {
            exitAttempts += 1;
            const body = JSON.parse(requestOptions.body);
            opIdFromBody.push(body.operacion_id);
            return response(201, { operacion_id: body.operacion_id, registro: { id: 99, trabajador_id: 15 } });
        }
        throw new Error(`Unexpected request ${url}`);
    };
    const document = {
        getElementById: (id) => elements.get(id) || null,
        querySelector: () => ({ content: "csrf-in-page" }),
        querySelectorAll: () => [],
        createElement: () => new Element("created"),
        head: { appendChild(script) {
            requests.push({ script: script.src, integrity: script.integrity });
            queueMicrotask(() => {
                if (harnessOptions.scriptLoadResults?.[script.src] === false) {
                    script.onerror();
                    return;
                }
                if (harnessOptions.qrScanner) context.window.QrScanner = makeQrScannerConstructor(harnessOptions.qrScanner);
                script.onload();
            });
        } },
        addEventListener: (name, fn) => { documentEvents[name] = fn; },
        visibilityState: "visible",
    };
    const window = {
        addEventListener: (name, fn) => { windowEvents[name] = fn; },
        setTimeout: (callback, delay) => {
            retryDelays.push(delay);
            const timer = { callback, delay, cancelled: false };
            retryTimers.push(timer);
            return timer;
        },
        clearTimeout(timer) { if (timer) timer.cancelled = true; },
        requestAnimationFrame() {},
    };
    class TestFormData {
        constructor(form) { this.form = form; }
        get(key) { return this.form.values?.[key] ?? this.form[key]?.value ?? ""; }
    }
    const indexedDB = createIndexedDb(harnessOptions.seedQueue || [], harnessOptions.indexedDBState || null);
    const context = {
        document, window, navigator: { onLine: harnessOptions.online !== false }, indexedDB, crypto, fetch,
        FormData: TestFormData, Intl, Date, Math, JSON,
        console: { error(...args) { diagnostics.push(args); } },
        BarcodeDetector: undefined,
    };
    context.window.document = document;
    context.window.navigator = context.navigator;
    context.window.crypto = crypto;
    context.window.BarcodeDetector = undefined;
    context.window.requestAnimationFrame = harnessOptions.cameraQr
        ? (callback) => setTimeout(callback, 0)
        : () => {};
    if (harnessOptions.cameraQr) {
        let scanned = false;
        class TestBarcodeDetector {
            static async getSupportedFormats() { return ["qr_code"]; }
            async detect() {
                if (scanned) return [];
                scanned = true;
                return [{ rawValue: harnessOptions.cameraQr }];
            }
        }
        context.BarcodeDetector = TestBarcodeDetector;
        context.window.BarcodeDetector = TestBarcodeDetector;
        context.navigator.mediaDevices = { async getUserMedia() { return { getTracks() { return [{ stop() {} }]; } }; } };
    }
    if (harnessOptions.qrScanner) {
        if (!harnessOptions.deferQrScanner) context.window.QrScanner = makeQrScannerConstructor(harnessOptions.qrScanner);
        context.navigator.mediaDevices = { async getUserMedia() { return { getTracks() { return [{ stop() {} }]; } }; } };
    }
    let initError = null;
    try {
        vm.runInNewContext(fs.readFileSync("static/js/asistencia.js", "utf8"), context, { filename: "asistencia.js" });
    } catch (error) {
        initError = error;
        if (!harnessOptions.allowInitFailure) throw error;
    }
    return { elements, indexedDB, indexedDBState: indexedDB.state, diagnostics, initError, windowEvents, documentEvents, requests, opIdFromBody, retryDelays, retryTimers, get entryAttempts() { return entryAttempts; }, get exitAttempts() { return exitAttempts; }, get visitAttempts() { return visitAttempts; } };
}

function response(status, data) {
    return { ok: status >= 200 && status < 300, status, async json() { return data; } };
}

async function prepareVisit(ui, project = "Obra de prueba") {
    const form = ui.elements.get("visit-project-form");
    form.values = { proyecto: project };
    await form.dispatch("submit");
}

test("búsqueda por cédula, pérdida al registrar y reintento automático conservan el UUID", async () => {
    const ui = createHarness();
    await new Promise((resolve) => setTimeout(resolve, 0));
    const form = ui.elements.get("manual-id-form");
    form.values = { identificacion: "12345" };
    await form.dispatch("submit");

    assert.equal(ui.elements.get("worker-name").textContent, "Ana Prueba");
    assert.equal(ui.elements.get("identification-status").textContent, "Trabajador activo encontrado. Confirma la operación.");
    assert.equal(ui.elements.get("continue-offline").hidden, true);

    await ui.elements.get("confirm-attendance").dispatch("click");
    assert.equal(ui.entryAttempts, 1);
    assert.equal(ui.elements.get("continue-offline").hidden, false);
    assert.deepEqual(ui.retryDelays, [2000]);
    assert.match(ui.elements.get("attendance-result").textContent, /no está guardada en Supabase|Continuar sin conexión/);
    assert.equal(ui.elements.get("pending-count").textContent, "1");

    await ui.elements.get("continue-offline").dispatch("click");
    assert.equal(ui.elements.get("scan-next").hidden, false);
    ui.retryTimers[0].callback();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(ui.entryAttempts, 2);
    assert.deepEqual(ui.retryDelays, [2000, 4000]);
    await ui.windowEvents.online();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(ui.entryAttempts, 3);
    assert.equal(ui.opIdFromBody[0], ui.opIdFromBody[1]);
    assert.equal(ui.opIdFromBody[1], ui.opIdFromBody[2]);
    assert.match(ui.elements.get("attendance-result").textContent, /confirmada en Supabase/i);
    assert.equal(ui.elements.get("pending-count").textContent, "0");
});

test("un rechazo de autorización no ofrece ni guarda el flujo sin conexión", async () => {
    const ui = createHarness({ identificationResponse: response(403, { error: "Solo un coordinador puede registrar asistencia." }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    const form = ui.elements.get("manual-id-form");
    form.values = { identificacion: "12345" };
    await form.dispatch("submit");

    assert.equal(ui.elements.get("worker-card").hidden, true, ui.elements.get("identification-status").textContent);
    assert.equal(ui.elements.get("continue-offline").hidden, true);
    assert.match(ui.elements.get("identification-status").textContent, /Solo un coordinador/);
    assert.equal(ui.elements.get("pending-count").textContent, "0");
});

test("la clasificación HTTP 503 previa del flujo COT se mantiene sin cambios", async () => {
    const ui = createHarness({ failEntryAttempts: 0, entryResponse: response(503, { error: "Servicio temporalmente no disponible" }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    const form = ui.elements.get("manual-id-form");
    form.values = { identificacion: "12345" };
    await form.dispatch("submit");
    await ui.elements.get("confirm-attendance").dispatch("click");
    assert.equal(ui.entryAttempts, 1);
    assert.equal(ui.elements.get("continue-offline").hidden, false);
    assert.match(ui.elements.get("attendance-result").textContent, /Falló la conexión/i);
});

test("confirmación online no se reenvía si ocurre una excepción visual después del acuse del servidor", async () => {
    const ui = createHarness({ failEntryAttempts: 0, failAttendanceConfirmationOnce: true });
    await new Promise((resolve) => setTimeout(resolve, 0));
    const form = ui.elements.get("manual-id-form");
    form.values = { identificacion: "12345" };
    await form.dispatch("submit");
    await ui.elements.get("confirm-attendance").dispatch("click");

    assert.equal(ui.entryAttempts, 1, "el UUID confirmado no debe reenviarse por una excepción de interfaz");
    assert.equal(ui.elements.get("pending-count").textContent, "0");
    assert.match(ui.elements.get("attendance-result").textContent, /confirmada en Supabase/i);
    assert.equal(ui.elements.get("continue-offline").hidden, true);
    assert.deepEqual(ui.retryDelays, [], "una excepción de interfaz no debe iniciar reintentos de red");
    assert.match(ui.elements.get("queue-status").textContent, /Error de aplicación/);
    assert.doesNotMatch(ui.elements.get("queue-status").textContent, /La cola sigue guardada en este dispositivo; no se confirmó el envío/i);
    const diagnostics = ui.diagnostics.filter(([label]) => label === "[ACT06] Error de interfaz").map(([, details]) => details);
    const sourceDiagnostic = diagnostics.find((details) => details.targetId === "attendance-result");
    assert.ok(sourceDiagnostic?.line > 0, "el diagnóstico debe señalar el selector y la línea que falló");
    const diagnostic = diagnostics.find((details) => details.localState === "confirmada");
    assert.ok(diagnostic);
    assert.equal(diagnostic.operationType, "entrada");
    assert.equal(diagnostic.localState, "confirmada");
    assert.ok(diagnostic.line > 0);
    await ui.elements.get("confirm-attendance").dispatch("click");
    assert.equal(ui.entryAttempts, 1, "volver a pulsar no debe generar otro UUID después de la confirmación");
});

test("visita técnica confirmada conserva el resultado y no crea otro registro ante una excepción visual", async () => {
    const ui = createHarness({ cameraQr: "qr-7", failVisitConfirmationOnce: true });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await prepareVisit(ui);
    await ui.elements.get("identify-visit-coordinator").dispatch("click");
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(ui.elements.get("register-visit").disabled, false);

    await ui.elements.get("register-visit").dispatch("click");
    assert.equal(ui.visitAttempts, 1);
    assert.match(ui.elements.get("visit-status").textContent, /confirmada en Supabase/i);
    assert.deepEqual(ui.retryDelays, []);
    const diagnostic = ui.diagnostics.map(([, details]) => details).find((details) => details.localState === "confirmada");
    assert.ok(diagnostic);
    assert.equal(diagnostic.operationType, "visita");
    assert.equal(diagnostic.localState, "confirmada");
});

test("confirmación de salida desde búsqueda por identificación completa el turno abierto", async () => {
    const ui = createHarness({
        failEntryAttempts: 0,
        identificationResponse: response(200, {
            trabajador: { id: 15, nombre: "Ana Prueba", cargo: "Operario" }, accion: "salida",
            registro_abierto: { fecha_entrada: "2026-10-23T12:00:00Z", cot: "COT-1", proyecto: "Obra" },
        }),
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    const form = ui.elements.get("manual-id-form");
    form.values = { identificacion: "12345" };
    await form.dispatch("submit");
    assert.equal(ui.elements.get("confirm-attendance").textContent, "Confirmar salida");
    await ui.elements.get("confirm-attendance").dispatch("click");
    assert.equal(ui.exitAttempts, 1);
    assert.match(ui.elements.get("attendance-result").textContent, /Salida confirmada en Supabase/i);
    assert.equal(ui.elements.get("pending-count").textContent, "0");
});

test("la pantalla secundaria conserva tres operaciones pendientes existentes en IndexedDB", async () => {
    const seedQueue = ["offline-a", "offline-b", "offline-c"].map((operacion_id, index) => ({
        operacion_id, tipo: index === 2 ? "visita" : "entrada", trabajador_id: 15,
        ocurrio_en: `2026-10-23T12:0${index}:00Z`, payload: {}, estado: "pendiente",
    }));
    const ui = createHarness({ online: false, seedQueue });
    await new Promise((resolve) => setTimeout(resolve, 0));

    assert.equal(ui.elements.get("pending-count").textContent, "3");
    assert.equal(ui.elements.get("pending-operations").children.length, 3);
    assert.deepEqual([...ui.indexedDB.stores.get("queue").keys()].sort(), ["offline-a", "offline-b", "offline-c"]);
});

test("los selectores DOM requeridos por JavaScript existen en la plantilla Flask actual", () => {
    const script = fs.readFileSync("static/js/asistencia.js", "utf8");
    const template = fs.readFileSync("templates/coordinador/registro.html", "utf8");
    const block = script.match(/const requiredIds = \[([\s\S]*?)\];/);
    assert.ok(block, "debe existir el contrato DOM del módulo");
    const ids = [...block[1].matchAll(/"([^"]+)"/g)].map((match) => match[1]);
    const missing = ids.filter((id) => !template.includes(`id="${id}"`));
    assert.deepEqual(missing, []);
});

test("la plantilla y el cargador alternativo usan el SRI verificado de qr-scanner 1.4.2", () => {
    const script = fs.readFileSync("static/js/asistencia.js", "utf8");
    const template = fs.readFileSync("templates/coordinador/registro.html", "utf8");
    const expected = "sha512-a/IwksuXdv0Q60tVkQpwMk5qY+6cJ0FJgi33lrrIddoFItTRiRfSdU1qogP3uYjgHfrGY7+AC+4LU4J+b9HcgQ==";
    assert.ok(script.includes(expected));
    assert.ok(template.includes(expected));
});

test("una visita pendiente conserva el UUID y su payload original tras navegar y recargar", async () => {
    const original = {
        operacion_id: "visit-original-uuid", tipo: "visita", trabajador_id: null,
        ocurrio_en: "2026-10-23T12:00:00Z", payload: { qr: "qr-7", ubicacion_estado: "no_disponible" },
        estado: "pendiente",
    };
    const ui = createHarness({ online: false, seedQueue: [original] });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await prepareVisit(ui, "Visita nueva");
    const afterNavigation = ui.indexedDB.stores.get("queue").get(original.operacion_id);
    assert.deepEqual(afterNavigation, original);
    const reloaded = createHarness({ online: false, indexedDBState: ui.indexedDBState });
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.deepEqual(reloaded.indexedDB.stores.get("queue").get(original.operacion_id), original);
    assert.deepEqual([...reloaded.indexedDB.stores.get("queue").keys()], [original.operacion_id]);
});

test("si falta un nodo DOM, el diagnóstico identifica selector, archivo y línea sin datos personales", () => {
    const ui = createHarness({ missingIds: ["attendance-result"], allowInitFailure: true });
    assert.match(ui.initError.message, /contrato DOM requerido/);
    const diagnostic = ui.diagnostics.find(([label]) => label === "[ACT06] Error de interfaz");
    assert.ok(diagnostic, "debe quedar un diagnóstico estructurado");
    const details = diagnostic[1];
    assert.equal(details.targetId, "attendance-result");
    assert.match(details.file, /asistencia\.js$/);
    assert.ok(details.line > 0, "debe identificar la línea en el archivo");
    assert.equal(details.errorType, "Error");
    assert.doesNotMatch(JSON.stringify(details), /Ana Prueba|12345|csrf-test|token/i);
});

test("la cola conserva UUID y se renderiza aunque falte pending-count en el HTML entregado", async () => {
    const seedQueue = ["keep-a", "keep-b", "keep-c"].map((operacion_id, index) => ({
        operacion_id, tipo: "entrada", trabajador_id: 15,
        ocurrio_en: `2026-10-23T12:0${index}:00Z`, payload: {}, estado: "pendiente",
    }));
    const ui = createHarness({ missingIds: ["pending-count"], seedQueue, online: false });
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(ui.initError, null);
    assert.deepEqual([...ui.indexedDB.stores.get("queue").keys()].sort(), ["keep-a", "keep-b", "keep-c"]);
    assert.equal(ui.elements.get("pending-operations").children.length, 3);
    assert.equal(ui.diagnostics.some(([, details]) => details.targetId === "pending-count"), false);
    const afterReload = createHarness({ online: false, indexedDBState: ui.indexedDBState });
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.deepEqual([...afterReload.indexedDB.stores.get("queue").keys()].sort(), ["keep-a", "keep-b", "keep-c"]);
});

test("el lector usa BarcodeDetector cuando está disponible", async () => {
    const ui = createHarness({ cameraQr: "qr-15" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    ui.elements.get("start-camera").dispatch("click");
    await new Promise((resolve) => setTimeout(resolve, 5));
    assert.equal(ui.requests.some(({ url }) => url === "/api/asistencia/qr"), true);
});

test("sin BarcodeDetector usa qr-scanner y el QR de coordinador se valida en servidor", async () => {
    const qrScanner = {};
    const ui = createHarness({ qrScanner });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await prepareVisit(ui);
    await ui.elements.get("identify-visit-coordinator").dispatch("click");
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(qrScanner.started, true);
    await qrScanner.instance.emit("qr-7");
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(ui.requests.some(({ url }) => url === "/api/visitas-tecnicas/verificar-coordinador"), true);
    assert.match(ui.elements.get("visit-coordinator-confirmation").textContent, /Coordinador identificado/);
    assert.equal(qrScanner.instance.stopped, true);
    assert.equal(qrScanner.instance.destroyed, true);
});

test("visitas técnicas reintenta la carga del lector en el CDN alternativo y valida el QR con sesión", async () => {
    const qrScanner = {};
    const jsdelivr = "https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner.umd.min.js";
    const cdnjs = "https://cdnjs.cloudflare.com/ajax/libs/qr-scanner/1.4.2/qr-scanner.umd.min.js";
    const ui = createHarness({ qrScanner, deferQrScanner: true, scriptLoadResults: { [jsdelivr]: false } });
    await new Promise((resolve) => setTimeout(resolve, 10));
    await prepareVisit(ui);
    await ui.elements.get("identify-visit-coordinator").dispatch("click");
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(qrScanner.started, true);
    const scripts = ui.requests.filter((item) => item.script);
    assert.deepEqual(scripts.map((item) => item.script), [jsdelivr, cdnjs]);
    assert.ok(scripts.every((item) => item.integrity.startsWith("sha512-")));
    await qrScanner.instance.emit("qr-7");
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(ui.requests.some(({ url }) => url === "/api/visitas-tecnicas/verificar-coordinador"), true);
});

test("visitas muestra el origen de carga si ambos CDN fallan, sin enviar un QR ni cambiar permisos", async () => {
    const qrScanner = {};
    const jsdelivr = "https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner.umd.min.js";
    const cdnjs = "https://cdnjs.cloudflare.com/ajax/libs/qr-scanner/1.4.2/qr-scanner.umd.min.js";
    const ui = createHarness({ qrScanner, deferQrScanner: true, scriptLoadResults: { [jsdelivr]: false, [cdnjs]: false } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await prepareVisit(ui);
    await ui.elements.get("identify-visit-coordinator").dispatch("click");
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.match(ui.elements.get("camera-status").textContent, /cdn.jsdelivr.net.*cdnjs.cloudflare.com.*SRI/i);
    assert.equal(ui.requests.some(({ url }) => url === "/api/visitas-tecnicas/verificar-coordinador"), false);
    assert.equal(ui.elements.get("register-visit").disabled, true);
});

test("un QR rechazado por el servidor no habilita visitas ni concede perfil", async () => {
    const qrScanner = {};
    const ui = createHarness({ qrScanner, coordinatorQrResponse: response(403, { error: "El QR no corresponde al coordinador autenticado." }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await prepareVisit(ui);
    await ui.elements.get("identify-visit-coordinator").dispatch("click");
    await new Promise((resolve) => setTimeout(resolve, 0));
    await qrScanner.instance.emit("qr-7");
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(ui.elements.get("register-visit").disabled, true);
    assert.match(ui.elements.get("camera-status").textContent, /no corresponde/);
});

test("identificación manual del coordinador para visita verifica contra endpoint de sesión", async () => {
    const ui = createHarness({ qrScanner: {} });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await prepareVisit(ui);
    const form = ui.elements.get("visit-coordinator-id-form");
    form.values = { identificacion: "123456" };
    await form.dispatch("submit");
    assert.equal(ui.requests.some(({ url }) => url === "/api/visitas-tecnicas/verificar-coordinador-identificacion"), true);
    assert.equal(ui.requests.some(({ url }) => url === "/api/asistencia/buscar-identificacion"), false);
    assert.match(ui.elements.get("visit-coordinator-confirmation").textContent, /Coordinador identificado/);
    assert.equal(ui.elements.get("register-visit").disabled, false);
});

test("la cédula que no corresponde al coordinador de la sesión no habilita la visita", async () => {
    const ui = createHarness({ qrScanner: {}, coordinatorIdResponse: response(403, { error: "La identificación no corresponde al coordinador autenticado." }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await prepareVisit(ui);
    ui.elements.get("visit-coordinator-id-form").values = { identificacion: "cedula-ajena" };
    await ui.elements.get("visit-coordinator-id-form").dispatch("submit");
    assert.equal(ui.elements.get("register-visit").disabled, true);
    assert.match(ui.elements.get("visit-coordinator-id-status").textContent, /no corresponde/i);
});

test("visita solo coordinador registra proyecto, GPS opcional e identificador estable", async () => {
    const ui = createHarness({ qrScanner: {} });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await prepareVisit(ui, "Bodega Norte");
    ui.elements.get("visit-coordinator-id-form").values = { identificacion: "123456" };
    await ui.elements.get("visit-coordinator-id-form").dispatch("submit");
    await ui.elements.get("register-visit").dispatch("click");
    const request = ui.requests.find(({ url }) => url === "/api/visitas-tecnicas");
    const body = JSON.parse(request.options.body);
    assert.equal(body.proyecto, "Bodega Norte");
    assert.equal(body.coordinador_id, 7);
    assert.equal(body.trabajador_id, null);
    assert.equal(body.ubicacion_estado, "no_disponible");
    assert.match(body.operacion_id, /^[0-9a-f-]{36}$/i);
    assert.match(ui.elements.get("visit-status").textContent, /confirmada en Supabase/i);
});

test("un HTTP 503 al guardar visita se muestra como fallo del servidor, no como falta de internet", async () => {
    const ui = createHarness({ qrScanner: {}, visitRegisterResponse: response(503, { error: "No se encontró la función RPC ACT06." }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await prepareVisit(ui, "Obra pendiente de migración");
    ui.elements.get("visit-coordinator-id-form").values = { identificacion: "123456" };
    await ui.elements.get("visit-coordinator-id-form").dispatch("submit");
    await ui.elements.get("register-visit").dispatch("click");

    const operation = [...ui.indexedDB.stores.get("queue").values()].find((item) => item.tipo === "visita");
    assert.ok(operation);
    assert.equal(operation.estado, "pendiente");
    assert.equal(operation.causa, "servidor");
    assert.match(ui.elements.get("visit-status").textContent, /servidor respondió/i);
    assert.doesNotMatch(ui.elements.get("visit-status").textContent, /Se perdió la conexión|Continuar sin conexión/i);
    assert.equal(ui.elements.get("register-visit").textContent, "Reintentar visita pendiente");
    assert.equal(ui.opIdFromBody.length, 1);
    assert.equal(ui.opIdFromBody[0], operation.operacion_id);
});

test("búsqueda manual de operario activo asocia el participante opcional a la visita", async () => {
    const ui = createHarness({ qrScanner: {} });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await prepareVisit(ui, "Obra Central");
    ui.elements.get("visit-coordinator-id-form").values = { identificacion: "123456" };
    await ui.elements.get("visit-coordinator-id-form").dispatch("submit");
    ui.elements.get("visit-worker-id-form").values = { identificacion: "12345" };
    await ui.elements.get("visit-worker-id-form").dispatch("submit");
    assert.match(ui.elements.get("visit-worker-confirmation").textContent, /Ana Prueba/);
    await ui.elements.get("register-visit").dispatch("click");
    const body = JSON.parse(ui.requests.find(({ url }) => url === "/api/visitas-tecnicas").options.body);
    assert.equal(body.trabajador_id, 15);
    assert.equal(body.proyecto, "Obra Central");
});

test("lector QR selecciona el operario en visita sin pasar por el flujo de asistencia COT", async () => {
    const qrScanner = {};
    const ui = createHarness({ qrScanner });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await prepareVisit(ui);
    ui.elements.get("visit-coordinator-id-form").values = { identificacion: "123456" };
    await ui.elements.get("visit-coordinator-id-form").dispatch("submit");
    await ui.elements.get("scan-visit-worker").dispatch("click");
    await new Promise((resolve) => setTimeout(resolve, 0));
    await qrScanner.instance.emit("qr-worker");
    assert.equal(ui.requests.some(({ url, options }) => url === "/api/visitas-tecnicas/buscar-operario" && JSON.parse(options.body).qr === "qr-worker"), true);
    assert.match(ui.elements.get("visit-worker-confirmation").textContent, /Ana Prueba/);
    assert.equal(ui.requests.some(({ url }) => url === "/api/asistencia/qr"), false);
});
