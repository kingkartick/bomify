# Deploying QuadStack to AWS (single EC2, free tier / credits)

One EC2 instance runs the whole stack with Docker Compose: nginx (serves the React build and proxies `/api`), FastAPI, Postgres, Redis. Only port 80 is public.

## 1. Launch the instance (AWS Console)

1. EC2 -> **Launch instance**
2. AMI: **Amazon Linux 2023**
3. Type: **t3.micro** (or t2.micro if t3 isn't marked "Free tier eligible" in your region). If you have credits and want it smoother, **t3.small** is much more comfortable (2 GB RAM).
4. Key pair: create one and download the `.pem`.
5. Network / Security group: allow **SSH (22) from My IP** and **HTTP (80) from anywhere**. Do NOT open 5432 or 6379.
6. Storage: 20 GB gp3 (free tier allows up to 30 GB).
7. Launch, then note the **Public IPv4 address**.

## 2. Install Docker on it

```bash
ssh -i your-key.pem ec2-user@<PUBLIC_IP>
```

Copy `deploy/ec2-setup.sh` to the server (or paste it), run `bash ec2-setup.sh`, then log out and back in.

## 3. Get the code on the server

From your PC (in the `bomify` folder, skipping node_modules):

```powershell
scp -i your-key.pem -r apps docker-compose.prod.yml .env.prod.example ec2-user@<PUBLIC_IP>:~/bomify/
```

(Or push to a private GitHub repo and `git clone` on the server.)

## 4. Configure and start

```bash
cd ~/bomify
cp .env.prod.example .env.prod
nano .env.prod          # replace every CHANGE_ME (use: openssl rand -hex 32)
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

The first build takes 5-10 minutes on a micro instance. Then open `http://<PUBLIC_IP>` and log in with the `ADMIN_USERNAME` / `ADMIN_PASSWORD` you set.

## Useful commands

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f api
# redeploy after changes
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

## Notes

- **Cost:** the instance and EBS volume are covered by free tier / credits. A public IPv4 address is billed (~$3.6/month) even on free tier for accounts created after July 2025; credits cover it. Stop/terminate the instance when you're done.
- **IP changes on stop/start.** Attach an Elastic IP if you want a stable address (free while attached to a running instance).
- **HTTPS:** this serves plain HTTP. For HTTPS, point a domain at the instance and put Caddy or certbot in front, or use CloudFront.
- **Backups:** data lives in the `pgdata` Docker volume on the instance. Take EBS snapshots if the data matters.

## Adding another client

The app is single-tenant, so each client gets its own isolated stack (database, secrets, login) on a separate port:

```bash
cd ~/bomify
bash deploy/add-client.sh acme 8080 "Acme Corp"
```

Then open TCP 8080 in the EC2 security group and visit `http://<server-ip>:8080`. The script prints the generated admin login once. Each client's secrets live in `.env.<slug>` (git-ignored). Budget roughly 600-800 MB RAM per client; on a t3.small expect 2 clients at most.

## Self-serve signup with payment (Razorpay)

`apps/billing` is a small control-plane service. A prospect opens the signup page, pays through Razorpay, and the service automatically:

1. verifies the payment (Checkout signature, plus the webhook as a fallback if the browser closes),
2. creates their isolated stack with `deploy/add-client.sh` (next free port in `CLIENT_PORT_START`–`CLIENT_PORT_END`, their email as the admin user, no demo data),
3. waits for the stack's `/api/health`, then
4. shows the login URL, username and a generated password on the signup page and downloads them as a text file (with a button to download them again).

### One-time setup

1. Make sure the first deploy (section 4) has built the `bomify-api` and `bomify-web` images.
2. Open TCP **9000** (signup page) and the client port range (**8081-8180** by default) in the EC2 security group, once.
3. Configure and start it:
   ```bash
   cd ~/bomify
   cp .env.billing.example .env.billing
   nano .env.billing     # Razorpay keys, PUBLIC_HOST, BILLING_ADMIN_TOKEN
   docker compose -p billing -f docker-compose.billing.yml --env-file .env.billing up -d --build
   ```
4. In the Razorpay Dashboard -> Webhooks, add `http://<PUBLIC_HOST>:9000/api/webhooks/razorpay` with events `payment.captured` and `order.paid`, and put the same secret in `RAZORPAY_WEBHOOK_SECRET`.
5. Visit `http://<PUBLIC_HOST>:9000` and do a test purchase with `rzp_test_` keys and a Razorpay test card before switching to live keys.

The signup page should be served over HTTPS before you take live payments (put Caddy/certbot in front of port 9000 and use that URL for the webhook).

### Operating it

```bash
TOKEN=<BILLING_ADMIN_TOKEN>
# All signups with status (pending / paid / provisioning / active / failed) and any error
curl -H "Authorization: Bearer $TOKEN" http://localhost:9000/api/admin/signups
# Retry a failed one after fixing the cause (e.g. a stack that never became healthy); reuses the same stack
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:9000/api/admin/signups/<id>/retry
docker compose -p billing -f docker-compose.billing.yml logs -f billing
```

Check the admin list (or the logs) for `failed` signups. The payment is already captured at that point, so act on it: once retried, the customer's open signup page picks up the login automatically.

Notes:
- The billing container mounts the Docker socket and the repo, which gives it control of the host's Docker. Keep `.env.billing` private and port 9000 limited to the signup page.
- Client env files (`.env.<slug>`) it creates are owned by root; use `sudo` to read them.
- Each client still costs ~600-800 MB RAM. Set `MAX_CLIENTS` to what the instance can run; once reached, the signup page refuses new customers *before* taking payment.
- After Checkout, the server confirms the payment with Razorpay and captures it if it's only authorized, so it works whether or not auto-capture is on.
- Tests: `cd apps/billing && pip install -r requirements.txt pytest && python -m pytest tests -v`
