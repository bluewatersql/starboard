# Deployment Guide

Production deployment options for the Starboard AI Agent.

---

## Deployment Options

| Option | Complexity | Best For | Auto-scaling |
|--------|-----------|----------|--------------|
| **Databricks Apps** ⭐ | Low | Production, Databricks users | Yes |
| **Docker Compose** | Low | Simple self-hosted | Manual |
| **Kubernetes** | High | Enterprise scale | Yes |

---

## Databricks Apps Deployment (Recommended)

### Quick Start

```bash
# 1. Setup secrets (one-time)
./scripts/setup_databricks_secrets.sh

# 2. Deploy to development
databricks bundle deploy -t dev

# 3. Test deployment
./scripts/smoke_test.sh dev

# 4. Deploy to production
databricks bundle deploy -t prod
```

### Prerequisites

- Databricks workspace with Apps support
- Databricks CLI (`pip install databricks-cli`)
- Docker installed
- Personal Access Token

### Architecture

```
Databricks Workspace
├── App: starboard-agent
│   ├── Container: MCP server + CLI
│   ├── Auto-scaling: 1-10 instances
│   └── Authentication: Workspace SSO
└── Resources:
    ├── SQL Warehouse
    ├── Lakebase Instance
    └── Secret Scope
```

### Configuration

Create `databricks.yml` in project root:

```yaml
bundle:
  name: starboard-agent
  
targets:
  prod:
    mode: production
    workspace:
      host: https://your-workspace.cloud.databricks.com
      
    resources:
      apps:
        starboard:
          name: starboard-agent
          
          compute:
            - name: main
              autoscaling:
                enabled: true
                min_instances: 1
                max_instances: 10
              
              resources:
                requests:
                  cpu: "2"
                  memory: "4Gi"
```

### Key Features

✅ **Integrated Auth**: Workspace SSO built-in  
✅ **Auto-scaling**: 1-10 instances automatically  
✅ **Cost Control**: Auto-pause when idle  
✅ **Monitoring**: Native Databricks observability

### Useful Commands

```bash
# Check status
databricks apps get starboard-agent

# View logs
databricks apps logs starboard-agent --follow

# Restart
databricks apps restart starboard-agent

# Destroy
databricks bundle destroy -t dev --auto-approve
```

---

## Docker Compose Deployment

### Quick Start

```bash
# Create .env file
cat > .env << EOF
OPENAI_API_KEY=<your-api-key>
DATABRICKS_HOST=https://...
DATABRICKS_TOKEN=dapi...
EOF

# Start services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

### Configuration

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  starboard:
    build: packages/starboard
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - DATABRICKS_HOST=${DATABRICKS_HOST}
      - DATABRICKS_TOKEN=${DATABRICKS_TOKEN}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health/ready"]
      interval: 30s
```

### Access

- MCP server (stdio): `starboard-mcp --transport stdio`
- CLI: `starboard --goal "..."`

---

## Kubernetes Deployment

### Quick Start

```bash
# Create namespace
kubectl create namespace starboard-agent

# Create secrets
kubectl create secret generic starboard-secrets \
  --namespace starboard-agent \
  --from-literal=openai-api-key="<your-api-key>" \
  --from-literal=databricks-token="dapi..."

# Deploy with Helm
helm install starboard-agent ./helm \
  --namespace starboard-agent \
  --values helm/values.yaml
```

### Configuration

Create `helm/values.yaml`:

```yaml
starboard:
  replicas: 3
  image:
    repository: your-registry/starboard
    tag: latest
  resources:
    requests:
      cpu: "1"
      memory: 2Gi
    limits:
      cpu: "2"
      memory: 4Gi
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
    targetCPUUtilization: 70

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: starboard.example.com
```

### Health Checks

```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
```

**Note**: Health endpoints are only available when running the MCP server in HTTP mode. For stdio transport (Claude Code / Cursor), health checks are not applicable.

---

## Production Checklist

### Security
- [ ] Secrets in secret manager (not code)
- [ ] TLS/HTTPS enabled
- [ ] CORS configured
- [ ] Rate limiting enabled
- [ ] PII redaction in logs

### Configuration
- [ ] Environment-specific configs (dev/staging/prod)
- [ ] Cost limits configured
- [ ] Timeout values set
- [ ] Circuit breakers enabled

### Monitoring
- [ ] Health check endpoints configured
- [ ] Metrics exported
- [ ] Distributed tracing enabled
- [ ] Alerting rules defined

### Performance
- [ ] Horizontal scaling configured
- [ ] Connection pooling enabled
- [ ] Caching configured
- [ ] Load testing completed

---

## Health Endpoints

```bash
# Liveness - process is alive
curl http://localhost:8000/health/live

# Readiness - ready to serve traffic
curl http://localhost:8000/health/ready
```

---

## Troubleshooting

### App Won't Start

```bash
# Check logs
databricks apps logs starboard-agent --tail 100

# Verify secrets
databricks secrets list --scope starboard-secrets

# Check resources
databricks apps describe starboard-agent
```

### High Memory Usage

```bash
# Check metrics
databricks apps metrics starboard-agent --metric memory_usage

# Increase limits
databricks apps update starboard-agent \
  --resources '{"limits":{"memory":"8Gi"}}'
```

### Authentication Errors

```bash
# Test credentials
databricks workspace list /

# Rotate token
databricks tokens create --comment "starboard-$(date +%Y%m%d)"

# Restart app
databricks apps restart starboard-agent
```

---

## Rollback Procedures

### Databricks

```bash
# List deployments
databricks bundle status -t prod

# Destroy current
databricks bundle destroy -t prod --auto-approve

# Redeploy previous version
git checkout previous-tag
databricks bundle deploy -t prod
```

### Kubernetes

```bash
# Rollback deployment
kubectl rollout undo deployment/starboard -n starboard-agent

# Check status
kubectl rollout status deployment/starboard -n starboard-agent
```

---

**Last Updated**: November 19, 2025  
**Version**: 2.0.0
