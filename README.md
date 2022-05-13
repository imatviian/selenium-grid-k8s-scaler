# selenium-grid-k8s-scaler ![Version: 1.0.0](https://img.shields.io/badge/Version-1.0.0-informational?style=flat-square)
Selenium Grid (v4) horizontal scaler for Kubernetes

# Usage
```bash
$ python scaler.py --help
usage: scaler.py [-h] [-c CONFIG] [-p PID_FILE] [-l LOG_LEVEL]

optional arguments:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        Path to configuration file
  -p PID_FILE, --pid-file PID_FILE
                        Path to PID file
  -l LOG_LEVEL, --log-level LOG_LEVEL
                        Application logging level

```

## Configuration file
```yaml
scaler:
  # (Seconds) The interval at which scaling up is performed
  scale_up_interval: 30
  # (Seconds) The interval at which scaling down is performed
  scale_down_interval: 30
selenium:
  # Selenium Grid Router URL
  url: "http://localhost:4444"
kubernetes:
  # Kubernetes API URL
  api_url: "https://kubernetes.default.svc.cluster.local"
  # Path to file contains Kubernetes API token (ignored if KUBE_API_TOKEN env variable set)
  auth_token_path: "/var/run/secrets/kubernetes.io/serviceaccount/token"
  # Path to file contains Kubernetes API CA certificate
  ca_cert_path: "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
deployments: # Target deployments configuration section
  # Deployment name
  default-deployment:
    # API version
    api_version: "apps/v1"
    # Namespace
    namespace: "default"
    # Selenium Grid stereotype selector
    stereotype_selector: "browserName"
    # Selenium Grid stereotype selector value
    stereotype_selector_value: "chrome"
    # Minimum pods in deployment
    min_replicas: 1
    # Maximum pods in deployment
    max_replicas: 2
    # Step by which scaling up is performed
    scale_up_step: 1
    # Step by which scaling down is performed
    scale_down_step: 1
    # Load index value (in the range from 0.0 to 1.0) that triggers scaling up
    scale_up_threshold: 1.0
    # Load index value (in the range from 0.0 to 1.0) that triggers scaling down
    scale_down_threshold: 0.7
```

## Optional environment variables
- `KUBE_API_TOKEN` - Kubernetes API token (overrides token from `kubernetes.auth_token_path`)
- `GRID_REGISTRATION_SECRET` - Selenium Grid registration secret

## Load index

Dimensionless value reflecting the current load of selenium nodes for a particular deployment.
Сalculated by the following formula: `sum of all sessions in deployment`/`sum of all slots in deployment`

For example: you started `15 sessions` on the node pool of `3` nodes with `10 slots` on each one. In this case your load index will be `15 sessions`/`30 slots` = `0.5`

With `0%` sessions load index will be `0.0` and `1.0` with `100%` of sessions
