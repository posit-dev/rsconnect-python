# Programmatic Provisioning

Posit Connect supports the programmatic bootstrapping of an administrator API key
for scripted provisioning tasks. This process is supported by the `rsconnect bootstrap` command,
which uses a JSON Web Token to request an initial API key from a fresh Connect instance.

```bash
rsconnect bootstrap \
    --server https://connect.example.org:3939 \
    --jwt-keypath /path/to/secret.key
```

A full description on how to use `rsconnect bootstrap` in a provisioning workflow is provided in the Connect administrator guide's
[programmatic provisioning](https://docs.posit.co/connect/admin/programmatic-provisioning) documentation.
