document.addEventListener("DOMContentLoaded", () => {
    if (new URLSearchParams(window.location.search).get("imprimir") === "1") {
        window.addEventListener("load", () => window.print(), { once: true });
    }
    document.querySelectorAll("[data-print]").forEach((button) => button.addEventListener("click", () => window.print()));
    const store = document.getElementById("store_id");
    const name = document.querySelector("[data-store-name]");
    if (store && name) {
        const update = () => { name.required = store.value === ""; };
        store.addEventListener("change", update);
        update();
    }
    document.querySelectorAll("[data-live-clock]").forEach((clock) => {
        const serverTime = Date.parse(clock.dateTime);
        const started = performance.now();
        if (!Number.isFinite(serverTime)) return;
        const format = new Intl.DateTimeFormat("es-PY", { timeZone: "America/Asuncion", dateStyle: "short", timeStyle: "medium" });
        const tick = () => { clock.textContent = format.format(new Date(serverTime + performance.now() - started)); };
        tick();
        setInterval(tick, 1000);
    });
});
