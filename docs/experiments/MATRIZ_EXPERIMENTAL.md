# Matriz experimental y método

Fuente normativa: evidence/sources/consigna-oficial-20261101.txt. 36 celdas:
1/3/5 nodos, dificultad fija 1/2/3, concurrencia 1/2/5/10. Matriz obligatoria: 36 PASS de 36 ejecutados / 36 previstos. Limpieza: PASS.
Las cargas 50/101 son adicionales; no se amplían durante el cierre.

Cada solicitud registra un documento sintético distinto. Se espera propagación al
mempool de todos los nodos; un minero produce el bloque; se sincroniza y compara la
cadena completa, recalculando hashes, reglas PoW, trabajo y validez de transacciones.
Se verifica inclusión exactamente una vez de cada transacción aceptada en cada nodo.
Una respuesta HTTP recibida no equivale a aceptación; sólo 202 se cuenta como aceptada.

Latencias HTTP y p95 nearest-rank; throughput = aceptadas / ventana de envío;
hash rate = intentos / segundos de minería; propagación y sync son observaciones
del cliente, con sondeo cada 0,2 s. CPU es tiempo del proceso API dividido por el
intervalo de muestreo; la suma puede superar 100% de un núcleo. RAM es RSS posterior,
no pico. No equivale a utilización de toda la VM ni consumo eléctrico.

Una iteración por celda; tamaños 1/2/5 tienen poca información de cola para p95.
Los tres/cinco nodos no son máquinas independientes. Sólo se activa un minero por
celda: no se midió competencia de mineros ni 1 API/3 workers o 2 APIs/3 workers.
Los resultados calculados se distinguen de muestras originales en CSV/JSON.

Estrés: el 503 plano Service Unavailable concuerda con el límite Uvicorn32; no es
422 de esquema, 409 de conflicto ni un bloque inválido. Se conservan rechazos y
limitaciones de correlación de los primeros intentos rechazados. No se los marca PASS.
