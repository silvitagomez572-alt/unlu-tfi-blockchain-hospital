# Despliegue GKE verificado y apagado

Matriz obligatoria: 36 PASS de 36 ejecutados / 36 previstos. Limpieza: PASS.

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
