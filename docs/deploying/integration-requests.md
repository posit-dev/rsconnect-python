Define integration requests for your deployed content by defining `integration_requests` in your content's `manifest.json` file, which can be produced manually or using the [`write-manifest`](../commands/write-manifest.md) command.

### Integration Request Specification

During deployment, these integration requests will be processed, and the specified integration specifications will be matched to integrations that are available on the Connect server. If a matching integration is found, it will be used for the deployment. If no matching integration is found, the deployment will fail with an error message indicating that the integration request could not be satisfied.

| Field | Description | Matching Type | Example |
|-------|-------------|---------------|---------|
| `name` | String identifier for the integration | regex match | `"my-integration"` |
| `description` | Description of the integration | regex match | `"My Azure Integration"` |
| `type` | Integration type | exact match | `"azure"` |
| `guid` | Unique identifier for the integration | exact match | `"123e4567-e89b-12d3-a456-426614174000"` |
| `auth_type` | Authentication type | exact match | `"Viewer"` |
| `config` | Configuration settings for the integration | key-value match | `"{"auth_mode": "Confidential"}"` |

Possible values for `type` include:
- `azure`
- `azure-openai`
- `sharepoint`
- `msgraph`
- `bigquery`
- `drive`
- `sheets`
- `vertex-ai`
- `databricks`
- `github`
- `salesforce`
- `snowflake`
- `connect`
- `aws`
- `custom`

Possible values for `auth_type` include:
- `Viewer`
- `Service Account`
- `Visitor API Key`


### Example

```json
{
    // ...
    "integration_requests": [
        {"name": "my-integration", "type": "azure"},
        {"name": "another-integration", "type": "aws"},
        {"name": "custom-integration", "type": "custom", "config": {"auth_mode": "Confidential"}},
        {"guid": "123e4567-e89b-12d3-a456-426614174000"}
    ]
    // ...
}
```
