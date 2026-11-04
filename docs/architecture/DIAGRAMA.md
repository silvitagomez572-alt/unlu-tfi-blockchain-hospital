# Diagrama lógico del despliegue observado

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
