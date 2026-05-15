# Railway Backend Deployment Guide

## Prerequisites

- GitHub account (repo already connected)
- Railway account (https://railway.app)

## Step 1: Create Railway Account & Connect GitHub

1. Visit https://railway.app and sign up
2. Click "Create a new project"
3. Select "Deploy from GitHub repo"
4. Authorize Railway to access your GitHub account
5. Select `AI-Guitar-Music-Sheet-Generator` repository
6. Select the `stage` branch for staging deployments

## Step 2: Create Database & Redis Services

### PostgreSQL Database

1. In Railway dashboard, click "+ Add Service"
2. Select "PostgreSQL"
3. Railway will automatically provision it
4. Note the `DATABASE_URL` from the service variables

### Redis Cache

1. Click "+ Add Service"
2. Select "Redis"
3. Railway will automatically provision it
4. Note the `REDIS_URL` from the service variables

## Step 3: Configure Backend Service

### Deploy Backend

1. Click "+ Add Service"
2. Select "GitHub Repo"
3. Select your repository
4. Configure the service:
   - **Name:** backend
   - **Branch:** stage
   - **Root Directory:** backend/

### Set Environment Variables

In Railway dashboard, go to the backend service and add these variables:

```
DATABASE_URL=postgresql://user:password@host:port/dbname
REDIS_URL=redis://:password@host:port
CELERY_BROKER_URL=redis://:password@host:port
CELERY_RESULT_BACKEND=redis://:password@host:port
SECRET_KEY=your-very-secure-random-key-here
ALLOWED_ORIGINS=https://your-vercel-frontend-url.vercel.app
ENVIRONMENT=staging
```

**To generate a secure SECRET_KEY:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Configure Build & Start

1. **Root Directory:** backend
2. **Procfile:** Will be auto-detected
3. **Start Command:** `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`

## Step 4: Get Your Backend URL

After deployment completes:

1. The backend will have a public URL (e.g., `your-backend-xxxxx.railway.app`)
2. Copy this URL

## Step 5: Update Frontend

1. In your frontend `.env` (or `.env.staging`), update:

   ```
   VITE_API_URL=https://your-backend-xxxxx.railway.app
   ```

2. Update frontend `audioService.ts` to use the environment variable:

   ```typescript
   const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
   ```

3. Commit and push to `stage` branch - Vercel will auto-redeploy

## Step 6: Test the Integration

1. Visit your Vercel frontend URL
2. Test the login/register endpoints
3. Test audio upload functionality
4. Check Railway logs for any errors: `railway logs`

## Troubleshooting

### Database Connection Issues

- Verify PostgreSQL is running in Railway
- Check DATABASE_URL format
- Ensure migrations have run

### Redis Connection Issues

- Verify Redis service is running
- Check REDIS_URL format
- Test with: `redis-cli -u $REDIS_URL ping`

### CORS Errors

- Verify ALLOWED_ORIGINS includes your Vercel frontend URL
- Check for trailing slashes in URLs

### View Logs

```bash
railway logs -s backend
```

## Deployment Workflow

Each push to the `stage` branch will:

1. Trigger Railway build and deployment
2. Run your backend API
3. Vercel frontend auto-redeploys and uses new backend URL
4. Changes live within 2-5 minutes

## Commands for Local Testing

```bash
# Test backend locally
cd backend
python -m uvicorn main:app --reload

# Test with production database
REDIS_URL=redis://... DATABASE_URL=postgresql://... python -m uvicorn main:app

# Run migrations
alembic upgrade head
```

## Cost Breakdown

- Railway: $5/month credit (free tier) - includes backend, PostgreSQL, Redis
- Vercel: Free tier for frontend
- Total: **Free** (within free tier limits)

## Additional Resources

- [Railway Documentation](https://docs.railway.app)
- [FastAPI Production Deployment](https://fastapi.tiangolo.com/deployment/concepts/)
- [Railway GitHub Integration](https://docs.railway.app/guides/github-integration)
