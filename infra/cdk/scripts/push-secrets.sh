#!/usr/bin/env bash
# Copies API keys from apps/api/.env.local into the sahaj/app secret (keeps the generated JWT_SECRET). Prints no values.
set -euo pipefail
ENV_FILE="$(cd "$(dirname "$0")/../../.." && pwd)/apps/api/.env.local"
REGION="${REGION:-ap-southeast-2}"
current="$(aws secretsmanager get-secret-value --secret-id sahaj/app --region "$REGION" --query SecretString --output text)"
merged="$(ENV_FILE="$ENV_FILE" CURRENT="$current" python3 - <<'PY'
import json, os
keys = ["SARVAM_API_KEY", "OPENAI_API_KEY", "LANGSMITH_API_KEY", "ADMIN_API_KEY", "GOOGLE_CLIENT_IDS"]
secret = json.loads(os.environ["CURRENT"])
for line in open(os.environ["ENV_FILE"]):
    k, _, v = line.strip().partition("=")
    if k in keys and v:
        secret[k] = v
print(json.dumps(secret))
PY
)"
aws secretsmanager put-secret-value --secret-id sahaj/app --region "$REGION" --secret-string "$merged" --query VersionId --output text >/dev/null
echo "sahaj/app updated: $(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(", ".join(k for k,v in d.items() if v))' "$merged") set"
