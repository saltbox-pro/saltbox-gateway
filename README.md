<div align = right>

&ensp;[<kbd> <br> EN <br> </kbd>](./README.md)&ensp;
&ensp;[<kbd> <br> RU <br> </kbd>](./README_RU.md)&ensp;

</div>

---

# Salt.Box Gateway

## Table of Contents

- **[About](#about)**
- **[Key capabilities](#key-capabilities)**
- **[Quick Start](#quick-start)**
  - [Running](#1-running)
  - [Environment variables](#2-environment-variables)
  - [Main endpoints](#3-main-endpoints)
- **[Architecture](#architecture)**
- **[Managing services](#managing-services)**
  - [Registering a service in Discovery](#registering-a-service-in-discovery)
- **[Load balancing](#load-balancing)**
- **[Caching](#caching)**
- **[Static file proxying](#static-file-proxying)**
- **[Audit](#audit)**
- **[Authorization and access control](#authorization-and-access-control)**
  - [Advantages of this approach](#advantages-of-this-approach)
  - [OPA, Open Policy Agent](#1-opa-open-policy-agent)
  - [Permissions](#2-permissions)
  - [Partial Query](#3-partial-query)
- **[Updating OPA policies](#updating-opa-policies)**


## About

**Salt.Box Gateway** is a component of the Salt.Box platform that implements the API Gateway for its microservice architecture. It handles request routing, load balancing, service health checks, caching, and centralized access control based on OPA policies and the permission system.

Gateway runs on top of FastAPI, integrates with Redis for state and cache storage, and with OPA, Open Policy Agent, for permission checks.

---

## Key capabilities

- **Dynamic service discovery**
- **Load balancing**
- **Instance health checks**
- **Response caching**
- **Static file proxying**
- **Access control through OPA and permissions**
- **Audit event publishing for proxied requests**
- **API for managing services, instances and user settings**
- **Swagger/OpenAPI documentation for services**

---

## Quick Start

### 1. Running

Gateway runs as part of **Salt.Box Compose** and has no Docker Compose file of its own. From the `saltbox-compose` directory:

```bash
sudo ./bin/sb-compose.sh up saltbox-gateway
```

### 2. Environment variables

- `GATEWAY_HTTP_PORT` – port to serve on, `8000` by default
- `REDIS_URL` – Redis connection string
- `OPA_URL` – OPA server address
- `PROXY_REQUEST_TIMEOUT` – timeout for proxied requests

### 3. Main endpoints

- `/api/discovery/health` – gateway liveness check
- `/api/discovery/config` – current configuration of registered services
- `/api/discovery/register` – register a service or its instance
- `/api/discovery/add-standalone-front` – register a standalone frontend module
- `/api/discovery/services` – list of registered services
- `/api/discovery/services/{service_name}` – a single registered service
- `/api/discovery/services/{service_name}/toggle` – enable or disable a service
- `/api/discovery/services/{service_name}/change-strategy` – change the balancing strategy
- `/api/discovery/unregister/{service_name}` – remove a service
- `/api/discovery/unregister/{service_name}/{instance_id}` – remove an instance
- `/api/{service_name}/{path}` – proxy a request to a service
- `/static/{service_name}/{path}` – proxy a service's static files
- `/api/permissions/{service_name}` – check the current user's permissions for a service
- `/api/user-settings` – read and save the current user's personal settings

---

## Architecture

- **ServiceDAO** – data access layer for services in Redis
- **ProxyService** – the main class for request proxying, balancing and access checks
- **BalancingStrategy** – factory of balancing strategies
- **AsyncOpaClient** – client for checking OPA policies
- **CustomRedisCache** – response caching
- **AuditEventPublisher** – publishes audit events for proxied requests through the SDK

---

## Managing services

- Register, disable and remove services and instances through the API
- State is kept up to date automatically through health checks
- Multiple instances of the same service are supported

### Registering a service in Discovery

A new service, core for example, registers itself through the Service Discovery mechanism.
On startup a service sends the gateway, through the API or directly through Redis, information about itself: its name, endpoints, type, balancing strategy, vendor and other parameters.
A registration example can be found in the core and saltbox-sdk source code, in the registration function of the discovery_client module.

- If a service with that name is not registered yet, it is added with a single instance.
- If the service already exists, a new instance is added, or the current instance is updated if the id matches.
- The SDK implements a client that sends a POST request to `/api/discovery/register` describing the service and its instance.
- On registration the service passes the gateway its full list of endpoints with their settings: an OPA access policy, caching parameters `cache_ttl`, partial-query, action and others.
- After registration the service appears in the gateway's list of available services and becomes available for proxying.
- Based on the registered endpoints, the gateway checks access through OPA and caches responses according to each endpoint's settings.
- The list of official modules allowed to register without extra checks includes core, processing, metric, scheduler, inventory, migration, audit and client-toolkit.

---

## Load balancing

Supported strategies:
- `rr` – Round Robin
- `wrr` – Weighted Round Robin
- `rand` – Random

The strategy is set per service and can be changed through the API.

---

## Caching

- Only successful responses with status 200 OK are cached, if the endpoint supports TTL.
- The cache is stored in Redis, under the `gate_cache` namespace.
- Caching is disabled for Swagger/OpenAPI and private endpoints.

---

## Static file proxying

For services with `static_host` configured, requests for static files are proxied directly.

---

## Audit

Every proxied API request, whether served directly by a service or from cache, publishes a data access event through the SDK's `AuditEventPublisher`. This keeps a single audit trail of data access regardless of which service handled the request.

---

## Authorization and access control

Salt.Box Gateway implements a centralized access control system based on OPA, Open Policy Agent, and permissions, supporting the ABAC, Attribute-Based Access Control, model.

### Advantages of this approach

- **ABAC:** Access is determined by attributes of the user, resource, action and service.
- **Flexibility:** Policies are grouped by service, core and scheduler for example, by resource, tasks, jobs and collections for example, and by action, read, create and list for example.
- **Scalability:** New services, resources, roles and conditions are easy to add.
- **Partial Query:** OPA can return a filter to narrow down data at the request level.

### 1. OPA, Open Policy Agent

- An OPA config is set for every service endpoint: policy, action, partial-query, unknowns.
- Gateway builds the OPA input from three parts: subject, the user, action and resource, which includes service, path, query and body.
- OPA returns the `allow` decision and, for a partial query, a filter to narrow down data.

#### Example OPA input:

```json
{
  "subject": {
    "sub": "user_id",
    "email": "user@example.com",
    "roles": ["tasks_admin"]
  },
  "action": {
    "method": "GET",
    "name": "read"
  },
  "resource": {
    "service_name": "core",
    "path": ["tasks", "123"],
    "query_params": {},
    "body": null
  }
}
```

#### Example policy in Rego:

```rego
package core.tasks.read

import data.utils

default allow := false

allow if utils.base.is_admin
allow if utils.base.is_tasks_admin
allow if utils.conditions.check_user_permissions(
    data.permissions,
    input.resource.service_name,
    "tasks",
    "read",
    input.subject,
    object_from_api
)
```

#### User object format

```json
"subject": {
    "sub": "26b9a3e6-2e80-40c7-8f84-a993a1282169",
    "email": "master@example.com",
    "email_verified": false,
    "name": "Petr Petrov",
    "roles": [
        "test_common"
    ]
}
```

### 2. Permissions

- Permissions are currently stored in a `data.json` file loaded into OPA.
- Future releases plan to store permissions in MongoDB, along with a full frontend interface for managing them: creating, editing, deleting and viewing.
- This will allow access rights to change dynamically without restarting containers.

#### Example permission

```json
{
    "is_active": true,
    "service": "core",
    "resource": "collections",
    "action": "read",
    "object_conditions": {
        "slug": { "$in": ["linux", "alt"] }
    },
    "subject_type": "user",
    "subject_conditions": {
        "roles": { "$in": ["test_common"] }
    },
    "created": "2024-07-28T12:00:00Z",
    "modified": "2024-07-28T12:00:00Z"
}
```

**Permission structure:**
- `is_active`: whether the permission is active.
- `service`: the service name, core for example.
- `resource`: the resource type, collections for example.
- `action`: the action, read or create for example.
- `object_conditions`: conditions on the object, for example that slug must be in a list.
- `subject_type`: the subject type, usually `user`.
- `subject_conditions`: conditions on the user, for example their role.
- `created`, `modified`: creation and modification dates.

**Condition format:**
- Conditions are objects with operators such as `$in`, `$eq`, `$lt` and others.
- Conditions on different fields can be combined, including nested `$and`/`$or`.
- The example `"roles": { "$in": ["test_common"] }` means the user must have one of the listed roles.
- The example `"slug": { "$in": ["linux", "alt"] }` means the object's slug must be in the list.

### 3. Partial Query

For listing and filtering endpoints, a task or collection list for example, OPA does not just return `allow`. It compiles a set of conditions under which the `allow` rule would hold for different values of data that is still unknown at the time.

- An endpoint's config sets `is_partial: true`, a list of `unknowns`, that is, the parts of the data not yet known at evaluation time, `permissions` for example, and optionally `partial_query`, `allow == true` by default.
- Gateway sends a `data.<policy>.<partial_query>` query to OPA's `/v1/compile` endpoint, together with the input data and the list of `unknowns`.
- OPA returns a set of partial `queries`, each describing the condition under which access is granted for one combination of the unknown data.
- Gateway compiles this set into a filter in one of two formats, set through `query_filter_format`: `mongo`, a MongoDB-style query object, or `sql`, part of a SQL WHERE clause.
- If OPA returns no queries at all, access is denied. If one of the queries is empty, access is granted without restriction. Otherwise access is granted, but only to data matching the computed filter.
- When a filter is computed, Gateway adds it as a JSON-encoded `opa_query` query parameter on the proxied request. The receiving service is responsible for applying that filter to its own data, merging it into its MongoDB query for example.
- Each such check publishes a `permission_check` audit event recording the decision and whether a filter was applied.

---

## Updating OPA policies

- Currently OPA policies are updated manually: the Rego files must be changed and the OPA container restarted for the changes to take effect.
- In future releases policies will be distributed through OPA Bundles stored in Git. Pushing to main will trigger CI, build a fresh bundle and automatically distribute it to every OPA instance.
