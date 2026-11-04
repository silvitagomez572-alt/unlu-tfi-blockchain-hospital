# HISJB: despliegue temporal propuesto, todavía NO ejecutado

Actualizado 04/11/2026. Esta preparación no acredita un despliegue.

## Aislamiento y autorización recibida

Silvia autorizó el 04/11/2026 un máximo total de USD 2 antes de impuestos,
con duración máxima de dos horas y estimación de USD 0,5901. Incluye publicar
los cambios revisados en la rama `tfi/despliegue-temporal`, validarlos en un runner,
crear exclusivamente este proyecto y eliminar sus recursos temporales al terminar.
La autorización no acredita ninguna ejecución: las validaciones nuevas y cuotas
deben comprobarse antes de crear el clúster.

La cuenta 01091D-82ABD9-7BDBC4 respondió `open=true`; la titular tiene
`roles/billing.admin`. TP2, TP3 y Lab 3 tienen `billingEnabled=true`, comprobado
por consulta actual. Ninguno es el destino de este TFI.

No figura un proyecto del TFI entre los seis proyectos accesibles. La consulta a
`unlu-tfi-hisjb-20261104` devolvió «sin permiso o puede no existir»; no demuestra
disponibilidad global del ID. Se propone ese ID exclusivamente. Si estuviera ocupado,
se debe resolver la identidad antes de crear recursos, sin usar otro laboratorio.

No se crearon proyectos, APIs, identidades, registros ni recursos facturables.
No se puede certificar aún la cuota del proyecto propuesto: no es accesible.
Las cuotas de otro proyecto no se transfieren como evidencia de este preflight.

## Orden obligatorio tras aprobar el presupuesto

1. Verificar disponibilidad del ID y permiso para crear proyecto. Aplicar sólo
   bootstrap en su propio directorio de estado, con el importe autorizado.
2. Vincular sólo el nuevo proyecto a 7BDBC4 y verificar su billingEnabled.
3. Verificar las APIs GKE/Compute/AR/IAM/STS del nuevo proyecto y consultar allí:
   `gcloud compute regions describe us-central1 --project=unlu-tfi-hisjb-20261104`,
   `gcloud compute project-info describe --project=unlu-tfi-hisjb-20261104`,
   `gcloud container get-server-config --zone=us-central1-a --project=unlu-tfi-hisjb-20261104`.
   Se necesitan 4 CPU E2 y 4 CPU totales regionales libres, 1 IPv4 externa, al menos
   80 GiB de disco estándar y capacidad para 1 clúster zonal. Se solicitan 10 GiB
   por PVC, mínimo documentado de Persistent Disk estándar. No asumir cuotas.
4. Guardar inventario previo vacío de VMs, discos, IP, forwarding rules, clústeres
   y repositorios del nuevo proyecto. Registrar propiedad/identificadores de cada
   recurso creado y el plan JSON de OpenTofu. Parar si hay recursos preexistentes.
5. Verificar con testIamPermissions los permisos efectivos de creación de red/GKE,
   uso de cuenta de servicio y lectura/escritura del registro. No ampliar roles de
   otros proyectos. El publicador OIDC sólo tiene Writer sobre el nuevo repositorio.
6. Publicar la imagen desde el repo TFI ID 1444937330, rama tfi/despliegue-temporal,
   por workflow_dispatch y OIDC. Revisar commit, ausencia de secretos, digest base
   y digest resultante. No publicar el ZIP o los datos/credenciales locales.
7. Iniciar reloj de costos antes del primer recurso facturable. Aplicar runtime
   con una sola VM e2-standard-4; GKE REGULAR, zona us-central1-a. No autoscaling.
   Registrar versión efectiva. Fijar /32 del operador para el endpoint de GKE.
8. Crear únicamente namespace tfi-hospital, secretos efímeros y configuración común
   de actores sintéticos; nunca incluir secretos en YAML versionado, logs o PDF.
   Instalar StorageClass exclusiva y Helm por digest. Validar 1, después 3/5 pods.
9. Abrir la aplicación usando `kubectl port-forward --address 127.0.0.1 pod/hisjb-0
   19980:19980 -n tfi-hospital`. Si el puerto local ya está ocupado por HISJB, detener
   sólo su supervisor después de conservar el estado. No publicar Ingress/LB.

## Modelo de ejecución y medición

Cada pod tiene una API, un hilo minero y un PVC. Cinco pods NO son cinco VMs.
Una VM física compartida limita las conclusiones sobre tolerancia a fallos y escala.
El perfil Kubernetes sólo permite los DNS exactos de hisjb-0 a hisjb-4 en su namespace;
excluye self. La consola exige cliente loopback más Host, sesión y CSRF originales.
La API entre pods conserva sus credenciales de rol; NetworkPolicy restringe la red.
La persistencia de QR es local a cada nodo: no se afirma revocación distribuida.

Matriz pedida: 1/3/5 nodos, dificultades 1/2/3, concurrencias 1/2/5/10 (36 celdas).
La consigna original también pide 50 y más de 100; se agregan 50/101 como 18 celdas
complementarias. Total 54 celdas por repetición. Las dificultades se fijan por red
durante la comparación controlada; demostrar dificultad dinámica por separado.
No confundir los mineros por nodo con 1 API/3 workers independientes: no implementado.

Cada escenario usa un subdirectorio nuevo en su PVC; nunca sobrescribir una red
con otra configuración ni borrar las cadenas anteriores. Solicitudes de registro
usan documentos/UUID diferentes y fixtures sintéticos. Respetar el límite de
120 solicitudes/minuto por rol y no atribuir 429 a consenso. Espaciar las celdas
para evitar arrastre de límites; medir tiempo con reloj monótono. Comparar cadenas
completas y trabajo, no sólo altura. CPU mediante delta cpu.stat y RAM mediante
memory.current/cgroup o métricas identificadas; registrar fuente y periodo.

La matriz aún no se ejecutó ni tiene resultados. Faltan validaciones runtime de
las nuevas configuraciones, build Linux, PVC/GKE y observabilidad del TFI.

## Costos y controles

Estimación calculada en COSTO_PROPUESTO.json: aproximadamente USD 0,59 por 2 horas,
antes de impuestos, incluyendo 48 h de una imagen de hasta 0,5 GiB y una reserva
de tráfico/artefactos. Máximo propuesto: USD 2, aún NO autorizado.
No se descuentan créditos gratuitos. Alertas 50/90/100% no detienen el gasto.
Una imagen retenida puede costar hasta USD 0,05/mes fuera de la cuota gratuita;
por defecto eliminarla tras guardar el digest y evidencia, al finalizar la entrega.

No comenzar un experimento nuevo después de 90 minutos desde la primera creación.
Reservar 30 minutos para exportación y destrucción. No se garantiza un tope técnico
con el presupuesto de Billing; ante gasto previsto mayor o limpieza fallida, parar
las cargas propias, informar y resolver exclusivamente los recursos del TFI.

## Apagado verificable (obligatorio, también ante error crítico)

1. Detener la carga sintética. Guardar logs, recibos, cadenas, mempools, UID de PVC,
   métricas, capturas y decisiones fuera del clúster. Excluir tokens/QR activos.
2. Calcular SHA-256 local y comparar las copias. Abrir ZIP. No borrar PVC antes de
   esta comprobación. Copiar tfstate al almacenamiento privado local, nunca Git.
3. Capturar inventario de UID y nombres. Eliminar sólo el release hisjb y sus PVC
   inventariados del namespace tfi-hospital; la StorageClass tiene reclaimPolicy Delete.
   Verificar que los volúmenes GCE correspondientes desaparezcan; no tocar otros discos.
4. Generar y revisar `tofu plan -destroy` exclusivamente en infrastructure/opentofu/runtime.
   Compararlo con el inventario de esta corrida y aplicar ese plan. Nunca ejecutar
   destroy en bootstrap, cuyo proyecto tiene prevent_destroy.
5. Consultar en el nuevo proyecto VMs, discos, direcciones, forwarding rules,
   balanceadores, clústeres, redes y operaciones pendientes. Una lista vacía verificable
   es el criterio de limpieza, no el mensaje de finalización de Helm.
6. Retirar la única imagen/repositorio nuevo si no se autoriza su conservación;
   conservar evidencia/digest. Desactivar la federación temporal específica del TFI
   y sus identidades si ya no hacen falta. No tocar pools o IAM de TP3/Lab 8.
7. Revocar únicamente la sesión SDK aislada del TFI al terminar las consultas.

## Fuentes de precios y permisos consultadas

- https://cloud.google.com/kubernetes-engine/pricing
- https://cloud.google.com/products/compute/pricing/general-purpose
- https://cloud.google.com/compute/disks-image-pricing
- https://cloud.google.com/vpc/network-pricing
- https://cloud.google.com/artifact-registry/pricing
- https://docs.cloud.google.com/kubernetes-engine/security/configure-node-service-accounts

La lectura de estas tarifas no crea una cotización contractual ni acredita cargos
reales. La facturación pospago no requiere que este procedimiento solicite un pago
anticipado o cambie la tarjeta.
