# Environment Setup

Create a `.env.local` file in the frontend directory with:

```bash
# Backend API Configuration
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_API_BASE_PATH=/api
```

For Databricks App deployment, use:
```bash
NEXT_PUBLIC_API_URL=https://your-databricks-workspace.cloud.databricks.com
NEXT_PUBLIC_API_BASE_PATH=/api
```
