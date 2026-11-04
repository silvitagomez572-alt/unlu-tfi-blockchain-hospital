"""Update current documentation from preserved evidence, backing up older prose."""
import json
import shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/phase4/gke-runtime-20261104'

def write(name,text):
    dest=ROOT/name
    old=ROOT/'evidence/phase4/documentacion-previa'/name
    if dest.exists() and not old.exists():
        old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,old)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(text.strip()+'\n',encoding='utf-8')

def main():
    a=json.loads((OUT/'ANALISIS_CARGA.json').read_text())
    clean=json.loads((OUT/'CLEANUP.json').read_text()) if (OUT/'CLEANUP.json').exists() else {'status':'NOT TESTED'}
    count=a['core_executed'];passed=sum(r['category']=='core' and r['status']=='PASS' for r in a['cells'])
    summary=f'Matriz obligatoria: {passed} PASS de {count} ejecutados / 36 previstos. Limpieza: {clean["status"]}.'
    write('README.md',f'''# HISJB Evidence Chain - TFI UNLu

Silvia Andrea Gómez Villagra · Modalidad individual · Actualización 04/11/2026.
Prototipo educativo de trazabilidad documental con datos exclusivamente sintéticos.

## Resultado comprobado

Se ejecutó realmente en Google Kubernetes Engine, proyecto exclusivo
`unlu-tfi-hisjb-20261104`, clúster temporal `hisjb-tfi-temp`, namespace `tfi-hospital`.
Una VM e2-standard-4 alojó de uno a cinco nodos blockchain independientes, cada uno
con FastAPI, un hilo minero y un PVC. No son cinco máquinas ni cinco operadores independientes.
{summary}

La consola mostró transacciones reales, minería, bloques, coincidencia SHA-256,
alteración detectada, historial y QR revocado. La persistencia sobrevivió a recrear
`hisjb-0`: cambió el UID del pod, se conservó el UID del PVC y el estado fue idéntico.
Prometheus registró hasta cinco targets UP. Grafana se ejecutó en el mismo GKE.
Las capturas existentes son originales; las faltantes no se sustituyen por imágenes fabricadas.

## Reproducibilidad

- Motor y API: `blockchain/`, `node/`, `documents/`; consola `webconsole/`.
- Entrada de contenedor: `python -B -m deployment.cluster`; puerto interno 19980.
- Docker: `Dockerfile`, dependencias fijadas, usuario 10001, healthcheck.
- Helm: `infrastructure/helm/hisjb`; StatefulSet, headless Service, PVC y NetworkPolicy.
- IaC: `infrastructure/opentofu/`; ejecución comprobada con Terraform 1.14.9.
- CI/OIDC: `.github/workflows/tfi-image.yml`; la publicación real fue la corrida 41886329974.
- Especificación de rutas: `docs/api/ENDPOINTS.md`.
- Datos medidos: `MATRIZ_EXPERIMENTAL.csv`, resultados JSON y logs en `evidence/phase4/`.

La imagen deriva de `681343963bb0315f68ddd1e49855e1a8460eeb25`, con digest
`sha256:0d78467787e7d20d8b648a3b3887a5d848e880607a0f4296247343fe0377230a`.
La identificación GKE de la consola y correcciones de Helm se aplicaron mediante
ConfigMap/configuración, sin alterar el motor ni reconstruir esa imagen.

## Demostración local

Con Python 3.12, dependencias y al menos 1 GiB disponible:

```powershell
python -B tools/serve_hisjb_demo.py --port 19980 --minutes 60
```

Abrir `http://127.0.0.1:19980/console/`. Este supervisor mantiene los límites de RAM,
sesión, Host/Origin y CSRF. Una URL documentada no implica que el servidor siga encendido.
No repetir ensayos aprobados para abrir la aplicación. No aplicar IaC automáticamente:
revalidar identidad del proyecto, permisos, cuota, plan y presupuesto.

## Procedencia y límites

Conservé el template `dpetrocelli/infra-cloud-template` en `reference/lab8/`,
referencia `d4b159c57e208a8a433ff6ac97b3b94098518aa0`; no modifiqué Lab 8.
Las cadenas del TFI tienen formato y reglas propios; no se reutilizan silenciosamente
estados de Lab 8. Consenso: trabajo acumulado verificable y desempate lexicográfico.
Los 35 tests de núcleo, 11 de API y A/B anteriores no se repitieron durante GKE.

No hay granja de workers separada de las APIs. La matriz activa un minero por celda;
los demás nodos validan y sincronizan. QR usa SQLite por nodo y no se replica por consenso.
Los roles son simulados; no se afirma firma digital, validez judicial ni cumplimiento automático.
La trazabilidad completa de rechazos con correlación durable requiere trabajo adicional.
La consigna original conservada del 01/11 exige 1,3,5 nodos; tres dificultades;
concurrencia 1,2,5,10. Las pruebas 50/101 son estrés adicional.

Consigna vigente conservada: propuesta 10/11/2026 y entrega final 20/12/2026.
La fecha personal de cierre solicitada es 06/11/2026. Consultar checklist y PDF para
los límites académicos; no confundir ejecución técnica con una aceptación de la cátedra.
''')
    write('docs/architecture/ARQUITECTURA.md','''# Arquitectura comprobada de HISJB

Una consola estática del mismo origen utiliza sesión, CSRF y operaciones cerradas
del adaptador ASGI; éste llama la API documental FastAPI real. Cada nodo dispone de
cadena, mempool, identidad, lista de peers, locks y persistencia independientes.
Los documentos son fixtures sintéticos externos al bloque; dentro se guardan hash,
identificadores seudónimos, versión, evento, actor simulado y timestamp.

## API, almacenamiento y procesamiento

API de recepción no equivale a nodo: es la interfaz del nodo. Un HTTP 202 admite
una transacción pendiente; su confirmación requiere inclusión en un bloque válido.
El snapshot JSON conserva cadena y mempool juntos con checksum, escritura temporal,
fsync y reemplazo atómico. SQLite guarda los accesos QR locales con hash del token.
El hilo de minería por nodo ejecuta PoW con lock, intentos y tiempo acotados; no es
un worker independiente ni una cola compartida por múltiples APIs.

El motor valida cadenas completas antes de adoptar mayor trabajo acumulado; en un
empate aplica orden lexicográfico del hash final. Se propagan transacciones y bloques
y se sincronizan peers. La matriz GKE compara las cadenas completas, no sólo alturas.

## Despliegue real

GKE zonal us-central1-a, una VM e2-standard-4, 1/3/5 pods, cinco PVC de 10 GiB como
máximo. Service headless y DNS estable, NetworkPolicy y puerto HTTP/métricas 19980.
La consola se accedió exclusivamente por túnel autenticado con escucha localhost.
Prometheus y Grafana compartieron un pod temporal con datos en emptyDir exportados.
No hubo balanceador público ni segundo clúster.

Se corrigió DNS del Service mediante una regla exacta /32 TCP/UDP53 y los cambios
de perfil se hicieron coordinadamente con OnDelete, conservando PVC. No se retiró
readiness ni se aumentaron timeouts para simular salud. Los perfiles experimentales
usan subdirectorios de estado distintos; la demo original quedó preservada.

## Límites

Los nodos comparten una sola máquina y administración. Esto prueba independencia
lógica y convergencia, no tolerancia a la pérdida del único host ni descentralización
institucional. La política documental exige pasos confirmados y reenvío ordenado tras
reorganizaciones. QR no es estado consensuado. El historial confirmado es durable;
el último tiempo de minería de la UI y algunos contadores reinician con el proceso.
''')
    write('docs/architecture/DIAGRAMA.md','''# Diagrama lógico del despliegue observado

```mermaid
flowchart LR
  B[Navegador / consola] --> T[Túnel kubectl autenticado localhost]
  T --> A[FastAPI y sesión CSRF]
  subgraph GKE[Proyecto exclusivo / una VM GKE]
    A --> N0[hisjb-0: API + hilo PoW]
    N0 <--> N1[hisjb-1: API + hilo PoW]
    N1 <--> NN[hisjb-2 a 4 según escenario]
    NN <--> N0
    N0 --> D0[PVC0 / JSON y SQLite]
    N1 --> D1[PVC1 / JSON y SQLite]
    NN --> DN[PVC2 a 4 independientes]
    P[Prometheus] --> N0
    P --> N1
    P --> NN
    F[Grafana] --> P
  end
  I[GitHub Actions OIDC] --> AR[Artifact Registry / una imagen]
  AR --> GKE
```

Diagrama explicativo, no captura de infraestructura. Los cinco nodos lógicos comparten
una VM. La consola es servida por el mismo backend; A es una responsabilidad, no un
proceso adicional. El clúster temporal se elimina tras exportar evidencias.
''')
    write('docs/deployment/GKE.md',f'''# Despliegue GKE verificado y apagado

{summary}

Proyecto exclusivo `unlu-tfi-hisjb-20261104`; clúster `hisjb-tfi-temp`, us-central1-a;
namespace `tfi-hospital`. Una VM e2-standard-4, disco de arranque estándar 30 GiB,
hasta cinco PVC estándar de 10 GiB. Sin LoadBalancer, NAT ni autoscaling.

La ejecución se inicia sólo después de revisar `runtime-plan-review.json` y los
seis recursos exactos del plan. `tools/gke_runtime.py` implementa etapas plan,
create, connect, install, snapshot, persistence y cleanup. No ejecutar nuevamente
para leer este informe: son operaciones con efectos reales.

La entrada pública del control plane se limita a la IP /32 del operador. La consola
se abre por `kubectl port-forward --address=127.0.0.1`, nunca mediante un Service
externo. Las credenciales de rol se generan fuera del repo y se montan como Secret.

Apagado: exportar JSON y snapshots consistentes SQLite con SHA-256; verificar que
cada PVC tenga propietario exportado; desinstalar sólo HISJB y eliminar esos PVC;
terraform plan -destroy y revisión de seis direcciones; apply del plan de destrucción;
inventario de clústeres, VM, discos, direcciones y forwarding rules del proyecto.
`CLEANUP.json` es la evidencia del resultado, no una promesa de eliminación.

Límite autorizado actualizado USD3 antes de impuestos; duración prevista dos horas. Estimación previa USD0,5901;
no equivale a cargo real. Las alertas de presupuesto no cortan cargos. Artifact Registry
puede conservar la única imagen y generar almacenamiento residual fuera de la cuota.
No se modificaron proyectos previos. Los logs sensibles y estado Terraform no forman
parte del paquete público.
''')
    write('docs/deployment/HELM.md','''# Helm y persistencia

Chart: `infrastructure/helm/hisjb`. Valores: digest inmutable de imagen, replicas
1/3/5, dificultad 1/2/3 y perfil experimental. StatefulSet `hisjb`, Service
`hisjb-headless`, PVC independientes `data-hisjb-0` a `data-hisjb-4`.
Se validaron lint y template y se aplicó el chart en GKE. Readiness `/readyz` exige
estado sincronizado/aislado; liveness `/healthz` comprueba el proceso.

No copiar el digest o namespace de otro laboratorio. El Service publica direcciones
antes de Ready para descubrimiento P2P; eso no convierte un pod no saludable en Ready.
NetworkPolicy permite aplicación y DNS necesarios, incluyendo DNS Service /32 53.
El mecanismo OnDelete coordina reemplazos al cambiar parámetros consensuados;
acepta downtime temporal de laboratorio y conserva el PVC. No es un rollout HA.

La consola GKE se monta mediante ConfigMap con checksum para distinguir entorno,
proyecto, namespace y nodo real. La imagen del motor permanece idéntica.
''')
    write('docs/deployment/DOCKER.md','''# Imagen reproducible

Dockerfile multicomponente único con Python 3.12.12-slim-bookworm fijado por digest,
dependencias fijadas en requirements-node/documents, usuario 10001:10001,
HEALTHCHECK /healthz y entrada `python -B -m deployment.cluster`.
La base exacta y digest final están en IMAGE_VERIFIED.json y el workflow tfi-image.yml.

Variables: TFI_REPLICAS, TFI_DIFFICULTY, TFI_DIFFICULTY_MODE, TFI_EXPERIMENT;
HOSTNAME identifica el pod. `/data` debe ser volumen independiente por nodo;
`/config/actors.json` es configuración sintética; `/run/hisjb/credentials.json` es
un secreto efímero externo al código. No ejecutar el contenedor sin esos archivos.
Los puertos internos no deben publicarse indiscriminadamente.

La prueba de contenedor 41876907701 ejecutó el recorrido real y reinicio con datos
persistentes; sus doce capturas son de Chromium en runner, no de GKE ni Edge.
La publicación OIDC 41886329974 construyó exclusivamente HISJB y verificó el digest.
No se repitieron builds para las correcciones de DNS/Helm o etiquetas de consola.
''')
    write('docs/deployment/OPENTOFU.md','''# Infraestructura como código

La consigna permite Terraform u OpenTofu. Se usó Terraform 1.14.9 con provider
hashicorp/google 5.45.2; no se presenta OpenTofu como ejecutado.
Bootstrap: APIs, presupuesto, Artifact Registry, OIDC y permisos restringidos.
Runtime: red, subred, cuenta de nodo, permisos mínimos y clúster temporal.
El proyecto está validado por igualdad exacta; no admite otro ID.

Validación previa: fmt -check, init -backend=false y validate; Helm lint/template y
actionlint. Plan revisado antes de aplicar. El estado Terraform permanece privado.
No se incluyen estados ni planes binarios en el ZIP. El entorno de autenticación
usa sesión temporal del SDK y OIDC sin claves JSON permanentes.

La configuración final explicita monitoring_config vacío y managed_prometheus=false;
el cambio se verificó mediante operación DONE. La observabilidad de esta prueba se
ejecutó dentro de la VM ya prevista, con exportación antes de destruir el clúster.
''')
    write('docs/experiments/MATRIZ_EXPERIMENTAL.md',f'''# Matriz experimental y método

Fuente normativa: evidence/sources/consigna-oficial-20261101.txt. 36 celdas:
1/3/5 nodos, dificultad fija 1/2/3, concurrencia 1/2/5/10. {summary}
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
''')
    write('docs/REFLEXION_TECNICA.md','''# Reflexión técnica

Construí un prototipo que admite eventos documentales sintéticos, los enlaza con
SHA-256 y conserva cadenas independientes. Comprobé propagación, selección de forks,
reinicio y recuperación. El resultado no equivale a la seguridad económica de una
blockchain pública ni a una infraestructura hospitalaria aprobada.

La dificultad baja permite observar el algoritmo con recursos acotados; elevarla
consume trabajo y tiempo, pero no reemplaza la distribución del control. Mis nodos
GKE compartieron una VM: una falla del host afecta a todos. No medí consumo eléctrico.
Los ensayos A/B y la matriz son casos concretos, no una prueba general de seguridad.

El circuito informado por la estudiante contiene mesa de entrada, dirección,
departamento legal y Bioestadística. Roles y eventos se simulan; no acreditan identidad
institucional. Registrar un hash permite contrastar una copia, no establecer quién
la produjo, su veracidad ni su validez judicial. Hashes y seudónimos pueden correlacionarse.

Los documentos deben permanecer en infraestructura institucional segura. Un QR
temporal limita consultas futuras, pero no revoca una copia descargada. La base QR
es local y no se replica por consenso. Tampoco una escritura atómica sustituye backups.

Si un único administrador controla todos los nodos, una base de datos con auditoría
firmada puede ser más simple y suficiente. La validación independiente aporta valor
si actores con controles separados necesitan contrastar el registro; mi despliegue
académico no demuestra esa separación organizacional.

Para el Curso 4 quedan identidad institucional, gobierno de permisos, disponibilidad,
replicación segura de concesiones y validación del circuito con usuarios. No afirmo
cumplimiento normativo, firma digital ni cadena de custodia legal automática.
''')
    security=(ROOT/'docs/security/SEGURIDAD_Y_PRIVACIDAD.md').read_text(encoding='utf-8')
    security=security.replace('Bind exclusivo en 127.0.0.1.','Bind local en 127.0.0.1; dentro del pod GKE la API escucha en 0.0.0.0:19980, protegida por NetworkPolicy. La consola sólo se accede mediante túnel localhost autenticado.')
    security=security.replace('Docker sin root,\nIAM, OIDC y políticas GKE del TFI todavía no están desplegados.','Docker sin root, IAM mínimo, OIDC y políticas GKE del TFI se ejecutaron y verificaron en el entorno temporal.')
    write('docs/security/SEGURIDAD_Y_PRIVACIDAD.md',security)
    print(summary)

if __name__=='__main__':main()
