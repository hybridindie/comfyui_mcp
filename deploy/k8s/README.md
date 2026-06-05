# Self-hosted GitHub Actions runner (K3s)

Runs the `docker` and `pypi` release jobs, which target
`runs-on: [self-hosted, linux, hybridindie]`. PR CI stays on GitHub-hosted
`ubuntu-latest` (see `.github/workflows/ci.yml`).

## What's deployed

`github-runner.yaml` — a Deployment in the `ci` namespace with two containers:

- **dind** — `docker:27-dind` (privileged) providing the Docker daemon the
  buildx/QEMU multi-arch build needs.
- **runner** — `myoung34/github-runner` registered to this repo with the
  `hybridindie` label, talking to the daemon via `DOCKER_HOST=tcp://localhost:2375`.

The runner is **persistent** (no `EPHEMERAL` env — myoung34 treats any non-empty
value, even `"false"`, as enabled, so it must be omitted).

## Registration token vs. PAT (durability)

The Deployment currently authenticates with a **registration token** stored in
the `github-actions-runner` secret under `RUNNER_TOKEN`. A registration token is
only used **once**, at first registration; afterward the runner authenticates
with its own stored credentials, so token expiry does not matter **while the pod
keeps running**.

⚠️ **A registration token expires ~1 hour after it is minted.** If the pod is
recreated after that (node reboot, eviction, image update), the runner cannot
re-register and release CI silently breaks again.

**Durable fix:** put a GitHub PAT (classic, `repo` scope — or a fine-grained
token with Administration: read/write) into the secret and switch the env var:

```bash
kubectl create secret generic github-actions-runner -n ci \
  --from-literal=ACCESS_TOKEN=<YOUR_PAT> \
  --dry-run=client -o yaml | kubectl apply -f -
# then in github-runner.yaml, replace the RUNNER_TOKEN env with:
#   - name: ACCESS_TOKEN
#     valueFrom: { secretKeyRef: { name: github-actions-runner, key: ACCESS_TOKEN } }
kubectl rollout restart deployment/github-runner -n ci
```

With `ACCESS_TOKEN` (a PAT) the image mints fresh registration tokens on every
start, so the runner survives restarts indefinitely.

## Re-mint a registration token (if not using a PAT)

```bash
TOKEN=$(gh api -X POST repos/hybridindie/comfyui_mcp/actions/runners/registration-token --jq '.token')
kubectl create secret generic github-actions-runner -n ci \
  --from-literal=ACCESS_TOKEN=unused --from-literal=RUNNER_TOKEN="$TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/github-runner -n ci
```

## Health checks

```bash
kubectl get pods -n ci -l app=github-runner
kubectl logs -n ci -l app=github-runner -c runner --tail=20
gh api repos/hybridindie/comfyui_mcp/actions/runners --jq '.runners[] | {name,status,busy}'
```
