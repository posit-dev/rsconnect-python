Integration requests streamline your deployment process by automatically associating the necessary OAuth integrations with your content, eliminating the need for manual configuration and ensuring that your deployed content has immediate access to the external resources that it depends on.

You can define integration requests for your content by defining `integration_requests` in your content's `manifest.json` file. The base `manifest.json` file can be produced using the [`write-manifest`](../commands/write-manifest.md) command, but you will need to edit the file by hand to add the `integration_requests`.

### Integration Request Specification

During deployment, these integration requests will be processed, and the specified integration specifications will be matched to integrations that are available on the Connect server. If a matching integration is found, it will be used for the deployment. If no matching integration is found, the deployment will fail with an error message indicating that the integration request could not be satisfied.

There are a variety of different fields that can be used within an integration request to reference the desired OAuth integration:

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

An integration request can contain any combination of the fields listed above, and the correct combination will vary by situation.

### Examples

#### Using the integration guid

If the content will only ever be deployed to a single server, the easiest way to make sure the correct OAuth integration gets automatically associated is by listing the OAuth integration `guid` in the integration request:

```json

    // ...
    "integration_requests": [
        {"guid": "123e4567-e89b-12d3-a456-426614174000"}
    ]
    // ...
}
```

A Connect administrator can locate the `guid` for an OAuth integration by navigating to **System** &gt; **Integrations** within Connect and then clicking on the desired integration. The `guid` is listed directly beneath the integration name in the resulting popup.

#### Using the integration name and template

```json
{
    // ...
    "integration_requests": [
        {"name": "my-integration", "type": "azure"}
    ]
    // ...
}
```

#### Using the name, template, and config

```json
{
  // ...
  "integration_requests": [
    {
      "name": "custom-integration",
      "type": "custom",
      "config": {
        "auth_mode": "Confidential"
      }
    }
  ]
  // ...
}
```


#### Multiple integration requests

In Posit Connect v2025.07.0 and later, multiple integrations can be associated with a single piece of content. When running this version of Connect, multiple integration requests can be listed in the manifest, and they all will be associated with the content upon deployment.

```json
{
    // ...
    "integration_requests": [
        {"name": "my-integration", "type": "azure"},
        {"name": "another-integration", "type": "aws"}
    ]
    // ...
}
```

### Deploying from manifest

Once the integration requests have been specified in the `manifest.json`. A publisher will need to use the `rsconnect deploy manifest` command in order for the auto-association to take place. See `rsconnect deploy manifest --help` for more details on deploying from manifest.
