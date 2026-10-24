# SpendPilot frontend

Consumer shopping UI for SpendPilot. This app is the `frontend` folder.

The shopping request page (`/shopping`) accepts a natural-language request, a total budget, and preferences. Submit keeps that request on the page and, after a short delay, shows sample products. It does not search live listings, build a cart, or check out.

## Install

```bash
npm install
```

## Run

```bash
cp .env.example .env.local
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The home page links to [http://localhost:3000/shopping](http://localhost:3000/shopping).

`NEXT_PUBLIC_API_URL` is reserved for the SpendPilot API (default `http://localhost:8000`). This page does not call it.

## Lint

```bash
npm run lint
```
