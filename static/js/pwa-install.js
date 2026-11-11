/* Installation UI only: no service worker, cache, requests or session changes. */
(() => {
    const strip = document.getElementById("installStrip");
    const button = document.getElementById("installApp");
    const hint = document.getElementById("installHint");
    const guide = document.getElementById("installGuide");
    const steps = document.getElementById("installSteps");
    if (!strip || !button || !guide) return;

    const standalone = window.matchMedia("(display-mode: standalone)");
    const installedKey = "samudio-pwa-installed";
    let deferredPrompt = null;
    let installed = false;
    try { installed = localStorage.getItem(installedKey) === "yes"; } catch (_) { /* Storage can be blocked. */ }
    const isStandalone = () => standalone.matches || navigator.standalone === true;
    const update = () => {
        strip.hidden = installed || isStandalone();
        hint.textContent = deferredPrompt
            ? "Confirma la instalación en tu navegador."
            : "Ver instrucciones para tu navegador.";
    };
    const rememberInstalled = () => {
        installed = true;
        deferredPrompt = null;
        try { localStorage.setItem(installedKey, "yes"); } catch (_) { /* No storage required. */ }
        if (guide.open) guide.close();
        update();
    };
    window.addEventListener("beforeinstallprompt", (event) => {
        event.preventDefault();
        deferredPrompt = event;
        // A fresh prompt also allows reinstallation after a previous uninstall.
        installed = false;
        try { localStorage.removeItem(installedKey); } catch (_) { /* Optional. */ }
        update();
    });
    window.addEventListener("appinstalled", rememberInstalled);
    standalone.addEventListener("change", update);
    window.addEventListener("pageshow", update);

    const showGuide = (retry = false) => {
        const ios = /iPad|iPhone|iPod/.test(navigator.userAgent)
            || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
        let instructions;
        if (ios) {
            instructions = [
                "Abre samudiohnos.com en Safari.",
                "Toca Compartir (el cuadrado con una flecha hacia arriba). Según tu versión, puede estar dentro del menú Más.",
                "Selecciona Agregar a pantalla de inicio. Si no aparece, revisa Editar acciones.",
                "Activa Abrir como app web si aparece y toca Agregar."
            ];
        } else if (/Android/i.test(navigator.userAgent)) {
            instructions = [
                "Abre samudiohnos.com en Chrome u otro navegador compatible, fuera de WhatsApp o redes sociales.",
                "Abre el menú del navegador y busca Instalar aplicación o Agregar a pantalla de inicio.",
                "Confirma si la opción está disponible. Si no aparece, usa un marcador o prueba otro navegador."
            ];
        } else {
            instructions = [
                "En Chrome o Edge, busca el icono de instalación en la barra de direcciones o la opción de instalar en el menú.",
                "En Safari para Mac, busca Archivo > Agregar al Dock, si está disponible.",
                "Si tu navegador no ofrece instalación, guarda la tienda en Favoritos o Marcadores."
            ];
        }
        steps.replaceChildren();
        if (retry) {
            const note = document.createElement("p");
            note.textContent = "No se pudo abrir la solicitud automática. Puedes usar el menú del navegador:";
            steps.append(note);
        }
        const list = document.createElement("ol");
        instructions.forEach((instruction) => {
            const item = document.createElement("li");
            item.textContent = instruction;
            list.append(item);
        });
        steps.append(list);
        guide.showModal();
    };
    button.addEventListener("click", async () => {
        if (isStandalone() || installed) return;
        if (!deferredPrompt) { showGuide(); return; }
        const prompt = deferredPrompt;
        deferredPrompt = null;
        button.disabled = true;
        try {
            // Called directly from this click, preserving real user activation.
            await prompt.prompt();
            const choice = await prompt.userChoice;
            if (choice.outcome === "accepted") rememberInstalled();
        } catch (_) {
            if (!isStandalone() && !installed) showGuide(true);
        } finally {
            button.disabled = false;
            update();
        }
    });
    if (isStandalone()) rememberInstalled();
    update();
})();
