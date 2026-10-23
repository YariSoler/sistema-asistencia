(() => {
    const $ = (id) => document.getElementById(id);
    const sections = [$("flow-choice"), $("cot-flow"), $("scanner-flow"), $("visit-flow")];
    const camera = $("camera-preview");
    const cameraStatus = $("camera-status");
    let mediaStream = null;
    let scanLoopActive = false;
    let detector = null;
    let selectedQr = "";
    let selectedAction = "";
    let contextCot = "";
    let contextProject = "";
    let scanPurpose = "attendance";
    let coordinatorQr = "";
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";

    function showSection(id) {
        stopCamera();
        sections.forEach((section) => { section.hidden = section.id !== id; });
    }

    function stopCamera() {
        scanLoopActive = false;
        if (mediaStream) {
            mediaStream.getTracks().forEach((track) => track.stop());
            mediaStream = null;
        }
        if (camera) camera.srcObject = null;
        if (camera) camera.hidden = true;
        const placeholder = $("camera-placeholder");
        if (placeholder) placeholder.hidden = false;
    }

    function setStatus(element, message, kind = "") {
        element.textContent = message;
        element.classList.toggle("is-error", kind === "error");
        element.classList.toggle("is-success", kind === "success");
    }

    async function sendJson(url, body) {
        const response = await fetch(url, {
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
        catch (_) { throw new Error("El servidor respondió en un formato inesperado."); }
        if (!response.ok) throw new Error(result.error || "No se pudo completar el registro.");
        return result;
    }

    function formatDate(value) {
        if (!value) return "fecha no disponible";
        return new Intl.DateTimeFormat("es-CO", {
            dateStyle: "medium", timeStyle: "short", timeZone: "America/Bogota",
        }).format(new Date(value));
    }

    document.querySelectorAll("[data-show]").forEach((button) => {
        button.addEventListener("click", () => {
            scanPurpose = "attendance";
            showSection(button.dataset.show);
        });
    });
    document.querySelectorAll("[data-back]").forEach((button) => {
        button.addEventListener("click", () => showSection("flow-choice"));
    });

    $("cot-form").addEventListener("submit", (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        contextCot = String(form.get("cot") || "").trim();
        contextProject = String(form.get("proyecto") || "").trim();
        if (!contextCot || !contextProject) return;
        $("project-context").textContent = `${contextCot} | ${contextProject}`;
        $("worker-card").hidden = true;
        showSection("scanner-flow");
        $("scanner-title").textContent = "Escanea el QR del trabajador o tu QR de coordinador";
        $("scanner-description").textContent = "El coordinador solo puede registrar su propia asistencia; el personal debe estar activo para iniciar un turno.";
    });

    async function findWorker(qr) {
        if (scanPurpose === "visit") {
            setStatus(cameraStatus, "Validando el QR de coordinador con la sesión…");
            try {
                const result = await sendJson("/api/visitas-tecnicas/verificar-coordinador", { qr });
                coordinatorQr = qr;
                $("visit-coordinator-confirmation").textContent = `Coordinador identificado: ${result.coordinador.nombre}.`;
                $("visit-coordinator-confirmation").classList.remove("is-error");
                $("visit-coordinator-confirmation").classList.add("is-success");
                $("register-visit").disabled = false;
                showSection("visit-flow");
            } catch (error) {
                coordinatorQr = "";
                $("register-visit").disabled = true;
                setStatus(cameraStatus, error.message, "error");
            }
            return;
        }
        selectedQr = qr;
        $("worker-card").hidden = true;
        setStatus(cameraStatus, "Consultando el QR con el servidor…");
        try {
            const result = await sendJson("/api/asistencia/qr", { qr });
            selectedAction = result.accion;
            $("worker-name").textContent = result.trabajador.nombre;
            $("worker-detail").textContent = result.trabajador.cargo || "Trabajador";
            const openDetail = $("open-attendance-detail");
            if (result.registro_abierto) {
                openDetail.textContent = `Entrada abierta: ${result.registro_abierto.cot} · ${result.registro_abierto.proyecto} · ${formatDate(result.registro_abierto.fecha_entrada)}`;
                openDetail.hidden = false;
            } else {
                openDetail.hidden = true;
            }
            $("confirm-attendance").textContent = selectedAction === "entrada" ? "Confirmar entrada" : "Confirmar salida";
            $("confirm-attendance").disabled = false;
            $("attendance-result").textContent = "";
            $("scan-next").hidden = true;
            $("worker-card").hidden = false;
            setStatus(cameraStatus, "Código encontrado. Revisa el nombre y confirma la acción.", "success");
        } catch (error) {
            setStatus(cameraStatus, error.message, "error");
        }
    }

    async function startCamera() {
        stopCamera();
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            setStatus(cameraStatus, "Este navegador no permite abrir la cámara aquí. Usa la entrada manual del QR o prueba con HTTPS.", "error");
            return;
        }
        if (!("BarcodeDetector" in window)) {
            setStatus(cameraStatus, "Este navegador no incluye lector QR. Usa Chrome o Edge actualizado, o ingresa el contenido del QR manualmente.", "error");
            return;
        }
        try {
            const formats = await BarcodeDetector.getSupportedFormats();
            if (!formats.includes("qr_code")) throw new Error("El navegador no admite códigos QR.");
            detector = new BarcodeDetector({ formats: ["qr_code"] });
            mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: false,
                video: { facingMode: { ideal: "environment" } },
            });
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
                } catch (_) {
                    // El siguiente cuadro de vídeo puede ser legible aunque este no lo sea.
                }
                if (scanLoopActive) window.requestAnimationFrame(scanFrame);
            };
            window.requestAnimationFrame(scanFrame);
        } catch (error) {
            stopCamera();
            setStatus(cameraStatus, error.name === "NotAllowedError"
                ? "No se concedió permiso para usar la cámara. Puedes habilitarlo en el navegador o ingresar el QR manualmente."
                : (error.message || "No fue posible abrir la cámara."), "error");
        }
    }

    $("start-camera").addEventListener("click", startCamera);
    $("identify-visit-coordinator").addEventListener("click", () => {
        scanPurpose = "visit";
        $("scanner-title").textContent = "Identifica al coordinador";
        $("scanner-description").textContent = "El QR debe pertenecer a la cuenta de coordinador que inició esta sesión.";
        setStatus(cameraStatus, "Activa la cámara o escribe el contenido de tu QR.");
        showSection("scanner-flow");
        void startCamera();
    });
    $("manual-qr-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const qr = String(new FormData(event.currentTarget).get("qr") || "").trim();
        if (qr) await findWorker(qr);
    });

    $("confirm-attendance").addEventListener("click", async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        setStatus($("attendance-result"), "Guardando en Supabase…");
        try {
            const endpoint = selectedAction === "entrada" ? "/api/asistencia/entrada" : "/api/asistencia/salida";
            const body = { qr: selectedQr };
            if (selectedAction === "entrada") {
                body.cot = contextCot;
                body.proyecto = contextProject;
            }
            const result = await sendJson(endpoint, body);
            const registro = result.registro || {};
            const momento = selectedAction === "entrada" ? registro.fecha_entrada : registro.fecha_salida;
            setStatus($("attendance-result"), `${result.mensaje} ${formatDate(momento)} (hora de Colombia).`, "success");
            $("scan-next").hidden = false;
        } catch (error) {
            button.disabled = false;
            setStatus($("attendance-result"), error.message, "error");
        }
    });

    $("scan-next").addEventListener("click", () => {
        selectedQr = "";
        $("worker-card").hidden = true;
        $("manual-qr-form").reset();
        startCamera();
    });

    function createIdempotencyKey() {
        if (crypto.randomUUID) return crypto.randomUUID();
        const bytes = new Uint8Array(16);
        crypto.getRandomValues(bytes);
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
        return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
    }

    let pendingVisit = null;
    const visitButton = $("register-visit");
    async function sendVisit(payload) {
        const status = $("visit-status");
        visitButton.disabled = true;
        setStatus(status, "Guardando visita en Supabase…");
        try {
            const result = await sendJson("/api/visitas-tecnicas", payload);
            const registrado = (result.registro || {}).registrado_en;
            setStatus(status, `${result.mensaje} ${formatDate(registrado)} (hora de Colombia).`, "success");
            pendingVisit = null;
        } catch (error) {
            setStatus(status, `${error.message} Si reintentas, se enviarán los mismos datos con la misma clave.`, "error");
        } finally {
            visitButton.disabled = false;
        }
    }

    visitButton.addEventListener("click", () => {
        const status = $("visit-status");
        if (!coordinatorQr) {
            setStatus(status, "Identifícate con tu QR de coordinador antes de registrar la visita.", "error");
            return;
        }
        if (pendingVisit) {
            void sendVisit(pendingVisit);
            return;
        }
        if (!navigator.geolocation) {
            setStatus(status, "Este navegador no ofrece geolocalización.", "error");
            return;
        }
        visitButton.disabled = true;
        setStatus(status, "Solicitando ubicación al dispositivo…");
        navigator.geolocation.getCurrentPosition(async (position) => {
            const { latitude, longitude, accuracy } = position.coords;
            setStatus(status, `Ubicación obtenida (precisión aproximada: ${Math.round(accuracy)} m).`);
            pendingVisit = {
                latitud: latitude,
                longitud: longitude,
                precision_m: accuracy,
                idempotency_key: createIdempotencyKey(),
                qr: coordinatorQr,
            };
            await sendVisit(pendingVisit);
        }, (error) => {
            const message = error.code === error.PERMISSION_DENIED
                ? "No se concedió permiso de ubicación. Habilítalo para registrar una visita."
                : (error.code === error.TIMEOUT ? "El dispositivo tardó demasiado en obtener la ubicación. Inténtalo de nuevo." : "No fue posible obtener la ubicación GPS.");
            setStatus(status, message, "error");
            visitButton.disabled = false;
        }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
    });

    window.addEventListener("pagehide", stopCamera);
})();
