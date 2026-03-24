# Cloud Authentication Guide

**Package**: `starboard-log-parser`  
**Version**: 0.2.0+

---

## Overview

The log parser supports multiple cloud storage providers with flexible authentication options. This guide covers credential configuration for AWS, Azure, and GCP.

---

## Authentication Patterns

### Pattern 1: Environment Variables (Recommended)

**Use when**: Running on developer machines, CI/CD, or servers with configured environment

**Pros**:
- ✅ No hardcoded credentials
- ✅ Works with standard cloud CLI tools
- ✅ Easy to rotate credentials

**Cons**:
- ⚠️ Requires environment setup
- ⚠️ Credentials must be manually rotated

---

## AWS Authentication

### Option 1: Environment Variables (Recommended)

```python
from starboard_log_parser.auth.providers import EnvironmentCredentialProvider
from starboard_log_parser.adapters.cloud.s3 import S3Adapter

# Reads AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
provider = EnvironmentCredentialProvider(cloud="aws")
s3 = S3Adapter(credential_provider=provider)
```

**Environment variables**:
```bash
export AWS_ACCESS_KEY_ID="AKIAIOSFODNN7EXAMPLE"
export AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
export AWS_REGION="us-west-2"  # Optional, default: us-east-1
export AWS_SESSION_TOKEN="..."  # Optional, for temporary credentials
```

### Option 2: Static Credentials (Development Only)

```python
from starboard_log_parser.auth.providers import StaticCredentialProvider

provider = StaticCredentialProvider(
    access_key="AKIAIOSFODNN7EXAMPLE",
    secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    region="us-west-2"
)
```

⚠️ **Warning**: Never commit credentials to version control.

### AWS IAM Best Practices

1. **Use IAM roles** when running on EC2/ECS (future support)
2. **Least privilege**: Grant only required S3 permissions
3. **Rotate regularly**: Use temporary credentials when possible
4. **Audit access**: Enable CloudTrail for S3 access logs

**Minimal IAM policy**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket-name/*",
        "arn:aws:s3:::your-bucket-name"
      ]
    }
  ]
}
```

---

## Azure Authentication

### Option 1: Environment Variables

```python
from starboard_log_parser.auth.providers import EnvironmentCredentialProvider
from starboard_log_parser.adapters.cloud.adls import ADLSAdapter  # Future

# Reads AZURE_STORAGE_ACCOUNT, AZURE_STORAGE_KEY
provider = EnvironmentCredentialProvider(cloud="azure")
adls = ADLSAdapter(credential_provider=provider)
```

**Environment variables**:
```bash
export AZURE_STORAGE_ACCOUNT="mystorageaccount"
export AZURE_STORAGE_KEY="base64-encoded-key"
```

### Option 2: Static Credentials

```python
from starboard_log_parser.auth.providers import StaticCredentialProvider

provider = StaticCredentialProvider(
    storage_account="mystorageaccount",
    storage_key="base64-encoded-key",
    cloud="azure"
)
```

**Status**: Azure ADLS support coming in v0.2.0 (Week 3)

---

## GCP Authentication

### Option 1: Environment Variables

```python
from starboard_log_parser.auth.providers import EnvironmentCredentialProvider
from starboard_log_parser.adapters.cloud.gcs import GCSAdapter  # Future

# Reads GOOGLE_APPLICATION_CREDENTIALS
provider = EnvironmentCredentialProvider(cloud="gcp")
gcs = GCSAdapter(credential_provider=provider)
```

**Environment variables**:
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

### Option 2: Service Account File

```python
from starboard_log_parser.auth.providers import StaticCredentialProvider

provider = StaticCredentialProvider(
    service_account_file="/path/to/service-account-key.json",
    cloud="gcp"
)
```

**Status**: GCP Cloud Storage support coming in v0.2.0 (Week 4)

---

## Credential Expiration

The credential providers track expiration and can signal when refresh is needed.

```python
from starboard_log_parser.auth.providers import StaticCredentialProvider
from datetime import datetime, timedelta, timezone

# Create credential with expiration
provider = StaticCredentialProvider(
    access_key="...",
    secret_key="...",
    region="us-west-2",
    expiration=datetime.now(timezone.utc) + timedelta(hours=1)
)

# Check if expired or needs refresh
creds = provider.get_credentials()

if creds.is_expired():
    print("Credentials expired!")

if creds.needs_refresh():
    print("Credentials should be refreshed soon")
```

**Default refresh buffer**: 5 minutes before expiration

---

## Security Best Practices

### ✅ DO

1. **Use environment variables** for credentials in production
2. **Rotate credentials regularly** (90 days max)
3. **Use temporary credentials** when available
4. **Enable MFA** for AWS console access
5. **Monitor access logs** for unusual activity
6. **Use least privilege** IAM policies
7. **Store credentials securely** (AWS Secrets Manager, Azure Key Vault)

### ❌ DON'T

1. **Never commit credentials** to version control
2. **Don't log credentials** in application logs
3. **Don't use root account** credentials
4. **Don't share credentials** between environments
5. **Don't hardcode credentials** in application code
6. **Don't grant excessive permissions** (avoid `s3:*`)

---

## Troubleshooting

### Error: "Could not find AWS credentials"

**Solution**: Set environment variables or configure AWS CLI:
```bash
aws configure
```

### Error: "Credentials have expired"

**Solution**: Refresh credentials or generate new temporary credentials.

### Error: "Access Denied"

**Causes**:
- Invalid credentials
- Insufficient IAM permissions
- Wrong region
- Bucket policy restrictions

**Solution**: Verify credentials and IAM policy.

---

## Future: Databricks Credential Vending

**Coming in v0.2.1** (Weeks 5-6):

```python
from starboard_log_parser.auth.providers import DatabricksCredentialVendingProvider

# Automatically generates temporary credentials via Unity Catalog
provider = DatabricksCredentialVendingProvider(
    external_location="s3://my-bucket/data/",
    databricks_host="https://my-workspace.databricks.com",
    databricks_token="dapi..."
)

# Credentials auto-refresh, scoped to Unity Catalog permissions
s3 = S3Adapter(credential_provider=provider)
```

**Benefits**:
- ✅ Temporary credentials (1-12 hour TTL)
- ✅ Unity Catalog permissions enforced
- ✅ Automatic refresh
- ✅ Full audit trail

---

## Examples

### Example 1: Development with Static Credentials

```python
from starboard_log_parser.auth.providers import StaticCredentialProvider
from starboard_log_parser.adapters.cloud.s3 import S3Adapter

# For local development only
provider = StaticCredentialProvider(
    access_key="AKIAIOSFODNN7EXAMPLE",
    secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    region="us-west-2"
)

s3 = S3Adapter(credential_provider=provider)
```

### Example 2: Production with Environment Variables

```python
import os
from starboard_log_parser.auth.providers import EnvironmentCredentialProvider
from starboard_log_parser.adapters.cloud.s3 import S3Adapter

# Validate environment variables are set
required_vars = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"]
missing = [var for var in required_vars if not os.getenv(var)]

if missing:
    raise ValueError(f"Missing required environment variables: {missing}")

# Create provider
provider = EnvironmentCredentialProvider(cloud="aws")
s3 = S3Adapter(credential_provider=provider)

# Use S3 adapter
files = s3.list_files("s3://production-logs/", pattern="*.json")
```

### Example 3: Multi-Cloud with Same Pattern

```python
# AWS
aws_provider = EnvironmentCredentialProvider(cloud="aws")
s3 = S3Adapter(credential_provider=aws_provider)

# Azure (future)
azure_provider = EnvironmentCredentialProvider(cloud="azure")
adls = ADLSAdapter(credential_provider=azure_provider)

# GCP (future)
gcp_provider = EnvironmentCredentialProvider(cloud="gcp")
gcs = GCSAdapter(credential_provider=gcp_provider)

# Same interface across all clouds
for adapter in [s3, adls, gcs]:
    if adapter.path_exists("cloud://bucket/file"):
        files = adapter.list_files("cloud://bucket/")
```

---

## See Also

- [S3 Connector Guide](./S3_CONNECTOR_GUIDE.md) - Using AWS S3
- [Architecture](./ARCHITECTURE.md) - System design
- [Configuration](./CONFIGURATION.md) - General configuration

---

**Last Updated**: 2025-11-29  
**Version**: 1.0

