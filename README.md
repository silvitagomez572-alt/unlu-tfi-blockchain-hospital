# UNLu · Trabajo Final Integrador · Blockchain hospitalaria sintética

**Silvia Andrea Gómez Villagra · Individual · Curso 3**

Proyecto local independiente del Lab 8. Se agregó una API FastAPI por nodo,
persistencia conjunta de cadena/mempool, propagación y sincronización P2P local.
**No es un sistema apto para documentación clínica real ni un despliegue GKE.**
El estado comprobado de esta fase está en `RESULTADOS_FASE2.json` y `INFORME_FASE2.txt`.

Consigna vigente: propuesta **10/11/2026**; entrega final **20/12/2026**.
`INFORME_INICIO.txt` y `CHECKLIST_INICIO.json` conservan el estado histórico de fase 1.
La copia de sus documentos/manifiesto está en `evidence/phase2/phase1-documents/`;
el manifiesto vigente de esta fase es `MANIFIESTO_FASE2_SHA256.json`.

## Procedencia

Base de la cátedra: `dpetrocelli/infra-cloud-template`, continuada en
`silvitagomez572-alt/unlu-lab4-infra-cloud-template`, commit
`d4b159c57e208a8a433ff6ac97b3b94098518aa0`.
`reference/lab8/` conserva copias exactas de los archivos seleccionados, sin activar
sus workflows ni aplicar sus configuraciones. `evidence/SOURCE_MANIFEST.json`
registra los hashes y la correspondencia con los blobs Git.

`blockchain/block.py` conserva el enfoque del template: bloque, cabecera JSON
canónica, SHA-256 y nonce. Se modularizan y extienden dificultad, validación y
selección de cadenas; el formato nuevo **no es compatible** con las cadenas del Lab 8.
La persistencia del adaptador de fase 2 reutiliza el patrón temporal + fsync + replace
del template y agrega checksum, identidad, cadena/mempool juntos y lock por directorio.

## Qué puede usarse ahora

- `NetworkConfig`: parámetros consensuados y huella de identidad de red.
- `Block` / `Transaction`: modelos inmutables y metadatos sintéticos cerrados.
- `mine_next`: minado local con presupuesto de intentos y tiempo, sin mutar la cadena.
- `validate_chain`: estructura, génesis, enlaces, dificultad, prueba de trabajo,
  transacciones y rechazo de repeticiones exactas.
- `choose_best_chain`: función pura de selección por trabajo acumulado y desempate.
- `verify_document_hash`: búsqueda local y detección de coincidencia, alteración,
  ausencia o conflicto de hashes para una versión. La API de fase 2 lo expone en
  `/documents/verify`; el registro acepta solo fixtures sintéticos.

No se implementaron firmas, permisos de actores, orden administrativo de eventos ni
política completa de versiones. Los identificadores
de actor no autentican a nadie. El indicador “sintético” es una regla operativa:
un hash o UUID no demuestra por sí mismo que su origen no contenga datos personales.

## Estructura

```
blockchain/        núcleo local y selección de forks
node/             FastAPI, estado, snapshots, esquemas y transporte P2P
tests/unit/       casos acotados del nuevo motor
tests/integration/ ciclo multinodo aprobado y escenarios de consenso A/B pendientes
infrastructure/   decisiones y contratos de variables; sin recursos aplicables aún
docs/             arquitectura, API prevista, seguridad y experimentación
reference/lab8/   referencia auditada, no aplicación activa
evidence/         fuentes, trazabilidad y registros verificables
tools/            preparación de fuentes, ejecución acotada y auditoría de archivos
```

## Reproducir las pruebas, cuando haya capacidad

Python 3.12. El núcleo usa únicamente la biblioteca estándar. Pytest 8.3.5 se
encuentra en `.runtime/test-tools` como copia local de herramientas ya instaladas;
no se descargaron paquetes ni se modificó su instalación original. Para un equipo
nuevo, preparar un entorno virtual independiente e instalar `requirements-test.txt`.

Desde la raíz, con un Python 3.12 válido, ejecutar una invocación por vez:

```powershell
python -B tools/run_bounded_tests.py protocol
python -B tools/run_bounded_tests.py validation
python -B tools/run_bounded_tests.py forks_document
```

El supervisor es específico de Windows y comprueba RAM antes de crear pytest.
Si un grupo falla, se interrumpe o queda bloqueado, revisar su evidencia antes de
continuar. No ejecutar las tres órdenes como lote automático. Requiere 640 MiB
disponibles; límite de proceso 192 MiB; timeout 12 s; pila a los 6 s;
interrupción si quedan menos de 384 MiB. Cada proceso pertenece a un Job Object
propio; solo ese proceso puede ser terminado por el supervisor.

En otro sistema, ejecutar los mismos node IDs de `tools/run_bounded_tests.py`
con pytest, pero con un supervisor de recursos equivalente. No se afirma que el
supervisor Windows sea portable.

## Límites operativos

No hay remoto, commits, runners, builds ni recursos GCP creados por esta entrega.
Los procesos locales de pruebas se crean bajo supervisor y se apagan al concluir.
Las pruebas del Lab 8 son antecedentes, no resultados del TFI.
La publicación remota, OIDC, Artifact Registry y GKE requieren autorización posterior.
El presupuesto histórico de Lab 8 no es un presupuesto disponible para GKE.

La red HTTP local ya tiene evidencia de propagación, recuperación y reconvergencia.
Restan los ensayos específicos A/B, Helm/GKE, CI/CD, observabilidad y matriz experimental.
Consultar el backlog antes
de avanzar. No se promete validez judicial, cadena de custodia legal ni cumplimiento
normativo automático.

## API y ejecución local de fase 2

Consultar `docs/api/API_FASE2.txt`, `docs/architecture/PERSISTENCIA_P2P_FASE2.txt`
y `docs/EJECUCION_LOCAL_FASE2.txt`. Los archivos `config/local/node-*.example.json`
son ejemplos sin ejecutar: verificar los puertos y presupuesto antes de usarlos.
Desde la raíz del proyecto, un proceso por configuración:

```powershell
python -B tools/start_local_node.py --config config/local/node-0.example.json
```

Repetir para las configuraciones 1 y 2 solo cuando esté autorizado y haya memoria.
El wrapper utiliza las dependencias locales aisladas. No inicia otros nodos automáticamente.
Las rutas `var/node-*` se resuelven respecto del directorio actual: ejecutar desde la raíz.

Las pruebas se ejecutan mediante `tools/run_phase2_test.py` con un único node ID.
No usar `run_bounded_tests.py` de fase 1 para repetir las 35 pruebas aprobadas.
El supervisor espera hasta 15 s por el mínimo de memoria antes de iniciar; esa espera
no amplía los 12 s del test unitario ni los 90 s de un escenario de integración.
En el entorno restringido de Codex, asyncio puede bloquearse al crear su socketpair:
los tests HTTP requieren permiso de loopback; no quitar timeouts para ocultar el fallo.

## Recuperación del ensayo de consenso

`docs/experiments/PLAN_RUNNER_CONSENSO.txt` y `.github/workflows/tfi-consensus.yml`
preparan dos jobs Ubuntu aislados. Es un borrador sin publicar ni ejecutar.
El preflight de integración conserva **1 GiB** como mínimo y no inicia nodos
si no se cumple. A quedó BLOCKED por RAM; B continúa sin ejecución.
La validación estática del workflow no acredita el resultado de consenso.
La fecha objetivo personal de entrega es **06/11/2026**; la consigna adjunta
vigente, modificada el 01/11, fija 20/12/2026 como fecha oficial.
