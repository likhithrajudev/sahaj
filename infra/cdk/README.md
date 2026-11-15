# Sahaj on AWS (CDK)

Stacks, all in `ap-southeast-2`:

| Stack | What | Deployed by |
|---|---|---|
| `SahajData` | VPC, RDS Postgres 16 (`sahaj/db` secret, TLS forced), app secret `sahaj/app`, task security group. Termination protected. | hand |
| `SahajApp` | ECS Fargate (ARM64) service behind an ALB, blue/green. Serves the API and the web app at `/app`. | CI on `main` |
| `SahajDeploy` | GitHub OIDC provider and the `sahaj-github-deploy` role (can only assume the CDK bootstrap roles, only from `main`). | hand, once |

## Blue/green

The service uses ECS native blue/green. On each deploy ECS starts the new task set in the idle target group (`Blue`/`Green`) and moves the production listener rule to it. It then bakes for 5 minutes with the old tasks still running. It rolls back automatically if the new tasks fail health checks (circuit breaker) or if the `Api5xx` alarm fires.

Both versions run together during a deploy. The consent/audit ledger is therefore in Postgres (`LEDGER_BACKEND=postgres`), and appends are serialised with an advisory lock. Working memory and the live desk relay are in-process: a conversation that is open during the switch reconnects to the new task with its working memory reset.

## First deploy

```sh
npm ci
npx cdk bootstrap aws://<account>/ap-southeast-2
npx cdk deploy SahajData
scripts/push-secrets.sh            # copies keys from apps/api/.env.local into sahaj/app (values never printed)
npx cdk deploy SahajApp SahajDeploy
gh variable set AWS_DEPLOY_ROLE_ARN --body "<SahajDeploy.RoleArn output>"
```

After that, every push to `main` that passes the frontend, backend and infra jobs deploys `SahajApp`, then smoke-tests `/health`.

## HTTPS and Google sign-in

Without `certificateArn` the load balancer serves plain HTTP on its AWS hostname. Google sign-in needs HTTPS on an authorised origin, so a real domain is needed. Request an ACM certificate for it in `ap-southeast-2`, set `certificateArn` in `cdk.json`, point the domain at the ALB, and add `https://<domain>` to the OAuth client's authorised JavaScript origins and to `corsOrigins`.
