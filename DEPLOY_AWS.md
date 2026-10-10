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
