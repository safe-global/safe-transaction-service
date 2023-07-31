# Safe Transaction Service Chart

This chart packages the Safe transaction service resources. The chart assumes that there is already an existing Postgres, Redis and RabbitMQ instance available and connection attribute should be passed in the values of the Helm Chart

## Parameters

### Common parameters

| Name               | Description                                        | Value |
| ------------------ | -------------------------------------------------- | ----- |
| `nameOverride`     | String to partially override common.names.fullname | `""`  |
| `fullnameOverride` | String to fully override common.names.fullname     | `""`  |

### Installation Parameters

| Name                       | Description                                                      | Value                                 |
| -------------------------- | ---------------------------------------------------------------- | ------------------------------------- |
| `replicas`                 | Replicas for deployment                                          | `1`                                   |
| `strategy`                 | Strategy for deployment                                          | `RollingUpdate`                       |
| `commonLabels`             | Labels to add to all related objects                             | `{}`                                  |
| `commonAnnotations`        | Annotations to to all related objects                            | `{}`                                  |
| `nodeSelector`             | Object containing node selection constraint to deployment        | `{}`                                  |
| `resources`                | Resource specification to deployment                             | `{}`                                  |
| `tolerations`              | Tolerations specifications to deployment                         | `[]`                                  |
| `affinity`                 | Affinity specifications to deployment                            | `{}`                                  |
| `image.registry`           | Docker registry to deployment                                    | `registry.hub.docker.com`             |
| `image.repository`         | Docker image repository to deployment                            | `safeglobal/safe-transaction-service` |
| `image.tag`                | Docker image tag to deployment                                   | `""`                                  |
| `image.pullPolicy`         | Pull policy to deployment as deinfed in                          | `IfNotPresent`                        |
| `service.type`             | service type                                                     | `ClusterIP`                           |
| `service.ports.number`     | service port number                                              | `80`                                  |
| `service.ports.name`       | service port name                                                | `nginx`                               |
| `service.sessionAffinity`  | Control where client requests go, to the same pod or round-robin | `None`                                |
| `ingress.ingressClassName` | Name of the ingress class name to be used                        | `""`                                  |
| `ingress.hostname`         | Default host for the ingress record                              | `safe.cluster.local`                  |
| `ingress.annotations`      | Annotations to be added to ingress resources                     | `{}`                                  |

### Configuration Parameters

| Name                                 | Description                                                                                                   | Value                                           |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `config.secretKey`                   | Transaction Service Secret Key. You should generate a random string of 50+ characters for this value in prod. | `""`                                            |
| `config.secretReferenceKey`          | Reference to an existing secret containing the following entries: DJANGO_SECRET_KEY                           | `""`                                            |
| `config.debug`                       | Enable debug                                                                                                  | `true`                                          |
| `config.ethL2Network`                | Log Level                                                                                                     | `1`                                             |
| `config.ethereumRpcUrl`              |                                                                                                               | `https://rpc.gnosis.gateway.fm` |
| `config.extraEnvVars`                | Add additional extra environment vairables to the configMap                                                   | `{}`                                            |
| `config.django.allowedHosts`         | Allowed hosts                                                                                                 | `*`                                             |
| `config.postgres.secretReferenceKey` | Reference to an existing secret containing the following entry: DATABASE_URL                                  | `""`                                            |
| `config.postgres.username`           | PostgreSQL user                                                                                               | `""`                                            |
| `config.postgres.password`           | PostgreSQL user's password                                                                                    | `""`                                            |
| `config.postgres.database`           | PostgreSQL database name                                                                                      | `safe-transaction`                              |
| `config.postgres.host`               | PostgreSQL server host                                                                                        | `""`                                            |
| `config.postgres.port`               | PostgreSQL server port                                                                                        | `5432`                                          |
| `config.redis.secretReferenceKey`    | Reference to an existing secret containing the following entries: REDIS_URL                                   | `""`                                            |
| `config.redis.username`              | Redis username                                                                                                | `default`                                       |
| `config.redis.password`              | Redis user's password                                                                                         | `""`                                            |
| `config.redis.database`              | Redis database number                                                                                         | `0`                                             |
| `config.redis.host`                  | Redis server host                                                                                             | `""`                                            |
| `config.redis.port`                  | Redis server port                                                                                             | `6379`                                          |
| `config.redis.storageClassName`      | StorageClassName                                                                                              | `""`                                            |
| `config.rabbitmq.secretReferenceKey` | Reference to an existing secret containing the following entry: CELERY_BROKER_URL                             | `""`                                            |
| `config.rabbitmq.username`           | RabbitMQ user                                                                                                 | `""`                                            |
| `config.rabbitmq.password`           | RabbitMQ user's password                                                                                      | `""`                                            |
| `config.rabbitmq.virtualHost`        | RabbitMQ virtual host name                                                                                    | `/`                                             |
| `config.rabbitmq.host`               | RabbitMQ server host                                                                                          | `""`                                            |
